"""
AST Analyzer — Python Abstract Syntax Tree analysis.

Extracts structural information from Python files:
functions, classes, imports, decorators, docstrings.
Uses Python's built-in ast module for deterministic parsing.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from debug2learn.core.models import (
    FunctionInfo,
    ClassInfo,
    ImportInfo,
    FileContext,
    Language,
)


class ASTAnalyzer:
    """Analyzes Python files using the AST to extract structural info."""

    def analyze_source(self, source: str, file_path: str = "file.py", project_root: str = ".") -> FileContext | None:
        """Analyze source code string directly."""
        rel_path = file_path.replace("\\", "/")
        try:
            tree = ast.parse(source, filename=file_path)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            return None

        context = FileContext(
            path=file_path,
            relative_path=rel_path,
            language=Language.PYTHON,
            size_bytes=len(source.encode("utf-8")),
            is_test_file=self._is_test_file(rel_path),
            is_entry_point=self._is_entry_point(rel_path, source),
        )

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                context.functions.append(self._extract_function(node, rel_path))
            elif isinstance(node, ast.ClassDef):
                context.classes.append(self._extract_class(node, rel_path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    context.imports.append(ImportInfo(module=alias.name, names=[alias.asname or alias.name]))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names = [a.name for a in node.names]
                    context.imports.append(ImportInfo(module=node.module, names=names, is_from_import=True))

        return context

    def analyze_code(self, source: str, file_path: str = "file.py") -> dict[str, Any]:
        """Analyze source code string and return dict for Explorer."""
        fc = self.analyze_source(source, file_path)
        if fc is None:
            return {
                "functions": [],
                "classes": [],
                "imports": [],
                "is_test_file": False,
                "is_entry_point": False,
                "context": None,
            }
        return {
            "functions": fc.functions,
            "classes": fc.classes,
            "imports": fc.imports,
            "is_test_file": fc.is_test_file,
            "is_entry_point": fc.is_entry_point,
            "context": fc,
        }

    def analyze_file(self, file_path: Path, project_root: Path) -> FileContext | None:
        """
        Analyze a single Python file and return its structural context.
        
        Returns None if the file cannot be parsed.
        """
        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except (UnicodeDecodeError, OSError):
            return None

        try:
            relative = str(file_path.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            relative = file_path.name

        return self.analyze_source(source, relative)

    def _extract_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        file_path: str,
        class_name: str | None = None,
    ) -> FunctionInfo:
        """Extract function information from an AST node."""
        params = []
        for arg in node.args.args:
            if arg.arg != "self" and arg.arg != "cls":
                params.append(arg.arg)

        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(ast.dump(dec))
            elif isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name):
                decorators.append(dec.func.id)

        body_dump = ast.dump(node)
        body_hash = hashlib.md5(body_dump.encode("utf-8")).hexdigest()

        return FunctionInfo(
            name=node.name,
            file_path=file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            parameters=params,
            decorators=decorators,
            docstring=ast.get_docstring(node) or "",
            is_method=class_name is not None,
            class_name=class_name,
            body_hash=body_hash,
        )

    def _extract_class(self, node: ast.ClassDef, file_path: str) -> ClassInfo:
        """Extract class information from an AST node."""
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(f"{ast.dump(base)}")

        methods = []
        for item in node.body:
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                methods.append(item.name)

        return ClassInfo(
            name=node.name,
            file_path=file_path,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            bases=bases,
            methods=methods,
            docstring=ast.get_docstring(node) or "",
        )

    def _is_test_file(self, relative_path: str) -> bool:
        """Check if a file is likely a test file."""
        name = Path(relative_path).name.lower()
        parts = relative_path.lower().split("/")
        return (
            name.startswith("test_")
            or name.endswith("_test.py")
            or "tests" in parts
            or "test" in parts
        )

    def _is_entry_point(self, relative_path: str, source: str) -> bool:
        """Check if a file is likely an entry point."""
        name = Path(relative_path).name.lower()
        if name in ("main.py", "app.py", "manage.py", "wsgi.py", "asgi.py", "run.py"):
            return True
        if 'if __name__ == "__main__"' in source or "if __name__ == '__main__'" in source:
            return True
        return False

    def compare_files(
        self,
        old_context: FileContext | str | None,
        new_context: FileContext | str | None,
        file_path: str = "file.py",
    ) -> list[dict]:
        """
        Compare two FileContext snapshots or code strings and return a list of structural changes.
        """
        if isinstance(old_context, str):
            old_an = self.analyze_code(old_context, file_path)
            old_context = FileContext(
                path=file_path,
                relative_path=file_path,
                functions=old_an["functions"],
                classes=old_an["classes"],
                imports=old_an["imports"],
            )

        if isinstance(new_context, str):
            new_an = self.analyze_code(new_context, file_path)
            new_context = FileContext(
                path=file_path,
                relative_path=file_path,
                functions=new_an["functions"],
                classes=new_an["classes"],
                imports=new_an["imports"],
            )

        changes = []
        
        if old_context is None and new_context is not None:
            changes.append({
                "type": "file_added",
                "change_type": "file_added",
                "file": new_context.relative_path,
                "symbol": "",
                "description": f"File {new_context.relative_path} added",
            })
            return changes
        
        if old_context is not None and new_context is None:
            changes.append({
                "type": "file_deleted",
                "change_type": "file_deleted",
                "file": old_context.relative_path,
                "symbol": "",
                "description": f"File {old_context.relative_path} deleted",
            })
            return changes
        
        if old_context is None or new_context is None:
            return changes

        # Compare functions
        old_funcs = {f.name for f in old_context.functions}
        new_funcs = {f.name for f in new_context.functions}

        for name in new_funcs - old_funcs:
            changes.append({"type": "function_added", "change_type": "function_added", "symbol": name, "file": new_context.relative_path, "description": f"Function {name} added"})
        for name in old_funcs - new_funcs:
            changes.append({"type": "function_deleted", "change_type": "function_deleted", "symbol": name, "file": new_context.relative_path, "description": f"Function {name} deleted"})
        for name in old_funcs & new_funcs:
            old_f = next(f for f in old_context.functions if f.name == name)
            new_f = next(f for f in new_context.functions if f.name == name)
            is_modified = (
                old_f.parameters != new_f.parameters
                or (bool(old_f.body_hash) and bool(new_f.body_hash) and old_f.body_hash != new_f.body_hash)
                or (old_f.line_end - old_f.line_start != new_f.line_end - new_f.line_start)
            )
            if is_modified:
                changes.append({"type": "function_modified", "change_type": "function_modified", "symbol": name, "file": new_context.relative_path, "description": f"Function {name} modified"})

        # Compare classes
        old_classes = {c.name for c in old_context.classes}
        new_classes = {c.name for c in new_context.classes}

        for name in new_classes - old_classes:
            changes.append({"type": "class_added", "change_type": "class_added", "symbol": name, "file": new_context.relative_path, "description": f"Class {name} added"})
        for name in old_classes - new_classes:
            changes.append({"type": "class_deleted", "change_type": "class_deleted", "symbol": name, "file": new_context.relative_path, "description": f"Class {name} deleted"})
        for name in old_classes & new_classes:
            old_c = next(c for c in old_context.classes if c.name == name)
            new_c = next(c for c in new_context.classes if c.name == name)
            if old_c.methods != new_c.methods or old_c.bases != new_c.bases:
                changes.append({"type": "class_modified", "change_type": "class_modified", "symbol": name, "file": new_context.relative_path, "description": f"Class {name} modified"})

        # Compare imports
        old_imports = {(i.module, tuple(i.names)) for i in old_context.imports}
        new_imports = {(i.module, tuple(i.names)) for i in new_context.imports}

        for imp in new_imports - old_imports:
            changes.append({"type": "import_added", "change_type": "import_added", "symbol": imp[0], "file": new_context.relative_path, "description": f"Import {imp[0]} added"})
        for imp in old_imports - new_imports:
            changes.append({"type": "import_removed", "change_type": "import_removed", "symbol": imp[0], "file": new_context.relative_path, "description": f"Import {imp[0]} removed"})

        return changes
