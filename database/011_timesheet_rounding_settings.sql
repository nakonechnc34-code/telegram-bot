CREATE TABLE IF NOT EXISTS timesheet_rounding_settings (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    step_minutes INTEGER NOT NULL DEFAULT 5 CHECK (step_minutes IN (1,5,10,15,30,60)),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0)
);
INSERT INTO timesheet_rounding_settings(singleton) VALUES (TRUE) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS timesheet_rounding_history (
    revision INTEGER PRIMARY KEY CHECK (revision > 0),
    previous_step INTEGER NOT NULL CHECK (previous_step IN (1,5,10,15,30,60)),
    new_step INTEGER NOT NULL CHECK (new_step IN (1,5,10,15,30,60)),
    actor_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
