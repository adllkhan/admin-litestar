"""The object a host application constructs, configures and mounts."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from litestar import Router, get
from litestar.config.csrf import CSRFConfig
from litestar.di import Provide
from litestar.exceptions import NotAuthorizedException
from litestar.middleware.base import DefineMiddleware
from litestar.middleware.csrf import CSRFMiddleware
from litestar.middleware.session.server_side import ServerSideSessionConfig
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.response import Redirect
from litestar.static_files import create_static_files_router
from litestar.template.config import TemplateConfig

from .auth import Revalidator, require_actor, unauthorized_handler
from .constants import (
    DEFAULT_PATH,
    DEFAULT_STATIC_PATH,
    DEFAULT_THEME,
    LIST,
    THEMES,
)
from .controllers import ModelController, SessionController
from .flash import pop_flash
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


def _handler_paths(handler: Any) -> tuple[str, ...]:
    """Return the paths a handler or controller declares, normalised.

    A decorated handler carries a ``paths`` set; a ``Controller`` subclass
    carries a single ``path`` string. Both shapes reach here, because both are
    things a host puts in ``CustomPage.handlers``.
    """
    paths = getattr(handler, "paths", None)
    if paths is None:
        single = getattr(handler, "path", None)
        paths = () if single is None else (single,)
    return tuple(str(path).rstrip("/") for path in paths)


def _owns_root(page: CustomPage) -> bool:
    """Whether a host page answers at the admin root.

    An empty slug says so by declaration; a handler mounted at ``/`` says so by
    routing. Either way the admin must not add its own root route, or Litestar
    would see two handlers for one path.
    """
    if page.slug.strip("/") == "":
        return True
    return any(path == "" for handler in page.handlers for path in _handler_paths(handler))


class _HostStoreSessionConfig(ServerSideSessionConfig):
    """A session config bound to a store object rather than a registry name.

    ``ServerSideSessionConfig`` normally resolves its store by looking up a
    name in the Litestar app's store registry — but ``Admin`` never builds
    that app, so it has no way to register the host's store under a name.
    Binding directly to the supplied store sidesteps that registry entirely.
    """

    def __init__(self, backing_store: Store, *, secure: bool) -> None:
        """Wrap the host's store, keeping the registry-name field cosmetic."""
        super().__init__(store=SESSION_STORE_NAME, secure=secure)
        self._backing_store = backing_store

    def get_store_from_app(self, app: Litestar) -> Store:
        """Return the host-supplied store, ignoring the app's registry."""
        return self._backing_store


@dataclass(frozen=True, slots=True)
class AdminConfig:
    """Where the admin lives and what it calls itself.

    Attributes:
        path: The admin's mount path.
        static_path: Path segment for the admin's static assets, relative to
            ``path`` — not an absolute path. The default nests assets at
            ``<path>/static``, so a host mounts one router for the whole
            admin rather than the assets separately.
        brand: The name shown in the sidebar.
        template_dirs: Host template directories, searched before the
            package's own so any template can be overridden by name.
        secure_cookies: Whether the session and CSRF cookies carry the
            ``Secure`` attribute. Defaults to ``True`` because a stolen
            session cookie defeats the login gate, the lockout and
            revalidation together; set to ``False`` only for a local or test
            environment served over plain HTTP.
        theme: Which shipped stylesheet the shell links — a key of
            :data:`THEMES`, not a filename or a path. Both themes carry the
            same class names, so a host's own templates work under either. A
            host wanting neither overrides ``base.html`` and links its own.
    """

    path: str = DEFAULT_PATH
    static_path: str = DEFAULT_STATIC_PATH
    brand: str = "admin"
    template_dirs: tuple[Path, ...] = field(default=())
    secure_cookies: bool = True
    theme: str = DEFAULT_THEME

    def __post_init__(self) -> None:
        """Reject an unknown theme by name, rather than serving a 404 link."""
        if self.theme not in THEMES:
            available = ", ".join(sorted(THEMES))
            raise ValueError(f"unknown theme {self.theme!r}; available: {available}")


