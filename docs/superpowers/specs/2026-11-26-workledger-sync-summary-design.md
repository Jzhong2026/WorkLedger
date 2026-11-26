# WorkLedger 外部同步与项目汇总 — 设计文档

日期：2026-11-26 · 状态：待用户评审 · 分支：main（不新建分支）

## 1. 背景与目标

WorkLedger（FastAPI + SQLite + Vue3 SPA，端口 8600）目前只有 2026-11-18 导入的 Jira 快照，
无实时同步、无 Bitbucket 数据、无汇总接口、无 `/api/health`；周报/briefing 因缺 work item 而为空。

目标：让助手（MCP/HTTP）能拿到**带新鲜度标记的**项目日常汇总。

1. Jira RW/AIP 同步（跳过 AIP-96），记录上次同步时间。
2. Bitbucket `transfinderorg/core`、`routefinderapi`、`routefinder-web` 的 PR 同步（只与 Jason 相关）。
3. `GET /api/summary/project?key=RW&window=7d`：明细 + 汇总计数 + 同步时间 + stale 标记。
4. `GET /api/health`、`POST /api/sync/*`、`GET /api/sync/status`；MCP 新增同步/汇总 tools，
   并准备好 `examples/mcp-config.json` 供任意 MCP 客户端接入。
5. Jira 导入后自动生成 work item（仅 Jason 名下、非 Backlog），让周报/briefing 可用。
6. 按周导出：`Period` 增加 `"week"`。

## 2. 非目标（本期跳过，用户已确认）

- Knowledge Vault / Confluence 关联。
- Jira/Bitbucket webhook（本机 127.0.0.1 无公网入口；polling 覆盖需求）。
- 前端 UI 改动。**下一期跟进（用户已提出）**：前端加一条同步状态；
  insights 按来源（人工/Jira/Bitbucket）分开统计。

## 3. 已确认决策

| 决策 | 内容 |
|---|---|
| 方案 | A：后端内置同步服务（lifespan polling + 手动触发），否决外部计划任务与 webhook |
| Jira 范围 | `project in (RW,AIP) AND key != AIP-96 AND (assignee = currentUser() OR updated >= -30d OR key in (已导入 keys))` —— 项目汇总口径，含他人近期活跃票 |
| PR 范围 | `(author.uuid = Jason OR reviewers.uuid = Jason) AND updated_on >= now-30d`，OPEN/MERGED/DECLINED 全状态 |
| 凭据 | 将 Qoder settings.json 中现有 `ATLASSIAN_USER_EMAIL`/`ATLASSIAN_API_TOKEN` 复制到 WorkLedger `.env`（已 gitignore，用户已批准）。Jira 走 twg CLI，无需额外凭据 |
| PR 事件形态 | **不用新 event_type**（enum 是 CHECK 闭集）。每 PR 一条 `pr_created` 锚点事件，状态变化只更新锚点 `extra_json.state`；**不追加迁移事件**（现有 Jira 快照已是 manual，追加会污染周报/导出/insights） |
| Backlog 票 | **不建 work item**（`waiting` 语义是等待/阻塞，且 stage 是 SQL CHECK 闭集，加值需重建表）。票在 summary tickets 中可见；转 In Progress 后下次同步自动建 item |
| 历史 Done 票 | **不建 work item**（避免刷屏 briefing）；仅当本次同步观察到 非done→done 迁移（刚完成）时补建 done item |
| 他人票 | 只进 work_events 快照供汇总计数，**不建 work item**（briefing 保持 Jason 的工作） |
| MCP 交付 | Jason 日常走 HTTP 127.0.0.1:8600；stdio MCP 给本机 IDE 用，准备好 `examples/mcp-config.json`（.venv 解释器绝对路径），不注册进 Qoder |

已验证的可行性（2026-11-26 实测）：
- twg CLI（v1.3.3，transfinder 站点）查询成功；线上已出现快照外的新票 RW-82353（In Progress）。
  返回的 status 对象**含 statusCategory（new/indeterminate/done），已实测确认**。
  注意：twg 提示低于最低支持版本 1.4.4，建议用户自行 `twg upgrade`（不在本任务内执行）。
- 账本内 6 张已完成票的 status 为中文 **「已完成」**（已实测），回退列表必须包含。
- Bitbucket REST + 现有 token：三仓库均 200；Jason uuid `{d78122ae-7322-4d1a-8dcc-77e9c3a5059e}`，
  `author.uuid OR reviewers.uuid` 过滤有效。
- 旧记忆中"Bitbucket 停用"指 `transfinder`/`jasonzhong` workspace，与本次 `transfinderorg` 无关。

