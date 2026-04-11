# Testing guide

The tool touches real billing APIs, so the testing strategy prioritizes **catching wrong-money bugs cheaply** and **making the write path boring to verify**.

## Run the tests

```bash
# Install dev deps
uv pip install -e ".[dev]"

# Run everything (fast — <1 second)
pytest tests/unit -v

# With coverage
pytest tests/unit --cov=invoicer --cov-report=term-missing
```

## Test tiers

### Tier 1 — Pure-function unit tests (`tests/unit/`)

These are the heart of the safety story. They cover every pure function that produces money numbers or API payloads. No HTTP, no env vars, no filesystem — just `assert fn(input) == expected`.

| File | What it covers | Why it matters |
|---|---|---|
| `test_clockify_rounding.py` | ISO 8601 duration parsing, per-entry 15-min ceiling rounding | If rounding is off, every invoice is off |
| `test_qonto_payloads.py` | `build_client_payload`, `build_invoice_item`, `build_invoice_payload` | The exact JSON we POST to Qonto — including regression tests for the `payment_methods` field name bug we hit in v0.1 |
| `test_csv_export.py` | Timesheet CSV generation from invoice items, including Unicode usernames, malformed descriptions, float precision | The timesheet attached to the email |
| `test_project_config.py` | Fuzzy project matcher, `_normalize` helper, exact-vs-substring priority | Users typing `allsafe` must find the right project; ambiguous queries must return all candidates |

### Tier 2 — Integration tests against sandboxes (not yet implemented)

A future directory `tests/integration/` would verify the HTTP clients against:

- **Clockify**: real test workspace (read-only, safe)
- **Qonto**: against a test client that the test deletes after each run
- **Gmail API**: against a dedicated test inbox, asserting drafts appear

These need credentials and are slow — they'd run on a schedule, not on every commit.

### Tier 3 — End-to-end manual testing

Still the primary way any change to the write path gets validated:

1. Create a throwaway Qonto client named e.g. "TEST — DO NOT SEND"
2. Create a throwaway Clockify project with a few hours
3. Run `invoicer draft test-client --month YYYY-MM`
4. Review in the Qonto UI, verify lines / totals / VAT match expectations
5. Delete the draft
6. Test `finalize` only against the throwaway client
7. Test `mail-draft` against your own email as the recipient

Document any new E2E scenarios in the PR description.

## What we deliberately DON'T test

- **External API schemas**: if Qonto renames a field, the tests won't catch it — you'll find out when a real 422 hits the CLI. We rely on the clear error messages and the pre-mutation gates to contain the blast radius.
- **Typer CLI argument parsing**: Typer itself is tested upstream. We trust it.
- **`rich` rendering**: the panels are cosmetic and not worth testing.
- **The LLM output**: `invoicer client extract` calls Haiku which is non-deterministic by design. Tests would have to stub the Anthropic SDK, which is more mocking than value. We review extracted fields manually before any write.

## Pre-commit hook

The repo ships a `.pre-commit-config.yaml` that runs on every `git commit`:

```bash
# One-time setup
uv pip install pre-commit
pre-commit install

# Now every commit runs:
# - trailing whitespace / EOF fixes
# - YAML/TOML syntax check
# - gitleaks (secret detection)
# - ruff lint + format
# - pytest tests/unit (fast)
```

To skip the hook for a WIP commit, use `git commit --no-verify` — but don't push such commits to `main`.

To run it manually on all files without committing:

```bash
pre-commit run --all-files
```

## Writing new tests

A new test should be added whenever:

1. **You fix a bug** — add a test that fails before the fix and passes after. Goal: never regress the same bug twice.
2. **You add a new pure function** on the write path or the aggregation path.
3. **Qonto's API rejects a payload** — add a regression test asserting our payload builder produces the corrected shape.

Tests that require real network access go in `tests/integration/` (future) and are skipped by default with `pytest tests/unit`.

## Current coverage

Run:
```bash
pytest tests/unit --cov=invoicer --cov-report=term
```

As of v0.1.0, coverage is **intentionally uneven**:
- `clockify.py` rounding math: ~100%
- `qonto.py` payload builders: ~100%
- `csv_export.py`: ~100%
- `project_config.py`: ~100%
- Everything else (HTTP clients, CLI glue, Gmail draft creation): **0%**, intentionally, because those paths require network access.

If you want to improve coverage meaningfully, focus on Tier 2 integration tests rather than mocking the HTTP calls.
