import os
import io
import csv
import json
import gzip
import re
import time
import secrets
import hashlib
import logging
import asyncio
import random
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from aiohttp import web
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor, Json

try:
    from zoneinfo import ZoneInfo
    MOSCOW_TZ = ZoneInfo("Europe/Moscow")
except Exception:
    MOSCOW_TZ = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise ValueError("DATABASE_URL is not set")

ADMIN_LOGIN = os.getenv("ADMIN_LOGIN", "adm01").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Wokker2026")
APP_URL = os.getenv("MINI_APP_URL", "").rstrip("/")

LOGIN_RE = re.compile(r"^[a-z]{3}\d{2}$")

# ============= ПРАВА =============
PERMISSIONS_LIST = [
    {"key": "users_create", "label": "Добавлять сотрудников"},
    {"key": "users_edit", "label": "Редактировать сотрудников"},
    {"key": "users_fire", "label": "Увольнять сотрудников"},
    {"key": "medbook_edit", "label": "Заполнять медкнижки"},
    {"key": "medbook_doctors_manage", "label": "Врачи: добавление и сроки"},
    {"key": "medbook_tests_manage", "label": "Анализы: добавление и сроки"},
    {"key": "medbook_vaccines_manage", "label": "Прививки: добавление и сроки"},
    {"key": "restaurant_tu", "label": "Менять ТУ у ресторанов"},
    {"key": "standards_edit", "label": "Менять стандарты"},
    {"key": "checklist_create", "label": "Создавать чек-листы"},
    {"key": "checklist_edit", "label": "Редактировать чек-листы"},
    {"key": "news_write", "label": "Писать новости"},
    {"key": "news_edit", "label": "Редактировать новости"},
    {"key": "news_suggest", "label": "Предлагать новости"},
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
        if len(letters) >= 3:
            break
        t = TRANSLIT.get(ch)
        if t:
            letters += t
    while len(letters) < 3:
        letters += random.choice("abcdefghijklmnopqrstuvwxyz")
    letters = letters[:3]

    digits = list(range(10, 100))
    random.shuffle(digits)
    for d in digits:
        candidate = f"{letters}{d}"
        if candidate not in existing_logins:
            return candidate
    for _ in range(500):
        rl = "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(3))
        d = random.randint(10, 99)
        candidate = f"{rl}{d}"
        if candidate not in existing_logins:
            return candidate
    raise RuntimeError("Не удалось сгенерировать логин")

# ============= МЕДКНИЖКИ =============
def parse_date_ddmmYYYY(s):
    if not s:
        return None
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", str(s).strip())
    if not m:
        return None
    try:
        d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d.day != int(m.group(1)) or d.month != int(m.group(2)):
            return None
        return d
    except ValueError:
        return None

def add_months(dt, months):
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=y, month=m)

def entry_status(date_str, validity_months):
    if not date_str:
        return "missing"
    d = parse_date_ddmmYYYY(date_str)
    if not d:
        return "invalid_date"
    exp = add_months(d, validity_months)
    now = datetime.utcnow()
    if exp < now:
        return "expired"
    if (exp - now).days <= 30:
        return "expiring"
    return "ok"

def compute_medbook_status(medbook, doctors, tests, vaccines):
    mb = medbook or {}
    if isinstance(mb, str):
        try:
            mb = json.loads(mb)
        except Exception:
            mb = {}
    items = []
    for d in doctors:
        items.append((mb.get("doctors", {}).get(str(d["id"])), d["validity_months"]))
    for t in tests:
        items.append((mb.get("tests", {}).get(str(t["id"])), t["validity_months"]))
    for v in vaccines:
        items.append((mb.get("vaccines", {}).get(str(v["id"])), v["validity_months"]))
    has_expiring = False
    for date_str, validity in items:
        s = entry_status(date_str, validity)
        if s in ("missing", "invalid_date", "expired"):
            return "invalid"
        if s == "expiring":
            has_expiring = True
    return "expiring" if has_expiring else "ok"

def medbook_missing_count(medbook, doctors, tests, vaccines):
    mb = medbook or {}
    if isinstance(mb, str):
        try:
            mb = json.loads(mb)
        except Exception:
            mb = {}
    items = []
    for d in doctors:
        items.append((mb.get("doctors", {}).get(str(d["id"])), d["validity_months"]))
    for t in tests:
        items.append((mb.get("tests", {}).get(str(t["id"])), t["validity_months"]))
    for v in vaccines:
        items.append((mb.get("vaccines", {}).get(str(v["id"])), v["validity_months"]))
    missing = sum(1 for date_str, v in items if entry_status(date_str, v) in ("missing", "invalid_date", "expired"))
    return missing, len(items)

# ============= БД =============
_pool = None

def init_pool():
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(2, 20, DB_URL)

@contextmanager
def get_conn():
    init_pool()
    conn = _pool.getconn()
    try:
        with conn:
            yield conn
    finally:
        _pool.putconn(conn)

async def _run(fn, *args):
    return await asyncio.to_thread(fn, *args)

