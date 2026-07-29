"""Declarative per-model admin configuration and the registry holding it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence


def _column_names(model: type) -> frozenset[str]:
    """Return the mapped column names of a model."""
    return frozenset(column.key for column in model.__table__.columns)


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
    audit_on_detail: bool = False

    def __post_init__(self) -> None:
        """Reject contradictory column declarations at construction time."""
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
        unknown = declared - known
        if unknown:
            raise ValueError(f"{self.slug}: unknown columns: {sorted(unknown)}")

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

    def in_group(self, group: str) -> tuple[ModelSpec, ...]:
        """Return the specs belonging to one group."""
        return tuple(spec for spec in self._specs if spec.group == group)

    def __contains__(self, slug: object) -> bool:
        """True when a slug is registered."""
        return slug in self._by_slug
