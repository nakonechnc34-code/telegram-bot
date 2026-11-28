CREATE INDEX IF NOT EXISTS attendance_partial_reports_source_idx
ON attendance_partial_reports (sha256(source_file), COALESCE(default_restaurant_key, ''));
