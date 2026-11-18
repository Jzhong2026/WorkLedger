-- Track the latest capture attempt separately from the last saved snapshot.
ALTER TABLE work_events ADD COLUMN snapshot_attempt_at TEXT;
ALTER TABLE work_events ADD COLUMN snapshot_error TEXT;
ALTER TABLE work_events ADD COLUMN snapshot_source_url TEXT;
ALTER TABLE work_events ADD COLUMN source_fingerprint TEXT;

UPDATE work_events
SET snapshot_attempt_at = snapshot_at,
    snapshot_at = CASE WHEN evidence_snapshot IS NOT NULL THEN snapshot_at END
WHERE snapshot_at IS NOT NULL;

-- A previously dismissed note must not retain actionable drafts.
UPDATE event_drafts
SET status = 'discarded', updated_at = datetime('now')
WHERE status = 'pending'
  AND note_id IN (SELECT id FROM inbox_notes WHERE status = 'discarded');

-- Earlier versions left notes stranded after the final draft was discarded.
UPDATE inbox_notes
SET status = CASE
    WHEN EXISTS (
        SELECT 1 FROM event_drafts WHERE note_id = inbox_notes.id AND status = 'confirmed'
    ) THEN 'committed'
    ELSE 'raw'
END,
    updated_at = datetime('now')
WHERE status = 'structured'
  AND NOT EXISTS (
      SELECT 1 FROM event_drafts WHERE note_id = inbox_notes.id AND status = 'pending'
  );
