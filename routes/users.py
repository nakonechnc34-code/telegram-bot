from aiohttp import web
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import sql
from db import get_conn, _run
from utils.auth_helpers import get_admin_user, denied, require_perm, _sync_user_has_perm, _is_tu, _sync_get_tu_rests
from utils.security import hash_password
from routes.medbooks import compute_medbook_status, _sync_get_medbook_refs
from utils.common import safe_int, safe_float, generate_login_for
import random

routes = web.RouteTableDef()

def validate_user_create_data(body):
    if not isinstance(body, dict): return None, "invalid_json"
    full_name = (body.get("full_name") or "").strip()
    password = body.get("password") or ""
    if not full_name or len(full_name) > 100: return None, "invalid_full_name"
    if not password or len(password) < 6: return None, "invalid_password"
    payment_type = body.get("payment_type") or "hourly"
    if payment_type not in ('hourly', 'fixed'): return None, "invalid_payment_type"
    citizenship_id = body.get("citizenship_id")
    if citizenship_id == "": citizenship_id = None
    elif citizenship_id is not None:
        try: citizenship_id = int(citizenship_id)
        except (ValueError, TypeError): return None, "invalid_citizenship_id"
    return {
        "full_name": full_name, "password": password,
        "personnel_number": (body.get("personnel_number") or "").strip()[:50],
        "phone": (body.get("phone") or "")[:50], "birth_date": (body.get("birth_date") or "")[:20],
        "position": (body.get("position") or "")[:100],
        "restaurant_key": (body.get("restaurant_key") or body.get("restaurant") or "")[:100],
        "is_certified": bool(body.get("is_certified")), "hire_date": (body.get("hire_date") or "")[:20],
        "citizenship_id": citizenship_id, "payment_type": payment_type,
    }, None

def _sync_list_users(search="", fired=False, tu_rests=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            base = """SELECT u.user_id, u.login, u.full_name, u.personnel_number, u.phone, u.birth_date, u.position, u.restaurant_key, r.name AS restaurant_name,
                       COALESCE(u.is_admin, FALSE) AS is_admin, COALESCE(u.is_super_admin, FALSE) AS is_super_admin,
                       COALESCE(u.is_fired, FALSE) AS is_fired, COALESCE(u.is_certified, FALSE) AS is_certified,
                       u.medbook, u.created_at, u.last_seen_at, u.fired_at, u.fired_by,
                       u.hire_date, u.citizenship_id, c.name AS citizenship_name, u.payment_type
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN citizenships c ON u.citizenship_id = c.id
                WHERE COALESCE(u.is_fired, FALSE) = %s AND u.login IS NOT NULL"""
            params = [bool(fired)]
            if tu_rests is not None:
                if not tu_rests: return []
                base += " AND u.restaurant_key = ANY(%s)"; params.append(tu_rests)
            if search:
                base += " AND (LOWER(COALESCE(u.full_name,'')) LIKE %s OR LOWER(COALESCE(u.login,'')) LIKE %s OR COALESCE(u.phone,'') LIKE %s OR CAST(u.user_id AS TEXT) LIKE %s OR LOWER(COALESCE(u.personnel_number,'')) LIKE %s)"
                s = f"%{search.lower()}%"
                params.extend([s, s, f"%{search}%", f"%{search}%", s])
            base += " ORDER BY u.user_id DESC"
            cur.execute(base, params)
            return [dict(r) for r in cur.fetchall()]

async def _check_admin_can_manage_user(admin, target_uid):
    if admin.get("is_super_admin") or (admin.get("position") or "").strip().upper() == "HR":
        return True
    target = await _run(_sync_get_user_by_id, target_uid)
    if not target: return False
    if _is_tu(admin):
        allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"])
        return target.get("restaurant_key") in allowed_rests
    return False

@routes.post('/api/admin/users')
async def handle_admin_users(request):
    user, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: body = {}
    search = (body.get("search") or "").strip()
    fired = bool(body.get("fired"))
    tu_rests = None
    if _is_tu(user):
        tu_rests = await _run(_sync_get_tu_rests, user["user_id"])
        
    users = await _run(_sync_list_users, search, fired, tu_rests)
    
    doctors, tests, vaccines = await _run(_sync_get_medbook_refs)
    for u in users:
        mb = u.get("medbook") or {}
        if u.get("is_admin"):
            u["medbook_status"] = "—"
        else:
            u["medbook_status"] = compute_medbook_status(mb, doctors, tests, vaccines)
            
    return web.json_response({"users": users})

def _sync_create_user(data, existing_logins, admin_id=None):
    full_name = data["full_name"]
    login = generate_login_for(full_name, existing_logins)
    restaurant_key = data.get("restaurant_key") or ""
    if restaurant_key:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key FROM restaurants WHERE key = %s", (restaurant_key,))
                if not cur.fetchone(): return None, "invalid_restaurant"
    pw_hash = hash_password(data["password"])
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""INSERT INTO users (login, password_hash, full_name, personnel_number, phone, birth_date, position, restaurant_key, is_certified, hire_date, citizenship_id, payment_type) 
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (login, pw_hash, full_name, data.get("personnel_number", ""), data.get("phone", ""), data.get("birth_date", ""), data.get("position", ""), restaurant_key, data.get("is_certified", False), data.get("hire_date", ""), data.get("citizenship_id"), data.get("payment_type", "hourly")))
            new_user = dict(cur.fetchone())
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin_id, "user_create", "user", str(new_user["user_id"]), f"login={login}"))
    return new_user, None

