from aiohttp import web
from psycopg2.extras import RealDictCursor
from psycopg2.errors import CheckViolation
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, denied, _is_hr_or_super, _is_hr_position, _is_tu, _sync_user_has_perm, _sync_get_tu_rests
from utils.attendance_rounding import allocate_daily_minutes, round_daily_minutes
import calendar
from datetime import datetime, date, time
import io
import json
import math
import re
import traceback
import logging
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from utils.common import safe_int, safe_float

import secrets
import hashlib
from middleware.rate_limit import get_client_ip
from utils.security import validate_login_data, verify_password, _check_rate_limit, _reset_rate_limit
from routes.auth import _sync_get_user_by_login
from utils.auth_helpers import _extract_token

routes = web.RouteTableDef()

def _session_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _sync_timesheet_session(token):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT u.* FROM timesheet_sessions s JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=%s AND s.expires_at>NOW()", (_session_hash(token),))
            return cur.fetchone()

def _timesheet_role_allowed(user):
    return not user.get('is_fired') and (_is_hr_or_super(user) or _is_tu(user))

async def _timesheet_user(request):
    token = await _extract_token(request, allow_query=False)
    user = await _run(_sync_timesheet_session, token) if token else None
    if not user:
        return None, 401
    if not _timesheet_role_allowed(user) or not _sync_user_has_perm(user, "timesheet_access"):
        return None, 403
    return user, None

