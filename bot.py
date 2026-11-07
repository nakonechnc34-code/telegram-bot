import os
import io
import csv
import html
import asyncio
import logging
import json
import gzip
import re
import time
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from aiohttp import web
import psycopg2
from psycopg2.pool import SimpleConnectionPool

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
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Wokker2026!")
APP_URL = os.getenv("MINI_APP_URL", "https://ВАШ-ДОМЕН.amvera.io").rstrip("/")

LOGIN_RE = re.compile(r"^[A-Za-z]{3}\d{2}$")
NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z\- ]{2,100}$")
URL_RE = re.compile(r"^https?://[^\s]+$")

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

def gen_user_id() -> int:
    return secrets.randbelow(9_000_000_000) + 1_000_000_000

# ============= ПУЛ =============
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

async def _run(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)

_bg_tasks = set()

def spawn(coro, name=None):
    task = asyncio.create_task(coro, name=name)
    def _done(t):
        _bg_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logging.error("BG task %s failed", t.get_name(), exc_info=exc)
    _bg_tasks.add(task)
    task.add_done_callback(_done)
    return task

# ============= SEED =============
RESTAURANTS_SEED = [
    {"key": "mega_belaya_dacha", "name": "Мега Белая Дача", "address": "Московская область, Котельники, 1-й Покровский проезд, 5, ТРЦ Мега, этаж 1", "hours": "Пн–чт: 10:00–22:00\nПт–вс: 10:00–23:00", "lat": 55.6584, "lon": 37.8895, "org": "vokker/128833821207", "phone": "+7 (915) 479-09-41"},
    {"key": "belyaevo", "name": "Беляево", "address": "Москва, ул. Миклухо-Маклая, 32А, ТЦ «Капитолий», этаж 2", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6437, "lon": 37.5302, "org": "vokker/13122472923", "phone": "+7 (985) 857-06-69"},
    {"key": "vernadka", "name": "Вернадка", "address": "Москва, проспект Вернадского, 6, ТЦ «Капитолий Вернадского», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6845, "lon": 37.4948, "org": "vokker/91626648547", "phone": ""},
    {"key": "erevan_plaza", "name": "Ереван Плаза", "address": "Москва, ул. Большая Тульская, д. 13, ТРЦ «Ереван Плаза», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.7023, "lon": 37.6220, "org": "vokker/102264079721", "phone": "+7 (906) 094-61-46"},
    {"key": "kuzminki_mall", "name": "Кузьминки Молл", "address": "Москва, ул. Зеленодольская, д. 42, ТРЦ «Кузьминки Молл», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6989, "lon": 37.7772, "org": "vokker/24262320480", "phone": "+7 (968) 537-09-94"},
    {"key": "mega_teplyy_stan", "name": "Мега Тёплый стан", "address": "Москва, Калужское шоссе, 21-й километр, с1, ТЦ «Мега Тёплый Стан»", "hours": "Пн–вс: 10:00–22:00", "lat": 55.5795, "lon": 37.4865, "org": "vokker/1485953945", "phone": "+7 (985) 857-05-88"},
    {"key": "mega_himki", "name": "Мега Химки", "address": "Московская обл., г. Химки, микрорайон ИКЕА, к1, ТЦ «Мега Химки», этаж 1", "hours": "Пн–чт, вс: 10:00–23:00\nПт–сб: 10:00–24:00", "lat": 55.8948, "lon": 37.3973, "org": "vokker/132066311330", "phone": "+7 (985) 857-08-22"},
    {"key": "metropolis", "name": "Метрополис", "address": "Москва, Ленинградское ш., д. 16А, стр. 4, ТРЦ «Метрополис», этаж 3", "hours": "Пн–вс: 10:00–23:00", "lat": 55.8214, "lon": 37.4977, "org": "vokker/1298559872", "phone": "+7 (985) 857-07-14"},
    {"key": "moskva_city", "name": "Москва-Сити", "address": "Москва, 1-й Красногвардейский пр., д. 22, стр. 1 (Neva Towers), этаж 2, фуд-корт", "hours": "Пн–вс: 10:00–22:00", "lat": 55.7497, "lon": 37.5392, "org": "vokker/25826174821", "phone": "+7 (915) 479-91-70"},
    {"key": "okeaniya", "name": "Океания", "address": "Москва, Кутузовский пр., д. 57, ТРЦ «Океания», этаж 3", "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00", "lat": 55.7401, "lon": 37.4940, "org": "vokker/9739651477", "phone": "+7 (915) 478-64-01"},
    {"key": "polkovaya", "name": "Полковая", "address": "Москва, ул. Полковая, д. 3, стр. 5, БЦ «Шереметьевский», этаж 1", "hours": "Пн–вс: 10:00–22:00", "lat": 55.8046, "lon": 37.5917, "org": "vokker/84984433800", "phone": "+7 (915) 270-25-57"},
    {"key": "cdm", "name": "ЦДМ", "address": "Москва, Театральный пр., д. 5, стр. 1, «ЦДМ на Лубянке», этаж 6", "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00", "lat": 55.7597, "lon": 37.6243, "org": "vokker/31463245515", "phone": "+7 (968) 537-09-89"},
    {"key": "tsvetnoy", "name": "Цветной", "address": "Москва, Цветной бульвар, д. 15, стр. 1, ТРЦ «Цветной», этаж 5", "hours": "Пн–сб: 10:00–22:00\nВс: 11:00–22:00", "lat": 55.7694, "lon": 37.6183, "org": "vokker/110848206544", "phone": "+7 (985) 193-38-44"},
    {"key": "shchelkovskaya", "name": "Щёлковская", "address": "Москва, Щёлковское шоссе, 75, ТРЦ «Щёлковский», этаж 5", "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00", "lat": 55.8101, "lon": 37.7923, "org": "vokker/25844145312", "phone": "+7 (999) 665-26-54"},
    {"key": "shuka", "name": "Щука", "address": "Москва, ул. Щукинская, д. 42, ТРК «Щука», этаж 4", "hours": "Пн–вс: 10:00–22:00", "lat": 55.8007, "lon": 37.4649, "org": "vokker/1357579873", "phone": "+7 (985) 857-08-40"},
    {"key": "office", "name": "ОФИС", "address": "Центральный офис", "hours": "Пн–пт: 09:00–18:00", "lat": None, "lon": None, "org": "", "phone": ""},
]

STANDARDS_SEED = [
    {"title": "Правила открытия смены", "category": "Чек-листы", "description": "Что проверить перед открытием: оборудование, чистота, касса.", "url": ""},
    {"title": "Стандарт работы вокера", "category": "Технология", "description": "Пошаговый стандарт приготовления блюд на воке.", "url": ""},
    {"title": "Обработка жалоб гостей", "category": "Сервис", "description": "Как реагировать на претензии и когда звать управляющего.", "url": ""},
]

FAQ_SEED = [
    {"question": "Как посмотреть график смен?", "answer": "График вывешивается на информационной доске в ресторане и уточняется у управляющего сменой.", "category": "Работа"},
    {"question": "Куда сообщать о поломке оборудования?", "answer": "Напиши управляющему сменой.", "category": "Работа"},
    {"question": "Как поменять пароль?", "answer": "Обратись к администратору — он сменит пароль в админ-панели.", "category": "Бот"},
]

POSITIONS_SEED = [
    "Повар холодного цеха",
    "Повар горячего цеха",
    "Управляющий сменой",
    "Территориальный управляющий",
    "HR",
]

# ============= ИНИЦИАЛИЗАЦИЯ БД =============
init_pool()

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name TEXT, phone TEXT, birth_date TEXT,
                position TEXT, restaurant TEXT,
                welcomed BOOLEAN DEFAULT TRUE,
                is_blocked BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS position TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS restaurant TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_certified BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_medbook_valid BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS login TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users (LOWER(login)) WHERE login IS NOT NULL")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL, body TEXT NOT NULL,
                important BOOLEAN DEFAULT FALSE,
                level TEXT DEFAULT 'normal',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS level TEXT DEFAULT 'normal'")
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS publish_at TIMESTAMPTZ DEFAULT NOW()")
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS published BOOLEAN DEFAULT TRUE")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS restaurants (
                key TEXT PRIMARY KEY, name TEXT NOT NULL,
                address TEXT, hours TEXT, lat REAL, lon REAL,
                org TEXT, phone TEXT DEFAULT '',
                force_status TEXT, sort INT DEFAULT 100
            )
        """)
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS force_status TEXT")
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS sort INT DEFAULT 100")
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS territory_manager_id BIGINT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS standards (
                id SERIAL PRIMARY KEY, title TEXT NOT NULL,
                category TEXT DEFAULT '', description TEXT DEFAULT '', url TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS faq (
                id SERIAL PRIMARY KEY, question TEXT NOT NULL,
                answer TEXT NOT NULL, category TEXT DEFAULT ''
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
                admin_id BIGINT, action TEXT,
                target_type TEXT, target_id TEXT, details TEXT,
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_questions_open ON questions (created_at DESC) WHERE replied = FALSE")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                token TEXT PRIMARY KEY,
                user_id BIGINT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                last_used_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON admin_audit (created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_created ON news (created_at DESC)")

        # Seed news
        cur.execute("SELECT COUNT(*) FROM news")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s)",
                        ("Открытие новой точки", "Скоро открываем новый ресторан!", True, "urgent"))
            cur.execute("INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s)",
                        ("Обновление меню", "Появились новые позиции в меню.", False, "normal"))

        # Seed restaurants
        cur.execute("SELECT COUNT(*) FROM restaurants")
        if cur.fetchone()[0] == 0:
            for i, r in enumerate(RESTAURANTS_SEED):
                sort = 999 if r["key"] == "office" else i
                cur.execute(
                    "INSERT INTO restaurants (key, name, address, hours, lat, lon, org, phone, sort) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (r["key"], r["name"], r["address"], r["hours"], r["lat"], r["lon"], r["org"], r["phone"], sort))

        # Seed standards / faq / positions
        cur.execute("SELECT COUNT(*) FROM standards")
        if cur.fetchone()[0] == 0:
            for s in STANDARDS_SEED:
                cur.execute("INSERT INTO standards (title, category, description, url) VALUES (%s, %s, %s, %s)",
                            (s["title"], s["category"], s["description"], s["url"] or ""))
        cur.execute("SELECT COUNT(*) FROM faq")
        if cur.fetchone()[0] == 0:
            for f in FAQ_SEED:
                cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s, %s, %s)",
                            (f["question"], f["answer"], f["category"]))
        cur.execute("SELECT COUNT(*) FROM positions")
        if cur.fetchone()[0] == 0:
            for i, name in enumerate(POSITIONS_SEED):
                cur.execute("INSERT INTO positions (name, sort) VALUES (%s, %s)", (name, i))

        # Миграция: переименование должностей
        cur.execute("UPDATE users SET position = 'Повар холодного цеха' WHERE position = 'Холодный Цех'")
        cur.execute("UPDATE users SET position = 'Повар горячего цеха' WHERE position = 'Жарщик'")
        cur.execute("UPDATE positions SET name = 'Повар холодного цеха' WHERE name = 'Холодный Цех'")
        cur.execute("UPDATE positions SET name = 'Повар горячего цеха' WHERE name = 'Жарщик'")
        cur.execute("SELECT COUNT(*) FROM positions WHERE LOWER(name) = 'hr'")
        if cur.fetchone()[0] == 0:
            cur.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM positions")
            next_sort = cur.fetchone()[0]
            cur.execute("INSERT INTO positions (name, sort) VALUES ('HR', %s)", (next_sort,))

        # Первичный админ
        cur.execute("SELECT COUNT(*) FROM users WHERE is_admin = TRUE")
        if cur.fetchone()[0] == 0:
            uid = gen_user_id()
            pw_hash = hash_password(ADMIN_PASSWORD)
            cur.execute("""
                INSERT INTO users (user_id, login, password_hash, is_admin,
                                   full_name, position, welcomed)
                VALUES (%s, %s, %s, TRUE, 'Администратор', 'Администратор', TRUE)
            """, (uid, ADMIN_LOGIN, pw_hash))
            print(f"✅ Создан администратор: логин={ADMIN_LOGIN} (пароль из ADMIN_PASSWORD)")
            print(f"   user_id = {uid}")

print("✅ База данных подключена")

# ============= УТИЛИТЫ =============
def _moscow_now() -> datetime:
    if MOSCOW_TZ:
        return datetime.now(MOSCOW_TZ)
    return datetime.now(timezone(timedelta(hours=3)))

DAY_MAP = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
DAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

REST_CACHE = {"data": None, "ts": 0.0}
REST_CACHE_TTL = 60

def invalidate_rest_cache():
    REST_CACHE["data"] = None
    REST_CACHE["ts"] = 0.0

def validate_hours_schedule(text):
    if not text:
        return False
    ranges = re.findall(r"(\d{1,2}):(\d{2})\s*[–\-—]\s*(\d{1,2}):(\d{2})", text)
    if not ranges:
        return False
    for h1, m1, h2, m2 in ranges:
        h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
        if not (0 <= h1 <= 23 and 0 <= m1 <= 59):
            return False
        if not (0 <= h2 <= 24 and 0 <= m2 <= 59):
            return False
    return True

def parse_hours(hours_text):
    schedule = {}
    if not hours_text:
        return schedule
    for line in hours_text.split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        days_part, _, times_part = line.partition(":")
        m = re.search(r"(\d{1,2}):(\d{2})\s*[–\-—]\s*(\d{1,2}):(\d{2})", times_part)
        if not m:
            continue
        open_m = int(m.group(1)) * 60 + int(m.group(2))
        close_m = int(m.group(3)) * 60 + int(m.group(4))
        if close_m <= open_m:
            close_m += 1440
        days = set()
        for chunk in days_part.replace(";", ",").split(","):
            chunk = chunk.strip().lower()
            if not chunk:
                continue
            day_tokens = re.findall(r"(пн|вт|ср|чт|пт|сб|вс)", chunk)
            if len(day_tokens) >= 2:
                d1 = DAY_MAP.get(day_tokens[0])
                d2 = DAY_MAP.get(day_tokens[-1])
                if d1 is not None and d2 is not None:
                    if d1 <= d2:
                        days.update(range(d1, d2 + 1))
                    else:
                        days.update(list(range(d1, 7)) + list(range(0, d2 + 1)))
            elif len(day_tokens) == 1:
                d = DAY_MAP.get(day_tokens[0])
                if d is not None:
                    days.add(d)
        for d in days:
            schedule[d] = (open_m, close_m)
    return schedule

def _fmt_minutes(total_min):
    total_min = total_min % 1440
    return f"{total_min // 60:02d}:{total_min % 60:02d}"

def restaurant_status(hours_text):
    schedule = parse_hours(hours_text)
    now = _moscow_now()
    cur = now.hour * 60 + now.minute
    dow = now.weekday()
    today = schedule.get(dow)
    if today:
        o, c = today
        if o <= cur < c:
            return "open", f"Открыто до {_fmt_minutes(c)}"
    yesterday = (dow - 1) % 7
    yd = schedule.get(yesterday)
    if yd:
        yo, yc = yd
        if yc > 1440 and cur < (yc - 1440):
            return "open", f"Открыто до {_fmt_minutes(yc)}"
    for add in range(0, 8):
        d = (dow + add) % 7
        s = schedule.get(d)
        if not s:
            continue
        o, c = s
        if add == 0 and o > cur:
            return "closed", f"Закрыто · откроется в {_fmt_minutes(o)}"
        if add > 0:
            return "closed", f"Закрыто · откроется в {DAY_NAMES[d]} {_fmt_minutes(o)}"
    return "closed", "Закрыто"

def restaurant_status_for(r):
    fs = r.get("force_status")
    if fs == "open":
        return "open", "Открыто (администратором)"
    if fs == "closed":
        return "closed", "Закрыто (администратором)"
    return restaurant_status(r.get("hours") or "")

def slugify(name):
    translit = {"а":"a","б":"b","в":"v","г":"g","д":"d","е":"e","ё":"e","ж":"zh","з":"z","и":"i","й":"y","к":"k","л":"l","м":"m","н":"n","о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"h","ц":"ts","ч":"ch","ш":"sh","щ":"sch","ъ":"","ы":"y","ь":"","э":"e","ю":"yu","я":"ya"}
    s = name.lower()
    out = []
    for ch in s:
        if ch in translit:
            out.append(translit[ch])
        elif ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("_")
    result = re.sub(r"_+", "_", "".join(out)).strip("_")
    return result or "rest"

def safe_int(s, default=0):
    try:
        return int(s)
    except (ValueError, TypeError):
        return default

def json_dumps(data):
    return json.dumps(data, ensure_ascii=False)

def row_user_flags(row):
    if not row:
        return False, False, False
    is_blocked = bool(row[6]) if len(row) > 6 else False
    is_certified = bool(row[7]) if len(row) > 7 else False
    is_medbook_valid = bool(row[8]) if len(row) > 8 else False
    return is_blocked, is_certified, is_medbook_valid

# ============= DB SYNC =============
def _sync_db_restaurants_all():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, name, address, hours, lat, lon, org, phone, force_status, sort, "
                        "territory_manager_id FROM restaurants ORDER BY sort, name")
            cols = ["key","name","address","hours","lat","lon","org","phone","force_status","sort","territory_manager_id"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def _sync_db_restaurants_for_app():
    return [r for r in _sync_db_restaurants_all() if r["key"] != "office"]

def _sync_db_restaurant(key):
    for r in _sync_db_restaurants_all():
        if r["key"] == key:
            return r
    return None

def _sync_db_restaurant_update(key, field, value):
    sqls = {
        "name": "UPDATE restaurants SET name = %s WHERE key = %s",
        "address": "UPDATE restaurants SET address = %s WHERE key = %s",
        "phone": "UPDATE restaurants SET phone = %s WHERE key = %s",
        "hours": "UPDATE restaurants SET hours = %s WHERE key = %s",
        "org": "UPDATE restaurants SET org = %s WHERE key = %s",
    }
    sql = sqls.get(field)
    if not sql:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (value, key))
            return cur.rowcount > 0

def _sync_db_restaurant_set_coords(key, lat, lon):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE restaurants SET lat = %s, lon = %s WHERE key = %s", (lat, lon, key))
            return cur.rowcount > 0

def _sync_db_restaurant_set_status(key, fs):
    if fs not in (None, "open", "closed"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE restaurants SET force_status = %s WHERE key = %s", (fs, key))
            return cur.rowcount > 0

def _sync_db_restaurant_set_tu(key, tu_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE restaurants SET territory_manager_id = %s WHERE key = %s", (tu_id, key))
            return cur.rowcount > 0

def _sync_db_restaurant_add(key, name, address, hours, phone, org):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM restaurants WHERE key = %s", (key,))
            if cur.fetchone()[0] > 0:
                return False
            cur.execute("SELECT COALESCE(MAX(sort), 0) FROM restaurants WHERE key != 'office'")
            next_sort = cur.fetchone()[0] + 1
            cur.execute("INSERT INTO restaurants (key, name, address, hours, phone, org, sort) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (key, name, address, hours, phone, org, next_sort))
            return True

def _sync_db_restaurant_delete(key):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE restaurant = %s", (key,))
            if cur.fetchone()[0] > 0:
                return False, "users_attached"
            cur.execute("DELETE FROM restaurants WHERE key = %s", (key,))
            return cur.rowcount > 0, None

def _sync_db_get(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT full_name, phone, birth_date, position, restaurant, welcomed, "
                        "is_blocked, is_certified, is_medbook_valid, login, is_admin "
                        "FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()

def _sync_db_get_by_login(login):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT user_id, full_name, password_hash, is_admin, is_blocked
                           FROM users WHERE LOWER(login) = LOWER(%s) AND password_hash IS NOT NULL""", (login,))
            row = cur.fetchone()
            if not row:
                return None
            return {"user_id": row[0], "full_name": row[1] or "",
                    "password_hash": row[2], "is_admin": bool(row[3]), "is_blocked": bool(row[4])}

def _sync_db_login_exists(login, exclude_user_id=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if exclude_user_id:
                cur.execute("SELECT 1 FROM users WHERE LOWER(login) = LOWER(%s) AND user_id != %s", (login, exclude_user_id))
            else:
                cur.execute("SELECT 1 FROM users WHERE LOWER(login) = LOWER(%s)", (login,))
            return cur.fetchone() is not None

def _sync_db_create_user(login, password, full_name, phone, birth_date, position, restaurant,
                         is_certified, is_medbook_valid, is_admin):
    pw_hash = hash_password(password)
    for _ in range(20):
        uid = gen_user_id()
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO users (user_id, login, password_hash, is_admin,
                                           full_name, phone, birth_date, position, restaurant,
                                           is_certified, is_medbook_valid, welcomed)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
                        RETURNING user_id
                    """, (uid, login, pw_hash, is_admin, full_name, phone, birth_date,
                          position, restaurant, is_certified, is_medbook_valid))
                    return cur.fetchone()[0]
        except psycopg2.errors.UniqueViolation:
            continue
    raise RuntimeError("Cannot allocate unique user_id")

def _sync_db_update_user(user_id, field, value):
    sqls = {
        "full_name": "UPDATE users SET full_name = %s WHERE user_id = %s",
        "phone": "UPDATE users SET phone = %s WHERE user_id = %s",
        "birth_date": "UPDATE users SET birth_date = %s WHERE user_id = %s",
        "position": "UPDATE users SET position = %s WHERE user_id = %s",
        "restaurant": "UPDATE users SET restaurant = %s WHERE user_id = %s",
        "is_certified": "UPDATE users SET is_certified = %s WHERE user_id = %s",
        "is_medbook_valid": "UPDATE users SET is_medbook_valid = %s WHERE user_id = %s",
        "is_blocked": "UPDATE users SET is_blocked = %s WHERE user_id = %s",
        "is_admin": "UPDATE users SET is_admin = %s WHERE user_id = %s",
        "login": "UPDATE users SET login = %s WHERE user_id = %s",
        "password_hash": "UPDATE users SET password_hash = %s WHERE user_id = %s",
    }
    sql = sqls.get(field)
    if not sql:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (value, user_id))
            return cur.rowcount > 0

def _sync_db_is_blocked(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT is_blocked FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return bool(row and row[0])

def _sync_db_list_active_users(restaurant_key=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if restaurant_key:
                cur.execute("SELECT user_id FROM users WHERE is_blocked = FALSE AND full_name IS NOT NULL AND restaurant = %s", (restaurant_key,))
            else:
                cur.execute("SELECT user_id FROM users WHERE is_blocked = FALSE AND full_name IS NOT NULL")
            return [r[0] for r in cur.fetchall()]

def _sync_db_delete_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            return cur.rowcount > 0

def _sync_db_list_tu_candidates():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT user_id, full_name FROM users
                           WHERE is_blocked = FALSE AND full_name IS NOT NULL
                             AND LOWER(COALESCE(position,'')) LIKE '%%территориальный управляющий%%'
                           ORDER BY full_name""")
            return cur.fetchall()

def _sync_db_admin_users_list(search=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            base = """SELECT u.user_id, u.full_name, u.phone, u.birth_date, u.position,
                      u.restaurant, r.name, u.welcomed, u.is_blocked,
                      u.is_certified, u.is_medbook_valid,
                      u.created_at, u.last_seen_at, u.login, u.is_admin
                      FROM users u LEFT JOIN restaurants r ON u.restaurant = r.key"""
            if search:
                q = f"%{search}%"
                cur.execute(base + """ WHERE LOWER(COALESCE(u.full_name,'')) LIKE %s
                                  OR LOWER(COALESCE(u.phone,'')) LIKE %s
                                  OR LOWER(COALESCE(u.login,'')) LIKE %s
                                  OR CAST(u.user_id AS TEXT) LIKE %s
                                  ORDER BY u.user_id DESC""", (q, q, q, f"%{search}%"))
            else:
                cur.execute(base + " ORDER BY u.user_id DESC")
            return cur.fetchall()

def _sync_get_report_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE login IS NOT NULL")
            total = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE AND login IS NOT NULL")
            active = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
            blocked = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE login IS NOT NULL AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '7 days')")
            inactive7 = cur.fetchone()[0] or 0
            cur.execute("""SELECT COUNT(*) FROM users
                           WHERE created_at AT TIME ZONE 'Europe/Moscow' >=
                                 (NOW() AT TIME ZONE 'Europe/Moscow') - INTERVAL '7 days'
                             AND login IS NOT NULL""")
            new7 = cur.fetchone()[0] or 0
    return {"total": total, "active": active, "blocked": blocked,
            "inactive7": inactive7, "new7": new7,
            "date": _moscow_now().strftime("%d.%m.%Y %H:%M")}

def _sync_db_dashboard_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) FROM users
                           WHERE (created_at AT TIME ZONE 'Europe/Moscow')::date
                                 = (NOW() AT TIME ZONE 'Europe/Moscow')::date
                             AND login IS NOT NULL""")
            new_today = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM questions WHERE replied = FALSE")
            questions_open = cur.fetchone()[0] or 0
            cur.execute("""SELECT COUNT(*) FROM users WHERE login IS NOT NULL AND is_blocked = FALSE
                           AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '7 days')""")
            inactive = cur.fetchone()[0] or 0
            cur.execute("""SELECT (created_at AT TIME ZONE 'Europe/Moscow')::date AS d, COUNT(*)
                           FROM users
                           WHERE (created_at AT TIME ZONE 'Europe/Moscow')::date
                                 >= (NOW() AT TIME ZONE 'Europe/Moscow')::date - 6
                             AND login IS NOT NULL
                           GROUP BY 1 ORDER BY 1""")
            chart_rows = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM news WHERE NOT published AND publish_at > NOW()")
            news_scheduled = cur.fetchone()[0] or 0
    chart = []
    today = _moscow_now().date()
    by_date = {r[0]: r[1] for r in chart_rows}
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        chart.append(by_date.get(d, 0))
    return {"new_today": new_today, "questions_open": questions_open,
            "inactive": inactive, "chart": chart, "news_scheduled": news_scheduled,
            "unfinished": 0}

def _sync_db_add_news(title, body, level, publish_at=None):
    if level not in ("urgent", "important", "normal"):
        level = "normal"
    with get_conn() as conn:
        with conn.cursor() as cur:
            if publish_at:
                cur.execute("INSERT INTO news (title, body, important, level, published, publish_at) "
                            "VALUES (%s,%s,%s,%s,FALSE,%s) RETURNING id",
                            (title, body, level != "normal", level, publish_at))
            else:
                cur.execute("INSERT INTO news (title, body, important, level, published, publish_at) "
                            "VALUES (%s,%s,%s,%s,TRUE,NOW()) RETURNING id",
                            (title, body, level != "normal", level))
            return cur.fetchone()[0]

def _sync_db_list_news():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body, important, level, created_at FROM news "
                        "WHERE published = TRUE ORDER BY created_at DESC, id DESC")
            return cur.fetchall()

def _sync_db_list_news_admin():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body, important, level, created_at, published, publish_at "
                        "FROM news ORDER BY created_at DESC, id DESC")
            return cur.fetchall()

def _sync_db_get_news_full(news_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body, important, level, created_at, published, publish_at "
                        "FROM news WHERE id = %s", (news_id,))
            return cur.fetchone()

def _sync_db_news_update_title(news_id, title):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE news SET title = %s WHERE id = %s", (title, news_id))
            return cur.rowcount > 0

def _sync_db_delete_news(news_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news WHERE id = %s", (news_id,))
            return cur.rowcount > 0

def _sync_db_publish_due():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE news SET published = TRUE "
                        "WHERE NOT published AND publish_at <= NOW() "
                        "RETURNING id, title")
            return cur.fetchall()

def _sync_db_list_standards():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, category, description, url FROM standards ORDER BY id")
            return cur.fetchall()

def _sync_db_add_standard(title, category, description, url=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO standards (title, category, description, url) VALUES (%s,%s,%s,%s)",
                        (title, category, description, url))

def _sync_db_delete_standard(sid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM standards WHERE id = %s", (sid,))
            return cur.rowcount > 0

def _sync_db_update_standard(sid, field, value):
    sqls = {
        "title": "UPDATE standards SET title = %s WHERE id = %s",
        "category": "UPDATE standards SET category = %s WHERE id = %s",
        "description": "UPDATE standards SET description = %s WHERE id = %s",
        "url": "UPDATE standards SET url = %s WHERE id = %s",
    }
    sql = sqls.get(field)
    if not sql:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (value, sid))
            return cur.rowcount > 0

def _sync_db_list_faq():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, question, answer, category FROM faq ORDER BY id")
            return cur.fetchall()

def _sync_db_add_faq(question, answer, category=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s,%s,%s)",
                        (question, answer, category))

def _sync_db_delete_faq(fid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM faq WHERE id = %s", (fid,))
            return cur.rowcount > 0

def _sync_db_update_faq(fid, field, value):
    sqls = {
        "question": "UPDATE faq SET question = %s WHERE id = %s",
        "answer": "UPDATE faq SET answer = %s WHERE id = %s",
    }
    sql = sqls.get(field)
    if not sql:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (value, fid))
            return cur.rowcount > 0

def _sync_db_positions_list(include_archived=False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if include_archived:
                cur.execute("SELECT id, name, sort, is_archived FROM positions ORDER BY is_archived, sort, name")
            else:
                cur.execute("SELECT id, name, sort, is_archived FROM positions WHERE is_archived = FALSE ORDER BY sort, name")
            return cur.fetchall()

def _sync_db_position_add(name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM positions WHERE LOWER(name) = LOWER(%s)", (name,))
            if cur.fetchone()[0] > 0:
                return False
            cur.execute("SELECT COALESCE(MAX(sort), 0) FROM positions")
            next_sort = cur.fetchone()[0] + 1
            cur.execute("INSERT INTO positions (name, sort) VALUES (%s,%s)", (name, next_sort))
            return True

def _sync_db_position_archive(pid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE positions SET is_archived = TRUE WHERE id = %s", (pid,))
            return cur.rowcount > 0

def _sync_db_audit(admin_id, action, target_type="", target_id="", details=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) "
                        "VALUES (%s,%s,%s,%s,%s)",
                        (admin_id, action, target_type, str(target_id) if target_id is not None else "", details))

def _sync_db_audit_list(limit=200):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, admin_id, action, target_type, target_id, details, created_at "
                        "FROM admin_audit ORDER BY created_at DESC LIMIT %s", (limit,))
            return cur.fetchall()

def _sync_db_question_add(user_id, text):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO questions (user_id, text) VALUES (%s,%s) RETURNING id", (user_id, text))
            return cur.fetchone()[0]

def _sync_db_questions_list(unanswered_only=True, limit=200):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if unanswered_only:
                cur.execute("""SELECT q.id, q.user_id, q.text, q.created_at, q.replied, u.full_name
                               FROM questions q LEFT JOIN users u ON q.user_id = u.user_id
                               WHERE q.replied = FALSE ORDER BY q.created_at DESC LIMIT %s""", (limit,))
            else:
                cur.execute("""SELECT q.id, q.user_id, q.text, q.created_at, q.replied, u.full_name
                               FROM questions q LEFT JOIN users u ON q.user_id = u.user_id
                               ORDER BY q.created_at DESC LIMIT %s""", (limit,))
            return cur.fetchall()

def _sync_db_question_get(qid):
    if qid is None:
        return None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT q.id, q.user_id, q.text, q.replied, q.reply_text, u.full_name
                           FROM questions q LEFT JOIN users u ON q.user_id = u.user_id
                           WHERE q.id = %s""", (qid,))
            row = cur.fetchone()
            if not row:
                return None
            return {"id": row[0], "user_id": row[1], "text": row[2],
                    "replied": row[3], "reply_text": row[4], "full_name": row[5]}

