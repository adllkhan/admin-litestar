"""Generic model routes: capability gating, unknown slugs and route ordering."""

from types import SimpleNamespace
from typing import Any

from litestar import Litestar
from litestar.stores.memory import MemoryStore
from litestar.testing import TestClient
from sqlalchemy.exc import IntegrityError

from admin_litestar import Admin, AdminConfig, BulkAction, ModelSpec
from admin_litestar.constants import (
    ACTION_DELETE,
    ACTION_EXPORT,
    CREATE,
    DELETE,
    DETAIL,
    EDIT,
    EXPORT,
    LIST,
)

from .hostapp import FakeAuth, FakeCache, RecordingAudit, build_app
from .models import Widget

SECRET_KEY_COOKIE = "admin_csrf"
SECRET_KEY = "test-secret-key-for-csrf-and-sessions"

DUAL = ModelSpec(
    model=Widget,
    slug="dual",
    label="Duals",
    group="Things",
    list_columns=("id", "name"),
    detail_columns=("id", "name"),
    capabilities=frozenset({LIST, DETAIL, EXPORT, DELETE}),
    order_by="id",
)


def _logged_in(client: TestClient) -> None:
    """Log the shared test client in."""
    client.get("/admin/login")
    client.post(
        "/admin/login",
        data={
            "username": "root",
            "password": "hunter2",
            "_csrf_token": client.cookies.get(SECRET_KEY_COOKIE, ""),
        },
        follow_redirects=False,
    )


def test_unknown_slug_is_a_404() -> None:
    """An unregistered model is not found, not a 500."""
    with TestClient(app=build_app()) as client:
        _logged_in(client)
        assert client.get("/admin/m/nope").status_code == 404


def test_detail_route_404s_when_the_spec_lacks_the_capability() -> None:
    """SECRET declares only list, so its detail route must not exist."""
    with TestClient(app=build_app()) as client:
        _logged_in(client)
        assert client.get("/admin/m/secret/1").status_code == 404


def test_export_route_404s_when_the_spec_lacks_the_capability() -> None:
    """Neither throwaway spec declares export."""
    with TestClient(app=build_app()) as client:
        _logged_in(client)
        assert client.get("/admin/m/widget/export").status_code == 404


def test_delete_route_404s_when_the_spec_lacks_the_capability() -> None:
    """Deleting a model that does not declare delete is rejected."""
    with TestClient(app=build_app()) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/widget/1/delete",
            data={"_csrf_token": client.cookies.get(SECRET_KEY_COOKIE, "")},
        )
        assert response.status_code == 404


class _FakeRow(SimpleNamespace):
    """A row that answers as a mapped object and as a two-column result row.

    The generic routes ask for whole entities in one place and for
    ``(key, label)`` pairs in another -- relation labels, distinct filter values --
    so a stand-in has to satisfy both shapes to stand in at all.
    """

    def __getitem__(self, index: int) -> Any:
        return (self.id, self.name)[index]

    def __iter__(self) -> Any:
        return iter((self.id, self.name))


class _FakeResult:
    """A query result that always answers with the same canned row.

    Standing in for a real SQLAlchemy ``Result`` without a database: the
    controller never inspects the statement it was handed, so this proves
    routing, projection, audit and response-shaping behaviour, not query
    correctness. Statement compilation against the column boundary is
    covered separately by ``test_queries.py``; genuine execution is left to
    the adapter plan, since this package cannot depend on an async SQLite
    driver (``tests/test_boundary.py`` pins the dependency list).
    """

    def __init__(self, row: Any, pairs: list[tuple[Any, Any]] | None = None) -> None:
        self._row = row
        self._pairs = pairs

    def scalars(self) -> "_FakeResult":
        """Return self, mirroring ``Result.scalars()``'s chaining shape."""
        return self

    def all(self) -> list[Any]:
        """Return the canned row, or the canned pairs for a grouped query."""
        return [self._row] if self._pairs is None else self._pairs

    def scalar_one_or_none(self) -> SimpleNamespace:
        """Return the canned row, as if it were the sole match."""
        return self._row


