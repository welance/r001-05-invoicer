"""Cached defaults stored in invoicer.yaml under `defaults:`.

Only *routing* answers are cached here — things the tool would otherwise
re-prompt for on every run (which Qonto org, which locale, etc.).
Confirmation gates (pre-mutation panels, finalize typed confirmation) are
NEVER cached; they must be answered every run. See CLAUDE.md § Safety
invariants.

The writer does targeted text surgery on invoicer.yaml rather than a full
PyYAML round-trip, so the rest of the file (comments, ordering, custom
sections) survives untouched. Users should not put top-level comments
*inside* the `defaults:` block — put them above or below it.
"""

from __future__ import annotations

from .config import get_project_root
from .project_config import get_defaults, list_orgs

KNOWN_KEYS = ("org", "locale", "gmail_sender")
LOCALE_CHOICES = ("it", "en", "de")


def read_all() -> dict:
    """Return the current defaults dict, or {} if none."""
    return get_defaults()


def validate(key: str, value: str) -> None:
    """Raise ValueError if (key, value) is not a legal default."""
    if key not in KNOWN_KEYS:
        raise ValueError(
            f"Unknown default key {key!r}. Known keys: {', '.join(KNOWN_KEYS)}."
        )
    if not value:
        raise ValueError(f"Empty value for {key!r}.")
    if key == "locale" and value not in LOCALE_CHOICES:
        raise ValueError(
            f"locale must be one of {LOCALE_CHOICES}, got {value!r}."
        )
    if key == "org":
        orgs = list_orgs()
        if orgs and not any(o.get("id") == value for o in orgs):
            known = ", ".join(o.get("id", "?") for o in orgs)
            raise ValueError(
                f"Org {value!r} is not declared in invoicer.yaml `orgs:`. "
                f"Known: {known}."
            )


def set_default(key: str, value: str) -> None:
    """Set one default key in invoicer.yaml. Validates first, then writes."""
    validate(key, value)
    current = read_all()
    current[key] = value
    _write_block(current)


def unset_default(key: str) -> None:
    """Remove one default key from invoicer.yaml. No-op if key wasn't set."""
    if key not in KNOWN_KEYS:
        raise ValueError(
            f"Unknown default key {key!r}. Known keys: {', '.join(KNOWN_KEYS)}."
        )
    current = read_all()
    current.pop(key, None)
    _write_block(current)


# -------- internals --------------------------------------------------------


def _find_defaults_block(lines: list[str]) -> tuple[int, int] | None:
    """Return (start, end) half-open line range covering the `defaults:` block,
    or None if not present. The block starts at the line `defaults:` and
    extends through all immediately-following indented or blank lines.
    """
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped == "defaults:" or stripped.startswith("defaults:"):
            # Sanity: must be at column 0 (top-level key), not nested.
            if line.startswith(" ") or line.startswith("\t"):
                continue
            end = i + 1
            for j in range(i + 1, len(lines)):
                peek = lines[j]
                if peek.strip() == "":
                    end = j + 1
                    continue
                if peek.startswith(" ") or peek.startswith("\t"):
                    end = j + 1
                    continue
                break
            return (i, end)
    return None


def _render_block(defaults: dict) -> str:
    """Render a `defaults:` block as text. Empty dict renders as nothing."""
    if not defaults:
        return ""
    rendered = ["defaults:"]
    for k in KNOWN_KEYS:
        if k in defaults:
            rendered.append(f"  {k}: {defaults[k]}")
    return "\n".join(rendered) + "\n"


def _write_block(new_defaults: dict) -> None:
    """Surgically replace (or insert, or delete) the `defaults:` block in
    invoicer.yaml. Preserves every other line of the file verbatim.
    """
    path = get_project_root() / "invoicer.yaml"
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    found = _find_defaults_block(lines)
    block = _render_block(new_defaults)

    if found is None:
        # No existing block. Append one at the end — unless the new block is
        # empty (unsetting the only key on a no-block file), in which case
        # there is nothing to do.
        if not block:
            return
        if lines and not lines[-1].endswith("\n"):
            lines.append("\n")
        if lines:
            lines.append("\n")
        lines.append(block)
    else:
        start, end = found
        if block:
            lines[start:end] = [block]
        else:
            # Empty dict + existing block → drop the block entirely.
            lines[start:end] = []

    path.write_text("".join(lines))
