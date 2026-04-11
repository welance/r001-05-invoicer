"""`invoicer help [topic]` — long-form docs rendered in the terminal.

Topics are Markdown files shipped inside the `invoicer.help` package.
Loaded via `importlib.resources` so it works for editable installs and
wheels alike.
"""

from __future__ import annotations

from importlib.resources import files

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

_console = Console()


# Topics are ordered for the overview listing.
TOPICS: dict[str, str] = {
    "getting-started": "First-run setup: prerequisites, `invoicer init`, Gmail OAuth",
    "workflow": "The monthly 4-command invoicing flow",
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


def list_topics() -> None:
    """Print the welcome panel with both the command list AND the topic index."""
    lines: list[str] = [
        "[bold]r001-05-invoicer[/bold] — Clockify → Qonto invoicing CLI",
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
