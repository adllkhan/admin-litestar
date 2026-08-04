"""Foreign keys: labels in place of keys, and choices in place of a number field."""

from types import SimpleNamespace

from litestar.plugins.jinja import JinjaTemplateEngine
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from admin_litestar import CREATE, DETAIL, EDIT, LIST, ModelSpec, Relation
from admin_litestar.forms import fields_for
from admin_litestar.relations import labels_for, options_for
from admin_litestar.render import render_value
from admin_litestar.spec import Registry
from admin_litestar.templates import TEMPLATES

from .models import Base, Widget


class Parent(Base):
    """The target of the relation under test."""

    __tablename__ = "relation_parent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40))


class _Result:
    """A result answering with fixed (key, label) pairs."""

    def __init__(self, pairs: list[tuple[object, object]]) -> None:
        self._pairs = pairs

    def all(self) -> list[tuple[object, object]]:
        return self._pairs


class _Session:
    """A session recording statements and answering with canned pairs."""

    def __init__(self, pairs: list[tuple[object, object]], total: int = 2) -> None:
        self.pairs = pairs
        self.total = total
        self.statements: list[str] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(str(statement))
        return _Result(self.pairs)

    async def scalar(self, statement: object) -> int:
        self.statements.append(str(statement))
        return self.total


PARENT = ModelSpec(
    model=Parent,
    slug="parent",
    label="Parents",
    group="Things",
    list_columns=("id", "name"),
    detail_columns=("id", "name"),
    capabilities=frozenset({LIST, DETAIL}),
    order_by="id",
)

CHILD = ModelSpec(
    model=Widget,
    slug="child",
    label="Children",
    group="Things",
    list_columns=("id", "kind"),
    detail_columns=("id", "kind"),
    capabilities=frozenset({LIST, DETAIL, EDIT, CREATE}),
    order_by="id",
    # `kind` stands in for a foreign key column: the code cares only that the
    # column holds a key into the target model.
    relations={"kind": Relation(model=Parent, label="name")},
)


async def test_labels_are_resolved_in_one_query_per_relation() -> None:
    """A query per row is how an admin list becomes slow."""
    session = _Session([(1, "First"), (2, "Second")])
    rows = [{"kind": 1}, {"kind": 2}, {"kind": 1}]
    labels = await labels_for(session, CHILD, rows)
    assert labels == {"kind": {1: "First", 2: "Second"}}
    assert len(session.statements) == 1


async def test_a_relation_with_no_values_on_the_page_costs_no_query() -> None:
    """Nothing to resolve means nothing to ask."""
    session = _Session([])
    assert await labels_for(session, CHILD, [{"kind": None}]) == {}
    assert session.statements == []


async def test_choices_are_withheld_when_the_target_is_too_large() -> None:
    """A truncated list of options hides records with no way to pick them."""
    session = _Session([(1, "First")], total=10_000)
    assert await options_for(session, CHILD, "kind", CHILD.relations["kind"]) is None


async def test_choices_are_offered_when_the_target_is_small() -> None:
    """A short target enumerates, and the pairs are strings for the control."""
    session = _Session([(1, "First"), (2, "Second")], total=2)
    options = await options_for(session, CHILD, "kind", CHILD.relations["kind"])
    assert options == (("1", "First"), ("2", "Second"))


def test_a_relation_field_becomes_a_choice() -> None:
    """The form stops asking for a key by hand."""
    fields = {
        field.name: field
        for field in fields_for(CHILD, options={"kind": (("1", "First"),)})
    }
    assert fields["kind"].kind == "relation"
    assert fields["kind"].options == (("1", "First"),)
    # without resolved options the column stays whatever its type says
    plain = {field.name: field for field in fields_for(CHILD)}
    assert plain["kind"].kind != "relation"


def _render(template: str, **context: object) -> str:
    engine = JinjaTemplateEngine(directory=TEMPLATES)
    return engine.get_template(template).render(
        render_value=render_value, admin_path="/admin", **context
    )


def test_a_key_renders_as_a_linked_label() -> None:
    """The cell reads as the related record, and reaches it."""
    html = _render(
        "_row.html",
        spec=CHILD,
        row={"id": 7, "kind": 2},
        pk_name="id",
        labels={"kind": {2: "Second"}},
        registry=Registry([CHILD, PARENT]),
        page_url="/admin/m/child",
    )
    assert 'href="/admin/m/parent/2"' in html
    assert "Second" in html
    assert ">2<" not in html, "the key is not what a reader wants to see"


def test_an_unregistered_target_renders_a_label_without_a_link() -> None:
    """There is nowhere to link, so nothing pretends there is."""
    html = _render(
        "_row.html",
        spec=CHILD,
        row={"id": 7, "kind": 2},
        pk_name="id",
        labels={"kind": {2: "Second"}},
        registry=Registry([CHILD]),
        page_url="/admin/m/child",
    )
    assert "Second" in html
    assert "href=\"/admin/m/" not in html.split("<td>")[-1]


def test_an_unresolved_key_falls_back_to_the_key() -> None:
    """A row whose target has been deleted still has to render."""
    html = _render(
        "_row.html",
        spec=CHILD,
        row={"id": 7, "kind": 99},
        pk_name="id",
        labels={"kind": {}},
        registry=Registry([CHILD, PARENT]),
        page_url="/admin/m/child",
    )
    assert "99" in html


def test_an_explicit_slug_settles_which_spec_a_relation_links_to() -> None:
    """Two specs can expose one model, and then the model alone is ambiguous.

    An admin with "All customers" and "Active customers" registers the same class
    twice; a link resolved by model would land on whichever came first, silently.
    Naming the slug on the relation makes the choice the host's.
    """
    ambiguous = ModelSpec(
        model=Parent,
        slug="parents-archive",
        label="Archived parents",
        group="Things",
        list_columns=("id", "name"),
        detail_columns=("id", "name"),
        capabilities=frozenset({LIST, DETAIL}),
        order_by="id",
    )
    spec = ModelSpec(
        model=Widget,
        slug="child2",
        label="Children",
        group="Things",
        list_columns=("id", "kind"),
        detail_columns=("id", "kind"),
        capabilities=frozenset({LIST, DETAIL}),
        order_by="id",
        relations={
            "kind": Relation(model=Parent, label="name", slug="parents-archive")
        },
    )
    html = _render(
        "_row.html",
        spec=spec,
        row={"id": 7, "kind": 2},
        pk_name="id",
        labels={"kind": {2: "Second"}},
        # PARENT is registered first, so the model alone would resolve to it
        registry=Registry([PARENT, ambiguous, spec]),
        page_url="/admin/m/child2",
    )
    assert 'href="/admin/m/parents-archive/2"' in html
