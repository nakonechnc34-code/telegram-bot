CREATE TABLE IF NOT EXISTS control_schedules (
 id BIGSERIAL PRIMARY KEY,
 restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
 version_id BIGINT NOT NULL REFERENCES control_template_versions(id),
 created_by BIGINT NOT NULL REFERENCES users(user_id),
 frequency TEXT NOT NULL CHECK(frequency IN ('daily','weekly','monthly')),
 next_due TIMESTAMPTZ NOT NULL,
 active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_control_schedules_due ON control_schedules(next_due) WHERE active;
