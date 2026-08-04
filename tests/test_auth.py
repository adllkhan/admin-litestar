"""Lockout counting, the route guard, and session revalidation."""

import pytest
from litestar.exceptions import NotAuthorizedException
from litestar.testing import TestClient

from admin_litestar.admin import CSRF_COOKIE
from admin_litestar.auth import (
    Revalidator,
    actor_of,
    clear_failures,
    is_locked,
    register_failure,
    require_actor,
    safe_next,
)
from admin_litestar.constants import LOGIN_MAX_ATTEMPTS, SESSION_ACTOR_KEY

from .hostapp import build_app


class _Cache:
    """In-memory CacheBackend with no expiry, sufficient for counting."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    async def get(self, key: str) -> object:
        return self.data.get(key)

    async def set(self, key: str, value: object, ttl: int) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class _Connection:
    """Minimal ASGIConnection stand-in carrying a session dict."""

    def __init__(self, session: dict[str, object]) -> None:
        self.session = session


class _Backend:
    """AuthBackend whose validity answer the test controls."""

    def __init__(self, valid: bool) -> None:
        self.valid = valid
        self.calls = 0

    async def authenticate(self, session, username, password):
        return None

    def identity_of(self, user):
        return user

    async def is_valid(self, session, actor_id) -> bool:
        self.calls += 1
        return self.valid


async def test_lockout_after_max_attempts() -> None:
    """The account locks once the failure count reaches the limit."""
    cache = _Cache()
    assert await is_locked(cache, "admin", "10.0.0.1") is False
    for _ in range(LOGIN_MAX_ATTEMPTS):
        await register_failure(cache, "admin", "10.0.0.1")
    assert await is_locked(cache, "admin", "10.0.0.1") is True


async def test_lockout_is_scoped_per_ip() -> None:
    """Failures from one address do not lock another."""
    cache = _Cache()
    for _ in range(LOGIN_MAX_ATTEMPTS):
        await register_failure(cache, "admin", "10.0.0.1")
    assert await is_locked(cache, "admin", "10.0.0.2") is False


async def test_lockout_is_scoped_per_username() -> None:
    """Failures against one account do not lock another from the same address."""
    cache = _Cache()
    for _ in range(LOGIN_MAX_ATTEMPTS):
        await register_failure(cache, "admin", "10.0.0.1")
    assert await is_locked(cache, "other", "10.0.0.1") is False


async def test_clearing_failures_unlocks() -> None:
    """A successful login resets the counter."""
    cache = _Cache()
    for _ in range(LOGIN_MAX_ATTEMPTS):
        await register_failure(cache, "admin", "10.0.0.1")
    await clear_failures(cache, "admin", "10.0.0.1")
    assert await is_locked(cache, "admin", "10.0.0.1") is False


def test_guard_rejects_sessionless_connections() -> None:
    """No actor in the session means no access."""
    with pytest.raises(NotAuthorizedException):
        require_actor(_Connection({}), None)


def test_guard_allows_a_logged_in_actor() -> None:
    """A session carrying an actor passes, and the actor is readable."""
    connection = _Connection({SESSION_ACTOR_KEY: 4821})
    require_actor(connection, None)
    assert actor_of(connection) == 4821


async def test_revalidator_clears_the_session_when_the_gate_closes() -> None:
    """A de-authorised actor is logged out on the next request."""
    cache = _Cache()
    backend = _Backend(valid=False)
    request = _Connection({SESSION_ACTOR_KEY: 7})
    revalidate = Revalidator(backend, lambda: _NullSession(), lambda _r: cache)
    with pytest.raises(NotAuthorizedException):
        await revalidate(request)
    assert request.session == {}


async def test_revalidator_caches_a_positive_answer() -> None:
    """A valid actor is not re-queried on every request."""
    cache = _Cache()
    backend = _Backend(valid=True)
    request = _Connection({SESSION_ACTOR_KEY: 7})
    revalidate = Revalidator(backend, lambda: _NullSession(), lambda _r: cache)
    await revalidate(request)
    await revalidate(request)
    assert backend.calls == 1


async def test_revalidator_ignores_anonymous_requests() -> None:
    """With no actor in session there is nothing to revalidate."""
    backend = _Backend(valid=False)
    revalidate = Revalidator(backend, lambda: _NullSession(), lambda _r: _Cache())
    await revalidate(_Connection({}))
    assert backend.calls == 0


def test_guard_allows_actor_id_zero() -> None:
    """A legitimate actor id of 0 is not treated as absent."""
    connection = _Connection({SESSION_ACTOR_KEY: 0})
    require_actor(connection, None)
    assert actor_of(connection) == 0


async def test_revalidator_consults_backend_for_actor_id_zero() -> None:
    """An actor id of 0 triggers revalidation, not early return."""
    cache = _Cache()
    backend = _Backend(valid=True)
    request = _Connection({SESSION_ACTOR_KEY: 0})
    revalidate = Revalidator(backend, lambda: _NullSession(), lambda _r: cache)
    await revalidate(request)
    assert backend.calls == 1


class _NullSession:
    """Async context manager yielding a placeholder database session."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_exc: object) -> None:
        return None


