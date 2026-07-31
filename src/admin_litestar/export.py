"""Streaming CSV export driven by a spec's list columns."""

from __future__ import annotations

import csv
import io
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from .spec import ModelSpec


class _Sink:
    """A one-line buffer the csv writer writes into."""

    def __init__(self) -> None:
        self._buffer = io.StringIO()
        self._writer = csv.writer(self._buffer)

    def line(self, values: list[Any]) -> str:
        """Encode one row and return it, clearing the buffer."""
        self._writer.writerow(values)
        text = self._buffer.getvalue()
        self._buffer.seek(0)
        self._buffer.truncate(0)
        return text


def csv_rows(spec: ModelSpec, rows: Iterable[dict[str, Any]]) -> Iterator[str]:
    """Yield CSV lines for a spec's list columns, header first.

    Args:
        spec: The spec being exported. Its ``list_columns`` define the column
            set, so hidden and excluded columns cannot appear.
        rows: Projected row dictionaries.

    Yields:
        CSV-encoded lines, each including its trailing newline.
    """
    sink = _Sink()
    yield sink.line(list(spec.list_columns))
    for row in rows:
        yield sink.line([row.get(column) for column in spec.list_columns])
