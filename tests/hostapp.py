"""A minimal host application, standing in for a real consumer."""

from __future__ import annotations

from typing import Any

from admin_litestar import Admin, AdminConfig
from admin_litestar.constants import DEFAULT_THEME
from litestar import Litestar
from litestar.stores.memory import MemoryStore

from .test_spec import SECRET, WIDGET

SECRET_KEY = "test-secret-key-for-csrf-and-sessions"


class FakeCache:
    """CacheBackend with no expiry."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.data.get(key)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class FakeAuth:
    """AuthBackend accepting one hard-coded credential pair."""

    def __init__(self, username: str = "root", password: str = "hunter2") -> None:
        self.username = username
        self.password = password
        self.valid = True

    async def authenticate(self, session: Any, username: str, password: str) -> Any:
        if username == self.username and password == self.password:
            return {"id": 1, "name": username}
        return None

    def identity_of(self, user: Any) -> Any:
        return user["id"]

    async def is_valid(self, session: Any, actor_id: Any) -> bool:
        return self.valid


class RecordingAudit:
    """AuditSink collecting what it was asked to record."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def write(
        self,
        session: Any,
        actor_id: Any,
        action: str,
        *,
        subject: str | None = None,
        subject_pk: Any = None,
        request: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.entries.append({
            "actor": actor_id,
            "action": action,
            "subject": subject,
            "pk": subject_pk,
            "extra": extra,
        })


class _PlaceholderSession:
    """A database-session stand-in offering the one method ``Admin`` calls."""

    async def commit(self) -> None:
        """Do nothing: there is no real transaction to commit."""
        return


class NullSession:
    """Async context manager yielding a placeholder database session."""

    async def __aenter__(self) -> _PlaceholderSession:
        return _PlaceholderSession()

    async def __aexit__(self, *_exc: object) -> None:
        return None


def build_admin(
    auth: FakeAuth | None = None,
    audit: RecordingAudit | None = None,
    cache: FakeCache | None = None,
    specs: list[Any] | None = None,
    pages: list[Any] | None = None,
    theme: str = DEFAULT_THEME,
) -> Admin:
    """Build a configured Admin over the throwaway specs."""
    shared = cache or FakeCache()
    return Admin(
        # secure_cookies=False: the test suite runs over plain HTTP, and a
        # real deployment gets True (the default) unless it opts out the
        # same way, for the same reason.
        config=AdminConfig(path="/admin", secure_cookies=False, theme=theme),
        specs=specs if specs is not None else [WIDGET, SECRET],
        auth=auth or FakeAuth(),
        audit=audit or RecordingAudit(),
        cache=lambda _request: shared,
        session_factory=NullSession,
        csrf_secret=SECRET_KEY,
        pages=pages or [],
    )


def build_app(admin: Admin | None = None) -> Litestar:
    """Build a Litestar app hosting the admin, as a real consumer would."""
    built = admin or build_admin()
    return Litestar(
        route_handlers=[built.router()],
        template_config=built.template_config(),
        middleware=[built.session_config(MemoryStore()).middleware],
    )
