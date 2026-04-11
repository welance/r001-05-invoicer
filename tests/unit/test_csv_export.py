"""Unit tests for the CSV timesheet exporter.

The CSV is derived from a Qonto invoice's line items, so these tests assert
that the parsing of the `description` metadata line is robust and that totals
add up to the same numbers shown on the invoice PDF.
"""

import csv
import io

from invoicer.csv_export import _parse_date_user, _sanitize_cell, build_invoice_csv


class TestSanitizeCell:
    def test_plain_text_unchanged(self):
        assert _sanitize_cell("hello world") == "hello world"

    def test_empty_unchanged(self):
        assert _sanitize_cell("") == ""

    def test_none_returns_empty(self):
        assert _sanitize_cell(None) == ""

    def test_equals_prefix_escaped(self):
        assert _sanitize_cell("=SUM(A1:A10)") == "'=SUM(A1:A10)"

    def test_plus_prefix_escaped(self):
        assert _sanitize_cell("+1234") == "'+1234"

    def test_minus_prefix_escaped(self):
        assert _sanitize_cell("-bugs") == "'-bugs"

    def test_at_prefix_escaped(self):
        assert _sanitize_cell("@SUM") == "'@SUM"

    def test_tab_prefix_escaped(self):
        assert _sanitize_cell("\t=BAD") == "'\t=BAD"

    def test_formula_in_middle_not_escaped(self):
        assert _sanitize_cell("user=admin") == "user=admin"


class TestParseDateUser:
    def test_standard_format(self):
        assert _parse_date_user("2026-03-17 · Misiti") == ("2026-03-17", "Misiti")

    def test_double_space_no_separator(self):
        # This is what Qonto returned at one point — the · was dropped.
        assert _parse_date_user("2026-03-17  Misiti") == ("2026-03-17", "Misiti")

    def test_hyphen_separator(self):
        assert _parse_date_user("2026-03-17 - Misiti") == ("2026-03-17", "Misiti")

    def test_username_with_space(self):
        assert _parse_date_user("2026-03-17 · Enrico Icardi") == (
            "2026-03-17",
            "Enrico Icardi",
        )

    def test_username_with_unicode(self):
        assert _parse_date_user("2026-03-17 · José García") == (
            "2026-03-17",
            "José García",
        )

    def test_no_date_returns_full_string_as_user(self):
        assert _parse_date_user("freeform note") == ("", "freeform note")

    def test_empty_description(self):
        assert _parse_date_user("") == ("", "")

    def test_none_description(self):
        assert _parse_date_user(None) == ("", "")


class TestBuildInvoiceCsv:
    def _invoice_with_items(self, items):
        return {"items": items}

    def test_single_item(self):
        inv = self._invoice_with_items(
            [
                {
                    "title": "Webshop refactor",
                    "description": "2026-03-17 · Misiti",
                    "quantity": "3",
                    "unit_price": {"value": "85.00", "currency": "EUR"},
                }
            ]
        )
        csv_bytes = build_invoice_csv(inv)
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))

        assert rows[0] == [
            "date",
            "user",
            "work",
            "hours",
            "unit_price_eur",
            "subtotal_eur",
        ]
        assert rows[1] == ["2026-03-17", "Misiti", "Webshop refactor", "3.00", "85.00", "255.00"]
        # Blank row + total row at the end
        assert rows[-1] == ["", "", "TOTAL", "3.00", "", "255.00"]

    def test_multiple_items_total_sum(self):
        inv = self._invoice_with_items(
            [
                {
                    "title": "Task A",
                    "description": "2026-03-17 · Alice",
                    "quantity": "1.5",
                    "unit_price": {"value": "100", "currency": "EUR"},
                },
                {
                    "title": "Task B",
                    "description": "2026-03-18 · Bob",
                    "quantity": "2",
                    "unit_price": {"value": "100", "currency": "EUR"},
                },
            ]
        )
        csv_bytes = build_invoice_csv(inv)
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
        # Total row is last, should sum hours (3.5) and subtotals (350)
        total_row = rows[-1]
        assert total_row[3] == "3.50"
        assert total_row[5] == "350.00"

    def test_empty_items(self):
        csv_bytes = build_invoice_csv({"items": []})
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
        # Header + blank + total row
        assert rows[0][0] == "date"
        assert rows[-1] == ["", "", "TOTAL", "0.00", "", "0.00"]

    def test_missing_items_key(self):
        csv_bytes = build_invoice_csv({})
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
        assert rows[0][0] == "date"  # still produces header

    def test_quantity_and_price_strings(self):
        """Qonto returns quantity and unit_price as strings — must parse cleanly."""
        inv = self._invoice_with_items(
            [
                {
                    "title": "Task",
                    "description": "2026-03-17 · Alice",
                    "quantity": "23.25",
                    "unit_price": {"value": "85.00", "currency": "EUR"},
                }
            ]
        )
        csv_bytes = build_invoice_csv(inv)
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
        assert rows[1][3] == "23.25"
        assert rows[1][5] == "1976.25"  # 23.25 × 85

    def test_float_precision_regression(self):
        """23.25 × 85 should equal exactly 1976.25, not 1976.2499999."""
        inv = self._invoice_with_items(
            [
                {
                    "title": "Task",
                    "description": "2026-03-17 · Alice",
                    "quantity": "23.25",
                    "unit_price": {"value": "85.00", "currency": "EUR"},
                }
            ]
        )
        csv_bytes = build_invoice_csv(inv).decode("utf-8")
        assert "1976.25" in csv_bytes

    def test_csv_injection_in_work_description(self):
        """A Clockify description starting with = must NOT become an Excel formula."""
        inv = self._invoice_with_items(
            [
                {
                    "title": "=SUM(A1:A10)",
                    "description": "2026-03-17 · Alice",
                    "quantity": "1",
                    "unit_price": {"value": "100", "currency": "EUR"},
                }
            ]
        )
        csv_bytes = build_invoice_csv(inv)
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
        # The work cell should have a leading single quote to neutralize the formula
        assert rows[1][2].startswith("'=")

    def test_csv_injection_in_username(self):
        """A username starting with @ must be sanitized."""
        inv = self._invoice_with_items(
            [
                {
                    "title": "Work",
                    "description": "2026-03-17 · @admin",
                    "quantity": "1",
                    "unit_price": {"value": "100", "currency": "EUR"},
                }
            ]
        )
        csv_bytes = build_invoice_csv(inv)
        rows = list(csv.reader(io.StringIO(csv_bytes.decode("utf-8"))))
        assert rows[1][1].startswith("'@")
