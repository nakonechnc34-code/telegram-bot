from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, denied, _is_hr_or_super, _is_tu, _sync_user_has_perm
import calendar
from datetime import datetime, date, time
import io
import traceback
import logging
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

routes = web.RouteTableDef()

def _safe_int(val, default=0):
    try: return int(val)
    except: return default

def _safe_float(val, default=0.0):
    try: return float(val)
    except: return default

def _require_timesheet_access(user):
    if not _sync_user_has_perm(user, "timesheet_access"):
        raise web.HTTPForbidden(text='{"error": "forbidden"}', content_type='application/json')

def _check_can_edit_user(editor_user, target_uid):
    if editor_user["is_super_admin"] or (editor_user.get("position") or "").strip().upper() == "HR": 
        return True
    if editor_user["user_id"] == target_uid: 
        return True
    pos_lower = (editor_user.get("position") or "").lower()
    is_tu = "территориальный" in pos_lower
    is_us = "управляющий сменой" in pos_lower
    if not (is_tu or is_us): return False
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT restaurant_key FROM users WHERE user_id = %s", (target_uid,))
            target = cur.fetchone()
            if not target: return False
            if is_us: return target["restaurant_key"] == editor_user.get("restaurant_key")
            elif is_tu:
                cur.execute("SELECT key FROM restaurants WHERE territory_manager_id = %s AND key = %s", (editor_user["user_id"], target["restaurant_key"]))
                return cur.fetchone() is not None
    return False

# Автоматически добавляем колонки для времени, если их нет
def _ensure_timesheet_schema():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE timesheet_records ADD COLUMN IF NOT EXISTS start_time TIME")
            cur.execute("ALTER TABLE timesheet_records ADD COLUMN IF NOT EXISTS end_time TIME")

