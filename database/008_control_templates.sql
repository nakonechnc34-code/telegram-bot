CREATE TABLE IF NOT EXISTS control_templates (
 id BIGSERIAL PRIMARY KEY,
 title TEXT NOT NULL,
 created_by BIGINT NOT NULL REFERENCES users(user_id),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS control_template_versions (
 id BIGSERIAL PRIMARY KEY,
 template_id BIGINT NOT NULL REFERENCES control_templates(id),
 version INTEGER NOT NULL CHECK(version > 0),
 definition JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(template_id, version)
);
