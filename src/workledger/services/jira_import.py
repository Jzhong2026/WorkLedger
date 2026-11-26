"""Jira snapshot import shared by the CLI script and the sync service."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from ..db import write_transaction
from ..schemas import EventCreate
from . import events, master_data


def adf_to_text(node) -> str:
    """Extract text while retaining the boundaries of ADF blocks."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(adf_to_text(child) for child in node)
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    parts = [adf_to_text(child) for child in node.get("content", [])]
    if kind in ("paragraph", "heading", "codeBlock"):
        return "".join(parts) + "\n"
    return "\n".join(part.rstrip("\n") for part in parts if part) + ("\n" if parts else "")


def _timestamp(value: str | None) -> datetime | None:
    if value:
        return datetime.fromisoformat(value)
    return None


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


DONE_STATUS_NAMES = frozenset({
    "done", "closed", "resolved", "cancelled", "canceled",
    "已完成", "已关闭", "已解决", "已取消",
})


def is_done(status_category: str | None, status_name: str | None) -> bool:
    if status_category:
        return status_category == "done"
    return (status_name or "").strip().lower() in DONE_STATUS_NAMES


def _metadata(raw_json: str | None) -> dict:
    if not raw_json:
        return {}
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        parsed = raw_json
    return parsed if isinstance(parsed, dict) else {"previous_extra_json": parsed}


def _url(url: str | None) -> str | None:
    if url:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None:
            raise ValueError("Jira links must use an HTTP(S) URL without credentials.")
    return url


def _edited_fields(conn: sqlite3.Connection, event: sqlite3.Row) -> set[str]:
    edited = {
        row[0] for row in conn.execute(
            "SELECT field_name FROM revisions WHERE entity_type='work_event' AND entity_id=? AND changed_by='user'",
            (event["id"],),
        )
    }
    if event["user_edited"] and not edited:
        # Honor legacy rows marked as edited even if their field history is unavailable.
        return {"summary", "detail", "evidence_url"}
    return edited


def _import_issue(
    conn: sqlite3.Connection, issue: dict, project_id: int, base_url: str | None,
) -> str:
    key = issue["key"].strip().upper()
    if not key:
        raise ValueError("Every Jira issue needs a non-empty key.")
    fields = {**(issue.get("fields") or {}), **issue}
    source_key = f"jira:{key}"
    original = conn.execute("SELECT * FROM work_events WHERE source_key=?", (source_key,)).fetchone()
    if original is not None and original["source_agent"] != "jira-import":
        raise ValueError(f"Jira key {key} belongs to a WorkLedger record created outside the importer.")

    metadata = _metadata(original["extra_json"]) if original is not None else {}
    created = _timestamp(fields.get("created"))
    updated = _timestamp(fields.get("updated"))
    previous_updated = metadata.get("jira_updated")
    if updated is not None and previous_updated:
        old = _timestamp(previous_updated)
        if old is not None and _as_utc(updated) < _as_utc(old):
            return "unchanged"
    if created is not None:
        metadata["jira_created"] = created.isoformat()
    if updated is not None:
        metadata["jira_updated"] = updated.isoformat()
    for field in ("issuetype", "status", "priority"):
        if field in fields and fields[field] is not None:
            metadata[field] = fields[field].get("name") or "?"
    if "status" in fields and fields["status"]:
        category = (fields["status"].get("statusCategory") or {}).get("key")
        if category:
            metadata["status_category"] = category
    if "assignee" in fields:
        assignee = fields.get("assignee") or {}
        metadata["assignee_account_id"] = assignee.get("accountId")
        metadata["assignee_name"] = assignee.get("displayName")
    if "parent" in fields:
        parent_key = (fields["parent"] or {}).get("key")
        metadata["jira_parent_key"] = parent_key.strip().upper() if parent_key else None

    url = _url(fields.get("url") or (f"{base_url}/browse/{quote(key, safe='')}" if base_url else None))
    if url is not None:
        metadata["jira_url"] = url
    if created is not None:
        metadata["occurred_at_basis"] = "jira_created"
    elif original is None:
        metadata["occurred_at_basis"] = "import_time"
    elif "occurred_at_basis" not in metadata:
        metadata["occurred_at_basis"] = "legacy_import_time"

    description = None
    if "description" in fields:
        description = adf_to_text(fields["description"]).strip()
    if description is None and original is not None:
        existing = original["detail"] or ""
        description = existing.partition("\n\n")[2] if existing.startswith("[") else existing
    context = " · ".join((
        metadata.get("issuetype", "?"), metadata.get("status", "?"),
        f"priority {metadata.get('priority', '?')}",
    ))
    detail = f"[{context}]"
    if description:
        detail += f"\n\n{description}"
    summary = fields.get("summary") or (original["summary"] if original is not None else key)
    extra = json.dumps(metadata, ensure_ascii=False, sort_keys=True)

    if original is None:
        event = events.create_event(conn, EventCreate(
            event_type="manual", occurred_at=created or datetime.now(UTC), jira_key=key,
            source_key=source_key, source_agent="jira-import", summary=summary, detail=detail,
            evidence_url=url, extra_json=extra,
        ))
        conn.execute("UPDATE work_events SET project_id=? WHERE id=?", (project_id, event["id"]))
        return "created"

    edited = _edited_fields(conn, original)
    source_fields = {"summary": summary, "detail": detail}
    if url is not None:
        source_fields["evidence_url"] = url
    changes = {k: v for k, v in source_fields.items() if k not in edited}
    changes["extra_json"] = extra
    if created is not None:
        changes["occurred_at"] = created.strftime("%Y-%m-%d %H:%M:%S")
    if original["project_id"] is None:
        changes["project_id"] = project_id
    changes = {k: v for k, v in changes.items() if v != original[k]}
    if not changes:
        return "unchanged"
    cols = ", ".join(f"{k}=?" for k in changes)
    conn.execute(
        f"UPDATE work_events SET {cols}, updated_at=datetime('now') WHERE id=?",
        (*changes.values(), original["id"]),
    )
    return "updated"


