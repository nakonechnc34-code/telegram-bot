CREATE TABLE IF NOT EXISTS attendance_matching (
    kind TEXT NOT NULL CHECK (kind IN ('employees', 'restaurants')),
    source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 200),
    target TEXT NOT NULL CHECK (length(target) BETWEEN 1 AND 200),
    actor_id BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, source)
);
CREATE TABLE IF NOT EXISTS attendance_matching_history (
    id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('employees', 'restaurants')),
    source TEXT NOT NULL,
    previous_target TEXT,
    new_target TEXT,
    actor_id BIGINT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (previous_target IS DISTINCT FROM new_target)
);
