# Italy / SDI e-invoicing

If your Qonto organization is Italian, every finalized invoice is automatically submitted to **Sistema di Interscambio (SDI)** — the Italian tax authority's mandatory e-invoicing channel. This affects what fields you must set and what the safe gates are.

## VAT exemption codes (0% VAT lines)

Italian orgs **must** provide a `vat_exemption_reason` SDI code on any 0%-VAT line. Qonto rejects payloads without it. The common codes for agency work:

| Code | Description | When |
|---|---|---|
| **N2.1** | Operations not subject to VAT per art. 7-ter DPR 633/72 | Services to a foreign EU B2B client (strict reading — the most "correct" code for consulting services) |
| **N3.2** | Non-taxable intra-community supplies per art. 41 DL 331/93 | Common practice for intra-EU, even for services — what Welance's existing invoices use |
| **N6.7** | Other reverse-charge scenarios | Less common; specific reverse-charge cases |

**Which one to use is a tax question, not a technical one. Ask your accountant.** This tool doesn't validate the code — it just passes it through to Qonto.

Configure in `invoicer.yaml`:
```yaml
projects:
  "<clockify_id>":
    vat_rate: 0
    vat_exemption_reason: "N3.2"  # or N2.1, or whatever your accountant says
```

## Payment reporting (TP/MP codes)

SDI requires payment-method metadata on every invoice. The tool hardcodes sensible defaults in `qonto.py`:

- `conditions: "TP02"` = full payment (not installments, not advance)
- `method: "MP05"` = bank transfer

Other TP/MP codes exist for cash, check, wire, etc. Edit `qonto.build_invoice_payload()` if you need different codes.

## Client-side SDI fields

For a Qonto **client** record to be SDI-valid, it needs:

- `vat_number` (P.IVA if IT, or EU VAT number)
- `tax_identification_number` (codice fiscale for Italian individuals/companies)
- `billing_address` with `country_code`
- For Italian clients: either a `recipient_code` (7-char codice destinatario) **or** a PEC email. Foreign clients don't need these.

When you run `invoicer client add`, the tool extracts these fields from pasted text using Haiku, asks you to review, and POSTs the result. If you'd rather not use the LLM, run `invoicer client add --no-ai` and answer the guided field prompts by hand. If you create clients manually in Qonto's UI instead, make sure these fields are set before you run `invoicer draft`.

## Foreign clients (non-IT EU)

Italian orgs still route **cross-border** invoices through SDI (mandatory since July 2022, replacing the esterometro). The recipient_code `XXXXXXX` (seven X's) is used as a placeholder for foreign EU clients — Qonto handles this automatically as long as the client has a valid VAT number.

The client **does not** receive anything through SDI directly. They get the PDF via the `mail-draft` → Gmail flow.

## The SDI status lifecycle

After `invoicer finalize`, Qonto's invoice response includes an `einvoicing_status` field:

- **`pending`** — queued, not yet sent to SDI
- **`accepted`** — SDI has it; invoice is legally valid; only voidable via credit note
- **`rejected`** — SDI refused; usually a schema/data error, fixable by correcting the client or invoice and retrying
- **`failed`** — transport error; Qonto retries

You can check via a direct API call or by opening the invoice in Qonto's web UI.

## If SDI rejects

1. Read the rejection reason in Qonto's UI
2. Identify the bad field (usually client vat_number, codice destinatario, or an invalid N-code)
3. Fix in Qonto's web UI (the client, not the invoice — invoices can't be edited after finalize)
4. Qonto will re-submit automatically, or trigger a retry manually

## Non-Italian Qonto orgs

If your Qonto org is French / Spanish / German, the Italian SDI fields are ignored by the API and the flow is simpler. The tool is **Italy-first** and untested outside Italy — contributions welcome.
