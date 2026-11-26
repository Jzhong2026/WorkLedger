---
name: workledger
description: Use WorkLedger MCP to resume work by project or Jira issue, checkpoint verified progress, hand off to another agent, recall reviewed lessons, or prepare an evidence-backed work report.
---

# WorkLedger Agent Skill

Record, search, and follow up on your work — PR reviews, fixes, verification, replies, accomplishments, and lessons — through a local-first SQLite assistant.

## When to use

Invoke WorkLedger tools when you:
- Create or review a PR and want to record findings, decisions, and fixes
- Analyze a review comment and decide on a root cause or action
- Apply a fix and run verification
- Draft or publish a reply to a review comment
- Complete a meaningful accomplishment worth remembering at year-end
- Encounter a problem worth recording as a case/lesson
- Need to create or update a follow-up to-do
- Want to search past work by keyword, PR, repo, Jira, or date range

## MCP Connection

WorkLedger exposes an MCP server (stdio transport). Add to your MCP config:

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

Or if installed as a package:
```json
{
  "mcpServers": {
    "workledger": {
      "command": "workledger-mcp",
      "env": {
        "WORKLEDGER_DATA_DIR": "./data"
      }
    }
  }
}
```

## Tools

Tools marked 🔑 use the configured built-in agent. The handoff, weekly evidence and lesson-recall tools work locally.

### Starting, handing off, and learning from an assignment

1. Call `get_work_context` with the work item ID, or look up the project/Jira key.
   Read the goal, verified result, blockers, next owner and related confirmed lessons.
   Historical events can be used as the source for a newly tracked item.
2. If the work is new, call `create_work_item` with a `data` object containing a title,
   goal, actor, and stable source key. Link an existing event via `source_event_id`.
3. At a meaningful checkpoint, call `record_work_handoff`. Use the version from context,
   describe your contribution, attach evidence event IDs, and give the next step an owner.
   The optional to-do and event are recorded in the same transaction as the handoff.
4. Retry a delivery with the original source key and payload. On a stale version, read the
   new context and reconcile with the other agent before submitting a new checkpoint.
5. Use `propose_lesson` for a reusable skill or process improvement. Include the source
   item, trigger, first step and limits. An operator reviews candidates in **Lessons**.
   Call `recall_lessons` on later assignments, then `record_lesson_use` with the new
   work item and observed outcome. Use `get_weekly_review` for the week's evidence.

Example handoff tool arguments (replace IDs and version with values from context):

```json
{
  "item_id": 12,
  "data": {
    "expected_version": 1,
    "actor": "Development agent",
    "source_key": "atlas-lookup:unit-check:1",
    "summary": "Implemented the lookup change and ran the targeted tests.",
    "last_verified_result": "Targeted lookup tests passed.",
    "stage": "verification",
    "owner": "QA",
    "next_step": "Verify behavior with the restricted test account.",
    "event_ids": [42],
    "todo": {"title": "Verify restricted-account lookup"}
  }
}
```

### Work events
| Tool | Purpose |
|------|---------|
| `record_event` | Record a work event (review, fix, verification, reply, etc.) |
| `update_event` | Update an existing event (add root cause, verification, evidence) |
| `search_events` | Filter by keyword (Chinese/English), repo, PR, Jira, type, date |
| `get_event_detail` | Full detail of one event with evidence links |
| `get_pr_timeline` | All events for a PR in chronological order |

### To-dos & follow-ups
| Tool | Purpose |
|------|---------|
| `create_todo` | Create a follow-up, optionally linked to an event |
| `update_todo` | Change status (pending/waiting/done), dates, wait target |
| `list_todos` | List to-dos by status |
| `today_followups` | To-dos needing attention today |

### Retrospectives
| Tool | Purpose |
|------|---------|
| `record_accomplishment` | Record an accomplishment for retrospectives |
| `record_case` | Record a problem/lesson with root cause and verification |
| `retrospective` | Get accomplishments, cases, events for month/quarter/year |
| `export_retrospective` | Export structured Markdown (accomplishments/cases/events + evidence) |
| `export_narrative` 🔑 | Agent-synthesized prose retrospective, grounded in records, states coverage gaps |

