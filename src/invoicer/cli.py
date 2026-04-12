import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import typer

from . import clockify, qonto
from .config import load_env

app = typer.Typer(help="Clockify → Qonto invoicing tool", no_args_is_help=True)
client_app = typer.Typer(help="Manage Qonto clients", no_args_is_help=True)
defaults_app = typer.Typer(
    help="View and edit cached defaults (org, locale, …) stored in invoicer.yaml",
    no_args_is_help=False,
    invoke_without_command=True,
)
secrets_app = typer.Typer(
    help="Fetch / inspect secrets referenced by invoicer.yaml (1Password, …)",
    no_args_is_help=True,
)
app.add_typer(client_app, name="client")
app.add_typer(defaults_app, name="defaults")
app.add_typer(secrets_app, name="secrets")


def _version_callback(value: bool) -> None:
    if not value:
        return
    from . import __version__

    typer.echo(f"invoicer {__version__}")
    raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Clockify → Qonto invoicing tool."""
    # Callback body intentionally empty — all work happens in `_version_callback`.
    return


def _resolve_org(
    cli_override: str | None,
    project_org: str | None = None,
) -> tuple[str | None, bool]:
    """Pick the active Qonto org for this command invocation.

    Returns (org_id, was_prompted). `org_id` is None when invoicer.yaml has
    no `orgs:` block (legacy single-org mode — caller skips `activate_org`
    and falls back to raw QONTO_LOGIN / QONTO_SECRET_KEY env vars).
    `was_prompted` is True only when we interactively asked the user, so the
    caller can offer to save the pick as the new default.

    Priority chain:
      1. --org CLI flag
      2. project-level `org:` (only for draft)
      3. defaults.org from invoicer.yaml
      4. single-org list → silently pick it
      5. questionary.select prompt
    """
    from . import project_config

    orgs = project_config.list_orgs()
    if cli_override:
        return (cli_override, False)
    if project_org:
        return (project_org, False)
    if not orgs:
        # Legacy single-org mode: no `orgs:` block. Validate that the
        # direct env vars are set so the user gets a clean error rather
        # than a KeyError on first Qonto call.
        if not os.environ.get("QONTO_LOGIN") or not os.environ.get("QONTO_SECRET_KEY"):
            raise RuntimeError(
                "invoicer.yaml has no `orgs:` block and QONTO_LOGIN / "
                "QONTO_SECRET_KEY are not set in .env. Either set them for "
                "single-org mode, or add an `orgs:` block to invoicer.yaml "
                "for multi-org."
            )
        return (None, False)

    defaults = project_config.get_defaults()
    default_org = defaults.get("org")
    if default_org and any(o.get("id") == default_org for o in orgs):
        return (default_org, False)

    if len(orgs) == 1:
        return (orgs[0]["id"], False)

    import questionary

    choices = [
        questionary.Choice(
            title=f"{o['id']}  ({o.get('country', '?')})",
            value=o["id"],
        )
        for o in orgs
    ]
    picked = questionary.select("Which Qonto org?", choices=choices).ask()
    if not picked:
        typer.echo("Aborted — no org selected.", err=True)
        raise typer.Exit(1)
    return (picked, True)


def _maybe_offer_save_as_default(key: str, value: str, prompted: bool) -> None:
    """After a command that had to prompt the user for a routing answer,
    offer to remember it as a default. Never offers if the answer was read
    from config (--org flag, project cfg, existing default, single-org).
    Confirmation gates (pre-mutation panels, finalize typed confirmation)
    are NEVER cached — only routing answers land here.
    """
    if not prompted:
        return
    import questionary

    from . import defaults as defaults_mod

    if not questionary.confirm(
        f"Save {value!r} as the default {key} for future runs?",
        default=False,
    ).ask():
        return
    defaults_mod.set_default(key, value)
    typer.echo(
        f"→ Saved defaults.{key} = {value!r} to invoicer.yaml",
        err=True,
    )


@app.command()
def init(
    force: bool = typer.Option(
        False,
        "--force",
        help="Re-prompt every section even if already configured. Default: skip sections that are already set.",
    ),
) -> None:
    """Interactive first-run setup. Prompts for API keys, tests every connection.

    Idempotent: re-running this against an already-configured project skips
    sections that have existing values and asks per-section whether you want
    to keep, edit, or add. Pass --force to walk through every prompt.
    """
    from .init_cmd import run_init

    run_init(force=force)


@app.command()
def help(
    topic: str = typer.Argument(
        None,
        help="Topic name. Omit to list all topics.",
    ),
) -> None:
    """Show long-form help for a specific topic, or list all topics."""
    from .help_cmd import list_topics, show_topic

    if topic is None or topic == "topics":
        list_topics()
        return
    show_topic(topic)


@defaults_app.callback(invoke_without_command=True)
def _defaults_root(ctx: typer.Context) -> None:
    """Show current defaults when `invoicer defaults` is run with no subcommand."""
    if ctx.invoked_subcommand is not None:
        return
    from . import defaults as defaults_mod
    from .config import get_project_root

    yaml_path = get_project_root() / "invoicer.yaml"
    load_env()
    current = defaults_mod.read_all()

    _ENV_FALLBACKS = {
        "gmail_sender": "GMAIL_SENDER",
    }

    # All .env keys invoicer uses. Secrets are masked; non-secrets shown.
    _ENV_KEYS: list[tuple[str, bool]] = [
        ("CLOCKIFY_API_KEY", True),
        ("CLOCKIFY_WORKSPACE_ID", False),
        ("GMAIL_SENDER", False),
        ("GMAIL_SENDER_NAME", False),
        ("ANTHROPIC_API_KEY", True),
    ]

    from rich.console import Console
    from rich.table import Table

    console = Console()

    if not current and not yaml_path.exists():
        typer.echo(
            f"No invoicer.yaml in {yaml_path.parent} — nothing to show.\n"
            f"Run `invoicer init` to create one, or cd into a directory "
            f"that already has an invoicer.yaml."
        )
        return

    # --- defaults: table ---
    dt = Table(title="invoicer.yaml defaults", title_style="bold green")
    dt.add_column("Key", style="cyan")
    dt.add_column("Value")
    dt.add_column("Source", style="dim")
    for k in defaults_mod.KNOWN_KEYS:
        val = current.get(k)
        if val:
            dt.add_row(k, str(val), "defaults:")
        else:
            env_key = _ENV_FALLBACKS.get(k)
            env_val = os.environ.get(env_key) if env_key else None
            if env_val:
                dt.add_row(k, str(env_val), f".env ({env_key})")
            else:
                dt.add_row(k, "[dim][not-set][/dim]", "")
    console.print(dt)

    # --- .env keys table ---
    # Discover per-org Qonto keys dynamically from invoicer.yaml orgs.
    from . import project_config

    orgs = project_config.list_orgs()
    org_keys: list[tuple[str, bool]] = []
    for o in orgs:
        login_env = o.get("login_env", "")
        secret_env = o.get("secret_env", "")
        if login_env:
            org_keys.append((login_env, True))
        if secret_env:
            org_keys.append((secret_env, True))

    all_env_keys = org_keys + _ENV_KEYS

    et = Table(title=".env keys", title_style="bold green")
    et.add_column("Key", style="cyan")
    et.add_column("Value")
    for env_key, is_secret in all_env_keys:
        val = os.environ.get(env_key)
        if val:
            et.add_row(env_key, "[dim][*******][/dim]" if is_secret else val)
        else:
            et.add_row(env_key, "[dim][not-set][/dim]")
    console.print(et)

    typer.echo(
        "\nDefaults stored in invoicer.yaml under `defaults:`. "
        "Edit via `invoicer defaults set` or `invoicer defaults unset <key>`.\n"
        "Env keys stored in .env. Edit via `invoicer init` or manually.",
        err=True,
    )


@defaults_app.command("set")
def defaults_set(
    ai: bool = typer.Option(
        False,
        "--ai",
        help="Describe the defaults in free-form text; Haiku maps it to keys.",
    ),
) -> None:
    """Edit cached defaults. Walks known keys with prompts, then confirms.

    With --ai, the tool asks for a single free-form description and uses
    Haiku (with an enum-constrained schema so it can't hallucinate org
    names) to propose a set of defaults. You confirm the diff before
    anything is written to invoicer.yaml.
    """
    import questionary

    from . import defaults as defaults_mod
    from . import project_config

    load_env()

    current = defaults_mod.read_all()
    orgs = project_config.list_orgs()
    known_org_ids = [o.get("id", "?") for o in orgs]

    if ai:
        if not known_org_ids:
            typer.echo(
                "AI mode needs at least one org declared in invoicer.yaml "
                "`orgs:`. Add one first, or use `invoicer defaults set` "
                "without --ai.",
                err=True,
            )
            raise typer.Exit(1)

        from .llm import extract_defaults

        typer.echo(
            "Describe the defaults you want in one or two sentences. "
            "Example: \"use the GmbH as default and English locale\".",
            err=True,
        )
        text = questionary.text("Your description:").ask()
        if not text or not text.strip():
            typer.echo("No description given. Aborted.", err=True)
            raise typer.Exit(0)

        typer.echo("Asking Haiku to map that to defaults keys...", err=True)
        proposed = extract_defaults(
            text,
            known_org_ids=known_org_ids,
            locale_choices=list(defaults_mod.LOCALE_CHOICES),
        )
        # Drop empty fields that the model may have filled with ""
        proposed = {k: v for k, v in proposed.items() if v}
    else:
        proposed = {}
        typer.echo("\n== Editing defaults (press Enter to keep the current value) ==\n", err=True)

        if known_org_ids:
            org_choices = [questionary.Choice(title=oid, value=oid) for oid in known_org_ids]
            current_org = current.get("org", "")
            picked_org = questionary.select(
                f"Default org (current: {current_org or '(unset)'}):",
                choices=[*org_choices, questionary.Choice(title="(leave unset)", value="")],
                default=current_org if current_org in known_org_ids else None,
            ).ask()
            if picked_org:
                proposed["org"] = picked_org

        current_locale = current.get("locale", "")
        locale_choices = [
            questionary.Choice(title=loc, value=loc)
            for loc in defaults_mod.LOCALE_CHOICES
        ] + [questionary.Choice(title="(leave unset)", value="")]
        picked_locale = questionary.select(
            f"Default locale (current: {current_locale or '(unset)'}):",
            choices=locale_choices,
            default=current_locale if current_locale in defaults_mod.LOCALE_CHOICES else None,
        ).ask()
        if picked_locale:
            proposed["locale"] = picked_locale

        gmail = questionary.text(
            f"Default gmail_sender (current: {current.get('gmail_sender', '')!r} — empty to leave unset):",
            default=current.get("gmail_sender", ""),
        ).ask()
        if gmail and gmail.strip():
            proposed["gmail_sender"] = gmail.strip()

    # Validate everything before showing the diff.
    for k, v in proposed.items():
        try:
            defaults_mod.validate(k, v)
        except ValueError as e:
            typer.echo(f"Invalid value for {k}: {e}", err=True)
            raise typer.Exit(1) from e

    # Compute diff
    merged = {**current, **proposed}
    changes = [
        (k, current.get(k, ""), merged.get(k, ""))
        for k in defaults_mod.KNOWN_KEYS
        if current.get(k) != merged.get(k)
    ]
    if not changes:
        typer.echo("No changes.", err=True)
        raise typer.Exit(0)

    typer.echo("\n== Proposed changes to invoicer.yaml defaults ==")
    for k, old, new in changes:
        old_s = old or "(unset)"
        new_s = new or "(unset)"
        typer.echo(f"  {k}: {old_s} → {new_s}")

    if not questionary.confirm(
        "Write these changes to invoicer.yaml?", default=False
    ).ask():
        typer.echo("Aborted.", err=True)
        raise typer.Exit(0)

    try:
        for k, _, new in changes:
            if new:
                defaults_mod.set_default(k, new)
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    typer.echo("\n✓ Defaults updated.")


@defaults_app.command("unset")
def defaults_unset(
    key: str = typer.Argument(..., help="Default key to remove (org, locale, gmail_sender)"),
) -> None:
    """Remove one default from invoicer.yaml. No-op if it wasn't set."""
    from . import defaults as defaults_mod

    load_env()

    try:
        defaults_mod.unset_default(key)
    except ValueError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    typer.echo(f"✓ Unset defaults.{key}.")


