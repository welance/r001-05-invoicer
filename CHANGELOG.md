# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.5.0] - 2026-04-12

### Added

- **`invoicer draft` auto-onboards new projects.** Running `draft` with a
  raw Clockify project id that isn't in `invoicer.yaml` now launches a
  guided wizard instead of a dead-end error. The wizard:
  1. **Resolves the Qonto client** — exact-name match with a confirm gate,
     or a ranked similarity picker when names don't align (C1 flow).
  2. **Validates client completeness** — checks required fields for the
     org's country (VAT, address, IT-specific SDI fields like
     `recipient_code`/`pec_email`). Gaps are prompted field-by-field and
     PATCHed directly to Qonto.
  3. **Synthesizes project settings** — defaults rate from Clockify's
     `hourlyRate`, VAT from the org↔client country pair, alias from the
     project name prefix. A single review panel lets you accept-all or
     edit any field before writing.
  All three steps write to `invoicer.yaml` (via the existing text-surgery
  helpers) and continue straight into the normal draft flow — one command,
  zero hand-editing.

- **`qonto.update_client`** — PATCH `/v2/clients/{id}` for filling missing
  fields on existing Qonto clients without leaving the CLI.

- **`project_config.append_client_mapping` / `append_project_entry`** — new
  block-surgery helpers for programmatically appending `clients:` and
  `projects:` entries to `invoicer.yaml`. Idempotent, comment-preserving.

- **VAT defaults table** — `draft_setup.vat_defaults_for_country_pair`
  encodes the common Italian / German country-pair rules (IT→IT: 22%,
  IT→EU: 0% N3.2, IT→non-EU: 0% N3.1, DE→DE: 19%, DE→other: 0%).
  Used as defaults in the project wizard; always overridable.

- **65 new unit tests** (258 total). Covers block writers, VAT defaults,
  alias derivation, client completeness checking, and project synthesis.

## [0.4.6] - 2026-04-11

### Changed

- **`invoicer init` now actually feels like a wizard.** Previous
  releases made init idempotent and added the 1Password proposal,
  but running it cold still left users without a map of the journey:
  no welcome, no step count, no explanation of what command started
  everything. This release fixes that — init now opens with a rich
  welcome panel listing every step, each section gets a numbered
  header (`Step 2/6: Qonto`, `Step 3/6: Clockify`, ...), and the
  very first step is a non-blocking pre-flight check that verifies
  `uv`, `git`, and `op` are on PATH with install URLs for anything
  missing.

  The welcome panel, in full:

  ```
  ┌──────────────────────────────────────────────────────────────┐
  │                                                              │
  │  invoicer setup wizard  ·  6 steps                           │
  │                                                              │
  │  This wizard will walk you through:                          │
  │                                                              │
  │    1. Verify prerequisites (uv, git, optionally 1Password CLI)
  │    2. Qonto API credentials (per legal entity)               │
  │    3. Clockify API key + workspace                           │
  │    4. Gmail sender + OAuth (via 1Password if available)      │
  │    5. Anthropic API key (optional, for AI-assisted client add)
  │    6. Test every connection                                  │
  │                                                              │
  │  Ctrl-C at any prompt to abort — nothing is written until    │
  │  you confirm.                                                │
  │                                                              │
  │  Re-running this command is safe: it detects what's already  │
  │  configured and asks per-section whether to keep, edit, or   │
  │  add.                                                        │
  │                                                              │
  └──────────────────────────────────────────────────────────────┘
  ```

- **`invoicer help` welcome panel now shows a "New here?" banner
  when it detects the current directory has no `.env` and no
  `invoicer.yaml`.** Prominently points at `invoicer init` as the
  single command to start everything:

  ```
  📦 New here?  Run invoicer init to set everything up in one
                guided wizard.
  No `.env` or `invoicer.yaml` detected in this directory — this
  looks like a first-run.
  ```

  The banner is additive — it only appears on first-run and doesn't
  clutter the panel once you're set up.

- **`getting-started` help topic gets a Quick Start table** at the
  very top listing every step the wizard will walk you through, so
  you know what to expect before running the command. Prerequisites
  section generalized: 1Password CLI is now listed as "optional but
  strongly recommended" for any 1Password user, not just welance.

### Added

- **`init_cmd._WIZARD_STEPS`** — the canonical list of wizard step
  descriptions, used by both the welcome panel and the CHANGELOG
  so everything stays in sync if a step is added later.
