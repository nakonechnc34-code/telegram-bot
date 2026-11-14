import os
import re
import json
import gzip
import logging
import asyncio
import threading
import random
import secrets
import hashlib
import calendar
import traceback
import base64
import uuid
import time
import bleach
from datetime import datetime, date, timezone as _tz
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from decimal import Decimal  # <--- ДОБАВЛЕНО

from aiohttp import web
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor, Json
from psycopg2 import sql
from pywebpush import webpush, WebPushException

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ============= SECURITY & ENV SETTINGS =============
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise ValueError("DATABASE_URL is not set")

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "BMwTeMsr3z1qBO1igGp9Fh2I3ZtAG7ZiuwZiKpCbu3na77MFJJwN2fvk2agYtR0MgjxX_CDjhpfamLV0oBR0TC4")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "gy-5yLP8ymvrjDzf43zsSjWkLbuknlw11wQyI6Ef1kI")

VAPID_CLAIMS = {"sub": "mailto:admin@wokker.ru"}

ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "adm01").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Wokker2026")

APP_ENV = os.getenv("ENV", "development").lower()
LOGIN_RE = re.compile(r"^[a-z]{3}\d{2}$")
SESSION_TTL_DAYS = 30
SESSION_CACHE_TTL = 30  # секунд

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

# ============= SESSION CACHE =============
_session_cache = {}
_session_cache_lock = threading.Lock()

# ============= РУЧНАЯ ВАЛИДАЦИЯ =============
def validate_login_data(body):
    if not isinstance(body, dict):
        return None, "invalid_json"
    login = body.get("login")
    password = body.get("password")
    if not isinstance(login, str) or not isinstance(password, str):
        return None, "invalid_data"
    login = login.strip().lower()
    if not LOGIN_RE.match(login):
        return None, "invalid_login_format"
    if not password:
        return None, "password_required"
    return {"login": login, "password": password}, None

def validate_user_create_data(body):
    if not isinstance(body, dict):
        return None, "invalid_json"
    full_name = (body.get("full_name") or "").strip()
    password = body.get("password") or ""
    if not full_name or len(full_name) > 100:
        return None, "invalid_full_name"
    if not password or len(password) < 6:
        return None, "invalid_password"
    payment_type = body.get("payment_type") or "hourly"
    if payment_type not in ('hourly', 'fixed'):
        return None, "invalid_payment_type"
    citizenship_id = body.get("citizenship_id")
    if citizenship_id == "":
        citizenship_id = None
    elif citizenship_id is not None:
        try:
            citizenship_id = int(citizenship_id)
        except (ValueError, TypeError):
            return None, "invalid_citizenship_id"
    return {
        "full_name": full_name,
        "password": password,
        "phone": (body.get("phone") or "")[:50],
        "birth_date": (body.get("birth_date") or "")[:20],
        "position": (body.get("position") or "")[:100],
        "restaurant_key": (body.get("restaurant_key") or body.get("restaurant") or "")[:100],
        "is_certified": bool(body.get("is_certified")),
        "hire_date": (body.get("hire_date") or "")[:20],
        "citizenship_id": citizenship_id,
        "payment_type": payment_type,
    }, None

def validate_bulk_save_data(body):
    if not isinstance(body, dict):
        return None, "invalid_json"
    cells = body.get("cells")
    if not isinstance(cells, list):
        return None, "invalid_cells"
    cleaned = []
    for cell in cells:
        if not isinstance(cell, dict):
            return None, "invalid_cell"
        try:
            uid = int(cell.get("user_id", 0))
            hours = float(cell.get("hours", 0))
        except (ValueError, TypeError):
            return None, "invalid_cell_data"
        status = cell.get("status", "work")
        if status not in ("work", "vacation", "sick", "absent"):
            return None, "invalid_status"
        work_date = cell.get("work_date")
        if not isinstance(work_date, str):
            return None, "invalid_date"
        cleaned.append({
            "user_id": uid,
            "work_date": work_date,
            "hours": hours,
            "status": status,
        })
    return {"cells": cleaned}, None

# ============= JSON SERIALIZER =============
def _json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):  # <--- ДОБАВЛЕНО
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def _json_dumps(data):
    return json.dumps(data, ensure_ascii=False, default=_json_default)

_orig_json_response = web.json_response
def _safe_json_response(data=None, *args, **kwargs):
    kwargs.setdefault("dumps", _json_dumps)
    return _orig_json_response(data, *args, **kwargs)
web.json_response = _safe_json_response

def _safe_int(val, default=0):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default

# ============= RATE LIMITING =============
_login_attempts = {}
_login_lock = threading.Lock()

def _check_rate_limit(ip):
    now = time.time()
    with _login_lock:
        if ip not in _login_attempts:
            _login_attempts[ip] = []
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < 60]
        if len(_login_attempts[ip]) >= 5:
            return False
        _login_attempts[ip].append(now)
        return True

def _reset_rate_limit(ip):
    with _login_lock:
        _login_attempts.pop(ip, None)

# ============= БЕЗОПАСНОСТЬ HTML (XSS) =============
ALLOWED_TAGS = ['p', 'br', 'strong', 'b', 'i', 'em', 'u', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'blockquote', 'a', 'span', 'div', 'img']
ALLOWED_ATTRS = {
    'a': ['href', 'target', 'rel'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
    'img': ['src', 'alt', 'width', 'height'],
    '*': ['class']
}

def sanitize_html(html_str):
    if not html_str:
        return ""
    return bleach.clean(html_str, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)

# ============= ПРАВА =============
PERMISSIONS_LIST = [
    {"key": "users_create", "label": "Добавлять сотрудников"},
    {"key": "users_edit", "label": "Редактировать сотрудников"},
    {"key": "users_fire", "label": "Увольнять сотрудников"},
    {"key": "citizenships_edit", "label": "Управлять гражданствами"},
    {"key": "medbook_edit", "label": "Заполнять медкнижки"},
    {"key": "medbook_doctors_manage", "label": "Врачи: добавление и сроки"},
    {"key": "medbook_tests_manage", "label": "Анализы: добавление и сроки"},
    {"key": "medbook_vaccines_manage", "label": "Прививки: добавление и сроки"},
    {"key": "restaurant_tu", "label": "Менять ТУ у ресторанов"},
    {"key": "restaurant_create", "label": "Добавлять рестораны"},
    {"key": "restaurant_edit", "label": "Редактировать рестораны"},
    {"key": "standards_edit", "label": "Предлагать стандарты"},
    {"key": "checklist_create", "label": "Создавать чек-листы"},
    {"key": "checklist_edit", "label": "Редактировать чек-листы"},
    {"key": "news_write", "label": "Писать новости"},
    {"key": "news_edit", "label": "Редактировать новости"},
    {"key": "news_suggest", "label": "Предлагать новости"},
    {"key": "faq_edit", "label": "Редактировать FAQ"},
    {"key": "positions_edit", "label": "Управлять должностями"},
    {"key": "questions_reply", "label": "Отвечать на вопросы"},
    {"key": "certification_edit", "label": "Управлять вопросами сертификации"},
    {"key": "academy_edit", "label": "Управлять Академией"},
    {"key": "timesheet_access", "label": "Доступ к Табелю"},
]
PERM_KEYS = [p["key"] for p in PERMISSIONS_LIST]
REF_TYPE_PERM = {
    "doctor": "medbook_doctors_manage",
    "test": "medbook_tests_manage",
    "vaccine": "medbook_vaccines_manage",
}

# ============= ПАРОЛИ =============
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${dk.hex()}"

def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, hash_hex = stored.split("$", 2)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
        return secrets.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False

# ============= ЛОГИН =============
TRANSLIT = {
    "а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z",
    "и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r",
    "с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch",
    "ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya",
}

def _generate_login_for(full_name, existing_logins):
    parts = (full_name or "").strip().split()
    surname = (parts[0] if parts else "").lower()
    letters = ""
    for ch in surname:
        if len(letters) >= 3: break
        t = TRANSLIT.get(ch)
        if t: letters += t
    while len(letters) < 3:
        letters += random.choice("abcdefghijklmnopqrstuvwxyz")
    letters = letters[:3]

    digits = list(range(10, 100))
    random.shuffle(digits)
    for d in digits:
        candidate = f"{letters}{d}"
        if candidate not in existing_logins: return candidate
    for _ in range(500):
        rl = "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(3))
        d = random.randint(10, 99)
        candidate = f"{rl}{d}"
        if candidate not in existing_logins: return candidate
    raise RuntimeError("Не удалось сгенерировать логин")

# ============= МЕДКНИЖКИ =============
def parse_date_ddmmYYYY(s):
    if not s: return None
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", str(s).strip())
    if not m: return None
    try:
        d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d.day != int(m.group(1)) or d.month != int(m.group(2)): return None
        return d
    except ValueError: return None

def add_months(dt, months):
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)

def entry_status(date_str, validity_months):
    if not date_str: return "missing"
    d = parse_date_ddmmYYYY(date_str)
    if not d: return "invalid_date"
    exp = add_months(d, validity_months)
    now = datetime.utcnow()
    if exp < now: return "expired"
    if (exp - now).days <= 30: return "expiring"
    return "ok"

def _mb_items(medbook, doctors, tests, vaccines):
    mb = medbook or {}
    if isinstance(mb, str):
        try: mb = json.loads(mb)
        except Exception: mb = {}
    items = []
    for d in doctors: items.append((mb.get("doctors", {}).get(str(d["id"])), d["validity_months"]))
    for t in tests: items.append((mb.get("tests", {}).get(str(t["id"])), t["validity_months"]))
    for v in vaccines: items.append((mb.get("vaccines", {}).get(str(v["id"])), v["validity_months"]))
    return items

def compute_medbook_status(medbook, doctors, tests, vaccines):
    has_expiring = False
    for date_str, validity in _mb_items(medbook, doctors, tests, vaccines):
        s = entry_status(date_str, validity)
        if s in ("missing", "invalid_date", "expired"): return "invalid"
        if s == "expiring": has_expiring = True
    return "expiring" if has_expiring else "ok"

def medbook_missing_count(medbook, doctors, tests, vaccines):
    items = _mb_items(medbook, doctors, tests, vaccines)
    missing = sum(1 for date_str, v in items if entry_status(date_str, v) in ("missing", "invalid_date", "expired"))
    return missing, len(items)

# ============= БД =============
_pool = None
_pool_lock = threading.Lock()

def init_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(2, 20, DB_URL)

@contextmanager
def get_conn():
    init_pool()
    conn = _pool.getconn()
    try:
        with conn: yield conn
    finally: _pool.putconn(conn)

async def _run(fn, *args):
    return await asyncio.to_thread(fn, *args)

def _run_migration(sql_query, label):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur: cur.execute(sql_query)
        return True
    except Exception as e:
        logging.error(f"Миграция '{label}': {type(e).__name__}: {str(e)[:150]}")
        return False

async def _cleanup_sessions_loop():
    while True:
        try:
            await asyncio.sleep(3600)
            def _do_cleanup():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("DELETE FROM web_sessions WHERE last_used_at < NOW() - INTERVAL %s", (f"{int(SESSION_TTL_DAYS)} days",))
                        return cur.rowcount
            count = await _run(_do_cleanup)
            if count: logging.info(f"🧹 Очищено старых сессий: {count}")
        except asyncio.CancelledError: raise
        except Exception as e: logging.error(f"Cleanup sessions error: {e}")

def _auto_publish_scheduled(cur):
    cur.execute("""
        UPDATE news SET status = 'published'
        WHERE status = 'scheduled' AND publish_at IS NOT NULL AND publish_at <= NOW()
    """)

