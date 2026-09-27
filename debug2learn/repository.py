"""Clone and clean up public GitHub repositories for hosted sessions."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

_GITHUB_HOSTS = {"github.com", "www.github.com"}
_GITHUB_PATH = re.compile(r"^/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?(?:/(?P<rest>.*))?$")


class RepositoryError(Exception):
    """Raised when a public GitHub repository cannot be acquired."""


@dataclass
class TemporaryRepository:
    """A cloned repository that lives in a temporary directory."""

    root: Path

    def cleanup(self) -> None:
        if self.root.exists():
            _rmtree(self.root)


def acquire_repository(project_url: str) -> tuple[TemporaryRepository, Path]:
    """Clone a public GitHub repository and return (handle, project path)."""
    clone_url, branch, subdir = _parse_github_url(project_url)
    temp_root = Path(tempfile.mkdtemp(prefix="debug2learn-repo-"))
    command = ["git", "clone", "--depth", "1", "--single-branch"]
    if branch:
        command.extend(["--branch", branch])
    command.extend([clone_url, str(temp_root)])
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as exc:
        _rmtree(temp_root)
        raise RepositoryError("Git is not installed on the server.") from exc
    except subprocess.TimeoutExpired as exc:
        _rmtree(temp_root)
        raise RepositoryError("Timed out while cloning the GitHub repository.") from exc
    except subprocess.CalledProcessError as exc:
        _rmtree(temp_root)
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RepositoryError(
            f"Unable to clone the public GitHub repository. {detail}"
        ) from exc

    target = temp_root
    if subdir:
        target = (temp_root / subdir).resolve()
        try:
            target.relative_to(temp_root.resolve())
        except ValueError as exc:
            TemporaryRepository(temp_root).cleanup()
            raise RepositoryError("Repository subdirectory is invalid.") from exc
        if not target.is_dir():
            TemporaryRepository(temp_root).cleanup()
            raise RepositoryError(f"Repository subdirectory not found: {subdir}")

    return TemporaryRepository(temp_root), target


def _parse_github_url(raw_url: str) -> tuple[str, str | None, str | None]:
    url = (raw_url or "").strip()
    if not url:
        raise RepositoryError("A public GitHub project_url is required.")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        url = "https://" + url.lstrip("/")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RepositoryError("Only public GitHub HTTPS URLs are supported.")
    host = (parsed.hostname or "").lower()
    if host not in _GITHUB_HOSTS:
        raise RepositoryError("Only public GitHub repositories are supported.")

    match = _GITHUB_PATH.match(parsed.path or "")
    if not match:
        raise RepositoryError("GitHub URL must look like https://github.com/owner/repo.")

    owner = match.group("owner")
    repo = match.group("repo")
    rest = (match.group("rest") or "").strip("/")
    clone_url = f"https://github.com/{owner}/{repo}.git"

    branch: str | None = None
    subdir: str | None = None
    if rest:
        parts = rest.split("/")
        if parts[0] in {"tree", "blob", "raw"} and len(parts) >= 2:
            branch = parts[1]
            nested = "/".join(parts[2:])
            subdir = nested or None
        elif parts[0] not in {"issues", "pull", "commit", "actions", "wiki", "releases"}:
            raise RepositoryError("GitHub URL must look like https://github.com/owner/repo.")

    return clone_url, branch, subdir


def _rmtree(path: Path) -> None:
    def _onerror(func, name, _exc):
        try:
            os.chmod(name, stat.S_IWRITE)
            func(name)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_onerror)
