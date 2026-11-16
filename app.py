import os
import asyncio
import logging
import gzip
import traceback
import json
from datetime import datetime, date
from decimal import Decimal
from email.utils import formatdate # Добавили для кэширования
from aiohttp import web

import config
from db import init_pool, close_pool, get_conn

# ============= JSON SERIALIZER FIX =============
def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def _json_dumps(data):
    return json.dumps(data, ensure_ascii=False, default=_json_default)

_orig_json_response = web.json_response
def _safe_json_response(data=None, *args, **kwargs):
    kwargs.setdefault("dumps", _json_dumps)
    return _orig_json_response(data, *args, **kwargs)
web.json_response = _safe_json_response

# ============= ИМПОРТ ВСЕХ РОУТОВ =============
from routes.auth import routes as auth_routes
from routes.users import routes as users_routes
from routes.medbooks import routes as medbooks_routes
from routes.timesheet import routes as timesheet_routes
from routes.content import routes as content_routes
from routes.core import routes as core_routes
from routes.academy import routes as academy_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ============= МИГРАЦИИ БАЗЫ ДАННЫХ =============
def run_migrations():
    """Автоматически добавляет нужные колонки в БД при старте"""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE timesheet_records ADD COLUMN IF NOT EXISTS restaurant_key TEXT;")
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS personnel_number VARCHAR(50);")
                logging.info("✅ Миграция БД: колонки проверены/добавлены.")
    except Exception as e:
        logging.error(f"❌ Ошибка миграции БД: {e}")

# ============= MIDDLEWARES =============
@web.middleware
async def error_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        logging.error("Unhandled %s %s: %s\n%s", request.method, request.path, type(e).__name__, traceback.format_exc())
        detail = str(e)[:200] if config.APP_ENV != "production" else "Internal Server Error"
        return web.json_response({"error": "internal", "detail": detail}, status=500)

_GZIP_TYPES = ("application/json", "text/plain", "text/html", "text/css", "application/javascript", "image/svg+xml")

@web.middleware
async def gzip_middleware(request, handler):
    response = await handler(request)
    body = getattr(response, "body", None)
    if (body is not None and len(body) > 500 and "gzip" in request.headers.get("Accept-Encoding", "")
            and not response.headers.get("Content-Encoding") and response.content_type in _GZIP_TYPES):
        
        body_bytes = body.encode('utf-8') if isinstance(body, str) else body
        try:
            compressed = gzip.compress(body_bytes, compresslevel=6)
            if len(compressed) < len(body_bytes):
                response.body = compressed
                response.headers["Content-Encoding"] = "gzip"
                if "Content-Length" in response.headers:
                    del response.headers["Content-Length"]
                response.headers["Vary"] = "Accept-Encoding"
        except Exception as e:
            logging.warning(f"Gzip compression failed: {e}")
    return response

@web.middleware
async def security_headers_middleware(request, handler):
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # TODO: В будущем убрать 'unsafe-inline', вынеся JS в отдельные файлы
    csp = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://images.unsplash.com; "
        "connect-src 'self' https://fonts.googleapis.com; frame-ancestors 'none';"
    )
    response.headers["Content-Security-Policy"] = csp
    return response

# ============= STATIC FILE SERVING =============
_INDEX_CACHE = {"data": None, "mtime": 0.0}
_ADMIN_CACHE = {"data": None, "mtime": 0.0}
_ACADEMY_CACHE = {"data": None, "mtime": 0.0}
_TIMESHEET_CACHE = {"data": None, "mtime": 0.0}
_STATIC_FILES_CACHE = {}

