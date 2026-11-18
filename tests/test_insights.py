"""Tests for insights aggregation."""
from __future__ import annotations

from datetime import UTC, datetime

from workledger.schemas import AccomplishmentCreate, EventCreate, TodoCreate
from workledger.services import events, insights, master_data, retrospectives, todos


def _seed(conn):
    events.create_event(conn, EventCreate(event_type="fix", occurred_at=datetime(2026, 6, 1, tzinfo=UTC), repo="org/a", summary="f1", root_cause="missing guard", source_key="k1"))
    events.create_event(conn, EventCreate(event_type="fix", occurred_at=datetime(2026, 6, 15, tzinfo=UTC), repo="org/a", summary="f2", root_cause="missing guard", source_key="k2"))
    events.create_event(conn, EventCreate(event_type="review_finding", occurred_at=datetime(2026, 7, 1, tzinfo=UTC), repo="org/b", summary="r1", source_key="k3"))
    retrospectives.create_accomplishment(conn, AccomplishmentCreate(title="A", occurred_at=datetime(2026, 6, 1, tzinfo=UTC), is_highlight=True))
    todos.create_todo(conn, TodoCreate(title="t1", status="pending"))
    todos.create_todo(conn, TodoCreate(title="t2", status="done"))


class TestInsights:
    def test_filtered_rows_link_to_the_same_records(self, conn):
        _seed(conn)
        project = master_data.create_project(conn, name='Alpha', key='ALPHA')
        conn.execute('UPDATE work_events SET project_id = ? WHERE source_key = ?', (project['id'], 'k2'))
        scope = {'project_id': project['id'], 'date_from': '2026-06-10', 'date_to': '2026-06-20'}

        result = insights.get_insights(conn, **scope)

        assert result['totals']['events'] == 1
        assert result['totals']['accomplishments'] == 0
        for group in ('by_type', 'by_repo', 'by_project', 'by_month', 'root_causes'):
            row, = result[group]
            assert row['filters']['date_from'] == '2026-06-10'
            assert row['filters']['date_to'] == '2026-06-20'
            items, total = events.search_events(conn, **row['filters'])
            assert total == row['value'] == 1
            assert items[0]['source_key'] == 'k2'

    def test_totals(self, conn):
        _seed(conn)
        d = insights.get_insights(conn)
        assert d["totals"]["events"] == 3
        assert d["totals"]["accomplishments"] == 1
        assert d["totals"]["highlights"] == 1
        assert d["totals"]["todos"] == 2

    def test_by_type(self, conn):
        _seed(conn)
        d = insights.get_insights(conn)
        types = {r["label"]: r["value"] for r in d["by_type"]}
        assert types["fix"] == 2
        assert types["review_finding"] == 1

    def test_by_month(self, conn):
        _seed(conn)
        d = insights.get_insights(conn)
        months = {r["label"]: r["value"] for r in d["by_month"]}
        assert months["2026-06"] == 2
        assert months["2026-07"] == 1

    def test_root_causes_ranked(self, conn):
        _seed(conn)
        d = insights.get_insights(conn)
        assert d["root_causes"][0]["label"] == "missing guard"
        assert d["root_causes"][0]["value"] == 2

    def test_todo_status(self, conn):
        _seed(conn)
        d = insights.get_insights(conn)
        st = {r["label"]: r["value"] for r in d["todo_status"]}
        assert st["pending"] == 1
        assert st["done"] == 1

    def test_empty(self, conn):
        d = insights.get_insights(conn)
        assert d["totals"]["events"] == 0
        assert d["by_type"] == []
