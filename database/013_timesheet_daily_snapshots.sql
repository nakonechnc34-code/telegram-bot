CREATE TABLE IF NOT EXISTS timesheet_accrual_snapshot_days (
    restaurant_key TEXT NOT NULL,
    month_start DATE NOT NULL,
    revision INTEGER NOT NULL,
    user_id BIGINT NOT NULL,
    work_date DATE NOT NULL,
    worked_minutes INTEGER NOT NULL CHECK (worked_minutes >= 0),
    total_salary NUMERIC(18,2) NOT NULL CHECK (total_salary >= 0),
    PRIMARY KEY (restaurant_key, month_start, revision, user_id, work_date),
    FOREIGN KEY (restaurant_key, month_start, revision, user_id)
        REFERENCES timesheet_accrual_snapshots(restaurant_key, month_start, revision, user_id)
        ON DELETE RESTRICT,
    CHECK (work_date >= month_start AND work_date < month_start + INTERVAL '1 month')
);
CREATE INDEX IF NOT EXISTS timesheet_accrual_snapshot_days_date
    ON timesheet_accrual_snapshot_days(work_date, user_id);
