"""Fix 1: ``Admin._provide_session`` commits on success, never on error.

Unit-level companion to the consumer's ``db``-marked, real-database test:
this exercises the same code path with a fake session that simply records
whether ``commit`` was called, so the contract is pinned here even without a
database, and the failure mode (an exception must not commit) is covered
too — something the real-database test does not attempt.
"""

from __future__ import annotations

from typing import Any

from litestar import Litestar, get
from litestar.di import NamedDependency
from litestar.stores.memory import MemoryStore
from litestar.testing import TestClient

from admin_litestar import Admin, AdminConfig, CustomPage

from .hostapp import FakeAuth, FakeCache, RecordingAudit
from .test_spec import SECRET, WIDGET


class _RecordingSession:
    """Stands in for a database session, recording whether it was committed."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        """Record that a commit was requested."""
        self.committed = True


class _RecordingSessionScope:
    """Async context manager yielding a pre-built recording session."""

    def __init__(self, session: _RecordingSession) -> None:
        self._session = session

    async def __aenter__(self) -> _RecordingSession:
        """Hand back the shared recording session."""
        return self._session

    async def __aexit__(self, *_exc: object) -> None:
        """Nothing to close: the test asserts on the session directly."""
        return None


def _build_app(session: _RecordingSession, handler: Any) -> Litestar:
    """Host one probe handler inside the admin's own gated router.

    The handler is registered as a ``CustomPage`` rather than a bare app
    route so it runs behind ``admin_session`` — the dependency the fix is
    about — while ``exclude_from_auth=True`` on the handler itself keeps the
    guard from requiring a login this test has no interest in.
    """
    admin = Admin(
        config=AdminConfig(path="/admin"),
        specs=[WIDGET, SECRET],
        auth=FakeAuth(),
        audit=RecordingAudit(),
        cache=lambda _request: FakeCache(),
        session_factory=lambda: _RecordingSessionScope(session),
        pages=[CustomPage(slug="probe", label="", group="", handlers=[handler])],
    )
    return Litestar(
        route_handlers=[admin.router()],
        template_config=admin.template_config(),
        middleware=[admin.session_config(MemoryStore()).middleware],
    )


def test_session_commits_after_a_successful_handler() -> None:
    """A handler that returns normally leaves its session committed."""
    session = _RecordingSession()

    @get("/probe", exclude_from_auth=True, sync_to_thread=False)
    def probe(admin_session: NamedDependency[Any]) -> str:
        assert admin_session is session
        return "ok"

    with TestClient(app=_build_app(session, probe)) as client:
        response = client.get("/admin/probe")

    assert response.status_code == 200
    assert session.committed is True


def test_session_is_not_committed_when_the_handler_raises() -> None:
    """An exception must not reach the commit — only rollback applies."""
    session = _RecordingSession()

    @get("/probe", exclude_from_auth=True, sync_to_thread=False)
    def probe(admin_session: NamedDependency[Any]) -> str:
        assert admin_session is session
        raise ValueError("boom")

    with TestClient(app=_build_app(session, probe), raise_server_exceptions=False) as client:
        response = client.get("/admin/probe")

    assert response.status_code == 500
    assert session.committed is False
