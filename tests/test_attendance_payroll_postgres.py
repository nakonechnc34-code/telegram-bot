"""Run against a disposable PostgreSQL database using ATTENDANCE_TEST_DSN."""
import os
from decimal import Decimal

import pytest
import psycopg2

from routes.timesheet import _EFFECTIVE_ATTENDANCE_SQL


def test_effective_attendance_postgres():
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TEMP TABLE timesheet_records
                (user_id bigint, work_date date, restaurant_key text, hours numeric);
                CREATE TEMP TABLE attendance_import_days
                (user_id bigint, work_date date, restaurant_key text,
                 status text, worked_minutes integer);
                INSERT INTO timesheet_records VALUES
                (1,'2026-11-01','a',8),(1,'2026-11-02','a',4),
                (1,'2026-11-03','a',8),(2,'2026-11-01','a',7);
                INSERT INTO attendance_import_days VALUES
                (1,'2026-11-01','a','work',515),
                (1,'2026-11-01','b','work',85),
                (1,'2026-11-03','a','sick',0)""")
            def totals():
                cur.execute("WITH effective AS (" + _EFFECTIVE_ATTENDANCE_SQL +
                            ") SELECT user_id, round(sum(hours)*60), round(sum(hours)*350,2)"
                            " FROM effective GROUP BY user_id ORDER BY user_id")
                return cur.fetchall()
            assert totals() == [(1, Decimal(840), Decimal("4900.00")),
                                (2, Decimal(420), Decimal("2450.00"))]
            cur.execute("UPDATE attendance_import_days SET worked_minutes=575 WHERE restaurant_key='a' AND status='work'")
            assert totals()[0] == (1, Decimal(900), Decimal("5250.00"))
            cur.execute("DELETE FROM attendance_import_days WHERE work_date='2026-11-01'")
            assert totals()[0] == (1, Decimal(720), Decimal("4200.00"))
    finally:
        conn.rollback()
        conn.close()


def test_fixed_salary_report_postgres(monkeypatch):
    from contextlib import nullcontext
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TEMP TABLE users
                (user_id bigint, full_name text, position text, restaurant_key text,
                 rate numeric, payment_type text, is_fired boolean, login text);
                CREATE TEMP TABLE restaurants (key text, name text, territory_manager_id bigint);
                CREATE TEMP TABLE position_rates (position_name text, rate numeric);
                CREATE TEMP TABLE timesheet_records
                (user_id bigint, work_date date, restaurant_key text, hours numeric);
                CREATE TEMP TABLE attendance_import_days
                (user_id bigint, work_date date, restaurant_key text,
                 status text, worked_minutes integer);
                INSERT INTO users VALUES (1,'Fixed','Cook','a',80000,'fixed',false,'fixed'),
                    (2,'Hourly','Cook','a',350,'hourly',false,'hourly');
                INSERT INTO restaurants VALUES ('a','A',10),('b','B',20);
                INSERT INTO attendance_import_days VALUES
                    (1,'2026-11-01','a','work',480),(1,'2026-11-01','b','work',120),
                    (2,'2026-11-01','a','work',480),(2,'2026-11-01','b','work',120)""")
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        monkeypatch.setattr(timesheet, "_is_hr_or_super", lambda u: True)
        monkeypatch.setattr(timesheet, "_is_tu", lambda u: False)
        rows = timesheet._sync_reports(1, "2026-11-01", "2026-11-30")
        fixed = [r for r in rows if r["full_name"] == "Fixed"]
        assert len(fixed) == 2
        assert sum(r["total_salary"] for r in fixed) == 80000
        assert next(r for r in fixed if r["restaurant_name"] == "A")["total_salary"] == 80000
        assert sum(r["total_salary"] for r in rows if r["full_name"] == "Hourly") == 3500
        monkeypatch.setattr(timesheet, "_is_hr_or_super", lambda u: False)
        personal = timesheet._sync_reports(2, "2026-11-01", "2026-11-30", True)
        assert {r["full_name"] for r in personal} == {"Hourly"}
        cur = conn.cursor()
        cur.execute("INSERT INTO users VALUES (10,'Manager','TU','a',0,'hourly',false,'manager'), (20,'Shift','Управляющий сменой','b',0,'hourly',false,'shift')")
        cur.close()
        monkeypatch.setattr(timesheet, "_is_tu", lambda u: u["user_id"] == 10)
        territory = timesheet._sync_reports(10, "2026-11-01", "2026-11-30")
        assert territory and {r["restaurant_name"] for r in territory} == {"A"}
        shift = timesheet._sync_reports(20, "2026-11-01", "2026-11-30")
        assert shift and {r["restaurant_name"] for r in shift} == {"B"}
        assert next(r for r in territory if r["full_name"] == "Fixed")["total_salary"] == 80000
        assert next(r for r in shift if r["full_name"] == "Fixed")["total_salary"] == 0
        assert sum(r["total_salary"] for r in territory + shift if r["full_name"] == "Fixed") == 80000
        assert sum(r["total_salary"] for r in territory + shift if r["full_name"] == "Hourly") == 3500
    finally:
        conn.rollback()
        conn.close()


