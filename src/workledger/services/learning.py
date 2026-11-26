"""Capture, review, recall, and apply work-backed lessons."""
from __future__ import annotations

import json
import re
import sqlite3
from hashlib import sha256
from unicodedata import normalize

from pydantic import ValidationError

from ..agent import propose_lesson
from ..db import DatabaseError, write_transaction
from ..learning_models import (
    LessonCreate,
    LessonReviewStatus,
    LessonStatus,
    LessonText,
    LessonUpdate,
    LessonUseCreate,
    LessonUseOutcome,
)

_LESSONS = """
    SELECT l.*, w.title AS source_work_item_title, w.project_id AS source_project_id,
           p.name AS source_project_name, e.summary AS source_event_summary,
           e.evidence_url AS source_event_url,
           (SELECT COUNT(*) FROM lesson_uses u WHERE u.lesson_id=l.id) AS use_count
    FROM lessons l
    JOIN work_items w ON w.id=l.source_work_item_id
    LEFT JOIN projects p ON p.id=w.project_id
    LEFT JOIN work_events e ON e.id=l.source_event_id
"""
_USES = """
    SELECT u.*, w.title AS work_item_title
    FROM lesson_uses u JOIN work_items w ON w.id=u.work_item_id
"""
_ITEM_EVENTS = """
    SELECT e.*
    FROM work_items w JOIN work_events e ON (
        e.id=w.source_event_id OR EXISTS (
            SELECT 1 FROM work_item_events link WHERE link.item_id=w.id AND link.event_id=e.id
        )
    )
    WHERE w.id=?
"""
_STOPWORDS = frozenset({
    "a", "about", "an", "and", "are", "be", "for", "has", "in", "is", "it", "of",
    "on", "or", "the", "to", "with", "work", "task", "issue", "investigate",
    "这个", "一个", "问题", "任务", "处理", "进行", "相关", "需要",
})
_HAN_RUN = re.compile(r"([\u3400-\u9fff]+)")
_WORD = re.compile(r"[^\W_]+")


def _lesson_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    result["tags"] = json.loads(result["tags"])
    result.pop("request_fingerprint")
    result["evidence_url_override"] = result["evidence_url"]
    result["evidence_url"] = result["evidence_url"] or result["source_event_url"]
    return result


def _lesson(conn: sqlite3.Connection, lesson_id: int) -> sqlite3.Row:
    row = conn.execute(_LESSONS + " WHERE l.id=?", (lesson_id,)).fetchone()
    if row is None:
        raise DatabaseError("Lesson not found.", status_code=404)
    return row


