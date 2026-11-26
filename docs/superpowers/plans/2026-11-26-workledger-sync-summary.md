# WorkLedger 外部同步与项目汇总 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 WorkLedger 实时同步 Jira（RW/AIP）与 Bitbucket（transfinderorg 三仓库）PR，提供带新鲜度标记的项目汇总 API/MCP 工具，并自动生成 work item 使周报/briefing 可用。

**Architecture:** FastAPI 进程内同步服务（lifespan polling + 手动触发）。Jira 走 twg CLI subprocess，Bitbucket 走 httpx REST。数据复用 `work_events`（票据快照 + PR 锚点），新增 `sync_state` 表记录新鲜度。汇总服务只读本地数据。

**Tech Stack:** Python 3.14 / FastAPI / SQLite(WAL) / httpx / pydantic-settings / pytest / twg CLI

**Spec:** `docs/superpowers/specs/2026-11-26-workledger-sync-summary-design.md`（实现前必读，尤其是 §3 已确认决策与 §9 口径定义）

## Global Constraints

- 解释器：一律用 `.venv/Scripts/python.exe`（仓库根目录的 venv，已装 workledger）。
- 跑测试：`.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`（Windows 默认 pytest 临时目录有权限问题，必须带 `--basetemp`）。
- Git：只在 `main` 分支工作，不新建分支。提交信息用英文祈使句（仓库风格，如 "Add …"），不用 `feat:` 前缀。每个任务结束 commit；"提交" 含 push（`git push origin main`）。
- 绝不提交 `.env`、`data/`（已 gitignore，暂存时仍要检查）。
- `event_type` 是 CHECK 闭集：`pr_created/review_finding/comment_analysis/fix/verification/reply_drafted/reply_published/manual`。**禁止新增类型**。PR 状态只存锚点 `extra_json.state`，**不追加迁移事件**。
- `work_items.stage` 是 CHECK 闭集：`active/waiting/verification/done`。**禁止新增**。
- 自动 work item 只给 Jason（按 `assignee.accountId`，不用人名）；Backlog 不建；历史 Done 不建；仅 非done→done 迁移建 done item；已有 item 不覆盖不删除。
- 状态回退必须含中文「已完成」（账本实测值）。
- 同步失败只影响该源，不得影响本地功能（离线核心原则）。
- 凭据：`ATLASSIAN_USER_EMAIL`/`ATLASSIAN_API_TOKEN` 从 `C:\Users\jason\.qoder-cn\settings.json` 的 `mcpServers.bitbucket.env` 复制到 `.env`（用户已批准）。不要在日志/输出中打印 token。
- twg CLI 全路径：`C:\Users\jason\AppData\Local\Programs\twg\bin\twg`（写入 .env 的 TWG_CLI_PATH）。

---

### Task 1: Migration 010 + sync_state 服务 + settings + 凭据

**Files:**
- Create: `src/workledger/migrations/010_sync_state.sql`
- Create: `src/workledger/services/sync_state.py`
- Modify: `src/workledger/config.py`（Settings 类内追加字段）
- Modify: `pyproject.toml`（dependencies 加 `"httpx>=0.27"`）
- Modify: `.env`（不提交）
- Test: `tests/test_sync_state.py`

**Interfaces:**
- Consumes: `workledger.db.write_transaction(conn)`、`get_connection`
- Produces:
  - `sync_state.utc_now_iso() -> str`
  - `sync_state.record_attempt(conn, source: str) -> None`
  - `sync_state.record_success(conn, source: str, detail: dict) -> None`
  - `sync_state.record_error(conn, source: str, error: str) -> None`
  - `sync_state.get_states(conn) -> dict[str, dict]`（每行含 `source/last_attempt_at/last_success_at/last_error/detail`，detail 是解析后的 dict）
  - `sync_state.is_stale(state: dict | None, interval_minutes: int) -> bool`
  - settings 新字段（全部有默认值）：`atlassian_user_email=""`、`atlassian_api_token=""`、`twg_cli_path="twg"`、`sync_interval_minutes=15`、`sync_jira_site="transfinder"`、`sync_jira_projects="RW,AIP"`、`sync_jira_exclude="AIP-96"`、`sync_jira_window_days=30`、`sync_bitbucket_workspace="transfinderorg"`、`sync_bitbucket_repos="core,routefinderapi,routefinder-web"`、`sync_bitbucket_project="RW"`、`sync_bitbucket_window_days=30`

- [ ] **Step 1: 写失败测试** `tests/test_sync_state.py`

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from workledger.services import sync_state


def test_migration_010_applies(conn):
    version = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
    assert version >= 10
    conn.execute("SELECT source, last_attempt_at, last_success_at, last_error, detail_json FROM sync_state")


def test_success_roundtrip_and_error_clears(conn):
    sync_state.record_attempt(conn, "jira")
    sync_state.record_success(conn, "jira", {"created": 2, "my_account_id": "acc-1"})
    states = sync_state.get_states(conn)
    assert states["jira"]["last_success_at"] is not None
    assert states["jira"]["detail"] == {"created": 2, "my_account_id": "acc-1"}
    assert states["jira"]["last_error"] is None
    sync_state.record_error(conn, "jira", "twg exploded")
    states = sync_state.get_states(conn)
    assert states["jira"]["last_error"] == "twg exploded"
    assert states["jira"]["last_success_at"] is not None  # 失败不清空上次成功时间
    sync_state.record_success(conn, "jira", {})
    assert sync_state.get_states(conn)["jira"]["last_error"] is None


def test_is_stale_rules(conn):
    assert sync_state.is_stale(None, 15) is True
    assert sync_state.is_stale({"last_success_at": None}, 15) is True
    now = datetime.now(UTC)
    fresh = {"last_success_at": (now - timedelta(minutes=10)).isoformat()}
    old = {"last_success_at": (now - timedelta(minutes=61)).isoformat()}
    assert sync_state.is_stale(fresh, 15) is False
    assert sync_state.is_stale(old, 15) is True
    day_old = {"last_success_at": (now - timedelta(hours=25)).isoformat()}
    assert sync_state.is_stale(day_old, 0) is True
    assert sync_state.is_stale({"last_success_at": (now - timedelta(hours=2)).isoformat()}, 0) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_state.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（`No module named workledger.services.sync_state` / no such table）

- [ ] **Step 3: 实现**

`src/workledger/migrations/010_sync_state.sql`:
```sql
CREATE TABLE sync_state (
    source TEXT PRIMARY KEY,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    detail_json TEXT
);
```

`src/workledger/services/sync_state.py`:
```python
"""Sync freshness bookkeeping."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from ..db import write_transaction


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def record_attempt(conn: sqlite3.Connection, source: str) -> None:
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO sync_state (source, last_attempt_at) VALUES (?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at",
            (source, utc_now_iso()),
        )


def record_success(conn: sqlite3.Connection, source: str, detail: dict) -> None:
    now = utc_now_iso()
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO sync_state (source, last_attempt_at, last_success_at, last_error, detail_json) "
            "VALUES (?, ?, ?, NULL, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at, "
            "last_success_at=excluded.last_success_at, last_error=NULL, detail_json=excluded.detail_json",
            (source, now, now, json.dumps(detail, ensure_ascii=False, sort_keys=True)),
        )


def record_error(conn: sqlite3.Connection, source: str, error: str) -> None:
    with write_transaction(conn):
        conn.execute(
            "INSERT INTO sync_state (source, last_attempt_at, last_error) VALUES (?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET last_attempt_at=excluded.last_attempt_at, "
            "last_error=excluded.last_error",
            (source, utc_now_iso(), error[:2000]),
        )


def get_states(conn: sqlite3.Connection) -> dict[str, dict]:
    states = {}
    for row in conn.execute("SELECT * FROM sync_state ORDER BY source"):
        state = dict(row)
        state["detail"] = json.loads(state.pop("detail_json") or "{}")
        states[state["source"]] = state
    return states


def is_stale(state: dict | None, interval_minutes: int) -> bool:
    if not state or not state.get("last_success_at"):
        return True
    last = datetime.fromisoformat(state["last_success_at"])
    threshold = max(2 * interval_minutes, 30) if interval_minutes > 0 else 24 * 60
    return (datetime.now(UTC) - last).total_seconds() / 60 > threshold
```

`config.py` Settings 类内（`agent_model` 之后）追加：
```python
    atlassian_user_email: str = ""
    atlassian_api_token: str = ""
    twg_cli_path: str = "twg"
    sync_interval_minutes: int = 15
    sync_jira_site: str = "transfinder"
    sync_jira_projects: str = "RW,AIP"
    sync_jira_exclude: str = "AIP-96"
    sync_jira_window_days: int = 30
    sync_bitbucket_workspace: str = "transfinderorg"
    sync_bitbucket_repos: str = "core,routefinderapi,routefinder-web"
    sync_bitbucket_project: str = "RW"
    sync_bitbucket_window_days: int = 30
```