# ============= SEED =============
RESTAURANTS_SEED = [
    {"key": "belyaevo", "name": "Беляево", "address": "Москва, ул. Миклухо-Маклая, 32А, ТЦ «Капитолий», этаж 2", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6437, "lon": 37.5302, "org": "vokker/13122472923", "phone": "+7 (985) 857-06-69"},
    {"key": "vernadka", "name": "Вернадка", "address": "Москва, проспект Вернадского, 6, ТЦ «Капитолий Вернадского», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6845, "lon": 37.4948, "org": "vokker/91626648547", "phone": ""},
    {"key": "metropolis", "name": "Метрополис", "address": "Москва, Ленинградское ш., д. 16А, стр. 4, ТРЦ «Метрополис», этаж 3", "hours": "Пн–вс: 10:00–23:00", "lat": 55.8214, "lon": 37.4977, "org": "vokker/1298559872", "phone": "+7 (985) 857-07-14"},
    {"key": "mega_himki", "name": "Мега Химки", "address": "Московская обл., г. Химки, микрорайон ИКЕА, к1, ТЦ «Мега Химки», этаж 1", "hours": "Пн–чт, вс: 10:00–23:00\nПт–сб: 10:00–24:00", "lat": 55.8948, "lon": 37.3973, "org": "vokker/132066311330", "phone": "+7 (985) 857-08-22"},
    {"key": "office", "name": "ОФИС", "address": "Центральный офис", "hours": "Пн–пт: 09:00–18:00", "lat": None, "lon": None, "org": "", "phone": ""},
]
FAQ_SEED = [
    {"question": "Как посмотреть график смен?", "answer": "График вывешивается на информационной доске в ресторане и уточняется у управляющего сменой.", "category": "Работа"},
    {"question": "Куда сообщать о поломке оборудования?", "answer": "Напиши управляющему сменой. Если поломка серьёзная — он оформляет заявку в сервис.", "category": "Работа"},
    {"question": "Как поменять пароль?", "answer": "Обратись к администратору — он сменит пароль в админ-панели.", "category": "Бот"},
]
POSITIONS_SEED = ["Повар холодного цеха", "Повар горячего цеха", "Управляющий сменой", "Территориальный управляющий", "HR"]
CITIZENSHIPS_SEED = ["Россия", "Кыргызстан", "Узбекистан", "Таджикистан"]

DOCTORS_SEED = [
    {"name": "Терапевт", "required": True, "validity_months": 12, "sort": 0},
    {"name": "Психиатр", "required": True, "validity_months": 12, "sort": 1},
    {"name": "Нарколог", "required": True, "validity_months": 12, "sort": 2},
    {"name": "Дерматовенеролог", "required": True, "validity_months": 12, "sort": 3},
    {"name": "ЛОР", "required": False, "validity_months": 12, "sort": 4},
    {"name": "Стоматолог", "required": False, "validity_months": 12, "sort": 5},
]
TESTS_SEED = [
    {"name": "Общий анализ крови", "required": True, "validity_months": 12, "sort": 0},
    {"name": "Общий анализ мочи", "required": True, "validity_months": 12, "sort": 1},
    {"name": "Флюорография", "required": True, "validity_months": 12, "sort": 2},
    {"name": "Кровь на RW", "required": True, "validity_months": 6, "sort": 3},
    {"name": "ЭКГ", "required": False, "validity_months": 12, "sort": 4},
]
VACCINES_SEED = [
    {"name": "Грипп", "required": False, "validity_months": 12, "sort": 0},
    {"name": "Корь", "required": False, "validity_months": 60, "sort": 1},
    {"name": "Дифтерия и столбняк (АДС-М)", "required": False, "validity_months": 120, "sort": 2},
    {"name": "COVID-19", "required": False, "validity_months": 12, "sort": 3},
]

def init_db_and_seed():
    logging.info("⏳ Начинаю миграции и заполнение БД...")
    data_dir = os.getenv("DATA_DIR", "/data")
    upload_dir = os.path.join(data_dir, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    _run_migration("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGSERIAL PRIMARY KEY, login TEXT, password_hash TEXT, full_name TEXT, phone TEXT,
            birth_date TEXT, position TEXT, restaurant_key TEXT, is_admin BOOLEAN DEFAULT FALSE,
            is_super_admin BOOLEAN DEFAULT FALSE, permissions JSONB DEFAULT '{}', is_fired BOOLEAN DEFAULT FALSE,
            fired_at TIMESTAMPTZ, fired_by TEXT, is_certified BOOLEAN DEFAULT FALSE,
            medbook JSONB DEFAULT '{"doctors":{},"tests":{},"vaccines":{}}',
            created_at TIMESTAMPTZ DEFAULT NOW(), last_seen_at TIMESTAMPTZ,
            hire_date TEXT, citizenship_id INT, rate NUMERIC(10,2) DEFAULT 0,
            payment_type TEXT DEFAULT 'hourly'
        )
    """, "CREATE users")

    for _col, _sql in [
        ("login", "ALTER TABLE users ADD COLUMN IF NOT EXISTS login TEXT"),
        ("password_hash", "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT"),
        ("is_admin", "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"),
        ("is_super_admin", "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN DEFAULT FALSE"),
        ("permissions", "ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT '{}'"),
        ("is_fired", "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_fired BOOLEAN DEFAULT FALSE"),
        ("fired_at", "ALTER TABLE users ADD COLUMN IF NOT EXISTS fired_at TIMESTAMPTZ"),
        ("fired_by", "ALTER TABLE users ADD COLUMN IF NOT EXISTS fired_by TEXT"),
        ("is_certified", "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_certified BOOLEAN DEFAULT FALSE"),
        ("medbook", "ALTER TABLE users ADD COLUMN IF NOT EXISTS medbook JSONB DEFAULT '{\"doctors\":{},\"tests\":{},\"vaccines\":{}}'"),
        ("last_seen_at", "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ"),
        ("restaurant_key", "ALTER TABLE users ADD COLUMN IF NOT EXISTS restaurant_key TEXT"),
        ("restaurant", "ALTER TABLE users ADD COLUMN IF NOT EXISTS restaurant TEXT"),
        ("hire_date", "ALTER TABLE users ADD COLUMN IF NOT EXISTS hire_date TEXT"),
        ("citizenship_id", "ALTER TABLE users ADD COLUMN IF NOT EXISTS citizenship_id INT"),
        ("rate", "ALTER TABLE users ADD COLUMN IF NOT EXISTS rate NUMERIC(10,2) DEFAULT 0"),
        ("payment_type", "ALTER TABLE users ADD COLUMN IF NOT EXISTS payment_type TEXT DEFAULT 'hourly'"),
    ]:
        _run_migration(_sql, f"ADD {_col}")

    _run_migration("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users (LOWER(login)) WHERE login IS NOT NULL", "idx login")
    _run_migration("CREATE INDEX IF NOT EXISTS idx_users_rest ON users(restaurant_key)", "idx users rest")
    _run_migration("UPDATE users SET is_fired = FALSE WHERE is_fired IS NULL", "NULL is_fired")
    _run_migration("UPDATE users SET is_admin = FALSE WHERE is_admin IS NULL", "NULL is_admin")
    _run_migration("UPDATE users SET is_super_admin = FALSE WHERE is_super_admin IS NULL", "NULL is_super_admin")
    _run_migration("UPDATE users SET is_certified = FALSE WHERE is_certified IS NULL", "NULL is_certified")

    _run_migration("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'users_user_id_seq') THEN
                CREATE SEQUENCE users_user_id_seq;
            END IF;
            PERFORM setval('users_user_id_seq', GREATEST((SELECT COALESCE(MAX(user_id), 0) FROM users), 1), (SELECT COUNT(*) FROM users) > 0);
            ALTER TABLE users ALTER COLUMN user_id SET DEFAULT nextval('users_user_id_seq');
            ALTER SEQUENCE users_user_id_seq OWNED BY users.user_id;
        END $$;
    """, "user_id sequence")

    _run_migration("""
        CREATE TABLE IF NOT EXISTS restaurants (
            key TEXT PRIMARY KEY, name TEXT NOT NULL, address TEXT, hours TEXT, lat REAL, lon REAL,
            org TEXT, phone TEXT DEFAULT '', force_status TEXT DEFAULT 'open', sort INT DEFAULT 100, territory_manager_id BIGINT
        )
    """, "CREATE restaurants")

    for _sql in [
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS force_status TEXT DEFAULT 'open'",
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS sort INT DEFAULT 100",
        "ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS territory_manager_id BIGINT",
    ]:
        _run_migration(_sql, "restaurants alter")

    _run_migration("""
        CREATE TABLE IF NOT EXISTS medbook_doctors (id SERIAL PRIMARY KEY, name TEXT NOT NULL, required BOOLEAN DEFAULT FALSE, validity_months INT DEFAULT 12, sort INT DEFAULT 100)
    """, "CREATE medbook_doctors")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS medbook_tests (id SERIAL PRIMARY KEY, name TEXT NOT NULL, required BOOLEAN DEFAULT FALSE, validity_months INT DEFAULT 12, sort INT DEFAULT 100)
    """, "CREATE medbook_tests")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS medbook_vaccines (id SERIAL PRIMARY KEY, name TEXT NOT NULL, required BOOLEAN DEFAULT FALSE, validity_months INT DEFAULT 12, sort INT DEFAULT 100)
    """, "CREATE medbook_vaccines")

    _run_migration("""
        CREATE TABLE IF NOT EXISTS news (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL, level TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'published', publish_at TIMESTAMPTZ, proposed_by TEXT, approved_by TEXT,
            image_url TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """, "CREATE news")
    _run_migration("CREATE INDEX IF NOT EXISTS idx_news_status ON news(status)", "idx news status")

    for _sql in [
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS level TEXT DEFAULT 'normal'",
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'published'",
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS publish_at TIMESTAMPTZ",
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS proposed_by TEXT",
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS approved_by TEXT",
        "ALTER TABLE news ADD COLUMN IF NOT EXISTS image_url TEXT DEFAULT ''",
    ]:
        _run_migration(_sql, "news alter")

    # ===== STANDARDS =====
    _run_migration("""
        CREATE TABLE IF NOT EXISTS standards (
            id SERIAL PRIMARY KEY, number TEXT DEFAULT '', title TEXT NOT NULL, body TEXT DEFAULT '', image_url TEXT DEFAULT '',
            status TEXT DEFAULT 'published', proposed_by TEXT, approved_by TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """, "CREATE standards")
    _run_migration("CREATE INDEX IF NOT EXISTS idx_std_status ON standards(status)", "idx std status")

    for _sql in [
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS number TEXT DEFAULT ''",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS body TEXT DEFAULT ''",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS image_url TEXT DEFAULT ''",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'published'",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS proposed_by TEXT",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS approved_by TEXT",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS group_name TEXT DEFAULT 'Общее'",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS content_type TEXT DEFAULT 'text'",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS content_data JSONB",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS file_url TEXT DEFAULT ''",
        "ALTER TABLE standards ADD COLUMN IF NOT EXISTS file_name TEXT DEFAULT ''",
        "ALTER TABLE standards DROP COLUMN IF EXISTS category",
        "ALTER TABLE standards DROP COLUMN IF EXISTS description",
        "ALTER TABLE standards DROP COLUMN IF EXISTS url",
    ]:
        _run_migration(_sql, "standards alter")

    # ===== CERTIFICATION =====
    _run_migration("""
        CREATE TABLE IF NOT EXISTS certification_questions (
            id SERIAL PRIMARY KEY, question TEXT NOT NULL, 
            option_a TEXT NOT NULL, option_b TEXT NOT NULL, option_c TEXT NOT NULL, option_d TEXT NOT NULL,
            correct_option TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """, "CREATE certification_questions")

    # ===== ACADEMY =====
    _run_migration("""
        CREATE TABLE IF NOT EXISTS academy_courses (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT, color TEXT DEFAULT 'pink', icon TEXT DEFAULT '🚀', created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """, "CREATE academy_courses")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS academy_lessons (
            id SERIAL PRIMARY KEY, course_id INT REFERENCES academy_courses(id) ON DELETE CASCADE, title TEXT NOT NULL, content TEXT, sort INT DEFAULT 0
        )
    """, "CREATE academy_lessons")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS academy_tests (
            id SERIAL PRIMARY KEY, course_id INT REFERENCES academy_courses(id) ON DELETE CASCADE, 
            question TEXT NOT NULL, options JSONB NOT NULL, correct_index INT NOT NULL
        )
    """, "CREATE academy_tests")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS academy_progress (
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE, course_id INT REFERENCES academy_courses(id) ON DELETE CASCADE,
            status TEXT DEFAULT 'in_progress', score INT DEFAULT 0, updated_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (user_id, course_id)
        )
    """, "CREATE academy_progress")

    # ===== TIMESHEET =====
    _run_migration("""
        CREATE TABLE IF NOT EXISTS timesheet_records (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            work_date DATE NOT NULL,
            hours NUMERIC(4,1) DEFAULT 0,
            status TEXT DEFAULT 'work',
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, work_date)
        )
    """, "CREATE timesheet_records")
    _run_migration("CREATE INDEX IF NOT EXISTS idx_ts_date ON timesheet_records(work_date)", "idx ts date")

    _run_migration("""
        CREATE TABLE IF NOT EXISTS faq (id SERIAL PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, category TEXT DEFAULT '')
    """, "CREATE faq")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS positions (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, sort INT DEFAULT 100, is_archived BOOLEAN DEFAULT FALSE)
    """, "CREATE positions")
    
    _run_migration("""
        CREATE TABLE IF NOT EXISTS citizenships (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL)
    """, "CREATE citizenships")

    _run_migration("""
        CREATE TABLE IF NOT EXISTS admin_audit (id SERIAL PRIMARY KEY, admin_id BIGINT, action TEXT, target_type TEXT, target_id TEXT, details TEXT, created_at TIMESTAMPTZ DEFAULT NOW())
    """, "CREATE audit")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS questions (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL, text TEXT NOT NULL, replied BOOLEAN DEFAULT FALSE, reply_text TEXT, replied_at TIMESTAMPTZ, replied_by BIGINT, created_at TIMESTAMPTZ DEFAULT NOW())
    """, "CREATE questions")
    _run_migration("CREATE INDEX IF NOT EXISTS idx_q_replied ON questions(replied)", "idx q replied")
    _run_migration("""
        CREATE TABLE IF NOT EXISTS web_sessions (token TEXT PRIMARY KEY, user_id BIGINT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW(), last_used_at TIMESTAMPTZ DEFAULT NOW())
    """, "CREATE sessions")

    # ===== PUSH SUBSCRIPTIONS =====
    _run_migration("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id SERIAL PRIMARY KEY, 
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE, 
            subscription JSONB NOT NULL, 
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """, "CREATE push_subscriptions")

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM restaurants")
            if cur.fetchone()[0] == 0:
                for i, r in enumerate(RESTAURANTS_SEED):
                    sort = 999 if r["key"] == "office" else i
                    status = "closed" if r["key"] == "office" else "open"
                    cur.execute("INSERT INTO restaurants (key, name, address, hours, lat, lon, org, phone, sort, force_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (r["key"], r["name"], r["address"], r["hours"], r["lat"], r["lon"], r["org"], r["phone"], sort, status))

            cur.execute("SELECT COUNT(*) FROM faq")
            if cur.fetchone()[0] == 0:
                for f in FAQ_SEED: cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s,%s,%s)", (f["question"], f["answer"], f["category"]))
            cur.execute("SELECT COUNT(*) FROM positions")
            if cur.fetchone()[0] == 0:
                for i, name in enumerate(POSITIONS_SEED): cur.execute("INSERT INTO positions (name, sort) VALUES (%s,%s)", (name, i))
            
            cur.execute("SELECT COUNT(*) FROM citizenships")
            if cur.fetchone()[0] == 0:
                for name in CITIZENSHIPS_SEED: cur.execute("INSERT INTO citizenships (name) VALUES (%s)", (name,))

            cur.execute("SELECT COUNT(*) FROM medbook_doctors")
            if cur.fetchone()[0] == 0:
                for d in DOCTORS_SEED: cur.execute("INSERT INTO medbook_doctors (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)", (d["name"], d["required"], d["validity_months"], d["sort"]))
            cur.execute("SELECT COUNT(*) FROM medbook_tests")
            if cur.fetchone()[0] == 0:
                for t in TESTS_SEED: cur.execute("INSERT INTO medbook_tests (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)", (t["name"], t["required"], t["validity_months"], t["sort"]))
            cur.execute("SELECT COUNT(*) FROM medbook_vaccines")
            if cur.fetchone()[0] == 0:
                for v in VACCINES_SEED: cur.execute("INSERT INTO medbook_vaccines (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)", (v["name"], v["required"], v["validity_months"], v["sort"]))
            
            cur.execute("SELECT COUNT(*) FROM news")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO news (title, body, level, status) VALUES (%s,%s,%s,%s)", ("Открытие новой точки", "Скоро открываем новый ресторан!", "urgent", "published"))
                cur.execute("INSERT INTO news (title, body, level, status) VALUES (%s,%s,%s,%s)", ("Обновление меню", "Появились новые позиции в меню.", "normal", "published"))

            cur.execute("SELECT COUNT(*) FROM certification_questions")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO certification_questions (question, option_a, option_b, option_c, option_d, correct_option) VALUES (%s,%s,%s,%s,%s,%s)", ("Что нужно сделать перед открытием смены?", "Проверить чистоту и кассу", "Пойти покурить", "Позвонить другу", "Ничего", "a"))

            cur.execute("SELECT COUNT(*) FROM academy_courses")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO academy_courses (title, description, color, icon) VALUES (%s,%s,%s,%s) RETURNING id", ("Основы сервиса", "Как общаться с гостями, чтобы они возвращались.", "pink", "💖"))
                c1_id = cur.fetchone()[0]
                cur.execute("INSERT INTO academy_lessons (course_id, title, content, sort) VALUES (%s,%s,%s,%s)", (c1_id, "Улыбка решает всё", "Всегда улыбайтесь гостю. Это создает позитивное настроение.", 0))
                cur.execute("INSERT INTO academy_lessons (course_id, title, content, sort) VALUES (%s,%s,%s,%s)", (c1_id, "Как реагировать на жалобы", "Слушайте, не перебивайте, предложите решение.", 1))
                cur.execute("INSERT INTO academy_tests (course_id, question, options, correct_index) VALUES (%s,%s,%s,%s)", (c1_id, "Что делать, если гость жалуется?", '["Спорить", "Слушать и предложить решение", "Игнорировать", "Позвать охрану"]', 1))

            cur.execute("SELECT COUNT(*) FROM users WHERE is_super_admin = TRUE")
            if cur.fetchone()[0] == 0:
                pw = hash_password(ADMIN_PASSWORD)
                cur.execute("SELECT user_id FROM users WHERE LOWER(login) = LOWER(%s)", (ADMIN_LOGIN,))
                existing = cur.fetchone()
                if existing:
                    cur.execute("UPDATE users SET password_hash = %s, is_admin = TRUE, is_super_admin = TRUE, is_fired = FALSE, fired_at = NULL, fired_by = NULL, full_name = COALESCE(NULLIF(full_name, ''), 'Администратор'), position = COALESCE(NULLIF(position, ''), 'Администратор') WHERE user_id = %s", (pw, existing[0]))
                else:
                    cur.execute("INSERT INTO users (login, password_hash, full_name, position, is_admin, is_super_admin) VALUES (%s, %s, 'Администратор', 'Администратор', TRUE, TRUE)", (ADMIN_LOGIN, pw))
    logging.info("✅ БД инициализирована и заполнена")

