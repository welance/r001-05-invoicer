# Security Policy

## Supported Versions

This project is in early development. Only the latest `0.1.x` release is supported.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

If you believe you've found a security issue in this tool, please report it privately:

- **Preferred**: open a [GitHub Security Advisory](https://github.com/welance/r001-05-invoicer/security/advisories/new) (private)
- **Alternate**: email `hello@welance.com` with `[SECURITY] r001-05-invoicer` in the subject

Please include:

- A clear description of the issue
- Steps to reproduce
- The versions affected
- Any suggested mitigation

We will acknowledge receipt within **5 business days** and aim to provide a fix or workaround within **30 days** for high-severity issues.

## Scope

Because this tool touches **real billing APIs** (Qonto) and **real mailboxes** (Gmail), we take security reports particularly seriously in these areas:

- **Credential leakage**: anything that could log, transmit, or expose API keys, OAuth tokens, or `credentials.json`.
- **Unauthorized writes**: any code path that could create, modify, finalize, or send an invoice without the explicit user confirmation gates in place.
- **Unauthorized sends**: the `mail-draft` command uses the Gmail `gmail.modify` scope, which per Google's documentation DOES technically allow `messages.send` / `drafts.send`. The safety comes from the source code (`src/invoicer/gmail.py` only calls `drafts.create()` and `drafts.update()`). If you find any code path — direct or transitive — that could result in an actual send without the user clicking Send in Gmail's UI, that is a high-severity issue.
- **Injection**: unsanitized user input that could be interpreted by Qonto, Gmail, or Clockify APIs in unintended ways.

## Out of scope

- Vulnerabilities in third-party APIs (Clockify, Qonto, Gmail, Anthropic) — report those directly to the respective vendor.
- Issues that require local file system access already equivalent to the attacker reading `.env`.
