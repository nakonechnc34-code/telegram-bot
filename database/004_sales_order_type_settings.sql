-- Run once during deployment, before enabling the Sales settings API.
-- Additive and idempotent; does not modify existing sales records.
CREATE TABLE IF NOT EXISTS sales_order_type_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    mapping JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
