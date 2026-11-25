ALTER TABLE control_tasks ADD COLUMN IF NOT EXISTS assignee_id BIGINT REFERENCES users(user_id);
ALTER TABLE control_tasks ADD COLUMN IF NOT EXISTS due_at TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS control_task_history (
 id BIGSERIAL PRIMARY KEY,
 task_id BIGINT NOT NULL REFERENCES control_tasks(id),
 actor_id BIGINT NOT NULL REFERENCES users(user_id),
 action TEXT NOT NULL,
 details JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_control_task_history_task ON control_task_history(task_id,id);
