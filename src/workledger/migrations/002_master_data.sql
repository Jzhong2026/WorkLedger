-- 002: Master data - projects and sprints

CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    repo TEXT,
    description TEXT,
    color TEXT NOT NULL DEFAULT '#2563eb',
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE sprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    goal TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned', 'active', 'completed')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_sprints_project ON sprints(project_id);
CREATE INDEX idx_sprints_status ON sprints(status);

ALTER TABLE work_events ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE work_events ADD COLUMN sprint_id INTEGER REFERENCES sprints(id) ON DELETE SET NULL;
ALTER TABLE todos ADD COLUMN project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE todos ADD COLUMN sprint_id INTEGER REFERENCES sprints(id) ON DELETE SET NULL;

CREATE INDEX idx_events_project ON work_events(project_id);
CREATE INDEX idx_todos_project ON todos(project_id);