`pyproject.toml` dependencies 列表加 `"httpx>=0.27"`，然后 `.venv/Scripts/python.exe -m pip install -e ".[dev]"` 安装。

`.env` 追加（用脚本从 Qoder settings 复制，不打印 token）：
```bash
.venv/Scripts/python.exe -c "
import json
cfg = json.load(open(r'C:\Users\jason\.qoder-cn\settings.json', encoding='utf-8'))
env = cfg['mcpServers']['bitbucket']['env']
lines = [
    f\"ATLASSIAN_USER_EMAIL={env['ATLASSIAN_USER_EMAIL']}\",
    f\"ATLASSIAN_API_TOKEN={env['ATLASSIAN_API_TOKEN']}\",
    r'TWG_CLI_PATH=C:\Users\jason\AppData\Local\Programs\twg\bin\twg',
    'SYNC_INTERVAL_MINUTES=15',
]
with open('.env', 'a', encoding='utf-8') as f:
    f.write('\n' + '\n'.join(lines) + '\n')
print('appended', len(lines), 'keys')
"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_state.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 3 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`（Expected: 129 passed）
```bash
git add src/workledger/migrations/010_sync_state.sql src/workledger/services/sync_state.py src/workledger/config.py pyproject.toml tests/test_sync_state.py
git status --short  # 确认 .env/data 不在暂存区
git commit -m "Add sync_state migration, freshness service, and sync settings"
git push origin main
```

---

### Task 2: jira_import 模块迁移 + status_category/assignee 扩展

**Files:**
- Create: `src/workledger/services/jira_import.py`（自 `scripts/import_jira.py` 移入除 `main()` 外全部代码）
- Modify: `scripts/import_jira.py`（变薄 CLI 壳）
- Modify: `tests/test_jira_import.py:7`（导入路径）
- Test: `tests/test_jira_import.py`（追加新测试）

**Interfaces:**
- Consumes: `events.create_event`、`master_data.create_project`、`write_transaction`、`revisions` 表（`_edited_fields`）
- Produces:
  - `jira_import.import_issues(conn, issues: list[dict], *, project_key: str, project_name: str, base_url: str | None = None) -> dict[str, int]`（签名不变）
  - `jira_import.is_done(status_category: str | None, status_name: str | None) -> bool`
  - `jira_import.DONE_STATUS_NAMES: frozenset[str]`
  - `jira_import.adf_to_text`、`_metadata`、`_edited_fields`、`_timestamp`、`_as_utc`、`_url`（Task 4 复用 `_metadata`/`_edited_fields`）
  - `_import_issue` 写入 extra_json 新字段：`status_category`（statusCategory.key）、`assignee_account_id`、`assignee_name`

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_jira_import.py`，并把第 7 行改为 `from workledger.services.jira_import import import_issues`）

```python
def test_import_stores_status_category_and_assignee_identity(conn):
    from workledger.services.jira_import import import_issues
    issue = {
        'key': 'RW-900', 'summary': 'Identity', 'created': '2026-11-01T09:00:00+0800',
        'status': {'name': 'In Progress', 'statusCategory': {'key': 'indeterminate'}},
        'assignee': {'accountId': 'acc-jason', 'displayName': 'JasonZhong'},
    }
    import_issues(conn, [issue], project_key='RW', project_name='RW')
    from workledger.services import events
    row = events.search_events(conn, jira_key='RW-900')[0][0]
    extra = json.loads(row['extra_json'])
    assert extra['status_category'] == 'indeterminate'
    assert extra['assignee_account_id'] == 'acc-jason'
    assert extra['assignee_name'] == 'JasonZhong'


def test_is_done_handles_chinese_legacy_statuses():
    from workledger.services.jira_import import is_done
    assert is_done(None, '已完成') is True
    assert is_done(None, 'Done') is True
    assert is_done(None, '已关闭') is True
    assert is_done(None, 'In Backlog') is False
    assert is_done(None, 'Acceptance') is False
    assert is_done('done', 'Whatever') is True
    assert is_done('indeterminate', '已完成') is False  # category 优先
    assert is_done(None, None) is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_jira_import.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 迁移 + 扩展**

把 `scripts/import_jira.py` 中 `adf_to_text` 到 `import_issues`（含）的全部代码复制到 `src/workledger/services/jira_import.py`，头部改为：
```python
"""Jira snapshot import shared by the CLI script and the sync service."""
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from ..db import write_transaction
from ..schemas import EventCreate
from . import events, master_data
```
（`argparse`/`Path`/`settings`/`init_db`/`DatabaseError` 只被 `main()` 用，不迁移。）

在 `DONE_STATUS_NAMES` 模块级常量 + `is_done` 加在 `_metadata` 之前：
```python
DONE_STATUS_NAMES = frozenset({
    "done", "closed", "resolved", "cancelled", "canceled",
    "已完成", "已关闭", "已解决", "已取消",
})


def is_done(status_category: str | None, status_name: str | None) -> bool:
    if status_category:
        return status_category == "done"
    return (status_name or "").strip().lower() in DONE_STATUS_NAMES
```

在 `_import_issue` 的 `for field in ("issuetype", "status", "priority")` 循环之后插入：
```python
    if "status" in fields and fields["status"]:
        category = (fields["status"].get("statusCategory") or {}).get("key")
        if category:
            metadata["status_category"] = category
    if "assignee" in fields:
        assignee = fields.get("assignee") or {}
        metadata["assignee_account_id"] = assignee.get("accountId")
        metadata["assignee_name"] = assignee.get("displayName")
```

`scripts/import_jira.py` 整体替换为：
```python
"""Import work item snapshots from a local Jira JSON file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from workledger.config import settings
from workledger.db import DatabaseError, init_db
from workledger.services.jira_import import import_issues


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", type=Path)
    parser.add_argument("--project-key", default="RW")
    parser.add_argument("--project-name", default="RW")
    parser.add_argument("--jira-base-url", help="Base URL for browse links when the export lacks a URL")
    args = parser.parse_args()

    try:
        payload = json.loads(args.json_path.read_text(encoding="utf-8-sig"))
        issues = payload.get("data", payload)["issues"]
        if not isinstance(issues, list):
            raise TypeError("The JSON file must contain an issues array.")
        counts = import_issues(
            init_db(settings.db_path), issues, project_key=args.project_key,
            project_name=args.project_name, base_url=args.jira_base_url,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, DatabaseError) as exc:
        parser.exit(2, f"Jira import failed: {exc}\n")

    print(
        f"Jira import for {args.project_key}: {counts['created']} created, "
        f"{counts['updated']} refreshed, {counts['unchanged']} unchanged."
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_jira_import.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 原有测试 + 2 新测试全绿

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add src/workledger/services/jira_import.py scripts/import_jira.py tests/test_jira_import.py
git commit -m "Move Jira import into services and store status category and assignee identity"
git push origin main
```

---

### Task 3: sync_jira + 自动 work item

**Files:**
- Create: `src/workledger/services/sync_jira.py`
- Test: `tests/test_sync_jira.py`

**Interfaces:**
- Consumes: Task 1 `sync_state.*`、settings 字段；Task 2 `jira_import.import_issues/is_done`；`work_items.create_work_item(conn, WorkItemCreate)`；`WorkItemCreate(title, jira_key, project_id, source_event_id, source_key, actor, stage)`
- Produces:
  - `sync_jira.sync_jira(conn, *, runner: Callable[[list[str]], str] | None = None) -> dict`
    成功：`{"source": "jira", "ok": True, "issues": n, "created": n, "updated": n, "unchanged": n, "items_created": n, "truncated": bool, "my_account_id"?: str}`
    失败：`{"source": "jira", "ok": False, "error": str}`（并 record_error）
  - `sync_jira.build_jql(project_keys: list[str], exclude_keys: list[str], window_days: int, imported_keys: list[str]) -> str`
  - `sync_jira._twg_runner(args: list[str]) -> str`（subprocess，settings.twg_cli_path）
  - `sync_jira.LIMIT = 200`

- [ ] **Step 1: 写失败测试** `tests/test_sync_jira.py`

