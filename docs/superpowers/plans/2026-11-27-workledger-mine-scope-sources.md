# WorkLedger「只看我的」视图、同步稳定性与来源区分 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** scope=mine 个人视图（summary/export/weekly）、Jira 同步稳定性（truncated 合并 + twg 重试）、按来源区分事件（insights/周报/导出）、前端同步状态 chip、周回顾自动带合并 PR 并幂等写 accomplishments。

**Architecture:** 新 services/sources.py 提供来源分类 + mine 归属谓词（SQL 用于 search_events，Python 纯函数用于 weekly 后过滤）。同步服务增量加固。前端 Vue3 组件遵循 AgentBoard 设计语言。

**Tech Stack:** Python 3.14 / FastAPI / SQLite(JSON1) / httpx / Vue 3 + vue-tsc / Chart.js

**Spec:** `docs/superpowers/specs/2026-11-27-workledger-mine-scope-sources-design.md`（必读，尤其 §2 不回退约束）

## Global Constraints

- 解释器 `.venv/Scripts/python.exe`；pytest 必须 `--basetemp="D:\tmp\Debug\pytest-workledger"`。
- Git：main，不新建分支；英文祈使句提交信息；每任务 commit 后 `git push origin main`（预授权；瞬时 SSH 中断重试一次）。
- 绝不提交 `.env`、`data/`、临时文件（临时产物放 `D:\tmp\Debug\`）。
- **不回退**：分页/分块刷新、历史 Done 不建 item、PR 锚点-only、accountId 归属、AIP-96 排除、event_type/stage CHECK 闭集、失败只记录不崩。
- scope 默认 "all"；非法值 422。身份缺失时 mine 分支不匹配（不猜）。
- 前端构建：`cd frontend && npm run build`（含 vue-tsc 类型检查）。UI 验证用无头 Chrome 截图，不开 GUI 窗口。
- 测试基线：当前 166 passed。

---

### Task 1: sources.py 基础 + search_events scope

**Files:**
- Create: `src/workledger/services/sources.py`
- Modify: `src/workledger/services/events.py`（search_events 加 scope 参数）
- Test: `tests/test_sources.py`

**Interfaces:**
- Produces:
  - `sources.event_source(source_agent: str | None) -> str`（"jira"/"bitbucket"/"human"）
  - `sources.my_identities(conn) -> tuple[str | None, str | None]`（account_id, uuid）
  - `sources.mine_predicate(conn, alias: str = "") -> tuple[str, list]`（SQL 片段 + [account_id, uuid, uuid]）
  - `sources.is_mine_row(source_agent: str | None, extra_json: str | None, account_id: str | None, uuid: str | None) -> bool`
  - `events.search_events(..., scope: str | None = None)`（"mine" 追加谓词；非法值 ValueError）

- [ ] **Step 1: 写失败测试** `tests/test_sources.py`

```python
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from workledger.schemas import EventCreate
from workledger.services import events, sources, sync_state


def _event(conn, summary, source_agent=None, extra=None, jira_key=None, repo=None, pr_number=None):
    return events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=datetime.now(UTC), summary=summary,
        source_agent=source_agent, jira_key=jira_key, repo=repo, pr_number=pr_number,
        extra_json=json.dumps(extra) if extra is not None else None,
    ))


def _identities(conn):
    sync_state.record_success(conn, "jira", {"my_account_id": "acc-jason"})
    sync_state.record_success(conn, "bitbucket:transfinderorg/core", {"my_uuid": "{jason}"})


def test_event_source_mapping():
    assert sources.event_source("jira-import") == "jira"
    assert sources.event_source("bitbucket-sync") == "bitbucket"
    assert sources.event_source("inbox") == "human"
    assert sources.event_source(None) == "human"


def test_is_mine_row():
    assert sources.is_mine_row(None, None, "acc-jason", "{jason}") is True
    assert sources.is_mine_row("jira-import", json.dumps({"assignee_account_id": "acc-jason"}), "acc-jason", "{jason}") is True
    assert sources.is_mine_row("jira-import", json.dumps({"assignee_account_id": "acc-other"}), "acc-jason", "{jason}") is False
    assert sources.is_mine_row("bitbucket-sync", json.dumps({"author_uuid": "{jason}"}), "acc-jason", "{jason}") is True
    assert sources.is_mine_row("bitbucket-sync", json.dumps({"author_uuid": "{o}", "reviewers": [{"uuid": "{jason}"}]}), "acc-jason", "{jason}") is True
    assert sources.is_mine_row("bitbucket-sync", json.dumps({"author_uuid": "{o}", "reviewers": []}), "acc-jason", "{jason}") is False
    assert sources.is_mine_row("jira-import", None, None, None) is False


def test_search_events_scope_mine(conn):
    _identities(conn)
    mine_ticket = _event(conn, "mine ticket", "jira-import", {"assignee_account_id": "acc-jason"}, jira_key="RW-1")
    _event(conn, "other ticket", "jira-import", {"assignee_account_id": "acc-other"}, jira_key="RW-2")
    mine_pr = _event(conn, "mine pr", "bitbucket-sync", {"author_uuid": "{jason}"}, repo="transfinderorg/core", pr_number=1)
    _event(conn, "reviewed pr", "bitbucket-sync", {"author_uuid": "{o}", "reviewers": [{"uuid": "{jason}"}]}, repo="transfinderorg/core", pr_number=2)
    _event(conn, "other pr", "bitbucket-sync", {"author_uuid": "{o}", "reviewers": []}, repo="transfinderorg/core", pr_number=3)
    human = _event(conn, "human note", None)
    items, total = events.search_events(conn, scope="mine")
    assert total == 4
    assert {i["id"] for i in items} == {mine_ticket["id"], mine_pr["id"], human["id"]} | {i["id"] for i in items if i["summary"] == "reviewed pr"}
    _, all_total = events.search_events(conn)
    assert all_total == 6
    with pytest.raises(ValueError):
        events.search_events(conn, scope="bogus")


