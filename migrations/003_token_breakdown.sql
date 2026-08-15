ALTER TABLE usage_events
    ADD COLUMN IF NOT EXISTS token_breakdown JSONB;
