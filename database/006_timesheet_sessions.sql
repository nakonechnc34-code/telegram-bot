-- Separate, revocable sessions for WOKKER Timesheet; never reuse WOKKER Control tokens.
CREATE TABLE IF NOT EXISTS timesheet_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '12 hours')
);
CREATE INDEX IF NOT EXISTS idx_timesheet_sessions_user ON timesheet_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_timesheet_sessions_expiry ON timesheet_sessions(expires_at);
