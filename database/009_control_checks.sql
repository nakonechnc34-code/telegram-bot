CREATE TABLE IF NOT EXISTS control_checks (
 id BIGSERIAL PRIMARY KEY,
 restaurant_key TEXT NOT NULL REFERENCES restaurants(key),
 version_id BIGINT NOT NULL REFERENCES control_template_versions(id),
 assigned_by BIGINT NOT NULL REFERENCES users(user_id),
 due_at TIMESTAMPTZ NOT NULL,
 completed_by BIGINT REFERENCES users(user_id),
 completed_at TIMESTAMPTZ,
 answers JSONB,
 score NUMERIC(5,2),
 UNIQUE(restaurant_key, version_id, due_at)
);
CREATE TABLE IF NOT EXISTS control_tasks (
 id BIGSERIAL PRIMARY KEY,
 check_id BIGINT NOT NULL REFERENCES control_checks(id),
 question_key TEXT NOT NULL,
 description TEXT NOT NULL,
 critical BOOLEAN NOT NULL DEFAULT FALSE,
 status TEXT NOT NULL DEFAULT 'new' CHECK(status IN ('new','in_progress','review','closed')),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(check_id, question_key)
);
