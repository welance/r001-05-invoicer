# Getting started

The tool turns Clockify hours into Qonto draft invoices, then helps you send them via a Gmail draft you review before clicking Send.

## Prerequisites

- **Python 3.11+**
- **Clockify API key** — profile → API in Clockify
- **Qonto Business API** credentials — login slug + secret key from Qonto → Settings → Integrations → API. One pair per legal entity (SRL + GmbH, for example).
- **Gmail account** that will own the drafts (OAuth2)
- **1Password CLI** (welance team only) — to fetch the shared `credentials.json`
- **Anthropic API key** (optional, only for LLM-assisted client extraction — skip this if you plan to use `invoicer client add --no-ai` and `invoicer defaults set` without `--ai`)

## One-command setup

```bash
invoicer init
```

This walks you through every environment variable interactively, writes your `.env`, seeds an `invoicer.yaml` from the example, tests every connection, and — if your `invoicer.yaml` has a `secrets:` block — fetches the Gmail OAuth client file from 1Password for you. Run it from the **root of your clone** (not from anywhere else — config is resolved against the current working directory).

`init` is **idempotent**: re-running it on an already-configured project detects what's already set and asks per-section "**K**eep / **E**dit / **A**dd another?" for each. It never forces you to hit Enter through 15 pre-filled prompts just to add one new org. Pass `--force` to bypass detection and walk through every section.

## Gmail — the welance path (1Password)

If your project config (`invoicer.yaml`) has a `secrets:` block pointing at a 1Password vault, the tool fetches `credentials.json` for you automatically. This is how the welance team works — one file in 1Password, shared across everyone.

**Prerequisites** (one-time, per machine):

1. **Install 1Password CLI**:
   - macOS: `brew install 1password-cli`
   - Windows: https://app-updates.agilebits.com/product_history/CLI2
   - Linux: https://developer.1password.com/docs/cli/get-started/

2. **Enable the desktop-app integration**: open the 1Password desktop app → Settings → Developer → check **"Integrate with 1Password CLI"**. This makes every `op` command biometric-prompt (Touch ID / Face ID / Windows Hello) instead of asking for a password.

3. **Verify you can fetch**:
   ```bash
   op whoami
   ```
   This should return your welance email address. If it doesn't, sign into 1Password in the desktop app and retry.

Once those three are done, `invoicer init` handles the rest: it reads the `secrets.credentials_json` block from `invoicer.yaml`, runs `op read "op://<vault>/<item>/credentials.json"`, writes the file next to `.env`, and walks you through the OAuth consent flow in your browser. Your personal `token.json` lives only on your machine — it's the per-user half of the OAuth pair.

**The welance team's specific config** (already committed to `invoicer.example.yaml`, commented; uncomment and paste into your `invoicer.yaml`):

```yaml
secrets:
  credentials_json:
    source: 1password
    vault: "p007-01 Welance"
    item: invoicer-credentials-json
    file: credentials.json
```

**What's shared vs. what's yours alone**:

- **Shared** (via 1Password): `credentials.json` — the OAuth *client identifier*. Google's docs say the `client_secret` inside isn't actually a cryptographic secret for Desktop apps; it's just the well-known identifier of your registered OAuth client. One per Google Cloud project, good for everyone.
- **Yours alone** (never synced): `token.json` — your personal access + refresh tokens, tied to *your* Google account. Written locally by the OAuth flow. Stays on your machine. If it leaks, you rotate your personal Google credentials. If 1Password access is revoked, your existing `token.json` keeps working until *you* revoke it.

**Rotating credentials** (admin flow): the admin updates the Document item in 1Password, then every colleague runs:

```bash
invoicer secrets fetch --force
```

to pull the new `credentials.json`. Takes 2 seconds each.

## Gmail — the manual path (without 1Password)

If you're forking this tool outside welance, or the 1Password path isn't available, the tool falls back to the original 4-step Google Cloud Console flow. Leave the `secrets:` block out of your `invoicer.yaml`; `invoicer init` will detect its absence and walk you through creating your own OAuth client:

1. Create a Google Cloud project: https://console.cloud.google.com/projectcreate
2. Enable the Gmail API: https://console.cloud.google.com/apis/library/gmail.googleapis.com
3. Configure the OAuth consent screen: user type **Internal** if you're on Google Workspace (skips Google's verification).
4. Create OAuth credentials: **Desktop app** type → download JSON → save as `credentials.json` in your project root.

The first time you run `invoicer mail-draft`, a browser opens for consent. A `token.json` is cached for all future runs.

## Shell autocomplete (optional but nice)

Tab-completion for `invoicer` commands, options, and subcommand names comes for free via Typer. Run it once per shell:

```bash
invoicer --install-completion
```

This detects your shell (bash, zsh, fish, or PowerShell) and writes the completion script to the right place. Open a new terminal, type `invoicer ` and press Tab — you'll see `init`, `draft`, `defaults`, `client add`, etc. listed as you type.

## Editing invoicer.yaml

After `invoicer init`, open `invoicer.yaml` and add:

- A `clients:` entry mapping your Clockify client id to your Qonto client id
- A `projects:` entry keyed by Clockify project id, with a short `alias`, hourly rate, VAT rate, and (if Italy) SDI exemption code

Get IDs by running `invoicer discover` — it lists your Clockify and Qonto inventories.

## Next steps

- `invoicer help workflow` — the monthly 4-command invoicing flow
- `invoicer help multi-org` — invoicing from multiple legal entities (SRL + GmbH)
- `invoicer help italy-sdi` — Italian e-invoicing specifics
- `invoicer help troubleshooting` — common errors and recovery
