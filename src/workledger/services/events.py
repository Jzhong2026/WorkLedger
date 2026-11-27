"""Work event CRUD with source-based deduplication."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from ..db import DatabaseError, write_transaction
from ..schemas import EventCreate, EventUpdate


def _legacy_source_key(data: EventCreate) -> str | None:
    parts = [data.event_type]
    if data.repo:
        parts.append(data.repo)
    if data.pr_number is not None:
        parts.append(str(data.pr_number))
    if data.comment_id:
        parts.append(data.comment_id)
    return ":".join(parts) if len(parts) > 1 else None


def _source_fingerprint(data: EventCreate) -> str:
    payload = data.model_dump(mode="json", exclude={"source_key"})
    if data.occurred_at.tzinfo is not None:
        payload["occurred_at"] = data.occurred_at.astimezone(UTC).isoformat()
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _matches_legacy_event(row: sqlite3.Row, data: EventCreate, occurred: str) -> bool:
    fields = data.model_dump(exclude={"source_key", "occurred_at"})
    return row["occurred_at"] == occurred and all(row[name] == value for name, value in fields.items())


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("source_fingerprint", None)
    for k in ("root_cause_confirmed", "verification_done", "user_edited"):
        d[k] = bool(d[k])
    return d


def create_event(conn: sqlite3.Connection, data: EventCreate) -> dict:
    fingerprint = _source_fingerprint(data)
    source_key = data.source_key or f"event:{fingerprint}"
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    occurred = data.occurred_at.strftime("%Y-%m-%d %H:%M:%S")

    try:
        with write_transaction(conn):
            existing = conn.execute(
                "SELECT * FROM work_events WHERE source_key = ?", (source_key,)
            ).fetchone()
            if existing:
                result = _row_to_dict(existing)
                stored_fingerprint = existing["source_fingerprint"]
                if stored_fingerprint and stored_fingerprint != fingerprint:
                    result["source_conflict"] = True
                return result

            # A replay of a matching pre-upgrade record should still return that
            # row. A different action sharing the old coarse key can be written.
            legacy_key = _legacy_source_key(data) if not data.source_key else None
            if legacy_key:
                legacy = conn.execute(
                    "SELECT * FROM work_events WHERE source_key = ? AND source_fingerprint IS NULL",
                    (legacy_key,),
                ).fetchone()
                if legacy and _matches_legacy_event(legacy, data, occurred):
                    return _row_to_dict(legacy)

            conn.execute(
                """INSERT INTO work_events
                   (event_type, occurred_at, recorded_at, repo, pr_number, comment_id,
                    jira_key, source_key, source_agent, summary, detail, evidence_url,
                    root_cause, root_cause_confirmed, verification_result, verification_done,
                    reply_status, extra_json, created_at, updated_at, source_fingerprint)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    data.event_type, occurred, now, data.repo, data.pr_number,
                    data.comment_id, data.jira_key, source_key, data.source_agent,
                    data.summary, data.detail, data.evidence_url,
                    data.root_cause, int(data.root_cause_confirmed),
                    data.verification_result, int(data.verification_done),
                    data.reply_status, data.extra_json, now, now, fingerprint,
                ),
            )
            row = conn.execute(
                "SELECT * FROM work_events WHERE source_key = ?", (source_key,)
            ).fetchone()
            return _row_to_dict(row)
    except sqlite3.IntegrityError as e:
        raise DatabaseError(f"Invalid event data: {e}", status_code=422) from e
    except sqlite3.OperationalError as e:
        raise DatabaseError(f"Write failed: {e}") from e


