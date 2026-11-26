CREATE TABLE sync_state (
    source TEXT PRIMARY KEY,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    detail_json TEXT
);
