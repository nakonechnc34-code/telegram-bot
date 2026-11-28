CREATE TABLE IF NOT EXISTS control_notifications (
    id BIGSERIAL PRIMARY KEY,
    recipient_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    restaurant_key TEXT NOT NULL REFERENCES restaurants(key) ON DELETE CASCADE,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('check_assigned','check_overdue','task_assigned','task_overdue','task_critical','haccp_deviation')),
    source_id BIGINT NOT NULL CHECK (source_id > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ,
    UNIQUE (recipient_id, event_kind, source_id),
    CHECK (read_at IS NULL OR read_at >= created_at)
);
CREATE INDEX IF NOT EXISTS control_notifications_recipient_idx
    ON control_notifications(recipient_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS control_notifications_unread_idx
    ON control_notifications(recipient_id, created_at DESC) WHERE read_at IS NULL;
