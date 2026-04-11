# Multi-org setups

`invoicer` supports invoicing from more than one legal entity — e.g. an
Italian SRL and a German GmbH sharing the same Clockify workspace — through
an `orgs:` block in `invoicer.yaml` plus one pair of Qonto credentials per
entity in `.env`.

## Why multi-org at all

Qonto's API is **per-organization**. Each legal entity has its own API
credentials (Settings → Integrations → API, inside that org's web UI) — your
web-UI user account may span multiple orgs, but each one hands out its own
login slug and secret key. To invoice from both, the tool must know which
credentials to use for a given draft.

## `invoicer.yaml` shape

```yaml
orgs:
  - id: welance-srl
    country: IT                         # drives SDI payment_reporting inclusion
    login_env: QONTO_LOGIN_SRL
    secret_env: QONTO_SECRET_KEY_SRL
  - id: welance-gmbh
    country: DE
    login_env: QONTO_LOGIN_GMBH
    secret_env: QONTO_SECRET_KEY_GMBH

defaults:
  org: welance-srl          # default when --org isn't passed and no project-level override
  locale: en

clients:
  - clockify_id: "..."
    qonto_id: "..."
    org: welance-srl        # optional: scopes this mapping to one Qonto org

projects:
  "clockify_project_id":
    alias: my-proj
    rate_eur_per_hour: 120
    vat_rate: 19
    org: welance-gmbh       # optional: pins this project to an org (skips the org prompt)
```

## How commands pick an org

`draft`, `client add`, `mail-draft`, `finalize`, and `discover` all accept
`--org <id>`. The priority chain is:

1. `--org` CLI flag
2. Project-level `org:` in `invoicer.yaml` (draft only)
3. `defaults.org` in `invoicer.yaml`
4. Single-org list → silently picked
5. `questionary.select` prompt listing all known orgs

After prompting (step 5), the tool asks *"Save 'welance-gmbh' as the default
org for future runs? (y/N)"* so you only pay the prompt tax once. See
`invoicer defaults set` / `invoicer defaults` to inspect and edit what's
cached.

## `.env` layout

```bash
# One credentials pair per legal entity.
QONTO_LOGIN_SRL=welance-srl-1234
QONTO_SECRET_KEY_SRL=srl_api_secret_here
QONTO_LOGIN_GMBH=welance-gmbh-5678
QONTO_SECRET_KEY_GMBH=gmbh_api_secret_here

CLOCKIFY_API_KEY=...
CLOCKIFY_WORKSPACE_ID=...
GMAIL_SENDER=invoices@welance.com
```

Note the convention: `QONTO_LOGIN_<SUFFIX>` where `<SUFFIX>` is the org id
upper-cased with non-alphanumerics replaced by `_`. `welance-srl` →
`WELANCE_SRL`. `invoicer init` generates this for you — you don't have to
name them by hand.

## SDI vs. not

For any org with `country: IT`, the `draft` command attaches
`payment_reporting: {conditions: TP02, method: MP05}` — the Italian SDI
"full payment, bank transfer" codes — because Italian e-invoicing requires
it. For any other country (DE, FR, etc.), the field is omitted entirely.
Neither behavior is hardcoded to the caller: the `qonto.build_invoice_payload`
builder takes `payment_reporting` as an explicit parameter and `cli.draft`
reads the active org's `country` to decide what to pass.

If you change an org's `country` after creating it, re-run `invoicer draft`
against a dry run (decline the final confirmation) to see that the new
behavior kicks in.

## Gmail across orgs — short version

Gmail is **user-based OAuth**, not per-org. The account that went through
the installed-app OAuth flow on first run owns `token.json`, and Gmail drafts
always land in *that* mailbox regardless of `GMAIL_SENDER`. In practice the
cleanest setup is one shared mailbox (e.g. `invoices@welance.com`) that both
legal entities' invoices go through — one OAuth token, one audit trail.
`GMAIL_SENDER` is only used to set the `From:` header; if it doesn't match
the authenticated account, Google Workspace's "Send as" settings decide what
happens (usually: rewrites the header back, sometimes: fails at send time).

## Listing clients across orgs

`invoicer discover` walks both Clockify (workspace-wide, unchanged) and one
Qonto org at a time. To see the client list from each of your Qonto accounts,
run it twice:

```bash
invoicer discover --org welance-srl
invoicer discover --org welance-gmbh
```

Or run it without `--org` and get prompted.

## Single-org, no `orgs:` block

If you only have one entity, you can omit the `orgs:` block entirely and
keep the pre-0.4.0 setup: just `QONTO_LOGIN` and `QONTO_SECRET_KEY` in
`.env`. The tool skips all org-resolution logic in that case. This is a
pure backward-compat path — `invoicer init` no longer generates this shape,
but existing `.env` files keep working untouched.