def _work_item(conn: sqlite3.Connection, work_item_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM work_items WHERE id=?", (work_item_id,)).fetchone()
    if row is None:
        raise DatabaseError("The source or follow-up work item was not found.", status_code=404)
    return row


def _source_event(
    conn: sqlite3.Connection, work_item_id: int, event_id: int | None,
) -> sqlite3.Row | None:
    if event_id is None:
        return conn.execute(
            _ITEM_EVENTS + " ORDER BY e.verification_done DESC, e.occurred_at DESC, e.id DESC LIMIT 1",
            (work_item_id,),
        ).fetchone()
    row = conn.execute(_ITEM_EVENTS + " AND e.id=?", (work_item_id, event_id)).fetchone()
    if row is None:
        raise DatabaseError("Select evidence linked to this work item.", status_code=422)
    return row


def get_lesson(conn: sqlite3.Connection, lesson_id: int) -> dict:
    result = _lesson_dict(_lesson(conn, lesson_id))
    result["uses"] = [
        dict(row) for row in conn.execute(
            _USES + " WHERE u.lesson_id=? ORDER BY u.updated_at DESC, u.work_item_id DESC",
            (lesson_id,),
        )
    ]
    return result


def list_lessons(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    status: LessonStatus | None = None,
    page: int = 1,
    page_size: int = 30,
) -> dict:
    conditions = []
    params = []
    if status:
        conditions.append("l.status=?")
        params.append(status)
    if q and q.strip():
        fields = '"trigger"', "title", "first_step", "limits", "tags"
        conditions.append("(" + " OR ".join(
            f"instr(lower(l.{field}), lower(?)) > 0" for field in fields
        ) + " OR instr(lower(w.title), lower(?)) > 0)")
        params.extend([q.strip()] * (len(fields) + 1))
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    total = conn.execute(
        "SELECT COUNT(*) FROM lessons l JOIN work_items w ON w.id=l.source_work_item_id" + where,
        params,
    ).fetchone()[0]
    rows = conn.execute(
        _LESSONS + where + " ORDER BY l.updated_at DESC, l.id DESC LIMIT ? OFFSET ?",
        (*params, page_size, (page - 1) * page_size),
    )
    return {
        "items": [_lesson_dict(row) for row in rows],
        "total": total, "page": page, "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


def _fingerprint(data: LessonCreate) -> str:
    payload = json.dumps(data.model_dump(), ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode()).hexdigest()


def _insert_lesson(conn: sqlite3.Connection, data: LessonCreate, origin: str, fingerprint: str) -> dict:
    lesson_id = conn.execute(
        """INSERT INTO lessons (kind, title, "trigger", first_step, limits, tags,
                                source_work_item_id, source_event_id, evidence_url, origin, request_fingerprint)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
        (
            data.kind, data.title, data.trigger, data.first_step, data.limits,
            json.dumps(data.tags, ensure_ascii=False),
            data.source_work_item_id, data.source_event_id, data.evidence_url, origin, fingerprint,
        ),
    ).fetchone()[0]
    return get_lesson(conn, lesson_id)


def create_lesson(conn: sqlite3.Connection, data: LessonCreate) -> dict:
    with write_transaction(conn):
        fingerprint = _fingerprint(data)
        existing = conn.execute(
            "SELECT id FROM lessons WHERE origin='manual' AND request_fingerprint=?", (fingerprint,),
        ).fetchone()
        if existing:
            return get_lesson(conn, existing["id"])
        _work_item(conn, data.source_work_item_id)
        if data.source_event_id is not None:
            _source_event(conn, data.source_work_item_id, data.source_event_id)
        return _insert_lesson(conn, data, "manual", fingerprint)


def update_lesson(conn: sqlite3.Connection, lesson_id: int, data: LessonUpdate) -> dict:
    with write_transaction(conn):
        row = _lesson(conn, lesson_id)
        edits = data.model_dump(exclude_unset=True)
        if "tags" in edits:
            edits["tags"] = json.dumps(LessonText.unique_tags(edits["tags"]), ensure_ascii=False)
        if "limits" in edits:
            edits["limits"] = edits["limits"] or None
        changes = {field: value for field, value in edits.items() if value != row[field]}
        if "source_event_id" in changes:
            if row["origin"] == "codebuddy":
                raise DatabaseError("The original evidence for an AI candidate is fixed.", status_code=422)
            if changes["source_event_id"] is not None:
                _source_event(conn, row["source_work_item_id"], changes["source_event_id"])
        if changes:
            assignments = ", ".join(f'"{field}"=?' for field in changes)
            conn.execute(
                f"UPDATE lessons SET {assignments}, status='candidate', reviewed_at=NULL, "
                "updated_at=datetime('now') WHERE id=?",
                (*changes.values(), lesson_id),
            )
        return get_lesson(conn, lesson_id)


def review_lesson(conn: sqlite3.Connection, lesson_id: int, status: LessonReviewStatus) -> dict:
    with write_transaction(conn):
        row = _lesson(conn, lesson_id)
        if row["status"] != status:
            conn.execute(
                "UPDATE lessons SET status=?, reviewed_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
                (status, lesson_id),
            )
        return get_lesson(conn, lesson_id)


def record_lesson_use(
    conn: sqlite3.Connection,
    lesson_id: int,
    *,
    work_item_id: int,
    outcome: LessonUseOutcome,
    detail: str | None = None,
) -> dict:
    data = LessonUseCreate(work_item_id=work_item_id, outcome=outcome, detail=detail)
    with write_transaction(conn):
        row = _lesson(conn, lesson_id)
        if row["status"] != "confirmed":
            raise DatabaseError("Confirm the lesson before recording reuse.", status_code=409)
        if work_item_id == row["source_work_item_id"]:
            raise DatabaseError("Choose a different work item from the lesson source.", status_code=422)
        _work_item(conn, work_item_id)
        change = conn.execute(
            """INSERT INTO lesson_uses (lesson_id, work_item_id, outcome, detail)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (lesson_id, work_item_id) DO UPDATE
               SET outcome=excluded.outcome, detail=excluded.detail, updated_at=datetime('now')
               WHERE lesson_uses.outcome IS NOT excluded.outcome OR lesson_uses.detail IS NOT excluded.detail
               RETURNING outcome, detail""",
            (lesson_id, work_item_id, data.outcome, data.detail or None),
        ).fetchone()
        if change:
            conn.execute(
                "INSERT INTO lesson_use_history (lesson_id, work_item_id, outcome, detail) VALUES (?, ?, ?, ?)",
                (lesson_id, work_item_id, change["outcome"], change["detail"]),
            )
        return dict(conn.execute(
            _USES + " WHERE u.lesson_id=? AND u.work_item_id=?",
            (lesson_id, work_item_id),
        ).fetchone())


def _terms(text: str) -> set[str]:
    tokens = set()
    for index, run in enumerate(_HAN_RUN.split(normalize("NFKC", text).casefold())):
        if index % 2:
            tokens.update(run[i:i + 2] for i in range(len(run) - 1))
        else:
            tokens.update(word for word in _WORD.findall(run) if len(word) >= 2)
    return tokens - _STOPWORDS


def _relevance(
    row: dict, query_terms: set[str], project_id: int | None,
) -> tuple[int, list[str]]:
    tags = [tag for tag in row["tags"] if query_terms & _terms(tag)]
    keywords = query_terms & _terms(row["title"] + " " + row["trigger"])
    score = 5 * len(tags) + 3 * len(keywords)
    if not score:
        return 0, []
    reasons = []
    if tags:
        reasons.append("Matching tags: " + ", ".join(tags))
    if keywords:
        reasons.append("Matching terms: " + ", ".join(sorted(keywords)[:5]))
    if project_id is not None and row["source_project_id"] == project_id:
        score += 1
    elif project_id is not None and row["source_project_name"]:
        reasons.append(f"From {row['source_project_name']}, with a matching trigger or topic.")
    return score, reasons


def recall_lessons(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: int | None = None,
    limit: int = 5,
    exclude_source_work_item_id: int | None = None,
) -> list[dict]:
    """Rank confirmed lessons by current-work signals, including cross-project matches."""
    query_terms = _terms(query)
    if not query_terms or limit < 1:
        return []
    matches = []
    for row in conn.execute(_LESSONS + " WHERE l.status='confirmed'"):
        if row["source_work_item_id"] == exclude_source_work_item_id:
            continue
        record = _lesson_dict(row)
        score, reasons = _relevance(record, query_terms, project_id)
        if reasons:
            matches.append((score, {**record, "reasons": reasons}))
    matches.sort(key=lambda match: (match[0], match[1]["reviewed_at"], match[1]["id"]), reverse=True)
    return [record for _, record in matches[:limit]]


def _existing_draft(conn: sqlite3.Connection, work_item_id: int, event_id: int) -> dict | None:
    row = conn.execute(
        "SELECT id FROM lessons WHERE origin='codebuddy' AND source_work_item_id=? AND source_event_id=?",
        (work_item_id, event_id),
    ).fetchone()
    return get_lesson(conn, row["id"]) if row else None


def draft_lesson(
    conn: sqlite3.Connection, work_item_id: int, *, source_event_id: int | None = None,
) -> dict:
    item = _work_item(conn, work_item_id)
    event = _source_event(conn, work_item_id, source_event_id)
    if event is None:
        raise DatabaseError("Link an event to this work item before drafting from evidence.", status_code=422)
    event_id = event["id"]
    existing = _existing_draft(conn, work_item_id, event_id)
    if existing:
        return existing
    context = {
        "work_item": item["title"][:500],
        "goal": (item["goal"] or "")[:600],
        "event_summary": event["summary"][:500],
        "event_detail": (event["detail"] or "")[:1200],
        "root_cause": (event["root_cause"] or "")[:500],
        "root_cause_confirmed": bool(event["root_cause_confirmed"]),
        "verification_result": (event["verification_result"] or "")[:500],
        "verification_done": bool(event["verification_done"]),
    }
    result = propose_lesson(context)
    if not result.get("ok"):
        raise DatabaseError(result.get("error") or "CodeBuddy could not draft the lesson.", status_code=503)
    if result.get("candidate") is None:
        raise DatabaseError(
            "The selected evidence does not support a reusable lesson. Choose more evidence or write one manually.",
            status_code=422,
        )
    try:
        text = LessonText.model_validate(result["candidate"])
    except ValidationError as exc:
        raise DatabaseError("CodeBuddy returned an invalid lesson candidate. Retry or write one manually.", status_code=502) from exc
    data = LessonCreate(
        source_work_item_id=work_item_id, source_event_id=event_id, **text.model_dump(),
    )
    with write_transaction(conn):
        _source_event(conn, work_item_id, event_id)
        return _existing_draft(conn, work_item_id, event_id) or _insert_lesson(
            conn, data, "codebuddy", _fingerprint(data),
        )
