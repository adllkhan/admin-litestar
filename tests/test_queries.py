"""Query builders: the hidden/excluded column boundary and pagination."""

import datetime
from dataclasses import replace

import pytest
from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from admin_litestar.queries import (
    count_statement,
    facet_counts,
    detail_statement,
    list_statement,
    primary_key,
    sort_column,
)

from .models import CompositeKeyModel
from .test_spec import SECRET, WIDGET


def _sql(statement: Select) -> str:
    """Render a statement as PostgreSQL text for assertions."""
    return str(statement.compile(dialect=postgresql.dialect()))


def test_list_statement_omits_hidden_columns() -> None:
    """Hidden columns are never loaded by a list query."""
    assert "_blob_data" not in _sql(list_statement(WIDGET))


def test_detail_statement_includes_hidden_columns() -> None:
    """Detail views deliberately load hidden columns."""
    assert "_blob_data" in _sql(detail_statement(WIDGET, 1))


def test_excluded_columns_appear_in_no_statement() -> None:
    """An excluded column is absent from list, detail and count queries."""
    for sql in (
        _sql(list_statement(SECRET)),
        _sql(detail_statement(SECRET, 1)),
    ):
        assert "token" not in sql
    # Count statement must not reference any entity columns.
    count_sql = _sql(count_statement(SECRET))
    assert "count(" in count_sql.lower()
    assert "secret." not in count_sql


def test_list_statement_orders_and_limits() -> None:
    """Listing is bounded and deterministically ordered."""
    sql = _sql(list_statement(WIDGET))
    assert "ORDER BY" in sql
    assert "LIMIT" in sql


def test_search_uses_ilike_on_searchable_columns() -> None:
    """A term matches searchable columns case-insensitively."""
    spec = replace(WIDGET, searchable=("name",))
    sql = _sql(list_statement(spec, search="thing"))
    assert "ILIKE" in sql.upper()
    assert "name" in sql


def test_exact_search_uses_equality_and_the_transform() -> None:
    """An exact-search column matches by equality on the transformed term."""
    calls: list[str] = []

    def _digest(term: str) -> str:
        calls.append(term)
        return f"xx{term}"

    spec = replace(
        WIDGET, exact_searchable=("digest",), search_transform=_digest
    )
    sql = _sql(list_statement(spec, search="12345"))
    assert "digest" in sql
    assert "ILIKE" not in sql.upper()
    assert calls == ["12345"]


def test_keyset_pagination_uses_a_cursor_not_offset() -> None:
    """Paging narrows the query rather than skipping rows."""
    sql = _sql(list_statement(WIDGET, after="500"))
    assert "OFFSET" not in sql.upper()
    assert "id <" in sql


def test_filters_are_restricted_to_declared_columns() -> None:
    """An undeclared filter key is ignored rather than injected."""
    spec = replace(WIDGET, filters=("kind",))
    sql = _sql(list_statement(spec, filters={"kind": "a", "name": "b"}))
    assert "kind" in sql
    assert "name =" not in sql


def test_exact_search_wins_over_fuzzy() -> None:
    """When both are declared, exact search takes precedence."""
    spec = replace(
        WIDGET,
        searchable=("name",),
        exact_searchable=("digest",),
        search_transform=lambda x: f"xx{x}",
    )
    sql = _sql(list_statement(spec, search="12345"))
    assert "digest" in sql
    assert "ILIKE" not in sql.upper()


def test_count_statement_is_a_count() -> None:
    """Counting does not select entity columns."""
    assert "count(" in _sql(count_statement(WIDGET)).lower()


def test_primary_key_rejects_composite_keys() -> None:
    """Composite primary keys are not supported."""
    with pytest.raises(ValueError, match="composite"):
        primary_key(CompositeKeyModel)


def test_keyset_cursor_coerces_to_column_type() -> None:
    """Integer cursors are bound as integers, not strings."""
    statement = list_statement(WIDGET, after="500")
    compiled = statement.compile()
    # Check that the parameter bound is an integer (500), not a string.
    assert any(v == 500 for v in compiled.params.values())


