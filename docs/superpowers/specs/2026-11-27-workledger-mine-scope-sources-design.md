# WorkLedger「只看我的」视图、同步稳定性与来源区分 — 设计文档

日期：2026-11-27 · 状态：用户已批准设计（"ok 继续"）· 分支：main（不新建分支）

## 1. 背景与目标

同步/汇总功能已上线（166 测试绿，live 双同步验证）。本轮 5 项增强，按用户优先级：

1. **scope=mine 视图**：`GET /api/summary/project`、`GET /api/export`、`GET /api/work-review/weekly`
   增加 `scope=mine`——只含 assignee 是 Jason 的票 + 他 authored/reviewed 的 PR。项目级全量保留（默认 all）。
2. **Jira 同步稳定性**：truncated=true 时再合并 `assignee=currentUser()` 全量查询；twg 套接字断开自动重试 2 次。
3. **按来源区分事件**：insights/周报/导出把 jira-import、bitbucket-sync、人工记录分开；
   几千条 Jira 快照不再显示成 manual。
4. **前端同步状态**：topbar chip——上次成功时间、是否过期、最近错误（接口字段已齐）。
5. **周回顾带合并 PR**：本周窗口内 MERGED 的 PR 自动进周报并按票号关联 Jira；
   合并结果幂等写成 accomplishments（"做完了什么"）。

## 2. 非目标与不回退约束

- 不做：Knowledge Vault/Confluence 关联、webhook。
- **不回退**：twg 游标分页（100/页，5000 上限）、缺失 keys 按 500/块刷新、历史 Done 不建 work item、
  PR 只用 pr_created 锚点（状态存 extra_json，无迁移事件）、accountId 判断归属、排除 AIP-96、
  event_type 与 stage 的 SQL CHECK 闭集、同步失败只记录不崩。
- 默认行为不变：scope 默认 all；by_type 语义变化见 §6（唯一有意的展示变更）。

## 3. 共享基础 — services/sources.py（新文件）

```python
def event_source(source_agent: str | None) -> str:
    # jira-import → "jira"；bitbucket-sync → "bitbucket"；其余（inbox/handoff/user/None）→ "human"

def mine_predicate(conn: sqlite3.Connection) -> tuple[str, list]:
    """返回 (SQL 片段, 位置参数列表 [my_account_id, my_uuid, my_uuid])。
    身份取自 sync_state detail：jira.my_account_id、任一 bitbucket 源的 my_uuid。
    缺失时对应参数为 None → 分支不匹配（不猜）。"""
```

SQL 片段（位置参数 ?，与 search_events/insights 一致）：
```sql
(
  COALESCE(source_agent, '') NOT IN ('jira-import', 'bitbucket-sync')
  OR (source_agent = 'jira-import'
      AND json_extract(extra_json, '$.assignee_account_id') = ?)
  OR (source_agent = 'bitbucket-sync' AND (
        json_extract(extra_json, '$.author_uuid') = ?
        OR EXISTS (SELECT 1 FROM json_each(json_extract(extra_json, '$.reviewers'))
                   WHERE json_extract(value, '$.uuid') = ?)))
)
```
- SQLite JSON1 已验证可用（migration 009 用过 json_valid/json_type；json_extract 实测通过）。
- source_agent 为 NULL 的人工事件必须通过（COALESCE）。
- `events.search_events` 增加 `scope: str | None = None`；scope=="mine" 时追加上式（表别名适配）。

## 4. 功能 1 — scope=mine

- 三个端点加 `scope` 查询参数，`Literal["all","mine"]`，默认 "all"（FastAPI 自动 422 非法值）。
- **summary**：`project_summary(conn, key, window="7d", scope="all")`。mine 时：
  tickets 仅 assignee_account_id == my_account_id；prs 仅 mine.authored or mine.reviewing；
  counts 在过滤集上重算；todos/work_items 不变（本就是个人记录）；响应加 `"scope"` 字段。
- **export**：`export_markdown(conn, period, *, today=None, scope="all")` → events 段经
  search_events(scope=…) 过滤；accomplishments/cases/lessons/lesson_uses 段不变（人工策展记录）。
- **weekly**：`weekly_review(conn, day=None, project_id=None, scope="all")`。weekly 无分页，
  用 Python 后过滤：SELECT 加 `e.extra_json`，取回行后经 `sources.is_mine_row(source_agent, extra_json, account_id, uuid)`
  过滤（纯函数，可单测）；SQL 保持命名参数不动。accomplishments/cases/lessons 段不变。
- MCP：`get_project_summary(key, window="7d", scope="all")`、`get_weekly_review(day, project_id, scope="all")`、
  `export_retrospective(period, scope="all")` 加参。
- 前端 WeeklyView 加 Mine/All 切换（T7）。

## 5. 功能 2 — 同步稳定性

- **truncated 合并**：scope 查询命中 5000 上限时，追加一次
  `project in (…) AND key not in (…) AND assignee = currentUser()`（无时间窗口）并合并去重。
  未完成已导入票已由现有 missing-keys 分块刷新覆盖（missing = imported − scope_keys，
  open 票必然在 missing 里）——代码验证，不重复查询。
- **twg 重试**：`_twg_runner` 对非零退出/TimeoutExpired/OSError 重试至多 2 次（退避 1s、3s），
  共 3 次尝试；最终失败才抛（进 sync_state 错误包络）。JQL 语法错误也会重试——可接受（用户指定 1-2 次）。
  注入式 fake runner 不经重试（重试只在默认 runner）。

