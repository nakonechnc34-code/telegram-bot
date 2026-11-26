-- Run the historical conversion once, even when startup reapplies SQL files.
CREATE TABLE IF NOT EXISTS timesheet_rate_backfill_state (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
WITH claimed AS (
    INSERT INTO timesheet_rate_backfill_state(singleton) VALUES(TRUE)
    ON CONFLICT DO NOTHING RETURNING singleton
)
INSERT INTO timesheet_individual_rates (user_id, hourly_rate)
SELECT u.user_id, ROUND(COALESCE(NULLIF(u.rate,0),NULLIF(p.rate,0))::numeric,2)
FROM users u
LEFT JOIN position_rates p ON p.position_name=u.position
CROSS JOIN claimed
WHERE COALESCE(u.payment_type,'hourly') <> 'fixed'
  AND COALESCE(NULLIF(u.rate,0),NULLIF(p.rate,0)) > 0
ON CONFLICT (user_id) DO NOTHING;
