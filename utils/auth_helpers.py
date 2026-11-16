import time
import secrets
import threading
import json
from datetime import datetime, timezone as _tz
from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from config import SESSION_TTL_DAYS, SESSION_CACHE_TTL

_session_cache = {}
_session_cache_lock = threading.Lock()

def _sync_get_user(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()

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

def _sync_create_session(user_id):
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO web_sessions (token, user_id) VALUES (%s,%s)", (token, user_id))
    return token

def _sync_delete_session(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
            with _session_cache_lock:
                _session_cache.pop(token, None)
            return cur.rowcount > 0

def _sync_user_has_perm(user, perm):
    if not user: return False
    
    # ВРЕМЕННЫЙ ЛОГ ДЛЯ ОТЛАДКИ
    print(f"DEBUG [AUTH]: Проверка {perm} для {user.get('login')}. is_super={user.get('is_super_admin')}, pos={user.get('position')}, perms={user.get('permissions')}")

    # Супер-админ и HR имеют доступ ко всему
    if user.get("is_super_admin"): return True
    if (user.get("position") or "").strip().upper() == "HR": return True
    
    # ВСЕ ОСТАЛЬНЫЕ — только по галочке из JSON permissions
    perms = user.get("permissions")
    if isinstance(perms, str):
        try: perms = json.loads(perms)
        except Exception: perms = {}
        
    if not isinstance(perms, dict):
        return False
        
    val = perms.get(perm)
    
    # ИСПРАВЛЕНИЕ: Жесткая проверка на булево значение или строку "true"/"1"
    if val is True or val == 1 or val == "1" or (isinstance(val, str) and val.lower() == "true"):
        return True
    return False

def _is_hr_or_super(user):
    if not user: return False
    return user.get("is_super_admin") or (user.get("position") or "").strip().upper() == "HR"

def _is_tu(user):
    if not user: return False
    if _is_hr_or_super(user): return False
    return "территориальный" in (user.get("position") or "").lower()

def _sync_get_tu_rests(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM restaurants WHERE territory_manager_id = %s", (user_id,))
            return [r[0] for r in cur.fetchall()]

async def get_auth_user(request):
    try:
        token = request.query.get("token") or request.query.get("webToken")
        if not token:
            body = await request.json()
            token = body.get("webToken") or ""
    except Exception:
        return None, 401
        
    if not token: return None, 401
    user_id = await _run(_sync_get_session_user, token)
    if not user_id: return None, 401
    user = await _run(_sync_get_user, user_id)
    if not user: return None, 401
    if user.get("is_fired"): return None, "fired"
    return user, None

def denied(status):
    if status == "fired": return web.json_response({"error": "fired"}, status=403)
    if status == 403: return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"error": "unauthorized"}, status=401)

def require_perm(user, perm):
    if not _sync_user_has_perm(user, perm):
        return web.json_response({"error": "forbidden"}, status=403)
    return None

async def get_admin_user(request):
    user, err = await get_auth_user(request)
    if err: return None, err
    if not user.get("is_admin"): return None, 403
    return user, None
