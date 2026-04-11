"""Pre-mutation summary helpers.

Every write path (create client, create invoice, finalize) prints one of these
before asking for confirmation. Human-readable, explicit about reversibility.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

_console = Console()


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    t = Table(show_header=False, box=None, padding=(0, 1))
    t.add_column(style="dim", justify="right", no_wrap=True)
    t.add_column()
    for k, v in rows:
        t.add_row(k, v if v else "[dim]—[/dim]")
    return t


def print_client_summary(payload: dict, *, endpoint: str) -> None:
    """Summary for POST /v2/clients."""
    ba = payload.get("billing_address", {})
    address = "\n".join(
        filter(
            None,
            [
                ba.get("street_address"),
                " ".join(filter(None, [ba.get("zip_code"), ba.get("city")])),
                ba.get("province_code"),
                ba.get("country_code"),
            ],
        )
    )
    rows = [
        ("Legal name", payload.get("name", "")),
        ("Kind", payload.get("kind", "")),
        ("Country", ba.get("country_code", "")),
        ("VAT number", payload.get("vat_number", "")),
        ("Tax ID", payload.get("tax_identification_number", "")),
        ("Address", address),
        ("Email", payload.get("email", "")),
        ("Currency", payload.get("currency", "")),
        ("Locale", payload.get("locale", "")),
    ]
    if ba.get("country_code") == "IT":
        rows.append(("Recipient code (SDI)", payload.get("recipient_code", "")))
    panel = Panel(
        _kv_table(rows),
        title="[bold yellow]About to CREATE Qonto client[/bold yellow]",
        subtitle=f"[dim]{endpoint}  ·  reversible: yes (edit/delete in Qonto UI)[/dim]",
        border_style="yellow",
    )
    _console.print(panel)


def print_finalize_summary(inv: dict) -> None:
    """Pre-mutation summary for POST /v2/client_invoices/{id}/finalize."""
    client = inv.get("client", {}) or {}
    total = inv.get("total_amount") or {}
    total_val = total.get("value") if isinstance(total, dict) else total
    rows = [
        ("Invoice id", inv.get("id", "")),
        ("Invoice #", inv.get("number", "")),
        ("Client", client.get("name", "")),
        ("Country", client.get("country_code", "")),
        ("VAT", client.get("vat_number", "")),
        ("Total", f"€{total_val}" if total_val else ""),
        ("Issue date", inv.get("issue_date", "")),
        ("Due date", inv.get("due_date", "")),
        ("Status now", inv.get("status", "")),
        ("Status after", "[bold red]unpaid (finalized)[/bold red]"),
        ("SDI after", "[bold]queued (pending)[/bold]"),
    ]
    panel = Panel(
        _kv_table(rows),
        title="[bold red]⚠  ABOUT TO FINALIZE — IRREVERSIBLE[/bold red]",
        subtitle="[dim]POST /v2/client_invoices/{id}/finalize  ·  locks number, queues SDI submission[/dim]",
        border_style="red",
    )
    _console.print(panel)
    _console.print()
    _console.print(
        "[red bold]This is IRREVERSIBLE.[/red bold] The number locks in, and for IT orgs "
        "Qonto queues the invoice for SDI (Italian tax authority) submission. Once SDI "
        "accepts, voiding requires issuing a credit note."
    )


def print_mail_draft_summary(
    *,
    sender: str,
    recipient: str,
    cc: str | None,
    subject: str,
    body_preview: str,
    pdf_filename: str,
    pdf_size_bytes: int,
) -> None:
    """Pre-mutation summary for Gmail IMAP APPEND to Drafts."""
    rows = [
        ("From", sender),
        ("To", recipient),
        ("Cc", cc or ""),
        ("Subject", subject),
        ("Attachment", f"{pdf_filename}  [dim]({pdf_size_bytes:,} bytes)[/dim]"),
    ]
    panel = Panel(
        _kv_table(rows),
        title="[bold cyan]About to CREATE Gmail draft[/bold cyan]",
        subtitle="[dim]Gmail API drafts.create  ·  scope gmail.modify (cannot send)  ·  draft appears in Gmail for review[/dim]",
        border_style="cyan",
    )
    _console.print(panel)
    _console.print("\n[dim]Body preview:[/dim]")
    for line in body_preview.splitlines()[:10]:
        _console.print(f"  [dim]{line}[/dim]")
    if len(body_preview.splitlines()) > 10:
        _console.print("  [dim]...[/dim]")


def print_invoice_summary(
    *,
    client_name: str,
    client_id: str,
    project_name: str,
    period_label: str,
    raw_hours: float,
    billed_hours: float,
    rounding_rule: str,
    unit_price_eur: float,
    vat_rate_pct: float,
    vat_exemption_reason: str | None,
    subtotal_eur: float,
    vat_eur: float,
    total_eur: float,
    status: str,
    issue_date: str,
    due_date: str,
    purchase_order: str | None,
    endpoint: str,
    line_entries: list[dict] | None = None,
) -> None:
    """Summary for POST /v2/client_invoices.

    If `line_entries` is provided (each dict: date, user, description,
    raw_hours, billed_hours), a detailed line table is printed above the totals.
    """
    vat_label = f"{vat_rate_pct:g}%"
    if vat_exemption_reason:
        vat_label += f"  (reverse charge, {vat_exemption_reason})"

    if line_entries:
        lt = Table(title=f"Invoice lines ({len(line_entries)})", title_style="dim")
        lt.add_column("Date", no_wrap=True, style="dim")
        lt.add_column("User", no_wrap=True)
        lt.add_column("Description", overflow="fold", max_width=60)
        lt.add_column("Raw", justify="right", no_wrap=True, style="dim")
        lt.add_column("Billed", justify="right", no_wrap=True)
        lt.add_column("€", justify="right", no_wrap=True)
        for e in line_entries:
            amt = e["billed_hours"] * unit_price_eur
            lt.add_row(
                e["date"],
                e["user"],
                e["description"],
                f"{e['raw_hours']:.2f}h",
                f"{e['billed_hours']:.2f}h",
                f"€{amt:,.2f}",
            )
        _console.print(lt)

    rows = [
        ("Client", f"{client_name}  [dim]({client_id})[/dim]"),
        ("Project", project_name),
        ("Period", period_label),
        ("Hours (raw)", f"{raw_hours:.2f}h"),
        ("Hours (billed)", f"{billed_hours:.2f}h  [dim]{rounding_rule}[/dim]"),
        ("Lines", str(len(line_entries)) if line_entries else "1 (summary)"),
        ("", ""),
        ("Unit price", f"€{unit_price_eur:,.2f} / h"),
        ("VAT", vat_label),
        ("", ""),
        ("Subtotal", f"€{subtotal_eur:,.2f}"),
        ("VAT amount", f"€{vat_eur:,.2f}"),
        ("[bold]Total[/bold]", f"[bold]€{total_eur:,.2f}[/bold]"),
        ("", ""),
        ("Issue date", issue_date),
        ("Due date", due_date),
        ("Purchase order", purchase_order or ""),
        ("Status", f"[bold]{status.upper()}[/bold]"),
    ]
    reversible = (
        "yes  ·  draft only, not sent to SDI"
        if status == "draft"
        else "[red]NO  ·  finalize submits to SDI[/red]"
    )
    panel = Panel(
        _kv_table(rows),
        title="[bold yellow]About to CREATE Qonto invoice[/bold yellow]",
        subtitle=f"[dim]{endpoint}  ·  reversible: {reversible}[/dim]",
        border_style="yellow" if status == "draft" else "red",
    )
    _console.print(panel)
