-- 004: Evidence snapshotting (anti link-rot)

ALTER TABLE work_events ADD COLUMN evidence_snapshot TEXT;
ALTER TABLE work_events ADD COLUMN snapshot_status TEXT CHECK(snapshot_status IN ('captured', 'failed', 'inaccessible'));
ALTER TABLE work_events ADD COLUMN snapshot_at TEXT;