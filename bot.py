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
import secrets
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, BaseMiddleware, types
from aiogram.exceptions import (
    TelegramRetryAfter,
    TelegramForbiddenError,
    TelegramBadRequest,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    BufferedInputFile,
    InaccessibleMessage,
)
import psycopg2
from psycopg2.pool import SimpleConnectionPool

try:
    from zoneinfo import ZoneInfo
    MOSCOW_TZ = ZoneInfo("Europe/Moscow")
except Exception:
    MOSCOW_TZ = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN is not set")
TOKEN = TOKEN.strip()

ADMIN_ID = os.getenv("ADMIN_ID")
if not ADMIN_ID:
    print("ПРЕДУПРЕЖДЕНИЕ: ADMIN_ID не задан — админ-панель отключена.")
    ADMIN_ID = None
else:
    ADMIN_ID = int(ADMIN_ID)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise ValueError("DATABASE_URL is not set")

APP_URL = os.getenv("MINI_APP_URL", "https://ВАШ-ДОМЕН.amvera.io").rstrip("/")

# ============= FSM STORAGE =============
REDIS_URL = os.getenv("REDIS_URL", "").strip()

if REDIS_URL:
    try:
        from aiogram.fsm.storage.redis import RedisStorage
        fsm_storage = RedisStorage.from_url(REDIS_URL)
        print("FSM: Redis storage")
    except Exception as e:
        print(f"⚠ Не удалось подключить Redis ({e}), fallback на MemoryStorage")
        fsm_storage = MemoryStorage()
else:
    fsm_storage = MemoryStorage()
    print("⚠ FSM: MemoryStorage — задай REDIS_URL для устойчивого хранения.")

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

    def _done(t: asyncio.Task):
        _bg_tasks.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logging.error("Background task %s failed", t.get_name(), exc_info=exc)

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
    {"key": "office", "name": "ОФИС", "address": "Центральный офис (уточните адрес у HR)", "hours": "Пн–пт: 09:00–18:00", "lat": None, "lon": None, "org": "", "phone": ""},
]

STANDARDS_SEED = [
    {"title": "Правила открытия смены", "category": "Чек-листы", "description": "Что проверить перед открытием: оборудование, чистота, касса.", "url": ""},
    {"title": "Стандарт работы вокера", "category": "Технология", "description": "Пошаговый стандарт приготовления блюд на воке.", "url": ""},
    {"title": "Обработка жалоб гостей", "category": "Сервис", "description": "Как реагировать на претензии и когда звать управляющего.", "url": ""},
]

FAQ_SEED = [
    {"question": "Как посмотреть график смен?", "answer": "График вывешивается на информационной доске в ресторане и уточняется у управляющего сменой.", "category": "Работа"},
    {"question": "Куда сообщать о поломке оборудования?", "answer": "Напиши управляющему сменой. Если поломка серьёзная — он оформляет заявку в сервис.", "category": "Работа"},
    {"question": "Как поменять ресторан в профиле?", "answer": "Обратись к администратору — данные в профиле меняются только через админа.", "category": "Бот"},
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
                welcomed BOOLEAN DEFAULT FALSE,
                is_blocked BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS position TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS restaurant TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_certified BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_medbook_valid BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bot_blocked BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_messages (
                user_id BIGINT, message_id BIGINT,
                PRIMARY KEY (user_id, message_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id BIGINT, message_id BIGINT,
                PRIMARY KEY (user_id, message_id)
            )
        """)
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
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS auto_broadcast BOOLEAN DEFAULT FALSE")

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
            CREATE TABLE IF NOT EXISTS greetings_log (
                user_id BIGINT, kind TEXT, year INT,
                PRIMARY KEY (user_id, kind, year)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS holiday_broadcast_log (
                kind TEXT, year INT, PRIMARY KEY (kind, year)
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
            CREATE TABLE IF NOT EXISTS admin_pinned (
                admin_id BIGINT,
                user_id BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (admin_id, user_id)
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS web_auth_codes (
                user_id BIGINT PRIMARY KEY,
                code TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_created ON admin_audit (created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_blocked ON users (is_blocked)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_bot_blocked ON users (bot_blocked)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_created ON news (created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_publish ON news (published, publish_at)")

        cur.execute("SELECT COUNT(*) FROM news")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s)",
                        ("Открытие новой точки", "Скоро открываем новый ресторан! Подробности расскажет управляющий на ближайшей смене.", True, "urgent"))
            cur.execute("INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s)",
                        ("Обновление меню", "В сезоне осень появились новые позиции — уточните состав у шеф-повара на смене.", False, "normal"))
        cur.execute("SELECT COUNT(*) FROM restaurants")
        if cur.fetchone()[0] == 0:
            for i, r in enumerate(RESTAURANTS_SEED):
                sort = 999 if r["key"] == "office" else i
                cur.execute(
                    "INSERT INTO restaurants (key, name, address, hours, lat, lon, org, phone, sort) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (r["key"], r["name"], r["address"], r["hours"], r["lat"], r["lon"], r["org"], r["phone"], sort))

        PHONE_MIGRATION = {
            "mega_belaya_dacha": "+7 (915) 479-09-41",
            "belyaevo":          "+7 (985) 857-06-69",
            "erevan_plaza":      "+7 (906) 094-61-46",
            "kuzminki_mall":     "+7 (968) 537-09-94",
            "mega_teplyy_stan":  "+7 (985) 857-05-88",
            "mega_himki":        "+7 (985) 857-08-22",
            "metropolis":        "+7 (985) 857-07-14",
            "moskva_city":       "+7 (915) 479-91-70",
            "okeaniya":          "+7 (915) 478-64-01",
            "polkovaya":         "+7 (915) 270-25-57",
            "cdm":               "+7 (968) 537-09-89",
            "tsvetnoy":          "+7 (985) 193-38-44",
            "shchelkovskaya":    "+7 (999) 665-26-54",
            "shuka":             "+7 (985) 857-08-40",
        }
        for key, phone in PHONE_MIGRATION.items():
            cur.execute(
                "UPDATE restaurants SET phone = %s WHERE key = %s AND (phone IS NULL OR phone = '')",
                (phone, key))

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

        cur.execute("UPDATE users SET position = 'Повар холодного цеха' WHERE position = 'Холодный Цех'")
        cur.execute("UPDATE users SET position = 'Повар горячего цеха' WHERE position = 'Жарщик'")
        cur.execute("UPDATE positions SET name = 'Повар холодного цеха' WHERE name = 'Холодный Цех'")
        cur.execute("UPDATE positions SET name = 'Повар горячего цеха' WHERE name = 'Жарщик'")
        cur.execute("SELECT COUNT(*) FROM positions WHERE LOWER(name) = 'hr'")
        if cur.fetchone()[0] == 0:
            cur.execute("SELECT COALESCE(MAX(sort), 0) + 1 FROM positions")
            next_sort = cur.fetchone()[0]
            cur.execute("INSERT INTO positions (name, sort) VALUES ('HR', %s)", (next_sort,))

        cur.execute("SELECT 1 FROM admin_audit WHERE action = 'migration:coords_v1' LIMIT 1")
        if cur.fetchone() is None:
            COORDS_MIGRATION_V1 = {
                "mega_belaya_dacha": (55.6584, 37.8895),
                "belyaevo":          (55.6437, 37.5302),
                "vernadka":          (55.6845, 37.4948),
                "erevan_plaza":      (55.7023, 37.6220),
                "kuzminki_mall":     (55.6989, 37.7772),
                "mega_teplyy_stan":  (55.5795, 37.4865),
                "mega_himki":        (55.8948, 37.3973),
                "metropolis":        (55.8214, 37.4977),
                "moskva_city":       (55.7497, 37.5392),
                "okeaniya":          (55.7401, 37.4940),
                "polkovaya":         (55.8046, 37.5917),
                "cdm":               (55.7597, 37.6243),
                "tsvetnoy":          (55.7694, 37.6183),
                "shchelkovskaya":    (55.8101, 37.7923),
                "shuka":             (55.8007, 37.4649),
            }
            for key, (lat, lon) in COORDS_MIGRATION_V1.items():
                cur.execute(
                    "UPDATE restaurants SET lat = %s, lon = %s WHERE key = %s",
                    (lat, lon, key))
            cur.execute(
                "INSERT INTO admin_audit (admin_id, action, target_type, details) "
                "VALUES (0, 'migration:coords_v1', 'system', %s)",
                (f"updated {len(COORDS_MIGRATION_V1)} restaurants",))
            print(f"✅ Миграция координат v1 применена ({len(COORDS_MIGRATION_V1)} точек)")

print("База данных подключена, таблицы готовы.")

# ============= ПРАЗДНИКИ =============
HOLIDAYS = {
    (1, 1): ("🎉 Новый год!", "С Новым годом! Пусть он принесёт яркие события, отдых и вкусный стол."),
    (1, 7): ("✨ Рождество Христово", "Светлого Рождества! Тепла, уюта и добрых людей рядом."),
    (2, 23): ("🎖 День защитника Отечества", "С 23 Февраля! Поздравляем всех, кто оберегает и поддерживает команду."),
    (3, 8): ("🌷 Международный женский день", "С 8 Марта! Пусть весна приносит улыбки, цветы и лёгкие смены."),
    (4, 12): ("🚀 День космонавтики", "С Днём космонавтики! Пусть удача будет космической."),
    (5, 1): ("🌼 Праздник Весны и Труда", "С Первым мая! Отдохните, наберитесь сил и насладитесь весной."),
    (5, 9): ("🎗 День Победы", "С Днём Победы! Помним и благодарим."),
    (6, 12): ("🇷🇺 День России", "С Днём России! Хорошего праздника и выходного настроения."),
    (8, 22): ("🇷🇺 День Государственного флага России", "С Днём флага! Три цвета — одна команда."),
    (9, 1): ("🔔 День знаний", "С Днём знаний! Учиться новому — всегда хорошая идея."),
    (11, 4): ("🤝 День народного единства", "С Днём народного единства! Вместе мы — сила."),
    (12, 31): ("🎄 Канун Нового года", "Последний день года — выдохните и подведите итоги. Праздник уже на пороге!"),
}

def _moscow_now() -> datetime:
    if MOSCOW_TZ:
        return datetime.now(MOSCOW_TZ)
    return datetime.now(timezone(timedelta(hours=3)))

def greeting_for_user(birth_date: str, now=None):
    now = now or _moscow_now()
    if birth_date:
        try:
            b = datetime.strptime(birth_date, "%d.%m.%Y")
            if (b.month, b.day) == (now.month, now.day):
                return ("birthday", "🎂 С Днём рождения!",
                        "Вся команда Wokker поздравляет вас. Пусть этот день будет вкусным и счастливым!")
        except ValueError:
            pass
    hol = HOLIDAYS.get((now.month, now.day))
    if hol:
        return ("holiday", hol[0], hol[1])
    return ("normal", "", "")

# ============= СИНХРОННЫЕ DB =============
RESTAURANT_DB_FIELDS = ("name", "address", "phone", "hours", "org", "coords")

def _sync_db_restaurants_all():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, name, address, hours, lat, lon, org, phone, force_status, sort, "
                        "territory_manager_id FROM restaurants ORDER BY sort, name")
            cols = ["key", "name", "address", "hours", "lat", "lon", "org", "phone",
                    "force_status", "sort", "territory_manager_id"]
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
            cur.execute("UPDATE restaurants SET lat = %s, lon = %s WHERE key = %s",
                        (lat, lon, key))
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
            cur.execute("UPDATE restaurants SET territory_manager_id = %s WHERE key = %s",
                        (tu_id, key))
            return cur.rowcount > 0

def _sync_db_restaurant_add(key, name, address, hours, phone, org):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM restaurants WHERE key = %s", (key,))
            if cur.fetchone()[0] > 0:
                return False
            cur.execute("SELECT COALESCE(MAX(sort), 0) FROM restaurants WHERE key != 'office'")
            next_sort = cur.fetchone()[0] + 1
            cur.execute("INSERT INTO restaurants (key, name, address, hours, phone, org, sort) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
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
                        "is_blocked, is_certified, is_medbook_valid "
                        "FROM users WHERE user_id = %s", (user_id,))
            return cur.fetchone()

def _sync_db_get_first_name(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT first_name FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None

def _sync_db_set_welcomed(user_id, first_name=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, welcomed, first_name) VALUES (%s, TRUE, %s) "
                        "ON CONFLICT (user_id) DO UPDATE SET welcomed = TRUE, "
                        "first_name = COALESCE(EXCLUDED.first_name, users.first_name)",
                        (user_id, first_name))

def _sync_db_save_profile(user_id, full_name, phone, birth_date, position, restaurant, first_name=None):
    if isinstance(restaurant, dict):
        restaurant = restaurant.get("key", "")
    if restaurant is not None:
        restaurant = str(restaurant)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, full_name, phone, birth_date, position, restaurant, welcomed, first_name)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                full_name = %s, phone = %s, birth_date = %s, position = %s, restaurant = %s, welcomed = TRUE,
                first_name = COALESCE(EXCLUDED.first_name, users.first_name)
                """,
                (user_id, full_name, phone, birth_date, position, restaurant, first_name,
                 full_name, phone, birth_date, position, restaurant))

def _sync_db_update_user(user_id, field, value):
    sqls = {
        "full_name": "UPDATE users SET full_name = %s WHERE user_id = %s",
        "phone": "UPDATE users SET phone = %s WHERE user_id = %s",
        "birth_date": "UPDATE users SET birth_date = %s WHERE user_id = %s",
        "position": "UPDATE users SET position = %s WHERE user_id = %s",
        "restaurant": "UPDATE users SET restaurant = %s WHERE user_id = %s",
        "is_certified": "UPDATE users SET is_certified = %s WHERE user_id = %s",
        "is_medbook_valid": "UPDATE users SET is_medbook_valid = %s WHERE user_id = %s",
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

def _sync_db_list_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, full_name, phone, position, restaurant, welcomed, is_blocked "
                        "FROM users ORDER BY user_id")
            return cur.fetchall()

def _sync_db_search_users(q):
    ql = f"%{q.lower()}%"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, full_name, phone, position, restaurant, welcomed, is_blocked
                FROM users
                WHERE LOWER(COALESCE(full_name,'')) LIKE %s
                   OR LOWER(COALESCE(phone,'')) LIKE %s
                   OR CAST(user_id AS TEXT) LIKE %s
                ORDER BY user_id
            """, (ql, ql, f"%{q}%"))
            return cur.fetchall()

def _sync_db_list_active_users(restaurant_key=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if restaurant_key:
                cur.execute("SELECT user_id FROM users WHERE is_blocked = FALSE AND bot_blocked = FALSE "
                            "AND full_name IS NOT NULL AND restaurant = %s", (restaurant_key,))
            else:
                cur.execute("SELECT user_id FROM users WHERE is_blocked = FALSE AND bot_blocked = FALSE "
                            "AND full_name IS NOT NULL")
            return [r[0] for r in cur.fetchall()]

def _sync_db_delete_user(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            return cur.rowcount > 0

def _sync_db_set_blocked(user_id, blocked):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_blocked = %s WHERE user_id = %s", (blocked, user_id))
            return cur.rowcount > 0

def _sync_db_mark_bot_blocked(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET bot_blocked = TRUE WHERE user_id = %s", (user_id,))

def _sync_db_mark_seen(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_seen_at = NOW() WHERE user_id = %s", (user_id,))

def _sync_db_birthday_candidates(md):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT user_id, full_name, first_name
                           FROM users
                           WHERE is_blocked = FALSE AND bot_blocked = FALSE
                             AND full_name IS NOT NULL
                             AND birth_date IS NOT NULL
                             AND SUBSTRING(birth_date, 1, 5) = %s""", (md,))
            return cur.fetchall()

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
                      u.created_at, u.last_seen_at
                      FROM users u LEFT JOIN restaurants r ON u.restaurant = r.key"""
            if search:
                q = f"%{search}%"
                cur.execute(base + """ WHERE LOWER(COALESCE(u.full_name,'')) LIKE %s
                                  OR LOWER(COALESCE(u.phone,'')) LIKE %s
                                  OR CAST(u.user_id AS TEXT) LIKE %s
                                  ORDER BY u.user_id DESC""",
                            (q, q, f"%{search}%"))
            else:
                cur.execute(base + " ORDER BY u.user_id DESC")
            return cur.fetchall()

def _sync_get_report_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE")
            active = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
            blocked = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE full_name IS NOT NULL "
                        "AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '7 days')")
            inactive7 = cur.fetchone()[0] or 0
            cur.execute("""SELECT COUNT(*) FROM users
                           WHERE created_at AT TIME ZONE 'Europe/Moscow' >=
                                 (NOW() AT TIME ZONE 'Europe/Moscow') - INTERVAL '7 days'
                             AND full_name IS NOT NULL""")
            new7 = cur.fetchone()[0] or 0
    return {"total": total, "active": active, "blocked": blocked,
            "inactive7": inactive7, "new7": new7,
            "date": _moscow_now().strftime("%d.%m.%Y %H:%M")}

def _sync_db_dashboard_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT COUNT(*) FROM users
                           WHERE (created_at AT TIME ZONE 'Europe/Moscow')::date
                                 = (NOW() AT TIME ZONE 'Europe/Moscow')::date""")
            new_today = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE welcomed = TRUE AND full_name IS NULL")
            unfinished = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM questions WHERE replied = FALSE")
            questions_open = cur.fetchone()[0] or 0
            cur.execute("""SELECT COUNT(*) FROM users WHERE full_name IS NOT NULL AND is_blocked = FALSE
                           AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '7 days')""")
            inactive = cur.fetchone()[0] or 0
            cur.execute("""SELECT (created_at AT TIME ZONE 'Europe/Moscow')::date AS d, COUNT(*)
                           FROM users
                           WHERE (created_at AT TIME ZONE 'Europe/Moscow')::date
                                 >= (NOW() AT TIME ZONE 'Europe/Moscow')::date - 6
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
    return {
        "new_today": new_today, "unfinished": unfinished, "questions_open": questions_open,
        "inactive": inactive, "chart": chart, "news_scheduled": news_scheduled,
    }

def _sync_db_add_news(title, body, level, publish_at=None):
    if level not in ("urgent", "important", "normal"):
        level = "normal"
    with get_conn() as conn:
        with conn.cursor() as cur:
            if publish_at:
                cur.execute("INSERT INTO news (title, body, important, level, published, publish_at, auto_broadcast) "
                            "VALUES (%s, %s, %s, %s, FALSE, %s, TRUE) RETURNING id",
                            (title, body, level != "normal", level, publish_at))
            else:
                cur.execute("INSERT INTO news (title, body, important, level, published, publish_at) "
                            "VALUES (%s, %s, %s, %s, TRUE, NOW()) RETURNING id",
                            (title, body, level != "normal", level))
            return cur.fetchone()[0]

def _sync_db_list_news():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body, important, level, created_at "
                        "FROM news WHERE published = TRUE ORDER BY created_at DESC, id DESC")
            return cur.fetchall()

def _sync_db_list_news_admin():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body, important, level, created_at, published, publish_at "
                        "FROM news ORDER BY created_at DESC, id DESC")
            return cur.fetchall()

def _sync_db_get_news(news_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, body, level FROM news WHERE id = %s", (news_id,))
            return cur.fetchone()

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
                        "RETURNING id, title, body, level, auto_broadcast")
            return cur.fetchall()

def _sync_db_list_standards():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, category, description, url FROM standards ORDER BY id")
            return cur.fetchall()

def _sync_db_add_standard(title, category, description, url=""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO standards (title, category, description, url) VALUES (%s, %s, %s, %s)",
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
            cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s, %s, %s)",
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

def _sync_db_add_bot_msg(user_id, message_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO bot_messages (user_id, message_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (user_id, message_id))

def _sync_db_get_and_trim_bot_msgs(user_id, keep=1):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT message_id FROM bot_messages WHERE user_id = %s ORDER BY message_id DESC",
                        (user_id,))
            ids = [r[0] for r in cur.fetchall()]
            to_delete = ids[keep:]
            for mid in to_delete:
                cur.execute("DELETE FROM bot_messages WHERE user_id = %s AND message_id = %s", (user_id, mid))
    return to_delete

def _sync_db_add_user_msg(user_id, message_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO user_messages (user_id, message_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (user_id, message_id))

def _sync_db_get_and_trim_user_msgs(user_id, keep=1):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT message_id FROM user_messages WHERE user_id = %s ORDER BY message_id DESC",
                        (user_id,))
            ids = [r[0] for r in cur.fetchall()]
            to_delete = ids[keep:]
            for mid in to_delete:
                cur.execute("DELETE FROM user_messages WHERE user_id = %s AND message_id = %s", (user_id, mid))
    return to_delete

def _sync_db_already_greeted(user_id, kind, year):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM greetings_log WHERE user_id = %s AND kind = %s AND year = %s",
                        (user_id, kind, year))
            return cur.fetchone() is not None

def _sync_db_mark_greeted(user_id, kind, year):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO greetings_log (user_id, kind, year) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (user_id, kind, year))

def _sync_db_holiday_broadcast_done(kind, year):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM holiday_broadcast_log WHERE kind = %s AND year = %s", (kind, year))
            return cur.fetchone() is not None

def _sync_db_mark_holiday_broadcast(kind, year):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO holiday_broadcast_log (kind, year) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (kind, year))

def _sync_db_positions_list(include_archived=False):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if include_archived:
                cur.execute("SELECT id, name, sort, is_archived FROM positions ORDER BY is_archived, sort, name")
            else:
                cur.execute("SELECT id, name, sort, is_archived FROM positions "
                            "WHERE is_archived = FALSE ORDER BY sort, name")
            return cur.fetchall()

def _sync_db_position_add(name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM positions WHERE LOWER(name) = LOWER(%s)", (name,))
            if cur.fetchone()[0] > 0:
                return False
            cur.execute("SELECT COALESCE(MAX(sort), 0) FROM positions")
            next_sort = cur.fetchone()[0] + 1
            cur.execute("INSERT INTO positions (name, sort) VALUES (%s, %s)", (name, next_sort))
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
                        "VALUES (%s, %s, %s, %s, %s)",
                        (admin_id, action, target_type,
                         str(target_id) if target_id is not None else "",
                         details))

def _sync_db_audit_list(limit=200):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, admin_id, action, target_type, target_id, details, created_at "
                        "FROM admin_audit ORDER BY created_at DESC LIMIT %s", (limit,))
            return cur.fetchall()

def _sync_db_question_add(user_id, text):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO questions (user_id, text) VALUES (%s, %s) RETURNING id",
                        (user_id, text))
            return cur.fetchone()[0]

def _sync_db_questions_list(unanswered_only=True, limit=50):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if unanswered_only:
                cur.execute("""SELECT q.id, q.user_id, q.text, q.created_at, q.replied, u.full_name
                               FROM questions q LEFT JOIN users u ON q.user_id = u.user_id
                               WHERE q.replied = FALSE
                               ORDER BY q.created_at DESC LIMIT %s""", (limit,))
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
    if qid is None:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE questions SET replied = TRUE, reply_text = %s,
                           replied_at = NOW(), replied_by = %s WHERE id = %s""",
                        (reply_text, admin_id, qid))
            return cur.rowcount > 0

