"""Presentation helpers shared by templates and controllers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .constants import (
    BYTES_CELL,
    CELL_MAX_LENGTH,
    EMPTY_CELL,
    FALSE_CELL,
    HTMX_HEADER,
    TRUE_CELL,
)

if TYPE_CHECKING:
    from litestar import Request


def render_value(value: object) -> str:
    """Format a column value for display in a table cell or detail row."""
    if value is None:
        return EMPTY_CELL
    if isinstance(value, bool):
        return TRUE_CELL if value else FALSE_CELL
    if isinstance(value, (bytes, bytearray, memoryview)):
        return BYTES_CELL.format(size=len(bytes(value)))
    text = str(value)
    if len(text) > CELL_MAX_LENGTH:
        return f"{text[:CELL_MAX_LENGTH]}…"
    return text


def is_htmx(request: Request) -> bool:
    """True when the caller is HTMX and expects a fragment, not a page."""
    return request.headers.get(HTMX_HEADER) is not None


def project(row: Any, columns: tuple[str, ...]) -> dict[str, Any]:
    """Project a model instance onto ``columns``, missing attributes as None."""
    return {column: getattr(row, column, None) for column in columns}