# ============= СИНХРОННЫЕ ХЕЛПЕРЫ =============
def _sync_get_user_by_login(login):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE LOWER(login) = LOWER(%s)", (login,))
            return cur.fetchone()

def _sync_get_user(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()

def _sync_get_session_user(token):
    now = time.time()
    with _session_cache_lock:
        cached = _session_cache.get(token)
        if cached and now - cached[1] < SESSION_CACHE_TTL:
            return cached[0]
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, last_used_at FROM web_sessions WHERE token = %s", (token,))
            row = cur.fetchone()
            if not row:
                with _session_cache_lock:
                    _session_cache.pop(token, None)
                return None
            uid, last_used = row
            if last_used is not None:
                now_dt = datetime.now(_tz.utc)
                lu = last_used if last_used.tzinfo else last_used.replace(tzinfo=_tz.utc)
                if (now_dt - lu).days > SESSION_TTL_DAYS:
                    cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
                    with _session_cache_lock:
                        _session_cache.pop(token, None)
                    return None
            
            cur.execute("UPDATE web_sessions SET last_used_at = NOW() WHERE token = %s AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '1 hour')", (token,))
            
            with _session_cache_lock:
                _session_cache[token] = (uid, now)
            return uid

def _sync_create_session(user_id):
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO web_sessions (token, user_id) VALUES (%s,%s)", (token, user_id))
    return token

def _sync_delete_session(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
            with _session_cache_lock:
                _session_cache.pop(token, None)
            return cur.rowcount > 0

def _sync_get_medbook_refs():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM medbook_doctors ORDER BY sort, id")
            doctors = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_tests ORDER BY sort, id")
            tests = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_vaccines ORDER BY sort, id")
            vaccines = [dict(r) for r in cur.fetchall()]
    return doctors, tests, vaccines

def _sync_get_all_logins():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT LOWER(login) FROM users WHERE login IS NOT NULL")
            return set(r[0] for r in cur.fetchall())

def _sync_user_has_perm(user, perm):
    if not user: return False
    if user.get("is_super_admin"): return True
    if (user.get("position") or "").strip().upper() == "HR": return True
    perms = user.get("permissions") or {}
    if isinstance(perms, str):
        try: perms = json.loads(perms)
        except Exception: perms = {}
    return bool(perms.get(perm))

# ============= AUTH =============
async def get_auth_user(request):
    try:
        token = request.query.get("token") or request.query.get("webToken")
        if not token:
            body = await request.json()
            token = body.get("webToken") or ""
    except Exception:
        return None, 401
        
    if not token: return None, 401
    user_id = await _run(_sync_get_session_user, token)
    if not user_id: return None, 401
    user = await _run(_sync_get_user, user_id)
    if not user: return None, 401
    if user.get("is_fired"): return None, "fired"
    return user, None

def denied(status):
    if status == "fired": return web.json_response({"error": "fired"}, status=403)
    if status == 403: return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"error": "unauthorized"}, status=401)

def require_perm(user, perm):
    if not _sync_user_has_perm(user, perm):
        return web.json_response({"error": "forbidden"}, status=403)
    return None

async def get_admin_user(request):
    user, err = await get_auth_user(request)
    if err: return None, err
    if not user.get("is_admin"): return None, 403
    return user, None

async def _enrich_user_with_medbook_status(user):
    if not user: return user
    if user.get("is_admin"):
        user["medbook_status"] = "—"
        return user
    doctors, tests, vaccines = await _run(_sync_get_medbook_refs)
    user["medbook_status"] = compute_medbook_status(user.get("medbook") or {}, doctors, tests, vaccines)
    return user

# ============= API: AUTH =============
async def handle_auth_login(request):
    try: 
        body = await request.json()
    except Exception: 
        return web.json_response({"error": "invalid_json"}, status=400)
    
    data, err = validate_login_data(body)
    if err:
        return web.json_response({"error": err}, status=400)
    
    login = data["login"]
    password = data["password"]
    
    ip = request.remote or "unknown"
    if not _check_rate_limit(ip):
        logging.warning(f"Rate limit exceeded for IP: {ip}")
        return web.json_response({"error": "too_many_attempts"}, status=429)

    user = await _run(_sync_get_user_by_login, login)
    if not user or not verify_password(password, user.get("password_hash") or ""):
        return web.json_response({"error": "invalid_credentials"}, status=401)
    
    _reset_rate_limit(ip)
    if user.get("is_fired"): return web.json_response({"error": "fired"}, status=403)
    if not user.get("is_admin"): return web.json_response({"error": "not_admin"}, status=403)
    token = await _run(_sync_create_session, user["user_id"])
    return web.json_response({"ok": True, "token": token, "is_admin": True})

async def handle_auth_login_staff(request):
    try: 
        body = await request.json()
    except Exception: 
        return web.json_response({"error": "invalid_json"}, status=400)
    
    data, err = validate_login_data(body)
    if err:
        return web.json_response({"error": err}, status=400)
        
    login = data["login"]
    password = data["password"]

    ip = request.remote or "unknown"
    if not _check_rate_limit(ip):
        logging.warning(f"Rate limit exceeded for IP: {ip}")
        return web.json_response({"error": "too_many_attempts"}, status=429)

    user = await _run(_sync_get_user_by_login, login)
    if not user or not verify_password(password, user.get("password_hash") or ""):
        return web.json_response({"error": "invalid_credentials"}, status=401)
    
    _reset_rate_limit(ip)
    if user.get("is_fired"): return web.json_response({"error": "fired"}, status=403)
    token = await _run(_sync_create_session, user["user_id"])
    return web.json_response({"ok": True, "token": token, "is_admin": bool(user.get("is_admin"))})

