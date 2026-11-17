-- 001: Initial schema for WorkLedger MVP

CREATE TABLE work_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL CHECK(event_type IN (
        'pr_created', 'review_finding', 'comment_analysis',
        'fix', 'verification', 'reply_drafted', 'reply_published',
        'manual'
    )),
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    repo TEXT,
    pr_number INTEGER,
    comment_id TEXT,
    jira_key TEXT,
    source_key TEXT NOT NULL UNIQUE,
    source_agent TEXT,
    summary TEXT NOT NULL DEFAULT '',
    detail TEXT,
    evidence_url TEXT,
    root_cause TEXT,
    root_cause_confirmed INTEGER NOT NULL DEFAULT 0,
    verification_result TEXT,
    verification_done INTEGER NOT NULL DEFAULT 0,
    reply_status TEXT CHECK(reply_status IN ('draft', 'published')),
    extra_json TEXT,
    user_edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_events_occurred ON work_events(occurred_at);
CREATE INDEX idx_events_repo_pr ON work_events(repo, pr_number);
CREATE INDEX idx_events_type ON work_events(event_type);
CREATE INDEX idx_events_jira ON work_events(jira_key);

CREATE TABLE todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'waiting', 'done')),
    event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL,
    wait_target TEXT,
    due_date TEXT,
    next_followup TEXT,
    completed_at TEXT,
    source_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_todos_status ON todos(status);
CREATE INDEX idx_todos_followup ON todos(next_followup);
CREATE INDEX idx_todos_due ON todos(due_date);

CREATE TABLE accomplishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    occurred_at TEXT NOT NULL,
    impact TEXT,
    impact_evidence_url TEXT,
    is_highlight INTEGER NOT NULL DEFAULT 0,
    tags TEXT,
    source_key TEXT UNIQUE,
    user_edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_accomplishments_occurred ON accomplishments(occurred_at);

CREATE TABLE cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    phenomenon TEXT NOT NULL DEFAULT '',
    root_cause TEXT,
    root_cause_confirmed INTEGER NOT NULL DEFAULT 0,
    solution TEXT,
    verification TEXT,
    verification_done INTEGER NOT NULL DEFAULT 0,
    occurred_at TEXT NOT NULL,
    tags TEXT,
    source_key TEXT UNIQUE,
    user_edited INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_cases_occurred ON cases(occurred_at);

CREATE TABLE revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT NOT NULL DEFAULT 'user',
    change_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_revisions_entity ON revisions(entity_type, entity_id);