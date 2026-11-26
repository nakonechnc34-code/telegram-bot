from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, denied, _is_hr_or_super, _is_tu, _sync_user_has_perm, _sync_get_tu_rests
import calendar
from datetime import datetime, date, time
import io
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

def _private_guest(user):
    return (user.get("position") or "").strip().casefold() == "тайный гость"


def _session_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def _sync_timesheet_session(token):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT u.* FROM timesheet_sessions s JOIN users u ON u.user_id=s.user_id WHERE s.token_hash=%s AND s.expires_at>NOW()", (_session_hash(token),))
            return cur.fetchone()

async def _timesheet_user(request):
    token = await _extract_token(request, allow_query=False)
    user = await _run(_sync_timesheet_session, token) if token else None
    if not user:
        return None, 401
    if user.get("is_fired") or _private_guest(user) or not _sync_user_has_perm(user, "timesheet_access"):
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
    if user.get("is_fired") or _private_guest(user) or not _sync_user_has_perm(user,"timesheet_access"):
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
    if _private_guest(editor_user):
        return False
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
            cur.execute("SELECT restaurant_key, position FROM users WHERE user_id = %s", (target_uid,))
            target = cur.fetchone()
            if not target or _private_guest(target):
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


@routes.post('/api/timesheet/restaurants')
async def handle_timesheet_restaurants(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if "управляющий сменой" in (user.get("position") or "").lower():
                    cur.execute("SELECT key, name FROM restaurants WHERE key = %s", (user.get("restaurant_key"),))
                else:
                    cur.execute("SELECT key, name FROM restaurants ORDER BY name")
                return [dict(r) for r in cur.fetchall()]

    rests = await _run(_sync)
    return web.json_response({"restaurants": rests})


def _sync_timesheet_matrix(user_id, date_from, date_to):
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
                       COALESCE(NULLIF(u.rate, 0), pr.rate, 0) AS rate, u.payment_type, r.name AS restaurant_name
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN position_rates pr ON u.position = pr.position_name
                WHERE COALESCE(u.is_fired, FALSE) = FALSE
                  AND COALESCE(u.is_admin, FALSE) = FALSE
                  AND u.login IS NOT NULL
                  AND COALESCE(u.payment_type, '') != 'fixed' """
            params = []
            if not is_hr_or_super:
                query += " AND lower(btrim(COALESCE(u.position, ''))) <> 'тайный гость'"
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
                   WHERE user_id = ANY(%s) AND work_date >= %s::date AND work_date <= %s::date""",
                (emp_ids, date_from, date_to)
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
            for e in employees:
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

    employees = await _run(_sync_timesheet_matrix, user["user_id"], date_from, date_to)
    return web.json_response({"employees": employees})


def _sync_save_cell(user_id, target_uid, work_date, hours, status, restaurant_key=None, start_time=None, end_time=None):
    hours = round(hours, 2)
    with get_conn() as conn:
        with conn.cursor() as cur:
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

    await _run(_sync_save_cell, user["user_id"], target_uid, work_date, hours, status, restaurant_key, start_time, end_time)
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
                  AND (%s OR lower(btrim(COALESCE(position, ''))) <> 'тайный гость')
            """, (_is_hr_or_super(user),))
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
    rows = list(ws.iter_rows(values_only=True))

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


@routes.post('/api/timesheet/import_attendance')
async def handle_import_attendance(request):
    user, err = await _timesheet_user(request)
    if err:
        return denied(err)
    _require_timesheet_access(user)

    reader = await request.multipart()
    file_data = None
    default_rest = request.query.get("restaurant_key")

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == 'file':
            file_data = bytearray()
            while chunk := await part.read_chunk():
                file_data.extend(chunk)
                if request.client_max_size and len(file_data) > request.client_max_size:
                    return web.json_response({"error": "Файл слишком большой"}, status=413)
            break

    if not file_data:
        return web.json_response({"error": "Файл не загружен"}, status=400)

    try:
        rows = await _run(_parse_excel_rows, file_data)
    except Exception:
        return web.json_response({"error": "Не удалось прочитать Excel"}, status=400)

    success, errors = await _run(_sync_import_attendance, user, rows, default_rest)
    return web.json_response({"ok": True, "success_count": success, "errors": errors})


# ИСПРАВЛЕНО: добавлен флаг only_me и LEFT JOIN для корректной работы сотрудников без часов
def _sync_reports(user_id, date_from, date_to, only_me=False):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            is_hr_or_super = _is_hr_or_super(u)
            is_tu = _is_tu(u)
            is_us = "управляющий сменой" in (u.get("position") or "").lower()

            base = """SELECT u.full_name, u.position,
                       COALESCE(tr.name, r.name) AS restaurant_name,
                       COALESCE(SUM(t.hours), 0) as total_hours,
                       COALESCE(NULLIF(u.rate, 0), pr.rate, 0) AS rate, u.payment_type,
                       CASE WHEN u.payment_type = 'fixed' THEN COALESCE(NULLIF(u.rate, 0), pr.rate, 0)
                            ELSE (COALESCE(SUM(t.hours), 0) * COALESCE(NULLIF(u.rate, 0), pr.rate, 0)) END as total_salary
                FROM users u 
                LEFT JOIN timesheet_records t ON u.user_id = t.user_id AND t.work_date >= %s::date AND t.work_date <= %s::date
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN restaurants tr ON t.restaurant_key = tr.key
                LEFT JOIN position_rates pr ON u.position = pr.position_name
                WHERE COALESCE(u.is_fired, FALSE) = FALSE AND u.login IS NOT NULL"""
            
            params = [date_from, date_to]
            if not is_hr_or_super:
                base += " AND lower(btrim(COALESCE(u.position, ''))) <> 'тайный гость'"
            
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
                
            base += " GROUP BY u.user_id, u.full_name, u.position, COALESCE(tr.name, r.name), u.rate, pr.rate, u.payment_type ORDER BY COALESCE(tr.name, r.name), u.full_name"

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
    report = await _run(_sync_reports, user["user_id"], date_from, date_to, True)
    return web.json_response({"report": report})


@routes.get('/api/timesheet/export_excel')
async def handle_timesheet_export_excel(request):
    user, err = await _timesheet_user(request)
    if err and request.query.get("only_me") == "true":
        user, err = await get_auth_user(request)
    if err:
        return denied(err)
    # ИСПРАВЛЕНО: убрали _require_timesheet_access(user)

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
    report = await _run(_sync_reports, user["user_id"], date_from, date_to, only_me)

    wb = Workbook()
    ws = wb.active
    ws.title = "Табель"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1C1C1E", end_color="1C1C1E", fill_type="solid")
    border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    center_align = Alignment(horizontal="center", vertical="center")

    headers = ["Сотрудник", "Должность", "Ресторан", "Часов", "Ставка (₽)", "К оплате (₽)"]
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
            "Оклад" if r.get("payment_type") == 'fixed' else float(r.get("rate", 0)),
            float(r.get("total_salary", 0)),
        ]
        ws.append(row_data)
        current_row = ws.max_row
        for col_num in range(1, 7):
            cell = ws.cell(row=current_row, column=col_num)
            cell.border = border
            if col_num >= 4:
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
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "invalid_json"}, status=400)

    position_name = body.get("position_name")
    if not isinstance(position_name, str) or not position_name.strip():
        return web.json_response({"error": "invalid_position"}, status=400)

    position_name = position_name.strip()
    try:
        rate = _finite_number(body.get("rate", 0))
        if rate < 0:
            raise ValueError("invalid rate")
    except ValueError:
        return web.json_response({"error": "invalid_rate"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO position_rates (position_name, rate) VALUES (%s, %s)
                       ON CONFLICT (position_name) DO UPDATE SET rate = EXCLUDED.rate""",
                    (position_name, rate)
                )

    await _run(_sync)
    return web.json_response({"ok": True})


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
                    CASE WHEN u.payment_type = 'fixed'
                         THEN COALESCE(NULLIF(u.rate, 0), pr.rate, 0)
                         ELSE COALESCE(t.total_hours, 0) *
                              COALESCE(NULLIF(u.rate, 0), pr.rate, 0)
                    END AS timesheet_accrued,
                    COALESCE(p.extra_accrued, 0) AS extra_accrued,
                    COALESCE(p.paid, 0) AS paid
                FROM users u
                LEFT JOIN position_rates pr ON pr.position_name = u.position
                LEFT JOIN LATERAL (
                    SELECT SUM(hours) AS total_hours
                    FROM timesheet_records
                    WHERE user_id = u.user_id
                      AND work_date BETWEEN %s::date AND %s::date
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
    if _private_guest(user):
        return web.json_response({"error": "forbidden"}, status=403)
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
