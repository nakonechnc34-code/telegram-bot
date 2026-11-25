import os
import uuid
import json
import logging
from aiohttp import web
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import sql
from db import get_conn, _run
from config import (
    ALLOWED_EXTENSIONS, IMAGE_EXTENSIONS, ENABLE_PUSH, VAPID_PRIVATE_KEY, VAPID_CLAIMS, PERM_KEYS, PERMISSIONS_LIST,
    CACHE_TTL_RESTAURANTS, CACHE_TTL_MEDBOOK_REF, CACHE_TTL_NEWS
)
from utils.auth_helpers import (
    get_admin_user, get_auth_user, denied, require_perm, _is_hr_or_super, _is_tu, _sync_get_tu_rests, _sync_user_has_perm
)
from utils.security import hash_password, verify_password
from routes.medbooks import (
    compute_medbook_status, entry_status, _mb_items, _sync_get_medbook_refs
)
from routes.users import _sync_dashboard_stats
from utils.common import safe_int, safe_int as _safe_int
from middleware.cache import get_cached, set_cached, clear_cache

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = Exception

routes = web.RouteTableDef()


def _medbook_missing_count(medbook, doctors, tests, vaccines):
    items = _mb_items(medbook, doctors, tests, vaccines)
    missing = sum(1 for date_str, v in items if entry_status(date_str, v) in ("missing", "invalid_date", "expired"))
    return missing, len(items)


def _auto_publish_scheduled(cur):
    cur.execute("UPDATE news SET status = 'published' WHERE status = 'scheduled' AND publish_at IS NOT NULL AND publish_at <= NOW()")