def test_search_events_mine_without_identities_keeps_human(conn):
    _event(conn, "jira row", "jira-import", {"assignee_account_id": "acc-jason"})
    human = _event(conn, "human note", None)
    items, total = events.search_events(conn, scope="mine")
    assert total == 1
    assert items[0]["id"] == human["id"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sources.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

`src/workledger/services/sources.py`:
```python
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
```

`events.py` search_events：签名加 `scope: str | None = None`（放 raw_match 后）；函数体开头（conditions 初始化后）加：
```python
    if scope not in (None, "all", "mine"):
        raise ValueError("Scope must be 'all' or 'mine'.")
    if scope == "mine":
        from . import sources
        mine_sql, mine_params = sources.mine_predicate(conn)
        conditions.append(mine_sql)
        params.extend(mine_params)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sources.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 4 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`（Expected: 170 passed）
```bash
git add src/workledger/services/sources.py src/workledger/services/events.py tests/test_sources.py
git commit -m "Add event source classification and mine-ownership filtering"
git push origin main
```

---

### Task 2: scope=mine 三端点 + MCP

**Files:**
- Modify: `src/workledger/services/summary.py`（scope 参数 + 过滤 + scope 响应字段；my_uuid 改用 sources.my_identities）
- Modify: `src/workledger/services/export.py`（export_markdown/_render_export/narrative_input 加 scope；events 段传 scope）
- Modify: `src/workledger/services/work_review.py`（weekly_review/_weekly_snapshot 加 scope；SELECT 加 e.extra_json；Python 后过滤）
- Modify: `src/workledger/routers/summary.py`、`src/workledger/routers/api.py`（export/narrative）、`src/workledger/routers/work_review.py`（weekly）
- Modify: `src/workledger/routers/inputs.py`（NarrativeRequest 加 scope）
- Modify: `src/workledger/mcp_server.py`（get_project_summary/get_weekly_review/export_retrospective 加 scope）
- Test: `tests/test_scope_mine.py`

**Interfaces:**
- Consumes: Task 1 `sources.my_identities/is_mine_row/mine_predicate`、`search_events(scope=…)`
- Produces: `project_summary(conn, key, window="7d", scope="all")`；`export_markdown(conn, period="year", *, today=None, scope="all")`；`weekly_review(conn, day=None, project_id=None, scope="all")`；三端点 `scope` Query 参数 `Literal["all","mine"]` 默认 "all"

- [ ] **Step 1: 写失败测试** `tests/test_scope_mine.py`

```python
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workledger.db import get_connection
from workledger.routers import summary as summary_router
from workledger.schemas import AccomplishmentCreate, EventCreate
from workledger.services import events, master_data, retrospectives, summary, sync_state, work_review
from workledger.services import export as export_service


@pytest.fixture()
def seeded(conn):
    sync_state.record_success(conn, "jira", {"my_account_id": "acc-jason"})
    sync_state.record_success(conn, "bitbucket:transfinderorg/core", {"my_uuid": "{jason}"})
    rw = master_data.create_project(conn, name="RW (Atlas)", key="RW")
    now = datetime.now(UTC)
    events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=now, summary="My ticket", source_agent="jira-import",
        jira_key="RW-1", project_id=None,
        extra_json=json.dumps({"assignee_account_id": "acc-jason", "status": "In Progress", "status_category": "indeterminate"}),
    ))
    events.create_event(conn, EventCreate(
        event_type="manual", occurred_at=now, summary="Other ticket", source_agent="jira-import",
        jira_key="RW-2",
        extra_json=json.dumps({"assignee_account_id": "acc-other", "status": "In Progress", "status_category": "indeterminate"}),
    ))
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=now, summary="My PR", source_agent="bitbucket-sync",
        repo="transfinderorg/core", pr_number=1,
        extra_json=json.dumps({"state": "OPEN", "author_uuid": "{jason}", "reviewers": [], "bitbucket_updated": now.isoformat()}),
    ))
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=now, summary="Other PR", source_agent="bitbucket-sync",
        repo="transfinderorg/core", pr_number=2,
        extra_json=json.dumps({"state": "OPEN", "author_uuid": "{o}", "reviewers": [], "bitbucket_updated": now.isoformat()}),
    ))
    conn.execute("UPDATE work_events SET project_id=? WHERE jira_key IS NOT NULL OR repo IS NOT NULL", (rw["id"],))
    retrospectives.create_accomplishment(conn, AccomplishmentCreate(title="Manual win", occurred_at=now))
    return rw


def test_summary_mine_filters_tickets_and_prs(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d", scope="mine")
    assert result["scope"] == "mine"
    assert {t["key"] for t in result["tickets"]["open"]} == {"RW-1"}
    assert result["tickets"]["counts"]["open"] == 1
    assert {p["pr_number"] for p in result["prs"]["items"]} == {1}
    all_result = summary.project_summary(conn, "RW", "7d")
    assert all_result["scope"] == "all"
    assert all_result["tickets"]["counts"]["open"] == 2
    with pytest.raises(ValueError):
        summary.project_summary(conn, "RW", "7d", scope="bogus")


def test_export_mine_filters_events_keeps_accomplishments(seeded, conn):
    md = export_service.export_markdown(conn, "all", scope="mine")
    assert "My ticket" in md and "My PR" in md
    assert "Other ticket" not in md and "Other PR" not in md
    assert "Manual win" in md


def test_weekly_mine_filters_groups(seeded, conn):
    result = work_review.weekly_review(conn, scope="mine")
    summaries = [e["summary"] for g in result["groups"] for e in g["events"]]
    assert "My ticket" in summaries and "My PR" in summaries
    assert "Other ticket" not in summaries and "Other PR" not in summaries
    assert len(result["accomplishments"]) == 1


def test_summary_router_scope_validation(seeded, conn, monkeypatch):
    app = FastAPI()
    app.include_router(summary_router.router, prefix="/api")
    monkeypatch.setattr(summary_router, "_conn", lambda: conn)
    with TestClient(app) as client:
        assert client.get("/api/summary/project?key=RW&scope=mine").json()["scope"] == "mine"
        assert client.get("/api/summary/project?key=RW&scope=bogus").status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scope_mine.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（TypeError: unexpected keyword 'scope'）

- [ ] **Step 3: 实现**

**summary.py**：签名 `def project_summary(conn, key, window="7d", scope="all")`；开头加 `if scope not in ("all", "mine"): raise ValueError("Scope must be 'all' or 'mine'.")`；`my_uuid` 提取改为 `account_id, my_uuid = sources.my_identities(conn)`（import sources）；ticket rows 取出后：
```python
    if scope == "mine":
        ticket_rows = [r for r in ticket_rows
                       if json.loads(r["extra_json"] or "{}").get("assignee_account_id") == account_id]
```
（ticket_rows 是 fetchall() 列表；tickets 列表推导基于它。）prs 列表构建完成后：
```python
    if scope == "mine":
        prs = [p for p in prs if p["mine"]["authored"] or p["mine"]["reviewing"]]
```
返回 dict 加 `"scope": scope`。

**export.py**：`_render_export(conn, period, *, max_chars=None, today=None, scope="all")`；循环内 events 段用独立 window：
```python
        first_pages = [fetch(conn, **({**window, "scope": scope} if key == "events" else window))
                       for key, _, fetch in _SECTIONS]
```
分页 fetch 同样：`rows, _ = fetch(conn, page=page, **({**window, "scope": scope} if key == "events" else window))`。
`export_markdown(conn, period="year", *, today=None, scope="all")` 与 `narrative_input(conn, period="year", *, max_chars=_NARRATIVE_CHARS, today=None, scope="all")` 透传。

**work_review.py**：`weekly_review(conn, day=None, project_id=None, scope="all")` → `_weekly_snapshot(conn, day or date.today(), project_id, scope)`；SELECT 列表加 `e.extra_json`；rows 取出后：
```python
    if scope == "mine":
        from . import sources
        account_id, uuid = sources.my_identities(conn)
        rows = [r for r in rows if sources.is_mine_row(r["source_agent"], r["extra_json"], account_id, uuid)]
```
（rows 是 fetchall()；scope 非法值 ValueError 同 summary。）

**routers/summary.py**：`from typing import Literal`；`def get_project_summary(key: str, window: str = "7d", scope: Literal["all", "mine"] = "all")` 透传。
**routers/api.py** export_markdown 端点加 `scope: Literal["all", "mine"] = "all"` 透传；export_narrative 用 `data.scope`。
**routers/inputs.py** NarrativeRequest 加 `scope: Literal["all", "mine"] = "all"`（检查该文件已有 Literal 导入）。
**routers/work_review.py** weekly 端点加 `scope: Literal["all", "mine"] = "all"` 透传。
**mcp_server.py**：`get_project_summary(key, window="7d", scope="all")`、`get_weekly_review(day=None, project_id=None, scope="all")`、`export_retrospective` 加 `scope: str = "all"` 并透传（先读现有 export_retrospective 签名再改）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_scope_mine.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 4 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`（Expected: 174 passed）
```bash
git add src/workledger/services/summary.py src/workledger/services/export.py src/workledger/services/work_review.py src/workledger/routers/summary.py src/workledger/routers/api.py src/workledger/routers/work_review.py src/workledger/routers/inputs.py src/workledger/mcp_server.py tests/test_scope_mine.py
git commit -m "Add scope=mine view to summary, export, and weekly review"
git push origin main
```

---

### Task 3: Jira 同步稳定性（truncated 合并 + twg 重试）

**Files:**
- Modify: `src/workledger/services/sync_jira.py`
- Test: `tests/test_sync_stability.py`

**Interfaces:**
- Consumes: 现有 sync_jira 结构（scope_issues/issues/missing/dedupe）
- Produces: `_twg_runner` 重试语义（3 次尝试，退避 1s/3s）；truncated 时 currentUser() 全量合并

- [ ] **Step 1: 写失败测试** `tests/test_sync_stability.py`

```python
from __future__ import annotations

import json
import subprocess

import pytest

from workledger.services import sync_jira


def test_twg_runner_retries_transient_failures(monkeypatch):
    calls = []
    sleeps = []

    class Result:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def fake_run(args, **kwargs):
        calls.append(args)
        if len(calls) < 3:
            raise OSError("socket disconnect")
        return Result(0, "ok-output")

    monkeypatch.setattr(sync_jira.subprocess, "run", fake_run)
    monkeypatch.setattr(sync_jira, "sleep", lambda s: sleeps.append(s))
    assert sync_jira._twg_runner(["jira"]) == "ok-output"
    assert len(calls) == 3
    assert sleeps == [1, 3]


def test_twg_runner_gives_up_after_three(monkeypatch):
    def fake_run(args, **kwargs):
        raise OSError("socket disconnect")
    monkeypatch.setattr(sync_jira.subprocess, "run", fake_run)
    monkeypatch.setattr(sync_jira, "sleep", lambda s: None)
    with pytest.raises(OSError):
        sync_jira._twg_runner(["jira"])


def test_truncated_merges_current_user_query(conn, tmp_path, monkeypatch):
    monkeypatch.setattr(sync_jira, "LIMIT", 2)
    monkeypatch.setattr(sync_jira, "PAGE_SIZE", 2)
    calls = []

    def runner(args):
        calls.append(args)
        jql = args[args.index("--jql") + 1]
        if "assignee = currentUser()" in jql and "updated >=" not in jql:
            issues = [{"key": "RW-777", "summary": "Deep mine", "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                       "assignee": {"accountId": "acc-jason", "displayName": "JasonZhong"},
                       "created": "2026-01-01T00:00:00.000-0500", "updated": "2026-01-02T00:00:00.000-0500"}]
        else:
            issues = [{"key": f"RW-{n}", "summary": f"S{n}", "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}},
                       "assignee": {"accountId": "acc-other", "displayName": "Other"},
                       "created": "2026-11-01T00:00:00.000-0500", "updated": "2026-11-2{n}T00:00:00.000-0500"} for n in (1, 2)]
        payload = tmp_path / f"p{len(calls)}.json"
        payload.write_text(json.dumps({"data": {"issues": issues}}), encoding="utf-8")
        return f'output_files:\n  stdout: "{payload}"\n'

    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["ok"] is True
    assert result["truncated"] is True
    mine_calls = [a for a in calls if "assignee = currentUser()" in a[a.index("--jql") + 1] and "updated >=" not in a[a.index("--jql") + 1]]
    assert len(mine_calls) == 1
    assert conn.execute("SELECT 1 FROM work_events WHERE jira_key='RW-777'").fetchone() is not None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_stability.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（无 sleep 属性/无重试/无 currentUser 合并）

- [ ] **Step 3: 实现**

`sync_jira.py` 顶部加 `from time import sleep`。`_twg_runner` 替换为：
```python
def _twg_runner(args: list[str]) -> str:
    last: Exception | None = None
    for attempt in range(3):
        try:
            result = subprocess.run(
                [settings.twg_cli_path, *args],
                capture_output=True, text=True, encoding="utf-8", timeout=120,
            )
            if result.returncode == 0:
                return result.stdout
            last = ValueError(f"twg exited {result.returncode}: {(result.stderr or result.stdout)[:500]}")
        except (subprocess.TimeoutExpired, OSError) as exc:
            last = exc
        if attempt < 2:
            sleep(1 if attempt == 0 else 3)
    raise last
```
sync_jira 内 missing-refresh 之后、dedupe 之前加：
```python
        if len(scope_issues) >= LIMIT:
            mine_jql = f"project in ({', '.join(project_keys)})"
            if exclude_keys:
                mine_jql += f" AND key not in ({', '.join(exclude_keys)})"
            mine_jql += " AND assignee = currentUser() ORDER BY updated DESC"
            issues.extend(_fetch_issues(runner, mine_jql))
```
（变量名以现有代码为准：scope_issues 是 scope 查询结果列表；issues 是合并列表。先读现有 sync_jira 再插入。）
**同时把 sync_jira 内主 scope 查询的 `_fetch_issues(runner, scope_jql)` 改为显式 `_fetch_issues(runner, scope_jql, limit=LIMIT)`**——默认参数在 def 时绑定，显式传参才能让测试 monkeypatch LIMIT 生效（探测查询的 limit=1 不变）。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_stability.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 3 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`（Expected: 177 passed）
```bash
git add src/workledger/services/sync_jira.py tests/test_sync_stability.py
git commit -m "Harden Jira sync with truncation merge and twg retries"
git push origin main
```

---

### Task 4: 来源区分后端（insights/weekly/export）

**Files:**
- Modify: `src/workledger/services/insights.py`（by_source + by_type 人工-only）
- Modify: `src/workledger/services/work_review.py`（event row 加 source 字段）
- Modify: `src/workledger/services/export.py`（events 段子节渲染，仅 max_chars=None）
- Test: `tests/test_source_separation.py`

**Interfaces:**
- Consumes: Task 1 `sources.event_source`
- Produces: insights 返回加 `"by_source"`；weekly event dict 加 `"source"`；export markdown events 段含 `### Human records` / `### Jira snapshots` / `### Bitbucket PRs` 子节

- [ ] **Step 1: 写失败测试** `tests/test_source_separation.py`

```python
from __future__ import annotations

from datetime import UTC, datetime

from workledger.schemas import EventCreate
from workledger.services import events, export, insights, work_review


def _seed(conn):
    now = datetime.now(UTC)
    for agent, summary in (("jira-import", "Jira snap"), ("jira-import", "Jira snap 2"),
                           ("bitbucket-sync", "PR anchor"), (None, "Human note")):
        events.create_event(conn, EventCreate(
            event_type="manual", occurred_at=now, summary=summary, source_agent=agent,
        ))


def test_insights_by_source_and_human_only_by_type(conn):
    _seed(conn)
    result = insights.get_insights(conn)
    by_source = {r["label"]: r["value"] for r in result["by_source"]}
    assert by_source == {"jira": 2, "bitbucket": 1, "human": 1}
    by_type = {r["label"]: r["value"] for r in result["by_type"]}
    assert by_type == {"manual": 1}  # 同步快照不再灌进 manual


def test_weekly_events_carry_source(conn):
    _seed(conn)
    result = work_review.weekly_review(conn)
    sources_by_summary = {e["summary"]: e["source"] for g in result["groups"] for e in g["events"]}
    assert sources_by_summary["Jira snap"] == "jira"
    assert sources_by_summary["PR anchor"] == "bitbucket"
    assert sources_by_summary["Human note"] == "human"


def test_export_events_subsections(conn):
    _seed(conn)
    md = export.export_markdown(conn, "all")
    assert "### Human records (1)" in md
    assert "### Jira snapshots (2)" in md
    assert "### Bitbucket PRs (1)" in md
    assert md.index("### Human records") < md.index("### Jira snapshots") < md.index("### Bitbucket PRs")


def test_export_empty_sources_omitted(conn):
    events.create_event(conn, EventCreate(event_type="manual", occurred_at=datetime.now(UTC), summary="Only human"))
    md = export.export_markdown(conn, "all")
    assert "### Human records (1)" in md
    assert "### Jira snapshots" not in md
    assert "### Bitbucket PRs" not in md


def test_narrative_input_stays_flat(conn):
    _seed(conn)
    md, coverage = export.narrative_input(conn, "all")
    assert "### Human records" not in md
    assert coverage["totals"]["events"] == 4
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_source_separation.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（KeyError 'by_source' 等）

- [ ] **Step 3: 实现**

**insights.py**：by_type 的 select_sql 改为
`"SELECT e.event_type AS label, COUNT(*) AS value FROM work_events e WHERE {where} AND COALESCE(e.source_agent, '') NOT IN ('jira-import', 'bitbucket-sync') GROUP BY e.event_type ORDER BY value DESC, label"`；
新增 by_source chart（root_causes 之后）：
```python
    by_source = chart(
        "SELECT CASE WHEN e.source_agent = 'jira-import' THEN 'jira' "
        "WHEN e.source_agent = 'bitbucket-sync' THEN 'bitbucket' ELSE 'human' END AS label, "
        "COUNT(*) AS value FROM work_events e WHERE {where} GROUP BY label ORDER BY value DESC, label",
        lambda row: {},
    )
```
返回 dict 加 `"by_source": by_source`。

**work_review.py**：group events append 处 `group["events"].append({**dict(row), "source": event_source(row["source_agent"])})`（from .sources import event_source）。

**export.py**：`_render_export` 的渲染循环里，events 段且 max_chars is None 时走子节路径：
```python
        for key, heading, fetch, rows, total in rendered:
            if key == "events" and max_chars is None:
                all_rows = list(rows)
                page = 1
                while page * _PAGE_SIZE < total:
                    page += 1
                    more, _ = fetch(conn, page=page, **window)
                    all_rows.extend(more)
                blocks = []
                for src, sub in (("human", "Human records"), ("jira", "Jira snapshots"), ("bitbucket", "Bitbucket PRs")):
                    src_rows = [r for r in all_rows if event_source(r.get("source_agent")) == src]
                    if src_rows:
                        blocks.append(f"### {sub} ({len(src_rows)})")
                        blocks.extend(_render_record(conn, key, r) for r in src_rows)
                included[key] = len(all_rows)
                parts.append(f"## {heading} ({total})")
                parts.append("\n\n".join(blocks) if blocks else "_None recorded in this period._")
                continue
            # …现有循环体不变…
```
（from .sources import event_source；events 段 window 已含 scope（Task 2），子节路径复用同一 window。）

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_source_separation.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 5 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`（Expected: 182 passed）
```bash
git add src/workledger/services/insights.py src/workledger/services/work_review.py src/workledger/services/export.py tests/test_source_separation.py
git commit -m "Separate event sources in insights, weekly review, and export"
git push origin main
```

---

### Task 5: 前端 SyncStatus chip

**Files:**
- Create: `frontend/src/components/SyncStatus.vue`
- Modify: `frontend/src/components/AppLayout.vue`（topbar-right 插入）
- Modify: `frontend/src/api/client.ts`（syncStatus/syncAll）
- Modify: `frontend/src/types/index.ts`（SyncSourceState）
- Modify: `frontend/src/assets/main.css`（chip/panel 样式，复用变量）

**Interfaces:**
- Consumes: `GET /api/sync/status`（{source: {last_success_at, stale, last_error, detail, …}}）、`POST /api/sync`
- Produces: topbar 同步状态 chip + 展开面板 + Sync now

- [ ] **Step 1: api + types**

`types/index.ts` 追加：
```typescript
export interface SyncSourceState {
  source: string
  last_attempt_at: string | null
  last_success_at: string | null
  last_error: string | null
  stale: boolean
  detail: Record<string, unknown>
}
export type SyncStatusMap = Record<string, SyncSourceState>
```
`client.ts` api 对象追加（Insights & agent 注释块附近）：
```typescript
  syncStatus: () => get<SyncStatusMap>('/sync/status'),
  syncAll: () => post<{ ok: boolean; jira: unknown; bitbucket: unknown }>('/sync'),
```
（import 类型按现有模式补 SyncStatusMap。）

- [ ] **Step 2: SyncStatus.vue**

```vue
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, errorMessage } from '@/api/client'
import { useToast } from '@/stores/toast'
import type { SyncStatusMap } from '@/types'

const toast = useToast()
const states = ref<SyncStatusMap | null>(null)
const open = ref(false)
const syncing = ref(false)
const root = ref<HTMLElement | null>(null)
let timer: ReturnType<typeof setInterval> | undefined

const rows = computed(() => Object.values(states.value ?? {}))
const tone = computed(() => {
  if (!rows.value.length) return 'idle'
  if (rows.value.some(r => r.last_error)) return 'error'
  if (rows.value.some(r => r.stale)) return 'stale'
  return 'ok'
})
const label = computed(() => ({ ok: 'Sync fresh', stale: 'Sync stale', error: 'Sync error', idle: 'Sync' }[tone.value]))

function shortName(source: string) {
  return source.startsWith('bitbucket:') ? source.split('/').pop() ?? source : source
}
function relative(iso: string | null) {
  if (!iso) return 'never'
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`
}
async function refresh() {
  try { states.value = await api.syncStatus() } catch { /* chip stays idle on failure */ }
}
async function syncNow() {
  if (syncing.value) return
  syncing.value = true
  try {
    await api.syncAll()
    toast.success('Sync complete')
  } catch (err) {
    toast.error(errorMessage(err))
  } finally {
    syncing.value = false
    await refresh()
  }
}
function onDocClick(event: MouseEvent) {
  if (open.value && root.value && !root.value.contains(event.target as Node)) open.value = false
}
function onFocus() { void refresh() }
onMounted(() => {
  void refresh()
  timer = setInterval(refresh, 60000)
  document.addEventListener('click', onDocClick)
  window.addEventListener('focus', onFocus)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  document.removeEventListener('click', onDocClick)
  window.removeEventListener('focus', onFocus)
})
</script>

