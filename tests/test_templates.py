"""Templates render from plain dictionaries, with no app, session or database."""

from litestar.plugins.jinja import JinjaTemplateEngine

from admin_litestar.render import render_value
from admin_litestar.templates import TEMPLATES

from .test_spec import WIDGET

ROW = {"id": 1, "name": "widget one", "kind": "alpha", "created_at": "2026-07-29"}


def _engine() -> JinjaTemplateEngine:
    """Build a Jinja engine over the package's template directory."""
    return JinjaTemplateEngine(directory=TEMPLATES)


def test_table_renders_every_list_column_and_its_values() -> None:
    """Declared columns appear as headers and their values as cells."""
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[ROW], cursor=None,
        page_url="/admin/m/widget", render_value=render_value,
    )
    for column in WIDGET.list_columns:
        assert column in html
    assert "widget one" in html


def test_table_renders_an_empty_result_set() -> None:
    """No rows still produces a well-formed table."""
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[], cursor=None,
        page_url="/admin/m/widget", render_value=render_value,
    )
    assert "<tbody>" in html


def test_none_values_never_render_as_the_word_none() -> None:
    """Missing values render as an em dash."""
    row = dict.fromkeys(WIDGET.list_columns)
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[row], cursor=None,
        page_url="/admin/m/widget", render_value=render_value,
    )
    assert "None" not in html
    assert "—" in html


def test_cursor_renders_a_load_more_control() -> None:
    """A cursor produces the HTMX paging button; its absence does not."""
    def _render(cursor: str | None) -> str:
        return _engine().get_template("_table.html").render(
            spec=WIDGET, rows=[ROW], cursor=cursor,
            page_url="/admin/m/widget", render_value=render_value,
        )

    assert "Load more" in _render("500")
    assert "Load more" not in _render(None)
