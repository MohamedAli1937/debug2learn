"""
Git Analyzer — Git-based change detection.

Uses GitPython to detect file changes via git status and git diff.
This is the primary deterministic mechanism for the Checker agent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from git import Repo, InvalidGitRepositoryError, GitCommandNotFound
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False


class GitAnalyzer:
    """Analyzes git repositories for change detection."""

    def __init__(self, project_path: Path):
        self.project_path = project_path.resolve()
        self._repo: Any | None = None
        self._available = False
        self._init_repo()

    def _init_repo(self):
        """Try to initialize the git repo."""
        if not GIT_AVAILABLE:
            return
        try:
            self._repo = Repo(self.project_path)
            self._available = True
        except (InvalidGitRepositoryError, Exception):
            self._available = False

    @property
    def is_available(self) -> bool:
        """Whether git is available and the project is a git repository."""
        return self._available and self._repo is not None

    def get_current_commit(self) -> str:
        """Get the current HEAD commit hash."""
        if not self.is_available:
            return ""
        try:
            return str(self._repo.head.commit.hexsha)  # type: ignore
        except Exception:
            return ""

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        if not self.is_available:
            return ""
        try:
            return str(self._repo.active_branch.name)  # type: ignore
        except Exception:
            return ""

    def get_changed_files(self) -> dict[str, list[str]]:
        """
        Get all changed files grouped by status.
        
        Returns dict with keys: 'modified', 'added', 'deleted', 'untracked'
        """
        if not self.is_available:
            return {"modified": [], "added": [], "deleted": [], "untracked": []}

        result: dict[str, list[str]] = {
            "modified": [],
            "added": [],
            "deleted": [],
            "untracked": [],
        }

        try:
            # Staged changes
            diff_staged = self._repo.index.diff(self._repo.head.commit)  # type: ignore
            for d in diff_staged:
                if d.change_type == "A":
                    result["added"].append(d.b_path)
                elif d.change_type == "D":
                    result["deleted"].append(d.a_path)
                elif d.change_type in ("M", "R"):
                    result["modified"].append(d.b_path or d.a_path)

            # Unstaged changes
            diff_unstaged = self._repo.index.diff(None)  # type: ignore
            for d in diff_unstaged:
                if d.change_type == "A":
                    result["added"].append(d.b_path)
                elif d.change_type == "D":
                    result["deleted"].append(d.a_path)
                elif d.change_type in ("M", "R"):
                    path = d.b_path or d.a_path
                    if path not in result["modified"]:
                        result["modified"].append(path)

            # Untracked files
            result["untracked"] = list(self._repo.untracked_files)  # type: ignore

        except Exception:
            pass

        return result

    def get_diff(self, file_path: str | None = None) -> str:
        """
        Get the git diff for the working directory.
        
        If file_path is provided, only get diff for that file.
        """
        if not self.is_available:
            return ""

        try:
            if file_path:
                return self._repo.git.diff("--", file_path)  # type: ignore
            return self._repo.git.diff()  # type: ignore
        except Exception:
            return ""

    def get_diff_since_commit(self, commit_hash: str) -> str:
        """Get diff since a specific commit."""
        if not self.is_available or not commit_hash:
            return ""

        try:
            return self._repo.git.diff(commit_hash, "--")  # type: ignore
        except Exception:
            return ""

    def get_file_content_at_commit(self, file_path: str, commit_hash: str) -> str | None:
        """Get file content at a specific commit."""
        if not self.is_available:
            return None

        try:
            commit = self._repo.commit(commit_hash)  # type: ignore
            blob = commit.tree / file_path
            return blob.data_stream.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    def create_snapshot_commit(self, message: str = "debug2learn: snapshot") -> str:
        """
        Create a snapshot commit to mark the current state.
        Used to track changes between Teacher interactions.
        
        Returns the commit hash, or empty string if failed.
        """
        if not self.is_available:
            return ""

        try:
            self._repo.git.add("-A")  # type: ignore
            self._repo.index.commit(message)  # type: ignore
            return self.get_current_commit()
        except Exception:
            return ""
