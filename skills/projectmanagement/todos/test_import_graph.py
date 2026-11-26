"""The layer graph of the todo tools, read from the modules' own import statements.

Calls go inward only: arg parse and policy (the front ends) over local core over
common core. A module's imports are its calls into other layers, so the graph
is checked on imports. See IMPLEMENTATION.md, "Code layout: layers and front
ends".
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import List, Set

import pytest

pytestmark = pytest.mark.integration

HERE = Path(__file__).resolve().parent

COMMON_CORE = (
    "todo_common",
    "todo_store",
    "todo_db",
    "todo_objid",
    "todo_ref",
    "todo_url",
    "todo_search",
    "todo_embed",
    "todo_embed_apple",
    "git_command",
)
TODO_LOCAL_CORE = ("todo_ops",)
FRONT_END_MODULES = ("todo", "todo_web", "todoweb", "todoweb_core")


def _tree(module: str) -> ast.Module:
    return ast.parse((HERE / f"{module}.py").read_text(encoding="utf-8"))


def imported_modules(module: str) -> Set[str]:
    """Top-level names of every module *module* imports, at any depth in the file."""
    found: Set[str] = set()
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module.split(".")[0])
    return found


def stdout_writes(module: str) -> List[int]:
    """Lines of *module* that print without a ``file=`` or touch ``sys.stdout``/``sys.exit``."""
    lines: List[int] = []
    for node in ast.walk(_tree(module)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "print" and not any(
                k.arg == "file" for k in node.keywords
            ):
                lines.append(node.lineno)
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr in ("stdout", "exit")
        ):
            lines.append(node.lineno)
    return sorted(lines)


class CommonCoreTest(unittest.TestCase):
    """Common core calls nothing above it."""

    def test_common_core_imports_no_front_end_and_no_local_core(self) -> None:
        """No common-core module imports a front end or a local core."""
        above = set(FRONT_END_MODULES) | set(TODO_LOCAL_CORE)
        for module in COMMON_CORE:
            with self.subTest(module=module):
                self.assertEqual(imported_modules(module) & above, set())


class TodoLocalCoreTest(unittest.TestCase):
    """todo's local core calls only inward and carries no CLI concerns."""

    def test_local_core_imports_no_front_end(self) -> None:
        """todo_ops imports no front end."""
        for module in TODO_LOCAL_CORE:
            with self.subTest(module=module):
                self.assertEqual(
                    imported_modules(module) & set(FRONT_END_MODULES), set()
                )

    def test_local_core_has_no_argparse_stdout_or_exit(self) -> None:
        """todo_ops neither parses arguments, nor writes stdout, nor exits."""
        for module in TODO_LOCAL_CORE:
            with self.subTest(module=module):
                self.assertNotIn("argparse", imported_modules(module))
                self.assertEqual(stdout_writes(module), [])


if __name__ == "__main__":
    unittest.main()