- **`init_cmd._print_welcome_panel()`** — renders the welcome panel
  via `rich.Panel`.
- **`init_cmd._check_prerequisites()`** — non-blocking pre-flight
  check via `shutil.which` for `uv`, `git`, and `op`. Prints
  platform-specific install URLs for any missing tool but doesn't
  stop the wizard. Called as Step 1 of 6.
- **`help_cmd._is_first_run()`** — heuristic detection of
  first-run state (no `.env` and no `invoicer.yaml` in the project
  root). Feeds the welcome-panel banner. Graceful: returns False on
  any unexpected exception so a weird environment can't break the
  help output.

### Tests

- **+10 new unit tests**:
  - `_WIZARD_STEPS` not empty / content sanity
  - `_print_welcome_panel` runs without error and renders every step
    description in the output
  - `_check_prerequisites` all-present / all-missing / mixed-state
    (3 cases covering the full install-hint logic)
  - `_is_first_run` first-run-clean-dir / has-env-only / has-yaml-only
    / has-both (4 cases covering the detection heuristic)
- **221 passing** total (up from 211).

## [0.4.5] - 2026-04-11

### Changed

- **`invoicer init` now PROPOSES the 1Password route interactively**
  instead of silently falling back to the 15-minute Google Cloud
  Console walkthrough when `credentials.json` is missing AND
  `invoicer.yaml` has no `secrets:` block yet. You get a real
  3-way choice at that exact moment:

  ```
  credentials.json not found at /path/to/credentials.json.
  ? How would you like to set it up?
    ❯ Fetch from 1Password  — 30 seconds if you already use 1Password
      Manual Google Cloud Console setup  — ~15 minutes, 4 steps
      Skip for now  — come back later with `invoicer init`
  ```

  If you pick **1Password**, the tool runs a full interactive
  onboarding:
  1. Pre-flights `op` installation + `op whoami` with actionable
     recovery messages if either fails.
  2. Enumerates your 1Password vaults via `op vault list --format=json`
     and offers them as a picker (falls back to free-text input if
     `op vault list` fails for any reason).
  3. Prompts for the item name (default: `invoicer-credentials-json`)
     and file field (default: `credentials.json`) — both standard
     conventions, both editable.
  4. Runs the fetch. On failure, offers to retry with different
     values or abort the 1P path.
  5. **Persists the successful vault/item/file combo to
     `invoicer.yaml`'s `secrets:` block via text surgery**, so every
     future `invoicer init` run skips this prompt entirely and goes
     straight to the cached fetch.

  Root cause of the bug this fixes: the 0.4.3 flow only checked for
  an already-declared `secrets:` block. If none was declared, it fell
  through to the manual Google Cloud Console walk without ever
  mentioning 1Password. Users with 1Password installed but an empty
  `secrets:` section never saw the 1P option offered — they'd just get
  walked into the slow path by default. Shouldn't happen; doesn't
  happen anymore.

- **Manual Google Cloud Console path** is still one click away — it's
  the second option in the picker. And "Skip for now" exits cleanly so
  you can come back later without a dirty working tree.

### Added

- **`secrets_vault.list_op_vaults()`** — enumerates the current `op`
  session's accessible vaults by parsing `op vault list --format=json`.
  Returns an empty list on any failure (not installed, not
  authenticated, malformed output, timeout) — callers fall back to
  free-text input. Best-effort UX, never raises.
- **`project_config.render_secrets_block(config)`** +
  **`_find_secrets_block(lines)`** + **`write_secrets_credentials_json_block(vault, item, file)`**
  — text-surgery helpers for the `secrets:` block in `invoicer.yaml`.
  Same pattern as the existing `defaults:` and `orgs:` writers:
  preserves comments and surrounding content, handles insert-when-
  absent / replace-when-present cases cleanly. Vault names with
  spaces are automatically quoted on write.
- **`_setup_1password_credentials_interactively()`** in `init_cmd.py`
  — drives the full interactive flow from the pre-flight checks to
  the yaml persist step. Recursively retries on fetch failure (user
  can type a different vault/item name without re-running init).

### Tests

