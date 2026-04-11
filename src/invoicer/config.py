"""Environment and project-root resolution.

The tool is designed to be run from the root of a project clone (the directory
containing `.env`, `invoicer.yaml`, `credentials.json`, `token.json`). By default
that's the **current working directory**. Override with `INVOICER_DIR=/path` if
you need to run the tool from elsewhere.

Prior to 0.1.1 the project root was resolved from `Path(__file__).parents[2]`,
which broke for editable installs used across multiple clones — the tool would
silently read and write config in the directory where it was installed from.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Clockify credentials are required for every command that reads time
# entries. Qonto credentials are NOT in this list — in multi-org mode
# (invoicer.yaml `orgs:` block present) they are set per-command by
# project_config.activate_org() from org-scoped .env keys like
# QONTO_LOGIN_SRL / QONTO_SECRET_KEY_SRL. Legacy single-org mode uses
# QONTO_LOGIN / QONTO_SECRET_KEY directly; that is checked in cli._resolve_org
# rather than here so the error messages can cite invoicer.yaml.
REQUIRED_ENV = [
    "CLOCKIFY_API_KEY",
    "CLOCKIFY_WORKSPACE_ID",
]


def get_project_root() -> Path:
    """Resolve the directory that holds .env / invoicer.yaml / credentials.json.

    Resolution order:
      1. `$INVOICER_DIR` env var (if set)
      2. Current working directory (`Path.cwd()`)
    """
    explicit = os.environ.get("INVOICER_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return Path.cwd()


def load_env() -> None:
    env_path = get_project_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing env vars: {missing}. Copy .env.example to .env and fill in, "
            f"and make sure you run `invoicer` from the project directory "
            f"(currently looking in {env_path.parent})."
        )
