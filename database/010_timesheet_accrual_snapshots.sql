CREATE TABLE IF NOT EXISTS timesheet_accrual_snapshots (
    restaurant_key TEXT NOT NULL,
    month_start DATE NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    user_id BIGINT NOT NULL,
    full_name TEXT NOT NULL,
    position TEXT,
    restaurant_name TEXT NOT NULL,
    payment_type TEXT,
    rate NUMERIC NOT NULL CHECK (rate >= 0),
    worked_minutes INTEGER NOT NULL CHECK (worked_minutes >= 0),
    total_salary NUMERIC(18,2) NOT NULL CHECK (total_salary >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (restaurant_key, month_start, revision, user_id),
    FOREIGN KEY (restaurant_key, month_start, revision)
        REFERENCES timesheet_approval_history(restaurant_key, month_start, revision)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS timesheet_accrual_snapshots_user_month
    ON timesheet_accrual_snapshots(user_id, month_start);
