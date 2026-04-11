import sys
from datetime import UTC
from pathlib import Path

import typer

from . import clockify, qonto
from .config import load_env

app = typer.Typer(help="Clockify → Qonto invoicing tool", no_args_is_help=True)
client_app = typer.Typer(help="Manage Qonto clients", no_args_is_help=True)
app.add_typer(client_app, name="client")


@app.command()
def init() -> None:
    """Interactive first-run setup. Prompts for API keys, tests every connection."""
    from .init_cmd import run_init

    run_init()


@app.command()
def discover() -> None:
    """List Clockify projects/clients and Qonto clients to fill invoicer.yaml."""
    load_env()

    typer.echo("\n== Clockify clients ==")
    for cl in clockify.list_clients():
        typer.echo(f"  {cl['id']}  {cl.get('name', '')}")

    typer.echo("\n== Clockify projects ==")
    for p in clockify.list_projects():
        typer.echo(
            f"  {p['id']}  {p.get('name', '')}"
            f"  (client_id={p.get('clientId', '-')})"
        )

    typer.echo("\n== Qonto clients ==")
    for c in qonto.list_clients():
        name = c.get("name") or f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
        typer.echo(f"  {c['id']}  {name}")


@client_app.command("extract")
def client_extract(
    from_file: Path = typer.Option(None, "--from-file", "-f", help="Read source text from a file"),
) -> None:
    """Extract structured client fields from free-form text with Haiku.

    Reads from stdin if --from-file is not given. Prints the extracted dict.
    Does NOT create anything in Qonto — use `client add` for that.
    """
    load_env()
    from .llm import extract_client_fields

    if from_file:
        text = from_file.read_text()
    else:
        typer.echo("Paste client text, then Ctrl-D (EOF) on its own line:", err=True)
        text = sys.stdin.read()

    if not text.strip():
        typer.echo("No input text.", err=True)
        raise typer.Exit(1)

    fields = extract_client_fields(text)
    typer.echo("\n== Extracted fields ==")
    for k, v in fields.items():
        typer.echo(f"  {k}: {v}")


@client_app.command("add")
def client_add(
    from_file: Path = typer.Option(None, "--from-file", "-f", help="Read source text from a file"),
    locale: str = typer.Option("en", help="Qonto client locale: en, it, de, fr, es"),
) -> None:
    """Create a new Qonto client. Extract with Haiku, review, then POST /v2/clients."""
    import questionary

    from .llm import extract_client_fields

    load_env()

    if from_file:
        text = from_file.read_text()
    else:
        typer.echo("Paste client text, then Ctrl-D (EOF) on its own line:", err=True)
        text = sys.stdin.read()
    if not text.strip():
        typer.echo("No input text.", err=True)
        raise typer.Exit(1)

    typer.echo("Extracting fields with Haiku...", err=True)
    fields = extract_client_fields(text)

    typer.echo("\n== Extracted (edit any field, press Enter to accept) ==\n")
    editable_keys = [
        "name",
        "country_code",
        "vat_number",
        "tax_identification_number",
        "street_address",
        "city",
        "zip_code",
        "province_code",
        "email",
        "pec_email",
        "recipient_code",
    ]
    for k in editable_keys:
        fields[k] = questionary.text(f"{k}:", default=str(fields.get(k, ""))).ask()

    if fields.get("confidence_notes"):
        typer.echo(f"\nLLM notes: {fields['confidence_notes']}")

    payload = qonto.build_client_payload(fields, locale=locale)
    from .summary import print_client_summary
    print_client_summary(payload, endpoint="POST https://thirdparty.qonto.com/v2/clients")

    if not questionary.confirm("Create this client in Qonto?", default=False).ask():
        typer.echo("Aborted.", err=True)
        raise typer.Exit(0)

    created = qonto.create_client(payload)
    typer.echo(f"\n✓ Created Qonto client: {created.get('id')}")
    typer.echo(f"  Name: {created.get('name')}")


