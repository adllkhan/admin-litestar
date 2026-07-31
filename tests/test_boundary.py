"""The package must not depend on any host application."""

import re
from pathlib import Path

import litestar_admin

FORBIDDEN = ("pgo_auth", "core", "modules", "infrastructure", "app")
SOURCE_ROOT = Path(litestar_admin.__file__).resolve().parent

_IMPORT_RE = re.compile(
    r"^(?:import|from)\s+(" + "|".join(FORBIDDEN) + r")(?:\.|\s|,|;|$)"
)


def _sources() -> list[Path]:
    """Every Python source file in the package."""
    return sorted(SOURCE_ROOT.rglob("*.py"))


def test_sources_exist() -> None:
    """Guard against the scan passing because it found nothing."""
    assert len(_sources()) >= 5


def test_no_host_application_imports() -> None:
    """A host import here would defeat the entire point of the package."""
    offenders: list[str] = []
    for path in _sources():
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if _IMPORT_RE.match(stripped):
                offenders.append(f"{path.name}:{number}: {stripped}")
            if stripped.startswith("#"):
                # A comment mentioning import_module cannot execute, so it is
                # not an evasion of the boundary — skip it to avoid flagging
                # prose. Docstring bodies are not excluded: doing so cheaply
                # would need an AST walk, so a docstring naming a forbidden
                # package in an import_module(...) call would still be
                # flagged. That residual false-positive risk is accepted.
                continue
            if "import_module(" in stripped:
                if any(pkg in stripped for pkg in FORBIDDEN):
                    offenders.append(f"{path.name}:{number}: {stripped}")
    assert not offenders, "host imports found:\n" + "\n".join(offenders)


def test_boundary_catches_bare_package_imports() -> None:
    """The regex catches 'import core', 'from core import X', etc."""
    test_cases = [
        ("import core", True),
        ("from core import Something", True),
        ("import modules", True),
        ("from modules import X", True),
        ("import app", True),
        ("from app import Y", True),
        ("import infrastructure", True),
        ("from infrastructure import Z", True),
    ]
    for line, should_match in test_cases:
        assert bool(_IMPORT_RE.match(line)) == should_match, f"Failed on: {line}"


def test_boundary_catches_comma_and_semicolon_separators() -> None:
    """A multi-import or statement-separated line cannot evade the scan."""
    test_cases = [
        ("import core, sys", True),
        ("import core;x=1", True),
    ]
    for line, should_match in test_cases:
        assert bool(_IMPORT_RE.match(line)) == should_match, f"Failed on: {line}"


def test_boundary_catches_submodule_imports() -> None:
    """The regex catches 'from core.models import X', etc."""
    test_cases = [
        ("from core.models import Something", True),
        ("import core.models", True),
        ("from modules.calls import X", True),
        ("import app.main", True),
    ]
    for line, should_match in test_cases:
        assert bool(_IMPORT_RE.match(line)) == should_match, f"Failed on: {line}"


def test_boundary_does_not_false_positive() -> None:
    """The regex does not catch similar but different names."""
    test_cases = [
        ("import coreutils", False),
        ("from apples import X", False),
        ("import infrastructure_code", False),
        ("from app_config import Y", False),
    ]
    for line, should_match in test_cases:
        assert bool(_IMPORT_RE.match(line)) == should_match, f"Failed on: {line}"


def test_declared_dependencies_stay_minimal() -> None:
    """The dependency list is the boundary in machine-readable form."""
    manifest = (SOURCE_ROOT.parents[1] / "pyproject.toml").read_text()
    body = manifest.split("dependencies = [", 1)[1].split("]", 1)[0]
    declared = {
        line.strip().strip('",').split(">=")[0]
        for line in body.splitlines()
        if line.strip().startswith('"')
    }
    assert declared == {"litestar", "sqlalchemy", "jinja2"}
