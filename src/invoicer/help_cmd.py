"""`invoicer help [topic]` — long-form docs rendered in the terminal.

Topics are Markdown files shipped inside the `invoicer.help` package.
Loaded via `importlib.resources` so it works for editable installs and
wheels alike.
"""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from . import __version__

_console = Console()

_REPO_URL = "https://github.com/welance/r001-05-invoicer"


def _find_changelog() -> Path | None:
    """Walk up from this module to find CHANGELOG.md. Works for editable
    installs where the source sits inside a git clone; returns None for
    wheel installs (CHANGELOG isn't bundled), so callers must tolerate
    that case.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        cl = parent / "CHANGELOG.md"
        if cl.exists():
            return cl
    return None


def _previous_tag(current: str) -> str | None:
    """Find the version tag published before `current` by parsing
    CHANGELOG.md's `## [X.Y.Z]` headings in file order. Returns None if
    the changelog isn't reachable or has fewer than 2 tagged entries.
    """
    cl = _find_changelog()
    if not cl:
        return None
    try:
        text = cl.read_text(encoding="utf-8")
    except OSError:
        return None
    # Match ## [X.Y.Z] — ignore ## [Unreleased] headings.
    tags = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.MULTILINE)
    if not tags:
        return None
    # Try to find `current` in the list; the next one is the previous tag.
    if current in tags:
        idx = tags.index(current)
        if idx + 1 < len(tags):
            return tags[idx + 1]
        return None
    # Current isn't in the changelog yet (e.g. dev build between releases).
    # Fall back to the most recent tagged entry.
    return tags[0]


# Topics are ordered for the overview listing.
TOPICS: dict[str, str] = {
    "getting-started": "First-run setup: prerequisites, `invoicer init`, Gmail OAuth",
    "workflow": "The monthly 4-command invoicing flow",
    "multi-org": "Invoicing from multiple legal entities (SRL + GmbH) in one install",
    "italy-sdi": "Italian e-invoicing specifics: N-codes, TP/MP codes, SDI lifecycle",
    "troubleshooting": "Common errors and how to recover",
    "security": "Secrets, rotation, Gmail scope honesty, branch protection",
}


def _load_topic(name: str) -> str:
    """Load the markdown content for a topic. Raises FileNotFoundError if unknown."""
    resource = files("invoicer.help") / f"{name}.md"
    return resource.read_text(encoding="utf-8")


def _collect_commands() -> list[tuple[str, str]]:
    """Introspect the Typer app and return (name, short-help) for every command.

    Lazy imports `invoicer.cli` to avoid a circular dependency. Walks both
    top-level `registered_commands` and any sub-typer groups (e.g. `client`).
    """
    from . import cli as cli_module

    app = cli_module.app
    out: list[tuple[str, str]] = []

    def _short_help(fn) -> str:
        if not fn:
            return ""
        doc = (fn.__doc__ or "").strip()
        return doc.split("\n", 1)[0] if doc else ""

    for info in getattr(app, "registered_commands", []) or []:
        name = info.name or (info.callback.__name__ if info.callback else "?")
        help_text = info.help or _short_help(info.callback)
        out.append((name, help_text))

    for group in getattr(app, "registered_groups", []) or []:
        group_name = group.name or "?"
        sub_app = getattr(group, "typer_instance", None)
        if sub_app is None:
            continue
        for info in getattr(sub_app, "registered_commands", []) or []:
            sub_name = info.name or (info.callback.__name__ if info.callback else "?")
            help_text = info.help or _short_help(info.callback)
            out.append((f"{group_name} {sub_name}", help_text))

    out.sort(key=lambda t: t[0])
    return out


def _is_first_run() -> bool:
    """Detect whether the current directory looks like a freshly-cloned
    install that hasn't been through `invoicer init` yet. Used to show a
    prominent call-to-action banner in the help welcome panel.

    Heuristic: if neither .env nor invoicer.yaml exists in the project
    root, we call it first-run. Can't go wrong with a hint — the banner
    is additive, not intrusive.
    """
    try:
        from .config import get_project_root
    except Exception:
        return False
    try:
        root = get_project_root()
    except Exception:
        return False
    return not (root / ".env").exists() and not (root / "invoicer.yaml").exists()


def list_topics() -> None:
    """Print the welcome panel with both the command list AND the topic index."""
    previous = _previous_tag(__version__)
    version_line = f"[bold]r001-05-invoicer v{__version__}[/bold] — Clockify → Qonto invoicing CLI"
    release_url = f"{_REPO_URL}/releases/tag/v{__version__}"
    link_lines = [
        f"[dim]Release notes:[/dim]  {release_url}",
    ]
    if previous:
        compare_url = f"{_REPO_URL}/compare/v{previous}...v{__version__}"
        link_lines.append(
            f"[dim]What changed since v{previous}:[/dim]  {compare_url}"
        )

    lines: list[str] = [
        version_line,
        *link_lines,
    ]
    if _is_first_run():
        lines += [
            "",
            "[bold yellow]📦 New here?[/bold yellow]  "
            "Run [bold cyan]invoicer init[/bold cyan] to set everything "
            "up in one guided wizard.",
            "[dim]No `.env` or `invoicer.yaml` detected in this directory — "
            "this looks like a first-run.[/dim]",
        ]
    lines += [
        "",
        "[bold]Usage:[/bold]  [cyan]invoicer <command> [options][/cyan]",
        "",
        "[bold]Commands:[/bold]",
        "",
    ]
    commands = _collect_commands()
    cmd_width = max((len(n) for n, _ in commands), default=12) + 2
    for name, help_text in commands:
        lines.append(f"  [cyan]{name:<{cmd_width}}[/cyan] {help_text}")

    lines += [
        "",
        "[bold]Help topics:[/bold]   [dim](long-form docs; run [cyan]invoicer help <topic>[/cyan])[/dim]",
        "",
    ]
    topic_width = max((len(n) for n in TOPICS), default=12) + 2
    for name, description in TOPICS.items():
        lines.append(f"  [cyan]{name:<{topic_width}}[/cyan] {description}")

    lines += [
        "",
        "[dim]Per-command usage:[/dim]   [cyan]invoicer <command> --help[/cyan]",
        "[dim]Full README:[/dim]         https://github.com/welance/r001-05-invoicer",
    ]
    _console.print(
        Panel(
            "\n".join(lines),
            title="[bold green]r001-05-invoicer help[/bold green]",
            border_style="green",
        )
    )


def show_topic(name: str) -> None:
    """Render a single topic's markdown content via rich."""
    if name not in TOPICS:
        _console.print(
            f"[red]Unknown topic:[/red] {name!r}. Run [cyan]invoicer help[/cyan] "
            "to see the list."
        )
        raise SystemExit(1)
    try:
        content = _load_topic(name)
    except FileNotFoundError as e:
        _console.print(
            f"[red]Topic file missing:[/red] {e}. This is a packaging bug."
        )
        raise SystemExit(1) from e
    _console.print(Markdown(content))
