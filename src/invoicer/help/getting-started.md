# Getting started

The tool turns Clockify hours into Qonto draft invoices, then helps you send them via a Gmail draft you review before clicking Send.

## Quick start — the command that does everything

**TL;DR**: run **`invoicer init`** from the root of your clone. It's an interactive wizard that walks you through six numbered steps, detects what's already configured, and never writes anything without asking.

```bash
cd r001-05-invoicer          # or wherever you cloned it
invoicer init                # the wizard
```

**What the wizard asks you for, in order:**

| Step | What | Why |
|---|---|---|
| 1 | Verifies `uv` / `git` / `op` are on your PATH | Quick sanity check — non-blocking, just shows install hints for missing tools |
| 2 | Your Qonto API credentials (per legal entity) | One `QONTO_LOGIN_<NAME>` + `QONTO_SECRET_KEY_<NAME>` pair per SRL / GmbH / etc. |
| 3 | Clockify API key + workspace id | To pull billable time entries for the invoices |
| 4a | Gmail sender email address (and optional display name) | The `From:` header on drafts |
| 4b | Gmail OAuth — three-way picker | *Fetch from 1Password* (30 sec if you have 1P) · *Manual Google Cloud Console walk* (~15 min) · *Skip for now* |
| 5 | Anthropic API key (optional) | Only needed for `invoicer client add` default mode and `invoicer defaults set --ai` |
| 6 | Tests every connection | One Qonto ping per org, Clockify workspace check, Anthropic ping, Gmail token validation |

**Re-running is safe and idempotent.** If you already have some things configured, each section asks **Keep / Edit / Add** rather than re-prompting everything. Pass `--force` to walk through every step from scratch.

**If the wizard is missing anything**, it'll tell you — and it'll tell you *which command to run next*. At the very end, a "Next steps" block lists only the actions that are actually new based on what changed in this run (not a boilerplate chore list).

## Prerequisites

- **Python 3.11+**
- **Clockify API key** — profile → API in Clockify
- **Qonto Business API** credentials — login slug + secret key from Qonto → Settings → Integrations → API. One pair per legal entity (SRL + GmbH, for example).
- **Gmail account** that will own the drafts (OAuth2)
- **1Password CLI** (optional but strongly recommended) — lets `invoicer init` fetch `credentials.json` from a shared vault so you don't have to walk the Google Cloud Console setup by hand. Works for any 1Password plan: Personal, Teams, or Business.
- **Anthropic API key** (optional, only for LLM-assisted client extraction — skip if you plan to use `invoicer client add --no-ai` and `invoicer defaults set` without `--ai`)

## Running `invoicer init` is the "one command to do everything"

```bash
invoicer init
```

Run it from the **root of your clone** (not from anywhere else — config is resolved against the current working directory). It walks you through every environment variable interactively, writes your `.env`, seeds an `invoicer.yaml` from the example, tests every connection, and — if your `invoicer.yaml` has a `secrets:` block OR you pick the 1Password option in the Gmail step — fetches the Gmail OAuth client file from 1Password for you. No manual Google Cloud Console trip required unless you explicitly pick that path.

**Idempotent by design**: re-running on an already-configured project detects what's already set and asks per-section "**K**eep / **E**dit / **A**dd another?". It never forces you to hit Enter through 15 pre-filled prompts just to add one new org. Pass `--force` to bypass detection and walk through every section.

## Gmail — the 1Password path (recommended for teams)

If your project config (`invoicer.yaml`) has a `secrets:` block pointing at a 1Password vault, the tool fetches `credentials.json` for you automatically. This works for **any 1Password user** — personal, Teams, or Business. The welance team uses it (vault `"p007-01 Welance"`, item `invoicer-credentials-json`), but the pattern is fully generic: pick your own vault, upload your `credentials.json` once, and everyone on the vault can clone-and-run without touching Google Cloud Console.

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
   This should return your 1Password account email. If it doesn't, sign into 1Password in the desktop app and retry.

### Setting up the shared 1Password item (one-time per team)

Admin or first team member does this once:

1. Create a Google Cloud OAuth client (Desktop app type) — see the [manual fallback section below](#gmail--the-manual-path-without-1password) for the four steps. Download `credentials.json`.
2. In the 1Password web UI, go to a **shared vault** that every colleague is (or will be) a member of.
3. Click **New Item → Document**. Upload `credentials.json`. Name the item `invoicer-credentials-json` (or anything — this is the convention). Save.
4. Paste the YAML block below into your team's `invoicer.yaml`, replacing the vault name with yours:

   ```yaml
   secrets:
     credentials_json:
       source: 1password
       vault: "Your Vault Name"          # exact match, case-sensitive
       item: invoicer-credentials-json
       file: credentials.json
   ```

Every colleague runs `invoicer init`, the tool reads that block, runs `op read "op://Your Vault Name/invoicer-credentials-json/credentials.json"`, writes the file next to `.env`, and walks them through the OAuth consent flow in their own browser.

### What's shared vs. what's yours alone

- **Shared** (via 1Password): `credentials.json` — the OAuth **client identifier**. Google's docs say the `client_secret` inside isn't actually a cryptographic secret for Desktop apps; it's just the well-known identifier of your registered OAuth client. One per Google Cloud project, safe to share across a team, rotation done in one place.
- **Yours alone** (never synced): `token.json` — your personal access + refresh tokens, tied to **your** Google account. Written locally by the OAuth flow on your machine. Stays on your machine. Drafts created by the tool land in the Gmail mailbox that authenticated that token — so even though your entire team shares one `credentials.json`, philipp@welance.com's drafts go to philipp's Drafts folder and enricoz@welance.com's go to enricoz's. If your 1Password access is revoked, your existing local `token.json` keeps working until *you* revoke it.

### Rotating credentials (admin flow)

When the OAuth client needs rotating (security review, compromise, or just good hygiene):

1. Admin generates a new `credentials.json` in Google Cloud Console (can keep the old client alive temporarily if needed).
2. Admin replaces the file in the 1Password Document item. One upload, done.
3. Every colleague runs:
   ```bash
   invoicer secrets fetch --force
   ```
   to pull the new `credentials.json`. Takes 2 seconds each.
4. Existing `token.json` files on every machine will fail on next refresh and automatically trigger re-auth via `invoicer mail-draft`'s OAuth flow.

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
