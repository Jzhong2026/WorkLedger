-- Active work items are explicit. Earlier events remain available as historical records.
CREATE TABLE work_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    goal TEXT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    jira_key TEXT COLLATE NOCASE,
    source_event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL,
    stage TEXT NOT NULL CHECK (stage IN ('active', 'waiting', 'verification', 'done')),
    owner TEXT,
    last_verified_result TEXT,
    blocker TEXT,
    next_step TEXT,
    needs_decision INTEGER NOT NULL CHECK (needs_decision IN (0, 1)),
    followup_date TEXT,
    version INTEGER NOT NULL CHECK (version >= 1),
    source_key TEXT UNIQUE,
    request_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_work_items_project ON work_items(project_id, updated_at);
CREATE INDEX idx_work_items_jira ON work_items(jira_key, updated_at);
CREATE INDEX idx_work_items_stage ON work_items(stage, updated_at);

CREATE TABLE work_item_events (
    item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES work_events(id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (item_id, event_id)
);

CREATE INDEX idx_work_item_events_event ON work_item_events(event_id);

CREATE TABLE work_item_todos (
    item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    todo_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    actor TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    PRIMARY KEY (item_id, todo_id)
);

CREATE INDEX idx_work_item_todos_todo ON work_item_todos(todo_id);

CREATE TABLE work_item_handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 2),
    summary TEXT NOT NULL,
    event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL,
    todo_id INTEGER REFERENCES todos(id) ON DELETE SET NULL,
    actor TEXT NOT NULL,
    previous_stage TEXT NOT NULL CHECK (previous_stage IN ('active', 'waiting', 'verification', 'done')),
    stage TEXT NOT NULL CHECK (stage IN ('active', 'waiting', 'verification', 'done')),
    owner TEXT,
    last_verified_result TEXT,
    blocker TEXT,
    next_step TEXT,
    needs_decision INTEGER NOT NULL CHECK (needs_decision IN (0, 1)),
    followup_date TEXT,
    linked_event_ids TEXT NOT NULL,
    linked_todo_ids TEXT NOT NULL,
    source_key TEXT,
    request_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (item_id, version),
    UNIQUE (item_id, source_key)
);

CREATE INDEX idx_work_item_handoffs_event ON work_item_handoffs(event_id);
CREATE INDEX idx_work_item_handoffs_created ON work_item_handoffs(created_at);
