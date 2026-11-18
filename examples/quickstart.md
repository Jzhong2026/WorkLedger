# WorkLedger Quick Start

## 1. Install and build

From the repository root, using Python 3.11+ and Node.js with npm:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Push-Location frontend
npm ci
npm run build
Pop-Location
```

## 2. Initialize database

```powershell
.\.venv\Scripts\workledger.exe init-db
```

## 3. Start web server

```powershell
.\.venv\Scripts\workledger.exe serve
# Open http://127.0.0.1:8600
```

## 4. Connect external agent via MCP

Copy `examples/mcp-config.json` into your agent's MCP configuration.
The server runs on stdio — no network port needed.

## 5. Smoke test

Open **Inbox**, capture a note, and choose **Record manually**. Confirm that the
event opens from Inbox and can be found in Search. From the event, create an
accomplishment or case, then verify its source link in Retrospective.

Ask your agent:

> Record a manual work event: "WorkLedger smoke test", occurred now,
> source_key "smoke:test:001". Search for "smoke" and confirm it appears.
> Create a to-do "Verify smoke test" linked to that event.
> Call today_followups and confirm the to-do shows.

Then open http://127.0.0.1:8600/search?q=smoke to see the record in the Web UI.

## 6. Backup / Restore

```powershell
.\.venv\Scripts\workledger.exe backup ./backups/workledger-backup.db
```

Before restoring, stop the web server and any connected WorkLedger MCP processes.

```powershell
.\.venv\Scripts\workledger.exe restore ./backups/workledger-backup.db
```

## Import Jira issues

Import a local issue export. The script reads the issue creation time and records
the import time separately. If a source date is absent, the work event shows the
import date as a fallback. Re-importing the issue updates source metadata and
resolves parents from previous imports. Locally edited fields are preserved.

```powershell
.\.venv\Scripts\python.exe scripts/import_jira.py ./issues.json --project-key RW
```

An export with missing issue URLs can use `--jira-base-url https://your-site.atlassian.net`.

## Configuration

Edit `.env` (never committed to git):

| Variable | Default | Purpose |
|----------|---------|---------|
| WORKLEDGER_DATA_DIR | ./data | SQLite database location |
| WORKLEDGER_HOST | 127.0.0.1 | Web server bind address |
| WORKLEDGER_PORT | 8600 | Web server port |
| CODEBUDDY_API_KEY | (empty) | CodeBuddy CLI key for built-in agent |
| AGENT_ENABLED | false | Enable built-in agent |
| AGENT_MODEL | deepseek-flash | Model choice |

For built-in AI, install CodeBuddy CLI and set both `AGENT_ENABLED=true` and
`CODEBUDDY_API_KEY`. Restart the local server after changing configuration. Built-in
AI uses print mode with tools disabled. Markdown export is complete. Narrative
generation uses a bounded selection and displays its coverage.
