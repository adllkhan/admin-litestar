"""Generic list, detail, delete and export routes driven by ModelSpec."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from litestar import Controller, Request, get, post
from litestar.di import NamedDependency
from litestar.exceptions import NotFoundException
from litestar.params import FromPath, FromQuery
from litestar.response import Redirect, Stream, Template
from litestar.status_codes import HTTP_303_SEE_OTHER

from ..auth import actor_of
from ..constants import (
    ACTION_DELETE,
    ACTION_DETAIL_VIEW,
    ACTION_EXPORT,
    DELETE,
    DETAIL,
    EXPORT,
    EXPORT_LIMIT,
    LIST,
    PAGE_SIZE,
)
from ..export import csv_rows
from ..protocols import AuditSink
from ..queries import detail_statement, list_statement
from ..render import project
from ..spec import Registry

if TYPE_CHECKING:
    from ..spec import ModelSpec

LIST_TEMPLATE = "list.html"
ROWS_TEMPLATE = "_rows.html"
DETAIL_TEMPLATE = "detail.html"
CSV_MEDIA_TYPE = "text/csv"
HTMX_HEADER = "HX-Request"


def _spec_or_404(registry: Registry, slug: str, capability: str) -> ModelSpec:
    """Return the spec offering ``capability``, or raise 404."""
    try:
        spec = registry.get(slug)
    except KeyError as exc:
        raise NotFoundException() from exc
    if not spec.renders(capability):
        raise NotFoundException()
    return spec


class ModelController(Controller):
    """Routes shared by every registered model."""

    path = "/m"

    @get("/{slug:str}")
    async def index(
        self,
        slug: FromPath[str],
        request: Request,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_path: NamedDependency[str],
        search: FromQuery[str | None] = None,
        after: FromQuery[str | None] = None,
    ) -> Template:
        """Render a filtered, paginated list."""
        spec = _spec_or_404(admin_registry, slug, LIST)
        filters = {
            name: request.query_params[name]
            for name in spec.filters
            if request.query_params.get(name)
        }
        result = (
            await admin_session.execute(
                list_statement(spec, search=search, filters=filters, after=after)
            )
        ).scalars().all()
        rows = [project(row, spec.list_columns) for row in result]
        cursor = rows[-1][spec.order_by] if len(rows) == PAGE_SIZE else None
        context = {
            "spec": spec,
            "rows": rows,
            "search": search,
            "filters": filters,
            "after": after,
            "cursor": cursor,
            "page_url": f"{admin_path}/m/{spec.slug}",
        }
        # A paging click asks for rows to append, not a second copy of the page;
        # the same URL without the HTMX header still renders the whole page, so
        # it stays usable with scripting off.
        if after is not None and request.headers.get(HTMX_HEADER):
            return Template(ROWS_TEMPLATE, context=context)
        return Template(LIST_TEMPLATE, context=context)

    @get("/{slug:str}/export")
    async def export(
        self,
        slug: FromPath[str],
        request: Request,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_audit: NamedDependency[AuditSink],
    ) -> Stream:
        """Stream the list as CSV and audit the export."""
        spec = _spec_or_404(admin_registry, slug, EXPORT)
        result = (
            await admin_session.execute(list_statement(spec, limit=EXPORT_LIMIT))
        ).scalars().all()
        rows = [project(row, spec.list_columns) for row in result]
        await admin_audit.write(
            admin_session, actor_of(request), ACTION_EXPORT,
            subject=spec.slug, request=request, extra={"rows": len(rows)},
        )
        return Stream(
            csv_rows(spec, rows),
            media_type=CSV_MEDIA_TYPE,
            headers={
                "content-disposition": f'attachment; filename="{spec.slug}.csv"'
            },
        )

    @get("/{slug:str}/{pk:str}")
    async def detail(
        self,
        slug: FromPath[str],
        pk: FromPath[str],
        request: Request,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_audit: NamedDependency[AuditSink],
        admin_path: NamedDependency[str],
    ) -> Template:
        """Render one record, auditing the view when the spec asks for it."""
        spec = _spec_or_404(admin_registry, slug, DETAIL)
        row = (
            await admin_session.execute(detail_statement(spec, pk))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundException()
        if spec.audit_on_detail:
            await admin_audit.write(
                admin_session, actor_of(request), ACTION_DETAIL_VIEW,
                subject=spec.slug, subject_pk=pk, request=request,
            )
        return Template(
            DETAIL_TEMPLATE,
            context={
                "spec": spec,
                "pk": pk,
                "row": project(row, spec.detail_columns),
                "page_url": f"{admin_path}/m/{spec.slug}",
            },
        )

    @post("/{slug:str}/{pk:str}/delete", status_code=HTTP_303_SEE_OTHER)
    async def delete(
        self,
        slug: FromPath[str],
        pk: FromPath[str],
        request: Request,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_audit: NamedDependency[AuditSink],
        admin_path: NamedDependency[str],
    ) -> Redirect:
        """Delete one record and audit it."""
        spec = _spec_or_404(admin_registry, slug, DELETE)
        row = (
            await admin_session.execute(detail_statement(spec, pk))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundException()
        await admin_session.delete(row)
        await admin_audit.write(
            admin_session, actor_of(request), ACTION_DELETE,
            subject=spec.slug, subject_pk=pk, request=request,
        )
        return Redirect(f"{admin_path}/m/{spec.slug}")
