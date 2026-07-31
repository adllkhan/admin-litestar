"""Login and logout."""

from __future__ import annotations

from typing import Annotated, Any

from litestar import Controller, Request, get, post
from litestar.di import NamedDependency
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Redirect, Template
from litestar.status_codes import HTTP_303_SEE_OTHER

from ..auth import clear_failures, is_locked, register_failure
from ..constants import (
    ACTION_LOGIN,
    ACTION_LOGIN_FAILED,
    SESSION_ACTOR_KEY,
)
from ..protocols import AuditSink, AuthBackend, CacheBackend

LOCKED_MESSAGE = "too many attempts, try again later"
INVALID_MESSAGE = "invalid credentials"
UNKNOWN_IP = "unknown"
LOGIN_TEMPLATE = "login.html"

Form = Annotated[dict[str, Any], Body(media_type=RequestEncodingType.URL_ENCODED)]


class SessionController(Controller):
    """Renders the login form and manages the admin session."""

    @get("/login", exclude_from_auth=True)
    async def form(self) -> Template:
        """Render the login form."""
        return Template(LOGIN_TEMPLATE, context={"error": None})

    @post("/login", exclude_from_auth=True, status_code=HTTP_303_SEE_OTHER)
    async def submit(
        self,
        request: Request,
        data: Form,
        admin_auth: NamedDependency[AuthBackend],
        admin_audit: NamedDependency[AuditSink],
        admin_cache: NamedDependency[CacheBackend],
        admin_session: NamedDependency[Any],
        admin_path: NamedDependency[str],
    ) -> Redirect | Template:
        """Validate credentials, open a session, and audit the outcome."""
        username = str(data.get("username", ""))
        password = str(data.get("password", ""))
        ip = request.client.host if request.client else UNKNOWN_IP
        if await is_locked(admin_cache, username, ip):
            return Template(LOGIN_TEMPLATE, context={"error": LOCKED_MESSAGE})
        user = await admin_auth.authenticate(admin_session, username, password)
        if user is None:
            await register_failure(admin_cache, username, ip)
            await admin_audit.write(
                admin_session, None, ACTION_LOGIN_FAILED,
                request=request, extra={"username": username},
            )
            return Template(LOGIN_TEMPLATE, context={"error": INVALID_MESSAGE})
        await clear_failures(admin_cache, username, ip)
        actor_id = admin_auth.identity_of(user)
        request.session[SESSION_ACTOR_KEY] = actor_id
        await admin_audit.write(
            admin_session, actor_id, ACTION_LOGIN, request=request
        )
        return Redirect(f"{admin_path}/")

    @post("/logout", status_code=HTTP_303_SEE_OTHER)
    async def logout(
        self, request: Request, admin_path: NamedDependency[str]
    ) -> Redirect:
        """Clear the admin session."""
        request.session.clear()
        return Redirect(f"{admin_path}/login")
