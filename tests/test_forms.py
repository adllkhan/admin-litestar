"""Field derivation and the coercion of submitted strings into column values."""

import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from admin_litestar import CREATE, DETAIL, EDIT, LIST, ModelSpec
from admin_litestar.forms import editable_columns, fields_for, parse

from .models import Base


class Thing(Base):
    """A model with one column of each shape a form has to handle."""

    __tablename__ = "form_thing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    blurb: Mapped[str | None] = mapped_column(Text, nullable=True)
    count: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    active: Mapped[bool] = mapped_column(Boolean)
    starts_on: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    seen_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))


THING = ModelSpec(
    model=Thing,
    slug="thing",
    label="Things",
    group="Things",
    list_columns=("id", "name"),
    detail_columns=(
        "id", "name", "blurb", "count", "price", "active", "starts_on", "seen_at",
    ),
    capabilities=frozenset({LIST, DETAIL, EDIT, CREATE}),
    order_by="id",
)


def test_the_primary_key_is_never_editable() -> None:
    """A rewritable key would let one form address a different record."""
    assert "id" not in editable_columns(THING)
    assert editable_columns(THING) == (
        "name", "blurb", "count", "price", "active", "starts_on", "seen_at",
    )


def test_fields_classify_columns_by_the_control_they_need() -> None:
    """Each column arrives as something a browser can render."""
    kinds = {field.name: field.kind for field in fields_for(THING)}
    assert kinds == {
        "name": "text",
        "blurb": "textarea",
        "count": "integer",
        "price": "number",
        "active": "checkbox",
        "starts_on": "date",
        "seen_at": "datetime",
    }


def test_fields_mark_non_nullable_columns_required() -> None:
    """Requiredness comes from the column, not from a second declaration."""
    required = {field.name: field.required for field in fields_for(THING)}
    assert required["name"] is True
    assert required["blurb"] is False
    assert required["starts_on"] is False


def test_fields_carry_current_values_formatted_for_their_control() -> None:
    """An edit form opens on what is stored, in the format the control accepts."""
    row = {
        "name": "widget",
        "blurb": None,
        "count": 3,
        "price": Decimal("12.50"),
        "active": True,
        "starts_on": datetime.date(2026, 8, 3),
        "seen_at": datetime.datetime(2026, 8, 3, 14, 30, tzinfo=datetime.timezone.utc),
    }
    values = {field.name: field.value for field in fields_for(THING, row=row)}
    assert values["name"] == "widget"
    assert values["blurb"] == ""
    assert values["price"] == "12.50"
    assert values["active"] == "true"
    assert values["starts_on"] == "2026-08-03"
    # datetime-local neither sends nor accepts an offset
    assert values["seen_at"] == "2026-08-03T14:30:00"


def test_a_rejected_submission_comes_back_with_what_was_typed() -> None:
    """Re-rendering stored values would discard the user's work silently."""
    fields = fields_for(
        THING,
        row={"name": "stored", "count": 1},
        submitted={"name": "typed", "count": "not a number"},
        errors={"count": "must be a whole number"},
    )
    by_name = {field.name: field for field in fields}
    assert by_name["name"].value == "typed"
    assert by_name["count"].value == "not a number"
    assert by_name["count"].error == "must be a whole number"
    assert by_name["name"].error is None


def test_parse_coerces_each_kind_to_its_python_type() -> None:
    """A form sends strings; a column wants values."""
    values, errors = parse(
        THING,
        {
            "name": " widget ",
            "blurb": "",
            "count": "42",
            "price": "12.50",
            "active": "true",
            "starts_on": "2026-08-03",
            "seen_at": "2026-08-03T14:30",
        },
    )
    assert errors == {}
    assert values["name"] == "widget"
    assert values["blurb"] is None
    assert values["count"] == 42
    assert values["price"] == Decimal("12.50")
    assert values["active"] is True
    assert values["starts_on"] == datetime.date(2026, 8, 3)
    # A timezone-aware column cannot take a naive value, and the control cannot
    # send an offset, so UTC is the only honest reading.
    assert values["seen_at"] == datetime.datetime(
        2026, 8, 3, 14, 30, tzinfo=datetime.timezone.utc
    )


def test_an_unchecked_checkbox_is_false_rather_than_missing() -> None:
    """A browser sends nothing for an unchecked box, which still means false."""
    values, errors = parse(THING, {"name": "widget"})
    assert errors == {}
    assert values["active"] is False
    # a field absent from the body is left alone, not nulled
    assert "count" not in values


@pytest.mark.parametrize(
    ("field", "raw", "message"),
    [
        ("count", "many", "must be a whole number"),
        ("price", "cheap", "must be a number"),
        ("starts_on", "yesterday", "must be a date, as 2026-08-03"),
        ("seen_at", "noon", "must be a date and time, as 2026-08-03T14:30"),
        ("name", "", "required"),
    ],
)
def test_bad_input_is_reported_per_field(field: str, raw: str, message: str) -> None:
    """Errors name the field and say what would be acceptable."""
    values, errors = parse(THING, {field: raw})
    assert errors == {field: message}
    assert field not in values


def test_a_field_the_form_never_offered_cannot_be_written() -> None:
    """Only editable columns are read, so an extra body field is inert."""
    values, _ = parse(THING, {"name": "widget", "id": "99", "nonsense": "x"})
    assert "id" not in values
    assert "nonsense" not in values
