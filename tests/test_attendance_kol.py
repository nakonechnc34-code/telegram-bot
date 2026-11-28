from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import os

import pytest
from openpyxl import load_workbook
from psycopg2.extras import RealDictCursor

from routes.timesheet import _kol_excel
from utils.attendance_kol import kol_metrics, load_period


@pytest.mark.parametrize("turnover", [None, Decimal(0)])
def test_kol_undefined_without_positive_turnover(turnover):
    assert kol_metrics(turnover, Decimal(50), None)["percentage"] is None


def test_postgres_kol_uses_confirmed_cashflow_and_current_sales():
    import psycopg2

    dsn = os.getenv("ATTENDANCE_TEST_DSN")
    if not dsn:
        pytest.skip("ATTENDANCE_TEST_DSN not configured")
    conn = psycopg2.connect(dsn)
    try:
        schema = "kol_" + uuid4().hex
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"CREATE SCHEMA {schema}; SET LOCAL search_path TO {schema}")
            cur.execute("""
                CREATE TABLE restaurants(key TEXT PRIMARY KEY, name TEXT, territory_manager_id BIGINT);
                CREATE TABLE payments(id INTEGER PRIMARY KEY, amount NUMERIC(10,2), payment_date DATE, status TEXT, record_type TEXT);
                CREATE TABLE sales_records(restaurant_key TEXT, sale_date DATE, total_amount NUMERIC(12,2));
                INSERT INTO restaurants VALUES ('a','=literal',1),('b','Restaurant B',1);
                INSERT INTO payments VALUES (1,100,'2026-11-01','approved','payout'),
                   (2,200,'2026-11-02','approved','payout'),(3,500,'2026-11-02','pending','payout'),
                   (4,500,'2026-11-02','approved','accrual'),(5,25,'2026-11-02','approved','payout');
                INSERT INTO sales_records VALUES ('a','2026-11-01',1000),('a','2026-11-02',1000),('b','2026-11-02',8000);
            """)
            migration = Path(__file__).resolve().parents[1] / "database/018_timesheet_kol.sql"
            for _ in range(2):
                cur.execute(migration.read_text(encoding="utf-8"))
            cur.execute("""
                INSERT INTO timesheet_kol_plans(restaurant_key,effective_from,percentage,created_by)
                VALUES ('a','2026-10-01',10,1), ('a','2026-11-02',20,1), ('b','2026-10-01',5,1);
                INSERT INTO timesheet_kol_payment_locations(payment_id,restaurant_key,created_by,reason)
                VALUES (1,'a',1,'x'), (2,'b',1,'x');
            """)
            start, end = date(2026, 11, 1), date(2026, 11, 2)
            period = load_period(cur, start, end, ["a", "b"], all_restaurants=True)
            assert period["total"]["paid"] == Decimal("325")
            assert period["total"]["percentage"] == Decimal("3.25")
            assert period["total"]["planned_percentage"] == Decimal("7")
            assert period["restaurants"][0]["percentage"] is None
            assert period["unattributed"] == {"count": 1, "amount": Decimal("25")}
            cur.execute("""
                INSERT INTO timesheet_kol_payment_locations(payment_id,restaurant_key,created_by,reason)
                VALUES (5,'b',1,'verified');
                DELETE FROM sales_records WHERE restaurant_key='b' AND sale_date='2026-11-02';
                INSERT INTO sales_records VALUES ('b','2026-11-02',3000);
            """)
            comparison = load_period(cur, start, end, ["a", "b"], all_restaurants=True)
            assert comparison["territories"][0]["percentage"] == Decimal("6.5")
            assert comparison["total"]["turnover"] == Decimal("5000")
            book = load_workbook(BytesIO(_kol_excel([period, comparison])))
            assert book.sheetnames == ["КОЛ", "Сравнение"]
            assert book["КОЛ"]["A4"].data_type == "s"
    finally:
        conn.rollback()
        conn.close()
