# Security

This tool touches a **real billing API** (Qonto) and a **real mailbox** (Gmail). The safety model is explicit and worth understanding.

## Secrets are never in git

The following files are gitignored and **must never be committed**:

- `.env` — API keys for Clockify, Qonto, Anthropic, and the Gmail sender address
- `credentials.json` — Google OAuth client (technically not secret per Google's own docs for desktop apps, but still)
- `token.json` — Gmail OAuth refresh token (very sensitive — grants full mailbox access)
- `invoicer.yaml` — client mappings and rates (not secrets, but business data)

The `.gitignore` catches all four. The pre-commit hook runs `gitleaks` to scan for accidental leaks.

## Gmail scope — the honest story

This tool uses the `https://www.googleapis.com/auth/gmail.modify` scope. Per Google's official documentation, this scope permits:

- `drafts.create`, `drafts.update`, `drafts.delete`
- `messages.get`, `messages.list`, `messages.modify`
- **`messages.send`**
- **`drafts.send`**
- Everything else short of permanent deletion

**The scope does NOT enforce "drafts only"**. Earlier versions of this README falsely claimed it did. The actual safety property is:

> **This tool's source code only calls `drafts().create()` and `drafts().update()`, never `send()`.**

Audit `src/invoicer/gmail.py` — the file is ~100 lines and has no call to `send()`, `messages.send()`, or `smtplib`. If a future contributor adds one, it will show up in code review and tests will fail (the test suite asserts `gmail.py` doesn't import `smtplib` or call `send`).

The guarantee is **code-level**, not scope-level. If you don't trust the code, don't run it with a real Gmail account.

## Rotating secrets

Rotate any credentials that appear in your chat history, logs, or were copy-pasted anywhere non-trusted. Sources:

| Secret | Rotate at |
|---|---|
| Clockify API key | https://app.clockify.me/user/settings |
| Qonto API secret | Qonto app → Settings → Integrations → API |
| Anthropic API key | https://console.anthropic.com/settings/keys |
| Google OAuth client_secret | https://console.cloud.google.com/apis/credentials → your project |
| Gmail OAuth token (token.json) | Delete the file; next run opens a browser for re-consent |

After rotation, update `.env` with the new values and run `invoicer init` to test the connections.

## Rotating Google OAuth

If you suspect `credentials.json` is compromised:

1. https://console.cloud.google.com/apis/credentials → your OAuth client → Delete
2. Create a new OAuth client → Download JSON → save as `credentials.json`
3. Delete `token.json` (the old access token is now invalid anyway)
4. Next `invoicer mail-draft` run re-runs OAuth consent

## Branch protection

The GitHub repo has:
- Required PR before merging to `main`
- Required CI status checks (`build (3.11)`, `build (3.12)`)
- Required branches up-to-date before merge
- Linear history (no merge commits)
- No force pushes
- No branch deletion
- GitHub secret scanning + push protection enabled
- Dependabot security updates enabled

These prevent "oops I pushed a secret to main" as a class of mistake.

## Reporting vulnerabilities

See `SECURITY.md` in the repo root. Use GitHub Security Advisories for private disclosure — don't open public issues for security findings.
