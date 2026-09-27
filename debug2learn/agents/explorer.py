from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from debug2learn.agents.base import BaseAgent
from debug2learn.analyzers.ast_analyzer import ASTAnalyzer
from debug2learn.analyzers.file_scanner import FileScanner
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    FileContext,
    Language,
    ProjectContext,
)

logger = logging.getLogger(__name__)

EXPLORER_PROMPT = """You are the Explorer agent in Debug2Learn.
Your mission is to understand software projects quickly and accurately.
Given project metadata, file structures, and key functions, provide:
1. A concise project description (1-2 sentences)
2. The detected framework (e.g. FastAPI, Flask, Django, CLI, Pytest, or Vanilla Python)
3. Architecture summary (components and how data flows)
4. Key component relationships (especially how test suites map to the source code under test)

Respond ONLY with valid JSON with keys:
- "description": str
- "framework": str
- "architecture_summary": str
- "component_relationships": list[str]
"""


class ExplorerAgent(BaseAgent):
    """
    🧭 Explorer — Scans and builds project understanding.
    """

    def __init__(self, config: AppConfig):
        super().__init__(config, system_prompt=EXPLORER_PROMPT)
        self.ast_analyzer = ASTAnalyzer()
        self.file_scanner = FileScanner()

    def explore(
        self,
        project_path: Path,
        relevant_files_hint: list[str] | None = None,
        max_files: int = 50,
    ) -> ProjectContext:
        """
        Explore the project structure and build a ProjectContext.
        Focuses on relevant files and maps relationships between tests and implementations.
        """
        project_path = project_path.resolve()
        py_files = self.file_scanner.find_python_files(project_path)
        dep_files = self.file_scanner.find_dependency_files(project_path)

        # Prioritize relevant files if provided
        if relevant_files_hint:
            relevant_set = {Path(f).name for f in relevant_files_hint}
            prioritized = [f for f in py_files if f.name in relevant_set or str(f) in relevant_files_hint]
            others = [f for f in py_files if f not in prioritized]
            py_files = (prioritized + others)[:max_files]
        else:
            py_files = py_files[:max_files]

        file_contexts: dict[str, FileContext] = {}
        entry_points: list[str] = []
        test_files: list[str] = []
        source_files: list[str] = []
        function_to_file: dict[str, str] = {}
        total_funcs = 0
        total_classes = 0

        for fpath in py_files:
            try:
                rel = str(fpath.relative_to(project_path)).replace("\\", "/")
            except ValueError:
                rel = fpath.name

            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            analysis = self.ast_analyzer.analyze_code(content, str(fpath))
            
            f_context = FileContext(
                path=str(fpath),
                relative_path=rel,
                language=Language.PYTHON,
                size_bytes=len(content.encode("utf-8")),
                purpose="",
                functions=analysis["functions"],
                classes=analysis["classes"],
                imports=analysis["imports"],
                is_test_file=analysis["is_test_file"],
                is_entry_point=analysis["is_entry_point"],
            )

            file_contexts[rel] = f_context
            total_funcs += len(analysis["functions"])
            total_classes += len(analysis["classes"])

            if analysis["is_entry_point"]:
                entry_points.append(rel)
            if analysis["is_test_file"]:
                test_files.append(rel)
            else:
                source_files.append(rel)

            # Map function names to file
            for fn in analysis["functions"]:
                function_to_file[fn.name] = rel

        # Map tests to source files (e.g. test_todo.py -> todo.py)
        test_to_source_mapping: dict[str, str] = {}
        for tf in test_files:
            fc = file_contexts.get(tf)
            if not fc:
                continue

            # Method 1: Check imports in test file
            matched_source = None
            for imp in fc.imports:
                mod_name = imp.module.split(".")[-1]
                for sf in source_files:
                    sf_stem = Path(sf).stem
                    if mod_name == sf_stem:
                        matched_source = sf
                        break
                if matched_source:
                    break

            # Method 2: Check naming convention (e.g. test_todo.py -> todo.py)
            if not matched_source:
                tf_stem = Path(tf).stem
                if tf_stem.startswith("test_"):
                    cand = tf_stem[5:]
                    for sf in source_files:
                        if Path(sf).stem == cand:
                            matched_source = sf
                            break

            if matched_source:
                test_to_source_mapping[tf] = matched_source

        # Detect dependencies
        dependencies: list[str] = []
        for dpath in dep_files:
            try:
                lines = dpath.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        dependencies.append(line.split("==")[0].split(">=")[0].split("<=")[0].strip())
            except Exception:
                pass

        # Build context
        context = ProjectContext(
            project_path=str(project_path),
            project_name=project_path.name,
            language=Language.PYTHON,
            files=file_contexts,
            entry_points=entry_points,
            test_files=test_files,
            source_files=source_files,
            test_to_source_mapping=test_to_source_mapping,
            function_to_file=function_to_file,
            dependencies=list(set(dependencies)),
            total_files=len(file_contexts),
            total_functions=total_funcs,
            total_classes=total_classes,
        )

        # Enhance with AI overview if model available
        if self._model and self.config.gemini.api_key:
            try:
                summary_prompt = self._build_prompt(
                    project_name=project_path.name,
                    files=", ".join(list(file_contexts.keys())[:20]),
                    dependencies=", ".join(dependencies[:15]),
                    test_files=", ".join(test_files),
                    source_files=", ".join(source_files),
                )
                raw = self._send_sync(summary_prompt)
                parsed = self._parse_json_response(raw)
                context.description = parsed.get("description", f"Python project: {project_path.name}")
                context.framework = parsed.get("framework", "Python")
                context.architecture_summary = parsed.get("architecture_summary", "")
                context.component_relationships = parsed.get("component_relationships", [])
            except Exception as e:
                logger.warning(f"AI project enhancement skipped: {e}")
                context.description = f"Python project: {project_path.name}"
                context.framework = "Python"
        else:
            context.description = f"Python project: {project_path.name}"
            context.framework = "Python"

        return context

    def resolve_relationships(
        self,
        context: ProjectContext,
        mentioned_files: list[str],
        mentioned_symbol: str = "",
    ) -> dict[str, Any]:
        """
        Understand the relationship between failing tests and the implementation under test.
        Returns:
            {
                "failure_detection_file": str,
                "root_cause_file": str,
                "target_symbol": str,
                "relevant_files": list[str]
            }
        """
        failure_detection_file = ""
        root_cause_file = ""
        target_symbol = mentioned_symbol
        all_relevant = list(mentioned_files)

        # Check if mentioned symbol points to a source file
        if target_symbol and target_symbol in context.function_to_file:
            cand_file = context.function_to_file[target_symbol]
            if cand_file in context.test_files:
                failure_detection_file = cand_file
                # Find the source file tested
                root_cause_file = context.test_to_source_mapping.get(cand_file, "")
            else:
                root_cause_file = cand_file

        # Check mentioned files
        for f in mentioned_files:
            # Match against context files
            norm_f = f.replace("\\", "/")
            matched = None
            for cf in context.files:
                if cf == norm_f or cf.endswith(norm_f) or norm_f.endswith(cf):
                    matched = cf
                    break
            
            if matched:
                if matched in context.test_files:
                    failure_detection_file = matched
                    src = context.test_to_source_mapping.get(matched)
                    if src and not root_cause_file:
                        root_cause_file = src
                        if src not in all_relevant:
                            all_relevant.append(src)
                else:
                    if not root_cause_file:
                        root_cause_file = matched

        # If we have a root_cause_file but no test file, look for test
        if root_cause_file and not failure_detection_file:
            for tf, sf in context.test_to_source_mapping.items():
                if sf == root_cause_file:
                    failure_detection_file = tf
                    if tf not in all_relevant:
                        all_relevant.append(tf)
                    break

        # If we have a failure_detection_file but no root_cause_file
        if failure_detection_file and not root_cause_file:
            src = context.test_to_source_mapping.get(failure_detection_file)
            if src:
                root_cause_file = src
                if src not in all_relevant:
                    all_relevant.append(src)

        # Ensure both root cause file and failure detection file are included in relevant files
        if root_cause_file and root_cause_file not in all_relevant:
            all_relevant.append(root_cause_file)
        if failure_detection_file and failure_detection_file not in all_relevant:
            all_relevant.append(failure_detection_file)

        return {
            "failure_detection_file": failure_detection_file,
            "root_cause_file": root_cause_file,
            "target_symbol": target_symbol,
            "relevant_files": list(dict.fromkeys(all_relevant)),
        }
