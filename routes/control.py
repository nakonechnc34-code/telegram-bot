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


async def restaurant_scope(user):
    if user.get("is_super_admin"):
        return None
    if _is_tu(user):
        return list(await db._run(_sync_get_tu_rests, user["user_id"]) or [])
    return [user["restaurant_key"]] if user.get("restaurant_key") else []

def score_check(definition, answers):
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
            if q.get("required"):
                raise ValueError("required_answer")
            continue
        # Only yes/no/NA checks are supported by this execution stage.
        if q["type"] != "yes_no_na" or answer not in ("yes","no","na"):
            raise ValueError("unsupported_answer")
        if answer == "na":
            if q.get("critical"):
                raise ValueError("critical_na")
            continue
        if q.get("photo_required") or q.get("comment_required"):
            raise ValueError("evidence_not_supported")
        possible += q["weight"]
        if answer == "yes":
            earned += q["weight"]
        else:
            violations.append((key,q))
    return (round(100*earned/possible,2) if possible else None), violations

@routes.post("/api/control/checks/assign")
async def assign_check(request):
    user = await template_editor(request)
    if not user:
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
    async with db.get_pool(request.app).acquire() as conn:
        row = await conn.fetchrow("SELECT id,definition FROM control_template_versions WHERE template_id=$1 AND version=$2",tid,version)
        if not row or not await conn.fetchval("SELECT 1 FROM restaurants WHERE key=$1",key):
            return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
        definition = json.loads(row["definition"]) if isinstance(row["definition"],str) else row["definition"]
        if any(q["type"]!="yes_no_na" or q.get("photo_required") or q.get("comment_required") for sec in definition["sections"] for q in sec["questions"]):
            return web.json_response({"error":"Шаблон требует ещё не реализованных типов ответов или доказательств"},status=400,headers=NO_STORE)
        cid = await conn.fetchval("""INSERT INTO control_checks(restaurant_key,version_id,assigned_by,due_at)
            VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING RETURNING id""",key,row["id"],user["user_id"],due)
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
            WHERE ($1::text[] IS NULL OR c.restaurant_key=ANY($1)) ORDER BY c.due_at DESC LIMIT 200""",scope)
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
                WHERE c.id=$1 AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2)) FOR UPDATE OF c""",body["id"],scope)
            if not row:
                return web.json_response({"error":"not_found"},status=404,headers=NO_STORE)
            if row["completed_at"]:
                return web.json_response({"error":"already_completed"},status=409,headers=NO_STORE)
            definition=json.loads(row["definition"]) if isinstance(row["definition"],str) else row["definition"]
            try:
                score,violations=score_check(definition,body.get("answers"))
            except ValueError as exc:
                return web.json_response({"error":str(exc)},status=400,headers=NO_STORE)
            await conn.execute("UPDATE control_checks SET completed_at=NOW(),completed_by=$1,answers=$2::jsonb,score=$3 WHERE id=$4",user["user_id"],json.dumps(body["answers"]),score,row["id"])
            for key,q in violations:
                if q.get("create_task") or q.get("critical"):
                    await conn.execute("INSERT INTO control_tasks(check_id,question_key,description,critical) VALUES($1,$2,$3,$4)",row["id"],key,q["text"],bool(q.get("critical")))
    return web.json_response({"score":score,"violations":len(violations)},headers=NO_STORE)


def task_manager(user):
    return bool(user.get("is_super_admin") or _is_tu(user))

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
        rows = await conn.fetch("""SELECT t.*,c.restaurant_key,
            (t.due_at<NOW() AND t.status!='closed') AS overdue
            FROM control_tasks t JOIN control_checks c ON c.id=t.check_id
            WHERE ($1::text[] IS NULL OR c.restaurant_key=ANY($1))
            AND ($2::boolean OR t.assignee_id=$3)
            ORDER BY t.critical DESC,t.id DESC LIMIT 200""",scope,task_manager(user),user["user_id"])
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
                if not target or not control_allowed(dict(target)):
                    return web.json_response({"error":"invalid_assignee"},status=400,headers=NO_STORE)
                await conn.execute("UPDATE control_tasks SET assignee_id=$1,due_at=$2 WHERE id=$3",assignee,due,row["id"])
                details.update({"assignee_id":assignee,"due_at":due.isoformat(),"previous_assignee_id":row["assignee_id"]})
                status=row["status"]
            else:
                try:
                    status=task_transition(row["status"],action,manager,row["assignee_id"]==user["user_id"],comment)
                except ValueError as exc:
                    return web.json_response({"error":str(exc)},status=409,headers=NO_STORE)
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
        rows=await conn.fetch("""SELECT h.actor_id,h.action,h.details,h.created_at FROM control_task_history h
            JOIN control_tasks t ON t.id=h.task_id JOIN control_checks c ON c.id=t.check_id
            WHERE t.id=$1 AND ($2::text[] IS NULL OR c.restaurant_key=ANY($2))
            AND ($3::boolean OR t.assignee_id=$4) ORDER BY h.id""",body["id"],scope,task_manager(user),user["user_id"])
    return web.json_response({"history":[{"actor_id":r["actor_id"],"action":r["action"],"details":json.loads(r["details"]) if isinstance(r["details"],str) else r["details"],"created_at":r["created_at"].isoformat()} for r in rows]},headers=NO_STORE)
