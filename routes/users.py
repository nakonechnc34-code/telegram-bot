from aiohttp import web
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from db import get_conn, _run
from utils.auth_helpers import get_admin_user, denied, require_perm, _sync_user_has_perm, _is_tu, _sync_get_tu_rests
from utils.security import hash_password
import random

routes = web.RouteTableDef()

TRANSLIT = {
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z",
    "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r",
    "с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch",
    "ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
}

def _generate_login_for(full_name, existing_logins):
    parts = (full_name or "").strip().split()
    surname = (parts[0] if parts else "").lower()
    letters = ""
    for ch in surname:
        if len(letters) >= 3: break
        t = TRANSLIT.get(ch)
        if t: letters += t
    while len(letters) < 3:
        letters += random.choice("abcdefghijklmnopqrstuvwxyz")
    letters = letters[:3]

    digits = list(range(10, 100))
    random.shuffle(digits)
    for d in digits:
        candidate = f"{letters}{d}"
        if candidate not in existing_logins: return candidate
    for _ in range(500):
        rl = "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(3))
        d = random.randint(10, 99)
        candidate = f"{rl}{d}"
        if candidate not in existing_logins: return candidate
    raise RuntimeError("Не удалось сгенерировать логин")

def validate_user_create_data(body):
    if not isinstance(body, dict):
        return None, "invalid_json"
    full_name = (body.get("full_name") or "").strip()
    password = body.get("password") or ""
    if not full_name or len(full_name) > 100:
        return None, "invalid_full_name"
    if not password or len(password) < 6:
        return None, "invalid_password"
    payment_type = body.get("payment_type") or "hourly"
    if payment_type not in ('hourly', 'fixed'):
        return None, "invalid_payment_type"
    citizenship_id = body.get("citizenship_id")
    if citizenship_id == "":
        citizenship_id = None
    elif citizenship_id is not None:
        try:
            citizenship_id = int(citizenship_id)
        except (ValueError, TypeError):
            return None, "invalid_citizenship_id"
    return {
        "full_name": full_name,
        "password": password,
        "phone": (body.get("phone") or "")[:50],
        "birth_date": (body.get("birth_date") or "")[:20],
        "position": (body.get("position") or "")[:100],
        "restaurant_key": (body.get("restaurant_key") or body.get("restaurant") or "")[:100],
        "is_certified": bool(body.get("is_certified")),
        "hire_date": (body.get("hire_date") or "")[:20],
        "citizenship_id": citizenship_id,
        "payment_type": payment_type,
    }, None

def _sync_list_users(search="", fired=False, tu_rests=None):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            base = """
                SELECT u.user_id, u.login, u.full_name, u.phone, u.birth_date, u.position, u.restaurant_key, r.name AS restaurant_name,
                       COALESCE(u.is_admin, FALSE) AS is_admin, COALESCE(u.is_super_admin, FALSE) AS is_super_admin,
                       COALESCE(u.is_fired, FALSE) AS is_fired, COALESCE(u.is_certified, FALSE) AS is_certified,
                       u.medbook, u.created_at, u.last_seen_at, u.fired_at, u.fired_by,
                       u.hire_date, u.citizenship_id, c.name AS citizenship_name, u.payment_type
                FROM users u 
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN citizenships c ON u.citizenship_id = c.id
                WHERE COALESCE(u.is_fired, FALSE) = %s AND u.login IS NOT NULL
            """
            params = [bool(fired)]
            
            if tu_rests is not None:
                if not tu_rests: return []
                base += " AND u.restaurant_key = ANY(%s)"
                params.append(tu_rests)
                
            if search:
                base += " AND (LOWER(COALESCE(u.full_name,'')) LIKE %s OR LOWER(COALESCE(u.login,'')) LIKE %s OR COALESCE(u.phone,'') LIKE %s OR CAST(u.user_id AS TEXT) LIKE %s)"
                s = f"%{search.lower()}%"
                params.extend([s, s, f"%{search}%", f"%{search}%"])
                
            base += " ORDER BY u.user_id DESC"
            cur.execute(base, params)
            return [dict(r) for r in cur.fetchall()]

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
    # Для простоты пока опустим сборку медкнижек здесь, сделаем это позже
    return web.json_response({"users": users})

def _sync_create_user(data, existing_logins, admin_id=None):
    full_name = data["full_name"]
    login = _generate_login_for(full_name, existing_logins)
    restaurant_key = data.get("restaurant_key") or ""
    if restaurant_key:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key FROM restaurants WHERE key = %s", (restaurant_key,))
                if not cur.fetchone(): return None, "invalid_restaurant"

    pw_hash = hash_password(data["password"])
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO users (login, password_hash, full_name, phone, birth_date, position, restaurant_key, is_certified, hire_date, citizenship_id, payment_type) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", 
                        (login, pw_hash, full_name, data.get("phone", ""), data.get("birth_date", ""), data.get("position", ""), restaurant_key, data.get("is_certified", False), data.get("hire_date", ""), data.get("citizenship_id"), data.get("payment_type", "hourly")))
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

# ... (Остальные функции для увольнения, обновления, админов и дашборда идут сюда)
