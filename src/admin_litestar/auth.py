"""Session gating, revalidation, and login lockout."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from litestar.exceptions import NotAuthorizedException

from .constants import (
    EXCLUDE_FROM_AUTH_KEY,
    LOGIN_LOCK_TTL,
    LOGIN_MAX_ATTEMPTS,
    REVALIDATE_TTL,
    SESSION_ACTOR_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from litestar.connection import ASGIConnection
    from litestar.handlers.base import BaseRouteHandler

    from .protocols import AuthBackend, CacheBackend

FAILURE_KEY = "admin:login:fail:{username}:{ip}"
REVALIDATE_KEY = "admin:actor:{actor_id}"


def _failure_key(username: str, ip: str) -> str:
    """Build the cache key counting failures for a username and address."""
    return FAILURE_KEY.format(username=username, ip=ip)


async def register_failure(cache: CacheBackend, username: str, ip: str) -> int:
    """Increment and return the failure count for a username and address."""
    key = _failure_key(username, ip)
    count = int(await cache.get(key) or 0) + 1
    await cache.set(key, count, LOGIN_LOCK_TTL)
    return count


async def is_locked(cache: CacheBackend, username: str, ip: str) -> bool:
    """True when the failure count has reached the lockout threshold."""
    return int(await cache.get(_failure_key(username, ip)) or 0) >= LOGIN_MAX_ATTEMPTS


async def clear_failures(cache: CacheBackend, username: str, ip: str) -> None:
    """Reset the failure counter after a successful login."""
    await cache.delete(_failure_key(username, ip))


def actor_of(connection: ASGIConnection) -> Any:
    """Return the acting admin's identity from the session, or None."""
    return connection.session.get(SESSION_ACTOR_KEY)


def require_actor(
    connection: ASGIConnection, _handler: BaseRouteHandler | None
) -> None:
    """Litestar guard: reject requests without a logged-in admin session.

    A handler opted out with ``exclude_from_auth=True`` (the same opt key
    Litestar's own auth middlewares use) is exempt — this is how the login
    form and its submission stay reachable by anonymous callers even though
    the router that hosts them carries this guard for every other route.
    """
    if _handler is not None and _handler.opt.get(EXCLUDE_FROM_AUTH_KEY):
        return
    if actor_of(connection) is None:
        raise NotAuthorizedException()


class Revalidator:
    """Re-asserts the host's auth gate on established sessions.

    Runs as a ``before_request`` hook rather than a guard, because guards receive
    no dependency injection and this needs a database session. Revoking an
    admin's access therefore takes effect within ``REVALIDATE_TTL`` seconds
    instead of at session expiry.
    """

    def __init__(
        self,
        backend: AuthBackend,
        session_factory: Callable[[], Any],
        cache_provider: Callable[[Any], CacheBackend],
    ) -> None:
        """Store the collaborators supplied by :class:`~admin_litestar.Admin`."""
        self._backend = backend
        self._session_factory = session_factory
        self._cache_provider = cache_provider

    async def __call__(self, request: Any) -> None:
        """Clear the session and reject when the actor no longer qualifies."""
        actor_id = actor_of(request)
        if actor_id is None:
            return
        cache = self._cache_provider(request)
        key = REVALIDATE_KEY.format(actor_id=actor_id)
        if await cache.get(key):
            return
        async with self._session_factory() as session:
            valid = await self._backend.is_valid(session, actor_id)
        if not valid:
            request.session.clear()
            raise NotAuthorizedException()
        await cache.set(key, True, REVALIDATE_TTL)
