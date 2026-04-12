# CLAUDE.md

Project conventions for `r001-05-invoicer` (Clockify → Qonto invoicing CLI).
Read before editing.

## Command surface — keep these in sync

Adding, removing, or renaming a Typer command in `src/invoicer/cli.py`
requires updating:

- `README.md` — the `## Commands` block, and the env-var table if the
  command needs a new `.env` key
- `CHANGELOG.md` — a bullet under `## [Unreleased]`
- `tests/unit/test_help_topics.py` — the
  `TestListTopics.test_list_topics_includes_commands` assertion lists the
  expected command names
- `src/invoicer/help/*.md` — any topic that references the old/new command
  by name (grep before editing)
- `.env.example` and `src/invoicer/init_cmd.py` — if the command touches an
  environment variable

`invoicer help` auto-introspects Typer via `src/invoicer/help_cmd.py`
(`registered_commands` + `registered_groups`). Do **not** hand-edit the
command list there — add/rename commands in `cli.py` and help updates
itself.

The welcome panel also surfaces `invoicer v<current>`, a release-notes
URL, and a GitHub compare URL against the previous version. The
previous version is found by parsing `CHANGELOG.md` `## [X.Y.Z]`
headings in file order. **Whenever you cut a release, add the new
`## [X.Y.Z] - YYYY-MM-DD` heading ABOVE the prior one** — the order
is what the compare URL depends on. If you skip this, the compare
link will point at the wrong predecessor until you fix it.

## Safety invariants — do not break

- **Every write command shows a rich pre-mutation summary panel + explicit
  confirm.** See `src/invoicer/summary.py`. Any new command that POSTs /
  PATCHes / PUTs needs one.
- **`draft` auto-registration writes to `invoicer.yaml` only after a
  confirm panel; never silent.** See `src/invoicer/draft_setup.py`. The
  Qonto pre-mutation panel still runs after registration completes —
  registering does not skip the invoice confirm. Client PATCHes go through
  `print_client_summary` before writing.
- **`src/invoicer/gmail.py` must never call `.send()` and must never import
  `smtplib`.** Enforced by AST tests in
  `tests/unit/test_help_topics.py::TestGmailModuleSafety`. The `gmail.modify`
  OAuth scope *does* technically permit sending; the safety property is
  code-level, not scope-level.
- **`finalize` requires typed confirmation** of the invoice number — not a
  `y/N`. Do not soften this.
- **LLM calls are opt-in only.** Today that means `invoicer client add` in
  its default (AI) mode and `invoicer defaults set --ai`; both paths have
  a `--no-ai` / non-AI variant. A happy-path monthly invoice run uses zero
  LLM tokens. Do not add LLM calls to `draft` / `finalize` / `mail-draft`.
- **`defaults:` in `invoicer.yaml` caches ONLY routing answers** (`org`,
  `locale`, `gmail_sender`) — never confirmation gates. Do not add keys
  that would let the tool skip the pre-mutation panel or the typed
  finalize confirmation. The point of those prompts is that the user
  cannot *not* see them.
- **Gmail sender ≠ authenticated account** is a lurking footgun. `token.json`
  is issued to whoever goes through the installed-app OAuth flow on first
  run; the `GMAIL_SENDER` env var only sets the `From:` header. If they
  disagree, Google Workspace either rewrites the header or fails at send
  time. When in doubt: auth as the mailbox you want to send from.
- **SDI `payment_reporting` codes (`TP02`/`MP05`) belong ONLY on Italian
  invoices.** The `draft` command gates them on the active org's `country`
  field in `invoicer.yaml`. Never pass them unconditionally —
  `qonto.build_invoice_payload` accepts `payment_reporting=None` precisely
  so non-IT orgs don't carry Italian e-invoicing metadata.
- **`secrets_vault.py` must NEVER log or echo the contents of
  `credentials.json`.** Subprocess stdout from `op read` is written
  directly to disk via `output_path.write_bytes(result.stdout)` — the
  bytes never land in a log, a print, an f-string, or an exception
  message. Only subprocess **stderr** and our own diagnostic strings
  (email of signed-in user, vault name, item name) may appear in
  error output. `test_secrets_vault.py::TestNoSecretContentInErrorMessages`
  locks this in with a regression test. If a future contributor adds
  a print-stdout-on-error code path to help debugging, that test fails
  — on purpose.
