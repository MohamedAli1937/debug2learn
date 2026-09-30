"""
Git Analyzer — Git-based change detection.

Uses GitPython to detect:
- staged changes
- unstaged changes
- untracked files
- changes introduced by newer remote commits

The analyzer never performs `git pull` and never modifies the
developer's working tree when checking remote updates.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    from git import GitCommandNotFound, InvalidGitRepositoryError, Repo

    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False

logger = logging.getLogger(__name__)


class GitAnalyzer:
    """Analyzes git repositories for local and remote changes."""

    def __init__(self, project_path: Path):
        self.project_path = project_path.resolve()
        self._repo: Any | None = None
        self._available = False
        self._init_repo()

    def _init_repo(self) -> None:
        """Try to initialize the git repository."""
        if not GIT_AVAILABLE:
            logger.warning("GitPython is not installed.")
            return

        try:
            self._repo = Repo(self.project_path)
            self._available = not self._repo.bare
        except InvalidGitRepositoryError:
            logger.warning(
                "Not a git repository: %s",
                self.project_path,
            )
            self._available = False
        except GitCommandNotFound:
            logger.warning("Git executable was not found.")
            self._available = False
        except Exception as exc:
            logger.warning(
                "Failed to initialize git repository: %s",
                exc,
            )
            self._available = False

    @property
    def is_available(self) -> bool:
        """Whether git is available and the project is a git repository."""
        return self._available and self._repo is not None

    def get_current_commit(self) -> str:
        """Get the current local HEAD commit hash."""
        if not self.is_available:
            return ""

        try:
            return str(self._repo.head.commit.hexsha)
        except Exception as exc:
            logger.warning(
                "Could not get current commit: %s",
                exc,
            )
            return ""

    def get_current_branch(self) -> str:
        """Get the current local branch name."""
        if not self.is_available:
            return ""

        try:
            if self._repo.head.is_detached:
                return ""

            return str(self._repo.active_branch.name)
        except Exception as exc:
            logger.warning(
                "Could not get current branch: %s",
                exc,
            )
            return ""

    def get_remote_url(self) -> str:
        """Get the URL of the first configured remote."""
        if not self.is_available:
            return ""

        try:
            if not self._repo.remotes:
                return ""

            return str(self._repo.remotes[0].url)
        except Exception as exc:
            logger.warning(
                "Could not get remote URL: %s",
                exc,
            )
            return ""

    def fetch_remote(self) -> bool:
        """
        Fetch remote refs without changing the working tree.

        This updates local remote-tracking refs such as origin/main,
        but does not merge or checkout anything.
        """
        if not self.is_available:
            return False

        try:
            if not self._repo.remotes:
                logger.info("No git remotes configured.")
                return False

            for remote in self._repo.remotes:
                remote.fetch(prune=True)

            return True

        except Exception as exc:
            logger.warning(
                "Failed to fetch remote repository: %s",
                exc,
            )
            return False

    def get_remote_branch(self) -> str:
        """Return the remote tracking branch for the current branch."""
        if not self.is_available:
            return ""

        try:
            branch = self._repo.active_branch

            if branch.tracking_branch() is not None:
                return str(branch.tracking_branch().name)

            # Fallback to origin/<current-branch>.
            branch_name = branch.name

            if self._repo.remotes:
                remote_name = self._repo.remotes[0].name
                return f"{remote_name}/{branch_name}"

            return ""

        except Exception as exc:
            logger.warning(
                "Could not determine remote branch: %s",
                exc,
            )
            return ""

    def get_remote_commit(self) -> str:
        """Get the latest fetched commit on the configured remote branch."""
        if not self.is_available:
            return ""

        try:
            remote_branch = self.get_remote_branch()

            if not remote_branch:
                return ""

            commit = self._repo.commit(remote_branch)
            return str(commit.hexsha)

        except Exception as exc:
            logger.warning(
                "Could not get remote commit: %s",
                exc,
            )
            return ""

    def has_remote_updates(self) -> bool:
        """
        Fetch the remote and determine whether it contains commits
        that are not present in the local HEAD.
        """
        if not self.is_available:
            return False

        if not self.fetch_remote():
            return False

        local_commit = self.get_current_commit()
        remote_commit = self.get_remote_commit()

        if not local_commit or not remote_commit:
            return False

        return local_commit != remote_commit

    def get_remote_update_info(self) -> dict[str, Any]:
        """
        Return information about remote updates without modifying
        the working tree.
        """
        result: dict[str, Any] = {
            "has_updates": False,
            "local_commit": "",
            "remote_commit": "",
            "branch": self.get_current_branch(),
            "remote_branch": self.get_remote_branch(),
            "behind_by": 0,
            "commits": [],
        }

        if not self.is_available:
            return result

        if not self.fetch_remote():
            return result

        local_commit = self.get_current_commit()
        remote_commit = self.get_remote_commit()

        result["local_commit"] = local_commit
        result["remote_commit"] = remote_commit

        if not local_commit or not remote_commit:
            return result

        if local_commit == remote_commit:
            return result

        result["has_updates"] = True

        try:
            commits = list(self._repo.iter_commits(f"{local_commit}..{remote_commit}"))

            result["behind_by"] = len(commits)

            result["commits"] = [
                {
                    "hash": commit.hexsha,
                    "short_hash": commit.hexsha[:8],
                    "message": commit.message.strip(),
                    "author": str(commit.author),
                }
                for commit in commits
            ]

        except Exception as exc:
            logger.warning(
                "Could not inspect remote commits: %s",
                exc,
            )

        return result

    def get_changed_files(self) -> dict[str, list[str]]:
        """
        Get all local working-tree changes grouped by status.

        Returns:
            {
                "modified": [],
                "added": [],
                "deleted": [],
                "untracked": []
            }
        """
        result: dict[str, list[str]] = {
            "modified": [],
            "added": [],
            "deleted": [],
            "untracked": [],
        }

        if not self.is_available:
            return result

        try:
            head_commit = self._repo.head.commit

            # Staged changes.
            diff_staged = self._repo.index.diff(head_commit)

            for diff in diff_staged:
                change_type = diff.change_type

                if change_type == "A":
                    if diff.b_path:
                        result["added"].append(diff.b_path)

                elif change_type == "D":
                    if diff.a_path:
                        result["deleted"].append(diff.a_path)

                elif change_type in ("M", "R"):
                    path = diff.b_path or diff.a_path

                    if path and path not in result["modified"]:
                        result["modified"].append(path)

            # Unstaged changes.
            diff_unstaged = self._repo.index.diff(None)

            for diff in diff_unstaged:
                change_type = diff.change_type

                if change_type == "A":
                    if diff.b_path and diff.b_path not in result["added"]:
                        result["added"].append(diff.b_path)

                elif change_type == "D":
                    if diff.a_path and diff.a_path not in result["deleted"]:
                        result["deleted"].append(diff.a_path)

                elif change_type in ("M", "R"):
                    path = diff.b_path or diff.a_path

                    if path and path not in result["modified"]:
                        result["modified"].append(path)

            # Untracked files.
            for path in self._repo.untracked_files:
                if path not in result["untracked"]:
                    result["untracked"].append(path)

        except Exception as exc:
            logger.warning(
                "Git local change detection failed: %s",
                exc,
            )

        return result

    def get_changed_files_since_commit(
        self,
        commit_hash: str,
    ) -> dict[str, list[str]]:
        """
        Get files changed between a given commit and current HEAD.
        """
        result: dict[str, list[str]] = {
            "modified": [],
            "added": [],
            "deleted": [],
            "renamed": [],
        }

        if not self.is_available or not commit_hash:
            return result

        try:
            current_commit = self.get_current_commit()

            if not current_commit:
                return result

            diffs = self._repo.commit(commit_hash).diff(
                self._repo.commit(current_commit)
            )

            for diff in diffs:
                change_type = diff.change_type

                if change_type == "A":
                    if diff.b_path:
                        result["added"].append(diff.b_path)

                elif change_type == "D":
                    if diff.a_path:
                        result["deleted"].append(diff.a_path)

                elif change_type == "R":
                    path = diff.b_path or diff.a_path

                    if path:
                        result["renamed"].append(path)

                elif change_type == "M":
                    path = diff.b_path or diff.a_path

                    if path:
                        result["modified"].append(path)

        except Exception as exc:
            logger.warning(
                "Could not get changed files since %s: %s",
                commit_hash,
                exc,
            )

        return result

    def get_remote_changed_files(
        self,
        include_local_uncommitted: bool = False,
    ) -> dict[str, list[str]]:
        """
        Fetch remote updates and return files changed by remote commits
        that are ahead of local HEAD.

        The working tree is never modified.
        """
        result: dict[str, list[str]] = {
            "modified": [],
            "added": [],
            "deleted": [],
            "renamed": [],
        }

        if not self.is_available:
            return result

        if not self.fetch_remote():
            return result

        local_commit = self.get_current_commit()
        remote_commit = self.get_remote_commit()

        if not local_commit or not remote_commit:
            return result

        if local_commit == remote_commit:
            return result

        try:
            diffs = self._repo.commit(local_commit).diff(
                self._repo.commit(remote_commit)
            )

            for diff in diffs:
                change_type = diff.change_type

                if change_type == "A":
                    if diff.b_path:
                        result["added"].append(diff.b_path)

                elif change_type == "D":
                    if diff.a_path:
                        result["deleted"].append(diff.a_path)

                elif change_type == "R":
                    path = diff.b_path or diff.a_path

                    if path:
                        result["renamed"].append(path)

                elif change_type == "M":
                    path = diff.b_path or diff.a_path

                    if path:
                        result["modified"].append(path)

        except Exception as exc:
            logger.warning(
                "Could not inspect remote file changes: %s",
                exc,
            )

        # Optionally include local working-tree changes too.
        if include_local_uncommitted:
            local_changes = self.get_changed_files()

            result["modified"].extend(local_changes["modified"])
            result["added"].extend(local_changes["added"])
            result["deleted"].extend(local_changes["deleted"])

        # Remove duplicates while preserving order.
        for key in result:
            result[key] = list(dict.fromkeys(result[key]))

        return result

    def get_diff(self, file_path: str | None = None) -> str:
        """
        Get the unstaged git diff for the working directory.

        If file_path is provided, only return the diff for that file.
        """
        if not self.is_available:
            return ""

        try:
            if file_path:
                return self._repo.git.diff("--", file_path)

            return self._repo.git.diff()

        except Exception as exc:
            logger.warning(
                "Could not get working-tree diff: %s",
                exc,
            )
            return ""

    def get_staged_diff(self, file_path: str | None = None) -> str:
        """Get the staged git diff."""
        if not self.is_available:
            return ""

        try:
            if file_path:
                return self._repo.git.diff(
                    "--cached",
                    "--",
                    file_path,
                )

            return self._repo.git.diff("--cached")

        except Exception as exc:
            logger.warning(
                "Could not get staged diff: %s",
                exc,
            )
            return ""

    def get_diff_since_commit(self, commit_hash: str) -> str:
        """Get the diff from a commit to the current local HEAD."""
        if not self.is_available or not commit_hash:
            return ""

        try:
            current_commit = self.get_current_commit()

            if not current_commit:
                return ""

            return self._repo.git.diff(
                commit_hash,
                current_commit,
                "--",
            )

        except Exception as exc:
            logger.warning(
                "Could not get diff since commit %s: %s",
                commit_hash,
                exc,
            )
            return ""

    def get_remote_diff(self) -> str:
        """
        Fetch the remote and return the diff between local HEAD
        and the latest remote-tracking commit.
        """
        if not self.is_available:
            return ""

        if not self.fetch_remote():
            return ""

        local_commit = self.get_current_commit()
        remote_commit = self.get_remote_commit()

        if not local_commit or not remote_commit:
            return ""

        if local_commit == remote_commit:
            return ""

        try:
            return self._repo.git.diff(
                local_commit,
                remote_commit,
                "--",
            )

        except Exception as exc:
            logger.warning(
                "Could not get remote diff: %s",
                exc,
            )
            return ""

    def get_file_content_at_commit(
        self,
        file_path: str,
        commit_hash: str,
    ) -> str | None:
        """Get file content at a specific commit."""
        if not self.is_available:
            return None

        try:
            commit = self._repo.commit(commit_hash)
            blob = commit.tree / file_path

            return blob.data_stream.read().decode(
                "utf-8",
                errors="replace",
            )

        except Exception as exc:
            logger.warning(
                "Could not read %s at commit %s: %s",
                file_path,
                commit_hash,
                exc,
            )
            return None

    def create_snapshot_commit(
        self,
        message: str = "debug2learn: snapshot",
    ) -> str:
        """
        Create a snapshot commit to mark the current state.

        WARNING:
        This modifies the repository by staging and committing all changes.
        It should not be used automatically during normal tracking.
        """
        if not self.is_available:
            return ""

        try:
            self._repo.git.add("-A")
            self._repo.index.commit(message)

            return self.get_current_commit()

        except Exception as exc:
            logger.warning(
                "Could not create snapshot commit: %s",
                exc,
            )
            return ""
