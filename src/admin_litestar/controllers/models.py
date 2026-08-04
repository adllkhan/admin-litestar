"""Generic list, detail, edit, create, delete and export routes from ModelSpec."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Annotated, Any

from litestar import Controller, Request, get, post
from litestar.di import NamedDependency
from litestar.enums import RequestEncodingType
from litestar.exceptions import NotFoundException
from litestar.params import Body, FromPath, FromQuery
from litestar.response import Redirect, Stream, Template
from litestar.status_codes import HTTP_303_SEE_OTHER
from sqlalchemy.exc import IntegrityError

from ..auth import actor_of
from ..constants import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_DETAIL_VIEW,
    ACTION_EXPORT,
    ACTION_UPDATE,
    CREATE,
    DELETE,
    DETAIL,
    EDIT,
    EXPORT,
    ASCENDING,
    DESCENDING,
    EXPORT_LIMIT,
    FLASH_KIND_SUCCESS,
    LIST,
    PAGE_SIZE,
)
from ..export import csv_rows
from ..filters import (
    facets_for,
    is_range_column,
    parse as parse_filters,
    range_presets,
)
from ..flash import set_flash
from ..forms import fields_for, parse
from ..protocols import AuditSink
from ..queries import detail_statement, list_statement, primary_key, sort_column
from ..relations import labels_for, options_for
from ..render import is_htmx, project
from ..spec import Registry
from ..views import ListView

if TYPE_CHECKING:
    from ..spec import ModelSpec

LIST_TEMPLATE = "list.html"
ROWS_TEMPLATE = "_rows.html"
DETAIL_TEMPLATE = "detail.html"
MODAL_TEMPLATE = "_modal.html"
FORM_MODAL_TEMPLATE = "_form_modal.html"
FORM_TEMPLATE = "form.html"
CSV_MEDIA_TYPE = "text/csv"
DATABASE_REFUSED = "the database refused this"
DELETED_MESSAGE = "Record {pk} deleted"
CREATED_MESSAGE = "Record {pk} created"
SAVED_MESSAGE = "Record {pk} saved"
BULK_DELETED_MESSAGE = "{count} record(s) deleted"
SELECTION_FIELD = "pk"

Form = Annotated[dict[str, Any], Body(media_type=RequestEncodingType.URL_ENCODED)]


def _selected_keys(data: dict[str, Any]) -> tuple[str, ...]:
    """Read the selected primary keys out of a posted form.

    A single checkbox posts one value and several post a list, so both shapes
    arrive here; empty values are dropped rather than looked up as keys.
    """
    raw = data.get(SELECTION_FIELD)
    if raw is None:
        return ()
    values = raw if isinstance(raw, (list, tuple)) else [raw]
    return tuple(str(value) for value in values if str(value))


def _constraint_detail(exc: IntegrityError) -> str:
    """Summarise what the database objected to, in one line.

    The driver's own message names the constraint, which is the useful part for
    whoever is filling in the form; the surrounding SQL is not.
    """
    detail = str(getattr(exc, "orig", exc) or exc).strip()
    return detail.splitlines()[0] if detail else "constraint violation"


def _filters_from(
    request: Request, spec: ModelSpec
) -> tuple[dict[str, tuple[str, ...]], dict[str, Any]]:
    """Read the spec's declared filters and ranges out of the query string.

    Shared by the list and the export, so the two cannot drift into showing one
    set of rows and downloading another.
    """
    return parse_filters(request.query_params, spec)


def _list_columns_with_key(
    spec: ModelSpec, *extra: str
) -> tuple[str, ...]:
    """List columns plus the primary key, and whatever else the page needs loaded.

    The key is there because a row links to itself. The sort column is there
    because the keyset cursor is read off the last row: a spec whose ``order_by``
    is not one of its list columns would otherwise produce no cursor at all, and
    paging would stop after the first page without saying why.
    """
    columns = list(spec.list_columns)
    for name in (primary_key(spec.model).key, *extra):
        if name not in columns:
            columns.append(name)
    return tuple(columns)


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

    async def _row_or_404(
        self, session: Any, spec: ModelSpec, pk: str
    ) -> Any:
        """Load one record for writing, or raise 404."""
        row = (
            await session.execute(detail_statement(spec, pk))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundException()
        return row

    async def _flush(
        self,
        session: Any,
        spec: ModelSpec,
        admin_path: str,
        request: Request,
        values: dict[str, Any],
        *,
        pk: str | None = None,
    ) -> Template | None:
        """Write pending changes, returning the form again if the database refuses.

        A constraint violation is a statement about the submitted values -- a
        duplicate key, a missing default, a broken reference -- so it belongs in
        the form the values came from, not in a 500. The session is rolled back
        first: after a failed flush it can accept nothing else, and the commit
        ``Admin`` performs when the handler returns would fail in the same way.
        """
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            return await self._form_response(
                session, request, spec, admin_path, pk=pk,
                submitted=values,
                form_error=f"{DATABASE_REFUSED}: {_constraint_detail(exc)}",
            )
        return None

    async def _form_response(
        self,
        session: Any,
        request: Request,
        spec: ModelSpec,
        admin_path: str,
        *,
        pk: str | None,
        row: Any = None,
        submitted: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
        form_error: str | None = None,
    ) -> Template:
        """Render a create or edit form, as a dialog for HTMX and a page otherwise.

        A rejected submission comes back with 200 rather than 422: HTMX does not
        swap an error status by default, and a form the user cannot see is worse
        than a status code that is merely unfussy.
        """
        options = {}
        for column, relation in spec.relations.items():
            resolved = await options_for(session, spec, column, relation)
            if resolved is not None:
                options[column] = resolved
        context = {
            "spec": spec,
            "pk": pk,
            "fields": fields_for(
                spec,
                row=None if row is None else project(row, spec.detail_columns),
                submitted=submitted,
                errors=errors,
                options=options,
            ),
            "errors": errors or {},
            "form_error": form_error,
            "page_url": f"{admin_path}/m/{spec.slug}",
        }
        template = FORM_MODAL_TEMPLATE if is_htmx(request) else FORM_TEMPLATE
        return Template(template, context=context)

    async def _saved_response(
        self,
        session: Any,
        request: Request,
        spec: ModelSpec,
        admin_path: str,
        pk: Any,
        row: Any,
        *,
        created: bool = False,
    ) -> Template | Redirect:
        """Answer a successful write.

        For HTMX the record comes back as the read dialog, carrying an
        out-of-band copy of its own table row so the list behind the dialog stops
        showing stale values. A created record has no row to replace, so the list
        is reloaded instead. Without HTMX it is a redirect to the record's page,
        which is what makes the form work with scripting off.
        """
        page_url = f"{admin_path}/m/{spec.slug}"
        message = (CREATED_MESSAGE if created else SAVED_MESSAGE).format(pk=pk)
        if not is_htmx(request):
            set_flash(request, message)
            return Redirect(f"{page_url}/{pk}", status_code=HTTP_303_SEE_OTHER)
        if created:
            # A new row has nothing to replace in place, so the list is reloaded
            # and picks the message up from the session like any other page.
            set_flash(request, message)
            return Redirect(page_url, status_code=HTTP_303_SEE_OTHER)
        projected = project(row, spec.detail_columns)
        oob_row = project(row, _list_columns_with_key(spec))
        return Template(
            MODAL_TEMPLATE,
            context={
                "spec": spec,
                "pk": pk,
                "row": projected,
                "labels": await labels_for(session, spec, [projected, oob_row]),
                "page_url": page_url,
                # Renders the row again, out of band, next to the dialog.
                "oob_row": oob_row,
                "pk_name": primary_key(spec.model).key,
                # And the message, also out of band: no navigation will happen.
                "flash": {"message": message, "kind": FLASH_KIND_SUCCESS},
            },
        )

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
        sort: FromQuery[str | None] = None,
        direction: FromQuery[str | None] = None,
    ) -> Template:
        """Render a filtered, sorted, paginated list."""
        spec = _spec_or_404(admin_registry, slug, LIST)
        filters, ranges = _filters_from(request, spec)
        # Resolved rather than echoed: the cursor, the header state and the query
        # all have to agree on which column is actually ordering the rows.
        sort = sort_column(spec, sort)
        descending = direction != ASCENDING
        result = (
            await admin_session.execute(
                list_statement(
                    spec, search=search, filters=filters, ranges=ranges,
                    after=after, sort=sort, descending=descending,
                )
            )
        ).scalars().all()
        # A row has to be able to name its own record to link to it, and the
        # primary key is not necessarily one of the columns on display.
        pk_name = primary_key(spec.model).key
        rows = [project(row, _list_columns_with_key(spec, sort)) for row in result]
        labels = await labels_for(admin_session, spec, rows)
        facets = await facets_for(
            admin_session, spec, search=search, filters=filters, ranges=ranges
        )
        cursor = rows[-1].get(sort) if len(rows) == PAGE_SIZE else None
        # One object describing the view, and the only thing that builds a URL
        # for a variation of it -- so a sort link, a filter segment, the paging
        # trigger and the export cannot disagree about what is being shown.
        view = ListView(
            page_url=f"{admin_path}/m/{spec.slug}",
            search=search or "",
            filters=filters,
            ranges=ranges,
            sort=sort,
            direction=ASCENDING if not descending else DESCENDING,
        )
        context = {
            "spec": spec,
            "rows": rows,
            "pk_name": pk_name,
            "search": search,
            "filters": filters,
            "view": view,
            "after": after,
            "cursor": cursor,
            "sort": sort,
            "direction": ASCENDING if not descending else DESCENDING,
            "labels": labels,
            "facets": facets,
            "ranges": ranges,
            # Resolved here, against today, so a preset is absolute dates in a URL
            # rather than a keyword that means something different tomorrow.
            "range_presets": range_presets(datetime.now(timezone.utc).date()),
            # Date and timestamp columns are bounded rather than chosen from.
            "range_filters": tuple(
                name for name in spec.filters if is_range_column(spec, name)
            ),
            # Declared filters with neither a list nor bounds: plain text fields.
            "text_filters": tuple(
                name
                for name in spec.filters
                if name not in facets and not is_range_column(spec, name)
            ),
            "page_url": f"{admin_path}/m/{spec.slug}",
        }
        # A paging click asks for rows to append, not a second copy of the page;
        # the same URL without the HTMX header still renders the whole page, so
        # it stays usable with scripting off.
        if after is not None and is_htmx(request):
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
        search: FromQuery[str | None] = None,
        sort: FromQuery[str | None] = None,
        direction: FromQuery[str | None] = None,
    ) -> Stream:
        """Stream the current view as CSV and audit the export.

        The same search, filters and ordering the list is showing, because the
        button sits in that toolbar: exporting the whole table, or the same rows
        in a different order, is a different result than the one on screen -- and
        silently so, since nobody checks a download against the page.
        """
        spec = _spec_or_404(admin_registry, slug, EXPORT)
        filters, ranges = _filters_from(request, spec)
        sort = sort_column(spec, sort)
        descending = direction != ASCENDING
        result = (
            await admin_session.execute(
                list_statement(
                    spec, search=search, filters=filters, ranges=ranges,
                    sort=sort, descending=descending, limit=EXPORT_LIMIT,
                )
            )
        ).scalars().all()
        rows = [project(row, spec.list_columns) for row in result]
        await admin_audit.write(
            admin_session, actor_of(request), ACTION_EXPORT,
            subject=spec.slug, request=request,
            extra={
                "rows": len(rows),
                "search": search,
                "filters": filters,
                "ranges": {
                    name: [bounds.start, bounds.end] for name, bounds in ranges.items()
                },
                "sort": sort,
                "direction": ASCENDING if not descending else DESCENDING,
            },
        )
        return Stream(
            csv_rows(spec, rows),
            media_type=CSV_MEDIA_TYPE,
            headers={
                "content-disposition": f'attachment; filename="{spec.slug}.csv"'
            },
        )

    @post("/{slug:str}/bulk-delete", status_code=HTTP_303_SEE_OTHER)
    async def bulk_delete(
        self,
        slug: FromPath[str],
        request: Request,
        data: Form,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_audit: NamedDependency[AuditSink],
        admin_path: NamedDependency[str],
    ) -> Redirect:
        """Delete every selected record, auditing each one.

        Audited per record rather than once for the batch: an audit trail answering
        "who deleted invoice 4821" must not depend on someone having reconstructed
        which batch it was in. Loaded and deleted one at a time for the same
        reason -- a bulk ``DELETE`` statement would skip the model's own cascades
        and events.
        """
        spec = _spec_or_404(admin_registry, slug, DELETE)
        keys = _selected_keys(data)
        deleted = 0
        for pk in keys:
            row = (
                await admin_session.execute(detail_statement(spec, pk))
            ).scalar_one_or_none()
            if row is None:
                # Someone else got there first; not an error worth failing on.
                continue
            await admin_session.delete(row)
            await admin_audit.write(
                admin_session, actor_of(request), ACTION_DELETE,
                subject=spec.slug, subject_pk=pk, request=request,
                extra={"bulk": True},
            )
            deleted += 1
        set_flash(request, BULK_DELETED_MESSAGE.format(count=deleted))
        return Redirect(f"{admin_path}/m/{spec.slug}")

    @get("/{slug:str}/new")
    async def create_form(
        self,
        slug: FromPath[str],
        request: Request,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_path: NamedDependency[str],
    ) -> Template:
        """Render a blank form for a new record.

        Takes a session because a relation's choices come from the database.
        """
        spec = _spec_or_404(admin_registry, slug, CREATE)
        return await self._form_response(admin_session, request, spec, admin_path, pk=None)

    @post("/{slug:str}/new")
    async def create(
        self,
        slug: FromPath[str],
        request: Request,
        data: Form,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_audit: NamedDependency[AuditSink],
        admin_path: NamedDependency[str],
    ) -> Template | Redirect:
        """Insert a record from a submitted form, or re-render it with errors."""
        spec = _spec_or_404(admin_registry, slug, CREATE)
        values, errors = parse(spec, data)
        if errors:
            return await self._form_response(
                admin_session, request, spec, admin_path,
                pk=None, submitted=data, errors=errors,
            )
        row = spec.model(**values)
        admin_session.add(row)
        # Flushed here rather than at commit, because the audit entry and the
        # response both need the key the database assigns -- and because a
        # constraint the database enforces is caught here, while there is still
        # a form to send it back to.
        rejected = await self._flush(admin_session, spec, admin_path, request, values)
        if rejected is not None:
            return rejected
        pk = getattr(row, primary_key(spec.model).key)
        await admin_audit.write(
            admin_session, actor_of(request), ACTION_CREATE,
            subject=spec.slug, subject_pk=pk, request=request,
            extra={"columns": sorted(values)},
        )
        return await self._saved_response(
            admin_session, request, spec, admin_path, pk, row, created=True
        )

    @get("/{slug:str}/{pk:str}/edit")
    async def edit_form(
        self,
        slug: FromPath[str],
        pk: FromPath[str],
        request: Request,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_path: NamedDependency[str],
    ) -> Template:
        """Render the form for an existing record."""
        spec = _spec_or_404(admin_registry, slug, EDIT)
        row = await self._row_or_404(admin_session, spec, pk)
        return await self._form_response(
            admin_session, request, spec, admin_path, pk=pk, row=row
        )

    @post("/{slug:str}/{pk:str}/edit")
    async def edit(
        self,
        slug: FromPath[str],
        pk: FromPath[str],
        request: Request,
        data: Form,
        admin_session: NamedDependency[Any],
        admin_registry: NamedDependency[Registry],
        admin_audit: NamedDependency[AuditSink],
        admin_path: NamedDependency[str],
    ) -> Template | Redirect:
        """Apply a submitted form to a record, or re-render it with errors."""
        spec = _spec_or_404(admin_registry, slug, EDIT)
        row = await self._row_or_404(admin_session, spec, pk)
        values, errors = parse(spec, data)
        if errors:
            return await self._form_response(
                admin_session, request, spec, admin_path, pk=pk, row=row,
                submitted=data, errors=errors,
            )
        changed = [
            name for name, value in values.items() if getattr(row, name) != value
        ]
        for name, value in values.items():
            setattr(row, name, value)
        rejected = await self._flush(
            admin_session, spec, admin_path, request, values, pk=pk
        )
        if rejected is not None:
            return rejected
        await admin_audit.write(
            admin_session, actor_of(request), ACTION_UPDATE,
            subject=spec.slug, subject_pk=pk, request=request,
            extra={"changed": sorted(changed)},
        )
        return await self._saved_response(
            admin_session, request, spec, admin_path, pk, row
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
        projected = project(row, spec.detail_columns)
        context = {
            "spec": spec,
            "pk": pk,
            "row": projected,
            "labels": await labels_for(admin_session, spec, [projected]),
            "page_url": f"{admin_path}/m/{spec.slug}",
        }
        # Clicked from a row, the record is wanted over the list it came from, so
        # it arrives as a dialog. Opened directly -- a bookmark, a shared link, or
        # scripting off -- it is a page of its own.
        if is_htmx(request):
            return Template(MODAL_TEMPLATE, context=context)
        return Template(DETAIL_TEMPLATE, context=context)

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
        set_flash(request, DELETED_MESSAGE.format(pk=pk))
        await admin_audit.write(
            admin_session, actor_of(request), ACTION_DELETE,
            subject=spec.slug, subject_pk=pk, request=request,
        )
        return Redirect(f"{admin_path}/m/{spec.slug}")
