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


def test_load_more_swaps_the_row_it_lives_in() -> None:
    """The trigger sits inside the table body and replaces its own row.

    It used to sit after ``.wrap`` and target ``closest .wrap`` -- a selector
    matching ancestors only, so it never resolved a target and the click did
    nothing. Observed: the trigger is a row, and the row is what gets swapped,
    which is also what makes appended pages land in the existing tbody.
    """
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[ROW], cursor="500",
        page_url="/admin/m/widget", render_value=render_value,
    )
    assert 'hx-target="closest tr"' in html
    assert 'hx-swap="outerHTML"' in html
    assert html.index("<tbody>") < html.index("Load more") < html.index("</tbody>")


def test_load_more_carries_the_current_search_and_filters() -> None:
    """The next page is drawn from the result set already on screen."""
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[ROW], cursor="500", search="widget one",
        filters={"kind": "alpha"}, page_url="/admin/m/widget",
        render_value=render_value,
    )
    assert "kind=alpha" in html
    assert "after=500" in html
    assert "search=widget+one" in html


def test_an_exhausted_page_does_not_claim_the_result_set_is_empty() -> None:
    """No rows plus an ``after`` cursor is the end of paging, not an empty view."""
    rows_template = _engine().get_template("_rows.html")
    exhausted = rows_template.render(
        spec=WIDGET, rows=[], cursor=None, after="500",
        page_url="/admin/m/widget", render_value=render_value,
    )
    empty = rows_template.render(
        spec=WIDGET, rows=[], cursor=None,
        page_url="/admin/m/widget", render_value=render_value,
    )
    assert exhausted.strip() == ""
    assert "Nothing matches this view yet." in empty
