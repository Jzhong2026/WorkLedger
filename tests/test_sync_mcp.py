from __future__ import annotations

import json

from workledger import mcp_server
from workledger.services import master_data


def test_mcp_sync_tools_and_summary(conn, monkeypatch):
    monkeypatch.setattr(mcp_server, "_conn", lambda: conn)
    master_data.create_project(conn, name="RW (Atlas)", key="RW")
    monkeypatch.setattr(
        "workledger.services.sync_jira.sync_jira",
        lambda c, **kw: {"source": "jira", "ok": True, "created": 0},
    )
    assert json.loads(mcp_server.sync_jira())["ok"] is True
    summary = json.loads(mcp_server.get_project_summary("RW", "7d"))
    assert summary["project"]["key"] == "RW"
    assert "sync" in summary
    status = json.loads(mcp_server.get_sync_status())
    assert isinstance(status, dict)
    missing = json.loads(mcp_server.get_project_summary("NOPE"))
    assert "error" in missing
