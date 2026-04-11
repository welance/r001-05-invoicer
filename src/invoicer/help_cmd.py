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


def list_topics() -> None:
    """Print the welcome panel + topic index."""
    body_lines = [
        "[bold]r001-05-invoicer[/bold] — Clockify → Qonto invoicing CLI",
        "",
        "[dim]Long-form help is organized into topics. Run:[/dim]",
        "",
        "  [cyan]invoicer help <topic>[/cyan]",
        "",
        "[bold]Available topics:[/bold]",
        "",
    ]
    for name, description in TOPICS.items():
        body_lines.append(f"  [cyan]{name:<18}[/cyan] {description}")
    body_lines += [
        "",
        "[dim]For per-command help:[/dim]  [cyan]invoicer <command> --help[/cyan]",
        "[dim]For the full README:[/dim]    https://github.com/welance/r001-05-invoicer",
    ]
    _console.print(
        Panel(
            "\n".join(body_lines),
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
