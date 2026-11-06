import os
import io
import csv
import asyncio
import logging
import json
import hmac
import hashlib
import re
import time
import aiohttp
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from urllib.parse import unquote

from aiohttp import web
from aiogram import Bot, Dispatcher, Router, BaseMiddleware, types
from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError
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
    WebAppInfo,
    BufferedInputFile,
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

MINI_APP_URL = os.getenv("MINI_APP_URL", "https://ВАШ-ДОМЕН.amvera.io")


# ================== FSM STORAGE: Redis или Memory ==================

REDIS_URL = os.getenv("REDIS_URL", "").strip()

if REDIS_URL:
    try:
        from aiogram.fsm.storage.redis import RedisStorage
        fsm_storage = RedisStorage.from_url(REDIS_URL)
        print(f"FSM: Redis storage ({REDIS_URL.split('@')[-1] if '@' in REDIS_URL else REDIS_URL})")
    except Exception as e:
        print(f"⚠ Не удалось подключить Redis ({e}), fallback на MemoryStorage")
        fsm_storage = MemoryStorage()
else:
    fsm_storage = MemoryStorage()
    print("⚠ FSM: MemoryStorage — данные FSM не переживут рестарт сервера. "
          "Задай REDIS_URL для устойчивого хранения.")


# ================== ПУЛ СОЕДИНЕНИЙ ==================

_pool = None


def init_pool():
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(1, 10, DB_URL)


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


def spawn(coro):
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)
    return task


# ================== SEED ==================

