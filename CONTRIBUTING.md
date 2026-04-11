# Contributing

Thanks for considering a contribution.

## Scope

This tool is intentionally small and opinionated. Its job is to connect **Clockify** to **Qonto** for a single use case: monthly consulting invoices for small digital agencies. Features that broaden that scope (other time trackers, other billing providers, other invoice types) are welcome as discussions first.

## What we like in PRs

- **Bug fixes** with a minimal repro in the PR description
- **Documentation improvements** — especially for non-Italian jurisdictions (Germany, France, Spain e-invoicing)
- **New safety gates** — typed confirmations, dry-run modes, sanity checks
- **Small command additions** that follow the existing pattern: a pre-mutation summary panel, a confirmation prompt, then the write
- **Clear error messages** when an API returns a 4xx

## What we'd rather not merge

- **Unrelated new integrations** (e.g. "add Stripe support") — these usually deserve their own fork
- **Aggressive refactors** without a concrete problem they solve
- **Implicit API writes** — anything that touches Qonto or Gmail without an explicit `y/N` gate
- **Hardcoded company-specific logic** — per-org config goes in `invoicer.yaml`, not in Python

## Development setup

```bash
git clone https://github.com/welance/invoicer.git
cd invoicer
uv venv
uv pip install -e .
cp .env.example .env   # fill in your own keys (use a throwaway Qonto client for testing)
cp invoicer.example.yaml invoicer.yaml
```

## Testing

There are currently **no automated tests**. Given the tool's dependency on real external APIs (Clockify, Qonto, Gmail, Anthropic), testing has been manual against real accounts using draft/throwaway clients. PRs that add unit tests for the pure functions (aggregation math, rate/VAT math, payload building, CSV generation) are very welcome.

## Reporting issues

Open a GitHub issue with:
- The command you ran
- What you expected
- What happened
- Redacted API error response if any (**never paste secrets or real client data**)

## Disclaimer

This tool writes real fiscal documents. Contributions that affect the write path (`draft`, `finalize`, payload builders) will be scrutinized carefully. See the disclaimers in `README.md`.
