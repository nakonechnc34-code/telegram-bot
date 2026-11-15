from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.security import validate_login_data, verify_password, _check_rate_limit, _reset_rate_limit
from utils.auth_helpers import _sync_create_session, _sync_delete_session

routes = web.RouteTableDef()

def _sync_get_user_by_login(login):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE LOWER(login) = LOWER(%s)", (login,))
            return cur.fetchone()

@routes.post('/api/auth/login')
async def handle_auth_login_staff(request):
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    data, err = validate_login_data(body)
    if err: return web.json_response({"error": err}, status=400)
        
    login, password = data["login"], data["password"]

    ip = request.remote or "unknown"
    if not _check_rate_limit(ip):
        return web.json_response({"error": "too_many_attempts"}, status=429)

    user = await _run(_sync_get_user_by_login, login)
    if not user or not verify_password(password, user.get("password_hash") or ""):
        return web.json_response({"error": "invalid_credentials"}, status=401)
    
    _reset_rate_limit(ip)
    if user.get("is_fired"): return web.json_response({"error": "fired"}, status=403)
    
    token = await _run(_sync_create_session, user["user_id"])
    return web.json_response({"ok": True, "token": token, "is_admin": bool(user.get("is_admin"))})

@routes.post('/api/auth/logout')
async def handle_auth_logout(request):
    try: data = await request.json()
    except Exception: data = {}
    token = data.get("webToken") or ""
    if token: await _run(_sync_delete_session, token)
    return web.json_response({"ok": True})