# ============= SEED =============
RESTAURANTS_SEED = [
    {"key": "belyaevo", "name": "Беляево", "address": "Москва, ул. Миклухо-Маклая, 32А, ТЦ «Капитолий», этаж 2", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6437, "lon": 37.5302, "org": "vokker/13122472923", "phone": "+7 (985) 857-06-69"},
    {"key": "vernadka", "name": "Вернадка", "address": "Москва, проспект Вернадского, 6, ТЦ «Капитолий Вернадского», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6845, "lon": 37.4948, "org": "vokker/91626648547", "phone": ""},
    {"key": "metropolis", "name": "Метрополис", "address": "Москва, Ленинградское ш., д. 16А, стр. 4, ТРЦ «Метрополис», этаж 3", "hours": "Пн–вс: 10:00–23:00", "lat": 55.8214, "lon": 37.4977, "org": "vokker/1298559872", "phone": "+7 (985) 857-07-14"},
    {"key": "mega_himki", "name": "Мега Химки", "address": "Московская обл., г. Химки, микрорайон ИКЕА, к1, ТЦ «Мега Химки», этаж 1", "hours": "Пн–чт, вс: 10:00–23:00\nПт–сб: 10:00–24:00", "lat": 55.8948, "lon": 37.3973, "org": "vokker/132066311330", "phone": "+7 (985) 857-08-22"},
    {"key": "office", "name": "ОФИС", "address": "Центральный офис", "hours": "Пн–пт: 09:00–18:00", "lat": None, "lon": None, "org": "", "phone": ""},
]

STANDARDS_SEED = [
    {"title": "Правила открытия смены", "category": "Чек-листы", "description": "Что проверить перед открытием: оборудование, чистота, касса.", "url": ""},
    {"title": "Стандарт работы вокера", "category": "Технология", "description": "Пошаговый стандарт приготовления блюд на воке.", "url": ""},
    {"title": "Обработка жалоб гостей", "category": "Сервис", "description": "Как реагировать на претензии и когда звать управляющего.", "url": ""},
]

FAQ_SEED = [
    {"question": "Как посмотреть график смен?", "answer": "График вывешивается на информационной доске в ресторане и уточняется у управляющего сменой.", "category": "Работа"},
    {"question": "Куда сообщать о поломке оборудования?", "answer": "Напиши управляющему сменой. Если поломка серьёзная — он оформляет заявку в сервис.", "category": "Работа"},
    {"question": "Как поменять пароль?", "answer": "Обратись к администратору — он сменит пароль в админ-панели.", "category": "Бот"},
]

POSITIONS_SEED = ["Повар холодного цеха", "Повар горячего цеха", "Управляющий сменой", "Территориальный управляющий", "HR"]

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

# ============= ИНИЦИАЛИЗАЦИЯ БД =============
init_pool()

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGSERIAL PRIMARY KEY,
                login TEXT,
                password_hash TEXT,
                full_name TEXT,
                phone TEXT,
                birth_date TEXT,
                position TEXT,
                restaurant_key TEXT,
                is_admin BOOLEAN DEFAULT FALSE,
                is_super_admin BOOLEAN DEFAULT FALSE,
                permissions JSONB DEFAULT '{}',
                is_fired BOOLEAN DEFAULT FALSE,
                fired_at TIMESTAMPTZ,
                fired_by TEXT,
                is_certified BOOLEAN DEFAULT FALSE,
                medbook JSONB DEFAULT '{"doctors":{},"tests":{},"vaccines":{}}',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ
            )
        """)
        # Миграции для старой схемы
        for col, ddl in [
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
        ]:
            cur.execute(ddl)
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users (LOWER(login)) WHERE login IS NOT NULL")

        # === МИГРАЦИЯ: гарантируем, что user_id имеет автоинкремент (BIGSERIAL) ===
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'users_user_id_seq') THEN
                    CREATE SEQUENCE users_user_id_seq;
                END IF;
                PERFORM setval(
                    'users_user_id_seq',
                    GREATEST((SELECT COALESCE(MAX(user_id), 0) FROM users), 1),
                    (SELECT COUNT(*) FROM users) > 0
                );
                ALTER TABLE users ALTER COLUMN user_id SET DEFAULT nextval('users_user_id_seq');
                ALTER SEQUENCE users_user_id_seq OWNED BY users.user_id;
            END $$;
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS restaurants (
                key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                address TEXT,
                hours TEXT,
                lat REAL,
                lon REAL,
                org TEXT,
                phone TEXT DEFAULT '',
                force_status TEXT,
                sort INT DEFAULT 100,
                territory_manager_id BIGINT
            )
        """)
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS force_status TEXT")
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS sort INT DEFAULT 100")
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS territory_manager_id BIGINT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS medbook_doctors (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                required BOOLEAN DEFAULT FALSE,
                validity_months INT DEFAULT 12,
                sort INT DEFAULT 100
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS medbook_tests (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                required BOOLEAN DEFAULT FALSE,
                validity_months INT DEFAULT 12,
                sort INT DEFAULT 100
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS medbook_vaccines (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                required BOOLEAN DEFAULT FALSE,
                validity_months INT DEFAULT 12,
                sort INT DEFAULT 100
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                level TEXT DEFAULT 'normal',
                status TEXT DEFAULT 'published',
                publish_at TIMESTAMPTZ,
                proposed_by TEXT,
                approved_by TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS level TEXT DEFAULT 'normal'")
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'published'")
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS publish_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS proposed_by TEXT")
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS approved_by TEXT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS standards (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT DEFAULT '',
                description TEXT DEFAULT '',
                url TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS faq (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                sort INT DEFAULT 100,
                is_archived BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_audit (
                id SERIAL PRIMARY KEY,
                admin_id BIGINT,
                action TEXT,
                target_type TEXT,
                target_id TEXT,
                details TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                text TEXT NOT NULL,
                replied BOOLEAN DEFAULT FALSE,
                reply_text TEXT,
                replied_at TIMESTAMPTZ,
                replied_by BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                token TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_used_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Seеды
        cur.execute("SELECT COUNT(*) FROM restaurants")
        if cur.fetchone()[0] == 0:
            for i, r in enumerate(RESTAURANTS_SEED):
                sort = 999 if r["key"] == "office" else i
                cur.execute(
                    "INSERT INTO restaurants (key, name, address, hours, lat, lon, org, phone, sort) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (r["key"], r["name"], r["address"], r["hours"], r["lat"], r["lon"], r["org"], r["phone"], sort)
                )

        cur.execute("SELECT COUNT(*) FROM standards")
        if cur.fetchone()[0] == 0:
            for s in STANDARDS_SEED:
                cur.execute("INSERT INTO standards (title, category, description, url) VALUES (%s,%s,%s,%s)",
                            (s["title"], s["category"], s["description"], s["url"]))
        cur.execute("SELECT COUNT(*) FROM faq")
        if cur.fetchone()[0] == 0:
            for f in FAQ_SEED:
                cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s,%s,%s)",
                            (f["question"], f["answer"], f["category"]))
        cur.execute("SELECT COUNT(*) FROM positions")
        if cur.fetchone()[0] == 0:
            for i, name in enumerate(POSITIONS_SEED):
                cur.execute("INSERT INTO positions (name, sort) VALUES (%s,%s)", (name, i))

        cur.execute("SELECT COUNT(*) FROM medbook_doctors")
        if cur.fetchone()[0] == 0:
            for d in DOCTORS_SEED:
                cur.execute("INSERT INTO medbook_doctors (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)",
                            (d["name"], d["required"], d["validity_months"], d["sort"]))
        cur.execute("SELECT COUNT(*) FROM medbook_tests")
        if cur.fetchone()[0] == 0:
            for t in TESTS_SEED:
                cur.execute("INSERT INTO medbook_tests (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)",
                            (t["name"], t["required"], t["validity_months"], t["sort"]))
        cur.execute("SELECT COUNT(*) FROM medbook_vaccines")
        if cur.fetchone()[0] == 0:
            for v in VACCINES_SEED:
                cur.execute("INSERT INTO medbook_vaccines (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)",
                            (v["name"], v["required"], v["validity_months"], v["sort"]))

        cur.execute("SELECT COUNT(*) FROM news")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO news (title, body, level, status) VALUES (%s,%s,%s,%s)",
                        ("Открытие новой точки", "Скоро открываем новый ресторан!", "urgent", "published"))
            cur.execute("INSERT INTO news (title, body, level, status) VALUES (%s,%s,%s,%s)",
                        ("Обновление меню", "Появились новые позиции в меню.", "normal", "published"))

        # Создание первичного супер-админа
        cur.execute("SELECT COUNT(*) FROM users WHERE is_super_admin = TRUE")
        if cur.fetchone()[0] == 0:
            pw = hash_password(ADMIN_PASSWORD)
            cur.execute("""
                INSERT INTO users (login, password_hash, full_name, position, is_admin, is_super_admin)
                VALUES (%s, %s, 'Администратор', 'Администратор', TRUE, TRUE)
            """, (ADMIN_LOGIN, pw))
            print(f"✅ Создан супер-администратор: логин={ADMIN_LOGIN}")

print("✅ БД инициализирована")

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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM web_sessions WHERE token = %s", (token,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE web_sessions SET last_used_at = NOW() WHERE token = %s", (token,))
                return row[0]
    return None

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
    if not user:
        return False
    if user["is_super_admin"]:
        return True
    if user["position"] == "HR":
        return True
    perms = user.get("permissions") or {}
    if isinstance(perms, str):
        try:
            perms = json.loads(perms)
        except Exception:
            perms = {}
    return bool(perms.get(perm))

def _sync_compute_user_status(user, doctors, tests, vaccines):
    if user.get("is_admin"):
        return "—"
    return compute_medbook_status(user.get("medbook") or {}, doctors, tests, vaccines)

# ============= AUTH =============
async def get_auth_user(request):
    try:
        body = await request.json()
    except Exception:
        return None, 401
    token = body.get("webToken") or ""
    if not token:
        return None, 401
    user_id = await _run(_sync_get_session_user, token)
    if not user_id:
        return None, 401
    user = await _run(_sync_get_user, user_id)
    if not user:
        return None, 401
    if user.get("is_fired"):
        return None, 403
    return user, None

def denied(status):
    if status == 403:
        return web.json_response({"error": "forbidden"}, status=403)
    return web.json_response({"error": "unauthorized"}, status=401)

# ============= АДМИНСКИЕ ХЕЛПЕРЫ =============
def require_perm(user, perm):
    if not _sync_user_has_perm(user, perm):
        return web.json_response({"error": "forbidden"}, status=403)
    return None

async def get_admin_user(request):
    user, err = await get_auth_user(request)
    if err:
        return None, err
    if not user.get("is_admin"):
        return None, 403
    return user, None

# ============= API: AUTH =============
async def handle_auth_login(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    login = (data.get("login") or "").strip().lower()
    password = data.get("password") or ""
    if not LOGIN_RE.match(login):
        return web.json_response({"error": "invalid_login_format"}, status=400)
    if not password:
        return web.json_response({"error": "password_required"}, status=400)

    user = await _run(_sync_get_user_by_login, login)
    if not user or not verify_password(password, user.get("password_hash") or ""):
        return web.json_response({"error": "invalid_credentials"}, status=401)
    if user.get("is_fired"):
        return web.json_response({"error": "fired"}, status=403)
    if not user.get("is_admin"):
        return web.json_response({"error": "not_admin"}, status=403)

    token = await _run(_sync_create_session, user["user_id"])
    return web.json_response({"ok": True, "token": token, "is_admin": True})

async def handle_auth_login_staff(request):
    """Логин для сотрудников (без обязательного is_admin)"""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    login = (data.get("login") or "").strip().lower()
    password = data.get("password") or ""
    if not LOGIN_RE.match(login):
        return web.json_response({"error": "invalid_login_format"}, status=400)
    if not password:
        return web.json_response({"error": "password_required"}, status=400)

    user = await _run(_sync_get_user_by_login, login)
    if not user or not verify_password(password, user.get("password_hash") or ""):
        return web.json_response({"error": "invalid_credentials"}, status=401)
    if user.get("is_fired"):
        return web.json_response({"error": "fired"}, status=403)

    token = await _run(_sync_create_session, user["user_id"])
    return web.json_response({"ok": True, "token": token, "is_admin": bool(user.get("is_admin"))})

async def handle_auth_logout(request):
    try:
        data = await request.json()
    except Exception:
        data = {}
    token = data.get("webToken") or ""
    if token:
        await _run(_sync_delete_session, token)
    return web.json_response({"ok": True})

# ============= API: ADMIN ME / DASHBOARD =============
async def handle_admin_me(request):
    user, err = await get_admin_user(request)
    if err:
        return denied(err)
    return web.json_response({
        "is_admin": True,
        "profile": {
            "user_id": user["user_id"],
            "login": user.get("login") or "",
            "full_name": user.get("full_name") or "",
            "position": user.get("position") or "",
            "is_super_admin": bool(user.get("is_super_admin")),
            "is_hr": user.get("position") == "HR",
            "permissions": user.get("permissions") or {},
        }
    })

def _sync_dashboard_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE is_admin = FALSE AND is_fired = FALSE AND login IS NOT NULL")
            active = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE login IS NOT NULL")
            total = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_fired = TRUE")
            fired = cur.fetchone()[0] or 0
            cur.execute("""SELECT COUNT(*) FROM users WHERE created_at::date = NOW()::date
                           AND is_admin = FALSE AND is_fired = FALSE AND login IS NOT NULL""")
            new_today = cur.fetchone()[0] or 0
            cur.execute("""SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '7 days'
                           AND is_admin = FALSE AND is_fired = FALSE AND login IS NOT NULL""")
            new7 = cur.fetchone()[0] or 0
            cur.execute("""SELECT COUNT(*) FROM users WHERE is_admin = FALSE AND is_fired = FALSE
                           AND login IS NOT NULL AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '7 days')""")
            inactive7 = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM questions WHERE replied = FALSE")
            questions_open = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM news WHERE status = 'pending'")
            news_pending = cur.fetchone()[0] or 0
    return {
        "total": total, "active": active, "fired": fired,
        "new_today": new_today, "new7": new7, "inactive7": inactive7,
        "questions_open": questions_open, "news_pending": news_pending,
    }

async def handle_admin_dashboard(request):
    user, err = await get_admin_user(request)
    if err:
        return denied(err)
    stats = await _run(_sync_dashboard_stats)
    return web.json_response({"stats": stats})

# ============= API: USERS =============
def _sync_list_users(search="", fired=False):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            base = """
                SELECT u.*, r.name AS restaurant_name
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                WHERE u.is_fired = %s AND u.login IS NOT NULL
            """
            params = [fired]
            if search:
                base += """ AND (LOWER(COALESCE(u.full_name,'')) LIKE %s
                              OR LOWER(COALESCE(u.login,'')) LIKE %s
                              OR COALESCE(u.phone,'') LIKE %s
                              OR CAST(u.user_id AS TEXT) LIKE %s)"""
                s = f"%{search.lower()}%"
                params.extend([s, s, f"%{search}%", f"%{search}%"])
            base += " ORDER BY u.user_id DESC"
            cur.execute(base, params)
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_users(request):
    user, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        body = {}
    search = (body.get("search") or "").strip()
    fired = bool(body.get("fired"))
    users = await _run(_sync_list_users, search, fired)
    doctors, tests, vaccines = await _run(_sync_get_medbook_refs)
    for u in users:
        u["medbook_status"] = compute_medbook_status(u.get("medbook") or {}, doctors, tests, vaccines) if not u["is_admin"] else "—"
        u.pop("password_hash", None)
        if isinstance(u.get("medbook"), dict):
            pass
        else:
            try:
                u["medbook"] = json.loads(u.get("medbook") or "{}")
            except Exception:
                u["medbook"] = {}
    return web.json_response({"users": users})

def _sync_create_user(body, existing_logins):
    login = body.get("login") or ""
    full_name = body.get("full_name") or ""
    password = body.get("password") or ""

    if not full_name or not password or len(password) < 6:
        return None, "invalid"
    if not login or not LOGIN_RE.match(login) or login in existing_logins:
        login = _generate_login_for(full_name, existing_logins)

    pw_hash = hash_password(password)
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO users (login, password_hash, full_name, phone, birth_date, position,
                                   restaurant_key, is_certified)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
            """, (login, pw_hash, full_name, body.get("phone") or "",
                  body.get("birth_date") or "", body.get("position") or "",
                  body.get("restaurant") or "", bool(body.get("is_certified"))))
            new_user = dict(cur.fetchone())
            cur.execute("INSERT INTO admin_audit (action, target_type, target_id, details) VALUES (%s,%s,%s,%s)",
                        ("user_create", "user", str(new_user["user_id"]), f"login={login}"))
    return new_user, None

async def handle_admin_user_create(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "users_create")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)

    existing_logins = await _run(_sync_get_all_logins)
    new_user, err_code = await _run(_sync_create_user, body, existing_logins)
    if err_code:
        return web.json_response({"error": err_code}, status=400)
    new_user.pop("password_hash", None)
    return web.json_response({"ok": True, "user": new_user})

def _sync_get_user_by_id(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT u.*, r.name AS restaurant_name
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                WHERE u.user_id = %s
            """, (user_id,))
            return cur.fetchone()

async def handle_admin_user_get(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)
    user = await _run(_sync_get_user_by_id, uid)
    if not user:
        return web.json_response({"error": "not_found"}, status=404)
    user.pop("password_hash", None)
    return web.json_response({"user": user})

def _sync_update_user(uid, updates):
    allowed_simple = {"full_name", "phone", "birth_date", "position", "restaurant_key", "is_certified"}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for k, v in updates.items():
                if k in allowed_simple:
                    cur.execute(f"UPDATE users SET {k} = %s WHERE user_id = %s", (v, uid))
            if "password" in updates and updates["password"]:
                pw = hash_password(updates["password"])
                cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (pw, uid))
            if "is_admin" in updates:
                cur.execute("UPDATE users SET is_admin = %s WHERE user_id = %s",
                            (bool(updates["is_admin"]), uid))
                if not updates["is_admin"]:
                    cur.execute("UPDATE users SET permissions = '{}'::jsonb, is_super_admin = FALSE WHERE user_id = %s", (uid,))
    return True

async def handle_admin_user_update(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "users_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)
    updates = body.get("updates") or {}

    target = await _run(_sync_get_user_by_id, uid)
    if not target:
        return web.json_response({"error": "not_found"}, status=404)

    if "is_admin" in updates and not admin["is_super_admin"]:
        return web.json_response({"error": "forbidden_is_admin"}, status=403)
    if target.get("is_super_admin") and not admin["is_super_admin"]:
        return web.json_response({"error": "cannot_edit_super"}, status=403)

    if "restaurant" in updates:
        updates["restaurant_key"] = updates.pop("restaurant")

    await _run(_sync_update_user, uid, updates)
    updated = await _run(_sync_get_user_by_id, uid)
    updated.pop("password_hash", None)
    return web.json_response({"ok": True, "user": updated})

async def handle_admin_user_fire(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "users_fire")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)

    target = await _run(_sync_get_user_by_id, uid)
    if not target:
        return web.json_response({"error": "not_found"}, status=404)
    if target.get("is_super_admin"):
        return web.json_response({"error": "cannot_fire_super"}, status=403)
    if uid == admin["user_id"]:
        return web.json_response({"error": "cannot_fire_self"}, status=403)
    if target.get("is_fired"):
        return web.json_response({"error": "already_fired"}, status=400)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE users SET is_fired = TRUE, fired_at = NOW(), fired_by = %s,
                           is_admin = FALSE, is_super_admin = FALSE, permissions = '{}'::jsonb
                           WHERE user_id = %s""", (admin["login"], uid))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (admin["user_id"], "user_fire", "user", str(uid), f"by={admin['login']}"))
    return web.json_response({"ok": True})

async def handle_admin_user_restore(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "users_fire")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_fired = FALSE, fired_at = NULL, fired_by = NULL WHERE user_id = %s", (uid,))
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (admin["user_id"], "user_restore", "user", str(uid), f"by={admin['login']}"))
    return web.json_response({"ok": True})

async def handle_admin_user_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "users_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)
    target = await _run(_sync_get_user_by_id, uid)
    if not target:
        return web.json_response({"error": "not_found"}, status=404)
    if target.get("is_super_admin"):
        return web.json_response({"error": "cannot_delete_super"}, status=403)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (uid,))
    return web.json_response({"ok": True})

# ============= API: ADMINS / PERMISSIONS =============
def _sync_list_admins():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE is_admin = TRUE AND is_fired = FALSE ORDER BY user_id")
            admins = [dict(r) for r in cur.fetchall()]
    for a in admins:
        a.pop("password_hash", None)
    return admins

async def handle_admin_admins(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not admin["is_super_admin"]:
        return web.json_response({"error": "forbidden"}, status=403)
    admins = await _run(_sync_list_admins)
    return web.json_response({"admins": admins})

async def handle_admin_set_permissions(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not admin["is_super_admin"]:
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)
    perms = body.get("permissions") or {}
    target = await _run(_sync_get_user_by_id, uid)
    if not target:
        return web.json_response({"error": "not_found"}, status=404)
    if target.get("is_super_admin"):
        return web.json_response({"error": "cannot_edit_super"}, status=403)
    if not target.get("is_admin"):
        return web.json_response({"error": "not_admin"}, status=400)
    cleaned = {k: True for k in PERM_KEYS if perms.get(k)}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET permissions = %s WHERE user_id = %s", (Json(cleaned), uid))
    return web.json_response({"ok": True})

# ============= API: RESTAURANTS =============
def _sync_restaurants():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT r.*, u.full_name AS territory_manager_name
                FROM restaurants r LEFT JOIN users u ON r.territory_manager_id = u.user_id
                ORDER BY r.sort, r.name
            """)
            return [dict(r) for r in cur.fetchall()]

