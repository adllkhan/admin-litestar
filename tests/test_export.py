"""CSV serialisation."""

import csv
import io

from admin_litestar.export import csv_rows

from .test_spec import WIDGET


def test_header_row_is_the_specs_list_columns() -> None:
    """Export shape follows the spec, so hidden columns cannot appear."""
    lines = list(csv_rows(WIDGET, []))
    assert lines[0].strip().split(",") == list(WIDGET.list_columns)


def test_values_containing_separators_are_quoted() -> None:
    """A comma in a value must not shift columns."""
    rows = [{"id": 1, "name": "a,b", "kind": "k", "created_at": "t"}]
    assert '"a,b"' in list(csv_rows(WIDGET, rows))[1]


def test_newlines_in_values_are_quoted() -> None:
    """A newline in a value must not split the record."""
    rows = [{"id": 1, "name": "a\nb", "kind": "k", "created_at": "t"}]
    assert '"a\nb"' in "".join(list(csv_rows(WIDGET, rows))[1:])


def test_missing_keys_render_as_empty_fields() -> None:
    """A row lacking a column yields an empty field, not a KeyError."""
    lines = list(csv_rows(WIDGET, [{"id": 1}]))
    reader = csv.reader(io.StringIO(lines[1]))
    fields = next(reader)
    assert fields == ["1", "", "", ""]


def test_hidden_columns_never_appear_in_export() -> None:
    """A hidden column in the row dict does not reach the output."""
    rows = [
        {
            "id": 1,
            "name": "w",
            "kind": "k",
            "created_at": "t",
            "_blob_data": b"SECRET",
        }
    ]
    lines = list(csv_rows(WIDGET, rows))
    output = "".join(lines)
    assert "_blob_data" not in output
    assert "SECRET" not in output