def test_malformed_keyset_cursor_is_ignored() -> None:
    """An unparseable cursor is silently ignored."""
    sql = _sql(list_statement(WIDGET, after="abc"))
    assert "id <" not in sql


def test_datetime_ordered_spec_with_iso_cursor() -> None:
    """DateTime cursors are parsed with fromisoformat and bound as datetime."""
    spec = replace(WIDGET, order_by="created_at")
    statement = list_statement(spec, after="2026-07-29T09:14:00+00:00")
    compiled = statement.compile()
    # Check that a datetime parameter is bound, not a string.
    assert any(isinstance(v, datetime.datetime) for v in compiled.params.values())


def test_datetime_ordered_spec_with_nonsense_cursor() -> None:
    """A malformed datetime cursor is silently ignored."""
    spec = replace(WIDGET, order_by="created_at")
    sql = _sql(list_statement(spec, after="not-a-timestamp"))
    assert "created_at <" not in sql


def test_detail_statement_coerces_a_string_pk_to_the_column_type() -> None:
    """A URL-supplied string pk is bound as the column's own type.

    ``{pk:str}`` on the generic detail and delete routes means a real
    request always hands this function a ``str``, even for an integer
    primary key. PostgreSQL via asyncpg refuses an implicit
    ``bigint = character varying`` comparison, so binding the pk as the
    literal string it arrived as would 500 against a real database even
    though the id plainly matches a row — this is what makes that work.
    """
    statement = detail_statement(WIDGET, "500")
    compiled = statement.compile()
    assert any(v == 500 and isinstance(v, int) for v in compiled.params.values())


def test_detail_statement_passes_through_an_uncoercible_pk() -> None:
    """A pk that cannot become the column's type is passed through as-is.

    It cannot match any row of an integer-keyed table either way; passing
    it through unchanged (rather than raising) leaves that to the query
    returning no rows, the same as any other lookup miss.
    """
    statement = detail_statement(WIDGET, "not-a-number")
    compiled = statement.compile()
    assert "not-a-number" in compiled.params.values()


def test_naive_datetime_cursor_against_aware_column_is_ignored() -> None:
    """A cursor with no UTC offset must not reach a tz-aware column.

    Binding a naive datetime against ``DateTime(timezone=True)`` mismatches
    at the driver level, so it is treated as an absent cursor instead.
    """
    spec = replace(WIDGET, order_by="created_at")
    sql = _sql(list_statement(spec, after="2026-07-29T09:14:00"))
    assert "created_at <" not in sql


def test_the_sort_column_is_checked_against_the_list() -> None:
    """A sort arrives from a URL, so it is validated rather than trusted."""
    assert sort_column(WIDGET, "name") == "name"
    # not a list column, not a column at all, and absent: all fall back
    assert sort_column(WIDGET, "_blob_data") == WIDGET.order_by
    assert sort_column(WIDGET, "nonsense") == WIDGET.order_by
    assert sort_column(WIDGET, None) == WIDGET.order_by


def test_sorting_orders_by_the_requested_column() -> None:
    """The requested column drives the ORDER BY."""
    statement = str(list_statement(WIDGET, sort="name"))
    assert "ORDER BY widget.name DESC" in statement


def test_an_ascending_sort_pages_forwards_not_backwards() -> None:
    """The keyset comparison has to follow the direction of the order.

    With ``<`` hardcoded, an ascending sort would page away from the rows it had
    just shown and repeat the first page forever.
    """
    descending = str(list_statement(WIDGET, sort="name", after="m"))
    ascending = str(
        list_statement(WIDGET, sort="name", descending=False, after="m")
    )
    assert "widget.name <" in descending
    assert "ORDER BY widget.name ASC" in ascending
    assert "widget.name >" in ascending


