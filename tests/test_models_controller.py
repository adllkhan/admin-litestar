"""Generic model routes: capability gating, unknown slugs and route ordering."""

from types import SimpleNamespace

from litestar import Litestar
from litestar.stores.memory import MemoryStore
from litestar.testing import TestClient

from litestar_admin import Admin, AdminConfig, ModelSpec
from litestar_admin.constants import (
    ACTION_DELETE,
    ACTION_EXPORT,
    DELETE,
    DETAIL,
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

    def __init__(self, row: SimpleNamespace) -> None:
        self._row = row

    def scalars(self) -> "_FakeResult":
        """Return self, mirroring ``Result.scalars()``'s chaining shape."""
        return self

    def all(self) -> list[SimpleNamespace]:
        """Return the one canned row as the full result set."""
        return [self._row]

    def scalar_one_or_none(self) -> SimpleNamespace:
        """Return the canned row, as if it were the sole match."""
        return self._row


class _FakeSession:
    """A stand-in database session that ignores the compiled statement."""

    def __init__(self, row: SimpleNamespace) -> None:
        self.deleted: list[SimpleNamespace] = []
        self._row = row

    async def execute(self, _statement: object) -> _FakeResult:
        """Answer any statement with the same canned row."""
        return _FakeResult(self._row)

    async def delete(self, row: SimpleNamespace) -> None:
        """Record the row as deleted."""
        self.deleted.append(row)


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
) -> tuple[Litestar, _FakeSession]:
    """Build an app hosting one spec that declares every capability."""
    row = SimpleNamespace(id=1, name="Widget A")
    session = _FakeSession(row)
    admin = Admin(
        config=AdminConfig(path="/admin", static_path="/admin-static"),
        specs=[DUAL],
        auth=FakeAuth(),
        audit=audit or RecordingAudit(),
        cache=lambda _request: FakeCache(),
        session_factory=lambda: _FakeSessionScope(session),
    )
    app = Litestar(
        route_handlers=[admin.router(), admin.static_router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
        csrf_config=admin.csrf_config(SECRET_KEY),
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
    """A successful export is recorded in the audit trail."""
    audit = RecordingAudit()
    app, _ = _build_dual_app(audit=audit)
    with TestClient(app=app) as client:
        _logged_in(client)
        client.get("/admin/m/dual/export")
    export_entries = [e for e in audit.entries if e["action"] == ACTION_EXPORT]
    assert len(export_entries) == 1
    assert export_entries[0]["extra"] == {"rows": 1}


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
