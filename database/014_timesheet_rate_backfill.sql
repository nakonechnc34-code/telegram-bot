-- Preserve existing hourly rates; never interpret legacy monthly salary as hourly.
INSERT INTO timesheet_individual_rates (user_id, hourly_rate)
SELECT u.user_id, ROUND(COALESCE(NULLIF(u.rate,0),p.rate,0)::numeric,2)
FROM users u
LEFT JOIN position_rates p ON p.position_name=u.position
WHERE COALESCE(u.payment_type,'hourly') <> 'fixed'
ON CONFLICT (user_id) DO NOTHING;
