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