- **+18 unit tests**:
  - `list_op_vaults`: not-installed / success / non-zero-exit /
    malformed-json / timeout / entry-without-name / non-list-payload
  - `render_secrets_block`: empty / vault-name-with-spaces-quoted /
    simple-vault-name-unquoted / fixed-key-order / skips-empty-values
  - `_find_secrets_block`: simple / missing / ignores-nested
  - `write_secrets_credentials_json_block`: insert-when-absent /
    replace-preserving-surrounding / raises-when-yaml-missing
- **211 passing** total (up from 193).

## [0.4.4] - 2026-04-11

### Changed

- **1Password onboarding docs broadened beyond welance.** The 0.4.3
  release shipped the 1Password fetch path, but the framing implied it
  was a welance-specific feature. It's not — the tool has zero
  welance-specific logic; the vault name, item name, and field name
  are all config values in `invoicer.yaml`. Anyone with 1Password
  (Personal, Teams, or Business) can adopt the same pattern: upload
  their own `credentials.json` to a Document item in a shared vault,
  point `invoicer.yaml`'s `secrets:` block at it, and every colleague
  with vault access runs `invoicer init` without ever touching Google
  Cloud Console by hand.
- **README quick-start** retitled from "Get started (welance team)" to
  "Get started with 1Password (3 commands)". Welance kept as a
  concrete worked example, not as the only supported path. Adds a
  "Setting up the shared 1Password item" section walking any team
  through creating their own Document item and pointing `invoicer.yaml`
  at it.
- **`getting-started` help topic** retitled from "Gmail — the welance
  path" to "Gmail — the 1Password path (recommended for teams)". Same
  expansion: generic walkthrough first, welance vault as a concrete
  instance.
- **`invoicer.example.yaml`** `secrets:` comment block now shows TWO
  examples: a generic template with `"Your Vault Name"` as the
  placeholder, and the welance-specific one underneath for welance
  colleagues to copy. Anyone else edits the generic one.
- **`troubleshooting` help topic** language broadened: "Ask whoever
  manages the 1Password vault" instead of the previous welance-only
  phrasing.

### Tests

- No code changes → no test changes. **193 passing** unchanged.

## [0.4.3] - 2026-04-11

### Added

- **1Password-backed distribution for `credentials.json`.** New
  `secrets:` block in `invoicer.yaml` lets a project declare which
  1Password vault + item holds its Gmail OAuth client file. On
  `invoicer init`, if `credentials.json` is missing locally AND the
  `secrets:` block is declared, the tool uses the 1Password CLI (`op`)
  to fetch the file directly from the vault, then runs the OAuth
  flow — no manual Google Cloud Console walk required. Welance
  colleagues can onboard in 3 commands: `brew install 1password-cli`,
  `uv tool install --editable .`, `invoicer init`.
  - Config shape: `secrets.credentials_json.{source, vault, item, file}`
  - Only `source: 1password` is implemented today; the discriminator
    leaves room for other vaults (Bitwarden, gcloud secret manager,
    etc.) without a config migration.
  - The `client_secret` inside `credentials.json` is, per Google's own
    docs, not actually cryptographically secret for Desktop OAuth
    clients — it's just a well-known identifier of the registered
    client. So one file is safe to share across a team, each member
    runs their own OAuth flow and gets their own `token.json` locally.
    Access is gated by 1Password vault membership, rotated in one place.
- **New `invoicer secrets fetch [--force]` command.** Explicit
  re-fetch of `credentials.json` from the configured 1Password vault.
  Useful when the admin rotates the Google Cloud OAuth client:
  admin updates the 1Password item once, every colleague runs
  `invoicer secrets fetch --force` on their machine to pull the new
  file. Refuses to overwrite an existing local `credentials.json`
  unless `--force` is passed, so you can't stomp on a manually-placed
  file by accident.
- **New `src/invoicer/secrets_vault.py` module** encapsulating the
  1Password CLI wrapper: `check_op_installed`, `check_op_authenticated`
  (returns signed-in email via `op whoami --format=json`),
  `fetch_credentials_json` (uses `op read "op://..."` with the
  secret-reference URI), and `fetch_credentials_json_from_config`.
  All error paths raise `VaultError` with actionable recovery hints
  that land directly in CLI output.

### Changed

- **README quick-start rewritten** to put the welance 1Password path
  first: three commands (`brew install 1password-cli`, `uv tool install`,
  `invoicer init`) and you're authenticated. The manual Google Cloud
  Console walkthrough is still there, relegated to a fallback section
  for non-welance forkers.
