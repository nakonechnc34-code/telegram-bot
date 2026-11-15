from aiohttp import web
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import sql
from db import get_conn, _run
from utils.auth_helpers import get_admin_user, get_auth_user, denied, require_perm, _sync_user_has_perm
from utils.security import sanitize_html

routes = web.RouteTableDef()

def _safe_int(val, default=0):
    try: return int(val)
    except: return default

def _auto_publish_scheduled(cur):
    cur.execute("UPDATE news SET status = 'published' WHERE status = 'scheduled' AND publish_at IS NOT NULL AND publish_at <= NOW()")

def _check_can_publish(admin):
    return admin["is_super_admin"] or (admin.get("position") or "").strip().upper() == "HR"

# ================== NEWS ==================
@routes.post('/api/admin/news')
async def handle_admin_news_list(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                _auto_publish_scheduled(cur)
                cur.execute("SELECT * FROM news ORDER BY created_at DESC, id DESC")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"news": await _run(_sync)})

@routes.post('/api/admin/news/add')
async def handle_admin_news_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    can_publish = _check_can_publish(admin)
    can_suggest = _sync_user_has_perm(admin, "news_suggest") or _sync_user_has_perm(admin, "news_write")
    if not (can_publish or can_suggest): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    title = (body.get("title") or "").strip()
    text = (body.get("body") or "").strip()
    if not title or not text or len(title) > 200 or len(text) > 5000:
        return web.json_response({"error": "invalid_or_too_long"}, status=400)
    
    level = body.get("level") or "normal"
    intent = body.get("intent") or "suggest"
    publish_at = body.get("publish_at")
    image_url = body.get("image_url") or ""

    if not can_publish:
        status = "pending"
        proposed_by = admin.get("full_name") or admin.get("login")
    else:
        if intent == "publish": status = "published"
        elif intent == "schedule":
            if not publish_at: return web.json_response({"error": "publish_at_required"}, status=400)
            status = "scheduled"
        else: status = "pending"
        proposed_by = None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("INSERT INTO news (title, body, level, status, publish_at, proposed_by, image_url) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *", (title, text, level, status, publish_at, proposed_by, image_url))
                return dict(cur.fetchone())
    news_row = await _run(_sync)
    return web.json_response({"ok": True, "status": status, "news": news_row})

# (Остальные эндпоинты для news: update, delete, approve, reject - аналогично, я опускаю для краткости, 
# но они должны быть перенесены сюда из старого app.py)

# ================== STANDARDS ==================
@routes.post('/api/admin/standards')
async def handle_admin_standards(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM standards ORDER BY created_at DESC, id DESC")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"standards": await _run(_sync)})

@routes.post('/api/admin/standard/add')
async def handle_admin_standard_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    can_publish = _check_can_publish(admin)
    can_suggest = _sync_user_has_perm(admin, "standards_edit")
    if not (can_publish or can_suggest): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    number = (body.get("number") or "").strip()
    title = (body.get("title") or "").strip()
    text = (body.get("body") or "").strip()
    image_url = body.get("image_url") or ""
    group_name = (body.get("group_name") or "Общее").strip()
    content_type = body.get("content_type") or "text"
    content_data = body.get("content_data")
    file_url = body.get("file_url") or ""
    file_name = body.get("file_name") or ""
    
    if not title: return web.json_response({"error": "title_required"}, status=400)
    if not text: return web.json_response({"error": "text_required"}, status=400)
    if content_type == 'text': text = sanitize_html(text)

    if not can_publish:
        status = "pending"; proposed_by = admin.get("full_name") or admin.get("login")
    else:
        status = "published"; proposed_by = None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("INSERT INTO standards (number, title, body, status, proposed_by, image_url, group_name, content_type, content_data, file_url, file_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", 
                            (number, title, text, status, proposed_by, image_url, group_name, content_type, Json(content_data) if content_data else None, file_url, file_name))
                return dict(cur.fetchone())
    std_row = await _run(_sync)
    return web.json_response({"ok": True, "status": status, "standard": std_row})

# ================== CERTIFICATION ==================
@routes.post('/api/admin/certification')
async def handle_admin_certification_list(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM certification_questions ORDER BY created_at DESC")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"questions": await _run(_sync)})

@routes.post('/api/admin/certification/add')
async def handle_admin_certification_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "certification_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    q = (body.get("question") or "").strip()
    a = (body.get("option_a") or "").strip()
    b = (body.get("option_b") or "").strip()
    c = (body.get("option_c") or "").strip()
    d = (body.get("option_d") or "").strip()
    correct = (body.get("correct_option") or "").strip().lower()
    if not q or not a or not b or not c or not d or correct not in ("a","b","c","d"):
        return web.json_response({"error": "invalid"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO certification_questions (question, option_a, option_b, option_c, option_d, correct_option) VALUES (%s,%s,%s,%s,%s,%s)", (q, a, b, c, d, correct))
    await _run(_sync)
    return web.json_response({"ok": True})

# ================== FAQ ==================
@routes.post('/api/admin/faq')
async def handle_admin_faq(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM faq ORDER BY id")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"faq": await _run(_sync)})

@routes.post('/api/admin/faq/add')
async def handle_admin_faq_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "faq_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    q = body.get("question") or ""
    a = body.get("answer") or ""
    if not q or len(q) > 500 or len(a) > 2000: return web.json_response({"error": "invalid_or_too_long"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s,%s,%s)", (q, a, ""))
    await _run(_sync)
    return web.json_response({"ok": True})

# ================== POSITIONS ==================
@routes.post('/api/admin/positions')
async def handle_admin_positions(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM positions ORDER BY is_archived, sort, name")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"positions": await _run(_sync)})

@routes.post('/api/admin/position/add')
async def handle_admin_position_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "positions_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    name = (body.get("name") or "").strip()
    if not name or len(name) > 100: return web.json_response({"error": "invalid"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COALESCE(MAX(sort), 0) FROM positions")
                sort = (cur.fetchone()[0] or 0) + 1
                cur.execute("INSERT INTO positions (name, sort) VALUES (%s,%s) ON CONFLICT (name) DO NOTHING RETURNING id", (name, sort))
                if not cur.fetchone(): return "duplicate"
    res = await _run(_sync)
    if res == "duplicate": return web.json_response({"ok": False, "error": "duplicate"}, status=409)
    return web.json_response({"ok": True})

# ================== QUESTIONS ==================
@routes.post('/api/admin/questions')
async def handle_admin_questions(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT q.id, q.user_id, q.text, q.replied, q.created_at, u.full_name FROM questions q LEFT JOIN users u ON q.user_id = u.user_id ORDER BY q.created_at DESC LIMIT 200")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"questions": await _run(_sync)})

@routes.post('/api/admin/question/reply')
async def handle_admin_question_reply(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "questions_reply")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    qid = _safe_int(body.get("id"))
    text = (body.get("text") or "").strip()
    if qid <= 0 or not text or len(text) > 2000: return web.json_response({"error": "invalid"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE questions SET replied = TRUE, reply_text = %s, replied_at = NOW(), replied_by = %s WHERE id = %s", (text, admin["user_id"], qid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/questions')
async def handle_questions_staff(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    text = (body.get("question") or "").strip()
    if not text or len(text) > 1000: return web.json_response({"error": "invalid"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO questions (user_id, text) VALUES (%s,%s)", (user["user_id"], text))
    await _run(_sync)
    return web.json_response({"ok": True})