def test_the_order_is_tie_broken_by_the_primary_key() -> None:
    """Keyset paging over a non-unique sort needs a stable total order.

    Sorting by a column with repeated values leaves rows within a value ordered
    arbitrarily, and a cursor over an unstable order both skips and repeats rows.
    """
    statement = str(list_statement(WIDGET, sort="kind"))
    assert "ORDER BY widget.kind DESC, widget.id DESC" in statement


def test_facet_counts_are_taken_against_the_rest_of_the_view() -> None:
    """A count has to say what clicking that value would give you.

    Counted over the whole table it would promise rows the current search does not
    contain; counted with its own filter applied, every value but the active one
    would read zero. So the search and the *other* filters are applied, and the
    column's own filter is not.
    """
    spec = replace(WIDGET, searchable=("name",), filters=("kind", "created_at"))
    statement = str(
        facet_counts(
            spec, "kind", search="one",
            filters={"kind": "alpha", "created_at": "2026-08-04"},
        )
    )
    assert "GROUP BY widget.kind" in statement
    # the search reaches the count
    assert "LIKE" in statement.upper()
    # so does the other filter, while the column's own filter does not
    assert "widget.created_at =" in statement
    assert "widget.kind =" not in statement


def test_facet_counts_keep_a_stable_order() -> None:
    """Segments that reorder as data changes are a control you cannot learn."""
    statement = str(facet_counts(replace(WIDGET, filters=("kind",)), "kind"))
    assert "ORDER BY widget.kind ASC" in statement
    assert "ORDER BY count" not in statement


def test_several_values_for_one_filter_widen_it() -> None:
    """Asking for paid and pending means either, which is IN, not a contradiction."""
    spec = replace(WIDGET, filters=("kind",))
    one = _sql(list_statement(spec, filters={"kind": ("alpha",)}))
    many = _sql(list_statement(spec, filters={"kind": ("alpha", "beta")}))
    assert "widget.kind = " in one and "IN" not in one
    assert "IN" in many


def test_an_empty_selection_filters_nothing() -> None:
    """A filter cleared to an empty set is not a filter for nothing."""
    spec = replace(WIDGET, filters=("kind",))
    # asserted on the clause, not on the name: the column is in the SELECT either way
    assert "WHERE" not in _sql(list_statement(spec, filters={"kind": ()}))


def test_a_date_range_bounds_the_column_at_both_ends() -> None:
    """Between two dates, with either end optional."""
    from admin_litestar.filters import Range

    spec = replace(WIDGET, filters=("created_at",))
    both = _sql(list_statement(spec, ranges={"created_at": Range("2026-01-01", "2026-08-04")}))
    assert "created_at >=" in both
    assert "created_at <" in both
    open_ended = _sql(list_statement(spec, ranges={"created_at": Range("2026-01-01", "")}))
    assert "created_at >=" in open_ended
    assert "created_at <" not in open_ended


def test_a_date_end_covers_the_whole_day_it_names() -> None:
    """"To 4 August" on a timestamp column has to include 4 August.

    Compared as ``<= midnight`` it would exclude every row in that day, which
    reads as data missing rather than as a boundary being off by a day.
    """
    from admin_litestar.filters import Range

    spec = replace(WIDGET, filters=("created_at",))
    day = _sql(list_statement(spec, ranges={"created_at": Range("", "2026-08-04")}))
    instant = _sql(list_statement(spec, ranges={"created_at": Range("", "2026-08-04T12:00")}))
    # a day is bounded exclusively at the start of the next one
    assert "created_at <" in day and "created_at <=" not in day
    # an instant is bounded inclusively at itself
    assert "created_at <=" in instant


def test_a_malformed_bound_is_ignored_rather_than_raising() -> None:
    """Bounds arrive from URLs, and URLs get edited."""
    from admin_litestar.filters import Range

    spec = replace(WIDGET, filters=("created_at",))
    assert "WHERE" not in _sql(
        list_statement(spec, ranges={"created_at": Range("yesterday", "")})
    )