<template>
  <div ref="root" class="sync-status">
    <button type="button" class="sync-chip" :class="`tone-${tone}`" :aria-expanded="open" @click="open = !open">
      <span class="sync-dot" aria-hidden="true"></span>{{ label }}
    </button>
    <div v-if="open" class="sync-panel" role="dialog" aria-label="Sync status">
      <p v-if="!rows.length" class="meta">No sync sources recorded yet.</p>
      <div v-for="r in rows" :key="r.source" class="sync-row">
        <div class="sync-row-head">
          <strong>{{ shortName(r.source) }}</strong>
          <span v-if="r.stale" class="sync-badge stale">stale</span>
          <span v-if="r.last_error" class="sync-badge error">error</span>
        </div>
        <span class="meta">Last success: {{ relative(r.last_success_at) }}</span>
        <p v-if="r.last_error" class="sync-error">{{ r.last_error }}</p>
      </div>
      <button type="button" class="ghost-btn sync-now" :disabled="syncing" @click="syncNow">
        {{ syncing ? 'Syncing…' : 'Sync now' }}
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: AppLayout + CSS**

AppLayout.vue：import SyncStatus；topbar-right 内 command-trigger 按钮之前插入 `<SyncStatus />`。
main.css 追加（复用变量，AgentBoard 风）：
```css
.sync-status { position: relative; display: inline-flex; }
.sync-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-full); color: var(--text-2); font-size: .78rem; cursor: pointer; }
.sync-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); }
.tone-ok .sync-dot { background: #10b981; }
.tone-stale .sync-dot { background: #f59e0b; }
.tone-error .sync-dot { background: #ef4444; }
.sync-panel { position: absolute; top: calc(100% + 8px); right: 0; width: 300px; max-height: 360px; overflow-y: auto; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md, 10px); box-shadow: var(--sh-md, 0 8px 24px rgba(0,0,0,.18)); padding: 12px; z-index: 200; }
.sync-row { padding: 8px 0; border-bottom: 1px solid var(--border); }
.sync-row-head { display: flex; align-items: center; gap: 6px; }
.sync-badge { font-size: .68rem; padding: 1px 6px; border-radius: var(--r-full); }
.sync-badge.stale { background: rgba(245,158,11,.15); color: #b45309; }
.sync-badge.error { background: rgba(239,68,68,.15); color: #b91c1c; }
.sync-error { font-size: .72rem; color: #b91c1c; margin: 4px 0 0; overflow-wrap: anywhere; max-height: 3.6em; overflow: hidden; }
.sync-now { width: 100%; margin-top: 10px; }
```
（若 --r-md/--sh-md 变量不存在，用括号内 fallback——已写。）