- **`op` subprocess errors must surface cleanly with actionable recovery
  hints.** Never catch `VaultError` silently and fall back to a different
  setup path when the user explicitly opted into 1Password (i.e. when
  `invoicer.yaml` has a `secrets:` block). Swallowing the error would
  turn "you're not a vault member" into a mysterious "OAuth flow failed"
  — a much worse debugging experience. The ONLY silent fallback allowed
  is when the `secrets:` block is absent entirely (non-welance forkers
  using the manual Google Cloud Console path).
- **Off-boarding story for `credentials.json` rotation** (documented so
  future-me can re-derive it): removing a colleague from the
  `p007-01 Welance` 1Password vault revokes their ability to fetch new
  copies, but their existing local `credentials.json` and `token.json`
  keep working until someone explicitly revokes them. To invalidate
  every active `token.json` across every machine, rotate the Google
  Cloud OAuth client: delete the old client ID in Google Cloud Console,
  generate a new `credentials.json`, replace the file in 1Password, and
  every colleague runs `invoicer secrets fetch --force` on next use.
  Old tokens fail on first refresh; new OAuth flow triggers
  automatically via `_ensure_gmail_oauth`.

## Italian SDI specifics

`src/invoicer/qonto.py` hardcodes Italian e-invoicing defaults
(`payment_reporting: { conditions: TP02, method: MP05 }`, N-codes for VAT
exemptions, etc.). These are real SDI tax codes, not cosmetic strings. Read
`src/invoicer/help/italy-sdi.md` before touching them.

## Tests

- `uv run pytest -q` — the full suite should pass (108 tests as of the
  last edit). Fast: runs in well under a second because we mock nothing.
- `uv run ruff check src/invoicer tests` — CI runs this, so run it locally
  before committing.
- Unit tests cover pure math, payload builders, and parsers. External APIs
  and LLM output are deliberately not stubbed — rationale in
  `docs/TESTING.md`.
- CI (`.github/workflows/ci.yml`) runs lint + unit tests + a CLI smoke test
  that `--help`s every top-level command. When you add a new command, add
  it to the smoke-test list too.

## Shipping a change (commits → PR → release)

Non-technical users install from a clone and run `invoicer update` to
pull + reinstall. For that to mean anything, merged work must land on
tagged releases. The flow:

1. **Branch + commits.** Work on a feature branch (`feat/...`,
   `fix/...`). Group commits by logical change — e.g. "merge two
   commands" and "add update command" are separate commits, not one
   dump. Commit messages follow conventional-commit prefixes (`feat:`,
   `fix:`, `docs:`, `chore:`, `build:`) — `git log` shows the
   convention.
2. **PR.** Open with `gh pr create`. Title ≤70 chars, conventional
   prefix. Body: `## Summary` bullets + `## Test plan` checklist. Wait
   for CI green before merging.
3. **Version bump + CHANGELOG.** User-visible changes need a
   `pyproject.toml` version bump and a `CHANGELOG.md` entry. Bumping
   rule:
   - **patch** (`0.2.1 → 0.2.2`) — bug fixes, doc-only changes
   - **minor** (`0.2.1 → 0.3.0`) — new commands, new flags, removed
     commands (pre-1.0, removals are minor not major)
   - **major** — reserved for post-1.0
   Do the bump + CHANGELOG as part of the same PR that ships the
   feature, not a separate "release PR".
4. **Tag + GitHub release after merge.** Once the PR is merged to
   `main`:
   ```bash
   git checkout main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   gh release create vX.Y.Z --title "vX.Y.Z" --notes-from-tag
   ```
   Or pass `--notes` directly with the CHANGELOG section for that
   version. There is no auto-publish workflow on tag — the tag + GitHub
   release are the deliverable, and `invoicer update` pulls them via
   plain `git pull`.
5. **Never tag an unmerged or dirty tree.** Tags must point at a commit
   that is on `origin/main` and matches the CHANGELOG entry exactly.
