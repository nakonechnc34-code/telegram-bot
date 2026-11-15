from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, denied
import json

routes = web.RouteTableDef()

def _safe_int(val, default=0):
    try: return int(val)
    except: return default

def _sync_academy_courses(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT c.*, 
                       COALESCE(p.status, 'new') as status,
                       COALESCE(p.score, 0) as score
                FROM academy_courses c
                LEFT JOIN academy_progress p ON c.id = p.course_id AND p.user_id = %s
                ORDER BY c.id
            """, (user_id,))
            return [dict(r) for r in cur.fetchall()]

@routes.post('/api/academy/courses')
async def handle_academy_courses(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    courses = await _run(_sync_academy_courses, user["user_id"])
    return web.json_response({"courses": courses})

def _sync_academy_course_detail(course_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM academy_courses WHERE id = %s", (course_id,))
            course = cur.fetchone()
            if not course: return None, None, None
            
            cur.execute("SELECT * FROM academy_lessons WHERE course_id = %s ORDER BY sort", (course_id,))
            lessons = [dict(r) for r in cur.fetchall()]
            
            cur.execute("SELECT * FROM academy_tests WHERE course_id = %s", (course_id,))
            tests = [dict(r) for r in cur.fetchall()]
            
            return dict(course), lessons, tests

@routes.post('/api/academy/course')
async def handle_academy_course_detail(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    cid = _safe_int(body.get("course_id"))
    if cid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    course, lessons, tests = await _run(_sync_academy_course_detail, cid)
    if not course: return web.json_response({"error": "not_found"}, status=404)
    
    for t in tests:
        del t["correct_index"]
        
    return web.json_response({"course": course, "lessons": lessons, "tests": tests})

@routes.post('/api/academy/submit-test')
async def handle_academy_submit_test(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    cid = _safe_int(body.get("course_id"))
    answers = body.get("answers") or {}
    
    if cid <= 0 or not answers:
        return web.json_response({"error": "invalid_data"}, status=400)
        
    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, correct_index FROM academy_tests WHERE course_id = %s", (cid,))
                correct_db = {str(r["id"]): r["correct_index"] for r in cur.fetchall()}
                
                total = len(correct_db)
                if total == 0: return {"ok": True, "passed": True, "score": 100}
                    
                correct_count = 0
                for qid, ans in answers.items():
                    if str(correct_db.get(qid)) == str(ans):
                        correct_count += 1
                        
                score = int((correct_count / total) * 100)
                passed = score >= 80
                
                if passed:
                    cur.execute("""
                        INSERT INTO academy_progress (user_id, course_id, status, score, updated_at)
                        VALUES (%s, %s, 'completed', %s, NOW())
                        ON CONFLICT (user_id, course_id) DO UPDATE 
                        SET status = 'completed', score = GREATEST(academy_progress.score, EXCLUDED.score), updated_at = NOW()
                    """, (user["user_id"], cid, score))
                    
                    cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", 
                                (user["user_id"], "academy_test_pass", "course", str(cid), f"score={score}"))
        return {"ok": True, "passed": passed, "score": score}

    result = await _run(_sync)
    return web.json_response(result)