class Admin:
    """Assembles the admin's router and the Litestar configuration it needs.

    The host supplies ``session_factory``, a zero-argument callable returning
    an async context manager over a database session (the same shape an
    ``async_sessionmaker`` provides). ``Admin`` opens one such session per
    request and injects it into its own handlers as ``admin_session`` — a
    dependency every handler under :meth:`router` may request. The session is
    committed once the handler returns successfully, and closed automatically
    either way — including on error, where the context manager rolls back —
    via Litestar's generator-dependency cleanup.

    ``session_factory`` is wrapped in a plain closure before it is stored
    anywhere reachable from the router Litestar builds, rather than kept as
    whatever callable the host handed in. Litestar deep-copies every
    ``Router`` it registers — twice over, in fact, once when :meth:`router`
    nests the gated router inside the returned one, and again when the host
    registers that router into its own app — and ``copy.deepcopy`` treats a
    plain function as atomic, returning it unchanged rather than recursing
    into whatever it closes over. A bound method (``sqlalchemy_config.
    get_session``) or a bare ``async_sessionmaker`` instance is not atomic:
    deep-copying either tries to deep-copy what it is bound to — a live
    engine or connection pool — and that fails loudly on the *second*
    ``Admin`` an application constructs in one process, once the first
    engine exists. Wrapping unconditionally means any callable shape the
    host supplies is safe, rather than only the one shape a fail-fast check
    happened to name.
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
        csrf_secret: str | None = None,
    ) -> None:
        """Store the host's configuration and build the registry.

        Args:
            config: Where the admin lives and what it calls itself.
            specs: Every model the admin exposes.
            auth: Decides who may enter and whether they still may.
            audit: Records admin actions.
            cache: Returns the host's cache for a given request.
            session_factory: Zero-argument callable returning an async
                context manager over a database session. Any callable shape
                works; see the class docstring for why.
            pages: Host-contributed pages, rendered inside the same shell.
            csrf_secret: Secret used to sign the CSRF token. ``None`` (the
                default) leaves CSRF protection off, matching a host that has
                deliberately declined it. When supplied, CSRF protection is
                attached only to the admin's own routes — never app-wide —
                because the package knows its own mount path and a host does
                not need to teach it one.
        """
        self.config = config
        self.registry = Registry(specs)
        self.auth = auth
        self.audit = audit
        self.cache = cache
        self.session_factory = self._atomic_factory(session_factory)
        self.pages = tuple(pages)
        self.csrf_secret = csrf_secret

    @staticmethod
    def _atomic_factory(factory: Callable[[], Any]) -> Callable[[], Any]:
        """Wrap ``factory`` in a plain closure, opaque to ``copy.deepcopy``.

        See the class docstring: this is what keeps any session factory
        shape safe under the deep-copying Litestar's ``Router`` registration
        performs.
        """

        def _call() -> Any:
            return factory()

        return _call

    def _url_for_spec(self, spec: ModelSpec) -> str:
        """Return the list URL for a spec."""
        return f"{self.config.path}/m/{spec.slug}"

    def _url_for_page(self, page: CustomPage) -> str:
        """Return the URL for a host-contributed page."""
        return f"{self.config.path}/{page.slug}"

    def _index_handler(self) -> Any | None:
        """Build the root redirect, or None when the root is already taken.

        The login redirect and the brand link both point at the admin root, so
        something has to answer there. A host landing page is the better answer
        and wins whenever one exists; this fallback keeps the two paths from
        leading to a 404 in every host that has not written one yet. With no
        listable spec there is nowhere to send the caller, so nothing is
        registered and the root 404s as before.
        """
        if any(_owns_root(page) for page in self.pages):
            return None
        listable = [spec for spec in self.registry.specs if spec.renders(LIST)]
        if not listable:
            return None
        target = self._url_for_spec(listable[0])

        @get("/", sync_to_thread=False)
        def index() -> Redirect:
            """Send the admin root to the first listable model."""
            return Redirect(target)

        return index

    def _static_url(self) -> str:
        """Return the full URL the admin's static assets are served at."""
        return f"{self.config.path}{self.config.static_path}"

    def _stylesheet_url(self) -> str:
        """Return the URL of the stylesheet the configured theme names."""
        return f"{self._static_url()}/{THEMES[self.config.theme]}"

    async def _provide_session(self) -> AsyncIterator[Any]:
        """Open one database session per request for the ``admin_session`` name.

        Yielding keeps the session open for the handler's duration; Litestar
        resumes this generator after the response is built. On success, the
        transaction is committed here — the host's own SQLAlchemy plugin,
        if any, autocommits only sessions *it* provides, never one ``Admin``
        opens itself. On an exception, this line is never reached and the
        ``async with`` block's exit rolls back whatever was uncommitted.
        """
        async with self.session_factory() as session:
            yield session
            await session.commit()

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

    def _csrf_middleware(self) -> list[Any]:
        """Return the admin's own CSRF middleware, or none.

        Built here rather than handed to the host as a ``CSRFConfig`` for
        ``Litestar(csrf_config=...)``: that hook applies app-wide, which is
        the whole defect — every other mutating route's rejection becomes a
        403 instead of whatever it would otherwise be. Attaching
        ``CSRFMiddleware`` directly to the gated router scopes enforcement
        to the admin's own routes structurally, through the same per-route
        middleware resolution Litestar already uses for guards, so no
        ``exclude`` pattern is needed — and none of the ``exclude``-based
        approaches tried avoided Litestar's own "middleware is effectively
        disabled" warning, which fires on exactly the kind of pattern that
        would exclude everything outside the admin's path.
        """
        if self.csrf_secret is None:
            return []
        config = CSRFConfig(
            secret=self.csrf_secret,
            cookie_name=CSRF_COOKIE,
            cookie_secure=self.config.secure_cookies,
        )
        return [DefineMiddleware(CSRFMiddleware, config=config)]

    def router(self) -> Router:
        """Build the admin's one mounted router: gated pages plus static assets.

        A single ``Router`` is returned, nesting two children: the gated
        router carrying every generic and host-contributed handler, guarded
        and revalidated and (optionally) CSRF-protected; and a static-files
        router with none of that, so the login page's own stylesheet stays
        reachable by the anonymous caller it is rendered for. Guards and
        CSRF middleware accumulate down Litestar's ownership chain, so
        nesting them only inside the gated child — never on this outer
        router — is what keeps the static child free of both.
        """
        handlers: list[Any] = [SessionController, ModelController]
        for page in self.pages:
            handlers.extend(page.handlers)
        index = self._index_handler()
        if index is not None:
            handlers.append(index)
        gated = Router(
            path="",
            route_handlers=handlers,
            guards=[require_actor],
            before_request=Revalidator(self.auth, self.session_factory, self.cache),
            middleware=self._csrf_middleware(),
        )
        static = create_static_files_router(
            path=self.config.static_path, directories=[STATIC]
        )
        return Router(
            path=self.config.path,
            route_handlers=[gated, static],
            dependencies=self._dependencies(),
            # Registered on the outer router so it covers the gated child, and
            # scoped to this router so a host's own 401s keep their own shape.
            exception_handlers={
                NotAuthorizedException: unauthorized_handler(self.config.path)
            },
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
            static_path=self._static_url(),
            stylesheet_path=self._stylesheet_url(),
            brand=self.config.brand,
            registry=self.registry,
            groups=self.registry.groups,
            pages=self.pages,
            url_for_spec=self._url_for_spec,
            url_for_page=self._url_for_page,
            render_value=render_value,
            pop_flash=pop_flash,
        )
        return TemplateConfig(instance=engine)

    def session_config(self, store: Store) -> ServerSideSessionConfig:
        """Build the server-side session config over a host-supplied store."""
        return _HostStoreSessionConfig(store, secure=self.config.secure_cookies)