```python
from __future__ import annotations

import json

import pytest

from workledger.config import settings
from workledger.services import jira_import, sync_jira, sync_state


def _issue(key, status="In Progress", category="indeterminate", assignee="acc-jason", updated="2026-11-24T20:33:40.416-0500"):
    return {
        "key": key, "summary": f"Summary {key}",
        "status": {"name": status, "statusCategory": {"key": category}},
        "assignee": {"accountId": assignee, "displayName": "JasonZhong"} if assignee else None,
        "created": "2026-11-01T09:00:00.000-0500", "updated": updated,
    }


def _runner(tmp_path, issues):
    payload = tmp_path / "twg.json"
    payload.write_text(json.dumps({"data": {"issues": issues}}), encoding="utf-8")
    calls = []

    def runner(args):
        calls.append(args)
        return f'output_files:\n  stdout: "{payload}"\n'

    return runner, calls


def test_sync_creates_snapshots_and_items_for_my_open_tickets(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-901"), _issue("AIP-902")])
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["ok"] is True
    assert result["created"] == 2
    assert result["items_created"] == 2
    assert conn.execute("SELECT COUNT(*) FROM work_items").fetchone()[0] == 2
    stages = {r["jira_key"]: r["stage"] for r in conn.execute("SELECT jira_key, stage FROM work_items")}
    assert stages == {"RW-901": "active", "AIP-902": "active"}
    assert conn.execute("SELECT key FROM projects WHERE key='AIP'").fetchone() is not None
    state = sync_state.get_states(conn)["jira"]
    assert state["last_success_at"] is not None
    assert state["detail"]["my_account_id"] == "acc-jason"


def test_backlog_and_historical_done_get_no_items(conn, tmp_path):
    issues = [_issue("RW-903", "In Backlog", "new"), _issue("RW-904", "Done", "done")]
    runner, _ = _runner(tmp_path, issues)
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["created"] == 2
    assert result["items_created"] == 0


def test_done_transition_creates_done_item(conn, tmp_path):
    jira_import.import_issues(conn, [_issue("RW-905")], project_key="RW", project_name="RW")
    runner, _ = _runner(tmp_path, [_issue("RW-905", "Done", "done", updated="2026-11-25T20:33:40.416-0500")])
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["items_created"] == 1
    assert conn.execute("SELECT stage FROM work_items WHERE jira_key='RW-905'").fetchone()[0] == "done"


def test_acceptance_maps_to_verification(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-906", "Acceptance", "indeterminate")])
    sync_jira.sync_jira(conn, runner=runner)
    assert conn.execute("SELECT stage FROM work_items WHERE jira_key='RW-906'").fetchone()[0] == "verification"


def test_other_assignee_gets_snapshot_not_item(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-907", assignee="acc-joseph")])
    result = sync_jira.sync_jira(conn, runner=runner)
    assert result["created"] == 1
    assert result["items_created"] == 0


def test_rerun_idempotent_and_reassignment_keeps_item(conn, tmp_path):
    runner, _ = _runner(tmp_path, [_issue("RW-908")])
    sync_jira.sync_jira(conn, runner=runner)
    runner2, _ = _runner(tmp_path, [_issue("RW-908", assignee=None)])
    result = sync_jira.sync_jira(conn, runner=runner2)
    assert result["items_created"] == 0
    assert conn.execute("SELECT COUNT(*) FROM work_items WHERE jira_key='RW-908'").fetchone()[0] == 1


def test_jql_contains_exclude_window_and_imported_keys(conn, tmp_path):
    jira_import.import_issues(conn, [_issue("RW-909", "Done", "done")], project_key="RW", project_name="RW")
    runner, calls = _runner(tmp_path, [_issue("RW-910")])
    sync_jira.sync_jira(conn, runner=runner)
    main_jql = calls[0][calls[0].index("--jql") + 1]
    assert "project in (RW, AIP)" in main_jql
    assert "key not in (AIP-96)" in main_jql
    assert "updated >= -30d" in main_jql
    assert "RW-909" in main_jql
    assert "assignee = currentUser()" in main_jql


def test_failure_records_error(conn, tmp_path):
    def broken(args):
        raise ValueError("twg exploded")
    result = sync_jira.sync_jira(conn, runner=broken)
    assert result["ok"] is False
    assert "twg exploded" in sync_state.get_states(conn)["jira"]["last_error"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_jira.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现** `src/workledger/services/sync_jira.py`

```python
"""Jira sync via the twg CLI."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..config import settings
from ..db import DatabaseError
from ..work_item_models import WorkItemCreate
from . import jira_import, sync_state, work_items

FIELDS = "key,summary,status,issuetype,priority,assignee,parent,created,updated,description"
LIMIT = 200


def _twg_runner(args: list[str]) -> str:
    result = subprocess.run(
        [settings.twg_cli_path, *args],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if result.returncode != 0:
        raise ValueError(f"twg exited {result.returncode}: {(result.stderr or result.stdout)[:500]}")
    return result.stdout


def _stdout_path(output: str) -> Path:
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("stdout:"):
            return Path(stripped.split(":", 1)[1].strip().strip('"'))
    raise ValueError("twg output did not contain a stdout file path.")


def _fetch_issues(runner: Callable[[list[str]], str], jql: str, limit: int = LIMIT) -> list[dict]:
    output = runner([
        "jira", "workitem", "query", "--site", settings.sync_jira_site,
        "--jql", jql, "--fields", FIELDS, "--limit", str(limit), "--output", "json",
    ])
    payload = json.loads(_stdout_path(output).read_text(encoding="utf-8-sig"))
    issues = payload.get("data", payload)["issues"]
    if not isinstance(issues, list):
        raise ValueError("twg query result must contain an issues array.")
    return issues


def build_jql(project_keys: list[str], exclude_keys: list[str], window_days: int, imported_keys: list[str]) -> str:
    clauses = [f"project in ({', '.join(project_keys)})"]
    if exclude_keys:
        clauses.append(f"key not in ({', '.join(exclude_keys)})")
    scope = ["assignee = currentUser()", f"updated >= -{window_days}d"]
    if imported_keys:
        scope.append(f"key in ({', '.join(imported_keys)})")
    clauses.append("(" + " OR ".join(scope) + ")")
    return " AND ".join(clauses) + " ORDER BY updated DESC"


def _imported_keys(conn: sqlite3.Connection, project_keys: list[str]) -> list[str]:
    likes = " OR ".join("jira_key LIKE ?" for _ in project_keys)
    rows = conn.execute(
        f"SELECT DISTINCT jira_key FROM work_events "
        f"WHERE jira_key IS NOT NULL AND source_agent='jira-import' AND ({likes})",
        [f"{key}-%" for key in project_keys],
    ).fetchall()
    return sorted(row["jira_key"] for row in rows)


def _my_account_id(conn: sqlite3.Connection, runner) -> str | None:
    cached = sync_state.get_states(conn).get("jira", {}).get("detail", {}).get("my_account_id")
    if cached:
        return cached
    keys = [k.strip().upper() for k in settings.sync_jira_projects.split(",") if k.strip()]
    issues = _fetch_issues(runner, f"project in ({', '.join(keys)}) AND assignee = currentUser()", limit=1)
    if issues:
        return (issues[0].get("assignee") or {}).get("accountId")
    return None


def _stage_for(status: dict) -> str | None:
    category = (status.get("statusCategory") or {}).get("key")
    name = (status.get("name") or "").lower()
    if category == "indeterminate":
        if any(word in name for word in ("acceptance", "verification", "review")):
            return "verification"
        return "active"
    return None


def _auto_work_items(conn, issues, previous, my_account_id) -> int:
    if not my_account_id:
        return 0
    created = 0
    for issue in issues:
        key = issue["key"].strip().upper()
        if (issue.get("assignee") or {}).get("accountId") != my_account_id:
            continue
        status = issue.get("status") or {}
        category = (status.get("statusCategory") or {}).get("key")
        stage = _stage_for(status)
        if category == "done":
            prev = previous.get(key)
            if prev is None or jira_import.is_done(prev.get("status_category"), prev.get("status")):
                continue
            stage = "done"
        if stage is None:
            continue
        if conn.execute("SELECT 1 FROM work_items WHERE jira_key=?", (key,)).fetchone():
            continue
        event = conn.execute(
            "SELECT id, project_id, summary FROM work_events WHERE source_key=?", (f"jira:{key}",)
        ).fetchone()
        if event is None:
            continue
        work_items.create_work_item(conn, WorkItemCreate(
            title=issue.get("summary") or event["summary"], jira_key=key,
            project_id=event["project_id"], source_event_id=event["id"],
            source_key=f"jira-item:{key}", actor="jira-sync", stage=stage,
        ))
        created += 1
    return created


def sync_jira(conn: sqlite3.Connection, *, runner: Callable[[list[str]], str] | None = None) -> dict:
    runner = runner or _twg_runner
    sync_state.record_attempt(conn, "jira")
    try:
        project_keys = [k.strip().upper() for k in settings.sync_jira_projects.split(",") if k.strip()]
        exclude_keys = [k.strip().upper() for k in settings.sync_jira_exclude.split(",") if k.strip()]
        imported = _imported_keys(conn, project_keys)
        jql = build_jql(project_keys, exclude_keys, settings.sync_jira_window_days, imported)
        issues = _fetch_issues(runner, jql)
        previous = {
            row["jira_key"]: json.loads(row["extra_json"] or "{}")
            for row in conn.execute(
                "SELECT jira_key, extra_json FROM work_events "
                "WHERE source_agent='jira-import' AND jira_key IS NOT NULL"
            )
        }
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        for project_key in project_keys:
            subset = [i for i in issues if i["key"].strip().upper().startswith(f"{project_key}-")]
            if subset:
                part = jira_import.import_issues(
                    conn, subset, project_key=project_key, project_name=project_key,
                    base_url=f"https://{settings.sync_jira_site}.atlassian.net",
                )
                for k in counts:
                    counts[k] += part[k]
        my_account_id = _my_account_id(conn, runner)
        items_created = _auto_work_items(conn, issues, previous, my_account_id)
        detail = {**counts, "issues": len(issues), "items_created": items_created,
                  "truncated": len(issues) >= LIMIT}
        if my_account_id:
            detail["my_account_id"] = my_account_id
        sync_state.record_success(conn, "jira", detail)
        return {"source": "jira", "ok": True, **detail}
    except (OSError, ValueError, KeyError, TypeError, DatabaseError, subprocess.SubprocessError) as exc:
        sync_state.record_error(conn, "jira", str(exc))
        return {"source": "jira", "ok": False, "error": str(exc)}
```

注意：`_my_account_id` 的探测查询复用同一 runner；测试里 fake runner 对探测返回完整列表，取第一个 issue 的 accountId。`previous` 快照必须在 `import_issues` 之前采集。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_jira.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 8 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add src/workledger/services/sync_jira.py tests/test_sync_jira.py
git commit -m "Add Jira sync with scoped auto work-item creation"
git push origin main
```

---

### Task 4: sync_bitbucket（PR 锚点，无迁移事件）

**Files:**
- Create: `src/workledger/services/sync_bitbucket.py`
- Test: `tests/test_sync_bitbucket.py`

**Interfaces:**
- Consumes: Task 1 `sync_state.*`/settings；Task 2 `jira_import._metadata/_edited_fields`；`events.create_event(conn, EventCreate)`；`write_transaction`；`master_data.create_project(conn, name=…, key=…)`（测试用）
- Produces:
  - `sync_bitbucket.sync_bitbucket(conn, *, client: httpx.Client | None = None) -> dict`
    `{"ok": bool, "repos": {"bitbucket:transfinderorg/core": {"ok": True, "prs": n, "created": n, "updated": n, "unchanged": n, "my_uuid": str} | {"ok": False, "error": str}}}`
  - PR 锚点契约（Task 6 依赖）：`event_type='pr_created'`、`repo='{workspace}/{repo_slug}'`、`source_agent='bitbucket-sync'`、`source_key='bitbucket:{ws}/{repo}:pr:{id}'`、extra_json 含 `state/bitbucket_updated/author/author_uuid/reviewers[{name,uuid,approved}]/jira_keys/url/source_branch/target_branch`

- [ ] **Step 1: 写失败测试** `tests/test_sync_bitbucket.py`

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from workledger.config import settings
from workledger.schemas import EventUpdate
from workledger.services import events, master_data, sync_bitbucket, sync_state

JASON_UUID = "{jason-uuid}"


@pytest.fixture()
def bb_settings(monkeypatch, conn):
    monkeypatch.setattr(settings, "atlassian_user_email", "jason@example.com")
    monkeypatch.setattr(settings, "atlassian_api_token", "token")
    monkeypatch.setattr(settings, "sync_bitbucket_workspace", "transfinderorg")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    monkeypatch.setattr(settings, "sync_bitbucket_project", "RW")
    master_data.create_project(conn, name="RW (Atlas)", key="RW")


def _pr(pr_id=1, state="OPEN", title="feat(RW-901): something", updated=None, reviewers=None):
    return {
        "id": pr_id, "title": title, "state": state,
        "created_on": "2026-11-01T00:00:00+00:00",
        "updated_on": updated or (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        "author": {"display_name": "JasonZhong", "uuid": JASON_UUID},
        "reviewers": reviewers or [],
        "links": {"html": {"href": f"https://bitbucket.org/transfinderorg/core/pull-requests/{pr_id}"}},
        "source": {"branch": {"name": "feat"}}, "destination": {"branch": {"name": "main"}},
    }


def _client(prs):
    def handler(request):
        if request.url.path == "/2.0/user":
            return httpx.Response(200, json={"uuid": JASON_UUID, "display_name": "JasonZhong"})
        if request.url.path == "/2.0/repositories/transfinderorg/core/pullrequests":
            assert JASON_UUID in request.url.params["q"]
            return httpx.Response(200, json={"values": prs})
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.bitbucket.org/2.0")


def test_anchor_created_with_identity_and_jira_link(conn, bb_settings):
    result = sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    assert result["ok"] is True
    row = conn.execute("SELECT * FROM work_events WHERE source_key='bitbucket:transfinderorg/core:pr:1'").fetchone()
    assert row["event_type"] == "pr_created"
    assert row["repo"] == "transfinderorg/core"
    assert row["jira_key"] == "RW-901"
    assert row["project_id"] is not None
    extra = json.loads(row["extra_json"])
    assert extra["state"] == "OPEN"
    assert extra["author_uuid"] == JASON_UUID
    assert extra["jira_keys"] == ["RW-901"]
    assert sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["detail"]["my_uuid"] == JASON_UUID


def test_rerun_unchanged_and_state_update_touches_anchor_only(conn, bb_settings):
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    result = sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    assert result["repos"]["bitbucket:transfinderorg/core"]["unchanged"] == 1
    merged = _pr(state="MERGED", updated=datetime.now(UTC).isoformat())
    sync_bitbucket.sync_bitbucket(conn, client=_client([merged]))
    rows = conn.execute("SELECT * FROM work_events WHERE repo='transfinderorg/core'").fetchall()
    assert len(rows) == 1  # 不追加迁移事件
    assert json.loads(rows[0]["extra_json"])["state"] == "MERGED"


def test_edited_summary_preserved_and_stale_update_skipped(conn, bb_settings):
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr()]))
    row = conn.execute("SELECT id FROM work_events WHERE pr_number=1").fetchone()
    events.update_event(conn, row["id"], EventUpdate(summary="My title"))
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr(updated=datetime.now(UTC).isoformat())]))
    assert conn.execute("SELECT summary FROM work_events WHERE id=?", (row["id"],)).fetchone()[0] == "My title"
    older = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    result = sync_bitbucket.sync_bitbucket(conn, client=_client([_pr(updated=older)]))
    assert result["repos"]["bitbucket:transfinderorg/core"]["unchanged"] == 1


def test_reviewers_stored_for_needs_review(conn, bb_settings):
    reviewers = [{"display_name": "JasonZhong", "uuid": JASON_UUID, "approved": False}]
    sync_bitbucket.sync_bitbucket(conn, client=_client([_pr(reviewers=reviewers)]))
    extra = json.loads(conn.execute("SELECT extra_json FROM work_events WHERE pr_number=1").fetchone()[0])
    assert extra["reviewers"] == [{"name": "JasonZhong", "uuid": JASON_UUID, "approved": False}]


def test_missing_credentials_records_error(conn, monkeypatch):
    monkeypatch.setattr(settings, "atlassian_user_email", "")
    monkeypatch.setattr(settings, "atlassian_api_token", "")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    result = sync_bitbucket.sync_bitbucket(conn)
    assert result["ok"] is False
    assert "credentials" in sync_state.get_states(conn)["bitbucket:transfinderorg/core"]["last_error"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_bitbucket.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现** `src/workledger/services/sync_bitbucket.py`

```python
"""Bitbucket PR sync via REST. State lives on the pr_created anchor; no transition events."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import httpx

