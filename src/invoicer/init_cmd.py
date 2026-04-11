"""`invoicer init` — interactive first-run setup.

Walks a fresh user through:
  1. Detect / prompt for every env var → write .env
  2. Detect / copy invoicer.example.yaml → invoicer.yaml
  3. Check for credentials.json and explain how to obtain one
  4. Test connectivity to every service (Clockify, Qonto, Gmail, Anthropic)
  5. Print next steps

Idempotent: re-running preserves existing values as defaults.
"""

from __future__ import annotations

import os
import shutil
import webbrowser
from pathlib import Path

import questionary
import typer

from .config import get_project_root


def _env_path() -> Path:
    return get_project_root() / ".env"


def _env_example_path() -> Path:
    return get_project_root() / ".env.example"


def _invoicer_yaml_path() -> Path:
    return get_project_root() / "invoicer.yaml"


def _invoicer_example_path() -> Path:
    return get_project_root() / "invoicer.example.yaml"


def _credentials_path() -> Path:
    return get_project_root() / "credentials.json"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def _env_suffix(org_id: str) -> str:
    """Normalize an org id like 'welance-srl' to an env-var suffix: 'WELANCE_SRL'.

    Only [A-Z0-9_] is permitted; anything else becomes '_'. Collapses runs.
    """
    import re

    up = (org_id or "").upper()
    cleaned = re.sub(r"[^A-Z0-9]+", "_", up).strip("_")
    return cleaned or "ORG"


def _write_env_file(
    path: Path,
    values: dict[str, str],
    orgs: list[dict[str, str]],
) -> None:
    lines: list[str] = [
        "# Qonto Business API (https://thirdparty.qonto.com)",
        "# Per-org credentials — one pair per legal entity. The invoicer.yaml",
        "# `orgs:` block references these by env-var name.",
    ]
    for org in orgs:
        suffix = _env_suffix(org["id"])
        lines += [
            "",
            f"# Org: {org['id']}  ({org.get('country', '?')})",
            f"QONTO_LOGIN_{suffix}={org.get('login', '')}",
            f"QONTO_SECRET_KEY_{suffix}={org.get('secret', '')}",
        ]
    lines += [
        "",
        "# Clockify API (https://clockify.me/developers-api)",
        f"CLOCKIFY_API_KEY={values.get('CLOCKIFY_API_KEY', '')}",
        f"CLOCKIFY_WORKSPACE_ID={values.get('CLOCKIFY_WORKSPACE_ID', '')}",
        "",
        "# Gmail API (OAuth2) — also needs credentials.json + token.json",
        f"GMAIL_SENDER={values.get('GMAIL_SENDER', '')}",
        f"GMAIL_SENDER_NAME={values.get('GMAIL_SENDER_NAME', '')}",
        "",
        "# Optional: Anthropic for `invoicer client add` (not needed with --no-ai)",
        f"ANTHROPIC_API_KEY={values.get('ANTHROPIC_API_KEY', '')}",
    ]
    path.write_text("\n".join(lines) + "\n")


