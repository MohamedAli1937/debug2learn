"""
Tests for the AST Analyzer.

Tests deterministic Python code analysis without needing an LLM.
"""

import ast
import tempfile
from pathlib import Path

import pytest

from debug2learn.analyzers.ast_analyzer import ASTAnalyzer


@pytest.fixture
def analyzer():
    return ASTAnalyzer()


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary Python project for testing."""
    # Create a simple Python file
    auth_py = tmp_path / "auth.py"
    auth_py.write_text('''
"""Authentication module."""

import hashlib
from datetime import datetime

def login(username: str, password: str) -> dict:
    """Handle user login."""
    user = get_user(username)
    if verify_password(password, user["password_hash"]):
        return create_token(user)
    return None

def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    return hashlib.sha256(plain.encode()).hexdigest() == hashed

def create_token(user: dict) -> dict:
    """Create an authentication token."""
    return {"token": "abc123", "user": user["username"]}

class AuthManager:
    """Manages authentication state."""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
    
    def authenticate(self, username: str, password: str):
        """Authenticate a user."""
        pass
    
    def logout(self, token: str):
        """Logout a user."""
        pass
''')

    # Create a test file
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_auth = tests_dir / "test_auth.py"
    test_auth.write_text('''
"""Tests for auth module."""

import pytest
from auth import login, verify_password

def test_login_success():
    result = login("admin", "password")
    assert result is not None

def test_login_failure():
    result = login("admin", "wrong")
    assert result is None

def test_verify_password():
    assert verify_password("test", "hash") == False
''')

    # Create main.py
    main_py = tmp_path / "main.py"
    main_py.write_text('''
"""Application entry point."""

from auth import AuthManager

if __name__ == "__main__":
    manager = AuthManager("secret")
    print("Server started")
''')

    return tmp_path


class TestASTAnalyzer:
    """Tests for ASTAnalyzer."""

    def test_analyze_file_extracts_functions(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        ctx = analyzer.analyze_file(auth_path, tmp_project)

        assert ctx is not None
        func_names = [f.name for f in ctx.functions]
        assert "login" in func_names
        assert "verify_password" in func_names
        assert "create_token" in func_names

    def test_analyze_file_extracts_classes(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        ctx = analyzer.analyze_file(auth_path, tmp_project)

        assert ctx is not None
        class_names = [c.name for c in ctx.classes]
        assert "AuthManager" in class_names

    def test_analyze_file_extracts_imports(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        ctx = analyzer.analyze_file(auth_path, tmp_project)

        assert ctx is not None
        import_modules = [i.module for i in ctx.imports]
        assert "hashlib" in import_modules

    def test_detect_test_file(self, analyzer, tmp_project):
        test_path = tmp_project / "tests" / "test_auth.py"
        ctx = analyzer.analyze_file(test_path, tmp_project)

        assert ctx is not None
        assert ctx.is_test_file is True

    def test_detect_entry_point(self, analyzer, tmp_project):
        main_path = tmp_project / "main.py"
        ctx = analyzer.analyze_file(main_path, tmp_project)

        assert ctx is not None
        assert ctx.is_entry_point is True

    def test_non_entry_point(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        ctx = analyzer.analyze_file(auth_path, tmp_project)

        assert ctx is not None
        assert ctx.is_entry_point is False

    def test_function_parameters(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        ctx = analyzer.analyze_file(auth_path, tmp_project)

        login_func = next(f for f in ctx.functions if f.name == "login")
        assert "username" in login_func.parameters
        assert "password" in login_func.parameters

    def test_class_methods(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        ctx = analyzer.analyze_file(auth_path, tmp_project)

        auth_class = next(c for c in ctx.classes if c.name == "AuthManager")
        assert "authenticate" in auth_class.methods
        assert "logout" in auth_class.methods
        assert "__init__" in auth_class.methods

    def test_compare_files_detect_new_function(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        old_ctx = analyzer.analyze_file(auth_path, tmp_project)

        # Add a new function
        content = auth_path.read_text()
        content += "\ndef validate_token(token: str) -> bool:\n    return True\n"
        auth_path.write_text(content)

        new_ctx = analyzer.analyze_file(auth_path, tmp_project)

        changes = analyzer.compare_files(old_ctx, new_ctx)
        assert any(c["type"] == "function_added" and c["symbol"] == "validate_token" for c in changes)

    def test_compare_files_detect_deleted_function(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        old_ctx = analyzer.analyze_file(auth_path, tmp_project)

        # Remove create_token function
        content = auth_path.read_text()
        lines = content.split("\n")
        new_lines = []
        skip = False
        for line in lines:
            if "def create_token" in line:
                skip = True
                continue
            if skip and (line.startswith("def ") or line.startswith("class ")):
                skip = False
            if not skip:
                new_lines.append(line)
        auth_path.write_text("\n".join(new_lines))

        new_ctx = analyzer.analyze_file(auth_path, tmp_project)

        changes = analyzer.compare_files(old_ctx, new_ctx)
        assert any(c["type"] == "function_deleted" and c["symbol"] == "create_token" for c in changes)

    def test_invalid_python_file(self, analyzer, tmp_project):
        bad_file = tmp_project / "bad.py"
        bad_file.write_text("def broken(:\n    pass")

        ctx = analyzer.analyze_file(bad_file, tmp_project)
        assert ctx is None

    def test_relative_path(self, analyzer, tmp_project):
        auth_path = tmp_project / "auth.py"
        ctx = analyzer.analyze_file(auth_path, tmp_project)

        assert ctx is not None
        assert ctx.relative_path == "auth.py"

    def test_nested_file_path(self, analyzer, tmp_project):
        test_path = tmp_project / "tests" / "test_auth.py"
        ctx = analyzer.analyze_file(test_path, tmp_project)

        assert ctx is not None
        assert ctx.relative_path == "tests/test_auth.py"
