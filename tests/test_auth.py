"""Lockout counting, the route guard, and session revalidation."""

import pytest
from litestar.exceptions import NotAuthorizedException

from litestar_admin.auth import (
    Revalidator,
    actor_of,
    clear_failures,
    is_locked,
    register_failure,
    require_actor,
)
from litestar_admin.constants import LOGIN_MAX_ATTEMPTS, SESSION_ACTOR_KEY


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


class _NullSession:
    """Async context manager yielding a placeholder database session."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_exc: object) -> None:
        return None
