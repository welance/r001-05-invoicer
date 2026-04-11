"""LLM-assisted helpers. Only called on explicit user opt-in.

Each function is one-shot, small context, Haiku — kept cheap on purpose.
Field names mirror Qonto's POST /v2/clients payload to avoid a translation layer.
"""

import os

from anthropic import Anthropic

MODEL = "claude-haiku-4-5-20251001"

CLIENT_EXTRACTION_TOOL = {
    "name": "record_client",
    "description": (
        "Record structured company client data extracted from free-form text "
        "(prior invoice, email footer, company profile). Field names match "
        "Qonto's POST /v2/clients payload."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Legal/business name including suffix (S.r.l., GmbH, S.p.A., etc.). Maps to Qonto `name`.",
            },
            "country_code": {
                "type": "string",
                "description": "ISO 3166-1 alpha-2 country code of the company's legal seat (IT, DE, FR, etc.).",
            },
            "vat_number": {
                "type": "string",
                "description": "VAT ID with country prefix if shown (IT12345678901, DE123456789). Empty if not found.",
            },
            "tax_identification_number": {
                "type": "string",
                "description": "Codice Fiscale (Italy) / Steuernummer (DE) / NIF (ES) / SIREN (FR). Often same as VAT for IT companies. Empty if not found.",
            },
            "street_address": {
                "type": "string",
                "description": "Full street line including number (e.g. 'Via Roma 10').",
            },
            "city": {"type": "string"},
            "zip_code": {
                "type": "string",
                "description": "Postal code. For Italy must be exactly 5 digits.",
            },
            "province_code": {
                "type": "string",
                "description": "Italian 2-letter province code (MI, RM, TO, etc.). Empty for non-Italian clients.",
            },
            "email": {"type": "string", "description": "General contact email. Empty if not found."},
            "pec_email": {
                "type": "string",
                "description": "Italian PEC (certified) email. Empty if not found or non-Italian client.",
            },
            "recipient_code": {
                "type": "string",
                "description": "Italian SDI codice destinatario, exactly 7 chars (letters+digits). Empty if not found or non-Italian client.",
            },
            "confidence_notes": {
                "type": "string",
                "description": "Brief note on anything uncertain or missing the user should double-check.",
            },
        },
        "required": ["name", "country_code"],
    },
}


def extract_client_fields(text: str) -> dict:
    """Extract structured company fields from free-form text. One Haiku call."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        tools=[CLIENT_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_client"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the company/client details from the text below. "
                    "Leave a field as an empty string if not found. "
                    "For Italian companies pay special attention to codice destinatario (recipient_code, 7 chars) "
                    "and PEC email. For German/EU companies, the recipient_code and province_code should stay empty.\n\n"
                    f"---\n{text}\n---"
                ),
            }
        ],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_client":
            return block.input
    raise RuntimeError("LLM did not return a tool_use block")


def extract_defaults(
    text: str,
    *,
    known_org_ids: list[str],
    locale_choices: list[str],
) -> dict:
    """Map a free-form description of desired defaults to the structured shape.

    The tool schema is built fresh from the caller's known org IDs so Haiku
    cannot hallucinate an org that isn't in invoicer.yaml. One Haiku call.
    """
    schema = {
        "type": "object",
        "properties": {
            "org": {
                "type": "string",
                "description": "Default Qonto org id. Empty string if the user didn't mention one.",
                "enum": [*known_org_ids, ""],
            },
            "locale": {
                "type": "string",
                "description": "Default Qonto client locale. Empty string if not mentioned.",
                "enum": [*locale_choices, ""],
            },
            "gmail_sender": {
                "type": "string",
                "description": "Default Gmail sender address. Empty string if not mentioned.",
            },
        },
    }
    tool = {
        "name": "record_defaults",
        "description": (
            "Record the invoicer defaults described in the user's text. "
            "Leave any field the user did not mention as an empty string."
        ),
        "input_schema": schema,
    }
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model=MODEL,
        max_tokens=512,
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_defaults"},
        messages=[
            {
                "role": "user",
                "content": (
                    "Map the user's description to invoicer default keys. "
                    "Only pick an `org` value from the provided enum. "
                    f"Known orgs: {known_org_ids}. "
                    f"Valid locales: {locale_choices}. "
                    "If the user mentions 'GmbH' or 'German entity', pick the org id "
                    "whose name suggests Germany. If they say 'SRL' or 'Italian entity', "
                    "pick the Italian one. Leave fields empty when the user is silent.\n\n"
                    f'---\n"{text}"\n---'
                ),
            }
        ],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "record_defaults":
            return block.input
    raise RuntimeError("LLM did not return a tool_use block")