def _sync_db_pin_toggle(admin_id, user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admin_pinned WHERE admin_id = %s AND user_id = %s",
                        (admin_id, user_id))
            if cur.rowcount > 0:
                return False
            cur.execute("INSERT INTO admin_pinned (admin_id, user_id) VALUES (%s, %s)",
                        (admin_id, user_id))
            return True

def _sync_db_pinned_list(admin_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT u.user_id, u.full_name, u.position
                           FROM admin_pinned p JOIN users u ON u.user_id = p.user_id
                           WHERE p.admin_id = %s ORDER BY p.created_at DESC""", (admin_id,))
            return cur.fetchall()

def _sync_db_is_pinned(admin_id, user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM admin_pinned WHERE admin_id = %s AND user_id = %s",
                        (admin_id, user_id))
            return cur.fetchone() is not None

def _sync_db_recent_users(admin_id, limit=5):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT target_id::BIGINT AS uid, MAX(created_at) AS last_at
                           FROM admin_audit
                           WHERE admin_id = %s AND target_type = 'user' AND target_id ~ '^[0-9]+$'
                           GROUP BY target_id ORDER BY last_at DESC LIMIT %s""",
                        (admin_id, limit))
            return [r[0] for r in cur.fetchall()]

def _sync_db_recent_restaurant_keys(limit=3):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""SELECT SPLIT_PART(details, '=', 2) AS rkey, MAX(created_at) AS last_at
                           FROM admin_audit
                           WHERE action = 'user_update' AND target_type = 'user'
                                 AND details LIKE 'restaurant=%%'
                           GROUP BY SPLIT_PART(details, '=', 2)
                           ORDER BY last_at DESC LIMIT %s""", (limit,))
            return [r[0] for r in cur.fetchall() if r[0]]

def _sync_db_web_session_create(user_id):
    token = secrets.token_urlsafe(32)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO web_sessions (token, user_id) VALUES (%s, %s)", (token, user_id))
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

def _sync_db_request_web_code(phone_raw):
    digits = re.sub(r'\D', '', phone_raw)
    if len(digits) < 10:
        return None
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    last10 = digits[-10:]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id FROM users
                WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(phone, '+', ''), ' ', ''), '-', ''), '(', ''), ')', '') LIKE %s
                AND full_name IS NOT NULL
                AND is_blocked = FALSE
            """, ('%' + last10,))
            row = cur.fetchone()
            if not row:
                return None
            user_id = row[0]
            code = f"{secrets.randbelow(900000) + 100000}"
            cur.execute("DELETE FROM web_auth_codes WHERE user_id = %s", (user_id,))
            cur.execute("INSERT INTO web_auth_codes (user_id, code) VALUES (%s, %s)", (user_id, code))
            return user_id, code

def _sync_db_verify_web_code(phone_raw, code):
    digits = re.sub(r'\D', '', phone_raw)
    if len(digits) == 11 and digits.startswith('8'):
        digits = '7' + digits[1:]
    last10 = digits[-10:]
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.user_id FROM users u
                JOIN web_auth_codes c ON c.user_id = u.user_id
                WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(u.phone, '+', ''), ' ', ''), '-', ''), '(', ''), ')', '') LIKE %s
                AND c.code = %s
                AND c.created_at > NOW() - INTERVAL '10 minutes'
            """, ('%' + last10, code))
            row = cur.fetchone()
            if not row:
                return None
            user_id = row[0]
            cur.execute("DELETE FROM web_auth_codes WHERE user_id = %s", (user_id,))
            return user_id

# ============= АСИНХРОННЫЕ ОБЁРТКИ =============
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
async def db_get_first_name(user_id): return await _run(_sync_db_get_first_name, user_id)
async def db_set_welcomed(user_id, fn=None): return await _run(_sync_db_set_welcomed, user_id, fn)
async def db_save_profile(*a, **kw): return await _run(_sync_db_save_profile, *a, **kw)
async def db_update_user(uid, f, v): return await _run(_sync_db_update_user, uid, f, v)
async def db_is_blocked(user_id): return await _run(_sync_db_is_blocked, user_id)
async def db_list_users(): return await _run(_sync_db_list_users)
async def db_search_users(q): return await _run(_sync_db_search_users, q)
async def db_list_active_users(rk=None): return await _run(_sync_db_list_active_users, rk)
async def db_delete_user(user_id): return await _run(_sync_db_delete_user, user_id)
async def db_set_blocked(uid, b): return await _run(_sync_db_set_blocked, uid, b)
async def db_mark_bot_blocked(uid): return await _run(_sync_db_mark_bot_blocked, uid)
async def db_mark_seen(uid): return await _run(_sync_db_mark_seen, uid)
async def db_birthday_candidates(md): return await _run(_sync_db_birthday_candidates, md)
async def db_list_tu_candidates(): return await _run(_sync_db_list_tu_candidates)
async def get_report_stats(): return await _run(_sync_get_report_stats)
async def db_dashboard_stats(): return await _run(_sync_db_dashboard_stats)
async def db_add_news(t, b, l, publish_at=None): return await _run(_sync_db_add_news, t, b, l, publish_at)
async def db_list_news(): return await _run(_sync_db_list_news)
async def db_list_news_admin(): return await _run(_sync_db_list_news_admin)
async def db_get_news(nid): return await _run(_sync_db_get_news, nid)
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
async def db_add_bot_msg(u, m): return await _run(_sync_db_add_bot_msg, u, m)
async def db_get_and_trim_bot_msgs(u, keep=1): return await _run(_sync_db_get_and_trim_bot_msgs, u, keep)
async def db_add_user_msg(u, m): return await _run(_sync_db_add_user_msg, u, m)
async def db_get_and_trim_user_msgs(u, keep=1): return await _run(_sync_db_get_and_trim_user_msgs, u, keep)
async def db_already_greeted(u, k, y): return await _run(_sync_db_already_greeted, u, k, y)
async def db_mark_greeted(u, k, y): return await _run(_sync_db_mark_greeted, u, k, y)
async def db_holiday_broadcast_done(k, y): return await _run(_sync_db_holiday_broadcast_done, k, y)
async def db_mark_holiday_broadcast(k, y): return await _run(_sync_db_mark_holiday_broadcast, k, y)
async def db_positions_list(inc=False): return await _run(_sync_db_positions_list, inc)
async def db_position_add(name): return await _run(_sync_db_position_add, name)
async def db_position_archive(pid): return await _run(_sync_db_position_archive, pid)
async def db_web_session_create(user_id): return await _run(_sync_db_web_session_create, user_id)
async def db_web_session_get_user(token): return await _run(_sync_db_web_session_get_user, token)
async def db_request_web_code(phone): return await _run(_sync_db_request_web_code, phone)
async def db_verify_web_code(phone, code): return await _run(_sync_db_verify_web_code, phone, code)

async def db_audit(admin_id, action, tt="", ti="", details=""):
    try:
        return await _run(_sync_db_audit, admin_id, action, tt, ti, details)
    except Exception as e:
        logging.warning(f"audit failed: {e}")

async def db_audit_list(limit=100): return await _run(_sync_db_audit_list, limit)
async def db_question_add(uid, text): return await _run(_sync_db_question_add, uid, text)
async def db_questions_list(unanswered_only=True, limit=50): return await _run(_sync_db_questions_list, unanswered_only, limit)
async def db_question_get(qid): return await _run(_sync_db_question_get, qid)
async def db_question_reply(qid, txt, aid): return await _run(_sync_db_question_reply, qid, txt, aid)
async def db_pin_toggle(aid, uid): return await _run(_sync_db_pin_toggle, aid, uid)
async def db_pinned_list(aid): return await _run(_sync_db_pinned_list, aid)
async def db_is_pinned(aid, uid): return await _run(_sync_db_is_pinned, aid, uid)
async def db_recent_users(aid, limit=5): return await _run(_sync_db_recent_users, aid, limit)
async def db_recent_restaurant_keys(limit=3): return await _run(_sync_db_recent_restaurant_keys, limit)

def _sync_bootstrap_data(user_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET last_seen_at = NOW() WHERE user_id = %s", (user_id,))
            cur.execute("SELECT full_name, phone, birth_date, position, restaurant, welcomed, "
                        "is_blocked, first_name, is_certified, is_medbook_valid "
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
                            SELECT u.full_name, u.position, u.phone,
                                   u.is_certified, u.is_medbook_valid,
                                   u.restaurant, r.name, COALESCE(mgr.full_name, '')
                            FROM users u
                            LEFT JOIN restaurants r ON u.restaurant = r.key
                            LEFT JOIN users mgr ON r.territory_manager_id = mgr.user_id
                            WHERE u.user_id != %s
                              AND u.is_blocked = FALSE
                              AND u.full_name IS NOT NULL
                              AND u.restaurant = %s
                            ORDER BY u.full_name
                        """, (user_id, user_row[4]))
                    else:
                        cur.execute("""
                            SELECT u.full_name, u.position, u.phone,
                                   u.is_certified, u.is_medbook_valid,
                                   u.restaurant, r.name, COALESCE(mgr.full_name, '')
                            FROM users u
                            LEFT JOIN restaurants r ON u.restaurant = r.key
                            LEFT JOIN users mgr ON r.territory_manager_id = mgr.user_id
                            WHERE u.user_id != %s
                              AND u.is_blocked = FALSE
                              AND u.full_name IS NOT NULL
                            ORDER BY u.full_name
                        """, (user_id,))
                    team_rows = cur.fetchall()
    return {
        "user_row": user_row, "news_rows": news_rows, "std_rows": std_rows,
        "faq_rows": faq_rows, "rest_rows": rest_rows,
        "team_rows": team_rows, "can_see_team": can_see_team,
    }

async def db_bootstrap_data(user_id):
    return await _run(_sync_bootstrap_data, user_id)

# ============= СТАТУС РЕСТОРАНОВ =============
DAY_MAP = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
DAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

REST_CACHE = {"data": None, "ts": 0.0}
REST_CACHE_TTL = 60

def invalidate_rest_cache():
    REST_CACHE["data"] = None
    REST_CACHE["ts"] = 0.0

def validate_hours_schedule(text):
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

def parse_hours(hours_text: str):
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

def _fmt_minutes(total_min: int) -> str:
    total_min = total_min % 1440
    return f"{total_min // 60:02d}:{total_min % 60:02d}"

def restaurant_status(hours_text: str):
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

def restaurant_status_for(r: dict):
    fs = r.get("force_status")
    if fs == "open":
        return "open", "Открыто (администратором)"
    if fs == "closed":
        return "closed", "Закрыто (администратором)"
    return restaurant_status(r.get("hours") or "")

# ============= УТИЛИТЫ =============
PAGE_USERS = 10
PAGE_NEWS = 8
PAGE_RESTS = 12
PAGE_STD = 10
PAGE_FAQ = 10
PAGE_AUDIT = 15
PAGE_QUESTIONS = 8

NAME_RE = re.compile(r"^[А-Яа-яЁёA-Za-z\- ]{2,100}$")
URL_RE = re.compile(r"^https?://[^\s]+$")

def paginate(items, page, size):
    total = len(items)
    pages = max(1, (total + size - 1) // size)
    page = max(0, min(page, pages - 1))
    start = page * size
    return items[start:start + size], page, pages

def safe_int(s, default=0):
    try:
        return int(s)
    except (ValueError, TypeError):
        return default

def slugify(name):
    translit = {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
                "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
                "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
                "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya"}
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

def progress_bar(step, total, width=10):
    filled = max(0, min(width, int(step / total * width)))
    return "▓" * filled + "░" * (width - filled) + f"  {step}/{total}"

def sparkline(values):
    if not values:
        return ""
    chars = " ▁▂▃▄▅▆▇█"
    mn, mx = min(values), max(values)
    if mx == mn:
        return chars[4] * len(values)
    out = []
    for v in values:
        idx = int((v - mn) / (mx - mn) * (len(chars) - 1))
        idx = max(0, min(idx, len(chars) - 1))
        out.append(chars[idx])
    return "".join(out)

def row_user_flags(row):
    if not row:
        return False, False, False
    is_blocked = bool(row[6]) if len(row) > 6 else False
    is_certified = bool(row[7]) if len(row) > 7 else False
    is_medbook_valid = bool(row[8]) if len(row) > 8 else False
    return is_blocked, is_certified, is_medbook_valid

SOURCE_LABELS = {
    "users": "👥 Пользователи",
    "search": "🔍 Поиск",
    "pinned": "📌 Закреплённые",
    "recent": "🕒 Недавние",
    "attention": "⚠️ Внимание",
    "dashboard": "🏠 Админка",
    "newreg": "🔔 Регистрация",
    "questions": "❓ Вопросы",
    "rests": "🏪 Рестораны",
}

def back_callback(source, page):
    if source == "users":
        return f"adm_users_p:{page}"
    if source == "rests":
        return f"adm_rests_p:{page}"
    if source == "attention":
        return "adm_attention"
    if source == "questions":
        return "adm_questions"
    if source == "pinned":
        return "adm_users_pinned"
    if source == "recent":
        return "adm_users_recent"
    return "adm_menu"

def breadcrumbs(source, current):
    s = SOURCE_LABELS.get(source, "🏠 Админка")
    return f"{s} → {current}"

async def restaurant_names_map():
    return {r["key"]: r["name"] for r in await db_restaurants_all()}

async def restaurant_name_by_key(key):
    if not key:
        return key
    names = await restaurant_names_map()
    return names.get(key, key)

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

_broadcast_locks = set()

def try_lock_broadcast(key):
    if key in _broadcast_locks:
        return False
    _broadcast_locks.add(key)
    return True

def unlock_broadcast(key):
    _broadcast_locks.discard(key)

def cb_chat_id(callback: types.CallbackQuery) -> int:
    msg = getattr(callback, "message", None)
    if msg is not None and not isinstance(msg, InaccessibleMessage):
        try:
            return msg.chat.id
        except AttributeError:
            pass
    return callback.from_user.id

# ============= BOT / ROUTERS =============
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=fsm_storage)
user_router = Router()
admin_router = Router()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

class AdminOnlyMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user and not is_admin(user.id):
            if isinstance(event, types.CallbackQuery):
                try:
                    await event.answer("⛔ Недоступно", show_alert=True)
                except Exception:
                    pass
            return
        return await handler(event, data)

class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self):
        self.cache = {}
        self._last_cleanup = 0.0

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            now = time.time()
            if now - self._last_cleanup > 60:
                self._last_cleanup = now
                cutoff = now - 120
                self.cache = {k: v for k, v in self.cache.items() if v > cutoff}
            last = self.cache.get(user.id, 0)
            if now - last < 1.0:
                return
            self.cache[user.id] = now
        return await handler(event, data)

class CallbackFloodMiddleware(BaseMiddleware):
    def __init__(self):
        self.cache = {}
        self._last_cleanup = 0.0

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user:
            now = time.time()
            if now - self._last_cleanup > 60:
                self._last_cleanup = now
                cutoff = now - 60
                self.cache = {k: v for k, v in self.cache.items() if v > cutoff}
            last = self.cache.get(user.id, 0)
            if now - last < 0.5:
                try:
                    await event.answer()
                except Exception:
                    pass
                return
            self.cache[user.id] = now
        return await handler(event, data)

admin_router.message.middleware(AdminOnlyMiddleware())
admin_router.callback_query.middleware(AdminOnlyMiddleware())
user_router.message.middleware(AntiFloodMiddleware())
user_router.callback_query.middleware(CallbackFloodMiddleware())

dp.include_router(user_router)
dp.include_router(admin_router)

async def cleanup_chat(user_id: int, keep: int = 0):
    for mid in await db_get_and_trim_bot_msgs(user_id, keep=keep):
        try:
            await bot.delete_message(user_id, mid)
        except Exception:
            pass

async def delete_incoming(message: types.Message):
    if message is None:
        return
    user_id = message.from_user.id
    await db_add_user_msg(user_id, message.message_id)
    for mid in await db_get_and_trim_user_msgs(user_id, keep=1):
        try:
            await bot.delete_message(user_id, mid)
        except Exception:
            pass

async def send_tracked(chat_id: int, user_id: int, text: str, **kwargs) -> types.Message:
    msg = await bot.send_message(chat_id, text, **kwargs)
    await db_add_bot_msg(user_id, msg.message_id)
    return msg

# ============= FSM =============
class Registration(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()
    position = State()
    restaurant = State()

class NewsAdmin(StatesGroup):
    title = State()
    body = State()
    important = State()
    schedule_choice = State()
    schedule_time = State()
    preview = State()

class NewsEditTitle(StatesGroup):
    text = State()

class EditUser(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()

class RestEdit(StatesGroup):
    value = State()

class RestAdd(StatesGroup):
    name = State()
    address = State()
    hours = State()
    phone = State()
    org = State()

class StdAdmin(StatesGroup):
    title = State()
    category = State()
    description = State()

class StdEdit(StatesGroup):
    value = State()

class FaqAdmin(StatesGroup):
    question = State()
    answer = State()

class FaqEdit(StatesGroup):
    value = State()

class PosAdmin(StatesGroup):
    name = State()

class UserSearch(StatesGroup):
    query = State()

class QuestionReply(StatesGroup):
    text = State()

class BulkSelect(StatesGroup):
    active = State()

class BulkMessage(StatesGroup):
    text = State()

# ============= АВТОРИЗАЦИЯ (Только веб-токены) =============
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

# ============= КЛАВИАТУРЫ =============
FULL_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🌐 Открыть приложение", url=APP_URL)],
    [InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data="copy_link")],
])

REGISTER_ONLY = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✍️ Зарегистрироваться", callback_data="register")],
])

WELCOME_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🌐 Открыть приложение", url=APP_URL)],
    [InlineKeyboardButton(text="📋 Скопировать ссылку", callback_data="copy_link")],
])

def phone_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True)

async def positions_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"pos:{pid}")]
        for pid, name, sort, arch in await db_positions_list()
    ])

async def positions_edit_kb(target_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"editsetpos:{target_id}:{pid}")]
        for pid, name, sort, arch in await db_positions_list()
    ] + [[InlineKeyboardButton(text="🔙 К карточке", callback_data=f"adm_user:{target_id}")]])

async def restaurants_pick_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r["name"], callback_data=f"restpick:{r['key']}")]
        for r in await db_restaurants_all()
    ])

async def restaurants_edit_kb(target_id: int, recent_only=False):
    if recent_only:
        keys = await db_recent_restaurant_keys(limit=3)
        all_rests = await db_restaurants_all()
        rows = [r for r in all_rests if r["key"] in keys]
        key_order = {k: i for i, k in enumerate(keys)}
        rows.sort(key=lambda r: key_order.get(r["key"], 999))
        kb = [[InlineKeyboardButton(text=f"🕒 {r['name']}",
                                    callback_data=f"editsetrest:{target_id}:{r['key']}")]
              for r in rows]
        kb.append([InlineKeyboardButton(text="📜 Все рестораны",
                                        callback_data=f"edit_rest_all:{target_id}")])
        kb.append([InlineKeyboardButton(text="🔙 К карточке", callback_data=f"adm_user:{target_id}")])
        return InlineKeyboardMarkup(inline_keyboard=kb)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r["name"], callback_data=f"editsetrest:{target_id}:{r['key']}")]
        for r in await db_restaurants_all()
    ] + [[InlineKeyboardButton(text="🔙 К карточке", callback_data=f"adm_user:{target_id}")]])

