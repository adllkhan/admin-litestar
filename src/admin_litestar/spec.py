"""Declarative per-model admin configuration and the registry holding it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .constants import CAPABILITIES, DELETE

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence


def _column_names(model: type) -> frozenset[str]:
    """Return the mapped column names of a model."""
    return frozenset(column.key for column in model.__table__.columns)


@dataclass(frozen=True, slots=True)
class Relation:
    """What a foreign-key column points at, and how to name it.

    A key column holds an integer; nobody reads an admin to learn that invoice
    4821 belongs to customer 12. Declaring the relation turns that cell into the
    customer's name, linked to its own record, and turns the form control from a
    number field into a list of choices.

    Attributes:
        model: The mapped class the column refers to.
        label: Column on that model to display -- a name, a reference, a title.
        order_by: Column to order the form's choices by; defaults to ``label``.
        slug: Which spec to link to, when more than one exposes ``model``. Left
            unset the registry picks the first spec registered for it, which is
            unambiguous only while there is one.
    """

    model: type
    label: str
    order_by: str | None = None
    slug: str | None = None

    def __post_init__(self) -> None:
        """Reject a label that is not a column on the target."""
        known = _column_names(self.model)
        if self.label not in known:
            raise ValueError(
                f"{self.model.__name__}.{self.label} is not a column; "
                f"a relation label must name one"
            )
        if self.order_by is not None and self.order_by not in known:
            raise ValueError(
                f"{self.model.__name__}.{self.order_by} is not a column"
            )

    @property
    def ordering(self) -> str:
        """The column the choices are ordered by."""
        return self.order_by or self.label


@dataclass(frozen=True, slots=True)
class RowAction:
    """A host-defined button on every row of a list.

    The admin renders it and posts it safely; what it does is the host's route.
    ``path`` is formatted with the row's primary key, so one declaration serves
    every row.

    Attributes:
        label: Text on the button.
        path: URL, with ``{pk}`` where the record's key belongs.
        method: ``"get"`` for a link, ``"post"`` for a form carrying a CSRF token.
        confirm: Whether a POST asks before it fires. Ignored for GET, which is
            not supposed to change anything.
        danger: Whether to style it as destructive.
    """

    label: str
    path: str
    method: str = "get"
    confirm: bool = False
    danger: bool = False

    def __post_init__(self) -> None:
        """Reject a method the admin cannot render, or a path with no key in it."""
        if self.method not in ("get", "post"):
            raise ValueError(
                f"row action {self.label!r}: method must be 'get' or 'post', "
                f"not {self.method!r}"
            )
        if "{pk}" not in self.path:
            raise ValueError(
                f"row action {self.label!r}: path must contain '{{pk}}', so it can "
                f"name the record it acts on"
            )

    def url_for(self, pk: Any) -> str:
        """Return this action's URL for one record."""
        return self.path.format(pk=pk)