@app.command()
def draft(
    project: str = typer.Argument(..., help="Project alias from invoicer.yaml, or raw Clockify project id"),
    month: str = typer.Option(..., help="Billing month, YYYY-MM"),
    purchase_order: str = typer.Option(None, help="Optional PO / reference printed on the invoice"),
) -> None:
    """Create a Qonto draft invoice for a Clockify project + month."""
    from calendar import monthrange
    from datetime import date, datetime, timedelta

    import questionary

    from . import project_config
    from .summary import print_invoice_summary

    load_env()

    # Parse month
    try:
        year, mon = (int(x) for x in month.split("-"))
        period_start = datetime(year, mon, 1, tzinfo=UTC)
        period_end = datetime(year, mon, monthrange(year, mon)[1], 23, 59, 59, tzinfo=UTC)
    except (ValueError, IndexError) as e:
        typer.echo(f"Invalid --month {month!r}, expected YYYY-MM.", err=True)
        raise typer.Exit(1) from e

    # Fuzzy search for a project match. Prompt on ambiguity.
    matches = project_config.find_projects(project)
    if not matches:
        typer.echo(
            f"No project in invoicer.yaml matches {project!r}. "
            f"Run `invoicer discover` or edit invoicer.yaml to add it.",
            err=True,
        )
        raise typer.Exit(1)
    if len(matches) == 1:
        project_id, proj_cfg = matches[0]
        name = proj_cfg.get("name", "(unnamed)")
        alias = proj_cfg.get("alias", "")
        typer.echo(
            f"→ Matched: {name}  [{alias}]  ({project_id})", err=True
        )
    else:
        choices = [
            questionary.Choice(
                title=f"{(cfg or {}).get('name', '(unnamed)')}  "
                      f"[{(cfg or {}).get('alias', '')}]",
                value=pid,
            )
            for pid, cfg in matches
        ]
        project_id = questionary.select(
            f"{len(matches)} projects match {project!r}. Pick one:",
            choices=choices,
        ).ask()
        if not project_id:
            typer.echo("Aborted.", err=True)
            raise typer.Exit(1)
        proj_cfg = project_config.get_project(project_id)
    rate = float(proj_cfg["rate_eur_per_hour"])
    vat_rate = float(proj_cfg.get("vat_rate", 0))
    vat_exemption_reason = proj_cfg.get("vat_exemption_reason")
    rounding = int(proj_cfg.get("rounding_minutes", 15))
    payment_terms_days = int(proj_cfg.get("payment_terms_days", 30))
    description_template = proj_cfg.get(
        "description_template", "Consulting services — {month_name} {year}"
    )
    project_name_cfg = proj_cfg.get("name", project_id)

    # Clockify → Qonto client resolution
    typer.echo("Fetching Clockify project...", err=True)
    cp = clockify.get_project(project_id)
    clockify_client_id = cp.get("clientId")
    if not clockify_client_id:
        typer.echo(f"Clockify project {project_id} has no client assigned.", err=True)
        raise typer.Exit(1)
    qonto_client_id = project_config.resolve_qonto_client_id(clockify_client_id)

    typer.echo("Fetching Qonto client...", err=True)
    qc = qonto.get_client(qonto_client_id)
    qonto_client_name = qc.get("name", qonto_client_id)

    # Aggregate
    typer.echo(
        f"Aggregating Clockify billable hours ({period_start.date()} → {period_end.date()}, "
        f"per-entry ceiling {rounding} min)...",
        err=True,
    )
    agg = clockify.aggregate_billable_hours(
        project_id, period_start, period_end, round_up_minutes=rounding
    )
    if agg["entry_count"] == 0:
        typer.echo("No billable entries in that period. Nothing to invoice.", err=True)
        raise typer.Exit(1)

    billed_hours = agg["billed_hours"]
    subtotal = billed_hours * rate
    vat_amount = subtotal * (vat_rate / 100)
    total = subtotal + vat_amount

    # Dates
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    month_name = month_names[mon - 1]
    # description_template is preserved in config for forward compatibility but not
    # rendered onto per-entry line items in v0.1.
    _ = description_template
    issue_date = date.today().isoformat()
    due_date = (date.today() + timedelta(days=payment_terms_days)).isoformat()

    # Build one Qonto line item per Clockify entry (chronological)
    items = []
    for e in agg["entries"]:
        items.append(
            qonto.build_invoice_item(
                title=e["description"],
                description=f"{e['date']} · {e['user']}",
                quantity=e["billed_hours"],
                unit_price_eur=rate,
                vat_rate_pct=vat_rate,
                vat_exemption_reason=vat_exemption_reason,
            )
        )

    payload = qonto.build_invoice_payload(
        client_id=qonto_client_id,
        issue_date=issue_date,
        due_date=due_date,
        items=items,
        purchase_order=purchase_order,
        status="draft",
    )

    # Pre-mutation summary
    print_invoice_summary(
        client_name=qonto_client_name,
        client_id=qonto_client_id,
        project_name=project_name_cfg,
        period_label=f"{month_name} {year} ({period_start.date()} → {period_end.date()})",
        raw_hours=agg["raw_hours"],
        billed_hours=billed_hours,
        rounding_rule=f"per-entry ceiling {rounding} min",
        unit_price_eur=rate,
        vat_rate_pct=vat_rate,
        vat_exemption_reason=vat_exemption_reason,
        subtotal_eur=subtotal,
        vat_eur=vat_amount,
        total_eur=total,
        status="draft",
        issue_date=issue_date,
        due_date=due_date,
        purchase_order=purchase_order,
        endpoint="POST https://thirdparty.qonto.com/v2/client_invoices",
        line_entries=agg["entries"],
    )

    if not questionary.confirm("Create this DRAFT invoice in Qonto?", default=False).ask():
        typer.echo("Aborted.", err=True)
        raise typer.Exit(0)

    created = qonto.create_client_invoice(payload)
    typer.echo("\n✓ Created Qonto draft invoice")
    typer.echo(f"  id:     {created.get('id')}")
    typer.echo(f"  number: {created.get('number', '(auto)')}")
    typer.echo(f"  status: {created.get('status')}")
    if created.get("invoice_url"):
        typer.echo(f"  url:    {created['invoice_url']}")


