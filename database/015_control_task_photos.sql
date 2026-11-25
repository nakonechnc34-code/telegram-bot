CREATE TABLE IF NOT EXISTS control_task_photos (
 id BIGSERIAL PRIMARY KEY,
 task_id BIGINT NOT NULL REFERENCES control_tasks(id) ON DELETE CASCADE,
 uploaded_by BIGINT NOT NULL REFERENCES users(user_id),
 content_type TEXT NOT NULL CHECK(content_type IN ('image/jpeg','image/png')),
 content BYTEA NOT NULL CHECK(octet_length(content) BETWEEN 1 AND 5242880),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS control_task_photos_task_idx ON control_task_photos(task_id,id);
