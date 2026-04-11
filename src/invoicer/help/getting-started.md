# Getting started

The tool turns Clockify hours into Qonto draft invoices, then helps you send them via a Gmail draft you review before clicking Send.

## Prerequisites

- **Python 3.11+**
- **Clockify API key** — profile → API in Clockify
- **Qonto Business API** credentials — login slug + secret key from Qonto → Settings → Integrations → API
- **Gmail account** that will own the drafts (OAuth2, see below)
- **Anthropic API key** (optional, only for LLM-assisted client extraction)

## One-command setup

```bash
invoicer init
```

This walks you through every environment variable interactively, writes your `.env`, copies `invoicer.example.yaml` to `invoicer.yaml`, and tests every connection. Run it from the **root of your clone** (not from anywhere else — config is resolved against the current working directory).

## Gmail: the one service that needs more than env vars

Gmail uses OAuth2, not API keys. You need a `credentials.json` file in the repo root. Get it via:

1. https://console.cloud.google.com/projectcreate → create a project
2. https://console.cloud.google.com/apis/library/gmail.googleapis.com → Enable Gmail API
3. https://console.cloud.google.com/apis/credentials/consent → set user type to **Internal** (works instantly for Workspace accounts, skips Google's verification)
4. https://console.cloud.google.com/apis/credentials → Create Credentials → OAuth client ID → **Desktop app** → Download JSON
5. Save the downloaded file as `credentials.json` in your project root

The first time you run `invoicer mail-draft`, a browser opens for consent. A `token.json` is cached for all future runs.

## Editing invoicer.yaml

After `invoicer init`, open `invoicer.yaml` and add:

- A `clients:` entry mapping your Clockify client id to your Qonto client id
- A `projects:` entry keyed by Clockify project id, with a short `alias`, hourly rate, VAT rate, and (if Italy) SDI exemption code

Get IDs by running `invoicer discover` — it lists your Clockify and Qonto inventories.

## Next steps

- `invoicer help workflow` — the monthly 4-command invoicing flow
- `invoicer help italy-sdi` — Italian e-invoicing specifics
- `invoicer help troubleshooting` — common errors and recovery
