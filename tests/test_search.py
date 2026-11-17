"""Tests for FTS5 full-text search."""
from __future__ import annotations

from datetime import datetime, timezone

from workledger.schemas import EventCreate
from workledger.services import events


def _ev(conn, summary, detail=None, **kw):
    return events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        summary=summary, detail=detail, **kw,
    ))


class TestFTS:
    def test_english_substring(self, conn):
        _ev(conn, "Updated import to MCPServer")
        _ev(conn, "Unrelated note")
        items, total = events.search_fts(conn, "MCPServer")
        assert total == 1
        assert items[0]["summary"] == "Updated import to MCPServer"

    def test_chinese_substring(self, conn):
        _ev(conn, "修复了空指针检查缺陷")
        _ev(conn, "其他记录")
        items, total = events.search_fts(conn, "空指针")
        assert total == 1
        assert "空指针" in items[0]["summary"]

    def test_short_query_like_fallback(self, conn):
        _ev(conn, "Fix ab bug")
        items, total = events.search_fts(conn, "ab")
        assert total == 1

    def test_detail_searchable(self, conn):
        _ev(conn, "Some title", detail="the root cause was a missing guard clause")
        items, total = events.search_fts(conn, "guard clause")
        assert total == 1

    def test_raw_match_or(self, conn):
        _ev(conn, "alpha feature")
        _ev(conn, "beta feature")
        _ev(conn, "gamma feature")
        items, total = events.search_fts(conn, "", raw_match='"alpha" OR "beta"')
        assert total == 2

    def test_fts_updates_on_edit(self, conn):
        ev = _ev(conn, "original text")
        events.update_event(conn, ev["id"], events.EventUpdate(summary="changed wording"))
        _, old_total = events.search_fts(conn, "original")
        _, new_total = events.search_fts(conn, "changed")
        assert old_total == 0
        assert new_total == 1

    def test_repo_filter(self, conn):
        _ev(conn, "shared keyword", repo="org/a")
        _ev(conn, "shared keyword", repo="org/b")
        items, total = events.search_fts(conn, "shared", repo="org/a")
        assert total == 1
        assert items[0]["repo"] == "org/a"