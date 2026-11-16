from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, denied, _is_hr_or_super, _is_tu, _sync_user_has_perm
import calendar
from datetime import datetime, date
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

# ... (Роуты restaurants, matrix, save_cell остаются без изменений, они безопасны) ...

@routes.post('/api/timesheet/save_cell')
async def handle_timesheet_save_cell(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    _require_timesheet_access(user)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    target_uid = _safe_int(body.get("user_id"))
    work_date = body.get("work_date")
    hours = _safe_float(body.get("hours", 0)) # ИСПРАВЛЕНО: безопасный float
    status = body.get("status", "work")
    restaurant_key = body.get("restaurant_key") 
    
    if not work_date or target_uid <= 0: return web.json_response({"error": "invalid_data"}, status=400)
    allowed = await _run(_check_can_edit_user, user, target_uid)
    if not allowed: return web.json_response({"error": "forbidden_edit_other"}, status=403)
    
    await _run(_sync_save_cell, user["user_id"], target_uid, work_date, hours, status, restaurant_key)
    return web.json_response({"ok": True})

# ИСПРАВЛЕНО: Парсинг Excel вынесен в отдельный поток!
def _parse_excel_rows(file_data):
    wb = load_workbook(filename=io.BytesIO(file_data), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    return rows[1:] if len(rows) > 1 else []

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
        # ИСПРАВЛЕНО: Вызов в отдельном потоке
        rows = await _run(_parse_excel_rows, file_data)
    except Exception as e:
        return web.json_response({"error": f"Не удалось прочитать Excel: {str(e)}"}, status=400)

    success, errors = await _run(_sync_import_attendance, user["user_id"], rows, default_rest)
    return web.json_response({"ok": True, "success_count": success, "errors": errors})
# ... (Остальной код без изменений)
