"""Statement builders — the single place the column boundary is enforced."""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import load_only

from .constants import PAGE_SIZE

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy import Select

    from .spec import ModelSpec, Relation


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
            parsed = datetime.datetime.fromisoformat(cursor)
        except (ValueError, TypeError):
            return None
        # A naive datetime bound against a timezone-aware column mismatches
        # at the driver level (e.g. asyncpg raises). Treat it as an absent
        # cursor, same as any other malformed value.
        column_is_aware = getattr(order_column.type, "timezone", False)
        if parsed.tzinfo is None and column_is_aware:
            return None
        return parsed

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


def sort_column(spec: ModelSpec, sort: str | None) -> str:
    """Return the column to order by: the requested one, or the spec's default.

    A sort arrives from a query string, so it is checked against the columns the
    list already shows rather than trusted. Anything else — a typo, a hidden
    column, a probe — falls back to ``order_by`` instead of raising, because a
    bad sort in a URL should still render the list.
    """
    if sort and sort in spec.list_columns and sort not in spec.hidden_columns:
        return sort
    return spec.order_by


def _equality_clause(spec: ModelSpec, name: str, value: Any) -> Any:
    """Build the clause for one filter value, or for several of them.

    A filter holding more than one value is a union, not a contradiction: asking
    for paid *and* pending means either, which is ``IN``.
    """
    column = getattr(spec.model, name)
    if isinstance(value, (list, tuple, set, frozenset)):
        chosen = [item for item in value if item != ""]
        if not chosen:
            return None
        if len(chosen) == 1:
            return column == chosen[0]
        return column.in_(chosen)
    return None if value == "" else column == value


def _is_date_only(text: str) -> bool:
    """True when a bound names a day rather than an instant."""
    return "T" not in text and " " not in text


def _coerce_bound(column: Any, text: str) -> Any:
    """Coerce a filter bound to the column's type, or None if it cannot.

    Deliberately not the cursor rule: a cursor is a value this admin produced, so
    a naive datetime against an aware column means something went wrong and is
    discarded. A bound is a date a person typed into a form, and the only useful
    reading of it is UTC.
    """
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return text
    if python_type is datetime.datetime:
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is None and getattr(column.type, "timezone", False):
            return parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    if python_type is datetime.date:
        try:
            return datetime.date.fromisoformat(text)
        except (ValueError, TypeError):
            return None
    if python_type is str:
        return text
    try:
        return python_type(text)
    except (ValueError, TypeError):
        return None


def _range_clauses(spec: ModelSpec, name: str, bounds: Any) -> list[Any]:
    """Build the clauses bounding one column, skipping ends that are absent.

    A malformed bound is treated as absent rather than as a reason to fail the
    page, because bounds arrive from URLs.
    """
    column = getattr(spec.model, name)
    clauses = []
    start, end = getattr(bounds, "start", None), getattr(bounds, "end", None)
    if start:
        coerced = _coerce_bound(column, start)
        if coerced is not None:
            clauses.append(column >= coerced)
    if end:
        coerced = _coerce_bound(column, end)
        if coerced is not None:
            # "to 4 August" on a timestamp column means through that whole day.
            # Comparing <= midnight would silently exclude every row in it.
            if _is_date_only(end) and isinstance(coerced, datetime.datetime):
                clauses.append(column < coerced + datetime.timedelta(days=1))
            else:
                clauses.append(column <= coerced)
    return clauses


def list_statement(
    spec: ModelSpec,
    *,
    search: str | None = None,
    filters: dict[str, Any] | None = None,
    ranges: dict[str, Any] | None = None,
    after: str | None = None,
    sort: str | None = None,
    descending: bool = True,
    limit: int = PAGE_SIZE,
) -> Select:
    """Build the list query, loading only the spec's list columns.

    Args:
        spec: The model spec being listed.
        search: Free-text term, applied per :func:`_search_clause`.
        filters: Column to value, or to several values, matched by equality
            or ``IN``; keys outside ``spec.filters`` are ignored.
        ranges: Column to a start/end pair bounding it; keys outside
            ``spec.filters`` are ignored.
        after: Keyset cursor — rows ordered strictly past this value, in
            whichever direction the sort runs.
        sort: Column to order by; ignored unless it is a list column.
        descending: Direction of that order.
        limit: Maximum rows returned.

    Returns:
        A Select that references no hidden or excluded column.
    """
    order_name = sort_column(spec, sort)
    order_column = getattr(spec.model, order_name)
    key_column = primary_key(spec.model)
    ordering = order_column.desc() if descending else order_column.asc()
    statement = (
        select(spec.model)
        .options(load_only(*_attributes(spec.model, spec.list_columns)))
        # Tie-broken by the key: a sort on a non-unique column would otherwise
        # order rows arbitrarily within a value, and keyset paging over an
        # unstable order skips and repeats rows.
        .order_by(ordering, key_column.desc() if descending else key_column.asc())
        .limit(limit)
    )
    if search:
        clause = _search_clause(spec, search)
        if clause is not None:
            statement = statement.where(clause)
    for name, value in (filters or {}).items():
        if name in spec.filters:
            clause = _equality_clause(spec, name, value)
            if clause is not None:
                statement = statement.where(clause)
    for name, bounds in (ranges or {}).items():
        if name in spec.filters:
            for clause in _range_clauses(spec, name, bounds):
                statement = statement.where(clause)
    if after is not None:
        coerced_after = _coerce_cursor(order_column, after)
        if coerced_after is not None:
            statement = statement.where(
                order_column < coerced_after
                if descending
                else order_column > coerced_after
            )
    return statement