def _prompt_orgs(existing: dict[str, str]) -> list[dict[str, str]]:
    """Prompt for one or more Qonto orgs. Returns a list of dicts with
    id / country / login / secret. Pre-fills defaults from existing .env
    values when possible (legacy QONTO_LOGIN / QONTO_SECRET_KEY → first org).
    """
    orgs: list[dict[str, str]] = []
    typer.secho("== Qonto ==", fg="cyan", bold=True)
    typer.echo(
        "Each Qonto org (legal entity) needs its own API credentials — "
        "Qonto's API is per-org-scoped. If you only invoice from one entity, "
        "just add one org here.\n"
    )

    while True:
        idx = len(orgs) + 1
        typer.secho(f"-- Qonto org #{idx} --", fg="cyan")

        # For the first org, pre-fill id + login from legacy env vars if present.
        default_login = ""
        if idx == 1:
            default_login = existing.get("QONTO_LOGIN", "")
        # Also try per-org keys if re-running init on a multi-org setup.
        # The user may have already added a few orgs.

        org_id = questionary.text(
            "Short id for this org (e.g. 'welance-srl', 'welance-gmbh'):",
        ).ask() or ""
        org_id = org_id.strip()
        if not org_id:
            typer.echo("Empty org id — skipping.", err=True)
            break

        country = questionary.text(
            "Country (2-letter code, e.g. IT, DE, FR):",
        ).ask() or ""
        country = country.strip().upper()

        # If re-running init, honor existing QONTO_LOGIN_<SUFFIX> as default.
        suffix = _env_suffix(org_id)
        pre_login = existing.get(f"QONTO_LOGIN_{suffix}") or default_login
        pre_secret = existing.get(f"QONTO_SECRET_KEY_{suffix}") or (
            existing.get("QONTO_SECRET_KEY", "") if idx == 1 else ""
        )

        login = questionary.text(
            f"Qonto login slug for {org_id} (e.g. 'acme-1234'):",
            default=pre_login,
        ).ask() or ""
        secret = questionary.password(
            f"Qonto API secret for {org_id}:",
            default=pre_secret,
        ).ask() or ""

        orgs.append(
            {
                "id": org_id,
                "country": country,
                "login": login.strip(),
                "secret": secret.strip(),
            }
        )

        if not questionary.confirm(
            "Add another Qonto org?", default=False
        ).ask():
            break

    return orgs


def _prompt_env(existing: dict[str, str]) -> tuple[dict[str, str], list[dict[str, str]]]:
    def ask(key: str, label: str, secret: bool = False, optional: bool = False) -> str:
        default = existing.get(key, "")
        prompt_fn = questionary.password if secret else questionary.text
        help_text = f"{label}" + (" (optional)" if optional else "")
        answer = prompt_fn(f"{help_text}:", default=default).ask()
        return (answer or "").strip()

    typer.echo()
    orgs = _prompt_orgs(existing)

    typer.echo()
    typer.secho("== Clockify ==", fg="cyan", bold=True)
    clockify_key = ask("CLOCKIFY_API_KEY", "Clockify API key", secret=True)
    clockify_ws = ask("CLOCKIFY_WORKSPACE_ID", "Clockify workspace id")

    typer.echo()
    typer.secho("== Gmail ==", fg="cyan", bold=True)
    gmail_sender = ask("GMAIL_SENDER", "Gmail address that will own the drafts")
    gmail_name = ask(
        "GMAIL_SENDER_NAME",
        "Display name for the email signature",
        optional=True,
    )

    typer.echo()
    typer.secho("== Anthropic (optional) ==", fg="cyan", bold=True)
    anthropic_key = ask(
        "ANTHROPIC_API_KEY",
        "Only needed for LLM-assisted client extraction",
        secret=True,
        optional=True,
    )

    values = {
        "CLOCKIFY_API_KEY": clockify_key,
        "CLOCKIFY_WORKSPACE_ID": clockify_ws,
        "GMAIL_SENDER": gmail_sender,
        "GMAIL_SENDER_NAME": gmail_name,
        "ANTHROPIC_API_KEY": anthropic_key,
    }
    return values, orgs


