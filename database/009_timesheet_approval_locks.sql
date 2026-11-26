CREATE OR REPLACE FUNCTION guard_timesheet_approval_edit() RETURNS trigger AS $$
DECLARE
    item RECORD;
    effective_key TEXT;
BEGIN
    PERFORM pg_advisory_xact_lock(814726, 2);
    FOR item IN SELECT * FROM jsonb_to_recordset(
        CASE TG_OP WHEN 'INSERT' THEN jsonb_build_array(to_jsonb(NEW))
                   WHEN 'DELETE' THEN jsonb_build_array(to_jsonb(OLD))
                   ELSE jsonb_build_array(to_jsonb(OLD),to_jsonb(NEW)) END
        ) AS x(user_id BIGINT, work_date DATE, restaurant_key TEXT)
    LOOP
        SELECT COALESCE(item.restaurant_key,u.restaurant_key) INTO effective_key
        FROM users u WHERE u.user_id=item.user_id;
        IF EXISTS (
            SELECT 1 FROM timesheet_approvals a
            WHERE a.month_start=date_trunc('month',item.work_date)::date
              AND a.status IN ('pending','approved')
              AND (a.restaurant_key=effective_key OR EXISTS (
                SELECT 1 FROM attendance_import_days d
                WHERE d.user_id=item.user_id AND d.work_date=item.work_date
                  AND d.restaurant_key=a.restaurant_key
              ) OR EXISTS (
                SELECT 1 FROM timesheet_records t JOIN users u ON u.user_id=t.user_id
                WHERE t.user_id=item.user_id AND t.work_date=item.work_date
                  AND COALESCE(t.restaurant_key,u.restaurant_key)=a.restaurant_key
              ))
        ) THEN
            RAISE EXCEPTION 'Timesheet is locked for approval' USING ERRCODE='23514';
        END IF;
    END LOOP;
    IF TG_OP='DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS timesheet_approval_edit_guard ON timesheet_records;
CREATE TRIGGER timesheet_approval_edit_guard BEFORE INSERT OR UPDATE OR DELETE
ON timesheet_records FOR EACH ROW EXECUTE FUNCTION guard_timesheet_approval_edit();

DROP TRIGGER IF EXISTS attendance_approval_edit_guard ON attendance_import_days;
CREATE TRIGGER attendance_approval_edit_guard BEFORE INSERT OR UPDATE OR DELETE
ON attendance_import_days FOR EACH ROW EXECUTE FUNCTION guard_timesheet_approval_edit();