- [ ] **Step 4: 构建 + 无头截图验证**

Run: `cd frontend && npm run build`（vue-tsc 必须过）
重启服务加载新 dist（taskkill 旧 PID + Start-Process 脱离启动，同前例）。
无头截图（不开 GUI）：
```bash
"/c/Program Files/Google/Chrome/Application/chrome.exe" --headless --disable-gpu --screenshot="D:\tmp\Debug\workledger-sync-chip.png" --window-size=1440,900 --virtual-time-budget=4000 http://127.0.0.1:8600/
```
（Chrome 路径以实测为准；Read 截图确认 chip 渲染。面板交互截图可选：--run-all-compositor-stages-before-draw + JS 点击难控，chip 静态确认即可，面板逻辑靠类型检查 + live 冒烟 T8 人工确认。）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/SyncStatus.vue frontend/src/components/AppLayout.vue frontend/src/api/client.ts frontend/src/types/index.ts frontend/src/assets/main.css
git commit -m "Add topbar sync status chip with per-source freshness panel"
git push origin main
```

---

### Task 6: 周回顾合并 PR + accomplishments

**Files:**
- Modify: `src/workledger/services/work_review.py`（weekly OR 分支）
- Modify: `src/workledger/services/sync_bitbucket.py`（merge 收集 + accomplishment 写入）
- Modify: `src/workledger/config.py`（sync_record_merge_accomplishments: bool = True）
- Test: `tests/test_weekly_merges.py`

**Interfaces:**
- Consumes: Task 4 weekly source 字段；retrospectives.create_accomplishment（source_key 幂等）；AccomplishmentCreate
- Produces: weekly 含本周 MERGED PR（按 bitbucket_updated）；sync 时幂等 accomplishment（source_key=`bitbucket-merge:{repo}:pr:{id}`）

- [ ] **Step 1: 写失败测试** `tests/test_weekly_merges.py`

```python
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from workledger.config import settings
from workledger.schemas import EventCreate
from workledger.services import events, master_data, sync_bitbucket, work_review

