"""Generate CSV timesheet from a Qonto invoice's line items.

Each item has:
  - title       = Clockify entry description (the work)
  - description = "YYYY-MM-DD · username"  (set by the draft builder)
  - quantity    = billed hours (string decimal)
  - unit_price  = {"value": "85.00", "currency": "EUR"}
"""

import csv
import io
import re

_DATE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*[·\-]?\s*(.*?)\s*$")

# Cells starting with these characters can be interpreted as formulas by
# Excel / LibreOffice / Google Sheets when a CSV is opened. Prepend a
# single-quote (standard OWASP mitigation) to neutralize them.
_FORMULA_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: str) -> str:
    """Escape a leading formula-trigger character. Returns value unchanged otherwise."""
    s = str(value or "")
    if s and s[0] in _FORMULA_PREFIX:
        return "'" + s
    return s


def _parse_date_user(description: str) -> tuple[str, str]:
    """Parse a 'YYYY-MM-DD · username' (or similar) metadata line."""
    m = _DATE_RE.match(description or "")
    if not m:
        return "", (description or "").strip()
    return m.group(1), m.group(2).strip()


def build_invoice_csv(invoice: dict) -> bytes:
    """Return UTF-8 CSV bytes with one row per line item."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["date", "user", "work", "hours", "unit_price_eur", "subtotal_eur"])
    total_hours = 0.0
    total_subtotal = 0.0
    for item in invoice.get("items") or []:
        date, user = _parse_date_user(item.get("description", ""))
        work = item.get("title", "")
        try:
            hours = float(item.get("quantity") or 0)
        except (TypeError, ValueError):
            hours = 0.0
        unit_price_obj = item.get("unit_price") or {}
        try:
            unit_price = float(unit_price_obj.get("value") or 0)
        except (TypeError, ValueError):
            unit_price = 0.0
        subtotal = hours * unit_price
        total_hours += hours
        total_subtotal += subtotal
        writer.writerow(
            [
                _sanitize_cell(date),
                _sanitize_cell(user),
                _sanitize_cell(work),
                f"{hours:.2f}",
                f"{unit_price:.2f}",
                f"{subtotal:.2f}",
            ]
        )
    writer.writerow([])
    writer.writerow(["", "", "TOTAL", f"{total_hours:.2f}", "", f"{total_subtotal:.2f}"])
    return buf.getvalue().encode("utf-8")
