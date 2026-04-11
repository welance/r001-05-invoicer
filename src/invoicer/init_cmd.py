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

_REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = _REPO_ROOT / ".env"
ENV_EXAMPLE_PATH = _REPO_ROOT / ".env.example"
INVOICER_YAML_PATH = _REPO_ROOT / "invoicer.yaml"
INVOICER_EXAMPLE_PATH = _REPO_ROOT / "invoicer.example.yaml"
CREDENTIALS_PATH = _REPO_ROOT / "credentials.json"


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
        "# Optional: Anthropic for `invoicer client extract` / `client add`",
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
    if not CREDENTIALS_PATH.exists():
        return False, "credentials.json missing"
    try:
        from .gmail import _get_credentials  # type: ignore

        creds = _get_credentials()
        from googleapiclient.discovery import build  # type: ignore

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
    typer.echo(f"Save the file as: {CREDENTIALS_PATH}")
    typer.echo()
    if questionary.confirm(
        "Open the first page (projectcreate) in your browser now?",
        default=True,
    ).ask():
        webbrowser.open("https://console.cloud.google.com/projectcreate")


def run_init() -> None:
    typer.secho("\n==  invoicer — interactive setup  ==\n", fg="green", bold=True)

    # --- env vars ---
    existing = _read_env_file(ENV_PATH)
    if existing:
        typer.echo(f"Found existing .env ({len(existing)} keys) — using values as defaults.")
    else:
        typer.echo("No .env found — let's create one.")
    new_values = _prompt_env(existing)
    if questionary.confirm(
        f"\nWrite these values to {ENV_PATH.name}?", default=True
    ).ask():
        _write_env_file(ENV_PATH, new_values)
        typer.secho(f"✓ Wrote {ENV_PATH}", fg="green")
    else:
        typer.secho("Aborted — .env not written.", fg="yellow")
        raise typer.Exit(1)

    # Reload into process for the connectivity tests
    for k, v in new_values.items():
        if v:
            os.environ[k] = v

    # --- invoicer.yaml ---
    typer.echo()
    if INVOICER_YAML_PATH.exists():
        typer.echo(f"✓ {INVOICER_YAML_PATH.name} already exists.")
    elif INVOICER_EXAMPLE_PATH.exists():
        shutil.copy(INVOICER_EXAMPLE_PATH, INVOICER_YAML_PATH)
        typer.secho(
            f"✓ Copied {INVOICER_EXAMPLE_PATH.name} → {INVOICER_YAML_PATH.name}",
            fg="green",
        )
        typer.echo(
            f"  Edit {INVOICER_YAML_PATH.name} to map Clockify projects to Qonto clients."
        )
    else:
        typer.secho(
            f"⚠ Neither {INVOICER_YAML_PATH.name} nor {INVOICER_EXAMPLE_PATH.name} found.",
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
    if not CREDENTIALS_PATH.exists():
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
