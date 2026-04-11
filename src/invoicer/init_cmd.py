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


def _detect_qonto_orgs_in_env(existing: dict[str, str]) -> list[dict[str, str]]:
    """Reverse-engineer the list of already-configured Qonto orgs from a
    .env dict. Looks for matching `QONTO_LOGIN_<SUFFIX>` /
    `QONTO_SECRET_KEY_<SUFFIX>` pairs.

    Country code is NOT recoverable from .env alone — it lives in
    invoicer.yaml's orgs: block. Returns dicts with id (derived from
    the suffix, lowercased with underscores as hyphens) and the env var
    names, but no country. Caller fills in country from invoicer.yaml
    or re-prompts if missing.
    """
    import re

    logins = {
        m.group(1): v
        for k, v in existing.items()
        if (m := re.match(r"^QONTO_LOGIN_([A-Z0-9_]+)$", k)) and v
    }
    secrets = {
        m.group(1): v
        for k, v in existing.items()
        if (m := re.match(r"^QONTO_SECRET_KEY_([A-Z0-9_]+)$", k)) and v
    }
    paired_suffixes = sorted(set(logins.keys()) & set(secrets.keys()))
    out: list[dict[str, str]] = []
    for suffix in paired_suffixes:
        org_id = suffix.lower().replace("_", "-")
        out.append(
            {
                "id": org_id,
                "country": "",  # unknown from .env
                "login": logins[suffix],
                "secret": secrets[suffix],
            }
        )
    return out


def _detect_clockify_configured(existing: dict[str, str]) -> bool:
    return bool(
        existing.get("CLOCKIFY_API_KEY") and existing.get("CLOCKIFY_WORKSPACE_ID")
    )


def _detect_gmail_sender_configured(existing: dict[str, str]) -> bool:
    return bool(existing.get("GMAIL_SENDER"))


def _detect_anthropic_configured(existing: dict[str, str]) -> bool:
    return bool(existing.get("ANTHROPIC_API_KEY"))


def _detect_gmail_oauth_ready() -> tuple[bool, str]:
    """Gmail is fully ready only when BOTH credentials.json and a valid
    token.json are present. Reuses _test_gmail() for the validity check.
    """
    if not _credentials_path().exists():
        return False, "credentials.json missing"
    token_path = get_project_root() / "token.json"
    if not token_path.exists():
        return False, "token.json missing — OAuth not yet granted"
    return _test_gmail()


def _ask_keep_edit_add(
    section: str,
    detail: str,
    *,
    add_allowed: bool = False,
) -> str:
    """Return 'keep', 'edit', or 'add'. 'add' only offered when add_allowed.
    """
    choices = [
        questionary.Choice(title="Keep as is (skip this section)", value="keep"),
        questionary.Choice(title="Edit existing values", value="edit"),
    ]
    if add_allowed:
        choices.append(
            questionary.Choice(title="Add another", value="add")
        )
    picked = questionary.select(
        f"{section}: {detail}",
        choices=choices,
    ).ask()
    return picked or "keep"