def _sync_bootstrap(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("UPDATE users SET last_seen_at = NOW() WHERE user_id = %s", (user_id,))
            cur.execute("SELECT u.*, c.name AS citizenship_name FROM users u LEFT JOIN citizenships c ON u.citizenship_id = c.id WHERE u.user_id = %s", (user_id,))
            user = dict(cur.fetchone())
            if not user:
                return None
            _auto_publish_scheduled(cur)

            cur.execute("SELECT * FROM news WHERE status = 'published' ORDER BY created_at DESC LIMIT 50")
            news_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM standards WHERE status = 'published' ORDER BY created_at DESC")
            std_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM faq ORDER BY id")
            faq_rows = [dict(r) for r in cur.fetchall()]

            if _is_tu(user):
                cur.execute("SELECT * FROM restaurants WHERE key != 'office' AND territory_manager_id = %s ORDER BY sort, name", (user_id,))
            else:
                cur.execute("SELECT * FROM restaurants WHERE key != 'office' ORDER BY sort, name")
            rest_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM medbook_doctors ORDER BY sort, id")
            doctors = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_tests ORDER BY sort, id")
            tests = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_vaccines ORDER BY sort, id")
            vaccines = [dict(r) for r in cur.fetchall()]

            pos_lower = (user.get("position") or "").lower()
            is_hr = _is_hr_or_super(user)
            is_tu = "территориальный" in pos_lower
            is_us = "управляющий сменой" in pos_lower
            can_see_team = is_hr or is_tu or is_us

            team_rows = []
            if can_see_team:
                cur.execute("""
                    SELECT u.user_id, u.full_name, u.position, u.phone, u.restaurant_key, r.name AS restaurant_name,
                           COALESCE(u.is_certified, FALSE) AS is_certified, u.medbook, CASE WHEN %s OR lower(btrim(COALESCE(mgr.position, ''))) <> 'тайный гость' THEN mgr.full_name ELSE NULL END AS manager_name,
                           c.name AS citizenship_name, u.hire_date
                    FROM users u
                    LEFT JOIN restaurants r ON u.restaurant_key = r.key
                    LEFT JOIN users mgr ON r.territory_manager_id = mgr.user_id
                    LEFT JOIN citizenships c ON u.citizenship_id = c.id
                    WHERE u.user_id != %s AND COALESCE(u.is_fired, FALSE) = FALSE AND COALESCE(u.is_admin, FALSE) = FALSE AND u.login IS NOT NULL
                    AND (%s OR lower(btrim(COALESCE(u.position, ''))) <> 'тайный гость')
                    ORDER BY u.full_name
                """, (is_hr, user_id, is_hr))
                all_staff = [dict(r) for r in cur.fetchall()]

                if is_us:
                    my_rest = user.get("restaurant_key")
                    team_rows = [s for s in all_staff if s.get("restaurant_key") == my_rest]
                elif is_tu:
                    cur.execute("SELECT key FROM restaurants WHERE territory_manager_id = %s", (user_id,))
                    my_rests = {r["key"] for r in cur.fetchall()}
                    team_rows = [s for s in all_staff if s.get("restaurant_key") in my_rests]
                else:
                    team_rows = all_staff

    user.pop("password_hash", None)
    return (user, news_rows, std_rows, faq_rows, rest_rows, doctors, tests, vaccines, team_rows, can_see_team)


@routes.post('/api/bootstrap')
async def handle_bootstrap(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    result = await _run(_sync_bootstrap, user["user_id"])
    if not result:
        return web.json_response({"error": "not_found"}, status=404)
    (u, news_rows, std_rows, faq_rows, rest_rows, doctors, tests, vaccines, team_rows, can_see_team) = result

    restaurant_name = ""
    restaurant_key = u.get("restaurant_key") or ""
    for r in rest_rows:
        if r["key"] == restaurant_key:
            restaurant_name = r["name"]
            break

    profile = {
        "user_id": u["user_id"],
        "full_name": u.get("full_name") or "",
        "first_name": (u.get("full_name") or "").split()[0] if u.get("full_name") else "",
        "phone": u.get("phone") or "",
        "birth_date": u.get("birth_date") or "",
        "position": u.get("position") or "—",
        "restaurant": restaurant_name or "—",
        "restaurant_key": restaurant_key,
        "is_certified": bool(u.get("is_certified")),
        "is_admin": bool(u.get("is_admin")),
        "hire_date": u.get("hire_date") or "—",
        "citizenship_name": u.get("citizenship_name") or "—",
        "can_access_timesheet": _sync_user_has_perm(u, "timesheet_access"),
    }

    mb = u.get("medbook") or {}
    if isinstance(mb, str):
        try:
            mb = json.loads(mb)
        except Exception:
            mb = {}

    def build_section(items, source):
        out = []
        for it in items:
            date_str = mb.get(source, {}).get(str(it["id"]), "")
            st = entry_status(date_str, it["validity_months"])
            out.append({
                "id": it["id"],
                "name": it["name"],
                "required": bool(it.get("required")),
                "validity_months": it["validity_months"],
                "date": date_str,
                "status": st,
            })
        return out

    medbook_status = compute_medbook_status(mb, doctors, tests, vaccines)
    missing, total = _medbook_missing_count(mb, doctors, tests, vaccines)

    medbook_payload = {
        "status": medbook_status,
        "missing": missing,
        "total": total,
        "doctors": build_section(doctors, "doctors"),
        "tests": build_section(tests, "tests"),
        "vaccines": build_section(vaccines, "vaccines"),
    }

    team_list = []
    for t in team_rows:
        tmb = t.get("medbook") or {}
        if isinstance(tmb, str):
            try:
                tmb = json.loads(tmb)
            except Exception:
                tmb = {}
        team_list.append({
            "user_id": t["user_id"],
            "full_name": t["full_name"] or "",
            "position": t["position"] or "",
            "phone": t["phone"] or "",
            "restaurant_key": t.get("restaurant_key") or "",
            "restaurant_name": t.get("restaurant_name") or "",
            "manager_name": t.get("manager_name") or "",
            "is_certified": bool(t.get("is_certified")),
            "medbook_status": compute_medbook_status(tmb, doctors, tests, vaccines),
            "hire_date": t.get("hire_date") or "—",
            "citizenship_name": t.get("citizenship_name") or "—",
        })

    return web.json_response({
        "profile": profile,
        "medbook": medbook_payload,
        "news": news_rows,
        "standards": std_rows,
        "faq": faq_rows,
        "restaurants": rest_rows,
        "team": team_list,
        "can_see_team": can_see_team,
    })


def _sync_restaurants():
    cached = get_cached("restaurants_all")
    if cached is not None:
        return cached
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT r.*, u.full_name AS territory_manager_name FROM restaurants r LEFT JOIN users u ON r.territory_manager_id = u.user_id ORDER BY r.sort, r.name")
            result = [dict(r) for r in cur.fetchall()]
    set_cached("restaurants_all", result, CACHE_TTL_RESTAURANTS)
    return result


def _sync_restaurants_by_tu(user_id):
    cache_key = f"restaurants_tu_{user_id}"
    cached = get_cached(cache_key)
    if cached is not None:
        return cached
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT r.*, u.full_name AS territory_manager_name FROM restaurants r "
                "LEFT JOIN users u ON r.territory_manager_id = u.user_id "
                "WHERE r.territory_manager_id = %s ORDER BY r.sort, r.name",
                (user_id,)
            )
            result = [dict(r) for r in cur.fetchall()]
    set_cached(cache_key, result, CACHE_TTL_RESTAURANTS)
    return result


def _sync_tu_candidates():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT user_id, full_name FROM users WHERE COALESCE(is_fired, FALSE) = FALSE AND LOWER(COALESCE(position,'')) LIKE '%территориальный%' ORDER BY full_name")
            return [dict(r) for r in cur.fetchall()]


@routes.post('/api/admin/restaurants')
async def handle_admin_restaurants(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if _is_tu(admin):
        restaurants = await _run(_sync_restaurants_by_tu, admin["user_id"])
    else:
        restaurants = await _run(_sync_restaurants)
    tu = await _run(_sync_tu_candidates)
    return web.json_response({"restaurants": restaurants, "tu_candidates": tu})


@routes.post('/api/admin/restaurant/add')
async def handle_admin_restaurant_add(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "restaurant_create")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = (body.get("key") or "").strip().lower().replace(" ", "_")
    name = (body.get("name") or "").strip()
    if not key or not name or len(name) > 100:
        return web.json_response({"error": "invalid"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key FROM restaurants WHERE key = %s", (key,))
                if cur.fetchone():
                    return "duplicate"
                cur.execute(
                    "INSERT INTO restaurants (key, name, address, hours, phone, org, lat, lon, force_status, sort) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open', 100)",
                    (key, name, body.get("address", ""), body.get("hours", ""), body.get("phone", ""),
                     body.get("org", ""), body.get("lat"), body.get("lon"))
                )
                cur.execute(
                    "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)",
                    (admin["user_id"], "restaurant_create", "restaurant", key, f"name={name}")
                )
    res = await _run(_sync)
    if res == "duplicate":
        return web.json_response({"error": "duplicate"}, status=409)
    clear_cache("restaurants_all")
    return web.json_response({"ok": True})


@routes.post('/api/admin/restaurant/update')
async def handle_admin_restaurant_update(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "restaurant_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    updates = body.get("updates") or {}
    allowed = {"name", "address", "phone", "hours", "org", "lat", "lon"}

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                for k, v in updates.items():
                    if k in allowed:
                        query = sql.SQL("UPDATE restaurants SET {} = %s WHERE key = %s").format(sql.Identifier(k))
                        cur.execute(query, (v, key))
                cur.execute(
                    "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)",
                    (admin["user_id"], "restaurant_update", "restaurant", key, f"fields={','.join(updates.keys())}")
                )
    await _run(_sync)
    clear_cache("restaurants_all")
    return web.json_response({"ok": True})


@routes.post('/api/admin/restaurant/tu')
async def handle_admin_restaurant_tu(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "restaurant_tu")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    tu = _safe_int(body.get("territory_manager_id")) if body.get("territory_manager_id") else None
    if tu is not None and tu <= 0:
        tu = None

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                if tu is not None:
                    cur.execute(
                        "SELECT user_id FROM users WHERE user_id = %s AND LOWER(COALESCE(position,'')) LIKE '%территориальный%' AND COALESCE(is_fired, FALSE) = FALSE",
                        (tu,)
                    )
                    if not cur.fetchone():
                        return "invalid_tu"
                cur.execute("UPDATE restaurants SET territory_manager_id = %s WHERE key = %s", (tu, key))
    res = await _run(_sync)
    if res == "invalid_tu":
        return web.json_response({"error": "invalid_tu"}, status=400)
    clear_cache("restaurants_all")
    return web.json_response({"ok": True})


@routes.post('/api/admin/restaurant/status')
async def handle_admin_restaurant_status(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "restaurant_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    st = body.get("status") or "open"
    if st == "auto":
        st = "open"

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE restaurants SET force_status = %s WHERE key = %s", (st, key))
    await _run(_sync)
    clear_cache("restaurants_all")
    return web.json_response({"ok": True})


@routes.post('/api/admin/citizenships')
async def handle_admin_citizenships(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM citizenships ORDER BY name")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"citizenships": await _run(_sync)})


@routes.post('/api/admin/citizenship/add')
async def handle_admin_citizenship_add(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "citizenships_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    name = (body.get("name") or "").strip()
    if not name or len(name) > 50:
        return web.json_response({"error": "invalid"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO citizenships (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING *",
                    (name,)
                )
                return cur.fetchone()
    new_c = await _run(_sync)
    if not new_c:
        return web.json_response({"ok": False, "error": "duplicate"}, status=409)
    return web.json_response({"ok": True, "citizenship": dict(new_c)})


@routes.post('/api/admin/citizenship/delete')
async def handle_admin_citizenship_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "citizenships_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    cid = int(body.get("id", 0))
    if cid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM citizenships WHERE id = %s", (cid,))
    await _run(_sync)
    return web.json_response({"ok": True})


def _sync_list_admins():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id, login, full_name, position, permissions, "
                "COALESCE(is_admin, FALSE) AS is_admin, COALESCE(is_super_admin, FALSE) AS is_super_admin "
                "FROM users WHERE COALESCE(is_admin, FALSE) = TRUE AND COALESCE(is_fired, FALSE) = FALSE ORDER BY user_id"
            )
            return [dict(r) for r in cur.fetchall()]


@routes.post('/api/admin/admins')
async def handle_admin_admins(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not admin["is_super_admin"]:
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"admins": await _run(_sync_list_admins)})


@routes.post('/api/admin/permissions-list')
async def handle_permissions_list(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not admin["is_super_admin"]:
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"permissions": PERMISSIONS_LIST})


@routes.post('/api/admin/set-permissions')
async def handle_admin_set_permissions(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not admin["is_super_admin"]:
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)
    perms = body.get("permissions") or {}
    cleaned = {k: True for k in PERM_KEYS if perms.get(k)}

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET permissions = %s WHERE user_id = %s", (Json(cleaned), uid))
                cur.execute(
                    "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)",
                    (admin["user_id"], "set_permissions", "user", str(uid), ",".join(cleaned.keys()))
                )
    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/reports')
async def handle_admin_reports(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    stats = await _run(_sync_dashboard_stats, admin)
    return web.json_response({"report": stats})


@routes.post('/api/admin/audit')
async def handle_admin_audit(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT a.* FROM admin_audit a
                    WHERE %s OR NOT EXISTS (
                        SELECT 1 FROM users u
                        WHERE lower(btrim(COALESCE(u.position, ''))) = 'тайный гость'
                          AND (u.user_id = a.admin_id OR
                               (a.target_type = 'user' AND u.user_id::text = a.target_id::text))
                    )
                    ORDER BY a.created_at DESC LIMIT 300
                """, (_is_hr_or_super(admin),))
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"audit": await _run(_sync)})


@routes.post('/api/admin/change-password')
async def handle_admin_change_password(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    old = body.get("old_password") or ""
    new = body.get("new_password") or ""
    if not verify_password(old, admin.get("password_hash") or ""):
        return web.json_response({"error": "wrong_password"}, status=401)
    if len(new) < 8:
        return web.json_response({"error": "password_too_short"}, status=400)

    # Определяем текущий токен, чтобы его не удалять
    current_token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        current_token = auth_header[7:].strip()

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET password_hash = %s WHERE user_id = %s",
                    (hash_password(new), admin["user_id"])
                )
                if current_token:
                    cur.execute(
                        "DELETE FROM web_sessions WHERE user_id = %s AND token != %s",
                        (admin["user_id"], current_token)
                    )
                else:
                    cur.execute(
                        "DELETE FROM web_sessions WHERE user_id = %s",
                        (admin["user_id"],)
                    )
                cur.execute(
                    "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)",
                    (admin["user_id"], "change_password", "user", str(admin["user_id"]), "")
                )
    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/upload')
async def handle_admin_upload(request):
    token = request.query.get('webToken') or request.headers.get('X-Token')
    if not token and request.headers.get('Authorization', '').startswith('Bearer '):
        token = request.headers['Authorization'].split(' ', 1)[1]

    if not token:
        return web.json_response({"error": "Unauthorized: No token provided"}, status=401)

    from multidict import CIMultiDict

    class TokenRequest:
        def __init__(self, orig, tok):
            self._orig = orig
            self._token = tok
            self.headers = CIMultiDict(orig.headers)
            self.headers['Authorization'] = f'Bearer {tok}'
            self.query = orig.query
            self.match_info = orig.match_info

        async def json(self):
            return {"webToken": self._token}

        def __getattr__(self, name):
            return getattr(self._orig, name)

    auth_req = TokenRequest(request, token)
    admin, err = await get_admin_user(auth_req)
    if err:
        return denied(err)

    try:
        reader = await request.multipart()
        field = await reader.next()
        if not field or field.name != 'file':
            return web.json_response({"error": "invalid_file"}, status=400)
        filename = field.filename
        if not filename:
            return web.json_response({"error": "filename_required"}, status=400)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return web.json_response({"error": "invalid_file_type"}, status=400)

        new_name = f"{uuid.uuid4().hex}{ext}"
        data_dir = os.getenv("DATA_DIR", "/data")
        upload_dir = os.path.join(data_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, new_name)

        with open(file_path, "wb") as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                f.write(chunk)
        return web.json_response({"ok": True, "url": f"/uploads/{new_name}", "name": filename})
    except Exception as e:
        logging.error(f"Upload error: {e}")
        return web.json_response({"error": "upload_failed"}, status=500)


@routes.get('/uploads/{filename}')
async def handle_uploaded_file(request):
    user, err = await get_auth_user(request)
    if err:
        return web.Response(status=401, text="Unauthorized")

    filename = request.match_info['filename']
    data_dir = os.getenv("DATA_DIR", "/data")
    upload_dir = os.path.abspath(os.path.join(data_dir, "uploads"))
    safe_path = os.path.abspath(os.path.join(upload_dir, os.path.basename(filename)))

    if not safe_path.startswith(upload_dir + os.sep):
        return web.Response(status=403)
    if not os.path.exists(safe_path):
        return web.Response(status=404)

    ext = os.path.splitext(safe_path)[1].lower()
    headers = {}
    if ext not in IMAGE_EXTENSIONS:
        orig_name = request.query.get("name") or os.path.basename(filename)
        headers["Content-Disposition"] = f'attachment; filename="{orig_name}"'
    else:
        if ext in ('.jpg', '.jpeg'):
            headers["Content-Type"] = "image/jpeg"
        elif ext == '.png':
            headers["Content-Type"] = "image/png"
        elif ext == '.gif':
            headers["Content-Type"] = "image/gif"
        elif ext == '.webp':
            headers["Content-Type"] = "image/webp"
    return web.FileResponse(safe_path, headers=headers)


def _sync_get_user(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()


def _sync_get_session_user(token):
    from utils.auth_helpers import _sync_get_session_user as gs
    return gs(token)


@routes.post('/api/push/subscribe')
async def handle_push_subscribe(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    subscription = body.get("subscription")
    if not subscription:
        return web.json_response({"error": "invalid_sub"}, status=400)
    endpoint = subscription.get("endpoint")
    if not endpoint:
        return web.json_response({"error": "no_endpoint"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM push_subscriptions WHERE user_id = %s AND subscription->>'endpoint' = %s",
                    (user["user_id"], endpoint)
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        "UPDATE push_subscriptions SET subscription = %s WHERE id = %s",
                        (Json(subscription), row[0])
                    )
                else:
                    cur.execute(
                        "INSERT INTO push_subscriptions (user_id, subscription) VALUES (%s, %s)",
                        (user["user_id"], Json(subscription))
                    )
    await _run(_sync)
    return web.json_response({"ok": True})
