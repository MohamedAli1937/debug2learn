from __future__ import annotations

import difflib
import logging
from pathlib import Path
from typing import Any

from debug2learn.analyzers.ast_analyzer import ASTAnalyzer
from debug2learn.analyzers.git_analyzer import GitAnalyzer
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    Change,
    ChangeSet,
    ChangeType,
    ProjectContext,
)

logger = logging.getLogger(__name__)


class TrackerAgent:
    """
    🎯 Tracker — Detects and summarizes developer code changes in relevant files.
    """

    def __init__(self, config: AppConfig, project_path: Path):
        self.config = config
        self.project_path = project_path.resolve()
        self.ast_analyzer = ASTAnalyzer()
        self.git_analyzer = GitAnalyzer(self.project_path)
        self._file_snapshots: dict[str, str] = {}

    def _normalize_path(self, raw_path: str | Path) -> str:
        """Normalize any path or symbol reference into a project-relative path."""
        s = str(raw_path).strip()
        if "->" in s:
            s = s.split("->")[0].strip()
        if "::" in s:
            s = s.split("::")[0].strip()
        
        p = Path(s)
        if p.is_absolute():
            try:
                rel = p.resolve().relative_to(self.project_path)
                return str(rel).replace("\\", "/")
            except ValueError:
                return p.name
        
        try:
            full = (self.project_path / p).resolve()
            rel = full.relative_to(self.project_path)
            return str(rel).replace("\\", "/")
        except (ValueError, AttributeError):
            pass
            
        return str(p).replace("\\", "/").lstrip("./")

    def snapshot_relevant_files(self, relevant_files: list[str]) -> None:
        """
        Take an in-memory snapshot of the relevant files before the user makes changes.
        Existing baseline snapshots are preserved to avoid resetting the baseline.
        """
        for raw_entry in relevant_files:
            rel_file = self._normalize_path(raw_entry)
            if not rel_file:
                continue
            file_path = self.project_path / rel_file
            if file_path.exists() and file_path.is_file():
                # Do not overwrite an existing baseline snapshot
                if rel_file not in self._file_snapshots:
                    try:
                        self._file_snapshots[rel_file] = file_path.read_text(encoding="utf-8", errors="replace")
                    except Exception as e:
                        logger.warning(f"Could not snapshot {rel_file}: {e}")

    def track_changes(self, relevant_files: list[str] | None = None) -> ChangeSet:
        """
        Detect changes in relevant files.
        Compares current file contents against initial snapshots.
        """
        changes: list[Change] = []
        files_changed: set[str] = set()
        raw_diffs: list[str] = []

        # Determine files to check: if specified, check only those; otherwise check all snapshots
        if relevant_files is not None:
            target_files = {self._normalize_path(f) for f in relevant_files if self._normalize_path(f)}
        else:
            target_files = set(self._file_snapshots.keys())

        # Check relevant files against snapshots
        for rel_file in sorted(target_files):
            file_path = self.project_path / rel_file
            if not file_path.exists():
                if rel_file in self._file_snapshots:
                    files_changed.add(rel_file)
                    changes.append(Change(
                        file_path=rel_file,
                        change_type=ChangeType.FILE_DELETED,
                        description=f"File {rel_file} was deleted.",
                    ))
                continue

            try:
                current_code = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            old_code = self._file_snapshots.get(rel_file)
            if old_code is None:
                # Try finding matching snapshot by filename
                for snap_k, snap_v in self._file_snapshots.items():
                    if Path(snap_k).name == Path(rel_file).name:
                        old_code = snap_v
                        break

            if old_code is not None:
                if old_code != current_code:
                    files_changed.add(rel_file)
                    
                    diff_lines = list(difflib.unified_diff(
                        old_code.splitlines(),
                        current_code.splitlines(),
                        fromfile=f"a/{rel_file}",
                        tofile=f"b/{rel_file}",
                        lineterm="",
                    ))
                    diff_text = "\n".join(diff_lines)
                    raw_diffs.append(diff_text)

                    # AST symbol level change analysis
                    sym_changes = self.ast_analyzer.compare_files(old_code, current_code, rel_file)
                    for sc in sym_changes:
                        changes.append(Change(
                            file_path=rel_file,
                            change_type=ChangeType(sc.get("change_type", "file_modified")),
                            symbol=sc.get("symbol", ""),
                            description=sc.get("description", f"Modified {rel_file}"),
                            diff=diff_text,
                        ))

                    if not sym_changes:
                        changes.append(Change(
                            file_path=rel_file,
                            change_type=ChangeType.FILE_MODIFIED,
                            diff=diff_text,
                            description=f"Changes made in {rel_file}",
                        ))

        # Check git as fallback if no snapshot changes detected
        if not changes and self.git_analyzer.is_available:
            git_diff = self.git_analyzer.get_diff()
            if git_diff:
                raw_diffs.append(git_diff)
                changed_dict = self.git_analyzer.get_changed_files()
                for cat, file_list in changed_dict.items():
                    for f in file_list:
                        norm_f = self._normalize_path(f)
                        if target_files and not any(norm_f == tf or norm_f.endswith(tf) for tf in target_files):
                            continue
                        files_changed.add(norm_f)
                        changes.append(Change(
                            file_path=norm_f,
                            change_type=ChangeType.FILE_MODIFIED,
                            diff=git_diff,
                            description=f"Git change: {cat} {norm_f}",
                        ))

        return ChangeSet(
            changes=changes,
            files_changed=list(files_changed),
            git_diff_raw="\n\n".join(raw_diffs),
        )

    def get_file_content(self, rel_path: str) -> str:
        """Read current content of a file."""
        norm = self._normalize_path(rel_path)
        p = self.project_path / norm
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
        p2 = Path(rel_path)
        if p2.exists() and p2.is_file():
            return p2.read_text(encoding="utf-8", errors="replace")
        return ""
