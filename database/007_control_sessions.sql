CREATE TABLE IF NOT EXISTS control_sessions (
 token_hash TEXT PRIMARY KEY,
 user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
 expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '12 hours')
);
CREATE INDEX IF NOT EXISTS idx_control_sessions_user ON control_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_control_sessions_expiry ON control_sessions(expires_at);
