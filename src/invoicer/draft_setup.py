"""`invoicer draft` auto-onboarding wizard.

When `draft` is invoked against a Clockify project that isn't yet registered
in invoicer.yaml, this module walks the user through:

  1. Resolving the Clockify client to a Qonto client (C1: exact-name match
     with confirm gate, or ranked picker on ambiguity).
  2. Validating the Qonto client record has the fields Qonto needs for an
     invoice (VAT number, IT-SDI fields, address, …) — prompting + PATCHing
     on gaps.
  3. Synthesizing a `projects:` entry with sensible defaults (rate from
     Clockify, VAT from country pair, alias from project name) and showing
     a single review panel for confirmation.

Pure helpers (VAT defaults, alias derivation, completeness check) are
separated from the interactive wrappers for testability.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import questionary
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import project_config, qonto

_console = Console()


# -------- Pure helpers (tested without I/O) --------------------------------

EU_COUNTRY_CODES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
    "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL",
    "PT", "RO", "SE", "SI", "SK",
}


def vat_defaults_for_country_pair(
    org_country: str | None,
    client_country: str | None,
) -> dict:
    """Return {vat_rate, vat_exemption_reason} defaults for the country pair."""
    oc = (org_country or "").upper()
    cc = (client_country or "").upper()

    if not oc or not cc:
        return {"vat_rate": 0, "vat_exemption_reason": None}

    if oc == "IT":
        if cc == "IT":
            return {"vat_rate": 22, "vat_exemption_reason": None}
        if cc in EU_COUNTRY_CODES:
            return {"vat_rate": 0, "vat_exemption_reason": "N3.2"}
        return {"vat_rate": 0, "vat_exemption_reason": "N3.1"}

    if oc == "DE":
        if cc == "DE":
            return {"vat_rate": 19, "vat_exemption_reason": None}
        return {"vat_rate": 0, "vat_exemption_reason": None}

    if oc == cc:
        return {"vat_rate": 0, "vat_exemption_reason": None}
    return {"vat_rate": 0, "vat_exemption_reason": None}


def derive_alias_from_name(project_name: str) -> str:
    """Derive a short alias from a Clockify project name.

    'r001-03 - ommi.shop' → 'r001-03'
    'OptionFactory Recruitment SaaS' → 'optionfactory'
    """
    name = (project_name or "").strip()
    if not name:
        return ""
    parts = re.split(r"\s*[-–—]\s*", name, maxsplit=1)
    token = parts[0].strip()
    if re.match(r"^[a-zA-Z]\d{3}-\d{2}", token):
        return token.lower()
    return re.sub(r"[^a-z0-9-]", "", name.split()[0].lower()) if name else ""


def check_client_completeness(
    client: dict,
    org_country: str | None,
) -> list[str]:
    """Return a list of missing field names required for invoicing.

    Empty list = client is complete enough to invoice against.
    """
    missing: list[str] = []
    cc = (client.get("billing_address") or {}).get("country_code", "")
    cc = (cc or "").upper()

    for field in ("name",):
        if not client.get(field):
            missing.append(field)

    ba = client.get("billing_address") or {}
    for field in ("street_address", "city", "zip_code", "country_code"):
        if not ba.get(field):
            missing.append(field)

    if not client.get("email"):
        missing.append("email")

    if cc in EU_COUNTRY_CODES and not client.get("vat_number"):
        missing.append("vat_number")

    if cc == "IT":
        if not client.get("tax_identification_number"):
            missing.append("tax_identification_number")
        if not ba.get("province_code"):
            missing.append("province_code")
        has_sdi = client.get("recipient_code") or client.get("pec_email")
        if not has_sdi:
            missing.append("recipient_code or pec_email")

    return missing


def synthesize_project_entry(
    *,
    clockify_project: dict,
    org_country: str | None,
    client_country: str | None,
) -> dict:
    """Build a default project entry dict from Clockify data + country pair."""
    name = clockify_project.get("name", "")
    alias = derive_alias_from_name(name)

    hourly = clockify_project.get("hourlyRate") or {}
    rate_raw = hourly.get("amount", 0)
    rate = rate_raw / 100 if rate_raw > 100 else rate_raw

    vat = vat_defaults_for_country_pair(org_country, client_country)

    return {
        "alias": alias,
        "name": name,
        "rate_eur_per_hour": rate,
        "vat_rate": vat["vat_rate"],
        "vat_exemption_reason": vat["vat_exemption_reason"],
        "description_template": "Consulting services — {month_name} {year}",
        "payment_terms_days": 30,
        "rounding_minutes": 15,
    }


# -------- Interactive wrappers --------------------------------------------

def _rank_qonto_clients(
    qonto_clients: list[dict],
    clockify_client_name: str,
) -> list[dict]:
    """Rank Qonto clients by name similarity to the Clockify client."""
    target = (clockify_client_name or "").lower().strip()
    scored = []
    for c in qonto_clients:
        qname = (c.get("name") or "").lower().strip()
        ratio = SequenceMatcher(None, target, qname).ratio()
        scored.append((ratio, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def ensure_client_mapping(
    *,
    clockify_client_id: str,
    clockify_client_name: str,
    org_id: str | None,
) -> str:
    """Return a Qonto client id, registering the mapping if missing.

    C1 logic: exact-name match → confirm gate. Otherwise → ranked picker.
    """
    try:
        return project_config.resolve_qonto_client_id(
            clockify_client_id, org_id=org_id
        )
    except RuntimeError:
        pass

    typer.echo(
        f"\nClockify client '{clockify_client_name}' ({clockify_client_id}) "
        f"has no Qonto mapping yet.",
        err=True,
    )
    typer.echo("Fetching Qonto client list...", err=True)
    qonto_clients = qonto.list_clients()
    if not qonto_clients:
        typer.echo("No Qonto clients found. Create one first with `invoicer client add`.", err=True)
        raise typer.Exit(1)

    target_norm = (clockify_client_name or "").lower().strip()
    exact = [
        c for c in qonto_clients
        if (c.get("name") or "").lower().strip() == target_norm
    ]

    if len(exact) == 1:
        c = exact[0]
        cc = (c.get("billing_address") or {}).get("country_code", "?")
        typer.echo(
            f"\n→ Exact name match: {c['name']}  ({cc}, {c['id']})",
            err=True,
        )
        if not questionary.confirm("Use this Qonto client?", default=True).ask():
            exact = []

    if not exact:
        ranked = _rank_qonto_clients(qonto_clients, clockify_client_name)
        choices = [
            questionary.Choice(
                title=f"{c.get('name', '?')}  "
                      f"({(c.get('billing_address') or {}).get('country_code', '?')}, "
                      f"{c['id'][:12]}…)",
                value=c["id"],
            )
            for c in ranked[:10]
        ]
        choices.append(questionary.Choice(title="Enter UUID manually", value="__manual__"))
        choices.append(questionary.Choice(title="Abort", value="__abort__"))

        picked = questionary.select(
            "Pick the Qonto client for this Clockify client:",
            choices=choices,
        ).ask()

        if picked == "__abort__" or not picked:
            typer.echo("Aborted.", err=True)
            raise typer.Exit(1)

        if picked == "__manual__":
            picked = questionary.text("Qonto client UUID:").ask()
            if not picked or not picked.strip():
                typer.echo("Aborted.", err=True)
                raise typer.Exit(1)
            picked = picked.strip()

        qonto_client_id = picked
    else:
        qonto_client_id = exact[0]["id"]

    mapping: dict = {
        "clockify_id": clockify_client_id,
        "qonto_id": qonto_client_id,
    }
    if org_id:
        mapping["org"] = org_id

    project_config.append_client_mapping(mapping)
    typer.echo(
        "✓ Saved client mapping → invoicer.yaml",
        err=True,
    )
    return qonto_client_id


def ensure_client_complete(
    *,
    qonto_client_id: str,
    org_country: str | None,
) -> dict:
    """Validate Qonto client completeness, prompt + PATCH on gaps.

    Returns the (possibly refreshed) client dict.
    """
    client = qonto.get_client(qonto_client_id)
    missing = check_client_completeness(client, org_country)

    if not missing:
        return client

    typer.echo(
        f"\nQonto client '{client.get('name')}' is missing fields "
        f"needed for invoicing: {', '.join(missing)}",
        err=True,
    )
    typer.echo("Fill them in now to continue.\n", err=True)

    from .summary import print_client_summary

    patch_payload: dict = {}
    patch_billing: dict = {}

    for field in missing:
        if field == "recipient_code or pec_email":
            val = questionary.text("recipient_code (7-char SDI code, or empty for PEC):").ask() or ""
            if val.strip():
                patch_payload["recipient_code"] = val.strip().upper()
            else:
                pec = questionary.text("pec_email:").ask() or ""
                if pec.strip():
                    patch_payload["recipient_code"] = "0000000"
                    if not client.get("email"):
                        patch_payload["email"] = pec.strip()
        elif field in ("street_address", "city", "zip_code", "country_code", "province_code"):
            val = questionary.text(f"{field}:").ask() or ""
            if val.strip():
                patch_billing[field] = val.strip()
                if field == "country_code":
                    patch_billing[field] = patch_billing[field].upper()
                if field == "province_code":
                    patch_billing[field] = patch_billing[field].upper()
        else:
            val = questionary.text(f"{field}:").ask() or ""
            if val.strip():
                patch_payload[field] = val.strip()

    if patch_billing:
        patch_payload["billing_address"] = {
            **(client.get("billing_address") or {}),
            **patch_billing,
        }

    if not patch_payload:
        typer.echo("No fields filled — continuing with incomplete client.", err=True)
        return client

    summary_fields = {
        "name": patch_payload.get("name", client.get("name", "")),
        "country_code": (patch_payload.get("billing_address") or client.get("billing_address") or {}).get("country_code", ""),
        **(client.get("billing_address") or {}),
        **patch_billing,
        **{k: v for k, v in patch_payload.items() if k != "billing_address"},
    }
    payload_for_summary = qonto.build_client_payload(summary_fields)
    print_client_summary(
        payload_for_summary,
        endpoint=f"PATCH https://thirdparty.qonto.com/v2/clients/{qonto_client_id}",
    )

    if not questionary.confirm("Update this client in Qonto?", default=False).ask():
        typer.echo("Skipping client update — continuing with incomplete data.", err=True)
        return client

    updated = qonto.update_client(qonto_client_id, patch_payload)
    typer.echo(f"✓ Updated Qonto client {qonto_client_id}", err=True)
    return updated


def ensure_project_registered(
    *,
    project_id: str,
    clockify_project: dict,
    org_country: str | None,
    qonto_client_country: str | None,
) -> dict:
    """Return the project config dict, synthesizing + registering on miss.

    Shows a single review panel; user can accept all or edit fields inline.
    """
    try:
        return project_config.get_project(project_id)
    except RuntimeError:
        pass

    entry = synthesize_project_entry(
        clockify_project=clockify_project,
        org_country=org_country,
        client_country=qonto_client_country,
    )

    typer.echo(
        f"\nProject '{entry['name']}' isn't registered in invoicer.yaml yet.",
        err=True,
    )

    vat_label = f"{entry['vat_rate']}%"
    if entry.get("vat_exemption_reason"):
        vat_label += f"  ({entry['vat_exemption_reason']})"

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dim", justify="right", no_wrap=True)
    table.add_column()
    table.add_row("Alias", entry["alias"])
    table.add_row("Name", entry["name"])
    table.add_row("Rate (€/h)", str(entry["rate_eur_per_hour"]))
    table.add_row("VAT", vat_label)
    table.add_row("Payment terms", f"{entry['payment_terms_days']} days")
    table.add_row("Rounding", f"{entry['rounding_minutes']} min")
    table.add_row("Description", entry["description_template"])

    _console.print(Panel(
        table,
        title="[bold cyan]New project — review defaults[/bold cyan]",
        subtitle="[dim]Will be saved to invoicer.yaml[/dim]",
        border_style="cyan",
    ))

    edit = questionary.confirm(
        "Accept these defaults? (n = edit field by field)", default=True,
    ).ask()
    if edit is None:
        typer.echo("Aborted.", err=True)
        raise typer.Exit(1)

    if not edit:
        entry["alias"] = questionary.text(
            "alias:", default=entry["alias"],
        ).ask() or entry["alias"]
        entry["name"] = questionary.text(
            "name:", default=entry["name"],
        ).ask() or entry["name"]
        rate_str = questionary.text(
            "rate_eur_per_hour:", default=str(entry["rate_eur_per_hour"]),
        ).ask() or str(entry["rate_eur_per_hour"])
        entry["rate_eur_per_hour"] = float(rate_str)
        vat_str = questionary.text(
            "vat_rate:", default=str(entry["vat_rate"]),
        ).ask() or str(entry["vat_rate"])
        entry["vat_rate"] = float(vat_str)
        entry["vat_exemption_reason"] = questionary.text(
            "vat_exemption_reason (empty = none):",
            default=entry.get("vat_exemption_reason") or "",
        ).ask() or None
        terms_str = questionary.text(
            "payment_terms_days:", default=str(entry["payment_terms_days"]),
        ).ask() or str(entry["payment_terms_days"])
        entry["payment_terms_days"] = int(terms_str)
        round_str = questionary.text(
            "rounding_minutes:", default=str(entry["rounding_minutes"]),
        ).ask() or str(entry["rounding_minutes"])
        entry["rounding_minutes"] = int(round_str)
        entry["description_template"] = questionary.text(
            "description_template:", default=entry["description_template"],
        ).ask() or entry["description_template"]

    if entry["rate_eur_per_hour"] <= 0:
        rate_str = questionary.text(
            "Rate is 0 — Clockify has no hourly rate set. Enter rate (€/h):",
        ).ask()
        if not rate_str or float(rate_str) <= 0:
            typer.echo("Cannot draft with 0 rate. Aborted.", err=True)
            raise typer.Exit(1)
        entry["rate_eur_per_hour"] = float(rate_str)

    project_config.append_project_entry(project_id, entry)
    typer.echo("✓ Saved project → invoicer.yaml", err=True)
    return entry
