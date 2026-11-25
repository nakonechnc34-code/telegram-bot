"""Independent CONTROL authentication and scoped restaurant directory."""
import hashlib
import json
import secrets
from aiohttp import web
import db
from middleware.rate_limit import get_client_ip
from utils.security import validate_login_data, verify_password, _check_rate_limit, _reset_rate_limit
from routes.auth import _sync_get_user_by_login
from utils.auth_helpers import _is_tu, _sync_get_tu_rests

routes = web.RouteTableDef()
NO_STORE = {"Cache-Control": "no-store"}

def control_allowed(user):
    if not user or user.get("is_fired"):
        return False
    if user.get("is_super_admin"):
        return True
    perms = user.get("permissions")
    if isinstance(perms, str):
        try:
            perms = json.loads(perms)
        except (ValueError, TypeError):
            return False
    return isinstance(perms, dict) and perms.get("control_access") is True

def token_hash(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    if not 32 <= len(token) <= 256:
        return None
    return hashlib.sha256(token.encode()).hexdigest()

async def control_user(request):
    digest = token_hash(request)
    if not digest:
        return None
    async with db.get_pool(request.app).acquire() as conn:
        row = await conn.fetchrow("""SELECT u.* FROM control_sessions s
            JOIN users u ON u.user_id=s.user_id
            WHERE s.token_hash=$1 AND s.expires_at>NOW()""", digest)
    user = dict(row) if row else None
    return user if control_allowed(user) else None

@routes.post("/api/control/login")
async def login(request):
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError()
    except (ValueError, TypeError):
        return web.json_response({"error": "Некорректный запрос"}, status=400, headers=NO_STORE)
    data, err = validate_login_data(body)
    if err:
        return web.json_response({"error": "Некорректные данные"}, status=400, headers=NO_STORE)
    ip = get_client_ip(request)
    if not _check_rate_limit(ip):
        return web.json_response({"error": "Слишком много попыток"}, status=429, headers=NO_STORE)
    user = await db._run(_sync_get_user_by_login, data["login"])
    if not user or not verify_password(data["password"], user.get("password_hash") or "") or not control_allowed(user):
        return web.json_response({"error": "Неверные данные или доступ не назначен"}, status=401, headers=NO_STORE)
    _reset_rate_limit(ip)
    token = secrets.token_urlsafe(48)
    async with db.get_pool(request.app).acquire() as conn:
        await conn.execute("INSERT INTO control_sessions(token_hash,user_id) VALUES($1,$2)",
                           hashlib.sha256(token.encode()).hexdigest(), user["user_id"])
    return web.json_response({"token": token}, headers=NO_STORE)

@routes.post("/api/control/logout")
async def logout(request):
    digest = token_hash(request)
    if digest:
        async with db.get_pool(request.app).acquire() as conn:
            await conn.execute("DELETE FROM control_sessions WHERE token_hash=$1", digest)
    return web.json_response({"ok": True}, headers=NO_STORE)

@routes.post("/api/control/me")
async def me(request):
    user = await control_user(request)
    if not user:
        return web.json_response({"error": "Доступ запрещён"}, status=403, headers=NO_STORE)
    return web.json_response({"full_name": user.get("full_name"), "position": user.get("position")}, headers=NO_STORE)

@routes.post("/api/control/restaurants")
async def restaurants(request):
    user = await control_user(request)
    if not user:
        return web.json_response({"error": "Доступ запрещён"}, status=403, headers=NO_STORE)
    if user.get("is_super_admin"):
        allowed = None
    elif _is_tu(user):
        allowed = await db._run(_sync_get_tu_rests, user["user_id"])
    else:
        allowed = [user["restaurant_key"]] if user.get("restaurant_key") else []
    async with db.get_pool(request.app).acquire() as conn:
        rows = await conn.fetch("SELECT key,name FROM restaurants ORDER BY name")
    return web.json_response({"restaurants": [dict(r) for r in rows if allowed is None or r["key"] in allowed]}, headers=NO_STORE)