@routes.post('/api/timesheet/restaurants')
async def handle_timesheet_restaurants(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
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
    _ensure_timesheet_schema()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u: return []
            
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
            if is_us:
                query += " AND u.restaurant_key = %s"; params.append(u.get("restaurant_key"))
            elif is_tu:
                query += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"; params.append(user_id)
            elif not is_hr_or_super:
                query += " AND u.user_id = %s"; params.append(user_id)
            query += " ORDER BY r.name, u.full_name"
            
            cur.execute(query, params)
            employees = [dict(r) for r in cur.fetchall()]
            if not employees: return []
            
            emp_ids = [e["user_id"] for e in employees]
            cur.execute("""SELECT user_id, work_date, hours, status, restaurant_key, 
                                  to_char(start_time, 'HH24:MI') as st, to_char(end_time, 'HH24:MI') as et 
                           FROM timesheet_records 
                           WHERE user_id = ANY(%s) AND work_date >= %s::date AND work_date <= %s::date""", 
                        (emp_ids, date_from, date_to))
            records = cur.fetchall()
            
            data_map = {eid: {} for eid in emp_ids}
            for r in records:
                data_map[r["user_id"]][str(r["work_date"].day)] = {
                    "h": float(r["hours"] or 0), 
                    "s": r["status"] or "work",
                    "rk": r["restaurant_key"],
                    "st": r["st"] or "",
                    "et": r["et"] or ""
                }
            for e in employees:
                e["data"] = data_map[e["user_id"]]
            return employees

@routes.post('/api/timesheet/matrix')
async def handle_timesheet_matrix(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    _require_timesheet_access(user)

    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    if not date_from or not date_to:
        month = _safe_int(body.get("month", datetime.now().month))
        year = _safe_int(body.get("year", datetime.now().year))
        last_day = calendar.monthrange(year, month)[1]
        date_from = f"{year}-{month:02d}-01"
        date_to = f"{year}-{month:02d}-{last_day:02d}"
        
    employees = await _run(_sync_timesheet_matrix, user["user_id"], date_from, date_to)
    return web.json_response({"employees": employees})

def _sync_save_cell(user_id, target_uid, work_date, hours, status, restaurant_key=None, start_time=None, end_time=None):
    _ensure_timesheet_schema()
    hours = round(hours, 2)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            if hours <= 0 and status == 'work':
                cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s", (target_uid, work_date))
            else:
                cur.execute("""INSERT INTO timesheet_records (user_id, work_date, hours, status, restaurant_key, start_time, end_time, updated_at) 
                    VALUES (%s, %s, %s, %s, %s, %s::time, %s::time, NOW())
                    ON CONFLICT (user_id, work_date) DO UPDATE SET 
                        hours = EXCLUDED.hours, status = EXCLUDED.status, 
                        restaurant_key = EXCLUDED.restaurant_key, 
                        start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time, updated_at = NOW()""", 
                    (target_uid, work_date, hours, status, restaurant_key, start_time or None, end_time or None))

@routes.post('/api/timesheet/save_cell')
async def handle_timesheet_save_cell(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    _require_timesheet_access(user)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    target_uid = _safe_int(body.get("user_id"))
    work_date = body.get("work_date")
    hours = _safe_float(body.get("hours", 0))
    status = body.get("status", "work")
    restaurant_key = body.get("restaurant_key") 
    start_time = body.get("start_time")
    end_time = body.get("end_time")
    
    if not work_date or target_uid <= 0: return web.json_response({"error": "invalid_data"}, status=400)
    allowed = await _run(_check_can_edit_user, user, target_uid)
    if not allowed: return web.json_response({"error": "forbidden_edit_other"}, status=403)
    
    await _run(_sync_save_cell, user["user_id"], target_uid, work_date, hours, status, restaurant_key, start_time, end_time)
    return web.json_response({"ok": True})

def _parse_date(val):
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try: return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except: pass
    return None

def _sync_import_attendance(user_id, rows, default_rest_key=None):
    _ensure_timesheet_schema()
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
            
            cur.execute("SELECT key, name FROM restaurants")
            restaurants = cur.fetchall()
            rest_map = {r["name"].strip().lower(): r["key"] for r in restaurants}
            
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
                        
                    hours = 0
                    status = 'work'
                    start_time = None
                    end_time = None
                    
                    if raw_val in ('В', 'Б', 'Н'):
                        status = {'В': 'vacation', 'Б': 'sick', 'Н': 'absent'}[raw_val]
                        hours = 8 if status in ('vacation', 'sick') else 0
                    elif '-' in raw_val:
                        # Обработка формата "9:30-22:01"
                        parts = raw_val.split('-')
                        st_str = parts[0].strip()
                        et_str = parts[1].strip()
                        try:
                            sh, sm = map(int, st_str.split(':'))
                            eh, em = map(int, et_str.split(':'))
                            start_min = sh * 60 + sm
                            end_min = eh * 60 + em
                            if end_min < start_min: end_min += 24 * 60
                            hours = round((end_min - start_min) / 60.0, 2)
                            start_time = f"{sh:02d}:{sm:02d}:00"
                            end_time = f"{eh:02d}:{em:02d}:00"
                        except:
                            continue
                    else:
                        try: 
                            if ':' in raw_val:
                                parts = raw_val.split(':')
                                hours = float(parts[0]) + float(parts[1])/60.0
                            else:
                                hours = float(raw_val.replace(',', '.'))
                            hours = round(hours, 2)
                        except: 
                            continue
                        
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
                    
                    if hours <= 0 and status == 'work':
                        cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s", (target_user["user_id"], date_str))
                    else:
                        cur.execute("""INSERT INTO timesheet_records (user_id, work_date, hours, status, restaurant_key, start_time, end_time, updated_at) 
                            VALUES (%s, %s, %s, %s, %s, %s::time, %s::time, NOW())
                            ON CONFLICT (user_id, work_date) DO UPDATE SET 
                                hours = EXCLUDED.hours, status = EXCLUDED.status, 
                                restaurant_key = EXCLUDED.restaurant_key, 
                                start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time, updated_at = NOW()""", 
                            (target_user["user_id"], date_str, hours, status, r_key, start_time, end_time))
                    success += 1
                except Exception as e:
                    errors.append(f"Ошибка в строке {row}: {str(e)}")
                    
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
        if not cell_val: continue
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
    
    for row in rows[header_idx+1:]:
        if not row: continue
        
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
        if not has_data: continue
        
        for col_idx, date_str in date_cols.items():
            if col_idx < len(row) and row[col_idx] is not None:
                cell_val = row[col_idx]
                
                if isinstance(cell_val, time):
                    raw_val = f"{cell_val.hour}:{cell_val.minute:02d}"
                elif isinstance(cell_val, (float, int)):
                    raw_val = str(cell_val)
                else:
                    raw_val = str(cell_val).strip()
                    
                if not raw_val or raw_val.upper() == 'NONE': continue
                parsed_data.append((date_str, current_pers_num, raw_val.upper(), rest_name))
                
    return parsed_data

@routes.post('/api/timesheet/import_attendance')
async def handle_import_attendance(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    _require_timesheet_access(user)
    
    reader = await request.multipart()
    file_data = None
    default_rest = request.query.get("restaurant_key")
    
    while True:
        part = await reader.next()
        if part is None: break
        if part.name == 'file':
            file_data = await part.read()
            break

    if not file_data: 
        return web.json_response({"error": "Файл не загружен"}, status=400)

    try:
        rows = await _run(_parse_excel_rows, file_data)
    except Exception as e:
        return web.json_response({"error": f"Не удалось прочитать Excel: {str(e)}"}, status=400)

    success, errors = await _run(_sync_import_attendance, user["user_id"], rows, default_rest)
    return web.json_response({"ok": True, "success_count": success, "errors": errors})

# ... (функции _sync_reports, экспорт, настройки и выплаты остаются без изменений) ...

# Для краткости оставляю остальные функции (reports, export, payments) как были в предыдущей версии.
# Если нужно, могу прислать их снова, но они не меняются.