def test_a_browser_hitting_a_gated_page_is_sent_to_the_login_form() -> None:
    """A page request must land on the form, not on a bare 401.

    The guard raises ``NotAuthorizedException`` for every caller alike, which
    Litestar renders as a 401 body -- so an admin opening the bookmarked root in
    a browser saw an error page and no way to log in. Observed: the request is
    redirected to the login form, carrying where it was headed.
    """
    with TestClient(app=build_app()) as client:
        response = client.get(
            "/admin/m/widget", headers={"accept": "text/html"}, follow_redirects=False
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login?next=/admin/m/widget"


def test_the_login_redirect_keeps_the_query_string() -> None:
    """A deep link with search and filters returns to the same view."""
    with TestClient(app=build_app()) as client:
        response = client.get(
            "/admin/m/widget?search=one&kind=alpha",
            headers={"accept": "text/html"},
            follow_redirects=False,
        )
    assert response.headers["location"] == (
        "/admin/login?next=/admin/m/widget%3Fsearch%3Done%26kind%3Dalpha"
    )


def test_an_htmx_request_gets_a_redirect_header_not_a_body() -> None:
    """A 401 body would be swapped into the page as though it were content."""
    with TestClient(app=build_app()) as client:
        response = client.get(
            "/admin/m/widget",
            headers={"accept": "text/html", "HX-Request": "true"},
            follow_redirects=False,
        )
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/admin/login"
    assert response.text == ""


def test_a_non_browser_caller_still_gets_a_plain_401() -> None:
    """Scripts and probes keep the status they expect."""
    with TestClient(app=build_app()) as client:
        response = client.get(
            "/admin/m/widget",
            headers={"accept": "application/json"},
            follow_redirects=False,
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_the_login_form_carries_a_validated_next_field() -> None:
    """The destination survives the round trip through the form."""
    with TestClient(app=build_app()) as client:
        good = client.get("/admin/login?next=/admin/m/widget")
        assert 'name="next" value="/admin/m/widget"' in good.text

        hostile = client.get("/admin/login?next=https://evil.example/steal")
        assert 'name="next"' not in hostile.text


@pytest.mark.parametrize(
    "candidate",
    [
        "https://evil.example/steal",
        "//evil.example/steal",
        "/etc/passwd",
        "/admin/../../outside",
        "\\\\evil.example",
        "/adminlookalike/page",
        "/admin/login",
    ],
)
def test_login_refuses_to_redirect_outside_the_admin(candidate: str) -> None:
    """A post-login destination is only ever a path inside this admin.

    ``next`` arrives from a query string, so anyone who can get an admin to
    click a link can propose a destination. Anything not under the admin's mount
    point -- absolute, protocol-relative, backslash-obfuscated, or a sibling
    path that merely starts with the same characters -- falls back to the root.
    ``/admin/login`` itself is refused because it would loop.
    """
    with TestClient(app=build_app()) as client:
        client.get("/admin/login")
        response = client.post(
            "/admin/login",
            data={
                "username": "root",
                "password": "hunter2",
                "next": candidate,
                "_csrf_token": client.cookies.get(CSRF_COOKIE, ""),
            },
            follow_redirects=False,
        )
    assert response.status_code in (302, 303)
    assert response.headers["location"] == "/admin/"


def test_login_honours_a_destination_inside_the_admin() -> None:
    """A legitimate ``next`` is where the caller lands."""
    with TestClient(app=build_app()) as client:
        client.get("/admin/login")
        response = client.post(
            "/admin/login",
            data={
                "username": "root",
                "password": "hunter2",
                "next": "/admin/m/widget?search=one",
                "_csrf_token": client.cookies.get(CSRF_COOKIE, ""),
            },
            follow_redirects=False,
        )
    assert response.headers["location"] == "/admin/m/widget?search=one"


@pytest.mark.parametrize(
    "candidate", ["/admin/%2e%2e/outside", "/admin/%2E%2E%2Foutside"]
)
def test_encoded_dot_segments_are_refused_too(candidate: str) -> None:
    """An encoded traversal normalises the same way an unencoded one does."""
    assert safe_next(candidate, "/admin") is None


def test_safe_next_accepts_the_admin_root_and_its_children() -> None:
    """The allowed shapes, stated positively."""
    assert safe_next("/admin", "/admin") == "/admin"
    assert safe_next("/admin/", "/admin") == "/admin/"
    assert safe_next("/admin/m/widget", "/admin") == "/admin/m/widget"
    assert safe_next("/admin/m/widget?a=1", "/admin") == "/admin/m/widget?a=1"
    assert safe_next(None, "/admin") is None
    assert safe_next("", "/admin") is None
