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


def test_value_at_the_length_boundary_passes_through_unchanged() -> None:
    """A string of exactly CELL_MAX_LENGTH is not truncated."""
    text = "x" * CELL_MAX_LENGTH
    assert render_value(text) == text


def test_value_one_over_the_length_boundary_is_truncated() -> None:
    """A string one character past CELL_MAX_LENGTH is truncated with an ellipsis."""
    text = "x" * (CELL_MAX_LENGTH + 1)
    rendered = render_value(text)
    assert rendered == "x" * CELL_MAX_LENGTH + "…"


def test_bytes_do_not_render_as_a_python_repr() -> None:
    """Binary columns must not leak b'...' into the page."""
    assert "b'" not in render_value(b"\x00\x01")


def test_bytearray_does_not_render_as_a_python_repr() -> None:
    """A bytearray column must not leak a Python repr onto the page."""
    assert "bytearray(" not in render_value(bytearray(b"\x00\x01"))


def test_memoryview_does_not_render_as_a_python_repr() -> None:
    """A memoryview column must not leak a Python repr onto the page.

    This matters because in the first real consumer these columns hold AES
    ciphertext, and a fall-through to str() would put its repr on the page.
    """
    assert "memory at" not in render_value(memoryview(b"\x00\x01"))


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
