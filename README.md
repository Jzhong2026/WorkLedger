# WorkLedger

WorkLedger is a personal work ledger for connecting notes, Jira issues, pull requests,
follow-ups, and evidence. The browser app and stdio MCP server share a SQLite database.

- Use **Today** for due and unscheduled follow-ups.
- Use **Project progress** to track work items, decisions, blockers, next owners and handoffs
  shared with your external agents. Select an existing Jira event to start tracking past work.
- Use **Weekly review** to prepare a Monday–Sunday report from events, confirmed accomplishments
  and applications of lessons. Review suggested highlights before saving them.
- Use **Lessons** to turn a skill or process improvement into a sourced practice, then record
  how it worked on another assignment. Confirmed lessons are included in relevant agent context.
- Use **Inbox** to capture a note, then record it manually or review an AI-generated draft.
- Use **Search** to retrieve past work by text, date, project, Jira key, or PR.
- Create an accomplishment or case from an event to retain its source and evidence.
- Use **Retrospective** to export the selected period as complete Markdown.

See the [Quick Start](examples/quickstart.md) for installation, configuration, Jira import,
and backup. See [SKILL.md](SKILL.md) for MCP tool use.

## Live sync, summary, and health

Set `ATLASSIAN_USER_EMAIL`, `ATLASSIAN_API_TOKEN`, and `TWG_CLI_PATH` in `.env` (never
committed) and restart the server. Sync then also runs in the background every
`SYNC_INTERVAL_MINUTES` (default 15; `0` disables polling).

- `POST /api/sync/jira`, `POST /api/sync/bitbucket`, or `POST /api/sync` for both.
  `GET /api/sync/status` reports the last attempt, success, error, and staleness per source.
- Jira sync refreshes the same snapshots as the import script, at project level
  (`SYNC_JIRA_PROJECTS`, default `RW,AIP`) minus `SYNC_JIRA_EXCLUDE` (`AIP-96`), restricted to
  tickets assigned to you, updated within `SYNC_JIRA_WINDOW_DAYS` (default 30), or previously
  imported — not every project ticket. It pages through up to 5000 issues; `truncated: true`
  means that cap was hit and the oldest updates fall outside. Identity is your Jira
  `accountId`, not your display name. Tickets assigned to you in an active stage become work
  items automatically; backlog tickets and tickets already done at the previous sync stay
  events only.
- Bitbucket sync covers only PRs you authored or review in `SYNC_BITBUCKET_REPOS`, updated
  within `SYNC_BITBUCKET_WINDOW_DAYS` (default 30). Each PR is a single `pr_created` anchor
  whose metadata carries state, reviewers, and Jira keys — no transition events are invented.
- `GET /api/summary/project?key=RW&window=7d` returns ticket and PR counts, open work items,
  to-dos, and per-source freshness (`stale`) in one call. `GET /api/health` reports database
  status, schema version, and the same freshness.
- `GET /api/export?period=week` exports Monday-through-today Markdown.

Local IDE agents reach the same data over stdio MCP; copy `examples/mcp-config.json`.

Manual capture, search, follow-ups, and Markdown export work locally. Optional drafting,
AI search, and narrative generation send the selected input to CodeBuddy. Capturing an
evidence snapshot requests the evidence URL and stores readable text in SQLite.
