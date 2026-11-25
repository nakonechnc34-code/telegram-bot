ALTER TABLE control_checks ADD COLUMN IF NOT EXISTS guest_id BIGINT REFERENCES users(user_id);
CREATE INDEX IF NOT EXISTS control_checks_guest_idx ON control_checks(guest_id);
