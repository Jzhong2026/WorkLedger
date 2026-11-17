"""Aggregated insights over work records for the dashboard."""
from __future__ import annotations

import sqlite3


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_insights(conn: sqlite3.Connection) -> dict:
    totals = {
        "events": conn.execute("SELECT COUNT(*) c FROM work_events").fetchone()["c"],
        "accomplishments": conn.execute("SELECT COUNT(*) c FROM accomplishments").fetchone()["c"],
        "cases": conn.execute("SELECT COUNT(*) c FROM cases").fetchone()["c"],
        "todos": conn.execute("SELECT COUNT(*) c FROM todos").fetchone()["c"],
        "highlights": conn.execute("SELECT COUNT(*) c FROM accomplishments WHERE is_highlight=1").fetchone()["c"],
        "snapshots": conn.execute("SELECT COUNT(*) c FROM work_events WHERE snapshot_status='captured'").fetchone()["c"],
    }

    by_type = _rows(conn,
        "SELECT event_type AS label, COUNT(*) AS value FROM work_events GROUP BY event_type ORDER BY value DESC")

    by_repo = _rows(conn,
        "SELECT COALESCE(repo,'(no repo)') AS label, COUNT(*) AS value FROM work_events "
        "GROUP BY repo ORDER BY value DESC LIMIT 10")

    by_project = _rows(conn,
        "SELECT COALESCE(p.name,'(unassigned)') AS label, COUNT(*) AS value FROM work_events e "
        "LEFT JOIN projects p ON e.project_id=p.id GROUP BY e.project_id ORDER BY value DESC LIMIT 10")

    by_month = _rows(conn,
        "SELECT substr(occurred_at,1,7) AS label, COUNT(*) AS value FROM work_events "
        "GROUP BY label ORDER BY label ASC")

    root_causes = _rows(conn,
        "SELECT root_cause AS label, COUNT(*) AS value FROM work_events "
        "WHERE root_cause IS NOT NULL AND root_cause != '' GROUP BY root_cause ORDER BY value DESC LIMIT 8")

    todo_status = _rows(conn,
        "SELECT status AS label, COUNT(*) AS value FROM todos GROUP BY status")

    confirmed = conn.execute(
        "SELECT SUM(root_cause_confirmed) c FROM work_events WHERE root_cause IS NOT NULL"
    ).fetchone()["c"] or 0
    with_cause = conn.execute(
        "SELECT COUNT(*) c FROM work_events WHERE root_cause IS NOT NULL AND root_cause != ''"
    ).fetchone()["c"]

    return {
        "totals": totals,
        "by_type": by_type,
        "by_repo": by_repo,
        "by_project": by_project,
        "by_month": by_month,
        "root_causes": root_causes,
        "todo_status": todo_status,
        "root_cause_confirmation": {"confirmed": confirmed, "with_cause": with_cause},
    }