"""Event source classification and mine-ownership filtering."""
from __future__ import annotations

import json
import sqlite3

from . import sync_state

SYNC_SOURCES = ("jira-import", "bitbucket-sync")


def event_source(source_agent: str | None) -> str:
    if source_agent == "jira-import":
        return "jira"
    if source_agent == "bitbucket-sync":
        return "bitbucket"
    return "human"


def my_identities(conn: sqlite3.Connection) -> tuple[str | None, str | None]:
    states = sync_state.get_states(conn)
    account_id = states.get("jira", {}).get("detail", {}).get("my_account_id")
    uuid = next(
        (s["detail"].get("my_uuid") for s in states.values()
         if s["source"].startswith("bitbucket:") and s["detail"].get("my_uuid")),
        None,
    )
    return account_id, uuid


def mine_predicate(conn: sqlite3.Connection, alias: str = "") -> tuple[str, list]:
    account_id, uuid = my_identities(conn)
    p = f"{alias}." if alias else ""
    sql = f"""(
  COALESCE({p}source_agent, '') NOT IN ('jira-import', 'bitbucket-sync')
  OR ({p}source_agent = 'jira-import'
      AND json_extract({p}extra_json, '$.assignee_account_id') = ?)
  OR ({p}source_agent = 'bitbucket-sync' AND (
        json_extract({p}extra_json, '$.author_uuid') = ?
        OR EXISTS (SELECT 1 FROM json_each(json_extract({p}extra_json, '$.reviewers'))
                   WHERE json_extract(value, '$.uuid') = ?)))
)"""
    return sql, [account_id, uuid, uuid]


def is_mine_row(source_agent: str | None, extra_json: str | None,
                account_id: str | None, uuid: str | None) -> bool:
    if source_agent not in SYNC_SOURCES:
        return True
    try:
        extra = json.loads(extra_json or "{}")
    except json.JSONDecodeError:
        extra = {}
    if not isinstance(extra, dict):
        return False
    if source_agent == "jira-import":
        return account_id is not None and extra.get("assignee_account_id") == account_id
    if uuid is None:
        return False
    if extra.get("author_uuid") == uuid:
        return True
    return any(r.get("uuid") == uuid for r in extra.get("reviewers") or [] if isinstance(r, dict))