from ..config import settings
from ..db import DatabaseError, write_transaction
from ..schemas import EventCreate
from . import events, jira_import, sync_state


def _client() -> httpx.Client:
    if not settings.atlassian_user_email or not settings.atlassian_api_token:
        raise ValueError("Bitbucket credentials are not configured (ATLASSIAN_USER_EMAIL/ATLASSIAN_API_TOKEN).")
    return httpx.Client(
        base_url="https://api.bitbucket.org/2.0",
        auth=(settings.atlassian_user_email, settings.atlassian_api_token),
        timeout=30,
    )


def _repos() -> list[str]:
    return [r.strip() for r in settings.sync_bitbucket_repos.split(",") if r.strip()]


def _jira_key_pattern() -> re.Pattern:
    keys = [k.strip().upper() for k in settings.sync_jira_projects.split(",") if k.strip()]
    return re.compile(rf"\b(?:{'|'.join(keys)})-\d+\b")


def _fetch_prs(client: httpx.Client, workspace: str, repo: str, my_uuid: str, cutoff: datetime) -> list[dict]:
    q = f'(author.uuid="{my_uuid}" OR reviewers.uuid="{my_uuid}") AND updated_on >= "{cutoff.isoformat()}"'
    prs: list[dict] = []
    page = 1
    while True:
        response = client.get(
            f"/repositories/{workspace}/{repo}/pullrequests",
            params={"q": q, "sort": "-updated_on", "pagelen": "50", "page": str(page)},
        )
        response.raise_for_status()
        data = response.json()
        values = data.get("values", [])
        if not values:
            break
        prs.extend(values)
        oldest = min(datetime.fromisoformat(pr["updated_on"]) for pr in values)
        if "next" not in data or oldest < cutoff:
            break
        page += 1
    return [pr for pr in prs if datetime.fromisoformat(pr["updated_on"]) >= cutoff]