JASON = "{jason-uuid}"


def _anchor(conn, pr_id, state, updated, created="2026-01-01T00:00:00+00:00", jira_key="RW-50"):
    return events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=datetime.fromisoformat(created),
        repo="transfinderorg/core", pr_number=pr_id, jira_key=jira_key,
        source_key=f"bitbucket:transfinderorg/core:pr:{pr_id}", source_agent="bitbucket-sync",
        summary=f"feat(RW-50): PR {pr_id}",
        extra_json=json.dumps({"state": state, "bitbucket_updated": updated,
                               "author_uuid": JASON, "reviewers": [], "jira_keys": [jira_key]}),
    ))


def test_weekly_includes_merged_pr_by_update_window(conn):
    monday = date.today() - timedelta(days=date.today().weekday())
    merged_at = (monday + timedelta(days=2)).isoformat() + "T12:00:00+00:00"
    _anchor(conn, 1, "MERGED", merged_at)                       # 本周合并，创建很久以前
    _anchor(conn, 2, "MERGED", "2026-01-05T00:00:00+00:00")     # 旧合并，不进
    _anchor(conn, 3, "OPEN", merged_at)                          # OPEN 不按合并进
    result = work_review.weekly_review(conn)
    pr_groups = [g for g in result["groups"] if g["title"] == "RW-50"]
    assert pr_groups, "merged PR should group under its Jira key"
    ids = [e["pr_number"] for g in result["groups"] for e in g["events"] if e.get("pr_number")]
    assert 1 in ids and 2 not in ids and 3 not in ids


