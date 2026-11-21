import json
from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, get_admin_user, denied, require_perm
from utils.common import safe_int

routes = web.RouteTableDef()


def _parse_json_field(val, default):
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return default
    return default


# ================== СОТРУДНИК: АКАДЕМИЯ ==================
@routes.post('/api/academy/courses')
async def handle_academy_courses(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT c.id, c.title, c.description, c.category, c.sort,
                              COUNT(DISTINCT l.id) AS lessons_count,
                              COUNT(DISTINCT q.id) AS questions_count
                       FROM academy_courses c
                       LEFT JOIN academy_lessons l ON l.course_id = c.id
                       LEFT JOIN academy_questions q ON q.course_id = c.id
                       WHERE COALESCE(c.is_published, TRUE) = TRUE
                       GROUP BY c.id
                       ORDER BY c.sort, c.id"""
                )
                return [dict(r) for r in cur.fetchall()]

    courses = await _run(_sync)
    return web.json_response({"courses": courses})


@routes.post('/api/academy/course')
async def handle_academy_course_detail(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    cid = safe_int(body.get("course_id") or body.get("id"))
    if cid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM academy_courses WHERE id = %s", (cid,))
                course = cur.fetchone()
                if not course:
                    return None, [], []
                cur.execute("SELECT id, course_id, title, content, video_url, sort FROM academy_lessons WHERE course_id = %s ORDER BY sort, id", (cid,))
                lessons = [dict(r) for r in cur.fetchall()]
                cur.execute("SELECT id, course_id, question, options FROM academy_questions WHERE course_id = %s ORDER BY id", (cid,))
                questions = []
                for q in cur.fetchall():
                    qd = dict(q)
                    qd["options"] = _parse_json_field(qd.get("options"), [])
                    questions.append(qd)
                return dict(course), lessons, questions

    course, lessons, questions = await _run(_sync)
    if not course:
        return web.json_response({"error": "not_found"}, status=404)
    return web.json_response({"course": course, "lessons": lessons, "questions": questions})


@routes.post('/api/academy/submit')
async def handle_academy_submit_test(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    cid = safe_int(body.get("course_id") or body.get("id"))
    answers = body.get("answers") or {}
    if cid <= 0 or not isinstance(answers, dict):
        return web.json_response({"error": "invalid_data"}, status=400)

    norm_answers = {str(k): v for k, v in answers.items()}

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, correct_index FROM academy_questions WHERE course_id = %s ORDER BY id", (cid,))
                rows = cur.fetchall()
                total = len(rows)
                if total == 0:
                    return 0, 0, False
                correct_db = {str(r["id"]): r["correct_index"] for r in rows}
                correct = 0
                for qid, expected_idx in correct_db.items():
                    if qid in norm_answers and str(norm_answers[qid]) == str(expected_idx):
                        correct += 1
                score_pct = round((correct / total) * 100)
                passed = score_pct >= 80
                try:
                    cur.execute(
                        """INSERT INTO academy_test_results (user_id, course_id, correct_count, total_count, score_pct, passed)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (user["user_id"], cid, correct, total, score_pct, passed)
                    )
                except Exception:
                    conn.rollback()
                return correct, total, passed

    correct, total, passed = await _run(_sync)
    score = round((correct / total) * 100) if total else 0
    return web.json_response({
        "ok": True,
        "correct": correct,
        "total": total,
        "score": score,
        "passed": passed,
    })


