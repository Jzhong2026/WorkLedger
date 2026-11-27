"""Aggregated insights and their event drill-down filters."""
from __future__ import annotations

import sqlite3
from calendar import monthrange
from collections.abc import Callable


def _where(
    scope: dict[str, str | int],
    date_column: str,
    project_column: str,
) -> tuple[str, list]:
    conditions = []
    params = []
    if date_from := scope.get("date_from"):
        conditions.append(f"{date_column} >= ?")
        params.append(date_from)
    if date_to := scope.get("date_to"):
        conditions.append(f"{date_column} <= ?")
        params.append(f"{date_to} 23:59:59")
    project_id = scope.get("project_id")
    if project_id == 0:
        conditions.append(f"{project_column} IS NULL")
    elif project_id is not None:
        conditions.append(f"{project_column} = ?")
        params.append(project_id)
    return " AND ".join(conditions) or "1=1", params


def _month_filters(month: str, scope: dict[str, str | int]) -> dict[str, str]:
    year, month_number = map(int, month.split("-"))
    start = f"{month}-01"
    end = f"{month}-{monthrange(year, month_number)[1]:02d}"
    return {
        "date_from": max(start, str(scope.get("date_from", start))),
        "date_to": min(end, str(scope.get("date_to", end))),
    }


def get_insights(
    conn: sqlite3.Connection,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    project_id: int | None = None,
) -> dict:
    scope = {k: v for k, v in {
        "date_from": date_from, "date_to": date_to, "project_id": project_id,
    }.items() if v is not None}
    event_where, event_params = _where(scope, "e.occurred_at", "e.project_id")
    cause = "NULLIF(TRIM(e.root_cause), '') IS NOT NULL"
    event_counts = conn.execute(
        f"""SELECT COUNT(*) AS events,
                   COUNT(CASE WHEN e.snapshot_at IS NOT NULL AND e.evidence_snapshot IS NOT NULL
                              THEN 1 END) AS snapshots,
                   COUNT(CASE WHEN {cause} THEN 1 END) AS with_cause,
                   COUNT(CASE WHEN {cause} AND e.root_cause_confirmed = 1 THEN 1 END) AS confirmed
            FROM work_events e WHERE {event_where}""",
        event_params,
    ).fetchone()

    def chart(
        select_sql: str, filters: Callable[[sqlite3.Row], dict[str, str | int]],
    ) -> list[dict]:
        rows = conn.execute(select_sql.format(where=event_where), event_params)
        return [
            {"label": row["label"], "value": row["value"], "filters": {**scope, **filters(row)}}
            for row in rows
        ]

    by_type = chart(
        "SELECT e.event_type AS label, COUNT(*) AS value FROM work_events e WHERE {where} "
        "AND COALESCE(e.source_agent, '') NOT IN ('jira-import', 'bitbucket-sync') "
        "GROUP BY e.event_type ORDER BY value DESC, label",
        lambda row: {"event_type": row["label"]},
    )
    by_repo = chart(
        "SELECT COALESCE(NULLIF(e.repo, ''), '(no repo)') AS label, "
        "COALESCE(e.repo, '') AS repo, COUNT(*) AS value FROM work_events e WHERE {where} "
        "GROUP BY COALESCE(e.repo, '') ORDER BY value DESC, label LIMIT 10",
        lambda row: {"repo": row["repo"]},
    )
    by_project = chart(
        "SELECT COALESCE(p.name, '(unassigned)') AS label, COALESCE(e.project_id, 0) AS project_id, "
        "COUNT(*) AS value FROM work_events e LEFT JOIN projects p ON e.project_id=p.id WHERE {where} "
        "GROUP BY e.project_id ORDER BY value DESC, label LIMIT 10",
        lambda row: {"project_id": row["project_id"]},
    )
    by_month = chart(
        "SELECT substr(e.occurred_at, 1, 7) AS label, COUNT(*) AS value FROM work_events e "
        "WHERE {where} GROUP BY label ORDER BY label",
        lambda row: _month_filters(row["label"], scope),
    )
    root_causes = chart(
        f"SELECT e.root_cause AS label, COUNT(*) AS value FROM work_events e WHERE {{where}} AND {cause} "
        "GROUP BY e.root_cause ORDER BY value DESC, label LIMIT 8",
        lambda row: {"root_cause": row["label"]},
    )
    by_source = chart(
        "SELECT CASE WHEN e.source_agent = 'jira-import' THEN 'jira' "
        "WHEN e.source_agent = 'bitbucket-sync' THEN 'bitbucket' ELSE 'human' END AS label, "
        "COUNT(*) AS value FROM work_events e WHERE {where} GROUP BY label ORDER BY value DESC, label",
        lambda row: {},
    )

    acc_where, acc_params = _where(scope, "a.occurred_at", "e.project_id")
    acc = conn.execute(
        "SELECT COUNT(*) AS total, COUNT(CASE WHEN a.is_highlight = 1 THEN 1 END) AS highlights "
        f"FROM accomplishments a LEFT JOIN work_events e ON a.event_id=e.id WHERE {acc_where}",
        acc_params,
    ).fetchone()
    case_where, case_params = _where(scope, "c.occurred_at", "e.project_id")
    cases = conn.execute(
        f"SELECT COUNT(*) FROM cases c LEFT JOIN work_events e ON c.event_id=e.id WHERE {case_where}",
        case_params,
    ).fetchone()[0]
    todo_where, todo_params = _where(scope, "t.created_at", "COALESCE(t.project_id, e.project_id)")
    todo_status = [
        dict(row) for row in conn.execute(
            "SELECT t.status AS label, COUNT(*) AS value FROM todos t "
            f"LEFT JOIN work_events e ON t.event_id=e.id WHERE {todo_where} GROUP BY t.status",
            todo_params,
        )
    ]
    return {
        "totals": {
            "events": event_counts["events"],
            "accomplishments": acc["total"],
            "cases": cases,
            "todos": sum(row["value"] for row in todo_status),
            "highlights": acc["highlights"],
            "snapshots": event_counts["snapshots"],
        },
        "by_type": by_type,
        "by_repo": by_repo,
        "by_project": by_project,
        "by_month": by_month,
        "root_causes": root_causes,
        "by_source": by_source,
        "todo_status": todo_status,
        "root_cause_confirmation": {
            "confirmed": event_counts["confirmed"],
            "with_cause": event_counts["with_cause"],
        },
    }
