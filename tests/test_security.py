"""Fix 3 (secure cookies) and Fix 5 (CSRF scoped to the admin's own path)."""

from __future__ import annotations

import copy

from litestar import Litestar, post
from litestar.stores.memory import MemoryStore
from litestar.testing import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from admin_litestar import Admin, AdminConfig
from admin_litestar.admin import CSRF_COOKIE

from .hostapp import FakeAuth, FakeCache, NullSession, RecordingAudit
from .test_spec import SECRET, WIDGET

SECRET_KEY = "test-secret-key-for-csrf-and-sessions"


def _build_admin(*, secure_cookies: bool) -> Admin:
    """An admin over the throwaway specs, with CSRF enabled."""
    return Admin(
        config=AdminConfig(path="/admin", secure_cookies=secure_cookies),
        specs=[WIDGET, SECRET],
        auth=FakeAuth(),
        audit=RecordingAudit(),
        cache=lambda _request: FakeCache(),
        session_factory=NullSession,
        csrf_secret=SECRET_KEY,
    )


HTTPS_BASE_URL = "https://testserver.local"


def test_session_and_csrf_cookies_are_secure_by_default() -> None:
    """A host that changes nothing gets ``Secure`` on both cookies.

    A stolen session cookie defeats the login gate, the lockout and
    revalidation together, so this is the default a host must opt out of
    rather than opt into. Using an ``https://`` test client (rather than the
    default plain-HTTP one) is what makes this observable at all: a
    ``Secure`` cookie a client received over HTTP would not be sent back on
    the next request, by design, so a login flow run over plain HTTP could
    never even reach the handler that proves the flag was set correctly.
    """
    admin = _build_admin(secure_cookies=True)
    app = Litestar(
        route_handlers=[admin.router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
    )
    with TestClient(app=app, base_url=HTTPS_BASE_URL) as client:
        form = client.get("/admin/login")
        csrf_headers = [h for h in form.headers.get_list("set-cookie") if CSRF_COOKIE in h]
        assert csrf_headers, "no CSRF cookie was set on the login form"
        assert all("secure" in header.lower() for header in csrf_headers)

        login = client.post(
            "/admin/login",
            data={
                "username": "root",
                "password": "hunter2",
                "_csrf_token": client.cookies.get(CSRF_COOKIE, ""),
            },
            follow_redirects=False,
        )
        assert login.status_code in (302, 303), "csrf cookie should round-trip over https"
        session_headers = [
            h for h in login.headers.get_list("set-cookie") if CSRF_COOKIE not in h
        ]
        assert session_headers
        assert all("secure" in header.lower() for header in session_headers)


def test_secure_cookies_can_be_turned_off_for_local_and_test_environments() -> None:
    """The escape hatch actually removes the ``Secure`` attribute."""
    admin = _build_admin(secure_cookies=False)
    app = Litestar(
        route_handlers=[admin.router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
    )
    with TestClient(app=app) as client:
        form = client.get("/admin/login")
        csrf_headers = [h for h in form.headers.get_list("set-cookie") if CSRF_COOKIE in h]
        assert csrf_headers
        assert not any("secure" in header.lower() for header in csrf_headers)


def test_csrf_is_not_enforced_on_a_route_outside_the_admin_router() -> None:
    """A host's own mutating route is unaffected by the admin's CSRF secret.

    This is the defect: an unscoped ``CSRFConfig`` applied app-wide turns
    every other mutating route's rejection into a 403. Attaching
    ``CSRFMiddleware`` to the admin's own gated router instead — rather than
    handing the host a ``CSRFConfig`` for ``Litestar(csrf_config=...)`` —
    means a sibling route never sees it. Running this suite under
    ``-W error`` is also the check that no "middleware is effectively
    disabled" warning fired: an ``exclude`` pattern broad enough to scope
    CSRF to one path trips that warning, and this approach uses no
    ``exclude`` at all.
    """
    admin = _build_admin(secure_cookies=False)

    @post("/outside")
    async def outside() -> str:
        return "ok"

    app = Litestar(
        route_handlers=[outside, admin.router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
    )
    with TestClient(app=app) as client:
        response = client.post("/outside")
    assert response.status_code == 201


def test_csrf_still_rejects_an_admin_route_without_a_token() -> None:
    """The admin's own mutating routes remain protected."""
    admin = _build_admin(secure_cookies=False)
    app = Litestar(
        route_handlers=[admin.router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
    )
    with TestClient(app=app) as client:
        response = client.post("/admin/login", data={"username": "root", "password": "hunter2"})
    assert response.status_code == 403


def test_no_csrf_secret_means_no_csrf_protection_anywhere() -> None:
    """Declining CSRF (``csrf_secret=None``) leaves admin routes unprotected too.

    Documents the consumer's current, deliberate stance rather than asserting
    new behaviour: a host that has not supplied a secret gets none of this.
    """
    admin = Admin(
        config=AdminConfig(path="/admin", secure_cookies=False),
        specs=[WIDGET, SECRET],
        auth=FakeAuth(),
        audit=RecordingAudit(),
        cache=lambda _request: FakeCache(),
        session_factory=NullSession,
    )
    app = Litestar(
        route_handlers=[admin.router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
    )
    with TestClient(app=app) as client:
        response = client.post("/admin/login", data={"username": "root", "password": "hunter2"})
    assert response.status_code != 403


def test_session_factory_survives_the_deep_copy_litestar_performs_on_every_router() -> None:
    """Fix 4 regression: any session-factory shape must survive router registration.

    Litestar deep-copies a ``Router`` whenever one is registered as a
    route handler of another — which happens once inside :meth:`Admin.router`
    itself (nesting the gated router) and again when a host registers the
    returned router into its own app. A bound method whose ``__self__``
    holds a live engine fails that deep-copy; so, less obviously, does a
    bare ``async_sessionmaker`` instance — the very shape ``Admin``'s own
    docstring recommends passing. Both must now survive, because
    ``session_factory`` is wrapped in a plain closure before either
    ``Revalidator`` or the ``admin_session`` dependency ever sees it, and
    ``copy.deepcopy`` treats a plain function as atomic.
    """
    engine = create_async_engine("postgresql+asyncpg://u:p@localhost/db")

    class _Holder:
        def __init__(self, engine: object) -> None:
            self._engine = engine

        def get_session(self) -> object:
            return NullSession()

    for factory in (_Holder(engine).get_session, async_sessionmaker(engine)):
        admin = Admin(
            config=AdminConfig(path="/admin"),
            specs=[WIDGET, SECRET],
            auth=FakeAuth(),
            audit=RecordingAudit(),
            cache=lambda _request: FakeCache(),
            session_factory=factory,
        )
        router = admin.router()  # nests a router inside this one: one deep-copy
        copy.deepcopy(router)  # a host registering it into its own app: a second
