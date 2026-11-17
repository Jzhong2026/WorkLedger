"""Best-effort evidence snapshotting to survive link rot."""
from __future__ import annotations

import sqlite3
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

from ..db import DatabaseError

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
    req = urllib.request.Request(url, headers={"User-Agent": "WorkLedger/0.1 (evidence snapshot)"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read(2_000_000)
            content_type = resp.headers.get("Content-Type", "")
    except Exception as e:
        return {"status": "failed", "text": None, "error": str(e)[:300]}

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
    row = conn.execute("SELECT * FROM work_events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        raise DatabaseError(f"Event {event_id} not found.")
    if not row["evidence_url"]:
        raise DatabaseError(f"Event {event_id} has no evidence_url to snapshot.")

    result = fetch_url_text(row["evidence_url"])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.execute(
            "UPDATE work_events SET evidence_snapshot=?, snapshot_status=?, snapshot_at=?, updated_at=? WHERE id=?",
            (result["text"], result["status"], now, now, event_id),
        )
    return {
        "event_id": event_id,
        "snapshot_status": result["status"],
        "snapshot_at": now,
        "chars": len(result["text"]) if result["text"] else 0,
        "error": result["error"],
    }