@pytest.fixture()
def bb(monkeypatch, conn):
    monkeypatch.setattr(settings, "atlassian_user_email", "j@example.com")
    monkeypatch.setattr(settings, "atlassian_api_token", "t")
    monkeypatch.setattr(settings, "sync_bitbucket_workspace", "transfinderorg")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    monkeypatch.setattr(settings, "sync_bitbucket_project", "RW")
    monkeypatch.setattr(settings, "sync_record_merge_accomplishments", True)
    master_data.create_project(conn, name="RW", key="RW")


def _pr(state, updated):
    return {"id": 9, "title": "feat(RW-50): x", "state": state,
            "created_on": "2026-11-01T00:00:00+00:00", "updated_on": updated,
            "author": {"display_name": "JasonZhong", "uuid": JASON}, "reviewers": [],
            "links": {"html": {"href": "https://bitbucket.org/transfinderorg/core/pull-requests/9"}},
            "source": {"branch": {"name": "feat"}}, "destination": {"branch": {"name": "main"}}}


def _client(prs):
    def handler(request):
        if request.url.path == "/2.0/user":
            return httpx.Response(200, json={"uuid": JASON})
        return httpx.Response(200, json={"values": prs})
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitbucket.org/2.0")


def test_merge_transition_writes_idempotent_accomplishment(conn, bb):
    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("OPEN", recent)]))
    assert conn.execute("SELECT COUNT(*) FROM accomplishments").fetchone()[0] == 0
    newer = datetime.now(UTC).isoformat()
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("MERGED", newer)]))
    rows = conn.execute("SELECT * FROM accomplishments").fetchall()
    assert len(rows) == 1
    assert rows[0]["source_key"] == "bitbucket:transfinderorg/core:pr:9".replace("bitbucket:", "bitbucket-merge:", 1)
    assert rows[0]["event_id"] is not None
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("MERGED", newer)]))
    assert conn.execute("SELECT COUNT(*) FROM accomplishments").fetchone()[0] == 1