def _sync_tu_candidates():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""SELECT user_id, full_name FROM users
                           WHERE is_fired = FALSE AND LOWER(COALESCE(position,'')) LIKE '%%территориальный%%'
                           ORDER BY full_name""")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_restaurants(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    restaurants = await _run(_sync_restaurants)
    tu = await _run(_sync_tu_candidates)
    return web.json_response({"restaurants": restaurants, "tu_candidates": tu})

async def handle_admin_restaurant_update(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    updates = body.get("updates") or {}
    allowed = {"name", "address", "phone", "hours", "org", "lat", "lon"}
    with get_conn() as conn:
        with conn.cursor() as cur:
            for k, v in updates.items():
                if k in allowed:
                    cur.execute(f"UPDATE restaurants SET {k} = %s WHERE key = %s", (v, key))
    return web.json_response({"ok": True})

async def handle_admin_restaurant_tu(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "restaurant_tu")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    tu = body.get("territory_manager_id")
    tu = int(tu) if tu else None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE restaurants SET territory_manager_id = %s WHERE key = %s", (tu, key))
    return web.json_response({"ok": True})

async def handle_admin_restaurant_status(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    key = body.get("key") or ""
    st = body.get("status")
    if st == "auto":
        st = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE restaurants SET force_status = %s WHERE key = %s", (st, key))
    return web.json_response({"ok": True})

# ============= API: MEDBOOKS =============
def _sync_medbooks_full():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM medbook_doctors ORDER BY sort, id")
            doctors = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_tests ORDER BY sort, id")
            tests = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM medbook_vaccines ORDER BY sort, id")
            vaccines = [dict(r) for r in cur.fetchall()]
            cur.execute("""
                SELECT u.user_id, u.full_name, u.position, u.medbook, r.name AS restaurant_name
                FROM users u LEFT JOIN restaurants r ON u.restaurant_key = r.key
                WHERE u.is_admin = FALSE AND u.is_fired = FALSE AND u.login IS NOT NULL
                ORDER BY u.full_name
            """)
            users = [dict(r) for r in cur.fetchall()]
    for u in users:
        mb = u.get("medbook") or {}
        if isinstance(mb, str):
            try:
                mb = json.loads(mb)
            except Exception:
                mb = {}
        u["medbook"] = mb
        u["medbook_status"] = compute_medbook_status(mb, doctors, tests, vaccines)
        missing, total = medbook_missing_count(mb, doctors, tests, vaccines)
        u["missing"] = missing
        u["total"] = total
    return doctors, tests, vaccines, users

async def handle_admin_medbooks(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    doctors, tests, vaccines, users = await _run(_sync_medbooks_full)
    return web.json_response({
        "doctors": doctors, "tests": tests, "vaccines": vaccines, "users": users,
    })

async def handle_admin_medbook_get(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)
    user = await _run(_sync_get_user_by_id, uid)
    if not user:
        return web.json_response({"error": "not_found"}, status=404)
    doctors, tests, vaccines = await _run(_sync_get_medbook_refs)
    mb = user.get("medbook") or {}
    if isinstance(mb, str):
        try:
            mb = json.loads(mb)
        except Exception:
            mb = {}
    return web.json_response({
        "user": {"user_id": user["user_id"], "full_name": user.get("full_name"),
                 "position": user.get("position"), "restaurant_name": user.get("restaurant_name") or ""},
        "medbook": mb,
        "doctors": doctors, "tests": tests, "vaccines": vaccines,
    })

async def handle_admin_medbook_save(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    perm_err = require_perm(admin, "medbook_edit")
    if perm_err:
        return perm_err
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    uid = int(body.get("user_id") or 0)
    mb = body.get("medbook") or {"doctors": {}, "tests": {}, "vaccines": {}}
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET medbook = %s WHERE user_id = %s", (Json(mb), uid))
    return web.json_response({"ok": True})

async def handle_admin_medbook_ref_add(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    if rtype not in REF_TYPE_PERM:
        return web.json_response({"error": "invalid_type"}, status=400)
    perm_err = require_perm(admin, REF_TYPE_PERM[rtype])
    if perm_err:
        return perm_err
    name = (body.get("name") or "").strip()
    months = max(1, min(120, int(body.get("validity_months") or 12)))
    required = bool(body.get("required"))
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COALESCE(MAX(sort), 0) FROM {table}")
            sort = (cur.fetchone()[0] or 0) + 1
            cur.execute(f"INSERT INTO {table} (name, required, validity_months, sort) VALUES (%s,%s,%s,%s)",
                        (name, required, months, sort))
    return web.json_response({"ok": True})

async def handle_admin_medbook_ref_update(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    rid = int(body.get("id") or 0)
    if rtype not in REF_TYPE_PERM or not rid:
        return web.json_response({"error": "invalid"}, status=400)
    perm_err = require_perm(admin, REF_TYPE_PERM[rtype])
    if perm_err:
        return perm_err
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    with get_conn() as conn:
        with conn.cursor() as cur:
            if "name" in body:
                cur.execute(f"UPDATE {table} SET name = %s WHERE id = %s", (body["name"], rid))
            if "validity_months" in body:
                v = max(1, min(120, int(body["validity_months"] or 12)))
                cur.execute(f"UPDATE {table} SET validity_months = %s WHERE id = %s", (v, rid))
            if "required" in body:
                cur.execute(f"UPDATE {table} SET required = %s WHERE id = %s", (bool(body["required"]), rid))
    return web.json_response({"ok": True})

async def handle_admin_medbook_ref_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    rtype = body.get("type")
    rid = int(body.get("id") or 0)
    if rtype not in REF_TYPE_PERM or not rid:
        return web.json_response({"error": "invalid"}, status=400)
    perm_err = require_perm(admin, REF_TYPE_PERM[rtype])
    if perm_err:
        return perm_err
    table = {"doctor": "medbook_doctors", "test": "medbook_tests", "vaccine": "medbook_vaccines"}[rtype]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {table} WHERE id = %s", (rid,))
    return web.json_response({"ok": True})

# ============= API: NEWS =============
def _sync_news_list():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM news ORDER BY created_at DESC, id DESC")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_news_list(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    news = await _run(_sync_news_list)
    return web.json_response({"news": news})

async def handle_admin_news_add(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    title = (body.get("title") or "").strip()
    text = (body.get("body") or "").strip()
    if not title or not text:
        return web.json_response({"error": "invalid"}, status=400)
    level = body.get("level") or "normal"
    intent = body.get("intent") or "suggest"
    publish_at = body.get("publish_at")

    is_super = admin["is_super_admin"]
    is_hr = admin["position"] == "HR"
    can_publish = is_super or is_hr

    if not can_publish:
        status = "pending"
        proposed_by = admin.get("full_name") or admin.get("login")
    else:
        if intent == "publish":
            status = "published"
        elif intent == "schedule" and publish_at:
            status = "scheduled"
        else:
            status = "pending"
        proposed_by = None

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                INSERT INTO news (title, body, level, status, publish_at, proposed_by)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING *
            """, (title, text, level, status, publish_at, proposed_by))
            news_row = dict(cur.fetchone())
    return web.json_response({"ok": True, "status": status, "news": news_row})

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
    nid = int(body.get("id") or 0)
    title = body.get("title")
    with get_conn() as conn:
        with conn.cursor() as cur:
            if title:
                cur.execute("UPDATE news SET title = %s WHERE id = %s", (title.strip(), nid))
    return web.json_response({"ok": True})

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
    nid = int(body.get("id") or 0)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news WHERE id = %s", (nid,))
    return web.json_response({"ok": True})

