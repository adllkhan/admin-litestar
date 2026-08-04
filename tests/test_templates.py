"""Templates render from plain dictionaries, with no app, session or database."""

from litestar.plugins.jinja import JinjaTemplateEngine

from admin_litestar import DETAIL, LIST, ModelSpec, RowAction
from admin_litestar.charts import bars, spark
from admin_litestar.render import render_value
from admin_litestar.spec import Registry
from admin_litestar.templates import TEMPLATES
from admin_litestar.views import ListView

from .models import Widget
from .test_spec import SECRET, WIDGET

ROW = {"id": 1, "name": "widget one", "kind": "alpha", "created_at": "2026-07-29"}
PAGE_URL = "/admin/m/widget"


def _view(**state: object) -> ListView:
    """The state a list page is in, which its templates now read URLs from."""
    return ListView(page_url=PAGE_URL, **state)


def _engine() -> JinjaTemplateEngine:
    """Build a Jinja engine over the package's template directory."""
    return JinjaTemplateEngine(directory=TEMPLATES)


def test_table_renders_every_list_column_and_its_values() -> None:
    """Declared columns appear as headers and their values as cells."""
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[ROW], cursor=None,
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    for column in WIDGET.list_columns:
        assert column in html
    assert "widget one" in html


def test_table_renders_an_empty_result_set() -> None:
    """No rows still produces a well-formed table."""
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[], cursor=None,
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    assert "<tbody>" in html


def test_none_values_never_render_as_the_word_none() -> None:
    """Missing values render as an em dash."""
    row = dict.fromkeys(WIDGET.list_columns)
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[row], cursor=None,
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    assert "None" not in html
    assert "—" in html


def test_cursor_renders_a_load_more_control() -> None:
    """A cursor produces the HTMX paging button; its absence does not."""
    def _render(cursor: str | None) -> str:
        return _engine().get_template("_table.html").render(
            spec=WIDGET, rows=[ROW], cursor=cursor,
            page_url=PAGE_URL, render_value=render_value, view=_view(),
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
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    assert 'hx-target="closest tr"' in html
    assert 'hx-swap="outerHTML"' in html
    assert html.index("<tbody>") < html.index("Load more") < html.index("</tbody>")


def test_load_more_carries_the_current_search_and_filters() -> None:
    """The next page is drawn from the result set already on screen."""
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[ROW], cursor="500", search="widget one",
        page_url=PAGE_URL, render_value=render_value,
        view=_view(search="widget one", filters={"kind": ("alpha",)}),
    )
    assert "kind=alpha" in html
    assert "after=500" in html
    assert "search=widget+one" in html


