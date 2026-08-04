"""Resolving foreign keys to labels, and to the choices a form offers.

Kept apart from the statement builders so the rule about how many queries a page
costs lives in one readable place: one statement per related model, never one per
row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .constants import RELATION_OPTION_LIMIT
from .queries import relation_count, relation_labels, relation_options

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .spec import ModelSpec, Relation


async def labels_for(
    session: Any, spec: ModelSpec, rows: Sequence[Mapping[str, Any]]
) -> dict[str, dict[Any, Any]]:
    """Return ``{column: {key: label}}`` for every relation on show.

    One query per related model for the whole page. Keys the page does not
    mention are never asked for, and a relation with no values on this page costs
    no query at all.
    """
    resolved: dict[str, dict[Any, Any]] = {}
    for column, relation in spec.relations.items():
        values = {row[column] for row in rows if row.get(column) is not None}
        if not values:
            continue
        result = await session.execute(relation_labels(relation, values))
        resolved[column] = {key: label for key, label in result.all()}
    return resolved


async def options_for(
    session: Any, spec: ModelSpec, column: str, relation: Relation
) -> tuple[tuple[str, str], ...] | None:
    """Return the choices for one relation, or None when there are too many.

    Past ``RELATION_OPTION_LIMIT`` rows a select would be a lie: it would list
    some records and silently omit others, leaving no way to pick one of the
    missing. The field falls back to accepting a key directly instead.
    """
    total = await session.scalar(relation_count(relation))
    if total is not None and total > RELATION_OPTION_LIMIT:
        return None
    result = await session.execute(relation_options(relation, RELATION_OPTION_LIMIT))
    return tuple((str(key), str(label)) for key, label in result.all())