def get_event(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM work_events WHERE id = ?", (event_id,)).fetchone()
    return _row_to_dict(row) if row else None


def update_event(conn: sqlite3.Connection, event_id: int, data: EventUpdate, changed_by: str = "user") -> dict | None:
    with write_transaction(conn):
        existing = conn.execute("SELECT * FROM work_events WHERE id = ?", (event_id,)).fetchone()
        if not existing:
            return None
        updates = {
            field: value for field, value in data.model_dump(exclude_unset=True).items()
            if existing[field] != value
        }
        if not updates:
            return _row_to_dict(existing)

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        set_clauses = [f"{field} = ?" for field in updates]
        set_clauses.extend(["user_edited = 1", "updated_at = ?"])
        for field, value in updates.items():
            old_value = existing[field]
            conn.execute(
                "INSERT INTO revisions (entity_type, entity_id, field_name, old_value, new_value, changed_by) VALUES (?,?,?,?,?,?)",
                ("work_event", event_id, field, old_value, value, changed_by),
            )
        conn.execute(
            f"UPDATE work_events SET {', '.join(set_clauses)} WHERE id = ?",
            (*updates.values(), now, event_id),
        )
        return get_event(conn, event_id)


def split_expansion_keywords(raw: str) -> list[str]:
    values = raw.replace("，", ",").replace("、", ",").split(",")
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:6]


def _search_terms(terms: list[str]) -> tuple[str, list[str]]:
    conditions = []
    params = []
    for term in terms:
        term = term.strip()
        if not term:
            continue
        if len(term) >= 3:
            conditions.append("id IN (SELECT rowid FROM work_events_fts WHERE work_events_fts MATCH ?)")
            params.append('"' + term.replace('"', '""') + '"')
        else:
            conditions.append(
                "(summary LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\' "
                "OR root_cause LIKE ? ESCAPE '\\')"
            )
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.extend([f"%{escaped}%"] * 3)
    return " OR ".join(conditions), params


def search_events(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    repo: str | None = None,
    pr_number: int | None = None,
    jira_key: str | None = None,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: int | None = None,
    root_cause: str | None = None,
    page: int = 1,
    page_size: int = 20,
    keywords: list[str] | None = None,
    raw_match: str | None = None,
    scope: str | None = None,
) -> tuple[list[dict], int]:
    conditions = []
    params: list = []

    if scope not in (None, "all", "mine"):
        raise ValueError("Scope must be 'all' or 'mine'.")
    if scope == "mine":
        from . import sources
        mine_sql, mine_params = sources.mine_predicate(conn)
        conditions.append(mine_sql)
        params.extend(mine_params)

    if raw_match:
        conditions.append("id IN (SELECT rowid FROM work_events_fts WHERE work_events_fts MATCH ?)")
        params.append(raw_match)
    else:
        terms = keywords if keywords is not None else [q] if q else []
        term_filter, term_params = _search_terms(terms)
        if term_filter:
            conditions.append(f"({term_filter})")
            params.extend(term_params)
    if repo == "":
        conditions.append("(repo IS NULL OR repo = '')")
    elif repo is not None:
        conditions.append("repo = ?")
        params.append(repo)
    if pr_number is not None:
        conditions.append("pr_number = ?")
        params.append(pr_number)
    if jira_key:
        conditions.append("jira_key = ? COLLATE NOCASE")
        params.append(jira_key)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if project_id == 0:
        conditions.append("project_id IS NULL")
    elif project_id is not None:
        conditions.append("project_id = ?")
        params.append(project_id)
    if root_cause is not None:
        conditions.append("root_cause = ?")
        params.append(root_cause)
    if date_from:
        conditions.append("occurred_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("occurred_at <= ?")
        params.append(date_to + " 23:59:59")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = conn.execute(f"SELECT COUNT(*) AS c FROM work_events {where}", params).fetchone()["c"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        f"SELECT * FROM work_events {where} ORDER BY occurred_at DESC, id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()
    return [_row_to_dict(r) for r in rows], total


def get_pr_timeline(conn: sqlite3.Connection, repo: str, pr_number: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM work_events WHERE repo = ? AND pr_number = ? ORDER BY occurred_at ASC, id ASC",
        (repo, pr_number),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_children(conn: sqlite3.Connection, event_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM work_events WHERE parent_event_id = ? ORDER BY occurred_at ASC, id ASC",
        (event_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_repos(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT repo FROM work_events WHERE repo IS NOT NULL ORDER BY repo"
    ).fetchall()
    return [r["repo"] for r in rows]


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    repo: str | None = None,
    event_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
    keywords: list[str] | None = None,
    raw_match: str | None = None,
) -> tuple[list[dict], int]:
    """Find a literal query or any of the supplied keywords."""
    return search_events(
        conn, q=query, repo=repo, event_type=event_type, page=page, page_size=page_size,
        keywords=keywords, raw_match=raw_match,
    )