- **`getting-started` help topic** reframed around the 1Password path
  as primary, manual setup as fallback. Documents what's shared vs.
  what's per-user (credentials.json is client identifier → shared OK;
  token.json is per-user access+refresh → never shared). Includes
  the exact welance `secrets:` YAML block for copy-paste.
- **`_ensure_gmail_oauth` in `init_cmd.py`** now tries the 1P fetch
  first when `secrets:` is declared. Fetch failures are HARD errors
  when `secrets:` is declared — no silent fall-through to the manual
  path, because the user explicitly opted into 1Password and a
  silent fallback would hide the real problem (vault access revoked,
  item renamed, etc.). Only when `secrets:` is absent does init
  fall through to the manual Google Cloud Console walk.
- **`troubleshooting` help topic** gains three new 1Password-specific
  entries: "1Password CLI not installed", "Not signed in to 1Password
  CLI", and "Failed to fetch op://<vault>/<item>/credentials.json"
  with the three most likely causes in order.
- **`invoicer.example.yaml`** gets a commented `secrets:` block
  showing the welance values verbatim. Uncomment + paste into your
  `invoicer.yaml` and you're done.
- **`CLAUDE.md` safety invariants** get three new rules:
  - Never log or echo `credentials.json` contents in any code path.
    The bytes go from `subprocess.stdout` directly to disk via
    `write_bytes()` — no intermediate string representation.
    `TestNoSecretContentInErrorMessages` locks this in with a
    regression test that fails if a future contributor adds a
    print-stdout-on-error branch.
  - `op` subprocess errors must surface cleanly with actionable
    hints. Never catch `VaultError` silently and fall back to a
    different setup path when the user opted into 1Password.
  - The off-boarding flow for rotating the OAuth client is explicit:
    delete the old Google Cloud client, replace in 1Password,
    colleagues run `invoicer secrets fetch --force`. Old `token.json`
    files fail on first refresh, triggering automatic re-auth.

### Tests

- **+19 unit tests** in `test_secrets_vault.py`: `check_op_installed`
  present/absent, `check_op_authenticated` success/failure/timeout/
  malformed-JSON, `fetch_credentials_json` success/failure/timeout/
  nested-output-path, `fetch_credentials_json_from_config` missing-
  secrets/empty-secrets/unsupported-source/missing-vault-or-item/
  valid-config/default-file, `TestNoSecretContentInErrorMessages`
  (regression against stdout-bytes leaking into error output), and
  `TestFetchCredentialsJsonPathFromProject::test_respects_invoicer_dir`
  (wiring between config loader and `INVOICER_DIR` override).
- **All subprocess calls are mocked** — no real `op` binary required
  in CI.
- **193 passing** total (up from 174).

## [0.4.2] - 2026-04-11

### Changed

