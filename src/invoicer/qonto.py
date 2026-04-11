import os

import httpx

BASE = "https://thirdparty.qonto.com/v2"


def _client() -> httpx.Client:
    login = os.environ["QONTO_LOGIN"]
    secret = os.environ["QONTO_SECRET_KEY"]
    return httpx.Client(
        base_url=BASE,
        headers={"Authorization": f"{login}:{secret}"},
        timeout=30,
    )


def list_clients() -> list[dict]:
    """Paginated list of Qonto clients."""
    out: list[dict] = []
    page = 1
    with _client() as c:
        while True:
            r = c.get("/clients", params={"per_page": 100, "page": page})
            r.raise_for_status()
            data = r.json()
            batch = data.get("clients", [])
            out.extend(batch)
            meta = data.get("meta", {}) or {}
            total_pages = meta.get("total_pages") or 1
            if page >= total_pages or not batch:
                break
            page += 1
    return out


def get_client(client_id: str) -> dict:
    with _client() as c:
        r = c.get(f"/clients/{client_id}")
        r.raise_for_status()
        return r.json().get("client", {})


def get_organization() -> dict:
    with _client() as c:
        r = c.get("/organization")
        r.raise_for_status()
        return r.json().get("organization", {})


def get_main_bank_account() -> dict:
    """Returns the primary (main=True) EUR bank account for the org."""
    org = get_organization()
    accounts = org.get("bank_accounts", [])
    for a in accounts:
        if a.get("main") and a.get("status") == "active":
            return a
    for a in accounts:
        if a.get("status") == "active":
            return a
    raise RuntimeError("No active bank account found on Qonto organization")


def build_client_payload(
    fields: dict,
    *,
    currency: str = "EUR",
    locale: str = "en",
) -> dict:
    """Translate the flat extracted fields into Qonto's POST /v2/clients shape."""
    payload: dict = {
        "kind": "company",
        "name": fields["name"],
        "currency": currency,
        "locale": locale,
        "billing_address": {
            "street_address": fields.get("street_address", ""),
            "city": fields.get("city", ""),
            "zip_code": fields.get("zip_code", ""),
            "country_code": fields.get("country_code", "").upper(),
        },
    }
    if fields.get("vat_number"):
        payload["vat_number"] = fields["vat_number"]
    if fields.get("tax_identification_number"):
        payload["tax_identification_number"] = fields["tax_identification_number"]
    if fields.get("email"):
        payload["email"] = fields["email"]
    # Italian SDI fields
    if payload["billing_address"]["country_code"] == "IT":
        if fields.get("province_code"):
            payload["billing_address"]["province_code"] = fields["province_code"].upper()
        if fields.get("recipient_code"):
            payload["recipient_code"] = fields["recipient_code"]
        elif fields.get("pec_email"):
            # Qonto convention (unverified in docs): PEC-only clients use recipient_code "0000000"
            # and PEC lands in email or extra_emails. Flag this in the review step.
            payload["recipient_code"] = "0000000"
            if not payload.get("email"):
                payload["email"] = fields["pec_email"]
    return payload


def create_client(payload: dict) -> dict:
    """POST /v2/clients. Returns the created client object."""
    with _client() as c:
        r = c.post("/clients", json=payload)
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Qonto rejected the client payload: {r.status_code}\n{r.text}",
                request=r.request,
                response=r,
            )
        return r.json().get("client", {})


def build_invoice_item(
    *,
    title: str,
    description: str,
    quantity: float,
    unit_price_eur: float,
    vat_rate_pct: float,
    vat_exemption_reason: str | None,
    currency: str = "EUR",
    unit: str = "hour",
) -> dict:
    """Build one line item. Enforces SDI exemption code on 0%-VAT lines."""
    item: dict = {
        "title": title[:250],
        "description": description,
        "quantity": f"{quantity:.2f}",
        "unit": unit,
        "unit_price": {"value": f"{unit_price_eur:.2f}", "currency": currency},
        "vat_rate": f"{vat_rate_pct:.2f}",
    }
    if vat_exemption_reason and vat_rate_pct == 0:
        item["vat_exemption_reason"] = vat_exemption_reason
    return item


def build_invoice_payload(
    *,
    client_id: str,
    issue_date: str,
    due_date: str,
    items: list[dict],
    iban: str,
    bic: str | None = None,
    beneficiary_name: str | None = None,
    currency: str = "EUR",
    purchase_order: str | None = None,
    status: str = "draft",
    payment_reporting: dict | None = None,
) -> dict:
    """Build the POST /v2/client_invoices request body with pre-built items.

    `payment_reporting` is only included in the payload when provided — for
    Italian orgs the caller passes `{"conditions": "TP02", "method": "MP05"}`
    (or similar SDI codes); for non-IT orgs the caller passes `None` and the
    field is omitted entirely. Never set defaults here: the caller knows the
    org country, this builder doesn't.
    """
    transfer: dict = {"type": "transfer", "iban": iban}
    if bic:
        transfer["bic"] = bic
    if beneficiary_name:
        transfer["beneficiary_name"] = beneficiary_name
    payload: dict = {
        "client_id": client_id,
        "issue_date": issue_date,
        "due_date": due_date,
        "currency": currency,
        "status": status,
        "items": items,
        "payment_methods": transfer,
    }
    if payment_reporting:
        payload["payment_reporting"] = payment_reporting
    if purchase_order:
        payload["purchase_order"] = purchase_order
    return payload


def create_client_invoice(payload: dict) -> dict:
    """POST /v2/client_invoices. Returns the created invoice object."""
    with _client() as c:
        r = c.post("/client_invoices", json=payload)
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Qonto rejected the invoice payload: {r.status_code}\n{r.text}",
                request=r.request,
                response=r,
            )
        return r.json().get("client_invoice", r.json())


def get_invoice(invoice_id: str) -> dict:
    with _client() as c:
        r = c.get(f"/client_invoices/{invoice_id}")
        r.raise_for_status()
        return r.json().get("client_invoice", {})


def get_attachment(attachment_id: str) -> dict:
    with _client() as c:
        r = c.get(f"/attachments/{attachment_id}")
        r.raise_for_status()
        return r.json().get("attachment", {})


def download_invoice_pdf(invoice_id: str) -> tuple[str, bytes]:
    """Returns (filename, pdf_bytes). The PDF URL is a pre-signed S3 URL, so
    we fetch it with a clean httpx client (no Qonto auth header)."""
    inv = get_invoice(invoice_id)
    att_id = inv.get("attachment_id")
    if not att_id:
        raise RuntimeError(f"Invoice {invoice_id} has no attachment_id")
    att = get_attachment(att_id)
    url = att.get("url")
    filename = att.get("file_name") or f"invoice-{inv.get('number', invoice_id)}.pdf"
    if not url:
        raise RuntimeError(f"Attachment {att_id} has no download url")
    with httpx.Client(timeout=60) as c:
        r = c.get(url)
        r.raise_for_status()
        return filename, r.content


def finalize_invoice(invoice_id: str) -> dict:
    """POST /v2/client_invoices/{id}/finalize. IRREVERSIBLE.

    Locks the invoice number and queues the document for SDI submission
    (for Italian orgs). Once SDI accepts, voiding requires a credit note.
    """
    with _client() as c:
        r = c.post(f"/client_invoices/{invoice_id}/finalize")
        if r.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"Qonto finalize failed: {r.status_code}\n{r.text}",
                request=r.request,
                response=r,
            )
        return r.json().get("client_invoice", {})
