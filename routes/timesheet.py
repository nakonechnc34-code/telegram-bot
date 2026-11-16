from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, denied, _is_hr_or_super, _is_tu
import calendar
from datetime import datetime
import io
import traceback
import logging
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side

routes = web.RouteTableDef()

def _safe_int(val, default=0):
    try: return int(val)
    except: return default

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

# ================== МАТРИЦА ==================
def _sync_timesheet_matrix(user_id, date_from, date_to):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u: return []
            
            is_hr_or_super = _is_hr_or_super(u)
            is_tu = _is_tu(u)
            is_us = "управляющий сменой" in (u.get("position") or "").lower()
            
            query = """SELECT u.user_id, u.full_name, u.position, COALESCE(NULLIF(u.rate, 0), pr.rate, 0) AS rate, u.payment_type, r.name AS restaurant_name
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN position_rates pr ON u.position = pr.position_name
                WHERE COALESCE(u.is_fired, FALSE) = FALSE AND COALESCE(u.is_admin, FALSE) = FALSE AND u.login IS NOT NULL"""
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
            cur.execute("SELECT user_id, work_date, hours, status FROM timesheet_records WHERE user_id = ANY(%s) AND work_date >= %s::date AND work_date <= %s::date", (emp_ids, date_from, date_to))
            records = cur.fetchall()
            
            data_map = {eid: {} for eid in emp_ids}
            for r in records:
                data_map[r["user_id"]][str(r["work_date"].day)] = {"h": float(r["hours"] or 0), "s": r["status"] or "work"}
            for e in employees:
                e["data"] = data_map[e["user_id"]]
            return employees