- **`invoicer init` is now idempotent.** Re-running on an already-configured
  project no longer forces the user to hit Enter through 15 pre-filled
  prompts just to add one new org. Each section detects existing config
  up-front and asks **Keep / Edit / Add another?** via `questionary.select`:
  - **Qonto** — detects existing `QONTO_LOGIN_*` / `QONTO_SECRET_KEY_*`
    pairs in `.env`, summarizes them ("Found 2 orgs: welance-srl (IT),
    welance-gmbh (DE)"), then asks. *Keep* skips the whole section;
    *Edit* walks every org; *Add another* appends new orgs to the list.
  - **Clockify** / **Gmail sender** / **Anthropic** — each detects its
    existing value and offers keep/edit.
  - **Gmail OAuth** — if `credentials.json` AND `token.json` exist and
    the token validates against the Gmail API, skip the entire Google
    Cloud Console walk silently. Only show the 4-step guide when
    `credentials.json` is missing.
- **Gmail OAuth setup is now hands-on.** On the missing-`credentials.json`
  path, init opens the browser to the Google Cloud Console, then
  **polls for the file to appear** via a rich spinner with a 5-minute
  timeout and Ctrl-C escape. When it appears, init immediately triggers
  the OAuth flow — which opens a second browser for account selection
  and writes `token.json` — without requiring the user to re-run any
  command. Previously the tool walked away after opening the first
  browser tab, leaving the user to figure out when to re-run things.
- **`orgs:` block is written to `invoicer.yaml` automatically**, not
  printed as a copy-paste snippet. Init builds the target block from
  the fresh Qonto credentials, diffs it against the existing one in
  `invoicer.yaml`, and only prompts when they differ. The prompt
  shows the proposed block and asks y/N before writing — same
  confirm-before-mutation pattern the tool uses everywhere else.
  Text surgery preserves comments and ordering in the rest of the file
  (same approach as the 0.4.0 `defaults:` writer).
- **Inline "save default org?"** at the end of init — when you've
  configured at least one Qonto org and `defaults.org` isn't already
  set, init offers to cache your pick so `draft` / `mail-draft` /
  `client add` never have to prompt for `--org` again. Single-org setups
  get a y/N; multi-org setups get a `questionary.select`.
- **"Next steps" block now prints only the delta.** If you only
  fixed a typo in a secret, there's nothing printed beyond "Nothing
  changed. Run `invoicer draft …` when you're ready." If you added a
  new org, the next step is `invoicer discover --org <new-org>`.

### Added

- **`invoicer init --force`** — skip the idempotency checks and re-prompt
  every section even if it's already configured. For the rare case where
  the state is correct but the user wants to walk through it anyway
  (e.g. rotating a secret from scratch, or demoing the flow).

### Tests

- +29 unit tests: detection helpers (`_detect_qonto_orgs_in_env` for
  single org / multi-org / unpaired / legacy / empty edge cases; plus
  clockify/gmail/anthropic detectors), `_env_suffix` normalization,
  `_orgs_blocks_differ` semantic comparison, `render_orgs_block` output
  format, `_find_orgs_block` line-range detection, and
  `write_orgs_block` round-trip (insert-when-absent,
  replace-preserves-surrounding, raises-when-yaml-missing).
- **174 passing** total (up from 145).

## [0.4.1] - 2026-04-11

### Fixed

- **`invoicer defaults` no longer crashes with a Python traceback when
  invoicer.yaml is missing.** The 0.4.0 release introduced a regression:
  running `invoicer defaults` from a directory without a project config
  (a fresh clone, or a user exploring from the wrong `cwd`) blew up
  with a `RuntimeError` from `load_yaml()` via `get_defaults()`. Read
  operations on cached config should degrade gracefully — the listing
  path now returns `{}` when no yaml exists and prints a friendly "no
  invoicer.yaml here, run `invoicer init`" message. `defaults set` /
  `unset` (the mutating paths) still require a valid yaml but report
  a clean error instead of a traceback. New unit tests lock the
  graceful-missing-file path in for `get_defaults`, `list_orgs`,
  and the `_defaults_root` CLI handler.

### Added

- **`invoicer --version` / `-V`** — prints the installed version and
  exits. Standard CLI convention; we'd been missing it.
- **`invoicer help` welcome panel now shows version + release links.**
  The top of the panel surfaces:
  - `r001-05-invoicer v<current>` — so non-tech users can tell which
    build they have (useful when asking "did this change reach me?")
  - **Release notes** URL — a direct link to
    `/releases/tag/v<current>` on GitHub, which has the release page
    with the changelog for that version
  - **What changed since v<previous>** — a GitHub compare URL
    (`/compare/v<previous>...v<current>`) giving a diff view of every
    commit between the two tags
  The previous version is discovered by parsing `CHANGELOG.md` for
  `## [X.Y.Z]` headings in file order. For editable installs (what
  your non-tech colleagues have via `uv tool install --editable .`)
  both links always work; for wheel installs the compare link is
  omitted since the changelog isn't bundled.
- **Shell autocomplete — documented, not new.** Typer already provides
  `invoicer --install-completion` and `invoicer --show-completion` out
  of the box (auto-detects bash / zsh / fish / powershell). The
  `getting-started` help topic and the README Install section now
  tell non-technical users to run it once per shell.

## [0.4.0] - 2026-04-11

### Added

- **Multi-org support** — invoice from more than one legal entity (e.g. SRL
  + GmbH) out of a single installation. `invoicer.yaml` gets an `orgs:`
  block that maps an org id to its country and the env-var names that hold
  its Qonto credentials. `draft`, `client add`, `mail-draft`, `finalize`,
  and `discover` all accept a new `--org` flag; when absent, the tool
  resolves the active org via project-level pin → `defaults.org` →
  single-org shortcut → interactive prompt. The prompt path then offers to
  save the picked value as the default so you only pay the prompt tax once.
  See `invoicer help multi-org` for the full setup story.
- **`invoicer defaults` command group** — inspect and edit cached routing
  answers in `invoicer.yaml`.
  - `invoicer defaults` — rich table of current defaults
  - `invoicer defaults set` — walk known keys with questionary prompts,
    diff, confirm, write
  - `invoicer defaults set --ai` — describe the defaults you want in
    free-form text; Haiku maps it to keys via an **enum-constrained schema**
    that cannot hallucinate org ids. Diff + confirm + write.
  - `invoicer defaults unset <key>` — remove one default
  Known keys: `org`, `locale`, `gmail_sender`. The writer does targeted
  text surgery on `invoicer.yaml` so comments and formatting around the
  `defaults:` block survive untouched.
- **New help topic `multi-org`** covering `orgs:`/`defaults:` schema, the
  `--org` resolution chain, SDI-gating on org country, Gmail-across-orgs
  story, and the legacy single-org fallback.
- **`invoicer init` walks multi-org** — prompts for one or more Qonto orgs,
  writes per-org env vars (`QONTO_LOGIN_<SUFFIX>` / `QONTO_SECRET_KEY_<SUFFIX>`),
  runs one connectivity test per org, and prints an `orgs:` YAML snippet to
  paste into `invoicer.yaml`.

### Fixed

- **TP02/MP05 SDI payment codes no longer leak onto non-Italian invoices.**
  Before 0.4.0, `qonto.build_invoice_payload` hardcoded `payment_reporting:
  {conditions: TP02, method: MP05}` on *every* draft, regardless of the
  seller's country. For a German welance Ventures GmbH invoice this meant
  shipping Italian e-invoicing metadata to Qonto DE — either silently
  accepted but semantically wrong, or rejected at finalize time. The
  builder is now `payment_reporting: dict | None = None` and `cli.draft`
  only passes the IT codes when the active org has `country: IT` in
  `invoicer.yaml`.

### Changed

- **`invoicer client add --locale`** help string narrowed to advertise
  `it, en, de` only — these are the three actually used by the welance
  team. The flag still accepts any value; it just doesn't suggest others.
- **`invoicer discover`** now accepts `--org` and lists Qonto clients from
  one org at a time. Run it twice (or pass `--org` on each) to see both
  accounts' inventories.
- **`resolve_qonto_client_id`** now accepts an optional `org_id` and filters
  client mappings by their `org:` field if set — so the same Clockify client
  can map to different Qonto clients across the SRL and GmbH accounts.
- **Legacy `QONTO_LOGIN` / `QONTO_SECRET_KEY`** are no longer in `REQUIRED_ENV`;
  the check moved into `_resolve_org()` so the error message cites
  `invoicer.yaml` and tells the user how to migrate. Existing single-org
  installs keep working — nothing to change if you don't want to.
- **`CLAUDE.md` safety invariants extended**: explicit rules that defaults
  only cache routing answers (never confirmations), that Gmail sender and
  authenticated mailbox are distinct, and that SDI codes are gated on the
  active org's country.

## [0.3.0] - 2026-04-11

### Changed

- **`invoicer client extract` removed, folded into `invoicer client add`.** The
  two commands overlapped: `extract` parsed text with Haiku and printed the
  fields, `add` did the same plus review + POST. Having two entry points
  created pointless cognitive load and a permanent "which one do I run?"
  question. `client add` is now the single entry point — decline the final
  confirmation if you only want to preview extraction.

### Added

- **`invoicer update`** — one-command self-updater for non-technical users.
  Runs `git pull --ff-only` followed by `uv tool install --editable . --force`
  against the repo that backs the editable install. Refuses to run with a
  dirty working tree or a diverged branch, so there's no silent data loss.
- **`invoicer client add --no-ai`** — skip LLM extraction entirely and walk
  through a guided sequence of field prompts instead. Lets users without an
  Anthropic API key (or with exhausted credits) create Qonto clients from the
  CLI. Italian-specific fields (`province_code`, `pec_email`, `recipient_code`)
  are only prompted when `country_code` is `IT`, to avoid meaningless prompts
  for non-IT clients.


## [0.2.1] - 2026-04-11

### Fixed

- **`invoicer help` now shows the command list**, not just the topic index.
  The initial 0.2.0 implementation copied the `uv help` / `gh help` shape
  (topics only) but most users reach for `invoicer help` expecting a `git help`
  shape (commands first). The welcome panel now shows:

  1. A **Commands** section auto-generated from Typer's registered commands
     (top-level + sub-typer groups like `client add`)
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