def _serve_file(name, cache):
    """Возвращает (data, mtime)"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", name)
    if not os.path.exists(p): return None, 0
    try:
        mtime = os.stat(p).st_mtime
        if cache["data"] is None or cache["mtime"] != mtime:
            with open(p, "rb") as f: cache["data"] = f.read()
            cache["mtime"] = mtime
        return cache["data"], mtime
    except OSError: return None, 0

async def _handle_html(name, cache):
    data, mtime = _serve_file(name, cache)
    if not data: return web.Response(text=f"frontend/{name} not found", status=404)
    return web.Response(
        body=data, 
        content_type="text/html", 
        charset="utf-8",
        headers={"Last-Modified": formatdate(mtime, usegmt=True)}
    )

async def handle_index(request): return await _handle_html("index.html", _INDEX_CACHE)
async def handle_admin_page(request): return await _handle_html("admin.html", _ADMIN_CACHE)
async def handle_academy_page(request): return await _handle_html("academy.html", _ACADEMY_CACHE)
async def handle_timesheet_page(request): return await _handle_html("timesheet.html", _TIMESHEET_CACHE)

async def _send_static_file(name, content_type):
    if name not in _STATIC_FILES_CACHE: _STATIC_FILES_CACHE[name] = {"data": None, "mtime": 0.0}
    data, mtime = _serve_file(name, _STATIC_FILES_CACHE[name])
    if not data: return web.Response(status=404)
    kwargs = {"body": data, "content_type": content_type}
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/manifest+json"):
        kwargs["charset"] = "utf-8"
    kwargs["headers"] = {"Last-Modified": formatdate(mtime, usegmt=True)}
    return web.Response(**kwargs)

async def handle_manifest(request): return await _send_static_file("manifest.json", "application/manifest+json")
async def handle_sw(request): return await _send_static_file("sw.js", "application/javascript")
async def handle_icon192(request): return await _send_static_file("icon-192.svg", "image/svg+xml")
async def handle_icon512(request): return await _send_static_file("icon-512.svg", "image/svg+xml")
async def handle_icon192_png(request): return await _send_static_file("icon-192.png", "image/png")
async def handle_icon512_png(request): return await _send_static_file("icon-512.png", "image/png")
async def handle_screenshot(request): return await _send_static_file("screenshot1.png", "image/png")
async def handle_assetlinks(request): return await _send_static_file(".well-known/assetlinks.json", "application/json")

async def handle_favicon(request): return web.Response(status=204)
async def handle_health(request): return web.Response(text="OK")

# ============= APP SETUP =============
app = web.Application(
    middlewares=[error_middleware, gzip_middleware, security_headers_middleware],
    client_max_size=20 * 1024 * 1024,
)

app.add_routes(auth_routes)
app.add_routes(users_routes)
app.add_routes(medbooks_routes)
app.add_routes(timesheet_routes)
app.add_routes(content_routes)
app.add_routes(core_routes)
app.add_routes(academy_routes)

app.router.add_get("/", handle_index)
app.router.add_get("/admin", handle_admin_page)
app.router.add_get("/admin/", handle_admin_page)
app.router.add_get("/academy", handle_academy_page)
app.router.add_get("/academy/", handle_academy_page)
app.router.add_get("/timesheet", handle_timesheet_page)
app.router.add_get("/timesheet/", handle_timesheet_page)
app.router.add_get("/favicon.ico", handle_favicon)
app.router.add_get("/api/health", handle_health)
app.router.add_get("/manifest.json", handle_manifest)
app.router.add_get("/sw.js", handle_sw)
app.router.add_get("/static/icon-192.svg", handle_icon192)
app.router.add_get("/static/icon-512.svg", handle_icon512)
app.router.add_get("/static/icon-192.png", handle_icon192_png)
app.router.add_get("/static/icon-512.png", handle_icon512_png)
app.router.add_get("/static/screenshot1.png", handle_screenshot)
app.router.add_get("/.well-known/assetlinks.json", handle_assetlinks)

# ============= MAIN =============
async def main():
    port = int(os.getenv("PORT", 8080))
    
    # 1. Инициализируем пул соединений в отдельном потоке (не блокируем Event Loop)
    logging.info("⏳ Инициализация пула БД...")
    await asyncio.to_thread(init_pool)
    
    # 2. Запускаем миграции ТОЛЬКО если установлен флаг
    if os.getenv("RUN_MIGRATIONS", "true").lower() == "true":
        logging.info("⏳ Запуск миграций БД...")
        await asyncio.to_thread(run_migrations)
    else:
        logging.info("⏳ Миграции пропущены (RUN_MIGRATIONS=false)")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"✅ Server on port {port}")
    logging.info(f"👤 Admin: {config.ADMIN_LOGIN}")

    try:
        await asyncio.Event().wait()
    finally:
        logging.info("🛑 Завершение работы сервера...")
        await runner.cleanup()
        await asyncio.to_thread(close_pool)

if __name__ == "__main__":
    asyncio.run(main())
