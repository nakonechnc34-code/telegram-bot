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
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
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
            cur.execute("UPDATE timesheet_rounding_settings SET step_minutes=60")
            cur.execute("UPDATE attendance_import_days SET worked_minutes=517 WHERE restaurant_key='a' AND status='work'")
            assert totals()[0] == (1, Decimal(840), Decimal("4900.00"))
            cur.execute("UPDATE timesheet_rounding_settings SET step_minutes=1")
            assert totals()[0][1] == Decimal(842)
            cur.execute("UPDATE timesheet_rounding_settings SET step_minutes=5")
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
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
            cur.execute("""CREATE TEMP TABLE users
                (user_id bigint, full_name text, position text, restaurant_key text,
                 rate numeric, payment_type text, is_fired boolean, login text);
                CREATE TEMP TABLE restaurants (key text, name text, territory_manager_id bigint);
                CREATE TEMP TABLE position_rates (position_name text, rate numeric);
                 CREATE TEMP TABLE timesheet_individual_rates (user_id bigint PRIMARY KEY, hourly_rate numeric);
                CREATE TEMP TABLE timesheet_records
                (user_id bigint, work_date date, restaurant_key text, hours numeric);
                CREATE TEMP TABLE attendance_import_days
                (user_id bigint, work_date date, restaurant_key text,
                 status text, worked_minutes integer);
                INSERT INTO users VALUES (1,'Fixed','Cook','a',80000,'fixed',false,'fixed'),
                    (2,'Hourly','Cook','a',350,'hourly',false,'hourly');
                INSERT INTO timesheet_individual_rates VALUES (2,350);
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
        assert all(row["payment_type"] == "fixed" for row in fixed)
        assert all(row["total_hours"] > 0 for row in fixed)
        assert sum(r["total_salary"] for r in fixed) == 0
        assert next(r for r in fixed if r["restaurant_name"] == "A")["total_salary"] == 0
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
        assert next(r for r in territory if r["full_name"] == "Fixed")["total_salary"] == 0
        assert next(r for r in shift if r["full_name"] == "Fixed")["total_salary"] == 0
        assert sum(r["total_salary"] for r in territory + shift if r["full_name"] == "Fixed") == 0
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
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
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
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
            cur.execute("CREATE SCHEMA attendance_cycle_test")
            cur.execute("SET LOCAL search_path TO attendance_cycle_test")
            cur.execute("""CREATE TABLE users (user_id bigint PRIMARY KEY, personnel_number text,
                full_name text, position text, restaurant_key text, rate numeric,
                payment_type text, is_fired boolean, login text, is_super_admin boolean);
                CREATE TABLE restaurants (key text PRIMARY KEY, name text, territory_manager_id bigint);
                CREATE TABLE position_rates (position_name text, rate numeric);
                 CREATE TABLE timesheet_individual_rates (user_id bigint PRIMARY KEY, hourly_rate numeric);
                CREATE TABLE timesheet_records (user_id bigint, work_date date, restaurant_key text, hours numeric);
                INSERT INTO users VALUES (1,'021','Test Cook','Cook','a',360,'hourly',false,'cook',false),
                    (2,NULL,'Admin','Admin','a',0,'hourly',false,'admin',true);
                INSERT INTO timesheet_individual_rates VALUES (1,360);
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
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
            cur.execute("""CREATE TEMP TABLE users
                (user_id bigint, full_name text, position text, restaurant_key text,
                 rate numeric, payment_type text, is_fired boolean, login text, is_admin boolean);
                CREATE TEMP TABLE restaurants (key text, name text, territory_manager_id bigint);
                CREATE TEMP TABLE position_rates (position_name text, rate numeric);
                 CREATE TEMP TABLE timesheet_individual_rates (user_id bigint PRIMARY KEY, hourly_rate numeric);
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
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
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


def test_approval_snapshot_cycle_postgres(monkeypatch):
    from contextlib import nullcontext
    from datetime import date
    from pathlib import Path
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
            cur.execute("""CREATE SCHEMA approval_cycle_test;
                SET LOCAL search_path TO approval_cycle_test;
                CREATE TABLE users (user_id bigint PRIMARY KEY, full_name text, position text,
                    restaurant_key text, rate numeric, payment_type text, is_fired boolean,
                    login text, is_admin boolean, is_super_admin boolean);
                CREATE TABLE restaurants (key text PRIMARY KEY, name text, territory_manager_id bigint);
                CREATE TABLE position_rates (position_name text, rate numeric);
                CREATE TABLE timesheet_records (user_id bigint, work_date date, restaurant_key text, hours numeric);
                ALTER TABLE users ADD COLUMN personnel_number text;
                INSERT INTO restaurants VALUES ('a','A',10),('b','B',20);
                INSERT INTO users VALUES (1,'Cook','Cook','a',360,'hourly',false,'cook',false,false),
                    (10,'TU','Территориальный управляющий','a',0,'hourly',false,NULL,true,false),
                    (20,'Other TU','Территориальный управляющий','b',0,'hourly',false,NULL,true,false),
                    (30,'Admin','Admin',NULL,0,'hourly',false,NULL,true,true);
                INSERT INTO users VALUES
                    (91,'Missing','Unknown','a',0,'hourly',false,NULL,false,false),
                    (92,'Legacy fixed','Cook','a',80000,'fixed',false,NULL,false,false),
                    (93,'Legacy fallback','Helper','a',0,'hourly',false,NULL,false,false),
                    (94,'Legacy zero','Zero','a',0,'hourly',false,NULL,false,false);
                INSERT INTO position_rates VALUES ('Helper',250),('Zero',0);
                UPDATE users SET personnel_number='021' WHERE user_id=1;""")
            root = Path(__file__).resolve().parents[1] / "database"
            for filename in ("007_attendance_imports.sql", "015_attendance_matching.sql", "008_timesheet_approval.sql", "009_timesheet_approval_locks.sql",
                             "010_timesheet_accrual_snapshots.sql", "012_timesheet_individual_rates.sql", "013_timesheet_daily_snapshots.sql", "014_timesheet_rate_backfill.sql"):
                cur.execute((root / filename).read_text(encoding="utf-8"))
        with conn.cursor() as cur:
            cur.execute("INSERT INTO attendance_imports(uploaded_by,date_from,date_to) VALUES (30,'2026-11-01','2026-11-01') RETURNING id")
            original_import = cur.fetchone()[0]
            cur.execute("INSERT INTO attendance_import_days(import_id,user_id,work_date,restaurant_key,status,worked_minutes) VALUES (%s,1,'2026-11-01','a','work',493)", (original_import,))
            cur.execute("SELECT hourly_rate FROM timesheet_individual_rates WHERE user_id=1")
            assert cur.fetchone()[0] == Decimal("360")
            cur.execute("SELECT user_id,hourly_rate FROM timesheet_individual_rates WHERE user_id BETWEEN 91 AND 94 ORDER BY user_id")
            assert cur.fetchall() == [(93,Decimal("250.00"))]
            cur.execute("INSERT INTO timesheet_individual_rates(user_id,hourly_rate) VALUES (94,0)")
            cur.execute("UPDATE users SET position='New position',rate=999,payment_type='fixed' WHERE user_id=1")
            cur.execute("INSERT INTO users VALUES (99,'New','Cook','a',500,'hourly',false,NULL,false,false)")
            cur.execute((root / "014_timesheet_rate_backfill.sql").read_text(encoding="utf-8"))
            cur.execute("SELECT hourly_rate FROM timesheet_individual_rates WHERE user_id=1")
            assert cur.fetchone()[0] == Decimal("360")
            cur.execute("SELECT hourly_rate FROM timesheet_individual_rates WHERE user_id=99")
            assert cur.fetchone() is None
            cur.execute("SELECT hourly_rate FROM timesheet_individual_rates WHERE user_id=94")
            assert cur.fetchone()[0] == Decimal("0")
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        tu = {"user_id":10,"position":"Территориальный управляющий","is_admin":True}
        admin = {"user_id":30,"is_super_admin":True}
        month = date(2026,11,1)
        def transition(actor, action, revision, comment=""):
            return timesheet._sync_approval_transition(actor,"a",month,action,comment,revision)[0]
        def report(actor=30, only_me=False):
            return timesheet._sync_approved_reports(actor,"2026-11-01","2026-11-30",only_me)
        assert report() == []
        assert transition(tu,"submit",0) == 200
        assert report() == []
        assert transition(tu,"approve",1) == 403
        assert transition(admin,"approve",0) == 409
        hr = {"user_id":30,"is_admin":True,"position":"HR"}
        assert transition(hr,"approve",1) == 200
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT approved_import")
            with pytest.raises(psycopg2.errors.CheckViolation, match="Timesheet is locked for approval"):
                cur.execute("UPDATE attendance_import_days SET worked_minutes=600 WHERE user_id=1")
            cur.execute("ROLLBACK TO SAVEPOINT approved_import")
            cur.execute("RELEASE SAVEPOINT approved_import")
        assert report()[0]["total_salary"] == Decimal("2970.00")
        import asyncio
        from io import BytesIO
        from aiohttp import web, FormData
        from aiohttp.test_utils import TestClient, TestServer
        from openpyxl import Workbook
        from unittest.mock import AsyncMock
        async def repeat_import():
            app = web.Application()
            app.router.add_post("/api/timesheet/import_attendance/stage", timesheet.handle_import_attendance)
            workbook = Workbook()
            workbook.active.append(["Табельный номер","Ресторан","01.11.2026"])
            workbook.active.append(["021","A","09:00-19:00"])
            buf = BytesIO()
            workbook.save(buf)
            form = FormData()
            form.add_field("file",buf.getvalue(),filename="attendance.xlsx")
            async def run(fn,*args):
                return fn(*args)
            with monkeypatch.context() as mp:
                mp.setattr(timesheet,"_timesheet_user",AsyncMock(return_value=(hr,None)))
                mp.setattr(timesheet,"_require_timesheet_access",lambda user: None)
                mp.setattr(timesheet,"_run",run)
                async with TestClient(TestServer(app)) as client:
                    response = await client.post("/api/timesheet/import_attendance/stage",data=form)
                    assert response.status == 409
                    assert "утверждён" in (await response.json())["error"]
        with conn.cursor() as cur:
            cur.execute("SAVEPOINT repeat_import")
            asyncio.run(repeat_import())
            cur.execute("ROLLBACK TO SAVEPOINT repeat_import")
            cur.execute("RELEASE SAVEPOINT repeat_import")
            cur.execute("SELECT import_id,worked_minutes FROM attendance_import_days")
            assert cur.fetchall() == [(original_import,493)]
        assert report()[0]["total_salary"] == Decimal("2970.00")
        partial = timesheet._sync_approved_reports(30,"2026-11-01","2026-11-15")
        assert partial[0]["total_salary"] == Decimal("2970.00")
        assert partial[0]["total_hours"] == Decimal("8.25")
        assert timesheet._sync_approved_reports(30,"2026-11-02","2026-11-15") == []
        assert timesheet._sync_approved_reports(20,"2026-11-01","2026-11-15") == []
        assert report(10)[0]["total_salary"] == Decimal("2970.00")
        assert report(20) == []
        assert report(1,True)[0]["total_salary"] == Decimal("2970.00")
        assert {row["user_id"] for row in timesheet._sync_rate_employees(10)["employees"]} == {1}
        assert timesheet._sync_rate_employees(20)["employees"] == []
        assert timesheet._sync_rate_employees(1) is None
        assert timesheet._sync_rate_records(1,"history") is None
        assert timesheet._sync_rate_employees(30)["can_manage"] is True
        assert timesheet._sync_set_individual_rate(10,1,Decimal("600")) == 403
        assert timesheet._sync_create_rate_request(20,1,Decimal("600"),"Outside territory") == 404
        assert timesheet._sync_create_rate_request(10,1,Decimal("600"),"Promotion") == 201
        assert timesheet._sync_create_rate_request(10,1,Decimal("650"),"Duplicate") == 409
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM timesheet_rate_requests WHERE user_id=1")
            request_id=cur.fetchone()[0]
        assert {row["id"] for row in timesheet._sync_rate_records(10,"requests")} == {request_id}
        assert timesheet._sync_rate_records(20,"requests") == []
        assert timesheet._sync_decide_rate_request(10,request_id,"approved","") == 403
        assert timesheet._sync_decide_rate_request(30,request_id,"approved","Approved") == 200
        assert timesheet._sync_decide_rate_request(30,request_id,"approved","Again") == 409
        assert {row["user_id"] for row in timesheet._sync_rate_records(10,"history")} == {1}
        assert timesheet._sync_rate_records(20,"history") == []
        assert {row["user_id"] for row in timesheet._sync_rate_records(30,"history")} == {1}
        with conn.cursor() as cur:
            cur.execute("SELECT hourly_rate FROM timesheet_individual_rates WHERE user_id=1")
            assert cur.fetchone()[0] == Decimal("600")
            cur.execute("SELECT new_rate,actor_id,request_id FROM timesheet_rate_history")
            assert cur.fetchall() == [(Decimal("600"),30,request_id)]
            cur.execute("UPDATE users SET rate=999 WHERE user_id=1")
            cur.execute("UPDATE timesheet_rounding_settings SET step_minutes=60")
        assert report()[0]["rate"] == Decimal(360)
        assert report()[0]["total_salary"] == Decimal("2970.00")
        assert transition(admin,"reopen",2,"Correction") == 200
        assert report() == []
        assert transition(tu,"submit",3) == 200
        assert transition(admin,"approve",4) == 200
        assert report()[0]["total_salary"] == Decimal("4800.00")
        with conn.cursor() as cur:
            cur.execute("SELECT revision,total_salary FROM timesheet_accrual_snapshots ORDER BY revision")
            assert cur.fetchall() == [(2,Decimal("2970.00")),(5,Decimal("4800.00"))]
        assert transition(admin,"reopen",5,"Fractional cents") == 200
        with conn.cursor() as cur:
            cur.execute("UPDATE timesheet_rounding_settings SET step_minutes=1")
            cur.execute("DELETE FROM attendance_import_days WHERE user_id=1")
            cur.execute("""INSERT INTO attendance_import_days(import_id,user_id,work_date,restaurant_key,status,worked_minutes)
                VALUES (%s,1,'2026-11-01','a','work',1),(%s,1,'2026-11-02','a','work',1),(%s,1,'2026-11-03','a','work',1)""",
                (original_import,original_import,original_import))
            cur.execute("UPDATE attendance_imports SET date_to='2026-11-03' WHERE id=%s", (original_import,))
        assert timesheet._sync_set_individual_rate(30,1,Decimal("100")) == 200
        assert transition(tu,"submit",6) == 200
        assert transition(admin,"approve",7) == 200
        assert report()[0]["total_salary"] == Decimal("5.00")
        parts = [timesheet._sync_approved_reports(30,f"2026-11-0{day}",f"2026-11-0{day}")[0]["total_salary"] for day in (1,2,3)]
        assert parts == [Decimal("1.67"),Decimal("1.66"),Decimal("1.67")]
        import asyncio
        import io
        from types import SimpleNamespace
        from unittest.mock import AsyncMock
        from openpyxl import load_workbook
        monkeypatch.setattr(timesheet, "_timesheet_user", AsyncMock(return_value=({"user_id":1},None)))
        async def inline_run(fn, *args):
            return fn(*args)
        monkeypatch.setattr(timesheet, "_run", inline_run)
        for start,end,expected in (("2026-11-01","2026-11-30",Decimal("5.00")),
                                   ("2026-11-02","2026-11-02",Decimal("1.66"))):
            req = SimpleNamespace(query={"only_me":"true","date_from":start,"date_to":end})
            response = asyncio.run(timesheet.handle_timesheet_export_excel(req))
            assert response.status == 200
            book = load_workbook(io.BytesIO(response.body))
            sheet = book["Табель"]
            assert sheet.max_row == 2
            assert Decimal(str(sheet["F2"].value)) == expected
            assert sheet["E2"].value == 100
            assert sheet["G2"].value == "Оклад"
            assert "Предупреждение" not in book.sheetnames
            book.close()

        with conn.cursor() as cur:
            cur.execute("""SELECT s.revision FROM timesheet_accrual_snapshots s
                LEFT JOIN timesheet_accrual_snapshot_days d USING (restaurant_key,month_start,revision,user_id)
                GROUP BY s.restaurant_key,s.month_start,s.revision,s.user_id,s.worked_minutes,s.total_salary
                HAVING s.worked_minutes <> COALESCE(SUM(d.worked_minutes),0)
                    OR s.total_salary <> COALESCE(SUM(d.total_salary),0)""")
            assert cur.fetchall() == []
        # Persist only in the disposable CI database for the subsequent dump/restore step.
        if os.getenv("ATTENDANCE_BACKUP_FIXTURE") == "1":
            conn.commit()
    finally:
        conn.rollback()
        conn.close()


def test_fixed_salary_snapshot_is_informational_postgres(monkeypatch):
    from contextlib import nullcontext
    from datetime import date
    from pathlib import Path
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE timesheet_rounding_settings (singleton boolean PRIMARY KEY, step_minutes integer NOT NULL); INSERT INTO timesheet_rounding_settings VALUES (TRUE, 5)")
            cur.execute("""CREATE SCHEMA fixed_snapshot_test;
                SET LOCAL search_path TO fixed_snapshot_test;
                CREATE TABLE users (user_id bigint PRIMARY KEY, full_name text, position text,
                    restaurant_key text, rate numeric, payment_type text, is_fired boolean,
                    login text, is_admin boolean, is_super_admin boolean);
                CREATE TABLE restaurants (key text PRIMARY KEY, name text, territory_manager_id bigint);
                CREATE TABLE position_rates (position_name text, rate numeric);
                 CREATE TABLE timesheet_individual_rates (user_id bigint PRIMARY KEY, hourly_rate numeric);
                CREATE TABLE timesheet_records (user_id bigint, work_date date, restaurant_key text, hours numeric);
                CREATE TABLE attendance_import_days (user_id bigint, work_date date, restaurant_key text,
                    status text, worked_minutes integer);
                INSERT INTO restaurants VALUES ('a','A',10),('b','B',20);
                INSERT INTO users VALUES (1,'Fixed','Cook','a',80000,'fixed',false,'fixed',false,false),
                    (30,'Admin','Admin',NULL,0,'hourly',false,NULL,true,true);
                INSERT INTO attendance_import_days VALUES
                    (1,'2026-11-01','a','work',480),(1,'2026-11-02','b','work',480);""")
            root = Path(__file__).resolve().parents[1] / "database"
            for filename in ("008_timesheet_approval.sql", "009_timesheet_approval_locks.sql",
                             "010_timesheet_accrual_snapshots.sql", "013_timesheet_daily_snapshots.sql"):
                cur.execute((root / filename).read_text(encoding="utf-8"))
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        admin = {"user_id":30,"is_super_admin":True}
        month = date(2026,11,1)
        def transition(key, action, revision, comment=""):
            assert timesheet._sync_approval_transition(admin,key,month,action,comment,revision)[0] == 200
        def total():
            return sum(row["total_salary"] for row in
                       timesheet._sync_approved_reports(30,"2026-11-01","2026-11-30"))
        transition("a","submit",0)
        status, result = timesheet._sync_approval_transition(admin,"a",month,"approve","",1)
        assert status == 409
        assert result == {"error":"missing_hourly_rates","employees":[{"user_id":1,"full_name":"Fixed"}]}
        with conn.cursor() as cur:
            cur.execute("SELECT status,revision FROM timesheet_approvals WHERE restaurant_key='a'")
            assert cur.fetchone() == ("pending",1)
            cur.execute("SELECT count(*) FROM timesheet_accrual_snapshots")
            assert cur.fetchone()[0] == 0
            cur.execute("INSERT INTO timesheet_individual_rates VALUES (1,0)")
        transition("a","approve",1)
        assert total() == Decimal("0.00")
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET restaurant_key='b' WHERE user_id=1")
        transition("b","submit",0)
        transition("b","approve",1)
        assert total() == Decimal("0.00")
        transition("a","reopen",2,"Transfer")
        assert total() == Decimal("0.00")
        transition("b","reopen",2,"Recalculate transferred salary")
        transition("b","submit",3)
        transition("b","approve",4)
        assert total() == Decimal("0.00")
        transition("a","submit",3)
        transition("a","approve",4)
        assert total() == Decimal("0.00")
    finally:
        conn.rollback()
        conn.close()


def test_rounding_settings_migration_and_history_postgres(monkeypatch):
    from contextlib import nullcontext
    from pathlib import Path
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        sql = (Path(__file__).resolve().parents[1] / "database" /
               "011_timesheet_rounding_settings.sql").read_text(encoding="utf-8")
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA rounding_history_test")
            cur.execute("SET LOCAL search_path TO rounding_history_test")
            cur.execute("CREATE TABLE users (user_id bigint PRIMARY KEY)")
            cur.execute("INSERT INTO users VALUES (42)")
            cur.execute(sql)
            cur.execute(sql)
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        actor = {"user_id": 42, "is_super_admin": True}
        settings = timesheet._sync_rounding_settings
        assert settings(actor) == {"step_minutes": 5, "revision": 0, "history": []}
        first = settings(actor, {"step_minutes": 15, "revision": 0})
        assert first["revision"] == 1
        assert first["step_minutes"] == 15
        assert settings(actor, {"step_minutes": 30, "revision": 0}) is None
        assert settings(actor, {"step_minutes": 15, "revision": 1}) == first
        second = settings(actor, {"step_minutes": 60, "revision": 1})
        assert second["revision"] == 2
        assert [(h["revision"], h["previous_step"], h["new_step"], h["actor_id"])
                for h in second["history"]] == [(2, 15, 60, 42), (1, 5, 15, 42)]
        with conn.cursor() as cur:
            cur.execute(sql)
        assert settings(actor) == second
    finally:
        conn.rollback()
        conn.close()


def test_payroll_transaction_lock_postgres():
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    first = psycopg2.connect(dsn)
    second = psycopg2.connect(dsn)
    try:
        with first.cursor() as owner, second.cursor() as contender:
            owner.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            contender.execute("SELECT pg_try_advisory_xact_lock(814726, 2)")
            assert contender.fetchone() == (False,)
            first.commit()
            contender.execute("SELECT pg_try_advisory_xact_lock(814726, 2)")
            assert contender.fetchone() == (True,)
            owner.execute("SELECT pg_try_advisory_xact_lock(814726, 2)")
            assert owner.fetchone() == (False,)
            second.rollback()
            owner.execute("SELECT pg_try_advisory_xact_lock(814726, 2)")
            assert owner.fetchone() == (True,)
    finally:
        first.rollback()
        second.rollback()
        first.close()
        second.close()


def test_persistent_matching_postgres(monkeypatch):
    from contextlib import nullcontext
    from pathlib import Path
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA attendance_matching_test")
            cur.execute("SET LOCAL search_path TO attendance_matching_test")
            cur.execute("""CREATE TABLE users (user_id bigint PRIMARY KEY, personnel_number text,
                restaurant_key text, is_fired boolean, full_name text);
                CREATE TABLE restaurants (key text PRIMARY KEY, name text, territory_manager_id bigint);
                INSERT INTO users VALUES (1,'021','a',false,'Test One'),(2,NULL,'a',false,'Test Two'),(3,'042','a',false,'Test Three');
                INSERT INTO restaurants VALUES ('a','A',2)""")
            for filename in ("007_attendance_imports.sql", "015_attendance_matching.sql"):
                sql = (Path(__file__).resolve().parents[1] / "database" / filename).read_text(encoding="utf-8")
                cur.execute(sql)
                cur.execute(sql)
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        actor = {"user_id": 2, "is_super_admin": True}
        registry = timesheet._sync_matching_registry
        registry(actor, ("employees", "external", "1"))
        registry(actor, ("restaurants", "old restaurant", "a"))
        registry(actor, ("employees", "external", "3"))
        registry(actor, ("employees", "external", "1"))
        registry(actor, ("employees", "external", "1"))
        assert len(registry(actor)["history"]) == 4
        assert registry(actor)["employees"][0]["full_name"] == "Test One"
        assert not any(e["stale"] for e in registry(actor)["entries"])
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET personnel_number='099' WHERE user_id=1")
            cur.execute("UPDATE users SET personnel_number='021' WHERE user_id=3")
            cur.execute("UPDATE restaurants SET name='Renamed' WHERE key='a'")
        from io import BytesIO
        from openpyxl import Workbook
        workbook = Workbook()
        workbook.active.append(["Табельный номер", "Подразделение", "16.11.2026"])
        workbook.active.append(["external", "old restaurant", "09:00-12:00"])
        buffer = BytesIO()
        workbook.save(buffer)
        rows = timesheet._parse_excel_rows(buffer.getvalue())
        assert rows == [("2026-11-16", "external", "09:00-12:00", "old restaurant")]
        def mapped():
            return timesheet._merge_saved_attendance_mapping(rows, timesheet._load_saved_attendance_mapping(), None)
        first = timesheet._sync_stage_attendance(actor, mapped())
        assert first["ok"]
        second = timesheet._sync_stage_attendance(actor, mapped())
        assert second["ok"]
        assert first["import_id"] != second["import_id"]
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM attendance_imports")
            assert cur.fetchall() == [(second["import_id"],)]
            cur.execute("SELECT start_minute,end_minute FROM attendance_import_intervals")
            assert cur.fetchall() == [(540,720)]
        with conn.cursor() as cur:
            cur.execute("SELECT user_id,restaurant_key,worked_minutes FROM attendance_import_days")
            assert cur.fetchall() == [(1, "a", 180)]
        absence_rows = [("2026-11-17", "external", "В", "old restaurant"),
                        ("2026-11-18", "external", "Б", "old restaurant"),
                        ("2026-11-19", "external", "Н", "old restaurant")]
        absence_mapped = timesheet._merge_saved_attendance_mapping(
            absence_rows, timesheet._load_saved_attendance_mapping(), None)
        assert timesheet._sync_stage_attendance(actor, absence_mapped)["ok"]
        with conn.cursor() as cur:
            cur.execute("SELECT user_id,status,worked_minutes FROM attendance_import_days WHERE work_date > '2026-11-16' ORDER BY work_date")
            assert cur.fetchall() == [(1,"vacation",0),(1,"sick",0),(1,"absent",0)]
            cur.execute("UPDATE users SET is_fired=true WHERE user_id=1")
        stale = timesheet._sync_preview_attendance(actor, mapped())
        assert not stale["ok"]
        assert stale["matching"]["employees"] == ["external"]
        assert any(e["stale"] for e in registry(actor)["entries"] if e["kind"] == "employees")
        registry(actor, ("employees", "external", None))
        assert len(registry(actor)["history"]) == 5
        assert not timesheet._sync_preview_attendance(actor, mapped())["ok"]
    finally:
        conn.rollback()
        conn.close()


def test_full_size_attendance_import_postgres(monkeypatch):
    """Synthetic volume regression, without publishing employee data from the original workbook."""
    from contextlib import nullcontext
    from pathlib import Path
    from io import BytesIO
    from openpyxl import Workbook
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE SCHEMA attendance_volume_test;
                SET LOCAL search_path TO attendance_volume_test;
                CREATE TABLE users (user_id bigint PRIMARY KEY, personnel_number text,
                    restaurant_key text, is_fired boolean, full_name text);
                CREATE TABLE restaurants (key text PRIMARY KEY, name text, territory_manager_id bigint);""")
            for i in range(15):
                cur.execute("INSERT INTO restaurants VALUES (%s,%s,999)", (str(i),f"Restaurant {i}"))
            for i in range(56):
                cur.execute("INSERT INTO users VALUES (%s,%s,%s,false,%s)", (i+1,str(i+100),str(i%15),f"Test {i}"))
            cur.execute("INSERT INTO users VALUES (999,NULL,'0',false,'Test Administrator')")
            for filename in ("007_attendance_imports.sql","015_attendance_matching.sql"):
                cur.execute((Path(__file__).resolve().parents[1]/"database"/filename).read_text(encoding="utf-8"))
        monkeypatch.setattr(timesheet,"get_conn",lambda: nullcontext(conn))
        actor = {"user_id":999,"is_super_admin":True}
        book = Workbook()
        sheet = book.active
        sheet.append(["Табельный номер","Подразделение"]+[f"{d}.11.2026" for d in range(16,23)])
        for i in range(327):
            employee, day = i%56, i//56
            minutes = 757 if i < 80 else 756
            end = 480+minutes
            shift = f"08:00-{end//60:02d}:{end%60:02d}"
            values = [None]*7
            values[day] = shift
            sheet.append([str(employee+100),f"Restaurant {(employee+day)%15}"]+values)
            if i == 0:
                sheet.append([None,None,"22:05-22:12"])
                sheet.merge_cells("A2:A3")
                sheet.merge_cells("B2:B3")
        buf = BytesIO()
        book.save(buf)
        rows = timesheet._parse_excel_rows(buf.getvalue())
        assert len(rows) == 328
        expected = 80*757+247*756+7
        preview = timesheet._sync_preview_attendance(actor,rows)
        assert preview["ok"], preview["errors"]
        assert preview["total_minutes"] == expected
        for _ in range(2):
            result = timesheet._sync_stage_attendance(actor,rows)
            assert result["ok"], result
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*),SUM(worked_minutes),COUNT(DISTINCT user_id),COUNT(DISTINCT restaurant_key) FROM attendance_import_days")
                assert cur.fetchone() == (327,expected,56,15)
                cur.execute("SELECT COUNT(*) FROM attendance_import_intervals")
                assert cur.fetchone()[0] == 328
                cur.execute("SELECT COUNT(*) FROM attendance_imports")
                assert cur.fetchone()[0] == 1
    finally:
        conn.rollback()
        conn.close()


