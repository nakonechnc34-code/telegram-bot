"""Manual staging-only seed. Run from repository root with original XLSX.
Dry run by default; --apply commits. Never copies names or passwords from Excel.
"""
import argparse
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import Json
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL", "")
    url = urlsplit(dsn)
    if (os.environ.get("ENV") != "staging" or
            url.hostname != "cnpg-wokker-test-db-rw" or
            url.username != "wokkertestuser" or url.query or url.fragment):
        raise SystemExit("Refusing non-staging database configuration")
    from utils.security import hash_password
    book = load_workbook(args.xlsx, read_only=True, data_only=True)
    employees = {}
    restaurants = set()
    try:
        for row in book.active.iter_rows(min_row=6, values_only=True):
            if row[0] is None or not row[2]:
                continue
            number, restaurant = str(row[0]).strip(), str(row[2]).strip()
            if not number.isdigit():
                raise ValueError("Unexpected personnel number")
            employees.setdefault(number, restaurant)
            restaurants.add(restaurant)
    finally:
        book.close()
    if len(employees) != 56 or len(restaurants) != 15:
        raise SystemExit("Unexpected workbook dimensions; refusing seed")
    if len({int(n) for n in employees}) != len(employees):
        raise SystemExit("Ambiguous normalized personnel numbers")
    credentials = []
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, current_database()")
            user, database = cur.fetchone()
            if user != "wokkertestuser" or database != url.path.lstrip("/"):
                raise RuntimeError("Unexpected database identity")
            cur.execute("SELECT pg_advisory_xact_lock(814726, 99)")
            keys = {}
            for i, name in enumerate(sorted(restaurants), 1):
                key = f"staging-seed-{i:02d}"
                cur.execute("SELECT key,name FROM restaurants WHERE key=%s OR lower(name)=lower(%s)", (key,name))
                existing = cur.fetchall()
                if existing and existing != [(key,name)]:
                    raise RuntimeError("Restaurant collision; no changes committed")
                cur.execute("INSERT INTO restaurants(key,name) VALUES (%s,%s) ON CONFLICT(key) DO NOTHING", (key,name))
                keys[name] = key

            def account(login, name, position, restaurant, number=None, admin=False, super_admin=False, access=False):
                cur.execute("SELECT user_id,full_name,personnel_number FROM users WHERE login=%s", (login,))
                existing = cur.fetchone()
                if number is not None:
                    cur.execute("SELECT login FROM users WHERE ltrim(personnel_number,'0')=ltrim(%s,'0') AND login IS DISTINCT FROM %s", (number,login))
                    if cur.fetchone():
                        raise RuntimeError("Personnel number collision; no changes committed")
                if existing:
                    if existing[1:] != (name,number):
                        raise RuntimeError("Account collision; no changes committed")
                    return existing[0]
                password = secrets.token_urlsafe(24)
                cur.execute("""INSERT INTO users(login,password_hash,full_name,position,restaurant_key,personnel_number,is_admin,is_super_admin,permissions,payment_type)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'hourly') RETURNING user_id""",
                    (login,hash_password(password),name,position,restaurant,number,admin,super_admin,Json({"timesheet_access":True} if access else {})))
                uid = cur.fetchone()[0]
                if access:
                    credentials.append((login,password))
                return uid

            first = next(iter(keys.values()))
            hr = account("shr01","STAGING HR","HR",first,admin=True,access=True)
            account("ssa01","STAGING Super Admin","Администратор",first,admin=True,super_admin=True,access=True)
            tu = account("stu01","STAGING ТУ","Территориальный управляющий",first,admin=True,access=True)
            account("sus01","STAGING УС","Управляющий смены",first,admin=True,access=True)
            for key in list(keys.values())[:8]:
                cur.execute("UPDATE restaurants SET territory_manager_id=%s WHERE key=%s AND territory_manager_id IS NULL",(tu,key))
            for i,(number,restaurant) in enumerate(sorted(employees.items()),1):
                uid = account(f"ste{i:02d}",f"STAGING Сотрудник {i:02d}","Повар",keys[restaurant],number)
                cur.execute("INSERT INTO timesheet_individual_rates(user_id,hourly_rate,updated_by) VALUES (%s,%s,%s) ON CONFLICT(user_id) DO NOTHING",(uid,300+(i%5)*25,hr))
        if args.apply:
            conn.commit()
            print("Seed committed: 56 employees, 15 restaurants, 4 role accounts")
            for login,password in credentials:
                print(login,password)
        else:
            conn.rollback()
            print("Dry run successful; all changes rolled back")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
