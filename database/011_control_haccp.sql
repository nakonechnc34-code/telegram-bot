CREATE TABLE IF NOT EXISTS control_equipment (
 id BIGSERIAL PRIMARY KEY,
 restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
 name TEXT NOT NULL,
 kind TEXT NOT NULL,
 unit TEXT NOT NULL,
 lower_limit NUMERIC NOT NULL,
 upper_limit NUMERIC NOT NULL,
 created_by BIGINT NOT NULL REFERENCES users(user_id),
 CHECK(lower_limit <= upper_limit)
);
CREATE TABLE IF NOT EXISTS control_readings (
 id BIGSERIAL PRIMARY KEY,
 equipment_id BIGINT NOT NULL REFERENCES control_equipment(id),
 value NUMERIC NOT NULL,
 lower_limit NUMERIC NOT NULL,
 upper_limit NUMERIC NOT NULL,
 deviation BOOLEAN NOT NULL,
 comment TEXT NOT NULL DEFAULT '',
 recorded_by BIGINT NOT NULL REFERENCES users(user_id),
 recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_control_readings_equipment ON control_readings(equipment_id,recorded_at DESC);
