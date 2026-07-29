"""Cell formatting and request-shape helpers."""

from litestar_admin.constants import CELL_MAX_LENGTH, EMPTY_CELL
from litestar_admin.render import is_htmx, project, render_value

from .models import Widget


class _Request:
    """Minimal stand-in exposing only the headers the helper reads."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers


def test_none_renders_as_an_em_dash() -> None:
    """A missing value never renders as the string 'None'."""
    assert render_value(None) == EMPTY_CELL


def test_booleans_render_as_words() -> None:
    """Booleans read as yes/no rather than True/False."""
    assert render_value(True) == "yes"
    assert render_value(False) == "no"


def test_numbers_render_plainly() -> None:
    """Integers pass through unchanged."""
    assert render_value(42) == "42"


def test_long_values_are_truncated_with_an_ellipsis() -> None:
    """Long opaque values stay scannable in a table."""
    rendered = render_value("x" * (CELL_MAX_LENGTH + 50))
    assert len(rendered) == CELL_MAX_LENGTH + 1
    assert rendered.endswith("…")


def test_bytes_do_not_render_as_a_python_repr() -> None:
    """Binary columns must not leak b'...' into the page."""
    assert "b'" not in render_value(b"\x00\x01")


def test_htmx_detection() -> None:
    """The HX-Request header decides whether a fragment is wanted."""
    assert is_htmx(_Request({"HX-Request": "true"})) is True
    assert is_htmx(_Request({})) is False


def test_project_reads_declared_columns_only() -> None:
    """Projection returns exactly the requested keys, missing ones as None."""
    widget = Widget(id=1, name="a")
    assert project(widget, ("id", "name", "kind")) == {
        "id": 1,
        "name": "a",
        "kind": None,
    }