def test_merge_accomplishments_can_be_disabled(conn, bb, monkeypatch):
    monkeypatch.setattr(settings, "sync_record_merge_accomplishments", False)
    recent = datetime.now(UTC).isoformat()
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr("MERGED", recent)]))
    assert conn.execute("SELECT COUNT(*) FROM accomplishments").fetchone()[0] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_weekly_merges.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL

- [ ] **Step 3: 实现**

**config.py** 加 `sync_record_merge_accomplishments: bool = True`。

**work_review.py** `_weekly_snapshot` WHERE 改为：
```sql
        WHERE (e.occurred_at >= :start AND e.occurred_at < :stop
               OR (e.source_agent = 'bitbucket-sync' AND e.event_type = 'pr_created'
                   AND json_extract(e.extra_json, '$.state') = 'MERGED'
                   AND substr(json_extract(e.extra_json, '$.bitbucket_updated'), 1, 10) >= :start
                   AND substr(json_extract(e.extra_json, '$.bitbucket_updated'), 1, 10) < :stop))
          AND (:project IS NULL OR i.id IS NOT NULL OR e.project_id = :project)
```

**sync_bitbucket.py**：
- import `from . import retrospectives`、`from ..schemas import AccomplishmentCreate, EventCreate`（EventCreate 已有）。
- `_upsert_pr(conn, pr, repo_full, project_id, pattern, merges=None)`：在 metadata.update 之前取 `prev_state = metadata.get("state")`；创建/更新路径拿到 event id 后：
```python
    if merges is not None and pr["state"] == "MERGED" and (original is None or prev_state != "MERGED"):
        merges.append({"pr_id": pr_id, "title": title, "updated_on": pr["updated_on"],
                       "url": url, "event_id": event_id, "repo_full": repo_full,
                       "author": metadata.get("author"),
                       "branches": f"{metadata.get('source_branch') or '?'} → {metadata.get('target_branch') or '?'}"})
```
（created 路径 event_id=event["id"]；updated 路径 event_id=original["id"]；unchanged 路径不收集。）
- sync 循环：`merges: list[dict] = []`；`_upsert_pr(..., merges)`；**write_transaction 块之后**：
```python
                if settings.sync_record_merge_accomplishments:
                    for m in merges:
                        retrospectives.create_accomplishment(conn, AccomplishmentCreate(
                            title=f"PR #{m['pr_id']} merged: {m['title']}",
                            description=f"{m['repo_full']} · {m['author'] or '?'} · {m['branches']}",
                            occurred_at=datetime.fromisoformat(m["updated_on"]),
                            impact_evidence_url=m["url"], event_id=m["event_id"],
                            tags="pr,merged",
                            source_key=f"bitbucket-merge:{m['repo_full']}:pr:{m['pr_id']}",
                        ))
```
detail 加 `"merges_recorded": len(merges)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_weekly_merges.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 3 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`（Expected: 185 passed）
```bash
git add src/workledger/services/work_review.py src/workledger/services/sync_bitbucket.py src/workledger/config.py tests/test_weekly_merges.py
git commit -m "Include merged PRs in weekly review and record merge accomplishments"
git push origin main
```