def _reconcile_parents(conn: sqlite3.Connection) -> None:
    imported = conn.execute(
        "SELECT id, source_key, extra_json, parent_event_id FROM work_events WHERE source_agent='jira-import'"
    ).fetchall()
    by_key = {row["source_key"]: row["id"] for row in imported}
    parents = {}
    for row in imported:
        metadata = _metadata(row["extra_json"])
        if "jira_parent_key" in metadata:
            parents[row["id"]] = by_key.get(f"jira:{metadata['jira_parent_key']}")
        else:
            parents[row["id"]] = row["parent_event_id"]

    checked = set()
    for event_id in parents:
        chain = set()
        parent = event_id
        while parent is not None and parent not in checked:
            if parent in chain:
                raise ValueError(f"Jira parent links contain a cycle involving event #{event_id}.")
            chain.add(parent)
            parent = parents.get(parent)
        checked.update(chain)

    conn.executemany(
        "UPDATE work_events SET parent_event_id=?, updated_at=datetime('now') WHERE id=?",
        [
            (parents[row["id"]], row["id"]) for row in imported
            if parents[row["id"]] != row["parent_event_id"]
        ],
    )


def import_issues(
    conn: sqlite3.Connection,
    issues: list[dict],
    *,
    project_key: str,
    project_name: str,
    base_url: str | None = None,
) -> dict[str, int]:
    """Create or refresh Jira snapshots and resolve parent links in one transaction."""
    base_url = _url(base_url.rstrip("/")) if base_url else None
    if base_url and (urlsplit(base_url).query or urlsplit(base_url).fragment):
        raise ValueError("Jira base URL must not include a query or fragment.")
    counts = {"created": 0, "updated": 0, "unchanged": 0}
    if not issues:
        return counts
    with write_transaction(conn):
        project = conn.execute(
            "SELECT id FROM projects WHERE key=?", (project_key.upper(),),
        ).fetchone()
        if project is None:
            project = master_data.create_project(
                conn, name=project_name, key=project_key, description="Imported from Jira",
            )
        for issue in issues:
            outcome = _import_issue(conn, issue, project["id"], base_url)
            counts[outcome] += 1
        _reconcile_parents(conn)
    return counts