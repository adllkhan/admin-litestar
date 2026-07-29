"""Statement builders — the single place the column boundary is enforced."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import load_only

from .constants import PAGE_SIZE

if TYPE_CHECKING:
    from sqlalchemy import Select

    from .spec import ModelSpec


def primary_key(model: type) -> Any:
    """Return the single primary-key column of a model.

    Raises:
        ValueError: If the model has a composite primary key.
    """
    pk_columns = list(model.__table__.primary_key.columns)
    if len(pk_columns) != 1:
        raise ValueError(
            f"{model.__name__} has a composite primary key; single keys only"
        )
    return pk_columns[0]


def _attributes(model: type, names: tuple[str, ...]) -> list[Any]:
    """Return mapped attributes for ``names`` on ``model``."""
    return [getattr(model, name) for name in names]


def _search_clause(spec: ModelSpec, term: str) -> Any:
    """Build the clause matching ``term``, preferring exact over fuzzy.

    Exact matching wins when the spec declares exact-searchable columns and a
    transform is available, because a keyed digest cannot be matched partially.
    """
    if spec.exact_searchable:
        needle = spec.search_transform(term) if spec.search_transform else term
        clauses = [
            getattr(spec.model, name) == needle for name in spec.exact_searchable
        ]
        return or_(*clauses)
    if not spec.searchable:
        return None
    return or_(
        *(getattr(spec.model, name).ilike(f"%{term}%") for name in spec.searchable)
    )


def _coerce_cursor(order_column: Any, cursor: str) -> Any:
    """Coerce a keyset cursor string to the order column's Python type.

    Args:
        order_column: The SQLAlchemy column to read the Python type from.
        cursor: A string cursor value, typically from a URL query parameter.

    Returns:
        The cursor coerced to the column's Python type, or None if coercion
        fails (treating a malformed cursor as absent rather than raising).
    """
    # Try to read the Python type, falling back to the string if the type
    # does not expose it (JSON, ARRAY, and similar custom types).
    try:
        python_type = order_column.type.python_type
    except NotImplementedError:
        # Type does not describe itself; pass through unchanged.
        return cursor

    # String columns do not need coercion.
    if python_type is str:
        return cursor

    # For datetime types, use fromisoformat (the correct constructor for
    # a value round-tripped through a URL).
    if python_type is datetime.datetime:
        try:
            return datetime.datetime.fromisoformat(cursor)
        except (ValueError, TypeError):
            return None

    if python_type is datetime.date:
        try:
            return datetime.date.fromisoformat(cursor)
        except (ValueError, TypeError):
            return None

    # For other types, call the type constructor.
    try:
        return python_type(cursor)
    except (ValueError, TypeError):
        return None


def list_statement(
    spec: ModelSpec,
    *,
    search: str | None = None,
    filters: dict[str, Any] | None = None,
    after: str | None = None,
    limit: int = PAGE_SIZE,
) -> Select:
    """Build the list query, loading only the spec's list columns.

    Args:
        spec: The model spec being listed.
        search: Free-text term, applied per :func:`_search_clause`.
        filters: Column-to-value equality filters; keys outside
            ``spec.filters`` are ignored.
        after: Keyset cursor — rows ordered strictly below this value.
        limit: Maximum rows returned.

    Returns:
        A Select that references no hidden or excluded column.
    """
    order_column = getattr(spec.model, spec.order_by)
    statement = (
        select(spec.model)
        .options(load_only(*_attributes(spec.model, spec.list_columns)))
        .order_by(order_column.desc())
        .limit(limit)
    )
    if search:
        clause = _search_clause(spec, search)
        if clause is not None:
            statement = statement.where(clause)
    for name, value in (filters or {}).items():
        if name in spec.filters:
            statement = statement.where(getattr(spec.model, name) == value)
    if after is not None:
        coerced_after = _coerce_cursor(order_column, after)
        if coerced_after is not None:
            statement = statement.where(order_column < coerced_after)
    return statement


def count_statement(spec: ModelSpec) -> Select:
    """Build a bare row count for a spec."""
    return select(func.count()).select_from(spec.model)


def detail_statement(spec: ModelSpec, pk: Any) -> Select:
    """Build the detail query, loading the spec's detail columns."""
    return (
        select(spec.model)
        .options(load_only(*_attributes(spec.model, spec.detail_columns)))
        .where(primary_key(spec.model) == pk)
    )