def test_attendance_migration_preserves_legacy_postgres():
    from pathlib import Path
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    sql = (Path(__file__).resolve().parents[1] / "database" /
           "007_attendance_imports.sql").read_text(encoding="utf-8")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA attendance_migration_test")
            cur.execute("SET LOCAL search_path TO attendance_migration_test")
            cur.execute("""CREATE TABLE users (user_id bigint PRIMARY KEY);
                CREATE TABLE timesheet_records (user_id bigint, hours numeric);
                INSERT INTO users VALUES (1);
                INSERT INTO timesheet_records VALUES (1,8)""")
            cur.execute(sql)
            cur.execute(sql)
            cur.execute("SELECT * FROM timesheet_records")
            assert cur.fetchall() == [(1, Decimal("8"))]
            cur.execute("""INSERT INTO attendance_imports (uploaded_by,date_from,date_to)
                VALUES (1,'2026-11-01','2026-11-01') RETURNING id""")
            import_id = cur.fetchone()[0]
            cur.execute("""INSERT INTO attendance_import_days
                (import_id,user_id,work_date,restaurant_key,status,worked_minutes)
                VALUES (%s,1,'2026-11-01','a','work',480) RETURNING id""", (import_id,))
            day_id = cur.fetchone()[0]
            cur.execute("INSERT INTO attendance_import_intervals VALUES (%s,540,1020)", (day_id,))
            cur.execute("DELETE FROM attendance_imports WHERE id=%s", (import_id,))
            cur.execute("SELECT count(*) FROM attendance_import_days")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT count(*) FROM attendance_import_intervals")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT * FROM timesheet_records")
            assert cur.fetchall() == [(1, Decimal("8"))]
    finally:
        conn.rollback()
        conn.close()


def test_excel_import_replace_delete_payroll_postgres(monkeypatch):
    from contextlib import nullcontext
    from io import BytesIO
    from pathlib import Path
    from openpyxl import Workbook
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA attendance_cycle_test")
            cur.execute("SET LOCAL search_path TO attendance_cycle_test")
            cur.execute("""CREATE TABLE users (user_id bigint PRIMARY KEY, personnel_number text,
                full_name text, position text, restaurant_key text, rate numeric,
                payment_type text, is_fired boolean, login text, is_super_admin boolean);
                CREATE TABLE restaurants (key text PRIMARY KEY, name text, territory_manager_id bigint);
                CREATE TABLE position_rates (position_name text, rate numeric);
                CREATE TABLE timesheet_records (user_id bigint, work_date date, restaurant_key text, hours numeric);
                INSERT INTO users VALUES (1,'021','Test Cook','Cook','a',360,'hourly',false,'cook',false),
                    (2,NULL,'Admin','Admin','a',0,'hourly',false,'admin',true);
                INSERT INTO restaurants VALUES ('a','A',2);
                INSERT INTO timesheet_records VALUES (1,'2026-11-16','a',8)""")
            cur.execute((Path(__file__).resolve().parents[1] / "database" / "007_attendance_imports.sql").read_text(encoding="utf-8"))
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        actor = {"user_id": 2, "is_super_admin": True}
        def upload(shift):
            wb = Workbook()
            wb.active.append(["Табельный номер", "Ресторан", "16.11.2026"])
            wb.active.append(["021", "A", shift])
            buf = BytesIO()
            wb.save(buf)
            return timesheet._sync_stage_attendance(actor, timesheet._parse_excel_rows(buf.getvalue()))
        def salary():
            return sum(r["total_salary"] for r in timesheet._sync_reports(1, "2026-11-01", "2026-11-30", True))
        assert salary() == 2880
        first = upload("09:00-17:15")
        assert first["ok"]
        assert salary() == 2970
        second = upload("09:00-18:30")
        assert second["ok"] and second["import_id"] != first["import_id"]
        assert salary() == 3420
        assert timesheet._sync_delete_attendance(actor, second["import_id"], "a") == 1
        assert salary() == 2880
    finally:
        conn.rollback()
        conn.close()