async def handle_auth_logout(request):
    try: data = await request.json()
    except Exception: data = {}
    token = data.get("webToken") or ""
    if token: await _run(_sync_delete_session, token)
    return web.json_response({"ok": True})

# ============= API: ME / DASHBOARD =============
async def handle_admin_me(request):
    user, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({
        "is_admin": True,
        "profile": {
            "user_id": user["user_id"], "login": user.get("login") or "", "full_name": user.get("full_name") or "",
            "position": user.get("position") or "", "is_super_admin": bool(user.get("is_super_admin")),
            "is_hr": (user.get("position") or "").strip().upper() == "HR", "permissions": user.get("permissions") or {},
        }
    })

def _sync_dashboard_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL")
            active = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE login IS NOT NULL")
            total = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE COALESCE(is_fired, FALSE) = TRUE")
            fired = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE created_at::date = NOW()::date AND COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL")
            new_today = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days' AND COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL")
            new7 = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '7 days')")
            inactive7 = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM questions WHERE replied = FALSE")
            questions_open = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM news WHERE status = 'pending'")
            news_pending = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM standards WHERE status = 'pending'")
            standards_pending = cur.fetchone()[0] or 0
    return {"total": total, "active": active, "fired": fired, "new_today": new_today, "new7": new7, "inactive7": inactive7, "questions_open": questions_open, "news_pending": news_pending, "standards_pending": standards_pending}

async def handle_admin_dashboard(request):
    user, err = await get_admin_user(request)
    if err: return denied(err)
    stats = await _run(_sync_dashboard_stats)
    return web.json_response({"stats": stats})

# ============= MEDBOOK ALERTS =============
def _sync_medbook_alerts():
    doctors, tests, vaccines = _sync_get_medbook_refs()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT user_id, full_name, position, medbook FROM users WHERE COALESCE(is_admin, FALSE) = FALSE AND COALESCE(is_fired, FALSE) = FALSE AND login IS NOT NULL")
            users = [dict(r) for r in cur.fetchall()]
    expiring = []
    expired = []
    for u in users:
        mb = u.get("medbook") or {}
        if isinstance(mb, str):
            try: mb = json.loads(mb)
            except Exception: mb = {}
        status = compute_medbook_status(mb, doctors, tests, vaccines)
        if status == "invalid":
            has_expired = False
            for date_str, validity in _mb_items(mb, doctors, tests, vaccines):
                if entry_status(date_str, validity) == "expired": has_expired = True; break
            if has_expired: expired.append({"user_id": u["user_id"], "full_name": u["full_name"] or "", "position": u["position"] or ""})
        elif status == "expiring":
            expiring.append({"user_id": u["user_id"], "full_name": u["full_name"] or "", "position": u["position"] or ""})
    return expiring, expired

async def handle_admin_medbook_alerts(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    expiring, expired = await _run(_sync_medbook_alerts)
    return web.json_response({"expiring": expiring[:20], "expired": expired[:20], "expiring_count": len(expiring), "expired_count": len(expired)})

# ============= PUSH NOTIFICATIONS =============
def _sync_get_all_subscriptions():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, subscription FROM push_subscriptions")
            return [dict(r) for r in cur.fetchall()]

def _sync_delete_subscription(sub_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM push_subscriptions WHERE id = %s", (sub_id,))

async def send_push_to_all(title, body_text, url="/"):
    subs = await _run(_sync_get_all_subscriptions)
    if not subs: return
    
    payload = json.dumps({
        "title": title,
        "body": body_text[:100],
        "url": url
    })
    
    for sub in subs:
        try:
            def _send():
                webpush(
                    subscription_info=sub["subscription"],
                    data=payload,
                    vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims=VAPID_CLAIMS
                )
            await _run(_send)
        except WebPushException as ex:
            if ex.response is not None and ex.response.status_code == 410:
                await _run(_sync_delete_subscription, sub["id"])
        except Exception as e:
            logging.error(f"Push error: {e}")

async def handle_push_subscribe(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    subscription = body.get("subscription")
    if not subscription: return web.json_response({"error": "invalid_sub"}, status=400)
    
    endpoint = subscription.get("endpoint")
    if not endpoint: return web.json_response({"error": "no_endpoint"}, status=400)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM push_subscriptions WHERE user_id = %s AND subscription->>'endpoint' = %s", (user["user_id"], endpoint))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE push_subscriptions SET subscription = %s WHERE id = %s", (Json(subscription), row[0]))
            else:
                cur.execute("INSERT INTO push_subscriptions (user_id, subscription) VALUES (%s, %s)", (user["user_id"], Json(subscription)))
    return web.json_response({"ok": True})

# ============= USERS =============
def _sync_list_users(search="", fired=False):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            base = """
                SELECT u.user_id, u.login, u.full_name, u.phone, u.birth_date, u.position, u.restaurant_key, r.name AS restaurant_name,
                       COALESCE(u.is_admin, FALSE) AS is_admin, COALESCE(u.is_super_admin, FALSE) AS is_super_admin,
                       COALESCE(u.is_fired, FALSE) AS is_fired, COALESCE(u.is_certified, FALSE) AS is_certified,
                       u.medbook, u.created_at, u.last_seen_at, u.fired_at, u.fired_by,
                       u.hire_date, u.citizenship_id, c.name AS citizenship_name, u.payment_type
                FROM users u 
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                LEFT JOIN citizenships c ON u.citizenship_id = c.id
                WHERE COALESCE(u.is_fired, FALSE) = %s AND u.login IS NOT NULL
            """
            params = [bool(fired)]
            if search:
                base += " AND (LOWER(COALESCE(u.full_name,'')) LIKE %s OR LOWER(COALESCE(u.login,'')) LIKE %s OR COALESCE(u.phone,'') LIKE %s OR CAST(u.user_id AS TEXT) LIKE %s)"
                s = f"%{search.lower()}%"
                params.extend([s, s, f"%{search}%", f"%{search}%"])
            base += " ORDER BY u.user_id DESC"
            cur.execute(base, params)
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_users(request):
    user, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: body = {}
    search = (body.get("search") or "").strip()
    fired = bool(body.get("fired"))
    users = await _run(_sync_list_users, search, fired)
    doctors, tests, vaccines = await _run(_sync_get_medbook_refs)
    for u in users:
        u["medbook_status"] = compute_medbook_status(u.get("medbook") or {}, doctors, tests, vaccines) if not u["is_admin"] else "—"
        mb = u.get("medbook")
        if isinstance(mb, str):
            try: u["medbook"] = json.loads(mb or "{}")
            except Exception: u["medbook"] = {}
    return web.json_response({"users": users})

def _sync_create_user(data, existing_logins, admin_id=None):
    full_name = data["full_name"]
    login = _generate_login_for(full_name, existing_logins)
    
    restaurant_key = data.get("restaurant_key") or ""
    if restaurant_key:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key FROM restaurants WHERE key = %s", (restaurant_key,))
                if not cur.fetchone():
                    return None, "invalid_restaurant"

    pw_hash = hash_password(data["password"])
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO users (login, password_hash, full_name, phone, birth_date, position, restaurant_key, is_certified, hire_date, citizenship_id, payment_type) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", 
                        (login, pw_hash, full_name, data.get("phone", ""), data.get("birth_date", ""), data.get("position", ""), restaurant_key, data.get("is_certified", False), data.get("hire_date", ""), data.get("citizenship_id"), data.get("payment_type", "hourly")))
            new_user = dict(cur.fetchone())
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin_id, "user_create", "user", str(new_user["user_id"]), f"login={login}"))
    return new_user, None

async def handle_admin_user_create(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_create")
    if perm_err: return perm_err
    
    try:
        body = await request.json()
    except Exception: 
        return web.json_response({"error": "invalid_json"}, status=400)
    
    data, err = validate_user_create_data(body)
    if err:
        return web.json_response({"error": err}, status=400)
        
    existing_logins = await _run(_sync_get_all_logins)
    new_user, err_code = await _run(_sync_create_user, data, existing_logins, admin["user_id"])
    if err_code: return web.json_response({"error": err_code}, status=400)
    new_user.pop("password_hash", None)
    return web.json_response({"ok": True, "user": new_user})

def _sync_get_user_by_id(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT u.user_id, u.login, u.full_name, u.phone, u.birth_date, u.position, u.restaurant_key, r.name AS restaurant_name,
                       COALESCE(u.is_admin, FALSE) AS is_admin, COALESCE(u.is_super_admin, FALSE) AS is_super_admin,
                       COALESCE(u.is_fired, FALSE) AS is_fired, COALESCE(u.is_certified, FALSE) AS is_certified,
                       u.medbook, u.created_at, u.last_seen_at, u.fired_at, u.fired_by, u.permissions,
                       u.hire_date, u.citizenship_id, c.name AS citizenship_name, u.payment_type
                FROM users u 
                LEFT JOIN restaurants r ON u.restaurant_key = r.key 
                LEFT JOIN citizenships c ON u.citizenship_id = c.id
                WHERE u.user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            if row:
                d = dict(row)
                if isinstance(d.get("medbook"), str):
                    try: d["medbook"] = json.loads(d["medbook"] or "{}")
                    except Exception: d["medbook"] = {}
                return d
            return None

async def handle_admin_user_get(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    user = await _run(_sync_get_user_by_id, uid)
    if not user: return web.json_response({"error": "not_found"}, status=404)
    await _enrich_user_with_medbook_status(user)
    return web.json_response({"user": user})

def _sync_update_user(uid, updates):
    allowed_simple = {"full_name", "phone", "birth_date", "position", "restaurant_key", "is_certified", "hire_date", "citizenship_id", "payment_type"}
    
    if "payment_type" in updates and updates["payment_type"] not in ('hourly', 'fixed'):
        return "invalid_payment_type"
        
    if "restaurant_key" in updates and updates["restaurant_key"]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT key FROM restaurants WHERE key = %s", (updates["restaurant_key"],))
                if not cur.fetchone():
                    return "invalid_restaurant"

    with get_conn() as conn:
        with conn.cursor() as cur:
            for k, v in updates.items():
                if k in allowed_simple: 
                    if k == "citizenship_id" and v == "": v = None
                    elif k == "citizenship_id" and v is not None: v = int(v)
                    query = sql.SQL("UPDATE users SET {} = %s WHERE user_id = %s").format(sql.Identifier(k))
                    cur.execute(query, (v, uid))
            if "password" in updates and updates["password"]:
                pw = hash_password(updates["password"])
                cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (pw, uid))
            if "is_admin" in updates:
                cur.execute("UPDATE users SET is_admin = %s WHERE user_id = %s", (bool(updates["is_admin"]), uid))
                if not updates["is_admin"]: cur.execute("UPDATE users SET permissions = '{}'::jsonb, is_super_admin = FALSE WHERE user_id = %s", (uid,))
    return None

async def handle_admin_user_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    updates = body.get("updates") or {}
    target = await _run(_sync_get_user_by_id, uid)
    if not target: return web.json_response({"error": "not_found"}, status=404)
    if "is_admin" in updates and not admin["is_super_admin"]: return web.json_response({"error": "forbidden_is_admin"}, status=403)
    if target.get("is_super_admin") and not admin["is_super_admin"]: return web.json_response({"error": "cannot_edit_super"}, status=403)
    if "restaurant" in updates: updates["restaurant_key"] = updates.pop("restaurant")
    
    if "full_name" in updates and len(updates["full_name"]) > 100:
        return web.json_response({"error": "full_name_too_long"}, status=400)

    err_code = await _run(_sync_update_user, uid, updates)
    if err_code: return web.json_response({"error": err_code}, status=400)
    
    updated = await _run(_sync_get_user_by_id, uid)
    if updated: await _enrich_user_with_medbook_status(updated)
    return web.json_response({"ok": True, "user": updated})

async def handle_admin_user_fire(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_fire")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    target = await _run(_sync_get_user_by_id, uid)
    if not target: return web.json_response({"error": "not_found"}, status=404)
    if target.get("is_super_admin"): return web.json_response({"error": "cannot_fire_super"}, status=403)
    if target.get("is_admin") and not admin["is_super_admin"]: return web.json_response({"error": "cannot_fire_admin"}, status=403)
    if uid == admin["user_id"]: return web.json_response({"error": "cannot_fire_self"}, status=403)
    if target.get("is_fired"): return web.json_response({"error": "already_fired"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_fired = TRUE, fired_at = NOW(), fired_by = %s, is_admin = FALSE, is_super_admin = FALSE, permissions = '{}'::jsonb WHERE user_id = %s", (admin["login"], uid))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "user_fire", "user", str(uid), f"by={admin['login']}"))
    _session_cache.clear()
    return web.json_response({"ok": True})

async def handle_admin_user_restore(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_fire")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_fired = FALSE, fired_at = NULL, fired_by = NULL WHERE user_id = %s", (uid,))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "user_restore", "user", str(uid), f"by={admin['login']}"))
    _session_cache.clear()
    return web.json_response({"ok": True})

async def handle_admin_user_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "users_fire")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    target = await _run(_sync_get_user_by_id, uid)
    if not target: return web.json_response({"error": "not_found"}, status=404)
    if target.get("is_super_admin"): return web.json_response({"error": "cannot_delete_super"}, status=403)
    if target.get("is_admin") and not admin["is_super_admin"]: return web.json_response({"error": "cannot_delete_admin"}, status=403)
    if uid == admin["user_id"]: return web.json_response({"error": "cannot_delete_self"}, status=403)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (uid,))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "user_delete", "user", str(uid), f"login={target.get('login')}"))
    return web.json_response({"ok": True})

