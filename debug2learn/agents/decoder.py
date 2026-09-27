from __future__ import annotations

import logging
import re
from typing import Any

from debug2learn.agents.base import BaseAgent
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    ProjectContext,
    RequestContext,
    SingleTestResult,
    TestRunResult,
    TestStatus,
)

logger = logging.getLogger(__name__)

DECODER_PROMPT = """You are the Decoder agent in Debug2Learn.
Your mission is to decompose and analyze a developer's bug report or error message.

CRITICAL INSTRUCTIONS:
1. Preserve all exact code literals, special characters, and formatting (e.g. '[x]', '<', '!=', '->', '""') verbatim.
2. NEVER sanitize, escape, or remove meaningful code syntax or characters like '[x]'.
3. Extract specific signals: target function, expected value, actual value, failure location, and core concept domain.

Respond ONLY with valid JSON with keys:
- "intent": brief phrase summarizing problem
- "symptom": exact symptom description preserving all literal tokens like '[x]'
- "target_function": function name being tested or failing (e.g. "count_pending")
- "expected_value": expected output or behavior (e.g. "2")
- "actual_value": observed output or behavior (e.g. "1")
- "failure_location": test file or function where failure is observed (e.g. "test_todo.py::test_count_pending")
- "root_cause_file": source implementation file suspected (e.g. "todo.py")
- "expected_behavior": what should happen
- "observed_behavior": what actually happens
- "domain": technical domain (e.g. "filtering / boolean conditions", "list comprehension", "type safety")
- "possible_components": list of component names
- "relevant_files": list of file names
- "keywords": list of keywords
- "error_messages": list of error messages
- "constraints": list of constraints
"""


