import os
import uuid
from aiohttp import web
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import sql
from db import get_conn, _run
from utils.auth_helpers import get_admin_user, get_auth_user, denied, require_perm, _sync_user_has_perm
from utils.security import sanitize_html
import logging

routes = web.RouteTableDef()

def _safe_int(val, default=0):
    try: return int(val)
    except: return default

def _auto_publish_scheduled(cur):
    cur.execute("UPDATE news SET status = 'published' WHERE status = 'scheduled' AND publish_at IS NOT NULL AND publish_at <= NOW()")

def _check_can_publish(admin):
    return admin["is_super_admin"] or (admin.get("position") or "").strip().upper() == "HR"

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
    
    title = sanitize_html(title)
    text = sanitize_html(text)

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

@routes.post('/api/admin/news/update')
async def handle_admin_news_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "news_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    nid = _safe_int(body.get("id"))
    if nid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    allowed = {"title", "body", "level", "status", "publish_at", "image_url"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates: return web.json_response({"ok": True})
    
    if "title" in updates: 
        if len(updates["title"]) > 200: return web.json_response({"error": "title_too_long"}, status=400)
        updates["title"] = sanitize_html(updates["title"])
    if "body" in updates: 
        if len(updates["body"]) > 5000: return web.json_response({"error": "body_too_long"}, status=400)
        updates["body"] = sanitize_html(updates["body"])

    set_clause = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates)
    query = sql.SQL("UPDATE news SET {} WHERE id = %s").format(set_clause)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute(query, (*updates.values(), nid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/news/delete')
async def handle_admin_news_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "news_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    nid = _safe_int(body.get("id"))
    if nid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("DELETE FROM news WHERE id = %s", (nid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/news/approve')
async def handle_admin_news_approve(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    nid = _safe_int(body.get("id"))
    if nid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("UPDATE news SET status = 'published', approved_by = %s WHERE id = %s", (admin.get("full_name"), nid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/news/reject')
async def handle_admin_news_reject(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    nid = _safe_int(body.get("id"))
    if nid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("DELETE FROM news WHERE id = %s AND status = 'pending'", (nid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/standard/update')
async def handle_admin_standard_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "standards_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    sid = _safe_int(body.get("id"))
    if sid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    allowed = {"number", "title", "body", "image_url", "group_name", "content_type", "content_data", "file_url", "file_name"}
    updates = {k: body[k] for k in allowed if k in body}
    if not updates: return web.json_response({"ok": True})

    if "title" in updates and not updates["title"]: return web.json_response({"error": "title_required"}, status=400)
    if "body" in updates and not updates["body"]: return web.json_response({"error": "text_required"}, status=400)
    if "body" in updates: updates["body"] = sanitize_html(updates["body"])

    set_clause = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates)
    query = sql.SQL("UPDATE standards SET {} WHERE id = %s").format(set_clause)
    
    vals = []
    for k in updates.keys():
        if k == "content_data": vals.append(Json(updates[k]) if updates[k] else None)
        else: vals.append(updates[k])
    
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute(query, (*vals, sid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/standard/delete')
async def handle_admin_standard_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "standards_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    sid = _safe_int(body.get("id"))
    if sid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("DELETE FROM standards WHERE id = %s", (sid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/standard/approve')
async def handle_admin_standard_approve(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    sid = _safe_int(body.get("id"))
    if sid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("UPDATE standards SET status = 'published', approved_by = %s WHERE id = %s", (admin.get("full_name"), sid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/standard/reject')
async def handle_admin_standard_reject(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    sid = _safe_int(body.get("id"))
    if sid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("DELETE FROM standards WHERE id = %s AND status = 'pending'", (sid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/faq/update')
async def handle_admin_faq_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "faq_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    field = body.get("field")
    if field not in ("question", "answer"): return web.json_response({"error": "invalid"}, status=400)
    fid = _safe_int(body.get("id"))
    if fid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    val = body.get("value") or ""
    if (field == "question" and len(val) > 500) or (field == "answer" and len(val) > 2000):
        return web.json_response({"error": "value_too_long"}, status=400)
    query = sql.SQL("UPDATE faq SET {} = %s WHERE id = %s").format(sql.Identifier(field))
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute(query, (val, fid))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/faq/delete')
async def handle_admin_faq_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "faq_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    fid = _safe_int(body.get("id"))
    if fid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("DELETE FROM faq WHERE id = %s", (fid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/position/archive')
async def handle_admin_position_archive(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "positions_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    pid = _safe_int(body.get("id"))
    if pid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("UPDATE positions SET is_archived = TRUE WHERE id = %s", (pid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/admin/certification/delete')
async def handle_admin_certification_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "certification_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    qid = _safe_int(body.get("id"))
    if qid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur: 
                cur.execute("DELETE FROM certification_questions WHERE id = %s", (qid,))
    await _run(_sync)
    return web.json_response({"ok": True})

@routes.post('/api/certification/get')
async def handle_staff_certification_get(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, question, option_a, option_b, option_c, option_d FROM certification_questions ORDER BY random()")
                return [dict(r) for r in cur.fetchall()]
    return web.json_response({"questions": await _run(_sync)})

@routes.post('/api/certification/submit')
async def handle_staff_certification_submit(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    answers = body.get("answers") or {}
    if not answers: return web.json_response({"error": "no_answers"}, status=400)
        
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, correct_option FROM certification_questions")
                correct_db = {str(r["id"]): r["correct_option"] for r in cur.fetchall()}
                
                score = 0
                total = len(correct_db)
                for q_id, ans in answers.items():
                    if correct_db.get(str(q_id)) == str(ans).lower():
                        score += 1
                
                passed = total > 0 and (score / total) >= 0.8 
                if passed:
                    cur.execute("UPDATE users SET is_certified = TRUE WHERE user_id = %s", (user["user_id"],))
                
                return {"score": score, "total": total, "passed": passed}

    result = await _run(_sync)
    return web.json_response(result)

# ============= ЗАГРУЗКА ФАЙЛОВ =============
# Вспомогательный класс, чтобы get_admin_user смог прочитать токен из URL или FormData
class DummyRequest:
    def __init__(self, original_request, token):
        self._original = original_request
        self._token = token

    def __getattr__(self, name):
        # Делегируем все остальные атрибуты (query, headers и т.д.) оригинальному запросу
        return getattr(self._original, name)

    async def json(self):
        return {"webToken": self._token}

@routes.post('/api/admin/upload')
async def handle_admin_upload(request):
    # 1. Пытаемся взять токен из URL
    token = request.query.get('webToken')
    if not token:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            
    # 2. Читаем multipart-данные (файл и токен из формы)
    reader = await request.multipart()
    file_data = None
    original_name = "file.pdf"
    
    while True:
        part = await reader.next()
        if part is None: break
        
        # Если токен пришел в скрытом поле формы
        if part.name == 'webToken':
            token = await part.text()
            
        # Если это сам файл
        elif part.name == 'file':
            original_name = part.filename
            file_data = await part.read()
            
    if not token:
        return web.json_response({"error": "No token provided"}, status=401)
        
    # 3. Проверяем права через фейковый запрос
    dummy_req = DummyRequest(request, token)
    admin, err = await get_admin_user(dummy_req)
    if err: 
        return denied(err)
        
    if not file_data:
        return web.json_response({"error": "Файл не загружен"}, status=400)
        
    # 4. Сохраняем файл с уникальным именем
    ext = os.path.splitext(original_name)[1]
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    
    # Создаем папку uploads, если ее нет (в корне проекта)
    upload_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    filepath = os.path.join(upload_dir, unique_filename)
    
    with open(filepath, 'wb') as f:
        f.write(file_data)
        
    # 5. Возвращаем путь для сохранения в БД
    file_url = f"/uploads/{unique_filename}"
    
    return web.json_response({
        "ok": True,
        "file_url": file_url,
        "file_name": original_name
    })