def _prompt_qonto_orgs(existing: dict[str, str]) -> list[dict[str, str]]:
    """Append-one-or-more prompt loop for Qonto orgs. Returns a list of
    newly entered org dicts (id / country / login / secret). Used on both
    the 'edit' and 'add' branches.
    """
    new_orgs: list[dict[str, str]] = []
    while True:
        idx = len(new_orgs) + 1
        typer.secho(f"-- Qonto org #{idx} --", fg="cyan")
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

        suffix = _env_suffix(org_id)
        pre_login = existing.get(f"QONTO_LOGIN_{suffix}", "")
        pre_secret = existing.get(f"QONTO_SECRET_KEY_{suffix}", "")

        login = questionary.text(
            f"Qonto login slug for {org_id} (e.g. 'acme-1234'):",
            default=pre_login,
        ).ask() or ""
        secret = questionary.password(
            f"Qonto API secret for {org_id}:",
            default=pre_secret,
        ).ask() or ""

        new_orgs.append(
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
    return new_orgs


def _ensure_qonto(
    existing: dict[str, str],
    *,
    force: bool,
) -> tuple[list[dict[str, str]], bool]:
    """Resolve the final list of Qonto orgs this init run will write to .env.
    Returns (orgs, changed). `changed` is True iff the user touched anything
    or no orgs existed before.
    """
    typer.echo()
    typer.secho(f"== Step 2/{len(_WIZARD_STEPS)}: Qonto ==", fg="cyan", bold=True)

    existing_orgs = _detect_qonto_orgs_in_env(existing)

    if existing_orgs and not force:
        # Pre-fill country from invoicer.yaml if available, so we can display
        # a more informative summary.
        yaml_countries = _load_countries_from_invoicer_yaml()
        for o in existing_orgs:
            o["country"] = yaml_countries.get(o["id"], "")

        details = ", ".join(
            f"{o['id']}" + (f" ({o['country']})" if o["country"] else "")
            for o in existing_orgs
        )
        typer.echo(
            f"Found {len(existing_orgs)} existing Qonto org"
            f"{'s' if len(existing_orgs) != 1 else ''}: {details}"
        )
        action = _ask_keep_edit_add(
            "Qonto",
            "what would you like to do?",
            add_allowed=True,
        )
        if action == "keep":
            return existing_orgs, False
        if action == "add":
            new_ones = _prompt_qonto_orgs(existing)
            return existing_orgs + new_ones, True
        # action == "edit" — fall through to full prompt loop below, starting
        # with the existing orgs as defaults
        typer.echo(
            "Walking through each org. Press Ctrl-C at any prompt to abort.\n",
            err=True,
        )
        return _prompt_qonto_orgs(existing), True

    # Fresh install, or --force: run the full prompt loop
    typer.echo(
        "Each Qonto org (legal entity) needs its own API credentials — "
        "Qonto's API is per-org-scoped. If you only invoice from one entity, "
        "just add one org here.\n"
    )
    return _prompt_qonto_orgs(existing), True


def _ensure_clockify(
    existing: dict[str, str],
    *,
    force: bool,
) -> tuple[dict[str, str], bool]:
    typer.echo()
    typer.secho(f"== Step 3/{len(_WIZARD_STEPS)}: Clockify ==", fg="cyan", bold=True)

    if _detect_clockify_configured(existing) and not force:
        ws = existing.get("CLOCKIFY_WORKSPACE_ID", "?")
        typer.echo(f"Found existing Clockify config (workspace id: {ws})")
        action = _ask_keep_edit_add("Clockify", "keep or edit?")
        if action == "keep":
            return (
                {
                    "CLOCKIFY_API_KEY": existing.get("CLOCKIFY_API_KEY", ""),
                    "CLOCKIFY_WORKSPACE_ID": existing.get("CLOCKIFY_WORKSPACE_ID", ""),
                },
                False,
            )

    key = questionary.password(
        "Clockify API key:",
        default=existing.get("CLOCKIFY_API_KEY", ""),
    ).ask() or ""
    ws = questionary.text(
        "Clockify workspace id:",
        default=existing.get("CLOCKIFY_WORKSPACE_ID", ""),
    ).ask() or ""
    return (
        {"CLOCKIFY_API_KEY": key.strip(), "CLOCKIFY_WORKSPACE_ID": ws.strip()},
        True,
    )


def _ensure_gmail_sender(
    existing: dict[str, str],
    *,
    force: bool,
) -> tuple[dict[str, str], bool]:
    typer.echo()
    typer.secho(f"== Step 4a/{len(_WIZARD_STEPS)}: Gmail sender ==", fg="cyan", bold=True)

    if _detect_gmail_sender_configured(existing) and not force:
        sender = existing.get("GMAIL_SENDER", "")
        typer.echo(f"Found existing Gmail sender: {sender}")
        action = _ask_keep_edit_add("Gmail sender", "keep or edit?")
        if action == "keep":
            return (
                {
                    "GMAIL_SENDER": existing.get("GMAIL_SENDER", ""),
                    "GMAIL_SENDER_NAME": existing.get("GMAIL_SENDER_NAME", ""),
                },
                False,
            )

    sender = questionary.text(
        "Gmail address that will own the drafts:",
        default=existing.get("GMAIL_SENDER", ""),
    ).ask() or ""
    name = questionary.text(
        "Display name for the email signature (optional):",
        default=existing.get("GMAIL_SENDER_NAME", ""),
    ).ask() or ""
    return (
        {
            "GMAIL_SENDER": sender.strip(),
            "GMAIL_SENDER_NAME": name.strip(),
        },
        True,
    )


def _ensure_anthropic(
    existing: dict[str, str],
    *,
    force: bool,
) -> tuple[dict[str, str], bool]:
    typer.echo()
    typer.secho(f"== Step 5/{len(_WIZARD_STEPS)}: Anthropic (optional) ==", fg="cyan", bold=True)

    if _detect_anthropic_configured(existing) and not force:
        typer.echo("Found existing Anthropic API key.")
        action = _ask_keep_edit_add("Anthropic", "keep or edit?")
        if action == "keep":
            return ({"ANTHROPIC_API_KEY": existing.get("ANTHROPIC_API_KEY", "")}, False)

    key = questionary.password(
        "Anthropic API key (leave empty if you don't use LLM features):",
        default=existing.get("ANTHROPIC_API_KEY", ""),
    ).ask() or ""
    return ({"ANTHROPIC_API_KEY": key.strip()}, True)


def _load_countries_from_invoicer_yaml() -> dict[str, str]:
    """Return {org_id: country} from invoicer.yaml's orgs: block, or {}."""
    from . import project_config

    out: dict[str, str] = {}
    for org in project_config.list_orgs():
        oid = org.get("id")
        country = org.get("country")
        if oid and country:
            out[oid] = country
    return out


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


_WIZARD_STEPS = [
    "Verify prerequisites (uv, git, optionally 1Password CLI)",
    "Qonto API credentials (per legal entity)",
    "Clockify API key + workspace",
    "Gmail sender + OAuth (via 1Password if available)",
    "Anthropic API key (optional, for AI-assisted client add)",
    "Test every connection",
]


def _print_welcome_panel() -> None:
    """Rich panel at the top of run_init listing every step the user is
    about to go through, so they have a map of the journey before answering
    any prompts."""
    from rich.console import Console
    from rich.panel import Panel

    lines = [
        f"[bold green]invoicer setup wizard[/bold green]  ·  "
        f"{len(_WIZARD_STEPS)} steps",
        "",
        "This wizard will walk you through:",
        "",
    ]
    for i, step in enumerate(_WIZARD_STEPS, start=1):
        lines.append(f"  [cyan]{i}.[/cyan] {step}")
    lines += [
        "",
        "[dim]Ctrl-C at any prompt to abort — nothing is written until "
        "you confirm.[/dim]",
        "",
        "[dim]Re-running this command is safe: it detects what's already "
        "configured and asks[/dim]",
        "[dim]per-section whether to keep, edit, or add.[/dim]",
    ]
    Console().print(
        Panel(
            "\n".join(lines),
            border_style="green",
            padding=(1, 2),
        )
    )


def _check_prerequisites() -> None:
    """Check that the commands invoicer depends on are on PATH. Non-blocking —
    missing tools just produce a warning with install hints, because:
    - `op` is optional (only needed for the 1Password credentials path)
    - `git` and `uv` are needed for `invoicer update` but not for init itself
    - a user on a fresh CI image might legitimately not have some of them

    Called from run_init() as Step 1 of the wizard.
    """
    import shutil

    typer.echo()
    typer.secho(f"== Step 1/{len(_WIZARD_STEPS)}: Prerequisites ==", fg="cyan", bold=True)

    checks = [
        ("uv", "https://docs.astral.sh/uv/getting-started/installation/",
         "required for `invoicer update` (reinstall the tool)"),
        ("git", "https://git-scm.com/downloads",
         "required for `invoicer update` (pull new versions)"),
        ("op", "https://developer.1password.com/docs/cli/get-started/",
         "optional — lets `invoicer init` fetch credentials.json from 1Password"),
    ]
    for name, url, why in checks:
        if shutil.which(name):
            typer.secho(f"  ✓ {name:<4}", fg="green", nl=False)
            typer.echo(f"  {why}")
        else:
            typer.secho(f"  ✗ {name:<4}", fg="yellow", nl=False)
            typer.echo(f"  {why}")
            typer.echo(f"    install: {url}", err=True)

    typer.echo(
        "\n(Missing tools aren't blockers — the wizard will offer "
        "fallback paths when needed.)",
        err=True,
    )


def _setup_1password_credentials_interactively() -> bool:
    """Interactive 1Password onboarding flow, triggered when init detects
    credentials.json is missing AND invoicer.yaml has no `secrets:` block.

    Steps:
      1. Preflight — check `op` is installed and authenticated (clean
         install / sign-in hints otherwise).
      2. Prompt for the vault name. If we can enumerate vaults via
         `op vault list`, show them as a picker; otherwise free text.
      3. Prompt for the item name (default: invoicer-credentials-json)
         and file field (default: credentials.json).
      4. Run the fetch. Retry with different values on failure (or
         abort the 1P path).
      5. Persist the chosen vault/item/file to invoicer.yaml's `secrets:`
         block so future runs skip this prompt entirely.

    Returns True on success, False on any unrecoverable failure.
    """
    from . import project_config
    from .secrets_vault import (
        VaultError,
        check_op_authenticated,
        check_op_installed,
        fetch_credentials_json,
        list_op_vaults,
    )

    typer.echo()
    typer.secho("== 1Password setup ==", fg="cyan", bold=True)

    try:
        check_op_installed()
        signed_in_as = check_op_authenticated()
    except VaultError as e:
        typer.secho("✗ 1Password CLI not ready:", fg="red")
        typer.echo(str(e), err=True)
        typer.echo(
            "\nFix the above and re-run `invoicer init` to try again.\n"
            "Or pick 'Manual Google Cloud Console setup' from the previous "
            "prompt if you'd rather not use 1Password.",
            err=True,
        )
        return False

    typer.echo(f"Signed in to 1Password as: {signed_in_as}\n")

    vaults = list_op_vaults()
    if vaults:
        choices = [
            questionary.Choice(title=v, value=v) for v in vaults
        ]
        choices.append(
            questionary.Choice(title="Other (type it)", value="__other__")
        )
        vault = questionary.select(
            "Which vault holds your credentials.json?",
            choices=choices,
        ).ask()
        if vault == "__other__":
            vault = questionary.text(
                "Vault name (exact, case-sensitive):"
            ).ask()
    else:
        typer.echo(
            "(Couldn't enumerate your vaults automatically — type the name manually.)",
            err=True,
        )
        vault = questionary.text(
            "Which 1Password vault holds your credentials.json? "
            "(exact, case-sensitive)"
        ).ask()

    if not vault:
        typer.echo("No vault selected. Aborted.", err=True)
        return False

    item = questionary.text(
        "Item name inside the vault:",
        default="invoicer-credentials-json",
    ).ask() or "invoicer-credentials-json"

    file = questionary.text(
        "File field name inside the item:",
        default="credentials.json",
    ).ask() or "credentials.json"

    typer.echo(
        f"\nFetching op://{vault}/{item}/{file} ...", err=True
    )
    try:
        fetch_credentials_json(
            vault=vault,
            item=item,
            file=file,
            output_path=_credentials_path(),
        )
    except VaultError as e:
        typer.secho("✗ Fetch failed:", fg="red")
        typer.echo(str(e), err=True)
        if questionary.confirm(
            "\nTry again with different values?", default=True
        ).ask():
            return _setup_1password_credentials_interactively()
        return False

    typer.secho(
        f"✓ Fetched {_credentials_path().name} from 1Password",
        fg="green",
    )

    # Persist to invoicer.yaml so future runs skip the choice prompt.
    try:
        project_config.write_secrets_credentials_json_block(
            vault=vault, item=item, file=file
        )
        typer.secho(
            "✓ Added `secrets:` block to invoicer.yaml — future runs "
            "will fetch automatically.",
            fg="green",
        )
    except Exception as e:
        typer.echo(
            f"⚠ Could not persist secrets block to invoicer.yaml ({e}). "
            "The fetch worked, but `invoicer init` will ask again next "
            "time. You can add the block manually — see "
            "`invoicer help getting-started`.",
            err=True,
        )

    return True


def _wait_for_credentials_json(timeout_sec: int = 300) -> bool:
    """Poll for credentials.json to appear at the expected path. Shows a
    rich spinner while waiting. Returns True on success, False on
    timeout or Ctrl-C.
    """
    import time

    from rich.console import Console

    path = _credentials_path()
    console = Console()
    deadline = time.monotonic() + timeout_sec
    try:
        with console.status(
            f"[cyan]Waiting for {path.name} to appear at {path.parent}…[/cyan]  "
            "(Ctrl-C to skip for now)",
            spinner="dots",
        ):
            while time.monotonic() < deadline:
                if path.exists():
                    return True
                time.sleep(1)
    except KeyboardInterrupt:
        typer.echo("\nSkipped — come back with `invoicer init` when ready.", err=True)
        return False
    typer.echo(
        f"\nTimed out after {timeout_sec}s waiting for {path.name}. "
        "Come back with `invoicer init` when you've saved it.",
        err=True,
    )
    return False


def _ensure_gmail_oauth(*, force: bool) -> tuple[bool, bool]:
    """Make sure Gmail is fully set up: credentials.json present AND
    token.json valid. Returns (ready, changed).

    - If both files already exist and work, report and return (True, False)
      unless force=True.
    - If credentials.json missing: explain, open browser, poll for file.
    - If credentials.json present but token.json missing/invalid: trigger
      the OAuth flow directly (opens a second browser tab, writes token.json).
    """
    typer.echo()
    typer.secho(f"== Step 4b/{len(_WIZARD_STEPS)}: Gmail OAuth ==", fg="cyan", bold=True)

    ready, msg = _detect_gmail_oauth_ready()
    if ready and not force:
        typer.secho(f"✓ {msg}", fg="green")
        return True, False

    if not _credentials_path().exists():
        # If invoicer.yaml ALREADY declares a secrets block, use it
        # (hard-fail on errors — the user opted in). Otherwise, offer
        # them a three-way interactive choice at this exact moment:
        # 1Password, manual Google Cloud Console, or skip.
        from .secrets_vault import (
            VaultError,
            fetch_credentials_json_from_config,
        )

        try:
            fetched, _msg = fetch_credentials_json_from_config()
        except VaultError as e:
            typer.secho("✗ 1Password fetch failed:", fg="red")
            typer.echo(str(e), err=True)
            typer.echo(
                "\nFix the error above and re-run `invoicer init`. "
                "To switch to manual Google Cloud Console setup instead, "
                "remove the `secrets:` block from invoicer.yaml.",
                err=True,
            )
            return False, False

        if fetched:
            typer.secho(
                f"✓ Fetched {_credentials_path().name} from 1Password",
                fg="green",
            )
        else:
            # No secrets block declared. Propose the 1Password route
            # interactively instead of silently falling back to the
            # 15-minute Google Cloud Console walk. The manual path is
            # still one click away for users who want it (or forkers
            # without 1Password).
            typer.echo(
                f"\n{_credentials_path().name} not found at "
                f"{_credentials_path().parent}.",
                err=True,
            )
            choice = questionary.select(
                "How would you like to set it up?",
                choices=[
                    questionary.Choice(
                        title="Fetch from 1Password  — 30 seconds if you already use 1Password",
                        value="1password",
                    ),
                    questionary.Choice(
                        title="Manual Google Cloud Console setup  — ~15 minutes, 4 steps",
                        value="manual",
                    ),
                    questionary.Choice(
                        title="Skip for now  — come back later with `invoicer init`",
                        value="skip",
                    ),
                ],
            ).ask()

            if choice == "skip" or choice is None:
                typer.echo(
                    "Skipped. Come back with `invoicer init` when you're ready.",
                    err=True,
                )
                return False, False

            if choice == "1password":
                if not _setup_1password_credentials_interactively():
                    return False, False
            else:
                # Manual Google Cloud Console path
                _explain_google_oauth_setup()
                if not _wait_for_credentials_json():
                    return False, False
                typer.secho(
                    f"✓ Found {_credentials_path().name}", fg="green"
                )

    # credentials.json now exists. Trigger the OAuth flow unless we're
    # already authenticated and force wasn't set.
    token_path = get_project_root() / "token.json"
    if token_path.exists() and not force:
        ok, msg = _test_gmail()
        if ok:
            typer.secho(f"✓ {msg}", fg="green")
            return True, False

    typer.echo(
        "Opening a browser for Gmail account selection + consent. "
        "Pick the account that should OWN the invoice drafts — that "
        "mailbox will receive every `invoicer mail-draft`.",
        err=True,
    )
    try:
        from .gmail import _get_credentials

        _get_credentials()  # runs InstalledAppFlow, writes token.json
    except Exception as e:
        typer.secho(f"✗ OAuth flow failed: {e}", fg="red")
        return False, False

    ok, msg = _test_gmail()
    if ok:
        typer.secho(f"✓ {msg}", fg="green")
        return True, True
    typer.secho(f"✗ {msg}", fg="red")
    return False, True


def run_init(*, force: bool = False) -> None:
    """Idempotent interactive setup wizard.

    Walks the user through every piece of config invoicer needs, in a
    numbered sequence with a welcome panel up front. Each section
    detects what's already set and asks Keep/Edit/Add rather than
    forcing a full re-prompt, unless `force=True`. The "Next steps"
    block at the end prints only the delta — sections the user
    actually touched during this run.
    """
    _print_welcome_panel()

    project_dir = get_project_root()
    typer.echo(f"\nProject directory: {project_dir}")
    if force:
        typer.secho(
            "Running with --force: every section will re-prompt.",
            fg="yellow",
        )
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

    # --- Step 1: prerequisites (non-blocking) ---
    _check_prerequisites()

    env_path = _env_path()
    existing = _read_env_file(env_path)
    if existing:
        typer.echo(
            f"\nFound existing .env at {env_path} "
            f"({len(existing)} keys — will skip sections that are already set)."
        )
    else:
        typer.echo(f"\nNo .env at {env_path} — let's create one.")

    # Track which sections the user actually touched, for the delta
    # "Next steps" block at the end.
    touched: set[str] = set()

    # --- Qonto ---
    new_orgs, qonto_changed = _ensure_qonto(existing, force=force)
    if qonto_changed:
        touched.add("qonto")

    # --- Clockify ---
    clockify_values, clockify_changed = _ensure_clockify(existing, force=force)
    if clockify_changed:
        touched.add("clockify")

    # --- Gmail sender (env var only; OAuth comes later) ---
    gmail_values, gmail_sender_changed = _ensure_gmail_sender(existing, force=force)
    if gmail_sender_changed:
        touched.add("gmail_sender")

    # --- Anthropic ---
    anthropic_values, anthropic_changed = _ensure_anthropic(existing, force=force)
    if anthropic_changed:
        touched.add("anthropic")

    # --- Write .env ---
    # Merge the fresh values on top of existing, so we don't clobber
    # anything the user wanted to keep.
    final_values: dict[str, str] = dict(existing)
    final_values.update(clockify_values)
    final_values.update(gmail_values)
    final_values.update(anthropic_values)
    # orgs are written through a separate _write_env_file section so we
    # can restructure them by-org. Strip stale QONTO_LOGIN_* / SECRET_KEY_*
    # entries when the user took the Edit path (they replaced the list).
    if qonto_changed:
        final_values = {
            k: v
            for k, v in final_values.items()
            if not k.startswith("QONTO_LOGIN_") and not k.startswith("QONTO_SECRET_KEY_")
        }

    if touched:
        if questionary.confirm(
            f"\nWrite these values to {env_path.name}?", default=True
        ).ask():
            _write_env_file(env_path, final_values, new_orgs)
            typer.secho(f"✓ Wrote {env_path}", fg="green")
        else:
            typer.secho("Aborted — .env not written.", fg="yellow")
            raise typer.Exit(1)
    else:
        typer.echo(f"\nNothing to write — {env_path.name} already has everything.")

    # Reload into process for the connectivity tests
    for k, v in final_values.items():
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
    if not yaml_path.exists():
        if example_path.exists():
            shutil.copy(example_path, yaml_path)
            typer.secho(
                f"✓ Copied {example_path.name} → {yaml_path.name}",
                fg="green",
            )
            touched.add("invoicer_yaml")
        else:
            typer.secho(
                f"⚠ Neither {yaml_path.name} nor {example_path.name} found in {project_dir}.",
                fg="yellow",
            )

    # --- orgs: block in invoicer.yaml ---
    if yaml_path.exists() and new_orgs:
        from . import project_config

        current_orgs = project_config.list_orgs()
        target_orgs = [
            {
                "id": o["id"],
                "country": o["country"],
                "login_env": f"QONTO_LOGIN_{_env_suffix(o['id'])}",
                "secret_env": f"QONTO_SECRET_KEY_{_env_suffix(o['id'])}",
            }
            for o in new_orgs
        ]
        needs_write = _orgs_blocks_differ(current_orgs, target_orgs)
        if needs_write:
            typer.echo()
            typer.secho(
                "== invoicer.yaml `orgs:` block ==", fg="cyan", bold=True
            )
            typer.echo(
                "The tool can insert the `orgs:` block into invoicer.yaml "
                "for you. Review what it would write:\n"
            )
            typer.secho(
                project_config.render_orgs_block(target_orgs),
                fg="yellow",
            )
            if questionary.confirm(
                f"Write this orgs: block to {yaml_path.name}?",
                default=True,
            ).ask():
                try:
                    project_config.write_orgs_block(target_orgs)
                    typer.secho(
                        f"✓ Updated orgs: block in {yaml_path.name}",
                        fg="green",
                    )
                    touched.add("invoicer_yaml")
                except Exception as e:
                    typer.secho(
                        f"✗ Failed to write orgs block: {e}", fg="red"
                    )
            else:
                typer.echo(
                    "Skipped — you can paste the block above into invoicer.yaml by hand.",
                    err=True,
                )

    # --- connectivity tests ---
    typer.echo()
    typer.secho(f"== Step 6/{len(_WIZARD_STEPS)}: Testing connections ==", fg="cyan", bold=True)

    for org in new_orgs:
        label = f"Qonto [{org['id']}]".ljust(28)
        typer.echo(f"  {label} ... ", nl=False)
        ok, msg = _test_qonto_org(org)
        if ok:
            typer.secho(f"✓ {msg}", fg="green")
        else:
            typer.secho(f"✗ {msg}", fg="red")

    tests = [
        ("Clockify   ".ljust(28), lambda: _test_clockify(final_values)),
        ("Anthropic  ".ljust(28), lambda: _test_anthropic(final_values)),
    ]
    for label, fn in tests:
        typer.echo(f"  {label} ... ", nl=False)
        ok, msg = fn()
        if ok:
            typer.secho(f"✓ {msg}", fg="green")
        else:
            typer.secho(f"✗ {msg}", fg="red")

    # --- Gmail OAuth (credentials.json + token.json, with polling) ---
    gmail_oauth_ready, gmail_oauth_changed = _ensure_gmail_oauth(force=force)
    if gmail_oauth_changed:
        touched.add("gmail_oauth")

    # --- Inline: save default org? ---
    from . import defaults as defaults_mod
    from . import project_config

    current_defaults = defaults_mod.read_all()
    if (
        "qonto" in touched
        and new_orgs
        and "org" not in current_defaults
        and yaml_path.exists()
    ):
        typer.echo()
        chosen_default = None
        if len(new_orgs) == 1:
            chosen_default = new_orgs[0]["id"]
            if questionary.confirm(
                f"Save {chosen_default!r} as the default org for future runs?",
                default=True,
            ).ask():
                try:
                    defaults_mod.set_default("org", chosen_default)
                    typer.secho(
                        f"✓ defaults.org = {chosen_default}", fg="green"
                    )
                    touched.add("defaults")
                except Exception as e:
                    typer.secho(
                        f"✗ Could not save default org: {e}", fg="red"
                    )
        else:
            picked = questionary.select(
                "Save one of these as the default org for future runs?",
                choices=[
                    *(
                        questionary.Choice(title=o["id"], value=o["id"])
                        for o in new_orgs
                    ),
                    questionary.Choice(title="(skip, I'll decide later)", value=""),
                ],
            ).ask()
            if picked:
                try:
                    defaults_mod.set_default("org", picked)
                    typer.secho(f"✓ defaults.org = {picked}", fg="green")
                    touched.add("defaults")
                except Exception as e:
                    typer.secho(
                        f"✗ Could not save default org: {e}", fg="red"
                    )

    # --- Delta "Next steps" ---
    _print_next_steps(touched, new_orgs, project_config)


def _orgs_blocks_differ(current: list[dict], target: list[dict]) -> bool:
    """Return True iff the current orgs block doesn't match the target
    list by id/country/login_env/secret_env. Also True when current is
    empty but target isn't.
    """
    if not current:
        return bool(target)
    if len(current) != len(target):
        return True
    keyed_current = {o.get("id"): o for o in current}
    for t in target:
        c = keyed_current.get(t["id"])
        if not c:
            return True
        for k in ("country", "login_env", "secret_env"):
            if (c.get(k) or "") != (t.get(k) or ""):
                return True
    return False


def _print_next_steps(
    touched: set[str], new_orgs: list[dict], project_config_mod
) -> None:
    """Print only the delta — what actually changed and what the user
    should do next, given that delta. If nothing was touched, print
    a single-line "you're set" message.
    """
    typer.echo()
    typer.secho("== Next steps ==", fg="cyan", bold=True)

    if not touched:
        typer.echo(
            "  Nothing changed. Run `invoicer draft <project-alias> "
            "--month YYYY-MM` when you're ready."
        )
        return

    steps: list[str] = []
    if "qonto" in touched:
        if new_orgs:
            first = new_orgs[0]["id"]
            steps.append(
                f"Run `invoicer discover --org {first}` to list Clockify + "
                f"Qonto inventories and fill in your `clients:` / `projects:` "
                f"mapping in invoicer.yaml."
            )
    if "gmail_oauth" in touched:
        steps.append(
            "Gmail is authorized. Your first `invoicer mail-draft` will use "
            "this mailbox — review the draft in Gmail web UI before sending."
        )
    if "invoicer_yaml" in touched:
        steps.append(
            "Edit `invoicer.yaml` to add Clockify→Qonto client mappings and "
            "project billing terms (rate, VAT, alias). See `invoicer help workflow`."
        )

    # Always end with the flow tip
    steps.append(
        "When you're ready: `invoicer draft <project-alias> --month YYYY-MM`"
    )

    for i, s in enumerate(steps, start=1):
        typer.echo(f"  {i}. {s}")
    typer.echo()