### Quick inbox (capture first, organize later)
| Tool | Purpose |
|------|---------|
| `capture_note` | Capture a raw natural-language work note (offline) |
| `list_inbox` | List notes by status (raw/structured/committed/discarded) |
| `structure_note` 🔑 | LLM parses a note into draft events (no regex intent matching) |
| `list_drafts` | List pending drafts awaiting confirmation |
| `confirm_draft` | Confirm a draft, committing it to work_events |

### Search
| Tool | Purpose |
|------|---------|
| `search_fulltext` | FTS5 full-text search (Chinese + English), faster than LIKE |
| `search_semantic` 🔑 | Agent expands a vague question into keywords, then retrieves |

### Master data
| Tool | Purpose |
|------|---------|
| `create_project` / `list_projects` / `update_project` / `delete_project` | Manage projects (name/key/repo/color/archive) |
| `create_sprint` / `list_sprints` / `update_sprint` / `delete_sprint` | Manage sprints (one active per project) |

### Insights & evidence
| Tool | Purpose |
|------|---------|
| `get_insights` | Aggregates: totals, events by type/repo/project/month, top root causes, todo status |
| `snapshot_evidence` | Fetch + store an event's evidence URL content to survive link rot (best-effort) |

### Inbox workflow

`capture_note` → `structure_note` (LLM drafts) → human reviews → `confirm_draft` (commits).
The web Inbox can record a note manually without CodeBuddy. AI drafting requires an
enabled and configured CodeBuddy CLI.

## Source identity and deduplication

Every event has a `source_key`. WorkLedger fingerprints the event payload when the
key is omitted, so distinct events can share a PR, comment, and type. Reuse the same
key and payload for a retry. If an explicit key already identifies different
content, the response includes the existing event and `source_conflict: true`.
To-dos also deduplicate when a `source_key` is provided.

## Evidence rules

- `evidence_url`: link to the comment, commit, test result, or PR discussion
- `root_cause`: record even if unconfirmed; set `root_cause_confirmed: false`
- `verification_result`: record what was checked; set `verification_done: false` if not yet run
- `reply_status`: `"draft"` when composing, `"published"` when actually posted
- Missing fields (Jira, links, root cause) are fine — record what you know

## Workflow examples

### Handling a review comment

```
1. record_event(event_type="review_finding", repo="org/repo", pr_number=42,
     comment_id="r1", summary="Missing null check", evidence_url="...")
2. record_event(event_type="comment_analysis", repo="org/repo", pr_number=42,
     comment_id="r1", summary="Agreed, null check needed", root_cause="...",
     root_cause_confirmed=true)
3. record_event(event_type="fix", repo="org/repo", pr_number=42,
     comment_id="r1", summary="Added guard clause", evidence_url="commit-url")
4. record_event(event_type="verification", repo="org/repo", pr_number=42,
     comment_id="r1", summary="Unit test passes", verification_done=true,
     verification_result="test_null_guard passed")
5. record_event(event_type="reply_published", repo="org/repo", pr_number=42,
     comment_id="r1", summary="Replied with fix explanation",
     reply_status="published", evidence_url="comment-url")
6. create_todo(title="Check reviewer response", status="waiting",
     wait_target="reviewer", event_id=<finding_id>, next_followup="2026-11-20")
```

### Backfilling a historical PR

Use the same tools with past `occurred_at` dates. Use a stable explicit `source_key`
when the upstream system supplies a unique identifier for the action.

### Partial access

If you can only read some comments, record what you have. Note coverage in `detail`:
```
record_event(..., detail="Covered comments r1-r3; r4-r5 inaccessible (permissions)")
```

## Error handling

- `retryable: true` → database temporarily locked; wait and retry with same source_key
- `retryable: false` → invalid input or missing record; fix the request
- Write failure never leaves partial data (transactional)
- If WorkLedger is unavailable, continue your development work; retry recording later

## Test prompt

After configuring MCP, verify with:

> Record a manual work event: "WorkLedger skill smoke test", occurred now, source_key "smoke:test:001". Then search for "smoke" and confirm the record appears. Create a to-do "Verify smoke test" linked to that event. Finally call today_followups and confirm the to-do shows.

Expected: one event, one to-do, no duplicates on retry.
