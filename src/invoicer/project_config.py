"""Load and resolve invoicer.yaml — orgs, defaults, client map, projects."""

import os
import re

import yaml

from .config import get_project_root


def _normalize(s: str) -> str:
    """Lowercase and strip non-alphanumerics.

    Makes 'All-Safe', 'allsafe', 'ALL SAFE', 'all_safe' all equivalent for matching.
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_yaml() -> dict:
    """Load invoicer.yaml. Raises if the file is missing — use for operations
    that REQUIRE project config (draft, finalize, discover, client lookups)."""
    path = get_project_root() / "invoicer.yaml"
    if not path.exists():
        raise RuntimeError(
            f"{path} not found. Copy invoicer.example.yaml to invoicer.yaml and fill "
            f"in your mappings, or run `invoicer init`. Current project dir: {path.parent}"
        )
    return yaml.safe_load(path.read_text()) or {}


def load_yaml_or_empty() -> dict:
    """Load invoicer.yaml if it exists, else return {}. Use for side-effect-free
    inspections (e.g. `invoicer defaults`) that should degrade gracefully when
    no project config has been set up yet."""
    path = get_project_root() / "invoicer.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def find_projects(query: str) -> list[tuple[str, dict]]:
    """Return all projects whose alias, name or id matches `query`.

    Matching priority (stops at the first tier that produces results):
      1. exact id match
      2. exact alias match (case-insensitive)
      3. exact name match (case-insensitive)
      4. substring match on alias or name (case-insensitive)

    Returns a list of (project_id, project_cfg) tuples. Empty if nothing matches.
    """
    data = load_yaml()
    projects = data.get("projects") or {}
    q = (query or "").strip()
    if not q:
        return []
    qn = _normalize(q)
    # Reject queries that normalize to empty (e.g. "!!!", "...") — substring
    # matching against "" would return every project silently.
    if not qn:
        return []

    # 1. exact id
    if q in projects:
        return [(q, projects[q])]

    # 2. exact normalized alias
    exact_alias = [
        (pid, cfg)
        for pid, cfg in projects.items()
        if _normalize((cfg or {}).get("alias", "")) == qn
    ]
    if exact_alias:
        return exact_alias

    # 3. exact normalized name
    exact_name = [
        (pid, cfg)
        for pid, cfg in projects.items()
        if _normalize((cfg or {}).get("name", "")) == qn
    ]
    if exact_name:
        return exact_name

    # 4. normalized substring on alias or name
    substring = [
        (pid, cfg)
        for pid, cfg in projects.items()
        if qn in _normalize((cfg or {}).get("alias", ""))
        or qn in _normalize((cfg or {}).get("name", ""))
    ]
    return substring


def get_project(project_id: str) -> dict:
    data = load_yaml()
    projects = data.get("projects") or {}
    if project_id not in projects:
        raise RuntimeError(
            f"Project {project_id!r} not in invoicer.yaml. Add it under `projects:`."
        )
    return projects[project_id]


def resolve_qonto_client_id(
    clockify_client_id: str, org_id: str | None = None
) -> str:
    """Look up the Qonto client id for a Clockify client.

    If `org_id` is given and any mapping specifies an `org:` field, only
    mappings for that org are considered. Mappings without an `org:` field
    are treated as org-agnostic and always match — this keeps single-org
    setups from having to annotate every entry.
    """
    data = load_yaml()
    for mapping in data.get("clients") or []:
        if mapping.get("clockify_id") != clockify_client_id:
            continue
        mapping_org = mapping.get("org")
        if mapping_org and org_id and mapping_org != org_id:
            continue
        return mapping["qonto_id"]
    hint = f" for org {org_id!r}" if org_id else ""
    raise RuntimeError(
        f"No Qonto mapping for Clockify client {clockify_client_id!r}{hint}. "
        f"Add it under `clients:` in invoicer.yaml."
    )


# -------- Orgs -------------------------------------------------------------

def list_orgs() -> list[dict]:
    """Return the `orgs:` block from invoicer.yaml, or an empty list.

    Graceful when invoicer.yaml is missing (returns []) — this function
    is called by `_resolve_org` which must work before `invoicer init`
    has been run, e.g. when reading defaults for inspection.
    """
    data = load_yaml_or_empty()
    return list(data.get("orgs") or [])


def get_org(org_id: str) -> dict:
    """Look up one org by id, or raise with a useful message."""
    orgs = list_orgs()
    for o in orgs:
        if o.get("id") == org_id:
            return o
    known = ", ".join(o.get("id", "?") for o in orgs) or "(none defined)"
    raise RuntimeError(
        f"Org {org_id!r} not found in invoicer.yaml `orgs:`. Known: {known}."
    )


def activate_org(org_id: str) -> dict:
    """Set QONTO_LOGIN / QONTO_SECRET_KEY in the process environment from
    the named org's env vars, so downstream qonto.* calls see the right
    credentials. Returns the org dict for callers that need the id.

    Raises if the org doesn't exist or if its referenced env vars are unset.
    """
    org = get_org(org_id)
    login_key = org.get("login_env")
    secret_key = org.get("secret_env")
    if not login_key or not secret_key:
        raise RuntimeError(
            f"Org {org_id!r} is missing `login_env` or `secret_env` in "
            f"invoicer.yaml."
        )
    login_val = os.environ.get(login_key)
    secret_val = os.environ.get(secret_key)
    if not login_val or not secret_val:
        raise RuntimeError(
            f"Env vars {login_key} and/or {secret_key} for org {org_id!r} "
            f"are not set. Add them to your .env file, or run `invoicer init`."
        )
    os.environ["QONTO_LOGIN"] = login_val
    os.environ["QONTO_SECRET_KEY"] = secret_val
    return org


# -------- Defaults ---------------------------------------------------------

def get_defaults() -> dict:
    """Return the `defaults:` block from invoicer.yaml, or {}.

    Graceful when invoicer.yaml is missing — returns an empty dict so
    `invoicer defaults` can report "no defaults set" instead of
    crashing with a traceback.
    """
    data = load_yaml_or_empty()
    return dict(data.get("defaults") or {})


# -------- orgs: block surgery --------------------------------------------

def render_orgs_block(orgs: list[dict]) -> str:
    """Render an `orgs:` block from a list of org dicts. Each org must have
    id / country / login_env / secret_env keys. Output is YAML-valid and
    indented so it drops into invoicer.yaml as a top-level block.
    """
    if not orgs:
        return ""
    lines = ["orgs:"]
    for o in orgs:
        lines.append(f"  - id: {o['id']}")
        lines.append(f"    country: {o['country']}")
        lines.append(f"    login_env: {o['login_env']}")
        lines.append(f"    secret_env: {o['secret_env']}")
    return "\n".join(lines) + "\n"


def _find_orgs_block(lines: list[str]) -> tuple[int, int] | None:
    """Return (start, end) half-open line range of the top-level `orgs:`
    block, or None if not present. Matches identically to _find_defaults_block
    in defaults.py but for the `orgs:` prefix.
    """
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped == "orgs:" or stripped.startswith("orgs:"):
            if line.startswith(" ") or line.startswith("\t"):
                continue
            end = i + 1
            for j in range(i + 1, len(lines)):
                peek = lines[j]
                if peek.strip() == "":
                    end = j + 1
                    continue
                if peek.startswith(" ") or peek.startswith("\t") or peek.startswith("-"):
                    end = j + 1
                    continue
                break
            return (i, end)
    return None


def write_orgs_block(orgs: list[dict]) -> None:
    """Insert or replace the `orgs:` block in invoicer.yaml with the given
    list, preserving the rest of the file. Caller is responsible for asking
    the user to confirm before calling — this function writes unconditionally.

    Raises FileNotFoundError if invoicer.yaml doesn't exist.
    """
    path = get_project_root() / "invoicer.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `invoicer init` from your project "
            f"directory first, or copy invoicer.example.yaml to invoicer.yaml."
        )
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    found = _find_orgs_block(lines)
    block = render_orgs_block(orgs)

    if found is None:
        if not block:
            return
        # Insert at the top of the file, after any leading comment block.
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped == "" or stripped == "\n":
                insert_at = i + 1
                continue
            break
        lines = lines[:insert_at] + [block, "\n"] + lines[insert_at:]
    else:
        start, end = found
        if block:
            lines[start:end] = [block]
        else:
            lines[start:end] = []

    path.write_text("".join(lines))


# -------- secrets: block surgery -----------------------------------------

def render_secrets_block(credentials_json_config: dict) -> str:
    """Render the full `secrets:` block with a single `credentials_json`
    key. Today we only support one credential type; the rendering is
    flat enough that more can be added without changing callers.
    """
    if not credentials_json_config:
        return ""
    out = ["secrets:", "  credentials_json:"]
    for k in ("source", "vault", "item", "file"):
        v = credentials_json_config.get(k)
        if v is None or v == "":
            continue
        # Quote vault names with spaces so the YAML stays valid.
        if k == "vault" and (" " in str(v) or ":" in str(v)):
            out.append(f'    {k}: "{v}"')
        else:
            out.append(f"    {k}: {v}")
    return "\n".join(out) + "\n"


def _find_secrets_block(lines: list[str]) -> tuple[int, int] | None:
    """Return (start, end) half-open range of the top-level `secrets:` block,
    or None if not present. Follows the same shape-detection rules as
    `_find_orgs_block` and `defaults._find_defaults_block` — look for the
    key at column 0, then consume indented / blank lines until the next
    top-level key.
    """
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped == "secrets:" or stripped.startswith("secrets:"):
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


def write_secrets_credentials_json_block(
    *, vault: str, item: str, file: str = "credentials.json"
) -> None:
    """Insert or replace the `secrets.credentials_json` block in
    invoicer.yaml so future runs can find it. Preserves comments and
    surrounding content via text surgery. Caller confirms with the user
    before invoking — this writes unconditionally.

    Raises FileNotFoundError if invoicer.yaml doesn't exist.
    """
    path = get_project_root() / "invoicer.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `invoicer init` from your project "
            f"directory first, or copy invoicer.example.yaml to invoicer.yaml."
        )
    text = path.read_text()
    lines = text.splitlines(keepends=True)

    block = render_secrets_block(
        {
            "source": "1password",
            "vault": vault,
            "item": item,
            "file": file,
        }
    )

    found = _find_secrets_block(lines)
    if found is None:
        if not block:
            return
        # Insert after any leading comment block at the top of the file.
        insert_at = 0
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped == "" or stripped == "\n":
                insert_at = i + 1
                continue
            break
        lines = lines[:insert_at] + [block, "\n"] + lines[insert_at:]
    else:
        start, end = found
        if block:
            lines[start:end] = [block]
        else:
            lines[start:end] = []

    path.write_text("".join(lines))