@app.command()
def finalize(
    invoice_id: str = typer.Argument(..., help="Qonto invoice id (UUID)"),
) -> None:
    """Finalize a Qonto draft invoice. IRREVERSIBLE — locks number, queues SDI."""
    import questionary

    from .summary import print_finalize_summary

    load_env()
    inv = qonto.get_invoice(invoice_id)
    current_status = inv.get("status", "")
    if current_status != "draft":
        typer.echo(
            f"Invoice status is {current_status!r}, not 'draft'. Nothing to finalize.",
            err=True,
        )
        raise typer.Exit(1)

    print_finalize_summary(inv)

    # Typed confirmation: the user must retype the invoice number (minus -PROFORMA)
    number = (inv.get("number") or "").replace("-PROFORMA", "")
    if not number:
        typer.echo("Invoice has no number — cannot build typed confirmation.", err=True)
        raise typer.Exit(1)

    typer.echo()
    typed = questionary.text(
        f"Type the invoice number {number!r} exactly, to confirm (anything else aborts):",
    ).ask()
    if typed != number:
        typer.echo("Aborted — confirmation text did not match.", err=True)
        raise typer.Exit(1)

    finalized = qonto.finalize_invoice(invoice_id)
    typer.echo(f"\n✓ Finalized invoice {finalized.get('number')}")
    typer.echo(f"  status:            {finalized.get('status')}")
    typer.echo(f"  einvoicing_status: {finalized.get('einvoicing_status', '(not set)')}")
    typer.echo(f"  invoice_url:       {finalized.get('invoice_url', '')}")


@app.command("mail-draft")
def mail_draft(
    invoice_id: str = typer.Argument(..., help="Qonto invoice id (UUID)"),
    to: str = typer.Option(None, help="Override recipient (default: client.email on Qonto)"),
    cc_self: bool = typer.Option(True, help="CC GMAIL_SENDER for your own paper trail"),
) -> None:
    """Download the invoice PDF and create a Gmail draft with it attached.

    Does NOT send. The draft appears in [Gmail]/Drafts for manual review + send.
    """
    import os

    import questionary

    from .csv_export import build_invoice_csv
    from .gmail import build_invoice_email, create_draft
    from .summary import print_mail_draft_summary

    load_env()

    inv = qonto.get_invoice(invoice_id)
    if inv.get("status") == "draft":
        typer.echo(
            f"Invoice is still a draft. Finalize it first:\n"
            f"  invoicer finalize {invoice_id}",
            err=True,
        )
        raise typer.Exit(1)

    client = inv.get("client", {}) or {}
    recipient = to or client.get("email")
    if not recipient:
        typer.echo(
            "No recipient: invoice client has no email, and --to was not given.",
            err=True,
        )
        raise typer.Exit(1)

    number = inv.get("number", "")
    total_obj = inv.get("total_amount") or {}
    total = total_obj.get("value") if isinstance(total_obj, dict) else total_obj
    issue_date = inv.get("issue_date", "")
    due_date = inv.get("due_date", "")
    client_name = client.get("name", "")

    typer.echo("Downloading invoice PDF from Qonto...", err=True)
    pdf_filename, pdf_bytes = qonto.download_invoice_pdf(invoice_id)

    # CSV derived from the invoice's own line items
    csv_bytes = build_invoice_csv(inv)
    csv_filename = f"timesheet-{number}.csv"

    sender = os.environ["GMAIL_SENDER"]
    sender_name = os.environ.get("GMAIL_SENDER_NAME") or sender.split("@", 1)[0].capitalize()
    subject = f"{client_name} — Invoice {number}"
    body = (
        f"Hello,\n\n"
        f"Please find attached our invoice {number} for consulting services.\n\n"
        f"- Issue date: {issue_date}\n"
        f"- Due date:   {due_date}\n"
        f"- Amount:     €{total}\n"
        f"- Payment:    bank transfer (IBAN on the invoice)\n\n"
        f"VAT is not applied — intra-EU B2B service.\n\n"
        f"Please let us know if you have any questions.\n\n"
        f"Best regards,\n"
        f"{sender_name}\n"
    )

    cc = sender if cc_self else None
    print_mail_draft_summary(
        sender=sender,
        recipient=recipient,
        cc=cc,
        subject=subject,
        body_preview=body,
        pdf_filename=f"{pdf_filename} + {csv_filename}",
        pdf_size_bytes=len(pdf_bytes) + len(csv_bytes),
    )

    if not questionary.confirm(
        "Create Gmail draft (not send)?", default=True
    ).ask():
        typer.echo("Aborted.", err=True)
        raise typer.Exit(0)

    msg = build_invoice_email(
        sender=sender,
        recipient=recipient,
        cc=cc,
        subject=subject,
        body_text=body,
        attachments=[
            (pdf_filename, "application", "pdf", pdf_bytes),
            (csv_filename, "text", "csv", csv_bytes),
        ],
    )
    draft = create_draft(msg)
    typer.echo("\n✓ Gmail draft created")
    typer.echo(f"  draft_id: {draft.get('id')}")
    typer.echo("  Open Gmail web → Drafts → review → click Send.")


if __name__ == "__main__":
    app()