# ============= ADMINS / PERMISSIONS =============
def _sync_list_admins():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT user_id, login, full_name, position, permissions, COALESCE(is_admin, FALSE) AS is_admin, COALESCE(is_super_admin, FALSE) AS is_super_admin FROM users WHERE COALESCE(is_admin, FALSE) = TRUE AND COALESCE(is_fired, FALSE) = FALSE ORDER BY user_id")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_admins(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not admin["is_super_admin"]: return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"admins": await _run(_sync_list_admins)})

async def handle_admin_set_permissions(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not admin["is_super_admin"]: return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    perms = body.get("permissions") or {}
    target = await _run(_sync_get_user_by_id, uid)
    if not target: return web.json_response({"error": "not_found"}, status=404)
    if target.get("is_super_admin"): return web.json_response({"error": "cannot_edit_super"}, status=403)
    if not target.get("is_admin"): return web.json_response({"error": "not_admin"}, status=400)
    cleaned = {k: True for k in PERM_KEYS if perms.get(k)}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET permissions = %s WHERE user_id = %s", (Json(cleaned), uid))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "set_permissions", "user", str(uid), ",".join(cleaned.keys())))
    return web.json_response({"ok": True})

# ============= CITIZENSHIPS =============
def _sync_citizenships():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM citizenships ORDER BY name")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_citizenships(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"citizenships": await _run(_sync_citizenships)})

def _sync_citizenship_add(name):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO citizenships (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING *", (name,))
            return cur.fetchone()

async def handle_admin_citizenship_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "citizenships_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    name = (body.get("name") or "").strip()
    if not name or len(name) > 50: return web.json_response({"error": "invalid"}, status=400)
    
    new_c = await _run(_sync_citizenship_add, name)
    if not new_c:
        return web.json_response({"ok": False, "error": "duplicate"}, status=409)
    return web.json_response({"ok": True, "citizenship": new_c})

# ============= RESTAURANTS =============
def _sync_restaurants():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT r.*, u.full_name AS territory_manager_name FROM restaurants r LEFT JOIN users u ON r.territory_manager_id = u.user_id ORDER BY r.sort, r.name")
            return [dict(r) for r in cur.fetchall()]

def _sync_tu_candidates():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT user_id, full_name FROM users WHERE COALESCE(is_fired, FALSE) = FALSE AND LOWER(COALESCE(position,'')) LIKE '%%территориальный%%' ORDER BY full_name")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_restaurants(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    restaurants = await _run(_sync_restaurants)
    tu = await _run(_sync_tu_candidates)
    return web.json_response({"restaurants": restaurants, "tu_candidates": tu})

async def handle_admin_restaurant_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "restaurant_create")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    key = (body.get("key") or "").strip().lower().replace(" ", "_")
    name = (body.get("name") or "").strip()
    if not key or not name or len(name) > 100: return web.json_response({"error": "invalid"}, status=400)
    address = body.get("address") or ""
    hours = body.get("hours") or ""
    phone = body.get("phone") or ""
    org = body.get("org") or ""
    lat = body.get("lat")
    lon = body.get("lon")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key FROM restaurants WHERE key = %s", (key,))
            if cur.fetchone(): return web.json_response({"error": "duplicate"}, status=409)
            cur.execute("INSERT INTO restaurants (key, name, address, hours, phone, org, lat, lon, force_status, sort) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'open', 100)", (key, name, address, hours, phone, org, lat, lon))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "restaurant_create", "restaurant", key, f"name={name}"))
    return web.json_response({"ok": True})

async def handle_admin_restaurant_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "restaurant_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    updates = body.get("updates") or {}
    allowed = {"name", "address", "phone", "hours", "org", "lat", "lon"}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for k, v in updates.items():
                if k in allowed:
                    query = sql.SQL("UPDATE restaurants SET {} = %s WHERE key = %s").format(sql.Identifier(k))
                    cur.execute(query, (v, key))
    return web.json_response({"ok": True})

async def handle_admin_restaurant_tu(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "restaurant_tu")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    tu = body.get("territory_manager_id")
    tu = _safe_int(tu) if tu else None
    if tu is not None and tu <= 0: tu = None
    
    if tu is not None:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users WHERE user_id = %s AND LOWER(COALESCE(position,'')) LIKE '%%территориальный%%' AND COALESCE(is_fired, FALSE) = FALSE", (tu,))
                if not cur.fetchone():
                    return web.json_response({"error": "invalid_tu"}, status=400)

    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE restaurants SET territory_manager_id = %s WHERE key = %s", (tu, key))
    return web.json_response({"ok": True})

async def handle_admin_restaurant_status(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "restaurant_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    st = body.get("status")
    if st == "auto": st = "open"
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE restaurants SET force_status = %s WHERE key = %s", (st, key))
    return web.json_response({"ok": True})

# ============= MEDBOOKS =============
def _sync_medbooks_full():
    doctors, tests, vaccines = _sync_get_medbook_refs()
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT u.user_id, u.full_name, u.position, u.medbook, r.name AS restaurant_name FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key WHERE COALESCE(u.is_admin, FALSE) = FALSE AND COALESCE(u.is_fired, FALSE) = FALSE AND u.login IS NOT NULL ORDER BY u.full_name")
            users = [dict(r) for r in cur.fetchall()]
    for u in users:
        mb = u.get("medbook") or {}
        if isinstance(mb, str):
            try: mb = json.loads(mb)
            except Exception: mb = {}
        u["medbook"] = mb
        u["medbook_status"] = compute_medbook_status(mb, doctors, tests, vaccines)
        missing, total = medbook_missing_count(mb, doctors, tests, vaccines)
        u["missing"] = missing
        u["total"] = total
    return doctors, tests, vaccines, users

async def handle_admin_medbooks(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    doctors, tests, vaccines, users = await _run(_sync_medbooks_full)
    return web.json_response({"doctors": doctors, "tests": tests, "vaccines": vaccines, "users": users})

async def handle_admin_medbook_get(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    user = await _run(_sync_get_user_by_id, uid)
    if not user: return web.json_response({"error": "not_found"}, status=404)
    doctors, tests, vaccines = await _run(_sync_get_medbook_refs)
    return web.json_response({
        "user": {"user_id": user["user_id"], "full_name": user.get("full_name"), "position": user.get("position"), "restaurant_name": user.get("restaurant_name") or ""},
        "medbook": user.get("medbook") or {}, "doctors": doctors, "tests": tests, "vaccines": vaccines,
    })

async def handle_admin_medbook_save(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "medbook_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    uid = _safe_int(body.get("user_id"))
    if uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    mb = body.get("medbook") or {"doctors": {}, "tests": {}, "vaccines": {}}
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE users SET medbook = %s WHERE user_id = %s", (Json(mb), uid))
    return web.json_response({"ok": True})

async def handle_admin_medbook_ref_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    if rtype not in REF_TYPE_PERM: return web.json_response({"error": "invalid_type"}, status=400)
    perm_err = require_perm(admin, REF_TYPE_PERM[rtype])
    if perm_err: return perm_err
    name = (body.get("name") or "").strip()
    if not name or len(name) > 100: return web.json_response({"error": "invalid"}, status=400)
    months = max(1, min(120, _safe_int(body.get("validity_months", 12))))
    required = bool(body.get("required"))
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT COALESCE(MAX(sort), 0) FROM {}").format(sql.Identifier(table)))
            sort = (cur.fetchone()[0] or 0) + 1
            cur.execute(sql.SQL("INSERT INTO {} (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)").format(sql.Identifier(table)), (name, required, months, sort))
    return web.json_response({"ok": True})

async def handle_admin_medbook_ref_update(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    rid = _safe_int(body.get("id"))
    if rtype not in REF_TYPE_PERM or not rid: return web.json_response({"error": "invalid"}, status=400)
    perm_err = require_perm(admin, REF_TYPE_PERM[rtype])
    if perm_err: return perm_err
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    with get_conn() as conn:
        with conn.cursor() as cur:
            if "name" in body:
                cur.execute(sql.SQL("UPDATE {} SET name = %s WHERE id = %s").format(sql.Identifier(table)), (body["name"], rid))
            if "validity_months" in body:
                v = max(1, min(120, _safe_int(body["validity_months"])))
                cur.execute(sql.SQL("UPDATE {} SET validity_months = %s WHERE id = %s").format(sql.Identifier(table)), (v, rid))
            if "required" in body:
                cur.execute(sql.SQL("UPDATE {} SET required = %s WHERE id = %s").format(sql.Identifier(table)), (bool(body["required"]), rid))
    return web.json_response({"ok": True})

async def handle_admin_medbook_ref_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    rid = _safe_int(body.get("id"))
    if rtype not in REF_TYPE_PERM or not rid: return web.json_response({"error": "invalid"}, status=400)
    perm_err = require_perm(admin, REF_TYPE_PERM[rtype])
    if perm_err: return perm_err
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table)), (rid,))
    return web.json_response({"ok": True})

# ============= NEWS =============
def _sync_news_list():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            _auto_publish_scheduled(cur)
            cur.execute("SELECT * FROM news ORDER BY created_at DESC, id DESC")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_news_list(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"news": await _run(_sync_news_list)})

def _check_can_publish(admin):
    return admin["is_super_admin"] or (admin.get("position") or "").strip().upper() == "HR"

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

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO news (title, body, level, status, publish_at, proposed_by, image_url) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *", (title, text, level, status, publish_at, proposed_by, image_url))
            news_row = dict(cur.fetchone())
    
    if status == 'published':
        asyncio.create_task(send_push_to_all(
            title=f"📰 {title}", 
            body_text=text, 
            url="/"
        ))
        
    return web.json_response({"ok": True, "status": status, "news": news_row})

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
    
    if "title" in updates and len(updates["title"]) > 200: return web.json_response({"error": "title_too_long"}, status=400)
    if "body" in updates and len(updates["body"]) > 5000: return web.json_response({"error": "body_too_long"}, status=400)

    set_clause = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates)
    query = sql.SQL("UPDATE news SET {} WHERE id = %s").format(set_clause)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute(query, (*updates.values(), nid))
    return web.json_response({"ok": True})

async def handle_admin_news_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "news_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    nid = _safe_int(body.get("id"))
    if nid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("DELETE FROM news WHERE id = %s", (nid,))
    return web.json_response({"ok": True})

