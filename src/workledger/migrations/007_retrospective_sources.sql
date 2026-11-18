-- Preserve the connection between a retrospective entry and its source event.
ALTER TABLE accomplishments ADD COLUMN event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL;
ALTER TABLE cases ADD COLUMN event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL;
ALTER TABLE cases ADD COLUMN evidence_url TEXT;
CREATE INDEX idx_accomplishments_event ON accomplishments(event_id);
CREATE INDEX idx_cases_event ON cases(event_id);