def count_statement(spec: ModelSpec) -> Select:
    """Build a bare row count for a spec."""
    return select(func.count()).select_from(spec.model)


def facet_counts(
    spec: ModelSpec,
    column: str,
    *,
    search: str | None = None,
    filters: dict[str, Any] | None = None,
    ranges: dict[str, Any] | None = None,
    limit: int | None = None,
) -> Select:
    """Select each value of a filterable column with how many rows it has.

    Counted against the rest of the current view -- the search and every *other*
    filter -- so a number says what clicking that value would actually give you,
    not what the table holds in total. Its own filter is excluded, or every value
    but the active one would read zero.

    Ordered by value rather than by count: a segmented control whose segments
    reorder as data changes is a control you cannot learn.
    """
    target = getattr(spec.model, column)
    statement = (
        select(target, func.count())
        .where(target.is_not(None))
        .group_by(target)
        .order_by(target.asc())
    )
    if search:
        clause = _search_clause(spec, search)
        if clause is not None:
            statement = statement.where(clause)
    for name, value in (filters or {}).items():
        if name in spec.filters and name != column:
            clause = _equality_clause(spec, name, value)
            if clause is not None:
                statement = statement.where(clause)
    for name, bounds in (ranges or {}).items():
        if name in spec.filters and name != column:
            for clause in _range_clauses(spec, name, bounds):
                statement = statement.where(clause)
    return statement if limit is None else statement.limit(limit)


def relation_labels(relation: Relation, values: Iterable[Any]) -> Select:
    """Select the key and label of the related rows named by ``values``.

    One statement for a whole page of rows: resolving a foreign key per row would
    be a query per row, which is the classic way an admin list becomes slow.
    Selects two columns, never the whole related row.
    """
    key = primary_key(relation.model)
    label = getattr(relation.model, relation.label)
    return select(key, label).where(key.in_(list(values)))


def relation_options(relation: Relation, limit: int) -> Select:
    """Select the key and label of every choice a form may offer, up to a limit."""
    key = primary_key(relation.model)
    label = getattr(relation.model, relation.label)
    return (
        select(key, label)
        .order_by(getattr(relation.model, relation.ordering).asc())
        .limit(limit)
    )


def relation_count(relation: Relation) -> Select:
    """Count the related rows, to know whether a full list of choices is honest."""
    return select(func.count()).select_from(relation.model)


def _coerce_pk(pk_column: Any, pk: Any) -> Any:
    """Coerce a URL-supplied primary key to the column's Python type.

    A primary key arriving from a route path is always a ``str`` — the
    generic detail and delete routes declare ``{pk:str}`` — but the column
    itself is commonly an integer. PostgreSQL via asyncpg refuses an
    implicit ``bigint = character varying`` comparison, so a well-formed
    numeric pk against an integer-keyed model would otherwise fail at the
    database rather than match the row it plainly names. A pk that fails to
    coerce is passed through unchanged: it cannot match any row of that
    type either way, and returning it as-is keeps lookups against
    string-keyed columns — which never needed coercion — unaffected.
    """
    try:
        python_type = pk_column.type.python_type
    except NotImplementedError:
        return pk
    if python_type is str or isinstance(pk, python_type):
        return pk
    try:
        return python_type(pk)
    except (ValueError, TypeError):
        return pk


def detail_statement(spec: ModelSpec, pk: Any) -> Select:
    """Build the detail query, loading the spec's detail columns."""
    pk_column = primary_key(spec.model)
    return (
        select(spec.model)
        .options(load_only(*_attributes(spec.model, spec.detail_columns)))
        .where(pk_column == _coerce_pk(pk_column, pk))
    )