def test_an_exhausted_page_does_not_claim_the_result_set_is_empty() -> None:
    """No rows plus an ``after`` cursor is the end of paging, not an empty view."""
    rows_template = _engine().get_template("_rows.html")
    exhausted = rows_template.render(
        spec=WIDGET, rows=[], cursor=None, after="500",
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    empty = rows_template.render(
        spec=WIDGET, rows=[], cursor=None,
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    assert exhausted.strip() == ""
    assert "Nothing matches this view yet." in empty


def test_rows_open_their_record_in_a_dialog() -> None:
    """A row is clickable, and reaches its own record.

    Rows used to render as inert cells, so the detail page a spec declared was
    reachable only by typing its URL. Observed: each row carries the request that
    fetches its record into the modal container, and can be reached by keyboard.
    """
    html = _engine().get_template("_table.html").render(
        spec=WIDGET, rows=[ROW], cursor=None, pk_name="id",
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    assert 'hx-get="/admin/m/widget/1"' in html
    assert 'hx-target="#modal"' in html
    assert 'class="clickable"' in html
    assert 'tabindex="0"' in html
    assert "keyup[key=='Enter']" in html


def test_rows_are_inert_for_a_spec_with_no_detail_route() -> None:
    """A row must not offer to open what the spec does not render."""
    html = _engine().get_template("_table.html").render(
        spec=SECRET, rows=[{"id": 1, "created_at": "2026-07-29"}], cursor=None,
        pk_name="id", page_url="/admin/m/secret", render_value=render_value,
        view=ListView(page_url="/admin/m/secret"),
    )
    assert "hx-get" not in html
    assert "clickable" not in html


def test_the_dialog_and_the_detail_page_show_the_same_rows() -> None:
    """One partial backs both, so a record cannot read differently in each."""
    context = dict(
        spec=WIDGET, row=dict(ROW, _blob_data=None), pk=1,
        page_url=PAGE_URL, render_value=render_value, view=_view(),
    )
    dialog = _engine().get_template("_modal.html").render(groups=("Things",), **context)
    rows = _engine().get_template("_detail_rows.html").render(**context)
    for column in WIDGET.detail_columns:
        assert column in dialog
        assert column in rows
    assert "<dialog" in dialog
    assert 'method="dialog"' in dialog, "closing must not require script"


ACTIONS = ModelSpec(
    model=Widget,
    slug="widget",
    label="Widgets",
    group="Things",
    list_columns=("id", "name"),
    detail_columns=("id", "name"),
    capabilities=frozenset({LIST, DETAIL}),
    order_by="id",
    row_actions=(
        RowAction(label="Resend", path="/hooks/resend/{pk}", method="post"),
        RowAction(label="Open log", path="/logs/{pk}"),
        RowAction(label="Void", path="/hooks/void/{pk}", method="post",
                  confirm=True, danger=True),
    ),
)


def _render_rows(spec: ModelSpec, **extra: object) -> str:
    """Render the table for a spec, with the globals a row needs."""
    return _engine().get_template("_table.html").render(
        spec=spec, rows=[ROW], cursor=None, pk_name="id",
        page_url=PAGE_URL, render_value=render_value, view=_view(),
        admin_path="/admin", registry=Registry([spec]),
        csrf_token=lambda: "token", **extra,
    )


def test_a_row_carries_the_actions_the_spec_declares() -> None:
    """Host-defined buttons appear per row, addressed to that record."""
    html = _render_rows(ACTIONS)
    assert 'action="/hooks/resend/1"' in html
    assert 'href="/logs/1"' in html
    assert "Void" in html


def test_a_posting_action_carries_a_csrf_token() -> None:
    """A button that changes something goes through the same CSRF layer."""
    html = _render_rows(ACTIONS)
    assert html.count('name="_csrf_token"') >= 2


def test_a_destructive_action_asks_first() -> None:
    """`confirm` renders the two-step confirmation, not a bare button."""
    html = _render_rows(ACTIONS)
    assert "confirm--inline" in html
    assert "Void record 1?" in html


def test_a_click_on_an_action_does_not_open_the_record() -> None:
    """The row opens a dialog on click; a button inside it must not.

    Without the filter, every action click would also fire the row's own request
    and open the modal over whatever the button just did.
    """
    html = _render_rows(ACTIONS)
    # the selection checkbox is excluded for the same reason
    assert "click[!event.target.closest('.row-actions, .row-select')]" in html


def test_the_header_and_the_empty_state_account_for_the_actions_column() -> None:
    """A colspan that ignores the extra column leaves the table ragged."""
    html = _render_rows(ACTIONS)
    assert '<th class="row-actions">' in html
    empty = _engine().get_template("_table.html").render(
        spec=ACTIONS, rows=[], cursor=None, pk_name="id",
        page_url=PAGE_URL, render_value=render_value, view=_view(),
        admin_path="/admin", registry=Registry([ACTIONS]), csrf_token=lambda: "t",
    )
    assert 'colspan="3"' in empty


def test_a_spec_with_no_actions_grows_no_extra_column() -> None:
    """The column exists only where it is declared.

    Asserted on the cells rather than on the class name, which also appears in
    the row's own trigger filter whether or not any action exists.
    """
    html = _render_rows(WIDGET)
    assert '<th class="row-actions">' not in html
    assert '<td class="row-actions">' not in html


def test_a_bar_chart_labels_every_bar_with_its_category_and_value() -> None:
    """Identity is written next to the mark, never carried by colour alone."""
    html = _engine().get_template("_bars.html").render(
        title="Invoices by status", render_value=render_value,
        bars=bars([("paid", 46), ("pending", 47), ("void", 47)]),
    )
    assert "Invoices by status" in html
    for label in ("paid", "pending", "void"):
        assert label in html
    assert "width: 100.0%" in html
    assert "46" in html


def test_an_empty_chart_says_so_instead_of_drawing_an_empty_box() -> None:
    """A chart with no data is a sentence, not a frame."""
    html = _engine().get_template("_bars.html").render(
        title="Nothing", render_value=render_value, bars=()
    )
    assert "Nothing to show yet." in html
    assert "chart-bar" not in html


def test_a_sparkline_carries_a_text_description_of_its_shape() -> None:
    """The line is an image, so it needs words for anyone who cannot see it."""
    html = _engine().get_template("_spark.html").render(
        title="Invoices per week", render_value=render_value,
        spark=spark([3, 9, 5, 14]),
    )
    assert 'role="img"' in html
    assert "from 3 to 14" in html
    assert "low 3, high 14" in html
    assert "<polyline" in html


def test_a_sparkline_with_one_point_explains_itself() -> None:
    """Rather than rendering an empty SVG that looks like a bug."""
    html = _engine().get_template("_spark.html").render(
        title="Too short", render_value=render_value, spark=spark([1])
    )
    assert "Not enough history" in html
    assert "<polyline" not in html