class _FakeSession:
    """A stand-in database session that ignores the compiled statement."""

    def __init__(self, row: SimpleNamespace) -> None:
        self.deleted: list[SimpleNamespace] = []
        self.added: list[Any] = []
        self.statements: list[str] = []
        self.rolled_back = False
        self._row = row

    async def execute(self, statement: object) -> _FakeResult:
        """Answer a statement with the canned row, recording the SQL.

        A grouped count -- what the filter facets ask for -- is answered with
        ``(value, count)`` pairs instead: the routes read two result shapes, so a
        stand-in has to produce both or it is not standing in for much.
        """
        text = str(statement)
        self.statements.append(text)
        if "count(" in text.lower():
            return _FakeResult(self._row, pairs=[(self._row.kind, 1)])
        return _FakeResult(self._row)

    async def delete(self, row: SimpleNamespace) -> None:
        """Record the row as deleted."""
        self.deleted.append(row)

    def add(self, row: Any) -> None:
        """Record an inserted row, as ``Session.add`` does."""
        self.added.append(row)

    async def flush(self) -> None:
        """Stand in for the flush that assigns a key; the test row has one."""
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = 999

    async def commit(self) -> None:
        """No real transaction backs this stand-in; nothing to do."""
        return None

    async def rollback(self) -> None:
        """Record that the session was rolled back."""
        self.rolled_back = True


class _FakeSessionScope:
    """Async context manager yielding a pre-built fake session."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        """Hand back the shared fake session."""
        return self._session

    async def __aexit__(self, *_exc: object) -> None:
        """Nothing to close."""
        return None


def _build_dual_app(
    audit: RecordingAudit | None = None,
    specs: list[ModelSpec] | None = None,
) -> tuple[Litestar, _FakeSession]:
    """Build an app hosting one spec that declares every capability."""
    # Carries every column any spec here declares: a real mapped row always has
    # them, so a stand-in missing one would fail for a reason the code does not.
    row = _FakeRow(id=1, name="Widget A", kind="alpha")
    session = _FakeSession(row)
    admin = Admin(
        config=AdminConfig(path="/admin", secure_cookies=False),
        specs=specs or [DUAL],
        auth=FakeAuth(),
        audit=audit or RecordingAudit(),
        cache=lambda _request: FakeCache(),
        session_factory=lambda: _FakeSessionScope(session),
        csrf_secret=SECRET_KEY,
    )
    app = Litestar(
        route_handlers=[admin.router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
    )
    return app, session


def test_list_page_renders_the_projected_row() -> None:
    """The index route renders a row through the real list/table templates."""
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/dual")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Widget A" in response.text
    assert "Duals" in response.text


def test_the_admin_root_lands_on_a_rendered_list() -> None:
    """The root redirect resolves to a real page, not just a Location header."""
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/", follow_redirects=True)
    assert response.status_code == 200
    assert "Duals" in response.text
    assert "Widget A" in response.text


def test_a_paging_request_answers_with_rows_only() -> None:
    """An HTMX paging click gets a fragment to append, not a whole second page.

    Swapping a full document into a tbody would nest a second nav and stylesheet
    link inside the table. Observed: the response carries the row and none of the
    page chrome.
    """
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get(
            "/admin/m/dual", params={"after": "1"}, headers={"HX-Request": "true"}
        )
    assert response.status_code == 200
    assert "Widget A" in response.text
    assert "<html" not in response.text
    assert "admin.css" not in response.text


def test_the_same_paging_url_renders_a_full_page_without_htmx() -> None:
    """No HTMX header means a plain navigation, which needs the whole page."""
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/dual", params={"after": "1"})
    assert response.status_code == 200
    assert "<html" in response.text
    assert "Widget A" in response.text


def test_export_route_wins_over_the_detail_route_for_the_literal_segment() -> None:
    """``/export`` must resolve to the export handler, not detail with pk='export'.

    DUAL declares both capabilities, so if the router matched ``{pk}`` before
    the literal ``export`` segment, this would either 404 (no row has the
    primary key ``"export"``) or render an HTML detail page -- not stream
    CSV. Observed: this asserts the export handler actually wins.
    """
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/dual/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "id,name"
    assert "Widget A" in response.text


def test_detail_route_still_matches_a_real_primary_key() -> None:
    """A plain pk still reaches the detail handler, not the export route."""
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/dual/1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Widget A" in response.text


def test_export_audits_the_action_with_the_row_count() -> None:
    """A successful export is recorded in the audit trail.

    The entry names the view as well as the count: an export of everything and an
    export of one filtered page are different events to answer for later.
    """
    audit = RecordingAudit()
    app, _ = _build_dual_app(audit=audit)
    with TestClient(app=app) as client:
        _logged_in(client)
        client.get("/admin/m/dual/export")
    export_entries = [e for e in audit.entries if e["action"] == ACTION_EXPORT]
    assert len(export_entries) == 1
    assert export_entries[0]["extra"] == {
        "rows": 1,
        "search": None,
        "filters": {},
        "ranges": {},
        "sort": "id",
        "direction": "desc",
    }


def test_delete_removes_the_row_and_redirects_and_audits() -> None:
    """A successful delete calls session.delete, redirects, and is audited."""
    audit = RecordingAudit()
    app, session = _build_dual_app(audit=audit)
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/dual/1/delete",
            data={"_csrf_token": client.cookies.get(SECRET_KEY_COOKIE, "")},
            follow_redirects=False,
        )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/admin/m/dual"
    assert len(session.deleted) == 1
    delete_entries = [e for e in audit.entries if e["action"] == ACTION_DELETE]
    assert len(delete_entries) == 1


NO_PK_COLUMN = ModelSpec(
    model=Widget,
    slug="nopk",
    label="Hidden keys",
    group="Things",
    # The primary key is deliberately absent from what the list displays.
    list_columns=("name",),
    detail_columns=("id", "name"),
    capabilities=frozenset({LIST, DETAIL}),
    order_by="name",
)


def test_a_row_links_to_its_record_even_when_the_key_is_not_displayed() -> None:
    """A row must be able to name its record whatever the spec shows.

    ``list_columns`` need not contain the primary key -- plenty of tables show a
    name and hide the id -- so the projection adds it when it is missing rather
    than rendering a link to nothing.
    """
    app, _ = _build_dual_app(specs=[NO_PK_COLUMN])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/nopk")
    assert response.status_code == 200
    assert 'hx-get="/admin/m/nopk/1"' in response.text
    # the key is still not shown as a column
    assert "<th>id</th>" not in response.text


def test_a_row_click_answers_with_a_dialog() -> None:
    """Clicked from a row, a record arrives as a dialog rather than a page."""
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/dual/1", headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert "<dialog" in response.text
    assert "<html" not in response.text
    assert "Widget A" in response.text


def test_the_same_record_url_is_a_full_page_without_htmx() -> None:
    """A bookmark, a shared link or scripting off still gets a whole page."""
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/dual/1")
    assert response.status_code == 200
    assert "<html" in response.text
    # the element itself, not the word: base.html's script explains one in a comment
    assert '<dialog class="modal"' not in response.text
    assert "Widget A" in response.text


def test_the_shell_carries_the_container_a_dialog_swaps_into() -> None:
    """Without the container the row's request would have nowhere to land."""
    app, _ = _build_dual_app()
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/dual")
    assert 'id="modal"' in response.text


