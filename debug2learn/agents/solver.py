from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from debug2learn.agents.base import BaseAgent, is_groq_quota_error
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    ChangeSet,
    DebuggingPlan,
    DebuggingStep,
    LearningResource,
    ProjectContext,
    RequestContext,
    ValidationState,
)

logger = logging.getLogger(__name__)


SOLVER_SYSTEM_PROMPT = """You are the Solver agent in Debug2Learn.

Your role is to diagnose the root cause of bugs in the actual source code
and create an educational debugging plan.

CRITICAL RULES:

1. DISTINGUISH FAILURE LOCATION FROM ROOT CAUSE

- Failure Location:
  The test case, assertion, traceback, or runtime location where the
  problem becomes visible.

- Root Cause Location:
  The actual source-code implementation responsible for the problem.

Do not blame the test merely because the test detects the failure.

2. REASON ABOUT THE ACTUAL CODE

- Inspect the provided source code.
- Do not simply repeat the developer's bug report.
- Compare expected behavior with actual implementation.
- Identify the exact discrepancy supported by code evidence.
- Use the traceback, tests, imports, functions, conditions, data flow,
  and implementation details when relevant.

3. NEVER PROVIDE THE DIRECT CODE FIX

Teach the developer how to discover the fix themselves.

4. CREATE 2-3 PEDAGOGICAL STEPS

Each step should help the developer inspect, trace, compare, or reason
about the problem.

5. BE EVIDENCE-DRIVEN

Confidence must reflect the amount and quality of available evidence.

6. DO NOT ASSUME A SPECIFIC BUG TYPE

The bug may involve imports, control flow, data structures, APIs,
types, state, algorithms, configuration, I/O, or another concept.

Respond ONLY with valid JSON:

{
    "failure_location": "test_file.py::test_name",
    "root_cause_location": "source_file.py -> function()",
    "relevant_logic": "Specific explanation of the problematic logic",
    "hypothesis": "Explanation of the discrepancy between expected and actual behavior",
    "confidence": 0.95,
    "evidence": [
        "Evidence 1",
        "Evidence 2"
    ],
    "concept": "Relevant programming concept",
    "steps": [
        {
            "step_number": 1,
            "title": "Title",
            "description": "What the developer should inspect",
            "target_file": "source_file.py",
            "target_symbol": "function_name",
            "concept": "Relevant concept",
            "expected_observation": "What the developer should discover"
        }
    ]
}
"""


