CREATE TABLE IF NOT EXISTS attendance_partial_reports (
 id BIGSERIAL PRIMARY KEY,
 uploaded_by BIGINT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 source_file BYTEA NOT NULL,
 diagnostics JSONB NOT NULL,
 default_restaurant_key TEXT,
 resolved_at TIMESTAMPTZ
);
