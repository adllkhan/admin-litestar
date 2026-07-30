"""A minimal host application, standing in for a real consumer."""

from __future__ import annotations

from typing import Any

from litestar import Litestar
from litestar.stores.memory import MemoryStore

from litestar_admin import Admin, AdminConfig

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
        self.entries.append(
            {"actor": actor_id, "action": action, "subject": subject,
             "pk": subject_pk, "extra": extra}
        )


class NullSession:
    """Async context manager yielding a placeholder database session."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_exc: object) -> None:
        return None


def build_admin(
    auth: FakeAuth | None = None,
    audit: RecordingAudit | None = None,
    cache: FakeCache | None = None,
) -> Admin:
    """Build a configured Admin over the throwaway specs."""
    shared = cache or FakeCache()
    return Admin(
        config=AdminConfig(path="/admin", static_path="/admin-static"),
        specs=[WIDGET, SECRET],
        auth=auth or FakeAuth(),
        audit=audit or RecordingAudit(),
        cache=lambda _request: shared,
        session_factory=NullSession,
    )


def build_app(admin: Admin | None = None) -> Litestar:
    """Build a Litestar app hosting the admin, as a real consumer would."""
    built = admin or build_admin()
    return Litestar(
        route_handlers=[built.router(), built.static_router()],
        template_config=built.template_config(),
        middleware=[built.session_config(MemoryStore()).middleware],
        csrf_config=built.csrf_config(SECRET_KEY),
    )
