"""Form fields and value coercion for the write routes.

The single place a string arriving from a browser becomes a column value. Two
rules hold everything else together: a field exists only because the spec put
its column in ``detail_columns``, and the primary key is never one of them.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from .queries import primary_key

if TYPE_CHECKING:
    from .spec import ModelSpec

# Kinds map to input types in the template. Kept coarse deliberately: a column's
# storage type is a poor guide to its meaning, so this offers correct handling
# rather than clever widgets.
TEXT = "text"
TEXTAREA = "textarea"
NUMBER = "number"
INTEGER = "integer"
CHECKBOX = "checkbox"
DATETIME = "datetime"
DATE = "date"
SELECT = "select"
RELATION = "relation"

TEXTAREA_MIN_LENGTH = 240
TRUTHY = frozenset({"on", "true", "1", "yes"})
REQUIRED_MESSAGE = "required"
NUMBER_MESSAGE = "must be a number"
INTEGER_MESSAGE = "must be a whole number"
DATETIME_MESSAGE = "must be a date and time, as 2026-08-03T14:30"
DATE_MESSAGE = "must be a date, as 2026-08-03"
CHOICE_MESSAGE = "not one of the permitted values"


@dataclass(frozen=True, slots=True)
class Field:
    """One editable column, as a form needs to see it.

    Attributes:
        name: Column name, and the form field name.
        kind: Which control renders it.
        required: Whether the column refuses NULL.
        choices: Permitted values, for an enumerated column.
        options: ``(value, label)`` pairs, for a foreign key rendered as a
            choice. Empty when the column is not a relation, or when the target
            has too many rows to enumerate.
        value: The current value, pre-formatted for the control.
        error: Validation message from a rejected submission, if any.
    """

    name: str
    kind: str
    required: bool
    choices: tuple[str, ...] = ()
    options: tuple[tuple[str, str], ...] = ()
    value: str = ""
    error: str | None = None

    @property
    def checked(self) -> bool:
        """True when a checkbox field should render checked."""
        return self.value == "true"


def _kind_of(column: Any) -> str:
    """Classify a column into one of the form kinds."""
    if getattr(column.type, "enums", None):
        return SELECT
    try:
        python_type = column.type.python_type
    except NotImplementedError:
        return TEXT
    if python_type is bool:
        return CHECKBOX
    if python_type is int:
        return INTEGER
    if python_type in (float, Decimal):
        return NUMBER
    if python_type is datetime.datetime:
        return DATETIME
    if python_type is datetime.date:
        return DATE
    length = getattr(column.type, "length", None)
    if python_type is str and (length is None or length >= TEXTAREA_MIN_LENGTH):
        return TEXTAREA
    return TEXT


def _format(value: Any, kind: str) -> str:
    """Render a stored value into what the control expects to receive back."""
    if value is None:
        return ""
    if kind == CHECKBOX:
        return "true" if value else "false"
    if kind == DATETIME and isinstance(value, datetime.datetime):
        # The datetime-local control neither sends nor accepts an offset.
        return value.replace(tzinfo=None, microsecond=0).isoformat()
    if kind == DATE and isinstance(value, datetime.date):
        return value.isoformat()
    return str(value)


def editable_columns(spec: ModelSpec) -> tuple[str, ...]:
    """Return the columns a form may write.

    Every detail column except the primary key: a key is what identifies the
    row being edited, so allowing it to be rewritten in the same request would
    mean the form could silently address a different record. Anything else a
    host wants kept out of reach belongs in ``hidden_columns`` or
    ``excluded_columns``, which this never sees.
    """
    key = primary_key(spec.model).key
    return tuple(name for name in spec.detail_columns if name != key)


def fields_for(
    spec: ModelSpec,
    row: dict[str, Any] | None = None,
    submitted: dict[str, Any] | None = None,
    errors: dict[str, str] | None = None,
    options: dict[str, tuple[tuple[str, str], ...]] | None = None,
) -> tuple[Field, ...]:
    """Build the fields for a create or edit form.

    ``row`` supplies current values when editing. ``submitted`` and ``errors``
    are the rejected values and their messages, so a failed submission comes
    back with what was typed rather than with the stored values again.
    ``options`` carries the choices for relation columns, resolved by the caller
    because they need a database.
    """
    columns = spec.model.__table__.columns
    fields = []
    for name in editable_columns(spec):
        column = columns[name]
        kind = _kind_of(column)
        # A foreign key is a number only incidentally; offered as a list of
        # records it stops being one a person has to know by heart.
        relation_options = (options or {}).get(name)
        if relation_options is not None:
            kind = RELATION
        if submitted is not None and name in submitted:
            value = str(submitted[name])
        else:
            value = _format(None if row is None else row.get(name), kind)
        fields.append(
            Field(
                name=name,
                kind=kind,
                required=not column.nullable,
                choices=tuple(getattr(column.type, "enums", ()) or ()),
                options=relation_options or (),
                value=value,
                error=None if errors is None else errors.get(name),
            )
        )
    return tuple(fields)


def _coerce(column: Any, kind: str, raw: str) -> Any:
    """Turn one submitted string into a column value, or raise ValueError."""
    text = raw.strip()
    if kind == CHECKBOX:
        return text.lower() in TRUTHY
    if text == "":
        if not column.nullable:
            raise ValueError(REQUIRED_MESSAGE)
        return None
    if kind == INTEGER:
        try:
            return int(text)
        except ValueError as exc:
            raise ValueError(INTEGER_MESSAGE) from exc
    if kind == NUMBER:
        try:
            number = Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(NUMBER_MESSAGE) from exc
        return float(number) if column.type.python_type is float else number
    if kind == DATETIME:
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(DATETIME_MESSAGE) from exc
        if parsed.tzinfo is None and column.type.timezone:
            # A timezone-aware column refuses a naive value; the control cannot
            # send an offset, so the only honest reading is UTC.
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed
    if kind == DATE:
        try:
            return datetime.date.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(DATE_MESSAGE) from exc
    if kind == SELECT and text not in (getattr(column.type, "enums", ()) or ()):
        raise ValueError(CHOICE_MESSAGE)
    return text



def parse(
    spec: ModelSpec, data: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Coerce a submitted form into column values, collecting per-field errors.

    Only editable columns are read, so a field the form never offered cannot be
    written by adding it to the request body. An unchecked checkbox sends
    nothing at all, which is what makes it False rather than missing.
    """
    columns = spec.model.__table__.columns
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for name in editable_columns(spec):
        column = columns[name]
        kind = _kind_of(column)
        raw = data.get(name)
        if raw is None and kind != CHECKBOX:
            continue
        try:
            values[name] = _coerce(column, kind, "" if raw is None else str(raw))
        except ValueError as exc:
            errors[name] = str(exc)
    return values, errors
