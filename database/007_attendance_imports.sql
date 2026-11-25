-- Additive storage: legacy timesheet_records remain untouched.
CREATE TABLE IF NOT EXISTS attendance_imports (
    id BIGSERIAL PRIMARY KEY,
    uploaded_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    CHECK (date_from <= date_to)
);

CREATE TABLE IF NOT EXISTS attendance_import_days (
    id BIGSERIAL PRIMARY KEY,
    import_id BIGINT NOT NULL REFERENCES attendance_imports(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    work_date DATE NOT NULL,
    restaurant_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('work', 'vacation', 'sick', 'absent')),
    worked_minutes INTEGER NOT NULL CHECK (worked_minutes BETWEEN 0 AND 1440),
    CHECK (status = 'work' OR worked_minutes = 0),
    UNIQUE (import_id, user_id, work_date, restaurant_key)
);

CREATE TABLE IF NOT EXISTS attendance_import_intervals (
    day_id BIGINT NOT NULL REFERENCES attendance_import_days(id) ON DELETE CASCADE,
    start_minute INTEGER NOT NULL CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute INTEGER NOT NULL CHECK (end_minute BETWEEN 1 AND 2879),
    CHECK (end_minute > start_minute AND end_minute - start_minute <= 1440),
    PRIMARY KEY (day_id, start_minute, end_minute)
);
CREATE INDEX IF NOT EXISTS idx_attendance_import_days_scope ON attendance_import_days(restaurant_key, work_date);
CREATE INDEX IF NOT EXISTS idx_attendance_import_days_user ON attendance_import_days(user_id, work_date);
