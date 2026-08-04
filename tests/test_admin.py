"""Admin assembly: gating, login, logout, static assets, and audit calls."""

import pytest
from litestar import Litestar, get
from litestar.response import Template
from litestar.testing import TestClient

from admin_litestar import AdminConfig, DETAIL, CustomPage, ModelSpec
from admin_litestar.admin import CSRF_COOKIE
from admin_litestar.constants import THEMES
from admin_litestar.static import STATIC

from .hostapp import FakeAuth, RecordingAudit, build_admin, build_app
from .models import Widget


def _log_in(client: TestClient) -> None:
    """Put the client through a real login, so gated routes admit it."""
    client.get("/admin/login")
    client.post(
        "/admin/login",
        data={
            "username": "root",
            "password": "hunter2",
            "_csrf_token": client.cookies.get(CSRF_COOKIE, ""),
        },
        follow_redirects=False,
    )


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
    """The vendored stylesheet and script are reachable, nested under the admin path."""
    with TestClient(app=build_app()) as client:
        assert client.get("/admin/static/admin.css").status_code == 200
        assert client.get("/admin/static/htmx.min.js").status_code == 200


def test_static_assets_are_unguarded() -> None:
    """An anonymous caller can still fetch the stylesheet: no auth required."""
    with TestClient(app=build_app()) as client:
        response = client.get("/admin/static/admin.css")
    assert response.status_code == 200


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
    assert "/admin/static/admin.css" in response.text
    before_widgets = response.text.split("Widgets")[0][-120:]
    before_secrets = response.text.split("Secrets")[0][-120:]
    assert "aria-current" in before_widgets
    assert "aria-current" not in before_secrets


def test_the_admin_root_redirects_to_the_first_listable_model() -> None:
    """Something must answer at the admin root.

    ``SessionController`` redirects there after a successful login and
    ``nav.html`` points the brand link at it, but no route was ever registered
    for it -- so every host that had not written a landing page of its own sent
    each fresh login to a 404.

    Following the redirect needs a session that can execute a statement, which
    the stand-in here cannot; ``test_models_controller`` follows it end to end.
    """
    with TestClient(app=build_app()) as client:
        _log_in(client)
        response = client.get("/admin/", follow_redirects=False)
    assert response.status_code in (301, 302, 303, 307)
    assert response.headers["location"] == "/admin/m/widget"


def test_the_admin_root_is_gated_like_every_other_page() -> None:
    """The root redirect must not leak which models exist to an anonymous caller."""
    with TestClient(app=build_app()) as client:
        response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 401


def test_a_host_page_at_the_root_wins_over_the_redirect() -> None:
    """A host landing page owns the root, and the admin adds no route beside it.

    Two handlers for one path is a startup error in Litestar, so this asserts
    both that the app builds at all and that the host's page is what answers.
    """
    @get("/", sync_to_thread=False)
    def home() -> Template:
        return Template("base.html")

    page = CustomPage(slug="", label="", group="Things", handlers=[home])
    with TestClient(app=build_app(build_admin(pages=[page]))) as client:
        _log_in(client)
        response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 200
    assert "/admin/static/admin.css" in response.text


def test_a_host_page_declaring_the_root_by_handler_path_also_wins() -> None:
    """Root ownership is read from the handler's path, not the slug alone.

    A host that gives its landing page a slug -- so it appears in the nav --
    while mounting the handler at ``/`` would otherwise collide with the
    admin's own root route and fail to start.
    """
    @get("/", sync_to_thread=False)
    def home() -> Template:
        return Template("base.html")

    page = CustomPage(slug="home", label="Home", group="Things", handlers=[home])
    with TestClient(app=build_app(build_admin(pages=[page]))) as client:
        _log_in(client)
        response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 200


def test_no_listable_spec_means_no_root_route() -> None:
    """With nowhere to send the caller, the root stays a 404 rather than guessing."""
    detail_only = ModelSpec(
        model=Widget,
        slug="widget",
        label="Widgets",
        group="Things",
        list_columns=("id", "name"),
        detail_columns=("id", "name"),
        capabilities=frozenset({DETAIL}),
        order_by="id",
    )
    with TestClient(app=build_app(build_admin(specs=[detail_only]))) as client:
        _log_in(client)
        response = client.get("/admin/", follow_redirects=False)
    assert response.status_code == 404


def test_the_default_theme_links_the_classic_stylesheet() -> None:
    """An unconfigured admin keeps the look it shipped with."""
    with TestClient(app=build_app()) as client:
        response = client.get("/admin/login")
    assert "/admin/static/admin.css" in response.text
    assert "schematic.css" not in response.text


def test_the_schematic_theme_links_and_serves_its_own_stylesheet() -> None:
    """Choosing a theme swaps the stylesheet the shell links, nothing else."""
    admin = build_admin(theme="schematic")
    with TestClient(app=build_app(admin)) as client:
        response = client.get("/admin/login")
        stylesheet = client.get("/admin/static/schematic.css")
    assert "/admin/static/schematic.css" in response.text
    assert "/admin/static/admin.css" not in response.text
    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")


def test_both_themes_are_served_whichever_one_is_configured() -> None:
    """The stylesheets are package data, so either is reachable either way."""
    with TestClient(app=build_app()) as client:
        assert client.get("/admin/static/admin.css").status_code == 200
        assert client.get("/admin/static/schematic.css").status_code == 200


def test_an_unknown_theme_is_refused_by_name() -> None:
    """A typo must fail at construction, not as a 404 on the stylesheet link."""
    with pytest.raises(ValueError, match="unknown theme 'blueprint'") as caught:
        AdminConfig(theme="blueprint")
    assert "classic" in str(caught.value)
    assert "schematic" in str(caught.value)


def test_every_named_theme_resolves_to_a_shipped_file() -> None:
    """A theme a host may name must exist in the package's static directory."""
    for name, filename in THEMES.items():
        assert (STATIC / filename).is_file(), f"{name} names a missing stylesheet"
