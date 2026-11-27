"""Bitbucket PR sync via REST. State lives on the pr_created anchor; no transition events."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx

from ..config import settings
from ..db import DatabaseError, write_transaction
from ..schemas import AccomplishmentCreate, EventCreate
from . import events, jira_import, retrospectives, sync_state


def _client() -> httpx.Client:
    if not settings.atlassian_user_email or not settings.atlassian_api_token:
        raise ValueError("Bitbucket credentials are not configured (ATLASSIAN_USER_EMAIL/ATLASSIAN_API_TOKEN).")
    return httpx.Client(
        base_url="https://api.bitbucket.org/2.0",
        auth=(settings.atlassian_user_email, settings.atlassian_api_token),
        timeout=30,
        trust_env=False,
    )


def _repos() -> list[str]:
    return [r.strip() for r in settings.sync_bitbucket_repos.split(",") if r.strip()]


def _jira_key_pattern() -> re.Pattern:
    keys = [k.strip().upper() for k in settings.sync_jira_projects.split(",") if k.strip()]
    return re.compile(rf"\b(?:{'|'.join(keys)})-\d+\b")


def _fetch_prs(client: httpx.Client, workspace: str, repo: str, my_uuid: str, cutoff: datetime) -> list[dict]:
    q = f'(author.uuid="{my_uuid}" OR reviewers.uuid="{my_uuid}") AND updated_on >= "{cutoff.isoformat()}"'
    prs: list[dict] = []
    page = 1
    while True:
        response = client.get(
            f"/repositories/{workspace}/{repo}/pullrequests",
            params={"q": q, "sort": "-updated_on", "pagelen": "50", "page": str(page)},
        )
        response.raise_for_status()
        data = response.json()
        values = data.get("values", [])
        if not values:
            break
        prs.extend(values)
        oldest = min(datetime.fromisoformat(pr["updated_on"]) for pr in values)
        if "next" not in data or oldest < cutoff:
            break
        page += 1
    distinct = {pr["id"]: pr for pr in prs}
    return [pr for pr in distinct.values() if datetime.fromisoformat(pr["updated_on"]) >= cutoff]


def _upsert_pr(conn, pr: dict, repo_full: str, project_id: int | None, pattern: re.Pattern) -> str:
    pr_id = pr["id"]
    source_key = f"bitbucket:{repo_full}:pr:{pr_id}"
    original = conn.execute("SELECT * FROM work_events WHERE source_key=?", (source_key,)).fetchone()
    if original is not None and original["source_agent"] != "bitbucket-sync":
        raise ValueError(f"PR {repo_full}#{pr_id} belongs to a WorkLedger record created outside the sync.")
    metadata = jira_import._metadata(original["extra_json"]) if original is not None else {}
    updated = datetime.fromisoformat(pr["updated_on"])
    previous = metadata.get("bitbucket_updated")
    if previous and datetime.fromisoformat(previous) >= updated:
        return "unchanged"
    keys = pattern.findall(pr.get("title") or "")
    metadata.update({
        "bitbucket_updated": pr["updated_on"],
        "state": pr["state"],
        "author": (pr.get("author") or {}).get("display_name"),
        "author_uuid": (pr.get("author") or {}).get("uuid"),
        "reviewers": [
            {"name": r.get("display_name"), "uuid": r.get("uuid"), "approved": bool(r.get("approved"))}
            for r in pr.get("reviewers") or []
        ],
        "jira_keys": keys,
        "source_branch": ((pr.get("source") or {}).get("branch") or {}).get("name"),
        "target_branch": ((pr.get("destination") or {}).get("branch") or {}).get("name"),
    })
    url = ((pr.get("links") or {}).get("html") or {}).get("href")
    if url:
        metadata["url"] = url
    title = pr.get("title") or f"PR #{pr_id}"
    detail = (
        f"[PR {pr['state']} · {metadata.get('author') or '?'}] "
        f"{metadata.get('source_branch') or '?'} → {metadata.get('target_branch') or '?'}"
    )
    extra = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    if original is None:
        event = events.create_event(conn, EventCreate(
            event_type="pr_created", occurred_at=datetime.fromisoformat(pr["created_on"]),
            repo=repo_full, pr_number=pr_id, jira_key=keys[0] if keys else None,
            source_key=source_key, source_agent="bitbucket-sync", summary=title,
            detail=detail, evidence_url=url, extra_json=extra,
        ))
        conn.execute("UPDATE work_events SET project_id=? WHERE id=?", (project_id, event["id"]))
        return "created"
    edited = jira_import._edited_fields(conn, original)
    changes = {k: v for k, v in {"summary": title, "detail": detail}.items() if k not in edited}
    if url and "evidence_url" not in edited:
        changes["evidence_url"] = url
    changes["extra_json"] = extra
    if original["project_id"] is None:
        changes["project_id"] = project_id
    if keys and original["jira_key"] is None:
        changes["jira_key"] = keys[0]
    changes = {k: v for k, v in changes.items() if v != original[k]}
    if not changes:
        return "unchanged"
    cols = ", ".join(f"{k}=?" for k in changes)
    conn.execute(
        f"UPDATE work_events SET {cols}, updated_at=datetime('now') WHERE id=?",
        (*changes.values(), original["id"]),
    )
    return "updated"


def sync_bitbucket(conn: sqlite3.Connection, *, client: httpx.Client | None = None) -> dict:
    workspace = settings.sync_bitbucket_workspace
    repos = _repos()
    sources = [f"bitbucket:{workspace}/{repo}" for repo in repos]
    for source in sources:
        sync_state.record_attempt(conn, source)
    owns_client = client is None
    try:
        client = client or _client()
    except ValueError as exc:
        for source in sources:
            sync_state.record_error(conn, source, str(exc))
        return {"ok": False, "error": str(exc), "repos": {}}
    try:
        try:
            me = client.get("/user")
            me.raise_for_status()
            my_uuid = me.json()["uuid"]
        except (httpx.HTTPError, httpx.InvalidURL, KeyError, TypeError, ValueError,
                AttributeError, sqlite3.Error) as exc:
            for source in sources:
                sync_state.record_error(conn, source, f"Bitbucket identity fetch failed: {exc}")
            return {"ok": False, "error": str(exc), "repos": {}}
        cutoff = datetime.now(UTC) - timedelta(days=settings.sync_bitbucket_window_days)
        pattern = _jira_key_pattern()
        project = conn.execute(
            "SELECT id FROM projects WHERE key=?", (settings.sync_bitbucket_project.upper(),)
        ).fetchone()
        project_id = project["id"] if project else None
        results = {}
        for repo in repos:
            source = f"bitbucket:{workspace}/{repo}"
            try:
                prs = _fetch_prs(client, workspace, repo, my_uuid, cutoff)
                counts = {"created": 0, "updated": 0, "unchanged": 0}
                repo_full = f"{workspace}/{repo}"
                with write_transaction(conn):
                    for pr in prs:
                        counts[_upsert_pr(conn, pr, repo_full, project_id, pattern)] += 1
                # Record a merge accomplishment for every MERGED anchor, idempotently by
                # source_key. This covers new anchors, OPEN→MERGED transitions, and anchors
                # already MERGED before this feature shipped (which re-sync as "unchanged").
                # Written outside write_transaction: create_accomplishment uses `with conn:`
                # and would otherwise commit the outer transaction early.
                merges_recorded = 0
                if settings.sync_record_merge_accomplishments:
                    merged_rows = conn.execute(
                        "SELECT id, pr_number, summary, extra_json FROM work_events "
                        "WHERE source_agent='bitbucket-sync' AND event_type='pr_created' AND repo=? "
                        "AND json_extract(extra_json, '$.state')='MERGED'",
                        (repo_full,),
                    ).fetchall()
                    for row in merged_rows:
                        meta = json.loads(row["extra_json"] or "{}")
                        merge_key = f"bitbucket-merge:{repo_full}:pr:{row['pr_number']}"
                        if conn.execute("SELECT 1 FROM accomplishments WHERE source_key=?", (merge_key,)).fetchone():
                            continue
                        retrospectives.create_accomplishment(conn, AccomplishmentCreate(
                            title=f"PR #{row['pr_number']} merged: {row['summary']}",
                            description=f"{repo_full} · {meta.get('author') or '?'} · "
                                        f"{meta.get('source_branch') or '?'} → {meta.get('target_branch') or '?'}",
                            occurred_at=datetime.fromisoformat(meta["bitbucket_updated"]),
                            impact_evidence_url=meta.get("url"), event_id=row["id"],
                            tags="pr,merged", source_key=merge_key,
                        ))
                        merges_recorded += 1
                detail = {**counts, "prs": len(prs), "my_uuid": my_uuid, "merges_recorded": merges_recorded}
                sync_state.record_success(conn, source, detail)
                results[source] = {"ok": True, **detail}
            except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError,
                    AttributeError, sqlite3.Error, DatabaseError) as exc:
                sync_state.record_error(conn, source, str(exc))
                results[source] = {"ok": False, "error": str(exc)}
        return {"ok": all(r["ok"] for r in results.values()), "repos": results}
    finally:
        if owns_client:
            client.close()