def _test_qonto_org(org: dict[str, str]) -> tuple[bool, str]:
    try:
        import httpx

        r = httpx.get(
            "https://thirdparty.qonto.com/v2/organization",
            headers={"Authorization": f"{org['login']}:{org['secret']}"},
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json().get("organization", {})
            name = data.get("legal_name") or data.get("name", "?")
            return True, f"org: {name}"
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _test_clockify(env: dict[str, str]) -> tuple[bool, str]:
    try:
        import httpx

        r = httpx.get(
            f"https://api.clockify.me/api/v1/workspaces/{env['CLOCKIFY_WORKSPACE_ID']}",
            headers={"X-Api-Key": env["CLOCKIFY_API_KEY"]},
            timeout=15,
        )
        if r.status_code == 200:
            ws = r.json()
            return True, f"workspace: {ws.get('name', '?')}"
        return False, f"HTTP {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _test_gmail() -> tuple[bool, str]:
    """Check Gmail config. Does NOT trigger an OAuth browser flow on init.

    If `token.json` doesn't exist yet, reports "not authorized yet" instead
    of opening a browser — the user completes OAuth on their first real
    `invoicer mail-draft` run, where the browser popup makes sense.
    """
    creds_path = _credentials_path()
    token_path = get_project_root() / "token.json"
    if not creds_path.exists():
        return False, "credentials.json missing"
    if not token_path.exists():
        return True, "credentials.json present (first mail-draft run will authorize)"
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from googleapiclient.discovery import build  # type: ignore

        creds = Credentials.from_authorized_user_file(
            str(token_path),
            ["https://www.googleapis.com/auth/gmail.modify"],
        )
        if not creds or not creds.valid:
            return True, "token.json present (will refresh on next use)"
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return True, f"authenticated as {profile.get('emailAddress')}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def _test_anthropic(env: dict[str, str]) -> tuple[bool, str]:
    if not env.get("ANTHROPIC_API_KEY"):
        return False, "(skipped — not configured)"
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=env["ANTHROPIC_API_KEY"])
        # Lightweight sanity check: just instantiate and call models.list if available.
        # As a cheap probe we send a 1-token request.
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, f"model: {resp.model}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"


def _explain_google_oauth_setup() -> None:
    typer.echo()
    typer.secho(
        "credentials.json not found. You need a Google Cloud OAuth client.",
        fg="yellow",
        bold=True,
    )
    typer.echo()
    typer.echo("Quick steps (one-time, ~15 minutes):")
    typer.echo("  1. https://console.cloud.google.com/projectcreate  → create a project")
    typer.echo("  2. https://console.cloud.google.com/apis/library/gmail.googleapis.com  → Enable")
    typer.echo("  3. https://console.cloud.google.com/apis/credentials/consent  → 'Internal' user type")
    typer.echo("  4. https://console.cloud.google.com/apis/credentials  → Create OAuth client ID → Desktop app → Download JSON")
    typer.echo()
    typer.echo(f"Save the file as: {_credentials_path()}")
    typer.echo()
    if questionary.confirm(
        "Open the first page (projectcreate) in your browser now?",
        default=True,
    ).ask():
        webbrowser.open("https://console.cloud.google.com/projectcreate")


