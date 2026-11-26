"""Independent CONTROL authentication and scoped restaurant directory."""
import asyncio
import hashlib
import hmac
import os
import json
import secrets
from aiohttp import web
import db
from middleware.rate_limit import get_client_ip
from utils.security import validate_login_data, verify_password, _check_rate_limit, _reset_rate_limit
from routes.auth import _sync_get_user_by_login
from utils.auth_helpers import _is_tu, _sync_get_tu_rests, _is_hr_or_super

routes = web.RouteTableDef()
NO_STORE = {"Cache-Control": "no-store"}

def is_mystery_guest(user):
    return (user.get("position") or "").strip().casefold()=="тайный гость" and not user.get("is_super_admin")

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
    return (isinstance(perms, dict) and perms.get("control_access") is True
            and bool(user.get("is_admin") or _is_tu(user) or control_is_us(user) or is_mystery_guest(user)
                     or perms.get("control_view_all") is True or perms.get("control_manage") is True))

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
    if not control_allowed(user):
        return None
    if is_mystery_guest(user) and request.path not in (
        "/api/control/me","/api/control/checks","/api/control/checks/complete","/api/control/checks/photo"
    ):
        return None
    return user

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
    return web.json_response({"full_name": "Тайный гость" if is_mystery_guest(user) else user.get("full_name"), "position": user.get("position"), "template_editor":control_template_edit(user),"mystery_guest":is_mystery_guest(user)}, headers=NO_STORE)

@routes.post("/api/control/restaurants")
async def restaurants(request):
    user = await control_user(request)
    if not user:
        return web.json_response({"error": "Доступ запрещён"}, status=403, headers=NO_STORE)
    allowed = await restaurant_scope(user)
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
    category=body.get("category","checklist")
    if category not in ("checklist","audit","mystery_guest"):
        raise ValueError("invalid_category")
    return {"title": title.strip(), "sections": sections,"category":category}

async def template_editor(request):
    user = await control_user(request)
    if not user:
        return None
    return user if control_template_edit(user) else None

@routes.post("/api/control/templates")
async def templates(request):
    user=await control_user(request)
    if not user or not (task_manager(user) or control_template_edit(user)):
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


def control_permission(user,key):
    perms=user.get("permissions")
    if isinstance(perms,str):
        try:
            perms=json.loads(perms)
        except (ValueError,TypeError):
            return False
    return isinstance(perms,dict) and perms.get(key) is True

def control_is_us(user):
    return (user.get("position") or "").strip().lower() in ("ус","управляющий смены","управляющий сменой","управляющий сменой ресторана")

def control_network_view(user):
    if not control_allowed(user) or is_mystery_guest(user):
        return False
    if user.get("is_super_admin"):
        return True
    if control_is_us(user):
        return False
    return bool(_is_tu(user) or control_permission(user,"control_view_all"))

def control_template_edit(user):
    return bool(control_allowed(user) and not is_mystery_guest(user) and (user.get("is_super_admin") or (user.get("is_admin") and not control_is_us(user))))

async def restaurant_scope(user):
    if not control_allowed(user) or is_mystery_guest(user):
        return []
    if control_network_view(user):
        return None
    return [user["restaurant_key"]] if user.get("restaurant_key") else []


def score_check(definition, answers, photo_keys=()):
    if not isinstance(answers, dict):
        raise ValueError("invalid_answers")
    questions = {f"{i}:{j}": q for i, section in enumerate(definition["sections"]) for j,q in enumerate(section["questions"])}
    if set(answers) - set(questions):
        raise ValueError("unknown_question")
    earned = possible = 0
    violations = []
    for key,q in questions.items():
        answer = answers.get(key)
        if answer is None:
            if q.get("required") or q.get("critical"):
                raise ValueError("required_answer")
            continue
        # Only yes/no/NA checks are supported by this execution stage.
        if q["type"] != "yes_no_na" or answer not in ("yes","no","na"):
            raise ValueError("unsupported_answer")
        if answer == "na":
            if q.get("critical"):
                raise ValueError("critical_na")
            continue
        if q.get("photo_required") and key not in photo_keys:
            raise ValueError("photo_required")
        if q.get("comment_required"):
            raise ValueError("evidence_not_supported")
        possible += q["weight"]
        if answer == "yes":
            earned += q["weight"]
        else:
            violations.append((key,q))
    return (round(100*earned/possible,2) if possible else None), violations

