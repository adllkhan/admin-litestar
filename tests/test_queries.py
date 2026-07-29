"""Query builders: the hidden/excluded column boundary and pagination."""

from dataclasses import replace

from sqlalchemy import Select
from sqlalchemy.dialects import postgresql

from litestar_admin.queries import count_statement, detail_statement, list_statement

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
        _sql(count_statement(SECRET)),
    ):
        assert "token" not in sql


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


def test_count_statement_is_a_count() -> None:
    """Counting does not select entity columns."""
    assert "count(" in _sql(count_statement(WIDGET)).lower()
