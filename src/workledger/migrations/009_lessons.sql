CREATE TABLE lessons (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('skill', 'process')),
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'confirmed', 'declined')),
    title TEXT NOT NULL,
    "trigger" TEXT NOT NULL,
    first_step TEXT NOT NULL,
    limits TEXT,
    tags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(tags) AND json_type(tags) = 'array'),
    source_work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE RESTRICT,
    source_event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL,
    evidence_url TEXT,
    origin TEXT NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual', 'codebuddy')),
    request_fingerprint TEXT NOT NULL,
    reviewed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_lessons_status ON lessons(status, updated_at);
CREATE INDEX idx_lessons_source_item ON lessons(source_work_item_id);
CREATE UNIQUE INDEX idx_lessons_manual_request ON lessons(request_fingerprint) WHERE origin = 'manual';
CREATE UNIQUE INDEX idx_lessons_codebuddy_source
    ON lessons(source_work_item_id, source_event_id) WHERE origin = 'codebuddy';

CREATE TABLE lesson_uses (
    lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    work_item_id INTEGER NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL CHECK (outcome IN ('applied', 'helped', 'did_not_help')),
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (lesson_id, work_item_id)
);

CREATE INDEX idx_lesson_uses_work_item ON lesson_uses(work_item_id);
CREATE INDEX idx_lesson_uses_created ON lesson_uses(created_at);

CREATE TABLE lesson_use_history (
    id INTEGER PRIMARY KEY,
    lesson_id INTEGER NOT NULL,
    work_item_id INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('applied', 'helped', 'did_not_help')),
    detail TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (lesson_id, work_item_id) REFERENCES lesson_uses(lesson_id, work_item_id) ON DELETE CASCADE
);

CREATE INDEX idx_lesson_use_history_recorded ON lesson_use_history(recorded_at);
CREATE INDEX idx_lesson_use_history_use ON lesson_use_history(lesson_id, work_item_id);
