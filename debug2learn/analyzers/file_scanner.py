"""
File Scanner — Project file discovery and filtering.

Walks the project directory, applies ignore patterns, and
identifies relevant source files for analysis.
"""

from __future__ import annotations

from pathlib import Path

from debug2learn.config.settings import (
    IGNORE_PATTERNS,
    MAX_FILE_SIZE,
    MAX_FILES_INITIAL_SCAN,
    PYTHON_EXTENSIONS,
)


class FileScanner:
    """Scans a project directory to discover analyzable files."""

    def __init__(self, project_path: Path | str | None = None):
        self.project_path = Path(project_path).resolve() if project_path else Path.cwd()

    def scan(self, project_path: Path | str | None = None) -> list[Path]:
        """
        Scan the project and return a list of Python files to analyze.
        """
        base_path = Path(project_path).resolve() if project_path else self.project_path
        files: list[Path] = []

        for path in self._walk(base_path):
            if len(files) >= MAX_FILES_INITIAL_SCAN:
                break
            
            if not self._should_include(path):
                continue
            
            files.append(path)

        files.sort(key=lambda p: str(p.relative_to(base_path)))
        return files

    def find_python_files(self, project_path: Path | str | None = None) -> list[Path]:
        """Alias for scan."""
        return self.scan(project_path)

    def find_dependency_files(self, project_path: Path | str | None = None) -> list[Path]:
        """Find requirements.txt, Pipfile, pyproject.toml, etc."""
        base_path = Path(project_path).resolve() if project_path else self.project_path
        dep_names = {"requirements.txt", "Pipfile", "pyproject.toml", "setup.py", "environment.yml"}
        found = []
        for name in dep_names:
            p = base_path / name
            if p.exists() and p.is_file():
                found.append(p)
        return found

    def _walk(self, directory: Path):
        """Walk directory tree, skipping ignored directories."""
        try:
            for entry in sorted(directory.iterdir()):
                if entry.name in IGNORE_PATTERNS:
                    continue
                if entry.name.startswith(".") and entry.name != ".env":
                    continue

                if entry.is_dir():
                    yield from self._walk(entry)
                elif entry.is_file():
                    yield entry
        except PermissionError:
            pass

    def _should_include(self, path: Path) -> bool:
        """Check if a file should be included in analysis."""
        # Check extension
        if path.suffix not in PYTHON_EXTENSIONS:
            return False

        # Check file size
        try:
            if path.stat().st_size > MAX_FILE_SIZE:
                return False
            if path.stat().st_size == 0:
                return False
        except OSError:
            return False

        return True

    def get_dependency_files(self) -> dict[str, Path]:
        """
        Find dependency/configuration files in the project.
        
        Returns a dict of file type → path.
        """
        candidates = {
            "requirements.txt": None,
            "requirements-dev.txt": None,
            "pyproject.toml": None,
            "setup.py": None,
            "setup.cfg": None,
            "Pipfile": None,
            "poetry.lock": None,
            "Dockerfile": None,
            "docker-compose.yml": None,
            "docker-compose.yaml": None,
            ".env": None,
            ".env.example": None,
            "Makefile": None,
            "tox.ini": None,
            "pytest.ini": None,
            "conftest.py": None,
        }

        found: dict[str, Path] = {}
        for name in candidates:
            path = self.project_path / name
            if path.exists():
                found[name] = path

        return found