## 4. 架构总览

```
lifespan 后台任务(每15min) ─┐
POST /api/sync/* ──────────┤→ services/sync.py ──→ twg CLI subprocess (Jira)
                           │        │            httpx REST (Bitbucket)
                           │        ├→ services/jira_import.py（自 scripts/import_jira.py 移入）
                           │        │     └→ work_events 票据快照 + 自动 work_items
                           │        ├→ work_events PR 锚点（state 存 extra_json）
                           │        └→ sync_state 表（last_success/last_error/detail）
GET /api/summary/project ──→ services/summary.py（读 work_events/work_items/todos/sync_state）
GET /api/health ───────────→ db 检查 + schema_version + 各源新鲜度
MCP tools ─────────────────→ 同一批 service 函数
```

## 5. 数据模型 — migration 010

```sql
CREATE TABLE sync_state (
    source TEXT PRIMARY KEY,           -- 'jira' | 'bitbucket:transfinderorg/core' | ...
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    detail_json TEXT                   -- 计数、截断警告、缓存的 accountId/uuid 等
);
```

不新增实体表。票据沿用现有 `work_events` 快照模式（`source_key='jira:KEY'`，
`source_agent='jira-import'` 保持不变以兼容现有数据与 importer 守卫）。
**jira_import 增强**：extra_json 新增 `status_category`（twg 返回的 statusCategory.key：
new/indeterminate/done）与 `assignee_account_id`（assignee.accountId），
供 summary 判定 open/done、stage 映射与归属判断；
旧数据无 status_category 时按 status 名回退：
Done/Closed/Resolved/Cancelled/**已完成**/已关闭/已解决/已取消 → done，其余 → open。

**PR 事件规则：**
- 锚点：`event_type='pr_created'`，`repo='transfinderorg/core'`（含 workspace 前缀），
  `pr_number`，`source_key='bitbucket:{ws}/{repo}:pr:{id}'`，`source_agent='bitbucket-sync'`，
  `occurred_at=PR created_on`（不可变），`project_id=`映射项目（默认 RW），
  `jira_key=`标题提取的第一个 key，`summary=`PR 标题。
  `extra_json`：`{bitbucket_updated, state, author, author_uuid, reviewers:[{name,uuid,approved}],
  url, jira_keys, source_branch, target_branch}`。
- 更新：`bitbucket_updated` 单调递增守卫（旧数据跳过）；summary/detail 尊重人工编辑字段
  （复用 importer 的 `_edited_fields` 模式）；extra_json 总是刷新，**状态变化只改锚点 extra_json.state**。
- **不追加任何迁移事件**：现有 8 条 Jira 快照已是 `manual`，追加会污染周报/导出/insights。
  合并状态一律读锚点 `extra_json.state`；近期合并动态由 summary 按 `bitbucket_updated` 窗口呈现。
- 标题提取 jira key：`\b(?:RW|AIP)-\d+\b`（解析结构化票号，非用户意图识别）。

## 6. Jira 同步（services/sync.py::sync_jira）

1. 从 DB 取已导入 keys（`work_events.jira_key` 非空、属于同步项目，**不设数量上限**，保证旧票不掉出同步）。
2. 组装 JQL（§3），调 twg：
   `twg jira workitem query --site transfinder --jql … --fields key,summary,status,issuetype,priority,assignee,parent,created,updated,description --limit 100 --output json`。
   twg 每页上限 100，用 `pageInfo.hasNextPage/nextCursor` + `--after` 游标翻页，安全上限 50 页（5000 条）；
   达到上限时 detail_json 记 `truncated: true`。twg 路径来自 settings（.env 配全路径）；
   从命令输出解析 `output_files.stdout` 路径读 JSON。
   **已导入 keys 刷新不得内联进主 JQL**（数千 key 会超 Windows 命令行 32767 字符上限）：
   先跑 scope 查询（assignee/updated 窗口），再对**缺失**的已导入 keys 按 500/块分块查询合并。
3. 调 `jira_import.import_issues()`（核心逻辑自 `scripts/import_jira.py` 移入
   `src/workledger/services/jira_import.py`；脚本保留为薄 CLI 壳；测试导入路径同步更新），
   `base_url="https://transfinder.atlassian.net"` 保证 browse 链接。
   AIP 项目由 import_issues 自动创建。