async def profile_text(row, names=None):
    full_name, phone, birth_date, position, restaurant = row[0], row[1], row[2], row[3], row[4]
    if names is None:
        names = await restaurant_names_map()
    rest_name = names.get(restaurant, restaurant) if restaurant else "—"
    return (f"📋 <b>Твой профиль</b>\n──────────────────────────────\n"
            f"👤 ФИО: <b>{html.escape(full_name or '')}</b>\n💼 Должность: {html.escape(position or '—')}\n"
            f"📍 Ресторан: {html.escape(rest_name)}\n📞 Телефон: {html.escape(phone or '—')}\n"
            f"🎂 Дата рождения: {html.escape(birth_date or '—')}\n──────────────────────────────")

async def admin_menu_kb(stats=None):
    if stats is None:
        stats = await db_dashboard_stats()
    users_n = len([r for r in await db_list_users() if r[1]])
    news_n = len(await db_list_news_admin())
    std_n = len(await db_list_standards())
    faq_n = len(await db_list_faq())
    rest_n = len(await db_restaurants_for_app())
    pos_n = len(await db_positions_list())
    q_open = stats.get("questions_open", 0)
    attention_n = (stats.get("unfinished", 0) + stats.get("questions_open", 0)
                   + stats.get("inactive", 0) + stats.get("news_scheduled", 0))
    q_label = f"❓ Вопросы ({q_open})" if q_open else "❓ Вопросы"
    att_label = f"⚠️ Внимание ({attention_n})" if attention_n else "⚠️ Внимание"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=q_label, callback_data="adm_questions"),
         InlineKeyboardButton(text=att_label, callback_data="adm_attention")],
        [InlineKeyboardButton(text=f"👥 Пользователи ({users_n})", callback_data="adm_users")],
        [InlineKeyboardButton(text=f"🏪 Рестораны ({rest_n})", callback_data="adm_rests")],
        [InlineKeyboardButton(text=f"💼 Должности ({pos_n})", callback_data="adm_positions")],
        [InlineKeyboardButton(text=f"📰 Новости ({news_n})", callback_data="adm_news")],
        [InlineKeyboardButton(text=f"📚 Стандарты ({std_n})", callback_data="adm_std"),
         InlineKeyboardButton(text=f"❓ FAQ ({faq_n})", callback_data="adm_faq")],
        [InlineKeyboardButton(text="📊 Отчёты", callback_data="adm_reports"),
         InlineKeyboardButton(text="📜 История", callback_data="adm_audit")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_menu")],
    ])

LEVEL_LABELS = {"urgent": "🔴 Срочная", "important": "🟡 Важная", "normal": "🔵 Обычная"}

async def users_list_text(rows, page, pages, total, title="Пользователи", names=None):
    if not rows:
        return f"📋 {title} — пока пусто."
    if names is None:
        names = await restaurant_names_map()
    lines = [f"📋 {title} · всего {total} · стр. {page+1}/{pages}\n"]
    for row in rows:
        user_id, full_name, phone, position, restaurant, welcomed, is_blocked = row[:7]
        if not full_name:
            lines.append(f"• <code>{user_id}</code> — регистрация не завершена")
            continue
        mark = " 🚫" if is_blocked else ""
        rest = names.get(restaurant, restaurant) if restaurant else "—"
        lines.append(f"• <b>{html.escape(full_name)}</b>{mark} — {html.escape(position or '—')}, {html.escape(rest)}")
    return "\n".join(lines)

def users_list_kb(rows, page, pages, source="users"):
    kb = []
    for row in rows:
        user_id, full_name = row[0], row[1]
        is_blocked = bool(row[6]) if len(row) > 6 else False
        label = full_name if full_name else f"ID {user_id}"
        if is_blocked:
            label = "🚫 " + label
        kb.append([InlineKeyboardButton(text=label[:60],
                                        callback_data=f"adm_user:{user_id}:{source}:{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_users_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_users_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([
        InlineKeyboardButton(text="🔍 Поиск", callback_data="adm_users_search"),
        InlineKeyboardButton(text="📌 Закреплённые", callback_data="adm_users_pinned"),
    ])
    kb.append([InlineKeyboardButton(text="☑️ Массовые действия", callback_data="adm_users_bulk")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def user_card_text(target_id: int, row, is_pinned=False, source="users", names=None) -> str:
    if not row:
        return "Пользователь не найден."
    full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row[:7]
    is_certified = bool(row[7]) if len(row) > 7 else False
    is_medbook_valid = bool(row[8]) if len(row) > 8 else False
    if names is None:
        names = await restaurant_names_map()
    rest_name = names.get(restaurant, restaurant) if restaurant else "—"
    status = "🚫 Заблокирован" if is_blocked else "✅ Активен"
    cert = "✅ Пройдена" if is_certified else "❌ Не пройдена"
    medbook = "✅ Действительна" if is_medbook_valid else "❌ Недействительна/нет"
    pin = "📌 " if is_pinned else ""
    header = breadcrumbs(source, f"👤 {pin}Пользователь")
    return (f"{header}\n──────────────────────────────\n"
            f"🆔 ID: <code>{target_id}</code>\n"
            f"👤 ФИО: <b>{html.escape(full_name or '—')}</b>\n"
            f"💼 Должность: {html.escape(position or '—')}\n"
            f"📍 Ресторан: {html.escape(rest_name)}\n"
            f"📞 Телефон: {html.escape(phone or '—')}\n"
            f"🎂 Дата рождения: {html.escape(birth_date or '—')}\n"
            f"🎓 Сертификация: {cert}\n"
            f"📋 Мед. книжка: {medbook}\n"
            f"📊 Статус: {status}")

def user_edit_kb(target_id: int, is_blocked: bool = False, is_pinned: bool = False,
                 source: str = "users", page: int = 0,
                 is_certified: bool = False, is_medbook_valid: bool = False) -> InlineKeyboardMarkup:
    ban_btn = (InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"adm_unban:{target_id}")
               if is_blocked else
               InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"adm_ban_ask:{target_id}"))
    pin_btn = (InlineKeyboardButton(text="📌 Открепить", callback_data=f"adm_pin:{target_id}")
               if is_pinned else
               InlineKeyboardButton(text="📌 Закрепить", callback_data=f"adm_pin:{target_id}"))
    cert_btn = (InlineKeyboardButton(text="🎓 Сертификация ✅", callback_data=f"adm_cert:{target_id}")
                if is_certified else
                InlineKeyboardButton(text="🎓 Сертификация ❌", callback_data=f"adm_cert:{target_id}"))
    mb_btn = (InlineKeyboardButton(text="📋 Мед. книжка ✅", callback_data=f"adm_medbook:{target_id}")
              if is_medbook_valid else
              InlineKeyboardButton(text="📋 Мед. книжка ❌", callback_data=f"adm_medbook:{target_id}"))
    back_cb = back_callback(source, page)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ ФИО", callback_data=f"edit_field:{target_id}:full_name"),
         InlineKeyboardButton(text="📞 Телефон", callback_data=f"edit_field:{target_id}:phone")],
        [InlineKeyboardButton(text="🎂 Дата рождения", callback_data=f"edit_field:{target_id}:birth_date"),
         InlineKeyboardButton(text="💼 Должность", callback_data=f"edit_pos:{target_id}")],
        [InlineKeyboardButton(text="📍 Ресторан", callback_data=f"edit_rest:{target_id}")],
        [cert_btn, mb_btn],
        [pin_btn],
        [ban_btn, InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm_del:{target_id}")],
        [InlineKeyboardButton(text="✍️ Написать", callback_data=f"adm_msg_user:{target_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=back_cb),
         InlineKeyboardButton(text="🏠 Меню", callback_data="adm_menu")],
    ])

def news_admin_text(rows, page, pages, total):
    if not rows:
        return "📰 Новостей пока нет. Нажми «➕ Добавить новость»."
    lines = [f"📰 Новости · всего {total} · стр. {page+1}/{pages}\n"]
    for row in rows:
        news_id, title, body, important, level, created_at = row[0], row[1], row[2], row[3], row[4], row[5]
        published = row[6] if len(row) > 6 else True
        publish_at = row[7] if len(row) > 7 else None
        lvl = level if level in LEVEL_LABELS else "normal"
        date_str = created_at.strftime("%d.%m.%Y") if created_at else ""
        if not published and publish_at:
            mark = f" · ⏰ {publish_at.strftime('%d.%m %H:%M')}"
        else:
            mark = ""
        lines.append(f"{LEVEL_LABELS[lvl]} <b>{html.escape(title)}</b>{mark} ({date_str})")
    return "\n".join(lines)

def news_admin_kb(rows, page, pages):
    kb = []
    for row in rows:
        news_id, title = row[0], row[1]
        published = row[6] if len(row) > 6 else True
        short = (title or "Без названия")[:26]
        icon = "📢" if published else "⏰"
        kb.append([InlineKeyboardButton(text=f"{icon} {short}", callback_data=f"news_view:{news_id}")])
        actions = [
            InlineKeyboardButton(text="✏️", callback_data=f"news_edit_title:{news_id}"),
            InlineKeyboardButton(text="📢", callback_data=f"news_send:{news_id}"),
        ]
        if published:
            actions.append(InlineKeyboardButton(text="🗑", callback_data=f"news_del:{news_id}"))
        kb.append(actions)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_news_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_news_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="➕ Добавить новость", callback_data="news_add")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def news_important_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=LEVEL_LABELS["urgent"], callback_data="news_imp:urgent")],
        [InlineKeyboardButton(text=LEVEL_LABELS["important"], callback_data="news_imp:important")],
        [InlineKeyboardButton(text=LEVEL_LABELS["normal"], callback_data="news_imp:normal")],
    ])

def news_schedule_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Опубликовать сейчас", callback_data="news_sched_now")],
        [InlineKeyboardButton(text="⏰ Отложить", callback_data="news_sched_later")],
    ])

def news_preview_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Опубликовать", callback_data="news_pub")],
        [InlineKeyboardButton(text="✏️ Переписать", callback_data="news_restart")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_news")],
    ])

async def broadcast_news(title, body, level, restaurant_key=None):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Скрыть уведомление", callback_data="hide_notification")]
    ])
    icon = LEVEL_LABELS.get(level, LEVEL_LABELS["normal"])
    text = f"{icon} <b>{html.escape(title)}</b>\n\n{html.escape(body)}"
    sent, failed = 0, 0
    for user_id in await db_list_active_users(restaurant_key):
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            await db_mark_bot_blocked(user_id)
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    if ADMIN_ID:
        if restaurant_key:
            target = (await restaurant_names_map()).get(restaurant_key, restaurant_key)
        else:
            target = "всем"
        try:
            await bot.send_message(ADMIN_ID,
                                   f"📬 Рассылка завершена.\n\n📰 «{html.escape(title)}»\n🎯 Аудитория: {html.escape(target)}\n"
                                   f"✅ Доставлено: {sent}\n❌ Не доставлено: {failed}")
        except Exception:
            pass

FIELD_LABELS = {
    "name": "Название", "address": "Адрес", "phone": "Телефон",
    "hours": "Часы работы", "org": "Ссылка на Яндекс Картах",
    "coords": "Координаты",
}

FIELD_PROMPTS = {
    "name": "✏️ Напиши новое название точки (например: Мега Химки)",
    "address": "✏️ Напиши новый адрес (например: Москва, ул. Ленина, 5, ТЦ «Пример», этаж 2)",
    "phone": "📞 Напиши новый телефон в формате +79001234567 (или «нет», чтобы скрыть)",
    "hours": "🕒 Напиши часы работы в формате:\nПн–чт: 10:00–22:00\nПт–вс: 10:00–23:00",
    "org": "🗺 Напиши путь карточки Яндекс Карт (например: vokker/1234567890)\nили «нет», чтобы искать по адресу",
    "coords": (
        "📍 Пришли координаты в формате <code>широта, долгота</code>\n"
        "Пример: <code>55.7580, 37.6230</code>\n\n"
        "Где взять: открой Яндекс.Карты → найди ресторан → "
        "правый клик по нужной точке → «Что здесь?» → скопируй координаты."
    ),
}

def rest_status_label(r: dict) -> str:
    status, status_text = restaurant_status_for(r)
    if r.get("force_status") == "open":
        return f"🟢 {status_text}"
    if r.get("force_status") == "closed":
        return f"🔴 {status_text}"
    return f"♻️ Авто: {status_text}"

async def rest_card_text(r: dict, source="rests") -> str:
    phone = r.get("phone") or "—"
    lat = r.get("lat")
    lon = r.get("lon")
    if lat is not None and lon is not None:
        coords = f"{lat:.5f}, {lon:.5f}"
    else:
        coords = "не заданы"
    tu_id = r.get("territory_manager_id")
    tu_str = "не назначен"
    if tu_id:
        try:
            tu_row = await db_get(tu_id)
            tu_str = (tu_row[0] if tu_row else f"ID {tu_id}") or f"ID {tu_id}"
        except Exception:
            tu_str = f"ID {tu_id}"
    header = breadcrumbs(source, f"🏪 {html.escape(r['name'])}")
    return (f"{header}\n──────────────────────────────\n"
            f"{'🟢' if restaurant_status_for(r)[0] == 'open' else '🔴'} Статус: {rest_status_label(r)}\n"
            f"📍 Адрес: {html.escape(r.get('address') or '—')}\n📞 Телефон: {html.escape(phone)}\n"
            f"🕒 Часы: {html.escape((r.get('hours') or '—').replace(chr(10), ' / '))}\n"
            f"🗺 Яндекс Карты: {html.escape(r.get('org') or 'по адресу')}\n"
            f"📌 Координаты: <code>{coords}</code>\n"
            f"👔 ТУ: {html.escape(tu_str)}\n"
            f"🔑 Key: <code>{r['key']}</code>")

def rest_card_kb(r: dict, source="rests", page=0) -> InlineKeyboardMarkup:
    fs = r.get("force_status")
    if fs == "open":
        status_btn = InlineKeyboardButton(text="♻️ Вернуть авто-статус", callback_data=f"restset:{r['key']}:auto")
    elif fs == "closed":
        status_btn = InlineKeyboardButton(text="🟢 Открыть (вручную)", callback_data=f"restset:{r['key']}:open")
    else:
        status_btn = InlineKeyboardButton(text="🔴 Закрыть (вручную)", callback_data=f"restset:{r['key']}:closed")
    tu_btn = InlineKeyboardButton(text="👔 Назначить ТУ", callback_data=f"rest_tu:{r['key']}")
    rows = [
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"restedit:{r['key']}:name"),
         InlineKeyboardButton(text="✏️ Адрес", callback_data=f"restedit:{r['key']}:address")],
        [InlineKeyboardButton(text="✏️ Телефон", callback_data=f"restedit:{r['key']}:phone"),
         InlineKeyboardButton(text="✏️ Часы", callback_data=f"restedit:{r['key']}:hours")],
        [InlineKeyboardButton(text="✏️ Яндекс Карты", callback_data=f"restedit:{r['key']}:org"),
         InlineKeyboardButton(text="🗺 Координаты", callback_data=f"restedit:{r['key']}:coords")],
        [tu_btn, status_btn],
    ]
    if r["key"] != "office":
        rows.append([InlineKeyboardButton(text="🗑 Удалить точку", callback_data=f"rest_del_ask:{r['key']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=back_callback(source, page)),
                 InlineKeyboardButton(text="🏠 Меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def rests_list_kb(rests, page, pages):
    kb = []
    for r in rests:
        status, _ = restaurant_status_for(r)
        icon = "🟢" if status == "open" else "🔴"
        kb.append([
            InlineKeyboardButton(text=f"{icon} {r['name']}", callback_data=f"restadm:{r['key']}:rests:{page}"),
            InlineKeyboardButton(text=("🔓" if r.get("force_status") == "closed" else "🔒"),
                                 callback_data=f"restset:{r['key']}:{'open' if r.get('force_status') == 'closed' else 'closed'}"),
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_rests_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_rests_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="➕ Добавить точку", callback_data="rest_add")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def rests_list_text(rests, page, pages, total):
    if not rests:
        return "🏪 Список ресторанов пуст."
    lines = [f"🏪 Рестораны · всего {total} · стр. {page+1}/{pages}\n"]
    for r in rests:
        status, _ = restaurant_status_for(r)
        icon = "🟢" if status == "open" else "🔴"
        fs = r.get("force_status")
        mark = " (вручную)" if fs else ""
        lines.append(f"{icon} <b>{html.escape(r['name'])}</b>{mark} — {html.escape(r.get('address') or '—')}")
    return "\n".join(lines)

def std_card_text(row) -> str:
    sid, title, category, description, url = row
    return (f"📚 <b>{html.escape(title)}</b>\nКатегория: {html.escape(category or '—')}\n"
            f"Описание: {html.escape(description or '—')}\nСсылка: {html.escape(url or '—')}")

def std_card_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"std_edit:{sid}:title"),
         InlineKeyboardButton(text="✏️ Категория", callback_data=f"std_edit:{sid}:category")],
        [InlineKeyboardButton(text="✏️ Описание", callback_data=f"std_edit:{sid}:description"),
         InlineKeyboardButton(text="✏️ Ссылка", callback_data=f"std_edit:{sid}:url")],
        [InlineKeyboardButton(text="🗑 Удалить стандарт", callback_data=f"std_del:{sid}")],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="adm_std")],
    ])

def std_admin_kb(rows, page, pages):
    kb = []
    for sid, title, category, description, url in rows:
        kb.append([InlineKeyboardButton(text=f"📚 {html.escape(title[:28])}", callback_data=f"std_card:{sid}"),
                   InlineKeyboardButton(text="🗑", callback_data=f"std_del:{sid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_std_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_std_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="➕ Добавить стандарт", callback_data="std_add")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def std_admin_text(rows, page, pages, total):
    lines = [f"📚 Стандарты · всего {total} · стр. {page+1}/{pages}\n"]
    for sid, title, category, description, url in rows:
        lines.append(f"• {html.escape(title)}")
    return "\n".join(lines) if rows else "Пока пусто."

def faq_card_kb(fid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Вопрос", callback_data=f"faq_edit:{fid}:question")],
        [InlineKeyboardButton(text="✏️ Ответ", callback_data=f"faq_edit:{fid}:answer")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"faq_del:{fid}")],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="adm_faq")],
    ])

