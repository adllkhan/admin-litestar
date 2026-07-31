"""The package may import only its declared dependencies and the standard library.

This is the guarantee the package exists to keep. It is a reusable admin, so it
must never reach into the application that hosts it — and the way to enforce that
without naming any particular host is to allow only what is declared and reject
everything else. An allowlist also catches an undeclared third-party dependency,
which a denylist of known-bad names never could.

The scan parses each module with ``ast`` rather than matching text. That removes a
whole class of evasion and false positive at once: multi-line and parenthesised
imports, ``import a, b`` on one line, ``import a;b()``, aliases, and forbidden
names appearing inside comments or docstrings.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import admin_litestar

DECLARED = frozenset({"litestar", "sqlalchemy", "jinja2"})
SELF = "admin_litestar"
ALLOWED = DECLARED | {SELF} | frozenset(sys.stdlib_module_names)

SOURCE_ROOT = Path(admin_litestar.__file__).resolve().parent
DYNAMIC_IMPORT = "import_module"
MINIMUM_SOURCES = 5


def _sources() -> list[Path]:
    """Every Python source file in the package."""
    return sorted(SOURCE_ROOT.rglob("*.py"))


def _root_packages(tree: ast.AST) -> set[str]:
    """Return the top-level package of every absolute import in a module.

    Relative imports are omitted: they can only reach inside this package, so
    they are internal by construction and never a boundary violation.
    """
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _dynamic_imports(tree: ast.AST) -> set[str]:
    """Return package roots passed to ``import_module`` as string literals.

    A static import scan cannot see ``import_module("something.else")``, so this
    catches the obvious dynamic form. A computed argument would still evade it;
    the package has no legitimate reason to build an import target at runtime, so
    :func:`test_no_dynamic_imports_at_all` forbids the call outright instead.
    """
    targets: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name != DYNAMIC_IMPORT:
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                targets.add(argument.value.split(".")[0])
    return targets


def test_sources_exist() -> None:
    """Guard against every scan below passing because it found no files."""
    assert len(_sources()) >= MINIMUM_SOURCES


def test_only_declared_and_stdlib_imports() -> None:
    """Anything outside the allowlist is either a host reach-in or undeclared."""
    offenders: list[str] = []
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for root in sorted(_root_packages(tree) | _dynamic_imports(tree)):
            if root not in ALLOWED:
                offenders.append(f"{path.name}: {root}")
    assert not offenders, "imports outside the allowlist:\n" + "\n".join(offenders)


def test_no_dynamic_imports_at_all() -> None:
    """``import_module`` has no legitimate use here and would bypass the scan."""
    offenders = [
        path.name
        for path in _sources()
        if DYNAMIC_IMPORT in path.read_text()
    ]
    assert not offenders, f"dynamic import machinery found in: {offenders}"


def test_scan_detects_a_foreign_import() -> None:
    """The allowlist rejects an import from an application package."""
    tree = ast.parse("from some_host_app.models import User")
    assert _root_packages(tree) == {"some_host_app"}
    assert not _root_packages(tree) <= ALLOWED


def test_scan_detects_every_import_form() -> None:
    """Aliases, multi-imports, submodules and continuations are all seen."""
    source = (
        "import host_a\n"
        "import host_b.sub as alias\n"
        "import host_c, host_d\n"
        "from host_e.deep import Thing\n"
        "from host_f import (\n    One,\n    Two,\n)\n"
    )
    assert _root_packages(ast.parse(source)) == {
        "host_a",
        "host_b",
        "host_c",
        "host_d",
        "host_e",
        "host_f",
    }


def test_scan_ignores_relative_imports() -> None:
    """Relative imports stay inside the package and are not violations."""
    source = "from . import constants\nfrom .spec import ModelSpec\n"
    assert _root_packages(ast.parse(source)) == set()


def test_scan_ignores_names_in_comments_and_docstrings() -> None:
    """Prose mentioning a package is not an import — ast sees no such thing."""
    source = (
        '"""Docstring naming host_app and import_module(\'host_app.x\')."""\n'
        "# import host_app\n"
        "import json\n"
    )
    assert _root_packages(ast.parse(source)) == {"json"}


def test_scan_detects_dynamic_import_targets() -> None:
    """A string literal passed to import_module is resolved to its root."""
    source = "from importlib import import_module\nimport_module('host_app.models')\n"
    assert _dynamic_imports(ast.parse(source)) == {"host_app"}


def test_similar_names_are_not_confused_for_allowed_ones() -> None:
    """A package merely prefixed like a dependency is still outside the list."""
    tree = ast.parse("import litestar_extras\nimport sqlalchemy_utils\n")
    assert not _root_packages(tree) <= ALLOWED


def test_declared_dependencies_stay_minimal() -> None:
    """The dependency list is this boundary in machine-readable form."""
    manifest = (SOURCE_ROOT.parents[1] / "pyproject.toml").read_text()
    body = manifest.split("dependencies = [", 1)[1].split("]", 1)[0]
    declared = {
        line.strip().strip('",').split(">=")[0]
        for line in body.splitlines()
        if line.strip().startswith('"')
    }
    assert declared == set(DECLARED)