4. **自动 work item**（仅当 `assignee.accountId == Jason 的 accountId`，**用 accountId 判断，不用人名**）：
   - Jason accountId 首次同步时用一条轻量查询 `assignee = currentUser() AND project in (RW,AIP)`
     （limit 1）取得并缓存于 `sync_state('jira').detail_json`；取不到时本轮跳过自动建 item 并记录，不猜。
   - 该 jira_key 无 work_items 行时创建：`WorkItemCreate(title=summary, jira_key, project_id,
     source_event_id=快照事件id, source_key='jira-item:KEY', actor='jira-sync', stage=映射)`。
   - 创建范围（按 statusCategory + status 名）：
     `indeterminate→active`（status 名含 Acceptance/Verification/Review 时→`verification`）；
     `done`→**仅当本次同步观察到 非done→done 迁移**（对比上一快照的 status_category/status）时建 done item，
     历史 Done 票不建（避免刷屏 briefing）；`new（Backlog/To Do）→不建`。
   - 已存在的 item 绝不覆盖、**绝不删除**：创建前按 jira_key 查存在性（规避 source_key fingerprint 409）；
     **负责人改走后已有 item 保留**。
5. 写 sync_state：计数（created/updated/unchanged/items_created）、last_success_at。

## 7. Bitbucket 同步（services/sync.py::sync_bitbucket）

1. 凭据：settings `atlassian_user_email`/`atlassian_api_token`（.env）。缺失→该源报错记录，不崩。
2. Jason uuid：每次 sync_bitbucket 运行开始时 `GET /user` 获取一次（单次轻量请求，不做缓存）。
3. 每仓库：`GET /2.0/repositories/{ws}/{repo}/pullrequests`，
   `q=(author.uuid="{uuid}" OR reviewers.uuid="{uuid}") AND updated_on >= {now-30d}`，
   `sort=-updated_on`，`pagelen=50` 翻页直到超出窗口。
4. 按 §5 规则 upsert 锚点（状态只存 extra_json，无迁移事件）；写 sync_state（每仓库一行）。
5. httpx 升为主依赖（pyproject dependencies）。

## 8. 调度与触发

- lifespan 启动 asyncio 后台任务：每 `sync_interval_minutes`（默认 15，0=关闭）
  在 `asyncio.to_thread` 中跑 sync_all；shutdown 时取消。
- 每源一把 threading.Lock，手动与后台互斥；拿不到锁的手动请求返回 409 "sync in progress"。
- `POST /api/sync/jira`、`POST /api/sync/bitbucket`、`POST /api/sync`（全部）：
  同步执行并返回各源结果计数；失败返回 502 + 错误详情（已写入 sync_state）。
- `GET /api/sync/status`：所有源的 last_attempt/last_success/last_error/stale/detail。
- 任何同步失败只影响该源，服务与既有数据不受影响。

## 9. API 契约

### GET /api/health
```json
{"status":"ok","db":"ok","schema_version":10,"version":"0.1.0",
 "sync":{"jira":{"last_sync_at":"…","stale":false},"bitbucket:transfinderorg/core":{…}}}
```
DB 检查失败 → 503 `{"status":"error",…}`。

### GET /api/summary/project?key=RW&window=7d
- `key`：项目 key（RW/AIP/WL…），未知 key → 404。`window`：`{N}d` 格式，默认 7d，上限 90d。
- repo→项目映射：settings `sync_bitbucket_project`（默认 "RW"），三仓库都映射到该项目。

```json
{
  "project":{"id":2,"key":"RW","name":"RW (Atlas)"},
  "window":{"days":7,"from":"2026-11-19","to":"2026-11-26"},
  "generated_at":"…",
  "tickets":{
    "counts":{"open":8,"done":6,"by_status":{"In Progress":3,"In Backlog":2,"Acceptance":1,"Done":6}},
    "open":[{ "key","summary","status","assignee","updated","url","work_item_id" }],
    "changed_in_window":[ 同上结构 ]
  },
  "prs":{
    "counts":{"open":3,"merged":5,"needs_review":2},
    "items":[{ "repo","pr_number","title","state","author","reviewers","updated_on","url",
               "jira_keys","mine":{"authored":true,"reviewing":false,"needs_my_review":false} }]
  },
  "todos":{
    "overdue_global":[{ "id","title","due_date","project_key","status" }],
    "project_open":[…], "due_today":[…]
  },
  "work_items":{"open":4,"needs_decision":1,"items":[{ "id","title","stage","jira_key","next_step","followup_date" }]},
  "sync":{ 同 /api/sync/status 结构 }
}
```

口径定义：
- tickets.open = statusCategory ≠ done 的全部已同步票（不受 window 限制）；
  changed_in_window = `extra_json.jira_updated` 落在窗口内；counts.by_status 覆盖全部已同步票。
