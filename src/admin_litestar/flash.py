"""One-shot messages that survive a redirect.

A write either redirects (delete, create, any save without scripting) or swaps a
fragment (a save through HTMX). The first needs the message to outlive the
response that set it, which is what the session is for; the second carries it in
the fragment. Both end up in the same ``#toast`` container.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .constants import FLASH_KIND_SUCCESS, FLASH_SESSION_KEY

if TYPE_CHECKING:
    from litestar import Request


def set_flash(
    request: Request, message: str, kind: str = FLASH_KIND_SUCCESS
) -> None:
    """Store a message for the next page this session renders."""
    request.session[FLASH_SESSION_KEY] = {"message": message, "kind": kind}


def pop_flash(request: Request) -> dict[str, Any] | None:
    """Return the pending message and remove it, so it shows exactly once.

    Called from ``base.html`` rather than from every handler: the session is
    written back when the response is sent, so removing it during rendering is
    what makes the message one-shot.
    """
    # Touching request.session without the middleware installed raises, and a
    # template rendered outside the admin's own router -- a host reusing
    # base.html, a test rendering it bare -- has every right to have no session.
    if "session" not in request.scope:
        return None
    flash = request.session.pop(FLASH_SESSION_KEY, None)
    return flash if isinstance(flash, dict) else None