@secrets_app.command("fetch")
def secrets_fetch(
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite the local credentials.json if it already exists.",
    ),
) -> None:
    """Pull credentials.json from the vault configured in invoicer.yaml.

    Reads the `secrets.credentials_json` block and uses 1Password CLI
    (`op`) to fetch the file. Useful after the admin rotates the Google
    Cloud OAuth client: admin updates the 1Password item, every colleague
    runs `invoicer secrets fetch --force` to pull the new file. Refuses
    to overwrite an existing local credentials.json unless --force is
    passed, so you can't stomp on a manually-placed file by accident.
    """
    from .config import get_project_root
    from .secrets_vault import (
        VaultError,
        fetch_credentials_json_from_config,
    )

    load_env()

    target = get_project_root() / "credentials.json"
    if target.exists() and not force:
        typer.echo(
            f"{target} already exists. Use --force to overwrite.",
            err=True,
        )
        raise typer.Exit(1)

    try:
        fetched, msg = fetch_credentials_json_from_config()
    except VaultError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(1) from e

    if not fetched:
        typer.echo(
            f"Nothing to fetch — {msg}. "
            f"Add a `secrets:` block to invoicer.yaml (see "
            f"`invoicer help getting-started`).",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"✓ {msg}")


@app.command()
def update() -> None:
    """Pull the latest code and reinstall the CLI. One command for non-tech users.

    Runs `git pull --ff-only` and then `uv tool install --editable . --force`
    in the repo that backs this editable install. Refuses to run if the working
    tree has uncommitted changes — fix those first.
    """
    import shutil
    import subprocess

    # Walk up from this file to find the .git that backs the editable install.
    # If invoicer was installed via `uv tool install --editable .`, __file__
    # points inside the user's clone and the walk finds the repo root.
    here = Path(__file__).resolve()
    repo_root: Path | None = None
    for parent in here.parents:
        if (parent / ".git").exists():
            repo_root = parent
            break
    if repo_root is None:
        typer.echo(
            "Could not find a .git directory above the installed source.\n"
            "This command only works for editable installs from a git clone\n"
            "(`uv tool install --editable .`).",
            err=True,
        )
        raise typer.Exit(1)

    for tool in ("git", "uv"):
        if shutil.which(tool) is None:
            typer.echo(
                f"`{tool}` is not on your PATH. Install it first and re-run.",
                err=True,
            )
            raise typer.Exit(1)

    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        typer.echo(f"`git status` failed:\n{status.stderr}", err=True)
        raise typer.Exit(1)
    if status.stdout.strip():
        typer.echo(
            f"You have local changes in {repo_root}:\n{status.stdout}"
            "Commit, stash, or discard them before running `invoicer update`.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(f"→ Updating invoicer in {repo_root}", err=True)
    typer.echo("→ git pull --ff-only", err=True)
    pull = subprocess.run(
        ["git", "-C", str(repo_root), "pull", "--ff-only"],
        check=False,
    )
    if pull.returncode != 0:
        typer.echo(
            "`git pull --ff-only` failed. Your branch may have diverged from "
            "the remote. Ask a developer to help, then re-run `invoicer update`.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo("→ uv tool install --editable . --force", err=True)
    install = subprocess.run(
        ["uv", "tool", "install", "--editable", str(repo_root), "--force"],
        check=False,
    )
    if install.returncode != 0:
        typer.echo("`uv tool install` failed. See the output above.", err=True)
        raise typer.Exit(1)

    typer.echo("\n✓ invoicer updated. Run `invoicer --help` to see what's new.")


@app.command()
def discover(
    org: str = typer.Option(
        None,
        "--org",
        help="Which Qonto org to list clients from. Prompted if you have multiple.",
    ),
) -> None:
    """List Clockify projects/clients and Qonto clients to fill invoicer.yaml."""
    from . import project_config

    load_env()

    typer.echo("\n== Clockify clients ==")
    for cl in clockify.list_clients():
        typer.echo(f"  {cl['id']}  {cl.get('name', '')}")

    typer.echo("\n== Clockify projects ==")
    for p in clockify.list_projects():
        typer.echo(
            f"  {p['id']}  {p.get('name', '')}"
            f"  (client_id={p.get('clientId', '-')})"
        )

    org_id, _ = _resolve_org(cli_override=org)
    if org_id:
        project_config.activate_org(org_id)
        typer.echo(f"\n== Qonto clients ({org_id}) ==")
    else:
        typer.echo("\n== Qonto clients ==")
    for c in qonto.list_clients():
        name = c.get("name") or f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
        typer.echo(f"  {c['id']}  {name}")


@client_app.command("add")
def client_add(
    from_file: Path = typer.Option(
        None, "--from-file", "-f", help="Read source text from a file (AI mode only)"
    ),
    locale: str = typer.Option(
        None,
        "--locale",
        help="Qonto client locale: it, en, de (defaults: defaults.locale in invoicer.yaml, or en).",
    ),
    no_ai: bool = typer.Option(
        False,
        "--no-ai",
        help="Skip LLM extraction; answer stepped field prompts manually.",
    ),
    org: str = typer.Option(
        None,
        "--org",
        help="Which Qonto org to create this client in. Prompted if ambiguous.",
    ),
) -> None:
    """Create a new Qonto client.

    Default: paste company text, Haiku extracts fields, you review, then
    POST /v2/clients. With --no-ai: skip the LLM entirely and answer a
    guided sequence of field prompts instead. To preview without creating,
    decline the final confirmation.
    """
    import questionary

    from . import project_config

    load_env()

    # Resolve org early so any Qonto call hits the right account.
    org_id, org_was_prompted = _resolve_org(cli_override=org)
    if org_id:
        project_config.activate_org(org_id)
        typer.echo(f"→ Qonto org: {org_id}", err=True)

    # Locale resolution: --locale > defaults.locale > "en"
    if locale is None:
        locale = project_config.get_defaults().get("locale", "en")

    if no_ai:
        if from_file:
            typer.echo("--no-ai cannot be combined with --from-file.", err=True)
            raise typer.Exit(1)
        fields: dict = {}
        typer.echo(
            "\n== Manual client entry (no LLM). Press Enter to leave a field empty. ==\n"
        )
    else:
        from .llm import extract_client_fields

        if from_file:
            text = from_file.read_text()
        else:
            typer.echo("Paste client text, then Ctrl-D (EOF) on its own line:", err=True)
            text = sys.stdin.read()
        if not text.strip():
            typer.echo("No input text.", err=True)
            raise typer.Exit(1)

        typer.echo("Extracting fields with Haiku...", err=True)
        fields = extract_client_fields(text)
        typer.echo("\n== Extracted (edit any field, press Enter to accept) ==\n")

    base_keys = [
        "name",
        "country_code",
        "vat_number",
        "tax_identification_number",
        "street_address",
        "city",
        "zip_code",
        "email",
    ]
    for k in base_keys:
        fields[k] = questionary.text(f"{k}:", default=str(fields.get(k, ""))).ask()

    # Italian-specific fields: province_code, pec_email, recipient_code only
    # make sense for IT-seated companies. Skip the prompts otherwise.
    it_only_keys = ["province_code", "pec_email", "recipient_code"]
    if (fields.get("country_code") or "").strip().upper() == "IT":
        for k in it_only_keys:
            fields[k] = questionary.text(f"{k}:", default=str(fields.get(k, ""))).ask()
    else:
        for k in it_only_keys:
            fields.setdefault(k, "")

    if fields.get("confidence_notes"):
        typer.echo(f"\nLLM notes: {fields['confidence_notes']}")

    payload = qonto.build_client_payload(fields, locale=locale)
    from .summary import print_client_summary
    print_client_summary(payload, endpoint="POST https://thirdparty.qonto.com/v2/clients")

    if not questionary.confirm("Create this client in Qonto?", default=False).ask():
        typer.echo("Aborted.", err=True)
        raise typer.Exit(0)

    created = qonto.create_client(payload)
    typer.echo(f"\n✓ Created Qonto client: {created.get('id')}")
    typer.echo(f"  Name: {created.get('name')}")

    if org_id:
        _maybe_offer_save_as_default("org", org_id, org_was_prompted)


@app.command()
def draft(
    project: str = typer.Argument(..., help="Project alias from invoicer.yaml, or raw Clockify project id"),
    month: str = typer.Option(..., help="Billing month, YYYY-MM"),
    purchase_order: str = typer.Option(None, help="Optional PO / reference printed on the invoice"),
    org: str = typer.Option(
        None,
        "--org",
        help="Qonto org id from invoicer.yaml `orgs:`. Overrides project-level and default. "
        "Prompted if ambiguous.",
    ),
) -> None:
    """Create a Qonto draft invoice for a Clockify project + month."""
    from calendar import monthrange
    from datetime import date, datetime, timedelta

    import questionary

    from . import project_config
    from .summary import print_invoice_summary

    load_env()

    # Parse month in the org's local timezone, not UTC. An Italian user logging
    # time at 23:30 Europe/Rome on Jan 31 sits at 22:30 UTC — under a UTC boundary
    # it would be excluded from January.
    tz_name = os.environ.get("INVOICER_TIMEZONE", "Europe/Rome")
    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:
        typer.echo(f"Invalid INVOICER_TIMEZONE {tz_name!r}: {e}", err=True)
        raise typer.Exit(1) from e
    try:
        year, mon = (int(x) for x in month.split("-"))
        period_start = datetime(year, mon, 1, tzinfo=tz)
        period_end = datetime(
            year, mon, monthrange(year, mon)[1], 23, 59, 59, tzinfo=tz
        )
    except (ValueError, IndexError) as e:
        typer.echo(f"Invalid --month {month!r}, expected YYYY-MM.", err=True)
        raise typer.Exit(1) from e

    # Fuzzy search for a project match. If no match, try as a raw Clockify
    # project id and walk the auto-onboarding wizard to register it.
    matches = project_config.find_projects(project)
    if len(matches) == 1:
        project_id, proj_cfg = matches[0]
        name = proj_cfg.get("name", "(unnamed)")
        alias = proj_cfg.get("alias", "")
        typer.echo(
            f"→ Matched: {name}  [{alias}]  ({project_id})", err=True
        )
    elif len(matches) > 1:
        choices = [
            questionary.Choice(
                title=f"{(cfg or {}).get('name', '(unnamed)')}  "
                      f"[{(cfg or {}).get('alias', '')}]",
                value=pid,
            )
            for pid, cfg in matches
        ]
        project_id = questionary.select(
            f"{len(matches)} projects match {project!r}. Pick one:",
            choices=choices,
        ).ask()
        if not project_id:
            typer.echo("Aborted.", err=True)
            raise typer.Exit(1)
        proj_cfg = project_config.get_project(project_id)
    else:
        # No match in invoicer.yaml — treat `project` as a raw Clockify id
        # and try to onboard it via the wizard.
        project_id = project
        proj_cfg = None

    # Resolve and activate Qonto org BEFORE any Qonto API call.
    org_id, org_was_prompted = _resolve_org(
        cli_override=org,
        project_org=(proj_cfg or {}).get("org"),
    )
    org_country: str | None = None
    if org_id:
        org_cfg = project_config.activate_org(org_id)
        org_country = (org_cfg.get("country") or "").upper() or None
        typer.echo(f"→ Qonto org: {org_id}" + (f"  ({org_country})" if org_country else ""), err=True)

    # Clockify → Qonto client resolution (with auto-onboarding wizard)
    typer.echo("Fetching Clockify project...", err=True)
    cp = clockify.get_project(project_id)
    clockify_client_id = cp.get("clientId")
    if not clockify_client_id:
        typer.echo(f"Clockify project {project_id} has no client assigned.", err=True)
        raise typer.Exit(1)

    from . import draft_setup

    # Auto-onboard: register client mapping + project if missing.
    clockify_client_name = ""
    if clockify_client_id:
        try:
            for cl in clockify.list_clients():
                if cl["id"] == clockify_client_id:
                    clockify_client_name = cl.get("name", "")
                    break
        except Exception:
            pass

    qonto_client_id = draft_setup.ensure_client_mapping(
        clockify_client_id=clockify_client_id,
        clockify_client_name=clockify_client_name,
        org_id=org_id,
    )

    if proj_cfg is None:
        # Validate the Qonto client is complete enough for invoicing.
        qc_for_setup = draft_setup.ensure_client_complete(
            qonto_client_id=qonto_client_id,
            org_country=org_country,
        )
        qonto_client_country = (
            (qc_for_setup.get("billing_address") or {}).get("country_code") or ""
        ).upper() or None

        proj_cfg = draft_setup.ensure_project_registered(
            project_id=project_id,
            clockify_project=cp,
            org_country=org_country,
            qonto_client_country=qonto_client_country,
        )

    rate = float(proj_cfg["rate_eur_per_hour"])
    vat_rate = float(proj_cfg.get("vat_rate", 0))
    vat_exemption_reason = proj_cfg.get("vat_exemption_reason")
    rounding = int(proj_cfg.get("rounding_minutes", 15))
    payment_terms_days = int(proj_cfg.get("payment_terms_days", 30))
    description_template = proj_cfg.get(
        "description_template", "Consulting services — {month_name} {year}"
    )
    project_name_cfg = proj_cfg.get("name", project_id)

    typer.echo("Fetching Qonto client...", err=True)
    qc = qonto.get_client(qonto_client_id)
    qonto_client_name = qc.get("name", qonto_client_id)

    typer.echo("Fetching Qonto main bank account...", err=True)
    bank = qonto.get_main_bank_account()
    qonto_org = qonto.get_organization()

    # Aggregate
    typer.echo(
        f"Aggregating Clockify billable hours ({period_start.date()} → {period_end.date()}, "
        f"per-entry ceiling {rounding} min)...",
        err=True,
    )
    agg = clockify.aggregate_billable_hours(
        project_id, period_start, period_end, round_up_minutes=rounding
    )
    if agg["entry_count"] == 0:
        typer.echo("No billable entries in that period. Nothing to invoice.", err=True)
        raise typer.Exit(1)

    billed_hours = agg["billed_hours"]
    subtotal = billed_hours * rate
    vat_amount = subtotal * (vat_rate / 100)
    total = subtotal + vat_amount

    # Dates
    month_names = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    month_name = month_names[mon - 1]
    # description_template is preserved in config for forward compatibility but not
    # rendered onto per-entry line items in v0.1.
    _ = description_template
    issue_date = date.today().isoformat()
    due_date = (date.today() + timedelta(days=payment_terms_days)).isoformat()

    # Build one Qonto line item per Clockify entry (chronological)
    items = []
    for e in agg["entries"]:
        items.append(
            qonto.build_invoice_item(
                title=e["description"],
                description=f"{e['date']} · {e['user']}",
                quantity=e["billed_hours"],
                unit_price_eur=rate,
                vat_rate_pct=vat_rate,
                vat_exemption_reason=vat_exemption_reason,
            )
        )

    # SDI payment_reporting codes belong only on Italian invoices. If the
    # active org is non-IT (or legacy-mode with no declared country), omit
    # the field entirely — German/EU invoices must not carry Italian SDI
    # metadata.
    payment_reporting = (
        {"conditions": "TP02", "method": "MP05"}
        if org_country == "IT"
        else None
    )
    payload = qonto.build_invoice_payload(
        client_id=qonto_client_id,
        issue_date=issue_date,
        due_date=due_date,
        items=items,
        iban=bank["iban"],
        bic=bank.get("bic"),
        beneficiary_name=qonto_org.get("legal_name"),
        purchase_order=purchase_order,
        status="draft",
        payment_reporting=payment_reporting,
    )

    # Pre-mutation summary
    print_invoice_summary(
        client_name=qonto_client_name,
        client_id=qonto_client_id,
        project_name=project_name_cfg,
        period_label=f"{month_name} {year} ({period_start.date()} → {period_end.date()})",
        raw_hours=agg["raw_hours"],
        billed_hours=billed_hours,
        rounding_rule=f"per-entry ceiling {rounding} min",
        unit_price_eur=rate,
        vat_rate_pct=vat_rate,
        vat_exemption_reason=vat_exemption_reason,
        subtotal_eur=subtotal,
        vat_eur=vat_amount,
        total_eur=total,
        status="draft",
        issue_date=issue_date,
        due_date=due_date,
        purchase_order=purchase_order,
        endpoint="POST https://thirdparty.qonto.com/v2/client_invoices",
        line_entries=agg["entries"],
    )

    if not questionary.confirm("Create this DRAFT invoice in Qonto?", default=False).ask():
        typer.echo("Aborted.", err=True)
        raise typer.Exit(0)

    created = qonto.create_client_invoice(payload)
    typer.echo("\n✓ Created Qonto draft invoice")
    typer.echo(f"  id:     {created.get('id')}")
    typer.echo(f"  number: {created.get('number', '(auto)')}")
    typer.echo(f"  status: {created.get('status')}")
    if created.get("invoice_url"):
        typer.echo(f"  url:    {created['invoice_url']}")

    # After a successful draft, if we had to prompt the user for the org,
    # offer to remember it. Only fires when `org_was_prompted` is True.
    if org_id:
        _maybe_offer_save_as_default("org", org_id, org_was_prompted)


@app.command()
def finalize(
    invoice_id: str = typer.Argument(..., help="Qonto invoice id (UUID)"),
    org: str = typer.Option(
        None,
        "--org",
        help="Qonto org the invoice belongs to. Prompted if ambiguous.",
    ),
) -> None:
    """Finalize a Qonto draft invoice. IRREVERSIBLE — locks number, queues SDI."""
    import questionary

    from . import project_config
    from .summary import print_finalize_summary

    load_env()

    org_id, _ = _resolve_org(cli_override=org)
    if org_id:
        project_config.activate_org(org_id)

    inv = qonto.get_invoice(invoice_id)
    current_status = inv.get("status", "")
    if current_status != "draft":
        typer.echo(
            f"Invoice status is {current_status!r}, not 'draft'. Nothing to finalize.",
            err=True,
        )
        raise typer.Exit(1)

    print_finalize_summary(inv)

    # Typed confirmation: the user must retype the invoice number (minus -PROFORMA)
    number = (inv.get("number") or "").replace("-PROFORMA", "")
    if not number:
        typer.echo("Invoice has no number — cannot build typed confirmation.", err=True)
        raise typer.Exit(1)

    typer.echo()
    typed = questionary.text(
        f"Type the invoice number {number!r} exactly, to confirm (anything else aborts):",
    ).ask()
    if typed != number:
        typer.echo("Aborted — confirmation text did not match.", err=True)
        raise typer.Exit(1)

    finalized = qonto.finalize_invoice(invoice_id)
    typer.echo(f"\n✓ Finalized invoice {finalized.get('number')}")
    typer.echo(f"  status:            {finalized.get('status')}")
    typer.echo(f"  einvoicing_status: {finalized.get('einvoicing_status', '(not set)')}")
    typer.echo(f"  invoice_url:       {finalized.get('invoice_url', '')}")


@app.command("mail-draft")
def mail_draft(
    invoice_id: str = typer.Argument(..., help="Qonto invoice id (UUID)"),
    to: str = typer.Option(None, help="Override recipient (default: client.email on Qonto)"),
    cc_self: bool = typer.Option(True, help="CC GMAIL_SENDER for your own paper trail"),
    org: str = typer.Option(
        None,
        "--org",
        help="Qonto org the invoice belongs to. Prompted if ambiguous.",
    ),
) -> None:
    """Download the invoice PDF and create a Gmail draft with it attached.

    Creates a Gmail draft; the user reviews and sends from Gmail web UI.
    """
    import questionary

    from . import project_config
    from .csv_export import build_invoice_csv
    from .gmail import build_invoice_email, create_draft
    from .summary import print_mail_draft_summary

    load_env()

    org_id, _ = _resolve_org(cli_override=org)
    if org_id:
        project_config.activate_org(org_id)

    inv = qonto.get_invoice(invoice_id)
    if inv.get("status") == "draft":
        typer.echo(
            f"Invoice is still a draft. Finalize it first:\n"
            f"  invoicer finalize {invoice_id}",
            err=True,
        )
        raise typer.Exit(1)

    client = inv.get("client", {}) or {}
    recipient = to or client.get("email")
    if not recipient:
        typer.echo(
            "No recipient: invoice client has no email, and --to was not given.",
            err=True,
        )
        raise typer.Exit(1)

    number = inv.get("number", "")
    total_obj = inv.get("total_amount") or {}
    total = total_obj.get("value") if isinstance(total_obj, dict) else total_obj
    issue_date = inv.get("issue_date", "")
    due_date = inv.get("due_date", "")
    client_name = client.get("name", "")

    typer.echo("Downloading invoice PDF from Qonto...", err=True)
    pdf_filename, pdf_bytes = qonto.download_invoice_pdf(invoice_id)

    # CSV derived from the invoice's own line items
    csv_bytes = build_invoice_csv(inv)
    csv_filename = f"timesheet-{number}.csv"

    sender = os.environ["GMAIL_SENDER"]
    sender_name = os.environ.get("GMAIL_SENDER_NAME") or sender.split("@", 1)[0].capitalize()
    subject = f"{client_name} — Invoice {number}"

    # Compute VAT line from actual invoice data — never hardcode.
    vat_obj = inv.get("vat_amount") or {}
    vat_value = vat_obj.get("value") if isinstance(vat_obj, dict) else vat_obj
    try:
        vat_zero = float(vat_value or 0) == 0
    except (TypeError, ValueError):
        vat_zero = False
    vat_line = (
        "VAT is not applied on this invoice.\n"
        if vat_zero
        else "VAT is included as shown on the attached invoice.\n"
    )

    body = (
        f"Hello,\n\n"
        f"Please find attached our invoice {number} for consulting services.\n\n"
        f"- Issue date: {issue_date}\n"
        f"- Due date:   {due_date}\n"
        f"- Amount:     €{total}\n"
        f"- Payment:    bank transfer (IBAN on the invoice)\n\n"
        f"{vat_line}"
        f"\n"
        f"Please let us know if you have any questions.\n\n"
        f"Best regards,\n"
        f"{sender_name}\n"
    )

    cc = sender if cc_self else None
    print_mail_draft_summary(
        sender=sender,
        recipient=recipient,
        cc=cc,
        subject=subject,
        body_preview=body,
        pdf_filename=f"{pdf_filename} + {csv_filename}",
        pdf_size_bytes=len(pdf_bytes) + len(csv_bytes),
    )

    if not questionary.confirm(
        "Create Gmail draft (not send)?", default=True
    ).ask():
        typer.echo("Aborted.", err=True)
        raise typer.Exit(0)

    msg = build_invoice_email(
        sender=sender,
        recipient=recipient,
        cc=cc,
        subject=subject,
        body_text=body,
        attachments=[
            (pdf_filename, "application", "pdf", pdf_bytes),
            (csv_filename, "text", "csv", csv_bytes),
        ],
    )
    draft = create_draft(msg)
    typer.echo("\n✓ Gmail draft created")
    typer.echo(f"  draft_id: {draft.get('id')}")
    typer.echo("  Open Gmail web → Drafts → review → click Send.")


if __name__ == "__main__":
    app()
