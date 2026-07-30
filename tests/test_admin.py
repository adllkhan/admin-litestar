"""Admin assembly: gating, login, logout, static assets, and audit calls."""

from litestar import Litestar, get
from litestar.response import Template
from litestar.testing import TestClient

from litestar_admin.admin import CSRF_COOKIE

from .hostapp import FakeAuth, RecordingAudit, build_admin, build_app


def test_admin_gate_refuses_anonymous_and_admits_authenticated() -> None:
    """A gated route rejects an anonymous caller and admits a logged-in one.

    The package ships no model routes yet (``/admin/m/<slug>`` is a later
    task), so ``/admin/logout`` — gated like every route but ``/login`` — is
    what proves ``require_actor`` in both directions. Both calls carry a
    valid CSRF token so the CSRF layer cannot be mistaken for the auth gate.
    """
    with TestClient(app=build_app()) as client:
        client.get("/admin/login")

        anonymous = client.post(
            "/admin/logout",
            data={"_csrf_token": client.cookies.get(CSRF_COOKIE, "")},
            follow_redirects=False,
        )
        assert anonymous.status_code == 401

        login = client.post(
            "/admin/login",
            data={
                "username": "root",
                "password": "hunter2",
                "_csrf_token": client.cookies.get(CSRF_COOKIE, ""),
            },
            follow_redirects=False,
        )
        assert login.status_code in (302, 303)

        authenticated = client.post(
            "/admin/logout",
            data={"_csrf_token": client.cookies.get(CSRF_COOKIE, "")},
            follow_redirects=False,
        )
        assert authenticated.status_code in (302, 303)


def test_login_page_renders_without_a_session() -> None:
    """The login form is reachable and carries a CSRF field."""
    with TestClient(app=build_app()) as client:
        response = client.get("/admin/login")
        assert response.status_code == 200
        assert "password" in response.text
        assert "_csrf_token" in response.text


def test_login_without_a_csrf_token_is_rejected() -> None:
    """Mutating admin routes require a CSRF token."""
    with TestClient(app=build_app()) as client:
        response = client.post(
            "/admin/login",
            data={"username": "root", "password": "hunter2"},
            follow_redirects=False,
        )
        assert response.status_code == 403


def test_valid_credentials_open_a_session_and_are_audited() -> None:
    """A correct login reaches a gated page and records an audit entry."""
    audit = RecordingAudit()
    admin = build_admin(audit=audit)
    with TestClient(app=build_app(admin)) as client:
        client.get("/admin/login")
        response = client.post(
            "/admin/login",
            data={
                "username": "root",
                "password": "hunter2",
                "_csrf_token": client.cookies.get(CSRF_COOKIE, ""),
            },
            follow_redirects=False,
        )
        assert response.status_code in (302, 303)
    assert [entry["action"] for entry in audit.entries] == ["login"]


def test_wrong_credentials_are_audited_as_a_failure() -> None:
    """A rejected login records a failure rather than nothing."""
    audit = RecordingAudit()
    admin = build_admin(auth=FakeAuth(), audit=audit)
    with TestClient(app=build_app(admin)) as client:
        client.get("/admin/login")
        client.post(
            "/admin/login",
            data={
                "username": "root",
                "password": "wrong",
                "_csrf_token": client.cookies.get(CSRF_COOKIE, ""),
            },
            follow_redirects=False,
        )
    assert [entry["action"] for entry in audit.entries] == ["login_failed"]


def test_static_assets_are_served() -> None:
    """The vendored stylesheet and script are reachable."""
    with TestClient(app=build_app()) as client:
        assert client.get("/admin-static/admin.css").status_code == 200
        assert client.get("/admin-static/htmx.min.js").status_code == 200


def test_template_globals_render_live_and_mark_the_active_nav_item() -> None:
    """The engine Litestar actually renders with carries the admin's globals.

    Passing ``TemplateConfig(engine=JinjaTemplateEngine, directory=...)``
    would have Litestar build its own engine on first use — a second
    instance that never saw the globals set here. Rendering through a real
    handler, rather than calling the engine directly, is what proves the
    globals reach the response and that ``request`` is genuinely in scope
    for ``nav.html``'s ``aria-current`` comparison.
    """
    admin = build_admin()

    @get("/admin/m/widget")
    async def widget_page() -> Template:
        return Template("base.html")

    app = Litestar(
        route_handlers=[widget_page], template_config=admin.template_config()
    )
    with TestClient(app=app) as client:
        response = client.get("/admin/m/widget")

    assert response.status_code == 200
    assert "/admin-static/admin.css" in response.text
    before_widgets = response.text.split("Widgets")[0][-120:]
    before_secrets = response.text.split("Secrets")[0][-120:]
    assert "aria-current" in before_widgets
    assert "aria-current" not in before_secrets
