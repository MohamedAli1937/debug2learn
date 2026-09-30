"""
Tests for the File Scanner.
"""

import pytest

from backend.analyzers.file_scanner import FileScanner


@pytest.fixture
def sample_project(tmp_path):
    """Create a sample project structure for scanning."""
    # Python files
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "auth.py").write_text("def login(): pass")
    (tmp_path / "models.py").write_text("class User: pass")

    # Subdirectory
    utils_dir = tmp_path / "utils"
    utils_dir.mkdir()
    (utils_dir / "__init__.py").write_text("")
    (utils_dir / "helpers.py").write_text("def helper(): pass")

    # Test directory
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_auth.py").write_text("def test_login(): pass")

    # Non-Python files (should be excluded)
    (tmp_path / "README.md").write_text("# Project")
    (tmp_path / "requirements.txt").write_text("flask")

    # Ignored directories
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "main.cpython-310.pyc").write_text("compiled")

    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    (venv_dir / "somefile.py").write_text("# venv file")

    return tmp_path


class TestFileScanner:
    """Tests for FileScanner."""

    def test_scan_finds_python_files(self, sample_project):
        scanner = FileScanner(sample_project)
        files = scanner.scan()

        names = [f.name for f in files]
        assert "main.py" in names
        assert "auth.py" in names
        assert "models.py" in names

    def test_scan_ignores_pycache(self, sample_project):
        scanner = FileScanner(sample_project)
        files = scanner.scan()

        paths = [str(f) for f in files]
        assert not any("__pycache__" in p for p in paths)

    def test_scan_ignores_venv(self, sample_project):
        scanner = FileScanner(sample_project)
        files = scanner.scan()

        rel_paths = [f.relative_to(sample_project).parts for f in files]
        assert not any("venv" in parts for parts in rel_paths)

    def test_scan_excludes_non_python(self, sample_project):
        scanner = FileScanner(sample_project)
        files = scanner.scan()

        names = [f.name for f in files]
        assert "README.md" not in names
        assert "requirements.txt" not in names

    def test_scan_includes_subdirectories(self, sample_project):
        scanner = FileScanner(sample_project)
        files = scanner.scan()

        names = [f.name for f in files]
        assert "helpers.py" in names
        assert "test_auth.py" in names

    def test_get_dependency_files(self, sample_project):
        scanner = FileScanner(sample_project)
        deps = scanner.get_dependency_files()

        assert "requirements.txt" in deps

    def test_empty_project(self, tmp_path):
        scanner = FileScanner(tmp_path)
        files = scanner.scan()
        assert len(files) == 0