def _sync_db_question_reply(qid, reply_text, admin_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE questions SET replied = TRUE, reply_text = %s,
                           replied_at = NOW(), replied_by = %s WHERE id = %s""",
                        (reply_text, admin_id, qid))
            return cur.rowcount > 0

def _sync_db_web_session_create(user_id):
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO web_sessions (token, user_id) VALUES (%s,%s)", (token, user_id))
    return token

def _sync_db_web_session_get_user(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM web_sessions WHERE token = %s", (token,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE web_sessions SET last_used_at = NOW() WHERE token = %s", (token,))
                return row[0]
    return None

def _sync_db_web_session_delete(token):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM web_sessions WHERE token = %s", (token,))
            return cur.rowcount > 0

def _sync_db_mark_seen(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_seen_at = NOW() WHERE user_id = %s", (user_id,))

# ============= ASYNC WRAPPERS =============
async def db_restaurants_all(): return await _run(_sync_db_restaurants_all)
async def db_restaurants_for_app(): return await _run(_sync_db_restaurants_for_app)
async def db_restaurant(key): return await _run(_sync_db_restaurant, key)
async def db_restaurant_update(key, f, v): return await _run(_sync_db_restaurant_update, key, f, v)
async def db_restaurant_set_coords(key, lat, lon): return await _run(_sync_db_restaurant_set_coords, key, lat, lon)
async def db_restaurant_set_status(key, fs): return await _run(_sync_db_restaurant_set_status, key, fs)
async def db_restaurant_set_tu(key, tu_id): return await _run(_sync_db_restaurant_set_tu, key, tu_id)
async def db_restaurant_add(*a): return await _run(_sync_db_restaurant_add, *a)
async def db_restaurant_delete(key): return await _run(_sync_db_restaurant_delete, key)
async def db_get(user_id): return await _run(_sync_db_get, user_id)
async def db_get_by_login(login): return await _run(_sync_db_get_by_login, login)
async def db_login_exists(login, exclude=None): return await _run(_sync_db_login_exists, login, exclude)
async def db_create_user(*a, **kw): return await _run(_sync_db_create_user, *a, **kw)
async def db_update_user(uid, f, v): return await _run(_sync_db_update_user, uid, f, v)
async def db_is_blocked(user_id): return await _run(_sync_db_is_blocked, user_id)
async def db_list_active_users(rk=None): return await _run(_sync_db_list_active_users, rk)
async def db_delete_user(user_id): return await _run(_sync_db_delete_user, user_id)
async def db_list_tu_candidates(): return await _run(_sync_db_list_tu_candidates)
async def db_dashboard_stats(): return await _run(_sync_db_dashboard_stats)
async def get_report_stats(): return await _run(_sync_get_report_stats)
async def db_add_news(t, b, l, publish_at=None): return await _run(_sync_db_add_news, t, b, l, publish_at)
async def db_list_news(): return await _run(_sync_db_list_news)
async def db_list_news_admin(): return await _run(_sync_db_list_news_admin)
async def db_get_news_full(nid): return await _run(_sync_db_get_news_full, nid)
async def db_news_update_title(nid, title): return await _run(_sync_db_news_update_title, nid, title)
async def db_delete_news(nid): return await _run(_sync_db_delete_news, nid)
async def db_publish_due(): return await _run(_sync_db_publish_due)
async def db_list_standards(): return await _run(_sync_db_list_standards)
async def db_add_standard(*a, **kw): return await _run(_sync_db_add_standard, *a, **kw)
async def db_delete_standard(sid): return await _run(_sync_db_delete_standard, sid)
async def db_update_standard(sid, f, v): return await _run(_sync_db_update_standard, sid, f, v)
async def db_list_faq(): return await _run(_sync_db_list_faq)
async def db_add_faq(*a, **kw): return await _run(_sync_db_add_faq, *a, **kw)
async def db_delete_faq(fid): return await _run(_sync_db_delete_faq, fid)
async def db_update_faq(fid, f, v): return await _run(_sync_db_update_faq, fid, f, v)
async def db_positions_list(inc=False): return await _run(_sync_db_positions_list, inc)
async def db_position_add(name): return await _run(_sync_db_position_add, name)
async def db_position_archive(pid): return await _run(_sync_db_position_archive, pid)
async def db_audit(*a, **kw): return await _run(_sync_db_audit, *a, **kw)
async def db_audit_list(limit=200): return await _run(_sync_db_audit_list, limit)
async def db_question_add(uid, text): return await _run(_sync_db_question_add, uid, text)
async def db_questions_list(unanswered_only=True, limit=200): return await _run(_sync_db_questions_list, unanswered_only, limit)
async def db_question_get(qid): return await _run(_sync_db_question_get, qid)
async def db_question_reply(qid, txt, aid): return await _run(_sync_db_question_reply, qid, txt, aid)
async def db_web_session_create(uid): return await _run(_sync_db_web_session_create, uid)
async def db_web_session_get_user(token): return await _run(_sync_db_web_session_get_user, token)
async def db_web_session_delete(token): return await _run(_sync_db_web_session_delete, token)
async def db_mark_seen(uid): return await _run(_sync_db_mark_seen, uid)

async def restaurant_names_map():
    return {r["key"]: r["name"] for r in await db_restaurants_all()}

async def build_restaurants_payload():
    out = []
    for r in await db_restaurants_for_app():
        status, status_text = restaurant_status_for(r)
        out.append({"key": r["key"], "name": r["name"], "address": r["address"],
                    "hours": r["hours"], "org": r["org"], "phone": r.get("phone") or "",
                    "lat": r.get("lat"), "lon": r.get("lon"),
                    "sort": r.get("sort") if r.get("sort") is not None else 100,
                    "status": status, "status_text": status_text})
    return out

# ============= BOOTSTRAP =============
def _sync_bootstrap_data(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_seen_at = NOW() WHERE user_id = %s", (user_id,))
            cur.execute("SELECT full_name, phone, birth_date, position, restaurant, welcomed, "
                        "is_blocked, is_certified, is_medbook_valid "
                        "FROM users WHERE user_id = %s", (user_id,))
            user_row = cur.fetchone()
            cur.execute("SELECT id, title, body, important, level, created_at FROM news "
                        "WHERE published = TRUE ORDER BY created_at DESC, id DESC LIMIT 50")
            news_rows = cur.fetchall()
            cur.execute("SELECT id, title, category, description, url FROM standards ORDER BY id")
            std_rows = cur.fetchall()
            cur.execute("SELECT id, question, answer, category FROM faq ORDER BY id")
            faq_rows = cur.fetchall()
            cur.execute("SELECT key, name, address, hours, lat, lon, org, phone, force_status, sort "
                        "FROM restaurants ORDER BY sort, name")
            rest_rows = cur.fetchall()

            can_see_team = False
            team_rows = []
            if user_row and len(user_row) > 3 and user_row[3]:
                pos_lower = (user_row[3] or "").lower()
                can_see_team = ("управляющий" in pos_lower) or ("hr" in pos_lower)
                if can_see_team:
                    is_us = "управляющий сменой" in pos_lower
                    if is_us:
                        cur.execute("""
                            SELECT u.full_name, u.position, u.phone, u.is_certified, u.is_medbook_valid,
                                   u.restaurant, r.name, COALESCE(mgr.full_name, '')
                            FROM users u
                            LEFT JOIN restaurants r ON u.restaurant = r.key
                            LEFT JOIN users mgr ON r.territory_manager_id = mgr.user_id
                            WHERE u.user_id != %s AND u.is_blocked = FALSE
                              AND u.full_name IS NOT NULL AND u.restaurant = %s
                            ORDER BY u.full_name
                        """, (user_id, user_row[4]))
                    else:
                        cur.execute("""
                            SELECT u.full_name, u.position, u.phone, u.is_certified, u.is_medbook_valid,
                                   u.restaurant, r.name, COALESCE(mgr.full_name, '')
                            FROM users u
                            LEFT JOIN restaurants r ON u.restaurant = r.key
                            LEFT JOIN users mgr ON r.territory_manager_id = mgr.user_id
                            WHERE u.user_id != %s AND u.is_blocked = FALSE AND u.full_name IS NOT NULL
                            ORDER BY u.full_name
                        """, (user_id,))
                    team_rows = cur.fetchall()
    return {"user_row": user_row, "news_rows": news_rows, "std_rows": std_rows,
            "faq_rows": faq_rows, "rest_rows": rest_rows,
            "team_rows": team_rows, "can_see_team": can_see_team}

async def db_bootstrap_data(user_id):
    return await _run(_sync_bootstrap_data, user_id)

# ============= AUTH =============
async def get_auth_user(request):
    try:
        payload = await request.json()
    except Exception:
        return None, 401
    web_token = payload.get("webToken", "")
    if not web_token:
        return None, 401
    user_id = await db_web_session_get_user(web_token)
    if not user_id:
        return None, 401
    if await db_is_blocked(user_id):
        return None, 403
    return user_id, None

async def get_admin_user(request):
    user_id, err = await get_auth_user(request)
    if err:
        return None, err
    row = await db_get(user_id)
    if not row or len(row) < 11 or not row[10]:
        return None, 403
    return user_id, None

def denied_response(status):
    if status == 403:
        return web.json_response({"error": "blocked"}, status=403, dumps=json_dumps)
    return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)

def admin_denied(status):
    if status == 403:
        return web.json_response({"error": "forbidden"}, status=403, dumps=json_dumps)
    return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)

# Rate limiting for login
_login_rate = {}
_login_last_cleanup = [0.0]

async def handle_auth_login(request):
    try:
        payload = await request.json()
        login = (payload.get("login") or "").strip()
        password = payload.get("password") or ""
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)

    if not LOGIN_RE.match(login):
        return web.json_response({"error": "invalid_login_format"}, status=400, dumps=json_dumps)
    if not password:
        return web.json_response({"error": "password_required"}, status=400, dumps=json_dumps)

    key = login.lower()
    now = time.time()
    if now - _login_last_cleanup[0] > 300:
        _login_last_cleanup[0] = now
        cutoff = now - 300
        for k in [k for k, v in _login_rate.items() if v < cutoff]:
            del _login_rate[k]
    recent = [t for t in _login_rate.get(key, []) if now - t < 60]
    if len(recent) >= 5:
        return web.json_response({"error": "too_many_attempts"}, status=429, dumps=json_dumps)
    recent.append(now)
    _login_rate[key] = recent

    user = await db_get_by_login(login)
    if not user or not verify_password(password, user["password_hash"]):
        return web.json_response({"error": "invalid_credentials"}, status=401, dumps=json_dumps)
    if user["is_blocked"]:
        return web.json_response({"error": "blocked"}, status=403, dumps=json_dumps)

    token = await db_web_session_create(user["user_id"])
    return web.json_response({
        "ok": True, "token": token,
        "is_admin": user["is_admin"],
    }, dumps=json_dumps)

async def handle_auth_logout(request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    token = payload.get("webToken", "")
    if token:
        await db_web_session_delete(token)
    return web.json_response({"ok": True}, dumps=json_dumps)

# ============= STATIC =============
async def handle_favicon(request):
    return web.Response(status=204)

_INDEX_CACHE = {"data": None, "mtime": 0.0}
_ADMIN_CACHE = {"data": None, "mtime": 0.0}

def _serve_html(filename, cache):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", filename)
    if not os.path.exists(p):
        return None, "not found"
    try:
        mtime = os.stat(p).st_mtime
    except OSError:
        return None, "not found"
    if cache["data"] is None or cache["mtime"] != mtime:
        try:
            with open(p, "rb") as f:
                cache["data"] = f.read()
            cache["mtime"] = mtime
        except OSError:
            return None, "not found"
    return cache["data"], mtime

async def handle_index(request):
    data, mtime = _serve_html("index.html", _INDEX_CACHE)
    if data is None:
        return web.Response(text="frontend/index.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

async def handle_admin_page(request):
    data, mtime = _serve_html("admin.html", _ADMIN_CACHE)
    if data is None:
        return web.Response(text="frontend/admin.html not found", status=404)
    return web.Response(body=data, content_type="text/html", charset="utf-8")

# ============= USER API =============
async def handle_bootstrap(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    data = await db_bootstrap_data(user_id)
    user_row = data["user_row"]
    rest_map = {r[0]: r[1] for r in data["rest_rows"]}
    profile = None
    if user_row and user_row[0]:
        full_name = user_row[0]
        profile = {
            "full_name": full_name,
            "first_name": (full_name.split()[0] if full_name else ""),
            "phone": user_row[1], "birth_date": user_row[2],
            "position": user_row[3] or "—",
            "restaurant": rest_map.get(user_row[4], user_row[4]) if user_row[4] else "—",
            "restaurant_key": user_row[4] or "",
            "is_certified": bool(user_row[7]) if len(user_row) > 7 else False,
            "is_medbook_valid": bool(user_row[8]) if len(user_row) > 8 else False,
        }
    news_list = [{"id": nid, "title": t, "text": b,
                  "date": d.strftime("%d.%m.%Y") if d else "",
                  "important": bool(imp), "level": lv or "normal"}
                 for nid, t, b, imp, lv, d in data["news_rows"]]
    standards_list = [{"id": sid, "title": t, "category": c, "description": d, "url": u}
                      for sid, t, c, d, u in data["std_rows"]]
    faq_list = [{"id": fid, "question": q, "answer": a, "category": c}
                for fid, q, a, c in data["faq_rows"]]
    restaurants_list = []
    for r in data["rest_rows"]:
        rkey, rname, raddr, rhours, rlat, rlon, rorg, rphone, rfs, rsort = r
        if rkey == "office":
            continue
        rd = {"key": rkey, "hours": rhours or "", "force_status": rfs}
        status, status_text = restaurant_status_for(rd)
        restaurants_list.append({
            "key": rkey, "name": rname, "address": raddr, "hours": rhours,
            "org": rorg, "phone": rphone or "",
            "lat": rlat, "lon": rlon,
            "sort": rsort if rsort is not None else 100,
            "status": status, "status_text": status_text,
        })
    team_list = []
    if data.get("can_see_team"):
        for row in data["team_rows"]:
            fn, pos, ph, cert, mb, rkey, rname, mname = row
            team_list.append({
                "full_name": fn or "", "position": pos or "", "phone": ph or "",
                "is_certified": bool(cert), "is_medbook_valid": bool(mb),
                "restaurant_key": rkey or "", "restaurant_name": rname or "",
                "manager_name": mname or "",
            })
    return web.json_response({
        "profile": profile,
        "news": news_list, "restaurants": restaurants_list,
        "standards": standards_list, "faq": faq_list,
        "team": team_list,
    }, dumps=json_dumps)

async def handle_restaurants(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    now_ts = time.time()
    if REST_CACHE["data"] is None or now_ts - REST_CACHE["ts"] > REST_CACHE_TTL:
        REST_CACHE["data"] = await build_restaurants_payload()
        REST_CACHE["ts"] = now_ts
    return web.json_response(REST_CACHE["data"], dumps=json_dumps)

async def handle_questions(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    qtext = (payload.get("question") or "").strip()
    if not qtext or len(qtext) > 1000:
        return web.json_response({"error": "invalid_question"}, status=400, dumps=json_dumps)
    try:
        await db_question_add(user_id, qtext)
    except Exception:
        return web.json_response({"error": "db_error"}, status=500, dumps=json_dumps)
    return web.json_response({"ok": True}, dumps=json_dumps)

async def handle_health(request):
    return web.Response(text="OK")

# ============= ADMIN API =============
def _user_row_to_dict(target_id, row, names=None):
    names = names or {}
    if not row:
        return None
    return {
        "user_id": target_id,
        "full_name": row[0] or "", "phone": row[1] or "",
        "birth_date": row[2] or "", "position": row[3] or "",
        "restaurant_key": row[4] or "",
        "restaurant_name": names.get(row[4], row[4]) if row[4] else "",
        "welcomed": bool(row[5]) if len(row) > 5 else True,
        "is_blocked": bool(row[6]) if len(row) > 6 else False,
        "is_certified": bool(row[7]) if len(row) > 7 else False,
        "is_medbook_valid": bool(row[8]) if len(row) > 8 else False,
        "login": row[9] if len(row) > 9 else "",
        "is_admin": bool(row[10]) if len(row) > 10 else False,
    }

async def handle_admin_me(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    row = await db_get(uid)
    return web.json_response({
        "is_admin": True,
        "profile": {
            "user_id": uid,
            "full_name": row[0] if row else "",
            "login": row[9] if row and len(row) > 9 else "",
            "position": row[3] if row else "",
        },
    }, dumps=json_dumps)

async def handle_admin_dashboard(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    return web.json_response({
        "stats": await db_dashboard_stats(),
        "report": await get_report_stats(),
    }, dumps=json_dumps)

async def handle_admin_users(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    search = (payload.get("search") or "").strip().lower()
    rows = await _run(_sync_db_admin_users_list, search)
    result = []
    for r in rows:
        u, fn, ph, bd, pos, rest, rn, wel, blk, cert, mb, cr, ls, lg, adm = r
        result.append({
            "user_id": u, "full_name": fn or "", "phone": ph or "",
            "birth_date": bd or "", "position": pos or "",
            "restaurant_key": rest or "", "restaurant_name": rn or "",
            "welcomed": bool(wel), "is_blocked": bool(blk),
            "is_certified": bool(cert), "is_medbook_valid": bool(mb),
            "created_at": cr.isoformat() if cr else None,
            "last_seen_at": ls.isoformat() if ls else None,
            "login": lg or "", "is_admin": bool(adm),
        })
    return web.json_response({"users": result}, dumps=json_dumps)

async def handle_admin_user_get(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    target = safe_int(payload.get("user_id"))
    if not target:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    row = await db_get(target)
    if not row:
        return web.json_response({"error": "not_found"}, status=404, dumps=json_dumps)
    names = await restaurant_names_map()
    return web.json_response({"user": _user_row_to_dict(target, row, names)}, dumps=json_dumps)

async def handle_admin_user_create(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    login = (p.get("login") or "").strip().lower()
    password = p.get("password") or ""
    full_name = (p.get("full_name") or "").strip()
    phone = (p.get("phone") or "").strip()
    birth_date = (p.get("birth_date") or "").strip()
    position = (p.get("position") or "").strip()
    restaurant = (p.get("restaurant") or "").strip()
    is_certified = bool(p.get("is_certified"))
    is_medbook_valid = bool(p.get("is_medbook_valid"))
    is_admin = bool(p.get("is_admin"))

    if not LOGIN_RE.match(login):
        return web.json_response({"error": "invalid_login", "hint": "3 буквы + 2 цифры, например abc12"}, status=400, dumps=json_dumps)
    if not password or len(password) < 6:
        return web.json_response({"error": "invalid_password", "hint": "минимум 6 символов"}, status=400, dumps=json_dumps)
    if not full_name or not NAME_RE.match(full_name) or len(full_name.split()) < 2:
        return web.json_response({"error": "invalid_full_name"}, status=400, dumps=json_dumps)
    if birth_date:
        try:
            datetime.strptime(birth_date, "%d.%m.%Y")
        except ValueError:
            return web.json_response({"error": "invalid_birth_date"}, status=400, dumps=json_dumps)
    if await db_login_exists(login):
        return web.json_response({"error": "login_taken"}, status=409, dumps=json_dumps)

    try:
        new_id = await db_create_user(login, password, full_name, phone, birth_date,
                                      position, restaurant, is_certified, is_medbook_valid, is_admin)
    except Exception as e:
        logging.error(f"create_user: {e}")
        return web.json_response({"error": "create_failed"}, status=500, dumps=json_dumps)

    await db_audit(uid, "user_create", "user", new_id, f"login={login}")
    row = await db_get(new_id)
    names = await restaurant_names_map()
    return web.json_response({"ok": True, "user": _user_row_to_dict(new_id, row, names)}, dumps=json_dumps)

async def handle_admin_user_update(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    target = safe_int(payload.get("user_id"))
    updates = payload.get("updates") or {}
    if not target:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)

    allowed = {"full_name", "phone", "birth_date", "position", "restaurant",
               "is_certified", "is_medbook_valid", "is_blocked", "is_admin",
               "login", "password"}
    changed = {}
    errors = {}

    for field, value in updates.items():
        if field not in allowed:
            continue
        if field == "login":
            v = str(value).strip().lower()
            if not LOGIN_RE.match(v):
                errors["login"] = "invalid_format"
                continue
            if await db_login_exists(v, exclude=target):
                errors["login"] = "taken"
                continue
            await db_update_user(target, "login", v)
            changed["login"] = v
            await db_audit(uid, "user_update", "user", target, f"login={v}")
            continue
        if field == "password":
            v = str(value)
            if len(v) < 6:
                errors["password"] = "too_short"
                continue
            await db_update_user(target, "password_hash", hash_password(v))
            changed["password"] = "***"
            await db_audit(uid, "user_update", "user", target, "password_changed")
            continue
        if field in ("is_certified", "is_medbook_valid", "is_blocked", "is_admin"):
            v = bool(value)
        elif field == "full_name":
            v = str(value).strip()
            if not NAME_RE.match(v) or len(v.split()) < 2:
                errors["full_name"] = "invalid"
                continue
        elif field == "phone":
            v = str(value).strip()
        elif field == "birth_date":
            v = str(value).strip()
            if v:
                try:
                    datetime.strptime(v, "%d.%m.%Y")
                except ValueError:
                    errors["birth_date"] = "invalid"
                    continue
        else:
            v = str(value or "")
        await db_update_user(target, field, v)
        changed[field] = v
        await db_audit(uid, "user_update", "user", target, f"{field}={v}")

    row = await db_get(target)
    names = await restaurant_names_map()
    return web.json_response({
        "ok": True, "changed": changed, "errors": errors,
        "user": _user_row_to_dict(target, row, names),
    }, dumps=json_dumps)

async def handle_admin_user_delete(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    target = safe_int(payload.get("user_id"))
    if not target or target == uid:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    ok = await db_delete_user(target)
    if ok:
        await db_audit(uid, "user_delete", "user", target)
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_restaurants(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_restaurants_all()
    tu_ids = {r.get("territory_manager_id") for r in rows if r.get("territory_manager_id")}
    tu_names = {}
    for tid in tu_ids:
        t = await db_get(tid)
        if t:
            tu_names[tid] = t[0] or f"ID {tid}"
    result = []
    for r in rows:
        status, status_text = restaurant_status_for(r)
        result.append({
            "key": r["key"], "name": r["name"],
            "address": r.get("address") or "", "hours": r.get("hours") or "",
            "phone": r.get("phone") or "", "org": r.get("org") or "",
            "lat": r.get("lat"), "lon": r.get("lon"),
            "sort": r.get("sort") if r.get("sort") is not None else 100,
            "force_status": r.get("force_status"),
            "status": status, "status_text": status_text,
            "territory_manager_id": r.get("territory_manager_id"),
            "territory_manager_name": tu_names.get(r.get("territory_manager_id"), ""),
        })
    tu_candidates = await db_list_tu_candidates()
    return web.json_response({
        "restaurants": result,
        "tu_candidates": [{"user_id": u, "full_name": f} for u, f in tu_candidates],
    }, dumps=json_dumps)

async def handle_admin_restaurant_update(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    key = (payload.get("key") or "").strip()
    updates = payload.get("updates") or {}
    if not key:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    allowed = {"name", "address", "phone", "hours", "org", "coords"}
    changed = {}
    for field, value in updates.items():
        if field not in allowed:
            continue
        if field == "coords":
            try:
                lat = float(value.get("lat"))
                lon = float(value.get("lon"))
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    continue
                await db_restaurant_set_coords(key, round(lat, 6), round(lon, 6))
                changed["coords"] = {"lat": lat, "lon": lon}
                await db_audit(uid, "rest_update", "restaurant", key, f"coords={lat},{lon}")
            except (TypeError, ValueError, AttributeError):
                continue
            continue
        v = str(value or "")
        if field == "name" and len(v) < 2:
            continue
        if field == "hours" and v and not validate_hours_schedule(v):
            continue
        await db_restaurant_update(key, field, v)
        changed[field] = v
        await db_audit(uid, "rest_update", "restaurant", key, f"{field}={v}")
    invalidate_rest_cache()
    return web.json_response({"ok": True, "changed": changed}, dumps=json_dumps)

async def handle_admin_restaurant_add(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    name = (payload.get("name") or "").strip()
    address = (payload.get("address") or "").strip()
    hours = (payload.get("hours") or "").strip()
    phone = (payload.get("phone") or "").strip()
    org = (payload.get("org") or "").strip()
    if len(name) < 2 or not validate_hours_schedule(hours):
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    key = slugify(name)
    ok = await db_restaurant_add(key, name, address, hours, phone, org)
    if ok:
        invalidate_rest_cache()
        await db_audit(uid, "rest_add", "restaurant", key, name)
    return web.json_response({"ok": ok, "key": key}, dumps=json_dumps)

async def handle_admin_restaurant_delete(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    key = (payload.get("key") or "").strip()
    ok, reason = await db_restaurant_delete(key)
    if ok:
        invalidate_rest_cache()
        await db_audit(uid, "rest_delete", "restaurant", key)
    return web.json_response({"ok": ok, "reason": reason}, dumps=json_dumps)

async def handle_admin_restaurant_status(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    key = (payload.get("key") or "").strip()
    st = payload.get("status")
    if st == "auto":
        st = None
    if st not in (None, "open", "closed"):
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    ok = await db_restaurant_set_status(key, st)
    if ok:
        invalidate_rest_cache()
        await db_audit(uid, "rest_set_status", "restaurant", key, str(st))
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_restaurant_tu(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    key = (payload.get("key") or "").strip()
    tu = payload.get("territory_manager_id")
    if tu is not None:
        tu = safe_int(tu) or None
    ok = await db_restaurant_set_tu(key, tu)
    if ok:
        await db_audit(uid, "rest_set_tu", "restaurant", key, str(tu))
    return web.json_response({"ok": ok}, dumps=json_dumps)

def _news_row_to_dict(row):
    nid, title, body, imp, lvl, created, published, publish_at = row
    return {"id": nid, "title": title, "body": body, "level": lvl or "normal",
            "important": bool(imp),
            "created_at": created.isoformat() if created else None,
            "published": bool(published),
            "publish_at": publish_at.isoformat() if publish_at else None}

async def handle_admin_news_list(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_list_news_admin()
    return web.json_response({"news": [_news_row_to_dict(r) for r in rows]}, dumps=json_dumps)

async def handle_admin_news_add(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    level = payload.get("level") or "normal"
    if not title or len(title) > 100 or not body or len(body) > 2000:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    if level not in ("urgent", "important", "normal"):
        level = "normal"
    publish_at = None
    raw = payload.get("publish_at")
    if raw:
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            publish_at = dt.isoformat()
        except ValueError:
            return web.json_response({"error": "invalid_date"}, status=400, dumps=json_dumps)
    nid = await db_add_news(title, body, level, publish_at=publish_at)
    await db_audit(uid, "news_add", "news", nid, title)
    return web.json_response({"ok": True, "id": nid}, dumps=json_dumps)

async def handle_admin_news_update(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    nid = safe_int(payload.get("id"))
    title = payload.get("title")
    if not nid:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    if title is not None:
        title = title.strip()
        if not title or len(title) > 100:
            return web.json_response({"error": "invalid_title"}, status=400, dumps=json_dumps)
        await db_news_update_title(nid, title)
        await db_audit(uid, "news_edit_title", "news", nid, title)
    return web.json_response({"ok": True}, dumps=json_dumps)

async def handle_admin_news_delete(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    nid = safe_int(payload.get("id"))
    ok = await db_delete_news(nid)
    if ok:
        await db_audit(uid, "news_delete", "news", nid)
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_standards_list(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_list_standards()
    return web.json_response({"standards": [
        {"id": s, "title": t, "category": c or "", "description": d or "", "url": u or ""}
        for s, t, c, d, u in rows
    ]}, dumps=json_dumps)

async def handle_admin_standard_add(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    t = (p.get("title") or "").strip()
    c = (p.get("category") or "").strip()
    d = (p.get("description") or "").strip()
    u = (p.get("url") or "").strip()
    if len(t) < 3 or len(d) < 5:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    if u and not URL_RE.match(u):
        return web.json_response({"error": "invalid_url"}, status=400, dumps=json_dumps)
    await db_add_standard(t, c, d, u)
    await db_audit(uid, "std_add", "standard", "", t)
    return web.json_response({"ok": True}, dumps=json_dumps)

async def handle_admin_standard_update(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    sid = safe_int(p.get("id"))
    field = p.get("field")
    value = str(p.get("value") or "").strip()
    if not sid or field not in ("title", "category", "description", "url"):
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    if field == "url" and value and not URL_RE.match(value):
        return web.json_response({"error": "invalid_url"}, status=400, dumps=json_dumps)
    ok = await db_update_standard(sid, field, value)
    if ok:
        await db_audit(uid, "std_update", "standard", sid, f"{field}={value}")
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_standard_delete(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    sid = safe_int(p.get("id"))
    ok = await db_delete_standard(sid)
    if ok:
        await db_audit(uid, "std_delete", "standard", sid)
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_faq_list(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_list_faq()
    return web.json_response({"faq": [
        {"id": f, "question": q, "answer": a, "category": c or ""}
        for f, q, a, c in rows
    ]}, dumps=json_dumps)

async def handle_admin_faq_add(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    q = (p.get("question") or "").strip()
    a = (p.get("answer") or "").strip()
    c = (p.get("category") or "").strip()
    if len(q) < 5 or len(a) < 3:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    await db_add_faq(q, a, c)
    await db_audit(uid, "faq_add", "faq", "", q)
    return web.json_response({"ok": True}, dumps=json_dumps)

async def handle_admin_faq_update(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    fid = safe_int(p.get("id"))
    field = p.get("field")
    value = str(p.get("value") or "").strip()
    if not fid or field not in ("question", "answer"):
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    ok = await db_update_faq(fid, field, value)
    if ok:
        await db_audit(uid, "faq_update", "faq", fid, f"{field}={value}")
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_faq_delete(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    fid = safe_int(p.get("id"))
    ok = await db_delete_faq(fid)
    if ok:
        await db_audit(uid, "faq_delete", "faq", fid)
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_positions_list(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_positions_list(include_archived=True)
    return web.json_response({"positions": [
        {"id": p, "name": n, "sort": s, "is_archived": bool(a)}
        for p, n, s, a in rows
    ]}, dumps=json_dumps)

async def handle_admin_position_add(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    name = (p.get("name") or "").strip()
    if len(name) < 2:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    ok = await db_position_add(name)
    if ok:
        await db_audit(uid, "pos_add", "position", "", name)
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_position_archive(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    pid = safe_int(p.get("id"))
    ok = await db_position_archive(pid)
    if ok:
        await db_audit(uid, "pos_archive", "position", pid)
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_questions_list(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_questions_list(unanswered_only=False, limit=200)
    return web.json_response({"questions": [
        {"id": q, "user_id": u, "text": txt,
         "created_at": ca.isoformat() if ca else None,
         "replied": bool(rep), "full_name": fn or ""}
        for q, u, txt, ca, rep, fn in rows
    ]}, dumps=json_dumps)

async def handle_admin_question_reply(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    qid = safe_int(p.get("id"))
    text = (p.get("text") or "").strip()
    if not qid or not text or len(text) > 2000:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    q = await db_question_get(qid)
    if not q:
        return web.json_response({"error": "not_found"}, status=404, dumps=json_dumps)
    await db_question_reply(qid, text, uid)
    await db_audit(uid, "question_reply", "question", qid, text[:80])
    return web.json_response({"ok": True}, dumps=json_dumps)

async def handle_admin_audit_list(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_audit_list(limit=300)
    return web.json_response({"audit": [
        {"id": a, "admin_id": adm, "action": ac,
         "target_type": tt or "", "target_id": ti or "",
         "details": det or "",
         "created_at": ca.isoformat() if ca else None}
        for a, adm, ac, tt, ti, det, ca in rows
    ]}, dumps=json_dumps)

async def handle_admin_reports(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    return web.json_response({
        "report": await get_report_stats(),
        "stats": await db_dashboard_stats(),
    }, dumps=json_dumps)

async def handle_admin_export_users(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "login", "full_name", "phone", "birth_date", "position",
                     "restaurant", "is_admin", "is_blocked", "is_certified",
                     "is_medbook_valid", "created_at"])
    for r in await _run(_sync_db_admin_users_list, ""):
        u, fn, ph, bd, pos, rest, rn, wel, blk, cert, mb, cr, ls, lg, adm = r
        writer.writerow([u, lg or "", fn or "", ph or "", bd or "", pos or "",
                         rn or rest or "",
                         "yes" if adm else "no",
                         "yes" if blk else "no",
                         "yes" if cert else "no",
                         "yes" if mb else "no",
                         cr.strftime("%d.%m.%Y %H:%M") if cr else ""])
    return web.json_response({"csv": output.getvalue()}, dumps=json_dumps)

async def handle_admin_export_news(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "body", "level", "created_at", "published", "publish_at"])
    for row in await db_list_news_admin():
        nid, title, body, imp, lvl, cr, pub, pa = row
        writer.writerow([nid, title, body, lvl or "normal",
                         cr.strftime("%d.%m.%Y %H:%M") if cr else "",
                         "yes" if pub else "no",
                         pa.strftime("%d.%m.%Y %H:%M") if pa else ""])
    return web.json_response({"csv": output.getvalue()}, dumps=json_dumps)

async def handle_admin_change_password(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        p = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    old_password = p.get("old_password") or ""
    new_password = p.get("new_password") or ""
    if not old_password or not new_password or len(new_password) < 6:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    user = await _run(_sync_db_get_by_login, "")  # placeholder
    # Реальная проверка: перезапрашиваем пароль по user_id
    row = await db_get(uid)
    if not row or len(row) < 10 or not row[9]:
        return web.json_response({"error": "no_login"}, status=400, dumps=json_dumps)
    full = await db_get_by_login(row[9])
    if not full or not verify_password(old_password, full["password_hash"]):
        return web.json_response({"error": "wrong_password"}, status=401, dumps=json_dumps)
    await db_update_user(uid, "password_hash", hash_password(new_password))
    await db_audit(uid, "admin_password_change", "user", uid)
    return web.json_response({"ok": True}, dumps=json_dumps)

# ============= BACKGROUND =============
async def scheduled_publisher():
    while True:
        try:
            due = await db_publish_due()
            for news_id, title in due:
                logging.info(f"📤 Опубликована новость #{news_id}: {title}")
        except Exception as e:
            logging.error(f"scheduled_publisher: {e}")
        await asyncio.sleep(60)

# ============= MIDDLEWARES =============
@web.middleware
async def error_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        logging.error("Unhandled %s %s: %s: %s",
                      request.method, request.path, type(e).__name__, str(e)[:200])
        return web.json_response({"error": "internal_server_error"}, status=500)

_GZIP_TYPES = ("application/json", "text/plain", "text/html", "text/css",
               "application/javascript", "application/xml", "image/svg+xml")

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

app = web.Application(middlewares=[error_middleware, gzip_middleware])

# ============= ROUTES =============
app.router.add_get("/", handle_index)
app.router.add_get("/favicon.ico", handle_favicon)
app.router.add_get("/admin", handle_admin_page)
app.router.add_get("/admin/", handle_admin_page)

app.router.add_post("/api/auth/login", handle_auth_login)
app.router.add_post("/api/auth/logout", handle_auth_logout)
app.router.add_post("/api/bootstrap", handle_bootstrap)
app.router.add_post("/api/restaurants", handle_restaurants)
app.router.add_post("/api/questions", handle_questions)
app.router.add_get("/api/health", handle_health)

app.router.add_post("/api/admin/me", handle_admin_me)
app.router.add_post("/api/admin/dashboard", handle_admin_dashboard)
app.router.add_post("/api/admin/users", handle_admin_users)
app.router.add_post("/api/admin/user/get", handle_admin_user_get)
app.router.add_post("/api/admin/user/create", handle_admin_user_create)
app.router.add_post("/api/admin/user/update", handle_admin_user_update)
app.router.add_post("/api/admin/user/delete", handle_admin_user_delete)
app.router.add_post("/api/admin/restaurants", handle_admin_restaurants)
app.router.add_post("/api/admin/restaurant/update", handle_admin_restaurant_update)
app.router.add_post("/api/admin/restaurant/add", handle_admin_restaurant_add)
app.router.add_post("/api/admin/restaurant/delete", handle_admin_restaurant_delete)
app.router.add_post("/api/admin/restaurant/status", handle_admin_restaurant_status)
app.router.add_post("/api/admin/restaurant/tu", handle_admin_restaurant_tu)
app.router.add_post("/api/admin/news", handle_admin_news_list)
app.router.add_post("/api/admin/news/add", handle_admin_news_add)
app.router.add_post("/api/admin/news/update", handle_admin_news_update)
app.router.add_post("/api/admin/news/delete", handle_admin_news_delete)
app.router.add_post("/api/admin/standards", handle_admin_standards_list)
app.router.add_post("/api/admin/standard/add", handle_admin_standard_add)
app.router.add_post("/api/admin/standard/update", handle_admin_standard_update)
app.router.add_post("/api/admin/standard/delete", handle_admin_standard_delete)
app.router.add_post("/api/admin/faq", handle_admin_faq_list)
app.router.add_post("/api/admin/faq/add", handle_admin_faq_add)
app.router.add_post("/api/admin/faq/update", handle_admin_faq_update)
app.router.add_post("/api/admin/faq/delete", handle_admin_faq_delete)
app.router.add_post("/api/admin/positions", handle_admin_positions_list)
app.router.add_post("/api/admin/position/add", handle_admin_position_add)
app.router.add_post("/api/admin/position/archive", handle_admin_position_archive)
app.router.add_post("/api/admin/questions", handle_admin_questions_list)
app.router.add_post("/api/admin/question/reply", handle_admin_question_reply)
app.router.add_post("/api/admin/audit", handle_admin_audit_list)
app.router.add_post("/api/admin/reports", handle_admin_reports)
app.router.add_post("/api/admin/export/users", handle_admin_export_users)
app.router.add_post("/api/admin/export/news", handle_admin_export_news)
app.router.add_post("/api/admin/change-password", handle_admin_change_password)

async def main():
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server on port {port}")
    spawn(scheduled_publisher(), name="scheduled_publisher")
    try:
        await asyncio.Event().wait()
    finally:
        for t in list(_bg_tasks):
            t.cancel()
        if _bg_tasks:
            await asyncio.gather(*_bg_tasks, return_exceptions=True)
        await runner.cleanup()
        if _pool:
            _pool.closeall()

if __name__ == "__main__":
    asyncio.run(main())