def faq_admin_kb(rows, page, pages):
    kb = []
    for fid, question, answer, category in rows:
        kb.append([InlineKeyboardButton(text=f"❓ {html.escape(question[:28])}",
                                        callback_data=f"faq_edit_show:{fid}"),
                   InlineKeyboardButton(text="🗑", callback_data=f"faq_del:{fid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_faq_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_faq_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="faq_add")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def faq_admin_text(rows, page, pages, total):
    lines = [f"❓ FAQ · всего {total} · стр. {page+1}/{pages}\n"]
    for fid, q, a, c in rows:
        lines.append(f"• {html.escape(q)}")
    return "\n".join(lines) if rows else "Пока пусто."

# ============================================================
# ХЕНДЛЕРЫ БОТА
# ============================================================

@user_router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if await db_is_blocked(user_id):
        await delete_incoming(message)
        await cleanup_chat(user_id)
        await send_tracked(message.chat.id, user_id, "⛔ Доступ к боту ограничен.")
        return
    await delete_incoming(message)
    await cleanup_chat(user_id)

    current_state = await state.get_state()
    if current_state:
        if current_state == Registration.full_name.state:
            await send_tracked(message.chat.id, user_id, "Шаг 1 из 5.\nНапиши ФИО:")
        elif current_state == Registration.phone.state:
            await send_tracked(message.chat.id, user_id, "Шаг 2 из 5.\nОтправь номер телефона:",
                               reply_markup=phone_kb())
        elif current_state == Registration.birth_date.state:
            await send_tracked(message.chat.id, user_id, "Шаг 3 из 5.\nДата рождения ДД.ММ.ГГГГ:",
                               reply_markup=ReplyKeyboardRemove())
        elif current_state == Registration.position.state:
            await send_tracked(message.chat.id, user_id, "Шаг 4 из 5.\nВыбери должность:",
                               reply_markup=await positions_kb())
        elif current_state == Registration.restaurant.state:
            await send_tracked(message.chat.id, user_id, "Шаг 5 из 5.\nВыбери ресторан:",
                               reply_markup=await restaurants_pick_kb())
        else:
            await send_tracked(message.chat.id, user_id,
                               "Продолжаем заполнение. Напиши /cancel для сброса.")
        return

    await state.clear()
    row = await db_get(user_id)
    if row and row[0]:
        await db_set_welcomed(user_id, message.from_user.first_name)
        phone = row[1] or "указанный при регистрации"
        await send_tracked(
            message.chat.id, user_id,
            f"🌐 <b>Приложение Wokker</b>\n\n"
            f"{APP_URL}\n\n"
            f"🔑 Для входа введи свой номер телефона:\n"
            f"<b>{html.escape(phone)}</b>\n\n"
            f"Код придёт сюда, в этот чат.\n\n"
            f"💡 <b>Совет:</b> для постоянного входа (чтобы не вводить код каждый раз) "
            f"открой ссылку в <b>Safari</b> или <b>Chrome</b>. "
            f"На iPhone: тапни <b>⋯</b> вверху → «Открыть в браузере». "
            f"Или добавь на главный экран через «Поделиться → На экран Домой».",
            parse_mode="HTML",
            reply_markup=FULL_MENU,
            disable_web_page_preview=True,
        )
        return
    if row and row[5]:
        await send_tracked(message.chat.id, user_id, "Заверши регистрацию 👇", reply_markup=REGISTER_ONLY)
        return
    await db_set_welcomed(user_id, message.from_user.first_name)
    await send_tracked(message.chat.id, user_id,
                       f"👋 {html.escape(message.from_user.first_name)}, добро пожаловать в Wokker!")
    await send_tracked(message.chat.id, user_id, "Нажми кнопку ниже, чтобы зарегистрироваться:",
                       reply_markup=REGISTER_ONLY)

@user_router.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.clear()
    await send_tracked(message.chat.id, message.from_user.id, "Отменено.")

@user_router.message(Command("profile"))
async def cmd_profile(message: types.Message):
    if await db_is_blocked(message.from_user.id):
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ ограничен.")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    row = await db_get(message.from_user.id)
    if row and row[0]:
        await send_tracked(message.chat.id, message.from_user.id,
                           await profile_text(row), parse_mode="HTML")
    else:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Ты не зарегистрирован. Напиши /start.")

@user_router.message(Command("web"))
async def cmd_web(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    row = await db_get(message.from_user.id)
    if not row or not row[0]:
        await send_tracked(
            message.chat.id, message.from_user.id,
            "Сначала пройди регистрацию — напиши /start.",
        )
        return
    phone = row[1] or "указанный при регистрации"
    await send_tracked(
        message.chat.id, message.from_user.id,
        f"🌐 <b>Приложение Wokker</b>\n\n"
        f"{APP_URL}\n\n"
        f"🔑 Войди по номеру:\n<b>{html.escape(phone)}</b>\n\n"
        f"Код придёт сюда, в этот чат.\n\n"
        f"💡 <b>Совет:</b> открой ссылку в Safari/Chrome для постоянного входа.",
        parse_mode="HTML",
        reply_markup=FULL_MENU,
        disable_web_page_preview=True,
    )

@user_router.callback_query(lambda c: c.data == "copy_link")
async def cb_copy_link(callback: types.CallbackQuery):
    await callback.answer("Ссылка ниже")
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        cb_chat_id(callback), callback.from_user.id,
        f"📋 <b>Ссылка для копирования:</b>\n\n"
        f"<code>{APP_URL}</code>\n\n"
        f"Скопируй и открой в Safari, Chrome или любом другом браузере.",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

@user_router.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    if await db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    await state.set_state(Registration.full_name)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "Шаг 1 из 5.\nНапиши ФИО (например: Иванов Иван Иванович)")

@user_router.message(Registration.full_name)
async def process_name(message: types.Message, state: FSMContext):
    if await db_is_blocked(message.from_user.id):
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ ограничен.")
        await state.clear()
        return
    if not message.text:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Отправь текст с ФИО.")
        return
    name = message.text.strip()
    if not NAME_RE.match(name) or len(name.split()) < 2:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Нужны минимум имя и фамилия, только буквы и дефис.")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.update_data(full_name=name)
    await state.set_state(Registration.phone)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"ФИО: <b>{html.escape(name)}</b> ✅\n\n" + progress_bar(1, 5) +
                       "\n\nШаг 2 из 5.\nОтправь номер телефона:",
                       parse_mode="HTML", reply_markup=phone_kb())

@user_router.message(Registration.phone, lambda m: m.contact is not None)
async def process_phone_button(message: types.Message, state: FSMContext):
    if await db_is_blocked(message.from_user.id):
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ ограничен.")
        await state.clear()
        return
    if message.contact.user_id != message.from_user.id:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Пожалуйста, поделись своим номером.", reply_markup=phone_kb())
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Registration.birth_date)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(2, 5) +
                       "\n\nНомер получен ✅\nШаг 3 из 5.\nДата рождения ДД.ММ.ГГГГ:",
                       reply_markup=ReplyKeyboardRemove())

@user_router.message(Registration.phone)
async def process_phone_text(message: types.Message, state: FSMContext):
    if await db_is_blocked(message.from_user.id):
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ ограничен.")
        await state.clear()
        return
    if not message.text:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Отправь номер текстом.")
        return
    digits = message.text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or len(digits) < 10:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Не похоже на номер. Пример: +79001234567")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.update_data(phone=message.text.strip())
    await state.set_state(Registration.birth_date)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(2, 5) +
                       "\n\nНомер записан ✅\nШаг 3 из 5.\nДата рождения ДД.ММ.ГГГГ:",
                       reply_markup=ReplyKeyboardRemove())

@user_router.message(Registration.birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    if await db_is_blocked(message.from_user.id):
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ ограничен.")
        await state.clear()
        return
    if not message.text:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Дату текстом ДД.ММ.ГГГГ:")
        return
    try:
        bd = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        if bd.year < 1900 or bd > datetime.now().date():
            raise ValueError
    except ValueError:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Такой даты не бывает. ДД.ММ.ГГГГ:")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.update_data(birth_date=bd.strftime("%d.%m.%Y"))
    await state.set_state(Registration.position)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(3, 5) +
                       "\n\nДата записана ✅\nШаг 4 из 5. Должность:",
                       reply_markup=ReplyKeyboardRemove())
    await send_tracked(message.chat.id, message.from_user.id,
                       "Выбери должность:", reply_markup=await positions_kb())

@user_router.callback_query(Registration.position, lambda c: c.data and c.data.startswith("pos:"))
async def process_position(callback: types.CallbackQuery, state: FSMContext):
    if await db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        await state.clear()
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    pid = safe_int(callback.data.split(":")[1])
    positions = {p[0]: p[1] for p in await db_positions_list()}
    position = positions.get(pid)
    if not position:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "Должность не найдена. Выбери из списка.")
        return
    await state.update_data(position=position)
    await state.set_state(Registration.restaurant)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       progress_bar(4, 5) +
                       f"\n\nДолжность: <b>{html.escape(position)}</b> ✅\n\nШаг 5 из 5. Ресторан 👇",
                       parse_mode="HTML", reply_markup=await restaurants_pick_kb())

@user_router.callback_query(Registration.restaurant, lambda c: c.data and c.data.startswith("restpick:"))
async def process_restaurant_pick(callback: types.CallbackQuery, state: FSMContext):
    if await db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        await state.clear()
        return
    key = callback.data.split(":")[1]
    restaurant = await db_restaurant(key)
    if not restaurant:
        await callback.answer("Ресторан не найден", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    data = await state.get_data()
    full_name = data.get("full_name", "")
    phone = data.get("phone", "")
    birth_date = data.get("birth_date", "")
    position = data.get("position", "")
    try:
        await db_save_profile(callback.from_user.id, full_name, phone, birth_date, position,
                              restaurant["key"], callback.from_user.first_name)
    except Exception as e:
        logging.error(f"save profile: {e}")
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "❌ Ошибка сохранения. Попробуй позже.")
        await state.clear()
        return
    await state.clear()
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       progress_bar(5, 5) +
                       f"\n\n🎉 <b>{html.escape(callback.from_user.first_name)}, регистрация завершена!</b>\n\n"
                       f"👤 ФИО: {html.escape(full_name)}\n📞 {html.escape(phone)}\n🎂 {html.escape(birth_date)}\n"
                       f"💼 {html.escape(position)}\n📍 {html.escape(restaurant['name'])}\n\n"
                       f"🌐 <b>Приложение Wokker:</b>\n{APP_URL}\n\n"
                       f"🔑 Для входа введи свой номер:\n<b>{html.escape(phone)}</b>\n\n"
                       f"Код придёт сюда, в этот чат.\n\n"
                       f"💡 <b>Совет:</b> для постоянного входа открой ссылку в Safari или Chrome "
                       f"(⋯ → «Открыть в браузере»).",
                       parse_mode="HTML", reply_markup=WELCOME_MENU,
                       disable_web_page_preview=True)
    if ADMIN_ID:
        uname = f"@{html.escape(callback.from_user.username)}" if callback.from_user.username else "нет"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 Открыть карточку",
                                  callback_data=f"adm_user:{callback.from_user.id}:newreg:0")],
            [InlineKeyboardButton(text="✍️ Написать", callback_data=f"adm_msg_user:{callback.from_user.id}"),
             InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"adm_ban_ask:{callback.from_user.id}")],
        ])
        try:
            await bot.send_message(ADMIN_ID,
                                   f"🔔 <b>Новая регистрация!</b>\n\n"
                                   f"👤 {html.escape(full_name)}\n📞 {html.escape(phone)}\n🎂 {html.escape(birth_date)}\n"
                                   f"💼 {html.escape(position)}\n📍 {html.escape(restaurant['name'])}\n"
                                   f"🆔 <code>{callback.from_user.id}</code>\n🔗 {uname}",
                                   parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            logging.error(f"notify admin: {e}")

@user_router.callback_query(lambda c: c.data == "hide_notification")
async def hide_notification(callback: types.CallbackQuery):
    msg = getattr(callback, "message", None)
    if msg is not None and not isinstance(msg, InaccessibleMessage):
        try:
            await msg.delete()
        except Exception as e:
            logging.warning(f"hide: {e}")
    await callback.answer("Скрыто")

@user_router.callback_query(lambda c: c.data == "noop")
async def user_noop(callback: types.CallbackQuery):
    await callback.answer()

# ADMIN ROUTER
@admin_router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    await _show_dashboard(message.chat.id, message.from_user.id)

@admin_router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    await _show_stats(message.chat.id, message.from_user.id)

@admin_router.message(Command("user", "u"))
async def cmd_user_search(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    q = (message.text or "")
    for cmd in ("/user", "/u"):
        if q.startswith(cmd):
            q = q[len(cmd):].strip()
            break
    if not q or len(q) < 2:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Использование: <code>/u Иванов</code> или <code>/u 123456789</code>",
                           parse_mode="HTML")
        return
    rows = await db_search_users(q)
    if not rows:
        await send_tracked(message.chat.id, message.from_user.id, f"Никого не нашёл по «{html.escape(q)}» 🤷")
        return
    if len(rows) > 30:
        await send_tracked(message.chat.id, message.from_user.id,
                           f"Слишком много совпадений ({len(rows)}). Уточни запрос.")
        return
    await send_tracked(message.chat.id, message.from_user.id,
                       await users_list_text(rows, 0, 1, len(rows), title=f"Поиск: {html.escape(q)}"),
                       parse_mode="HTML", reply_markup=users_list_kb(rows, 0, 1, source="search"))

@admin_router.message(Command("q", "questions"))
async def cmd_questions(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    await _show_questions(message.chat.id, message.from_user.id, 0)

@admin_router.message(Command("news"))
async def cmd_news(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, 0, PAGE_NEWS)
    await send_tracked(message.chat.id, message.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))

@admin_router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    text = (message.text or "").replace("/broadcast", "", 1).strip().strip('"').strip("«»")
    if not text:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Использование: <code>/broadcast Текст сообщения</code>\n"
                           "Перед отправкой покажу превью.",
                           parse_mode="HTML")
        return
    if len(text) > 2000:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком длинно (макс. 2000).")
        return
    n = len(await db_list_active_users())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Отправить всем ({n})", callback_data="quick_bc_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_menu")],
    ])
    _quick_broadcast_cache[message.from_user.id] = text
    await send_tracked(message.chat.id, message.from_user.id,
                       f"👀 <b>Превью:</b>\n\n🔵 {html.escape(text)}\n\nОтправить всем <b>{n}</b> сотрудникам?",
                       parse_mode="HTML", reply_markup=kb)

_quick_broadcast_cache = {}

@admin_router.callback_query(lambda c: c.data == "quick_bc_confirm")
async def quick_broadcast_confirm(callback: types.CallbackQuery):
    text = _quick_broadcast_cache.pop(callback.from_user.id, None)
    if not text:
        await callback.answer("Текст потерялся, повтори /broadcast", show_alert=True)
        return
    lock = "quick_bc"
    if not try_lock_broadcast(lock):
        await callback.answer("Рассылка уже идёт", show_alert=True)
        return
    await callback.answer("Рассылка запущена")
    await db_audit(callback.from_user.id, "quick_broadcast", "", "", text[:80])

    async def _run():
        try:
            await broadcast_news("Быстрое сообщение", text, "normal")
        finally:
            unlock_broadcast(lock)

    spawn(_run(), name="quick_broadcast")
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "✅ Рассылка запущена. Придёт отчёт по завершении.")

async def _show_dashboard(chat_id, user_id):
    stats = await db_dashboard_stats()
    chart = stats.get("chart", [])
    chart_line = sparkline(chart) if chart else ""
    chart_max = max(chart) if chart else 0
    total_7d = sum(chart)

    attention_items = []
    if stats.get("questions_open", 0) > 0:
        attention_items.append(f"❓ {stats['questions_open']} вопросов без ответа")
    if stats.get("unfinished", 0) > 0:
        attention_items.append(f"🆕 {stats['unfinished']} незавершённых регистраций")
    if stats.get("inactive", 0) > 0:
        attention_items.append(f"💤 {stats['inactive']} не заходили 7+ дней")
    if stats.get("news_scheduled", 0) > 0:
        attention_items.append(f"⏰ {stats['news_scheduled']} отложенных новостей")

    attention_block = ("\n".join(f"   • {a}" for a in attention_items)
                       if attention_items else "   ✅ всё в порядке")

    text = (f"🛠 <b>Админ-панель</b>\n"
            f"══════════════════════════════\n"
            f"📊 <b>Сегодня</b>\n"
            f"   +{stats['new_today']} регистраций\n\n"
            f"⚡ <b>Требуют внимания:</b>\n{attention_block}\n\n")
    if chart_line:
        text += (f"📈 <b>Регистрации (7 дней)</b>\n"
                 f"   {chart_line}  {total_7d} всего\n"
                 f"   ▁ min · █ max = {chart_max}\n\n")
    text += "Выбери раздел:"
    await send_tracked(chat_id, user_id, text, parse_mode="HTML",
                       reply_markup=await admin_menu_kb(stats))

async def _show_stats(chat_id, user_id):
    stats = await get_report_stats()
    rests = await db_restaurants_all()
    names = {r["key"]: r["name"] for r in rests}
    counts = {}
    for r in await db_list_users():
        if r[1]:
            rn = names.get(r[4], r[4]) if r[4] else "Не указан"
            counts[rn] = counts.get(rn, 0) + 1
    rest_lines = "\n".join(f"• {html.escape(k)}: {v}" for k, v in
                           sorted(counts.items(), key=lambda x: -x[1])) or "• пока нет данных"
    await send_tracked(chat_id, user_id,
                       f"📊 <b>Сводка</b> ({stats['date']})\n\n"
                       f"👥 Всего: {stats['total']} · ✅ активных: {stats['active']} · "
                       f"🚫 заблокированных: {stats['blocked']}\n"
                       f"📈 Новых за 7 дней: {stats['new7']} · 💤 Не заходили 7+ дней: {stats['inactive7']}\n"
                       f"🏪 Точек: {len(rests) - 1}\n\n"
                       f"<b>По ресторанам:</b>\n{rest_lines}",
                       parse_mode="HTML")

@admin_router.callback_query(lambda c: c.data == "adm_menu")
async def adm_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    await _show_dashboard(cb_chat_id(callback), callback.from_user.id)

@admin_router.callback_query(lambda c: c.data == "adm_attention")
async def adm_attention(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    stats = await db_dashboard_stats()
    lines = ["⚠️ <b>Требуют внимания</b>\n"]
    kb = []

    if stats.get("questions_open", 0):
        lines.append(f"❓ <b>{stats['questions_open']}</b> вопросов без ответа")
        kb.append([InlineKeyboardButton(text=f"❓ Открыть вопросы ({stats['questions_open']})",
                                        callback_data="adm_questions")])
    if stats.get("unfinished", 0):
        lines.append(f"🆕 <b>{stats['unfinished']}</b> регистраций не завершены")
        kb.append([InlineKeyboardButton(text=f"🆕 Показать ({stats['unfinished']})",
                                        callback_data="adm_attention_unfinished")])
    if stats.get("inactive", 0):
        lines.append(f"💤 <b>{stats['inactive']}</b> не заходили 7+ дней")
        kb.append([InlineKeyboardButton(text=f"💤 Показать ({stats['inactive']})",
                                        callback_data="adm_attention_inactive")])
    if stats.get("news_scheduled", 0):
        lines.append(f"⏰ <b>{stats['news_scheduled']}</b> отложенных новостей")
        kb.append([InlineKeyboardButton(text=f"⏰ Открыть новости",
                                        callback_data="adm_news")])

    if len(kb) == 0:
        lines.append("✅ Всё в порядке — ничего не требует внимания.")

    kb.append([InlineKeyboardButton(text="🏠 В меню", callback_data="adm_menu")])
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data == "adm_attention_unfinished")
async def adm_attention_unfinished(callback: types.CallbackQuery):
    await callback.answer()
    rows = [r for r in await db_list_users() if r[5] and not r[1]]
    if not rows:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "✅ Нет незавершённых регистраций.")
        return
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       await users_list_text(rows, 0, 1, len(rows),
                                             title="Незавершённые регистрации"),
                       parse_mode="HTML",
                       reply_markup=users_list_kb(rows, 0, 1, source="attention"))

@admin_router.callback_query(lambda c: c.data == "adm_attention_inactive")
async def adm_attention_inactive(callback: types.CallbackQuery):
    await callback.answer()
    all_rows = await db_list_users()
    rows = [r for r in all_rows if r[1] and not r[6]][:30]
    if not rows:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "✅ Все активны.")
        return
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       await users_list_text(rows, 0, 1, len(rows),
                                             title="Не заходили 7+ дней (примерно)"),
                       parse_mode="HTML",
                       reply_markup=users_list_kb(rows, 0, 1, source="attention"))

async def _show_questions(chat_id, user_id, page=0):
    rows = await db_questions_list(unanswered_only=True, limit=200)
    chunk, page, pages = paginate(rows, page, PAGE_QUESTIONS)
    if not rows:
        await send_tracked(chat_id, user_id,
                           "❓ <b>Вопросы</b>\n\n✅ Открытых вопросов нет.",
                           parse_mode="HTML",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                               [InlineKeyboardButton(text="📜 Все (включая отвеченные)",
                                                     callback_data="adm_questions_all")],
                               [InlineKeyboardButton(text="🏠 В меню", callback_data="adm_menu")],
                           ]))
        return
    lines = [f"❓ <b>Открытые вопросы</b> · {len(rows)} · стр. {page+1}/{pages}\n"]
    kb = []
    for qid, uid, text, created_at, replied, full_name in chunk:
        date = created_at.strftime("%d.%m %H:%M") if created_at else ""
        who = html.escape(full_name) if full_name else f"ID {uid}"
        lines.append(f"• <b>{who}</b> · {date}\n  «{html.escape(text[:70])}{'…' if len(text) > 70 else ''}»")
        kb.append([InlineKeyboardButton(text=f"💬 {who[:25]} · {date}",
                                        callback_data=f"question_view:{qid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_questions_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_questions_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="📜 Все (включая отвеченные)", callback_data="adm_questions_all")])
    kb.append([InlineKeyboardButton(text="🏠 В меню", callback_data="adm_menu")])
    await send_tracked(chat_id, user_id, "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data == "adm_questions")
async def adm_questions(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    await _show_questions(cb_chat_id(callback), callback.from_user.id, 0)

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_questions_p:"))
async def adm_questions_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await _show_questions(cb_chat_id(callback), callback.from_user.id, page)

@admin_router.callback_query(lambda c: c.data == "adm_questions_all")
async def adm_questions_all(callback: types.CallbackQuery):
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_questions_list(unanswered_only=False, limit=50)
    if not rows:
        await send_tracked(cb_chat_id(callback), callback.from_user.id, "Вопросов нет.")
        return
    lines = [f"📜 <b>Все вопросы</b> (последние {len(rows)})\n"]
    kb = []
    for qid, uid, text, created_at, replied, full_name in rows[:20]:
        date = created_at.strftime("%d.%m %H:%M") if created_at else ""
        mark = "✅" if replied else "❓"
        who = html.escape(full_name) if full_name else f"ID {uid}"
        kb.append([InlineKeyboardButton(text=f"{mark} {who[:22]} · {date}",
                                        callback_data=f"question_view:{qid}")])
    kb.append([InlineKeyboardButton(text="⬅️ Только открытые", callback_data="adm_questions")])
    kb.append([InlineKeyboardButton(text="🏠 В меню", callback_data="adm_menu")])
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("question_view:"))
async def question_view(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    qid = safe_int(callback.data.split(":")[1])
    q = await db_question_get(qid)
    if not q:
        await send_tracked(cb_chat_id(callback), callback.from_user.id, "Вопрос не найден.")
        return
    await cleanup_chat(callback.from_user.id)
    who = html.escape(q["full_name"]) if q["full_name"] else f"ID {q['user_id']}"
    status = "✅ отвечен" if q["replied"] else "❓ открыт"
    text = (f"❓ <b>Вопрос #{qid}</b> · {status}\n"
            f"──────────────────────────────\n"
            f"👤 {who} (<code>{q['user_id']}</code>)\n\n"
            f"💬 {html.escape(q['text'])}")
    kb_rows = []
    if not q["replied"]:
        kb_rows.append([InlineKeyboardButton(text="✍️ Ответить",
                                             callback_data=f"question_reply:{qid}")])
    else:
        text += f"\n\n✅ <b>Ответ:</b> {html.escape(q['reply_text'] or '—')}"
    kb_rows.append([
        InlineKeyboardButton(text="📋 Профиль",
                             callback_data=f"adm_user:{q['user_id']}:questions:0"),
        InlineKeyboardButton(text="🚫 Блок",
                             callback_data=f"adm_ban_ask:{q['user_id']}"),
    ])
    kb_rows.append([InlineKeyboardButton(text="⬅️ К вопросам", callback_data="adm_questions"),
                    InlineKeyboardButton(text="🏠 Меню", callback_data="adm_menu")])
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       text, parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("question_reply:"))
async def question_reply_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    qid = safe_int(callback.data.split(":")[1])
    q = await db_question_get(qid)
    if not q:
        await send_tracked(cb_chat_id(callback), callback.from_user.id, "Вопрос не найден.")
        return
    await state.set_state(QuestionReply.text)
    await state.update_data(qid=qid, q_user_id=q["user_id"])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"✍️ <b>Ответ на вопрос #{qid}</b>\n\n"
                       f"💬 «{html.escape(q['text'][:200])}»\n\n"
                       f"Напиши ответ — пользователь получит его в боте:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data=f"question_view:{qid}")]
                       ]))

@admin_router.message(QuestionReply.text)
async def question_reply_do(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    text = (message.text or "").strip()
    if len(text) < 2:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком короткий ответ. Ещё раз:")
        return
    if len(text) > 2000:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком длинно (макс. 2000).")
        return
    data = await state.get_data()
    qid = data.get("qid")
    q_uid = data.get("q_user_id")
    await state.clear()

    if qid is None:
        sent = False
        try:
            await bot.send_message(q_uid,
                                   f"💬 <b>Сообщение от администратора</b>\n\n{html.escape(text)}",
                                   parse_mode="HTML")
            sent = True
        except Exception as e:
            logging.warning(f"dm to user {q_uid}: {e}")
        await db_audit(message.from_user.id, "admin_dm", "user", q_uid, text[:80])
        await send_tracked(message.chat.id, message.from_user.id,
                           f"✅ {'Отправлено' if sent else 'Не доставлено'}.",
                           parse_mode="HTML")
        row = await db_get(q_uid)
        if row:
            is_pin = await db_is_pinned(message.from_user.id, q_uid)
            is_blocked, is_cert, is_mb = row_user_flags(row)
            await send_tracked(message.chat.id, message.from_user.id,
                               await user_card_text(q_uid, row, is_pin),
                               parse_mode="HTML",
                               reply_markup=user_edit_kb(q_uid, is_blocked, is_pin,
                                                         is_certified=is_cert,
                                                         is_medbook_valid=is_mb))
        return

    await db_question_reply(qid, text, message.from_user.id)
    await db_audit(message.from_user.id, "question_reply", "question", qid, text[:80])
    sent = False
    try:
        await bot.send_message(q_uid,
                               f"💬 <b>Ответ от администратора</b>\n\n{html.escape(text)}",
                               parse_mode="HTML")
        sent = True
    except Exception as e:
        logging.warning(f"reply to user: {e}")
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Ответ {'отправлен' if sent else 'сохранён, но не доставлен'}.",
                       parse_mode="HTML")
    await _show_questions(message.chat.id, message.from_user.id, 0)

@admin_router.callback_query(lambda c: c.data == "adm_users")
async def adm_users(callback: types.CallbackQuery):
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_users()
    chunk, page, pages = paginate(rows, 0, PAGE_USERS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       await users_list_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=users_list_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_users_p:"))
async def adm_users_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_users()
    chunk, page, pages = paginate(rows, page, PAGE_USERS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       await users_list_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=users_list_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data == "adm_users_search")
async def adm_users_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserSearch.query)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "🔍 Введи запрос для поиска: ФИО, телефон или часть ID.",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_users")]
                       ]))