def guest_alias(user_id):
    secret = os.environ.get("CONTROL_GUEST_ALIAS_SECRET")
    if not secret:
        raise web.HTTPServiceUnavailable(text="Guest alias configuration required")
    return hmac.new(secret.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()


@routes.post("/api/control/guests")
async def list_guests(request):
    user = await control_user(request)
    if not user or not task_manager(user) or is_mystery_guest(user):
        return web.json_response({"error": "Доступ запрещён"}, status=403, headers=NO_STORE)
    async with db.get_pool(request.app).acquire() as conn:
        rows = await conn.fetch("SELECT user_id, full_name, position, is_fired, is_super_admin, permissions FROM users WHERE lower(btrim(position)) = $1 ORDER BY full_name, user_id", "тайный гость")
    guests = []
    for row in rows:
        if not is_mystery_guest(dict(row)) or not control_allowed(dict(row)):
            continue
        if _is_hr_or_super(user):
            guests.append({"id": str(row["user_id"]), "name": row["full_name"] or "Тайный гость"})
        else:
            guests.append({"id": guest_alias(row["user_id"]), "name": "Тайный гость " + guest_alias(row["user_id"])[:10]})
    guests.sort(key=lambda item: item["name"])
    return web.json_response({"guests": guests}, headers=NO_STORE)


@routes.post("/api/control/checks/assign")
async def assign_check(request):
    user=await control_user(request)
    if not user or not task_manager(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    from datetime import datetime
    try:
        body = await request.json()
        if not isinstance(body,dict):
            raise ValueError()
        key, tid, version = body["restaurant_key"],body["template_id"],body["version"]
        due = datetime.fromisoformat(body["due_at"])
        if not isinstance(key,str) or type(tid) is not int or type(version) is not int or due.tzinfo is None:
            raise ValueError()
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_assignment"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    if scope is not None and key not in scope:
        return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
    async with db.get_pool(request.app).acquire() as conn:
        row = await conn.fetchrow("SELECT id,definition FROM control_template_versions WHERE template_id=$1 AND version=$2",tid,version)
        if not row or not await conn.fetchval("SELECT 1 FROM restaurants WHERE key=$1",key):
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        definition = json.loads(row["definition"]) if isinstance(row["definition"],str) else row["definition"]
        if any(q["type"]!="yes_no_na" or q.get("comment_required") for sec in definition["sections"] for q in sec["questions"]):
            return web.json_response({"error":"Шаблон требует ещё не реализованных типов ответов или доказательств"},status=400,headers=NO_STORE)
        if definition.get("category")=="mystery_guest":
            guest=body.get("guest_id")
            if not _is_hr_or_super(user):
                if not isinstance(guest, str) or len(guest) != 64 or any(ch not in "0123456789abcdef" for ch in guest):
                    return web.json_response({"error":"Выберите тайного гостя"},status=400,headers=NO_STORE)
                candidates = await conn.fetch("SELECT user_id FROM users WHERE lower(btrim(position)) = $1", "тайный гость")
                guest = next((r["user_id"] for r in candidates if hmac.compare_digest(guest_alias(r["user_id"]), guest)), None)
            if isinstance(guest, str) and 1 <= len(guest) <= 19 and guest.isascii() and guest.isdecimal():
                guest = int(guest)
            if type(guest) is not int or not 0<guest<2**63:
                return web.json_response({"error":"Укажите ID тайного гостя"},status=400,headers=NO_STORE)
            target=await conn.fetchrow("SELECT * FROM users WHERE user_id=$1",guest)
            if not target or not is_mystery_guest(dict(target)) or not control_allowed(dict(target)):
                return web.json_response({"error":"Недоступный тайный гость"},status=400,headers=NO_STORE)
        else:
            guest=None
        cid = await conn.fetchval("""INSERT INTO control_checks(restaurant_key,version_id,assigned_by,due_at,guest_id)
            VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING RETURNING id""",key,row["id"],user["user_id"],due,guest)
    return web.json_response({"id":cid},status=201 if cid else 409,headers=NO_STORE)

@routes.post("/api/control/checks")
async def list_checks(request):
    user = await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    scope = await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows = await conn.fetch("""SELECT c.id,c.restaurant_key,c.due_at,c.completed_at,c.score,v.definition
            FROM control_checks c JOIN control_template_versions v ON v.id=c.version_id
            WHERE (CASE WHEN $2::bigint IS NOT NULL THEN c.guest_id=$2 AND v.definition->>'category'='mystery_guest' ELSE ($1::text[] IS NULL OR c.restaurant_key=ANY($1)) END) ORDER BY c.due_at DESC LIMIT 200""",scope,user['user_id'] if is_mystery_guest(user) else None)
    items=[]
    for row in rows:
        item=dict(row)
        for key in ("due_at","completed_at"):
            item[key]=item[key].isoformat() if item[key] else None
        item["score"]=float(item["score"]) if item["score"] is not None else None
        if isinstance(item["definition"],str):
            item["definition"]=json.loads(item["definition"])
        items.append(item)
    return web.json_response({"checks":items},headers=NO_STORE)

@routes.post("/api/control/checks/complete")
async def complete_check(request):
    user = await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        if not isinstance(body,dict) or type(body.get("id")) is not int:
            raise ValueError()
    except (ValueError,TypeError):
        return web.json_response({"error":"invalid_check"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("""SELECT c.*,v.definition FROM control_checks c JOIN control_template_versions v ON v.id=c.version_id
                WHERE c.id=$1 AND (CASE WHEN $3::bigint IS NOT NULL THEN c.guest_id=$3 AND v.definition->>'category'='mystery_guest' ELSE c.guest_id IS NULL AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2)) END) FOR UPDATE OF c""",body["id"],scope,user['user_id'] if is_mystery_guest(user) else None)
            if not row:
                return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
            if row["completed_at"]:
                return web.json_response({"error":"already_completed"},status=409,headers=NO_STORE)
            definition=json.loads(row["definition"]) if isinstance(row["definition"],str) else row["definition"]
            try:
                photos=await conn.fetch("SELECT question_key FROM control_check_photos WHERE check_id=$1",row["id"])
                score,violations=score_check(definition,body.get("answers"),{p["question_key"] for p in photos})
            except ValueError as exc:
                return web.json_response({"error":str(exc)},status=400,headers=NO_STORE)
            await conn.execute("UPDATE control_checks SET completed_at=NOW(),completed_by=$1,answers=$2::jsonb,score=$3 WHERE id=$4",user["user_id"],json.dumps(body["answers"]),score,row["id"])
            for key,q in violations:
                if q.get("create_task") or q.get("critical"):
                    await conn.execute("INSERT INTO control_tasks(check_id,question_key,description,critical) VALUES($1,$2,$3,$4)",row["id"],key,q["text"],bool(q.get("critical")))
    return web.json_response({"score":score,"violations":len(violations)},headers=NO_STORE)


def task_manager(user):
    if not control_allowed(user) or is_mystery_guest(user):
        return False
    if user.get("is_super_admin") or _is_tu(user):
        return True
    perms=user.get("permissions")
    if isinstance(perms,str):
        try:
            perms=json.loads(perms)
        except (ValueError,TypeError):
            return False
    return isinstance(perms,dict) and perms.get("control_manage") is True

def task_transition(status, action, manager, assigned, comment):
    if action == "start" and status == "new" and assigned:
        return "in_progress"
    if action == "submit" and status == "in_progress" and assigned and comment:
        return "review"
    if action == "approve" and status == "review" and manager and not assigned:
        return "closed"
    if action == "return" and status == "review" and manager and not assigned and comment:
        return "in_progress"
    raise ValueError("invalid_transition")

@routes.post("/api/control/tasks")
async def list_tasks(request):
    user = await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    scope = await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows = await conn.fetch("""SELECT t.*,c.restaurant_key, CASE WHEN $4::boolean OR NOT EXISTS (SELECT 1 FROM users g WHERE g.user_id=t.assignee_id AND lower(btrim(COALESCE(g.position, '')))='тайный гость') THEN t.assignee_id ELSE NULL END AS assignee_id,
            (t.due_at<NOW() AND t.status!='closed') AS overdue
            FROM control_tasks t JOIN control_checks c ON c.id=t.check_id
            WHERE ($1::text[] IS NULL OR c.restaurant_key=ANY($1))
            AND ($2::boolean OR t.assignee_id=$3)
            ORDER BY t.critical DESC,t.id DESC LIMIT 200""",scope,task_manager(user),user["user_id"],_is_hr_or_super(user))
    items=[]
    for row in rows:
        item=dict(row)
        for key in ("created_at","due_at"):
            item[key]=item[key].isoformat() if item[key] else None
        items.append(item)
    return web.json_response({"tasks":items,"manager":task_manager(user),"user_id":user["user_id"]},headers=NO_STORE)

@routes.post("/api/control/tasks/change")
async def change_task(request):
    from datetime import datetime
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        if not isinstance(body,dict) or type(body.get("id")) is not int:
            raise ValueError()
        action=body.get("action")
        comment=body.get("comment","")
        if not isinstance(comment,str) or len(comment)>4000:
            raise ValueError()
        comment=comment.strip()
    except (ValueError,TypeError):
        return web.json_response({"error":"invalid_request"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    manager=task_manager(user)
    async with db.get_pool(request.app).acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("""SELECT t.*,c.restaurant_key FROM control_tasks t
                JOIN control_checks c ON c.id=t.check_id WHERE t.id=$1
                AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2)) FOR UPDATE OF t""",body["id"],scope)
            if not row or (not manager and row["assignee_id"]!=user["user_id"]):
                return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
            details={"comment":comment,"previous_status":row["status"]}
            if action=="assign":
                if not manager or row["status"] not in ("new","in_progress"):
                    return web.json_response({"error":"forbidden"},status=403,headers=NO_STORE)
                try:
                    assignee=body["assignee_id"]
                    due=datetime.fromisoformat(body["due_at"])
                    if type(assignee) is not int or due.tzinfo is None:
                        raise ValueError()
                except (ValueError,TypeError,KeyError):
                    return web.json_response({"error":"invalid_assignment"},status=400,headers=NO_STORE)
                target=await conn.fetchrow("SELECT * FROM users WHERE user_id=$1 AND restaurant_key=$2",assignee,row["restaurant_key"])
                if not target or is_mystery_guest(dict(target)) or not control_allowed(dict(target)):
                    return web.json_response({"error":"invalid_assignee"},status=400,headers=NO_STORE)
                await conn.execute("UPDATE control_tasks SET assignee_id=$1,due_at=$2 WHERE id=$3",assignee,due,row["id"])
                details.update({"assignee_id":assignee,"due_at":due.isoformat(),"previous_assignee_id":row["assignee_id"]})
                status=row["status"]
            else:
                try:
                    status=task_transition(row["status"],action,manager,row["assignee_id"]==user["user_id"],comment)
                except ValueError as exc:
                    return web.json_response({"error":str(exc)},status=409,headers=NO_STORE)
                if action=="submit":
                    import base64
                    try:
                        encoded=body.get("photo")
                        if not isinstance(encoded,str) or len(encoded)>6990510:
                            raise ValueError()
                        data=base64.b64decode(encoded,validate=True)
                        data,mime=await asyncio.to_thread(sanitize_photo,data)
                    except (ValueError,TypeError):
                        return web.json_response({"error":"Требуется фото устранения JPG или PNG до 5 МБ"},status=400,headers=NO_STORE)
                    pid=await conn.fetchval("""INSERT INTO control_task_photos(task_id,uploaded_by,content_type,content)
                        VALUES($1,$2,$3,$4) RETURNING id""",row["id"],user["user_id"],mime,data)
                    details["photo_id"]=pid
                await conn.execute("UPDATE control_tasks SET status=$1 WHERE id=$2",status,row["id"])
            details["status"]=status
            await conn.execute("INSERT INTO control_task_history(task_id,actor_id,action,details) VALUES($1,$2,$3,$4::jsonb)",row["id"],user["user_id"],action,json.dumps(details,ensure_ascii=False))
    return web.json_response({"status":status},headers=NO_STORE)

@routes.post("/api/control/tasks/history")
async def task_history(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        if not isinstance(body,dict) or type(body.get("id")) is not int:
            raise ValueError()
    except (ValueError,TypeError):
        return web.json_response({"error":"invalid_request"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""SELECT CASE WHEN $5::boolean OR NOT EXISTS (SELECT 1 FROM users g WHERE g.user_id=h.actor_id AND lower(btrim(COALESCE(g.position, '')))='тайный гость') THEN h.actor_id ELSE NULL END AS actor_id,h.action,
            CASE WHEN $5::boolean THEN h.details ELSE h.details::jsonb - 'assignee_id' - 'previous_assignee_id' END AS details,h.created_at FROM control_task_history h
            JOIN control_tasks t ON t.id=h.task_id JOIN control_checks c ON c.id=t.check_id
            WHERE t.id=$1 AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2))
            AND ($3::boolean OR t.assignee_id=$4) ORDER BY h.id""",body["id"],scope,task_manager(user),user["user_id"],_is_hr_or_super(user))
    return web.json_response({"history":[{"actor_id":r["actor_id"],"action":r["action"],"details":json.loads(r["details"]) if isinstance(r["details"],str) else r["details"],"created_at":r["created_at"].isoformat()} for r in rows]},headers=NO_STORE)


HACCP_KINDS = {"fridge":"°C","freezer":"°C","food_temperature":"°C","fryer_oil":"%","equipment":"ед."}

def reading_number(value):
    from decimal import Decimal, InvalidOperation
    if type(value) not in (int,float,str):
        raise ValueError("invalid_number")
    try:
        number=Decimal(str(value))
        if not number.is_finite() or abs(number)>1000000 or number.as_tuple().exponent < -4:
            raise ValueError("invalid_number")
        return number
    except InvalidOperation:
        raise ValueError("invalid_number")

def reading_deviation(value, lower, upper):
    return not lower <= value <= upper

def journal_json(row):
    from decimal import Decimal
    from datetime import datetime
    return {k: str(v) if isinstance(v,Decimal) else v.isoformat() if isinstance(v,datetime) else v for k,v in dict(row).items()}

@routes.post("/api/control/haccp/equipment")
async def haccp_equipment(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""SELECT e.*,r.value AS last_value,r.recorded_at AS last_recorded_at,r.deviation AS last_deviation
            FROM control_equipment e LEFT JOIN LATERAL
            (SELECT value,recorded_at,deviation FROM control_readings WHERE equipment_id=e.id ORDER BY id DESC LIMIT 1) r ON TRUE
            WHERE ($1::text[] IS NULL OR e.restaurant_key=ANY($1)) ORDER BY e.restaurant_key,e.name LIMIT 500""",scope)
    return web.json_response({"equipment":[journal_json(r) for r in rows],"manager":task_manager(user),"kinds":HACCP_KINDS},headers=NO_STORE)

@routes.post("/api/control/haccp/equipment/save")
async def haccp_save_equipment(request):
    user=await control_user(request)
    if not user or not task_manager(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        key,name,kind=body["restaurant_key"],body["name"],body["kind"]
        if not all(isinstance(x,str) for x in (key,name,kind)) or not name.strip() or len(name)>200 or kind not in HACCP_KINDS:
            raise ValueError()
        lower,upper=reading_number(body["lower_limit"]),reading_number(body["upper_limit"])
        if lower>upper:
            raise ValueError()
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_equipment"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    if scope is not None and key not in scope:
        return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
    async with db.get_pool(request.app).acquire() as conn:
        if not await conn.fetchval("SELECT 1 FROM restaurants WHERE key=$1",key):
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        eid=await conn.fetchval("""INSERT INTO control_equipment(restaurant_key,name,kind,unit,lower_limit,upper_limit,created_by)
            VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id""",key,name.strip(),kind,HACCP_KINDS[kind],lower,upper,user["user_id"])
    return web.json_response({"id":eid},status=201,headers=NO_STORE)

@routes.post("/api/control/haccp/readings/add")
async def haccp_add_reading(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        eid=body["equipment_id"]
        value=reading_number(body["value"])
        comment=body.get("comment","")
        if type(eid) is not int or not isinstance(comment,str) or len(comment)>4000:
            raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError):
        return web.json_response({"error":"invalid_reading"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        async with conn.transaction():
            e=await conn.fetchrow("SELECT * FROM control_equipment WHERE id=$1 AND ($2::text[] IS NULL OR restaurant_key=ANY($2)) FOR SHARE",eid,scope)
            if not e:
                return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
            deviation=reading_deviation(value,e["lower_limit"],e["upper_limit"])
            if deviation and not comment.strip():
                return web.json_response({"error":"Укажите комментарий к отклонению"},status=400,headers=NO_STORE)
            rid=await conn.fetchval("""INSERT INTO control_readings(equipment_id,value,lower_limit,upper_limit,deviation,comment,recorded_by)
                VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING id""",eid,value,e["lower_limit"],e["upper_limit"],deviation,comment.strip(),user["user_id"])
    return web.json_response({"id":rid,"deviation":deviation},status=201,headers=NO_STORE)

@routes.post("/api/control/haccp/readings")
async def haccp_readings(request):
    from datetime import date,timedelta
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        eid=body["equipment_id"]
        start,end=date.fromisoformat(body["start"]),date.fromisoformat(body["end"])
        if type(eid) is not int or not 0 <= (end-start).days <= 366:
            raise ValueError()
        exclusive=end+timedelta(days=1)
    except (ValueError,TypeError,KeyError,OverflowError):
        return web.json_response({"error":"invalid_period"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""SELECT r.* FROM control_readings r JOIN control_equipment e ON e.id=r.equipment_id
            WHERE e.id=$1 AND ($2::text[] IS NULL OR e.restaurant_key=ANY($2))
            AND r.recorded_at >= ($3::date::timestamp AT TIME ZONE 'Europe/Moscow')
            AND r.recorded_at < ($4::date::timestamp AT TIME ZONE 'Europe/Moscow')
            ORDER BY r.id DESC LIMIT 1001""",eid,scope,start,exclusive)
    return web.json_response({"readings":[journal_json(r) for r in rows[:1000]],"truncated":len(rows)>1000},headers=NO_STORE)


def next_schedule_due(due, frequency, anchor_day):
    from datetime import timedelta
    from calendar import monthrange
    from zoneinfo import ZoneInfo
    local=due.astimezone(ZoneInfo("Europe/Moscow"))
    if frequency in ("daily","weekly"):
        return local+timedelta(days=1 if frequency=="daily" else 7)
    if frequency!="monthly":
        raise ValueError("invalid_frequency")
    year,month=local.year+(local.month==12),local.month%12+1
    return local.replace(year=year,month=month,day=min(anchor_day,monthrange(year,month)[1]))

async def generate_scheduled_checks(app):
    async with db.get_pool(app).acquire() as conn:
        async with conn.transaction():
            rows=await conn.fetch("""SELECT * FROM control_schedules WHERE active AND next_due<=NOW()+INTERVAL '24 hours'
                ORDER BY next_due LIMIT 100 FOR UPDATE SKIP LOCKED""")
            for row in rows:
                due=row["next_due"]
                await conn.execute("""INSERT INTO control_checks(restaurant_key,version_id,assigned_by,due_at)
                    VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING""",row["restaurant_key"],row["version_id"],row["created_by"],due)
                await conn.execute("UPDATE control_schedules SET next_due=$1 WHERE id=$2",
                    next_schedule_due(due,row["frequency"],row["anchor_day"]),row["id"])

async def schedule_worker(app):
    import asyncio,logging
    while True:
        try:
            await generate_scheduled_checks(app)
        except Exception:
            logging.exception("CONTROL schedule generation failed")
        await asyncio.sleep(60)

@routes.post("/api/control/schedules")
async def list_schedules(request):
    user=await control_user(request)
    if not user or not task_manager(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""SELECT s.*,t.title FROM control_schedules s
            JOIN control_template_versions v ON v.id=s.version_id JOIN control_templates t ON t.id=v.template_id
            WHERE ($1::text[] IS NULL OR s.restaurant_key=ANY($1)) ORDER BY s.next_due LIMIT 500""",scope)
    return web.json_response({"schedules":[journal_json(r) for r in rows]},headers=NO_STORE)

@routes.post("/api/control/schedules/save")
async def save_schedule(request):
    from datetime import datetime,timezone
    from zoneinfo import ZoneInfo
    user=await control_user(request)
    if not user or not task_manager(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        b=await request.json()
        key,tid,version,freq=b["restaurant_key"],b["template_id"],b["version"],b["frequency"]
        due=datetime.fromisoformat(b["next_due"])
        if not isinstance(key,str) or type(tid) is not int or type(version) is not int or freq not in ("daily","weekly","monthly") or due.tzinfo is None or due<=datetime.now(timezone.utc):
            raise ValueError()
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_schedule"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    if scope is not None and key not in scope:
        return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
    async with db.get_pool(request.app).acquire() as conn:
        row=await conn.fetchrow("SELECT id,definition FROM control_template_versions WHERE template_id=$1 AND version=$2",tid,version)
        if not row or not await conn.fetchval("SELECT 1 FROM restaurants WHERE key=$1",key):
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        definition=json.loads(row["definition"]) if isinstance(row["definition"],str) else row["definition"]
        if any(q["type"]!="yes_no_na" or q.get("comment_required") for sec in definition["sections"] for q in sec["questions"]):
            return web.json_response({"error":"unsupported_template"},status=400,headers=NO_STORE)
        if definition.get("category")=="mystery_guest":
            return web.json_response({"error":"Назначьте тайного гостя вручную"},status=400,headers=NO_STORE)
        sid=await conn.fetchval("""INSERT INTO control_schedules(restaurant_key,version_id,created_by,frequency,next_due,anchor_day)
            VALUES($1,$2,$3,$4,$5,$6) RETURNING id""",key,row["id"],user["user_id"],freq,due,due.astimezone(ZoneInfo("Europe/Moscow")).day)
    return web.json_response({"id":sid},status=201,headers=NO_STORE)

@routes.post("/api/control/schedules/pause")
async def pause_schedule(request):
    user=await control_user(request)
    if not user or not task_manager(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        b=await request.json()
        if type(b.get("id")) is not int:
            raise ValueError()
    except (ValueError,TypeError,AttributeError):
        return web.json_response({"error":"invalid_id"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        sid=await conn.fetchval("UPDATE control_schedules SET active=FALSE WHERE id=$1 AND ($2::text[] IS NULL OR restaurant_key=ANY($2)) RETURNING id",b["id"],scope)
    return web.json_response({"ok":bool(sid)},status=200 if sid else 404,headers=NO_STORE)


@routes.post("/api/control/academy/statistics")
async def academy_statistics(request):
    user=await control_user(request)
    if not user or not task_manager(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        if not isinstance(body,dict):
            raise ValueError()
        key=body.get("restaurant_key")
        if key is not None and (not isinstance(key,str) or not key or len(key)>200):
            raise ValueError()
    except (ValueError,TypeError):
        return web.json_response({"error":"invalid_filter"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    if key is not None:
        if scope is not None and key not in scope:
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        scope=[key]
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""SELECT u.user_id,u.full_name,u.restaurant_key,
            COUNT(DISTINCT r.course_id) AS attempted_courses,
            COUNT(DISTINCT r.course_id) FILTER (WHERE r.passed) AS passed_courses,
            COUNT(r.course_id) AS attempts
            FROM users u LEFT JOIN academy_test_results r ON r.user_id=u.user_id
            WHERE NOT COALESCE(u.is_fired,FALSE)
            AND lower(btrim(COALESCE(u.position, ''))) <> 'тайный гость'
            AND ($1::text[] IS NULL OR u.restaurant_key=ANY($1))
            GROUP BY u.user_id,u.full_name,u.restaurant_key
            ORDER BY u.restaurant_key,u.full_name,u.user_id LIMIT 1001""",scope)
        courses=await conn.fetchval("SELECT COUNT(*) FROM academy_courses WHERE COALESCE(is_published,TRUE)")
    return web.json_response({"employees":[dict(r) for r in rows[:1000]],"published_courses":courses,"truncated":len(rows)>1000},headers=NO_STORE)


DOCUMENT_CATEGORIES=("standards","instructions","technology","sanitation","equipment","other")

def validate_document(body):
    if not isinstance(body,dict):
        raise ValueError("invalid_document")
    title,content,category=body.get("title"),body.get("content"),body.get("category")
    if not isinstance(title,str) or not title.strip() or len(title)>200:
        raise ValueError("invalid_title")
    if not isinstance(content,str) or not content.strip() or len(content)>100000:
        raise ValueError("invalid_content")
    if category not in DOCUMENT_CATEGORIES:
        raise ValueError("invalid_category")
    key=body.get("restaurant_key")
    if key is not None and (not isinstance(key,str) or not key or len(key)>200):
        raise ValueError("invalid_restaurant")
    return title.strip(),content.strip(),category,key

@routes.post("/api/control/documents")
async def documents(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""SELECT d.id,d.category,d.restaurant_key,v.id AS version_id,v.version,v.title,v.published_at,
            a.acknowledged_at FROM control_documents d JOIN LATERAL
            (SELECT * FROM control_document_versions WHERE document_id=d.id ORDER BY version DESC LIMIT 1) v ON TRUE
            LEFT JOIN control_acknowledgements a ON a.version_id=v.id AND a.user_id=$2
            WHERE NOT d.archived AND (d.restaurant_key IS NULL OR $1::text[] IS NULL OR d.restaurant_key=ANY($1))
            ORDER BY v.published_at DESC LIMIT 501""",scope,user["user_id"])
    return web.json_response({"documents":[journal_json(r) for r in rows[:500]],"truncated":len(rows)>500,"editor":bool(user.get("is_super_admin"))},headers=NO_STORE)

@routes.post("/api/control/documents/save")
async def save_document(request):
    user=await control_user(request)
    if not user or not user.get("is_super_admin"):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        b=await request.json()
        title,content,category,key=validate_document(b)
        did=b.get("id")
        expected=b.get("version")
        if did is not None and (type(did) is not int or did<=0 or type(expected) is not int or expected<=0):
            raise ValueError("invalid_version")
    except (ValueError,TypeError) as exc:
        return web.json_response({"error":str(exc)[:100]},status=400,headers=NO_STORE)
    async with db.get_pool(request.app).acquire() as conn:
        async with conn.transaction():
            if did is None:
                if key is not None and not await conn.fetchval("SELECT 1 FROM restaurants WHERE key=$1",key):
                    return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
                did=await conn.fetchval("INSERT INTO control_documents(category,restaurant_key,created_by) VALUES($1,$2,$3) RETURNING id",category,key,user["user_id"])
                version=1
            else:
                row=await conn.fetchrow("SELECT * FROM control_documents WHERE id=$1 AND NOT archived FOR UPDATE",did)
                if not row:
                    return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
                if row["restaurant_key"]!=key or row["category"]!=category:
                    return web.json_response({"error":"immutable_scope"},status=409,headers=NO_STORE)
                current=await conn.fetchval("SELECT MAX(version) FROM control_document_versions WHERE document_id=$1",did)
                if current!=expected:
                    return web.json_response({"error":"version_conflict"},status=409,headers=NO_STORE)
                version=current+1
            vid=await conn.fetchval("INSERT INTO control_document_versions(document_id,version,title,content,published_by) VALUES($1,$2,$3,$4,$5) RETURNING id",did,version,title,content,user["user_id"])
    return web.json_response({"id":did,"version":version,"version_id":vid},status=201,headers=NO_STORE)

@routes.post("/api/control/documents/read")
async def read_document(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        b=await request.json()
        vid=b["version_id"]
        if type(vid) is not int:
            raise ValueError()
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_id"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        row=await conn.fetchrow("""SELECT v.*,d.category,d.restaurant_key FROM control_document_versions v JOIN control_documents d ON d.id=v.document_id
            WHERE v.id=$1 AND NOT d.archived AND (d.restaurant_key IS NULL OR $2::text[] IS NULL OR d.restaurant_key=ANY($2))""",vid,scope)
    if not row:
        return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
    return web.json_response({"document":journal_json(row)},headers=NO_STORE)

@routes.post("/api/control/documents/acknowledge")
async def acknowledge_document(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        b=await request.json()
        vid=b["version_id"]
        if type(vid) is not int:
            raise ValueError()
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_id"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("""SELECT d.id FROM control_documents d JOIN control_document_versions v ON v.document_id=d.id
                WHERE v.id=$1 AND NOT d.archived AND (d.restaurant_key IS NULL OR $2::text[] IS NULL OR d.restaurant_key=ANY($2)) FOR SHARE OF d""",vid,scope)
            if not row:
                return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
            latest=await conn.fetchval("SELECT id FROM control_document_versions WHERE document_id=$1 ORDER BY version DESC LIMIT 1",row["id"])
            if latest!=vid:
                return web.json_response({"error":"version_changed"},status=409,headers=NO_STORE)
            await conn.execute("INSERT INTO control_acknowledgements(version_id,user_id) VALUES($1,$2) ON CONFLICT DO NOTHING",vid,user["user_id"])
    return web.json_response({"ok":True},headers=NO_STORE)

def photo_content_type(data):
    if not 0 < len(data) <= 5*1024*1024:
        raise ValueError("invalid_photo_size")
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB\x60\x82"):
        return "image/png"
    raise ValueError("invalid_photo_type")

def sanitize_photo(data):
    from io import BytesIO
    from PIL import Image, ImageOps
    mime = photo_content_type(data)
    expected = "JPEG" if mime == "image/jpeg" else "PNG"
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format != expected or source.width * source.height > 20_000_000 or getattr(source, "n_frames", 1) != 1:
                raise ValueError("invalid_photo")
            source.load()
            oriented = ImageOps.exif_transpose(source).convert("RGB")
            clean = Image.new("RGB", oriented.size)
            clean.paste(oriented)
            output = BytesIO()
            clean.save(output, format=expected, **({"quality": 88} if expected == "JPEG" else {}))
            result = output.getvalue()
            photo_content_type(result)
            return result, mime
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("invalid_photo") from exc

async def safe_photo_response(data):
    try:
        clean, mime = await asyncio.to_thread(sanitize_photo, bytes(data))
    except (ValueError, TypeError):
        return web.Response(status=404, headers=NO_STORE)
    return web.Response(body=clean, content_type=mime,
                        headers={**NO_STORE, "X-Content-Type-Options": "nosniff"})

@routes.post("/api/control/checks/photo")
async def upload_check_photo(request):
    import base64
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"forbidden"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        cid,key,encoded=body["id"],body["question_key"],body["photo"]
        if type(cid) is not int or not isinstance(key,str) or not isinstance(encoded,str) or len(encoded)>6990510:
            raise ValueError("invalid_photo")
        data=base64.b64decode(encoded,validate=True)
        data,mime=await asyncio.to_thread(sanitize_photo,data)
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_photo"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("""SELECT c.completed_at,v.definition FROM control_checks c
                JOIN control_template_versions v ON v.id=c.version_id WHERE c.id=$1
                AND (CASE WHEN $3::bigint IS NOT NULL THEN c.guest_id=$3 AND v.definition->>'category'='mystery_guest' ELSE c.guest_id IS NULL AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2)) END) FOR UPDATE OF c""",cid,scope,user['user_id'] if is_mystery_guest(user) else None)
            if not row:
                return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
            if row["completed_at"]:
                return web.json_response({"error":"already_completed"},status=409,headers=NO_STORE)
            definition=json.loads(row["definition"]) if isinstance(row["definition"],str) else row["definition"]
            keys={f"{i}:{j}" for i,sec in enumerate(definition["sections"]) for j,q in enumerate(sec["questions"])}
            if key not in keys:
                return web.json_response({"error":"unknown_question"},status=400,headers=NO_STORE)
            pid=await conn.fetchval("""INSERT INTO control_check_photos(check_id,question_key,uploaded_by,content_type,content)
                VALUES($1,$2,$3,$4,$5) ON CONFLICT(check_id,question_key) DO UPDATE SET
                uploaded_by=EXCLUDED.uploaded_by,content_type=EXCLUDED.content_type,content=EXCLUDED.content,created_at=NOW()
                RETURNING id""",cid,key,user["user_id"],mime,data)
    return web.json_response({"id":pid},headers=NO_STORE)

@routes.post("/api/control/checks/photos")
async def list_check_photos(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"forbidden"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        cid=body["id"]
        if type(cid) is not int:
            raise ValueError()
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_id"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""SELECT p.id,p.question_key,CASE WHEN $3::boolean OR (c.guest_id IS NULL AND NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id=p.uploaded_by AND lower(btrim(COALESCE(u.position, ''))) = 'тайный гость')) THEN p.uploaded_by ELSE NULL END AS uploaded_by,p.created_at FROM control_check_photos p
            JOIN control_checks c ON c.id=p.check_id WHERE c.id=$1 AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2))""",cid,scope,_is_hr_or_super(user))
    return web.json_response({"photos":[journal_json(r) for r in rows]},headers=NO_STORE)

@routes.get("/api/control/photos/{id:\\d+}")
async def get_check_photo(request):
    user=await control_user(request)
    if not user:
        return web.Response(status=403,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        row=await conn.fetchrow("""SELECT p.content,p.content_type FROM control_check_photos p
            JOIN control_checks c ON c.id=p.check_id WHERE p.id=$1 AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2))""",int(request.match_info["id"]),scope)
    if not row:
        return web.Response(status=404,headers=NO_STORE)
    return await safe_photo_response(row["content"])

@routes.post("/api/control/tasks/photos")
async def task_photos(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"forbidden"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        tid=body["id"]
        if type(tid) is not int:
            raise ValueError()
    except (ValueError,TypeError,KeyError):
        return web.json_response({"error":"invalid_id"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        task=await conn.fetchrow("""SELECT t.check_id,t.question_key FROM control_tasks t JOIN control_checks c ON c.id=t.check_id
            WHERE t.id=$1 AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2)) AND ($3::boolean OR t.assignee_id=$4)""",tid,scope,task_manager(user),user["user_id"])
        if not task:
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        before=await conn.fetchrow("SELECT p.id,CASE WHEN $3::boolean OR (c.guest_id IS NULL AND NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id=p.uploaded_by AND lower(btrim(COALESCE(u.position, ''))) = 'тайный гость')) THEN p.uploaded_by ELSE NULL END AS uploaded_by,p.created_at FROM control_check_photos p JOIN control_checks c ON c.id=p.check_id WHERE p.check_id=$1 AND p.question_key=$2",task["check_id"],task["question_key"],_is_hr_or_super(user))
        after=await conn.fetch("SELECT p.id,CASE WHEN $2::boolean OR NOT EXISTS (SELECT 1 FROM users u WHERE u.user_id=p.uploaded_by AND lower(btrim(COALESCE(u.position, ''))) = 'тайный гость') THEN p.uploaded_by ELSE NULL END AS uploaded_by,p.created_at FROM control_task_photos p WHERE p.task_id=$1 ORDER BY p.id DESC LIMIT 100",tid,_is_hr_or_super(user))
    return web.json_response({"before":journal_json(before) if before else None,"after":[journal_json(p) for p in after]},headers=NO_STORE)

@routes.get("/api/control/task-photos/{id:\\d+}")
async def get_task_photo(request):
    user=await control_user(request)
    if not user:
        return web.Response(status=403,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        row=await conn.fetchrow("""SELECT p.content,p.content_type FROM control_task_photos p JOIN control_tasks t ON t.id=p.task_id
            JOIN control_checks c ON c.id=t.check_id WHERE p.id=$1 AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2))
            AND ($3::boolean OR t.assignee_id=$4)""",int(request.match_info["id"]),scope,task_manager(user),user["user_id"])
    if not row:
        return web.Response(status=404,headers=NO_STORE)
    return await safe_photo_response(row["content"])

def analytics_period(body):
    from datetime import date,timedelta
    if not isinstance(body,dict):
        raise ValueError("invalid_period")
    start=date.fromisoformat(body["start"])
    end=date.fromisoformat(body["end"])
    if end<start or (end-start).days>365:
        raise ValueError("invalid_period")
    return start,end+timedelta(days=1)

@routes.post("/api/control/analytics")
async def control_analytics(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"forbidden"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        start,end=analytics_period(body)
        key=body.get("restaurant_key")
        if key is not None and not isinstance(key,str):
            raise ValueError()
    except (ValueError,TypeError,KeyError,OverflowError):
        return web.json_response({"error":"Укажите период до 366 дней"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    if key is not None:
        if scope is not None and key not in scope:
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        scope=[key]
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""WITH bounds AS (
            SELECT ($1::date::timestamp AT TIME ZONE 'Europe/Moscow') AS lo,
                   ($2::date::timestamp AT TIME ZONE 'Europe/Moscow') AS hi
        ), checks AS (
            SELECT c.restaurant_key,COUNT(*) AS completed,COUNT(c.score) AS scored,
                   SUM(c.score) AS score_sum
            FROM control_checks c CROSS JOIN bounds b
            WHERE c.completed_at>=b.lo AND c.completed_at<b.hi
              AND ($3::text[] IS NULL OR c.restaurant_key=ANY($3))
            GROUP BY c.restaurant_key
        ), tasks AS (
            SELECT c.restaurant_key,COUNT(*) AS tasks_created,
                   COUNT(*) FILTER(WHERE t.critical) AS critical_tasks
            FROM control_tasks t JOIN control_checks c ON c.id=t.check_id CROSS JOIN bounds b
            WHERE t.created_at>=b.lo AND t.created_at<b.hi
              AND ($3::text[] IS NULL OR c.restaurant_key=ANY($3))
            GROUP BY c.restaurant_key
        ), overdue AS (
            SELECT c.restaurant_key,COUNT(*) AS overdue_now
            FROM control_tasks t JOIN control_checks c ON c.id=t.check_id
            WHERE t.due_at<NOW() AND t.status!='closed'
              AND ($3::text[] IS NULL OR c.restaurant_key=ANY($3))
            GROUP BY c.restaurant_key
        )
        SELECT r.key AS restaurant_key,r.name,CASE WHEN lower(btrim(COALESCE(u.position, ''))) = 'тайный гость' THEN NULL ELSE r.territory_manager_id END AS territory_manager_id,CASE WHEN lower(btrim(COALESCE(u.position, ''))) = 'тайный гость' THEN NULL ELSE u.full_name END AS territory_manager,COALESCE(c.completed,0) AS completed,
            COALESCE(c.scored,0) AS scored,c.score_sum,
            COALESCE(t.tasks_created,0) AS tasks_created,COALESCE(t.critical_tasks,0) AS critical_tasks,
            COALESCE(o.overdue_now,0) AS overdue_now
        FROM restaurants r LEFT JOIN users u ON u.user_id=r.territory_manager_id LEFT JOIN checks c ON c.restaurant_key=r.key
        LEFT JOIN tasks t ON t.restaurant_key=r.key LEFT JOIN overdue o ON o.restaurant_key=r.key
        WHERE ($3::text[] IS NULL OR r.key=ANY($3)) ORDER BY r.name""",start,end,scope)
    items=[]
    for row in rows:
        item=dict(row)
        total=item.pop("score_sum")
        item["average_score"]=round(float(total)/item["scored"],2) if item["scored"] else None
        items.append(item)
    scored=sum(r["scored"] for r in rows)
    total=sum(float(r["score_sum"] or 0) for r in rows)
    summary={k:sum(i[k] for i in items) for k in ("completed","scored","tasks_created","critical_tasks","overdue_now")}
    summary["average_score"]=round(total/scored,2) if scored else None
    items.sort(key=lambda i:(i["average_score"] is None,-(i["average_score"] or 0),i["name"]))
    territories={}
    for row in rows:
        tid=row["territory_manager_id"]
        group=territories.setdefault(tid,{"manager_id":tid,"name":row["territory_manager"] or "Без закреплённого ТУ","restaurants":0,"completed":0,"scored":0,"tasks_created":0,"critical_tasks":0,"overdue_now":0,"score_sum":0.0})
        group["restaurants"]+=1
        for field in ("completed","scored","tasks_created","critical_tasks","overdue_now"):
            group[field]+=row[field]
        group["score_sum"]+=float(row["score_sum"] or 0)
    for group in territories.values():
        total=group.pop("score_sum")
        group["average_score"]=round(total/group["scored"],2) if group["scored"] else None
    return web.json_response({"summary":summary,"restaurants":items,"territories":list(territories.values())},headers=NO_STORE)

@routes.post("/api/control/analytics/trends")
async def analytics_trends(request):
    from datetime import timedelta
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"forbidden"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        start,end=analytics_period(body)
        previous=start-(end-start)
        key=body.get("restaurant_key")
        if key is not None and not isinstance(key,str):
            raise ValueError()
    except (ValueError,TypeError,KeyError,OverflowError):
        return web.json_response({"error":"invalid_period"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    if key is not None:
        if scope is not None and key not in scope:
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        scope=[key]
    async with db.get_pool(request.app).acquire() as conn:
        checks=await conn.fetch("""SELECT (completed_at AT TIME ZONE 'Europe/Moscow')::date AS day,
            COUNT(*) AS completed,COUNT(score) AS scored,SUM(score) AS score_sum
            FROM control_checks WHERE completed_at>=($1::date::timestamp AT TIME ZONE 'Europe/Moscow')
            AND completed_at<($2::date::timestamp AT TIME ZONE 'Europe/Moscow')
            AND ($3::text[] IS NULL OR restaurant_key=ANY($3)) GROUP BY 1 ORDER BY 1""",previous,end,scope)
        readings=await conn.fetch("""SELECT (r.recorded_at AT TIME ZONE 'Europe/Moscow')::date AS day,
            COUNT(*) AS readings,COUNT(*) FILTER(WHERE r.deviation) AS deviations
            FROM control_readings r JOIN control_equipment e ON e.id=r.equipment_id
            WHERE r.recorded_at>=($1::date::timestamp AT TIME ZONE 'Europe/Moscow')
            AND r.recorded_at<($2::date::timestamp AT TIME ZONE 'Europe/Moscow')
            AND ($3::text[] IS NULL OR e.restaurant_key=ANY($3)) GROUP BY 1 ORDER BY 1""",previous,end,scope)
    def summarize(lo,hi):
        cs=[r for r in checks if lo<=r["day"]<hi]
        rs=[r for r in readings if lo<=r["day"]<hi]
        n=sum(r["scored"] for r in cs)
        return {"completed":sum(r["completed"] for r in cs),
                "average_score":round(sum(float(r["score_sum"] or 0) for r in cs)/n,2) if n else None,
                "readings":sum(r["readings"] for r in rs),"deviations":sum(r["deviations"] for r in rs)}
    current=summarize(start,end)
    prior=summarize(previous,start)
    daily=[]
    for offset in range((end-start).days):
        day=start+timedelta(days=offset)
        daily.append({"date":day.isoformat(),**summarize(day,day+timedelta(days=1))})
    return web.json_response({"current":current,"previous":prior,"previous_start":previous.isoformat(),
        "previous_end":(start-timedelta(days=1)).isoformat(),"daily":daily},headers=NO_STORE)

RATING_WEIGHTS={"audits":35,"checklists":20,"haccp":20,"tasks":15,"learning":5,"mystery_guest":5}

def calculate_control_rating(values):
    available={k:v for k,v in values.items() if k in RATING_WEIGHTS and v is not None}
    coverage=sum(RATING_WEIGHTS[k] for k in available)
    points=sum(RATING_WEIGHTS[k]*float(v)/100 for k,v in available.items())
    return {"rating":round(points,2) if coverage==100 else None,
            "provisional":round(points*100/coverage,2) if coverage else None,
            "coverage":coverage,"components":{k:values.get(k) for k in RATING_WEIGHTS}}

@routes.post("/api/control/analytics/rating")
async def analytics_rating(request):
    user=await control_user(request)
    if not user:
        return web.json_response({"error":"forbidden"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        start,end=analytics_period(body)
        key=body.get("restaurant_key")
        if key is not None and not isinstance(key,str):
            raise ValueError()
    except (ValueError,TypeError,KeyError,OverflowError):
        return web.json_response({"error":"invalid_period"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    if key is not None:
        if scope is not None and key not in scope:
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        scope=[key]
    async with db.get_pool(request.app).acquire() as conn:
        rows=await conn.fetch("""WITH bounds AS (
            SELECT ($1::date::timestamp AT TIME ZONE 'Europe/Moscow') lo,
                   ($2::date::timestamp AT TIME ZONE 'Europe/Moscow') hi
        ), checks AS (
            SELECT c.restaurant_key,
                AVG(c.score) FILTER(WHERE COALESCE(v.definition->>'category','checklist')='checklist') AS checklist_score,
                AVG(c.score) FILTER(WHERE v.definition->>'category'='audit') AS audit_score,
                AVG(c.score) FILTER(WHERE v.definition->>'category'='mystery_guest') AS mystery_score
            FROM control_checks c JOIN control_template_versions v ON v.id=c.version_id CROSS JOIN bounds
            WHERE c.completed_at>=lo AND c.completed_at<hi GROUP BY c.restaurant_key
        ), haccp AS (
            SELECT e.restaurant_key,100.0*COUNT(*) FILTER(WHERE NOT r.deviation)/COUNT(*) score
            FROM control_readings r JOIN control_equipment e ON e.id=r.equipment_id CROSS JOIN bounds
            WHERE r.recorded_at>=lo AND r.recorded_at<hi GROUP BY e.restaurant_key
        ), tasks AS (
            SELECT c.restaurant_key,100.0*COUNT(*) FILTER(WHERE EXISTS(
                SELECT 1 FROM control_task_history h WHERE h.task_id=t.id AND h.action='approve' AND h.created_at<=t.due_at
            ))/COUNT(*) score
            FROM control_tasks t JOIN control_checks c ON c.id=t.check_id CROSS JOIN bounds
            WHERE t.due_at>=lo AND t.due_at<hi AND t.due_at<=NOW() GROUP BY c.restaurant_key
        )
        SELECT r.key,r.name,c.checklist_score AS checklists,c.audit_score AS audits,c.mystery_score AS mystery_guest,h.score AS haccp,t.score AS tasks,
            NULL::numeric AS learning
        FROM restaurants r LEFT JOIN checks c ON c.restaurant_key=r.key
        LEFT JOIN haccp h ON h.restaurant_key=r.key LEFT JOIN tasks t ON t.restaurant_key=r.key
        WHERE ($3::text[] IS NULL OR r.key=ANY($3)) ORDER BY r.name""",start,end,scope)
    items=[]
    for r in rows:
        values={k:round(float(r[k]),2) if r[k] is not None else None for k in ("checklists","audits","mystery_guest","haccp","tasks")}
        items.append({"restaurant_key":r["key"],"name":r["name"],**calculate_control_rating(values)})
    return web.json_response({"weights":RATING_WEIGHTS,"restaurants":items,"learning_basis":"in_development"},headers=NO_STORE)


async def refresh_control_notifications(conn, user):
    """Materialize current attention events only for the authenticated recipient."""
    if not control_allowed(user) or is_mystery_guest(user):
        return
    scope = await restaurant_scope(user)
    await conn.execute("""INSERT INTO control_notifications(recipient_id,restaurant_key,event_kind,source_id)
        SELECT $1,c.restaurant_key,e.kind,c.id FROM control_checks c
        CROSS JOIN LATERAL (VALUES ('check_overdue',c.due_at<NOW()),('check_assigned',c.guest_id IS NULL)) e(kind,active)
        WHERE c.completed_at IS NULL AND e.active
          AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2))
        UNION ALL
        SELECT $1,c.restaurant_key,e.kind,t.id FROM control_tasks t
        JOIN control_checks c ON c.id=t.check_id
        CROSS JOIN LATERAL (VALUES ('task_overdue',t.due_at<NOW()),('task_critical',t.critical),('task_assigned',t.assignee_id=$1)) e(kind,active)
        WHERE t.status!='closed' AND e.active
          AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2))
        UNION ALL
        SELECT $1,e.restaurant_key,'haccp_deviation',r.id FROM control_readings r
        JOIN control_equipment e ON e.id=r.equipment_id
        WHERE r.deviation AND r.recorded_at >= NOW() - INTERVAL '30 days'
          AND ($2::text[] IS NULL OR e.restaurant_key=ANY($2))
        ON CONFLICT (recipient_id,event_kind,source_id) DO NOTHING""",user["user_id"],scope)

@routes.post("/api/control/notifications")
async def notifications(request):
    user=await control_user(request)
    if not user or is_mystery_guest(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        await refresh_control_notifications(conn,user)
        rows=await conn.fetch("""SELECT n.id,n.restaurant_key,n.event_kind,n.source_id,n.created_at,n.read_at,r.name AS restaurant_name
            FROM control_notifications n JOIN restaurants r ON r.key=n.restaurant_key WHERE n.recipient_id=$1
            AND ($2::text[] IS NULL OR n.restaurant_key=ANY($2))
            ORDER BY n.created_at DESC,n.id DESC LIMIT 100""",user["user_id"],scope)
        unread=await conn.fetchval("""SELECT count(*) FROM control_notifications WHERE recipient_id=$1
            AND read_at IS NULL AND ($2::text[] IS NULL OR restaurant_key=ANY($2))""",user["user_id"],scope)
    items=[dict(row,id=str(row["id"]),source_id=str(row["source_id"]),created_at=row["created_at"].isoformat(),read_at=row["read_at"].isoformat() if row["read_at"] else None) for row in rows]
    return web.json_response({"notifications":items,"unread":unread},headers=NO_STORE)


@routes.post("/api/control/notifications/read")
async def read_notifications(request):
    user=await control_user(request)
    if not user or is_mystery_guest(user):
        return web.json_response({"error":"Доступ запрещён"},status=403,headers=NO_STORE)
    try:
        body=await request.json()
        if not isinstance(body,dict):
            raise ValueError()
        all_items=body.get("all") is True
        raw=body.get("id")
        if all_items:
            if set(body)!={"all"}:
                raise ValueError()
            nid=None
        else:
            if set(body)!={"id"} or not isinstance(raw,str) or not raw.isascii() or not raw.isdecimal() or len(raw)>19:
                raise ValueError()
            nid=int(raw)
            if not 0<nid<2**63:
                raise ValueError()
    except (ValueError,TypeError):
        return web.json_response({"error":"invalid_notification"},status=400,headers=NO_STORE)
    scope=await restaurant_scope(user)
    async with db.get_pool(request.app).acquire() as conn:
        changed=await conn.fetchval("""WITH updated AS (UPDATE control_notifications SET read_at=NOW()
            WHERE recipient_id=$1 AND read_at IS NULL
            AND ($2::text[] IS NULL OR restaurant_key=ANY($2))
            AND ($3::bigint IS NULL OR id=$3) RETURNING id)
            SELECT count(*) FROM updated""",user["user_id"],scope,nid)
        unread=await conn.fetchval("""SELECT count(*) FROM control_notifications WHERE recipient_id=$1
            AND read_at IS NULL AND ($2::text[] IS NULL OR restaurant_key=ANY($2))""",user["user_id"],scope)
    return web.json_response({"updated":changed,"unread":unread},headers=NO_STORE)