def run_init() -> None:
    typer.secho("\n==  invoicer — interactive setup  ==\n", fg="green", bold=True)

    project_dir = get_project_root()
    typer.echo(f"Project directory: {project_dir}")
    if not (project_dir / "pyproject.toml").exists() and not (
        project_dir / "invoicer.example.yaml"
    ).exists():
        typer.secho(
            "⚠  This doesn't look like an invoicer project directory. "
            "Run `invoicer init` from the root of your clone, or set "
            "$INVOICER_DIR to point at it.",
            fg="yellow",
        )
        if not questionary.confirm("Continue anyway?", default=False).ask():
            raise typer.Exit(1)
    typer.echo()

    env_path = _env_path()

    # --- env vars ---
    existing = _read_env_file(env_path)
    if existing:
        typer.echo(f"Found existing .env at {env_path} ({len(existing)} keys) — using values as defaults.")
    else:
        typer.echo(f"No .env at {env_path} — let's create one.")
    new_values, new_orgs = _prompt_env(existing)
    if questionary.confirm(
        f"\nWrite these values to {env_path.name}?", default=True
    ).ask():
        _write_env_file(env_path, new_values, new_orgs)
        typer.secho(f"✓ Wrote {env_path}", fg="green")
    else:
        typer.secho("Aborted — .env not written.", fg="yellow")
        raise typer.Exit(1)

    # Reload into process for the connectivity tests
    for k, v in new_values.items():
        if v:
            os.environ[k] = v
    for org in new_orgs:
        suffix = _env_suffix(org["id"])
        if org.get("login"):
            os.environ[f"QONTO_LOGIN_{suffix}"] = org["login"]
        if org.get("secret"):
            os.environ[f"QONTO_SECRET_KEY_{suffix}"] = org["secret"]

    # --- invoicer.yaml ---
    typer.echo()
    yaml_path = _invoicer_yaml_path()
    example_path = _invoicer_example_path()
    if yaml_path.exists():
        typer.echo(f"✓ {yaml_path.name} already exists.")
    elif example_path.exists():
        shutil.copy(example_path, yaml_path)
        typer.secho(
            f"✓ Copied {example_path.name} → {yaml_path.name}",
            fg="green",
        )
        typer.echo(
            f"  Edit {yaml_path.name} to map Clockify projects to Qonto clients."
        )
    else:
        typer.secho(
            f"⚠ Neither {yaml_path.name} nor {example_path.name} found in {project_dir}.",
            fg="yellow",
        )

    # --- connectivity tests ---
    typer.echo()
    typer.secho("== Testing connections ==", fg="cyan", bold=True)

    # One Qonto test per org so the user sees which credentials work.
    for org in new_orgs:
        label = f"Qonto [{org['id']}]".ljust(28)
        typer.echo(f"  {label} ... ", nl=False)
        ok, msg = _test_qonto_org(org)
        if ok:
            typer.secho(f"✓ {msg}", fg="green")
        else:
            typer.secho(f"✗ {msg}", fg="red")

    tests = [
        ("Clockify   ".ljust(28), lambda: _test_clockify(new_values)),
        ("Anthropic  ".ljust(28), lambda: _test_anthropic(new_values)),
    ]
    for label, fn in tests:
        typer.echo(f"  {label} ... ", nl=False)
        ok, msg = fn()
        if ok:
            typer.secho(f"✓ {msg}", fg="green")
        else:
            typer.secho(f"✗ {msg}", fg="red")

    # --- Gmail credentials.json ---
    typer.echo("  Gmail      ... ", nl=False)
    if not _credentials_path().exists():
        typer.secho("✗ credentials.json missing", fg="red")
        _explain_google_oauth_setup()
    else:
        ok, msg = _test_gmail()
        if ok:
            typer.secho(f"✓ {msg}", fg="green")
        else:
            typer.secho(f"✗ {msg}", fg="red")

    # --- invoicer.yaml orgs block hint ---
    if new_orgs:
        typer.echo()
        typer.secho("== invoicer.yaml `orgs:` block ==", fg="cyan", bold=True)
        typer.echo(
            "Your .env now has the per-org Qonto credentials. Make sure "
            "your invoicer.yaml references them via an `orgs:` block. If "
            "it doesn't yet, paste this snippet at the top of the file:\n"
        )
        snippet = ["orgs:"]
        for org in new_orgs:
            suffix = _env_suffix(org["id"])
            snippet += [
                f"  - id: {org['id']}",
                f"    country: {org['country']}",
                f"    login_env: QONTO_LOGIN_{suffix}",
                f"    secret_env: QONTO_SECRET_KEY_{suffix}",
            ]
        typer.secho("\n".join(snippet), fg="yellow")

    typer.echo()
    typer.secho("== Next steps ==", fg="cyan", bold=True)
    typer.echo("  1. Edit invoicer.yaml — add the `orgs:` block above if it isn't there, plus Clockify→Qonto client mappings.")
    typer.echo("  2. Run `invoicer discover` to see Clockify + Qonto inventories.")
    typer.echo("  3. Run `invoicer defaults set` to cache a default org and locale.")
    typer.echo("  4. Run `invoicer draft <project-alias> --month YYYY-MM` to build your first draft.")
    typer.echo()