@routes.post('/api/timesheet/matrix')
async def handle_timesheet_matrix(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
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

# ================== СОХРАНЕНИЕ ЯЧЕЕК ==================
def _sync_save_cell(user_id, target_uid, work_date, hours, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if hours <= 0 and status == 'work':
                cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s", (target_uid, work_date))
            else:
                cur.execute("""INSERT INTO timesheet_records (user_id, work_date, hours, status, updated_at) VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, work_date) DO UPDATE SET hours = EXCLUDED.hours, status = EXCLUDED.status, updated_at = NOW()""", (target_uid, work_date, hours, status))

@routes.post('/api/timesheet/save_cell')
async def handle_timesheet_save_cell(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    target_uid = _safe_int(body.get("user_id"))
    work_date = body.get("work_date")
    hours = float(body.get("hours", 0))
    status = body.get("status", "work")
    
    if not work_date or target_uid <= 0: return web.json_response({"error": "invalid_data"}, status=400)
    allowed = await _run(_check_can_edit_user, user, target_uid)
    if not allowed: return web.json_response({"error": "forbidden_edit_other"}, status=403)
    
    await _run(_sync_save_cell, user["user_id"], target_uid, work_date, hours, status)
    return web.json_response({"ok": True})

def _sync_bulk_save_cells(user_id, cells):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for cell in cells:
                target_uid = cell.get("user_id")
                work_date = cell.get("work_date")
                hours = cell.get("hours", 0)
                status = cell.get("status", "work")
                if not work_date or not target_uid: continue
                if hours <= 0 and status == 'work':
                    cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s", (target_uid, work_date))
                else:
                    cur.execute("""INSERT INTO timesheet_records (user_id, work_date, hours, status, updated_at) VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (user_id, work_date) DO UPDATE SET hours = EXCLUDED.hours, status = EXCLUDED.status, updated_at = NOW()""", (target_uid, work_date, hours, status))

@routes.post('/api/timesheet/bulk_save')
async def handle_timesheet_bulk_save(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    cells = body.get("cells") or []
    if not cells: return web.json_response({"ok": True})
    for cell in cells:
        allowed = await _run(_check_can_edit_user, user, cell.get("user_id"))
        if not allowed: return web.json_response({"error": "forbidden_edit_other"}, status=403)
    await _run(_sync_bulk_save_cells, user["user_id"], cells)
    return web.json_response({"ok": True})

# ================== ОТЧЕТЫ И EXCEL ==================
def _sync_reports(user_id, date_from, date_to):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            is_hr_or_super = _is_hr_or_super(u)
            is_tu = _is_tu(u)
            is_us = "управляющий сменой" in (u.get("position") or "").lower()
            
            base = """SELECT u.full_name, u.position, r.name AS restaurant_name, SUM(t.hours) as total_hours, 
                       COALESCE(NULLIF(u.rate, 0), pr.rate, 0) AS rate, u.payment_type,
                       CASE WHEN u.payment_type = 'fixed' THEN COALESCE(NULLIF(u.rate, 0), pr.rate, 0)
                            ELSE (SUM(t.hours) * COALESCE(NULLIF(u.rate, 0), pr.rate, 0)) END as total_salary
                FROM users u JOIN timesheet_records t ON u.user_id = t.user_id
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN position_rates pr ON u.position = pr.position_name
                WHERE COALESCE(u.is_fired, FALSE) = FALSE AND u.login IS NOT NULL
                  AND t.work_date >= %s::date AND t.work_date <= %s::date"""
            params = [date_from, date_to]
            if is_us:
                base += " AND u.restaurant_key = %s"; params.append(u.get("restaurant_key"))
            elif is_tu:
                base += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"; params.append(user_id)
            elif not is_hr_or_super:
                base += " AND u.user_id = %s"; params.append(user_id)
            base += " GROUP BY u.user_id, u.full_name, u.position, r.name, u.rate, pr.rate, u.payment_type ORDER BY r.name, u.full_name"
            
            cur.execute(base, params)
            return [dict(r) for r in cur.fetchall()]

@routes.post('/api/timesheet/reports')
async def handle_timesheet_reports(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
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
        
    report = await _run(_sync_reports, user["user_id"], date_from, date_to)
    return web.json_response({"report": report})

@routes.get('/api/timesheet/export_excel')
async def handle_timesheet_export_excel(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    date_from = request.query.get("date_from")
    date_to = request.query.get("date_to")
    if not date_from or not date_to:
        return web.Response(text="Укажите даты", status=400)

    report = await _run(_sync_reports, user["user_id"], date_from, date_to)

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
            float(r.get("total_salary", 0))
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
            except: pass
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

# ================== НАСТРОЙКИ ==================
def _sync_settings_get(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u or not _is_hr_or_super(u): return []
            cur.execute("""SELECT p.name AS position_name, COALESCE(pr.rate, 0) AS rate
                FROM positions p LEFT JOIN position_rates pr ON p.name = pr.position_name
                WHERE p.is_archived = FALSE ORDER BY p.sort, p.name""")
            return [dict(r) for r in cur.fetchall()]

@routes.post('/api/timesheet/settings')
async def handle_timesheet_settings_get(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    settings = await _run(_sync_settings_get, user["user_id"])
    return web.json_response({"settings": settings})

@routes.post('/api/timesheet/settings/save')
async def handle_timesheet_settings_save(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    if not _is_hr_or_super(user): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    position_name = (body.get("position_name") or "").strip()
    rate = float(body.get("rate", 0))
    if not position_name: return web.json_response({"error": "invalid_position"}, status=400)
    
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO position_rates (position_name, rate) VALUES (%s, %s)
                    ON CONFLICT (position_name) DO UPDATE SET rate = EXCLUDED.rate""", (position_name, rate))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/timesheet/employees')
async def handle_timesheet_employees(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE user_id = %s", (user["user_id"],))
                u = cur.fetchone()
                is_hr_or_super = _is_hr_or_super(u)
                is_tu = _is_tu(u)
                is_us = "управляющий сменой" in (u.get("position") or "").lower()
                if not (is_hr_or_super or is_tu or is_us): return []
                
                query = """SELECT u.user_id, u.full_name, u.position, r.name AS restaurant_name
                    FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                    WHERE COALESCE(u.is_fired, FALSE) = FALSE AND COALESCE(u.is_admin, FALSE) = FALSE AND u.login IS NOT NULL"""
                params = []
                if is_us:
                    query += " AND u.restaurant_key = %s"; params.append(u.get("restaurant_key"))
                elif is_tu:
                    query += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"; params.append(user["user_id"])
                query += " ORDER BY u.full_name"
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]
                
    employees = await _run(_sync)
    return web.json_response({"employees": employees})

# ================== ВЫПЛАТЫ И НАЧИСЛЕНИЯ ==================

def _ensure_payments_table():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                    amount NUMERIC(10,2) NOT NULL,
                    comment TEXT NOT NULL,
                    payment_date DATE DEFAULT CURRENT_DATE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    created_by BIGINT,
                    record_type TEXT DEFAULT 'payout',
                    status TEXT DEFAULT 'approved',
                    proposed_by_name TEXT,
                    approved_by_name TEXT
                )
            """)
            cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'approved'")
            cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS proposed_by_name TEXT")
            cur.execute("ALTER TABLE payments ADD COLUMN IF NOT EXISTS approved_by_name TEXT")

@routes.post('/api/payments/add')
async def handle_payment_add(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    target_uid = _safe_int(body.get("user_id"))
    amount = float(body.get("amount", 0))
    comment = (body.get("comment") or "").strip()
    payment_date = body.get("payment_date") # <--- НОВОЕ
    
    if target_uid <= 0: return web.json_response({"error": "Выберите сотрудника"}, status=400)
    if amount <= 0: return web.json_response({"error": "Сумма должна быть больше нуля"}, status=400)
    if not comment: return web.json_response({"error": "Комментарий обязателен"}, status=400)
        
    def _sync():
        _ensure_payments_table()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payments (user_id, amount, comment, created_by, record_type, status, payment_date) 
                    VALUES (%s, %s, %s, %s, 'payout', 'approved', COALESCE(%s::date, CURRENT_DATE))
                """, (target_uid, amount, comment, user["user_id"], payment_date))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/accruals/add')
async def handle_accrual_add(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    target_uid = _safe_int(body.get("user_id"))
    amount = float(body.get("amount", 0))
    comment = (body.get("comment") or "").strip()
    payment_date = body.get("payment_date") # <--- НОВОЕ
    
    if target_uid <= 0: return web.json_response({"error": "Выберите сотрудника"}, status=400)
    if amount <= 0: return web.json_response({"error": "Сумма должна быть больше нуля"}, status=400)
    if not comment: return web.json_response({"error": "Комментарий обязателен"}, status=400)
        
    is_hr_or_super = _is_hr_or_super(user)
    status = 'approved' if is_hr_or_super else 'pending'
    proposed_by_name = None if is_hr_or_super else user.get("full_name")

    def _sync():
        _ensure_payments_table()
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO payments (user_id, amount, comment, created_by, record_type, status, proposed_by_name, payment_date) 
                    VALUES (%s, %s, %s, %s, 'accrual', %s, %s, COALESCE(%s::date, CURRENT_DATE))
                """, (target_uid, amount, comment, user["user_id"], status, proposed_by_name, payment_date))
    await _run(_sync)
    return web.json_response({"ok": True, "status": status})

@routes.post('/api/accruals/approve')
async def handle_accrual_approve(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    if not _is_hr_or_super(user): return web.json_response({"error": "forbidden"}, status=403)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    pid = _safe_int(body.get("id"))
    if pid <= 0: return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE payments SET status = 'approved', approved_by_name = %s WHERE id = %s", (user.get("full_name"), pid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/accruals/reject')
async def handle_accrual_reject(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    if not _is_hr_or_super(user): return web.json_response({"error": "forbidden"}, status=403)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    pid = _safe_int(body.get("id"))
    if pid <= 0: return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE payments SET status = 'rejected' WHERE id = %s", (pid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/payments/list')
async def handle_payments_list(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
        
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    if not date_from or not date_to:
        return web.json_response({"error": "invalid_dates"}, status=400)

    def _sync():
        _ensure_payments_table()
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM users WHERE user_id = %s", (user["user_id"],))
                u = cur.fetchone()
                is_hr_or_super = _is_hr_or_super(u)
                is_tu = _is_tu(u)
                is_us = "управляющий сменой" in (u.get("position") or "").lower()
                
                base = """
                    SELECT u.user_id, u.full_name, u.position, 
                           COALESCE(SUM(t.hours), 0) as total_hours, 
                           COALESCE(NULLIF(u.rate, 0), pr.rate, 0) AS rate, 
                           u.payment_type
                    FROM users u 
                    LEFT JOIN timesheet_records t ON u.user_id = t.user_id AND t.work_date >= %s::date AND t.work_date <= %s::date
                    LEFT JOIN position_rates pr ON u.position = pr.position_name
                    WHERE COALESCE(u.is_fired, FALSE) = FALSE AND COALESCE(u.is_admin, FALSE) = FALSE AND u.login IS NOT NULL
                """
                params = [date_from, date_to]
                if is_us:
                    base += " AND u.restaurant_key = %s"; params.append(u.get("restaurant_key"))
                elif is_tu:
                    base += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"; params.append(user["user_id"])
                elif not is_hr_or_super:
                    base += " AND u.user_id = %s"; params.append(user["user_id"])
                base += " GROUP BY u.user_id, u.full_name, u.position, u.rate, pr.rate, u.payment_type ORDER BY u.full_name"
                cur.execute(base, params)
                employees = [dict(r) for r in cur.fetchall()]
                
                cur.execute("""
                    SELECT user_id, record_type, SUM(amount) as total_amount
                    FROM payments
                    WHERE payment_date >= %s::date AND payment_date <= %s::date AND status = 'approved'
                    GROUP BY user_id, record_type
                """, (date_from, date_to))
                
                sums = cur.fetchall()
                extra_map = {}
                paid_map = {}
                for s in sums:
                    if s["record_type"] == 'accrual':
                        extra_map[s["user_id"]] = float(s["total_amount"])
                    else:
                        paid_map[s["user_id"]] = float(s["total_amount"])
                
                for emp in employees:
                    hours = float(emp["total_hours"] or 0)
                    rate = float(emp["rate"] or 0)
                    emp["timesheet_accrued"] = rate if emp["payment_type"] == 'fixed' else (hours * rate)
                    emp["extra_accrued"] = extra_map.get(emp["user_id"], 0.0)
                    emp["total_accrued"] = emp["timesheet_accrued"] + emp["extra_accrued"]
                    emp["paid"] = paid_map.get(emp["user_id"], 0.0)
                    emp["remaining"] = emp["total_accrued"] - emp["paid"]
                    
                pending = []
                if is_hr_or_super:
                    cur.execute("""
                        SELECT p.id, p.user_id, u.full_name, p.amount, p.comment, p.payment_date, p.proposed_by_name
                        FROM payments p
                        JOIN users u ON p.user_id = u.user_id
                        WHERE p.record_type = 'accrual' AND p.status = 'pending'
                        ORDER BY p.created_at DESC
                    """)
                    pending = [dict(r) for r in cur.fetchall()]
                    
        return employees, pending, is_hr_or_super

    try:
        employees, pending, is_hr_or_super = await _run(_sync)
        return web.json_response({"employees": employees, "pending": pending, "is_hr_or_super": is_hr_or_super})
    except Exception as e:
        logging.error(f"Error in payments list: {traceback.format_exc()}")
        return web.json_response({"error": f"Ошибка БД: {str(e)}"}, status=500)

@routes.post('/api/payments/employee')
async def handle_employee_finance(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)

    target_uid = _safe_int(body.get("user_id"))
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    
    if target_uid <= 0 or not date_from or not date_to:
        return web.json_response({"error": "invalid_data"}, status=400)

    is_hr = _is_hr_or_super(user)
    is_tu = _is_tu(user)
    is_us = "управляющий сменой" in (user.get("position") or "").lower()
    
    if not (is_hr or is_tu or is_us):
        if target_uid != user["user_id"]:
            return web.json_response({"error": "forbidden"}, status=403)

    def _sync():
        _ensure_payments_table()
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT u.position, u.payment_type, COALESCE(NULLIF(u.rate, 0), pr.rate, 0) AS rate 
                    FROM users u 
                    LEFT JOIN position_rates pr ON u.position = pr.position_name 
                    WHERE u.user_id = %s
                """, (target_uid,))
                emp = cur.fetchone()
                if not emp: return None

                cur.execute("""
                    SELECT COALESCE(SUM(hours), 0) as total_hours 
                    FROM timesheet_records 
                    WHERE user_id = %s AND work_date >= %s::date AND work_date <= %s::date
                """, (target_uid, date_from, date_to))
                total_hours = float(cur.fetchone()["total_hours"] or 0)

                cur.execute("""
                    SELECT p.id, p.amount, p.comment, p.payment_date, p.record_type, p.status, p.created_at, 
                           creator.full_name as created_by_name, p.proposed_by_name, p.approved_by_name
                    FROM payments p
                    LEFT JOIN users creator ON p.created_by = creator.user_id
                    WHERE p.user_id = %s AND p.payment_date >= %s::date AND p.payment_date <= %s::date
                    ORDER BY p.created_at DESC
                """, (target_uid, date_from, date_to))
                history = [dict(r) for r in cur.fetchall()]

                extra_accrued = sum(float(h["amount"]) for h in history if h["record_type"] == 'accrual' and h["status"] == 'approved')
                paid = sum(float(h["amount"]) for h in history if h["record_type"] == 'payout' and h["status"] == 'approved')
                
                rate = float(emp["rate"] or 0)
                is_fixed = emp["payment_type"] == 'fixed'
                timesheet_accrued = rate if is_fixed else (total_hours * rate)
                total_accrued = timesheet_accrued + extra_accrued
                remaining = total_accrued - paid

                return {
                    "total_hours": total_hours,
                    "timesheet_accrued": timesheet_accrued,
                    "extra_accrued": extra_accrued,
                    "total_accrued": total_accrued,
                    "paid": paid,
                    "remaining": remaining,
                    "rate": rate,
                    "payment_type": emp["payment_type"],
                    "history": history
                }

    try:
        data = await _run(_sync)
        if not data: return web.json_response({"error": "not_found"}, status=404)
        return web.json_response(data)
    except Exception as e:
        logging.error(f"Error in employee finance: {traceback.format_exc()}")
        return web.json_response({"error": f"Ошибка БД: {str(e)}"}, status=500)
