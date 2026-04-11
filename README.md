# r001-05-invoicer

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/welance/r001-05-invoicer/actions/workflows/ci.yml/badge.svg)](https://github.com/welance/r001-05-invoicer/actions/workflows/ci.yml)

A tiny, honest CLI that turns **Clockify** hours into **Qonto** client invoices — with real pre-mutation previews, typed-confirmation gates, and a **Gmail-drafts** step that never sends directly. Built for small digital agencies, initially Italy-first.

Open-sourced by [welance](https://welance.com) under MIT. The `r001-05` prefix is our internal project ID.

---

## 🚀 Get started in 60 seconds

```bash
git clone https://github.com/welance/r001-05-invoicer.git
cd r001-05-invoicer
uv tool install --editable .      # installs `invoicer` on your PATH
invoicer init                     # interactive: prompts for each API key, tests every connection
invoicer discover                 # shows your Clockify + Qonto inventory
```

Then edit `invoicer.yaml` to map one Clockify project to one Qonto client, and you can produce your first draft invoice:

```bash
invoicer draft <project-alias> --month 2026-04 --purchase-order "Attn: Nick"
```

See the full setup guide below if `invoicer init` can't auto-configure something.

---

---

## ⚠️ Important disclaimers — read before using

This tool creates **real invoices** in a **real Qonto account**. For Italian organizations it also queues those invoices for **SDI (Sistema di Interscambio) submission**, which is a legally binding fiscal event.

- **You are fully responsible** for reviewing every draft in Qonto's web UI before running `finalize`.
- **Tax rules are jurisdiction-specific.** The Italian VAT exemption codes in the examples (`N2.1`, `N3.2`, `N6.7`) are examples, not legal advice — **consult your accountant or fiscalist** before using any of them in production.
- **The authors and contributors accept no liability** for incorrect tax filings, missed or duplicate invoices, financial damages, credit notes, or any other consequences of using this software. See `LICENSE`.
- The tool is **Italy-first**. Support for other e-invoicing regimes (France Chorus Pro, Spain Facturae, Germany ZUGFeRD/XRechnung, etc.) is not implemented — contributions welcome.
- **Before first real-world use**, test against a throwaway Qonto client that you're willing to delete.
- **Never skip the pre-mutation previews.** They exist because we got bitten by an accidental finalize during endpoint discovery.

---

## What it does

```
Clockify (hours) → invoicer → Qonto draft invoice → review in Qonto UI
    → invoicer finalize → Qonto PDF → invoicer mail-draft → Gmail Drafts folder → you click Send
```

Concretely:

1. **Pulls billable time entries** from a Clockify project for a chosen month
2. **Rounds per-entry to 15 minutes** (configurable) and aggregates
3. **Builds a Qonto draft invoice** with one line per time entry (chronological, with date + user), full reverse-charge / e-invoicing metadata, and the right bank details auto-fetched from your Qonto org
4. **Shows a pre-mutation summary** (rich terminal panel) before every write — client, lines, totals, VAT code, status, irreversibility notes
5. **Requires typed confirmation** (re-type the invoice number) before `finalize`
6. **Downloads the finalized PDF** and generates a CSV timesheet from the invoice line items
7. **Creates a Gmail draft** via OAuth2, with the PDF + CSV attached, subject + body pre-filled
8. **Does NOT send.** This tool's code only calls `drafts.create()` / `drafts.update()` — never `messages.send()` or `drafts.send()`. You review and click Send in Gmail's web UI yourself. (Note: the `gmail.modify` OAuth scope technically *does* permit sending; the safety comes from the source code, not the scope. Audit `src/invoicer/gmail.py` to verify.)

## Commands

```
invoicer init                                  # Interactive first-run setup
invoicer help [topic]                          # Long-form help: getting-started, workflow, italy-sdi, troubleshooting, security
invoicer update                                # git pull + reinstall (for editable installs from a clone)
invoicer discover                              # List Clockify + Qonto inventories
invoicer client add                            # Paste company text → Haiku extracts → review → POST /v2/clients to Qonto
invoicer client add --no-ai                    # Same, but answer stepped field prompts manually (no LLM, no Anthropic key)
invoicer draft <project> --month YYYY-MM       # Build a Qonto draft invoice (project: alias, name, or id — fuzzy matched)
invoicer finalize <invoice_id>                 # Finalize a draft. IRREVERSIBLE. Typed confirmation.
invoicer mail-draft <invoice_id>               # Download PDF + CSV, create Gmail draft
```

## Requirements

- **Python 3.11+**
- **A Clockify API key** (from your profile settings)
- **A Qonto Business API login + secret key** (Qonto settings → Integrations → API)
- **A Google Cloud OAuth client** for Gmail API (one-time setup, ~15 minutes — see below)
- **Optional**: An Anthropic API key for the LLM-assisted client-extraction step (`claude-haiku-4-5`)

## Install

```bash
# Clone the repo
git clone https://github.com/welance/r001-05-invoicer.git
cd invoicer

# Install in a venv (recommended with uv)
uv venv
uv pip install -e .

# Or install globally as a tool on your PATH
uv tool install --editable .
```

## Configure

### 1. Environment variables

```bash
cp .env.example .env
# edit .env and fill in your keys
```

Required variables:

| Variable | Where to get it |
|---|---|
| `CLOCKIFY_API_KEY` | Clockify → profile → API |
| `CLOCKIFY_WORKSPACE_ID` | Clockify → workspace settings, or use `invoicer discover` |
| `QONTO_LOGIN` | Your Qonto organization slug (e.g. `acme-5678`) |
| `QONTO_SECRET_KEY` | Qonto → Settings → Integrations → API |
| `GMAIL_SENDER` | The Gmail address that will own the drafts (e.g. `you@yourdomain.com`) |
| `GMAIL_SENDER_NAME` | Optional. Display name used in the email signature. |
| `ANTHROPIC_API_KEY` | Optional. Only needed for `invoicer client add` in its default (AI) mode. Not required with `--no-ai`. |

### 2. Gmail API OAuth (one-time, ~15 minutes)

The tool uses the Gmail API with OAuth2 to create drafts — not app passwords, and not SMTP. This means no Workspace admin toggles to fight with, and no way for the tool to send email on its own.

1. **Create a Google Cloud project**: https://console.cloud.google.com/projectcreate
2. **Enable the Gmail API**: https://console.cloud.google.com/apis/library/gmail.googleapis.com → Enable
3. **Configure the OAuth consent screen**: https://console.cloud.google.com/apis/credentials/consent
   - User Type: **Internal** if you're on Google Workspace (skips Google's verification process)
   - App name: `invoicer` (or anything)
4. **Create OAuth credentials**: https://console.cloud.google.com/apis/credentials → Create Credentials → OAuth client ID → **Desktop app** → Download JSON
5. **Save the downloaded file as `credentials.json`** in the repo root (gitignored)
6. **First run** (`invoicer mail-draft ...`) opens a browser for consent. A `token.json` is cached and all subsequent runs are silent.

The tool requests the `https://www.googleapis.com/auth/gmail.modify` scope. **Be aware**: per Google's documentation, this scope technically *does* allow `messages.send` and `drafts.send`. The safety here comes from this tool's **source code** — `src/invoicer/gmail.py` only calls `drafts().create()` and `drafts().update()`, nothing else. Audit the file before trusting the tool with a real mailbox.

### 3. Billing config

```bash
cp invoicer.example.yaml invoicer.yaml
# edit invoicer.yaml — map Clockify clients to Qonto clients, set project rates and VAT rules
```

Then run `invoicer discover` to see the Clockify and Qonto ids you need.

## Typical monthly workflow

```bash
# 1. Create the draft (shows preview table + panel + y/N)
invoicer draft allsafe --month 2026-04 --purchase-order "Attn: Contact Name"

# 2. Open Qonto web → Invoicing → Drafts → eyeball the PDF
#    If something's wrong, delete the draft in Qonto UI and re-run step 1

# 3. Finalize (typed confirmation: re-type the invoice number)
invoicer finalize <invoice_id>

# 4. Build the Gmail draft with PDF + CSV attached
invoicer mail-draft <invoice_id>

# 5. Open Gmail → Drafts → review → click Send
```

Four commands, two reviews (Qonto UI + Gmail UI), one physical click to send.

## Design choices / Safety model

- **Every write command shows a rich terminal panel** with exactly what's going to change, where, and whether it's reversible, before asking for confirmation.
- **`finalize` requires typed confirmation** of the invoice number — not just `y/N`. The invoice number is different for every invoice, so accidental confirmation is impossible.
- **`mail-draft` never calls `smtplib.sendmail`, `messages.send`, or `drafts.send`.** The `gmail.modify` scope *does* technically allow these per Google's docs — the safety property is enforced at the code level, not the scope level. Audit `src/invoicer/gmail.py` to verify (the only Gmail API calls are `drafts().create()` and `drafts().update()`).
- **Qonto is the single source of truth for client data** — the tool never caches client info locally. Every run fetches fresh data from Qonto.
- **Rate math, VAT math, and payload building are pure functions** with no side effects. LLM is only invoked when the user opts in (`client add` in its default AI mode). `client add --no-ai` and the whole monthly invoicing run use **zero LLM tokens**.
- **Nothing that looks reversible is actually reversible past `finalize`.** Once Qonto finalizes an invoice, the number is locked and for Italian orgs the document is queued for SDI. Voiding requires a credit note.

## Italy / SDI specifics

- The tool sets `payment_reporting` with `conditions: TP02` (full payment) and `method: MP05` (bank transfer) by default, which match most consulting invoices paid by wire transfer. Change in `qonto.py` if you need different SDI codes.
- For 0% VAT lines, you MUST provide a `vat_exemption_reason` in `invoicer.yaml`. Qonto's API rejects IT-org invoices with 0% lines missing the exemption code.
- Common codes for consulting to foreign EU B2B clients:
  - **`N2.1`** — non-taxable services per art. 7-ter DPR 633/72 (most "correct" code for services)
  - **`N3.2`** — non-taxable intra-community supplies per art. 41 DL 331/93 (commonly used in practice)
  - Ask your accountant which one matches your setup.
- Cross-border Italian e-invoicing (to non-Italian clients) still flows through SDI using `recipient_code: "XXXXXXX"` (seven X's) — Qonto handles this automatically as long as the Qonto client has a valid VAT number.
- For non-Italian Qonto organizations, the SDI codes and payment reporting fields are ignored by the API — the tool should still work, but is untested outside Italy.

## Contributing

See `CONTRIBUTING.md`.

## Acknowledgements

Built end-to-end in one afternoon with [Claude Code](https://claude.com/claude-code) as the pair-programmer, driving design discussion and implementation. The schema-discovery subagent saved hours of API docs diving.

## License

MIT. See `LICENSE`.