@admin_router.message(UserSearch.query)
async def adm_users_search_do(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    q = (message.text or "").strip()
    if len(q) < 2:
        await send_tracked(message.chat.id, message.from_user.id, "Минимум 2 символа. Ещё раз:")
        return
    await state.clear()
    rows = await db_search_users(q)
    if not rows:
        await send_tracked(message.chat.id, message.from_user.id, f"Никого не нашёл по «{html.escape(q)}» 🤷")
        return
    chunk, page, pages = paginate(rows, 0, PAGE_USERS)
    await send_tracked(message.chat.id, message.from_user.id,
                       await users_list_text(chunk, page, pages, len(rows), title=f"Поиск: {html.escape(q)}"),
                       parse_mode="HTML", reply_markup=users_list_kb(chunk, page, pages, source="search"))

@admin_router.callback_query(lambda c: c.data == "adm_users_pinned")
async def adm_users_pinned(callback: types.CallbackQuery):
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    pinned = await db_pinned_list(callback.from_user.id)
    if not pinned:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "📌 Закреплённых нет.\n\n"
                           "В карточке пользователя нажми «📌 Закрепить», чтобы быстро возвращаться к нему.",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                               [InlineKeyboardButton(text="⬅️ К пользователям", callback_data="adm_users")]
                           ]))
        return
    kb = []
    lines = [f"📌 <b>Закреплённые</b> ({len(pinned)})\n"]
    for uid, fn, pos in pinned:
        lines.append(f"• <b>{html.escape(fn or '—')}</b> — {html.escape(pos or '—')}")
        kb.append([InlineKeyboardButton(text=fn or f"ID {uid}",
                                        callback_data=f"adm_user:{uid}:pinned:0")])
    kb.append([InlineKeyboardButton(text="⬅️ К пользователям", callback_data="adm_users")])
    kb.append([InlineKeyboardButton(text="🏠 Меню", callback_data="adm_menu")])
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data == "adm_users_recent")
async def adm_users_recent(callback: types.CallbackQuery):
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    ids = await db_recent_users(callback.from_user.id, limit=10)
    rows = []
    for uid in ids:
        r = await db_get(uid)
        if r:
            rows.append((uid, r[0], r[1], r[3], r[4], r[5], r[6]))
    if not rows:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "Недавних нет — открой любую карточку, и она появится здесь.")
        return
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       await users_list_text(rows, 0, 1, len(rows), title="Недавние"),
                       parse_mode="HTML",
                       reply_markup=users_list_kb(rows, 0, 1, source="recent"))

@admin_router.callback_query(lambda c: c.data == "adm_users_bulk")
async def adm_users_bulk_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(BulkSelect.active)
    await state.update_data(selected=[], bulk_page=0)
    await cleanup_chat(callback.from_user.id)
    await _show_bulk_page(cb_chat_id(callback), callback.from_user.id, state, 0)

async def _show_bulk_page(chat_id, user_id, state, page):
    data = await state.get_data()
    selected = set(data.get("selected", []))
    rows = await db_list_users()
    chunk, page, pages = paginate(rows, page, PAGE_USERS)
    await state.update_data(bulk_page=page)

    kb = []
    for uid, fn, phone, pos, rest, wel, blk in chunk:
        if not fn:
            continue
        mark = "✅" if uid in selected else "⬜️"
        kb.append([InlineKeyboardButton(
            text=f"{mark} {html.escape(fn[:35])}",
            callback_data=f"bulk_toggle:{uid}:{page}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"bulk_page:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"bulk_page:{page+1}"))
    if nav:
        kb.append(nav)

    kb.append([
        InlineKeyboardButton(text="✅ Выбрать всех на стр.",
                             callback_data=f"bulk_select_page:{page}"),
        InlineKeyboardButton(text="🧹 Сбросить", callback_data="bulk_clear"),
    ])
    if selected:
        kb.append([InlineKeyboardButton(text=f"⚙️ Действия ({len(selected)})",
                                        callback_data="bulk_actions")])
    kb.append([InlineKeyboardButton(text="❌ Выйти", callback_data="adm_users")])

    text = (f"☑️ <b>Массовые действия</b>\n"
            f"──────────────────────────────\n"
            f"Выбрано: <b>{len(selected)}</b>\n"
            f"Нажми на пользователя, чтобы выделить/снять.")
    await send_tracked(chat_id, user_id, text, parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(BulkSelect.active, lambda c: c.data and c.data.startswith("bulk_toggle:"))
async def bulk_toggle(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    parts = callback.data.split(":")
    uid = safe_int(parts[1])
    page = safe_int(parts[2])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    if uid in selected:
        selected.discard(uid)
    else:
        selected.add(uid)
    await state.update_data(selected=list(selected))
    await cleanup_chat(callback.from_user.id)
    await _show_bulk_page(cb_chat_id(callback), callback.from_user.id, state, page)

@admin_router.callback_query(BulkSelect.active, lambda c: c.data and c.data.startswith("bulk_page:"))
async def bulk_page(callback: types.CallbackQuery, state: FSMContext):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await _show_bulk_page(cb_chat_id(callback), callback.from_user.id, state, page)

@admin_router.callback_query(BulkSelect.active, lambda c: c.data and c.data.startswith("bulk_select_page:"))
async def bulk_select_page(callback: types.CallbackQuery, state: FSMContext):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    data = await state.get_data()
    selected = set(data.get("selected", []))
    rows = await db_list_users()
    chunk, _, _ = paginate(rows, page, PAGE_USERS)
    for uid, fn, *_ in chunk:
        if fn:
            selected.add(uid)
    await state.update_data(selected=list(selected))
    await cleanup_chat(callback.from_user.id)
    await _show_bulk_page(cb_chat_id(callback), callback.from_user.id, state, page)

@admin_router.callback_query(BulkSelect.active, lambda c: c.data == "bulk_clear")
async def bulk_clear(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(selected=[])
    data = await state.get_data()
    page = data.get("bulk_page", 0)
    await cleanup_chat(callback.from_user.id)
    await _show_bulk_page(cb_chat_id(callback), callback.from_user.id, state, page)

@admin_router.callback_query(BulkSelect.active, lambda c: c.data == "bulk_actions")
async def bulk_actions(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    selected = data.get("selected", [])
    if not selected:
        await callback.answer("Никого не выбрано", show_alert=True)
        return
    kb = [
        [InlineKeyboardButton(text="🚫 Заблокировать", callback_data="bulk_do_block")],
        [InlineKeyboardButton(text="✅ Разблокировать", callback_data="bulk_do_unblock")],
        [InlineKeyboardButton(text="📢 Написать сообщение", callback_data="bulk_do_msg")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="bulk_actions_back")],
    ]
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"⚙️ <b>Действия с выбранными ({len(selected)})</b>",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(BulkSelect.active, lambda c: c.data == "bulk_actions_back")
async def bulk_actions_back(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    page = data.get("bulk_page", 0)
    await cleanup_chat(callback.from_user.id)
    await _show_bulk_page(cb_chat_id(callback), callback.from_user.id, state, page)

@admin_router.callback_query(BulkSelect.active, lambda c: c.data in ("bulk_do_block", "bulk_do_unblock"))
async def bulk_do_block(callback: types.CallbackQuery, state: FSMContext):
    action = callback.data
    data = await state.get_data()
    selected = data.get("selected", [])
    if not selected:
        await callback.answer("Никого не выбрано", show_alert=True)
        return
    blocked = action == "bulk_do_block"
    done = 0
    for uid in selected:
        if uid == ADMIN_ID:
            continue
        if await db_set_blocked(uid, blocked):
            done += 1
            if blocked:
                try:
                    await bot.send_message(uid, "⛔ Доступ к боту ограничен. Обратитесь к администратору.")
                except Exception:
                    pass
    await db_audit(callback.from_user.id,
                   "bulk_block" if blocked else "bulk_unblock",
                   "user", "", f"{done} users")
    await callback.answer(f"{'Заблокировано' if blocked else 'Разблокировано'}: {done}")
    await state.update_data(selected=[])
    await cleanup_chat(callback.from_user.id)
    await _show_bulk_page(cb_chat_id(callback), callback.from_user.id, state,
                          data.get("bulk_page", 0))

@admin_router.callback_query(BulkSelect.active, lambda c: c.data == "bulk_do_msg")
async def bulk_do_msg(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    selected = data.get("selected", [])
    if not selected:
        await callback.answer("Никого не выбрано", show_alert=True)
        return
    await state.set_state(BulkMessage.text)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"✍️ Напиши сообщение для <b>{len(selected)}</b> пользователей:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="bulk_actions")]
                       ]))

@admin_router.message(BulkMessage.text)
async def bulk_msg_do(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    text = (message.text or "").strip()
    if len(text) < 2:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко. Ещё раз:")
        return
    if len(text) > 2000:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком длинно (макс. 2000).")
        return
    data = await state.get_data()
    selected = data.get("selected", [])
    await state.clear()

    sent, failed = 0, 0
    for uid in selected:
        try:
            await bot.send_message(uid, f"📢 <b>Сообщение от администратора</b>\n\n{html.escape(text)}",
                                   parse_mode="HTML")
            sent += 1
        except TelegramForbiddenError:
            await db_mark_bot_blocked(uid)
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await db_audit(message.from_user.id, "bulk_message", "user", "",
                   f"{len(selected)} users: {text[:60]}")
    await send_tracked(message.chat.id, message.from_user.id,
                       f"📬 Рассылка завершена.\n✅ Доставлено: {sent}\n❌ Не доставлено: {failed}",
                       parse_mode="HTML")

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_user:"))
async def adm_user_card(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    parts = callback.data.split(":")
    target_id = safe_int(parts[1]) if len(parts) > 1 else 0
    source = parts[2] if len(parts) > 2 else "users"
    page = safe_int(parts[3]) if len(parts) > 3 else 0
    if not target_id:
        await callback.answer("Данные устарели", show_alert=True)
        return
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    await cleanup_chat(callback.from_user.id)
    if not row:
        await send_tracked(cb_chat_id(callback), callback.from_user.id, "❌ Пользователь не найден.")
        return
    is_blocked, is_cert, is_mb = row_user_flags(row)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       await user_card_text(target_id, row, is_pin, source),
                       parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, is_blocked, is_pin, source, page,
                                                 is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_pin:"))
async def adm_pin(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    now_pinned = await db_pin_toggle(callback.from_user.id, target_id)
    await db_audit(callback.from_user.id, "pin_toggle", "user", target_id, str(now_pinned))
    await callback.answer("📌 Закреплён" if now_pinned else "Откреплён")
    row = await db_get(target_id)
    if row:
        is_blocked, is_cert, is_mb = row_user_flags(row)
        await cleanup_chat(callback.from_user.id)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await user_card_text(target_id, row, now_pinned),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, now_pinned,
                                                     is_certified=is_cert,
                                                     is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_cert:"))
async def adm_cert_toggle(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    row = await db_get(target_id)
    if not row:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    _, is_cert, _ = row_user_flags(row)
    new_val = not is_cert
    await db_update_user(target_id, "is_certified", new_val)
    await db_audit(callback.from_user.id, "user_update", "user", target_id, f"is_certified={new_val}")
    await callback.answer("Сертификация обновлена")
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    if row:
        is_blocked, is_cert2, is_mb = row_user_flags(row)
        await cleanup_chat(callback.from_user.id)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert2,
                                                     is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_medbook:"))
async def adm_medbook_toggle(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    row = await db_get(target_id)
    if not row:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    _, _, is_mb = row_user_flags(row)
    new_val = not is_mb
    await db_update_user(target_id, "is_medbook_valid", new_val)
    await db_audit(callback.from_user.id, "user_update", "user", target_id, f"is_medbook_valid={new_val}")
    await callback.answer("Мед. книжка обновлена")
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    if row:
        is_blocked, is_cert, is_mb2 = row_user_flags(row)
        await cleanup_chat(callback.from_user.id)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert,
                                                     is_medbook_valid=is_mb2))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_field:"))
async def edit_field_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        _, target_id, field = callback.data.split(":")
    except ValueError:
        return
    target_id = safe_int(target_id)
    if field == "full_name":
        prompt = "✏️ Напиши новое ФИО (например: Иванов Иван Иванович)"
        new_state = EditUser.full_name
    elif field == "phone":
        prompt = "📞 Напиши новый номер телефона (например: +79001234567)"
        new_state = EditUser.phone
    else:
        prompt = "🎂 Напиши новую дату рождения (например: 01.01.2000)"
        new_state = EditUser.birth_date
    await state.set_state(new_state)
    await state.update_data(edit_target=target_id)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"{prompt}\n\nИли нажми «Отменить»:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отменить", callback_data=f"edit_cancel:{target_id}")]
                       ]))

@admin_router.message(EditUser.full_name)
async def edit_full_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if not NAME_RE.match(name) or len(name.split()) < 2:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Нужны минимум имя и фамилия через пробел, только буквы и дефис.")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    data = await state.get_data()
    target_id = data.get("edit_target")
    await state.clear()
    await db_update_user(target_id, "full_name", name)
    await db_audit(message.from_user.id, "user_update", "user", target_id, f"full_name={name}")
    row = await db_get(target_id)
    is_pin = await db_is_pinned(message.from_user.id, target_id)
    if row:
        is_blocked, is_cert, is_mb = row_user_flags(row)
        await send_tracked(message.chat.id, message.from_user.id,
                           f"✅ ФИО обновлено: <b>{html.escape(name)}</b>\n\n" +
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.message(EditUser.phone)
async def edit_phone(message: types.Message, state: FSMContext):
    digits = (message.text or "").replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or len(digits) < 10:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Это не похоже на номер. Пример: +79001234567")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    data = await state.get_data()
    target_id = data.get("edit_target")
    await state.clear()
    await db_update_user(target_id, "phone", message.text.strip())
    await db_audit(message.from_user.id, "user_update", "user", target_id, f"phone={message.text.strip()}")
    row = await db_get(target_id)
    is_pin = await db_is_pinned(message.from_user.id, target_id)
    if row:
        is_blocked, is_cert, is_mb = row_user_flags(row)
        await send_tracked(message.chat.id, message.from_user.id,
                           f"✅ Телефон обновлён: <b>{html.escape(message.text.strip())}</b>\n\n" +
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.message(EditUser.birth_date)
async def edit_birth_date(message: types.Message, state: FSMContext):
    try:
        birth_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
        if birth_date.year < 1900 or birth_date > datetime.now().date():
            raise ValueError
    except ValueError:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Такой даты не бывает. ДД.ММ.ГГГГ:")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    data = await state.get_data()
    target_id = data.get("edit_target")
    await state.clear()
    bd = birth_date.strftime("%d.%m.%Y")
    await db_update_user(target_id, "birth_date", bd)
    await db_audit(message.from_user.id, "user_update", "user", target_id, f"birth_date={bd}")
    row = await db_get(target_id)
    is_pin = await db_is_pinned(message.from_user.id, target_id)
    if row:
        is_blocked, is_cert, is_mb = row_user_flags(row)
        await send_tracked(message.chat.id, message.from_user.id,
                           f"✅ Дата рождения обновлена: <b>{bd}</b>\n\n" +
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_cancel:"))
async def edit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    if row:
        is_blocked, is_cert, is_mb = row_user_flags(row)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_pos:"))
async def edit_pos_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "💼 Выбери новую должность:",
                       reply_markup=await positions_edit_kb(target_id))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("editsetpos:"))
async def edit_pos_set(callback: types.CallbackQuery):
    await callback.answer()
    try:
        _, target_id, pid = callback.data.split(":")
        target_id = safe_int(target_id)
        pid = safe_int(pid)
    except ValueError:
        return
    positions = {p[0]: p[1] for p in await db_positions_list(include_archived=True)}
    position = positions.get(pid)
    if not position:
        await callback.answer("Должность не найдена", show_alert=True)
        return
    await db_update_user(target_id, "position", position)
    await db_audit(callback.from_user.id, "user_update", "user", target_id, f"position={position}")
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    await cleanup_chat(callback.from_user.id)
    if row:
        is_blocked, is_cert, is_mb = row_user_flags(row)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           f"✅ Должность: <b>{html.escape(position)}</b>\n\n" +
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_rest:"))
async def edit_rest_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    recent = await db_recent_restaurant_keys(limit=3)
    if recent:
        kb = await restaurants_edit_kb(target_id, recent_only=True)
        title = "📍 Выбери ресторан (сверху — недавние):"
    else:
        kb = await restaurants_edit_kb(target_id)
        title = "📍 Выбери новый ресторан:"
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id, title, reply_markup=kb)

@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_rest_all:"))
async def edit_rest_all(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "📍 Все рестораны:",
                       reply_markup=await restaurants_edit_kb(target_id))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("editsetrest:"))
async def edit_rest_set(callback: types.CallbackQuery):
    await callback.answer()
    try:
        _, target_id, key = callback.data.split(":")
        target_id = safe_int(target_id)
    except ValueError:
        return
    await db_update_user(target_id, "restaurant", key)
    names = await restaurant_names_map()
    rest_name = names.get(key, key)
    await db_audit(callback.from_user.id, "user_update", "user", target_id, f"restaurant={key}")
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    await cleanup_chat(callback.from_user.id)
    if row:
        is_blocked, is_cert, is_mb = row_user_flags(row)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           f"✅ Ресторан: <b>{html.escape(rest_name)}</b>\n\n" +
                           await user_card_text(target_id, row, is_pin, names=names),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, is_blocked, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_msg_user:"))
