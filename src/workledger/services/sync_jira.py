"""Jira sync via the twg CLI."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..config import settings
from ..db import DatabaseError
from ..work_item_models import WorkItemCreate
from . import jira_import, sync_state, work_items

FIELDS = "key,summary,status,issuetype,priority,assignee,parent,created,updated,description"
LIMIT = 200


def _twg_runner(args: list[str]) -> str:
    result = subprocess.run(
        [settings.twg_cli_path, *args],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if result.returncode != 0:
        raise ValueError(f"twg exited {result.returncode}: {(result.stderr or result.stdout)[:500]}")
    return result.stdout


def _stdout_path(output: str) -> Path:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("stdout:"):
            return Path(stripped.split(":", 1)[1].strip().strip('"'))
    raise ValueError("twg output did not contain a stdout file path.")


def _fetch_issues(runner: Callable[[list[str]], str], jql: str, limit: int = LIMIT) -> list[dict]:
    output = runner([
        "jira", "workitem", "query", "--site", settings.sync_jira_site,
        "--jql", jql, "--fields", FIELDS, "--limit", str(limit), "--output", "json",
    ])
    payload = json.loads(_stdout_path(output).read_text(encoding="utf-8-sig"))
    issues = payload.get("data", payload)["issues"]
    if not isinstance(issues, list):
        raise ValueError("twg query result must contain an issues array.")
    return issues


def build_jql(project_keys: list[str], exclude_keys: list[str], window_days: int, imported_keys: list[str]) -> str:
    clauses = [f"project in ({', '.join(project_keys)})"]
    if exclude_keys:
        clauses.append(f"key not in ({', '.join(exclude_keys)})")
    scope = ["assignee = currentUser()", f"updated >= -{window_days}d"]
    if imported_keys:
        scope.append(f"key in ({', '.join(imported_keys)})")
    clauses.append("(" + " OR ".join(scope) + ")")
    return " AND ".join(clauses) + " ORDER BY updated DESC"


def _imported_keys(conn: sqlite3.Connection, project_keys: list[str]) -> list[str]:
    likes = " OR ".join("jira_key LIKE ?" for _ in project_keys)
    rows = conn.execute(
        f"SELECT DISTINCT jira_key FROM work_events "
        f"WHERE jira_key IS NOT NULL AND source_agent='jira-import' AND ({likes})",
        [f"{key}-%" for key in project_keys],
    ).fetchall()
    return sorted(row["jira_key"] for row in rows)


def _my_account_id(conn: sqlite3.Connection, runner) -> str | None:
    cached = sync_state.get_states(conn).get("jira", {}).get("detail", {}).get("my_account_id")
    if cached:
        return cached
    keys = [k.strip().upper() for k in settings.sync_jira_projects.split(",") if k.strip()]
    issues = _fetch_issues(runner, f"project in ({', '.join(keys)}) AND assignee = currentUser()", limit=1)
    if issues:
        return (issues[0].get("assignee") or {}).get("accountId")
    return None


def _stage_for(status: dict) -> str | None:
    category = (status.get("statusCategory") or {}).get("key")
    name = (status.get("name") or "").lower()
    if category == "indeterminate":
        if any(word in name for word in ("acceptance", "verification", "review")):
            return "verification"
        return "active"
    return None


def _auto_work_items(conn, issues, previous, my_account_id) -> int:
    if not my_account_id:
        return 0
    created = 0
    for issue in issues:
        key = issue["key"].strip().upper()
        if (issue.get("assignee") or {}).get("accountId") != my_account_id:
            continue
        status = issue.get("status") or {}
        category = (status.get("statusCategory") or {}).get("key")
        stage = _stage_for(status)
        if category == "done":
            prev = previous.get(key)
            if prev is None or jira_import.is_done(prev.get("status_category"), prev.get("status")):
                continue
            stage = "done"
        if stage is None:
            continue
        if conn.execute("SELECT 1 FROM work_items WHERE jira_key=?", (key,)).fetchone():
            continue
        event = conn.execute(
            "SELECT id, project_id, summary FROM work_events WHERE source_key=?", (f"jira:{key}",)
        ).fetchone()
        if event is None:
            continue
        work_items.create_work_item(conn, WorkItemCreate(
            title=issue.get("summary") or event["summary"], jira_key=key,
            project_id=event["project_id"], source_event_id=event["id"],
            source_key=f"jira-item:{key}", actor="jira-sync", stage=stage,
        ))
        created += 1
    return created


def sync_jira(conn: sqlite3.Connection, *, runner: Callable[[list[str]], str] | None = None) -> dict:
    runner = runner or _twg_runner
    sync_state.record_attempt(conn, "jira")
    try:
        project_keys = [k.strip().upper() for k in settings.sync_jira_projects.split(",") if k.strip()]
        exclude_keys = [k.strip().upper() for k in settings.sync_jira_exclude.split(",") if k.strip()]
        imported = _imported_keys(conn, project_keys)
        jql = build_jql(project_keys, exclude_keys, settings.sync_jira_window_days, imported)
        issues = _fetch_issues(runner, jql)
        previous = {
            row["jira_key"]: json.loads(row["extra_json"] or "{}")
            for row in conn.execute(
                "SELECT jira_key, extra_json FROM work_events "
                "WHERE source_agent='jira-import' AND jira_key IS NOT NULL"
            )
        }
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for project_key in project_keys:
            subset = [i for i in issues if i["key"].strip().upper().startswith(f"{project_key}-")]
            if subset:
                part = jira_import.import_issues(
                    conn, subset, project_key=project_key, project_name=project_key,
                    base_url=f"https://{settings.sync_jira_site}.atlassian.net",
                )
                for k in counts:
                    counts[k] += part[k]
        my_account_id = _my_account_id(conn, runner)
        items_created = _auto_work_items(conn, issues, previous, my_account_id)
        detail = {**counts, "issues": len(issues), "items_created": items_created,
                  "truncated": len(issues) >= LIMIT}
        if my_account_id:
            detail["my_account_id"] = my_account_id
        sync_state.record_success(conn, "jira", detail)
        return {"source": "jira", "ok": True, **detail}
    except (OSError, ValueError, KeyError, TypeError, DatabaseError, subprocess.SubprocessError) as exc:
        sync_state.record_error(conn, "jira", str(exc))
        return {"source": "jira", "ok": False, "error": str(exc)}
