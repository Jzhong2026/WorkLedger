-- 005: Story-Task hierarchy (self-referential parent link)

ALTER TABLE work_events ADD COLUMN parent_event_id INTEGER REFERENCES work_events(id) ON DELETE SET NULL;
CREATE INDEX idx_events_parent ON work_events(parent_event_id);