def _upsert_pr(conn, pr: dict, repo_full: str, project_id: int | None, pattern: re.Pattern) -> str:
    pr_id = pr["id"]
    source_key = f"bitbucket:{repo_full}:pr:{pr_id}"
    original = conn.execute("SELECT * FROM work_events WHERE source_key=?", (source_key,)).fetchone()
    if original is not None and original["source_agent"] != "bitbucket-sync":
        raise ValueError(f"PR {repo_full}#{pr_id} belongs to a WorkLedger record created outside the sync.")
    metadata = jira_import._metadata(original["extra_json"]) if original is not None else {}
    updated = datetime.fromisoformat(pr["updated_on"])
    previous = metadata.get("bitbucket_updated")
    if previous and datetime.fromisoformat(previous) >= updated:
        return "unchanged"
    keys = pattern.findall(pr.get("title") or "")
    metadata.update({
        "bitbucket_updated": pr["updated_on"],
        "state": pr["state"],
        "author": (pr.get("author") or {}).get("display_name"),
        "author_uuid": (pr.get("author") or {}).get("uuid"),
        "reviewers": [
            {"name": r.get("display_name"), "uuid": r.get("uuid"), "approved": bool(r.get("approved"))}
            for r in pr.get("reviewers") or []
        ],
        "jira_keys": keys,
        "source_branch": ((pr.get("source") or {}).get("branch") or {}).get("name"),
        "target_branch": ((pr.get("destination") or {}).get("branch") or {}).get("name"),
    })
    url = ((pr.get("links") or {}).get("html") or {}).get("href")
    if url:
        metadata["url"] = url
    title = pr.get("title") or f"PR #{pr_id}"
    detail = (
        f"[PR {pr['state']} · {metadata.get('author') or '?'}] "
        f"{metadata.get('source_branch') or '?'} → {metadata.get('target_branch') or '?'}"
    )
    extra = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
    if original is None:
        event = events.create_event(conn, EventCreate(
            event_type="pr_created", occurred_at=datetime.fromisoformat(pr["created_on"]),
            repo=repo_full, pr_number=pr_id, jira_key=keys[0] if keys else None,
            source_key=source_key, source_agent="bitbucket-sync", summary=title,
            detail=detail, evidence_url=url, extra_json=extra,
        ))
        conn.execute("UPDATE work_events SET project_id=? WHERE id=?", (project_id, event["id"]))
        return "created"
    edited = jira_import._edited_fields(conn, original)
    changes = {k: v for k, v in {"summary": title, "detail": detail}.items() if k not in edited}
    if url and "evidence_url" not in edited:
        changes["evidence_url"] = url
    changes["extra_json"] = extra
    if original["project_id"] is None:
        changes["project_id"] = project_id
    if keys and original["jira_key"] is None:
        changes["jira_key"] = keys[0]
    changes = {k: v for k, v in changes.items() if v != original[k]}
    if not changes:
        return "unchanged"
    cols = ", ".join(f"{k}=?" for k in changes)
    conn.execute(
        f"UPDATE work_events SET {cols}, updated_at=datetime('now') WHERE id=?",
        (*changes.values(), original["id"]),
    )
    return "updated"


def sync_bitbucket(conn: sqlite3.Connection, *, client: httpx.Client | None = None) -> dict:
    workspace = settings.sync_bitbucket_workspace
    repos = _repos()
    sources = [f"bitbucket:{workspace}/{repo}" for repo in repos]
    for source in sources:
        sync_state.record_attempt(conn, source)
    owns_client = client is None
    try:
        client = client or _client()
    except ValueError as exc:
        for source in sources:
            sync_state.record_error(conn, source, str(exc))
        return {"ok": False, "error": str(exc), "repos": {}}
    try:
        me = client.get("/user")
        me.raise_for_status()
        my_uuid = me.json()["uuid"]
        cutoff = datetime.now(UTC) - timedelta(days=settings.sync_bitbucket_window_days)
        pattern = _jira_key_pattern()
        project = conn.execute(
            "SELECT id FROM projects WHERE key=?", (settings.sync_bitbucket_project.upper(),)
        ).fetchone()
        project_id = project["id"] if project else None
        results = {}
        for repo in repos:
            source = f"bitbucket:{workspace}/{repo}"
            try:
                prs = _fetch_prs(client, workspace, repo, my_uuid, cutoff)
                counts = {"created": 0, "updated": 0, "unchanged": 0}
                with write_transaction(conn):
                    for pr in prs:
                        counts[_upsert_pr(conn, pr, f"{workspace}/{repo}", project_id, pattern)] += 1
                detail = {**counts, "prs": len(prs), "my_uuid": my_uuid}
                sync_state.record_success(conn, source, detail)
                results[source] = {"ok": True, **detail}
            except (httpx.HTTPError, ValueError, KeyError, TypeError, DatabaseError) as exc:
                sync_state.record_error(conn, source, str(exc))
                results[source] = {"ok": False, "error": str(exc)}
        return {"ok": all(r["ok"] for r in results.values()), "repos": results}
    finally:
        if owns_client:
            client.close()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_bitbucket.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 5 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add src/workledger/services/sync_bitbucket.py tests/test_sync_bitbucket.py
git commit -m "Add Bitbucket PR sync with anchor-only state updates"
git push origin main
```

---

### Task 5: 同步编排 + health/sync 端点 + 后台任务

**Files:**
- Create: `src/workledger/services/sync.py`
- Create: `src/workledger/routers/sync.py`
- Modify: `src/workledger/app.py`（include_router + lifespan）
- Test: `tests/test_sync_api.py`

**Interfaces:**
- Consumes: Task 3 `sync_jira.sync_jira(conn, *, runner=None)`；Task 4 `sync_bitbucket.sync_bitbucket(conn, *, client=None)`；Task 1 `sync_state.*`
- Produces:
  - `sync.run_locked(source: str, fn, conn) -> dict`（busy 时返回 `{"source": source, "ok": False, "error": "sync in progress", "busy": True}`）
  - `sync.sync_all(conn) -> dict`（`{"ok": bool, "jira": {...}, "bitbucket": {...}}`）
  - HTTP：`GET /api/health`、`GET /api/sync/status`、`POST /api/sync/jira`、`POST /api/sync/bitbucket`、`POST /api/sync`
  - `routers/sync.py` 有模块级 `_conn()`（测试 monkeypatch 用，与 `routers/api.py` 同模式）

- [ ] **Step 1: 写失败测试** `tests/test_sync_api.py`

```python
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workledger.db import get_connection
from workledger.routers import sync as sync_router
from workledger.services import sync, sync_state


@pytest.fixture()
def client(monkeypatch, db_path):
    app = FastAPI()
    app.include_router(sync_router.router, prefix="/api")
    monkeypatch.setattr(sync_router, "_conn", lambda: get_connection(db_path))
    with TestClient(app) as c:
        yield c


def test_health_ok_with_stale_sync(client, db_path):
    conn = get_connection(db_path)
    sync_state.record_success(conn, "jira", {})
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] >= 10
    assert body["sync"]["jira"]["stale"] is False
    assert body["sync"]["jira"]["last_sync_at"] is not None


def test_sync_status_lists_sources(client, db_path):
    conn = get_connection(db_path)
    sync_state.record_error(conn, "bitbucket:transfinderorg/core", "boom")
    body = client.get("/api/sync/status").json()
    assert body["bitbucket:transfinderorg/core"]["last_error"] == "boom"
    assert body["bitbucket:transfinderorg/core"]["stale"] is True


def test_trigger_jira_success_and_failure(client, monkeypatch):
    monkeypatch.setattr(sync.sync_jira, "sync_jira", lambda conn, **kw: {"source": "jira", "ok": True, "created": 1})
    assert client.post("/api/sync/jira").json()["created"] == 1
    monkeypatch.setattr(sync.sync_jira, "sync_jira", lambda conn, **kw: {"source": "jira", "ok": False, "error": "twg down"})
    response = client.post("/api/sync/jira")
    assert response.status_code == 502