RESTAURANTS_SEED = [
    {"key": "mega_belaya_dacha", "name": "Мега Белая Дача", "address": "Московская область, Котельники, 1-й Покровский проезд, 5, ТРЦ Мега, этаж 1", "hours": "Пн–чт: 10:00–22:00\nПт–вс: 10:00–23:00", "lat": 55.6578, "lon": 37.8891, "org": "vokker/128833821207", "phone": ""},
    {"key": "belyaevo", "name": "Беляево", "address": "Москва, ул. Миклухо-Маклая, 32А, ТЦ «Капитолий», этаж 2", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6470, "lon": 37.5420, "org": "vokker/13122472923", "phone": ""},
    {"key": "vernadka", "name": "Вернадка", "address": "Москва, проспект Вернадского, 6, ТЦ «Капитолий Вернадского», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6840, "lon": 37.4980, "org": "vokker/91626648547", "phone": ""},
    {"key": "erevan_plaza", "name": "Ереван Плаза", "address": "Москва, ул. Большая Тульская, д. 13, ТРЦ «Ереван Плаза», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.7030, "lon": 37.6210, "org": "vokker/102264079721", "phone": ""},
    {"key": "kuzminki_mall", "name": "Кузьминки Молл", "address": "Москва, ул. Зеленодольская, д. 42, ТРЦ «Кузьминки Молл», этаж 3", "hours": "Пн–вс: 10:00–22:00", "lat": 55.6980, "lon": 37.7750, "org": "vokker/24262320480", "phone": ""},
    {"key": "mega_teplyy_stan", "name": "Мега Тёплый стан", "address": "Москва, Калужское шоссе, 21-й километр, с1, ТЦ «Мега Тёплый Стан»", "hours": "Пн–вс: 10:00–22:00", "lat": 55.5790, "lon": 37.4870, "org": "vokker/1485953945", "phone": ""},
    {"key": "mega_himki", "name": "Мега Химки", "address": "Московская обл., г. Химки, микрорайон ИКЕА, к1, ТЦ «Мега Химки», этаж 1", "hours": "Пн–чт, вс: 10:00–23:00\nПт–сб: 10:00–24:00", "lat": 55.8970, "lon": 37.4120, "org": "vokker/132066311330", "phone": ""},
    {"key": "metropolis", "name": "Метрополис", "address": "Москва, Ленинградское ш., д. 16А, стр. 4, ТРЦ «Метрополис», этаж 3", "hours": "Пн–вс: 10:00–23:00", "lat": 55.8120, "lon": 37.5060, "org": "vokker/1298559872", "phone": ""},
    {"key": "moskva_city", "name": "Москва-Сити", "address": "Москва, 1-й Красногвардейский пр., д. 22, стр. 1 (Neva Towers), этаж 2, фуд-корт", "hours": "Пн–вс: 10:00–22:00", "lat": 55.7490, "lon": 37.5380, "org": "vokker/25826174821", "phone": ""},
    {"key": "okeaniya", "name": "Океания", "address": "Москва, Кутузовский пр., д. 57, ТРЦ «Океания», этаж 3", "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00", "lat": 55.7330, "lon": 37.4950, "org": "vokker/9739651477", "phone": ""},
    {"key": "polkovaya", "name": "Полковая", "address": "Москва, ул. Полковая, д. 3, стр. 5, БЦ «Шереметьевский», этаж 1", "hours": "Пн–вс: 10:00–22:00", "lat": 55.8010, "lon": 37.5920, "org": "vokker/84984433800", "phone": ""},
    {"key": "cdm", "name": "ЦДМ", "address": "Москва, Театральный пр., д. 5, стр. 1, «ЦДМ на Лубянке», этаж 6", "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00", "lat": 55.7580, "lon": 37.6230, "org": "vokker/31463245515", "phone": ""},
    {"key": "tsvetnoy", "name": "Цветной", "address": "Москва, Цветной бульвар, д. 15, стр. 1, ТРЦ «Цветной», этаж 5", "hours": "Пн–сб: 10:00–22:00\nВс: 11:00–22:00", "lat": 55.7670, "lon": 37.6180, "org": "vokker/110848206544", "phone": ""},
    {"key": "shchelkovskaya", "name": "Щёлковская", "address": "Москва, Щёлковское шоссе, 75, ТРЦ «Щёлковский», этаж 5", "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00", "lat": 55.8050, "lon": 37.7920, "org": "vokker/25844145312", "phone": ""},
    {"key": "shuka", "name": "Щука", "address": "Москва, ул. Щукинская, д. 42, ТРК «Щука», этаж 4", "hours": "Пн–вс: 10:00–22:00", "lat": 55.8020, "lon": 37.4650, "org": "vokker/1357579873", "phone": ""},
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

POSITIONS_SEED = ["Холодный Цех", "Жарщик", "Управляющий сменой", "Территориальный управляющий"]


# ================== ИНИЦИАЛИЗАЦИЯ БД ==================

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
        # Scheduled publish
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

print("База данных подключена, таблицы готовы.")


# ================== ПРАЗДНИКИ ==================

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


# ================== СИНХРОННЫЕ DB ==================

RESTAURANT_DB_FIELDS = ("name", "address", "phone", "hours", "org")


def _sync_db_restaurants_all():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, name, address, hours, lat, lon, org, phone, force_status, sort "
                "FROM restaurants ORDER BY sort, name")
            cols = ["key", "name", "address", "hours", "lat", "lon", "org", "phone", "force_status", "sort"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _sync_db_restaurants_for_app():
    return [r for r in _sync_db_restaurants_all() if r["key"] != "office"]


def _sync_db_restaurant(key):
    for r in _sync_db_restaurants_all():
        if r["key"] == key:
            return r
    return None


def _sync_db_restaurant_update(key, field, value):
    if field not in RESTAURANT_DB_FIELDS:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE restaurants SET {field} = %s WHERE key = %s", (value, key))
            return cur.rowcount > 0


def _sync_db_restaurant_set_status(key, fs):
    if fs not in (None, "open", "closed"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE restaurants SET force_status = %s WHERE key = %s", (fs, key))
            return cur.rowcount > 0


def _sync_db_restaurant_add(key, name, address, hours, phone, org):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM restaurants WHERE key = %s", (key,))
            if cur.fetchone()[0] > 0:
                return False
            cur.execute("SELECT COALESCE(MAX(sort), 0) FROM restaurants WHERE key != 'office'")
            next_sort = cur.fetchone()[0] + 1
            cur.execute(
                "INSERT INTO restaurants (key, name, address, hours, phone, org, sort) "
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
            cur.execute(
                "SELECT full_name, phone, birth_date, position, restaurant, welcomed, is_blocked "
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
            cur.execute(
                "INSERT INTO users (user_id, welcomed, first_name) VALUES (%s, TRUE, %s) "
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
            cur.execute(
                """
                INSERT INTO users (user_id, full_name, phone, birth_date, position, restaurant, welcomed, first_name)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                full_name = %s, phone = %s, birth_date = %s, position = %s, restaurant = %s, welcomed = TRUE,
                first_name = COALESCE(EXCLUDED.first_name, users.first_name)
                """,
                (user_id, full_name, phone, birth_date, position, restaurant, first_name,
                 full_name, phone, birth_date, position, restaurant))


def _sync_db_update_user(user_id, field, value):
    allowed = ("full_name", "phone", "birth_date", "position", "restaurant")
    if field not in allowed:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {field} = %s WHERE user_id = %s", (value, user_id))
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
            cur.execute("""
                SELECT user_id, full_name, phone, position, restaurant, welcomed, is_blocked
                FROM users ORDER BY user_id
            """)
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
                cur.execute(
                    "SELECT user_id FROM users WHERE is_blocked = FALSE AND bot_blocked = FALSE "
                    "AND full_name IS NOT NULL AND restaurant = %s",
                    (restaurant_key,))
            else:
                cur.execute(
                    "SELECT user_id FROM users WHERE is_blocked = FALSE AND bot_blocked = FALSE "
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


def _sync_get_report_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE")
            active = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
            blocked = cur.fetchone()[0] or 0
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE full_name IS NOT NULL "
                "AND (last_seen_at IS NULL OR last_seen_at < NOW() - INTERVAL '7 days')")
            inactive7 = cur.fetchone()[0] or 0
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '7 days' "
                "AND full_name IS NOT NULL")
            new7 = cur.fetchone()[0] or 0
    return {"total": total, "active": active, "blocked": blocked,
            "inactive7": inactive7, "new7": new7,
            "date": _moscow_now().strftime("%d.%m.%Y %H:%M")}


def _sync_db_add_news(title, body, level, publish_at=None):
    if level not in ("urgent", "important", "normal"):
        level = "normal"
    with get_conn() as conn:
        with conn.cursor() as cur:
            if publish_at:
                cur.execute(
                    "INSERT INTO news (title, body, important, level, published, publish_at, auto_broadcast) "
                    "VALUES (%s, %s, %s, %s, FALSE, %s, TRUE) RETURNING id",
                    (title, body, level != "normal", level, publish_at))
            else:
                cur.execute(
                    "INSERT INTO news (title, body, important, level, published, publish_at) "
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


def _sync_db_delete_news(news_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news WHERE id = %s", (news_id,))
            return cur.rowcount > 0


def _sync_db_publish_due():
    """Атомарно публикует все наступившие отложенные новости и возвращает их."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE news SET published = TRUE "
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
    if field not in ("title", "category", "description", "url"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE standards SET {field} = %s WHERE id = %s", (value, sid))
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
    if field not in ("question", "answer"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE faq SET {field} = %s WHERE id = %s", (value, fid))
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
                cur.execute("DELETE FROM bot_messages WHERE user_id = %s AND message_id = %s",
                            (user_id, mid))
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
                cur.execute("DELETE FROM user_messages WHERE user_id = %s AND message_id = %s",
                            (user_id, mid))
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
            cur.execute(
                "INSERT INTO admin_audit (admin_id, action, target_type, target_id, details) "
                "VALUES (%s, %s, %s, %s, %s)",
                (admin_id, action, target_type, str(target_id), details))


def _sync_db_audit_list(limit=200):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, admin_id, action, target_type, target_id, details, created_at "
                        "FROM admin_audit ORDER BY created_at DESC LIMIT %s", (limit,))
            return cur.fetchall()


# ================== АСИНХРОННЫЕ ОБЁРТКИ ==================

async def db_restaurants_all(): return await _run(_sync_db_restaurants_all)
async def db_restaurants_for_app(): return await _run(_sync_db_restaurants_for_app)
async def db_restaurant(key): return await _run(_sync_db_restaurant, key)
async def db_restaurant_update(key, f, v): return await _run(_sync_db_restaurant_update, key, f, v)
async def db_restaurant_set_status(key, fs): return await _run(_sync_db_restaurant_set_status, key, fs)
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
async def get_report_stats(): return await _run(_sync_get_report_stats)
async def db_add_news(t, b, l, publish_at=None): return await _run(_sync_db_add_news, t, b, l, publish_at)
async def db_list_news(): return await _run(_sync_db_list_news)
async def db_list_news_admin(): return await _run(_sync_db_list_news_admin)
async def db_get_news(nid): return await _run(_sync_db_get_news, nid)
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
async def db_audit(admin_id, action, tt="", ti="", details=""):
    try:
        return await _run(_sync_db_audit, admin_id, action, tt, ti, details)
    except Exception as e:
        logging.warning(f"audit failed: {e}")
async def db_audit_list(limit=100): return await _run(_sync_db_audit_list, limit)


# ================== СТАТУС РЕСТОРАНОВ ==================

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
            rng = re.findall(r"[а-яё]{2}", chunk)
            if len(rng) >= 2 and any(c in chunk for c in ("–", "-", "—")):
                if rng[0] in DAY_MAP and rng[-1] in DAY_MAP:
                    d1, d2 = DAY_MAP[rng[0]], DAY_MAP[rng[-1]]
                    if d1 <= d2:
                        days.update(range(d1, d2 + 1))
                    else:
                        days.update(list(range(d1, 7)) + list(range(0, d2 + 1)))
            elif rng and rng[0] in DAY_MAP:
                days.add(DAY_MAP[rng[0]])
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


# ================== УТИЛИТЫ ==================

PAGE_USERS = 10
PAGE_NEWS = 8
PAGE_RESTS = 12
PAGE_STD = 10
PAGE_FAQ = 10
PAGE_AUDIT = 15

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
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
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


async def restaurant_name_by_key(key):
    if not key:
        return key
    r = await db_restaurant(key)
    return r["name"] if r else key


async def build_restaurants_payload():
    out = []
    for r in await db_restaurants_for_app():
        status, status_text = restaurant_status_for(r)
        out.append({
            "key": r["key"], "name": r["name"], "address": r["address"],
            "hours": r["hours"], "org": r["org"], "phone": r.get("phone") or "",
            "sort": r.get("sort") if r.get("sort") is not None else 100,
            "status": status, "status_text": status_text,
        })
    return out


_broadcast_locks = set()


def try_lock_broadcast(key):
    if key in _broadcast_locks:
        return False
    _broadcast_locks.add(key)
    return True


def unlock_broadcast(key):
    _broadcast_locks.discard(key)


# ================== BOT + ROUTERS + STORAGE ==================

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


admin_router.message.middleware(AdminOnlyMiddleware())
admin_router.callback_query.middleware(AdminOnlyMiddleware())

dp.include_router(user_router)
dp.include_router(admin_router)


# ================== ОЧИСТКА ЧАТА ==================

async def cleanup_chat(user_id: int, keep: int = 1):
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


# ================== FSM ==================

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


# ================== ВАЛИДАЦИЯ INIT DATA ==================

def _check_auth_date(pairs_dict):
    s = pairs_dict.get("auth_date")
    if not s:
        return False
    try:
        return (time.time() - int(s)) <= 86400
    except (ValueError, TypeError):
        return False


def _parse_user_field(pairs_dict):
    try:
        return json.loads(unquote(pairs_dict.get("user", "{}")))
    except Exception as e:
        logging.warning(f"initData user: {e}")
        return None


def validate_init_data(init_data: str):
    if not init_data:
        return None
    try:
        pairs = []
        for pair in init_data.split("&"):
            if "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            pairs.append((key, value))
        pairs_dict = dict(pairs)
    except Exception:
        return None
    received_hash = pairs_dict.get("hash")
    if not received_hash:
        return None
    secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs) if k != "hash")
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(computed_hash, received_hash):
        if not _check_auth_date(pairs_dict):
            return None
        return _parse_user_field(pairs_dict)
    decoded_string = "\n".join(f"{k}={unquote(v)}" for k, v in sorted(pairs) if k != "hash")
    decoded_hash = hmac.new(secret_key, decoded_string.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(decoded_hash, received_hash):
        if not _check_auth_date(pairs_dict):
            return None
        return _parse_user_field(pairs_dict)
    return None


async def get_auth_user(request):
    try:
        payload = await request.json()
    except Exception:
        return None, 401
    user = validate_init_data(payload.get("initData", ""))
    if not user or not user.get("id"):
        return None, 401
    user_id = int(user["id"])
    if await db_is_blocked(user_id):
        return None, 403
    return user_id, None


# ================== КЛАВИАТУРЫ ==================

FULL_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📱 Открыть приложение Wokker", web_app=WebAppInfo(url=MINI_APP_URL))],
])

REGISTER_ONLY = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✍️ Зарегистрироваться", callback_data="register")],
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


async def restaurants_edit_kb(target_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r["name"], callback_data=f"editsetrest:{target_id}:{r['key']}")]
        for r in await db_restaurants_all()
    ] + [[InlineKeyboardButton(text="🔙 К карточке", callback_data=f"adm_user:{target_id}")]])


async def profile_text(row):
    full_name, phone, birth_date, position, restaurant = row[0], row[1], row[2], row[3], row[4]
    rest_name = await restaurant_name_by_key(restaurant) if restaurant else "—"
    return (
        "📋 <b>Твой профиль</b>\n"
        "──────────────────────────────\n"
        f"👤 ФИО: <b>{full_name}</b>\n"
        f"💼 Должность: {position or '—'}\n"
        f"📍 Ресторан: {rest_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}\n"
        "──────────────────────────────")


async def admin_menu_kb():
    users_n = len([r for r in await db_list_users() if r[1]])
    news_n = len(await db_list_news_admin())
    std_n = len(await db_list_standards())
    faq_n = len(await db_list_faq())
    rest_n = len(await db_restaurants_for_app())
    pos_n = len(await db_positions_list())
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📋 Пользователи ({users_n})", callback_data="adm_users")],
        [InlineKeyboardButton(text=f"🏪 Рестораны ({rest_n})", callback_data="adm_rests")],
        [InlineKeyboardButton(text=f"💼 Должности ({pos_n})", callback_data="adm_positions")],
        [InlineKeyboardButton(text=f"📰 Новости ({news_n})", callback_data="adm_news")],
        [InlineKeyboardButton(text=f"📚 Стандарты ({std_n})", callback_data="adm_std")],
        [InlineKeyboardButton(text=f"❓ FAQ ({faq_n})", callback_data="adm_faq")],
        [InlineKeyboardButton(text="📊 Отчёты", callback_data="adm_reports")],
        [InlineKeyboardButton(text="📜 История действий", callback_data="adm_audit")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_menu")],
    ])


LEVEL_LABELS = {
    "urgent": "🔴 Срочная",
    "important": "🟡 Важная",
    "normal": "🔵 Обычная",
}


# ================== КАРТОЧКИ ==================

async def users_list_text(rows, page, pages, total):
    if not rows:
        return "📋 Пока никто не зарегистрирован."
    lines = [f"📋 Пользователи · всего {total} · стр. {page+1}/{pages}\n"]
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        if not full_name:
            lines.append(f"• <code>{user_id}</code> — регистрация не завершена")
            continue
        mark = " 🚫" if is_blocked else ""
        rest = await restaurant_name_by_key(restaurant) if restaurant else "—"
        lines.append(f"• <b>{full_name}</b>{mark} — {position or '—'}, {rest}")
    return "\n".join(lines)


def users_list_kb(rows, page, pages):
    kb = []
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        label = full_name if full_name else f"ID {user_id}"
        if is_blocked:
            label = "🚫 " + label
        kb.append([InlineKeyboardButton(text=label[:60], callback_data=f"adm_user:{user_id}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"adm_users_p:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"adm_users_p:{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="🔍 Найти пользователя", callback_data="adm_users_search")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def user_card_text(target_id: int, row) -> str:
    if not row:
        return "Пользователь не найден."
    full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row
    rest_name = await restaurant_name_by_key(restaurant) if restaurant else "—"
    status = "🚫 Заблокирован" if is_blocked else "✅ Активен"
    return (
        "👤 <b>Пользователь</b>\n"
        "──────────────────────────────\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"👤 ФИО: <b>{full_name or '—'}</b>\n"
        f"💼 Должность: {position or '—'}\n"
        f"📍 Ресторан: {rest_name}\n"
        f"📞 Телефон: {phone or '—'}\n"
        f"🎂 Дата рождения: {birth_date or '—'}\n"
        f"📊 Статус: {status}")


def user_edit_kb(target_id: int, is_blocked: bool = False) -> InlineKeyboardMarkup:
    ban_btn = (
        InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"adm_unban:{target_id}")
        if is_blocked else
        InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"adm_ban_ask:{target_id}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ ФИО", callback_data=f"edit_field:{target_id}:full_name"),
         InlineKeyboardButton(text="📞 Телефон", callback_data=f"edit_field:{target_id}:phone")],
        [InlineKeyboardButton(text="🎂 Дата рождения", callback_data=f"edit_field:{target_id}:birth_date"),
         InlineKeyboardButton(text="💼 Должность", callback_data=f"edit_pos:{target_id}")],
        [InlineKeyboardButton(text="📍 Ресторан", callback_data=f"edit_rest:{target_id}")],
        [ban_btn, InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm_del:{target_id}")],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="adm_users")],
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
            mark = f" · ⏰ {publish_at.strftime('%d.%m.%Y %H:%M')}"
        else:
            mark = ""
        lines.append(f"{LEVEL_LABELS[lvl]} <b>{title}</b>{mark} ({date_str})")
    return "\n".join(lines)


def news_admin_kb(rows, page, pages):
    kb = []
    for row in rows:
        news_id, title = row[0], row[1]
        published = row[6] if len(row) > 6 else True
        short = (title or "Без названия")[:28]
        icon = "📢" if published else "⏰"
        kb.append([
            InlineKeyboardButton(text=f"{icon} {short}", callback_data=f"news_send:{news_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"news_del:{news_id}"),
        ])
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
    text = f"{icon} <b>{title}</b>\n\n{body}"
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
        target = await restaurant_name_by_key(restaurant_key) if restaurant_key else "всем"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"📬 Рассылка завершена.\n\n📰 «{title}»\n🎯 Аудитория: {target}\n"
                f"✅ Доставлено: {sent}\n❌ Не доставлено: {failed}")
        except Exception:
            pass


# ================== РЕСТОРАНЫ (карточка/клавиатуры) ==================

FIELD_LABELS = {
    "name": "Название",
    "address": "Адрес",
    "phone": "Телефон",
    "hours": "Часы работы",
    "org": "Ссылка на Яндекс Картах",
}

FIELD_PROMPTS = {
    "name": "✏️ Напиши новое название точки (например: Мега Химки)",
    "address": "✏️ Напиши новый адрес (например: Москва, ул. Ленина, 5, ТЦ «Пример», этаж 2)",
    "phone": "📞 Напиши новый телефон в формате +79001234567 (или «нет», чтобы скрыть)",
    "hours": "🕒 Напиши часы работы в формате:\nПн–чт: 10:00–22:00\nПт–вс: 10:00–23:00",
    "org": "🗺 Напиши путь карточки Яндекс Карт (например: vokker/1234567890)\nили «нет», чтобы искать по адресу",
}


def rest_status_label(r: dict) -> str:
    status, status_text = restaurant_status_for(r)
    if r.get("force_status") == "open":
        return f"🟢 {status_text}"
    if r.get("force_status") == "closed":
        return f"🔴 {status_text}"
    return f"♻️ Авто: {status_text}"


def rest_card_text(r: dict) -> str:
    phone = r.get("phone") or "—"
    return (
        f"🏪 <b>{r['name']}</b>\n"
        f"{'🟢' if restaurant_status_for(r)[0] == 'open' else '🔴'} Статус: {rest_status_label(r)}\n"
        "──────────────────────────────\n"
        f"📍 Адрес: {r.get('address') or '—'}\n"
        f"📞 Телефон: {phone}\n"
        f"🕒 Часы: {(r.get('hours') or '—').replace(chr(10), ' / ')}\n"
        f"🗺 Яндекс Карты: {r.get('org') or 'по адресу'}\n"
        f"🔑 Key: <code>{r['key']}</code>")


def rest_card_kb(r: dict) -> InlineKeyboardMarkup:
    fs = r.get("force_status")
    if fs == "open":
        status_btn = InlineKeyboardButton(text="♻️ Вернуть авто-статус", callback_data=f"restset:{r['key']}:auto")
    elif fs == "closed":
        status_btn = InlineKeyboardButton(text="🟢 Открыть (вручную)", callback_data=f"restset:{r['key']}:open")
    else:
        status_btn = InlineKeyboardButton(text="🔴 Закрыть (вручную)", callback_data=f"restset:{r['key']}:closed")
    rows = [
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"restedit:{r['key']}:name"),
         InlineKeyboardButton(text="✏️ Адрес", callback_data=f"restedit:{r['key']}:address")],
        [InlineKeyboardButton(text="✏️ Телефон", callback_data=f"restedit:{r['key']}:phone"),
         InlineKeyboardButton(text="✏️ Часы", callback_data=f"restedit:{r['key']}:hours")],
        [InlineKeyboardButton(text="✏️ Яндекс Карты", callback_data=f"restedit:{r['key']}:org")],
        [status_btn],
    ]
    if r["key"] != "office":
        rows.append([InlineKeyboardButton(text="🗑 Удалить точку", callback_data=f"rest_del_ask:{r['key']}")])
    rows.append([InlineKeyboardButton(text="🔙 К списку ресторанов", callback_data="adm_rests")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def rests_list_kb(rests, page, pages):
    kb = []
    for r in rests:
        status, _ = restaurant_status_for(r)
        icon = "🟢" if status == "open" else "🔴"
        kb.append([
            InlineKeyboardButton(text=f"{icon} {r['name']}", callback_data=f"restadm:{r['key']}"),
            InlineKeyboardButton(
                text=("🔓" if r.get("force_status") == "closed" else "🔒"),
                callback_data=f"restset:{r['key']}:{'open' if r.get('force_status') == 'closed' else 'closed'}"),
            InlineKeyboardButton(text="✏️", callback_data=f"restadm:{r['key']}"),
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
        lines.append(f"{icon} <b>{r['name']}</b>{mark} — {r.get('address') or '—'}")
    return "\n".join(lines)


# ================== USER ROUTER: /start, /cancel, /profile ==================

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
        await send_tracked(message.chat.id, user_id, "Выбери действие:", reply_markup=FULL_MENU)
        return
    if row and row[5]:
        await send_tracked(message.chat.id, user_id, "Заверши регистрацию 👇", reply_markup=REGISTER_ONLY)
        return
    await db_set_welcomed(user_id, message.from_user.first_name)
    await send_tracked(message.chat.id, user_id,
                       f"👋 {message.from_user.first_name}, добро пожаловать в Wokker!")
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
        await send_tracked(message.chat.id, message.from_user.id, await profile_text(row), parse_mode="HTML")
    else:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Ты не зарегистрирован. Напиши /start.")


@user_router.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    if await db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    await state.set_state(Registration.full_name)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
                       "Шаг 2 из 5.\nОтправь номер телефона:",
                       reply_markup=phone_kb())


@user_router.message(Registration.phone, lambda m: m.contact is not None)
async def process_phone_button(message: types.Message, state: FSMContext):
    if message.contact.user_id != message.from_user.id:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Пожалуйста, поделись своим номером.", reply_markup=phone_kb())
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Registration.birth_date)
    await send_tracked(message.chat.id, message.from_user.id,
                       "Номер получен ✅\nШаг 3 из 5.\nДата рождения ДД.ММ.ГГГГ:",
                       reply_markup=ReplyKeyboardRemove())


@user_router.message(Registration.phone)
async def process_phone_text(message: types.Message, state: FSMContext):
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
                       "Номер записан ✅\nШаг 3 из 5.\nДата рождения ДД.ММ.ГГГГ:",
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
                       "Дата записана ✅\nШаг 4 из 5. Должность:",
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
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           "Должность не найдена. Выбери из списка.")
        return
    await state.update_data(position=position)
    await state.set_state(Registration.restaurant)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"Должность: <b>{position}</b> ✅\n\nШаг 5 из 5. Ресторан 👇",
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
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           "❌ Ошибка сохранения. Попробуй позже.")
        await state.clear()
        return
    await state.clear()
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"🎉 <b>{callback.from_user.first_name}, регистрация завершена!</b>\n\n"
                       f"👤 ФИО: {full_name}\n📞 {phone}\n🎂 {birth_date}\n"
                       f"💼 {position}\n📍 {restaurant['name']}\n\n"
                       "Открой приложение:",
                       parse_mode="HTML", reply_markup=FULL_MENU)
    if ADMIN_ID:
        uname = f"@{callback.from_user.username}" if callback.from_user.username else "нет"
        try:
            await bot.send_message(ADMIN_ID,
                                   f"🔔 Новая регистрация!\n\n{full_name}\n{phone}\n{birth_date}\n"
                                   f"{position}\n{restaurant['name']}\n"
                                   f"ID: <code>{callback.from_user.id}</code>\n{uname}",
                                   parse_mode="HTML")
        except Exception as e:
            logging.error(f"notify admin: {e}")


@user_router.callback_query(lambda c: c.data == "hide_notification")
async def hide_notification(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception as e:
        logging.warning(f"hide: {e}")
    await callback.answer("Скрыто")


@user_router.callback_query(lambda c: c.data == "noop")
async def user_noop(callback: types.CallbackQuery):
    await callback.answer()


# ================== ADMIN ROUTER ==================

@admin_router.message(Command("admin"))
async def cmd_admin(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    await send_tracked(message.chat.id, message.from_user.id,
                       "🛠 <b>Админ-панель</b>\n\nВыбери действие:",
                       parse_mode="HTML", reply_markup=await admin_menu_kb())


@admin_router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    stats = await get_report_stats()
    rests = await db_restaurants_all()
    counts = {}
    for r in await db_list_users():
        if r[1]:
            rn = await restaurant_name_by_key(r[4]) if r[4] else "Не указан"
            counts[rn] = counts.get(rn, 0) + 1
    rest_lines = "\n".join(f"• {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])) or "• пока нет данных"
    await send_tracked(
        message.chat.id, message.from_user.id,
        f"📊 <b>Сводка</b> ({stats['date']})\n\n"
        f"👥 Всего: {stats['total']} · ✅ активных: {stats['active']} · 🚫 заблокированных: {stats['blocked']}\n"
        f"📈 Новых за 7 дней: {stats['new7']} · 💤 Не заходили 7+ дней: {stats['inactive7']}\n"
        f"🏪 Точек: {len(rests) - 1}\n\n"
        f"<b>По ресторанам:</b>\n{rest_lines}",
        parse_mode="HTML")


@admin_router.message(Command("user"))
async def cmd_user_search(message: types.Message):
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    q = (message.text or "").replace("/user", "", 1).strip()
    if not q or len(q) < 2:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Использование: <code>/user Иванов</code> или <code>/user 123456789</code>",
                           parse_mode="HTML")
        return
    rows = await db_search_users(q)
    if not rows:
        await send_tracked(message.chat.id, message.from_user.id, f"Никого не нашёл по «{q}» 🤷")
        return
    if len(rows) > 30:
        await send_tracked(message.chat.id, message.from_user.id,
                           f"Слишком много совпадений ({len(rows)}). Уточни запрос.")
        return
    await send_tracked(message.chat.id, message.from_user.id,
                       await users_list_text(rows, 0, 1, len(rows)),
                       parse_mode="HTML", reply_markup=users_list_kb(rows, 0, 1))


@admin_router.callback_query(lambda c: c.data == "adm_menu")
async def adm_menu(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "🛠 Админ-панель", reply_markup=await admin_menu_kb())


# ---------- Рестораны ----------

@admin_router.callback_query(lambda c: c.data == "adm_rests")
async def adm_rests(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rests = await db_restaurants_all()
    chunk, page, pages = paginate(rests, 0, PAGE_RESTS)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       rests_list_text(chunk, page, pages, len(rests)),
                       parse_mode="HTML", reply_markup=rests_list_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_rests_p:"))
async def adm_rests_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rests = await db_restaurants_all()
    chunk, page, pages = paginate(rests, page, PAGE_RESTS)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       rests_list_text(chunk, page, pages, len(rests)),
                       parse_mode="HTML", reply_markup=rests_list_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("restadm:"))
async def rest_card_view(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    key = callback.data.split(":")[1]
    r = await db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if not r:
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Ресторан не найден.")
        return
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r))


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
            await send_tracked(callback.message.chat.id, callback.from_user.id,
                               rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r))
            return
    await callback.answer("Не удалось изменить статус", show_alert=True)


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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"{FIELD_PROMPTS[field]}\n\nИли нажми «Отменить»:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отменить", callback_data=f"restedit_cancel:{key}")]
                       ]))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("restedit_cancel:"))
async def rest_edit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    key = callback.data.split(":")[1]
    r = await db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if r:
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r))


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

    if rest_field == "name":
        if len(value) < 2:
            err = "Название слишком короткое. Попробуй ещё раз:"
    elif rest_field == "address":
        if len(value) < 5:
            err = "Адрес слишком короткий. Попробуй ещё раз:"
    elif rest_field == "phone":
        if value.lower() in ("нет", "-", "—", ""):
            value = ""
        else:
            digits = value.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if not digits.isdigit() or len(digits) < 10:
                err = "Это не похоже на номер. Пример: +79001234567. Или напиши «нет»."
    elif rest_field == "hours":
        if not validate_hours_schedule(value):
            err = "Проверь формат и время. Пример:\nПн–чт: 10:00–22:00\nПт–вс: 10:00–23:00"
    elif rest_field == "org":
        if value.lower() in ("нет", "-", "—", ""):
            value = ""

    if err:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, err)
        return

    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.clear()
    await db_restaurant_update(rest_key, rest_field, value)
    invalidate_rest_cache()
    await db_audit(message.from_user.id, "rest_update", "restaurant", rest_key, f"{rest_field}={value}")
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ {FIELD_LABELS[rest_field]} обновлено: <b>{value if value else '—'}</b>",
                       parse_mode="HTML")
    r = await db_restaurant(rest_key)
    if r:
        await send_tracked(message.chat.id, message.from_user.id,
                           rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r))


@admin_router.callback_query(lambda c: c.data == "rest_add")
async def rest_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(RestAdd.name)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "🏪 <b>Новый ресторан</b>\n\nШаг 1 из 5.\nНазвание точки:",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отменить", callback_data="adm_rests")]
                       ]))


@admin_router.message(RestAdd.name)
async def rest_add_name(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    name = (message.text or "").strip()
    if len(name) < 2:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком короткое. Ещё раз:")
        return
    await state.update_data(name=name)
    await state.set_state(RestAdd.address)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Название: <b>{name}</b> ✅\n\nШаг 2 из 5. Адрес:", parse_mode="HTML")


@admin_router.message(RestAdd.address)
async def rest_add_address(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    addr = (message.text or "").strip()
    if len(addr) < 5:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком короткий адрес.")
        return
    await state.update_data(address=addr)
    await state.set_state(RestAdd.hours)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Адрес: <b>{addr}</b> ✅\n\nШаг 3 из 5. Часы работы:\n"
                       "Пример: <code>Пн–чт: 10:00–22:00\nПт–вс: 10:00–23:00</code>",
                       parse_mode="HTML")


@admin_router.message(RestAdd.hours)
async def rest_add_hours(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    hours = (message.text or "").strip()
    if not validate_hours_schedule(hours):
        await send_tracked(message.chat.id, message.from_user.id,
                           "Проверь формат и время. Пример:\nПн–чт: 10:00–22:00\nПт–вс: 10:00–23:00")
        return
    await state.update_data(hours=hours)
    await state.set_state(RestAdd.phone)
    await send_tracked(message.chat.id, message.from_user.id,
                       "Часы записаны ✅\n\nШаг 4 из 5. Телефон (или «нет»):")


@admin_router.message(RestAdd.phone)
async def rest_add_phone(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    value = (message.text or "").strip()
    if value.lower() in ("нет", "-", "—", ""):
        value = ""
    else:
        digits = value.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if not digits.isdigit() or len(digits) < 10:
            await send_tracked(message.chat.id, message.from_user.id,
                               "Не похоже на номер. Пример: +79001234567. Или «нет».")
            return
    await state.update_data(phone=value)
    await state.set_state(RestAdd.org)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Телефон: <b>{value or '—'}</b> ✅\n\n"
                       "Шаг 5 из 5. Ссылка на Яндекс Карты (например: <code>vokker/1234567890</code>) или «нет»:",
                       parse_mode="HTML")


@admin_router.message(RestAdd.org)
async def rest_add_org(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
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
                           f"❌ Ресторан с ключом <code>{key}</code> уже существует.",
                           parse_mode="HTML")
        return
    invalidate_rest_cache()
    await db_audit(message.from_user.id, "rest_add", "restaurant", key, name)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Ресторан <b>{name}</b> добавлен (key: <code>{key}</code>)",
                       parse_mode="HTML")
    r = await db_restaurant(key)
    if r:
        await send_tracked(message.chat.id, message.from_user.id,
                           rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("rest_del_ask:"))
async def rest_del_ask(callback: types.CallbackQuery):
    key = callback.data.split(":")[1]
    r = await db_restaurant(key)
    if not r:
        await callback.answer("Не найден", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"🗑 Удалить ресторан <b>{r['name']}</b>?\n\n"
                       "Если к нему привязаны сотрудники — удалить не получится.",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"rest_del_yes:{key}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data=f"restadm:{key}")],
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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"🗑 Удалено.\n\n" + rests_list_text(chunk, page, pages, len(rests)),
                       parse_mode="HTML", reply_markup=rests_list_kb(chunk, page, pages))


# ---------- Пользователи ----------

@admin_router.callback_query(lambda c: c.data == "adm_users")
async def adm_users(callback: types.CallbackQuery):
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_users()
    chunk, page, pages = paginate(rows, 0, PAGE_USERS)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       await users_list_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=users_list_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_users_p:"))
async def adm_users_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_users()
    chunk, page, pages = paginate(rows, page, PAGE_USERS)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       await users_list_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=users_list_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data == "adm_users_search")
async def adm_users_search(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(UserSearch.query)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
        await send_tracked(message.chat.id, message.from_user.id, f"Никого не нашёл по «{q}» 🤷")
        return
    chunk, page, pages = paginate(rows, 0, PAGE_USERS)
    await send_tracked(message.chat.id, message.from_user.id,
                       await users_list_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=users_list_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_user:"))
async def adm_user_card(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    if not target_id:
        await callback.answer("Данные устарели", show_alert=True)
        return
    row = await db_get(target_id)
    await cleanup_chat(callback.from_user.id)
    if not row:
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Пользователь не найден.")
        return
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       await user_card_text(target_id, row), parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, bool(row[6])))


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
        prompt = "🎂 Напиши новую дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)"
        new_state = EditUser.birth_date
    await state.set_state(new_state)
    await state.update_data(edit_target=target_id)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ ФИО обновлено: <b>{name}</b>", parse_mode="HTML")
    row = await db_get(target_id)
    if row:
        await send_tracked(message.chat.id, message.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, bool(row[6])))


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
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Телефон обновлён: <b>{message.text.strip()}</b>", parse_mode="HTML")
    row = await db_get(target_id)
    if row:
        await send_tracked(message.chat.id, message.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, bool(row[6])))


@admin_router.message(EditUser.birth_date)
async def edit_birth_date(message: types.Message, state: FSMContext):
    try:
        birth_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
        if birth_date.year < 1900 or birth_date > datetime.now().date():
            raise ValueError
    except ValueError:
        await delete_incoming(message); await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id,
                           "Такой даты не бывает. Напиши ещё раз в формате ДД.ММ.ГГГГ:")
        return
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    data = await state.get_data()
    target_id = data.get("edit_target")
    await state.clear()
    bd = birth_date.strftime("%d.%m.%Y")
    await db_update_user(target_id, "birth_date", bd)
    await db_audit(message.from_user.id, "user_update", "user", target_id, f"birth_date={bd}")
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Дата рождения обновлена: <b>{bd}</b>", parse_mode="HTML")
    row = await db_get(target_id)
    if row:
        await send_tracked(message.chat.id, message.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, bool(row[6])))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_cancel:"))
async def edit_cancel(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    row = await db_get(target_id)
    if row:
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, bool(row[6])))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_pos:"))
async def edit_pos_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "💼 Выбери новую должность:", reply_markup=await positions_edit_kb(target_id))


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
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"✅ Должность обновлена: <b>{position}</b>", parse_mode="HTML")
    row = await db_get(target_id)
    if row:
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, bool(row[6])))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("edit_rest:"))
async def edit_rest_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    target_id = safe_int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "📍 Выбери новый ресторан:",
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
    rest_name = await restaurant_name_by_key(key)
    await db_audit(callback.from_user.id, "user_update", "user", target_id, f"restaurant={key}")
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"✅ Ресторан обновлён: <b>{rest_name}</b>", parse_mode="HTML")
    row = await db_get(target_id)
    if row:
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, bool(row[6])))


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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"🚫 Заблокировать <b>{row[0] or 'без имени'}</b> (<code>{target_id}</code>)?",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="✅ Да, заблокировать", callback_data=f"adm_ban:{target_id}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm_user:{target_id}")],
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
    if row:
        await cleanup_chat(callback.from_user.id)
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, True))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_unban:"))
async def adm_unban(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if await db_set_blocked(target_id, False):
        await db_audit(callback.from_user.id, "user_unblock", "user", target_id)
        await callback.answer("Разблокирован")
    else:
        await callback.answer("Пользователь не найден", show_alert=True)
    row = await db_get(target_id)
    if row:
        await cleanup_chat(callback.from_user.id)
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           await user_card_text(target_id, row), parse_mode="HTML",
                           reply_markup=user_edit_kb(target_id, False))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_del:"))
async def adm_del_ask(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("Нельзя удалить самого себя", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"🗑 Удалить пользователя <code>{target_id}</code> из базы?\n\n"
                       "Он сможет зарегистрироваться заново.",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"adm_del_yes:{target_id}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_users")],
                       ]))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_del_yes:"))
async def adm_del_yes(callback: types.CallbackQuery):
    target_id = safe_int(callback.data.split(":")[1])
    if await db_delete_user(target_id):
        await db_audit(callback.from_user.id, "user_delete", "user", target_id)
        await callback.answer("Удалён")
        await cleanup_chat(callback.from_user.id)
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           f"🗑 Пользователь <code>{target_id}</code> удалён.", parse_mode="HTML")
    else:
        await callback.answer("Пользователь не найден", show_alert=True)


# ---------- Должности ----------

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
        lines.append(f"• {name}")
    if archived:
        lines.append(f"\n📦 Архив: {len(archived)}")
        for pid, name, sort, arch in archived:
            lines.append(f"• ~~{name}~~")
    kb = [[InlineKeyboardButton(text="➕ Добавить должность", callback_data="pos_add")]]
    for pid, name, sort, arch in active:
        kb.append([InlineKeyboardButton(text=f"📦 Архивировать «{name[:20]}»", callback_data=f"pos_archive:{pid}")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@admin_router.callback_query(lambda c: c.data == "pos_add")
async def pos_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(PosAdmin.name)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
                           f"❌ Должность «{name}» уже существует.")
        return
    await db_audit(message.from_user.id, "pos_add", "position", "", name)
    await send_tracked(message.chat.id, message.from_user.id, f"✅ Должность «{name}» добавлена.")


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
        lines.append(f"• {p[1]}")
    kb = [[InlineKeyboardButton(text="➕ Добавить", callback_data="pos_add")]]
    for p in active:
        kb.append([InlineKeyboardButton(text=f"📦 «{p[1][:20]}»", callback_data=f"pos_archive:{p[0]}")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "\n".join(lines), parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


# ---------- Новости (с отложенной публикацией) ----------

@admin_router.callback_query(lambda c: c.data == "adm_news")
async def adm_news(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, 0, PAGE_NEWS)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_news_p:"))
async def adm_news_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, page, PAGE_NEWS)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data == "news_add")
async def news_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(NewsAdmin.title)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "✍️ Шаг 1 из 3.\nНапиши заголовок новости:",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_news")]
                       ]))


@admin_router.message(NewsAdmin.title)
async def news_add_title(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    if not message.text:
        await send_tracked(message.chat.id, message.from_user.id, "Заголовок должен быть текстом.")
        return
    title = message.text.strip()
    if len(title) > 100:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком длинный заголовок (макс. 100).")
        return
    await state.update_data(title=title)
    await state.set_state(NewsAdmin.body)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Заголовок: <b>{title}</b> ✅\n\n✍️ Шаг 2 из 3.\nТекст новости:",
                       parse_mode="HTML")


@admin_router.message(NewsAdmin.body)
async def news_add_body(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    if not message.text:
        await send_tracked(message.chat.id, message.from_user.id, "Текст должен быть текстом.")
        return
    body = message.text.strip()
    if len(body) > 2000:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком длинный текст (макс. 2000).")
        return
    await state.update_data(body=body)
    await state.set_state(NewsAdmin.important)
    await send_tracked(message.chat.id, message.from_user.id,
                       "Текст записан ✅\n\n✍️ Шаг 3 из 3.\nПометка:",
                       reply_markup=news_important_kb())


@admin_router.callback_query(NewsAdmin.important, lambda c: c.data and c.data.startswith("news_imp:"))
async def news_schedule_choice(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    level = callback.data.split(":")[1]
    if level not in LEVEL_LABELS:
        level = "normal"
    await state.update_data(level=level)
    await state.set_state(NewsAdmin.schedule_choice)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "⏰ Когда опубликовать?",
                       reply_markup=news_schedule_kb())


@admin_router.callback_query(NewsAdmin.schedule_choice, lambda c: c.data == "news_sched_now")
async def news_sched_now(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.update_data(publish_at=None, publish_display=None)
    await state.set_state(NewsAdmin.preview)
    await _show_news_preview(callback.message.chat.id, callback.from_user.id, state)


@admin_router.callback_query(NewsAdmin.schedule_choice, lambda c: c.data == "news_sched_later")
async def news_sched_later(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(NewsAdmin.schedule_time)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "⏰ Введи дату и время публикации:\n\n"
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
                           "Не получилось разобрать дату. Формат: ДД.ММ.ГГГГ ЧЧ:ММ\n"
                           "Пример: 25.11.2026 09:00")
        return
    now_naive = _moscow_now().replace(tzinfo=None)
    if dt <= now_naive:
        await send_tracked(message.chat.id, message.from_user.id,
                           "Дата уже прошла. Введи дату и время в будущем:")
        return
    if MOSCOW_TZ:
        iso = dt.replace(tzinfo=MOSCOW_TZ).isoformat()
    else:
        iso = dt.isoformat()
    display = dt.strftime("%d.%m.%Y %H:%M")
    await state.update_data(publish_at=iso, publish_display=display)
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
        sched_line = f"\n\n⏰ Публикация: <b>{publish_display}</b>\n<i>В это время разошлётся всем автоматически.</i>"
    else:
        sched_line = "\n\n📤 Публикуется сейчас."
    await cleanup_chat(user_id)
    await send_tracked(chat_id, user_id,
                       f"👀 <b>Превью</b> — так увидят сотрудники:\n\n"
                       f"{icon} <b>{title}</b>\n\n{body}{sched_line}\n\n<i>Опубликовать?</i>",
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
                       f"{title} | {'scheduled ' + str(publish_display) if publish_at else 'immediate'}")
    except Exception as e:
        logging.error(f"news_add: {e}")
        await send_tracked(callback.message.chat.id, callback.from_user.id,
                           "❌ Не удалось сохранить. Попробуй позже.")
        return
    if publish_at:
        head = (f"⏰ Новость отложена до <b>{publish_display}</b>.\n"
                "В назначенное время она будет опубликована и разослана автоматически.")
    else:
        head = "✅ Новость опубликована!"
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"{head}\n\n{LEVEL_LABELS[level]} — <b>{title}</b>",
                       parse_mode="HTML")
    rows = await db_list_news_admin()
    chunk, page, pages = paginate(rows, 0, PAGE_NEWS)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))


@admin_router.callback_query(NewsAdmin.preview, lambda c: c.data == "news_restart")
async def news_add_restart(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Начинаем заново")
    await state.clear()
    await state.set_state(NewsAdmin.title)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "✍️ Шаг 1 из 3.\nНапиши заголовок новости:")


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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       news_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=news_admin_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_send:"))
async def news_send_menu(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "📬 Кому разослать?",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="🌍 Всем сотрудникам", callback_data=f"news_ask_all:{news_id}")],
                           [InlineKeyboardButton(text="📍 Одному ресторану", callback_data=f"news_send_rest:{news_id}")],
                           [InlineKeyboardButton(text="🔙 К списку", callback_data="adm_news")],
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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"📬 Разослать «<b>{title}</b>» на <b>{n}</b> сотрудников?",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text=f"✅ Да, отправить ({n})", callback_data=f"news_confirm_all:{news_id}")],
                           [InlineKeyboardButton(text="📤 Сначала мне", callback_data=f"news_test:{news_id}")],
                           [InlineKeyboardButton(text="❌ Отмена", callback_data="adm_news")],
                       ]))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_confirm_all:"))
async def news_confirm_all(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    row = await db_get_news(news_id)
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    lock_key = f"all:{news_id}"
    if not try_lock_broadcast(lock_key):
        await callback.answer("Рассылка уже идёт", show_alert=True)
        return
    title, body, level = row
    await callback.answer("Рассылка запущена")
    await db_audit(callback.from_user.id, "broadcast_all", "news", news_id, title)

    async def _run_bc():
        try:
            await broadcast_news(title, body, level)
        finally:
            unlock_broadcast(lock_key)
    spawn(_run_bc())
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"✅ Рассылка «{title}» запущена. Придёт отчёт по завершении.")


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
        await callback.message.answer(
            f"{icon} <b>{title}</b>\n\n{body}\n\n<i>(тестовая отправка)</i>",
            parse_mode="HTML")
        await callback.answer("Отправлено")
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@admin_router.callback_query(lambda c: c.data and c.data.startswith("news_send_rest:"))
async def news_send_rest(callback: types.CallbackQuery):
    news_id = safe_int(callback.data.split(":")[1])
    await callback.answer()
    kb = [
        [InlineKeyboardButton(text=r["name"], callback_data=f"news_ask_rest:{news_id}:{r['key']}")]
        for r in await db_restaurants_all()
    ]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"news_send:{news_id}")])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
    rest_name = await restaurant_name_by_key(key)
    n = len(await db_list_active_users(key))
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"📬 Разослать «<b>{title}</b>» сотрудникам «<b>{rest_name}</b>» ({n} чел.)?",
                       parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text=f"✅ Да ({n})", callback_data=f"news_confirm_rest:{news_id}:{key}")],
                           [InlineKeyboardButton(text="📤 Сначала мне", callback_data=f"news_test:{news_id}")],
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
    lock_key = f"rest:{news_id}:{key}"
    if not try_lock_broadcast(lock_key):
        await callback.answer("Рассылка уже идёт", show_alert=True)
        return
    title, body, level = row
    rest_name = await restaurant_name_by_key(key)
    await callback.answer("Рассылка запущена")
    await db_audit(callback.from_user.id, "broadcast_rest", "news", news_id, f"{title} → {key}")

    async def _run_bc():
        try:
            await broadcast_news(title, body, level, restaurant_key=key)
        finally:
            unlock_broadcast(lock_key)
    spawn(_run_bc())
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"✅ Рассылка для «{rest_name}» запущена.")


# ---------- Стандарты ----------

STD_FIELDS = {
    "title": ("Название", "✏️ Напиши новое название стандарта:"),
    "category": ("Категория", "✏️ Напиши новую категорию (например: Технология):"),
    "description": ("Описание", "✏️ Напиши новое описание стандарта:"),
    "url": ("Ссылка", "✏️ Пришли ссылку (или «нет», чтобы убрать):"),
}


def std_card_text(row) -> str:
    sid, title, category, description, url = row
    return (
        f"📚 <b>{title}</b>\n"
        f"Категория: {category or '—'}\n"
        f"Описание: {description or '—'}\n"
        f"Ссылка: {url or '—'}")


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
        kb.append([
            InlineKeyboardButton(text=f"📚 {title[:28]}", callback_data=f"std_card:{sid}"),
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
        lines.append(f"• {title}")
    return "\n".join(lines) if rows else "Пока пусто."


@admin_router.callback_query(lambda c: c.data == "adm_std")
async def adm_std(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, 0, PAGE_STD)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       std_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=std_admin_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_std_p:"))
async def adm_std_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, page, PAGE_STD)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Не найден.")
        return
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
    await send_tracked(message.chat.id, message.from_user.id, "✅ Обновлено.")
    rows = [r for r in await db_list_standards() if r[0] == sid]
    if rows:
        await send_tracked(message.chat.id, message.from_user.id,
                           std_card_text(rows[0]), parse_mode="HTML", reply_markup=std_card_kb(sid))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("std_del:"))
async def std_del(callback: types.CallbackQuery):
    sid = safe_int(callback.data.split(":")[1])
    await db_delete_standard(sid)
    await db_audit(callback.from_user.id, "std_delete", "standard", sid)
    await callback.answer("Удалено")
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, 0, PAGE_STD)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       std_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=std_admin_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data == "std_add")
async def std_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(StdAdmin.title)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "📚 Новый стандарт. Шаг 1 из 3. Название:",
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
                       f"Название: <b>{title}</b> ✅\nШаг 2 из 3. Категория:", parse_mode="HTML")


@admin_router.message(StdAdmin.category)
async def std_add_category(message: types.Message, state: FSMContext):
    await delete_incoming(message); await cleanup_chat(message.from_user.id)
    category = (message.text or "").strip()
    await state.update_data(category=category)
    await state.set_state(StdAdmin.description)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Категория: <b>{category}</b> ✅\nШаг 3 из 3. Описание:", parse_mode="HTML")


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
                       f"✅ Стандарт добавлен: <b>{data.get('title')}</b>", parse_mode="HTML")
    rows = await db_list_standards()
    chunk, page, pages = paginate(rows, 0, PAGE_STD)
    await send_tracked(message.chat.id, message.from_user.id,
                       std_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=std_admin_kb(chunk, page, pages))


# ---------- FAQ ----------

FAQ_FIELDS = {
    "question": ("Вопрос", "✏️ Напиши новый текст вопроса:"),
    "answer": ("Ответ", "✏️ Напиши новый текст ответа:"),
}


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
        kb.append([
            InlineKeyboardButton(text=f"❓ {question[:28]}", callback_data=f"faq_edit_show:{fid}"),
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
        lines.append(f"• {q}")
    return "\n".join(lines) if rows else "Пока пусто."


@admin_router.callback_query(lambda c: c.data == "adm_faq")
async def adm_faq(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_faq()
    chunk, page, pages = paginate(rows, 0, PAGE_FAQ)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       faq_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=faq_admin_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_faq_p:"))
async def adm_faq_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_list_faq()
    chunk, page, pages = paginate(rows, page, PAGE_FAQ)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Не найден.")
        return
    _, question, answer, _ = rows[0]
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"❓ <b>{question}</b>\n\n💬 {answer}",
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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
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
                           f"✅ Обновлено.\n\n❓ <b>{question}</b>\n\n💬 {answer}",
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
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       faq_admin_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=faq_admin_kb(chunk, page, pages))


@admin_router.callback_query(lambda c: c.data == "faq_add")
async def faq_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await state.set_state(FaqAdmin.question)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "❓ Новый вопрос. Шаг 1 из 2. Текст вопроса:",
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
                       f"Вопрос: <b>{question}</b> ✅\nШаг 2 из 2. Ответ:", parse_mode="HTML")


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


# ---------- Отчёты + экспорт + аудит ----------

@admin_router.callback_query(lambda c: c.data == "adm_reports")
async def adm_reports(callback: types.CallbackQuery):
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    stats = await get_report_stats()
    rows = await db_list_users()
    positions_count = {}
    restaurants_count = {}
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        if full_name:
            positions_count[position or "Не указана"] = positions_count.get(position or "Не указана", 0) + 1
            rn = await restaurant_name_by_key(restaurant) if restaurant else "Не указан"
            restaurants_count[rn] = restaurants_count.get(rn, 0) + 1
    positions_block = "\n".join(f"• {k}: {v}" for k, v in sorted(positions_count.items(), key=lambda x: -x[1])) or "• пока нет данных"
    restaurants_block = "\n".join(f"• {k}: {v}" for k, v in sorted(restaurants_count.items(), key=lambda x: -x[1])) or "• пока нет данных"
    text = (
        f"📊 <b>Отчёт</b> ({stats['date']})\n\n"
        f"👥 Всего: {stats['total']}\n"
        f"✅ Активных: {stats['active']}\n"
        f"🚫 Заблокированных: {stats['blocked']}\n"
        f"📈 Новых за 7 дней: {stats['new7']}\n"
        f"💤 Не заходили 7+ дней: {stats['inactive7']}\n\n"
        f"<b>По должностям:</b>\n{positions_block}\n\n"
        f"<b>По ресторанам:</b>\n{restaurants_block}")
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       text, parse_mode="HTML",
                       reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                           [InlineKeyboardButton(text="📤 Экспорт пользователей (CSV)", callback_data="adm_export_users")],
                           [InlineKeyboardButton(text="📤 Экспорт новостей (CSV)", callback_data="adm_export_news")],
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
                                caption=f"📤 Пользователи · {len(rows)} записей")
    except Exception as e:
        logging.warning(f"export: {e}")
        await send_tracked(callback.message.chat.id, callback.from_user.id, f"❌ Ошибка: {e}")


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
                                caption=f"📤 Новости · {len(rows)} записей")
    except Exception as e:
        logging.warning(f"export news: {e}")
        await send_tracked(callback.message.chat.id, callback.from_user.id, f"❌ Ошибка: {e}")


@admin_router.callback_query(lambda c: c.data == "adm_audit")
async def adm_audit(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = await db_audit_list(limit=200)
    chunk, page, pages = paginate(rows, 0, PAGE_AUDIT)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       audit_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=audit_kb(page, pages))


@admin_router.callback_query(lambda c: c.data and c.data.startswith("adm_audit_p:"))
async def adm_audit_p(callback: types.CallbackQuery):
    page = safe_int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = await db_audit_list(limit=200)
    chunk, page, pages = paginate(rows, page, PAGE_AUDIT)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       audit_text(chunk, page, pages, len(rows)),
                       parse_mode="HTML", reply_markup=audit_kb(page, pages))


def audit_text(rows, page, pages, total):
    if not rows:
        return "📜 История пуста."
    lines = [f"📜 <b>Последние действия</b> · стр. {page+1}/{pages}\n"]
    for aid, admin_id, action, tt, ti, details, created in rows:
        date = created.strftime("%d.%m %H:%M") if created else ""
        d = (details or "")[:60]
        lines.append(f"<code>{date}</code> · {action} · {tt}:{ti} · {d}")
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


# ================== ФОНОВЫЕ ПРОЦЕССЫ ==================

async def birthday_checker():
    while True:
        try:
            now = _moscow_now()
            year = now.year
            today_md = f"{now.day:02d}.{now.month:02d}"
            for user_id in await db_list_active_users():
                row = await db_get(user_id)
                if not row or not row[2]:
                    continue
                if row[2][:5] == today_md and not await db_already_greeted(user_id, "birthday", year):
                    name = await db_get_first_name(user_id)
                    if not name:
                        name = (row[0] or "").split()[0] if row[0] else "коллега"
                    try:
                        await bot.send_message(
                            user_id,
                            f"🎂 <b>{name}, с Днём рождения!</b>\n\n"
                            "Команда Wokker поздравляет тебя! Пусть год будет лёгким, "
                            "смены — удачными, а гости — благодарными.\n"
                            "Хорошего праздника! 🥳",
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
                            name = await db_get_first_name(user_id) or "коллега"
                            await bot.send_message(user_id, f"{title}\n\n{name}, {text}")
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
    """Раз в минуту публикует наступившие отложенные новости и рассылает их."""
    while True:
        try:
            due = await db_publish_due()
            for news_id, title, body, level, auto_b in due:
                logging.info(f"📤 Опубликована отложенная новость #{news_id}: {title}")
                if auto_b:
                    try:
                        await broadcast_news(title, body, level)
                    except Exception as e:
                        logging.warning(f"scheduled broadcast {news_id}: {e}")
                if ADMIN_ID:
                    try:
                        await bot.send_message(
                            ADMIN_ID,
                            f"⏰ Отложенная новость опубликована:\n\n"
                            f"{LEVEL_LABELS.get(level, LEVEL_LABELS['normal'])} <b>{title}</b>\n"
                            + ("📤 Рассылка запущена автоматически." if auto_b else "")
                        )
                    except Exception:
                        pass
        except Exception as e:
            logging.error(f"scheduled_publisher: {e}")
        await asyncio.sleep(60)


# ================== ВЕБ-СЕРВЕР ==================

def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def denied_response(status: int):
    if status == 403:
        return web.json_response({"error": "blocked"}, status=403, dumps=json_dumps)
    return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)


AVATAR_CACHE = {}
AVATAR_TTL = 600
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


async def handle_favicon(request):
    return web.Response(status=204)


async def handle_index(request):
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "index.html")
    if os.path.exists(p):
        resp = web.FileResponse(p)
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp
    return web.Response(text="frontend/index.html not found", status=404)


async def handle_bootstrap(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    await db_mark_seen(user_id)
    row = await db_get(user_id)
    profile = None
    if row and row[0]:
        full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row
        profile = {
            "full_name": full_name,
            "first_name": await db_get_first_name(user_id) or (full_name.split()[0] if full_name else ""),
            "phone": phone,
            "birth_date": birth_date,
            "position": position or "—",
            "restaurant": await restaurant_name_by_key(restaurant) if restaurant else "—",
        }
    now = _moscow_now()
    kind, title, sub = greeting_for_user(row[2] if row else None, now)
    news_list = [
        {"id": nid, "title": t, "text": b,
         "date": d.strftime("%d.%m.%Y") if d else "",
         "important": bool(imp), "level": lv or "normal"}
        for nid, t, b, imp, lv, d in await db_list_news()
    ]
    standards_list = [
        {"id": sid, "title": t, "category": c, "description": d, "url": u}
        for sid, t, c, d, u in await db_list_standards()
    ]
    faq_list = [
        {"id": fid, "question": q, "answer": a, "category": c}
        for fid, q, a, c in await db_list_faq()
    ]
    return web.json_response({
        "profile": profile,
        "greeting": {"kind": kind, "title": title, "sub": sub},
        "news": news_list,
        "restaurants": await build_restaurants_payload(),
        "standards": standards_list,
        "faq": faq_list,
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
    news_list = [
        {"id": nid, "title": t, "text": b,
         "date": d.strftime("%d.%m.%Y") if d else "",
         "important": bool(imp), "level": lv or "normal"}
        for nid, t, b, imp, lv, d in await db_list_news()
    ]
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
    full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row
    return web.json_response({
        "registered": True,
        "profile": {
            "full_name": full_name,
            "first_name": await db_get_first_name(user_id) or (full_name.split()[0] if full_name else ""),
            "phone": phone,
            "birth_date": birth_date,
            "position": position or "—",
            "restaurant": await restaurant_name_by_key(restaurant) if restaurant else "—",
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
        file_id = photos.photos[0][-1].file_id
        file = await bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url) as r:
                if r.content_length and r.content_length > AVATAR_MAX_BYTES:
                    return web.Response(status=204)
                data = await r.read()
                if len(data) > AVATAR_MAX_BYTES:
                    return web.Response(status=204)
                ctype = r.content_type or "image/jpeg"
        AVATAR_CACHE[user_id] = (data, ctype, datetime.now().timestamp())
        return web.Response(body=data, content_type=ctype)
    except Exception as e:
        logging.warning(f"avatar {user_id}: {e}")
        return web.Response(status=204)


_questions_rate = {}
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
    if now_ts - _questions_rate.get(user_id, 0) < _QUESTIONS_COOLDOWN:
        return web.json_response({"error": "too_fast"}, status=429, dumps=json_dumps)
    _questions_rate[user_id] = now_ts
    if ADMIN_ID:
        row = await db_get(user_id)
        who = row[0] if row and row[0] else "—"
        try:
            await bot.send_message(ADMIN_ID,
                                   f"❓ Вопрос из приложения\n\n👤 {who} (<code>{user_id}</code>)\n💬 {qtext}",
                                   parse_mode="HTML")
        except Exception as e:
            logging.warning(f"question to admin: {e}")
    return web.json_response({"ok": True}, dumps=json_dumps)


async def handle_health(request):
    return web.Response(text="OK")


app = web.Application()
app.router.add_get("/", handle_index)
app.router.add_get("/favicon.ico", handle_favicon)
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


# ================== ЗАПУСК ==================

async def main():
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server on port {port}")
    spawn(birthday_checker())
    spawn(holiday_broadcaster())
    spawn(scheduled_publisher())
    print("STARTING BOT SCRIPT...")
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        for task in list(_bg_tasks):
            task.cancel()
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