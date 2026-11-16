from aiohttp import web
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import sql
from db import get_conn, _run
from utils.auth_helpers import get_admin_user, denied, require_perm, _is_tu, _sync_get_tu_rests
import datetime
import calendar
import json

routes = web.RouteTableDef()

def parse_date_ddmmYYYY(s):
    if not s: return None
    import re
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", str(s).strip())
    if not m: return None
    try:
        d = datetime.datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d.day != int(m.group(1)) or d.month != int(m.group(2)): return None
        return d
    except ValueError: return None

def add_months(dt, months):
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)

def entry_status(date_str, validity_months):
    if not date_str: return "missing"
    d = parse_date_ddmmYYYY(date_str)
    if not d: return "invalid_date"
    exp = add_months(d, validity_months)
    now = datetime.datetime.utcnow()
    if exp < now: return "expired"
    if (exp - now).days <= 30: return "expiring"
    return "ok"

def _mb_items(medbook, doctors, tests, vaccines):
    mb = medbook or {}
    if isinstance(mb, str):
        try: mb = json.loads(mb)
        except Exception: mb = {}
    items = []
    for d in doctors: items.append((mb.get("doctors", {}).get(str(d["id"])), d["validity_months"]))
    for t in tests: items.append((mb.get("tests", {}).get(str(t["id"])), t["validity_months"]))
    for v in vaccines: items.append((mb.get("vaccines", {}).get(str(v["id"])), v["validity_months"]))
    return items

def compute_medbook_status(medbook, doctors, tests, vaccines):
    has_expiring = False
    for date_str, validity in _mb_items(medbook, doctors, tests, vaccines):
        s = entry_status(date_str, validity)
        if s in ("missing", "invalid_date", "expired"): return "invalid"
        if s == "expiring": has_expiring = True
    return "expiring" if has_expiring else "ok"

def _sync_get_medbook_refs():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM medbook_doctors ORDER BY sort, id")
            doctors = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_tests ORDER BY sort, id")
            tests = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_vaccines ORDER BY sort, id")
            vaccines = [dict(r) for r in cur.fetchall()]
    return doctors, tests, vaccines

def _sync_medbooks_full(user_id, is_tu_flag):
    doctors, tests, vaccines = _sync_get_medbook_refs()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if is_tu_flag:
                cur.execute("SELECT u.user_id, u.full_name, u.position, u.medbook, r.name AS restaurant_name FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key WHERE COALESCE(u.is_admin, FALSE) = FALSE AND COALESCE(u.is_fired, FALSE) = FALSE AND u.login IS NOT NULL AND r.territory_manager_id = %s ORDER BY u.full_name", (user_id,))
            else:
                cur.execute("SELECT u.user_id, u.full_name, u.position, u.medbook, r.name AS restaurant_name FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key WHERE COALESCE(u.is_admin, FALSE) = FALSE AND COALESCE(u.is_fired, FALSE) = FALSE AND u.login IS NOT NULL ORDER BY u.full_name")
            users = [dict(r) for r in cur.fetchall()]
    for u in users:
        mb = u.get("medbook") or {}
        u["medbook_status"] = compute_medbook_status(mb, doctors, tests, vaccines)
    return doctors, tests, vaccines, users

@routes.post('/api/admin/medbooks')
async def handle_admin_medbooks(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    doctors, tests, vaccines, users = await _run(_sync_medbooks_full, admin["user_id"], _is_tu(admin))
    return web.json_response({"doctors": doctors, "tests": tests, "vaccines": vaccines, "users": users})

@routes.post('/api/admin/medbook/get')
async def handle_admin_medbook_get(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id", 0))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT u.user_id, u.full_name, u.position, u.medbook, r.name AS restaurant_name FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key WHERE u.user_id = %s", (uid,))
                return cur.fetchone()
    user = await _run(_sync)
    if not user: return web.json_response({"error": "not_found"}, status=404)
    
    doctors, tests, vaccines = await _run(_sync_get_medbook_refs)
    return web.json_response({
        "user": {"user_id": user["user_id"], "full_name": user.get("full_name"), "position": user.get("position"), "restaurant_name": user.get("restaurant_name") or ""},
        "medbook": user.get("medbook") or {}, "doctors": doctors, "tests": tests, "vaccines": vaccines,
    })

@routes.post('/api/admin/medbook/save')
async def handle_admin_medbook_save(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "medbook_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id", 0))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    from routes.users import _check_admin_can_manage_user
    if not await _check_admin_can_manage_user(admin, uid):
        return web.json_response({"error": "forbidden"}, status=403)

    mb = body.get("medbook") or {"doctors": {}, "tests": {}, "vaccines": {}}
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("UPDATE users SET medbook = %s WHERE user_id = %s", (Json(mb), uid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/medbook/reference/add')
async def handle_admin_medbook_ref_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    if rtype not in ("doctor", "test", "vaccine"): return web.json_response({"error": "invalid_type"}, status=400)
    name = (body.get("name") or "").strip()
    if not name or len(name) > 100: return web.json_response({"error": "invalid"}, status=400)
    months = max(1, min(120, int(body.get("validity_months", 12))))
    required = bool(body.get("required"))
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT COALESCE(MAX(sort), 0) FROM {}").format(sql.Identifier(table)))
                sort = (cur.fetchone()[0] or 0) + 1
                cur.execute(sql.SQL("INSERT INTO {} (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)").format(sql.Identifier(table)), (name, required, months, sort))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/medbook/reference/update')
async def handle_admin_medbook_ref_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    rid = int(body.get("id", 0))
    if rtype not in ("doctor", "test", "vaccine") or not rid: return web.json_response({"error": "invalid"}, status=400)
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                if "name" in body: cur.execute(sql.SQL("UPDATE {} SET name = %s WHERE id = %s").format(sql.Identifier(table)), (body["name"], rid))
                if "validity_months" in body: cur.execute(sql.SQL("UPDATE {} SET validity_months = %s WHERE id = %s").format(sql.Identifier(table)), (max(1, min(120, int(body["validity_months"]))), rid))
                if "required" in body: cur.execute(sql.SQL("UPDATE {} SET required = %s WHERE id = %s").format(sql.Identifier(table)), (bool(body["required"]), rid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/medbook/reference/delete')
async def handle_admin_medbook_ref_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    rid = int(body.get("id", 0))
    if rtype not in ("doctor", "test", "vaccine") or not rid: return web.json_response({"error": "invalid"}, status=400)
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: cur.execute(sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table)), (rid,))
    await _run(_sync)
    return web.json_response({"ok": True})
