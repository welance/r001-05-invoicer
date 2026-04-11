# Troubleshooting

Common errors and how to recover. Each section is a real error we've hit or audited.

## `RuntimeError: Missing env vars: [...]`

You're running `invoicer` from a directory that has no `.env`. The tool resolves config against the **current working directory** (or `$INVOICER_DIR` if set).

**Fix**: `cd` to the root of your project clone, then retry. Or run `invoicer init` from that directory to create a `.env`.

## `invoicer.yaml not found`

Same cause as above — wrong directory, or you haven't copied `invoicer.example.yaml` yet.

**Fix**: `cp invoicer.example.yaml invoicer.yaml`, edit it to add your mappings, then retry. Or run `invoicer init`.

## `Qonto rejected the invoice payload: 422 ... IBAN is empty`

Very unlikely in v0.1.1+ — the `draft` command now auto-fetches the org's main bank account from Qonto. If you still see this, your Qonto org may have no active bank account, or the API schema changed.

**Fix**: verify you have an active EUR bank account in Qonto. If the schema drifted, open a GitHub issue with the exact error.

## `Qonto rejected ... {"code":"required","detail":"payment must have a value"}`

Same family as the IBAN error — means the `payment_methods` object is missing. Was a bug pre-0.1.0, should not happen now. If it does, the API schema changed.

## `Qonto rejected ... vat_exemption_reason required`

You configured `vat_rate: 0` on a project but didn't set `vat_exemption_reason`. Italian orgs require an SDI N-code for every 0%-VAT line.

**Fix**: set `vat_exemption_reason: "N3.2"` (or `N2.1`, or whichever code your accountant approved) in `invoicer.yaml` under the project, then retry. See `invoicer help italy-sdi`.

## `No project matches 'xxx'`

The fuzzy matcher couldn't find any alias or name in `invoicer.yaml` that matches. Possible causes:
- The project alias contains punctuation that normalizes differently than you typed
- You haven't added the project to `invoicer.yaml` yet
- Typo

**Fix**: run `invoicer discover` to see all configured projects and their aliases. Add the project to `invoicer.yaml` if missing.

## `invoicer init` says "Found existing .env (N keys)" but you expected a fresh one

**Fix in v0.1.1+**: this was a path-resolution bug where the tool read from the install source directory instead of the CWD. Upgrade to v0.1.1 or later:

```bash
cd /path/to/your/clone
git pull
uv tool uninstall r001-05-invoicer
uv tool install --editable .
```

## Gmail IMAP `[AUTHENTICATIONFAILED] Invalid credentials`

**Cause**: you're on an old version of the tool that used IMAP app passwords. v0.1.0+ uses Gmail API OAuth2 instead.

**Fix**: upgrade the tool, then follow `invoicer help getting-started` for Gmail OAuth setup.

## `credentials.json not found`

**Fix**: see the Gmail section of `invoicer help getting-started` — you need to create a Google Cloud project and download the OAuth Desktop client as `credentials.json`.

## Gmail draft is created but doesn't appear in my Drafts folder

**Cause 1 (most common)**: the OAuth flow authorized a different Google account than the one you're viewing Gmail as.

**Fix**: delete `token.json`, re-run `invoicer mail-draft ...`, and make sure your browser is logged into the correct Google account when the consent screen appears.

**Cause 2**: Gmail UI caching. Hard-reload with ⌘+Shift+R or search `in:drafts subject:<client>` directly.

## SDI status stuck on `pending` for hours

Qonto submits to SDI asynchronously. Typical time from finalize to `accepted` is minutes to hours, sometimes longer during Italian business hours peaks.

**Fix**: wait, or check Qonto's web UI for the real-time SDI status. If it's stuck for 24+ hours, contact Qonto support.

## SDI rejected my finalized invoice

See `invoicer help italy-sdi` → "If SDI rejects" section. You can't edit a finalized invoice — you fix the client record and Qonto retries.

## Clockify `401 Unauthorized`

**Cause**: invalid `CLOCKIFY_API_KEY` in `.env`.

**Fix**: regenerate at https://app.clockify.me/user/settings (bottom of page) and update `.env`.

## Qonto `401 Unauthorized`

**Cause**: invalid `QONTO_LOGIN` or `QONTO_SECRET_KEY`, or the auth header format is wrong. Qonto uses `Authorization: <login>:<secret>` (a single colon-separated header, not Basic auth).

**Fix**: verify both values in Qonto → Settings → Integrations → API, update `.env`.

## Anthropic `insufficient_quota`

**Cause**: your Anthropic API key has no credits left.

**Fix**: add credits at https://console.anthropic.com/settings/billing. Or use the manual form path (`invoicer client add` without `--from-file` for text input — but still needs the key for extraction).

## Nothing above matches

Open an issue at https://github.com/welance/r001-05-invoicer/issues/new/choose with:
- The exact command you ran
- The full error output (with any secrets redacted)
- `invoicer --version` (or the commit hash you're on)
- Your OS and Python version