def _sync_get_all_logins():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT LOWER(login) FROM users WHERE login IS NOT NULL")
            return set(r[0] for r in cur.fetchall())

@routes.post('/api/admin/user/create')
async def handle_admin_user_create(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_create")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    data, err = validate_user_create_data(body)
    if err: return web.json_response({"error": err}, status=400)
    if _is_tu(admin):
        allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"])
        if data.get("restaurant_key") not in allowed_rests:
            return web.json_response({"error": "forbidden_restaurant"}, status=403)
    existing_logins = await _run(_sync_get_all_logins)
    new_user, err_code = await _run(_sync_create_user, data, existing_logins, admin["user_id"])
    if err_code: return web.json_response({"error": err_code}, status=400)
    new_user.pop("password_hash", None)
    return web.json_response({"ok": True, "user": new_user})

def _sync_get_user_by_id(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT u.user_id, u.login, u.full_name, u.personnel_number, u.phone, u.birth_date, u.position, u.restaurant_key, r.name AS restaurant_name,
                       COALESCE(u.is_admin, FALSE) AS is_admin, COALESCE(u.is_super_admin, FALSE) AS is_super_admin,
                       COALESCE(u.is_fired, FALSE) AS is_fired, COALESCE(u.is_certified, FALSE) AS is_certified,
                       u.medbook, u.created_at, u.last_seen_at, u.fired_at, u.fired_by, u.permissions,
                       u.hire_date, u.citizenship_id, c.name AS citizenship_name, u.payment_type
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN citizenships c ON u.citizenship_id = c.id WHERE u.user_id = %s""", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

@routes.post('/api/admin/user/get')
async def handle_admin_user_get(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = safe_int(body.get("user_id")) # ИСПРАВЛЕНО
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    if not await _check_admin_can_manage_user(admin, uid):
        return web.json_response({"error": "forbidden"}, status=403)

    user = await _run(_sync_get_user_by_id, uid)
    if not user: return web.json_response({"error": "not_found"}, status=404)
    return web.json_response({"user": user})

def _sync_update_user(uid, updates):
    allowed_simple = {"full_name", "phone", "birth_date", "position", "restaurant_key", "is_certified", "hire_date", "citizenship_id", "payment_type", "personnel_number"}
    if "payment_type" in updates and updates["payment_type"] not in ('hourly', 'fixed'):
        return "invalid_payment_type"
    with get_conn() as conn:
        with conn.cursor() as cur:
            for k, v in updates.items():
                if k in allowed_simple:
                    if k == "citizenship_id" and v == "": v = None
                    elif k == "citizenship_id" and v is not None: v = int(v)
                    query = sql.SQL("UPDATE users SET {} = %s WHERE user_id = %s").format(sql.Identifier(k))
                    cur.execute(query, (v, uid))
            if "password" in updates and updates["password"]:
                cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (hash_password(updates["password"]), uid))
            if "is_admin" in updates:
                cur.execute("UPDATE users SET is_admin = %s WHERE user_id = %s", (bool(updates["is_admin"]), uid))
                if not updates["is_admin"]: cur.execute("UPDATE users SET permissions = '{}'::jsonb, is_super_admin = FALSE WHERE user_id = %s", (uid,))
    return None

@routes.post('/api/admin/user/update')
async def handle_admin_user_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = safe_int(body.get("user_id")) # ИСПРАВЛЕНО
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    if not await _check_admin_can_manage_user(admin, uid):
        return web.json_response({"error": "forbidden"}, status=403)

    updates = body.get("updates") or {}
    target = await _run(_sync_get_user_by_id, uid)
    if not target: return web.json_response({"error": "not_found"}, status=404)
    if "is_admin" in updates and not admin["is_super_admin"]: return web.json_response({"error": "forbidden_is_admin"}, status=403)
    if target.get("is_super_admin") and not admin["is_super_admin"]: return web.json_response({"error": "cannot_edit_super"}, status=403)
    if "restaurant" in updates: updates["restaurant_key"] = updates.pop("restaurant")
    
    if _is_tu(admin) and "restaurant_key" in updates:
        allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"])
        if updates["restaurant_key"] not in allowed_rests:
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    err_code = await _run(_sync_update_user, uid, updates)
    if err_code: return web.json_response({"error": err_code}, status=400)
    updated = await _run(_sync_get_user_by_id, uid)
    return web.json_response({"ok": True, "user": updated})

@routes.post('/api/admin/user/fire')
async def handle_admin_user_fire(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_fire")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = safe_int(body.get("user_id")) # ИСПРАВЛЕНО
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    if not await _check_admin_can_manage_user(admin, uid):
        return web.json_response({"error": "forbidden"}, status=403)

    target = await _run(_sync_get_user_by_id, uid)
    if not target: return web.json_response({"error": "not_found"}, status=404)
    if target.get("is_super_admin"): return web.json_response({"error": "cannot_fire_super"}, status=403)
    if target.get("is_admin") and not admin["is_super_admin"]: return web.json_response({"error": "cannot_fire_admin"}, status=403)
    if uid == admin["user_id"]: return web.json_response({"error": "cannot_fire_self"}, status=403)
    
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET is_fired = TRUE, fired_at = NOW(), fired_by = %s, is_admin = FALSE, is_super_admin = FALSE, permissions = '{}'::jsonb WHERE user_id = %s", (admin["login"], uid))
                cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "user_fire", "user", str(uid), f"by={admin['login']}"))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/user/restore')
async def handle_admin_user_restore(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_fire")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = safe_int(body.get("user_id")) # ИСПРАВЛЕНО
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    if not await _check_admin_can_manage_user(admin, uid):
        return web.json_response({"error": "forbidden"}, status=403)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET is_fired = FALSE, fired_at = NULL, fired_by = NULL WHERE user_id = %s", (uid,))
                cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "user_restore", "user", str(uid), f"by={admin['login']}"))
    await _run(_sync)
    return web.json_response({"ok": True})

def _sync_dashboard_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL")
            active = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE login IS NOT NULL")
            total = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE COALESCE(is_fired, FALSE) = TRUE")
            fired = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days' AND COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL")
            new7 = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM questions WHERE replied = FALSE")
            questions_open = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM news WHERE status = 'pending'")
            news_pending = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM standards WHERE status = 'pending'")
            standards_pending = cur.fetchone()[0] or 0
    return {"total": total, "active": active, "fired": fired, "new7": new7, "questions_open": questions_open, "news_pending": news_pending, "standards_pending": standards_pending}

@routes.post('/api/admin/dashboard')
async def handle_admin_dashboard(request):
    user, err = await get_admin_user(request)
    if err: return denied(err)
    stats = await _run(_sync_dashboard_stats)
    return web.json_response({"stats": stats})

# ================== БЫСТРЫЙ ДАШБОРД ==================
@routes.post('/api/admin/dashboard/summary')
async def handle_admin_dashboard_summary(request):
    user, err = await get_admin_user(request)
    if err: return denied(err)
    
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) FILTER (WHERE COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL) as active,
                        COUNT(*) FILTER (WHERE login IS NOT NULL) as total,
                        COUNT(*) FILTER (WHERE COALESCE(is_fired, FALSE) = TRUE) as fired,
                        COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days' AND COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL) as new7
                    FROM users
                """)
                stats = dict(cur.fetchone())

                cur.execute("SELECT COUNT(*) as cnt FROM questions WHERE replied = FALSE")
                stats["questions_open"] = cur.fetchone()["cnt"] or 0
                cur.execute("SELECT q.id, q.text, u.full_name FROM questions q LEFT JOIN users u ON q.user_id = u.user_id WHERE q.replied = FALSE ORDER BY q.created_at DESC LIMIT 4")
                open_qs = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT COUNT(*) as cnt FROM news WHERE status = 'pending'")
                stats["news_pending"] = cur.fetchone()["cnt"] or 0
                cur.execute("SELECT id, title FROM news WHERE status = 'pending' ORDER BY created_at DESC LIMIT 2")
                pending_news = [dict(r) for r in cur.fetchall()]

                cur.execute("SELECT COUNT(*) as cnt FROM standards WHERE status = 'pending'")
                stats["standards_pending"] = cur.fetchone()["cnt"] or 0

                cur.execute("SELECT user_id, full_name, position FROM users WHERE login IS NOT NULL AND COALESCE(is_fired, FALSE) = FALSE AND COALESCE(is_admin, FALSE) = FALSE ORDER BY created_at DESC LIMIT 4")
                new_users = [dict(r) for r in cur.fetchall()]

                doctors, tests, vaccines = _sync_get_medbook_refs()
                cur.execute("SELECT full_name, medbook FROM users WHERE login IS NOT NULL AND COALESCE(is_fired, FALSE) = FALSE AND COALESCE(is_admin, FALSE) = FALSE AND medbook IS NOT NULL")
                users_with_mb = cur.fetchall()
                
                total_mb_alerts = 0
                mb_alerts = []
                for u in users_with_mb:
                    st = compute_medbook_status(u.get("medbook") or {}, doctors, tests, vaccines)
                    if st in ('invalid', 'expiring'):
                        total_mb_alerts += 1
                        if len(mb_alerts) < 5:
                            mb_alerts.append({"full_name": u["full_name"], "status": st})
                
                stats["medbooks_alert"] = total_mb_alerts

        return {
            "stats": stats,
            "questions": open_qs,
            "news": pending_news,
            "users": new_users,
            "medbook_alerts": mb_alerts
        }

    data = await _run(_sync)
    return web.json_response(data)
