"""Human-readable glosses for Italian SDI VAT-exemption codes.

When `invoicer mail-draft` sends an invoice that carries an N-code (N3.1,
N3.2, N6.7, …), the invoice PDF has the code on every line item — which
is legally binding but reads as an opaque three-character token to the
customer's accountant. This module maps (code, client country) pairs to
a short explanatory paragraph in the customer's language, which
`mail-draft` appends to the email body.

New pairs are added here as the team expands into new jurisdictions.
The table is intentionally narrow — only languages we can actually
verify. Unknown pairs fall back to the English version of the code
(key `(code, "EN")`), and if that's missing too, no gloss is appended.
"""

from __future__ import annotations

# Keyed by (SDI N-code, ISO-2 country code). "EN" is the fallback key
# used when the specific country isn't in the table.
GLOSSES: dict[tuple[str, str], str] = {
    # N3.2 — intra-Community reverse charge (art. 41 DL 331/93)
    # Each gloss MUST stay ≤200 chars: SDI's <Causale> field has a
    # 200-char-per-occurrence cap and Qonto maps `footer` to a single
    # Causale element. F-2026-05 was rejected with a 249-char footer.
    ("N3.2", "DE"): (
        "N3.2 — Steuerfreie innergemeinschaftliche Lieferung gemäß "
        "Art. 41 DL 331/93 (italienisches Reverse-Charge-Verfahren). "
        "MwSt. schuldet der Leistungsempfänger."
    ),
    ("N3.2", "IT"): (
        "Nota: il codice \"N3.2\" indica operazioni non imponibili – "
        "cessioni intracomunitarie ai sensi dell'art. 41 DL 331/93. "
        "L'IVA è dovuta nel paese del destinatario (inversione contabile)."
    ),
    ("N3.2", "EN"): (
        "N3.2 — Non-taxable intra-Community supply under art. 41 "
        "DL 331/93 (Italian reverse-charge scheme). VAT to be "
        "accounted for by the recipient in their member state."
    ),
    # N3.1 — export outside the EU (art. 8 DPR 633/72)
    ("N3.1", "EN"): (
        "For reference: the \"N3.1\" code on the invoice indicates a "
        "non-taxable export of services outside the European Union "
        "(art. 8 DPR 633/72). No Italian VAT is charged."
    ),
    # N6.7 — specific reverse-charge scenarios (art. 17 DPR 633/72)
    ("N6.7", "EN"): (
        "For reference: the \"N6.7\" code on the invoice indicates a "
        "reverse-charge transaction under art. 17 DPR 633/72. VAT is "
        "to be self-assessed by the recipient."
    ),
}


def get_gloss(sdi_code: str | None, client_country: str | None) -> str | None:
    """Return the explanatory paragraph for a given (code, country) pair.

    Lookup order:
      1. Exact match on (code, country)
      2. Fallback on (code, "EN")
      3. None if neither is known

    Returns None when the SDI code is empty / missing — no gloss needed
    (the invoice wasn't exempt under an N-code).
    """
    if not sdi_code:
        return None
    code = sdi_code.strip()
    if not code:
        return None
    country = (client_country or "").strip().upper()

    if country:
        exact = GLOSSES.get((code, country))
        if exact:
            return exact

    return GLOSSES.get((code, "EN"))


def extract_sdi_code(invoice: dict) -> str | None:
    """Pull the SDI N-code off a Qonto invoice payload.

    Looks at the invoice's line items and returns the first non-empty
    `vat_exemption_reason`. Returns None if no line item carries one,
    which is the normal case for domestic (VAT-bearing) invoices.
    """
    for item in invoice.get("items") or []:
        code = (item.get("vat_exemption_reason") or "").strip()
        if code:
            return code
    return None


def extract_client_country(invoice: dict) -> str | None:
    """Pull the client country code off a Qonto invoice payload.

    Qonto returns the client embedded under `client` with either a
    top-level `country_code` or nested under `billing_address`. Handle
    both shapes so we work across API versions without guessing.
    """
    client = invoice.get("client") or {}
    direct = (client.get("country_code") or "").strip().upper()
    if direct:
        return direct
    ba = client.get("billing_address") or {}
    nested = (ba.get("country_code") or "").strip().upper()
    return nested or None