def _sync_timesheet_create(user_id, token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO timesheet_sessions(token_hash,user_id) VALUES(%s,%s)", (_session_hash(token),user_id))

def _sync_timesheet_delete(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM timesheet_sessions WHERE token_hash=%s", (_session_hash(token),))

@routes.post('/api/timesheet/login')
async def timesheet_login(request):
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return web.json_response({"error":"Некорректный запрос"}, status=400)
    data, err = validate_login_data(body)
    if err:
        return web.json_response({"error":"Некорректный логин или пароль"}, status=400)
    ip = get_client_ip(request)
    if not _check_rate_limit(ip):
        return web.json_response({"error":"Слишком много попыток"}, status=429)
    user = await _run(_sync_get_user_by_login, data["login"])
    if not user or not verify_password(data["password"], user.get("password_hash") or ""):
        return web.json_response({"error":"Неверный логин или пароль"}, status=401)
    if not _timesheet_role_allowed(user) or not _sync_user_has_perm(user,"timesheet_access"):
        return web.json_response({"error":"Нет доступа к Табелю"}, status=403)
    _reset_rate_limit(ip)
    token = secrets.token_urlsafe(48)
    await _run(_sync_timesheet_create,user["user_id"],token)
    return web.json_response({"token":token},headers={"Cache-Control":"no-store"})

@routes.post('/api/timesheet/logout')
async def timesheet_logout(request):
    token = await _extract_token(request, allow_query=False)
    if token:
        await _run(_sync_timesheet_delete,token)
    return web.json_response({"ok":True},headers={"Cache-Control":"no-store"})



def _require_timesheet_access(user):
    if not _sync_user_has_perm(user, "timesheet_access"):
        raise web.HTTPForbidden(text='{"error": "forbidden"}', content_type='application/json')


def _positive_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    value = safe_int(value)
    return value if 0 < value <= 2**63 - 1 else 0


def _date_range(body):
    date_from, date_to = body.get("date_from"), body.get("date_to")
    if date_from is None and date_to is None:
        today = date.today()
        month = _positive_id(body.get("month", today.month))
        year = _positive_id(body.get("year", today.year))
        date_from = date(year, month, 1).isoformat()
        date_to = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if start > end:
        raise ValueError("invalid date range")
    return start.isoformat(), end.isoformat()


def _finite_number(value):
    if isinstance(value, bool):
        raise ValueError("invalid number")
    number = safe_float(value, default=float("nan"))
    if not math.isfinite(number):
        raise ValueError("invalid number")
    return number


def _shift_time(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?", value):
        raise ValueError("invalid time")
    return time(*map(int, value.split(":")))


def _restaurant_in_scope(user, key, territory_keys):
    if _is_hr_or_super(user):
        return True
    if _is_tu(user):
        return key in territory_keys
    return bool(key) and key == user.get("restaurant_key")


def _check_can_edit_user(editor_user, target_uid):
    if _is_hr_or_super(editor_user):
        return True
    if editor_user["user_id"] == target_uid:
        return True
    pos_lower = (editor_user.get("position") or "").lower()
    is_tu = "территориальный" in pos_lower
    is_us = "управляющий сменой" in pos_lower
    if not (is_tu or is_us):
        return False
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT restaurant_key FROM users WHERE user_id = %s", (target_uid,))
            target = cur.fetchone()
            if not target:
                return False
            if is_us:
                return _restaurant_in_scope(editor_user, target["restaurant_key"], ())
            elif is_tu:
                cur.execute(
                    "SELECT key FROM restaurants WHERE territory_manager_id = %s AND key = %s",
                    (editor_user["user_id"], target["restaurant_key"])
                )
                return cur.fetchone() is not None
    return False


def _sync_rounding_settings(user, change=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if change is not None:
                cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            cur.execute("SELECT step_minutes, revision FROM timesheet_rounding_settings WHERE singleton = TRUE" + (" FOR UPDATE" if change is not None else ""))
            current = dict(cur.fetchone())
            if change is not None:
                if current["revision"] != change["revision"]:
                    return None
                if current["step_minutes"] != change["step_minutes"]:
                    revision = current["revision"] + 1
                    cur.execute("UPDATE timesheet_rounding_settings SET step_minutes=%s, revision=%s WHERE singleton=TRUE", (change["step_minutes"], revision))
                    cur.execute("INSERT INTO timesheet_rounding_history(revision, previous_step, new_step, actor_id) VALUES (%s,%s,%s,%s)", (revision, current["step_minutes"], change["step_minutes"], user["user_id"]))
                    current = {"step_minutes": change["step_minutes"], "revision": revision}
            cur.execute("SELECT revision, previous_step, new_step, actor_id, created_at::text AS created_at FROM timesheet_rounding_history ORDER BY revision DESC LIMIT 100")
            current["history"] = [dict(row) for row in cur.fetchall()]
            return current


@routes.get('/api/timesheet/rounding')
@routes.post('/api/timesheet/rounding')
async def handle_timesheet_rounding(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(user):
        return denied(403)
    change = None
    if request.method == "POST":
        try:
            change = await request.json()
        except (ValueError, TypeError):
            return web.json_response({"error": "Некорректный запрос"}, status=400)
        if (not isinstance(change, dict)
                or type(change.get("step_minutes")) is not int
                or change["step_minutes"] not in (1, 5, 10, 15, 30, 60)
                or type(change.get("revision")) is not int
                or not 0 <= change["revision"] < 2147483647):
            return web.json_response({"error": "Некорректные настройки"}, status=400)
    result = await _run(_sync_rounding_settings, user, change)
    if result is None:
        return web.json_response({"error": "Настройки уже изменены"}, status=409)
    return web.json_response(result, headers={"Cache-Control": "no-store"})


@routes.post('/api/timesheet/restaurants')
async def handle_timesheet_restaurants(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if _is_hr_or_super(user):
                    cur.execute("SELECT key, name FROM restaurants ORDER BY name")
                elif _is_tu(user):
                    cur.execute("SELECT key, name FROM restaurants WHERE territory_manager_id = %s ORDER BY name", (user["user_id"],))
                else:
                    cur.execute("SELECT key, name FROM restaurants WHERE key = %s", (user.get("restaurant_key"),))
                return [dict(r) for r in cur.fetchall()]

    rests = await _run(_sync)
    return web.json_response({"restaurants": rests})


def _sync_timesheet_matrix(user_id, date_from, date_to, include_imports=False):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u:
                return []

            is_hr_or_super = _is_hr_or_super(u)
            is_tu = _is_tu(u)
            is_us = "управляющий сменой" in (u.get("position") or "").lower()

            query = """SELECT u.user_id, u.full_name, u.position, u.restaurant_key AS main_restaurant_key,
                       COALESCE(ir.hourly_rate, 0) AS rate, u.payment_type, r.name AS restaurant_name
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN timesheet_individual_rates ir ON ir.user_id=u.user_id
                WHERE COALESCE(u.is_fired, FALSE) = FALSE
                  AND COALESCE(u.is_admin, FALSE) = FALSE
                  AND u.login IS NOT NULL
                  """
            params = []
            if is_us:
                query += " AND u.restaurant_key = %s"
                params.append(u.get("restaurant_key"))
            elif is_tu:
                query += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"
                params.append(user_id)
            elif not is_hr_or_super:
                query += " AND u.user_id = %s"
                params.append(user_id)
            query += " ORDER BY r.name, u.full_name"

            cur.execute(query, params)
            employees = [dict(r) for r in cur.fetchall()]
            if not employees:
                return []

            emp_ids = [e["user_id"] for e in employees]
            cur.execute(
                """SELECT user_id, work_date, hours, status, restaurant_key,
                          to_char(start_time, 'HH24:MI') as st, to_char(end_time, 'HH24:MI') as et
                   FROM timesheet_records
                   WHERE user_id = ANY(%s) AND work_date >= %s::date AND work_date <= %s::date
                     AND (%s OR (%s AND COALESCE(restaurant_key, (SELECT u.restaurant_key FROM users u WHERE u.user_id = timesheet_records.user_id))
                         IN (SELECT key FROM restaurants WHERE territory_manager_id = %s))
                         OR (%s AND COALESCE(restaurant_key, (SELECT u.restaurant_key FROM users u WHERE u.user_id = timesheet_records.user_id)) = %s)
                         OR (%s AND user_id = %s))""",
                (emp_ids, date_from, date_to, is_hr_or_super, is_tu, user_id,
                 is_us, u.get("restaurant_key"), not (is_hr_or_super or is_tu or is_us), user_id)
            )
            records = cur.fetchall()

            data_map = {eid: {} for eid in emp_ids}
            full_date_map = {eid: {} for eid in emp_ids}
            for r in records:
                cell = {
                    "h": float(r["hours"] or 0),
                    "s": r["status"] or "work",
                    "rk": r["restaurant_key"],
                    "st": r["st"] or "",
                    "et": r["et"] or ""
                }
                data_map[r["user_id"]][str(r["work_date"].day)] = cell
                full_date_map[r["user_id"]][r["work_date"].isoformat()] = cell
            imported = {eid: {} for eid in emp_ids}
            if include_imports:
                cur.execute("""SELECT d.user_id, d.work_date, d.restaurant_key, d.status,
                    d.worked_minutes FROM attendance_import_days d
                    JOIN restaurants r ON r.key = d.restaurant_key
                    WHERE d.user_id = ANY(%s) AND d.work_date BETWEEN %s::date AND %s::date
                    AND (%s OR (%s AND r.territory_manager_id = %s)
                         OR (%s AND r.key = %s) OR (%s AND d.user_id = %s))
                    ORDER BY d.work_date, d.restaurant_key""",
                    (emp_ids, date_from, date_to, is_hr_or_super, is_tu, user_id,
                     is_us, u.get("restaurant_key"), not (is_hr_or_super or is_tu or is_us), user_id))
                for r in cur.fetchall():
                    day = r["work_date"].isoformat()
                    imported[r["user_id"]].setdefault(day, {})[r["restaurant_key"]] = {
                        "h": r["worked_minutes"] / 60, "minutes": r["worked_minutes"],
                        "s": r["status"], "rk": r["restaurant_key"], "imported": True}
            if include_imports:
                cur.execute("SELECT step_minutes FROM timesheet_rounding_settings WHERE singleton = TRUE")
                step_minutes = cur.fetchone()["step_minutes"]
                cur.execute("""SELECT user_id, work_date, restaurant_key, worked_minutes
                    FROM attendance_import_days
                    WHERE user_id = ANY(%s) AND work_date BETWEEN %s::date AND %s::date
                    ORDER BY work_date, restaurant_key""", (emp_ids, date_from, date_to))
                all_daily = {}
                for row in cur.fetchall():
                    key = (row["user_id"], row["work_date"].isoformat())
                    all_daily.setdefault(key, {})[row["restaurant_key"]] = row["worked_minutes"]
                for eid in emp_ids:
                    for day, cells in imported[eid].items():
                        raw = {key: cell["minutes"] for key, cell in cells.items()}
                        rounded = allocate_daily_minutes(all_daily[(eid, day)], step_minutes)
                        for key, cell in cells.items():
                            cell["raw_minutes"] = raw[key]
                            cell["minutes"] = rounded[key]
                            cell["h"] = rounded[key] / 60
                    for day, cell in full_date_map[eid].items():
                        if (eid, day) not in all_daily:
                            raw = int(round(cell["h"] * 60))
                            if 0 <= raw <= 1440:
                                cell["raw_minutes"] = raw
                                cell["minutes"] = round_daily_minutes(raw, step_minutes)
                                cell["h"] = cell["minutes"] / 60
            for e in employees:
                e["imported_by_date"] = imported[e["user_id"]]
                e["data"] = data_map[e["user_id"]]
                e["data_by_date"] = full_date_map[e["user_id"]]
            return employees


@routes.post('/api/timesheet/matrix')
async def handle_timesheet_matrix(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    try:
        date_from, date_to = _date_range(body)
    except (ValueError, TypeError, OverflowError):
        return web.json_response({"error": "invalid_dates"}, status=400)

    employees = await _run(_sync_timesheet_matrix, user["user_id"], date_from, date_to, body.get("period") in ("week", "month"))
    return web.json_response({"employees": employees})


def _sync_save_cell(user_id, target_uid, work_date, hours, status, restaurant_key=None, start_time=None, end_time=None):
    hours = round(hours, 2)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            cur.execute("SELECT 1 FROM attendance_import_days WHERE user_id = %s AND work_date = %s LIMIT 1",
                        (target_uid, work_date))
            if cur.fetchone():
                return False
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            actor_row = cur.fetchone()
            if not actor_row:
                return "forbidden"
            actor = dict(zip([d[0] for d in cur.description], actor_row))
            if not _is_hr_or_super(actor):
                cur.execute("SELECT restaurant_key FROM users WHERE user_id = %s", (target_uid,))
                target = cur.fetchone()
                if not target:
                    return "forbidden"
                home = target[0]
                territory = ()
                if _is_tu(actor):
                    cur.execute("SELECT key FROM restaurants WHERE territory_manager_id = %s", (user_id,))
                    territory = tuple(row[0] for row in cur.fetchall())
                cur.execute("SELECT restaurant_key FROM timesheet_records WHERE user_id = %s AND work_date = %s FOR UPDATE", (target_uid, work_date))
                existing = cur.fetchone()
                if not _restaurant_in_scope(actor, home, territory) or not _restaurant_in_scope(actor, restaurant_key or home, territory):
                    return "forbidden"
                if existing and not _restaurant_in_scope(actor, existing[0] or home, territory):
                    return "forbidden"
            if hours <= 0 and status == 'work':
                cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s", (target_uid, work_date))
            else:
                cur.execute(
                    """INSERT INTO timesheet_records (user_id, work_date, hours, status, restaurant_key, start_time, end_time, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s::time, %s::time, NOW())
                       ON CONFLICT (user_id, work_date) DO UPDATE SET
                           hours = EXCLUDED.hours, status = EXCLUDED.status,
                           restaurant_key = EXCLUDED.restaurant_key,
                           start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time, updated_at = NOW()""",
                    (target_uid, work_date, hours, status, restaurant_key, start_time or None, end_time or None)
                )
    return True


@routes.post('/api/timesheet/save_cell')
async def handle_timesheet_save_cell(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    target_uid = _positive_id(body.get("user_id"))
    status = body.get("status", "work")
    restaurant_key = body.get("restaurant_key")
    try:
        work_date = date.fromisoformat(body.get("work_date")).isoformat()
        hours = _finite_number(body.get("hours", 0))
        start_time = _shift_time(body.get("start_time"))
        end_time = _shift_time(body.get("end_time"))
    except (ValueError, TypeError):
        return web.json_response({"error": "invalid_data"}, status=400)
    if (not target_uid or not 0 <= hours <= 24
            or status not in ("work", "vacation", "sick", "absent")
            or (restaurant_key is not None and not isinstance(restaurant_key, str))):
        return web.json_response({"error": "invalid_data"}, status=400)
    restaurant_key = restaurant_key or None
    allowed = await _run(_check_can_edit_user, user, target_uid)
    if not allowed:
        return web.json_response({"error": "forbidden_edit_other"}, status=403)

    if restaurant_key:
        territory_keys = await _run(_sync_get_tu_rests, user["user_id"]) if _is_tu(user) else ()
        if not _restaurant_in_scope(user, restaurant_key, territory_keys):
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    try:
        saved = await _run(_sync_save_cell, user["user_id"], target_uid, work_date, hours, status, restaurant_key, start_time, end_time)
    except CheckViolation as exc:
        if exc.diag.message_primary != "Timesheet is locked for approval":
            raise
        return web.json_response({"error": "Табель закрыт на согласование или утверждён"}, status=409)
    if saved == "forbidden":
        return web.json_response({"error": "forbidden_restaurant"}, status=403)
    if saved is False:
        return web.json_response({"error": "День закрыт импортированным отчётом"}, status=409)
    return web.json_response({"ok": True})


def _parse_date(val):
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return None


def _sync_import_attendance(user, rows, default_rest_key=None):
    success = 0
    errors = []

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT user_id, login, personnel_number, restaurant_key
                FROM users
                WHERE personnel_number IS NOT NULL AND personnel_number != '' AND COALESCE(is_fired, FALSE) = FALSE
            """)
            users_map = {str(u["personnel_number"]).strip(): u for u in cur.fetchall()}

            cur.execute("SELECT key, name, territory_manager_id FROM restaurants")
            restaurants = cur.fetchall()
            rest_map = {r["name"].strip().lower(): r["key"] for r in restaurants}
            known_keys = set(rest_map.values())
            territory_keys = {r["key"] for r in restaurants if r["territory_manager_id"] == user["user_id"]}
            is_shift_manager = "управляющий сменой" in (user.get("position") or "").lower()

            for row in rows:
                try:
                    date_str = row[0]
                    personnel_number = row[1]
                    raw_val = row[2]
                    rest_name = row[3] if len(row) > 3 else None

                    if not date_str or not personnel_number:
                        continue

                    target_user = users_map.get(personnel_number)
                    if not target_user:
                        errors.append(f"Сотрудник с таб. номером '{personnel_number}' не найден")
                        continue

                    if (target_user["user_id"] != user["user_id"] and not _is_hr_or_super(user)
                            and not ((_is_tu(user) or is_shift_manager)
                                     and _restaurant_in_scope(user, target_user["restaurant_key"], territory_keys))):
                        errors.append("Нет доступа к сотруднику в строке табеля")
                        continue

                    date_str = date.fromisoformat(date_str).isoformat()
                    status = "work"
                    start_time = end_time = None
                    if raw_val in ("В", "Б", "Н"):
                        status = {"В": "vacation", "Б": "sick", "Н": "absent"}[raw_val]
                        hours = 0 if status == "absent" else 8
                    elif "-" in raw_val:
                        start, end = raw_val.split("-")
                        start_time = _shift_time(start.strip())
                        end_time = _shift_time(end.strip())
                        start_seconds = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
                        end_seconds = end_time.hour * 3600 + end_time.minute * 60 + end_time.second
                        hours = (end_seconds - start_seconds) % 86400 / 3600
                    elif ":" in raw_val:
                        if raw_val in ("24:00", "24:00:00"):
                            hours = 24
                        else:
                            parsed = _shift_time(raw_val)
                            hours = parsed.hour + parsed.minute / 60 + parsed.second / 3600
                    else:
                        hours = _finite_number(raw_val)
                    if not 0 <= hours <= 24:
                        raise ValueError("invalid hours")
                    hours = round(hours, 2)

                    r_key = None
                    if rest_name:
                        clean_rest_name = rest_name.strip().lower()
                        r_key = rest_map.get(clean_rest_name)
                        if not r_key:
                            for db_name, db_key in rest_map.items():
                                if clean_rest_name in db_name or db_name in clean_rest_name:
                                    r_key = db_key
                                    break
                    if not r_key:
                        r_key = default_rest_key or target_user["restaurant_key"]

                    if r_key and (r_key not in known_keys or not _restaurant_in_scope(user, r_key, territory_keys)):
                        errors.append("Недопустимый ресторан в строке табеля")
                        continue

                    if hours <= 0 and status == 'work':
                        cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s",
                                    (target_user["user_id"], date_str))
                    else:
                        cur.execute(
                            """INSERT INTO timesheet_records (user_id, work_date, hours, status, restaurant_key, start_time, end_time, updated_at)
                               VALUES (%s, %s, %s, %s, %s, %s::time, %s::time, NOW())
                               ON CONFLICT (user_id, work_date) DO UPDATE SET
                                   hours = EXCLUDED.hours, status = EXCLUDED.status,
                                   restaurant_key = EXCLUDED.restaurant_key,
                                   start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time, updated_at = NOW()""",
                            (target_user["user_id"], date_str, hours, status, r_key, start_time, end_time)
                        )
                    success += 1
                except (ValueError, TypeError, AttributeError):
                    errors.append("Недопустимые дата, часы или время в строке табеля")

    return success, errors[:10]


def _parse_excel_rows(file_data):
    wb = load_workbook(filename=io.BytesIO(file_data), data_only=True)
    ws = wb.active
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    for merged in ws.merged_cells.ranges:
        if merged.min_col == merged.max_col and merged.min_row < merged.max_row:
            value = rows[merged.min_row - 1][merged.min_col - 1]
            for row_index in range(merged.min_row, merged.max_row):
                rows[row_index][merged.min_col - 1] = value

    header_idx = -1
    for i, row in enumerate(rows):
        if any(cell and "табельный номер" in str(cell).lower() for cell in row):
            header_idx = i
            break

    if header_idx == -1:
        raise Exception("Не найдена строка с заголовками (Табельный номер)")

    headers = rows[header_idx]
    pers_num_col = -1
    rest_col = -1
    date_cols = {}

    for col_idx, cell_val in enumerate(headers):
        if not cell_val:
            continue
        val_str = str(cell_val).strip().lower()

        if "табельный номер" in val_str:
            pers_num_col = col_idx
        elif "подразделение" in val_str or "ресторан" in val_str:
            rest_col = col_idx
        else:
            date_str = _parse_date(cell_val)
            if date_str:
                date_cols[col_idx] = date_str

    if pers_num_col == -1:
        raise Exception("Колонка 'Табельный номер' не найдена")

    parsed_data = []
    current_pers_num = None

    for row in rows[header_idx + 1:]:
        if not row:
            continue

        if len(row) > pers_num_col and row[pers_num_col]:
            current_pers_num = str(row[pers_num_col]).strip()

        if not current_pers_num:
            continue

        rest_name = ""
        if rest_col != -1 and rest_col < len(row) and row[rest_col]:
            rest_name = str(row[rest_col]).strip()

        has_data = False
        for col_idx in date_cols.keys():
            if col_idx < len(row) and row[col_idx] is not None:
                has_data = True
                break
        if not has_data:
            continue

        for col_idx, date_str in date_cols.items():
            if col_idx < len(row) and row[col_idx] is not None:
                cell_val = row[col_idx]

                if isinstance(cell_val, time):
                    raw_val = f"{cell_val.hour}:{cell_val.minute:02d}"
                elif isinstance(cell_val, (float, int)):
                    raw_val = str(cell_val)
                else:
                    raw_val = str(cell_val).strip()

                if not raw_val or raw_val.upper() == 'NONE':
                    continue
                parsed_data.append((date_str, current_pers_num, raw_val.upper(), rest_name))

    return parsed_data



def _normalize_attendance_number(value):
    number = str(value).strip()
    if number.isascii() and number.isdecimal():
        return number.lstrip("0") or "0"
    return number


def _attendance_restaurant_name(value):
    return " ".join(str(value).casefold().replace("ё", "е").split())


def _sync_matching_registry(user, change=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if change is not None:
                kind, source, target = change
                cur.execute("SELECT pg_advisory_xact_lock(814726, 3)")
                if target is not None:
                    if kind == "employees":
                        cur.execute("SELECT user_id FROM users WHERE user_id::text=%s AND COALESCE(is_fired,FALSE)=FALSE", (target,))
                        matches = cur.fetchall()
                    else:
                        cur.execute("SELECT key FROM restaurants WHERE key=%s", (target,))
                        matches = cur.fetchall()
                    if len(matches) != 1:
                        raise ValueError("Unknown or ambiguous target")
                cur.execute("SELECT target FROM attendance_matching WHERE kind=%s AND source=%s FOR UPDATE", (kind, source))
                row = cur.fetchone()
                previous = row["target"] if row else None
                if previous != target:
                    if target is None:
                        cur.execute("DELETE FROM attendance_matching WHERE kind=%s AND source=%s", (kind, source))
                    else:
                        cur.execute("INSERT INTO attendance_matching(kind,source,target,actor_id) VALUES (%s,%s,%s,%s) ON CONFLICT(kind,source) DO UPDATE SET target=EXCLUDED.target,actor_id=EXCLUDED.actor_id,updated_at=now()", (kind,source,target,user["user_id"]))
                    cur.execute("INSERT INTO attendance_matching_history(kind,source,previous_target,new_target,actor_id) VALUES (%s,%s,%s,%s,%s)", (kind,source,previous,target,user["user_id"]))
            cur.execute("SELECT kind,source,target,actor_id,updated_at::text FROM attendance_matching ORDER BY kind,source")
            entries = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT id,kind,source,previous_target,new_target,actor_id,created_at::text FROM attendance_matching_history ORDER BY id DESC LIMIT 100")
            history = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT user_id::text AS id, full_name, personnel_number FROM users WHERE COALESCE(is_fired,FALSE)=FALSE ORDER BY full_name,user_id")
            employees = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT key AS id,name FROM restaurants ORDER BY name,key")
            restaurants = [dict(r) for r in cur.fetchall()]
            targets = {"employees": {r["id"]: r for r in employees},
                       "restaurants": {r["id"]: r for r in restaurants}}
            for entry in entries:
                entry["stale"] = entry["target"] not in targets[entry["kind"]]
            return {"entries": entries, "history": history, "employees": employees, "restaurants": restaurants}


@routes.get('/api/timesheet/matching')
@routes.post('/api/timesheet/matching')
@routes.delete('/api/timesheet/matching')
async def handle_attendance_matching(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(user):
        return denied(403)
    change = None
    if request.method != "GET":
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError()
            kind, source = data.get("kind"), data.get("source")
            target = data.get("target") if request.method == "POST" else None
            if kind not in ("employees", "restaurants") or not isinstance(source,str) or not 1 <= len(source.strip()) <= 200:
                raise ValueError()
            if request.method == "POST" and (not isinstance(target,str) or not 1 <= len(target.strip()) <= 200):
                raise ValueError()
            change = (kind,source.strip(),target.strip() if target is not None else None)
        except (ValueError, TypeError):
            return web.json_response({"error":"Некорректное соответствие"},status=400)
    try:
        result = await _run(_sync_matching_registry,user,change)
    except ValueError:
        return web.json_response({"error":"Назначение не найдено или неоднозначно"},status=400)
    return web.json_response(result,headers={"Cache-Control":"no-store"})


def _merge_saved_attendance_mapping(rows, saved, manual):
    merged = {"employees": {}, "restaurants": {}}
    for entry in saved:
        merged[entry["kind"]][entry["source"]] = entry["target"]
    for kind, target_type in (("employees", "personnel_number"), ("restaurants", "restaurant_name")):
        for source, target in (manual or {}).get(kind, {}).items():
            merged[kind][source] = (target_type, target, source)

    def source(value):
        return value[2] if isinstance(value, tuple) else value

    def resolve(kind, value):
        key = source(value)
        target = merged[kind].get(str(key) if kind == "employees" else key)
        if isinstance(value, tuple) and value[0].startswith("confirmed_"):
            return (*value, target)
        return target if target is not None else value

    return [(day, resolve("employees", number), raw, resolve("restaurants", name))
            for day, number, raw, name in rows]


def _load_saved_attendance_mapping():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT kind,source,target FROM attendance_matching")
            return [dict(entry, target=("employee_id", entry["target"], entry["source"]) if entry["kind"] == "employees"
                         else ("restaurant_key", entry["target"], entry["source"])) for entry in cur.fetchall()]


def _apply_attendance_mapping(user, rows, mapping):
    if mapping is None:
        return rows
    if not _is_hr_or_super(user):
        raise PermissionError("Manual matching requires HR or super administrator")
    if not isinstance(mapping, dict) or set(mapping) - {"employees", "restaurants"}:
        raise ValueError("Invalid mapping")
    employees = mapping.get("employees", {})
    restaurants = mapping.get("restaurants", {})
    for entries in (employees, restaurants):
        if not isinstance(entries, dict) or len(entries) > 500 or any(
            not isinstance(k, str) or not isinstance(v, str) or not k.strip() or not v.strip()
            or len(k) > 200 or len(v) > 200 for k, v in entries.items()
        ):
            raise ValueError("Invalid mapping entries")
    source_numbers = {str(number) for _, number, _, _ in rows}
    source_names = {name for _, _, _, name in rows}
    if set(employees) - source_numbers or set(restaurants) - source_names:
        raise ValueError("Mapping source not present in report")
    return [(day, employees.get(str(number), number), raw, restaurants.get(name, name))
            for day, number, raw, name in rows]


def _sync_preview_attendance(user, rows, default_rest_key=None, pending=None):
    """Validate scope and calculate minutes without changing payroll records."""
    from utils.attendance_minutes import shift_interval, worked_minutes
    groups = {}
    statuses = {}
    errors = []
    matching_errors = set()
    cell_errors = []
    unresolved_employees = set()
    unresolved_restaurants = set()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT user_id, personnel_number, restaurant_key FROM users WHERE COALESCE(is_fired, FALSE) = FALSE")
            users = {}
            users_by_id = {}
            for employee in cur.fetchall():
                users_by_id[str(employee["user_id"])] = employee
                if employee["personnel_number"] is not None:
                    users.setdefault(_normalize_attendance_number(employee["personnel_number"]), []).append(employee)
            cur.execute("SELECT key, name, territory_manager_id FROM restaurants")
            restaurants = cur.fetchall()
    territory = {r["key"] for r in restaurants if r["territory_manager_id"] == user["user_id"]}
    known = {r["key"] for r in restaurants}
    for day, number, raw, name in rows:
        original_row = (day, number, raw, name)
        original_number = number[2] if isinstance(number, tuple) else number
        original_name = name[2] if isinstance(name, tuple) else name
        if isinstance(number, tuple) and number[0] != "personnel_number":
            selected = users_by_id.get(number[1])
            if selected is None and len(number) == 4 and number[3]:
                selected = users_by_id.get(number[3][1])
            candidates = [selected] if selected else []
        else:
            target_number = number[1] if isinstance(number, tuple) else number
            candidates = users.get(_normalize_attendance_number(target_number), [])
        employee = candidates[0] if len(candidates) == 1 else None
        if isinstance(name, tuple) and name[0] != "restaurant_name":
            target_key = name[1]
            if target_key not in known and len(name) == 4 and name[3]:
                target_key = name[3][1]
            matches = [target_key]
        elif name:
            target_name = name[1] if isinstance(name, tuple) else name
            matches = [r["key"] for r in restaurants if _attendance_restaurant_name(r["name"]) == _attendance_restaurant_name(target_name)]
        else:
            matches = []
        key = matches[0] if len(matches) == 1 else (default_rest_key or (employee or {}).get("restaurant_key")) if not name else None
        restaurant_unresolved = bool(name or employee) and (key not in known or not _restaurant_in_scope(user, key, territory))
        if not employee:
            unresolved_employees.add(str(original_number))
            reason = "не найден" if not candidates else "неоднозначен"
            matching_errors.add(f"Табельный номер {original_number}: {reason} ({original_name or '-'})")
        if restaurant_unresolved:
            if original_name:
                unresolved_restaurants.add(original_name)
            matching_errors.add(f"Неизвестный или недоступный ресторан: {original_name or '-'}")
        if not employee or restaurant_unresolved:
            if pending is not None:
                if employee and isinstance(number, tuple):
                    number = ("confirmed_employee", str(employee["user_id"]), original_number)
                elif isinstance(number, tuple) and number[0] == "confirmed_employee":
                    number = original_number
                if name and not restaurant_unresolved and isinstance(name, tuple):
                    name = ("confirmed_restaurant", key, original_name)
                elif isinstance(name, tuple) and name[0] == "confirmed_restaurant":
                    name = original_name
                pending.append((day, number, raw, name))
            continue
        number = employee["user_id"]
        if not _is_hr_or_super(user) and employee["user_id"] != user["user_id"]:
            if not (_is_tu(user) or "управляющий сменой" in (user.get("position") or "").lower()) or not _restaurant_in_scope(user, employee["restaurant_key"], territory):
                errors.append("Нет доступа к сотруднику")
                continue
        if raw in ("В", "Б", "Н"):
            statuses.setdefault((number, day, key), set()).add(raw)
            continue
        try:
            shift_interval(raw)
        except ValueError:
            cell_errors.append(f"{day}, табельный номер {original_number}: некорректный интервал смены")
            if pending is not None:
                pending.append(tuple(value[:3] if isinstance(value, tuple) else value for value in original_row))
            continue
        groups.setdefault((number, day, key), []).append(raw)
    records = [{"user_id": number, "personnel_number": _normalize_attendance_number(users_by_id[str(number)]["personnel_number"] or ""), "date": day, "restaurant_key": key,
                "minutes": worked_minutes(values), "shifts": values}
               for (number, day, key), values in sorted(groups.items())]
    work_days = {(number, day) for number, day, key in groups}
    status_days = {}
    for (number, day, key), values in statuses.items():
        status_days.setdefault((number, day), []).append((key, values))
        if len(values) != 1 or (number, day) in work_days:
            errors.append("Конфликт статуса отсутствия и смены")
        else:
            status = {"В": "vacation", "Б": "sick", "Н": "absent"}[next(iter(values))]
            records.append({"user_id": number, "personnel_number": _normalize_attendance_number(users_by_id[str(number)]["personnel_number"] or ""), "date": day, "restaurant_key": key,
                            "minutes": 0, "shifts": [], "status": status})
    for entries in status_days.values():
        if len(entries) > 1:
            errors.append("Статус отсутствия указан в нескольких ресторанах")
    by_employee = {}
    for (number, day, key), values in groups.items():
        offset = date.fromisoformat(day).toordinal() * 1440
        for value in values:
            start, end = shift_interval(value)
            by_employee.setdefault(number, []).append((offset + start, offset + end, day, key))
    for intervals in by_employee.values():
        intervals.sort()
        for i, (start, end, day, key) in enumerate(intervals):
            for left, right, other_day, other_key in intervals[i+1:]:
                if left >= end:
                    break
                if start < right and (other_key != key or other_day != day):
                    errors.append("Пересечение смен в разных ресторанах или рабочих датах")
                    break
    blocking_errors = len(errors)
    errors.extend(cell_errors)
    errors.extend(sorted(matching_errors))
    is_privileged = _is_hr_or_super(user)
    matching = {"employees": sorted(unresolved_employees), "restaurants": sorted(unresolved_restaurants)} if is_privileged else None
    partial_allowed = is_privileged and not blocking_errors and bool(matching_errors or cell_errors)
    return {"matching": matching, "ok": not errors, "partial_allowed": partial_allowed, "preview": True, "records": records,
            "total_minutes": sum(r["minutes"] for r in records) if not errors or partial_allowed else None,
            "error_count": len(errors), "errors": errors[:50]}


def _sync_attendance_history(user):
    """Return only restaurant-level summaries within the current user's scope."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT key, territory_manager_id FROM restaurants")
            restaurants = cur.fetchall()
            territory = {r["key"] for r in restaurants if r["territory_manager_id"] == user["user_id"]}
            allowed = [r["key"] for r in restaurants if _restaurant_in_scope(user, r["key"], territory)]
            cur.execute("""SELECT i.id, i.created_at::text AS created_at,
                d.restaurant_key, MIN(d.work_date)::text AS date_from,
                MAX(d.work_date)::text AS date_to, COUNT(*) AS record_count,
                SUM(d.worked_minutes) AS total_minutes
                FROM attendance_imports i JOIN attendance_import_days d ON d.import_id = i.id
                WHERE d.restaurant_key = ANY(%s)
                GROUP BY i.id, i.created_at, d.restaurant_key
                ORDER BY i.id DESC, d.restaurant_key LIMIT 200""", (allowed,))
            return [dict(row) for row in cur.fetchall()]


@routes.get('/api/timesheet/import_attendance/history')
async def handle_attendance_history(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)
    if not (_is_hr_or_super(user) or _is_tu(user)):
        return web.json_response({"error": "Нет права на просмотр истории"}, status=403)
    records = await _run(_sync_attendance_history, user)
    return web.json_response({"records": records}, headers={"Cache-Control": "no-store"})


def _sync_delete_attendance(user, import_id, restaurant_key):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            cur.execute("SELECT key, territory_manager_id FROM restaurants WHERE key = %s FOR SHARE", (restaurant_key,))
            restaurant = cur.fetchone()
            territory = {restaurant_key} if restaurant and restaurant["territory_manager_id"] == user["user_id"] else set()
            if not restaurant or not _restaurant_in_scope(user, restaurant_key, territory):
                return None
            cur.execute("DELETE FROM attendance_import_days WHERE import_id = %s AND restaurant_key = %s", (import_id, restaurant_key))
            deleted = cur.rowcount
            cur.execute("DELETE FROM attendance_imports i WHERE id = %s AND NOT EXISTS (SELECT 1 FROM attendance_import_days d WHERE d.import_id = i.id)", (import_id,))
            return deleted


@routes.post('/api/timesheet/import_attendance/delete')
async def handle_delete_attendance(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)
    if not (_is_hr_or_super(user) or _is_tu(user)):
        return web.json_response({"error": "Нет права на удаление"}, status=403)
    try:
        body = await request.json()
        import_id = body["import_id"]
        restaurant_key = body["restaurant_key"]
        if type(import_id) is not int or not 0 < import_id < 2**63 or not isinstance(restaurant_key, str) or not restaurant_key or len(restaurant_key) > 256:
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        return web.json_response({"error": "Некорректные параметры отчёта"}, status=400)
    try:
        deleted = await _run(_sync_delete_attendance, user, import_id, restaurant_key)
    except CheckViolation as exc:
        if exc.diag.message_primary != "Timesheet is locked for approval":
            raise
        return web.json_response({"error": "Табель закрыт на согласование или утверждён"}, status=409)
    if deleted is None:
        return web.json_response({"error": "Нет доступа к ресторану"}, status=403)
    if not deleted:
        return web.json_response({"error": "Отчёт не найден"}, status=404)
    logging.getLogger(__name__).info("attendance_import_deleted actor=%s import_id=%s restaurant=%r deleted_count=%s",
                                    user["user_id"], import_id, restaurant_key, deleted)
    return web.json_response({"ok": True, "deleted_count": deleted}, headers={"Cache-Control": "no-store"})


def _attendance_saved_conflict(cur, records, employee_ids, partial=False):
    """Check surviving staged records before replacing restaurant/date pairs."""
    from utils.attendance_minutes import shift_interval
    replacements = {(r["restaurant_key"], r["date"]) for r in records} if not partial else set()
    for record in records:
        day = date.fromisoformat(record["date"])
        cur.execute("""SELECT d.restaurant_key, d.work_date::text AS work_date,
            d.status, i.start_minute, i.end_minute
            FROM attendance_import_days d
            LEFT JOIN attendance_import_intervals i ON i.day_id = d.id
            WHERE d.user_id = %s AND d.work_date BETWEEN %s::date - 1 AND %s::date + 1""",
                    (record["user_id"], day, day))
        offset = day.toordinal() * 1440
        incoming = [(offset + a, offset + b) for a, b in
                    (shift_interval(v) for v in record["shifts"])]
        for saved in cur.fetchall():
            if (saved["restaurant_key"], saved["work_date"]) in replacements:
                continue
            if saved["work_date"] == record["date"] and (
                saved["status"] != "work" or record.get("status", "work") != "work"
            ):
                return True
            if saved["start_minute"] is None:
                continue
            base = date.fromisoformat(saved["work_date"]).toordinal() * 1440
            left, right = base + saved["start_minute"], base + saved["end_minute"]
            if any(start < right and left < end for start, end in incoming):
                return True
    return False


def _sync_stage_attendance(user, rows, default_rest_key=None, partial=False, source_file=None, retry_id=None, expected_pending=None):
    """Store a validated batch for review, without affecting legacy payroll."""
    from utils.attendance_minutes import shift_interval
    pending = []
    result = _sync_preview_attendance(user, rows, default_rest_key, pending) if partial else _sync_preview_attendance(user, rows, default_rest_key)
    allow_pending = partial and result["partial_allowed"]
    if not result["ok"] and not allow_pending:
        return {"ok": False, "errors": result["errors"]}
    records = result["records"]
    if not records and (not allow_pending or retry_id is not None):
        return {"ok": False, "errors": result["errors"] or ["Нет записей для загрузки"]}
    if partial and (not _is_hr_or_super(user) or (retry_id is None and not source_file)):
        raise ValueError("Partial import requires authorized source file")
    report_id = retry_id
    diagnostics = {key: result[key] for key in ("errors", "matching", "error_count")} if partial else None
    if partial:
        diagnostics["pending_rows"] = pending
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            if retry_id is not None:
                cur.execute("""SELECT diagnostics->'pending_rows' AS pending_rows
                    FROM attendance_partial_reports WHERE id=%s AND resolved_at IS NULL FOR UPDATE""", (retry_id,))
                archive = cur.fetchone()
                if not archive or (expected_pending is not None and archive["pending_rows"] != expected_pending):
                    return {"ok": False, "errors": ["Отчёт изменён или уже обработан. Повторите проверку."]}
            elif source_file:
                cur.execute("""SELECT id FROM attendance_partial_reports
                    WHERE sha256(source_file)=sha256(%s::bytea)
                    AND COALESCE(default_restaurant_key, '')=COALESCE(%s, '')
                    ORDER BY id LIMIT 1""", (bytes(source_file), default_rest_key))
                existing_report = cur.fetchone()
                if existing_report:
                    message = "Файл уже сохранён. Проверьте архив отчётов." if _is_hr_or_super(user) else "Файл уже сохранён"
                    return {"ok": False, "errors": [message]}
            employee_ids = {}
            cur.execute("SELECT key, territory_manager_id FROM restaurants FOR SHARE")
            restaurants = cur.fetchall()
            territory = {r["key"] for r in restaurants if r["territory_manager_id"] == user["user_id"]}
            known = {r["key"] for r in restaurants}
            for uid in sorted({r["user_id"] for r in records}):
                cur.execute("SELECT user_id,restaurant_key FROM users WHERE user_id=%s AND COALESCE(is_fired,FALSE)=FALSE FOR SHARE", (uid,))
                employee = cur.fetchone()
                if not employee or (not _is_hr_or_super(user) and not _restaurant_in_scope(user, employee["restaurant_key"], territory)):
                    raise ValueError("Employee changed during import")
            if any(r["restaurant_key"] not in known or not _restaurant_in_scope(user,r["restaurant_key"],territory) for r in records):
                raise ValueError("Restaurant changed during import")
            if partial:
                new_records = []
                for record in records:
                    cur.execute("""SELECT d.status, d.worked_minutes, i.start_minute, i.end_minute
                        FROM attendance_import_days d LEFT JOIN attendance_import_intervals i ON i.day_id=d.id
                        WHERE d.user_id=%s AND d.restaurant_key=%s AND d.work_date=%s""",
                        (record["user_id"], record["restaurant_key"], record["date"]))
                    existing = cur.fetchall()
                    if not existing:
                        new_records.append(record)
                        continue
                    expected = {shift_interval(value) for value in record["shifts"]}
                    actual = {(row["start_minute"], row["end_minute"]) for row in existing if row["start_minute"] is not None}
                    if expected != actual or any(row["status"] != record.get("status", "work") or row["worked_minutes"] != record["minutes"] for row in existing):
                        return {"ok": False, "errors": ["Исправленный отчёт отличается от сохранённого рабочего дня. Требуется ручная сверка; отчёт не закрыт."]}
                records = new_records
            if _attendance_saved_conflict(cur, records, employee_ids, partial):
                return {"ok": False, "errors": ["Конфликт с ранее загруженным отчётом: пересечение смен или статусов отсутствия. Проверьте данные."]}
            if not partial:
                for key, day in sorted({(r["restaurant_key"], r["date"]) for r in records}):
                    cur.execute("DELETE FROM attendance_import_days WHERE restaurant_key = %s AND work_date = %s", (key, day))
            import_id = None
            if records:
                cur.execute("DELETE FROM attendance_imports i WHERE NOT EXISTS (SELECT 1 FROM attendance_import_days d WHERE d.import_id = i.id)")
                cur.execute("INSERT INTO attendance_imports (uploaded_by, date_from, date_to) VALUES (%s, %s, %s) RETURNING id",
                            (user["user_id"], min(r["date"] for r in records), max(r["date"] for r in records)))
                import_id = cur.fetchone()["id"]
                for record in records:
                    cur.execute("""INSERT INTO attendance_import_days
                        (import_id, user_id, work_date, restaurant_key, status, worked_minutes)
                        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                        (import_id, record["user_id"], record["date"], record["restaurant_key"],
                         record.get("status", "work"), record["minutes"]))
                    day_id = cur.fetchone()["id"]
                    for start, end in sorted({shift_interval(v) for v in record["shifts"]}):
                        cur.execute("INSERT INTO attendance_import_intervals (day_id, start_minute, end_minute) VALUES (%s, %s, %s)",
                                    (day_id, start, end))
            if retry_id is not None:
                cur.execute("""UPDATE attendance_partial_reports SET diagnostics=%s::jsonb,
                    resolved_at=CASE WHEN %s THEN NULL ELSE now() END WHERE id=%s""",
                    (json.dumps(diagnostics), bool(pending), retry_id))
            elif allow_pending:
                cur.execute("""INSERT INTO attendance_partial_reports
                    (uploaded_by, source_file, diagnostics, default_restaurant_key)
                    VALUES (%s,%s,%s::jsonb,%s) RETURNING id""",
                    (user["user_id"], bytes(source_file), json.dumps(diagnostics), default_rest_key))
                report_id = cur.fetchone()["id"]
    return {"ok": True, "report_id": report_id, "import_id": import_id, "success_count": len(records), "staged": True,
            "partial": bool(partial and not result["ok"]), "errors": result["errors"], "error_count": result["error_count"]}


def _sync_partial_report_list():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT id, uploaded_by, created_at::text AS created_at,
                diagnostics - 'pending_rows' AS diagnostics, resolved_at::text AS resolved_at
                FROM attendance_partial_reports ORDER BY id DESC LIMIT 200""")
            return [dict(row) for row in cur.fetchall()]


def _sync_partial_report_pending(report_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT diagnostics, default_restaurant_key FROM attendance_partial_reports WHERE id=%s AND resolved_at IS NULL", (report_id,))
            row = cur.fetchone()
    if not row or not row["diagnostics"].get("pending_rows"):
        raise ValueError("No recoverable pending rows")
    pending = []
    for day, number, raw, name in row["diagnostics"]["pending_rows"]:
        pending.append((day, tuple(number) if isinstance(number, list) else number,
                        raw, tuple(name) if isinstance(name, list) else name))
    return pending, row["default_restaurant_key"]


def _sync_partial_report_file(report_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT source_file FROM attendance_partial_reports WHERE id=%s", (report_id,))
            row = cur.fetchone()
            return bytes(row["source_file"]) if row else None


@routes.get('/api/timesheet/import_attendance/partial_reports')
async def handle_partial_reports(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)
    if not _is_hr_or_super(user):
        return denied(403)
    return web.json_response({"records": await _run(_sync_partial_report_list)}, headers={"Cache-Control": "no-store"})


@routes.post('/api/timesheet/import_attendance/partial_reports/{report_id}/preview')
async def handle_partial_report_preview(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)
    if not _is_hr_or_super(user):
        return denied(403)
    try:
        report_id = int(request.match_info["report_id"])
        if not 0 < report_id < 2**63:
            raise ValueError()
    except ValueError:
        return web.json_response({"error": "Некорректный номер отчёта"}, status=400)
    try:
        rows, default_rest = await _run(_sync_partial_report_pending, report_id)
        saved = await _run(_load_saved_attendance_mapping)
        rows = _merge_saved_attendance_mapping(rows, saved, None)
        result = await _run(_sync_preview_attendance, user, rows, default_rest)
    except ValueError:
        return web.json_response({"error": "Не удалось проверить отчёт"}, status=400)
    return web.json_response(result, headers={"Cache-Control": "no-store"})


@routes.post('/api/timesheet/import_attendance/partial_reports/{report_id}/stage')
async def handle_partial_report_stage(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)
    if not _is_hr_or_super(user):
        return denied(403)
    try:
        report_id = int(request.match_info["report_id"])
        if not 0 < report_id < 2**63:
            raise ValueError()
    except ValueError:
        return web.json_response({"error": "Некорректный номер отчёта"}, status=400)
    try:
        rows, default_rest = await _run(_sync_partial_report_pending, report_id)
        expected_pending = json.loads(json.dumps(rows))
        saved = await _run(_load_saved_attendance_mapping)
        rows = _merge_saved_attendance_mapping(rows, saved, None)
        result = await _run(_sync_stage_attendance, user, rows, default_rest, True,
                            None, report_id, expected_pending)
    except CheckViolation as exc:
        if exc.diag.message_primary != "Timesheet is locked for approval":
            raise
        return web.json_response({"error": "Табель закрыт на согласование или утверждён"}, status=409)
    except ValueError:
        return web.json_response({"error": "Не удалось обработать отчёт"}, status=400)
    return web.json_response(result, headers={"Cache-Control": "no-store"})


@routes.get('/api/timesheet/import_attendance/partial_reports/{report_id}/file')
async def handle_partial_report_file(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)
    if not _is_hr_or_super(user):
        return denied(403)
    try:
        report_id = int(request.match_info["report_id"])
        if not 0 < report_id < 2**63:
            raise ValueError()
    except ValueError:
        return web.json_response({"error": "Некорректный номер отчёта"}, status=400)
    source = await _run(_sync_partial_report_file, report_id)
    if source is None:
        return web.json_response({"error": "Отчёт не найден"}, status=404)
    return web.Response(body=source, content_type="application/octet-stream",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Content-Disposition": f'attachment; filename="attendance-{report_id}.xlsx"'})


@routes.post('/api/timesheet/import_attendance/stage')
@routes.post('/api/timesheet/import_attendance/preview')
@routes.post('/api/timesheet/import_attendance')
async def handle_import_attendance(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    if not (_is_hr_or_super(user) or _is_tu(user)):
        return web.json_response({"error": "Нет права на загрузку"}, status=403)
    if request.path == "/api/timesheet/import_attendance":
        return web.json_response({"error": "Используйте предварительную проверку и сохранение отчёта"}, status=410)

    if request.content_type != "multipart/form-data":
        return web.json_response({"error": "Загрузите Excel через форму выбора файла"}, status=400)

    try:
        reader = await request.multipart()
        file_data = None
        default_rest = request.query.get("restaurant_key")
        mapping = None
        mapping_seen = False

        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == 'file':
                if file_data is not None:
                    return web.json_response({"error": "Допускается один файл"}, status=400)
                file_data = bytearray()
                while chunk := await part.read_chunk():
                    file_data.extend(chunk)
                    if request.client_max_size and len(file_data) > request.client_max_size:
                        return web.json_response({"error": "Файл слишком большой"}, status=413)
            elif part.name == "mapping":
                if not _is_hr_or_super(user):
                    return denied(403)
                if mapping_seen:
                    return web.json_response({"error": "Допускается один набор соответствий"}, status=400)
                mapping_seen = True
                try:
                    raw_mapping = bytearray()
                    while chunk := await part.read_chunk():
                        raw_mapping.extend(chunk)
                        if len(raw_mapping) > 100000:
                            break
                    if len(raw_mapping) > 100000:
                        return web.json_response({"error": "Слишком много соответствий"}, status=400)
                    mapping = json.loads(raw_mapping)
                    if not isinstance(mapping, dict):
                        raise ValueError("Invalid mapping")
                except (ValueError, UnicodeError):
                    return web.json_response({"error": "Некорректные соответствия"}, status=400)
    except (ValueError, AssertionError):
        return web.json_response({"error": "Не удалось прочитать форму загрузки Excel"}, status=400)

    if not file_data:
        return web.json_response({"error": "Файл не загружен"}, status=400)

    try:
        rows = await _run(_parse_excel_rows, file_data)
    except Exception:
        return web.json_response({"error": "Не удалось прочитать Excel"}, status=400)

    try:
        _apply_attendance_mapping(user, rows, mapping)
        saved = await _run(_load_saved_attendance_mapping)
        rows = _merge_saved_attendance_mapping(rows, saved, mapping)
    except PermissionError:
        return denied(403)
    except ValueError:
        return web.json_response({"error": "Некорректные соответствия"}, status=400)

    if request.path.endswith("/preview"):
        result = await _run(_sync_preview_attendance, user, rows, default_rest)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    if request.path.endswith("/stage"):
        if not (_is_hr_or_super(user) or _is_tu(user)):
            return web.json_response({"error": "Нет права на загрузку"}, status=403)
        try:
            if request.query.get("partial") == "1":
                if not _is_hr_or_super(user):
                    return denied(403)
                result = await _run(_sync_stage_attendance, user, rows, default_rest, True, file_data)
            else:
                result = await _run(_sync_stage_attendance, user, rows, default_rest, False, file_data)
        except CheckViolation as exc:
            if exc.diag.message_primary != "Timesheet is locked for approval":
                raise
            return web.json_response({"error": "Табель закрыт на согласование или утверждён"}, status=409)
        except ValueError:
            return web.json_response({"error": "Данные сотрудников изменились. Повторите проверку."}, status=409)
        return web.json_response(result, headers={"Cache-Control": "no-store"})

    success, errors = await _run(_sync_import_attendance, user, rows, default_rest)
    return web.json_response({"ok": True, "success_count": success, "errors": errors})


# ИСПРАВЛЕНО: добавлен флаг only_me и LEFT JOIN для корректной работы сотрудников без часов
# Imported employee-days supersede legacy records, including absence days.
_EFFECTIVE_ATTENDANCE_SQL = """
    WITH rounding AS (
        SELECT step_minutes AS step FROM timesheet_rounding_settings WHERE singleton = TRUE
    ), daily AS (
        SELECT d.user_id, d.work_date, d.restaurant_key,
               CASE WHEN d.status = 'work' THEN d.worked_minutes ELSE 0 END AS minutes
        FROM attendance_import_days d
    ), totals AS (
        SELECT *, SUM(minutes) OVER (PARTITION BY user_id, work_date) AS total
        FROM daily
    ), allocation AS (
        SELECT *, COALESCE(FLOOR(minutes::numeric * (ROUND(total::numeric / (SELECT step FROM rounding)) * (SELECT step FROM rounding)) / NULLIF(total, 0)), 0) AS base,
               COALESCE(MOD(minutes::numeric * (ROUND(total::numeric / (SELECT step FROM rounding)) * (SELECT step FROM rounding)), NULLIF(total, 0)), 0) AS remainder
        FROM totals
    ), ranked AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY user_id, work_date ORDER BY remainder DESC, restaurant_key COLLATE "C") AS rank,
               SUM(base) OVER (PARTITION BY user_id, work_date) AS allocated
        FROM allocation
    )
    SELECT t.user_id, t.work_date, t.restaurant_key,
           ROUND(ROUND(t.hours::numeric * 60) / (SELECT step FROM rounding)) * (SELECT step FROM rounding) / 60 AS hours
    FROM timesheet_records t
    WHERE NOT EXISTS (
        SELECT 1 FROM attendance_import_days d
        WHERE d.user_id = t.user_id AND d.work_date = t.work_date
    )
    UNION ALL
    SELECT user_id, work_date, restaurant_key,
           (base + CASE WHEN rank <= ROUND(total::numeric / (SELECT step FROM rounding)) * (SELECT step FROM rounding) - allocated THEN 1 ELSE 0 END) / 60 AS hours
    FROM ranked
"""


def _sync_approved_reports(user_id, date_from, date_to, only_me=False):
    """Return approved monthly totals or immutable daily detail, never draft calculations."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            user = cur.fetchone()
            if not user or user.get("is_fired"):
                return []
            sql = """SELECT s.full_name,s.position,s.restaurant_name,
                       SUM(CASE WHEN period.full_month THEN s.worked_minutes ELSE detail.minutes END)::numeric/60 AS total_hours,
                       s.rate,s.payment_type,SUM(CASE WHEN period.full_month THEN s.total_salary ELSE detail.salary END) AS total_salary
                FROM timesheet_accrual_snapshots s
                JOIN timesheet_approvals a ON a.restaurant_key=s.restaurant_key
                    AND a.month_start=s.month_start AND a.revision=s.revision
                CROSS JOIN (SELECT %s::date AS start_date,%s::date AS end_date) bounds
                CROSS JOIN LATERAL (SELECT s.month_start>=bounds.start_date
                    AND s.month_start+INTERVAL '1 month'-INTERVAL '1 day'<=bounds.end_date AS full_month) period
                LEFT JOIN LATERAL (
                    SELECT SUM(d.worked_minutes) AS minutes,SUM(d.total_salary) AS salary
                    FROM timesheet_accrual_snapshot_days d
                    WHERE d.restaurant_key=s.restaurant_key AND d.month_start=s.month_start
                        AND d.revision=s.revision AND d.user_id=s.user_id
                        AND d.work_date BETWEEN bounds.start_date AND bounds.end_date
                ) detail ON NOT period.full_month
                WHERE a.status='approved' AND s.month_start<=bounds.end_date
                    AND s.month_start+INTERVAL '1 month'>bounds.start_date
                    AND (period.full_month OR detail.minutes IS NOT NULL)"""
            params = [date_from,date_to]
            if only_me:
                sql += " AND s.user_id=%s"
                params.append(user_id)
            elif _is_tu(user):
                sql += " AND s.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id=%s)"
                params.append(user_id)
            elif not _is_hr_or_super(user):
                return []
            sql += """ GROUP BY s.user_id,s.restaurant_key,s.full_name,s.position,s.restaurant_name,s.rate,s.payment_type
                       ORDER BY s.restaurant_name,s.full_name"""
            cur.execute(sql,params)
            return [dict(row) for row in cur.fetchall()]


def _sync_legacy_partial_months(user_id, date_from, date_to, only_me=False):
    """Identify visible approved months whose historical daily detail is unavailable."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
            user = cur.fetchone()
            if not user or user.get("is_fired"):
                return []
            sql = """SELECT DISTINCT s.month_start::text AS month_start
                FROM timesheet_accrual_snapshots s
                JOIN timesheet_approvals a ON a.restaurant_key=s.restaurant_key
                    AND a.month_start=s.month_start AND a.revision=s.revision
                CROSS JOIN (SELECT %s::date AS start_date,%s::date AS end_date) b
                WHERE a.status='approved' AND s.month_start<=b.end_date
                    AND s.month_start+INTERVAL '1 month'>b.start_date
                    AND NOT (s.month_start>=b.start_date AND
                        s.month_start+INTERVAL '1 month'-INTERVAL '1 day'<=b.end_date)
                    AND (s.worked_minutes>0 OR s.total_salary>0)
                    AND NOT EXISTS (SELECT 1 FROM timesheet_accrual_snapshot_days d
                        WHERE d.restaurant_key=s.restaurant_key AND d.month_start=s.month_start
                        AND d.revision=s.revision AND d.user_id=s.user_id)"""
            params = [date_from,date_to]
            if only_me:
                sql += " AND s.user_id=%s"
                params.append(user_id)
            elif _is_tu(user):
                sql += " AND s.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id=%s)"
                params.append(user_id)
            elif not _is_hr_or_super(user):
                return []
            cur.execute(sql+" ORDER BY month_start",params)
            return [row["month_start"] for row in cur.fetchall()]


def _sync_reports(user_id, date_from, date_to, only_me=False):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            is_hr_or_super = _is_hr_or_super(u)
            is_tu = _is_tu(u)
            is_us = "управляющий сменой" in (u.get("position") or "").lower()

            base = "WITH effective_attendance AS (" + _EFFECTIVE_ATTENDANCE_SQL + """),
                period_attendance AS (
                    SELECT * FROM effective_attendance WHERE work_date BETWEEN %s::date AND %s::date
                )
                SELECT u.full_name, u.position,
                       COALESCE(tr.name, r.name) AS restaurant_name,
                       COALESCE(SUM(t.hours), 0) as total_hours,
                       COALESCE(ir.hourly_rate, 0) AS rate, u.payment_type,
                       ROUND(ROUND(COALESCE(SUM(t.hours), 0)*60)::numeric * COALESCE(ir.hourly_rate, 0)/60,2) as total_salary
                FROM users u 
                LEFT JOIN period_attendance t ON u.user_id = t.user_id
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN restaurants tr ON t.restaurant_key = tr.key
                LEFT JOIN timesheet_individual_rates ir ON ir.user_id=u.user_id
                WHERE COALESCE(u.is_fired, FALSE) = FALSE AND u.login IS NOT NULL"""
            
            params = [date_from, date_to]
            
            if only_me:
                base += " AND u.user_id = %s"
                params.append(user_id)
            elif is_us:
                base += " AND COALESCE(t.restaurant_key, u.restaurant_key) = %s"
                params.append(u.get("restaurant_key"))
            elif is_tu:
                base += " AND COALESCE(t.restaurant_key, u.restaurant_key) IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"
                params.append(user_id)
            elif not is_hr_or_super:
                base += " AND u.user_id = %s"
                params.append(user_id)
                
            base += " GROUP BY u.user_id, u.full_name, u.position, COALESCE(tr.name, r.name), COALESCE(t.restaurant_key, u.restaurant_key), u.restaurant_key, ir.hourly_rate, u.payment_type ORDER BY COALESCE(tr.name, r.name), u.full_name"

            cur.execute(base, params)
            return [dict(r) for r in cur.fetchall()]


@routes.post('/api/timesheet/reports')
async def handle_timesheet_reports(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    # ИСПРАВЛЕНО: убрали _require_timesheet_access(user), чтобы сотрудники могли видеть свои выплаты

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    try:
        date_from, date_to = _date_range(body)
    except (ValueError, TypeError, OverflowError):
        return web.json_response({"error": "invalid_dates"}, status=400)

    # ИСПРАВЛЕНО: Передаем True в only_me, чтобы каждый видел только свою зарплату в личном кабинете
    report = await _run(_sync_approved_reports, user["user_id"], date_from, date_to, True)
    legacy = await _run(_sync_legacy_partial_months, user["user_id"], date_from, date_to, True)
    return web.json_response({"report": [{**row, "total_hours": float(row["total_hours"]),
        "rate": float(row["rate"]), "total_salary": float(row["total_salary"])} for row in report],
        "legacy_partial_months": legacy}, headers={"Cache-Control":"no-store"})


@routes.post('/api/timesheet/accruals')
async def handle_timesheet_accruals(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("invalid body")
        date_from, date_to = _date_range(body)
    except (ValueError, TypeError, OverflowError):
        return web.json_response({"error": "invalid_dates"}, status=400)
    report = await _run(_sync_approved_reports, user["user_id"], date_from, date_to, False)
    legacy = await _run(_sync_legacy_partial_months, user["user_id"], date_from, date_to, False)
    return web.json_response({"legacy_partial_months": legacy, "report": [
        {**row, "total_hours": float(row["total_hours"]),
         "rate": float(row["rate"]), "total_salary": float(row["total_salary"])}
        for row in report
    ]}, headers={"Cache-Control": "no-store"})


@routes.get('/api/timesheet/export_excel')
async def handle_timesheet_export_excel(request):
    user, err = await _timesheet_user(request)
    if err and request.query.get("only_me") == "true":
        user, err = await get_auth_user(request)
    if err:
        return denied(err)
    if request.query.get("only_me") != "true":
        _require_timesheet_access(user)

    date_from = request.query.get("date_from")
    date_to = request.query.get("date_to")
    try:
        if not date_from or not date_to:
            raise ValueError("missing date")
        date_from, date_to = _date_range({"date_from": date_from, "date_to": date_to})
    except (ValueError, TypeError):
        return web.Response(text="Укажите корректные даты", status=400)

    # Если сотрудник качает из профиля, он передает only_me=true. Иначе (из табеля админа) качаем всех доступных.
    only_me = request.query.get("only_me") == "true"
    report = await _run(_sync_approved_reports, user["user_id"], date_from, date_to, only_me)

    legacy = await _run(_sync_legacy_partial_months, user["user_id"], date_from, date_to, only_me)
    wb = Workbook()
    ws = wb.active
    ws.title = "Табель"
    if legacy:
        notice = wb.create_sheet("Предупреждение")
        notice.append(["Отчёт неполный: отсутствует ежедневная детализация исторических табелей."])
        notice.append(["Выберите полный календарный месяц для просмотра исторических начислений."])
        for month in legacy:
            notice.append([month])
        notice.column_dimensions["A"].width = 100

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1C1C1E", end_color="1C1C1E", fill_type="solid")
    border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    center_align = Alignment(horizontal="center", vertical="center")

    headers = ["Сотрудник", "Должность", "Ресторан", "Часов", "Ставка (₽/ч)", "К оплате (₽)", "Пометка"]
    ws.append(headers)

    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = border

    for r in report:
        row_data = [
            r.get("full_name", ""),
            r.get("position", ""),
            r.get("restaurant_name", ""),
            float(r.get("total_hours", 0)),
            float(r.get("rate", 0)),
            float(r.get("total_salary", 0)),
            "Оклад" if r.get("payment_type") == "fixed" else "",
        ]
        ws.append(row_data)
        current_row = ws.max_row
        for col_num in range(1, 8):
            cell = ws.cell(row=current_row, column=col_num)
            cell.border = border
            if col_num <= 3 or col_num == 7:
                cell.data_type = "s"
            if 4 <= col_num <= 6:
                cell.alignment = Alignment(horizontal="right", vertical="center")

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                pass
        ws.column_dimensions[column].width = max_length + 2

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"Табель_{date_from}_{date_to}.xlsx"
    return web.Response(
        body=output.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _sync_settings_get(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u or not _is_hr_or_super(u):
                return []
            cur.execute("""SELECT p.name AS position_name, COALESCE(pr.rate, 0) AS rate
                FROM positions p LEFT JOIN position_rates pr ON p.name = pr.position_name
                WHERE p.is_archived = FALSE ORDER BY p.sort, p.name""")
            return [dict(r) for r in cur.fetchall()]


@routes.post('/api/timesheet/settings')
async def handle_timesheet_settings_get(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    settings = await _run(_sync_settings_get, user["user_id"])
    return web.json_response({"settings": settings})


@routes.post('/api/timesheet/settings/save')
async def handle_timesheet_settings_save(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(user):
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"error": "position_rates_retired"}, status=410)


# ===================== ВЫПЛАТЫ =====================
@routes.post('/api/payments/add')
async def handle_payment_add(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    target_uid = _positive_id(body.get("user_id"))
    comment = body.get("comment")
    payment_date = body.get("payment_date")
    try:
        amount = _finite_number(body.get("amount", 0))
        payment_date = date.fromisoformat(payment_date).isoformat() if payment_date else None
    except (ValueError, TypeError):
        return web.json_response({"error": "invalid_data"}, status=400)

    if target_uid <= 0:
        return web.json_response({"error": "Выберите сотрудника"}, status=400)
    if amount <= 0:
        return web.json_response({"error": "Сумма должна быть больше нуля"}, status=400)
    if not isinstance(comment, str) or not comment.strip():
        return web.json_response({"error": "Комментарий обязателен"}, status=400)
    comment = comment.strip()
    if not await _run(_check_can_edit_user, user, target_uid):
        return web.json_response({"error": "forbidden_edit_other"}, status=403)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payments (user_id, amount, comment, created_by, record_type, status, payment_date)
                    VALUES (%s, %s, %s, %s, 'payout', 'approved', COALESCE(%s::date, CURRENT_DATE))
                """, (target_uid, amount, comment, user["user_id"], payment_date))

    await _run(_sync)
    return web.json_response({"ok": True})


# ===================== НАЧИСЛЕНИЯ =====================
@routes.post('/api/accruals/add')
async def handle_accrual_add(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    target_uid = _positive_id(body.get("user_id"))
    comment = body.get("comment")
    payment_date = body.get("payment_date")
    try:
        amount = _finite_number(body.get("amount", 0))
        payment_date = date.fromisoformat(payment_date).isoformat() if payment_date else None
    except (ValueError, TypeError):
        return web.json_response({"error": "invalid_data"}, status=400)

    if target_uid <= 0:
        return web.json_response({"error": "Выберите сотрудника"}, status=400)
    if amount <= 0:
        return web.json_response({"error": "Сумма должна быть больше нуля"}, status=400)
    if not isinstance(comment, str) or not comment.strip():
        return web.json_response({"error": "Комментарий обязателен"}, status=400)
    comment = comment.strip()
    if not await _run(_check_can_edit_user, user, target_uid):
        return web.json_response({"error": "forbidden_edit_other"}, status=403)

    is_hr_or_super = _is_hr_or_super(user)
    status = 'approved' if is_hr_or_super else 'pending'
    proposed_by_name = None if is_hr_or_super else user.get("full_name")

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payments (user_id, amount, comment, created_by, record_type, status, proposed_by_name, payment_date)
                    VALUES (%s, %s, %s, %s, 'accrual', %s, %s, COALESCE(%s::date, CURRENT_DATE))
                """, (target_uid, amount, comment, user["user_id"], status, proposed_by_name, payment_date))

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/accruals/approve')
async def handle_accrual_approve(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(user):
        return web.json_response({"error": "forbidden"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    pid = _positive_id(body.get("id"))
    if pid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE payments SET status='approved', approved_by_name=%s WHERE id=%s",
                    (user.get("full_name"), pid)
                )

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/accruals/reject')
async def handle_accrual_reject(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(user):
        return web.json_response({"error": "forbidden"}, status=403)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    pid = _positive_id(body.get("id"))
    if pid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM payments WHERE id=%s AND status='pending'", (pid,))

    await _run(_sync)
    return web.json_response({"ok": True})


def _sync_employee_payment_summary(user_id, date_from, date_to):
    """Read-only summary scoped to the authenticated employee."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    COALESCE(t.total_hours, 0) AS total_hours,
                    COALESCE(t.timesheet_accrued, 0) AS timesheet_accrued,
                    COALESCE(p.extra_accrued, 0) AS extra_accrued,
                    COALESCE(p.paid, 0) AS paid
                FROM users u
                LEFT JOIN LATERAL (
                    SELECT SUM(s.worked_minutes)::numeric/60 AS total_hours,
                           SUM(s.total_salary) AS timesheet_accrued
                    FROM timesheet_accrual_snapshots s
                    JOIN timesheet_approvals a ON a.restaurant_key=s.restaurant_key
                        AND a.month_start=s.month_start AND a.revision=s.revision
                    WHERE s.user_id=u.user_id AND a.status='approved'
                      AND s.month_start >= %s::date
                      AND s.month_start + INTERVAL '1 month' - INTERVAL '1 day' <= %s::date
                ) t ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        SUM(amount) FILTER (
                            WHERE record_type = 'accrual' AND status = 'approved'
                        ) AS extra_accrued,
                        SUM(amount) FILTER (
                            WHERE record_type = 'payout' AND status = 'approved'
                        ) AS paid
                    FROM payments
                    WHERE user_id = u.user_id
                      AND payment_date BETWEEN %s::date AND %s::date
                ) p ON TRUE
                WHERE u.user_id = %s
            """, (date_from, date_to, date_from, date_to, user_id))
            row = cur.fetchone()
            if row is None:
                return None
            hours = float(row["total_hours"] or 0)
            accrued = float(row["timesheet_accrued"] or 0)
            extra = float(row["extra_accrued"] or 0)
            paid = float(row["paid"] or 0)
            return {
                "total_hours": hours,
                "timesheet_accrued": accrued,
                "extra_accrued": extra,
                "paid": paid,
                "remaining": accrued + extra - paid,
            }


@routes.post('/api/payments/employee')
async def handle_employee_payment_summary(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)
    try:
        date_from, date_to = _date_range(body)
    except (ValueError, TypeError, OverflowError):
        return web.json_response({"error": "invalid_dates"}, status=400)

    # Never trust a client-supplied user_id: employees may only read their own pay.
    summary = await _run(
        _sync_employee_payment_summary, user["user_id"], date_from, date_to
    )
    if summary is None:
        return web.json_response({"error": "user_not_found"}, status=404)
    return web.json_response(summary)


def _snapshot_approved_accruals(cur, key, month, revision):
    """Capture the monthly payroll using the approval transaction's cursor."""
    cur.execute("WITH effective AS (" + _EFFECTIVE_ATTENDANCE_SQL + """),
        monthly AS (
            SELECT e.user_id, COALESCE(e.restaurant_key,u.restaurant_key) AS restaurant_key,
                   ROUND(SUM(e.hours)*60)::integer AS minutes
            FROM effective e JOIN users u ON u.user_id=e.user_id
            WHERE e.work_date >= %s::date AND e.work_date < %s::date + INTERVAL '1 month'
            GROUP BY e.user_id, COALESCE(e.restaurant_key,u.restaurant_key)
        ), candidates AS (
            SELECT u.user_id,u.full_name,u.position,u.payment_type,
                   COALESCE(ir.hourly_rate, 0) AS rate,
                   COALESCE(m.restaurant_key,u.restaurant_key) AS restaurant_key,
                   COALESCE(m.minutes,0) AS minutes
            FROM users u LEFT JOIN monthly m ON m.user_id=u.user_id
                LEFT JOIN timesheet_individual_rates ir ON ir.user_id=u.user_id
            WHERE u.login IS NOT NULL AND COALESCE(u.is_fired,FALSE)=FALSE
        )
        , captured AS (
        INSERT INTO timesheet_accrual_snapshots
            (restaurant_key,month_start,revision,user_id,full_name,position,restaurant_name,payment_type,rate,worked_minutes,total_salary)
        SELECT c.restaurant_key,%s,%s,c.user_id,c.full_name,c.position,r.name,c.payment_type,c.rate,c.minutes,
               ROUND(c.minutes::numeric*c.rate/60,2)
        FROM candidates c JOIN restaurants r ON r.key=c.restaurant_key
        WHERE c.restaurant_key=%s
        RETURNING restaurant_key,month_start,revision,user_id,rate
        ),
        daily AS (
            SELECT s.restaurant_key,s.month_start,s.revision,s.user_id,e.work_date,
                   ROUND(SUM(e.hours)*60)::integer AS minutes,s.rate
            FROM captured s
            JOIN users u ON u.user_id=s.user_id
            JOIN effective e ON e.user_id=s.user_id
                AND COALESCE(e.restaurant_key,u.restaurant_key)=s.restaurant_key
            WHERE e.work_date>=s.month_start AND e.work_date<s.month_start+INTERVAL '1 month'
            GROUP BY s.restaurant_key,s.month_start,s.revision,s.user_id,e.work_date,s.rate
        ), cumulative AS (
            SELECT *, SUM(minutes) OVER (PARTITION BY restaurant_key,month_start,revision,user_id
                ORDER BY work_date ROWS UNBOUNDED PRECEDING) AS running_minutes
            FROM daily
        )
        INSERT INTO timesheet_accrual_snapshot_days
            (restaurant_key,month_start,revision,user_id,work_date,worked_minutes,total_salary)
        SELECT restaurant_key,month_start,revision,user_id,work_date,minutes,
               ROUND(running_minutes*rate/60,2)-ROUND((running_minutes-minutes)*rate/60,2)
        FROM cumulative""", (month,month,month,revision,key))



def _can_approve_timesheet(user):
    return _is_hr_or_super(user) and _is_hr_position(user.get("position"))


def _sync_approval_transition(user, key, month, action, comment, revision):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            cur.execute("SELECT territory_manager_id FROM restaurants WHERE key=%s", (key,))
            restaurant = cur.fetchone()
            if not restaurant or not _timesheet_role_allowed(user):
                return 403, {"error": "forbidden"}
            privileged = _is_hr_or_super(user)
            if action == "approve" and not _can_approve_timesheet(user):
                return 403, {"error": "forbidden"}
            if not privileged and (restaurant["territory_manager_id"] != user["user_id"] or action != "submit"):
                return 403, {"error": "forbidden"}
            cur.execute("INSERT INTO timesheet_approvals(restaurant_key,month_start) VALUES (%s,%s) ON CONFLICT DO NOTHING", (key,month))
            cur.execute("SELECT status,revision FROM timesheet_approvals WHERE restaurant_key=%s AND month_start=%s FOR UPDATE", (key,month))
            row = cur.fetchone()
            transitions = {("draft","submit"):"pending", ("returned","submit"):"pending",
                           ("pending","approve"):"approved", ("pending","return"):"returned",
                           ("approved","reopen"):"returned"}
            target = transitions.get((row["status"],action))
            if not target or revision != row["revision"]:
                return 409, {"error":"approval_conflict"}
            if target == "approved":
                cur.execute("WITH effective AS (" + _EFFECTIVE_ATTENDANCE_SQL + """)
                    SELECT DISTINCT u.user_id,u.full_name
                    FROM effective e JOIN users u ON u.user_id=e.user_id
                    LEFT JOIN timesheet_individual_rates ir ON ir.user_id=u.user_id
                    WHERE COALESCE(e.restaurant_key,u.restaurant_key)=%s
                      AND e.work_date >= %s::date
                      AND e.work_date < %s::date + INTERVAL '1 month'
                      AND e.hours > 0 AND ir.user_id IS NULL
                    ORDER BY u.full_name,u.user_id""", (key,month,month))
                missing = [dict(item) for item in cur.fetchall()]
                if missing:
                    return 409, {"error":"missing_hourly_rates","employees":missing}
            next_revision = revision + 1
            cur.execute("UPDATE timesheet_approvals SET status=%s,revision=%s,updated_by=%s,updated_at=NOW() WHERE restaurant_key=%s AND month_start=%s",
                        (target,next_revision,user["user_id"],key,month))
            cur.execute("INSERT INTO timesheet_approval_history(restaurant_key,month_start,revision,previous_status,new_status,actor_id,comment) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (key,month,next_revision,row["status"],target,user["user_id"],comment))
            if target == "approved":
                _snapshot_approved_accruals(cur,key,month,next_revision)
            return 200, {"status":target,"revision":next_revision}


@routes.post('/api/timesheet/approval/transition')
async def handle_approval_transition(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
        key, action = body["restaurant_key"], body["action"]
        month = date.fromisoformat(body["month_start"])
        revision = body["revision"]
        comment = body.get("comment", "")
        if not isinstance(key,str) or not key or len(key)>255 or month.day != 1:
            raise ValueError()
        if action not in ("submit","approve","return","reopen") or type(revision) is not int or not 0 <= revision < 2147483647:
            raise ValueError()
        if not isinstance(comment,str) or len(comment)>2000 or (action in ("return","reopen") and not comment.strip()):
            raise ValueError()
    except (ValueError, TypeError, KeyError, OverflowError):
        return web.json_response({"error":"invalid_approval"},status=400)
    status, result = await _run(_sync_approval_transition,user,key,month,action,comment.strip(),revision)
    return web.json_response(result,status=status,headers={"Cache-Control":"no-store"})



def _sync_approval_status(user, key, month):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT territory_manager_id FROM restaurants WHERE key=%s", (key,))
            restaurant = cur.fetchone()
            if not restaurant or not _timesheet_role_allowed(user):
                return None
            privileged = _is_hr_or_super(user)
            if not privileged and restaurant["territory_manager_id"] != user["user_id"]:
                return None
            cur.execute("SELECT status,revision FROM timesheet_approvals WHERE restaurant_key=%s AND month_start=%s", (key,month))
            row = cur.fetchone() or {"status":"draft","revision":0}
            cur.execute("""SELECT h.revision,h.previous_status,h.new_status,h.comment,
                           h.created_at::text AS created_at,u.full_name AS actor_name
                           FROM timesheet_approval_history h LEFT JOIN users u ON u.user_id=h.actor_id
                           WHERE h.restaurant_key=%s AND h.month_start=%s AND h.revision<=%s
                           ORDER BY h.revision DESC""", (key,month,row["revision"]))
            return {**row,"can_review":privileged,"can_approve":_can_approve_timesheet(user),"history":[dict(h) for h in cur.fetchall()]}


@routes.post('/api/timesheet/approval/status')
async def handle_approval_status(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
        key = body["restaurant_key"]
        month = date.fromisoformat(body["month_start"])
        if not isinstance(key,str) or not key or len(key)>255 or month.day != 1:
            raise ValueError()
    except (ValueError,TypeError,KeyError,OverflowError):
        return web.json_response({"error":"invalid_approval"},status=400)
    result = await _run(_sync_approval_status,user,key,month)
    if result is None:
        return denied(403)
    return web.json_response(result,headers={"Cache-Control":"no-store"})


# Individual hourly rates: HR and super administrators may write.
def _can_set_individual_rate(user):
    return bool(user and not user.get("is_fired") and _is_hr_or_super(user))


def _sync_set_individual_rate(actor, target, rate):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            cur.execute("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (actor,))
            if not _can_set_individual_rate(cur.fetchone()):
                return 403
            cur.execute("SELECT user_id FROM users WHERE user_id=%s AND NOT COALESCE(is_fired,FALSE) FOR UPDATE", (target,))
            if not cur.fetchone():
                return 404
            cur.execute("SELECT hourly_rate FROM timesheet_individual_rates WHERE user_id=%s FOR UPDATE", (target,))
            old = cur.fetchone()
            previous = old["hourly_rate"] if old else None
            if previous == rate:
                return 200
            cur.execute("""INSERT INTO timesheet_individual_rates(user_id,hourly_rate,updated_by)
                VALUES (%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET
                hourly_rate=EXCLUDED.hourly_rate, updated_by=EXCLUDED.updated_by,
                revision=timesheet_individual_rates.revision+1, updated_at=NOW()""", (target,rate,actor))
            cur.execute("""INSERT INTO timesheet_rate_history(user_id,previous_rate,new_rate,actor_id)
                VALUES (%s,%s,%s,%s)""", (target,previous,rate,actor))
            cur.execute("""UPDATE timesheet_rate_requests SET status='rejected',
                decided_by=%s,decided_at=NOW(),
                decision_comment='Ставка изменена напрямую. Создайте новый запрос.'
                WHERE user_id=%s AND status='pending'""",(actor,target))
            return 200


@routes.post('/api/timesheet/individual-rate')
async def handle_individual_rate(request):
    from decimal import Decimal, InvalidOperation
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not _can_set_individual_rate(user):
        return denied(403)
    try:
        data = await request.json()
        target = data["user_id"]
        raw = data["hourly_rate"]
        if type(target) is not int or not 0 < target < 2**63 or type(raw) not in (str,int,float):
            raise ValueError()
        rate = Decimal(str(raw))
        if not rate.is_finite() or not 0 <= rate <= Decimal("9999999999.99") or rate != rate.quantize(Decimal("0.01")):
            raise ValueError()
    except (ValueError, TypeError, KeyError, InvalidOperation):
        return web.json_response({"error":"Некорректная ставка"}, status=400)
    status = await _run(_sync_set_individual_rate, user["user_id"], target, rate)
    return web.json_response({"ok":status == 200}, status=status, headers={"Cache-Control":"no-store"})


def _sync_create_rate_request(actor, target, rate, reason):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            cur.execute("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (actor,))
            user = cur.fetchone()
            if not user or user.get("is_fired") or not (_is_tu(user) or user.get("is_super_admin")):
                return 403
            cur.execute("""SELECT u.user_id,r.territory_manager_id FROM users u
                LEFT JOIN restaurants r ON r.key=u.restaurant_key
                WHERE u.user_id=%s AND NOT COALESCE(u.is_fired,FALSE) FOR UPDATE OF u""", (target,))
            employee = cur.fetchone()
            if not employee or (not user.get("is_super_admin") and employee["territory_manager_id"] != actor):
                return 404
            cur.execute("""INSERT INTO timesheet_rate_requests(user_id,requested_by,proposed_rate,reason)
                VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) WHERE status='pending'
                DO NOTHING RETURNING id""", (target,actor,rate,reason))
            return 201 if cur.fetchone() else 409


@routes.post('/api/timesheet/rate-requests')
async def handle_create_rate_request(request):
    from decimal import Decimal, InvalidOperation
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not (_is_tu(user) or user.get("is_super_admin")):
        return denied(403)
    try:
        data = await request.json()
        target, raw, reason = data["user_id"], data["proposed_rate"], data["reason"]
        if type(target) is not int or not 0 < target < 2**63 or type(raw) not in (str,int,float):
            raise ValueError()
        if not isinstance(reason,str) or not 1 <= len(reason.strip()) <= 2000:
            raise ValueError()
        rate = Decimal(str(raw))
        if not rate.is_finite() or not 0 <= rate <= Decimal("9999999999.99") or rate != rate.quantize(Decimal("0.01")):
            raise ValueError()
    except (ValueError, TypeError, KeyError, InvalidOperation):
        return web.json_response({"error":"Некорректный запрос"}, status=400)
    status = await _run(_sync_create_rate_request,user["user_id"],target,rate,reason.strip())
    return web.json_response({"ok":status == 201},status=status,headers={"Cache-Control":"no-store"})


def _sync_decide_rate_request(actor, request_id, decision, comment):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(814726, 2)")
            cur.execute("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (actor,))
            if not _can_set_individual_rate(cur.fetchone()):
                return 403
            cur.execute("SELECT user_id FROM timesheet_rate_requests WHERE id=%s", (request_id,))
            target = cur.fetchone()
            if not target:
                return 404
            cur.execute("SELECT user_id,is_fired FROM users WHERE user_id=%s FOR UPDATE", (target["user_id"],))
            employee = cur.fetchone()
            cur.execute("SELECT * FROM timesheet_rate_requests WHERE id=%s FOR UPDATE", (request_id,))
            pending = cur.fetchone()
            if not pending:
                return 404
            if pending["status"] != "pending":
                return 409
            if decision == "approved":
                if not employee or employee["is_fired"]:
                    return 409
                cur.execute("SELECT hourly_rate FROM timesheet_individual_rates WHERE user_id=%s FOR UPDATE", (pending["user_id"],))
                old = cur.fetchone()
                previous = old["hourly_rate"] if old else None
                rate = pending["proposed_rate"]
                if previous != rate:
                    cur.execute("""INSERT INTO timesheet_individual_rates(user_id,hourly_rate,updated_by)
                        VALUES (%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET
                        hourly_rate=EXCLUDED.hourly_rate,updated_by=EXCLUDED.updated_by,
                        revision=timesheet_individual_rates.revision+1,updated_at=NOW()""",
                        (pending["user_id"],rate,actor))
                    cur.execute("""INSERT INTO timesheet_rate_history(user_id,previous_rate,new_rate,actor_id,request_id)
                        VALUES (%s,%s,%s,%s,%s)""",(pending["user_id"],previous,rate,actor,request_id))
            cur.execute("""UPDATE timesheet_rate_requests SET status=%s,decided_by=%s,
                decided_at=NOW(),decision_comment=%s WHERE id=%s""",(decision,actor,comment,request_id))
            return 200


@routes.post('/api/timesheet/rate-requests/{request_id}/decision')
async def handle_decide_rate_request(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    if not _can_set_individual_rate(user):
        return denied(403)
    try:
        request_id = int(request.match_info["request_id"])
        data = await request.json()
        decision = data["decision"]
        comment = data.get("comment","")
        if not 0 < request_id < 2**63 or decision not in ("approved","rejected"):
            raise ValueError()
        if not isinstance(comment,str) or len(comment.strip()) > 2000:
            raise ValueError()
        if decision == "rejected" and not comment.strip():
            raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError):
        return web.json_response({"error":"Некорректное решение"},status=400)
    status = await _run(_sync_decide_rate_request,user["user_id"],request_id,decision,comment.strip())
    return web.json_response({"ok":status == 200},status=status,headers={"Cache-Control":"no-store"})


def _sync_rate_records(actor, kind):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (actor,))
            user = cur.fetchone()
            if not user or user.get("is_fired") or not (_can_set_individual_rate(user) or _is_tu(user)):
                return None
            if kind == "requests":
                sql = """SELECT q.id,q.user_id,u.full_name,u.restaurant_key,
                    q.proposed_rate::text AS proposed_rate,q.reason,q.status,
                    q.requested_by,q.created_at::text AS created_at,q.decided_by,
                    q.decided_at::text AS decided_at,q.decision_comment,
                    ir.hourly_rate::text AS current_rate
                    FROM timesheet_rate_requests q JOIN users u ON u.user_id=q.user_id
                    LEFT JOIN timesheet_individual_rates ir ON ir.user_id=u.user_id
                    LEFT JOIN restaurants r ON r.key=u.restaurant_key"""
                order = " ORDER BY (q.status='pending') DESC,q.id DESC"
            else:
                sql = """SELECT h.id,h.user_id,u.full_name,u.restaurant_key,
                    h.previous_rate::text AS previous_rate,h.new_rate::text AS new_rate,
                    h.actor_id,h.request_id,h.created_at::text AS created_at
                    FROM timesheet_rate_history h JOIN users u ON u.user_id=h.user_id
                    LEFT JOIN restaurants r ON r.key=u.restaurant_key"""
                order = " ORDER BY h.id DESC"
            params = []
            if not _can_set_individual_rate(user):
                sql += " WHERE r.territory_manager_id=%s"
                params.append(actor)
            cur.execute(sql + order + " LIMIT 500", params)
            return [dict(row) for row in cur.fetchall()]


@routes.get('/api/timesheet/rate-requests')
@routes.get('/api/timesheet/rate-history')
async def handle_rate_records(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    kind = "requests" if request.path.endswith("/rate-requests") else "history"
    rows = await _run(_sync_rate_records,user["user_id"],kind)
    if rows is None:
        return denied(403)
    return web.json_response({kind:rows},headers={"Cache-Control":"no-store"})


def _sync_rate_employees(actor):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id=%s", (actor,))
            user = cur.fetchone()
            manage = _can_set_individual_rate(user)
            if not user or user.get("is_fired") or not (manage or _is_tu(user)):
                return None
            sql = """SELECT u.user_id,u.full_name,u.position,u.restaurant_key,
                r.name AS restaurant_name,u.payment_type,
                ir.hourly_rate::text AS individual_rate,
                COALESCE(ir.hourly_rate, 0)::text AS rate
                FROM users u LEFT JOIN restaurants r ON r.key=u.restaurant_key
                LEFT JOIN timesheet_individual_rates ir ON ir.user_id=u.user_id
                WHERE NOT COALESCE(u.is_fired,FALSE) AND u.login IS NOT NULL"""
            params = []
            if not manage:
                sql += " AND r.territory_manager_id=%s"
                params.append(actor)
            cur.execute(sql+" ORDER BY r.name,u.full_name,u.user_id",params)
            return {"employees":[dict(row) for row in cur.fetchall()],
                    "can_manage":manage,"can_request":bool(_is_tu(user) or user.get("is_super_admin"))}


@routes.get('/api/timesheet/rate-employees')
async def handle_rate_employees(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    result = await _run(_sync_rate_employees,user["user_id"])
    if result is None:
        return denied(403)
    return web.json_response(result,headers={"Cache-Control":"no-store"})