async def adm_msg_user(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    target_id = safe_int(callback.data.split(":")[1])
    await state.set_state(QuestionReply.text)
    await state.update_data(qid=None, q_user_id=target_id)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "✍️ Напиши сообщение пользователю — он получит его в боте:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm_user:{target_id}:users:0")]
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_ban_ask:"))
async def adm_ban_ask(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("Нельзя заблокировать самого себя", show_alert=True)
        return
    row = await db_get(target_id)
    if not row:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"🚫 Заблокировать <b>{html.escape(row[0] or 'без имени')}</b> (<code>{target_id}</code>)?\n\n"
                       f"Пользователь потеряет доступ к боту и приложению.",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="✅ Да, заблокировать",
                                                 callback_data=f"adm_ban:{target_id}")],
                           [InlineKeyboardButton(text="❌ Отмена",
                                                 callback_data=f"adm_user:{target_id}:users:0")],
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_ban:"))
async def adm_ban(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("Нельзя заблокировать самого себя", show_alert=True)
        return
    if await db_set_blocked(target_id, True):
        await db_audit(callback.from_user.id, "user_block", "user", target_id)
        await callback.answer("Заблокирован")
        try:
            await bot.send_message(target_id, "⛔ Доступ к боту ограничен. Обратитесь к администратору.")
        except Exception:
            pass
    else:
        await callback.answer("Пользователь не найден", show_alert=True)
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    if row:
        _, is_cert, is_mb = row_user_flags(row)
        await cleanup_chat(callback.from_user.id)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, True, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_unban:"))
async def adm_unban(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if await db_set_blocked(target_id, False):
        await db_audit(callback.from_user.id, "user_unblock", "user", target_id)
        await callback.answer("Разблокирован")
    else:
        await callback.answer("Пользователь не найден", show_alert=True)
    row = await db_get(target_id)
    is_pin = await db_is_pinned(callback.from_user.id, target_id)
    if row:
        _, is_cert, is_mb = row_user_flags(row)
        await cleanup_chat(callback.from_user.id)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await user_card_text(target_id, row, is_pin),
                           parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, False, is_pin,
                                                     is_certified=is_cert, is_medbook_valid=is_mb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_del:"))
async def adm_del_ask(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("Нельзя удалить самого себя", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"🗑 Удалить пользователя <code>{target_id}</code> из базы?\n\n"
                       f"Он сможет зарегистрироваться заново.",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="✅ Да, удалить",
                                                 callback_data=f"adm_del_yes:{target_id}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_users")],
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_del_yes:"))
async def adm_del_yes(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if await db_delete_user(target_id):
        await db_audit(callback.from_user.id, "user_delete", "user", target_id)
        await callback.answer("Удалён")
        await cleanup_chat(callback.from_user.id)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           f"🗑 Пользователь <code>{target_id}</code> удалён.",
                           parse_mode="HTML")
    else:
        await callback.answer("Пользователь не найден", show_alert=True)

@admin_router.callback_query(lambda c: c.data == "adm_rests")
async def adm_rests(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rests = await db_restaurants_all()
    chunk, page, pages = paginate(rests, 0, PAGE_RESTS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       rests_list_text(chunk, page, pages, len(rests)),
                       parse_mode="HTML", reply_markup=rests_list_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_rests_p:"))
async def adm_rests_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rests = await db_restaurants_all()
    chunk, page, pages = paginate(rests, page, PAGE_RESTS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       rests_list_text(chunk, page, pages, len(rests)),
                       parse_mode="HTML", reply_markup=rests_list_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("restadm:"))
async def rest_card_view(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    parts = callback.data.split(":")
    key = parts[1]
    source = parts[2] if len(parts) > 2 else "rests"
    page = safe_int(parts[3]) if len(parts) > 3 else 0
    r = await db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if not r:
        await send_tracked(cb_chat_id(callback), callback.from_user.id, "❌ Ресторан не найден.")
        return
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       await rest_card_text(r, source), parse_mode="HTML",
                       reply_markup=rest_card_kb(r, source, page))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("restset:"))
async def rest_set_status(callback: types.CallbackQuery):
    try:
        _, key, new_status = callback.data.split(":")
    except ValueError:
        await callback.answer("Данные устарели", show_alert=True)
        return
    if new_status == "auto":
        new_status = None
    if await db_restaurant_set_status(key, new_status):
        invalidate_rest_cache()
        await db_audit(callback.from_user.id, "rest_set_status", "restaurant", key, str(new_status))
        r = await db_restaurant(key)
        if r:
            await callback.answer("Статус обновлён")
            await cleanup_chat(callback.from_user.id)
            await send_tracked(cb_chat_id(callback), callback.from_user.id,
                               await rest_card_text(r), parse_mode="HTML",
                               reply_markup=rest_card_kb(r))
            return
    await callback.answer("Не удалось изменить статус", show_alert=True)

@admin_router.callback_query(lambda c: c.data and c.data.startswith("rest_tu:"))
async def rest_tu_pick(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    r = await db_restaurant(key)
    if not r:
        await callback.answer("Не найден", show_alert=True)
        return
    await callback.answer()
    tu_rows = await db_list_tu_candidates()
    if not tu_rows:
        await cleanup_chat(callback.from_user.id)
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "❕ Пока нет пользователей с должностью «Территориальный управляющий».\n"
                           "Назначь должность через карточку пользователя, затем вернись.",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                               [InlineKeyboardButton(text="⬅️ К ресторану",
                                                     callback_data=f"restadm:{key}")]
                           ]))
        return
    kb = [[InlineKeyboardButton(text=fn or f"ID {uid}",
                                callback_data=f"rest_tu_set:{key}:{uid}")]
          for uid, fn in tu_rows]
    if r.get("territory_manager_id"):
        kb.append([InlineKeyboardButton(text="🧹 Снять привязку",
                                        callback_data=f"rest_tu_clear:{key}")])
    kb.append([InlineKeyboardButton(text="⬅️ К ресторану", callback_data=f"restadm:{key}")])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"👔 Выбери ТУ для «{html.escape(r['name'])}»:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("rest_tu_set:"))
async def rest_tu_set(callback: types.CallbackQuery):
    try:
        _, key, uid = callback.data.split(":")
        uid = safe_int(uid)
    except ValueError:
        return
    if await db_restaurant_set_tu(key, uid):
        await db_audit(callback.from_user.id, "rest_set_tu", "restaurant", key, str(uid))
        await callback.answer("ТУ назначен")
    else:
        await callback.answer("Не удалось", show_alert=True)
        return
    r = await db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if r:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await rest_card_text(r), parse_mode="HTML",
                           reply_markup=rest_card_kb(r))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("rest_tu_clear:"))
async def rest_tu_clear(callback: types.CallbackQuery):
    key = callback.data.split(":")[1]
    if await db_restaurant_set_tu(key, None):
        await db_audit(callback.from_user.id, "rest_set_tu", "restaurant", key, "None")
        await callback.answer("Привязка снята")
    else:
        await callback.answer("Не удалось", show_alert=True)
        return
    r = await db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if r:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await rest_card_text(r), parse_mode="HTML",
                           reply_markup=rest_card_kb(r))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("restedit:"))
async def rest_edit_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        _, key, field = callback.data.split(":")
    except ValueError:
        return
    if field not in RESTAURANT_DB_FIELDS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    await state.set_state(RestEdit.value)
    await state.update_data(rest_key=key, rest_field=field)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"{FIELD_PROMPTS[field]}\n\nИли нажми «Отменить»:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отменить",
                                                 callback_data=f"restedit_cancel:{key}")]
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("restedit_cancel:"))
async def rest_edit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    key = callback.data.split(":")[1]
    r = await db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if r:
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           await rest_card_text(r), parse_mode="HTML",
                           reply_markup=rest_card_kb(r))

@admin_router.message(RestEdit.value)
async def rest_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    rest_key = data.get("rest_key")
    rest_field = data.get("rest_field")
    if not rest_key or not rest_field:
        await state.clear()
        return
    value = (message.text or "").strip()
    err = None
    coords_tuple = None

    if rest_field == "name":
        if len(value) < 2:
            err = "Название слишком короткое:"
    elif rest_field == "address":
        if len(value) < 5:
            err = "Адрес слишком короткий:"
    elif rest_field == "phone":
        if value.lower() in ("нет", "-", "—", ""):
            value = ""
        else:
            digits = value.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if not digits.isdigit() or len(digits) < 10:
                err = "Не похоже на номер. Пример: +79001234567. Или «нет»."
    elif rest_field == "hours":
        if not validate_hours_schedule(value):
            err = "Проверь формат. Пример:\nПн–чт: 10:00–22:00\nПт–вс: 10:00–23:00"
    elif rest_field == "org":
        if value.lower() in ("нет", "-", "—", ""):
            value = ""
    elif rest_field == "coords":
        try:
            parts = value.replace(";", ",").replace("  ", " ").split(",")
            if len(parts) != 2:
                raise ValueError
            lat = float(parts[0].strip())
            lon = float(parts[1].strip())
            if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
                raise ValueError
            if lat == 0 and lon == 0:
                raise ValueError
            coords_tuple = (round(lat, 6), round(lon, 6))
        except (ValueError, IndexError):
            err = ("Не похоже на координаты.\n"
                   "Формат: <code>55.7580, 37.6230</code>")

    if err:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, err)
        return

    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.clear()

    if rest_field == "coords":
        await db_restaurant_set_coords(rest_key, coords_tuple[0], coords_tuple[1])
        await db_audit(message.from_user.id, "rest_update", "restaurant", rest_key,
                       f"coords={coords_tuple[0]},{coords_tuple[1]}")
        shown = f"{coords_tuple[0]:.6f}, {coords_tuple[1]:.6f}"
    else:
        await db_restaurant_update(rest_key, rest_field, value)
        await db_audit(message.from_user.id, "rest_update", "restaurant", rest_key,
                       f"{rest_field}={value}")
        shown = value if value else "—"

    invalidate_rest_cache()
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ {FIELD_LABELS[rest_field]} обновлено: <b>{html.escape(shown)}</b>",
                       parse_mode="HTML")
    r = await db_restaurant(rest_key)
    if r:
        await send_tracked(message.chat.id, message.from_user.id,
                           await rest_card_text(r), parse_mode="HTML",
                           reply_markup=rest_card_kb(r))

@admin_router.callback_query(lambda c: c.data == "rest_add")
async def rest_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(RestAdd.name)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "🏪 <b>Новый ресторан</b>\n\n" + progress_bar(1, 5) +
                       "\n\nНазвание точки:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отменить", callback_data="adm_rests")]
                       ]))

@admin_router.message(RestAdd.name)
async def rest_add_name(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    name = (message.text or "").strip()
    if len(name) < 2:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком короткое. Ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(RestAdd.address)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(2, 5) + f"\n\nНазвание: <b>{html.escape(name)}</b> ✅\n\nАдрес:",
                       parse_mode="HTML")

@admin_router.message(RestAdd.address)
async def rest_add_address(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    addr = (message.text or "").strip()
    if len(addr) < 5:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком короткий адрес.")
        return
    await state.update_data(address=addr)
    await state.set_state(RestAdd.hours)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(3, 5) +
                       f"\n\nАдрес: <b>{html.escape(addr)}</b> ✅\n\nЧасы работы:\n"
                       f"Пример: <code>Пн–чт: 10:00–22:00\nПт–вс: 10:00–23:00</code>",
                       parse_mode="HTML")

@admin_router.message(RestAdd.hours)
async def rest_add_hours(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    hours = (message.text or "").strip()
    if not validate_hours_schedule(hours):
        await send_tracked(message.chat.id, message.from_user.id,
                           "Проверь формат. Пример:\nПн–чт: 10:00–22:00\nПт–вс: 10:00–23:00")
        return
    await state.update_data(hours=hours)
    await state.set_state(RestAdd.phone)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(4, 5) + "\n\nЧасы записаны ✅\n\nТелефон (или «нет»):")

@admin_router.message(RestAdd.phone)
async def rest_add_phone(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    value = (message.text or "").strip()
    if value.lower() in ("нет", "-", "—", ""):
        value = ""
    else:
        digits = value.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not digits.isdigit() or len(digits) < 10:
            await send_tracked(message.chat.id, message.from_user.id,
                               "Не похоже на номер. Или «нет».")
            return
    await state.update_data(phone=value)
    await state.set_state(RestAdd.org)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(5, 5) +
                       f"\n\nТелефон: <b>{html.escape(value or '—')}</b> ✅\n\n"
                       f"Ссылка на Яндекс Карты (например <code>vokker/1234567890</code>) или «нет»:",
                       parse_mode="HTML")

@admin_router.message(RestAdd.org)
async def rest_add_org(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    value = (message.text or "").strip()
    if value.lower() in ("нет", "-", "—", ""):
        value = ""
    await state.update_data(org=value)
    data = await state.get_data()
    await state.clear()
    name = data.get("name", "")
    key = slugify(name)
    ok = await db_restaurant_add(key, name, data.get("address", ""), data.get("hours", ""),
                                 data.get("phone", ""), data.get("org", ""))
    if not ok:
        await send_tracked(message.chat.id, message.from_user.id,
                           f"❌ Ключ <code>{key}</code> уже существует.", parse_mode="HTML")
        return
    invalidate_rest_cache()
    await db_audit(message.from_user.id, "rest_add", "restaurant", key, name)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Ресторан <b>{html.escape(name)}</b> добавлен (key: <code>{key}</code>)",
                       parse_mode="HTML")
    r = await db_restaurant(key)
    if r:
        await send_tracked(message.chat.id, message.from_user.id,
                           await rest_card_text(r), parse_mode="HTML",
                           reply_markup=rest_card_kb(r))
        await send_tracked(message.chat.id, message.from_user.id,
                           "💡 Совет: сразу задай координаты и назначь ТУ — "
                           "кнопки в карточке.",
                           parse_mode="HTML")

@admin_router.callback_query(lambda c: c.data and c.data.startswith("rest_del_ask:"))
async def rest_del_ask(callback: types.CallbackQuery):
    key = callback.data.split(":")[1]
    r = await db_restaurant(key)
    if not r:
        await callback.answer("Не найден", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"🗑 Удалить ресторан <b>{html.escape(r['name'])}</b>?\n\n"
                       f"Если к нему привязаны сотрудники — удалить не получится.",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="✅ Да", callback_data=f"rest_del_yes:{key}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data=f"restadm:{key}")]
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("rest_del_yes:"))
async def rest_del_yes(callback: types.CallbackQuery):
    key = callback.data.split(":")[1]
    ok, reason = await db_restaurant_delete(key)
    if not ok:
        if reason == "users_attached":
            await callback.answer("Сначала переназначь сотрудников", show_alert=True)
        else:
            await callback.answer("Не найден", show_alert=True)
        return
    invalidate_rest_cache()
    await db_audit(callback.from_user.id, "rest_delete", "restaurant", key)
    await callback.answer("Удалён")
    await cleanup_chat(callback.from_user.id)
    rests = await db_restaurants_all()
    chunk, page, pages = paginate(rests, 0, PAGE_RESTS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"🗑 Удалено.\n\n" + rests_list_text(chunk, page, pages, len(rests)),
                       parse_mode="HTML", reply_markup=rests_list_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data == "adm_positions")
async def adm_positions(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_positions_list(include_archived=True)
    active = [r for r in rows if not r[3]]
    archived = [r for r in rows if r[3]]
    lines = ["💼 <b>Должности</b>\n", f"Активных: {len(active)}"]
    for pid, name, sort, arch in active:
        lines.append(f"• {html.escape(name)}")
    if archived:
        lines.append(f"\n📦 Архив: {len(archived)}")
        for pid, name, sort, arch in archived:
            lines.append(f"• ~~{html.escape(name)}~~")
    kb = [[InlineKeyboardButton(text="➕ Добавить должность", callback_data="pos_add")]]
    for pid, name, sort, arch in active:
        kb.append([InlineKeyboardButton(text=f"📦 Архивировать «{html.escape(name[:20])}»",
                                        callback_data=f"pos_archive:{pid}")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data == "pos_add")
async def pos_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(PosAdmin.name)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "💼 Напиши название новой должности:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_positions")]
                       ]))

@admin_router.message(PosAdmin.name)
async def pos_add_do(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    name = (message.text or "").strip()
    if len(name) < 2:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко. Ещё раз:")
        return
    ok = await db_position_add(name)
    await state.clear()
    if not ok:
        await send_tracked(message.chat.id, message.from_user.id,
                           f"❌ Должность «{html.escape(name)}» уже существует.")
        return
    await db_audit(message.from_user.id, "pos_add", "position", "", name)
    await send_tracked(message.chat.id, message.from_user.id, f"✅ Должность «{html.escape(name)}» добавлена.")

@admin_router.callback_query(lambda c: c.data and c.data.startswith("pos_archive:"))
async def pos_archive(callback: types.CallbackQuery):
    pid = safe_int(callback.data.split(":")[1])
    if await db_position_archive(pid):
        await db_audit(callback.from_user.id, "pos_archive", "position", pid)
        await callback.answer("Архивирована")
    else:
        await callback.answer("Не найдена", show_alert=True)
    rows = await db_positions_list(include_archived=True)
    active = [r for r in rows if not r[3]]
    lines = ["💼 <b>Должности</b>\n", f"Активных: {len(active)}"]
    for p in active:
        lines.append(f"• {html.escape(p[1])}")
    kb = [[InlineKeyboardButton(text="➕ Добавить", callback_data="pos_add")]]
    for p in active:
        kb.append([InlineKeyboardButton(text=f"📦 «{html.escape(p[1][:20])}»",
                                        callback_data=f"pos_archive:{p[0]}")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data == "adm_news")
async def adm_news(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, 0, PAGE_NEWS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_news_p:"))
async def adm_news_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, page, PAGE_NEWS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_view:"))
async def news_view(callback: types.CallbackQuery):
    await callback.answer()
    news_id = safe_int(callback.data.split(":")[1])
    row = await db_get_news_full(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    nid, title, body, imp, lvl, created, published, publish_at = row
    lvl_label = LEVEL_LABELS.get(lvl, LEVEL_LABELS["normal"])
    date_str = created.strftime("%d.%m.%Y %H:%M") if created else "—"
    status = "✅ Опубликована" if published else f"⏰ Запланирована на {publish_at.strftime('%d.%m.%Y %H:%M') if publish_at else '—'}"
    text = (f"📰 <b>{html.escape(title)}</b>\n"
            f"{lvl_label} · {date_str}\n{status}\n"
            f"──────────────────────────────\n\n{html.escape(body)}")
    kb_rows = [
        [InlineKeyboardButton(text="✏️ Изменить заголовок",
                              callback_data=f"news_edit_title:{news_id}")],
        [InlineKeyboardButton(text="📢 Разослать", callback_data=f"news_send:{news_id}")],
    ]
    if published:
        kb_rows.append([InlineKeyboardButton(text="🗑 Удалить",
                                             callback_data=f"news_del:{news_id}")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ К новостям", callback_data="adm_news"),
                    InlineKeyboardButton(text="🏠 Меню", callback_data="adm_menu")])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id, text,
                       parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_edit_title:"))
async def news_edit_title_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    news_id = safe_int(callback.data.split(":")[1])
    row = await db_get_news_full(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    await state.set_state(NewsEditTitle.text)
    await state.update_data(news_id=news_id)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"✏️ Текущий заголовок: <b>{html.escape(row[1])}</b>\n\nПришли новый:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data=f"news_view:{news_id}")]
                       ]))

@admin_router.message(NewsEditTitle.text)
async def news_edit_title_do(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    title = (message.text or "").strip()
    if not title or len(title) > 100:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Заголовок 1–100 символов. Ещё раз:")
        return
    data = await state.get_data()
    news_id = data.get("news_id")
    await state.clear()
    await db_news_update_title(news_id, title)
    await db_audit(message.from_user.id, "news_edit_title", "news", news_id, title)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Заголовок обновлён: <b>{html.escape(title)}</b>", parse_mode="HTML")
    row = await db_get_news_full(news_id)
    if row:
        await send_tracked(message.chat.id, message.from_user.id,
                           f"📰 <b>{html.escape(row[1])}</b>\n{LEVEL_LABELS.get(row[4], LEVEL_LABELS['normal'])} · "
                           + ("✅ Опубликована" if row[6] else "⏰ Запланирована"),
                           parse_mode="HTML",
                           reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                               [InlineKeyboardButton(text="⬅️ К новостям", callback_data="adm_news")]
                           ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_del:"))
async def news_del(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    if await db_delete_news(news_id):
        await db_audit(callback.from_user.id, "news_delete", "news", news_id)
        await callback.answer("Удалена")
    else:
        await callback.answer("Не найдена", show_alert=True)
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, 0, PAGE_NEWS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data == "news_add")
async def news_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(NewsAdmin.title)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "✍️ <b>Новая новость</b>\n\n" + progress_bar(1, 4) +
                       "\n\nНапиши заголовок:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_news")]
                       ]))