class DecoderAgent(BaseAgent):
    """
    🔐 Decoder — Decodes bug descriptions and test traces into structured context.
    """

    def __init__(self, config: AppConfig):
        super().__init__(config, system_prompt=DECODER_PROMPT)

    def decode(
        self,
        raw_input: str,
        project_context: ProjectContext | None = None,
    ) -> RequestContext:
        """
        Decode the bug report into a structured RequestContext without sanitizing literals like '[x]'.
        """
        # Deterministic extraction
        extracted_files = self._extract_files(raw_input)
        extracted_errors = self._extract_errors(raw_input)
        extracted_target_func = self._extract_target_function(raw_input)
        missing_import = self._extract_missing_import(raw_input)
        if missing_import and not extracted_target_func:
            extracted_target_func = missing_import
        expected_val, actual_val = self._extract_expected_and_actual(raw_input)
        failure_loc = self._extract_failure_location(raw_input)

        # Match files against project context
        matched_files = list(extracted_files)
        if project_context:
            available_files = list(project_context.files.keys())
            for ef in extracted_files:
                for af in available_files:
                    if ef in af or af.endswith(ef):
                        if af not in matched_files:
                            matched_files.append(af)

            # If target function found, look up its file in project context
            if extracted_target_func and extracted_target_func in project_context.function_to_file:
                fn_file = project_context.function_to_file[extracted_target_func]
                if fn_file not in matched_files:
                    matched_files.append(fn_file)

        # Determine domain deterministically
        domain = self._detect_domain(raw_input)

        # If LLM available, enrich semantic understanding
        if self._model and self.config.gemini.api_key:
            try:
                prompt_parts = {
                    "developer_bug_report": raw_input,
                }
                if project_context:
                    prompt_parts["project_files"] = ", ".join(list(project_context.files.keys())[:25])
                    prompt_parts["test_files"] = ", ".join(project_context.test_files)
                    prompt_parts["source_files"] = ", ".join(project_context.source_files)
                if extracted_errors:
                    prompt_parts["detected_errors"] = "\n".join(extracted_errors)

                prompt = self._build_prompt(**prompt_parts)
                raw_response = self._send_sync(prompt)
                data = self._parse_json_response(raw_response)

                symptom = data.get("symptom") or (extracted_errors[0] if extracted_errors else raw_input)
                # Ensure literals in raw_input (like '[x]') are preserved in symptom
                if "[x]" in raw_input and "[x]" not in symptom:
                    symptom = raw_input

                return RequestContext(
                    raw_input=raw_input,
                    intent=data.get("intent", "fix_logic_bug"),
                    symptom=symptom,
                    target_function=data.get("target_function") or extracted_target_func,
                    expected_value=str(data.get("expected_value") or expected_val),
                    actual_value=str(data.get("actual_value") or actual_val),
                    failure_location=data.get("failure_location") or failure_loc,
                    root_cause_file=data.get("root_cause_file", ""),
                    expected_behavior=data.get("expected_behavior", f"Expected: {expected_val}" if expected_val else ""),
                    observed_behavior=data.get("observed_behavior", f"Actual: {actual_val}" if actual_val else raw_input),
                    domain=data.get("domain") or domain,
                    possible_components=data.get("possible_components", []),
                    relevant_files=list(dict.fromkeys(data.get("relevant_files", []) + matched_files)),
                    keywords=data.get("keywords", ["logic", "filter"]),
                    error_messages=list(dict.fromkeys(data.get("error_messages", []) + extracted_errors)),
                    constraints=data.get("constraints", []),
                )
            except Exception as e:
                logger.warning(f"AI decoding fallback to deterministic extraction: {e}")

        # Fallback deterministic extraction
        symptom = extracted_errors[0] if extracted_errors else raw_input

        # Infer expected and observed behaviors
        expected_behavior = f"Returns {expected_val}" if expected_val else "Correct behavior without error"
        observed_behavior = f"Returns {actual_val}" if actual_val else raw_input

        return RequestContext(
            raw_input=raw_input,
            intent=f"fix_{extracted_target_func}" if extracted_target_func else "debug_issue",
            symptom=symptom,
            target_function=extracted_target_func,
            expected_value=expected_val,
            actual_value=actual_val,
            failure_location=failure_loc,
            root_cause_file="",
            expected_behavior=expected_behavior,
            observed_behavior=observed_behavior,
            domain=domain,
            possible_components=[],
            relevant_files=matched_files,
            keywords=["logic", "filtering"] if "filter" in domain else ["bug"],
            error_messages=extracted_errors,
            constraints=[],
        )

    def _extract_files(self, text: str) -> list[str]:
        """Find mentioned python files in text or tracebacks."""
        py_file_pattern = r'[\w\-/\\.]+\.py\b'
        matches = re.findall(py_file_pattern, text)
        cleaned = []
        for m in matches:
            cleaned.append(m.replace("\\", "/").split("/")[-1])
        return list(dict.fromkeys(cleaned))

    def _extract_errors(self, text: str) -> list[str]:
        """Extract Python exceptions like TypeError: ..., ValueError: ..."""
        error_pattern = r'([A-Z]\w*(?:Error|Exception|Warning|Fault)):?\s*([^\n\r]*)'
        matches = re.findall(error_pattern, text)
        return [f"{exc}: {msg}".strip() for exc, msg in matches]

    def _extract_target_function(self, text: str) -> str:
        """Extract candidate target function name."""
        # Check pytest FAILED format e.g. FAILED test_todo.py::test_count_pending
        failed_match = re.search(r'FAILED\s+[\w/\\.]+\.py::(?:test_)?([a-zA-Z_]\w*)', text)
        if failed_match:
            return failed_match.group(1)

        # Check "count_pending returns 1" or "count_pending()"
        func_match = re.search(r'\b([a-zA-Z_]\w*)\s*(?:\(\)|\s+returns|\s+fails|\s+does\s+not)', text)
        if func_match:
            cand = func_match.group(1)
            if cand not in ("def", "return", "if", "for", "while", "class", "FAILED", "Expected", "Actual"):
                return cand
        return ""

    def _extract_missing_import(self, text: str) -> str:
        """Extract a symbol named by an import-collection failure."""
        match = re.search(r"cannot import name ['\"]([a-zA-Z_]\w*)['\"]", text, re.IGNORECASE)
        return match.group(1) if match else ""

    def _extract_expected_and_actual(self, text: str) -> tuple[str, str]:
        """Extract expected and actual values from text."""
        # e.g. "returns 1 instead of 2" -> actual=1, expected=2
        m1 = re.search(r'returns?\s+([^\s,]+)\s+instead\s+of\s+([^\s,.]+)', text, re.IGNORECASE)
        if m1:
            return m1.group(2).strip("'\""), m1.group(1).strip("'\"")

        # e.g. "Expected: 2\nActual: 1"
        exp_m = re.search(r'expected:?\s*([^\n\r,]+)', text, re.IGNORECASE)
        act_m = re.search(r'actual:?\s*([^\n\r,]+)', text, re.IGNORECASE)
        expected = exp_m.group(1).strip("'\"") if exp_m else ""
        actual = act_m.group(1).strip("'\"") if act_m else ""

        return expected, actual

    def _extract_failure_location(self, text: str) -> str:
        """Extract test failure location if pytest output present."""
        m = re.search(r'FAILED\s+([\w/\\.]+\.py::[a-zA-Z_]\w*)', text)
        if m:
            return m.group(1)
        return ""

    def _detect_domain(self, text: str) -> str:
        """Detect technical domain from bug report text."""
        lower = text.lower()
        if any(w in lower for w in ("[x]", "completed", "pending", "filter", "comprehension", "not marked")):
            return "filtering / boolean conditions"
        if any(w in lower for w in ("typeerror", "cannot concatenate", "unsupported operand")):
            return "type safety"
        if any(w in lower for w in ("keyerror", "indexerror", "out of range")):
            return "data structure access"
        if any(w in lower for w in ("async", "await", "coroutine", "event loop")):
            return "asynchronous execution"
        return "logic / condition validation"

    def parse_test_output(self, text: str) -> TestRunResult:
        """
        Parse test runner stdout/output (pytest or unittest) into structured TestRunResult.
        Does NOT execute code; operates purely on pasted output text.
        """
        text_clean = text.strip()
        passed = 0
        failed = 0
        errors = 0
        skipped = 0

        # Check for pytest summary numbers: e.g. "3 passed", "1 failed", "2 errors"
        passed_m = re.search(r'\b(\d+)\s+passed\b', text_clean, re.IGNORECASE)
        if passed_m:
            passed = int(passed_m.group(1))

        failed_m = re.search(r'\b(\d+)\s+failed\b', text_clean, re.IGNORECASE)
        if failed_m:
            failed = int(failed_m.group(1))

        errors_m = re.search(r'\b(\d+)\s+error(?:s)?\b', text_clean, re.IGNORECASE)
        if errors_m:
            errors = int(errors_m.group(1))

        skipped_m = re.search(r'\b(\d+)\s+skipped\b', text_clean, re.IGNORECASE)
        if skipped_m:
            skipped = int(skipped_m.group(1))

        # Check for unittest: "Ran X tests" ... "OK" or "FAILED (failures=Y)"
        ran_m = re.search(r'Ran\s+(\d+)\s+tests?', text_clean, re.IGNORECASE)
        if ran_m:
            total_ran = int(ran_m.group(1))
            if "OK" in text_clean and failed == 0 and errors == 0:
                passed = total_ran
            unit_fail_m = re.search(r'failures=(\d+)', text_clean)
            if unit_fail_m:
                failed = int(unit_fail_m.group(1))
            unit_err_m = re.search(r'errors=(\d+)', text_clean)
            if unit_err_m:
                errors = int(unit_err_m.group(1))

        # Check for FAILED test markers if failed count wasn't parsed
        failed_lines = re.findall(r'FAILED\s+([^\n\r]+)', text_clean)
        if failed_lines and failed == 0:
            failed = len(failed_lines)

        # Check for AssertionError or failures header
        if ("AssertionError" in text_clean or "=== FAILURES ===" in text_clean or "assert " in text_clean) and failed == 0:
            failed = 1

        # Check informal passed text if no numbers found
        if passed == 0 and failed == 0 and errors == 0:
            lower = text_clean.lower()
            if any(p in lower for p in ("all passed", "tests passed", "passed", "success", "ok")) and not any(f in lower for f in ("fail", "error")):
                passed = 1
            elif any(f in lower for f in ("fail", "error")):
                failed = 1

        total = passed + failed + errors + skipped
        exit_code = 0 if (failed == 0 and errors == 0 and passed > 0) else 1

        # Check duration: e.g. "in 0.01s" or "in 0.52s"
        duration_ms = 10.0
        dur_m = re.search(r'in\s+([\d\.]+)\s*s\b', text_clean, re.IGNORECASE)
        if dur_m:
            try:
                duration_ms = float(dur_m.group(1)) * 1000.0
            except ValueError:
                pass

        single_results = []
        for fl in failed_lines:
            single_results.append(SingleTestResult(
                name=fl.split("-")[0].strip(),
                status=TestStatus.FAILED,
                error_message=fl,
            ))

        return TestRunResult(
            total=total,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            duration_ms=duration_ms,
            test_results=single_results,
            stdout=text_clean,
            exit_code=exit_code,
        )

