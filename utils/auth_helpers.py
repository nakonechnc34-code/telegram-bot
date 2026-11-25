import secrets
import json
import logging
from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from config import SESSION_TTL_DAYS

logger = logging.getLogger(__name__)

def _sync_get_user(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()


def _sync_get_session_user(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            # Проверка срока и продление выполняются одной операцией в БД.
            cur.execute(
                "UPDATE web_sessions SET last_used_at = NOW() "
                "WHERE token = %s AND last_used_at > NOW() - %s * INTERVAL '1 day' "
                "RETURNING user_id",
                (token, SESSION_TTL_DAYS),
            )
            row = cur.fetchone()
            return row[0] if row else None


def _sync_create_session(user_id):
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO web_sessions (token, user_id, last_used_at) VALUES (%s,%s,NOW())", (token, user_id))
    return token


def _sync_delete_session(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
            return cur.rowcount > 0


def _sync_user_has_perm(user, perm):
    if not user:
        return False

    if _is_hr_or_super(user):
        return True

    perms = user.get("permissions")
    if isinstance(perms, str):
        try:
            perms = json.loads(perms)
        except Exception:
            perms = {}

    if not isinstance(perms, dict):
        return False

    val = perms.get(perm)
    if val is True or val == 1 or val == "1" or (isinstance(val, str) and val.lower() == "true"):
        return True
    return False


def _is_hr_position(position):
    return isinstance(position, str) and position.strip().upper() == "HR"


def _is_hr_or_super(user):
    return bool(user and (
        user.get("is_super_admin") or (user.get("is_admin") and _is_hr_position(user.get("position")))
    ))


def _is_tu(user):
    if not user:
        return False
    if _is_hr_or_super(user):
        return False
    return "территориальный" in (user.get("position") or "").lower()


def _sync_get_tu_rests(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM restaurants WHERE territory_manager_id = %s", (user_id,))
            return [r[0] for r in cur.fetchall()]


# ===================== EXTRACT TOKEN =====================
async def _extract_token(request, *, allow_query=True):
    """
    Единый способ извлечь токен из запроса.
    Приоритет:
      1) Authorization: Bearer <token>   — современный
      2) X-Token                         — для multipart/form-data
      3) query (?token= / ?webToken=)    — для скачивания файлов
      4) body JSON {webToken|token}      — LEGACY, для index.html/timesheet.html
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    x_token = request.headers.get("X-Token", "").strip()
    if x_token:
        return x_token

    if allow_query:
        token = request.query.get("token") or request.query.get("webToken")
        if token:
            return token

    if request.method == "POST":
        ctype = request.headers.get("Content-Type", "")
        if "application/json" in ctype:
            try:
                body_bytes = await request.read()
                if body_bytes:
                    body = json.loads(body_bytes)
                    if isinstance(body, dict):
                        token = body.get("webToken") or body.get("token")
                        if isinstance(token, str) and token:
                            logger.warning(
                                "[AUTH] Token via body (legacy). path=%s user_agent=%s",
                                request.path, request.headers.get("User-Agent", "-")
                            )
                            return token
            except Exception:
                pass

    return None


# ===================== GET AUTH USER =====================
async def get_auth_user(request):
    token = await _extract_token(request)
    if not token:
        return None, 401

    user_id = await _run(_sync_get_session_user, token)
    if not user_id:
        return None, 401

    user = await _run(_sync_get_user, user_id)
    if not user:
        return None, 401
    if user.get("is_fired") or (user.get("position") or "").strip().casefold()=="тайный гость":
        return None, "fired"
    return user, None


def denied(status):
    if status == "fired":
        return web.json_response({"error": "fired"}, status=403)
    if status == 403:
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"error": "unauthorized"}, status=401)


def require_perm(user, perm):
    if not _sync_user_has_perm(user, perm):
        return web.json_response({"error": "forbidden"}, status=403)
    return None


async def get_admin_user(request):
    user, err = await get_auth_user(request)
    if err:
        return None, err
    if not (user.get("is_admin") or user.get("is_super_admin")):
        return None, 403
    return user, None
