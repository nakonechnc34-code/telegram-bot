CREATE TABLE IF NOT EXISTS timesheet_individual_rates (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    hourly_rate NUMERIC(12,2) NOT NULL CHECK (hourly_rate >= 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    updated_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS timesheet_rate_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    requested_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    proposed_rate NUMERIC(12,2) NOT NULL CHECK (proposed_rate >= 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) BETWEEN 1 AND 2000),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_by BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ,
    decision_comment TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS timesheet_rate_one_pending
    ON timesheet_rate_requests(user_id) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS timesheet_rate_history (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    previous_rate NUMERIC(12,2),
    new_rate NUMERIC(12,2) NOT NULL CHECK (new_rate >= 0),
    actor_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    request_id BIGINT REFERENCES timesheet_rate_requests(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
