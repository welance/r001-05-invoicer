# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-04-11

### Fixed

- **`invoicer help` now shows the command list**, not just the topic index.
  The initial 0.2.0 implementation copied the `uv help` / `gh help` shape
  (topics only) but most users reach for `invoicer help` expecting a `git help`
  shape (commands first). The welcome panel now shows:

  1. A **Commands** section auto-generated from Typer's registered commands
     (top-level + sub-typer groups like `client add` / `client extract`)
  2. The **Help topics** section (unchanged — 5 long-form markdown topics)

  Commands are introspected from `invoicer.cli.app` via `registered_commands`
  / `registered_groups`, so the list stays in sync as commands are added or
  removed. Regression test `test_list_topics_includes_commands` locks this in.

- **108 unit tests pass** (up from 107 in 0.2.0).

## [0.2.0] - 2026-04-11

### Added

- **`invoicer help` command** — long-form, topic-based help rendered in the terminal with `rich.markdown`. Five initial topics shipped as markdown files inside the `invoicer.help` package:
  - `getting-started` — prerequisites, `invoicer init`, Gmail OAuth setup
  - `workflow` — the monthly 4-command invoicing flow
  - `italy-sdi` — Italian e-invoicing specifics: N-codes, TP/MP codes, SDI lifecycle
  - `troubleshooting` — common errors and how to recover
  - `security` — secrets rotation, gmail.modify scope honesty, branch protection
- `invoicer help` with no argument prints a welcome panel listing all topics.
- `invoicer help <topic>` renders the topic's markdown content with full styling.
- AST-based regression test (`TestGmailModuleSafety`) that fails if `gmail.py` ever
  imports `smtplib` or contains any `.send()` call. Locks in the code-level safety
  property the README and `security` topic both claim.

### Tests

- 107 unit tests pass in ~300ms (up from 95 in 0.1.1)

## [0.1.1] - 2026-04-11

### Fixed

- **Path resolution bug reported by a real user**: config files (`.env`,
  `invoicer.yaml`, `credentials.json`, `token.json`) were resolved against
  `Path(__file__).parents[2]`, which meant that after installing the tool
  with `uv tool install --editable .` from one directory, running `invoicer`
  from a DIFFERENT clone still read and wrote the original directory's files.
  A user who cloned a fresh copy and ran `invoicer init` found their secrets
  landing back in the original developer directory. Fixed by resolving the
  project root from `$INVOICER_DIR` env var (if set) or CWD. Added regression
  tests in `tests/unit/test_config.py`.
- **`invoicer init` triggered an unsolicited Gmail OAuth browser flow** as a
  side-effect of the "connection test". Now checks for `token.json` first and
  only probes Gmail if the user has already completed OAuth via `mail-draft`.
- **Better error messages** when config files are missing, including the exact
  path being searched and a hint to `cd` to the project directory.

## [0.1.0] - 2026-04-11

### Fixed (pre-release audit)

- **`draft` command missing `iban`**: the CLI's `draft` command did not pass `iban` to `build_invoice_payload`, which is a required keyword argument. The command now auto-fetches the org's main bank account from Qonto and passes `iban`, `bic`, and `beneficiary_name`. (Uncovered by pre-release audit; CLI draft command had never actually run end-to-end.)
- **Silent Clockify pagination break**: a non-200 response inside the time-entry pagination loop was silently treated as "no more pages", under-billing on transient 429/5xx. Replaced with `raise_for_status()`.
- **Month-boundary timezone bug**: the billing window was computed in UTC, which excluded entries logged near midnight Europe/Rome on the first/last day of the month. The window now uses `INVOICER_TIMEZONE` (default `Europe/Rome`).
- **`_list_users` and `list_clients` were not paginated**: silently capped at 200 users / 100 clients. Both now paginate.
- **CSV injection**: cells starting with `=+-@\t\r` are now escaped with a leading single-quote to prevent Excel/Google-Sheets formula execution when the timesheet CSV is opened.
- **Hardcoded "VAT is not applied" in email body**: now computed from the invoice's actual `vat_amount`.
- **Fuzzy matcher empty-query crash**: queries like `"!!!"` or `"..."` normalize to `""`, which previously matched every project via substring. Now returns `[]`.
- **`gmail.modify` safety claim retracted**: `README.md`, `SECURITY.md`, and `gmail.py` docstring incorrectly stated the `gmail.modify` scope "physically cannot send". Per Google's docs, it DOES allow sending. The actual safety is at the code level — this module only calls `drafts().create()` and `drafts().update()`. Documentation now states this honestly.


### Added

- Initial release.
- `invoicer init` — interactive first-run setup that prompts for API keys and tests each connection.
- `invoicer discover` — lists Clockify clients/projects and Qonto clients.
- `invoicer client extract` — uses Anthropic Haiku to parse free-form company text into structured fields.
- `invoicer client add` — creates a Qonto client with a pre-mutation review panel.
- `invoicer draft` — builds a Qonto draft invoice with one line per Clockify time entry, per-entry 15-minute ceiling rounding, Italian SDI e-invoicing fields, and a rich pre-mutation preview panel. Supports fuzzy project search (alias, name, or id).
- `invoicer finalize` — finalizes a draft invoice with a typed-confirmation gate (you must re-type the invoice number).
- `invoicer mail-draft` — downloads the finalized PDF from Qonto, generates a CSV timesheet from the invoice line items, and creates a Gmail draft (via Gmail API `gmail.modify` scope) with both attachments. The tool's source only calls `drafts.create()` / `drafts.update()` — never `send()` — so the user is always the one who clicks Send in Gmail's UI. (The OAuth scope itself *does* technically allow sending; the safety is at the code level.)
- MIT license.
- Italy-first Qonto integration: SDI e-invoicing, VAT exemption codes, intra-EU reverse charge, payment reporting (TP02 / MP05).
- Pure functions for rate math, VAT math, rounding, and payload building — zero LLM tokens on the happy path.

[Unreleased]: https://github.com/welance/r001-05-invoicer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/welance/r001-05-invoicer/releases/tag/v0.1.0
