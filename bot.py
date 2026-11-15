import os
import asyncio
import logging
import gzip
import traceback
from aiohttp import web

# Импорт конфигурации и БД
import config
from db import init_pool, close_pool

# Импорт роутов
from routes.auth import routes as auth_routes
from routes.users import routes as users_routes
from routes.medbooks import routes as medbooks_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

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
        compressed = gzip.compress(body, compresslevel=6)
        if len(compressed) < len(body):
            response.body = compressed
            response.headers["Content-Encoding"] = "gzip"
            if "Content-Length" in response.headers: 
                del response.headers["Content-Length"]
            response.headers["Vary"] = "Accept-Encoding"
    return response

@web.middleware
async def security_headers_middleware(request, handler):
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://images.unsplash.com; "
        "connect-src 'self' https://fonts.googleapis.com; "
        "frame-ancestors 'none';"
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
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", name)
    if not os.path.exists(p): return None
    try:
        mtime = os.stat(p).st_mtime
        if cache["data"] is None or cache["mtime"] != mtime:
            with open(p, "rb") as f: 
                cache["data"] = f.read()
            cache["mtime"] = mtime
        return cache["data"]
    except OSError: 
        return None

async def handle_index(request):
    data = _serve_file("index.html", _INDEX_CACHE)
    if not data: return web.Response(text="frontend/index.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

async def handle_admin_page(request):
    data = _serve_file("admin.html", _ADMIN_CACHE)
    if not data: return web.Response(text="frontend/admin.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

async def handle_academy_page(request):
    data = _serve_file("academy.html", _ACADEMY_CACHE)
    if not data: return web.Response(text="frontend/academy.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

async def handle_timesheet_page(request):
    data = _serve_file("timesheet.html", _TIMESHEET_CACHE)
    if not data: return web.Response(text="frontend/timesheet.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

async def _send_static_file(name, content_type):
    if name not in _STATIC_FILES_CACHE: 
        _STATIC_FILES_CACHE[name] = {"data": None, "mtime": 0.0}
    data = _serve_file(name, _STATIC_FILES_CACHE[name])
    if not data: return web.Response(status=404)
    kwargs = {"body": data, "content_type": content_type}
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/manifest+json"):
        kwargs["charset"] = "utf-8"
    return web.Response(**kwargs)

async def handle_manifest(request): 
    return await _send_static_file("manifest.json", "application/manifest+json")
async def handle_sw(request): 
    return await _send_static_file("sw.js", "application/javascript")
async def handle_icon192(request): 
    return await _send_static_file("icon-192.svg", "image/svg+xml")
async def handle_icon512(request): 
    return await _send_static_file("icon-512.svg", "image/svg+xml")
async def handle_favicon(request): 
    return web.Response(status=204)
async def handle_health(request): 
    return web.Response(text="OK")

# ============= APP SETUP =============
app = web.Application(
    middlewares=[error_middleware, gzip_middleware, security_headers_middleware], 
    client_max_size=20 * 1024 * 1024
)

# Регистрация роутов из модулей
app.add_routes(auth_routes)
app.add_routes(users_routes)
app.add_routes(medbooks_routes)

# Регистрация статики и страниц
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

# ============= MAIN =============
async def main():
    port = int(os.getenv("PORT", 8080))
    
    # Инициализируем пул БД
    init_pool()
    
    # Запуск миграций (если нужно)
    if os.getenv("RUN_MIGRATIONS", "true").lower() == "true":
        logging.info("⏳ Миграции пропущены (вынесите init_db_and_seed в отдельный файл для продакшена)")
        # await _run(init_db_and_seed) 

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"✅ Server on port {port}")
    logging.info(f"👤 Admin: {config.ADMIN_LOGIN}")

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        close_pool()

if __name__ == "__main__":
    asyncio.run(main())
