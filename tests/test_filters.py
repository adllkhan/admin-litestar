"""Where a filter's values come from, and what asking for them costs."""

from typing import Any

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from admin_litestar import DETAIL, LIST, ModelSpec
from admin_litestar.constants import FILTER_CHOICE_LIMIT
from admin_litestar.filters import declared_choices, facets_for

from .models import Base


class Ticket(Base):
    """One column that declares its values, one that does not."""

    __tablename__ = "filter_ticket"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(
        Enum("open", "held", "closed", name="ticket_state")
    )
    queue: Mapped[str] = mapped_column(String(20))


def _spec(*filters: str) -> ModelSpec:
    """A spec filtering on the named columns."""
    return ModelSpec(
        model=Ticket,
        slug="ticket",
        label="Tickets",
        group="Support",
        list_columns=("id", "state", "queue"),
        detail_columns=("id", "state", "queue"),
        capabilities=frozenset({LIST, DETAIL}),
        order_by="id",
        filters=filters,
    )


class _Result:
    """A result answering with fixed ``(value, count)`` pairs."""

    def __init__(self, pairs: list[tuple[Any, int]]) -> None:
        self._pairs = pairs

    def all(self) -> list[tuple[Any, int]]:
        return self._pairs


class _Session:
    """Records every statement and answers each with the same pairs."""

    def __init__(self, pairs: list[tuple[Any, int]]) -> None:
        self.pairs = pairs
        self.statements: list[str] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(str(statement))
        return _Result(self.pairs)


def test_a_column_that_declares_its_values_is_not_asked_for_them() -> None:
    """An enumerated column already knows its set."""
    assert declared_choices(_spec(), "state") == ("open", "held", "closed")
    assert declared_choices(_spec(), "queue") is None


async def test_an_enum_column_costs_one_query_and_keeps_its_own_order() -> None:
    """The value set comes from the column, so only the counts are asked for.

    Declaration order is kept rather than sorted: a lifecycle reads open, held,
    closed, and alphabetising it would say closed, held, open.
    """
    session = _Session([("open", 4), ("closed", 9)])
    facets = await facets_for(session, _spec("state"))
    assert len(session.statements) == 1, "no query for the value set"
    assert [facet.value for facet in facets["state"]] == ["open", "held", "closed"]
    # a declared value the data does not hold is offered at zero
    assert [facet.count for facet in facets["state"]] == [4, 0, 9]
    assert facets["state"][1].empty is True


async def test_a_plain_column_costs_two_queries() -> None:
    """One asks what values exist at all, the other how many are in this view.

    The set has to be independent of the view, or selecting one filter would make
    another filter's options disappear.
    """
    session = _Session([("billing", 3), ("ops", 5)])
    facets = await facets_for(session, _spec("queue"), search="x")
    assert len(session.statements) == 2
    values, counted = session.statements
    assert "LIKE" not in values.upper(), "the value set ignores the search"
    assert [facet.value for facet in facets["queue"]] == ["billing", "ops"]


async def test_a_column_with_too_many_values_is_left_to_a_text_field() -> None:
    """A truncated list of options hides the rest with no way to reach them."""
    session = _Session([(f"queue-{index}", 1) for index in range(FILTER_CHOICE_LIMIT + 1)])
    assert await facets_for(session, _spec("queue")) == {}


async def test_a_spec_with_no_filters_asks_nothing() -> None:
    """Nothing declared, nothing queried."""
    session = _Session([])
    assert await facets_for(session, _spec()) == {}
    assert session.statements == []


def test_presets_are_absolute_dates_not_keywords() -> None:
    """A shared URL has to mean the same list tomorrow.

    "last 7 days" as a keyword would quietly name a different week each time the
    link is opened, which makes a filtered list impossible to cite.
    """
    import datetime

    from admin_litestar.filters import range_presets

    presets = {p.label: (p.start, p.end) for p in range_presets(datetime.date(2026, 8, 4))}
    assert presets["Today"] == ("2026-08-04", "2026-08-04")
    # inclusive of today, so seven days means six back
    assert presets["7 days"] == ("2026-07-29", "2026-08-04")
    assert presets["30 days"] == ("2026-07-06", "2026-08-04")
    assert presets["This month"] == ("2026-08-01", "2026-08-04")


def test_presets_cross_a_month_boundary_without_arithmetic_errors() -> None:
    """The first of a month is the awkward case for every date control."""
    import datetime

    from admin_litestar.filters import range_presets

    presets = {p.label: (p.start, p.end) for p in range_presets(datetime.date(2026, 3, 1))}
    assert presets["This month"] == ("2026-03-01", "2026-03-01")
    # 1 March inclusive back six days lands on 23 February; 2026 has 28 of them
    assert presets["7 days"] == ("2026-02-23", "2026-03-01")
    assert presets["30 days"] == ("2026-01-31", "2026-03-01")


def test_a_preset_recognises_the_bounds_it_would_set() -> None:
    """Which segment is filled is decided by comparing, not by remembering."""
    import datetime

    from admin_litestar.filters import Range, range_presets

    today = range_presets(datetime.date(2026, 8, 4))[0]
    assert today.matches(Range("2026-08-04", "2026-08-04")) is True
    assert today.matches(Range("2026-08-01", "2026-08-04")) is False
    assert today.matches(None) is False
    # an unbounded preset would match no bounds at all
    from admin_litestar.filters import RangePreset

    assert RangePreset(label="All").matches(None) is True
