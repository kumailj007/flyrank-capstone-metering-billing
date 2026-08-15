CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS plans (
    id              TEXT PRIMARY KEY,
    api_call_limit  INTEGER NOT NULL,
    ai_token_limit  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               UUID NOT NULL REFERENCES tenants(id),
    plan_id                 TEXT NOT NULL REFERENCES plans(id),
    status                  TEXT NOT NULL DEFAULT 'active',
    stripe_customer_id      TEXT,
    stripe_subscription_id  TEXT,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS usage_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id),
    usage_type       TEXT NOT NULL CHECK (usage_type IN ('api_call', 'ai_tokens')),
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    idempotency_key  TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_usage_tenant_month
    ON usage_events (tenant_id, created_at);

CREATE TABLE IF NOT EXISTS webhook_events (
    id            TEXT PRIMARY KEY,
    event_type    TEXT NOT NULL,
    processed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