def test_matrix_restaurant_scope_postgres(monkeypatch):
    from contextlib import nullcontext
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TEMP TABLE users
                (user_id bigint, full_name text, position text, restaurant_key text,
                 rate numeric, payment_type text, is_fired boolean, login text, is_admin boolean);
                CREATE TEMP TABLE restaurants (key text, name text, territory_manager_id bigint);
                CREATE TEMP TABLE position_rates (position_name text, rate numeric);
                CREATE TEMP TABLE timesheet_records
                (user_id bigint, work_date date, restaurant_key text, hours numeric,
                 status text, start_time time, end_time time);
                CREATE TEMP TABLE attendance_import_days
                (user_id bigint, work_date date, restaurant_key text, status text, worked_minutes integer);
                INSERT INTO users VALUES (1,'Cook','Cook','a',360,'hourly',false,'cook',false),
                    (10,'TU','TU','a',0,'hourly',false,'tu',true),
                    (20,'US','Управляющий сменой','a',0,'hourly',false,'us',true),
                    (30,'HR','HR','a',0,'hourly',false,'hr',true);
                INSERT INTO restaurants VALUES ('a','A',10),('b','B',99);
                INSERT INTO timesheet_records VALUES
                    (1,'2026-11-16','a',8,'work',NULL,NULL),
                    (1,'2026-11-17','b',7,'work',NULL,NULL),
                    (1,'2026-11-18',NULL,6,'work',NULL,NULL);
                INSERT INTO attendance_import_days VALUES
                    (1,'2026-11-19','a','work',242),(1,'2026-11-19','b','work',242)""")
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        monkeypatch.setattr(timesheet, "_is_hr_or_super", lambda u: u["user_id"] == 30)
        monkeypatch.setattr(timesheet, "_is_tu", lambda u: u["user_id"] == 10)
        for start, end in [("2026-11-16", "2026-11-22"), ("2026-11-01", "2026-11-30")]:
            for actor in (10, 20, 30, 1):
                row = next(e for e in timesheet._sync_timesheet_matrix(actor, start, end, True) if e["user_id"] == 1)
                unrestricted = actor in (30, 1)
                assert ("2026-11-17" in row["data_by_date"]) == unrestricted
                assert "2026-11-16" in row["data_by_date"]
                assert "2026-11-18" in row["data_by_date"]
                imported = row["imported_by_date"]["2026-11-19"]
                assert imported["a"]["minutes"] == 243
                assert imported["a"]["raw_minutes"] == 242
                if unrestricted:
                    assert imported["b"]["minutes"] == 242
                    assert sum(cell["minutes"] for cell in imported.values()) == 485
                assert ("b" in imported) == unrestricted
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.parametrize("locked_status", ["pending", "approved"])
def test_approval_edit_guard_postgres(locked_status):
    from pathlib import Path
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE SCHEMA approval_guard_test;
                SET LOCAL search_path TO approval_guard_test;
                CREATE TABLE users (user_id bigint PRIMARY KEY, restaurant_key text);
                CREATE TABLE restaurants (key text PRIMARY KEY);
                CREATE TABLE timesheet_records (user_id bigint, work_date date, restaurant_key text, hours numeric);
                CREATE TABLE attendance_import_days (user_id bigint, work_date date, restaurant_key text, worked_minutes integer);
                INSERT INTO users VALUES (1,'a');
                INSERT INTO restaurants VALUES ('a'),('b');
                INSERT INTO timesheet_records VALUES (1,'2026-11-01','a',8);
                INSERT INTO attendance_import_days VALUES (1,'2026-11-02','a',240),(1,'2026-11-02','b',240);""")
            root = Path(__file__).resolve().parents[1] / "database"
            for filename in ("008_timesheet_approval.sql", "009_timesheet_approval_locks.sql"):
                cur.execute((root / filename).read_text(encoding="utf-8"))
            cur.execute("INSERT INTO timesheet_approvals(restaurant_key,month_start,status) VALUES ('a','2026-11-01',%s)", (locked_status,))
            for sql in (
                "UPDATE timesheet_records SET hours=9",
                "DELETE FROM timesheet_records",
                "INSERT INTO timesheet_records VALUES (1,'2026-11-03','a',8)",
                "DELETE FROM attendance_import_days WHERE restaurant_key='a'",
                "UPDATE attendance_import_days SET worked_minutes=250 WHERE restaurant_key='b'",
                "INSERT INTO attendance_import_days VALUES (1,'2026-11-01','b',60)",
            ):
                cur.execute("SAVEPOINT attempt")
                with pytest.raises(psycopg2.errors.CheckViolation, match="Timesheet is locked for approval"):
                    cur.execute(sql)
                cur.execute("ROLLBACK TO SAVEPOINT attempt")
                cur.execute("RELEASE SAVEPOINT attempt")
            cur.execute("INSERT INTO timesheet_records VALUES (1,'2026-12-01','a',8)")
            cur.execute("UPDATE timesheet_approvals SET status='returned'")
            cur.execute("UPDATE timesheet_records SET hours=9")
            cur.execute("DELETE FROM attendance_import_days")
            assert cur.rowcount == 2
    finally:
        conn.rollback()
        conn.close()
