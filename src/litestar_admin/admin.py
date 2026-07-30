"""The object a host application constructs, configures and mounts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from litestar import Router
from litestar.config.csrf import CSRFConfig
from litestar.di import Provide
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.static_files import create_static_files_router
from litestar.template.config import TemplateConfig

from .auth import Revalidator, require_actor
from .constants import DEFAULT_PATH, DEFAULT_STATIC_PATH
from .controllers import SessionController
from .protocols import CacheBackend
from .render import render_value
from .spec import Registry
from .static import STATIC
from .templates import TEMPLATES

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from litestar import Litestar
    from litestar.stores.base import Store

    from .pages import CustomPage
    from .protocols import AuditSink, AuthBackend
    from .spec import ModelSpec

SESSION_STORE_NAME = "admin_sessions"
CSRF_COOKIE = "admin_csrf"


class _HostStoreSessionConfig(ServerSideSessionConfig):
    """A session config bound to a store object rather than a registry name.

    ``ServerSideSessionConfig`` normally resolves its store by looking up a
    name in the Litestar app's store registry — but ``Admin`` never builds
    that app, so it has no way to register the host's store under a name.
    Binding directly to the supplied store sidesteps that registry entirely.
    """

    def __init__(self, backing_store: Store) -> None:
        """Wrap the host's store, keeping the registry-name field cosmetic."""
        super().__init__(store=SESSION_STORE_NAME)
        self._backing_store = backing_store

    def get_store_from_app(self, app: Litestar) -> Store:
        """Return the host-supplied store, ignoring the app's registry."""
        return self._backing_store


@dataclass(frozen=True, slots=True)
class AdminConfig:
    """Where the admin lives and what it calls itself."""

    path: str = DEFAULT_PATH
    static_path: str = DEFAULT_STATIC_PATH
    brand: str = "admin"
    template_dirs: tuple[Path, ...] = field(default=())


class Admin:
    """Assembles the admin's router and the Litestar configuration it needs.

    The host supplies ``session_factory``, a zero-argument callable returning
    an async context manager over a database session (the same shape an
    ``async_sessionmaker`` provides). ``Admin`` opens one such session per
    request and injects it into its own handlers as ``admin_session`` — a
    dependency every handler under :meth:`router` may request. The session is
    closed automatically once the handler returns, including on error, via
    Litestar's generator-dependency cleanup.
    """

    def __init__(
        self,
        config: AdminConfig,
        specs: Sequence[ModelSpec],
        auth: AuthBackend,
        audit: AuditSink,
        cache: Callable[[Any], CacheBackend],
        session_factory: Callable[[], Any],
        pages: Sequence[CustomPage] = (),
    ) -> None:
        """Store the host's configuration and build the registry."""
        self.config = config
        self.registry = Registry(specs)
        self.auth = auth
        self.audit = audit
        self.cache = cache
        self.session_factory = session_factory
        self.pages = tuple(pages)

    def _url_for_spec(self, spec: ModelSpec) -> str:
        """Return the list URL for a spec."""
        return f"{self.config.path}/m/{spec.slug}"

    def _url_for_page(self, page: CustomPage) -> str:
        """Return the URL for a host-contributed page."""
        return f"{self.config.path}/{page.slug}"

    async def _provide_session(self) -> AsyncIterator[Any]:
        """Open one database session per request for the ``admin_session`` name.

        Yielding keeps the session open for the handler's duration; Litestar
        resumes this generator after the response is built, closing the
        context manager whether the handler succeeded or raised.
        """
        async with self.session_factory() as session:
            yield session

    def _dependencies(self) -> dict[str, Provide]:
        """Provide the admin's collaborators to every handler."""
        return {
            "admin_auth": Provide(lambda: self.auth, sync_to_thread=False),
            "admin_audit": Provide(lambda: self.audit, sync_to_thread=False),
            "admin_registry": Provide(lambda: self.registry, sync_to_thread=False),
            "admin_path": Provide(lambda: self.config.path, sync_to_thread=False),
            "admin_cache": Provide(self._provide_cache, sync_to_thread=False),
            "admin_session": Provide(self._provide_session),
        }

    def _provide_cache(self, request: Any) -> CacheBackend:
        """Return the host's cache for this request."""
        return self.cache(request)

    def router(self) -> Router:
        """Build the admin router: generic controllers plus host pages."""
        handlers: list[Any] = [SessionController]
        for page in self.pages:
            handlers.extend(page.handlers)
        return Router(
            path=self.config.path,
            route_handlers=handlers,
            guards=[require_actor],
            before_request=Revalidator(self.auth, self.session_factory, self.cache),
            dependencies=self._dependencies(),
        )

    def static_router(self) -> Router:
        """Serve the package's vendored CSS and JS."""
        return create_static_files_router(
            path=self.config.static_path, directories=[STATIC]
        )

    def template_config(self) -> TemplateConfig:
        """Build the Jinja config, host template directories taking precedence.

        The engine is built and populated with globals here, then handed to
        ``TemplateConfig`` as a ready ``instance``. Passing ``engine=`` (a
        class) instead would have Litestar build its own, separate engine
        via ``TemplateConfig.engine_instance`` — a fresh instance that never
        saw these globals — so the config must carry the instance directly.
        """
        directories = [*self.config.template_dirs, TEMPLATES]
        engine = JinjaTemplateEngine(directory=directories)
        engine.engine.globals.update(
            admin_path=self.config.path,
            static_path=self.config.static_path,
            brand=self.config.brand,
            registry=self.registry,
            groups=self.registry.groups,
            pages=self.pages,
            url_for_spec=self._url_for_spec,
            url_for_page=self._url_for_page,
            render_value=render_value,
        )
        return TemplateConfig(instance=engine)

    def session_config(self, store: Store) -> ServerSideSessionConfig:
        """Build the server-side session config over a host-supplied store."""
        return _HostStoreSessionConfig(store)

    def csrf_config(self, secret: str) -> CSRFConfig:
        """Build CSRF protection for the admin's mutating routes."""
        return CSRFConfig(secret=secret, cookie_name=CSRF_COOKIE)
