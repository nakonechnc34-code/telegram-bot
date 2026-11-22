from aiohttp import web
from psycopg2.extras import RealDictCursor
from db import get_conn, _run
from utils.auth_helpers import get_auth_user, get_admin_user, denied, require_perm, _is_tu, _sync_get_tu_rests, _is_hr_or_super
from utils.common import safe_int
from utils.security import sanitize_html, sanitize_standard_html
import json
from utils.standard_docx import convert_standard_docx
from zipfile import BadZipFile, ZipFile

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
@routes.post('/api/admin/news')
async def handle_admin_news_list(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """SELECT n.id, n.title, n.body, n.image_url, n.status, n.level, n.created_at, n.restaurant_key,
                                  COALESCE(u.full_name, 'Редакция') AS author_name,
                                  COALESCE(u.full_name, 'Редакция') AS proposed_by,
                                  r.name AS restaurant_name
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
@routes.post('/api/admin/news/add')
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
    level = body.get("level") if body.get("level") in ("normal", "announcement", "event", "urgent", "important") else "normal"
    intent = body.get("intent") or "publish"

    if intent == "suggest":
        status = "pending"
    elif intent == "schedule":
        status = "scheduled"
    else:
        status = "published"

    publish_at = body.get("publish_at")

    if not title or not text:
        return web.json_response({"error": "empty_fields"}, status=400)
    if _is_tu(admin):
        allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"])
        if not restaurant_key or not allowed_rests or restaurant_key not in allowed_rests:
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                try:
                    cur.execute(
                        """INSERT INTO news (title, body, image_url, author_id, restaurant_key, status, level, publish_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                        (title, text, image_url or None, admin["user_id"], restaurant_key, status, level, publish_at)
                    )
                except Exception:
                    conn.rollback()
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
    level = body.get("level")
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
                if status in ("published", "draft", "pending", "rejected", "scheduled"):
                    cur.execute("UPDATE news SET status = %s WHERE id = %s", (status, nid))
                if level in ("normal", "announcement", "event", "urgent", "important"):
                    try:
                        cur.execute("UPDATE news SET level = %s WHERE id = %s", (level, nid))
                    except Exception:
                        pass
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

    def _sync_get():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, restaurant_key FROM news WHERE id = %s", (nid,))
                row = cur.fetchone()
                return dict(row) if row else None

    existing = await _run(_sync_get)
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


@routes.post('/api/admin/news/approve')
async def handle_admin_news_approve(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(admin):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    nid = safe_int(body.get("id"))
    if nid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE news SET status = 'published' WHERE id = %s", (nid,))

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/news/reject')
async def handle_admin_news_reject(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(admin):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    nid = safe_int(body.get("id"))
    if nid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE news SET status = 'rejected' WHERE id = %s", (nid,))

    await _run(_sync)
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
@routes.post('/api/admin/standards')
async def handle_admin_standards_list(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"]) if _is_tu(admin) else None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """SELECT s.id, s.title, s.body, s.category, s.group_name, s.number,
                                  s.file_url, s.file_name, s.image_url, s.content_type, s.content_data,
                                  s.status, s.created_at, s.restaurant_key,
                                  COALESCE(u.full_name, 'Редакция') AS author_name,
                                  COALESCE(u.full_name, 'Редакция') AS proposed_by,
                                  r.name AS restaurant_name
                           FROM standards s LEFT JOIN users u ON s.author_id = u.user_id
                           LEFT JOIN restaurants r ON s.restaurant_key = r.key"""
                params = []
                if allowed_rests is not None:
                    if not allowed_rests:
                        return []
                    query += " WHERE s.restaurant_key = ANY(%s)"
                    params.append(allowed_rests)
                query += " ORDER BY s.created_at DESC LIMIT 100"
                try:
                    cur.execute(query, params)
                    return [dict(r) for r in cur.fetchall()]
                except Exception:
                    conn.rollback()
                    # fallback на базовые поля, если в БД нет новых колонок
                    cur.execute("""
                        SELECT s.id, s.title, s.body, s.category, s.file_url,
                               s.status, s.created_at, s.restaurant_key,
                               COALESCE(u.full_name, 'Редакция') AS author_name,
                               COALESCE(u.full_name, 'Редакция') AS proposed_by,
                               r.name AS restaurant_name
                        FROM standards s LEFT JOIN users u ON s.author_id = u.user_id
                        LEFT JOIN restaurants r ON s.restaurant_key = r.key
                        ORDER BY s.created_at DESC LIMIT 100
                    """)
                    return [dict(r) for r in cur.fetchall()]

    items = await _run(_sync)
    return web.json_response({"standards": items})


@routes.post('/api/admin/standard/import-docx')
async def handle_admin_standard_import_docx(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "standards_edit")
    if perm_err:
        return perm_err
    if request.content_length and request.content_length > 3 * 1024 * 1024:
        return web.json_response({"error": "file_too_large"}, status=413)
    try:
        reader = await request.multipart()
        part = await reader.next()
        if not part or part.name != 'file' or not (part.filename or '').lower().endswith('.docx'):
            return web.json_response({"error": "invalid_docx"}, status=400)
        data = await part.read(decode=False)
        if len(data) > 3 * 1024 * 1024 or not data.startswith(b'PK'):
            return web.json_response({"error": "invalid_docx_or_too_large"}, status=400)
        with ZipFile(__import__('io').BytesIO(data)) as archive:
            if len(archive.infolist()) > 1000 or sum(info.file_size for info in archive.infolist()) > 15 * 1024 * 1024:
                return web.json_response({"error": "document_too_large"}, status=413)
        html = convert_standard_docx(data)
        if len(html) > 100000:
            return web.json_response({"error": "document_too_large"}, status=413)
        return web.json_response({"ok": True, "html": html})
    except (BadZipFile, ValueError, KeyError, OSError):
        return web.json_response({"error": "invalid_docx"}, status=400)


@routes.post('/api/admin/standard/add')
async def handle_admin_standard_add(request):
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

    title = (body.get("title") or "").strip()
    text = sanitize_standard_html((body.get("body") or "").strip())
    number = (body.get("number") or "").strip() or None
    group_name = (body.get("group_name") or "Общее").strip()[:100]
    content_type = body.get("content_type") if body.get("content_type") in ("text", "table") else "text"
    content_data = body.get("content_data")
    image_url = (body.get("image_url") or "").strip() or None
    file_url = (body.get("file_url") or "").strip() or None
    file_name = (body.get("file_name") or "").strip() or None
    restaurant_key = (body.get("restaurant_key") or "").strip() or None
    status = "published" if _is_hr_or_super(admin) else "pending"

    if not title:
        return web.json_response({"error": "empty_title"}, status=400)

    if _is_tu(admin) and restaurant_key:
        allowed_rests = await _run(_sync_get_tu_rests, admin["user_id"])
        if restaurant_key not in (allowed_rests or []):
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    content_data_json = json.dumps(content_data, ensure_ascii=False) if content_data else None

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                try:
                    cur.execute(
                        """INSERT INTO standards
                           (title, body, number, group_name, category, content_type, content_data,
                            image_url, file_url, file_name, author_id, restaurant_key, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (title, text, number, group_name, group_name, content_type, content_data_json,
                         image_url, file_url, file_name, admin["user_id"], restaurant_key, status)
                    )
                except Exception:
                    conn.rollback()
                    cur.execute(
                        """INSERT INTO standards
                           (title, body, category, file_url, author_id, restaurant_key, status)
                           VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                        (title, text, group_name, file_url, admin["user_id"], restaurant_key, status)
                    )
                item = dict(cur.fetchone())
                cur.execute(
                    "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)",
                    (admin["user_id"], "standard_add", "standard", str(item["id"]), f"title={title}")
                )
                return item

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


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
    text = sanitize_standard_html((body.get("body") or "").strip())
    number = body.get("number")
    group_name = body.get("group_name")
    category = body.get("category")
    file_url = body.get("file_url")
    file_name = body.get("file_name")
    image_url = body.get("image_url")
    content_type = body.get("content_type")
    content_data = body.get("content_data")
    status = body.get("status")
    restaurant_key = body.get("restaurant_key")

    if allowed_rests is not None and restaurant_key is not None:
        rk = (restaurant_key or "").strip()
        if not rk or rk not in allowed_rests:
            return web.json_response({"error": "forbidden_restaurant"}, status=403)

    content_data_json = json.dumps(content_data, ensure_ascii=False) if content_data else None

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                updates = []
                params = []
                if title:
                    updates.append("title = %s"); params.append(title)
                if text:
                    updates.append("body = %s"); params.append(text)
                if number is not None:
                    try:
                        updates.append("number = %s"); params.append(number or None)
                    except Exception:
                        pass
                if group_name is not None:
                    try:
                        updates.append("group_name = %s"); params.append((group_name or "Общее").strip()[:100])
                    except Exception:
                        pass
                if category is not None:
                    updates.append("category = %s"); params.append((category or "Общее").strip()[:100])
                if file_url is not None:
                    updates.append("file_url = %s"); params.append((file_url or "").strip() or None)
                if file_name is not None:
                    try:
                        updates.append("file_name = %s"); params.append((file_name or "").strip() or None)
                    except Exception:
                        pass
                if image_url is not None:
                    try:
                        updates.append("image_url = %s"); params.append((image_url or "").strip() or None)
                    except Exception:
                        pass
                if content_type in ("text", "table"):
                    try:
                        updates.append("content_type = %s"); params.append(content_type)
                    except Exception:
                        pass
                if content_data is not None:
                    try:
                        updates.append("content_data = %s"); params.append(content_data_json)
                    except Exception:
                        pass
                if status in ("published", "draft", "pending", "rejected"):
                    updates.append("status = %s"); params.append(status)
                if restaurant_key is not None:
                    updates.append("restaurant_key = %s"); params.append((restaurant_key or "").strip() or None)

                if updates:
                    try:
                        cur.execute(
                            "UPDATE standards SET " + ", ".join(updates) + " WHERE id = %s",
                            params + [sid]
                        )
                    except Exception:
                        conn.rollback()
                        # если в БД нет новых колонок — обновим только базовые поля
                        base_updates = []
                        base_params = []
                        if title: base_updates.append("title = %s"); base_params.append(title)
                        if text: base_updates.append("body = %s"); base_params.append(text)
                        if category is not None: base_updates.append("category = %s"); base_params.append((category or "Общее").strip()[:100])
                        if file_url is not None: base_updates.append("file_url = %s"); base_params.append((file_url or "").strip() or None)
                        if status in ("published", "draft", "pending", "rejected"): base_updates.append("status = %s"); base_params.append(status)
                        if restaurant_key is not None: base_updates.append("restaurant_key = %s"); base_params.append((restaurant_key or "").strip() or None)
                        if base_updates:
                            cur.execute("UPDATE standards SET " + ", ".join(base_updates) + " WHERE id = %s", base_params + [sid])

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


@routes.post('/api/admin/standard/approve')
async def handle_admin_standard_approve(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(admin):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    sid = safe_int(body.get("id"))
    if sid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE standards SET status = 'published' WHERE id = %s", (sid,))

    await _run(_sync)
    return web.json_response({"ok": True})


@routes.post('/api/admin/standard/reject')
async def handle_admin_standard_reject(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not _is_hr_or_super(admin):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    sid = safe_int(body.get("id"))
    if sid <= 0:
        return web.json_response({"error": "invalid_id"}, status=400)

    def _sync():
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE standards SET status = 'rejected' WHERE id = %s", (sid,))

    await _run(_sync)
    return web.json_response({"ok": True})


# ================== FAQ ==================
@routes.post('/api/faq')
@routes.post('/api/admin/faq')
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
@routes.post('/api/admin/faq/add')
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
                    cur.execute("SELECT COALESCE(MAX(sort), 0) + 1 AS next_sort FROM faq")
                    sort_val = cur.fetchone()["next_sort"]
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
def _cert_row_to_admin_format(r):
    """admin.js ожидает option_a..d + correct_option; БД хранит options + correct_index."""
    d = dict(r)
    opts = d.get("options")
    if isinstance(opts, str):
        try:
            opts = json.loads(opts)
        except Exception:
            opts = []
    if not isinstance(opts, list):
        opts = []
    d["options"] = opts
    d["option_a"] = opts[0] if len(opts) > 0 else ""
    d["option_b"] = opts[1] if len(opts) > 1 else ""
    d["option_c"] = opts[2] if len(opts) > 2 else ""
    d["option_d"] = opts[3] if len(opts) > 3 else ""
    ci = d.get("correct_index")
    if isinstance(ci, int) and 0 <= ci <= 3:
        d["correct_option"] = "abcd"[ci]
    else:
        d["correct_option"] = "a"
    return d


@routes.post('/api/certification/questions')
async def handle_certification_questions(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, question, options FROM certification_questions ORDER BY id")
                return [_cert_row_to_admin_format(r) for r in cur.fetchall()]

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
@routes.post('/api/admin/certification')
async def handle_admin_certification_questions(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "certification_edit")
    if perm_err:
        return perm_err

    def _sync():
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id, question, options, correct_index FROM certification_questions ORDER BY id")
                return [_cert_row_to_admin_format(r) for r in cur.fetchall()]

    items = await _run(_sync)
    return web.json_response({"questions": items})


@routes.post('/api/admin/certification/question/save')
@routes.post('/api/admin/certification/add')
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

    # Поддерживаем оба формата: options/correct_index и option_a..d/correct_option
    if "options" in body and isinstance(body.get("options"), list):
        options = body["options"]
        correct_index = safe_int(body.get("correct_index"))
    else:
        opts = [body.get("option_a"), body.get("option_b"), body.get("option_c"), body.get("option_d")]
        options = [str(o).strip() if o is not None else "" for o in opts]
        if not any(options):
            return web.json_response({"error": "invalid_options"}, status=400)
        correct_letter = (body.get("correct_option") or "a").lower()
        correct_index = {"a": 0, "b": 1, "c": 2, "d": 3}.get(correct_letter, 0)

    if not question or not isinstance(options, list) or len(options) < 2:
        return web.json_response({"error": "invalid_data"}, status=400)
    if correct_index < 0 or correct_index >= len(options):
        return web.json_response({"error": "invalid_correct_index"}, status=400)

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
                return _cert_row_to_admin_format(cur.fetchone())

    item = await _run(_sync)
    return web.json_response({"ok": True, "item": item})


@routes.post('/api/admin/certification/question/delete')
@routes.post('/api/admin/certification/delete')
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
