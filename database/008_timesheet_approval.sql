CREATE TABLE IF NOT EXISTS timesheet_approvals (
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key) ON DELETE RESTRICT,
    month_start DATE NOT NULL CHECK (EXTRACT(DAY FROM month_start) = 1),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','pending','approved','returned')),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (restaurant_key, month_start)
);

CREATE TABLE IF NOT EXISTS timesheet_approval_history (
    id BIGSERIAL PRIMARY KEY,
    restaurant_key TEXT NOT NULL,
    month_start DATE NOT NULL,
    revision INTEGER NOT NULL,
    previous_status TEXT NOT NULL CHECK (previous_status IN ('draft','pending','approved','returned')),
    new_status TEXT NOT NULL CHECK (new_status IN ('draft','pending','approved','returned')),
    actor_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (restaurant_key, month_start)
        REFERENCES timesheet_approvals(restaurant_key, month_start) ON DELETE RESTRICT,
    UNIQUE (restaurant_key, month_start, revision)
);