---

### Task 7: 前端来源展示 + WeeklyView Mine/All

**Files:**
- Modify: `frontend/src/views/InsightsView.vue`（By source chart）
- Modify: `frontend/src/types/index.ts`（Insights 加 by_source）
- Modify: `frontend/src/views/WeeklyView.vue`（Mine/All 切换 + 来源 badge + Evidence.source）

**Interfaces:**
- Consumes: Task 4 insights.by_source、weekly event.source；Task 2 weekly scope 参数
- Produces: InsightsView "By source" doughnut；WeeklyView mine 切换（query 参数 scope）+ 事件来源 badge

- [ ] **Step 1: types + InsightsView**

types/index.ts Insights 接口加 `by_source: ChartRow[]`（ChartRow 为该文件现有 chart row 类型名，先读确认；若叫别的名字用现有的）。
InsightsView.vue chart-grid 内 "By event type" 卡片后加：
```html
      <section class="card chart-card">
        <h2>By source</h2>
        <ChartBox type="doughnut" :rows="data.by_source" />
      </section>
```

- [ ] **Step 2: WeeklyView**

Evidence 接口加 `source?: string`。
script：`const mine = ref(false)`；scope computed 改为：
```typescript
const scope = computed(() => ({day: day.value || undefined, project_id: project.value || undefined, scope: mine.value ? 'mine' : 'all'}))
```
template form-grid-2 加第三个 field（或 card-actions 上方）：
```html
      <label class="field">Scope<select v-model="mine"><option :value="false">All activity</option><option :value="true">Mine only</option></select></label>
```
（form-grid-2 改 form-grid-3 若存在，否则保持两列自动换行——读 main.css 确认 grid 类。）
事件行 meta span 前加 badge：
```html
        <span v-if="e.source" class="source-badge" :class="`src-${e.source}`">{{ e.source }}</span>
```
scoped style：
```css
.source-badge { font-size: .68rem; padding: 1px 6px; border-radius: 999px; margin-right: 4px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-3); }
.src-jira { color: #2563eb; }
.src-bitbucket { color: #059669; }
```
download() 的 Recorded activity 行可选带 source（`e.source ? ' ['+e.source+']' : ''`）。

- [ ] **Step 3: 构建 + 截图**

Run: `cd frontend && npm run build`
重启服务；无头截图 `/insights` 与 `/weekly?scope=mine`（路由 URL 直接命中）确认渲染。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/views/InsightsView.vue frontend/src/views/WeeklyView.vue frontend/src/types/index.ts
git commit -m "Show event sources in insights and add mine-only weekly toggle"
git push origin main
```

---

### Task 8: Live 冒烟 + 文档 + 收尾

**Files:**
- Modify: `README.md`、`SKILL.md`（scope/by_source/sync chip/merge accomplishments）
- 运维：重启、真实同步、断言

- [ ] **Step 1: 重启 + 真实同步**

备份 DB（workledger backup）→ taskkill 旧 PID → Start-Process 脱离启动 → health ok。
POST /api/sync（curl --max-time 600）→ jira ok（观察 truncated 合并：detail.issues 可能 >5000）、bitbucket ok。

- [ ] **Step 2: 断言（python 脚本读 API + DB）**

- `GET /api/summary/project?key=RW&window=7d&scope=mine`：tickets 全部 assignee==JasonZhong；prs 全部 mine.authored/reviewing；scope=="mine"。
- `GET /api/work-review/weekly?scope=mine`：groups 事件不含他人票/PR。
- `GET /api/export?period=week&scope=mine`：markdown 含三子节标题（有数据时）且无他人票。
- `GET /api/insights`：by_source 三桶；by_type manual 计数 == 人工事件数（DB 对照）。
- weekly（all）：本周 MERGED PR 出现在 groups（DB 查本周 bitbucket_updated 的 MERGED 锚点对照）。
- accomplishments：存在 source_key LIKE 'bitbucket-merge:%' 记录；再跑一次 POST /api/sync/bitbucket 计数不增。
- 无头截图 topbar chip（Read 确认）。

- [ ] **Step 3: 文档**

README/SKILL 各加：scope=mine 用法（三端点 + MCP）、by_source/来源子节、SyncStatus chip、merge accomplishments（设置开关）、twg 重试与 truncated 合并行为。匹配既有风格。

- [ ] **Step 4: 全套测试 + 提交 + push**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add README.md SKILL.md
git commit -m "Document mine scope, source separation, and sync status UI"
git push origin main
```

---

## Self-Review 记录

- Spec 覆盖：§3→T1；§4→T2；§5→T3；§6→T4+T7；§7→T5；§8→T6；§9 冒烟→T8。
- 类型一致：sources 四函数签名 T1 定义 T2/T4/T6 消费一致；scope 参数名/默认值跨端点一致；SyncSourceState 与 /api/sync/status 实际字段一致。
- 已知风险：WeeklyView 现有 `scope` computed 与新 mine ref 命名共存（scope 是请求参数对象，mine 是布尔）——计划已区分；ChartRow 类型名以 types/index.ts 实际为准（T7 Step 1 注明先读）；export 子节路径与 Task 2 scope window 叠加（T4 代码复用同一 window）。