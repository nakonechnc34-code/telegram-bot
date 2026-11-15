from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from config import SESSION_TTL_DAYS, SESSION_CACHE_TTL
from utils.security import validate_login_data, verify_password, _check_rate_limit, _reset_rate_limit
import secrets
import time
import threading
from datetime import datetime, timezone as _tz

routes = web.RouteTableDef()

# Кэш сессий
_session_cache = {}
_session_cache_lock = threading.Lock()

# Синхронные хелперы для работы с БД
def _sync_get_user_by_login(login):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE LOWER(login) = LOWER(%s)", (login,))
            return cur.fetchone()

def _sync_create_session(user_id):
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO web_sessions (token, user_id) VALUES (%s,%s)", (token, user_id))
    return token

def _sync_get_session_user(token):
    now = time.time()
    with _session_cache_lock:
        cached = _session_cache.get(token)
        if cached and now - cached[1] < SESSION_CACHE_TTL:
            return cached[0]
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, last_used_at FROM web_sessions WHERE token = %s", (token,))
            row = cur.fetchone()
            if not row:
                with _session_cache_lock:
                    _session_cache.pop(token, None)
                return None
            uid, last_used = row
            
            if last_used is not None:
                now_dt = datetime.now(_tz.utc)
                lu = last_used if last_used.tzinfo else last_used.replace(tzinfo=_tz.utc)
                if (now_dt - lu).days > SESSION_TTL_DAYS:
                    cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
                    with _session_cache_lock:
                        _session_cache.pop(token, None)
                    return None
            
            cur.execute("UPDATE web_sessions SET last_used_at = NOW() WHERE token = %s AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '1 hour')", (token,))
            
            with _session_cache_lock:
                _session_cache[token] = (uid, now)
            return uid

def _sync_delete_session(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
            with _session_cache_lock:
                _session_cache.pop(token, None)
            return cur.rowcount > 0


# ================== ЭНДПОИНТЫ ==================
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
