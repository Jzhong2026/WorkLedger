"""Import Jira workitems (from twg query JSON) into WorkLedger as work events.

Usage: python scripts/import_jira.py <twg-stdout.json> [--project-key RW] [--project-name RW]
Deduplicates by jira:<KEY> source_key. Links events to a project.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workledger.config import settings
from workledger.db import get_connection, init_db
from workledger.schemas import EventCreate
from workledger.services import events, master_data


def adf_to_text(node) -> str:
    """Recursively extract plain text from Atlassian Document Format."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(adf_to_text(n) for n in node)
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        parts = [adf_to_text(c) for c in node.get("content", [])]
        joined = "".join(parts) if node.get("type") == "text" else "\n".join(p for p in parts if p)
        block = node.get("type") in ("paragraph", "heading", "codeBlock", "blockquote", "panel", "listItem")
        return joined + ("\n" if block else "")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("--project-key", default="RW")
    ap.add_argument("--project-name", default="RW")
    args = ap.parse_args()

    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    issues = data["data"]["issues"]

    conn = init_db(settings.db_path)

    projects = master_data.list_projects(conn, include_archived=True)
    proj = next((p for p in projects if p["key"] == args.project_key.upper()), None)
    if not proj:
        proj = master_data.create_project(conn, name=args.project_name, key=args.project_key, description="Imported from Jira")
    project_id = proj["id"]

    now = datetime.now(timezone.utc)
    created, skipped = 0, 0
    for i in issues:
        key = i["key"]
        source_key = f"jira:{key}"
        existing = conn.execute("SELECT id FROM work_events WHERE source_key = ?", (source_key,)).fetchone()
        if existing:
            skipped += 1
            print(f"skip {key} (already imported as event {existing['id']})")
            continue

        issuetype = (i.get("issuetype") or {}).get("name", "?")
        status = (i.get("status") or {}).get("name", "?")
        priority = (i.get("priority") or {}).get("name", "?")
        desc = adf_to_text(i.get("description")).strip()
        url = i.get("url") or f"https://transfinder.atlassian.net/browse/{key}"

        detail = f"[{issuetype} · {status} · priority {priority}]\n\n{desc}" if desc else f"[{issuetype} · {status} · priority {priority}]"
        extra = json.dumps({"issuetype": issuetype, "status": status, "priority": priority, "jira_url": url}, ensure_ascii=False)

        ev = events.create_event(conn, EventCreate(
            event_type="manual",
            occurred_at=now,
            jira_key=key,
            source_key=source_key,
            source_agent="jira-import",
            summary=i.get("summary", key),
            detail=detail,
            evidence_url=url,
            extra_json=extra,
        ))
        conn.execute("UPDATE work_events SET project_id = ? WHERE id = ?", (project_id, ev["id"]))
        conn.commit()
        created += 1
        print(f"import {key} [{issuetype}/{status}] -> event {ev['id']}")

    print(f"\nDone: {created} created, {skipped} skipped (dedup). Project '{args.project_key}' id={project_id}.")


if __name__ == "__main__":
    main()