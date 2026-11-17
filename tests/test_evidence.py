"""Tests for evidence snapshotting."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from workledger.db import DatabaseError
from workledger.schemas import EventCreate
from workledger.services import events, evidence


class TestTextExtractor:
    def test_strips_tags_and_scripts(self):
        ex = evidence._TextExtractor()
        ex.feed("<html><head><style>body{}</style></head><body><script>var x=1;</script><p>Hello</p><p>World</p></body></html>")
        text = "\n".join(ex.parts)
        assert "Hello" in text
        assert "World" in text
        assert "var x" not in text
        assert "body{}" not in text


class TestFetch:
    def test_non_http_inaccessible(self):
        r = evidence.fetch_url_text("javascript:alert(1)")
        assert r["status"] == "inaccessible"

    def test_empty_url(self):
        assert evidence.fetch_url_text("")["status"] == "inaccessible"

    def test_real_fetch(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><body><p>Review comment text</p></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a):
                pass

        srv = HTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            r = evidence.fetch_url_text(f"http://127.0.0.1:{port}/comment")
            assert r["status"] == "captured"
            assert "Review comment text" in r["text"]
        finally:
            srv.shutdown()


class TestCapture:
    def test_missing_event(self, conn):
        with pytest.raises(DatabaseError, match="not found"):
            evidence.capture_snapshot(conn, 999)

    def test_no_url(self, conn):
        ev = events.create_event(conn, EventCreate(event_type="manual", occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc), summary="no url"))
        with pytest.raises(DatabaseError, match="no evidence_url"):
            evidence.capture_snapshot(conn, ev["id"])

    def test_capture_stores_snapshot(self, conn, monkeypatch):
        ev = events.create_event(conn, EventCreate(
            event_type="fix", occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
            summary="x", evidence_url="https://example.com/c",
        ))
        monkeypatch.setattr(evidence, "fetch_url_text", lambda url: {"status": "captured", "text": "snapshot body", "error": None})
        r = evidence.capture_snapshot(conn, ev["id"])
        assert r["snapshot_status"] == "captured"
        assert r["chars"] == len("snapshot body")
        stored = events.get_event(conn, ev["id"])
        assert stored["evidence_snapshot"] == "snapshot body"
        assert stored["snapshot_status"] == "captured"