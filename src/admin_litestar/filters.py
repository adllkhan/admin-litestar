"""What a filter offers to choose from, and how many rows each choice has.

A declared filter is an equality match on a column, so the values worth offering
are the ones the column holds. Each arrives with a count taken against the rest of
the current view, which is what makes the control also a small readout of how the
rows are distributed.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .constants import FILTER_CHOICE_LIMIT, RANGE_END_SUFFIX, RANGE_START_SUFFIX
from .queries import facet_counts

if TYPE_CHECKING:
    from .spec import ModelSpec


@dataclass(frozen=True, slots=True)
class Facet:
    """One value of a filterable column, with its share of the current view.

    Attributes:
        value: The value, as it appears in a URL and on the control.
        count: Rows that would remain if this value were selected.
    """

    value: str
    count: int

    @property
    def empty(self) -> bool:
        """True when selecting this value would leave nothing."""
        return self.count == 0


@dataclass(frozen=True, slots=True)
class Range:
    """A bounded column, either end optional.

    Attributes:
        start: Inclusive lower bound, as typed.
        end: Upper bound, as typed. A date-only end covers its whole day.
    """

    start: str = ""
    end: str = ""

    def __bool__(self) -> bool:
        """True when either end is set, so an untouched range filters nothing."""
        return bool(self.start or self.end)


@dataclass(frozen=True, slots=True)
class RangePreset:
    """A named range, for the spans a reader asks for most.

    Attributes:
        label: What the segment says.
        start: Inclusive first day, ISO, or empty for unbounded.
        end: Last day, ISO, or empty for unbounded.
    """

    label: str
    start: str = ""
    end: str = ""

    def matches(self, bounds: Range | None) -> bool:
        """Whether the current bounds are exactly this preset."""
        if bounds is None:
            return not (self.start or self.end)
        return bounds.start == self.start and bounds.end == self.end

    @property
    def bounds(self) -> Range:
        """This preset as bounds, for building a URL."""
        return Range(start=self.start, end=self.end)


def range_presets(today: datetime.date) -> tuple[RangePreset, ...]:
    """The spans offered on a date filter, resolved against a given day.

    Absolute dates rather than relative keywords, so a filtered list stays the
    same list when it is shared or reopened tomorrow -- a URL saying "last 7 days"
    would quietly mean a different week each time it is read.
    """
    return (
        RangePreset(label="Today", start=today.isoformat(), end=today.isoformat()),
        RangePreset(
            label="7 days",
            start=(today - datetime.timedelta(days=6)).isoformat(),
            end=today.isoformat(),
        ),
        RangePreset(
            label="30 days",
            start=(today - datetime.timedelta(days=29)).isoformat(),
            end=today.isoformat(),
        ),
        RangePreset(
            label="This month",
            start=today.replace(day=1).isoformat(),
            end=today.isoformat(),
        ),
    )


def is_range_column(spec: ModelSpec, column: str) -> bool:
    """Whether a filter should be a range rather than a set of values.

    Decided from the column's type: dates and timestamps are asked "between", and
    everything else is asked "which of these". A year of distinct days is not a
    control, however few rows it holds.
    """
    try:
        python_type = spec.model.__table__.columns[column].type.python_type
    except NotImplementedError:
        return False
    return python_type in (datetime.date, datetime.datetime)


def parse(params: Any, spec: ModelSpec) -> tuple[dict[str, tuple[str, ...]], dict[str, Range]]:
    """Read a request's query string into filter values and ranges.

    Values come back as tuples because a filter may hold several -- the URL
    repeats the parameter, ``?status=paid&status=pending`` -- and a single value is
    simply a tuple of one, so callers have one shape to handle.
    """
    values: dict[str, tuple[str, ...]] = {}
    ranges: dict[str, Range] = {}
    for column in spec.filters:
        if is_range_column(spec, column):
            bounds = Range(
                start=(params.get(f"{column}{RANGE_START_SUFFIX}") or "").strip(),
                end=(params.get(f"{column}{RANGE_END_SUFFIX}") or "").strip(),
            )
            if bounds:
                ranges[column] = bounds
            continue
        # getall for a MultiDict, a plain get for anything else
        getall = getattr(params, "getall", None)
        chosen = getall(column, []) if getall else _as_list(params.get(column))
        selected = tuple(value for value in chosen if value)
        if selected:
            values[column] = selected
    return values, ranges


def _as_list(value: Any) -> list[str]:
    """Normalise a single query value into a list."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def declared_choices(spec: ModelSpec, column: str) -> tuple[str, ...] | None:
    """Return the choices a column declares in its own type, if it does."""
    enums = getattr(spec.model.__table__.columns[column].type, "enums", None)
    return tuple(enums) if enums else None


async def facets_for(
    session: Any,
    spec: ModelSpec,
    *,
    search: str | None = None,
    filters: dict[str, Any] | None = None,
    ranges: dict[str, Range] | None = None,
    limit: int = FILTER_CHOICE_LIMIT,
) -> dict[str, tuple[Facet, ...]]:
    """Return ``{column: facets}`` for every filter that can offer a list.

    One grouped query per filterable column. A column with more values than a
    control should hold is left out entirely, and the template falls back to a
    text field: a truncated list of options hides the rest with no way to reach
    them.

    A value that exists in the column but not in the current view is kept at zero
    rather than dropped, so the control keeps its shape as filters change; the
    template renders those as unselectable, since choosing one would leave nothing.
    """
    resolved: dict[str, tuple[Facet, ...]] = {}
    for column in spec.filters:
        if is_range_column(spec, column):
            # A date column is bounded, not chosen from; counting every distinct
            # day would be a list nobody can use.
            continue
        declared = declared_choices(spec, column)
        if declared is None:
            # Which values exist at all, asked without the current view applied:
            # a segment that disappears when another filter is set is a control
            # that moves under the reader, so the set of segments stays fixed and
            # the counts are what change.
            everything = await session.execute(facet_counts(spec, column))
            values = sorted(str(value) for value, _ in everything.all())
        else:
            values = list(declared)
        if len(values) > limit:
            continue
        counted = await session.execute(
            facet_counts(
                spec, column, search=search, filters=filters, ranges=ranges
            )
        )
        counts = {str(value): int(count) for value, count in counted.all()}
        resolved[column] = tuple(
            Facet(value=value, count=counts.get(value, 0)) for value in values
        )
    return resolved