def test_partial_archive_recovery_postgres(monkeypatch):
    from contextlib import nullcontext
    from pathlib import Path
    from io import BytesIO
    from openpyxl import Workbook
    from routes import timesheet
    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE SCHEMA attendance_partial_test;
                SET LOCAL search_path TO attendance_partial_test;
                CREATE TABLE users (user_id bigint PRIMARY KEY, personnel_number text,
                    restaurant_key text, is_fired boolean, full_name text);
                CREATE TABLE restaurants (key text PRIMARY KEY, name text, territory_manager_id bigint);
                INSERT INTO users VALUES (1,'021','a',false,'One'),(2,'042','a',false,'Two'),(999,NULL,'a',false,'Admin');
                INSERT INTO restaurants VALUES ('a','A',999)""")
            for filename in ("007_attendance_imports.sql", "015_attendance_matching.sql", "016_attendance_partial_reports.sql"):
                cur.execute((Path(__file__).resolve().parents[1] / "database" / filename).read_text(encoding="utf-8"))
        monkeypatch.setattr(timesheet, "get_conn", lambda: nullcontext(conn))
        actor = {"user_id":999,"is_super_admin":True}
        book = Workbook()
        book.active.append(["Табельный номер","Подразделение","16.11.2026"])
        book.active.append(["021","A","09:00-12:00"])
        book.active.append(["external","A","10:00-14:00"])
        buf = BytesIO()
        book.save(buf)
        source = buf.getvalue()
        rows = timesheet._parse_excel_rows(source)
        first = timesheet._sync_stage_attendance(actor, rows, partial=True, source_file=source)
        assert first["ok"] and first["partial"] and first["success_count"] == 1
        report_id = first["report_id"]
        assert timesheet._sync_partial_report_file(report_id) == source
        timesheet._sync_matching_registry(actor, ("employees","external","2"))
        mapped = timesheet._merge_saved_attendance_mapping(rows, timesheet._load_saved_attendance_mapping(), None)
        recovered = timesheet._sync_stage_attendance(actor, mapped, partial=True, source_file=source, retry_id=report_id)
        assert recovered["ok"] and recovered["success_count"] == 1
        assert not timesheet._sync_stage_attendance(actor, mapped, partial=True, source_file=source, retry_id=report_id)["ok"]
        with conn.cursor() as cur:
            cur.execute("SELECT user_id,worked_minutes FROM attendance_import_days ORDER BY user_id")
            assert cur.fetchall() == [(1,180),(2,240)]
            cur.execute("SELECT resolved_at IS NOT NULL FROM attendance_partial_reports WHERE id=%s",(report_id,))
            assert cur.fetchone() == (True,)
    finally:
        conn.rollback()
        conn.close()
