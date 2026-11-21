from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, get_admin_user, denied, require_perm, _is_tu, _sync_get_tu_rests
from utils.common import safe_int
from utils.security import sanitize_html

routes = web.RouteTableDef()


async def _can_manage_content_row(admin, row, allowed_rests):
    if allowed_rests is None:
        return True
    if not row:
        return False
    if not allowed_rests:
        return False
    rest_key = row.get("restaurant_key")
    if rest_key and rest_key in allowed_rests:
        return True
    return False


# ================== НОВОСТИ ==================
@routes.post('/api/news')
async def handle_news(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT n.id, n.title, n.body, n.image_url, n.created_at, n.restaurant_key,
                              COALESCE(u.full_name, 'Редакция') AS author_name, r.name AS restaurant_name
                       FROM news n LEFT JOIN users u ON n.author_id = u.user_id
                       LEFT JOIN restaurants r ON n.restaurant_key = r.key
                       WHERE n.status = 'published' ORDER BY n.created_at DESC LIMIT 50"""
                )
                return [dict(r) for r in cur.fetchall()]

    items = await _run(_sync)
    return web.json_response({"news": items})


@routes.post('/api/news/suggest')
async def handle_news_suggest(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    title = (body.get("title") or "").strip()
    text = sanitize_html((body.get("body") or body.get("text") or "").strip())
    image_url = (body.get("image_url") or "").strip()
    restaurant_key = (body.get("restaurant_key") or "").strip() or None
    if not title or not text:
        return web.json_response({"error": "empty_fields"}, status=400)
    if len(title) > 200 or len(text) > 10000:
        return web.json_response({"error": "too_long"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO news (title, body, image_url, author_id, restaurant_key, status)
                       VALUES (%s, %s, %s, %s, %s, 'pending') RETURNING id, title, created_at""",
                    (title, text, image_url or None, user["user_id"], restaurant_key)
                )
                return dict(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/news/list')
async def handle_admin_news_list(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """SELECT n.id, n.title, n.body, n.image_url, n.status, n.created_at, n.restaurant_key,
                                  COALESCE(u.full_name, 'Редакция') AS author_name, r.name AS restaurant_name
                           FROM news n LEFT JOIN users u ON n.author_id = u.user_id
                           LEFT JOIN restaurants r ON n.restaurant_key = r.key"""
                params = []
                if allowed_rests is not None:
                    if not allowed_rests:
                        return []
                    query += " WHERE n.restaurant_key = ANY(%s)"
                    params.append(allowed_rests)
                query += " ORDER BY n.created_at DESC LIMIT 100"
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]

    items = await _run(_sync)
    return web.json_response({"news": items})


@routes.post('/api/admin/news/create')
async def handle_admin_news_create(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "news_write")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    title = (body.get("title") or "").strip()
    text = sanitize_html((body.get("body") or body.get("text") or "").strip())
    image_url = (body.get("image_url") or "").strip()
    restaurant_key = (body.get("restaurant_key") or "").strip() or None
    status = body.get("status") if body.get("status") in ("published", "draft", "pending") else "published"
    if not title or not text:
        return web.json_response({"error": "empty_fields"}, status=400)
    if _is_tu(admin):
        allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"])
        if not restaurant_key or not allowed_rests or restaurant_key not in allowed_rests:
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO news (title, body, image_url, author_id, restaurant_key, status)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
                    (title, text, image_url or None, admin["user_id"], restaurant_key, status)
                )
                return dict(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/news/update')
async def handle_admin_news_update(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "news_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    nid = safe_int(body.get("id"))
    if nid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync_get():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM news WHERE id = %s", (nid,))
                row = cur.fetchone()
                return dict(row) if row else None

    existing = await _run(_sync_get)
    if not existing:
        return web.json_response({"error": "not_found"}, status=404)
    if not await _can_manage_content_row(admin, existing, allowed_rests):
        return web.json_response({"error": "forbidden"}, status=403)

    title = (body.get("title") or "").strip()
    text = sanitize_html((body.get("body") or body.get("text") or "").strip())
    image_url = body.get("image_url")
    status = body.get("status")
    restaurant_key = body.get("restaurant_key")

    if allowed_rests is not None and restaurant_key is not None:
        rk = (restaurant_key or "").strip()
        if not rk or rk not in allowed_rests:
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                if title:
                    cur.execute("UPDATE news SET title = %s WHERE id = %s", (title, nid))
                if text:
                    cur.execute("UPDATE news SET body = %s WHERE id = %s", (text, nid))
                if image_url is not None:
                    cur.execute("UPDATE news SET image_url = %s WHERE id = %s", ((image_url or "").strip() or None, nid))
                if status in ("published", "draft", "pending", "rejected"):
                    cur.execute("UPDATE news SET status = %s WHERE id = %s", (status, nid))
                if restaurant_key is not None:
                    cur.execute("UPDATE news SET restaurant_key = %s WHERE id = %s", ((restaurant_key or "").strip() or None, nid))

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/news/delete')
async def handle_admin_news_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "news_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    nid = safe_int(body.get("id"))
    if nid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, restaurant_key FROM news WHERE id = %s", (nid,))
                row = cur.fetchone()
                return dict(row) if row else None

    existing = await _run(_sync)
    if not existing:
        return web.json_response({"error": "not_found"}, status=404)
    if not await _can_manage_content_row(admin, existing, allowed_rests):
        return web.json_response({"error": "forbidden"}, status=403)

    def _sync_del():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM news WHERE id = %s", (nid,))

    await _run(_sync_del)
    return web.json_response({"ok": True})


# ================== СТАНДАРТЫ ==================
@routes.post('/api/standards')
async def handle_standards(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT s.id, s.title, s.body, s.category, s.file_url, s.created_at, s.restaurant_key,
                              COALESCE(u.full_name, 'Редакция') AS author_name, r.name AS restaurant_name
                       FROM standards s LEFT JOIN users u ON s.author_id = u.user_id
                       LEFT JOIN restaurants r ON s.restaurant_key = r.key
                       WHERE s.status = 'published' ORDER BY s.created_at DESC LIMIT 100"""
                )
                return [dict(r) for r in cur.fetchall()]

    items = await _run(_sync)
    return web.json_response({"standards": items})


@routes.post('/api/standards/suggest')
async def handle_standards_suggest(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    title = (body.get("title") or "").strip()
    text = sanitize_html((body.get("body") or body.get("text") or "").strip())
    category = (body.get("category") or "Общее").strip()[:100]
    file_url = (body.get("file_url") or "").strip()
    restaurant_key = (body.get("restaurant_key") or "").strip() or None
    if not title or not text:
        return web.json_response({"error": "empty_fields"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO standards (title, body, category, file_url, author_id, restaurant_key, status)
                       VALUES (%s, %s, %s, %s, %s, %s, 'pending') RETURNING id, title, created_at""",
                    (title, text, category, file_url or None, user["user_id"], restaurant_key)
                )
                return dict(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/standards/list')
async def handle_admin_standards_list(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """SELECT s.id, s.title, s.body, s.category, s.file_url, s.status, s.created_at, s.restaurant_key,
                                  COALESCE(u.full_name, 'Редакция') AS author_name, r.name AS restaurant_name
                           FROM standards s LEFT JOIN users u ON s.author_id = u.user_id
                           LEFT JOIN restaurants r ON s.restaurant_key = r.key"""
                params = []
                if allowed_rests is not None:
                    if not allowed_rests:
                        return []
                    query += " WHERE s.restaurant_key = ANY(%s)"
                    params.append(allowed_rests)
                query += " ORDER BY s.created_at DESC LIMIT 100"
                cur.execute(query, params)
                return [dict(r) for r in cur.fetchall()]

    items = await _run(_sync)
    return web.json_response({"standards": items})


@routes.post('/api/admin/standard/update')
async def handle_admin_standard_update(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "standards_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    sid = safe_int(body.get("id"))
    if sid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync_get():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM standards WHERE id = %s", (sid,))
                row = cur.fetchone()
                return dict(row) if row else None

    existing = await _run(_sync_get)
    if not existing:
        return web.json_response({"error": "not_found"}, status=404)
    if not await _can_manage_content_row(admin, existing, allowed_rests):
        return web.json_response({"error": "forbidden"}, status=403)

    title = (body.get("title") or "").strip()
    text = sanitize_html((body.get("body") or body.get("text") or "").strip())
    category = body.get("category")
    file_url = body.get("file_url")
    status = body.get("status")
    restaurant_key = body.get("restaurant_key")

    if allowed_rests is not None and restaurant_key is not None:
        rk = (restaurant_key or "").strip()
        if not rk or rk not in allowed_rests:
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                if title:
                    cur.execute("UPDATE standards SET title = %s WHERE id = %s", (title, sid))
                if text:
                    cur.execute("UPDATE standards SET body = %s WHERE id = %s", (text, sid))
                if category is not None:
                    cur.execute("UPDATE standards SET category = %s WHERE id = %s", ((category or "Общее").strip()[:100], sid))
                if file_url is not None:
                    cur.execute("UPDATE standards SET file_url = %s WHERE id = %s", ((file_url or "").strip() or None, sid))
                if status in ("published", "draft", "pending", "rejected"):
                    cur.execute("UPDATE standards SET status = %s WHERE id = %s", (status, sid))
                if restaurant_key is not None:
                    cur.execute("UPDATE standards SET restaurant_key = %s WHERE id = %s", ((restaurant_key or "").strip() or None, sid))

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/standard/delete')
async def handle_admin_standard_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "standards_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    sid = safe_int(body.get("id"))
    if sid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync_get():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, restaurant_key FROM standards WHERE id = %s", (sid,))
                row = cur.fetchone()
                return dict(row) if row else None

    existing = await _run(_sync_get)
    if not existing:
        return web.json_response({"error": "not_found"}, status=404)
    if not await _can_manage_content_row(admin, existing, allowed_rests):
        return web.json_response({"error": "forbidden"}, status=403)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM standards WHERE id = %s", (sid,))

    await _run(_sync)
    return web.json_response({"ok": True})


# ================== FAQ ==================
@routes.post('/api/faq')
async def handle_faq(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, question, answer, category, sort FROM faq ORDER BY sort, id")
                return [dict(r) for r in cur.fetchall()]

    items = await _run(_sync)
    return web.json_response({"faq": items})


@routes.post('/api/admin/faq/save')
async def handle_admin_faq_save(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "faq_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    fid = safe_int(body.get("id"))
    question = (body.get("question") or "").strip()
    answer = sanitize_html((body.get("answer") or "").strip())
    category = (body.get("category") or "Общее").strip()[:100]
    if not question or not answer:
        return web.json_response({"error": "empty_fields"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if fid > 0:
                    cur.execute(
                        "UPDATE faq SET question = %s, answer = %s, category = %s WHERE id = %s RETURNING *",
                        (question, answer, category, fid)
                    )
                else:
                    cur.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM faq")
                    sort_val = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO faq (question, answer, category, sort) VALUES (%s, %s, %s, %s) RETURNING *",
                        (question, answer, category, sort_val)
                    )
                return dict(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/faq/delete')
async def handle_admin_faq_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "faq_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    fid = safe_int(body.get("id"))
    if fid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM faq WHERE id = %s", (fid,))

    await _run(_sync)
    return web.json_response({"ok": True})


# ================== СЕРТИФИКАЦИЯ ==================
@routes.post('/api/certification/questions')
async def handle_certification_questions(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, question, options FROM certification_questions ORDER BY id")
                rows = [dict(r) for r in cur.fetchall()]
                for r in rows:
                    if isinstance(r.get("options"), str):
                        try:
                            r["options"] = json.loads(r["options"])
                        except Exception:
                            r["options"] = []
                return rows

    import json
    items = await _run(_sync)
    return web.json_response({"questions": items})


@routes.post('/api/certification/submit')
async def handle_certification_submit(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    answers = body.get("answers") or {}
    if not isinstance(answers, dict):
        return web.json_response({"error": "invalid_answers"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, correct_index FROM certification_questions ORDER BY id")
                qs = cur.fetchall()
                total = len(qs)
                if total == 0:
                    return 0, 0, False
                correct = 0
                norm_answers = {str(k): v for k, v in answers.items()}
                for q in qs:
                    qid = str(q["id"])
                    if qid in norm_answers and str(norm_answers[qid]) == str(q["correct_index"]):
                        correct += 1
                score_pct = round((correct / total) * 100)
                passed = score_pct >= 80
                if passed:
                    cur.execute("UPDATE users SET is_certified = TRUE WHERE user_id = %s", (user["user_id"],))
                return correct, total, passed

    correct, total, passed = await _run(_sync)
    return web.json_response({
        "ok": True,
        "correct": correct,
        "total": total,
        "score": round((correct / total) * 100) if total else 0,
        "passed": passed,
    })


@routes.post('/api/admin/certification/questions')
async def handle_admin_certification_questions(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "certification_edit")
    if perm_err:
        return perm_err

    import json

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, question, options, correct_index FROM certification_questions ORDER BY id")
                rows = [dict(r) for r in cur.fetchall()]
                for r in rows:
                    if isinstance(r.get("options"), str):
                        try:
                            r["options"] = json.loads(r["options"])
                        except Exception:
                            r["options"] = []
                return rows

    items = await _run(_sync)
    return web.json_response({"questions": items})


@routes.post('/api/admin/certification/question/save')
async def handle_admin_certification_question_save(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "certification_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    qid = safe_int(body.get("id"))
    question = (body.get("question") or "").strip()
    options = body.get("options") or []
    correct_index = safe_int(body.get("correct_index"))
    if not question or not isinstance(options, list) or len(options) < 2:
        return web.json_response({"error": "invalid_data"}, status=400)
    if correct_index < 0 or correct_index >= len(options):
        return web.json_response({"error": "invalid_correct_index"}, status=400)

    import json

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                opts_json = json.dumps(options, ensure_ascii=False)
                if qid > 0:
                    cur.execute(
                        "UPDATE certification_questions SET question = %s, options = %s, correct_index = %s WHERE id = %s RETURNING *",
                        (question, opts_json, correct_index, qid)
                    )
                else:
                    cur.execute(
                        "INSERT INTO certification_questions (question, options, correct_index) VALUES (%s, %s, %s) RETURNING *",
                        (question, opts_json, correct_index)
                    )
                return dict(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/certification/question/delete')
async def handle_admin_certification_question_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "certification_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    qid = safe_int(body.get("id"))
    if qid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM certification_questions WHERE id = %s", (qid,))

    await _run(_sync)
    return web.json_response({"ok": True})