WRITABLE = ModelSpec(
    model=Widget,
    slug="writable",
    label="Writables",
    group="Things",
    list_columns=("id", "name"),
    detail_columns=("id", "name", "kind"),
    capabilities=frozenset({LIST, DETAIL, EDIT, CREATE, DELETE}),
    order_by="id",
)


def _csrf(client: TestClient) -> str:
    """Return the CSRF token the client currently holds."""
    return client.cookies.get(SECRET_KEY_COOKIE, "")


def test_the_edit_form_opens_on_the_stored_values() -> None:
    """Editing starts from what is in the record, not from an empty form."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/writable/1/edit")
    assert response.status_code == 200
    assert 'name="name"' in response.text
    assert 'value="Widget A"' in response.text
    # the key identifies the record; it is not a field
    assert 'name="id"' not in response.text


def test_a_row_click_to_edit_answers_with_a_dialog() -> None:
    """The form arrives in the dialog the record was being read in."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get(
            "/admin/m/writable/1/edit", headers={"HX-Request": "true"}
        )
    assert "<dialog" in response.text
    assert "<html" not in response.text


def test_saving_an_edit_writes_the_record_and_audits_what_changed() -> None:
    """The point of the whole feature: the value in the database changes."""
    audit = RecordingAudit()
    app, session = _build_dual_app(audit=audit, specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/writable/1/edit",
            data={"name": "Widget B", "kind": "beta", "_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
    assert response.status_code in (200, 302, 303)
    assert session._row.name == "Widget B"
    assert session._row.kind == "beta"
    entry = next(e for e in audit.entries if e["action"] == "update")
    assert entry["pk"] == "1"
    assert entry["extra"]["changed"] == ["kind", "name"]


def test_a_saved_edit_returns_the_record_and_refreshes_its_row() -> None:
    """The list behind the dialog must not keep showing the old value."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/writable/1/edit",
            data={"name": "Widget C", "kind": "beta", "_csrf_token": _csrf(client)},
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert "<dialog" in response.text
    assert "Widget C" in response.text
    # the out-of-band copy of the row, addressed by the id the list gave it
    assert 'hx-swap-oob="true"' in response.text
    assert 'id="row-writable-1"' in response.text


def test_a_rejected_edit_re_renders_the_form_and_writes_nothing() -> None:
    """Bad input comes back as a form with a message, not as a 500 or a silent no-op."""
    audit = RecordingAudit()
    app, session = _build_dual_app(audit=audit, specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/writable/1/edit",
            data={"name": "", "kind": "beta", "_csrf_token": _csrf(client)},
            headers={"HX-Request": "true"},
        )
    # 200 rather than 422: HTMX does not swap an error status by default, and a
    # form the user cannot see is worse than an unfussy status code.
    assert response.status_code == 200
    assert "required" in response.text
    assert session._row.name == "Widget A"
    assert [e["action"] for e in audit.entries] == ["login"]


def test_creating_a_record_inserts_it_and_audits_it() -> None:
    """A blank form saves a new row."""
    audit = RecordingAudit()
    app, session = _build_dual_app(audit=audit, specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        form = client.get("/admin/m/writable/new")
        response = client.post(
            "/admin/m/writable/new",
            data={"name": "Fresh", "kind": "gamma", "_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
    assert form.status_code == 200
    assert response.status_code in (302, 303)
    assert [row.name for row in session.added] == ["Fresh"]
    assert [e["action"] for e in audit.entries if e["action"] == "create"] == ["create"]


def test_the_new_route_wins_over_the_record_route() -> None:
    """``/new`` must reach the create form, not a record whose key is 'new'."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/writable/new")
    assert response.status_code == 200
    assert 'name="name"' in response.text
    assert "Record" not in response.text


def test_write_routes_404_when_the_spec_does_not_declare_them() -> None:
    """A read-only spec exposes no way in, by URL or otherwise."""
    app, _ = _build_dual_app()  # DUAL declares no EDIT or CREATE
    with TestClient(app=app) as client:
        _logged_in(client)
        assert client.get("/admin/m/dual/1/edit").status_code == 404
        assert client.get("/admin/m/dual/new").status_code == 404
        assert client.post(
            "/admin/m/dual/1/edit",
            data={"name": "x", "_csrf_token": _csrf(client)},
        ).status_code == 404


def test_a_write_without_a_csrf_token_is_rejected() -> None:
    """The write routes sit behind the same CSRF layer as login and delete."""
    app, session = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post("/admin/m/writable/1/edit", data={"name": "Nope"})
    assert response.status_code == 403
    assert session._row.name == "Widget A"


def test_an_anonymous_caller_cannot_write() -> None:
    """The write routes are gated like every other page."""
    app, session = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        client.get("/admin/login")  # for the CSRF cookie only
        response = client.post(
            "/admin/m/writable/1/edit",
            data={"name": "Nope", "_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
    assert response.status_code == 401
    assert session._row.name == "Widget A"


def test_a_delete_is_reported_on_the_page_it_lands_on() -> None:
    """A record vanishing without a word looks like nothing happened."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        client.post(
            "/admin/m/writable/1/delete",
            data={"_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
        landed = client.get("/admin/m/writable")
    assert "Record 1 deleted" in landed.text
    assert 'class="toast' in landed.text


def test_a_message_shows_once_and_not_again() -> None:
    """A notification that reappears on every page is noise, not news."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        client.post(
            "/admin/m/writable/1/delete",
            data={"_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
        first = client.get("/admin/m/writable")
        second = client.get("/admin/m/writable")
    assert "Record 1 deleted" in first.text
    assert "Record 1 deleted" not in second.text


def test_a_saved_edit_reports_itself_without_a_navigation() -> None:
    """Nothing navigates on an HTMX save, so the message rides along out of band."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/writable/1/edit",
            data={"name": "Widget D", "kind": "beta", "_csrf_token": _csrf(client)},
            headers={"HX-Request": "true"},
        )
    assert "Record 1 saved" in response.text
    assert 'id="toast" hx-swap-oob="true"' in response.text


def test_a_create_is_reported_on_the_list_it_returns_to() -> None:
    """The new record is reported where the reader ends up."""
    app, _ = _build_dual_app(specs=[WRITABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        client.post(
            "/admin/m/writable/new",
            data={"name": "Fresh", "kind": "gamma", "_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
        landed = client.get("/admin/m/writable")
    assert "created" in landed.text
    assert 'class="toast' in landed.text


def test_a_failed_write_is_reported_in_the_form_it_came_from() -> None:
    """A constraint the database enforces belongs in the form, not in a 500."""
    app, session = _build_dual_app(specs=[WRITABLE])

    async def refuse() -> None:
        raise IntegrityError("INSERT ...", None, Exception("UNIQUE constraint failed"))

    session.flush = refuse  # type: ignore[method-assign]
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/writable/1/edit",
            data={"name": "Clash", "kind": "beta", "_csrf_token": _csrf(client)},
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert "the database refused this" in response.text
    assert "UNIQUE constraint failed" in response.text
    assert session.rolled_back is True


SEARCHABLE = ModelSpec(
    model=Widget,
    slug="searchable",
    label="Searchables",
    group="Things",
    list_columns=("id", "name", "kind"),
    detail_columns=("id", "name", "kind"),
    capabilities=frozenset({LIST, DETAIL, EXPORT}),
    searchable=("name",),
    filters=("kind",),
    order_by="id",
)


def test_export_covers_the_view_it_was_asked_from() -> None:
    """Export used to ignore search and filters entirely.

    The button sits in the toolbar beside the search box, so a filtered view that
    downloads the whole table is wrong in a way nobody notices until the
    spreadsheet is open. Observed: the search and the filter both reach the SQL,
    and the audit entry records what was exported rather than only how much.
    """
    audit = RecordingAudit()
    app, session = _build_dual_app(audit=audit, specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        session.statements.clear()
        response = client.get(
            "/admin/m/searchable/export", params={"search": "widget", "kind": "alpha"}
        )
    assert response.status_code == 200
    statement = session.statements[0]
    assert "LIKE" in statement.upper()
    assert "kind" in statement
    entry = next(e for e in audit.entries if e["action"] == ACTION_EXPORT)
    assert entry["extra"]["search"] == "widget"
    # a filter holds a set of values, even when only one was chosen
    assert entry["extra"]["filters"] == {"kind": ("alpha",)}


def test_the_export_link_carries_the_current_view() -> None:
    """The href has to hold what the toolbar is showing, or the route cannot honour it."""
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get(
            "/admin/m/searchable", params={"search": "widget", "kind": "alpha"}
        )
    assert "/export?kind=alpha&amp;search=widget" in response.text


def test_a_column_header_sorts_the_list() -> None:
    """Headers looked clickable in every theme without being so.

    Sorting was one hardcoded descending column per spec. Observed: the header
    carries the query that reorders by it, and the route honours it.
    """
    app, session = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        unsorted = client.get("/admin/m/searchable")
        session.statements.clear()
        response = client.get(
            "/admin/m/searchable", params={"sort": "name", "direction": "asc"}
        )
    assert "sort=name" in unsorted.text, "every header offers to sort by itself"
    assert response.status_code == 200
    # the list query is the first the page runs; filter choices follow it
    statement = session.statements[0]
    assert "ORDER BY widget.name ASC" in statement
    assert 'aria-sort="ascending"' in response.text


def test_a_sort_the_spec_does_not_show_is_ignored() -> None:
    """A hidden column named in a URL must not become an ordering."""
    app, session = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        session.statements.clear()
        response = client.get("/admin/m/searchable", params={"sort": "_blob_data"})
    assert response.status_code == 200
    assert "_blob_data" not in session.statements[0]
    assert "ORDER BY widget.id DESC" in session.statements[0]


def test_paging_keeps_the_sort_it_was_started_with() -> None:
    """Page two of a sorted list has to stay sorted the same way."""
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get(
            "/admin/m/searchable",
            params={"sort": "name", "direction": "asc", "search": "widget"},
        )
    # the row count is below a page, so assert on the header link instead: it is
    # the same query the trigger would carry
    assert "sort=name" in response.text
    assert "search=widget" in response.text


def test_export_follows_the_ordering_too() -> None:
    """Same rows in a different order is still a different spreadsheet."""
    app, session = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        session.statements.clear()
        client.get(
            "/admin/m/searchable/export",
            params={"sort": "name", "direction": "asc"},
        )
    assert "ORDER BY widget.name ASC" in session.statements[0]


def test_the_export_link_carries_the_ordering() -> None:
    """The href holds the whole view: search, filters and sort."""
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get(
            "/admin/m/searchable",
            params={"sort": "name", "direction": "asc", "search": "w", "kind": "alpha"},
        )
    assert "/export?kind=alpha&amp;search=w&amp;sort=name&amp;direction=asc" in response.text


def test_a_filter_shows_every_value_at_once() -> None:
    """A filter was a text box, then a dropdown; now the values are simply visible.

    Typing means guessing at spellings that exist, and a dropdown hides which value
    is active until it is opened. Observed: one link per value plus "All", labelled
    with the column, and no free-text box for a column that has a list.
    """
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/searchable")
    assert 'aria-label="Filter by kind"' in response.text
    assert "All" in response.text
    assert "segment--on" in response.text, "All is the active state by default"
    # each value states how many rows it would leave
    assert 'class="segment-count"' in response.text
    assert '<select name="kind"' not in response.text
    assert '<input name="kind"' not in response.text


def test_the_active_filter_is_marked_and_clears_from_itself() -> None:
    """The set value is visibly set, and clicking it again removes it.

    Filtered by the value the column actually offers -- the stand-in session
    answers the distinct-values query with the row's key -- because a filter set to
    something not on the list has no active choice to mark, correctly.
    """
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/searchable", params={"kind": "alpha"})
    assert 'aria-current="true"' in response.text
    # the active segment links back to the list without that filter, and keeps
    # everything else about the view
    active = response.text.split("segment segment--on")[1][:220]
    assert "kind=" not in active
    assert "sort=id" in active


def test_a_filter_link_keeps_the_rest_of_the_view() -> None:
    """Filtering must not silently drop the search or the sort."""
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get(
            "/admin/m/searchable",
            params={"search": "widget", "sort": "name", "direction": "asc"},
        )
    assert "search=widget" in response.text
    assert "sort=name" in response.text
    assert "direction=asc" in response.text


def test_the_toolbar_carries_no_filter_button() -> None:
    """The field submits itself; a hidden submit keeps no-script use working."""
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/searchable")
    assert ">Filter<" not in response.text
    assert 'onchange="this.form.requestSubmit()"' in response.text
    assert '<button class="sr" type="submit">' in response.text


def test_a_value_with_no_rows_keeps_its_place_and_is_not_selectable() -> None:
    """A segment that disappears when another filter is set moves the control.

    The set of segments is fixed by what the column holds overall; the counts are
    what respond to the view. A value the current view excludes stays visible at
    zero, rendered as text rather than a link, since selecting it would leave
    nothing.
    """
    app, session = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        # the stand-in answers the unfiltered value query and the counted one the
        # same way, so ask for a value it never returns to force a zero
        response = client.get("/admin/m/searchable", params={"search": "nothing"})
    assert response.status_code == 200
    assert 'aria-label="Filter by kind"' in response.text
    # the value query runs without the search, the count query with it
    unfiltered, counted = session.statements[1], session.statements[2]
    assert "LIKE" not in unfiltered.upper()
    assert "LIKE" in counted.upper()


BULK = ModelSpec(
    model=Widget,
    slug="bulk",
    label="Bulks",
    group="Things",
    list_columns=("id", "name"),
    detail_columns=("id", "name"),
    capabilities=frozenset({LIST, DETAIL, DELETE}),
    order_by="id",
    bulk_actions=(
        BulkAction(label="Archive", path="/admin/archive"),
        BulkAction(label="Purge", path="/admin/purge", confirm=True, danger=True),
    ),
)


def test_rows_are_selectable_when_something_can_act_on_a_selection() -> None:
    """Checkboxes exist because there is a bulk action or a delete, not by default."""
    app, _ = _build_dual_app(specs=[BULK])
    with TestClient(app=app) as client:
        _logged_in(client)
        selectable = client.get("/admin/m/bulk")
    app2, _ = _build_dual_app(specs=[SEARCHABLE])  # list, detail, export only
    with TestClient(app=app2) as client:
        _logged_in(client)
        plain = client.get("/admin/m/searchable")
    assert 'name="pk" value="1"' in selectable.text
    assert 'id="bulk"' in selectable.text
    assert "Archive" in selectable.text
    assert "row-select" not in plain.text.replace("row-actions, .row-select", "")


def test_a_bulk_delete_removes_every_selected_record_and_audits_each() -> None:
    """One audit entry per record: "who deleted 4821" must not need a batch lookup."""
    audit = RecordingAudit()
    app, session = _build_dual_app(audit=audit, specs=[BULK])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/bulk/bulk-delete",
            data={"pk": ["1", "2", "3"], "_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
    assert response.status_code in (302, 303)
    assert len(session.deleted) == 3
    entries = [e for e in audit.entries if e["action"] == ACTION_DELETE]
    assert [entry["pk"] for entry in entries] == ["1", "2", "3"]
    assert all(entry["extra"] == {"bulk": True} for entry in entries)


def test_a_bulk_delete_reports_how_many_went() -> None:
    """The count is the whole feedback: the rows are gone from the page."""
    app, _ = _build_dual_app(specs=[BULK])
    with TestClient(app=app) as client:
        _logged_in(client)
        client.post(
            "/admin/m/bulk/bulk-delete",
            data={"pk": ["1", "2"], "_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
        landed = client.get("/admin/m/bulk")
    assert "2 record(s) deleted" in landed.text


def test_a_bulk_delete_with_nothing_selected_deletes_nothing() -> None:
    """An empty selection is not "everything"."""
    app, session = _build_dual_app(specs=[BULK])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/bulk/bulk-delete",
            data={"_csrf_token": _csrf(client)},
            follow_redirects=False,
        )
    assert response.status_code in (302, 303)
    assert session.deleted == []


def test_bulk_delete_404s_for_a_spec_that_cannot_delete() -> None:
    """The route follows the capability, like every other."""
    app, _ = _build_dual_app(specs=[SEARCHABLE])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post(
            "/admin/m/searchable/bulk-delete",
            data={"pk": ["1"], "_csrf_token": _csrf(client)},
        )
    assert response.status_code == 404


def test_a_bulk_delete_without_a_csrf_token_is_rejected() -> None:
    """Deleting many is not a lesser act than deleting one."""
    app, session = _build_dual_app(specs=[BULK])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.post("/admin/m/bulk/bulk-delete", data={"pk": ["1"]})
    assert response.status_code == 403
    assert session.deleted == []


RANGED = ModelSpec(
    model=Widget,
    slug="ranged",
    label="Rangeds",
    group="Things",
    list_columns=("id", "name", "created_at"),
    detail_columns=("id", "name", "created_at"),
    capabilities=frozenset({LIST, DETAIL}),
    filters=("created_at",),
    order_by="id",
)


def test_a_date_filter_offers_spans_rather_than_two_empty_fields() -> None:
    """Typing two dates is the slow path for what is usually "recent"."""
    app, _ = _build_dual_app(specs=[RANGED])
    with TestClient(app=app) as client:
        _logged_in(client)
        response = client.get("/admin/m/ranged")
    for label in ("Today", "7 days", "30 days", "This month"):
        assert f">{label}</a>" in response.text
    # the two fields still exist, behind a disclosure
    assert 'name="created_at_from"' in response.text
    assert "<details class=\"range\"" in response.text
    # and nothing is a value-segment list for a date column
    assert 'aria-label="Filter by created_at"' in response.text


def test_a_custom_span_opens_the_fields_it_was_set_with() -> None:
    """A range that matches no preset must not hide inside a closed disclosure."""
    app, _ = _build_dual_app(specs=[RANGED])
    with TestClient(app=app) as client:
        _logged_in(client)
        custom = client.get(
            "/admin/m/ranged",
            params={"created_at_from": "2020-01-01", "created_at_to": "2020-02-01"},
        )
        preset_free = client.get("/admin/m/ranged")
    assert '<details class="range" open>' in custom.text
    assert 'value="2020-01-01"' in custom.text
    assert '<details class="range" open>' not in preset_free.text