# ================== АДМИН: АКАДЕМИЯ ==================
@routes.post('/api/admin/academy/courses')
async def handle_admin_academy_courses(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "academy_edit")
    if perm_err:
        return perm_err

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT c.*,
                              COUNT(DISTINCT l.id) AS lessons_count,
                              COUNT(DISTINCT q.id) AS questions_count
                       FROM academy_courses c
                       LEFT JOIN academy_lessons l ON l.course_id = c.id
                       LEFT JOIN academy_questions q ON q.course_id = c.id
                       GROUP BY c.id
                       ORDER BY c.sort, c.id"""
                )
                return [dict(r) for r in cur.fetchall()]

    courses = await _run(_sync)
    return web.json_response({"courses": courses})


@routes.post('/api/admin/academy/course/save')
async def handle_admin_academy_course_save(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "academy_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    cid = safe_int(body.get("id"))
    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    category = (body.get("category") or "Общее").strip()[:100]
    is_published = bool(body.get("is_published", True))
    if not title:
        return web.json_response({"error": "empty_title"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if cid > 0:
                    cur.execute(
                        "UPDATE academy_courses SET title = %s, description = %s, category = %s, is_published = %s WHERE id = %s RETURNING *",
                        (title, description, category, is_published, cid)
                    )
                else:
                    cur.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM academy_courses")
                    sort_val = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO academy_courses (title, description, category, is_published, sort) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                        (title, description, category, is_published, sort_val)
                    )
                item = dict(cur.fetchone())
                cur.execute(
                    "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)",
                    (admin["user_id"], "academy_course_save", "academy_course", str(item["id"]), f"title={title}")
                )
                return item

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/academy/course/delete')
async def handle_admin_academy_course_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "academy_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    cid = safe_int(body.get("id"))
    if cid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM academy_questions WHERE course_id = %s", (cid,))
                cur.execute("DELETE FROM academy_lessons WHERE course_id = %s", (cid,))
                cur.execute("DELETE FROM academy_courses WHERE id = %s", (cid,))
                cur.execute(
                    "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)",
                    (admin["user_id"], "academy_course_delete", "academy_course", str(cid), "")
                )

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/academy/lesson/save')
async def handle_admin_academy_lesson_save(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "academy_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    lid = safe_int(body.get("id"))
    cid = safe_int(body.get("course_id"))
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    video_url = (body.get("video_url") or "").strip() or None
    if cid <= 0 or not title:
        return web.json_response({"error": "invalid_data"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if lid > 0:
                    cur.execute(
                        "UPDATE academy_lessons SET course_id = %s, title = %s, content = %s, video_url = %s WHERE id = %s RETURNING *",
                        (cid, title, content, video_url, lid)
                    )
                else:
                    cur.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM academy_lessons WHERE course_id = %s", (cid,))
                    sort_val = cur.fetchone()[0]
                    cur.execute(
                        "INSERT INTO academy_lessons (course_id, title, content, video_url, sort) VALUES (%s, %s, %s, %s, %s) RETURNING *",
                        (cid, title, content, video_url, sort_val)
                    )
                return dict(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/academy/lesson/delete')
async def handle_admin_academy_lesson_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "academy_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    lid = safe_int(body.get("id"))
    if lid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM academy_lessons WHERE id = %s", (lid,))

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/academy/question/save')
async def handle_admin_academy_question_save(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "academy_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    qid = safe_int(body.get("id"))
    cid = safe_int(body.get("course_id"))
    question = (body.get("question") or "").strip()
    options = body.get("options") or []
    correct_index = safe_int(body.get("correct_index"))
    if cid <= 0 or not question or not isinstance(options, list) or len(options) < 2:
        return web.json_response({"error": "invalid_data"}, status=400)
    if correct_index < 0 or correct_index >= len(options):
        return web.json_response({"error": "invalid_correct_index"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                opts_json = json.dumps(options, ensure_ascii=False)
                if qid > 0:
                    cur.execute(
                        "UPDATE academy_questions SET course_id = %s, question = %s, options = %s, correct_index = %s WHERE id = %s RETURNING *",
                        (cid, question, opts_json, correct_index, qid)
                    )
                else:
                    cur.execute(
                        "INSERT INTO academy_questions (course_id, question, options, correct_index) VALUES (%s, %s, %s, %s) RETURNING *",
                        (cid, question, opts_json, correct_index)
                    )
                return dict(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/academy/question/delete')
async def handle_admin_academy_question_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "academy_edit")
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
                cur.execute("DELETE FROM academy_questions WHERE id = %s", (qid,))

    await _run(_sync)
    return web.json_response({"ok": True})
