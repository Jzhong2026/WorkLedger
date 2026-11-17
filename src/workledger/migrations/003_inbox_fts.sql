-- 003: Quick inbox, event drafts, and FTS5 full-text search

CREATE TABLE inbox_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'raw' CHECK(status IN ('raw', 'structured', 'committed', 'discarded')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_inbox_status ON inbox_notes(status);

CREATE TABLE event_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id INTEGER REFERENCES inbox_notes(id) ON DELETE CASCADE,
    draft_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'discarded')),
    committed_event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_drafts_note ON event_drafts(note_id);
CREATE INDEX idx_drafts_status ON event_drafts(status);

-- FTS5 full-text index over work events (trigram supports Chinese substring + English)
CREATE VIRTUAL TABLE work_events_fts USING fts5(
    summary, detail, root_cause,
    content='work_events', content_rowid='id',
    tokenize='trigram'
);

CREATE TRIGGER work_events_ai AFTER INSERT ON work_events BEGIN
    INSERT INTO work_events_fts(rowid, summary, detail, root_cause)
    VALUES (new.id, new.summary, new.detail, new.root_cause);
END;

CREATE TRIGGER work_events_ad AFTER DELETE ON work_events BEGIN
    INSERT INTO work_events_fts(work_events_fts, rowid, summary, detail, root_cause)
    VALUES ('delete', old.id, old.summary, old.detail, old.root_cause);
END;

CREATE TRIGGER work_events_au AFTER UPDATE ON work_events BEGIN
    INSERT INTO work_events_fts(work_events_fts, rowid, summary, detail, root_cause)
    VALUES ('delete', old.id, old.summary, old.detail, old.root_cause);
    INSERT INTO work_events_fts(rowid, summary, detail, root_cause)
    VALUES (new.id, new.summary, new.detail, new.root_cause);
END;

-- Backfill existing rows into the FTS index
INSERT INTO work_events_fts(rowid, summary, detail, root_cause)
    SELECT id, summary, detail, root_cause FROM work_events;