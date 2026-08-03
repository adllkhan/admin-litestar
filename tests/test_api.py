"""The public API surface, pinned.

A library's exports are its compatibility promise, so this file states them
explicitly. A new name appearing here is a deliberate act; one disappearing is a
breaking change. Both should be visible in a diff rather than discovered by a
consumer.
"""

from __future__ import annotations

import admin_litestar as al

EXPECTED_SURFACE = {
    # Assembly
    "Admin",
    "AdminConfig",
    "CustomPage",
    # Declaration
    "ModelSpec",
    "discover_specs",
    "CAPABILITIES",
    "LIST",
    "DETAIL",
    "DELETE",
    "EXPORT",
    # Protocols a host implements
    "AuthBackend",
    "AuditSink",
    "CacheBackend",
    # Helpers a host's own pages need
    "actor_of",
    "is_htmx",
    "project",
    "render_value",
    "csv_rows",
    "list_statement",
    "detail_statement",
    "count_statement",
    # Password handling for an AuthBackend implementation
    "hash_password",
    "verify_password",
    # Metadata
    "__version__",
}

INTERNALS = {"Registry", "Revalidator", "require_actor"}


def test_surface_is_exactly_as_documented() -> None:
    """Adding or removing an export is a decision, not an accident."""
    assert set(al.__all__) == EXPECTED_SURFACE


def test_every_export_resolves() -> None:
    """An export naming something absent would fail only on a consumer's import."""
    missing = [name for name in al.__all__ if not hasattr(al, name)]
    assert not missing


def test_all_is_sorted() -> None:
    """Sorted so a diff shows an addition in one place, not two."""
    assert al.__all__ == sorted(al.__all__)


def test_internals_are_not_exported() -> None:
    """Admin builds and wires these; exporting them would promise compatibility.

    They remain importable from their own modules for the package's own use and
    for anyone who accepts that deeper paths carry no promise.
    """
    assert not INTERNALS & set(al.__all__)


def test_version_is_a_real_version() -> None:
    """Consumers and bug reports need the installed version at runtime."""
    assert isinstance(al.__version__, str)
    assert al.__version__.split(".")[0].isdigit()


def test_version_matches_the_distribution_metadata() -> None:
    """The runtime version must not drift from what was installed."""
    from importlib.metadata import version

    assert al.__version__ == version("admin-litestar")


def test_capability_constants_are_the_complete_set() -> None:
    """The exported names and the validated set cannot disagree."""
    assert al.CAPABILITIES == frozenset({al.LIST, al.DETAIL, al.DELETE, al.EXPORT})
