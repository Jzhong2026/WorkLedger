"""Best-effort evidence snapshotting to survive link rot."""
from __future__ import annotations

import sqlite3
import urllib.error
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.client import HTTPException

from ..db import DatabaseError, write_transaction

_MAX_CHARS = 20000
_TIMEOUT = 15


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)


def fetch_url_text(url: str) -> dict:
    """Fetch a URL and extract readable text. Returns {status, text, error}."""
    if not url or not url.lower().startswith(("http://", "https://")):
        return {"status": "inaccessible", "text": None, "error": "Only http/https URLs can be snapshotted."}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WorkLedger/0.1 (evidence snapshot)"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read(2_000_000)
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        status = "inaccessible" if exc.code in (401, 403, 404, 410) else "failed"
        return {"status": status, "text": None, "error": f"Evidence URL returned HTTP {exc.code}."}
    except (OSError, ValueError, HTTPException) as e:
        return {"status": "failed", "text": None, "error": str(e)[:300]}

    mime_type = content_type.partition(";")[0].strip().lower()
    if mime_type and not (mime_type.startswith("text/") or mime_type in ("application/json", "application/xhtml+xml")):
        return {"status": "inaccessible", "text": None, "error": "The link did not return a readable text document."}

    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip()
    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")

    if "html" in content_type.lower():
        extractor = _TextExtractor()
        extractor.feed(body)
        text = "\n".join(extractor.parts)
    else:
        text = body

    text = text[:_MAX_CHARS]
    if not text.strip():
        return {"status": "failed", "text": None, "error": "No readable text extracted."}
    return {"status": "captured", "text": text, "error": None}


def capture_snapshot(conn: sqlite3.Connection, event_id: int) -> dict:
    row = conn.execute("SELECT evidence_url FROM work_events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        raise DatabaseError(f"Event {event_id} not found.", status_code=404)
    url = row["evidence_url"]
    if not url:
        raise DatabaseError(f"Event {event_id} has no evidence_url to snapshot.", status_code=422)

    started_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    result = fetch_url_text(url)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    updates = {
        "snapshot_status": result["status"],
        "snapshot_attempt_at": started_at,
        "snapshot_error": result["error"],
        "updated_at": now,
    }
    if result["status"] == "captured":
        updates.update(evidence_snapshot=result["text"], snapshot_at=now, snapshot_source_url=url)
    with write_transaction(conn):
        assignments = ", ".join(f"{field} = ?" for field in updates)
        cursor = conn.execute(
            f"""UPDATE work_events SET {assignments}
                WHERE id = ? AND evidence_url = ?
                  AND (snapshot_attempt_at IS NULL OR snapshot_attempt_at <= ?)""",
            (*updates.values(), event_id, url, started_at),
        )
        if not cursor.rowcount:
            raise DatabaseError(
                "The evidence URL changed or a newer capture finished. Refresh and check the saved snapshot.",
                status_code=409,
            )
        saved_at = conn.execute(
            "SELECT snapshot_at FROM work_events WHERE id = ?", (event_id,),
        ).fetchone()["snapshot_at"]
    return {
        "event_id": event_id,
        "snapshot_status": result["status"],
        "snapshot_at": saved_at,
        "snapshot_attempt_at": started_at,
        "chars": len(result["text"]) if result["text"] else 0,
        "error": result["error"],
    }
