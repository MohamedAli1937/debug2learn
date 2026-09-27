from __future__ import annotations

import difflib
import logging
from pathlib import Path

from debug2learn.analyzers.ast_analyzer import ASTAnalyzer
from debug2learn.analyzers.git_analyzer import GitAnalyzer
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    Change,
    ChangeSet,
    ChangeType,
)

logger = logging.getLogger(__name__)


class TrackerAgent:
    """
    🎯 Tracker — Detects and summarizes developer code changes
    in relevant files.

    Change sources:
    1. In-memory file snapshots
    2. Local Git working tree
    3. Remote Git repository
    """

    def __init__(self, config: AppConfig, project_path: Path):
        self.config = config
        self.project_path = project_path.resolve()
        self.ast_analyzer = ASTAnalyzer()
        self.git_analyzer = GitAnalyzer(self.project_path)

        # Initial file contents captured when the debugging session starts.
        self._file_snapshots: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Path handling
    # ------------------------------------------------------------------

    def _normalize_path(self, raw_path: str | Path) -> str:
        """
        Normalize a path or symbol reference into a project-relative path.
        """
        s = str(raw_path).strip()

        if not s:
            return ""

        # Handle references such as:
        # file.py -> function_name
        if "->" in s:
            s = s.split("->")[0].strip()

        # Handle references such as:
        # file.py::function_name
        if "::" in s:
            s = s.split("::")[0].strip()

        p = Path(s)

        # Absolute path
        if p.is_absolute():
            try:
                rel = p.resolve().relative_to(self.project_path)
                return str(rel).replace("\\", "/")
            except ValueError:
                return p.name.replace("\\", "/")

        # Relative path
        try:
            full = (self.project_path / p).resolve()
            rel = full.relative_to(self.project_path)
            return str(rel).replace("\\", "/")
        except (ValueError, AttributeError):
            pass

        return str(p).replace("\\", "/").lstrip("./")

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot_relevant_files(self, relevant_files: list[str]) -> None:
        """
        Take an in-memory snapshot of relevant files before the developer
        starts modifying the project.

        Existing snapshots are preserved so repeated calls do not reset
        the original debugging baseline.
        """
        for raw_entry in relevant_files:
            rel_file = self._normalize_path(raw_entry)

            if not rel_file:
                continue

            file_path = self.project_path / rel_file

            if not file_path.exists() or not file_path.is_file():
                logger.warning(
                    "Relevant file does not exist: %s",
                    rel_file,
                )
                continue

            if rel_file in self._file_snapshots:
                continue

            try:
                self._file_snapshots[rel_file] = file_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )

                logger.debug(
                    "Snapshot created for %s",
                    rel_file,
                )

            except Exception as exc:
                logger.warning(
                    "Could not snapshot %s: %s",
                    rel_file,
                    exc,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_relevant(
        self,
        path: str,
        target_files: set[str],
    ) -> bool:
        """
        Check whether a changed path belongs to the relevant files.
        """
        norm = self._normalize_path(path)

        if not target_files:
            return True

        return any(
            norm == target
            or norm.endswith(f"/{target}")
            or target.endswith(f"/{norm}")
            for target in target_files
        )

    def _add_snapshot_change(
        self,
        rel_file: str,
        old_code: str,
        current_code: str,
        changes: list[Change],
        files_changed: set[str],
        raw_diffs: list[str],
    ) -> None:
        """
        Analyze a file change between its initial snapshot and current
        working-tree contents.
        """
        if old_code == current_code:
            return

        files_changed.add(rel_file)

        diff_lines = list(
            difflib.unified_diff(
                old_code.splitlines(),
                current_code.splitlines(),
                fromfile=f"a/{rel_file}",
                tofile=f"b/{rel_file}",
                lineterm="",
            )
        )

        diff_text = "\n".join(diff_lines)

        if diff_text:
            raw_diffs.append(diff_text)

        # Analyze symbol-level changes using AST.
        try:
            symbol_changes = self.ast_analyzer.compare_files(
                old_code,
                current_code,
                rel_file,
            )
        except Exception as exc:
            logger.warning(
                "AST comparison failed for %s: %s",
                rel_file,
                exc,
            )
            symbol_changes = []

        for symbol_change in symbol_changes:
            try:
                change_type = ChangeType(
                    symbol_change.get(
                        "change_type",
                        "file_modified",
                    )
                )
            except ValueError:
                change_type = ChangeType.FILE_MODIFIED

            changes.append(
                Change(
                    file_path=rel_file,
                    change_type=change_type,
                    symbol=symbol_change.get("symbol", ""),
                    description=symbol_change.get(
                        "description",
                        f"Modified {rel_file}",
                    ),
                    diff=diff_text,
                )
            )

        # If AST did not identify symbols, still report the file change.
        if not symbol_changes:
            changes.append(
                Change(
                    file_path=rel_file,
                    change_type=ChangeType.FILE_MODIFIED,
                    diff=diff_text,
                    description=f"Changes made in {rel_file}",
                )
            )

    # ------------------------------------------------------------------
    # Main change detection
    # ------------------------------------------------------------------

    def track_changes(
        self,
        relevant_files: list[str] | None = None,
    ) -> ChangeSet:
        """
        Detect changes in relevant files.

        Detection order:

        1. Compare files against the original in-memory snapshot.
        2. Check local Git working-tree changes.
        3. Check remote Git repository changes.

        The Tracker only detects and summarizes changes.
        It does NOT decide whether a change fixes the bug.
        That decision belongs to Solver.
        """
        changes: list[Change] = []
        files_changed: set[str] = set()
        raw_diffs: list[str] = []

        # --------------------------------------------------------------
        # Determine relevant files
        # --------------------------------------------------------------

        if relevant_files is not None:
            target_files = {
                self._normalize_path(file)
                for file in relevant_files
                if self._normalize_path(file)
            }
        else:
            target_files = set(self._file_snapshots.keys())

        # --------------------------------------------------------------
        # 1. Compare against in-memory snapshots
        # --------------------------------------------------------------

        for rel_file in sorted(target_files):
            file_path = self.project_path / rel_file

            # File was deleted locally.
            if not file_path.exists():
                if rel_file in self._file_snapshots:
                    files_changed.add(rel_file)

                    changes.append(
                        Change(
                            file_path=rel_file,
                            change_type=ChangeType.FILE_DELETED,
                            description=(
                                f"File {rel_file} was deleted."
                            ),
                        )
                    )

                continue

            if not file_path.is_file():
                continue

            try:
                current_code = file_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as exc:
                logger.warning(
                    "Could not read %s: %s",
                    rel_file,
                    exc,
                )
                continue

            old_code = self._file_snapshots.get(rel_file)

            # Try matching by filename if the exact normalized path
            # was not found.
            if old_code is None:
                for snapshot_path, snapshot_code in (
                    self._file_snapshots.items()
                ):
                    if (
                        Path(snapshot_path).name
                        == Path(rel_file).name
                    ):
                        old_code = snapshot_code
                        break

            if old_code is None:
                continue

            self._add_snapshot_change(
                rel_file=rel_file,
                old_code=old_code,
                current_code=current_code,
                changes=changes,
                files_changed=files_changed,
                raw_diffs=raw_diffs,
            )

        # --------------------------------------------------------------
        # 2. Check local Git working-tree changes
        # --------------------------------------------------------------

        if not changes and self.git_analyzer.is_available:
            try:
                git_diff = self.git_analyzer.get_diff()
                changed_dict = self.git_analyzer.get_changed_files()

                if git_diff:
                    raw_diffs.append(git_diff)

                for category, file_list in changed_dict.items():
                    for file_path in file_list:
                        norm_file = self._normalize_path(file_path)

                        if not self._is_relevant(
                            norm_file,
                            target_files,
                        ):
                            continue

                        files_changed.add(norm_file)

                        if category == "deleted":
                            change_type = ChangeType.FILE_DELETED
                        else:
                            change_type = ChangeType.FILE_MODIFIED

                        changes.append(
                            Change(
                                file_path=norm_file,
                                change_type=change_type,
                                diff=git_diff,
                                description=(
                                    f"Git local change: "
                                    f"{category} {norm_file}"
                                ),
                            )
                        )

            except Exception as exc:
                logger.warning(
                    "Local Git change detection failed: %s",
                    exc,
                )

        # --------------------------------------------------------------
        # 3. Check remote Git repository
        # --------------------------------------------------------------

        if not changes and self.git_analyzer.is_available:
            try:
                # Fetch remote refs if supported.
                fetch_remote = getattr(
                    self.git_analyzer,
                    "fetch_remote",
                    None,
                )

                if callable(fetch_remote):
                    fetch_remote()

                get_remote_changed_files = getattr(
                    self.git_analyzer,
                    "get_remote_changed_files",
                    None,
                )

                get_remote_diff = getattr(
                    self.git_analyzer,
                    "get_remote_diff",
                    None,
                )

                if callable(get_remote_changed_files):
                    remote_changes = get_remote_changed_files()
                else:
                    remote_changes = {}

                if callable(get_remote_diff):
                    remote_diff = get_remote_diff()
                else:
                    remote_diff = ""

                if remote_diff:
                    raw_diffs.append(remote_diff)

                for category, file_list in remote_changes.items():
                    for file_path in file_list:
                        norm_file = self._normalize_path(file_path)

                        if not self._is_relevant(
                            norm_file,
                            target_files,
                        ):
                            continue

                        files_changed.add(norm_file)

                        if category == "deleted":
                            change_type = ChangeType.FILE_DELETED
                        else:
                            change_type = ChangeType.FILE_MODIFIED

                        changes.append(
                            Change(
                                file_path=norm_file,
                                change_type=change_type,
                                diff=remote_diff,
                                description=(
                                    f"Git remote change: "
                                    f"{category} {norm_file}"
                                ),
                            )
                        )

            except Exception as exc:
                logger.warning(
                    "Remote Git change detection failed: %s",
                    exc,
                )

        # --------------------------------------------------------------
        # Return result
        # --------------------------------------------------------------

        return ChangeSet(
            changes=changes,
            files_changed=sorted(files_changed),
            git_diff_raw="\n\n".join(
                diff for diff in raw_diffs if diff
            ),
        )

    # ------------------------------------------------------------------
    # File content
    # ------------------------------------------------------------------

    def get_file_content(self, rel_path: str) -> str:
        """
        Read the current local content of a file.

        Tracker does not modify the repository.
        """
        norm = self._normalize_path(rel_path)

        if not norm:
            return ""

        file_path = self.project_path / norm

        if file_path.exists() and file_path.is_file():
            try:
                return file_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as exc:
                logger.warning(
                    "Could not read file %s: %s",
                    norm,
                    exc,
                )

        # Fallback for callers passing an already-resolved path.
        direct_path = Path(rel_path)

        if direct_path.exists() and direct_path.is_file():
            try:
                return direct_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception as exc:
                logger.warning(
                    "Could not read direct path %s: %s",
                    rel_path,
                    exc,
                )

        return ""