## 6. 功能 3 — 来源区分

- **insights**：新增 `by_source` chart（human/jira/bitbucket 三桶，CASE source_agent 映射）；
  **by_type 改为只统计人工事件**（`COALESCE(source_agent,'') NOT IN ('jira-import','bitbucket-sync')`）——
  同步快照不再灌进 manual 类型图。其余 chart（by_month/by_repo/by_project/root_causes）不变。
- **weekly**：每个 event row 加 `"source"` 字段（event_source 映射）；group 不加（组内可混合来源）。
- **export**：events 段渲染为三个子节 `### Human records` / `### Jira snapshots` / `### Bitbucket PRs`
  （收集全部页后按来源分组渲染；空子节省略；max_chars 预算逻辑保持）。其他段不变。
- **前端**（T7）：InsightsView 加 "By source" doughnut；WeeklyView 事件行加来源 badge。
- 无 migration（source_agent 列已存在）。

## 7. 功能 4 — 前端同步状态（SyncStatus.vue）

- 位置：AppLayout topbar-right，command-trigger 之前。
- Chip：聚合四源状态点（绿=全部新鲜 / 琥珀=任一 stale / 红=任一 last_error）+ "Sync" 标签。
- 点击展开面板（absolute 定位）：每源一行——短名（jira/core/routefinderapi/routefinder-web）、
  上次成功相对时间、stale badge、last_error（截断显示）；底部 "Sync now" 按钮
  （POST /api/sync，busy 禁用 + 完成后刷新状态；失败 toast）。
- 数据：`api.syncStatus()`（GET /api/sync/status），60s 轮询 + 窗口聚焦刷新，卸载清理。
- 设计语言：AgentBoard 企业风，复用现有 CSS 变量（--surface-2/--border/--text-3/--r-full）与
  topbar-tag/badge 样式；移动端 chip 保留（topbar-tag 隐藏规则不影响它）。
- api/client.ts 加 `syncStatus()`、`syncAll()`；types 加 SyncSourceState。
- 验证：`npm run build`（vue-tsc 类型检查）+ 无头 Chrome 截图（系统 Chrome --headless --screenshot，
  不开 GUI 窗口）目视确认 chip/面板渲染。

## 8. 功能 5 — 周回顾合并 PR + accomplishments

- **weekly 查询 OR 分支**（_weekly_snapshot）：
  ```sql
  WHERE (e.occurred_at >= :start AND e.occurred_at < :stop
         OR (e.source_agent = 'bitbucket-sync' AND e.event_type = 'pr_created'
             AND json_extract(e.extra_json, '$.state') = 'MERGED'
             AND substr(json_extract(e.extra_json, '$.bitbucket_updated'), 1, 10) >= :start
             AND substr(json_extract(e.extra_json, '$.bitbucket_updated'), 1, 10) < :stop))
    AND (:project IS NULL OR i.id IS NOT NULL OR e.project_id = :project)
    [AND mine 谓词（scope=mine 时）]
  ```
  合并 PR 按现有键控规则归入 jira_key 组（jira_key 已从标题提取回填）。
- **sync 时写 accomplishment**：`_upsert_pr` 检测 非MERGED→MERGED（含新建 MERGED 锚点），
  把合并信息收集到传入的 merges 列表；**在 per-repo write_transaction 之外**逐条
  `retrospectives.create_accomplishment`（避免 `with conn:` 提交外层事务）：
  - title=`PR #{id} merged: {title}`，occurred_at=updated_on，event_id=锚点 id，
    impact_evidence_url=PR url，description=`{repo} · {author} · {source}→{target}`，tags="pr,merged"，
    source_key=`bitbucket-merge:{repo_full}:pr:{id}`（UNIQUE 幂等，重跑返回已有）。
  - 设置 `sync_record_merge_accomplishments: bool = True` 控制；关闭时不写。
- 周报 accomplishments 段按 occurred_at 窗口自然拾取——GET 无副作用。

## 9. 测试与验证

- 单测（TDD）：sources 谓词（NULL source_agent/缺失身份/reviewers 匹配）、search_events scope、
  summary mine counts、export mine + 子节、weekly mine + 合并 OR 分支、insights by_source/by_type、
  truncated currentUser 合并、重试（monkeypatch subprocess.run：2 败后成/3 败抛）、
  accomplishment 幂等/设置开关/事务边界。
- 前端：vue-tsc 构建通过 + 无头截图目视（chip、面板、by_source 图、weekly badge/toggle）。
- live 冒烟：重启服务 → POST /api/sync（观察 truncated 合并与重试日志）→
  scope=mine 三端点返回只含 Jason 票/PR → weekly 含本周 MERGED PR 组 →
  accomplishments 出现 bitbucket-merge 源_key 记录且重跑不增 → 截图同步 chip。
- 全套 pytest 绿（当前 166 + 新增）。

## 10. 交付顺序

T1 sources 基础 + search_events scope → T2 scope=mine 三端点 + MCP（P1）→
T3 同步稳定性（P2）→ T4 来源区分后端（P3）→ T5 前端 SyncStatus chip（P4）→
T6 周回顾合并 PR + accomplishments（P5）→ T7 前端来源展示 + WeeklyView toggle（P3/P1 UI）→
T8 live 冒烟 + 文档 + 收尾。每任务 commit+push（main）。