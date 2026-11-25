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


def validate_template(body):
    if not isinstance(body, dict):
        raise ValueError("invalid_template")
    title = body.get("title")
    sections = body.get("sections")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValueError("invalid_title")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 50:
        raise ValueError("invalid_sections")
    total = 0
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("title"), str) or not section["title"].strip() or len(section["title"]) > 200:
            raise ValueError("invalid_section")
        questions = section.get("questions")
        if not isinstance(questions, list) or not questions:
            raise ValueError("invalid_questions")
        total += len(questions)
        for q in questions:
            if not isinstance(q, dict) or not isinstance(q.get("text"), str) or not q["text"].strip() or len(q["text"]) > 1000:
                raise ValueError("invalid_question")
            if q.get("type") not in ("yes_no_na", "number", "temperature", "text", "photo"):
                raise ValueError("invalid_type")
            if type(q.get("weight")) is not int or not 0 <= q["weight"] <= 100:
                raise ValueError("invalid_weight")
            for flag in ("required", "critical", "photo_required", "comment_required", "create_task"):
                if type(q.get(flag, False)) is not bool:
                    raise ValueError("invalid_flag")
    if total > 500:
        raise ValueError("too_many_questions")
    return {"title": title.strip(), "sections": sections}

async def template_editor(request):
    user = await control_user(request)
    if not user:
        return None
    # Network-wide templates are restricted to superadmins until scoped editing is implemented.
    return user if user.get("is_super_admin") else None

@routes.post("/api/control/templates")
async def templates(request):
    if not await template_editor(request):
        return web.json_response({"error": "Доступ запрещён"}, status=403, headers=NO_STORE)
    async with db.get_pool(request.app).acquire() as conn:
        rows = await conn.fetch("""SELECT t.id,t.title,v.version,v.definition
            FROM control_templates t JOIN LATERAL
            (SELECT version,definition FROM control_template_versions WHERE template_id=t.id ORDER BY version DESC LIMIT 1) v ON TRUE
            ORDER BY t.id DESC LIMIT 200""")
    items = []
    for row in rows:
        item = dict(row)
        if isinstance(item["definition"], str):
            item["definition"] = json.loads(item["definition"])
        items.append(item)
    return web.json_response({"templates": items}, headers=NO_STORE)

@routes.post("/api/control/templates/save")
async def save_template(request):
    user = await template_editor(request)
    if not user:
        return web.json_response({"error": "Доступ запрещён"}, status=403, headers=NO_STORE)
    try:
        body = await request.json()
        definition = validate_template(body)
        tid = body.get("id")
        if tid is not None and (type(tid) is not int or tid <= 0):
            raise ValueError("invalid_id")
        expected = body.get("version")
        if tid is not None and (type(expected) is not int or expected <= 0):
            raise ValueError("invalid_version")
    except (ValueError, TypeError) as exc:
        return web.json_response({"error": str(exc)[:100]}, status=400, headers=NO_STORE)
    async with db.get_pool(request.app).acquire() as conn:
        async with conn.transaction():
            if tid is None:
                tid = await conn.fetchval("INSERT INTO control_templates(title,created_by) VALUES($1,$2) RETURNING id", definition["title"], user["user_id"])
                version = 1
            else:
                if not await conn.fetchval("SELECT id FROM control_templates WHERE id=$1 FOR UPDATE", tid):
                    return web.json_response({"error": "not_found"}, status=404, headers=NO_STORE)
                current = await conn.fetchval("SELECT MAX(version) FROM control_template_versions WHERE template_id=$1", tid)
                if current != expected:
                    return web.json_response({"error": "version_conflict"}, status=409, headers=NO_STORE)
                version = current + 1
                await conn.execute("UPDATE control_templates SET title=$1 WHERE id=$2", definition["title"], tid)
            await conn.execute("INSERT INTO control_template_versions(template_id,version,definition) VALUES($1,$2,$3::jsonb)", tid, version, json.dumps(definition, ensure_ascii=False))
    return web.json_response({"id": tid, "version": version}, headers=NO_STORE)
