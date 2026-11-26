-- Support network-wide and restaurant-scoped reporting and attention queries.
CREATE INDEX IF NOT EXISTS control_checks_completed_idx ON control_checks(completed_at, restaurant_key) WHERE completed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS control_checks_restaurant_completed_idx ON control_checks(restaurant_key, completed_at) WHERE completed_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS control_checks_open_due_idx ON control_checks(due_at, restaurant_key) WHERE completed_at IS NULL;
CREATE INDEX IF NOT EXISTS control_tasks_created_idx ON control_tasks(created_at, check_id);
CREATE INDEX IF NOT EXISTS control_tasks_open_due_idx ON control_tasks(due_at, check_id) WHERE status <> 'closed';
CREATE INDEX IF NOT EXISTS control_tasks_assignee_idx ON control_tasks(assignee_id, check_id);
CREATE INDEX IF NOT EXISTS control_readings_recorded_idx ON control_readings(recorded_at, equipment_id);
CREATE INDEX IF NOT EXISTS control_equipment_restaurant_idx ON control_equipment(restaurant_key);
