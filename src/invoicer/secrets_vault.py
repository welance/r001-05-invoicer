"""1Password-backed secret distribution for the Gmail OAuth client file.

Why this module exists
----------------------
`credentials.json` (the Desktop-app OAuth client for Google) is the same
for every colleague using the same Google Cloud project. Google even says
the "client_secret" inside isn't actually a cryptographic secret for
installed apps — it's a well-known identifier of the OAuth client. So we
want one source of truth, shared across the team, rotatable in one place,
never in git.

1Password fits: put the file in a shared vault, each colleague's `op` CLI
auths against their own 1P account and can fetch it iff they're a vault
member. No identity sniffing in the tool, no hardcoded domains — the auth
boundary lives in 1Password.

What this module does NOT do
----------------------------
- It never logs or echoes the contents of `credentials.json`. Subprocess
  stdout is written directly to the output file; only stderr is shown
  to the user (for error diagnostics).
- It never catches `op`'s error output silently. Every failure path
  raises `VaultError` with a concrete recovery hint. Swallowing these
  would turn "vault access revoked" into a mysterious "OAuth flow
  failed" — a much worse debugging experience.
- It never caches credentials in memory. The fetched bytes touch one
  local variable and get written to disk, same as any other file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .config import get_project_root
from .project_config import load_yaml_or_empty


class VaultError(RuntimeError):
    """Raised when anything in the 1Password fetch path fails. The message
    is user-facing — it lands directly in the CLI's error output, so it
    must be actionable.
    """


_INSTALL_HINT = (
    "  macOS:   brew install 1password-cli\n"
    "  Windows: https://app-updates.agilebits.com/product_history/CLI2\n"
    "  Linux:   https://developer.1password.com/docs/cli/get-started/\n"
    "Then enable the desktop-app integration: 1Password app →\n"
    "Settings → Developer → check \"Integrate with 1Password CLI\"."
)


def check_op_installed() -> None:
    """Raise VaultError if the 1Password CLI isn't on PATH."""
    if shutil.which("op") is None:
        raise VaultError(
            "1Password CLI ('op') is not installed.\n" + _INSTALL_HINT
        )


def check_op_authenticated() -> str:
    """Return the email of the currently signed-in 1Password account, or
    raise VaultError if no session is active. Uses `op whoami --format=json`.
    """
    try:
        result = subprocess.run(
            ["op", "whoami", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as e:
        raise VaultError(
            "1Password CLI ('op') vanished between checks. "
            "Is your PATH unstable?"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise VaultError(
            "`op whoami` timed out after 10s. The 1Password desktop app "
            "may be unresponsive — check its status and try again."
        ) from e

    if result.returncode != 0:
        raise VaultError(
            "Not signed in to 1Password CLI.\n"
            "  Option A (recommended): open the 1Password desktop app →\n"
            "    Settings → Developer → check \"Integrate with 1Password CLI\".\n"
            "    Your next `op` command will biometric-prompt and succeed.\n"
            "  Option B: run `op signin` in your shell first.\n\n"
            f"op whoami stderr:\n{result.stderr.strip() or '(empty)'}"
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "(signed in — account info unavailable)"
    return data.get("email") or "(signed in — email field missing)"


def fetch_credentials_json(
    *,
    vault: str,
    item: str,
    file: str,
    output_path: Path,
) -> None:
    """Fetch a file from 1Password via `op read` and write it to output_path.

    Uses the secret-reference URI form:
        op read "op://<vault>/<item>/<file>"

    Requires the authenticated 1Password account to be a member of the
    named vault. Raises VaultError on any failure — caller shows the
    message directly to the user.
    """
    check_op_installed()
    signed_in_as = check_op_authenticated()

    ref = f"op://{vault}/{item}/{file}"
    try:
        result = subprocess.run(
            ["op", "read", ref],
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as e:
        raise VaultError(
            f"`op read` timed out after 30s while fetching {ref}.\n"
            f"Signed in as: {signed_in_as}\n"
            "This is unusual — check your network and the 1Password desktop "
            "app's connectivity status."
        ) from e

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise VaultError(
            f"Failed to fetch {ref}\n"
            f"  Signed in as: {signed_in_as}\n"
            f"  op stderr:    {stderr or '(empty)'}\n"
            "\n"
            "Common causes, in order of likelihood:\n"
            f"  1. You are not a member of the vault {vault!r}. Ask the\n"
            "     1Password admin (welance workspace) to add you.\n"
            f"  2. The item or vault name in `invoicer.yaml` has a typo —\n"
            "     1Password is case-sensitive and exact-match.\n"
            f"  3. The field name inside the item is not {file!r}. Open the\n"
            "     item in 1Password and verify the file attachment name.\n"
        )

    # stdout is raw bytes — never log or echo. Write straight to disk.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(result.stdout)


def list_op_vaults() -> list[str]:
    """Return the names of 1Password vaults the current `op` session can
    see. Used by `invoicer init` to offer an interactive picker for the
    vault name. Returns an empty list if `op` isn't installed, isn't
    authenticated, or the command fails for any reason — callers fall
    back to free-text input.

    Never raises — this is a best-effort UX helper, not a required path.
    """
    if shutil.which("op") is None:
        return []
    try:
        result = subprocess.run(
            ["op", "vault", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    names: list[str] = []
    for entry in data:
        if isinstance(entry, dict):
            name = entry.get("name")
            if name and isinstance(name, str):
                names.append(name)
    return names


def fetch_credentials_json_from_config() -> tuple[bool, str]:
    """Read `secrets.credentials_json` from invoicer.yaml and fetch the
    file if configured. Returns (fetched, message).

    - (False, reason): no secrets block in config — caller can fall back
      to a different path (e.g. the manual Google Cloud Console walk).
    - (True, description): credentials.json is now at the expected local
      path, ready for OAuth.

    Raises VaultError if the config IS present but the fetch fails — this
    is a hard error because the user explicitly opted into 1Password and
    would not expect a silent fallback to a different setup path.
    """
    data = load_yaml_or_empty()
    secrets = data.get("secrets") or {}
    creds_config = secrets.get("credentials_json") or {}
    source = creds_config.get("source")

    if not source:
        return False, "no `secrets.credentials_json` block in invoicer.yaml"
    if source != "1password":
        raise VaultError(
            f"Unsupported secrets source {source!r}. "
            "Only 'source: 1password' is implemented today."
        )

    vault = creds_config.get("vault")
    item = creds_config.get("item")
    file = creds_config.get("file", "credentials.json")
    if not vault or not item:
        raise VaultError(
            "`secrets.credentials_json` must declare both `vault` and "
            "`item` in invoicer.yaml. See `invoicer help getting-started`."
        )

    output_path = get_project_root() / "credentials.json"
    fetch_credentials_json(
        vault=vault, item=item, file=file, output_path=output_path
    )
    return True, (
        f"Fetched {file} from 1Password vault {vault!r} "
        f"item {item!r} → {output_path}"
    )