@admin_router.message(NewsAdmin.title)
async def news_add_title(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    if not message.text:
        await send_tracked(message.chat.id, message.from_user.id, "Заголовок текстом.")
        return
    title = message.text.strip()
    if len(title) > 100:
        await send_tracked(message.chat.id, message.from_user.id, "Максимум 100 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(NewsAdmin.body)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(2, 4) + f"\n\nЗаголовок: <b>{html.escape(title)}</b> ✅\n\nТекст новости:",
                       parse_mode="HTML")

@admin_router.message(NewsAdmin.body)
async def news_add_body(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    if not message.text:
        await send_tracked(message.chat.id, message.from_user.id, "Текст текстом.")
        return
    body = message.text.strip()
    if len(body) > 2000:
        await send_tracked(message.chat.id, message.from_user.id, "Максимум 2000 символов.")
        return
    await state.update_data(body=body)
    await state.set_state(NewsAdmin.important)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(3, 4) + "\n\nТекст записан ✅\n\nПометка:",
                       parse_mode="HTML", reply_markup=news_important_kb())

@admin_router.callback_query(NewsAdmin.important, lambda c: c.data and c.data.startswith("news_imp:"))
async def news_schedule_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    level = callback.data.split(":")[1]
    if level not in LEVEL_LABELS:
        level = "normal"
    await state.update_data(level=level)
    await state.set_state(NewsAdmin.schedule_choice)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       progress_bar(4, 4) + "\n\nКогда опубликовать?",
                       parse_mode="HTML", reply_markup=news_schedule_kb())

@admin_router.callback_query(NewsAdmin.schedule_choice, lambda c: c.data == "news_sched_now")
async def news_sched_now(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(publish_at=None, publish_display=None)
    await state.set_state(NewsAdmin.preview)
    await _show_news_preview(cb_chat_id(callback), callback.from_user.id, state)

@admin_router.callback_query(NewsAdmin.schedule_choice, lambda c: c.data == "news_sched_later")
async def news_sched_later(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(NewsAdmin.schedule_time)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "⏰ Введи дату и время:\n\n"
                       "Формат: <code>ДД.ММ.ГГГГ ЧЧ:ММ</code>\n"
                       "Пример: <code>25.11.2026 09:00</code>\n\n"
                       "В назначенное время новость появится в приложении "
                       "и автоматически разошлётся сотрудникам.",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_news")]
                       ]))

@admin_router.message(NewsAdmin.schedule_time)
async def news_sched_time(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    raw = (message.text or "").strip()
    try:
        dt = datetime.strptime(raw, "%d.%m.%Y %H:%M")
    except ValueError:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Не получилось. Формат: ДД.ММ.ГГГГ ЧЧ:ММ\nПример: 25.11.2026 09:00")
        return
    if dt <= _moscow_now().replace(tzinfo=None):
        await send_tracked(message.chat.id, message.from_user.id,
                           "Дата уже прошла. Введи будущую:")
        return
    iso = dt.replace(tzinfo=MOSCOW_TZ).isoformat() if MOSCOW_TZ else dt.isoformat()
    await state.update_data(publish_at=iso, publish_display=dt.strftime("%d.%m.%Y %H:%M"))
    await state.set_state(NewsAdmin.preview)
    await _show_news_preview(message.chat.id, message.from_user.id, state)

async def _show_news_preview(chat_id, user_id, state):
    data = await state.get_data()
    title = data.get("title", "")
    body = data.get("body", "")
    level = data.get("level", "normal")
    publish_display = data.get("publish_display")
    icon = LEVEL_LABELS.get(level, LEVEL_LABELS["normal"])
    if publish_display:
        sched = f"\n\n⏰ <b>{publish_display}</b>\n<i>В это время разошлётся всем.</i>"
    else:
        sched = "\n\n📤 Публикуется сейчас."
    await cleanup_chat(user_id)
    await send_tracked(chat_id, user_id,
                       f"👀 <b>Превью</b>:\n\n{icon} <b>{html.escape(title)}</b>\n\n{html.escape(body)}{sched}\n\n<i>Опубликовать?</i>",
                       parse_mode="HTML", reply_markup=news_preview_kb())

@admin_router.callback_query(NewsAdmin.preview, lambda c: c.data == "news_pub")
async def news_publish(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    title = data.get("title", "")
    body = data.get("body", "")
    level = data.get("level", "normal")
    publish_at = data.get("publish_at")
    publish_display = data.get("publish_display")
    await state.clear()
    try:
        news_id = await db_add_news(title, body, level, publish_at=publish_at)
        await db_audit(callback.from_user.id, "news_add", "news", news_id,
                       f"{title} | {'sched ' + str(publish_display) if publish_at else 'now'}")
    except Exception as e:
        logging.error(f"news_add: {e}")
        await send_tracked(cb_chat_id(callback), callback.from_user.id,
                           "❌ Ошибка сохранения.")
        return
    head = (f"⏰ Отложено до <b>{publish_display}</b>."
            if publish_at else "✅ Опубликовано!")
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"{head}\n\n{LEVEL_LABELS[level]} — <b>{html.escape(title)}</b>",
                       parse_mode="HTML")
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, 0, PAGE_NEWS)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))

@admin_router.callback_query(NewsAdmin.preview, lambda c: c.data == "news_restart")
async def news_add_restart(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Заново")
    await state.clear()
    await state.set_state(NewsAdmin.title)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "✍️ Заголовок заново:")

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_send:"))
async def news_send_menu(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "📬 Кому разослать?",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="🌍 Всем сотрудникам",
                                                 callback_data=f"news_ask_all:{news_id}")],
                           [InlineKeyboardButton(text="📍 Одному ресторану",
                                                 callback_data=f"news_send_rest:{news_id}")],
                           [InlineKeyboardButton(text="🔙 К новостям", callback_data="adm_news")],
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_ask_all:"))
async def news_ask_all(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    row = await db_get_news(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    title, body, level = row
    n = len(await db_list_active_users())
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"📬 Разослать «<b>{html.escape(title)}</b>» на <b>{n}</b> сотрудников?",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text=f"✅ Да ({n})",
                                                 callback_data=f"news_confirm_all:{news_id}")],
                           [InlineKeyboardButton(text="📤 Сначала мне",
                                                 callback_data=f"news_test:{news_id}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_news")],
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_confirm_all:"))
async def news_confirm_all(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    row = await db_get_news(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    lock = f"all:{news_id}"
    if not try_lock_broadcast(lock):
        await callback.answer("Рассылка уже идёт", show_alert=True)
        return
    title, body, level = row
    await callback.answer("Рассылка запущена")
    await db_audit(callback.from_user.id, "broadcast_all", "news", news_id, title)

    async def _run():
        try:
            await broadcast_news(title, body, level)
        finally:
            unlock_broadcast(lock)

    spawn(_run(), name=f"broadcast_all_{news_id}")
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"✅ Рассылка «{html.escape(title)}» запущена.")

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_test:"))
async def news_test(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    row = await db_get_news(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    title, body, level = row
    icon = LEVEL_LABELS.get(level, LEVEL_LABELS["normal"])
    try:
        await bot.send_message(
            cb_chat_id(callback),
            f"{icon} <b>{html.escape(title)}</b>\n\n{html.escape(body)}\n\n<i>(тест)</i>",
            parse_mode="HTML")
        await callback.answer("Отправлено")
    except Exception as e:
        await callback.answer(f"Ошибка: {type(e).__name__}", show_alert=True)

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_send_rest:"))
async def news_send_rest(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    await callback.answer()
    kb = [[InlineKeyboardButton(text=r["name"],
                                 callback_data=f"news_ask_rest:{news_id}:{r['key']}")]
          for r in await db_restaurants_all()]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"news_send:{news_id}")])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "📍 Выбери ресторан:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_ask_rest:"))
async def news_ask_rest(callback: types.CallbackQuery):
    try:
        _, news_id, key = callback.data.split(":", 2)
        news_id = safe_int(news_id)
    except ValueError:
        return
    row = await db_get_news(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    title, body, level = row
    names = await restaurant_names_map()
    rest_name = names.get(key, key)
    n = len(await db_list_active_users(key))
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"📬 Разослать «<b>{html.escape(title)}</b>» сотрудникам «<b>{html.escape(rest_name)}</b>» ({n})?",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text=f"✅ Да ({n})",
                                                 callback_data=f"news_confirm_rest:{news_id}:{key}")],
                           [InlineKeyboardButton(text="📤 Сначала мне",
                                                 callback_data=f"news_test:{news_id}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_news")],
                       ]))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_confirm_rest:"))
async def news_confirm_rest(callback: types.CallbackQuery):
    try:
        _, news_id, key = callback.data.split(":", 2)
        news_id = safe_int(news_id)
    except ValueError:
        return
    row = await db_get_news(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    lock = f"rest:{news_id}:{key}"
    if not try_lock_broadcast(lock):
        await callback.answer("Рассылка уже идёт", show_alert=True)
        return
    title, body, level = row
    names = await restaurant_names_map()
    rest_name = names.get(key, key)
    await callback.answer("Рассылка запущена")
    await db_audit(callback.from_user.id, "broadcast_rest", "news", news_id, f"{title} → {key}")

    async def _run():
        try:
            await broadcast_news(title, body, level, restaurant_key=key)
        finally:
            unlock_broadcast(lock)

    spawn(_run(), name=f"broadcast_rest_{news_id}_{key}")
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"✅ Рассылка для «{html.escape(rest_name)}» запущена.")

STD_FIELDS = {
    "title": ("Название", "✏️ Напиши новое название стандарта:"),
    "category": ("Категория", "✏️ Напиши новую категорию:"),
    "description": ("Описание", "✏️ Напиши новое описание:"),
    "url": ("Ссылка", "✏️ Пришли ссылку (или «нет»):"),
}

@admin_router.callback_query(lambda c: c.data == "adm_std")
async def adm_std(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, 0, PAGE_STD)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       std_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=std_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_std_p:"))
async def adm_std_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, page, PAGE_STD)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       std_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=std_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("std_card:"))
async def std_card_view(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    sid = safe_int(callback.data.split(":")[1])
    rows = [r for r in await db_list_standards() if r[0] == sid]
    await cleanup_chat(callback.from_user.id)
    if not rows:
        await send_tracked(cb_chat_id(callback), callback.from_user.id, "❌ Не найден.")
        return
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       std_card_text(rows[0]), parse_mode="HTML", reply_markup=std_card_kb(sid))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("std_edit:"))
async def std_edit_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        _, sid, field = callback.data.split(":")
        sid = safe_int(sid)
    except ValueError:
        return
    if field not in STD_FIELDS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    await state.set_state(StdEdit.value)
    await state.update_data(std_id=sid, std_field=field)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"{STD_FIELDS[field][1]}\n\nИли нажми «Отменить»:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отменить", callback_data=f"std_card:{sid}")]
                       ]))

@admin_router.message(StdEdit.value)
async def std_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    sid, field = data.get("std_id"), data.get("std_field")
    if sid is None or field not in STD_FIELDS:
        await state.clear()
        return
    value = (message.text or "").strip()
    if field == "url":
        if value.lower() in ("нет", "-", "—", ""):
            value = ""
        elif not URL_RE.match(value):
            await delete_incoming(message); await cleanup_chat(message.from_user.id)
            await send_tracked(message.chat.id, message.from_user.id,
                               "Ссылка должна начинаться с http:// или https://")
            return
    elif len(value) < 2:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко.")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.clear()
    await db_update_standard(sid, field, value)
    await db_audit(message.from_user.id, "std_update", "standard", sid, f"{field}={value}")
    rows = [r for r in await db_list_standards() if r[0] == sid]
    if rows:
        await send_tracked(message.chat.id, message.from_user.id,
                           "✅ Обновлено.\n\n" + std_card_text(rows[0]),
                           parse_mode="HTML", reply_markup=std_card_kb(sid))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("std_del:"))
async def std_del(callback: types.CallbackQuery):
    sid = safe_int(callback.data.split(":")[1])
    await db_delete_standard(sid)
    await db_audit(callback.from_user.id, "std_delete", "standard", sid)
    await callback.answer("Удалено")
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, 0, PAGE_STD)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       std_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=std_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data == "std_add")
async def std_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(StdAdmin.title)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "📚 Новый стандарт.\n" + progress_bar(1, 3) + "\n\nНазвание:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_std")]
                       ]))

@admin_router.message(StdAdmin.title)
async def std_add_title(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    title = (message.text or "").strip()
    if len(title) < 3:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко.")
        return
    await state.update_data(title=title)
    await state.set_state(StdAdmin.category)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(2, 3) + f"\n\nНазвание: <b>{html.escape(title)}</b> ✅\n\nКатегория:",
                       parse_mode="HTML")

@admin_router.message(StdAdmin.category)
async def std_add_category(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    category = (message.text or "").strip()
    await state.update_data(category=category)
    await state.set_state(StdAdmin.description)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(3, 3) + f"\n\nКатегория: <b>{html.escape(category)}</b> ✅\n\nОписание:",
                       parse_mode="HTML")

@admin_router.message(StdAdmin.description)
async def std_add_desc(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    description = (message.text or "").strip()
    if len(description) < 5:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко.")
        return
    data = await state.get_data()
    await state.clear()
    await db_add_standard(data.get("title", ""), data.get("category", ""), description)
    await db_audit(message.from_user.id, "std_add", "standard", "", data.get("title", ""))
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Стандарт добавлен: <b>{html.escape(data.get('title'))}</b>", parse_mode="HTML")
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, 0, PAGE_STD)
    await send_tracked(message.chat.id, message.from_user.id,
                       std_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=std_admin_kb(chunk, page, pages))

FAQ_FIELDS = {
    "question": ("Вопрос", "✏️ Напиши новый текст вопроса:"),
    "answer": ("Ответ", "✏️ Напиши новый текст ответа:"),
}

@admin_router.callback_query(lambda c: c.data == "adm_faq")
async def adm_faq(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_faq()
    chunk, page, pages = paginate(rows, 0, PAGE_FAQ)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       faq_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=faq_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_faq_p:"))
async def adm_faq_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_faq()
    chunk, page, pages = paginate(rows, page, PAGE_FAQ)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       faq_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=faq_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("faq_edit_show:"))
async def faq_card_view(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    fid = safe_int(callback.data.split(":")[1])
    rows = [r for r in await db_list_faq() if r[0] == fid]
    await cleanup_chat(callback.from_user.id)
    if not rows:
        await send_tracked(cb_chat_id(callback), callback.from_user.id, "❌ Не найден.")
        return
    _, question, answer, _ = rows[0]
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"❓ <b>{html.escape(question)}</b>\n\n💬 {html.escape(answer)}",
                       parse_mode="HTML", reply_markup=faq_card_kb(fid))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("faq_edit:"))
async def faq_edit_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        _, fid, field = callback.data.split(":")
        fid = safe_int(fid)
    except ValueError:
        return
    if field not in FAQ_FIELDS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    await state.set_state(FaqEdit.value)
    await state.update_data(faq_id=fid, faq_field=field)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       f"{FAQ_FIELDS[field][1]}\n\nИли нажми «Отменить»:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отменить", callback_data=f"faq_edit_show:{fid}")]
                       ]))

@admin_router.message(FaqEdit.value)
async def faq_edit_value(message: types.Message, state: FSMContext):
    data = await state.get_data()
    fid, field = data.get("faq_id"), data.get("faq_field")
    if fid is None or field not in FAQ_FIELDS:
        await state.clear()
        return
    value = (message.text or "").strip()
    if len(value) < 3:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко.")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.clear()
    await db_update_faq(fid, field, value)
    await db_audit(message.from_user.id, "faq_update", "faq", fid, f"{field}={value}")
    rows = [r for r in await db_list_faq() if r[0] == fid]
    if rows:
        _, question, answer, _ = rows[0]
        await send_tracked(message.chat.id, message.from_user.id,
                           f"✅ Обновлено.\n\n❓ <b>{html.escape(question)}</b>\n\n💬 {html.escape(answer)}",
                           parse_mode="HTML", reply_markup=faq_card_kb(fid))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("faq_del:"))
async def faq_del(callback: types.CallbackQuery):
    fid = safe_int(callback.data.split(":")[1])
    await db_delete_faq(fid)
    await db_audit(callback.from_user.id, "faq_delete", "faq", fid)
    await callback.answer("Удалено")
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_faq()
    chunk, page, pages = paginate(rows, 0, PAGE_FAQ)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       faq_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=faq_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data == "faq_add")
async def faq_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(FaqAdmin.question)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       "❓ Новый вопрос.\n" + progress_bar(1, 2) + "\n\nТекст вопроса:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_faq")]
                       ]))

@admin_router.message(FaqAdmin.question)
async def faq_add_question(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    question = (message.text or "").strip()
    if len(question) < 5:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко.")
        return
    await state.update_data(question=question)
    await state.set_state(FaqAdmin.answer)
    await send_tracked(message.chat.id, message.from_user.id,
                       progress_bar(2, 2) + f"\n\nВопрос: <b>{html.escape(question)}</b> ✅\n\nОтвет:",
                       parse_mode="HTML")

@admin_router.message(FaqAdmin.answer)
async def faq_add_answer(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    answer = (message.text or "").strip()
    if len(answer) < 3:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко.")
        return
    data = await state.get_data()
    await state.clear()
    await db_add_faq(data.get("question", ""), answer)
    await db_audit(message.from_user.id, "faq_add", "faq", "", data.get("question", ""))
    await send_tracked(message.chat.id, message.from_user.id, "✅ Вопрос добавлен.")
    rows = await db_list_faq()
    chunk, page, pages = paginate(rows, 0, PAGE_FAQ)
    await send_tracked(message.chat.id, message.from_user.id,
                       faq_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=faq_admin_kb(chunk, page, pages))

@admin_router.callback_query(lambda c: c.data == "adm_reports")
async def adm_reports(callback: types.CallbackQuery):
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    stats = await get_report_stats()
    rows = await db_list_users()
    names = await restaurant_names_map()
    positions_count, restaurants_count = {}, {}
    for r in rows:
        if r[1]:
            positions_count[r[3] or "Не указана"] = positions_count.get(r[3] or "Не указана", 0) + 1
            rn = names.get(r[4], r[4]) if r[4] else "Не указан"
            restaurants_count[rn] = restaurants_count.get(rn, 0) + 1
    pos_block = "\n".join(f"• {html.escape(k)}: {v}" for k, v in
                          sorted(positions_count.items(), key=lambda x: -x[1])) or "• нет данных"
    rest_block = "\n".join(f"• {html.escape(k)}: {v}" for k, v in
                           sorted(restaurants_count.items(), key=lambda x: -x[1])) or "• нет данных"
    text = (f"📊 <b>Отчёт</b> ({stats['date']})\n\n"
            f"👥 Всего: {stats['total']}\n✅ Активных: {stats['active']}\n"
            f"🚫 Заблокированных: {stats['blocked']}\n"
            f"📈 Новых за 7 дней: {stats['new7']}\n💤 Не заходили: {stats['inactive7']}\n\n"
            f"<b>По должностям:</b>\n{pos_block}\n\n<b>По ресторанам:</b>\n{rest_block}")
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       text, parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="📤 Экспорт пользователей (CSV)",
                                                 callback_data="adm_export_users")],
                           [InlineKeyboardButton(text="📤 Экспорт новостей (CSV)",
                                                 callback_data="adm_export_news")],
                           [InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")],
                       ]))

@admin_router.callback_query(lambda c: c.data == "adm_export_users")
async def adm_export_users(callback: types.CallbackQuery):
    await callback.answer("Формирую CSV...")
    rows = await db_list_users()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "full_name", "phone", "position", "restaurant", "is_blocked", "welcomed"])
    for uid, fn, phone, pos, rest, wel, blk in rows:
        writer.writerow([uid, fn or "", phone or "", pos or "", rest or "",
                         "yes" if blk else "no", "yes" if wel else "no"])
    data = output.getvalue().encode("utf-8-sig")
    fname = f"users_{_moscow_now().strftime('%Y%m%d_%H%M')}.csv"
    try:
        await bot.send_document(callback.from_user.id,
                                BufferedInputFile(data, filename=fname),
                                caption=f"📤 Пользователи · {len(rows)}")
    except Exception as e:
        logging.warning(f"export: {type(e).__name__}")
        await send_tracked(cb_chat_id(callback), callback.from_user.id, f"❌ {type(e).__name__}")

@admin_router.callback_query(lambda c: c.data == "adm_export_news")
async def adm_export_news(callback: types.CallbackQuery):
    await callback.answer("Формирую CSV...")
    rows = await db_list_news_admin()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "title", "body", "level", "created_at", "published", "publish_at"])
    for row in rows:
        nid, title, body, imp, lvl, created = row[0], row[1], row[2], row[3], row[4], row[5]
        published = row[6] if len(row) > 6 else True
        publish_at = row[7] if len(row) > 7 else None
        writer.writerow([nid, title, body, lvl or "normal",
                         created.strftime("%d.%m.%Y %H:%M") if created else "",
                         "yes" if published else "no",
                         publish_at.strftime("%d.%m.%Y %H:%M") if publish_at else ""])
    data = output.getvalue().encode("utf-8-sig")
    fname = f"news_{_moscow_now().strftime('%Y%m%d_%H%M')}.csv"
    try:
        await bot.send_document(callback.from_user.id,
                                BufferedInputFile(data, filename=fname),
                                caption=f"📤 Новости · {len(rows)}")
    except Exception as e:
        logging.warning(f"export news: {type(e).__name__}")
        await send_tracked(cb_chat_id(callback), callback.from_user.id, f"❌ {type(e).__name__}")

@admin_router.callback_query(lambda c: c.data == "adm_audit")
async def adm_audit(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_audit_list(limit=200)
    chunk, page, pages = paginate(rows, 0, PAGE_AUDIT)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       audit_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=audit_kb(page, pages))

@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_audit_p:"))
async def adm_audit_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_audit_list(limit=200)
    chunk, page, pages = paginate(rows, page, PAGE_AUDIT)
    await send_tracked(cb_chat_id(callback), callback.from_user.id,
                       audit_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=audit_kb(page, pages))

