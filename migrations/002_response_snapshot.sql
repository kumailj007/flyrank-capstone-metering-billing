ALTER TABLE usage_events
    ADD COLUMN IF NOT EXISTS response_snapshot JSONB;