def test_trigger_busy_returns_409(client):
    lock = sync._lock("jira")
    lock.acquire()
    try:
        assert client.post("/api/sync/jira").status_code == 409
    finally:
        lock.release()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_api.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

`src/workledger/services/sync.py`:
```python
"""Sync orchestration with per-source mutual exclusion."""
from __future__ import annotations

import sqlite3
import threading

from . import sync_bitbucket, sync_jira

_LOCKS: dict[str, threading.Lock] = {}
_GUARD = threading.Lock()


def _lock(source: str) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault(source, threading.Lock())


def run_locked(source: str, fn, conn: sqlite3.Connection) -> dict:
    lock = _lock(source)
    if not lock.acquire(blocking=False):
        return {"source": source, "ok": False, "error": "sync in progress", "busy": True}
    try:
        return fn(conn)
    finally:
        lock.release()


def sync_all(conn: sqlite3.Connection) -> dict:
    jira = run_locked("jira", sync_jira.sync_jira, conn)
    bitbucket = run_locked("bitbucket", sync_bitbucket.sync_bitbucket, conn)
    return {"ok": bool(jira.get("ok")) and bool(bitbucket.get("ok")), "jira": jira, "bitbucket": bitbucket}
```

`src/workledger/routers/sync.py`:
```python
"""Sync triggers, status, and health."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ..config import settings
from ..db import DatabaseError, get_connection
from ..services import sync, sync_state

router = APIRouter(tags=["sync"])


def _conn():
    return get_connection(settings.db_path)


def _freshness(state: dict) -> dict:
    return {
        "last_sync_at": state["last_success_at"],
        "stale": sync_state.is_stale(state, settings.sync_interval_minutes),
        "last_error": state["last_error"],
    }


@router.get("/health")
def health():
    try:
        conn = _conn()
        conn.execute("SELECT 1")
        version = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0]
        states = sync_state.get_states(conn)
    except DatabaseError as exc:
        return JSONResponse(status_code=503, content={"status": "error", "db": "error", "error": str(exc)})
    return {
        "status": "ok", "db": "ok", "schema_version": version, "version": "0.1.0",
        "sync": {source: _freshness(state) for source, state in states.items()},
    }


@router.get("/sync/status")
def sync_status():
    return {
        source: {**state, "stale": sync_state.is_stale(state, settings.sync_interval_minutes)}
        for source, state in sync_state.get_states(_conn()).items()
    }


def _run(result: dict) -> dict:
    if result.get("busy"):
        raise HTTPException(409, "Sync already in progress for this source.")
    if not result.get("ok"):
        raise HTTPException(502, result.get("error", "Sync failed"))
    return result


@router.post("/sync/jira")
def trigger_jira():
    return _run(sync.run_locked("jira", sync.sync_jira.sync_jira, _conn()))


@router.post("/sync/bitbucket")
def trigger_bitbucket():
    return _run(sync.run_locked("bitbucket", sync.sync_bitbucket.sync_bitbucket, _conn()))


@router.post("/sync")
def trigger_all():
    result = sync.sync_all(_conn())
    if not result["ok"]:
        raise HTTPException(502, result)
    return result
```

`src/workledger/app.py`：顶部加 `import asyncio`；lifespan 改为：
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings.db_path)
    task = asyncio.create_task(_sync_loop()) if settings.sync_interval_minutes > 0 else None
    yield
    if task:
        task.cancel()
    close_connection(settings.db_path)


async def _sync_loop():
    from .services import sync
    while True:
        await asyncio.sleep(settings.sync_interval_minutes * 60)
        try:
            await asyncio.to_thread(sync.sync_all, get_connection(settings.db_path))
        except Exception:
            # 单源失败已记入 sync_state；循环本身不能死
            continue
```
（`get_connection` 已在 app.py 导入则复用，否则从 `.db` 补导入。）
`create_app()` 内注册路由处加：
```python
    from .routers.sync import router as sync_router
    app.include_router(sync_router, prefix="/api")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_api.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 4 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add src/workledger/services/sync.py src/workledger/routers/sync.py src/workledger/app.py tests/test_sync_api.py
git commit -m "Add sync orchestration, health and sync endpoints, background polling"
git push origin main
```

---

### Task 6: 项目汇总服务 + 端点

**Files:**
- Create: `src/workledger/services/summary.py`
- Create: `src/workledger/routers/summary.py`
- Modify: `src/workledger/app.py`（注册 summary router）
- Test: `tests/test_summary.py`

**Interfaces:**
- Consumes: Task 1 `sync_state.get_states/is_stale`；Task 2 `jira_import.is_done`；Task 4 PR 锚点 extra_json 契约；`work_events`/`work_items`/`todos`/`projects` 表
- Produces:
  - `summary.parse_window(window: str) -> int`（`"7d"` → 7；非法或 >90 → ValueError）
  - `summary.project_summary(conn, key: str, window: str = "7d") -> dict`（未知 key → KeyError；结构见 spec §9）
  - HTTP：`GET /api/summary/project?key=RW&window=7d`（404 未知 key / 422 非法 window）

- [ ] **Step 1: 写失败测试** `tests/test_summary.py`

```python
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from workledger.config import settings
from workledger.schemas import EventCreate, TodoCreate
from workledger.services import events, jira_import, master_data, summary, sync_state, todos
from workledger.work_item_models import WorkItemCreate
from workledger.services import work_items


@pytest.fixture()
def seeded(conn, monkeypatch):
    monkeypatch.setattr(settings, "sync_bitbucket_workspace", "transfinderorg")
    monkeypatch.setattr(settings, "sync_bitbucket_repos", "core")
    monkeypatch.setattr(settings, "sync_bitbucket_project", "RW")
    rw = master_data.create_project(conn, name="RW (Atlas)", key="RW")
    wl = master_data.create_project(conn, name="WorkLedger", key="WL")
    today = date.today()
    recent = (today - timedelta(days=2)).isoformat()
    old = (today - timedelta(days=40)).isoformat()
    jira_import.import_issues(conn, [
        {"key": "RW-1", "summary": "Open one", "created": f"{old}T09:00:00+0800",
         "updated": f"{recent}T09:00:00+0800",
         "status": {"name": "In Progress", "statusCategory": {"key": "indeterminate"}}},
        {"key": "RW-2", "summary": "Legacy done", "created": f"{old}T09:00:00+0800",
         "status": {"name": "已完成"}},
        {"key": "RW-3", "summary": "Old backlog", "created": f"{old}T09:00:00+0800",
         "updated": f"{old}T09:00:00+0800",
         "status": {"name": "In Backlog", "statusCategory": {"key": "new"}}},
    ], project_key="RW", project_name="RW")
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=datetime.now(UTC), repo="transfinderorg/core",
        pr_number=10, source_key="bitbucket:transfinderorg/core:pr:10", source_agent="bitbucket-sync",
        summary="feat(RW-1): open PR", jira_key="RW-1",
        extra_json=json.dumps({"state": "OPEN", "bitbucket_updated": datetime.now(UTC).isoformat(),
                               "author": "JasonZhong", "author_uuid": "{jason-uuid}",
                               "reviewers": [{"name": "JasonZhong", "uuid": "{jason-uuid}", "approved": False}],
                               "jira_keys": ["RW-1"], "url": "https://bitbucket.org/pr/10"}),
    ))
    events.create_event(conn, EventCreate(
        event_type="pr_created", occurred_at=datetime.now(UTC) - timedelta(days=50),
        repo="transfinderorg/core", pr_number=11,
        source_key="bitbucket:transfinderorg/core:pr:11", source_agent="bitbucket-sync",
        summary="old merged", extra_json=json.dumps({"state": "MERGED", "bitbucket_updated": old + "T00:00:00+00:00",
                                                    "author": "Other", "author_uuid": "{other}",
                                                    "reviewers": [], "jira_keys": []}),
    ))
    overdue = todos.create_todo(conn, TodoCreate(title="Overdue WL", due_date=(today - timedelta(days=1)).isoformat()))
    conn.execute("UPDATE todos SET project_id=? WHERE id=?", (wl["id"], overdue["id"]))
    rw_event = events.create_event(conn, EventCreate(event_type="manual", occurred_at=datetime.now(UTC), summary="RW context"))
    conn.execute("UPDATE work_events SET project_id=? WHERE id=?", (rw["id"], rw_event["id"]))
    todos.create_todo(conn, TodoCreate(title="RW open", event_id=rw_event["id"]))
    work_items.create_work_item(conn, WorkItemCreate(title="Track RW-1", jira_key="RW-1", project_id=rw["id"]))
    sync_state.record_success(conn, "bitbucket:transfinderorg/core", {"my_uuid": "{jason-uuid}"})
    return rw