def audit_text(rows, page, pages, total):
    if not rows:
        return "📜 История пуста."
    lines = [f"📜 <b>Последние действия</b> · стр. {page+1}/{pages}\n"]
    for aid, admin_id, action, tt, ti, details, created in rows:
        date = created.strftime("%d.%m %H:%M") if created else ""
        d = html.escape((details or "")[:60])
        lines.append(f"<code>{date}</code> · {html.escape(action or '')} · "
                     f"{html.escape(tt or '')}:{html.escape(ti or '')} · {d}")
    return "\n".join(lines)

def audit_kb(page, pages):
    kb = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_audit_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_audit_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def birthday_checker():
    while True:
        try:
            now = _moscow_now()
            year = now.year
            today_md = f"{now.day:02d}.{now.month:02d}"
            candidates = await db_birthday_candidates(today_md)
            for user_id, full_name, first_name in candidates:
                if await db_already_greeted(user_id, "birthday", year):
                    continue
                name = first_name or (full_name.split()[0] if full_name else "коллега")
                try:
                    await bot.send_message(
                        user_id,
                        f"🎂 <b>{html.escape(name)}, с Днём рождения!</b>\n\n"
                        "Команда Wokker поздравляет тебя! Пусть год будет лёгким, "
                        "смены — удачными, а гости — благодарными.\nХорошего праздника! 🥳",
                        parse_mode="HTML")
                    await db_mark_greeted(user_id, "birthday", year)
                except TelegramForbiddenError:
                    await db_mark_bot_blocked(user_id)
                except Exception as e:
                    logging.warning(f"birthday {user_id}: {e}")
        except Exception as e:
            logging.error(f"birthday_checker: {e}")
        await asyncio.sleep(3600)

async def holiday_broadcaster():
    while True:
        try:
            now = _moscow_now()
            hol = HOLIDAYS.get((now.month, now.day))
            if hol:
                kind = f"holiday:{now.month:02d}-{now.day:02d}"
                if not await db_holiday_broadcast_done(kind, now.year):
                    title, text = hol
                    sent = 0
                    for user_id in await db_list_active_users():
                        try:
                            first_name = await db_get_first_name(user_id) or "коллега"
                            await bot.send_message(user_id, f"{title}\n\n{html.escape(first_name)}, {text}")
                            sent += 1
                        except TelegramForbiddenError:
                            await db_mark_bot_blocked(user_id)
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                    await db_mark_holiday_broadcast(kind, now.year)
                    logging.info(f"holiday {kind}: {sent}")
        except Exception as e:
            logging.error(f"holiday_broadcaster: {e}")
        await asyncio.sleep(3600)

async def scheduled_publisher():
    while True:
        try:
            due = await db_publish_due()
            for news_id, title, body, level, auto_b in due:
                logging.info(f"📤 Опубликована отложенная #{news_id}: {title}")
                if auto_b:
                    try:
                        await broadcast_news(title, body, level)
                    except Exception as e:
                        logging.warning(f"scheduled bc {news_id}: {e}")
                if ADMIN_ID:
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"⏰ Отложенная новость опубликована:\n\n"
                            f"{LEVEL_LABELS.get(level, LEVEL_LABELS['normal'])} <b>{html.escape(title)}</b>\n"
                            + ("📤 Рассылка запущена автоматически." if auto_b else ""))
                    except Exception:
                        pass
        except Exception as e:
            logging.error(f"scheduled_publisher: {e}")
        await asyncio.sleep(60)

def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)

def denied_response(status: int):
    if status == 403:
        return web.json_response({"error": "blocked"}, status=403, dumps=json_dumps)
    return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)

AVATAR_CACHE = {}
AVATAR_TTL = 3600
AVATAR_MAX_BYTES = 5 * 1024 * 1024

def avatar_cache_get(user_id):
    entry = AVATAR_CACHE.get(user_id)
    if not entry:
        return None
    data, ctype, saved_at = entry
    if datetime.now().timestamp() - saved_at > AVATAR_TTL:
        AVATAR_CACHE.pop(user_id, None)
        return None
    return data, ctype

def _guess_image_ctype(data: bytes) -> str:
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:2] == b"GIF":
        return "image/gif"
    return "image/jpeg"

async def handle_favicon(request):
    return web.Response(status=204)

_INDEX_CACHE = {"data": None, "mtime": 0.0}

async def handle_index(request):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "index.html")
    if not os.path.exists(p):
        return web.Response(text="frontend/index.html not found", status=404)
    try:
        mtime = os.stat(p).st_mtime
    except OSError:
        return web.Response(text="frontend/index.html not found", status=404)

    if _INDEX_CACHE["data"] is None or _INDEX_CACHE["mtime"] != mtime:
        try:
            with open(p, "rb") as f:
                _INDEX_CACHE["data"] = f.read()
            _INDEX_CACHE["mtime"] = mtime
        except OSError:
            return web.Response(text="frontend/index.html not found", status=404)

    etag = f'W/"{int(mtime * 1000)}"'
    cache_headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=300, stale-while-revalidate=3600",
        "Vary": "Accept-Encoding",
    }
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=cache_headers)

    return web.Response(
        body=_INDEX_CACHE["data"],
        content_type="text/html",
        charset="utf-8",
        headers=cache_headers,
    )

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
        phone = user_row[1]
        birth_date = user_row[2]
        position = user_row[3]
        restaurant = user_row[4]
        first_name = user_row[7] if len(user_row) > 7 else None
        is_certified = bool(user_row[8]) if len(user_row) > 8 else False
        is_medbook_valid = bool(user_row[9]) if len(user_row) > 9 else False
        profile = {
            "full_name": full_name,
            "first_name": first_name or (full_name.split()[0] if full_name else ""),
            "phone": phone, "birth_date": birth_date,
            "position": position or "—",
            "restaurant": rest_map.get(restaurant, restaurant) if restaurant else "—",
            "restaurant_key": restaurant or "",
            "is_certified": is_certified,
            "is_medbook_valid": is_medbook_valid,
        }
    now = _moscow_now()
    kind, title, sub = greeting_for_user(user_row[2] if user_row else None, now)
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
                "full_name": fn or "",
                "position": pos or "",
                "phone": ph or "",
                "is_certified": bool(cert),
                "is_medbook_valid": bool(mb),
                "restaurant_key": rkey or "",
                "restaurant_name": rname or "",
                "manager_name": mname or "",
            })
    return web.json_response({
        "profile": profile,
        "greeting": {"kind": kind, "title": title, "sub": sub},
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

async def handle_greeting(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    row = await db_get(user_id)
    kind, title, sub = greeting_for_user(row[2] if row else None)
    return web.json_response({"kind": kind, "title": title, "sub": sub}, dumps=json_dumps)

async def handle_news(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    news_list = [{"id": nid, "title": t, "text": b,
                  "date": d.strftime("%d.%m.%Y") if d else "",
                  "important": bool(imp), "level": lv or "normal"}
                 for nid, t, b, imp, lv, d in await db_list_news()]
    return web.json_response(news_list, dumps=json_dumps)

async def handle_standards(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    data = [{"id": sid, "title": t, "category": c, "description": d, "url": u}
            for sid, t, c, d, u in await db_list_standards()]
    return web.json_response(data, dumps=json_dumps)

async def handle_faq(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    data = [{"id": fid, "question": q, "answer": a, "category": c}
            for fid, q, a, c in await db_list_faq()]
    return web.json_response(data, dumps=json_dumps)

async def handle_profile(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    row = await db_get(user_id)
    if not row or not row[0]:
        return web.json_response({"registered": False}, dumps=json_dumps)
    full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row[:7]
    is_certified = bool(row[7]) if len(row) > 7 else False
    is_medbook_valid = bool(row[8]) if len(row) > 8 else False
    names = await restaurant_names_map()
    return web.json_response({
        "registered": True,
        "profile": {
            "full_name": full_name,
            "first_name": await db_get_first_name(user_id) or (full_name.split()[0] if full_name else ""),
            "phone": phone, "birth_date": birth_date,
            "position": position or "—",
            "restaurant": names.get(restaurant, restaurant) if restaurant else "—",
            "restaurant_key": restaurant or "",
            "is_certified": is_certified,
            "is_medbook_valid": is_medbook_valid,
            "tg_id": user_id,
        },
    }, dumps=json_dumps)

async def handle_avatar(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    cached = avatar_cache_get(user_id)
    if cached:
        data, ctype = cached
        return web.Response(body=data, content_type=ctype)
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if not photos.total_count:
            return web.Response(status=204)
        file = await bot.get_file(photos.photos[0][-1].file_id)
        if file.file_size and file.file_size > AVATAR_MAX_BYTES:
            return web.Response(status=204)
        data = await bot.download(file)
        if not data or len(data) > AVATAR_MAX_BYTES:
            return web.Response(status=204)
        ctype = _guess_image_ctype(data)
        AVATAR_CACHE[user_id] = (data, ctype, datetime.now().timestamp())
        return web.Response(body=data, content_type=ctype)
    except TelegramRetryAfter as e:
        logging.warning(f"avatar {user_id}: rate limited {e.retry_after}s")
        return web.Response(status=204)
    except TelegramBadRequest as e:
        logging.warning(f"avatar {user_id}: bad request {type(e).__name__}")
        return web.Response(status=204)
    except Exception as e:
        logging.warning(f"avatar {user_id}: {type(e).__name__}")
        return web.Response(status=204)

_questions_rate = {}
_questions_last_cleanup = [0.0]
_QUESTIONS_COOLDOWN = 60

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

    now_ts = time.time()
    if now_ts - _questions_last_cleanup[0] > 300:
        _questions_last_cleanup[0] = now_ts
        cutoff = now_ts - 300
        for k in [k for k, v in _questions_rate.items() if v < cutoff]:
            del _questions_rate[k]
    if now_ts - _questions_rate.get(user_id, 0) < _QUESTIONS_COOLDOWN:
        return web.json_response({"error": "too_fast"}, status=429, dumps=json_dumps)
    _questions_rate[user_id] = now_ts

    try:
        qid = await db_question_add(user_id, qtext)
    except Exception as e:
        logging.error(f"question add failed: {type(e).__name__}")
        return web.json_response({"error": "db_error"}, status=500, dumps=json_dumps)

    if ADMIN_ID:
        row = await db_get(user_id)
        who = html.escape(row[0]) if row and row[0] else "—"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"question_reply:{qid}"),
             InlineKeyboardButton(text="📋 Профиль", callback_data=f"adm_user:{user_id}:questions:0")],
            [InlineKeyboardButton(text="🚫 Блок", callback_data=f"adm_ban_ask:{user_id}")],
        ])
        try:
            await bot.send_message(
                ADMIN_ID,
                f"❓ <b>Вопрос из приложения</b>\n\n"
                f"👤 {who} (<code>{user_id}</code>)\n💬 {html.escape(qtext)}",
                parse_mode="HTML", reply_markup=kb)
        except Exception as e:
            logging.warning(f"question to admin: {type(e).__name__}")
    return web.json_response({"ok": True}, dumps=json_dumps)

_auth_rate = {}
_auth_last_cleanup = [0.0]

async def handle_auth_request(request):
    try:
        payload = await request.json()
        phone = payload.get("phone", "").strip()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)

    if not phone:
        return web.json_response({"error": "phone_required"}, status=400, dumps=json_dumps)

    now_ts = time.time()
    if now_ts - _auth_last_cleanup[0] > 300:
        _auth_last_cleanup[0] = now_ts
        cutoff = now_ts - 300
        for k in [k for k, v in _auth_rate.items() if v < cutoff]:
            del _auth_rate[k]

    digits = re.sub(r'\D', '', phone)
    if now_ts - _auth_rate.get(digits, 0) < 60:
        return web.json_response({"error": "too_fast"}, status=429, dumps=json_dumps)
    _auth_rate[digits] = now_ts

    res = await db_request_web_code(phone)
    if not res:
        return web.json_response({"error": "not_found"}, status=404, dumps=json_dumps)

    user_id, code = res
    try:
        await bot.send_message(
            user_id,
            f"🔐 <b>Код для входа на сайт:</b>\n\n<code>{code}</code>\n\n<i>Никому не сообщайте. Код действует 10 минут.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logging.warning(f"auth bot send failed: {e}")
        return web.json_response({"error": "bot_blocked"}, status=400, dumps=json_dumps)

    return web.json_response({"ok": True}, dumps=json_dumps)

async def handle_auth_verify(request):
    try:
        payload = await request.json()
        phone = payload.get("phone", "").strip()
        code = payload.get("code", "").strip()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)

    if not phone or not code:
        return web.json_response({"error": "credentials_required"}, status=400, dumps=json_dumps)

    user_id = await db_verify_web_code(phone, code)
    if not user_id:
        return web.json_response({"error": "invalid_code"}, status=401, dumps=json_dumps)

    token = await db_web_session_create(user_id)
    return web.json_response({"ok": True, "token": token}, dumps=json_dumps)

async def handle_health(request):
    return web.Response(text="OK")


# ============= ADMIN WEB API =============
async def get_admin_user(request):
    user_id, err = await get_auth_user(request)
    if err:
        return None, err
    if not is_admin(user_id):
        return None, 403
    return user_id, None

def admin_denied(status):
    if status == 403:
        return web.json_response({"error": "forbidden"}, status=403, dumps=json_dumps)
    return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)

async def handle_admin_page(request):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "admin.html")
    if not os.path.exists(p):
        return web.Response(text="frontend/admin.html not found", status=404)
    with open(p, "rb") as f:
        return web.Response(body=f.read(), content_type="text/html", charset="utf-8")

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
        "welcomed": bool(row[5]), "is_blocked": bool(row[6]),
        "is_certified": bool(row[7]) if len(row) > 7 else False,
        "is_medbook_valid": bool(row[8]) if len(row) > 8 else False,
    }

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
        u, fn, ph, bd, pos, rest, rn, wel, blk, cert, mb, cr, ls = r
        result.append({
            "user_id": u, "full_name": fn or "", "phone": ph or "",
            "birth_date": bd or "", "position": pos or "",
            "restaurant_key": rest or "", "restaurant_name": rn or "",
            "welcomed": bool(wel), "is_blocked": bool(blk),
            "is_certified": bool(cert), "is_medbook_valid": bool(mb),
            "created_at": cr.isoformat() if cr else None,
            "last_seen_at": ls.isoformat() if ls else None,
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
    return web.json_response({
        "user": _user_row_to_dict(target, row, names),
        "is_pinned": await db_is_pinned(uid, target),
    }, dumps=json_dumps)

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
               "is_certified", "is_medbook_valid", "is_blocked"}
    changed = {}
    for field, value in updates.items():
        if field not in allowed:
            continue
        if field in ("is_certified", "is_medbook_valid", "is_blocked"):
            v = bool(value)
        elif field == "full_name":
            v = str(value).strip()
            if not NAME_RE.match(v) or len(v.split()) < 2:
                continue
        elif field == "phone":
            v = str(value).strip()
            d = v.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if not d.isdigit() or len(d) < 10:
                continue
        elif field == "birth_date":
            v = str(value).strip()
            try:
                datetime.strptime(v, "%d.%m.%Y")
            except ValueError:
                continue
        else:
            v = str(value or "")
        await db_update_user(target, field, v)
        await db_audit(uid, "user_update", "user", target, f"{field}={v}")
        changed[field] = v
    row = await db_get(target)
    names = await restaurant_names_map()
    return web.json_response({
        "ok": True, "changed": changed,
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
    if not target or target == ADMIN_ID:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    ok = await db_delete_user(target)
    if ok:
        await db_audit(uid, "user_delete", "user", target)
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_user_pin(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    target = safe_int(payload.get("user_id"))
    if not target:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    return web.json_response({"is_pinned": await db_pin_toggle(uid, target)}, dumps=json_dumps)

async def handle_admin_user_message(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    target = safe_int(payload.get("user_id"))
    text = (payload.get("text") or "").strip()
    if not target or not text or len(text) > 2000:
        return web.json_response({"error": "invalid"}, status=400, dumps=json_dumps)
    ok = False
    try:
        await bot.send_message(target,
            f"💬 <b>Сообщение от администратора</b>\n\n{html.escape(text)}",
            parse_mode="HTML")
        ok = True
    except Exception:
        pass
    await db_audit(uid, "admin_dm", "user", target, text[:80])
    return web.json_response({"ok": ok}, dumps=json_dumps)

async def handle_admin_restaurants(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    rows = await db_restaurants_all()
    tu_ids = set(r.get("territory_manager_id") for r in rows if r.get("territory_manager_id"))
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
    return {
        "id": nid, "title": title, "body": body,
        "level": lvl or "normal", "important": bool(imp),
        "created_at": created.isoformat() if created else None,
        "published": bool(published),
        "publish_at": publish_at.isoformat() if publish_at else None,
    }

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

async def handle_admin_news_broadcast(request):
    uid, err = await get_admin_user(request)
    if err:
        return admin_denied(err)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)
    nid = safe_int(payload.get("id"))
    rkey = payload.get("restaurant_key") or None
    row = await db_get_news(nid)
    if not row:
        return web.json_response({"error": "not_found"}, status=404, dumps=json_dumps)
    title, body, level = row
    lock = f"web:{nid}:{rkey or 'all'}"
    if not try_lock_broadcast(lock):
        return web.json_response({"error": "busy"}, status=409, dumps=json_dumps)
    await db_audit(uid, "broadcast_web", "news", nid, f"target={rkey or 'all'}")
    async def _r():
        try:
            await broadcast_news(title, body, level, restaurant_key=rkey)
        finally:
            unlock_broadcast(lock)
    spawn(_r(), name=f"web_bc_{nid}")
    return web.json_response({"ok": True}, dumps=json_dumps)

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
    sent = False
    try:
        await bot.send_message(q["user_id"],
            f"💬 <b>Ответ от администратора</b>\n\n{html.escape(text)}",
            parse_mode="HTML")
        sent = True
    except Exception:
        pass
    return web.json_response({"ok": True, "sent": sent}, dumps=json_dumps)

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
    writer.writerow(["user_id", "full_name", "phone", "birth_date", "position",
                     "restaurant", "is_blocked", "is_certified",
                     "is_medbook_valid", "welcomed", "created_at"])
    for r in await _run(_sync_db_admin_users_list, ""):
        u, fn, ph, bd, pos, rest, rn, wel, blk, cert, mb, cr, ls = r
        writer.writerow([u, fn or "", ph or "", bd or "", pos or "",
                         rn or rest or "",
                         "yes" if blk else "no",
                         "yes" if cert else "no",
                         "yes" if mb else "no",
                         "yes" if wel else "no",
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


@web.middleware
async def error_middleware(request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        logging.error("Unhandled error in %s %s: %s: %s",
                      request.method, request.path, type(e).__name__, str(e)[:200])
        return web.json_response({"error": "internal_server_error"}, status=500)

_GZIP_TYPES = ("application/json", "text/plain", "text/html", "text/css",
               "application/javascript", "application/xml", "image/svg+xml")

@web.middleware
async def gzip_middleware(request, handler):
    response = await handler(request)
    body = getattr(response, "body", None)
    if (body is not None
            and len(body) > 500
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
app.router.add_post("/api/auth/request-code", handle_auth_request)
app.router.add_post("/api/auth/verify-code", handle_auth_verify)
app.router.add_post("/api/bootstrap", handle_bootstrap)
app.router.add_post("/api/restaurants", handle_restaurants)
app.router.add_post("/api/greeting", handle_greeting)
app.router.add_post("/api/news", handle_news)
app.router.add_post("/api/standards", handle_standards)
app.router.add_post("/api/faq", handle_faq)
app.router.add_post("/api/profile", handle_profile)
app.router.add_post("/api/avatar", handle_avatar)
app.router.add_post("/api/questions", handle_questions)
app.router.add_get("/api/health", handle_health)

# ============= ADMIN WEB ROUTES =============
app.router.add_get("/admin", handle_admin_page)
app.router.add_get("/admin/", handle_admin_page)
app.router.add_post("/api/admin/me", handle_admin_me)
app.router.add_post("/api/admin/dashboard", handle_admin_dashboard)
app.router.add_post("/api/admin/users", handle_admin_users)
app.router.add_post("/api/admin/user/get", handle_admin_user_get)
app.router.add_post("/api/admin/user/update", handle_admin_user_update)
app.router.add_post("/api/admin/user/delete", handle_admin_user_delete)
app.router.add_post("/api/admin/user/pin", handle_admin_user_pin)
app.router.add_post("/api/admin/user/message", handle_admin_user_message)
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
app.router.add_post("/api/admin/news/broadcast", handle_admin_news_broadcast)
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


async def main():
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server on port {port}")
    spawn(birthday_checker(), name="birthday_checker")
    spawn(holiday_broadcaster(), name="holiday_broadcaster")
    spawn(scheduled_publisher(), name="scheduled_publisher")
    print("STARTING BOT SCRIPT...")
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        tasks_to_wait = list(_bg_tasks)
        for task in tasks_to_wait:
            task.cancel()
        if tasks_to_wait:
            await asyncio.gather(*tasks_to_wait, return_exceptions=True)
        await runner.cleanup()
        try:
            await fsm_storage.close()
        except Exception:
            pass
        await bot.session.close()
        if _pool:
            _pool.closeall()

if __name__ == "__main__":
    asyncio.run(main())