async def handle_admin_news_approve(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    nid = _safe_int(body.get("id"))
    if nid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE news SET status = 'published', approved_by = %s WHERE id = %s", (admin.get("full_name"), nid))
    return web.json_response({"ok": True})

async def handle_admin_news_reject(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    nid = _safe_int(body.get("id"))
    if nid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("DELETE FROM news WHERE id = %s AND status = 'pending'", (nid,))
    return web.json_response({"ok": True})

# ============= STANDARDS =============
def _sync_standards_list():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM standards ORDER BY created_at DESC, id DESC")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_standards(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"standards": await _run(_sync_standards_list)})

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
    if len(title) > 200: return web.json_response({"error": "title_too_long"}, status=400)
    if len(text) > 200000: return web.json_response({"error": "text_too_long"}, status=400)

    if content_type == 'text':
        text = sanitize_html(text)

    if not can_publish:
        status = "pending"
        proposed_by = admin.get("full_name") or admin.get("login")
    else:
        status = "published"
        proposed_by = None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("INSERT INTO standards (number, title, body, status, proposed_by, image_url, group_name, content_type, content_data, file_url, file_name) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *", 
                        (number, title, text, status, proposed_by, image_url, group_name, content_type, Json(content_data) if content_data else None, file_url, file_name))
            std_row = dict(cur.fetchone())
    return web.json_response({"ok": True, "status": status, "standard": std_row})

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
    if "title" in updates and len(updates["title"]) > 200: return web.json_response({"error": "title_too_long"}, status=400)
    if "body" in updates and not updates["body"]: return web.json_response({"error": "text_required"}, status=400)
    if "body" in updates and len(updates["body"]) > 200000: return web.json_response({"error": "text_too_long"}, status=400)

    if "body" in updates:
        updates["body"] = sanitize_html(updates["body"])

    set_clause = sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(k)) for k in updates)
    query = sql.SQL("UPDATE standards SET {} WHERE id = %s").format(set_clause)
    
    vals = []
    for k in updates.keys():
        if k == "content_data": vals.append(Json(updates[k]) if updates[k] else None)
        else: vals.append(updates[k])
    
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute(query, (*vals, sid))
    return web.json_response({"ok": True})

async def handle_admin_standard_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "standards_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    sid = _safe_int(body.get("id"))
    if sid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("DELETE FROM standards WHERE id = %s", (sid,))
    return web.json_response({"ok": True})

