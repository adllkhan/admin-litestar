"""Server-rendered admin for Litestar + SQLAlchemy applications.

Everything a host application needs is exported here. Deeper import paths such
as ``admin_litestar.queries`` happen to work, but the compatibility promise is
this module's ``__all__`` and nothing below it — see ARCHITECTURE.md.
"""

from importlib.metadata import PackageNotFoundError, version

from .admin import Admin, AdminConfig
from .auth import actor_of
from .constants import CAPABILITIES, CREATE, DELETE, DETAIL, EDIT, EXPORT, LIST
from .discovery import discover_specs
from .export import csv_rows
from .pages import CustomPage
from .passwords import hash_password, verify_password
from .protocols import AuditSink, AuthBackend, CacheBackend
from .queries import count_statement, detail_statement, list_statement
from .render import is_htmx, project, render_value
from .spec import BulkAction, ModelSpec, Relation, RowAction

try:
    __version__ = version("admin-litestar")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0.dev0"

__all__ = [
    "Admin",
    "AdminConfig",
    "AuditSink",
    "AuthBackend",
    "BulkAction",
    "CAPABILITIES",
    "CREATE",
    "CacheBackend",
    "CustomPage",
    "DELETE",
    "DETAIL",
    "EDIT",
    "EXPORT",
    "LIST",
    "ModelSpec",
    "Relation",
    "RowAction",
    "__version__",
    "actor_of",
    "count_statement",
    "csv_rows",
    "detail_statement",
    "discover_specs",
    "hash_password",
    "is_htmx",
    "list_statement",
    "project",
    "render_value",
    "verify_password",
]
