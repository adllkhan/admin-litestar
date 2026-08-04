"""The state a list page is in, and the URLs that change one part of it.

Every control on a list page — a sort header, a filter segment, a range form, the
paging trigger, the export link — is the same view with one thing altered. Built
here rather than in the templates: assembling query strings in Jinja worked while
a filter held one value, and stopped being honest the moment one could hold
several.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from .constants import ASCENDING, DESCENDING, RANGE_END_SUFFIX, RANGE_START_SUFFIX

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .filters import Range


@dataclass(frozen=True, slots=True)
class ListView:
    """What the list is showing, and how to link to a variation of it.

    Attributes:
        page_url: The list's own URL, without a query string.
        search: The current term, if any.
        filters: Column to the values selected for it.
        ranges: Column to the bounds set on it.
        sort: Column the rows are ordered by.
        direction: ``asc`` or ``desc``.
    """

    page_url: str
    search: str = ""
    filters: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    ranges: Mapping[str, Range] = field(default_factory=dict)
    sort: str = ""
    direction: str = DESCENDING

    def _pairs(self) -> list[tuple[str, str]]:
        """Flatten the view into query parameters, repeating multi-valued ones."""
        pairs: list[tuple[str, str]] = []
        for column, values in self.filters.items():
            pairs.extend((column, value) for value in values)
        for column, bounds in self.ranges.items():
            if bounds.start:
                pairs.append((f"{column}{RANGE_START_SUFFIX}", bounds.start))
            if bounds.end:
                pairs.append((f"{column}{RANGE_END_SUFFIX}", bounds.end))
        if self.search:
            pairs.append(("search", self.search))
        if self.sort:
            pairs.append(("sort", self.sort))
            pairs.append(("direction", self.direction))
        return pairs

    def url(self, **extra: str) -> str:
        """Return this view's URL, with any extra parameters appended."""
        pairs = self._pairs() + [(key, value) for key, value in extra.items() if value]
        query = urlencode(pairs)
        return f"{self.page_url}?{query}" if query else self.page_url

    def query(self) -> str:
        """Return the query string alone, for a form to carry in hidden fields."""
        return urlencode(self._pairs())

    def selected(self, column: str) -> tuple[str, ...]:
        """Return the values currently selected for one column."""
        return tuple(self.filters.get(column, ()))

    def has(self, column: str, value: str) -> bool:
        """Whether one value of one column is currently selected."""
        return value in self.selected(column)

    def toggled(self, column: str, value: str) -> str:
        """URL with one value of one column added, or removed if already there.

        Filters hold sets, so a second value widens rather than replaces: asking
        for paid and pending means either. Clicking a selected value removes it,
        which is how a filter is undone where it was set.
        """
        current = self.selected(column)
        remaining = tuple(item for item in current if item != value)
        if len(remaining) == len(current):
            remaining = (*current, value)
        filters = {name: values for name, values in self.filters.items() if values}
        if remaining:
            filters[column] = remaining
        else:
            filters.pop(column, None)
        return replace(self, filters=filters).url()

    def cleared(self, column: str) -> str:
        """URL with one column's filter removed entirely."""
        filters = {
            name: values for name, values in self.filters.items() if name != column
        }
        ranges = {
            name: bounds for name, bounds in self.ranges.items() if name != column
        }
        return replace(self, filters=filters, ranges=ranges).url()

    def ranged(self, column: str, bounds: Range) -> str:
        """URL with one column bounded, or unbounded if the bounds are empty."""
        ranges = {
            name: current for name, current in self.ranges.items() if name != column
        }
        if bounds:
            ranges[column] = bounds
        return replace(self, ranges=ranges).url()

    def bounds_of(self, column: str) -> Range | None:
        """Return the bounds currently set on a column, or None."""
        return self.ranges.get(column)

    def sorted_by(self, column: str) -> str:
        """URL ordered by one column, flipping direction if it already is.

        A first click sorts descending, which is what a reader wants from a list
        of records: the newest, the largest, the most recent.
        """
        flipped = (
            ASCENDING if self.sort == column and self.direction == DESCENDING
            else DESCENDING
        )
        return replace(self, sort=column, direction=flipped).url()

    def hidden_fields(self, skip: Iterable[str] = ()) -> list[tuple[str, str]]:
        """Return the view as form fields, minus the parts the form itself edits.

        A GET form replaces the whole query string, so anything it does not carry
        is silently dropped: searching would clear the filters, and setting a date
        range would clear the sort. Whatever a form renders as its own control it
        names here, so the value is not also submitted twice.
        """
        skipped: set[str] = set()
        for name in skip:
            skipped |= {
                name, f"{name}{RANGE_START_SUFFIX}", f"{name}{RANGE_END_SUFFIX}"
            }
        return [(key, value) for key, value in self._pairs() if key not in skipped]

    def export_url(self) -> str:
        """Return the CSV export of exactly this view."""
        query = self.query()
        return f"{self.page_url}/export?{query}" if query else f"{self.page_url}/export"

    def direction_of(self, column: str) -> str | None:
        """Return the direction this column is sorted in, or None if it is not."""
        return self.direction if self.sort == column else None