- prs.items = state=OPEN 的锚点（始终保留）+ `bitbucket_updated` 在窗口内的 MERGED/DECLINED；
  counts 同口径。**needs_review = OPEN 且 Jason 是 reviewer 且其 approved=false**。
- todos.overdue_global = 全库 status≠done 且 due_date<today（跨项目，带 project_key）；
  project_open/due_today 限本项目。
- stale = 从未成功同步，或 now-last_success > max(2×interval, 30min)；interval=0 时阈值 24h。
- 所有时间输出 ISO 格式；summary 永远携带 sync 段，过期数据显式可见。

## 10. MCP

- 新增 4 tools（共 42）：`sync_jira()`、`sync_bitbucket()`、`get_project_summary(key, window="7d")`、
  `get_sync_status()`。复用 service 函数，JSON 字符串输出，沿用 `_err` 错误模式。
- `examples/mcp-config.json`：stdio 模板给本机 IDE 用，解释器用
  `D:/AI/Projects/WorkLedger/.venv/Scripts/python.exe`（已验证：该 venv 装有 workledger，
  运行中的服务也用此解释器）+ `-m workledger.mcp_server` + cwd + `WORKLEDGER_DATA_DIR`。
- Jason 日常走 HTTP 127.0.0.1:8600，不做 Qoder MCP 注册。
- SQLite 已是 WAL，MCP 进程与 Web 进程并发读写安全。

## 11. 按周导出

`services/export.py`：`Period` 加 `"week"`；`period_range` 支持周一–周日（与 weekly_review 一致）。
`/api/export?period=week` 与 MCP 既有导出 tool 自动受益。

## 12. 配置与凭据

`.env` 追加（值不入库不入 git）：
```
ATLASSIAN_USER_EMAIL=…        # 自 Qoder settings.json 复制
ATLASSIAN_API_TOKEN=…
TWG_CLI_PATH=C:\Users\jason\AppData\Local\Programs\twg\bin\twg
SYNC_INTERVAL_MINUTES=15
```
settings 新增（均有默认值）：`atlassian_user_email`、`atlassian_api_token`、`twg_cli_path="twg"`、
`sync_interval_minutes=15`、`sync_jira_site="transfinder"`、`sync_jira_projects="RW,AIP"`、
`sync_jira_exclude="AIP-96"`、`sync_jira_window_days=30`、`sync_bitbucket_workspace="transfinderorg"`、
`sync_bitbucket_repos="core,routefinderapi,routefinder-web"`、`sync_bitbucket_project="RW"`、
`sync_bitbucket_window_days=30`。

## 13. 测试与验证（TDD）

单测（fake twg runner 注入 + httpx MockTransport，不打真实网络）：
- migration 010 在现有 schema 上干净应用。
- jira_import 模块迁移后现有测试全绿（更新导入路径）。
- sync_jira：JQL 组装（含 exclude/全部已导入 keys/30d）、事件创建、仅 Jason accountId 建 item、
  创建范围（In Progress/Acceptance 建、历史 Done 不建、非done→done 迁移建 done item、Backlog 不建）、
  负责人改走不删已有 item、重复同步幂等、sync_state 记录、截断警告。
- sync_bitbucket：锚点创建、状态变化只更新 extra_json.state（不新增事件）、重跑不重复、
  人工编辑 summary 保留、bitbucket_updated 单调守卫、needs_review 判定。
- summary：counts/open/changed 口径、status_category 旧数据回退（含「已完成」）、window 边界、
  未知 key 404、stale 判定、overdue_global。
- health/sync 端点（TestClient）；export week 区间。

 live 冒烟（实现完成后）：
- 备份 DB（`workledger backup`）→ 重启服务（旧进程 taskkill）→ migration 自动应用。
- 真实同步一次：断言 RW-82353 进账本、AIP-96 不在、PR 锚点存在、work item 只按创建范围生成
  （6 张历史「已完成」票不建 item）、
  `/api/summary/project?key=RW&window=7d` 与 `/api/health` 返回正确、周报/briefing 非空。

## 14. 交付顺序

0. **基线提交**：先把未提交的 work_items/learning/周报代码单独 commit（全套 126 测试已验证绿，
   `.env` 与 `data/` 不提交），再开始本次实现，不混在一起。
1. migration 010 + settings + .env 凭据 → 2. jira_import 模块迁移 → 3. sync_jira + 自动 item →
4. sync_bitbucket → 5. 调度/触发/health/sync 端点 → 6. summary → 7. MCP tools + examples 配置 →
8. export week → 9. live 冒烟 + 文档（README/SKILL.md 同步说明）→ 10. commit + push（main）。