def _check_can_publish(admin):
    return admin["is_super_admin"] or admin["position"] == "HR"

async def handle_admin_news_approve(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not _check_can_publish(admin):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    nid = int(body.get("id") or 0)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE news SET status = 'published', approved_by = %s WHERE id = %s",
                        (admin.get("full_name"), nid))
    return web.json_response({"ok": True})

async def handle_admin_news_reject(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    if not _check_can_publish(admin):
        return web.json_response({"error": "forbidden"}, status=403)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    nid = int(body.get("id") or 0)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news WHERE id = %s AND status = 'pending'", (nid,))
    return web.json_response({"ok": True})

# ============= API: STANDARDS =============
def _sync_standards():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM standards ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_standards(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    return web.json_response({"standards": await _run(_sync_standards)})

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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO standards (title, category, description, url) VALUES (%s,%s,%s,%s)",
                        (body.get("title") or "", body.get("category") or "",
                         body.get("description") or "", body.get("url") or ""))
    return web.json_response({"ok": True})

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
    field = body.get("field")
    if field not in ("title", "category", "description", "url"):
        return web.json_response({"error": "invalid"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE standards SET {field} = %s WHERE id = %s",
                        (body.get("value") or "", int(body.get("id") or 0)))
    return web.json_response({"ok": True})

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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM standards WHERE id = %s", (int(body.get("id") or 0),))
    return web.json_response({"ok": True})

# ============= API: FAQ / POSITIONS / QUESTIONS =============
def _sync_faq_list():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM faq ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_faq(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    return web.json_response({"faq": await _run(_sync_faq_list)})

async def handle_admin_faq_add(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s,%s,%s)",
                        (body.get("question") or "", body.get("answer") or "", ""))
    return web.json_response({"ok": True})

async def handle_admin_faq_update(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    field = body.get("field")
    if field not in ("question", "answer"):
        return web.json_response({"error": "invalid"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE faq SET {field} = %s WHERE id = %s",
                        (body.get("value") or "", int(body.get("id") or 0)))
    return web.json_response({"ok": True})

async def handle_admin_faq_delete(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM faq WHERE id = %s", (int(body.get("id") or 0),))
    return web.json_response({"ok": True})

def _sync_positions():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM positions ORDER BY is_archived, sort, name")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_positions(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    return web.json_response({"positions": await _run(_sync_positions)})

async def handle_admin_position_add(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    name = (body.get("name") or "").strip()
    if not name:
        return web.json_response({"error": "invalid"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(sort), 0) FROM positions")
            sort = (cur.fetchone()[0] or 0) + 1
            try:
                cur.execute("INSERT INTO positions (name, sort) VALUES (%s,%s)", (name, sort))
            except Exception:
                return web.json_response({"ok": False})
    return web.json_response({"ok": True})

async def handle_admin_position_archive(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE positions SET is_archived = TRUE WHERE id = %s", (int(body.get("id") or 0),))
    return web.json_response({"ok": True})

def _sync_questions():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("""
                SELECT q.id, q.user_id, q.text, q.replied, q.created_at, u.full_name
                FROM questions q LEFT JOIN users u ON q.user_id = u.user_id
                ORDER BY q.created_at DESC LIMIT 200
            """)
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_questions(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    return web.json_response({"questions": await _run(_sync_questions)})

async def handle_admin_question_reply(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    qid = int(body.get("id") or 0)
    text = (body.get("text") or "").strip()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE questions SET replied = TRUE, reply_text = %s, replied_at = NOW(),
                           replied_by = %s WHERE id = %s""", (text, admin["user_id"], qid))
    return web.json_response({"ok": True})

# ============= API: AUDIT / REPORTS / PASSWORD =============
def _sync_audit():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM admin_audit ORDER BY created_at DESC LIMIT 300")
            return [dict(r) for r in cur.fetchall()]

async def handle_admin_audit(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    return web.json_response({"audit": await _run(_sync_audit)})

async def handle_admin_reports(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    stats = await _run(_sync_dashboard_stats)
    return web.json_response({"report": stats})

async def handle_admin_change_password(request):
    admin, err = await get_admin_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    old = body.get("old_password") or ""
    new = body.get("new_password") or ""
    if not verify_password(old, admin.get("password_hash") or ""):
        return web.json_response({"error": "wrong_password"}, status=401)
    if len(new) < 6:
        return web.json_response({"error": "invalid"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE user_id = %s",
                        (hash_password(new), admin["user_id"]))
    return web.json_response({"ok": True})

# ============= API: BOOTSTRAP (для сотрудника) =============
def _sync_bootstrap(user_id):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("UPDATE users SET last_seen_at = NOW() WHERE user_id = %s", (user_id,))
            cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            user = dict(cur.fetchone())
            cur.execute("SELECT * FROM news WHERE status = 'published' ORDER BY created_at DESC LIMIT 50")
            news_rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM standards ORDER BY id")
            std_rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM faq ORDER BY id")
            faq_rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT * FROM restaurants WHERE key != 'office' ORDER BY sort, name")
            rest_rows = [dict(r) for r in cur.fetchall()]
    user.pop("password_hash", None)
    return user, news_rows, std_rows, faq_rows, rest_rows

async def handle_bootstrap(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    u, news_rows, std_rows, faq_rows, rest_rows = await _run(_sync_bootstrap, user["user_id"])
    restaurant_name = ""
    restaurant_key = u.get("restaurant_key") or ""
    for r in rest_rows:
        if r["key"] == restaurant_key:
            restaurant_name = r["name"]
            break

    profile = {
        "full_name": u.get("full_name") or "",
        "first_name": (u.get("full_name") or "").split()[0] if u.get("full_name") else "",
        "phone": u.get("phone") or "",
        "birth_date": u.get("birth_date") or "",
        "position": u.get("position") or "—",
        "restaurant": restaurant_name or "—",
        "restaurant_key": restaurant_key,
        "is_certified": bool(u.get("is_certified")),
        "is_admin": bool(u.get("is_admin")),
    }
    return web.json_response({
        "profile": profile,
        "news": news_rows,
        "standards": std_rows,
        "faq": faq_rows,
        "restaurants": rest_rows,
    })

# ============= API: QUESTIONS (для сотрудника) =============
async def handle_questions_staff(request):
    user, err = await get_auth_user(request)
    if err:
        return denied(err)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400)
    text = (body.get("question") or "").strip()
    if not text or len(text) > 1000:
        return web.json_response({"error": "invalid"}, status=400)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO questions (user_id, text) VALUES (%s,%s)", (user["user_id"], text))
    return web.json_response({"ok": True})

# ============= STATIC =============
_INDEX_CACHE = {"data": None, "mtime": 0.0}
_ADMIN_CACHE = {"data": None, "mtime": 0.0}

def _serve_file(name, cache):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", name)
    if not os.path.exists(p):
        return None
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
    if not data:
        return web.Response(text="frontend/index.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

async def handle_admin_page(request):
    data = _serve_file("admin.html", _ADMIN_CACHE)
    if not data:
        return web.Response(text="frontend/admin.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

async def handle_favicon(request):
    return web.Response(status=204)

async def handle_health(request):
    return web.Response(text="OK")

# ============= MIDDLEWARES =============
@web.middleware
async def error_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        logging.error("Unhandled %s %s: %s: %s", request.method, request.path, type(e).__name__, str(e)[:200])
        return web.json_response({"error": "internal"}, status=500)

_GZIP_TYPES = ("application/json", "text/plain", "text/html", "text/css",
               "application/javascript")

@web.middleware
async def gzip_middleware(request, handler):
    response = await handler(request)
    body = getattr(response, "body", None)
    if (body is not None and len(body) > 500
            and "gzip" in request.headers.get("Accept-Encoding", "")
            and not response.headers.get("Content-Encoding")
            and response.content_type in _GZIP_TYPES):
        compressed = gzip.compress(body, compresslevel=6)
        if len(compressed) < len(body):
            response.body = compressed
            response.headers["Content-Encoding"] = "gzip"
            if "Content-Length" in response.headers:
                del response.headers["Content-Length"]
            response.headers["Vary"] = "Accept-Encoding"
    return response

app = web.Application(middlewares=[error_middleware, gzip_middleware], client_max_size=10 * 1024 * 1024)

# ============= ROUTES =============
app.router.add_get("/", handle_index)
app.router.add_get("/admin", handle_admin_page)
app.router.add_get("/admin/", handle_admin_page)
app.router.add_get("/favicon.ico", handle_favicon)
app.router.add_get("/api/health", handle_health)

# AUTH
app.router.add_post("/api/auth/login", handle_auth_login_staff)
app.router.add_post("/api/auth/logout", handle_auth_logout)

# STAFF API
app.router.add_post("/api/bootstrap", handle_bootstrap)
app.router.add_post("/api/questions", handle_questions_staff)

# ADMIN AUTH
app.router.add_post("/api/admin/login", handle_auth_login)
app.router.add_post("/api/admin/me", handle_admin_me)
app.router.add_post("/api/admin/dashboard", handle_admin_dashboard)

# USERS
app.router.add_post("/api/admin/users", handle_admin_users)
app.router.add_post("/api/admin/user/get", handle_admin_user_get)
app.router.add_post("/api/admin/user/create", handle_admin_user_create)
app.router.add_post("/api/admin/user/update", handle_admin_user_update)
app.router.add_post("/api/admin/user/delete", handle_admin_user_delete)
app.router.add_post("/api/admin/user/fire", handle_admin_user_fire)
app.router.add_post("/api/admin/user/restore", handle_admin_user_restore)

# ADMINS / PERMISSIONS
app.router.add_post("/api/admin/admins", handle_admin_admins)
app.router.add_post("/api/admin/set-permissions", handle_admin_set_permissions)

# RESTAURANTS
app.router.add_post("/api/admin/restaurants", handle_admin_restaurants)
app.router.add_post("/api/admin/restaurant/update", handle_admin_restaurant_update)
app.router.add_post("/api/admin/restaurant/tu", handle_admin_restaurant_tu)
app.router.add_post("/api/admin/restaurant/status", handle_admin_restaurant_status)

# MEDBOOKS
app.router.add_post("/api/admin/medbooks", handle_admin_medbooks)
app.router.add_post("/api/admin/medbook/get", handle_admin_medbook_get)
app.router.add_post("/api/admin/medbook/save", handle_admin_medbook_save)
app.router.add_post("/api/admin/medbook/reference/add", handle_admin_medbook_ref_add)
app.router.add_post("/api/admin/medbook/reference/update", handle_admin_medbook_ref_update)
app.router.add_post("/api/admin/medbook/reference/delete", handle_admin_medbook_ref_delete)

# NEWS
app.router.add_post("/api/admin/news", handle_admin_news_list)
app.router.add_post("/api/admin/news/add", handle_admin_news_add)
app.router.add_post("/api/admin/news/update", handle_admin_news_update)
app.router.add_post("/api/admin/news/delete", handle_admin_news_delete)
app.router.add_post("/api/admin/news/approve", handle_admin_news_approve)
app.router.add_post("/api/admin/news/reject", handle_admin_news_reject)

# STANDARDS
app.router.add_post("/api/admin/standards", handle_admin_standards)
app.router.add_post("/api/admin/standard/add", handle_admin_standard_add)
app.router.add_post("/api/admin/standard/update", handle_admin_standard_update)
app.router.add_post("/api/admin/standard/delete", handle_admin_standard_delete)

# FAQ / POSITIONS / QUESTIONS
app.router.add_post("/api/admin/faq", handle_admin_faq)
app.router.add_post("/api/admin/faq/add", handle_admin_faq_add)
app.router.add_post("/api/admin/faq/update", handle_admin_faq_update)
app.router.add_post("/api/admin/faq/delete", handle_admin_faq_delete)
app.router.add_post("/api/admin/positions", handle_admin_positions)
app.router.add_post("/api/admin/position/add", handle_admin_position_add)
app.router.add_post("/api/admin/position/archive", handle_admin_position_archive)
app.router.add_post("/api/admin/questions", handle_admin_questions)
app.router.add_post("/api/admin/question/reply", handle_admin_question_reply)

# AUDIT / REPORTS / PASSWORD
app.router.add_post("/api/admin/audit", handle_admin_audit)
app.router.add_post("/api/admin/reports", handle_admin_reports)
app.router.add_post("/api/admin/change-password", handle_admin_change_password)

# ============= MAIN =============
async def main():
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"✅ Server on port {port}")
    logging.info(f"👤 Admin: {ADMIN_LOGIN}")
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        if _pool:
            _pool.closeall()

if __name__ == "__main__":
    asyncio.run(main())
