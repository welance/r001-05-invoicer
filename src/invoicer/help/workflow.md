# Monthly invoicing workflow

Four commands, two manual review steps, one physical click to send.

## The flow

```
1. invoicer draft <project> --month YYYY-MM    → creates a Qonto DRAFT
     ↓
2. open Qonto web UI → Invoicing → Drafts      → eyeball the PDF
     ↓
3. invoicer finalize <invoice_id>              → locks invoice number, SDI submitted
     ↓
4. invoicer mail-draft <invoice_id>            → creates a Gmail draft with PDF + CSV
     ↓
5. open Gmail → Drafts → review → click Send
```

## Step 1: create the draft

```bash
invoicer draft allsafe --month 2026-04 --purchase-order "Attn: Nick"
```

- The project argument is **fuzzy matched** against the `alias` or `name` field in `invoicer.yaml`. `allsafe`, `all-safe`, `r005-01`, and the raw Clockify project ID all resolve to the same project.
- **New project?** If the ID isn't in `invoicer.yaml`, `draft` auto-onboards it via a guided wizard: resolves the Qonto client by name match (or lets you pick from a ranked list), validates the client record is complete for invoicing, synthesizes project settings (rate from Clockify, VAT from country pair), shows a review panel, and writes everything to `invoicer.yaml`. Zero hand-editing — just confirm the defaults.
- `--month` takes `YYYY-MM`.
- `--purchase-order` is optional; prints as a reference on the invoice PDF.

The tool:
1. Fetches time entries from Clockify for the chosen month (using `INVOICER_TIMEZONE`, default `Europe/Rome`)
2. Rounds each entry up to 15-minute boundaries (configurable via `rounding_minutes`)
3. Fetches the mapped Qonto client + main bank account
4. Shows a **rich pre-mutation panel** with every line item, totals, VAT, and reversibility notes
5. Asks `y/N` — type `y` to create the draft

## Step 2: review in Qonto's web UI

Open the `invoice_url` printed after step 1, or go to Qonto → Invoicing → Drafts. Verify:
- Line items render correctly (chronological, one per Clockify entry)
- Client name, VAT number, billing address match
- Bank details are your org's primary account
- VAT rate and exemption code match expectations
- Purchase order line shows up as expected

**If something's wrong**: delete the draft in Qonto's UI and re-run step 1 after fixing config.

## Step 3: finalize (IRREVERSIBLE)

```bash
invoicer finalize <invoice_id>
```

- Shows a **red-bordered** summary panel
- Asks you to **type the exact invoice number** to confirm — not just `y/N`
- For Italian orgs, queues the invoice for SDI submission (Sistema di Interscambio)
- **Once SDI accepts, voiding requires a credit note**

After finalize, the invoice number is locked and the PDF becomes official.

## Step 4: build the Gmail draft

```bash
invoicer mail-draft <invoice_id>
```

- Downloads the finalized PDF from Qonto
- Generates a CSV timesheet from the invoice's line items (one row per Clockify entry)
- Builds a MIME email: From=`$GMAIL_SENDER`, To=client email, CC=`$GMAIL_SENDER` (paper trail)
- Creates a Gmail draft via `drafts.create()` — **never calls send**
- Prints the draft id

## Step 5: send it yourself

Open Gmail web → Drafts → the newest one. Review body, subject, attachments, recipient. Edit if needed. Click Send.

## Skipping steps safely

- `draft` is always reversible — delete from Qonto UI.
- `finalize` is **not** reversible for IT orgs after SDI accepts. Use the typed confirmation to force yourself to check.
- `mail-draft` is always safe — it cannot send. If you mis-address a draft, just delete it from Gmail and re-run.
