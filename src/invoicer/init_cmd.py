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


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Qonto Business API (https://thirdparty.qonto.com)",
        f"QONTO_LOGIN={values.get('QONTO_LOGIN', '')}",
        f"QONTO_SECRET_KEY={values.get('QONTO_SECRET_KEY', '')}",
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


def _prompt_env(existing: dict[str, str]) -> dict[str, str]:
    def ask(key: str, label: str, secret: bool = False, optional: bool = False) -> str:
        default = existing.get(key, "")
        prompt_fn = questionary.password if secret else questionary.text
        help_text = f"{label}" + (" (optional)" if optional else "")
        answer = prompt_fn(f"{help_text}:", default=default).ask()
        return (answer or "").strip()

    typer.echo()
    typer.secho("== Qonto ==", fg="cyan", bold=True)
    qonto_login = ask("QONTO_LOGIN", "Qonto org slug (e.g. 'acme-1234')")
    qonto_secret = ask("QONTO_SECRET_KEY", "Qonto API secret", secret=True)

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

    return {
        "QONTO_LOGIN": qonto_login,
        "QONTO_SECRET_KEY": qonto_secret,
        "CLOCKIFY_API_KEY": clockify_key,
        "CLOCKIFY_WORKSPACE_ID": clockify_ws,
        "GMAIL_SENDER": gmail_sender,
        "GMAIL_SENDER_NAME": gmail_name,
        "ANTHROPIC_API_KEY": anthropic_key,
    }


def _test_qonto(env: dict[str, str]) -> tuple[bool, str]:
    try:
        import httpx

        login = env["QONTO_LOGIN"]
        secret = env["QONTO_SECRET_KEY"]
        r = httpx.get(
            "https://thirdparty.qonto.com/v2/organization",
            headers={"Authorization": f"{login}:{secret}"},
            timeout=15,
        )
        if r.status_code == 200:
            org = r.json().get("organization", {})
            return True, f"org: {org.get('legal_name') or org.get('name', '?')}"
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
    new_values = _prompt_env(existing)
    if questionary.confirm(
        f"\nWrite these values to {env_path.name}?", default=True
    ).ask():
        _write_env_file(env_path, new_values)
        typer.secho(f"✓ Wrote {env_path}", fg="green")
    else:
        typer.secho("Aborted — .env not written.", fg="yellow")
        raise typer.Exit(1)

    # Reload into process for the connectivity tests
    for k, v in new_values.items():
        if v:
            os.environ[k] = v

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

    tests = [
        ("Qonto      ", lambda: _test_qonto(new_values)),
        ("Clockify   ", lambda: _test_clockify(new_values)),
        ("Anthropic  ", lambda: _test_anthropic(new_values)),
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

    typer.echo()
    typer.secho("== Next steps ==", fg="cyan", bold=True)
    typer.echo("  1. Edit invoicer.yaml to add your Clockify→Qonto client mappings.")
    typer.echo("  2. Run `invoicer discover` to see Clockify + Qonto inventories.")
    typer.echo("  3. Run `invoicer draft <project-alias> --month YYYY-MM` to build your first draft.")
    typer.echo()
