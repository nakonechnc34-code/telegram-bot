import os
import asyncio
import logging
import gzip
import traceback
import json
import time
from datetime import datetime, date
from decimal import Decimal
from email.utils import formatdate
from aiohttp import web

import config
from db import init_pool, close_pool, get_conn
from middleware.cache import clear_cache

# ============= START TIME =============
START_TIME = time.time()

# ============= SENTRY INIT =============
if config.SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        traces_sample_rate=0.1,
        environment=config.APP_ENV,
        release=f"app@1.2.0",
    )
    logging.info("📡 Sentry initialized")

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
from routes.sales import routes as sales_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ============= МИГРАЦИИ БАЗЫ ДАННЫХ =============
def run_migrations():
    """Автоматически добавляет нужные колонки в БД при старте и создает папку uploads"""
    try:
        # Определяем базовую папку для файлов (постоянное хранилище или локальная)
        base_dir = "/data" if os.path.exists("/data") else os.path.dirname(os.path.abspath(__file__))
        upload_dir = os.path.join(base_dir, "uploads")

        os.makedirs(upload_dir, exist_ok=True)
        logging.info(f"✅ Папка для загрузок проверена/создана: {upload_dir}")

        # МИГРАЦИИ БД
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Колонки табеля
                cur.execute("ALTER TABLE timesheet_records ADD COLUMN IF NOT EXISTS restaurant_key TEXT;")
                cur.execute("ALTER TABLE timesheet_records ADD COLUMN IF NOT EXISTS start_time TIME;")
                cur.execute("ALTER TABLE timesheet_records ADD COLUMN IF NOT EXISTS end_time TIME;")
                # Колонка сотрудников
                cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS personnel_number VARCHAR(50);")
                # Таблица выплат (если ещё не создана)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS payments (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                        amount NUMERIC(10,2) NOT NULL,
                        comment TEXT NOT NULL,
                        payment_date DATE DEFAULT CURRENT_DATE,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        created_by BIGINT,
                        record_type TEXT DEFAULT 'payout',
                        status TEXT DEFAULT 'approved',
                        proposed_by_name TEXT,
                        approved_by_name TEXT
                    )
                """)
                # Индексы БД (для производительности)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_web_sessions_token ON web_sessions(token);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_users_login ON users(LOWER(login));")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_timesheet_records_date ON timesheet_records(user_id, work_date);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_news_status ON news(status);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_standards_status ON standards(status);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date, status);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_date ON payments(user_id, payment_date);")

                # Миграция: таблицы товарооборота
                sales_sql_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "002_create_sales_tables.sql")
                if os.path.exists(sales_sql_path):
                    with open(sales_sql_path, "r") as f:
                        sales_sql = f.read()
                    cur.execute(sales_sql)
                    logging.info("✅ Миграция БД: таблицы товарооборота проверены/добавлены.")

                logging.info("✅ Миграция БД: колонки, таблицы и индексы проверены/добавлены.")
    except Exception as e:
        logging.error(f"❌ Ошибка миграции/создания папок: {e}")

# Мусорные пути от сканеров — не логируем
_SPAM_PATHS = (
    '/phpmyadmin', '/pma', '/phpMyAdmin',
    '/wp-admin', '/wp-login', '/wp-content', '/wp-includes', '/xmlrpc.php',
    '/.env', '/.git', '/.svn',
    '/actuator', '/actuator/health',
    '/api/v1/', '/swagger', '/swagger-ui',
    '/robots.txt',
)

# API эндпоинты, ожидающие только POST — игнорируем GET запросы (сканеры/bots)
_POST_ONLY_API_PATHS = (
    '/api/admin/question/reply',
)

# PWA-ресурсы — не логируем
_PWA_PATHS = (
    '/manifest.json', '/sw.js', '/favicon.ico',
    '/icon-192.svg', '/icon-512.svg', '/icon-192.png', '/icon-512.png',
    '/screenshot1.png', '/.well-known/assetlinks.json',
)

# ============= MIDDLEWARES =============

@web.middleware
async def error_middleware(request, handler):
    # Пропускаем мусорные пути — не логируем
    if any(request.path.startswith(sp) for sp in _SPAM_PATHS):
        return await handler(request)
    # Статика /static/ — не логируем ошибки (PWA иконки и т.п.)
    if request.path.startswith('/static/'):
        return await handler(request)
    # POST-only API эндпоинты — игнорируем GET запросы (сканеры/bots)
    if request.method == 'GET' and request.path in _POST_ONLY_API_PATHS:
        return web.Response(status=405)
    # PWA-ресурсы — не логируем ошибки
    if any(request.path == sp for sp in _PWA_PATHS):
        return await handler(request)
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
    # Обновлённый CSP
    csp = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://images.unsplash.com; "
        "connect-src 'self' https://fonts.googleapis.com; "
        "frame-ancestors 'none'; child-src 'none';"
    )
    response.headers["Content-Security-Policy"] = csp
    # Cache-Control для HTML (чтобы не кэшировался)
    if response.content_type == "text/html":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response

@web.middleware
async def request_logging_middleware(request, handler):
    """Middleware: логирует каждый HTTP запрос, пропуская мусор."""
    start = time.time()
    try:
        response = await handler(request)
        duration = time.time() - start
        method = request.method
        path = request.path
        # Пропускаем статику, мусор и PWA-ресурсы
        if (path.startswith('/static/') or path in ('/favicon.ico', '/.well-known/assetlinks.json')
                or any(path.startswith(sp) for sp in _SPAM_PATHS)
                or path in _PWA_PATHS):
            return response
        user_id = request.get('user', {}).get('user_id', '-') if 'user' in request else '-'
        status = response.status if hasattr(response, 'status') else '?'
        logging.info(
            "%s %-8s %-40s %d %.3fs user=%s",
            request.remote or '-',
            method,
            path,
            status,
            duration,
            user_id
        )
        return response
    except Exception as e:
        duration = time.time() - start
        logging.error("Unhandled %s %s: %s", request.method, request.path, str(e)[:100])
        return web.json_response({"error": "internal"}, status=500)

# ============= STATIC FILE SERVING =============
_INDEX_CACHE = {"data": None, "mtime": 0.0}
_ADMIN_CACHE = {"data": None, "mtime": 0.0}
_ACADEMY_CACHE = {"data": None, "mtime": 0.0}
_TIMESHEET_CACHE = {"data": None, "mtime": 0.0}
_SALES_CACHE = {"data": None, "mtime": 0.0}
_STATIC_FILES_CACHE = {}

def _serve_file(name, cache):
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
async def handle_sales_page(request): return await _handle_html("sales.html", _SALES_CACHE)

async def handle_admin_css(request):
    data, mtime = _serve_file("admin.css", _STATIC_FILES_CACHE.setdefault("admin.css", {"data": None, "mtime": 0.0}))
    if not data: return web.Response(text="admin.css not found", status=404)
    return web.Response(
        body=data,
        content_type="text/css",
        charset="utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Last-Modified": formatdate(mtime, usegmt=True)
        }
    )

async def handle_sales_css(request):
    data, mtime = _serve_file("sales.css", _STATIC_FILES_CACHE.setdefault("sales.css", {"data": None, "mtime": 0.0}))
    if not data: return web.Response(text="sales.css not found", status=404)
    return web.Response(
        body=data,
        content_type="text/css",
        charset="utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Last-Modified": formatdate(mtime, usegmt=True)
        }
    )

async def handle_sales_js(request):
    data, mtime = _serve_file("sales.js", _STATIC_FILES_CACHE.setdefault("sales.js", {"data": None, "mtime": 0.0}))
    if not data: return web.Response(text="sales.js not found", status=404)
    return web.Response(
        body=data,
        content_type="application/javascript",
        charset="utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "Last-Modified": formatdate(mtime, usegmt=True)
        }
    )

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

async def handle_robots_txt(request):
    return web.Response(text="User-agent: *\nDisallow: /\n", content_type="text/plain")

# ============= HEALTH CHECK =============
async def handle_health(request):
    """Health check с проверкой БД."""
    db_status = "ok"
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as e:
        db_status = f"error: {str(e)[:100]}"

    status = "healthy" if db_status == "ok" else "degraded"
    return web.json_response({
        "status": status,
        "database": db_status,
        "uptime": round(time.time() - START_TIME, 1),
        "version": "1.2.0",
        "env": config.APP_ENV
    })

# ============= СКАЧИВАНИЕ ФАЙЛОВ (API) =============
async def handle_download(request):
    # 1. Берем токен из URL
    token = request.query.get('webToken')
    if not token:
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

    if not token:
        return web.Response(status=401, text="Unauthorized: No token provided")

    # 2. Берем имя файла
    filename = request.match_info.get('filename')
    safe_filename = os.path.basename(filename) # Защита от Path Traversal

    # Ищем файл в постоянном хранилище (/data) или локальной папке
    base_dir = "/data" if os.path.exists("/data") else os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(base_dir, "uploads")
    filepath = os.path.join(upload_dir, safe_filename)

    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: реальный путь должен быть внутри upload_dir
    real_upload_dir = os.path.realpath(upload_dir)
    real_filepath = os.path.realpath(filepath)
    if not real_filepath.startswith(real_upload_dir + os.sep):
        logging.warning(f"Path traversal attempt: {filename}")
        return web.Response(status=403, text="Forbidden")

    if not os.path.exists(filepath):
        return web.Response(status=404, text="File not found")

    # 3. Отдаем файл
    return web.FileResponse(filepath)

# ============= APP SETUP =============
app = web.Application(
    middlewares=[
        error_middleware,
        request_logging_middleware,
        gzip_middleware,
        security_headers_middleware,
    ],
    client_max_size=20 * 1024 * 1024,
)

app.add_routes(auth_routes)
app.add_routes(users_routes)
app.add_routes(medbooks_routes)
app.add_routes(timesheet_routes)
app.add_routes(content_routes)
app.add_routes(core_routes)
app.add_routes(academy_routes)
app.add_routes(sales_routes)

app.router.add_get("/", handle_index)
app.router.add_get("/admin", handle_admin_page)
app.router.add_get("/admin/", handle_admin_page)
app.router.add_get("/sales", handle_sales_page)
app.router.add_get("/sales/", handle_sales_page)
app.router.add_get("/admin.css", handle_admin_css)
app.router.add_get("/sales.css", handle_sales_css)
app.router.add_get("/sales.js", handle_sales_js)
app.router.add_get("/academy", handle_academy_page)
app.router.add_get("/academy/", handle_academy_page)
app.router.add_get("/timesheet", handle_timesheet_page)
app.router.add_get("/timesheet/", handle_timesheet_page)
app.router.add_get("/api/health", handle_health)
app.router.add_get("/manifest.json", handle_manifest)
app.router.add_get("/sw.js", handle_sw)
app.router.add_get("/static/icon-192.svg", handle_icon192)
app.router.add_get("/static/icon-512.svg", handle_icon512)
app.router.add_get("/.well-known/assetlinks.json", handle_assetlinks)
app.router.add_get("/robots.txt", handle_robots_txt)
app.router.add_get("/favicon.ico", handle_favicon)

# РОУТ ДЛЯ СКАЧИВАНИЯ
app.router.add_get("/api/download/{filename:.*}", handle_download)

# ============= MAIN =============
async def main():
    port = int(os.getenv("PORT", 8080))

    logging.info("⏳ Инициализация пула БД...")
    await asyncio.to_thread(init_pool)

    if os.getenv("RUN_MIGRATIONS", "true").lower() == "true":
        logging.info("⏳ Запуск миграций БД и проверки папок...")
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