class SolverAgent(BaseAgent):
    """
    🧩 Solver — Creates progressive debugging plans and evaluates
    whether developer changes actually address the diagnosed root cause.
    """

    def __init__(self, config: AppConfig):
        super().__init__(
            config,
            system_prompt=SOLVER_SYSTEM_PROMPT,
        )

    # ------------------------------------------------------------------
    # Initial diagnosis
    # ------------------------------------------------------------------

    def create_plan(
        self,
        project_context: ProjectContext,
        request_context: RequestContext,
        relevant_code: dict[str, str],
    ) -> DebuggingPlan:
        """Create an educational debugging plan from the actual code."""

        source_files: dict[str, str] = {}
        test_files: dict[str, str] = {}

        for path, code in relevant_code.items():
            norm_path = path.replace("\\", "/")
            file_context = project_context.files.get(norm_path)

            is_test = (
                bool(file_context and file_context.is_test_file)
                or Path(norm_path).name.startswith("test_")
                or norm_path.endswith("_test.py")
                or "tests/" in norm_path
            )

            if is_test:
                test_files[norm_path] = code
            else:
                source_files[norm_path] = code

        target_fn = request_context.target_function
        root_cause_file = ""
        root_cause_symbol = target_fn or ""
        failure_location = request_context.failure_location

        # --------------------------------------------------------------
        # Locate the target function from actual source code.
        # --------------------------------------------------------------

        if target_fn:
            function_pattern = re.compile(
                rf"^\s*def\s+{re.escape(target_fn)}\s*\(",
                re.MULTILINE,
            )

            for source_path, source_code in source_files.items():
                if function_pattern.search(source_code):
                    root_cause_file = source_path
                    break

        if not root_cause_file and source_files:
            root_cause_file = next(iter(source_files))

        # --------------------------------------------------------------
        # Detect missing imports from actual test/source relationships.
        # --------------------------------------------------------------

        missing_import = self._missing_import_name(
            request_context.raw_input
        )

        if not missing_import:
            missing_import = self._find_missing_import(
                source_files,
                test_files,
            )

        if missing_import:
            return self._create_missing_import_plan(
                missing_import=missing_import,
                root_cause_file=root_cause_file,
                failure_loc=failure_location,
                request_context=request_context,
                relevant_code=relevant_code,
            )

        # --------------------------------------------------------------
        # Infer failure location when possible.
        # --------------------------------------------------------------

        if not failure_location and test_files:
            test_file = next(iter(test_files))
            test_code = test_files[test_file]

            if target_fn:
                test_name_pattern = re.compile(
                    rf"\btest_{re.escape(target_fn)}\b"
                )

                if test_name_pattern.search(test_code):
                    failure_location = (
                        f"{test_file}::test_{target_fn}"
                    )
                else:
                    failure_location = f"{test_file}::(test)"
            else:
                failure_location = f"{test_file}::(test)"

        root_cause_location = (
            f"{root_cause_file} -> {root_cause_symbol}()"
            if root_cause_symbol
            else root_cause_file
        )

        code_section = self._build_code_section(relevant_code)

        prompt = f"""
Analyze this debugging issue using the ACTUAL CODE.

## Bug Description

Symptom:
{request_context.symptom or "Not specified"}

Target Function:
{target_fn or "Unknown"}

Expected Value:
{request_context.expected_value or "Not specified"}

Actual Value:
{request_context.actual_value or "Not specified"}

Known Failure Location:
{failure_location or "Unknown"}

Raw Developer Input:
{request_context.raw_input or "Not specified"}

## Project Source & Test Code

{code_section}

## Analysis Goal

1. Identify the exact root cause in the implementation.

2. Distinguish the failure location from the root cause location.

3. Explain the relevant implementation logic and why it conflicts
   with the expected behavior.

4. Construct a 2-3 step pedagogical debugging plan.

5. Do not provide the direct code fix.

6. Base every conclusion on evidence visible in the provided code.
"""

        if self._model and self.config.groq.api_key:
            try:
                response = self._send_sync(prompt)
                data = self._parse_json_response(response)

                steps = self._parse_steps(
                    data.get("steps", []),
                    root_cause_file,
                    root_cause_symbol,
                )

                if not steps:
                    steps = self._construct_pedagogical_steps(
                        root_cause_file=root_cause_file,
                        target_fn=target_fn,
                        failure_loc=failure_location,
                        request_context=request_context,
                        relevant_code=relevant_code,
                    )

                confidence = self._safe_confidence(
                    data.get("confidence", 0.9)
                )

                return DebuggingPlan(
                    hypothesis=(
                        data.get("hypothesis")
                        or self._analyze_code_logic(
                            root_cause_file,
                            target_fn,
                            request_context,
                            relevant_code,
                        )
                    ),
                    confidence=confidence,
                    evidence=self._normalize_evidence(
                        data.get("evidence")
                    ),
                    bug_location=(
                        data.get("root_cause_location")
                        or root_cause_location
                    ),
                    failure_location=(
                        data.get("failure_location")
                        or failure_location
                    ),
                    root_cause_location=(
                        data.get("root_cause_location")
                        or root_cause_location
                    ),
                    relevant_logic=(
                        data.get("relevant_logic")
                        or self._summarize_logic_issue(
                            root_cause_file,
                            target_fn,
                            request_context,
                            relevant_code,
                        )
                    ),
                    concept=(
                        data.get("concept")
                        or self._infer_concept(
                            request_context,
                            root_cause_file,
                            relevant_code,
                        )
                    ),
                    steps=steps,
                    relevant_code_snippets=relevant_code,
                )

            except Exception as exc:
                logger.error(
                    "Solver LLM plan generation failed: %s",
                    exc,
                )

                if is_groq_quota_error(exc):
                    logger.warning(
                        "Groq quota reached during plan generation."
                    )

        # --------------------------------------------------------------
        # Deterministic fallback
        # --------------------------------------------------------------

        hypothesis = self._analyze_code_logic(
            root_cause_file,
            target_fn,
            request_context,
            relevant_code,
        )

        relevant_logic = self._summarize_logic_issue(
            root_cause_file,
            target_fn,
            request_context,
            relevant_code,
        )

        concept = self._infer_concept(
            request_context,
            root_cause_file,
            relevant_code,
        )

        steps = self._construct_pedagogical_steps(
            root_cause_file=root_cause_file,
            target_fn=target_fn,
            failure_loc=failure_location,
            request_context=request_context,
            relevant_code=relevant_code,
        )

        return DebuggingPlan(
            hypothesis=hypothesis,
            confidence=(
                0.95
                if target_fn and root_cause_file
                else 0.80
            ),
            evidence=[
                (
                    f"Failure detected by: {failure_location}"
                    if failure_location
                    else "Failure was reported by the developer."
                ),
                (
                    f"Implementation analyzed in: "
                    f"{root_cause_location or 'source files'}"
                ),
                relevant_logic,
            ],
            bug_location=root_cause_location,
            failure_location=failure_location,
            root_cause_location=root_cause_location,
            relevant_logic=relevant_logic,
            concept=concept,
            steps=steps,
            relevant_code_snippets=relevant_code,
        )

    # ------------------------------------------------------------------
    # Import analysis
    # ------------------------------------------------------------------

    def _missing_import_name(self, text: str) -> str:
        """Extract a missing symbol from an ImportError message."""

        if not text:
            return ""

        patterns = [
            r"""cannot import name ['"]([a-zA-Z_]\w*)['"]""",
            r"""ImportError:.*?['"]([a-zA-Z_]\w*)['"]""",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                return match.group(1)

        return ""

    def _find_missing_import(
        self,
        source_files: dict[str, str],
        test_files: dict[str, str],
    ) -> str:
        """
        Find a symbol imported by tests but not defined in source code.

        This is based on the actual project code, not a hardcoded symbol.
        """

        defined_symbols: set[str] = set()

        for code in source_files.values():
            defined_symbols.update(
                re.findall(
                    r"^\s*def\s+([a-zA-Z_]\w*)\s*\(",
                    code,
                    re.MULTILINE,
                )
            )

            defined_symbols.update(
                re.findall(
                    r"^\s*class\s+([a-zA-Z_]\w*)\s*[\(:]",
                    code,
                    re.MULTILINE,
                )
            )

        for code in test_files.values():
            imports = re.findall(
                r"from\s+[\w.]+\s+import\s+([^\n#]+)",
                code,
            )

            for imported_names in imports:
                for name in imported_names.split(","):
                    candidate = (
                        name.strip()
                        .split(" as ", 1)[0]
                        .strip()
                    )

                    if (
                        re.fullmatch(
                            r"[a-zA-Z_]\w*",
                            candidate,
                        )
                        and candidate not in defined_symbols
                    ):
                        return candidate

        return ""

    def _create_missing_import_plan(
        self,
        missing_import: str,
        root_cause_file: str,
        failure_loc: str,
        request_context: RequestContext,
        relevant_code: dict[str, str],
    ) -> DebuggingPlan:
        """Create a diagnosis for a genuinely missing imported symbol."""

        source_has_symbol = any(
            re.search(
                rf"^\s*def\s+{re.escape(missing_import)}\s*\(",
                code,
                re.MULTILINE,
            )
            for code in relevant_code.values()
        )

        hypothesis = (
            f"The test module imports `{missing_import}`, but the "
            "expected symbol is not available in the source module. "
            "This prevents the test module from being collected."
        )

        failure_file = (
            failure_loc.split("::", 1)[0]
            if failure_loc
            else "test file"
        )

        steps = [
            DebuggingStep(
                step_number=1,
                title="Trace the failed import",
                description=(
                    "Compare the symbols imported by the test with "
                    "the public symbols actually defined by the source module."
                ),
                target_file=failure_file,
                target_symbol=missing_import,
                concept="Python imports and module interfaces",
                expected_observation=(
                    f"The test expects `{missing_import}`, but the "
                    "source module does not currently expose that symbol."
                ),
            ),
            DebuggingStep(
                step_number=2,
                title="Inspect the missing API",
                description=(
                    "Determine what behavior the missing symbol is "
                    "supposed to provide by reading the tests and surrounding code."
                ),
                target_file=root_cause_file,
                target_symbol=missing_import,
                concept="Module interfaces and API contracts",
                expected_observation=(
                    "The expected interface and behavior of the missing "
                    "symbol become clear from its callers and tests."
                ),
            ),
        ]

        root_location = (
            f"{root_cause_file} -> {missing_import}()"
            if root_cause_file
            else missing_import
        )

        return DebuggingPlan(
            hypothesis=hypothesis,
            confidence=(
                0.98
                if not source_has_symbol
                else 0.80
            ),
            evidence=[
                f"Import analysis identified missing symbol: {missing_import}",
                (
                    f"Source inspected in: "
                    f"{root_cause_file or 'source files'}"
                ),
            ],
            bug_location=root_location,
            failure_location=failure_loc,
            root_cause_location=root_location,
            relevant_logic=(
                f"`{missing_import}` is expected by the test interface "
                "but is not currently defined or exposed by the source."
            ),
            concept="Python imports and module interfaces",
            steps=steps,
            relevant_code_snippets=relevant_code,
        )

    # ------------------------------------------------------------------
    # Generic deterministic reasoning
    # ------------------------------------------------------------------

    def _analyze_code_logic(
        self,
        root_cause_file: str,
        target_fn: str,
        req: RequestContext,
        code_snippets: dict[str, str],
    ) -> str:
        """
        Produce a generic evidence-based explanation when the LLM
        is unavailable.

        This intentionally avoids assumptions about a particular bug.
        """

        code = code_snippets.get(root_cause_file, "")

        if not code:
            return (
                f"Insufficient implementation evidence in "
                f"{root_cause_file or 'the available source files'}."
            )

        if target_fn:
            fn_body = self._extract_function_body(
                code,
                target_fn,
            )

            if fn_body:
                expected = req.expected_value or "the expected behavior"
                actual = req.actual_value or "the observed behavior"

                return (
                    f"The implementation of {target_fn}() in "
                    f"{root_cause_file} should produce {expected}, "
                    f"but the reported behavior is {actual}. "
                    "Inspect the function's input handling, control flow, "
                    "state changes, and return path to identify where the "
                    "implementation diverges from the requirement."
                )

        return (
            f"The available implementation in "
            f"{root_cause_file or 'the source code'} does not yet provide "
            "enough evidence to identify a more specific discrepancy. "
            "Trace the reported input through the relevant code path "
            "and compare each transformation with the expected behavior."
        )

    def _summarize_logic_issue(
        self,
        root_cause_file: str,
        target_fn: str,
        req: RequestContext,
        code_snippets: dict[str, str],
    ) -> str:
        """Create a generic summary of the diagnosed implementation area."""

        code = code_snippets.get(root_cause_file, "")

        if target_fn and code:
            fn_body = self._extract_function_body(
                code,
                target_fn,
            )

            if fn_body:
                return (
                    f"The relevant implementation is inside "
                    f"{root_cause_file} -> {target_fn}(). "
                    "Its input-to-output behavior should be compared "
                    "directly with the requirement and observed failure."
                )

        return (
            f"The diagnosed implementation area is "
            f"{root_cause_file or 'the available source code'}. "
            "The relevant logic should be traced against the reported behavior."
        )

    def _infer_concept(
        self,
        req: RequestContext,
        root_cause_file: str,
        code_snippets: dict[str, str],
    ) -> str:
        """
        Infer a broad programming concept without tying the Solver
        to a particular demo bug.
        """

        code = code_snippets.get(root_cause_file, "")

        if "import " in code or "from " in code:
            return "Python Modules and Imports"

        if re.search(r"\bif\b|\belif\b|\belse\b", code):
            return "Control Flow and Conditional Logic"

        if re.search(r"\bfor\b|\bwhile\b", code):
            return "Iteration and Data Processing"

        if "return " in code:
            return "Function Contracts and Return Values"

        if "class " in code:
            return "Object-Oriented Programming"

        if req.domain:
            return f"{req.domain} Programming Concepts"

        return "Program Logic and Debugging"

    # ------------------------------------------------------------------
    # Pedagogical steps
    # ------------------------------------------------------------------

    def _construct_pedagogical_steps(
        self,
        root_cause_file: str,
        target_fn: str,
        failure_loc: str,
        req: RequestContext,
        code_snippets: dict[str, str],
    ) -> list[DebuggingStep]:
        """Construct generic debugging steps when the LLM is unavailable."""

        target_file = root_cause_file or "source code"
        target_symbol = target_fn or "target logic"

        expected = req.expected_value or "the expected result"
        actual = req.actual_value or "the observed result"

        return [
            DebuggingStep(
                step_number=1,
                title="Trace the failing behavior",
                description=(
                    f"Start from {failure_loc or 'the reported failure'} "
                    f"and trace the input values toward {target_symbol}()."
                ),
                target_file=target_file,
                target_symbol=target_symbol,
                concept="Debugging and Data Flow",
                expected_observation=(
                    f"You should identify where the observed behavior "
                    f"({actual}) begins to differ from the expected behavior "
                    f"({expected})."
                ),
            ),
            DebuggingStep(
                step_number=2,
                title="Inspect the relevant logic",
                description=(
                    f"Examine the implementation of {target_symbol}() "
                    "and trace its conditions, transformations, and return path."
                ),
                target_file=target_file,
                target_symbol=target_symbol,
                concept="Program Logic and Control Flow",
                expected_observation=(
                    "You should find the specific operation or condition "
                    "responsible for the behavioral discrepancy."
                ),
            ),
            DebuggingStep(
                step_number=3,
                title="Compare behavior with the contract",
                description=(
                    "Compare what the implementation actually does with "
                    "what the test or requirement expects."
                ),
                target_file=target_file,
                target_symbol=target_symbol,
                concept="Contracts and Expected Behavior",
                expected_observation=(
                    "The mismatch between the implementation and the "
                    "expected contract should become explicit."
                ),
            ),
        ]

    # ------------------------------------------------------------------
    # Change evaluation
    # ------------------------------------------------------------------

    def evaluate_changes(
        self,
        plan: DebuggingPlan,
        changes: ChangeSet,
        request_context: RequestContext,
        changed_code: dict[str, str],
    ) -> dict[str, Any]:
        """
        Determine whether the developer's current changes actually
        address the diagnosed root cause.

        IMPORTANT:
        - Changing a relevant file is not enough.
        - Adding a similarly named function is not enough.
        - The implementation itself must address the diagnosis.
        - No bug-specific patterns are hardcoded.
        """

        current_step = (
            plan.steps[plan.current_step]
            if (
                plan.steps
                and 0 <= plan.current_step < len(plan.steps)
            )
            else None
        )

        test_cmd = (
            getattr(plan, "test_command", None)
            or "pytest"
        )

        changed_files = (
            ", ".join(changes.files_changed)
            if changes.files_changed
            else "None"
        )

        changed_symbols = [
            change.symbol
            for change in changes.changes
            if change.symbol
        ]

        root_cause = (
            plan.root_cause_location
            or plan.bug_location
            or "Unknown"
        )

        relevant_logic = (
            plan.relevant_logic
            or "No detailed logic description available."
        )

        hypothesis = (
            plan.hypothesis
            or "No hypothesis available."
        )

        concept = (
            plan.concept
            or "Unknown"
        )

        code_section = self._build_code_section(
            changed_code,
            max_chars_per_file=3500,
        )

        diff_section = changes.git_diff_raw or ""

        if len(diff_section) > 6000:
            diff_section = diff_section[:6000]

        step_context = ""

        if current_step:
            step_context = f"""
## CURRENT DEBUGGING STEP

Title:
{current_step.title}

Description:
{current_step.description}

Target File:
{current_step.target_file}

Target Symbol:
{current_step.target_symbol}

Expected Observation:
{current_step.expected_observation}
"""

        prompt = f"""
You are the Solver validating a developer's code change.

Your task is to determine whether the CURRENT CODE actually addresses
the ROOT CAUSE previously diagnosed.

Do not judge the change merely because:

- a relevant file changed
- a function was added
- a symbol has a similar name
- the code looks plausible
- the developer claims it is fixed
- the change is syntactically valid

You MUST compare the current implementation with the original diagnosis.

## ORIGINAL DEBUGGING DIAGNOSIS

Root Cause Location:
{root_cause}

Hypothesis:
{hypothesis}

Relevant Logic:
{relevant_logic}

Concept:
{concept}

{step_context}

## DEVELOPER CHANGES

Changed Files:
{changed_files}

Changed Symbols:
{", ".join(changed_symbols) or "None"}

## GIT DIFF

{diff_section or "No diff available."}

## CURRENT CODE

{code_section}

## EVALUATION

Classify the developer's current state into exactly one of:

1. WRONG / UNRELATED

The change does not address the diagnosed root cause.

Examples:
- unrelated code was changed
- comments only were changed
- a different API was introduced
- the change does not affect the diagnosed failure path
- the implementation still contradicts the diagnosis

2. RELEVANT BUT NOT FIXED

The developer is working in the correct area, but the current
implementation does not yet resolve the diagnosed problem.

3. FIXED / READY FOR TEST

The current implementation directly addresses the diagnosed root cause
and there is sufficient code evidence to justify running the tests.

IMPORTANT RULES:

- Do not invent a new root cause.
- Do not rely on keywords as proof of correctness.
- Do not require a particular function name unless the diagnosis itself
  identifies that interface.
- Do not require a particular operator.
- Do not assume the original bug type.
- Do not provide corrected code.
- Do not approve merely because the change is relevant.
- Only set ready_for_test=true when the current implementation itself
  addresses the diagnosed root cause.
- If evidence is insufficient, do NOT approve the change.
- If the implementation uses a different name or API than the diagnosed
  contract, verify whether it actually satisfies the same interface
  before considering it fixed.

Return ONLY valid JSON:

{{
    "is_relevant": false,
    "on_right_track": false,
    "ready_for_test": false,
    "advance_step": false,
    "progress": "Short assessment.",
    "feedback": "Clear Socratic feedback for the developer."
}}

Field meanings:

is_relevant:
Whether the change concerns the diagnosed problem.

on_right_track:
Whether the change is moving toward resolving the diagnosed root cause.

ready_for_test:
True ONLY when the implementation itself addresses the diagnosed root cause.

advance_step:
Normally false until tests confirm the change.

feedback:
Give concise educational feedback.
Do not reveal a direct code fix when the change is wrong or incomplete.
"""

        if self._model and self.config.groq.api_key:
            try:
                response = self._send_sync(prompt)
                data = self._parse_json_response(response)

                is_relevant = bool(
                    data.get("is_relevant", False)
                )

                on_right_track = bool(
                    data.get("on_right_track", False)
                )

                ready_for_test = bool(
                    data.get("ready_for_test", False)
                )

                advance_step = bool(
                    data.get("advance_step", False)
                )

                # ------------------------------------------------------
                # Safety guard:
                # A change cannot be ready for testing unless it is
                # actually relevant and on the right track.
                # ------------------------------------------------------

                if ready_for_test and not (
                    is_relevant and on_right_track
                ):
                    ready_for_test = False

                if ready_for_test:
                    state = (
                        ValidationState.AWAITING_TEST_VALIDATION
                    )
                elif is_relevant:
                    state = ValidationState.CHANGE_RELEVANT
                else:
                    state = ValidationState.CHANGE_DETECTED

                return {
                    "state": state,
                    "is_relevant": is_relevant,
                    "on_right_track": on_right_track,
                    "ready_for_test": ready_for_test,
                    "test_command": test_cmd,
                    "progress": data.get(
                        "progress",
                        "Changes detected and analyzed.",
                    ),
                    "advance_step": advance_step,
                    "feedback": data.get(
                        "feedback",
                        "The Solver analyzed your changes.",
                    ),
                }

            except Exception as exc:
                logger.error(
                    "Solver change evaluation failed: %s",
                    exc,
                )

                if is_groq_quota_error(exc):
                    logger.warning(
                        "Groq quota reached during change evaluation."
                    )

        # --------------------------------------------------------------
        # Safe fallback
        #
        # NEVER claim that an unverified change is fixed when the LLM
        # is unavailable.
        # --------------------------------------------------------------

        return {
            "state": ValidationState.CHANGE_RELEVANT,
            "is_relevant": True,
            "on_right_track": True,
            "ready_for_test": False,
            "test_command": test_cmd,
            "progress": (
                f"Changes detected in "
                f"{len(changes.files_changed)} file(s), "
                "but the fix could not be automatically confirmed."
            ),
            "advance_step": False,
            "feedback": (
                "🎯 Your changes are in the relevant area, but the "
                "Solver cannot confirm that the diagnosed root cause "
                "has been fixed yet. Continue investigating or ask "
                "Owl for a hint."
            ),
        }

    # ------------------------------------------------------------------
    # Test output evaluation
    # ------------------------------------------------------------------

    def evaluate_test_output(
        self,
        test_output: str,
        plan: DebuggingPlan,
        request_context: RequestContext,
    ) -> dict[str, Any]:
        """
        Evaluate test runner output supplied by the developer.

        The server only parses pasted output.
        It does not execute arbitrary developer code.
        """

        from debug2learn.agents.decoder import DecoderAgent

        decoder = DecoderAgent(self.config)

        test_result = decoder.parse_test_output(
            test_output
        )

        if test_result.all_passed:
            return {
                "state": ValidationState.TEST_PASSED,
                "passed": True,
                "test_result": test_result,
                "advance_step": True,
                "feedback": (
                    "🎉 Excellent! Your tests passed.\n\n"
                    "You identified the root cause, fixed the code "
                    "yourself, and proved that your solution works.\n\n"
                    "+100 XP\n"
                    "🏆 Quest Complete!"
                ),
            }

        fail_desc = (
            f"{test_result.failed} failed, "
            f"{test_result.passed} passed"
            if test_result.passed > 0
            else f"{test_result.failed} failed"
        )

        if test_result.errors > 0:
            fail_desc += (
                f", {test_result.errors} error(s)"
            )

        return {
            "state": ValidationState.TEST_FAILED,
            "passed": False,
            "test_result": test_result,
            "advance_step": False,
            "feedback": (
                f"❌ TEST VALIDATION FAILED ({fail_desc}).\n\n"
                "The bug is not confirmed fixed yet. "
                "The test suite is still reporting failures.\n"
                "Inspect the failure output, adjust your implementation, "
                "and run check again."
            ),
        }

    # ------------------------------------------------------------------
    # Librarian delegation
    # ------------------------------------------------------------------

    def find_resources(
        self,
        concept: str,
        domain: str = "python",
    ) -> list[LearningResource]:
        """Delegate resource discovery to the Librarian agent."""

        from debug2learn.agents.librarian import LibrarianAgent

        librarian = LibrarianAgent(self.config)

        request = RequestContext(
            raw_input=concept,
            symptom=concept,
            domain=domain,
        )

        return librarian.find_resources(request)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_code_section(
        self,
        code_mapping: dict[str, str],
        max_chars_per_file: int = 2500,
    ) -> str:
        """Format code snippets for an LLM prompt."""

        if not code_mapping:
            return "No code available."

        sections: list[str] = []

        for path, code in code_mapping.items():
            truncated = code[:max_chars_per_file]

            sections.append(
                f"\n### {path}\n"
                f"```python\n"
                f"{truncated}\n"
                f"```\n"
            )

        return "\n".join(sections)

    def _extract_function_body(
        self,
        code: str,
        function_name: str,
    ) -> str:
        """Extract a Python function body approximately using regex."""

        if not code or not function_name:
            return ""

        pattern = re.compile(
            rf"^\s*def\s+{re.escape(function_name)}\s*\([^)]*\)"
            rf"[\s\S]*?(?=^\s*def\s+|\Z)",
            re.MULTILINE,
        )

        match = pattern.search(code)

        return match.group(0) if match else ""

    def _parse_steps(
        self,
        raw_steps: Any,
        default_file: str,
        default_symbol: str,
    ) -> list[DebuggingStep]:
        """Convert LLM step dictionaries into DebuggingStep models."""

        if not isinstance(raw_steps, list):
            return []

        steps: list[DebuggingStep] = []

        for index, step in enumerate(raw_steps, start=1):
            if not isinstance(step, dict):
                continue

            try:
                step_number = int(
                    step.get(
                        "step_number",
                        index,
                    )
                )
            except (TypeError, ValueError):
                step_number = index

            steps.append(
                DebuggingStep(
                    step_number=step_number,
                    title=(
                        str(
                            step.get(
                                "title",
                                f"Step {index}",
                            )
                        )
                    ),
                    description=str(
                        step.get(
                            "description",
                            "",
                        )
                    ),
                    target_file=str(
                        step.get(
                            "target_file",
                            default_file,
                        )
                    ),
                    target_symbol=str(
                        step.get(
                            "target_symbol",
                            default_symbol,
                        )
                    ),
                    concept=str(
                        step.get(
                            "concept",
                            "",
                        )
                    ),
                    expected_observation=str(
                        step.get(
                            "expected_observation",
                            "",
                        )
                    ),
                )
            )

        return steps[:3]

    def _normalize_evidence(
        self,
        evidence: Any,
    ) -> list[str]:
        """Normalize LLM evidence into a list of strings."""

        if isinstance(evidence, list):
            return [
                str(item)
                for item in evidence
                if item is not None
            ]

        if isinstance(evidence, str) and evidence.strip():
            return [evidence.strip()]

        return [
            "The diagnosis was generated from the available code evidence."
        ]

    def _safe_confidence(
        self,
        value: Any,
    ) -> float:
        """Normalize confidence into the expected 0-1 range."""

        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.8

        return max(
            0.0,
            min(1.0, confidence),
        )