def test_counts_open_done_and_chinese_fallback(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d")
    assert result["tickets"]["counts"]["open"] == 2
    assert result["tickets"]["counts"]["done"] == 1
    assert result["tickets"]["counts"]["by_status"]["已完成"] == 1
    keys = {t["key"] for t in result["tickets"]["open"]}
    assert keys == {"RW-1", "RW-3"}


def test_changed_window_and_pr_counts(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d")
    assert {t["key"] for t in result["tickets"]["changed_in_window"]} == {"RW-1"}
    assert result["prs"]["counts"] == {"open": 1, "merged": 0, "needs_review": 1}
    assert result["prs"]["items"][0]["mine"]["needs_my_review"] is True
    assert result["tickets"]["open"][0]["work_item_id"] is not None


def test_todos_overdue_global_and_work_items(seeded, conn):
    result = summary.project_summary(conn, "RW", "7d")
    assert result["todos"]["overdue_global"][0]["project_key"] == "WL"
    assert result["todos"]["project_open"][0]["title"] == "RW open"
    assert result["work_items"]["open"] == 1


def test_unknown_key_and_bad_window(seeded, conn):
    with pytest.raises(KeyError):
        summary.project_summary(conn, "NOPE")
    with pytest.raises(ValueError):
        summary.project_summary(conn, "RW", "91d")
    with pytest.raises(ValueError):
        summary.project_summary(conn, "RW", "abc")


def test_sync_section_present(seeded, conn):
    result = summary.project_summary(conn, "RW")
    assert "sync" in result
    assert result["window"]["days"] == 7
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_summary.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

`src/workledger/services/summary.py`:
```python
"""Assistant-facing project summary with explicit freshness."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta

from ..config import settings
from . import jira_import, sync_state


def parse_window(window: str) -> int:
    match = re.fullmatch(r"(\d+)d", window.strip())
    if not match or not 1 <= int(match.group(1)) <= 90:
        raise ValueError("Window must look like '7d' (1-90 days).")
    return int(match.group(1))


def _ticket(row: sqlite3.Row, item_ids: dict) -> dict:
    extra = json.loads(row["extra_json"] or "{}")
    return {
        "key": row["jira_key"], "summary": row["summary"],
        "status": extra.get("status"), "assignee": extra.get("assignee_name"),
        "updated": extra.get("jira_updated"), "url": extra.get("jira_url"),
        "work_item_id": item_ids.get(row["jira_key"]),
        "done": jira_import.is_done(extra.get("status_category"), extra.get("status")),
    }


def project_summary(conn: sqlite3.Connection, key: str, window: str = "7d") -> dict:
    days = parse_window(window)
    project = conn.execute("SELECT * FROM projects WHERE key=?", (key.strip().upper(),)).fetchone()
    if project is None:
        raise KeyError(f"Project {key.strip().upper()} not found")
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    today_iso = today.isoformat()

    item_ids = {
        row["jira_key"]: row["id"]
        for row in conn.execute(
            "SELECT id, jira_key FROM work_items WHERE jira_key IS NOT NULL AND project_id=?",
            (project["id"],),
        )
    }
    tickets = [
        _ticket(row, item_ids)
        for row in conn.execute(
            "SELECT jira_key, summary, extra_json FROM work_events "
            "WHERE source_agent='jira-import' AND jira_key IS NOT NULL AND project_id=? ORDER BY jira_key",
            (project["id"],),
        )
    ]
    by_status: dict[str, int] = {}
    for ticket in tickets:
        name = ticket["status"] or "?"
        by_status[name] = by_status.get(name, 0) + 1
    open_tickets = [t for t in tickets if not t["done"]]
    changed = [t for t in tickets if t["updated"] and start <= t["updated"][:10] <= today_iso]

    states = sync_state.get_states(conn)
    my_uuid = next(
        (s["detail"].get("my_uuid") for s in states.values()
         if s["source"].startswith("bitbucket:") and s["detail"].get("my_uuid")),
        None,
    )
    prs = []
    if key.strip().upper() == settings.sync_bitbucket_project.upper():
        repos = [f"{settings.sync_bitbucket_workspace}/{r.strip()}" for r in settings.sync_bitbucket_repos.split(",") if r.strip()]
        placeholders = ", ".join("?" for _ in repos)
        for row in conn.execute(
            f"SELECT repo, pr_number, summary, extra_json FROM work_events "
            f"WHERE source_agent='bitbucket-sync' AND event_type='pr_created' AND repo IN ({placeholders})",
            repos,
        ):
            extra = json.loads(row["extra_json"] or "{}")
            state = extra.get("state")
            updated = (extra.get("bitbucket_updated") or "")[:10]
            if state != "OPEN" and not (start <= updated <= today_iso):
                continue
            reviewers = extra.get("reviewers") or []
            mine_review = next((r for r in reviewers if r.get("uuid") == my_uuid), None)
            prs.append({
                "repo": row["repo"], "pr_number": row["pr_number"], "title": row["summary"],
                "state": state, "author": extra.get("author"), "reviewers": reviewers,
                "updated_on": extra.get("bitbucket_updated"), "url": extra.get("url"),
                "jira_keys": extra.get("jira_keys") or [],
                "mine": {
                    "authored": extra.get("author_uuid") == my_uuid,
                    "reviewing": mine_review is not None,
                    "needs_my_review": state == "OPEN" and mine_review is not None and not mine_review.get("approved"),
                },
            })
    pr_counts = {
        "open": sum(1 for p in prs if p["state"] == "OPEN"),
        "merged": sum(1 for p in prs if p["state"] == "MERGED"),
        "needs_review": sum(1 for p in prs if p["mine"]["needs_my_review"]),
    }

    overdue = [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.due_date, t.status, p.key AS project_key FROM todos t "
        "LEFT JOIN work_events e ON t.event_id = e.id "
        "LEFT JOIN projects p ON p.id = COALESCE(t.project_id, e.project_id) "
        "WHERE t.status != 'done' AND t.due_date IS NOT NULL AND t.due_date < ? ORDER BY t.due_date",
        (today_iso,),
    )]
    project_open = [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.status, t.due_date, t.next_followup FROM todos t "
        "LEFT JOIN work_events e ON t.event_id = e.id "
        "WHERE COALESCE(t.project_id, e.project_id) = ? AND t.status != 'done' ORDER BY t.due_date",
        (project["id"],),
    )]
    due_today = [dict(r) for r in conn.execute(
        "SELECT t.id, t.title, t.status, t.due_date FROM todos t "
        "LEFT JOIN work_events e ON t.event_id = e.id "
        "WHERE COALESCE(t.project_id, e.project_id) = ? AND t.status != 'done' AND t.due_date=?",
        (project["id"], today_iso),
    )]
    items = [dict(r) for r in conn.execute(
        "SELECT id, title, stage, jira_key, next_step, followup_date, needs_decision FROM work_items "
        "WHERE project_id=? AND stage != 'done' ORDER BY needs_decision DESC, updated_at DESC",
        (project["id"],),
    )]
    return {
        "project": {"id": project["id"], "key": project["key"], "name": project["name"]},
        "window": {"days": days, "from": start, "to": today_iso},
        "generated_at": sync_state.utc_now_iso(),
        "tickets": {
            "counts": {"open": len(open_tickets), "done": len(tickets) - len(open_tickets), "by_status": by_status},
            "open": open_tickets, "changed_in_window": changed,
        },
        "prs": {"counts": pr_counts, "items": prs},
        "todos": {"overdue_global": overdue, "project_open": project_open, "due_today": due_today},
        "work_items": {
            "open": len(items), "needs_decision": sum(1 for i in items if i["needs_decision"]), "items": items,
        },
        "sync": {
            source: {
                "last_sync_at": state["last_success_at"],
                "stale": sync_state.is_stale(state, settings.sync_interval_minutes),
                "last_error": state["last_error"],
            }
            for source, state in states.items()
        },
    }
```

`src/workledger/routers/summary.py`:
```python
"""Project summary endpoint for assistants."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..db import get_connection
from ..services import summary

router = APIRouter(tags=["summary"])


def _conn():
    return get_connection(settings.db_path)


@router.get("/summary/project")
def get_project_summary(key: str, window: str = "7d"):
    try:
        return summary.project_summary(_conn(), key, window)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
```

`app.py` `create_app()` 加：
```python
    from .routers.summary import router as summary_router
    app.include_router(summary_router, prefix="/api")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_summary.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 5 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add src/workledger/services/summary.py src/workledger/routers/summary.py src/workledger/app.py tests/test_summary.py
git commit -m "Add project summary API with counts and freshness"
git push origin main
```

---

### Task 7: 按周导出

**Files:**
- Modify: `src/workledger/services/export.py:12`（Period）与 `period_range`（89-102 行区域）
- Test: `tests/test_export.py`（追加）

**Interfaces:**
- Consumes: 无新依赖
- Produces: `Period = Literal["week", "month", "quarter", "year", "all"]`；`period_range("week", today=…)` 返回周一→today（与 `work_review.weekly_review` 的周界一致）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_export.py`）

```python
def test_week_period_runs_monday_to_today():
    from datetime import date

    from workledger.services.export import period_range
    wednesday = date(2026, 11, 25)
    assert period_range("week", today=wednesday) == ("2026-11-23", "2026-11-25")
    monday = date(2026, 11, 23)
    assert period_range("week", today=monday) == ("2026-11-23", "2026-11-23")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_export.py::test_week_period_runs_monday_to_today -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（ValueError: Period must be month, quarter, year, or all.）

- [ ] **Step 3: 实现**

`export.py` 第 12 行：
```python
Period = Literal["week", "month", "quarter", "year", "all"]
```
`period_range` 在 `if period == "month":` 之前加：
```python
    if period == "week":
        start = today - timedelta(days=today.weekday())
```
（文件已导入 `from datetime import date`，补 `timedelta`。）错误消息改为 `"Period must be week, month, quarter, year, or all."`。

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_export.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 全绿

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add src/workledger/services/export.py tests/test_export.py
git commit -m "Add week period to retrospective export"
git push origin main
```

---

### Task 8: MCP 工具 + examples 配置

**Files:**
- Modify: `src/workledger/mcp_server.py`（`record_lesson_use` 之后、`main()` 之前追加 4 个 tool）
- Modify: `examples/mcp-config.json`
- Test: `tests/test_sync_mcp.py`

**Interfaces:**
- Consumes: Task 3/4/6 服务函数；Task 1 `sync_state.get_states/is_stale`
- Produces: MCP tools `sync_jira() -> str`、`sync_bitbucket() -> str`、`get_project_summary(key: str, window: str = "7d") -> str`、`get_sync_status() -> str`（JSON 字符串，错误走 `_err` 模式）

- [ ] **Step 1: 写失败测试** `tests/test_sync_mcp.py`

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_mcp.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: FAIL（AttributeError: module has no attribute sync_jira）

- [ ] **Step 3: 实现**

`mcp_server.py` 追加（`record_lesson_use` 之后）：
```python
@mcp.tool()
def sync_jira() -> str:
    """Refresh Jira RW/AIP snapshots and auto work items. Returns counts and freshness."""
    from .services import sync_jira as service
    try:
        return json.dumps(service.sync_jira(_conn()), ensure_ascii=False)
    except _TOOL_ERRORS as e:
        return _err(e)


@mcp.tool()
def sync_bitbucket() -> str:
    """Refresh my Bitbucket PRs (author or reviewer, last 30 days) across configured repos."""
    from .services import sync_bitbucket as service
    try:
        return json.dumps(service.sync_bitbucket(_conn()), ensure_ascii=False)
    except _TOOL_ERRORS as e:
        return _err(e)


@mcp.tool()
def get_project_summary(key: str, window: str = "7d") -> str:
    """One-call project briefing data: tickets, PRs, todos, work items, counts and sync freshness."""
    from .services import summary
    try:
        return json.dumps(summary.project_summary(_conn(), key, window), ensure_ascii=False)
    except KeyError as e:
        return json.dumps({"error": str(e)})
    except _TOOL_ERRORS as e:
        return _err(e)


@mcp.tool()
def get_sync_status() -> str:
    """Last sync time, errors and staleness per source (jira, bitbucket repos)."""
    from .services import sync_state
    try:
        states = sync_state.get_states(_conn())
        return json.dumps({
            source: {**state, "stale": sync_state.is_stale(state, settings.sync_interval_minutes)}
            for source, state in states.items()
        }, ensure_ascii=False)
    except _TOOL_ERRORS as e:
        return _err(e)
```

`examples/mcp-config.json` 整体替换：
```json
{
  "mcpServers": {
    "workledger": {
      "command": "D:/AI/Projects/WorkLedger/.venv/Scripts/python.exe",
      "args": ["-m", "workledger.mcp_server"],
      "cwd": "D:/AI/Projects/WorkLedger",
      "env": {
        "WORKLEDGER_DATA_DIR": "D:/AI/Projects/WorkLedger/data"
      }
    }
  }
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/Scripts/python.exe -m pytest tests/test_sync_mcp.py -q --basetemp="D:\tmp\Debug\pytest-workledger"`
Expected: 1 passed

- [ ] **Step 5: 全套回归 + 提交**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add src/workledger/mcp_server.py examples/mcp-config.json tests/test_sync_mcp.py
git commit -m "Expose sync and summary MCP tools with portable stdio config"
git push origin main
```

---

### Task 9: Live 冒烟 + 文档 + 收尾

**Files:**
- Modify: `README.md`、`SKILL.md`（同步/汇总使用说明）
- 运维操作：备份、重启服务、真实同步（不改代码）

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 运行中的最新版服务 + 真实数据验证 + 文档

- [ ] **Step 1: 备份数据库**

```bash
.venv/Scripts/python.exe -m workledger.cli backup "data/backups/pre-sync-$(date +%Y%m%d-%H%M%S).db"
```

- [ ] **Step 2: 重启服务加载新代码**

```bash
taskkill //PID 61372 //F   # PID 以 netstat -ano | grep :8600 实测为准
```
后台启动（run_in_background）：
```bash
.venv/Scripts/python.exe -m uvicorn workledger.app:app --host 127.0.0.1 --port 8600
```
等 `curl -s http://127.0.0.1:8600/api/health` 返回 `"status":"ok"` 且 `schema_version>=10`。

- [ ] **Step 3: 真实同步并断言**

```bash
curl -s -X POST http://127.0.0.1:8600/api/sync/jira
curl -s -X POST http://127.0.0.1:8600/api/sync/bitbucket
```
用 python 脚本断言（读 API 返回 + DB）：
- jira 结果 `ok=True`；`RW-82353` 在 `work_events`；`AIP-96` 不在；
- 6 张历史「已完成」票**没有** work item；`RW-81100`（Acceptance）有 verification item（若 assignee 仍是 Jason）；
- bitbucket 三源 `ok=True`，`work_events` 有 `source_agent='bitbucket-sync'` 锚点，且**没有**新增 manual 迁移事件；
- `GET /api/summary/project?key=RW&window=7d`：tickets/prs counts 非零、sync 段 `stale=False`；
- `GET /api/work-review/weekly` groups 非空；`POST /api/work-review/briefing`（project_id=RW）返回非空 items。
若 Bitbucket q 语法返回 400，调整 `_fetch_prs` 的日期引号格式后重跑单测与冒烟。

- [ ] **Step 4: 文档**

README.md 与 SKILL.md 各加一节（位置：现有 Jira 导入说明附近），内容要点：
- 同步：`POST /api/sync/jira|bitbucket|all`、`GET /api/sync/status`、后台 15 分钟 polling（`SYNC_INTERVAL_MINUTES`，0=关）；
- 汇总：`GET /api/summary/project?key=RW&window=7d`（含 counts 与 stale 标记）；`GET /api/health`；
- 凭据：.env 的 ATLASSIAN_*/TWG_CLI_PATH；Jira 范围 JQL 口径；PR 只同步 authored/reviewed + 30 天窗口；
- MCP：`examples/mcp-config.json`（stdio，本机 IDE 用）；
- 按周导出：`/api/export?period=week`。

- [ ] **Step 5: 全套测试 + 提交 + push**

Run: `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp="D:\tmp\Debug\pytest-workledger"`
```bash
git add README.md SKILL.md
git commit -m "Document sync, summary, and health workflows"
git push origin main
```

---

## Self-Review 记录

- Spec 覆盖：§5 migration→T1；§5 jira_import 增强→T2；§6→T3；§7→T4；§8→T5；§9→T6（health 在 T5）；§10→T8；§11→T7；§13 live 冒烟→T9；§14 基线提交已在计划前完成（15e58a5）。
- 类型一致性：`sync_jira(conn, *, runner=None)`、`sync_bitbucket(conn, *, client=None)`、`run_locked(source, fn, conn)`、`project_summary(conn, key, window)` 在各任务间引用一致；PR extra_json 字段名 T4 定义 T6 消费一致。
- 已知风险：Bitbucket q 的日期字面量引号格式未在 live 验证（T9 Step 3 有回退步骤）；twg 低于最低支持版本但仍可用（spec 已记录，升级由用户决定）。