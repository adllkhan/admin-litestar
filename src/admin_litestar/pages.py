"""Host-contributed pages the admin hosts alongside its generic ones."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class CustomPage:
    """A page the host application supplies.

    Attributes:
        slug: Path segment under the admin root; also the nav link target.
        label: Nav label. An empty label hides the page from the nav, which
            suits a landing page reached through the brand link.
        group: Nav grouping label, matched against the registry's groups so a
            custom page can sit beside related models.
        handlers: Litestar route handlers or controllers implementing the page.
    """

    slug: str
    label: str
    group: str
    handlers: Sequence[Any]
