import math
import os
import re
from datetime import UTC, datetime

import httpx

BASE = "https://api.clockify.me/api/v1"

_DURATION_RE = re.compile(
    r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?"
)


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE,
        headers={"X-Api-Key": os.environ["CLOCKIFY_API_KEY"]},
        timeout=30,
    )


def _parse_duration_seconds(iso: str | None) -> float:
    if not iso:
        return 0.0
    m = _DURATION_RE.match(iso)
    if not m:
        return 0.0
    h = int(m.group(1) or 0)
    mn = int(m.group(2) or 0)
    s = float(m.group(3) or 0)
    return h * 3600 + mn * 60 + s


def _round_up(seconds: float, step_minutes: int) -> float:
    if step_minutes <= 0:
        return seconds
    step = step_minutes * 60
    return math.ceil(seconds / step) * step


def list_projects() -> list[dict]:
    ws = os.environ["CLOCKIFY_WORKSPACE_ID"]
    with _client() as c:
        r = c.get(
            f"/workspaces/{ws}/projects",
            params={"page-size": 200, "archived": "false"},
        )
        r.raise_for_status()
        return r.json()


def get_project(project_id: str) -> dict:
    ws = os.environ["CLOCKIFY_WORKSPACE_ID"]
    with _client() as c:
        r = c.get(f"/workspaces/{ws}/projects/{project_id}")
        r.raise_for_status()
        return r.json()


def list_clients() -> list[dict]:
    ws = os.environ["CLOCKIFY_WORKSPACE_ID"]
    with _client() as c:
        r = c.get(f"/workspaces/{ws}/clients", params={"page-size": 200})
        r.raise_for_status()
        return r.json()


def _list_users() -> dict[str, str]:
    """Paginated list of workspace users. Returns {user_id: display_name}."""
    ws = os.environ["CLOCKIFY_WORKSPACE_ID"]
    out: dict[str, str] = {}
    page = 1
    with _client() as c:
        while True:
            r = c.get(
                f"/workspaces/{ws}/users",
                params={"page-size": 200, "page": page},
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for u in batch:
                out[u["id"]] = u.get("name") or u.get("email") or u["id"]
            if len(batch) < 200:
                break
            page += 1
    return out


def aggregate_billable_hours(
    project_id: str,
    start: datetime,
    end: datetime,
    *,
    round_up_minutes: int = 15,
) -> dict:
    """Fetch billable entries for (project, [start, end)) and aggregate.

    Per-entry ceiling rounding: each entry is rounded up to the next
    `round_up_minutes` boundary independently before summing.

    Returns:
      {
        "raw_hours": float,
        "billed_hours": float,
        "entries": [
          {"date": "YYYY-MM-DD", "user": str, "description": str,
           "raw_hours": float, "billed_hours": float, "start": iso_str}
        ],  # sorted chronologically
        "by_user": { user_name: {"raw_hours": ..., "billed_hours": ..., "entries": N} },
        "entry_count": int,
      }
    """
    ws = os.environ["CLOCKIFY_WORKSPACE_ID"]
    users = _list_users()
    all_entries: list[dict] = []
    by_user: dict[str, dict] = {}
    total_raw = 0.0
    total_billed = 0.0

    with _client() as c:
        for user_id, user_name in users.items():
            page = 1
            while True:
                r = c.get(
                    f"/workspaces/{ws}/user/{user_id}/time-entries",
                    params={
                        "project": project_id,
                        "start": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "end": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "page": page,
                        "page-size": 200,
                    },
                )
                # Loud failure — never silently skip pages. Under-billing via a
                # transient 429 / 5xx is worse than aborting with a clear error.
                r.raise_for_status()
                entries = r.json()
                if not entries:
                    break
                for e in entries:
                    if not e.get("billable", False):
                        continue
                    ti = e.get("timeInterval", {})
                    raw_sec = _parse_duration_seconds(ti.get("duration"))
                    billed_sec = _round_up(raw_sec, round_up_minutes)
                    start_iso = ti.get("start") or ""
                    date_str = start_iso[:10] if start_iso else ""
                    all_entries.append(
                        {
                            "date": date_str,
                            "start": start_iso,
                            "user": user_name,
                            "description": (e.get("description") or "").strip()
                            or "Unlabeled work",
                            "raw_hours": raw_sec / 3600,
                            "billed_hours": billed_sec / 3600,
                        }
                    )
                    bucket = by_user.setdefault(
                        user_name, {"raw_hours": 0.0, "billed_hours": 0.0, "entries": 0}
                    )
                    bucket["raw_hours"] += raw_sec / 3600
                    bucket["billed_hours"] += billed_sec / 3600
                    bucket["entries"] += 1
                    total_raw += raw_sec / 3600
                    total_billed += billed_sec / 3600
                if len(entries) < 200:
                    break
                page += 1

    all_entries.sort(key=lambda x: x["start"])

    return {
        "raw_hours": total_raw,
        "billed_hours": total_billed,
        "entries": all_entries,
        "by_user": by_user,
        "entry_count": len(all_entries),
    }
