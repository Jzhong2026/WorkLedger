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

Manual capture, search, follow-ups, and Markdown export work locally. Optional drafting,
AI search, and narrative generation send the selected input to CodeBuddy. Capturing an
evidence snapshot requests the evidence URL and stores readable text in SQLite.
