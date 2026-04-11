"""Load and resolve invoicer.yaml — project + client mapping."""

import re
from pathlib import Path

import yaml


def _normalize(s: str) -> str:
    """Lowercase and strip non-alphanumerics.

    Makes 'All-Safe', 'allsafe', 'ALL SAFE', 'all_safe' all equivalent for matching.
    """
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def load_yaml() -> dict:
    root = Path(__file__).resolve().parents[2]
    path = root / "invoicer.yaml"
    if not path.exists():
        raise RuntimeError(f"{path} not found")
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


def resolve_qonto_client_id(clockify_client_id: str) -> str:
    data = load_yaml()
    for mapping in data.get("clients") or []:
        if mapping.get("clockify_id") == clockify_client_id:
            return mapping["qonto_id"]
    raise RuntimeError(
        f"No Qonto mapping for Clockify client {clockify_client_id!r}. "
        f"Add it under `clients:` in invoicer.yaml."
    )