@dataclass(frozen=True, slots=True)
class BulkAction:
    """A host-defined button acting on every selected row at once.

    Posted with the selected keys as repeated ``pk`` fields, so the handler reads
    a list rather than being called once per row.

    Attributes:
        label: Text on the button.
        path: URL the selection is posted to. No ``{pk}``: it acts on many.
        confirm: Whether it asks before firing.
        danger: Whether to style it as destructive.
    """

    label: str
    path: str
    confirm: bool = False
    danger: bool = False

    def __post_init__(self) -> None:
        """Reject a path templated for one record, which this is not."""
        if "{pk}" in self.path:
            raise ValueError(
                f"bulk action {self.label!r}: path acts on the selection, so it "
                f"takes no '{{pk}}'; the keys arrive as repeated 'pk' fields"
            )


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """How one model is listed, shown, deleted and exported.

    Attributes:
        model: The mapped class.
        slug: URL-safe identifier, unique within a registry.
        label: Human-readable plural name for the nav and headings.
        group: Nav grouping label.
        list_columns: Columns loaded and rendered in list views.
        detail_columns: Columns loaded and rendered in detail views.
        hidden_columns: Columns permitted in detail views but never in lists.
        excluded_columns: Columns never selected, rendered or exported.
        capabilities: Which routes exist for this model.
        order_by: Column used for ordering and keyset pagination.
        searchable: Columns matched with ILIKE.
        exact_searchable: Columns matched by equality.
        search_transform: Applied to a term before exact matching, letting a
            host search a keyed-digest column by supplying its digest function.
        filters: Columns exposed as equality filters.
        relations: Foreign-key column to :class:`Relation`, so the column reads
            as the related record's label and edits as a choice.
        row_actions: Host-defined buttons rendered on every row.
        bulk_actions: Host-defined buttons acting on the selected rows.
        audit_on_detail: Whether viewing one record is itself auditable.
    """

    model: type
    slug: str
    label: str
    group: str
    list_columns: tuple[str, ...]
    detail_columns: tuple[str, ...]
    capabilities: frozenset[str]
    order_by: str
    hidden_columns: tuple[str, ...] = ()
    excluded_columns: tuple[str, ...] = ()
    searchable: tuple[str, ...] = ()
    exact_searchable: tuple[str, ...] = ()
    search_transform: Callable[[str], str] | None = None
    filters: tuple[str, ...] = ()
    relations: Mapping[str, Relation] = field(default_factory=dict)
    row_actions: tuple[RowAction, ...] = ()
    bulk_actions: tuple[BulkAction, ...] = ()
    audit_on_detail: bool = False

    def __post_init__(self) -> None:
        """Reject contradictory or unknown declarations at construction time."""
        unknown_capabilities = set(self.capabilities) - CAPABILITIES
        if unknown_capabilities:
            raise ValueError(
                f"{self.slug}: unknown capabilities: "
                f"{sorted(unknown_capabilities)}; "
                f"valid values are {sorted(CAPABILITIES)}"
            )
        leaked = set(self.list_columns) & set(self.hidden_columns)
        if leaked:
            raise ValueError(
                f"{self.slug}: hidden columns in list_columns: {sorted(leaked)}"
            )
        declared = set(self.list_columns) | set(self.detail_columns)
        excluded = declared & set(self.excluded_columns)
        if excluded:
            raise ValueError(
                f"{self.slug}: excluded columns declared: {sorted(excluded)}"
            )
        known = _column_names(self.model)
        if self.order_by not in known:
            raise ValueError(f"{self.slug}: order_by {self.order_by!r} is not a column")
        all_declared = declared | set(self.hidden_columns) | set(self.excluded_columns)
        unknown = all_declared - known
        if unknown:
            raise ValueError(f"{self.slug}: unknown columns: {sorted(unknown)}")
        for name in self.relations:
            if name not in known:
                raise ValueError(f"{self.slug}: relation on unknown column: {name}")
            if name not in declared:
                raise ValueError(
                    f"{self.slug}: relation on {name}, which is neither listed "
                    f"nor shown in detail"
                )
        # Validate searchable, exact_searchable, and filters.
        for attr in ("searchable", "exact_searchable", "filters"):
            names = getattr(self, attr)
            if not names:
                continue
            # Check they are real columns.
            unknown = set(names) - known
            if unknown:
                raise ValueError(
                    f"{self.slug}: unknown columns in {attr}: {sorted(unknown)}"
                )
            # Check they are not excluded.
            excluded = set(names) & set(self.excluded_columns)
            if excluded:
                raise ValueError(
                    f"{self.slug}: excluded columns in {attr}: {sorted(excluded)}"
                )

    @property
    def selectable(self) -> bool:
        """Whether rows need checkboxes: something can act on a selection."""
        return bool(self.bulk_actions) or DELETE in self.capabilities

    def renders(self, capability: str) -> bool:
        """True when this spec offers the given capability."""
        return capability in self.capabilities


class Registry:
    """An ordered collection of specs, addressable by slug."""

    def __init__(self, specs: Iterable[ModelSpec]) -> None:
        """Store the specs, rejecting duplicate slugs."""
        self._specs = tuple(specs)
        seen: dict[str, ModelSpec] = {}
        for spec in self._specs:
            if spec.slug in seen:
                raise ValueError(f"duplicate slug: {spec.slug}")
            seen[spec.slug] = spec
        self._by_slug = seen

    @property
    def specs(self) -> Sequence[ModelSpec]:
        """Every registered spec, in declaration order."""
        return self._specs

    @property
    def groups(self) -> tuple[str, ...]:
        """Distinct group labels, in the order they first appear."""
        ordered: list[str] = []
        for spec in self._specs:
            if spec.group not in ordered:
                ordered.append(spec.group)
        return tuple(ordered)

    def get(self, slug: str) -> ModelSpec:
        """Return the spec registered under ``slug``, raising KeyError if absent."""
        return self._by_slug[slug]

    def slug_for(self, model: type) -> str | None:
        """Return the slug registered for a model, or None if it has none.

        A relation names a model, not a slug: the admin URL is this registry's
        business, and a target nobody registered simply renders without a link
        rather than linking somewhere that 404s.
        """
        for spec in self._specs:
            if spec.model is model:
                return spec.slug
        return None

    def in_group(self, group: str) -> tuple[ModelSpec, ...]:
        """Return the specs belonging to one group."""
        return tuple(spec for spec in self._specs if spec.group == group)

    def __contains__(self, slug: object) -> bool:
        """True when a slug is registered."""
        return slug in self._by_slug
