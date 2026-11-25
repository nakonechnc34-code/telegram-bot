CREATE TABLE IF NOT EXISTS control_check_photos (
    id BIGSERIAL PRIMARY KEY,
    check_id BIGINT NOT NULL REFERENCES control_checks(id) ON DELETE CASCADE,
    question_key TEXT NOT NULL,
    uploaded_by BIGINT NOT NULL REFERENCES users(user_id),
    content_type TEXT NOT NULL CHECK (content_type IN ('image/jpeg','image/png')),
    content BYTEA NOT NULL CHECK (octet_length(content) BETWEEN 1 AND 5242880),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(check_id, question_key)
);
