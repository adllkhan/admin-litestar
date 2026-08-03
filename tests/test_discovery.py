"""``discover_specs`` behaviour, against throwaway packages built per test.

Every test builds a disposable package tree under ``tmp_path``, adds it to
``sys.path``, and removes both the path entry and every module it caused to
be imported afterwards — so no test's outcome depends on what an earlier
test happened to import.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from admin_litestar import ModelSpec
from admin_litestar.discovery import discover_specs

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture()
def package_root(tmp_path: Path) -> Iterator[Path]:
    """A directory on ``sys.path`` for one test's throwaway package tree.

    Restores ``sys.path`` and ``sys.modules`` on teardown, so a package this
    test caused to be imported cannot leak into a later test.
    """
    sys.path.insert(0, str(tmp_path))
    modules_before = set(sys.modules)
    try:
        yield tmp_path
    finally:
        sys.path.remove(str(tmp_path))
        for name in list(sys.modules):
            if name not in modules_before:
                del sys.modules[name]


def _specs_source(slug: str, table: str) -> str:
    """Source for a ``specs.py`` declaring one valid ``ModelSpec``."""
    return f'''\
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from admin_litestar import LIST, ModelSpec


class Base(DeclarativeBase):
    pass


class Thing(Base):
    __tablename__ = "{table}"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


SPECS = (
    ModelSpec(
        model=Thing,
        slug="{slug}",
        label="Things",
        group="G",
        list_columns=("id", "name"),
        detail_columns=("id", "name"),
        capabilities=frozenset({{LIST}}),
        order_by="id",
    ),
)
'''


def _write_package(
    root: Path, package_name: str, subpackages: dict[str, str | None]
) -> None:
    """Write a throwaway package with the given subpackages.

    Args:
        root: Directory already on ``sys.path``.
        package_name: Name of the top-level package to create.
        subpackages: Maps subpackage name to the source of its ``specs.py``,
            or ``None`` to create the subpackage without one.
    """
    package_dir = root / package_name
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    for name, source in subpackages.items():
        sub_dir = package_dir / name
        sub_dir.mkdir()
        (sub_dir / "__init__.py").write_text("")
        if source is not None:
            (sub_dir / "specs.py").write_text(source)


def test_collects_specs_from_multiple_subpackages_in_order(
    package_root: Path,
) -> None:
    """Specs from several subpackages come back sorted by subpackage name."""
    _write_package(
        package_root,
        "hostpkg",
        {
            "zeta": _specs_source(slug="zeta-thing", table="zeta_things"),
            "alpha": _specs_source(slug="alpha-thing", table="alpha_things"),
        },
    )

    specs = discover_specs("hostpkg")

    assert [spec.slug for spec in specs] == ["alpha-thing", "zeta-thing"]


def test_returns_a_tuple(package_root: Path) -> None:
    """The result is a tuple, not merely something tuple-like."""
    _write_package(
        package_root,
        "hostpkg",
        {"alpha": _specs_source(slug="alpha-thing", table="alpha_things")},
    )

    assert isinstance(discover_specs("hostpkg"), tuple)


def test_subpackage_without_specs_module_is_skipped(package_root: Path) -> None:
    """A domain module with no admin surface contributes nothing, silently."""
    _write_package(
        package_root,
        "hostpkg",
        {
            "alpha": _specs_source(slug="alpha-thing", table="alpha_things"),
            "quiet": None,
        },
    )

    specs = discover_specs("hostpkg")

    assert [spec.slug for spec in specs] == ["alpha-thing"]


def test_specs_module_without_attribute_raises_naming_module(
    package_root: Path,
) -> None:
    """A ``specs.py`` that forgot ``SPECS`` fails loudly, naming the module."""
    _write_package(package_root, "hostpkg", {"alpha": "NOT_SPECS = ()\n"})

    with pytest.raises(AttributeError, match="hostpkg.alpha.specs") as excinfo:
        discover_specs("hostpkg")
    assert "SPECS" in str(excinfo.value)


def test_specs_attribute_not_iterable_of_specs_raises(package_root: Path) -> None:
    """A ``SPECS`` that isn't specs fails, naming the module and the culprit."""
    _write_package(package_root, "hostpkg", {"alpha": "SPECS = 42\n"})

    with pytest.raises(TypeError, match="hostpkg.alpha.specs"):
        discover_specs("hostpkg")


def test_specs_attribute_containing_non_modelspec_elements_raises(
    package_root: Path,
) -> None:
    """A ``SPECS`` list whose elements are not ``ModelSpec`` fails."""
    _write_package(package_root, "hostpkg", {"alpha": 'SPECS = ["not-a-spec"]\n'})

    with pytest.raises(TypeError, match="hostpkg.alpha.specs"):
        discover_specs("hostpkg")


def test_duplicate_slugs_across_modules_raise_naming_both(
    package_root: Path,
) -> None:
    """A slug collision is caught at discovery, naming both modules."""
    _write_package(
        package_root,
        "hostpkg",
        {
            "alpha": _specs_source(slug="dup", table="alpha_things"),
            "beta": _specs_source(slug="dup", table="beta_things"),
        },
    )

    with pytest.raises(ValueError, match="dup") as excinfo:
        discover_specs("hostpkg")
    message = str(excinfo.value)
    assert "hostpkg.alpha.specs" in message
    assert "hostpkg.beta.specs" in message


def test_custom_module_name_and_attribute_are_honoured(package_root: Path) -> None:
    """A host may rename the module and the attribute it looks for."""
    source = _specs_source(slug="alpha-thing", table="alpha_things").replace(
        "SPECS =", "ADMIN_SPECS ="
    )
    package_dir = package_root / "hostpkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("")
    sub_dir = package_dir / "alpha"
    sub_dir.mkdir()
    (sub_dir / "__init__.py").write_text("")
    (sub_dir / "admin.py").write_text(source)

    specs = discover_specs("hostpkg", module_name="admin", attribute="ADMIN_SPECS")

    assert [spec.slug for spec in specs] == ["alpha-thing"]


def test_declaration_order_is_preserved_within_a_module(package_root: Path) -> None:
    """Multiple specs in one module keep their declared order."""
    source = '''\
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from admin_litestar import LIST, ModelSpec


class Base(DeclarativeBase):
    pass


class ThingOne(Base):
    __tablename__ = "thing_one"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


class ThingTwo(Base):
    __tablename__ = "thing_two"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))


def _spec(model, slug):
    return ModelSpec(
        model=model,
        slug=slug,
        label="Things",
        group="G",
        list_columns=("id", "name"),
        detail_columns=("id", "name"),
        capabilities=frozenset({LIST}),
        order_by="id",
    )


SPECS = (_spec(ThingTwo, "second"), _spec(ThingOne, "first"))
'''
    _write_package(package_root, "hostpkg", {"alpha": source})

    specs = discover_specs("hostpkg")

    assert [spec.slug for spec in specs] == ["second", "first"]
    assert all(isinstance(spec, ModelSpec) for spec in specs)
