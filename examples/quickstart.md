# WorkLedger Quick Start

## 1. Install

```bash
cd D:/AI/Projects/WorkLedger
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
```

## 2. Initialize database

```bash
.venv/Scripts/workledger init-db
```

## 3. Start web server

```bash
.venv/Scripts/workledger serve
# Open http://127.0.0.1:8600
```

## 4. Connect external agent via MCP

Copy `examples/mcp-config.json` into your agent's MCP configuration.
The server runs on stdio — no network port needed.

## 5. Smoke test

Ask your agent:

> Record a manual work event: "WorkLedger smoke test", occurred now,
> source_key "smoke:test:001". Search for "smoke" and confirm it appears.
> Create a to-do "Verify smoke test" linked to that event.
> Call today_followups and confirm the to-do shows.

Then open http://127.0.0.1:8600/search?q=smoke to see the record in the Web UI.

## 6. Backup / Restore

```bash
.venv/Scripts/workledger backup ./backups/workledger-2026-11-17.db
.venv/Scripts/workledger restore ./backups/workledger-2026-11-17.db
```

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