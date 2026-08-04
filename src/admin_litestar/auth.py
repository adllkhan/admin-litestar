"""Session gating, revalidation, and login lockout."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from litestar import MediaType, Response
from litestar.exceptions import NotAuthorizedException
from litestar.response import Redirect
from litestar.status_codes import HTTP_303_SEE_OTHER, HTTP_401_UNAUTHORIZED

from .constants import (
    EXCLUDE_FROM_AUTH_KEY,
    LOGIN_LOCK_TTL,
    LOGIN_MAX_ATTEMPTS,
    REVALIDATE_TTL,
    SESSION_ACTOR_KEY,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from litestar import Request
    from litestar.connection import ASGIConnection
    from litestar.handlers.base import BaseRouteHandler

    from .protocols import AuthBackend, CacheBackend

FAILURE_KEY = "admin:login:fail:{username}:{ip}"
REVALIDATE_KEY = "admin:actor:{actor_id}"
HTMX_HEADER = "HX-Request"
HTMX_REDIRECT_HEADER = "HX-Redirect"
UNAUTHORIZED_DETAIL = "Unauthorized"


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


def safe_next(candidate: str | None, admin_path: str) -> str | None:
    """Return ``candidate`` if it is a URL inside this admin, else None.

    A post-login destination arrives from a query string, which is to say from
    anyone who can get an admin to click a link — so it is only ever allowed to
    be a path under the admin's own mount point. Anything absolute,
    protocol-relative, backslash-obfuscated, or pointing at the login page
    itself (which would loop) is discarded in favour of the caller's default.
    """
    if not candidate or not candidate.startswith("/") or candidate.startswith("//"):
        return None
    if "\\" in candidate or "://" in candidate:
        return None
    root = admin_path.rstrip("/")
    path = candidate.split("?", 1)[0].split("#", 1)[0]
    # ``/admin/../../elsewhere`` passes a prefix test but resolves outside the
    # admin in the browser that receives the Location header, so dot segments
    # are refused outright -- encoded ones too, since they normalise the same.
    lowered = path.lower()
    if ".." in path or "%2e" in lowered:
        return None
    if path == f"{root}/login" or path == f"{root}/logout":
        return None
    if path == root or path == f"{root}/" or path.startswith(f"{root}/"):
        return candidate
    return None


def unauthorized_handler(admin_path: str) -> Callable[[Request, Exception], Response]:
    """Build the handler that answers a failed auth gate.

    The guard raises for every caller alike, but a browser and a script want
    different answers. A page request wants the login form, with the URL it was
    trying to reach carried along; an HTMX request wants a redirect header,
    because a 401 body would otherwise be swapped into the page as content; and
    anything else — a fetch, a probe — keeps the plain 401 it expects.
    """
    login_url = f"{admin_path.rstrip('/')}/login"

    def handle(request: Request, _exception: Exception) -> Response:
        """Answer according to what the caller can act on."""
        if request.headers.get(HTMX_HEADER):
            return Response(
                content=b"",
                status_code=HTTP_401_UNAUTHORIZED,
                headers={HTMX_REDIRECT_HEADER: login_url},
            )
        wants_html = "text/html" in request.headers.get("accept", "")
        if request.method in {"GET", "HEAD"} and wants_html:
            target = safe_next(str(request.url.path), admin_path)
            if request.url.query:
                target = safe_next(f"{request.url.path}?{request.url.query}", admin_path)
            url = f"{login_url}?next={quote(target, safe='/')}" if target else login_url
            return Redirect(url, status_code=HTTP_303_SEE_OTHER)
        return Response(
            content={"status_code": HTTP_401_UNAUTHORIZED, "detail": UNAUTHORIZED_DETAIL},
            status_code=HTTP_401_UNAUTHORIZED,
            media_type=MediaType.JSON,
        )

    return handle


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
