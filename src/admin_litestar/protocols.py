"""Protocols a host application implements to configure the admin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from litestar import Request


@runtime_checkable
class AuthBackend(Protocol):
    """Decides who may enter the admin and whether they still may."""

    async def authenticate(
        self, session: Any, username: str, password: str
    ) -> Any | None:
        """Return an opaque user object for valid credentials, else None."""
        ...

    def identity_of(self, user: Any) -> Any:
        """Return the JSON-serializable value to store in the session."""
        ...

    async def is_valid(self, session: Any, actor_id: Any) -> bool:
        """Re-assert the gate for an established session."""
        ...


@runtime_checkable
class AuditSink(Protocol):
    """Records admin actions wherever the host keeps its audit trail."""

    async def write(
        self,
        session: Any,
        actor_id: Any,
        action: str,
        *,
        subject: str | None = None,
        subject_pk: Any = None,
        request: Request | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Record one admin action."""
        ...


@runtime_checkable
class CacheBackend(Protocol):
    """Async key-value cache with per-key TTL, used for lockout and revalidation."""

    async def get(self, key: str) -> Any:
        """Return the cached value, or None when missing or expired."""
        ...

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Store a JSON-serializable value under ``key`` for ``ttl`` seconds."""
        ...

    async def delete(self, key: str) -> None:
        """Remove a key if present."""
        ...
