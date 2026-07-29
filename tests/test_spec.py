"""ModelSpec and Registry behaviour."""

import pytest

from litestar_admin import ModelSpec, Registry
from litestar_admin.constants import DETAIL, LIST

from .models import Secret, Widget

WIDGET = ModelSpec(
    model=Widget,
    slug="widget",
    label="Widgets",
    group="Things",
    list_columns=("id", "name", "kind", "created_at"),
    detail_columns=("id", "name", "kind", "_blob_data", "created_at"),
    hidden_columns=("_blob_data",),
    capabilities=frozenset({LIST, DETAIL}),
    order_by="id",
)
SECRET = ModelSpec(
    model=Secret,
    slug="secret",
    label="Secrets",
    group="Other",
    list_columns=("id", "created_at"),
    detail_columns=("id", "created_at"),
    excluded_columns=("token",),
    capabilities=frozenset({LIST}),
    order_by="id",
)


def test_registry_lookup_by_slug() -> None:
    """A registered spec is retrievable by its slug."""
    assert Registry([WIDGET, SECRET]).get("widget") is WIDGET


def test_unknown_slug_raises() -> None:
    """An unknown slug is a KeyError, not a silent None."""
    with pytest.raises(KeyError):
        Registry([WIDGET]).get("nope")


def test_duplicate_slugs_rejected_at_construction() -> None:
    """Slugs address models in URLs, so a collision must fail loudly."""
    with pytest.raises(ValueError, match="duplicate"):
        Registry([WIDGET, WIDGET])


def test_groups_preserve_declaration_order_without_duplicates() -> None:
    """Nav grouping follows the order specs were registered."""
    assert Registry([WIDGET, SECRET]).groups == ("Things", "Other")


def test_hidden_columns_may_not_appear_in_list_columns() -> None:
    """A hidden column in list_columns would defeat the whole boundary."""
    with pytest.raises(ValueError, match="hidden"):
        ModelSpec(
            model=Widget,
            slug="bad",
            label="Bad",
            group="G",
            list_columns=("id", "_blob_data"),
            detail_columns=("id",),
            hidden_columns=("_blob_data",),
            capabilities=frozenset({LIST}),
            order_by="id",
        )


def test_excluded_columns_may_not_appear_anywhere() -> None:
    """An excluded column is never selected, so declaring it is a contradiction."""
    with pytest.raises(ValueError, match="excluded"):
        ModelSpec(
            model=Secret,
            slug="bad",
            label="Bad",
            group="G",
            list_columns=("id",),
            detail_columns=("id", "token"),
            excluded_columns=("token",),
            capabilities=frozenset({LIST}),
            order_by="id",
        )


def test_order_by_must_be_a_real_column() -> None:
    """A typo in order_by should fail at import, not at first request."""
    with pytest.raises(ValueError, match="order_by"):
        ModelSpec(
            model=Widget,
            slug="bad",
            label="Bad",
            group="G",
            list_columns=("id",),
            detail_columns=("id",),
            capabilities=frozenset({LIST}),
            order_by="nonexistent",
        )


def test_searchable_may_not_include_excluded_columns() -> None:
    """A searchable column cannot be excluded."""
    with pytest.raises(ValueError, match="excluded"):
        ModelSpec(
            model=Secret,
            slug="bad",
            label="Bad",
            group="G",
            list_columns=("id",),
            detail_columns=("id",),
            excluded_columns=("token",),
            searchable=("token",),
            capabilities=frozenset({LIST}),
            order_by="id",
        )


def test_filters_must_be_real_columns() -> None:
    """A filter must be a real column."""
    with pytest.raises(ValueError, match="unknown"):
        ModelSpec(
            model=Widget,
            slug="bad",
            label="Bad",
            group="G",
            list_columns=("id",),
            detail_columns=("id",),
            capabilities=frozenset({LIST}),
            order_by="id",
            filters=("nonexistent",),
        )