async def handle_admin_standard_approve(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    sid = _safe_int(body.get("id"))
    if sid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE standards SET status = 'published', approved_by = %s WHERE id = %s", (admin.get("full_name"), sid))
    return web.json_response({"ok": True})

async def handle_admin_standard_reject(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not _check_can_publish(admin): return web.json_response({"error": "forbidden"}, status=403)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    sid = _safe_int(body.get("id"))
    if sid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("DELETE FROM standards WHERE id = %s AND status = 'pending'", (sid,))
    return web.json_response({"ok": True})

# ============= CERTIFICATION =============
def _sync_certification_list():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM certification_questions ORDER BY created_at DESC")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_certification_list(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"questions": await _run(_sync_certification_list)})

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
        
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO certification_questions (question, option_a, option_b, option_c, option_d, correct_option) VALUES (%s,%s,%s,%s,%s,%s)", (q, a, b, c, d, correct))
    return web.json_response({"ok": True})

async def handle_admin_certification_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "certification_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    qid = _safe_int(body.get("id"))
    if qid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("DELETE FROM certification_questions WHERE id = %s", (qid,))
    return web.json_response({"ok": True})

async def handle_staff_certification_get(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, question, option_a, option_b, option_c, option_d FROM certification_questions ORDER BY random()")
            questions = [dict(r) for r in cur.fetchall()]
    
    return web.json_response({"questions": questions})

async def handle_staff_certification_submit(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    answers = body.get("answers") or {}
    if not answers:
        return web.json_response({"error": "no_answers"}, status=400)
        
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, correct_option FROM certification_questions")
            correct_db = {str(r["id"]): r["correct_option"] for r in cur.fetchall()}
            
            total = len(correct_db)
            if total == 0:
                return web.json_response({"ok": True, "passed": True, "score": 100, "msg": "Вопросов нет, тест пройден автоматически"})
                
            correct_count = 0
            for qid, ans in answers.items():
                if correct_db.get(qid) == ans:
                    correct_count += 1
                    
            score = int((correct_count / total) * 100)
            passed = score >= 80
            
            if passed:
                cur.execute("UPDATE users SET is_certified = TRUE WHERE user_id = %s", (user["user_id"],))
                cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (user["user_id"], "certification_pass", "user", str(user["user_id"]), f"score={score}"))
                
    return web.json_response({"ok": True, "passed": passed, "score": score})

# ============= ACADEMY =============
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

async def handle_academy_submit_test(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    cid = _safe_int(body.get("course_id"))
    answers = body.get("answers") or {}
    
    if cid <= 0 or not answers:
        return web.json_response({"error": "invalid_data"}, status=400)
        
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT id, correct_index FROM academy_tests WHERE course_id = %s", (cid,))
            correct_db = {str(r["id"]): r["correct_index"] for r in cur.fetchall()}
            
            total = len(correct_db)
            if total == 0:
                return web.json_response({"ok": True, "passed": True, "score": 100})
                
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
                
    return web.json_response({"ok": True, "passed": passed, "score": score})

# ============= TIMESHEET (MATRIX & CALENDAR) =============
def _sync_timesheet_get(user_id, month, year):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT * FROM timesheet_records 
                WHERE user_id = %s AND EXTRACT(MONTH FROM work_date) = %s AND EXTRACT(YEAR FROM work_date) = %s
            """, (user_id, month, year))
            return [dict(r) for r in cur.fetchall()]

async def handle_timesheet_get(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    month = _safe_int(body.get("month", datetime.now().month))
    year = _safe_int(body.get("year", datetime.now().year))
    
    records = await _run(_sync_timesheet_get, user["user_id"], month, year)
    return web.json_response({"records": records})

async def handle_timesheet_save(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    work_date = body.get("work_date")
    hours = body.get("hours", 0)
    status = body.get("status", "work")
    
    if not work_date: return web.json_response({"error": "invalid_date"}, status=400)
    
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO timesheet_records (user_id, work_date, hours, status, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, work_date) DO UPDATE 
                SET hours = EXCLUDED.hours, status = EXCLUDED.status, updated_at = NOW()
            """, (user["user_id"], work_date, hours, status))
    return web.json_response({"ok": True})

def _sync_timesheet_matrix(user_id, month, year):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u: return []
            
            pos_lower = (u.get("position") or "").lower()
            is_hr = pos_lower.strip() == "hr"
            is_tu = "территориальный" in pos_lower
            is_us = "управляющий сменой" in pos_lower
            
            query = """
                SELECT u.user_id, u.full_name, u.position, COALESCE(u.rate, 0) AS rate, u.payment_type, r.name AS restaurant_name
                FROM users u
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                WHERE COALESCE(u.is_fired, FALSE) = FALSE AND COALESCE(u.is_admin, FALSE) = FALSE AND u.login IS NOT NULL
            """
            params = []
            
            if is_us:
                query += " AND u.restaurant_key = %s"
                params.append(u.get("restaurant_key"))
            elif is_tu:
                query += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"
                params.append(user_id)
            elif not is_hr:
                query += " AND u.user_id = %s"
                params.append(user_id)
                
            query += " ORDER BY u.full_name"
            cur.execute(query, params)
            employees = [dict(r) for r in cur.fetchall()]
            
            if not employees: return []
            
            emp_ids = [e["user_id"] for e in employees]
            
            cur.execute("""
                SELECT user_id, work_date, hours, status 
                FROM timesheet_records 
                WHERE user_id = ANY(%s) 
                  AND EXTRACT(MONTH FROM work_date) = %s 
                  AND EXTRACT(YEAR FROM work_date) = %s
            """, (emp_ids, month, year))
            
            records = cur.fetchall()
            
            data_map = {eid: {} for eid in emp_ids}
            for r in records:
                day = r["work_date"].day
                data_map[r["user_id"]][str(day)] = {
                    "h": float(r["hours"] or 0),
                    "s": r["status"] or "work"
                }
                
            for e in employees:
                e["data"] = data_map[e["user_id"]]
                
            return employees

async def handle_timesheet_matrix(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    month = _safe_int(body.get("month", datetime.now().month))
    year = _safe_int(body.get("year", datetime.now().year))
    
    employees = await _run(_sync_timesheet_matrix, user["user_id"], month, year)
    return web.json_response({"employees": employees})

def _sync_save_cell(user_id, target_uid, work_date, hours, status):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if hours <= 0 and status == 'work':
                cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s", (target_uid, work_date))
            else:
                cur.execute("""
                    INSERT INTO timesheet_records (user_id, work_date, hours, status, updated_at)
                    VALUES (%s, %s, %s, %s, NOW())
                    ON CONFLICT (user_id, work_date) DO UPDATE 
                    SET hours = EXCLUDED.hours, status = EXCLUDED.status, updated_at = NOW()
                """, (target_uid, work_date, hours, status))

def _check_can_edit_user(editor_user, target_uid):
    if editor_user["is_super_admin"] or (editor_user.get("position") or "").strip().upper() == "HR":
        return True
    if editor_user["user_id"] == target_uid:
        return True

    pos_lower = (editor_user.get("position") or "").lower()
    is_tu = "территориальный" in pos_lower
    is_us = "управляющий сменой" in pos_lower
    if not (is_tu or is_us):
        return False

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT restaurant_key FROM users WHERE user_id = %s", (target_uid,))
            target = cur.fetchone()
            if not target: return False
            
            if is_us:
                return target["restaurant_key"] == editor_user.get("restaurant_key")
            elif is_tu:
                cur.execute("SELECT key FROM restaurants WHERE territory_manager_id = %s AND key = %s", (editor_user["user_id"], target["restaurant_key"]))
                return cur.fetchone() is not None
    return False

async def handle_timesheet_save_cell(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    target_uid = _safe_int(body.get("user_id"))
    work_date = body.get("work_date")
    hours = float(body.get("hours", 0))
    status = body.get("status", "work")
    
    if not work_date or target_uid <= 0: return web.json_response({"error": "invalid_data"}, status=400)
    
    allowed = await _run(_check_can_edit_user, user, target_uid)
    if not allowed:
        return web.json_response({"error": "forbidden_edit_other"}, status=403)
    
    await _run(_sync_save_cell, user["user_id"], target_uid, work_date, hours, status)
    return web.json_response({"ok": True})

def _sync_bulk_save_cells(user_id, cells):
    with get_conn() as conn:
        with conn.cursor() as cur:
            for cell in cells:
                target_uid = cell.get("user_id")
                work_date = cell.get("work_date")
                hours = cell.get("hours", 0)
                status = cell.get("status", "work")
                
                if not work_date or not target_uid: continue
                
                if hours <= 0 and status == 'work':
                    cur.execute("DELETE FROM timesheet_records WHERE user_id = %s AND work_date = %s", (target_uid, work_date))
                else:
                    cur.execute("""
                        INSERT INTO timesheet_records (user_id, work_date, hours, status, updated_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        ON CONFLICT (user_id, work_date) DO UPDATE 
                        SET hours = EXCLUDED.hours, status = EXCLUDED.status, updated_at = NOW()
                    """, (target_uid, work_date, hours, status))

async def handle_timesheet_bulk_save(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: 
        body = await request.json()
    except Exception: 
        return web.json_response({"error": "invalid_json"}, status=400)
    
    data, err = validate_bulk_save_data(body)
    if err:
        return web.json_response({"error": err}, status=400)
    
    cells = data["cells"]
    if not cells: return web.json_response({"ok": True})
    
    unique_uids = set()
    for cell in cells:
        uid = cell["user_id"]
        if uid > 0:
            unique_uids.add(uid)
            
    for uid in unique_uids:
        allowed = await _run(_check_can_edit_user, user, uid)
        if not allowed:
            return web.json_response({"error": "forbidden_edit_other"}, status=403)
        
    await _run(_sync_bulk_save_cells, user["user_id"], cells)
    return web.json_response({"ok": True})

async def handle_timesheet_update_rate(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    target_uid = _safe_int(body.get("user_id"))
    rate = float(body.get("rate", 0))
    if target_uid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    
    allowed = await _run(_check_can_edit_user, user, target_uid)
    if not allowed:
        return web.json_response({"error": "forbidden_edit_other"}, status=403)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET rate = %s WHERE user_id = %s", (rate, target_uid))
            
    return web.json_response({"ok": True})

def _sync_timesheet_employees(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u: return []
            
            pos_lower = (u.get("position") or "").lower()
            is_hr = pos_lower.strip() == "hr"
            is_tu = "территориальный" in pos_lower
            is_us = "управляющий сменой" in pos_lower
            
            if not (is_hr or is_tu or is_us):
                return []

            query = """
                SELECT u.user_id, u.full_name, u.position, r.name AS restaurant_name
                FROM users u
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                WHERE COALESCE(u.is_fired, FALSE) = FALSE AND COALESCE(u.is_admin, FALSE) = FALSE AND u.login IS NOT NULL
            """
            params = []
            if is_us:
                query += " AND u.restaurant_key = %s"
                params.append(u.get("restaurant_key"))
            elif is_tu:
                query += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"
                params.append(user_id)
                
            query += " ORDER BY u.full_name"
            cur.execute(query, params)
            return [dict(r) for r in cur.fetchall()]

async def handle_timesheet_employees(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    employees = await _run(_sync_timesheet_employees, user["user_id"])
    return web.json_response({"employees": employees})

def _sync_timesheet_reports(user_id, month, year):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            u = cur.fetchone()
            if not u: return []
            
            pos_lower = (u.get("position") or "").lower()
            is_hr = pos_lower.strip() == "hr"
            is_tu = "территориальный" in pos_lower
            is_us = "управляющий сменой" in pos_lower
            
            base = """
                SELECT u.full_name, u.position, r.name AS restaurant_name, 
                       SUM(t.hours) as total_hours, COALESCE(u.rate, 0) as rate, u.payment_type,
                       CASE 
                           WHEN u.payment_type = 'fixed' THEN COALESCE(u.rate, 0)
                           ELSE (SUM(t.hours) * COALESCE(u.rate, 0))
                       END as total_salary
                FROM users u
                JOIN timesheet_records t ON u.user_id = t.user_id
                LEFT JOIN restaurants r ON u.restaurant_key = r.key
                WHERE COALESCE(u.is_fired, FALSE) = FALSE AND u.login IS NOT NULL
                  AND EXTRACT(MONTH FROM t.work_date) = %s AND EXTRACT(YEAR FROM t.work_date) = %s
            """
            params = [month, year]
            
            if is_us:
                base += " AND u.restaurant_key = %s"
                params.append(u.get("restaurant_key"))
            elif is_tu:
                base += " AND u.restaurant_key IN (SELECT key FROM restaurants WHERE territory_manager_id = %s)"
                params.append(user_id)
            elif not is_hr:
                base += " AND u.user_id = %s"
                params.append(user_id)
                
            base += " GROUP BY u.user_id, u.full_name, u.position, r.name, u.rate, u.payment_type ORDER BY total_hours DESC"
            cur.execute(base, params)
            return [dict(r) for r in cur.fetchall()]

async def handle_timesheet_reports(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    
    month = _safe_int(body.get("month", datetime.now().month))
    year = _safe_int(body.get("year", datetime.now().year))
    
    report = await _run(_sync_timesheet_reports, user["user_id"], month, year)
    return web.json_response({"report": report})

# ============= FAQ / POSITIONS / QUESTIONS =============
def _sync_faq_list():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM faq ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_faq(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"faq": await _run(_sync_faq_list)})

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
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s,%s,%s)", (q, a, ""))
    return web.json_response({"ok": True})

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
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute(query, (val, fid))
    return web.json_response({"ok": True})

async def handle_admin_faq_delete(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "faq_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    fid = _safe_int(body.get("id"))
    if fid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("DELETE FROM faq WHERE id = %s", (fid,))
    return web.json_response({"ok": True})

def _sync_positions():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM positions ORDER BY is_archived, sort, name")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_positions(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"positions": await _run(_sync_positions)})

async def handle_admin_position_add(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "positions_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    name = (body.get("name") or "").strip()
    if not name or len(name) > 100: return web.json_response({"error": "invalid"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(sort), 0) FROM positions")
            sort = (cur.fetchone()[0] or 0) + 1
            cur.execute("INSERT INTO positions (name, sort) VALUES (%s,%s) ON CONFLICT (name) DO NOTHING RETURNING id", (name, sort))
            if not cur.fetchone(): return web.json_response({"ok": False, "error": "duplicate"}, status=409)
    return web.json_response({"ok": True})

async def handle_admin_position_archive(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "positions_edit")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    pid = _safe_int(body.get("id"))
    if pid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE positions SET is_archived = TRUE WHERE id = %s", (pid,))
    return web.json_response({"ok": True})

def _sync_questions():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT q.id, q.user_id, q.text, q.replied, q.created_at, u.full_name FROM questions q LEFT JOIN users u ON q.user_id = u.user_id ORDER BY q.created_at DESC LIMIT 200")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_questions(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"questions": await _run(_sync_questions)})

async def handle_admin_question_reply(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    perm_err = require_perm(admin, "questions_reply")
    if perm_err: return perm_err
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    qid = _safe_int(body.get("id"))
    if qid <= 0: return web.json_response({"error": "invalid_id"}, status=400)
    text = (body.get("text") or "").strip()
    if not text or len(text) > 2000: return web.json_response({"error": "invalid_or_too_long"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("UPDATE questions SET replied = TRUE, reply_text = %s, replied_at = NOW(), replied_by = %s WHERE id = %s", (text, admin["user_id"], qid))
    return web.json_response({"ok": True})

# ============= AUDIT / REPORTS / PASSWORD =============
def _sync_audit():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM admin_audit ORDER BY created_at DESC LIMIT 300")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_audit(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    return web.json_response({"audit": await _run(_sync_audit)})

async def handle_admin_reports(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    stats = await _run(_sync_dashboard_stats)
    return web.json_response({"report": stats})

async def handle_admin_change_password(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    old = body.get("old_password") or ""
    new = body.get("new_password") or ""
    if not verify_password(old, admin.get("password_hash") or ""): return web.json_response({"error": "wrong_password"}, status=401)
    if len(new) < 8: return web.json_response({"error": "password_too_short"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (hash_password(new), admin["user_id"]))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) VALUES (%s,%s,%s,%s,%s)", (admin["user_id"], "change_password", "user", str(admin["user_id"]), ""))
    return web.json_response({"ok": True})

async def handle_admin_debug_users(request):
    admin, err = await get_admin_user(request)
    if err: return denied(err)
    if not admin["is_super_admin"]: return web.json_response({"error": "forbidden"}, status=403)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT user_id, login, full_name, is_admin, is_super_admin, is_fired, position FROM users ORDER BY user_id")
            rows = [dict(r) for r in cur.fetchall()]
    return web.json_response({"count": len(rows), "users": rows})

def _sync_bootstrap(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("UPDATE users SET last_seen_at = NOW() WHERE user_id = %s", (user_id,))
            cur.execute("""
                SELECT u.*, c.name AS citizenship_name 
                FROM users u 
                LEFT JOIN citizenships c ON u.citizenship_id = c.id
                WHERE u.user_id = %s
            """, (user_id,))
            user = dict(cur.fetchone())
            _auto_publish_scheduled(cur)

            cur.execute("SELECT * FROM news WHERE status = 'published' ORDER BY created_at DESC LIMIT 50")
            news_rows = [dict(r) for r in cur.fetchall()]
            
            cur.execute("SELECT * FROM standards WHERE status = 'published' ORDER BY created_at DESC")
            std_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM faq ORDER BY id")
            faq_rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM restaurants WHERE key != 'office' ORDER BY sort, name")
            rest_rows = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM medbook_doctors ORDER BY sort, id")
            doctors = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_tests ORDER BY sort, id")
            tests = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_vaccines ORDER BY sort, id")
            vaccines = [dict(r) for r in cur.fetchall()]

            pos_lower = (user.get("position") or "").lower()
            is_hr = pos_lower.strip() == "hr"
            is_tu = "территориальный" in pos_lower
            is_us = "управляющий сменой" in pos_lower
            can_see_team = is_hr or is_tu or is_us

            team_rows = []
            if can_see_team:
                cur.execute("""
                    SELECT u.user_id, u.full_name, u.position, u.phone, u.restaurant_key, r.name AS restaurant_name,
                           COALESCE(u.is_certified, FALSE) AS is_certified, u.medbook, mgr.full_name AS manager_name,
                           c.name AS citizenship_name, u.hire_date
                    FROM users u
                    LEFT JOIN restaurants r ON u.restaurant_key = r.key
                    LEFT JOIN users mgr ON r.territory_manager_id = mgr.user_id
                    LEFT JOIN citizenships c ON u.citizenship_id = c.id
                    WHERE u.user_id != %s AND COALESCE(u.is_fired, FALSE) = FALSE AND COALESCE(u.is_admin, FALSE) = FALSE AND u.login IS NOT NULL
                    ORDER BY u.full_name
                """, (user_id,))
                all_staff = [dict(r) for r in cur.fetchall()]

                if is_us:
                    my_rest = user.get("restaurant_key")
                    team_rows = [s for s in all_staff if s.get("restaurant_key") == my_rest]
                elif is_tu:
                    cur.execute("SELECT key FROM restaurants WHERE territory_manager_id = %s", (user_id,))
                    my_rests = {r["key"] for r in cur.fetchall()}
                    team_rows = [s for s in all_staff if s.get("restaurant_key") in my_rests]
                else:
                    team_rows = all_staff

    user.pop("password_hash", None)
    return (user, news_rows, std_rows, faq_rows, rest_rows, doctors, tests, vaccines, team_rows, can_see_team)

async def handle_bootstrap(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    (u, news_rows, std_rows, faq_rows, rest_rows, doctors, tests, vaccines, team_rows, can_see_team) = await _run(_sync_bootstrap, user["user_id"])

    restaurant_name = ""
    restaurant_key = u.get("restaurant_key") or ""
    for r in rest_rows:
        if r["key"] == restaurant_key:
            restaurant_name = r["name"]
            break

    profile = {
        "full_name": u.get("full_name") or "", "first_name": (u.get("full_name") or "").split()[0] if u.get("full_name") else "",
        "phone": u.get("phone") or "", "birth_date": u.get("birth_date") or "", "position": u.get("position") or "—",
        "restaurant": restaurant_name or "—", "restaurant_key": restaurant_key, "is_certified": bool(u.get("is_certified")), "is_admin": bool(u.get("is_admin")),
        "hire_date": u.get("hire_date") or "—", "citizenship_name": u.get("citizenship_name") or "—",
        "can_access_timesheet": _sync_user_has_perm(u, "timesheet_access"),
    }

    mb = u.get("medbook") or {}
    if isinstance(mb, str):
        try: mb = json.loads(mb)
        except Exception: mb = {}

    def build_section(items, source):
        out = []
        for it in items:
            date_str = mb.get(source, {}).get(str(it["id"]), "")
            st = entry_status(date_str, it["validity_months"])
            out.append({"id": it["id"], "name": it["name"], "required": bool(it.get("required")), "validity_months": it["validity_months"], "date": date_str, "status": st})
        return out

    medbook_status = compute_medbook_status(mb, doctors, tests, vaccines)
    missing, total = medbook_missing_count(mb, doctors, tests, vaccines)

    medbook_payload = {
        "status": medbook_status, "missing": missing, "total": total,
        "doctors": build_section(doctors, "doctors"), "tests": build_section(tests, "tests"), "vaccines": build_section(vaccines, "vaccines"),
    }

    team_list = []
    for t in team_rows:
        tmb = t.get("medbook") or {}
        if isinstance(tmb, str):
            try: tmb = json.loads(tmb)
            except Exception: tmb = {}
        team_list.append({
            "user_id": t["user_id"], "full_name": t["full_name"] or "", "position": t["position"] or "",
            "phone": t["phone"] or "", "restaurant_key": t.get("restaurant_key") or "", "restaurant_name": t.get("restaurant_name") or "",
            "manager_name": t.get("manager_name") or "", "is_certified": bool(t.get("is_certified")), "medbook_status": compute_medbook_status(tmb, doctors, tests, vaccines),
            "hire_date": t.get("hire_date") or "—", "citizenship_name": t.get("citizenship_name") or "—"
        })

    return web.json_response({
        "profile": profile, "medbook": medbook_payload, "news": news_rows, "standards": std_rows, "faq": faq_rows,
        "restaurants": rest_rows, "team": team_list, "can_see_team": can_see_team,
    })

# ============= QUESTIONS (staff) =============
async def handle_questions_staff(request):
    user, err = await get_auth_user(request)
    if err: return denied(err)
    ip = request.remote or "unknown"
    if not _check_rate_limit(ip):
        return web.json_response({"error": "too_many_attempts"}, status=429)
    try: body = await request.json()
    except Exception: return web.json_response({"error": "invalid_json"}, status=400)
    text = (body.get("question") or "").strip()
    if not text or len(text) > 1000: return web.json_response({"error": "invalid"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur: cur.execute("INSERT INTO questions (user_id, text) VALUES (%s,%s)", (user["user_id"], text))
    return web.json_response({"ok": True})

# ============= UPLOAD =============
async def handle_admin_upload(request):
    token = request.query.get("token") or request.query.get("webToken")
    if not token:
        return web.json_response({"error": "unauthorized"}, status=401)
    
    user_id = await _run(_sync_get_session_user, token)
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)
    
    admin = await _run(_sync_get_user, user_id)
    if not admin or not admin.get("is_admin"):
        return web.json_response({"error": "forbidden"}, status=403)

    try:
        reader = await request.multipart()
        field = await reader.next()
        
        if not field or field.name != 'file':
            return web.json_response({"error": "invalid_file"}, status=400)
            
        filename = field.filename
        if not filename:
            return web.json_response({"error": "filename_required"}, status=400)
            
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return web.json_response({"error": "invalid_file_type"}, status=400)
            
        new_name = f"{uuid.uuid4().hex}{ext}"
        
        data_dir = os.getenv("DATA_DIR", "/data")
        upload_dir = os.path.join(data_dir, "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, new_name)
        
        with open(file_path, "wb") as f:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                f.write(chunk)
                
        return web.json_response({"ok": True, "url": f"/uploads/{new_name}", "name": filename})
        
    except Exception as e:
        logging.error(f"Upload error: {e}")
        return web.json_response({"error": "upload_failed"}, status=500)


async def handle_uploaded_file(request):
    filename = request.match_info['filename']
    
    token = request.query.get("token") or request.query.get("webToken")
    if not token:
        return web.Response(status=401, text="Unauthorized")
        
    user_id = await _run(_sync_get_session_user, token)
    if not user_id:
        return web.Response(status=401, text="Unauthorized")
        
    user = await _run(_sync_get_user, user_id)
    if not user or user.get("is_fired"):
        return web.Response(status=403, text="Forbidden")

    data_dir = os.getenv("DATA_DIR", "/data")
    upload_dir = os.path.abspath(os.path.join(data_dir, "uploads"))
    safe_path = os.path.abspath(os.path.join(upload_dir, os.path.basename(filename)))
    
    if not safe_path.startswith(upload_dir + os.sep):
        logging.warning(f"Path traversal attempt blocked: {filename}")
        return web.Response(status=403)
    if not os.path.exists(safe_path): return web.Response(status=404)
    
    ext = os.path.splitext(safe_path)[1].lower()
    headers = {}
    
    if ext not in IMAGE_EXTENSIONS:
        orig_name = request.query.get("name") or os.path.basename(filename)
        headers["Content-Disposition"] = f'attachment; filename="{orig_name}"'
    else:
        if ext in ('.jpg', '.jpeg'): headers["Content-Type"] = "image/jpeg"
        elif ext == '.png': headers["Content-Type"] = "image/png"
        elif ext == '.gif': headers["Content-Type"] = "image/gif"
        elif ext == '.webp': headers["Content-Type"] = "image/webp"
        
    return web.FileResponse(safe_path, headers=headers)

# ============= STATIC =============
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
            with open(p, "rb") as f: cache["data"] = f.read()
            cache["mtime"] = mtime
        return cache["data"]
    except OSError: return None

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
    if name not in _STATIC_FILES_CACHE: _STATIC_FILES_CACHE[name] = {"data": None, "mtime": 0.0}
    data = _serve_file(name, _STATIC_FILES_CACHE[name])
    if not data: return web.Response(status=404)
    kwargs = {"body": data, "content_type": content_type}
    if content_type.startswith("text/") or content_type in ("application/javascript", "application/manifest+json"):
        kwargs["charset"] = "utf-8"
    return web.Response(**kwargs)

async def handle_manifest(request): return await _send_static_file("manifest.json", "application/manifest+json")
async def handle_sw(request): return await _send_static_file("sw.js", "application/javascript")
async def handle_icon192(request): return await _send_static_file("icon-192.svg", "image/svg+xml")
async def handle_icon512(request): return await _send_static_file("icon-512.svg", "image/svg+xml")
async def handle_favicon(request): return web.Response(status=204)
async def handle_health(request): return web.Response(text="OK")

# ============= MIDDLEWARES =============
@web.middleware
async def error_middleware(request, handler):
    try: return await handler(request)
    except web.HTTPException: raise
    except Exception as e:
        logging.error("Unhandled %s %s: %s\n%s", request.method, request.path, type(e).__name__, traceback.format_exc())
        detail = str(e)[:200] if APP_ENV != "production" else "Internal Server Error"
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
            if "Content-Length" in response.headers: del response.headers["Content-Length"]
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

app = web.Application(middlewares=[error_middleware, gzip_middleware, security_headers_middleware], client_max_size=20 * 1024 * 1024)

# ============= ROUTES =============
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
app.router.add_get("/uploads/{filename}", handle_uploaded_file)

app.router.add_post("/api/auth/login", handle_auth_login_staff)
app.router.add_post("/api/auth/logout", handle_auth_logout)
app.router.add_post("/api/bootstrap", handle_bootstrap)
app.router.add_post("/api/questions", handle_questions_staff)
app.router.add_post("/api/certification/get", handle_staff_certification_get)
app.router.add_post("/api/certification/submit", handle_staff_certification_submit)
app.router.add_post("/api/push/subscribe", handle_push_subscribe)

app.router.add_post("/api/academy/courses", handle_academy_courses)
app.router.add_post("/api/academy/course", handle_academy_course_detail)
app.router.add_post("/api/academy/submit-test", handle_academy_submit_test)

app.router.add_post("/api/timesheet/get", handle_timesheet_get)
app.router.add_post("/api/timesheet/save", handle_timesheet_save)
app.router.add_post("/api/timesheet/matrix", handle_timesheet_matrix)
app.router.add_post("/api/timesheet/save_cell", handle_timesheet_save_cell)
app.router.add_post("/api/timesheet/bulk_save", handle_timesheet_bulk_save)
app.router.add_post("/api/timesheet/update_rate", handle_timesheet_update_rate)
app.router.add_post("/api/timesheet/employees", handle_timesheet_employees)
app.router.add_post("/api/timesheet/reports", handle_timesheet_reports)

app.router.add_post("/api/admin/login", handle_auth_login)
app.router.add_post("/api/admin/me", handle_admin_me)
app.router.add_post("/api/admin/dashboard", handle_admin_dashboard)
app.router.add_post("/api/admin/medbook-alerts", handle_admin_medbook_alerts)
app.router.add_post("/api/admin/upload", handle_admin_upload)

app.router.add_post("/api/admin/citizenships", handle_admin_citizenships)
app.router.add_post("/api/admin/citizenship/add", handle_admin_citizenship_add)

app.router.add_post("/api/admin/users", handle_admin_users)
app.router.add_post("/api/admin/user/get", handle_admin_user_get)
app.router.add_post("/api/admin/user/create", handle_admin_user_create)
app.router.add_post("/api/admin/user/update", handle_admin_user_update)
app.router.add_post("/api/admin/user/delete", handle_admin_user_delete)
app.router.add_post("/api/admin/user/fire", handle_admin_user_fire)
app.router.add_post("/api/admin/user/restore", handle_admin_user_restore)

app.router.add_post("/api/admin/admins", handle_admin_admins)
app.router.add_post("/api/admin/set-permissions", handle_admin_set_permissions)
app.router.add_post("/api/admin/debug/users", handle_admin_debug_users)

app.router.add_post("/api/admin/restaurants", handle_admin_restaurants)
app.router.add_post("/api/admin/restaurant/add", handle_admin_restaurant_add)
app.router.add_post("/api/admin/restaurant/update", handle_admin_restaurant_update)
app.router.add_post("/api/admin/restaurant/tu", handle_admin_restaurant_tu)
app.router.add_post("/api/admin/restaurant/status", handle_admin_restaurant_status)

app.router.add_post("/api/admin/medbooks", handle_admin_medbooks)
app.router.add_post("/api/admin/medbook/get", handle_admin_medbook_get)
app.router.add_post("/api/admin/medbook/save", handle_admin_medbook_save)
app.router.add_post("/api/admin/medbook/reference/add", handle_admin_medbook_ref_add)
app.router.add_post("/api/admin/medbook/reference/update", handle_admin_medbook_ref_update)
app.router.add_post("/api/admin/medbook/reference/delete", handle_admin_medbook_ref_delete)

app.router.add_post("/api/admin/news", handle_admin_news_list)
app.router.add_post("/api/admin/news/add", handle_admin_news_add)
app.router.add_post("/api/admin/news/update", handle_admin_news_update)
app.router.add_post("/api/admin/news/delete", handle_admin_news_delete)
app.router.add_post("/api/admin/news/approve", handle_admin_news_approve)
app.router.add_post("/api/admin/news/reject", handle_admin_news_reject)

app.router.add_post("/api/admin/standards", handle_admin_standards)
app.router.add_post("/api/admin/standard/add", handle_admin_standard_add)
app.router.add_post("/api/admin/standard/update", handle_admin_standard_update)
app.router.add_post("/api/admin/standard/delete", handle_admin_standard_delete)
app.router.add_post("/api/admin/standard/approve", handle_admin_standard_approve)
app.router.add_post("/api/admin/standard/reject", handle_admin_standard_reject)

app.router.add_post("/api/admin/certification", handle_admin_certification_list)
app.router.add_post("/api/admin/certification/add", handle_admin_certification_add)
app.router.add_post("/api/admin/certification/delete", handle_admin_certification_delete)

app.router.add_post("/api/admin/faq", handle_admin_faq)
app.router.add_post("/api/admin/faq/add", handle_admin_faq_add)
app.router.add_post("/api/admin/faq/update", handle_admin_faq_update)
app.router.add_post("/api/admin/faq/delete", handle_admin_faq_delete)
app.router.add_post("/api/admin/positions", handle_admin_positions)
app.router.add_post("/api/admin/position/add", handle_admin_position_add)
app.router.add_post("/api/admin/position/archive", handle_admin_position_archive)
app.router.add_post("/api/admin/questions", handle_admin_questions)
app.router.add_post("/api/admin/question/reply", handle_admin_question_reply)

app.router.add_post("/api/admin/audit", handle_admin_audit)
app.router.add_post("/api/admin/reports", handle_admin_reports)
app.router.add_post("/api/admin/change-password", handle_admin_change_password)

# ============= MAIN =============
async def main():
    port = int(os.getenv("PORT", 8080))
    if os.getenv("RUN_MIGRATIONS", "true").lower() == "true":
        init_pool()
        await _run(init_db_and_seed)
    else:
        logging.info("⏩ Миграции пропущены (RUN_MIGRATIONS != true)")
        init_pool()

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"✅ Server on port {port}")
    logging.info(f"👤 Admin: {ADMIN_LOGIN}")

    cleanup_task = asyncio.create_task(_cleanup_sessions_loop())

    try:
        await asyncio.Event().wait()
    finally:
        cleanup_task.cancel()
        try: await cleanup_task
        except asyncio.CancelledError: pass
        await runner.cleanup()
        if _pool: _pool.closeall()

if __name__ == "__main__":
    asyncio.run(main())
