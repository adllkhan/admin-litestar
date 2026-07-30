"""The package must not depend on any host application."""

from pathlib import Path

import litestar_admin

FORBIDDEN = ("pgo_auth", "core.", "modules.", "infrastructure.", "app.")
SOURCE_ROOT = Path(litestar_admin.__file__).resolve().parent


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
            if not stripped.startswith(("import ", "from ")):
                continue
            if any(token in stripped for token in FORBIDDEN):
                offenders.append(f"{path.name}:{number}: {stripped}")
    assert not offenders, "host imports found:\n" + "\n".join(offenders)


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
