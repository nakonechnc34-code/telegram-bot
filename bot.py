import os
import asyncio
import logging
import json
import hmac
import hashlib
import re
import time
import aiohttp
from datetime import datetime, timedelta
from contextlib import contextmanager
from urllib.parse import unquote

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
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
    print("ОШИБКА: Переменная BOT_TOKEN не задана!")
    raise ValueError("BOT_TOKEN is not set")
TOKEN = TOKEN.strip()

ADMIN_ID = os.getenv("ADMIN_ID")
if not ADMIN_ID:
    print("ПРЕДУПРЕЖДЕНИЕ: Переменная ADMIN_ID не задана — админ-панель отключена.")
    ADMIN_ID = None
else:
    ADMIN_ID = int(ADMIN_ID)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("ОШИБКА: Переменная DATABASE_URL не задана!")
    raise ValueError("DATABASE_URL is not set")

MINI_APP_URL = os.getenv("MINI_APP_URL", "https://ВАШ-ДОМЕН.amvera.io")


# ================== ПУЛ СОЕДИНЕНИЙ С БАЗОЙ ==================

_pool = None


def init_pool():
    global _pool
    if _pool is None:
        _pool = SimpleConnectionPool(1, 10, DB_URL)


@contextmanager
def get_conn():
    """Соединение из пула. with conn: сам делает commit/rollback."""
    init_pool()
    conn = _pool.getconn()
    try:
        with conn:
            yield conn
    finally:
        _pool.putconn(conn)


# Стартовые данные. Дальше всё редактируется через админку,
# эти списки используются только для первичного заполнения таблиц.
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
    # ОФИС — только для выбора при регистрации, в приложении не показывается
    {"key": "office", "name": "ОФИС", "address": "Центральный офис (уточните адрес у HR)", "hours": "Пн–пт: 09:00–18:00", "lat": None, "lon": None, "org": "", "phone": ""},
]

STANDARDS_SEED = [
    ("Правила открытия смены", "Чек-листы", "Что проверить перед открытием: оборудование, чистота, касса.", ""),
    ("Стандарт работы вокера", "Технология", "Пошаговый стандарт приготовления блюд на воке.", ""),
    ("Обработка жалоб гостей", "Сервис", "Как реагировать на претензии и когда звать управляющего.", ""),
]

FAQ_SEED = [
    ("Как посмотреть график смен?", "График вывешивается на информационной доске в ресторане и уточняется у управляющего сменой.", "Работа"),
    ("Куда сообщать о поломке оборудования?", "Напиши управляющему сменой. Если поломка серьёзная — он оформляет заявку в сервис.", "Работа"),
    ("Как поменять ресторан в профиле?", "Обратись к администратору — данные в профиле меняются только через админа.", "Бот"),
]


init_pool()

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                birth_date TEXT,
                position TEXT,
                restaurant TEXT,
                welcomed BOOLEAN DEFAULT FALSE,
                is_blocked BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS position TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS restaurant TEXT")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE")
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_name TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_messages (
                user_id BIGINT,
                message_id BIGINT,
                PRIMARY KEY (user_id, message_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_messages (
                user_id BIGINT,
                message_id BIGINT,
                PRIMARY KEY (user_id, message_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                important BOOLEAN DEFAULT FALSE,
                level TEXT DEFAULT 'normal',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS level TEXT DEFAULT 'normal'")
        cur.execute("ALTER TABLE news ADD COLUMN IF NOT EXISTS photo_file_id TEXT")
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
                sort INT DEFAULT 100
            )
        """)
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS force_status TEXT")
        cur.execute("ALTER TABLE restaurants ADD COLUMN IF NOT EXISTS sort INT DEFAULT 100")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS standards (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT DEFAULT '',
                description TEXT DEFAULT '',
                url TEXT DEFAULT ''
            )
        """)
        cur.execute("ALTER TABLE standards ADD COLUMN IF NOT EXISTS photo_file_id TEXT")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS faq (
                id SERIAL PRIMARY KEY,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT DEFAULT ''
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS greetings_log (
                user_id BIGINT,
                kind TEXT,
                year INT,
                PRIMARY KEY (user_id, kind, year)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS holiday_broadcast_log (
                kind TEXT,
                year INT,
                PRIMARY KEY (kind, year)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_users_blocked ON users (is_blocked)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_created ON news (created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bot_msgs_user ON bot_messages (user_id, message_id DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_msgs_user ON user_messages (user_id, message_id DESC)")
        cur.execute("SELECT COUNT(*) FROM news")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s)",
                ("Открытие новой точки", "Скоро открываем новый ресторан! Подробности расскажет управляющий на ближайшей смене.", True, "urgent")
            )
            cur.execute(
                "INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s)",
                ("Обновление меню", "В сезоне осень появились новые позиции — уточните состав у шеф-повара на смене.", False, "normal")
            )
        cur.execute("SELECT COUNT(*) FROM restaurants")
        if cur.fetchone()[0] == 0:
            for i, r in enumerate(RESTAURANTS_SEED):
                sort = 999 if r["key"] == "office" else i
                cur.execute(
                    "INSERT INTO restaurants (key, name, address, hours, lat, lon, org, phone, sort) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (r["key"], r["name"], r["address"], r["hours"], r["lat"], r["lon"], r["org"], r["phone"], sort)
                )
        cur.execute("SELECT COUNT(*) FROM standards")
        if cur.fetchone()[0] == 0:
            for t, c, d, u in STANDARDS_SEED:
                cur.execute(
                    "INSERT INTO standards (title, category, description, url) VALUES (%s, %s, %s, %s)",
                    (t, c, d, u)
                )
        cur.execute("SELECT COUNT(*) FROM faq")
        if cur.fetchone()[0] == 0:
            for q, a, c in FAQ_SEED:
                cur.execute(
                    "INSERT INTO faq (question, answer, category) VALUES (%s, %s, %s)",
                    (q, a, c)
                )
print("База данных подключена, таблицы готовы.")


POSITIONS = [
    "Холодный Цех",
    "Жарщик",
    "Управляющий сменой",
    "Территориальный управляющий",
]


# ================== ПРАЗДНИКИ И ПОЗДРАВЛЕНИЯ ==================

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


def _moscow_now():
    if MOSCOW_TZ:
        return datetime.now(MOSCOW_TZ)
    return datetime.utcnow() + timedelta(hours=3)


def greeting_for_user(birth_date: str, now=None):
    """Возвращает (kind, title, sub): 'birthday', 'holiday' или 'normal'."""
    now = now or _moscow_now()
    if birth_date:
        try:
            b = datetime.strptime(birth_date, "%d.%m.%Y")
            if (b.month, b.day) == (now.month, now.day):
                return (
                    "birthday",
                    "🎂 С Днём рождения!",
                    "Вся команда Wokker поздравляет вас. Пусть этот день будет вкусным и счастливым!",
                )
        except ValueError:
            pass
    hol = HOLIDAYS.get((now.month, now.day))
    if hol:
        return ("holiday", hol[0], hol[1])
    return ("normal", "", "")


def db_already_greeted(user_id: int, kind: str, year: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM greetings_log WHERE user_id = %s AND kind = %s AND year = %s",
                (user_id, kind, year)
            )
            return cur.fetchone() is not None


def db_mark_greeted(user_id: int, kind: str, year: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO greetings_log (user_id, kind, year) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (user_id, kind, year)
            )


def db_holiday_broadcast_done(kind: str, year: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM holiday_broadcast_log WHERE kind = %s AND year = %s",
                (kind, year)
            )
            return cur.fetchone() is not None


def db_mark_holiday_broadcast(kind: str, year: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO holiday_broadcast_log (kind, year) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (kind, year)
            )


# ================== СТАТУС РЕСТОРАНОВ ПО РЕЖИМУ РАБОТЫ ==================

DAY_MAP = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
DAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

REST_CACHE = {"data": None, "ts": 0.0}
REST_CACHE_TTL = 60  # секунд


def invalidate_rest_cache():
    REST_CACHE["data"] = None
    REST_CACHE["ts"] = 0.0


def parse_hours(hours_text: str):
    """Разбирает текст часов в расписание: {0..6: (открытие_мин, закрытие_мин)}."""
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
        if close_m == 0:
            close_m = 1440
        days = set()
        for chunk in days_part.replace(";", ",").split(","):
            chunk = chunk.strip().lower()
            if not chunk:
                continue
            rng = re.findall(r"[а-яё]{2}", chunk)
            if len(rng) >= 2 and ("–" in chunk or "-" in chunk or "—" in chunk):
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
    return f"{total_min // 60:02d}:{total_min % 60:02d}"


def restaurant_status(hours_text: str):
    """Возвращает (status, status_text) по текущему московскому времени."""
    schedule = parse_hours(hours_text)
    now = _moscow_now()
    cur = now.hour * 60 + now.minute
    dow = now.weekday()

    today = schedule.get(dow)
    if today:
        o, c = today
        if o <= cur < c:
            return "open", f"Открыто до {_fmt_minutes(c)}"

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
    """Статус с учётом ручного переопределения из админки."""
    fs = r.get("force_status")
    if fs == "open":
        return "open", "Открыто (администратором)"
    if fs == "closed":
        return "closed", "Закрыто (администратором)"
    return restaurant_status(r.get("hours") or "")


# ================== БАЗА ДАННЫХ ==================

RESTAURANT_DB_FIELDS = ("name", "address", "phone", "hours", "org")


def db_restaurants_all():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, name, address, hours, lat, lon, org, phone, force_status, sort "
                "FROM restaurants ORDER BY sort, name"
            )
            cols = ["key", "name", "address", "hours", "lat", "lon", "org", "phone", "force_status", "sort"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def db_restaurants_for_app():
    return [r for r in db_restaurants_all() if r["key"] != "office"]


def db_restaurant(key: str):
    for r in db_restaurants_all():
        if r["key"] == key:
            return r
    return None


def db_restaurant_update(key: str, field: str, value: str) -> bool:
    if field not in RESTAURANT_DB_FIELDS:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE restaurants SET {field} = %s WHERE key = %s", (value, key))
            return cur.rowcount > 0


def db_restaurant_set_status(key: str, force_status) -> bool:
    if force_status not in (None, "open", "closed"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE restaurants SET force_status = %s WHERE key = %s", (force_status, key))
            return cur.rowcount > 0


def db_get(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT full_name, phone, birth_date, position, restaurant, welcomed, is_blocked "
                "FROM users WHERE user_id = %s",
                (user_id,)
            )
            return cur.fetchone()


def db_get_first_name(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT first_name FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None


def db_set_welcomed(user_id: int, first_name: str = None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id, welcomed, first_name) VALUES (%s, TRUE, %s) "
                "ON CONFLICT (user_id) DO UPDATE SET welcomed = TRUE, "
                "first_name = COALESCE(EXCLUDED.first_name, users.first_name)",
                (user_id, first_name)
            )


def db_save_profile(user_id: int, full_name: str, phone: str, birth_date: str, position: str, restaurant, first_name: str = None):
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
                 full_name, phone, birth_date, position, restaurant)
            )


def db_update_user(user_id: int, field: str, value: str) -> bool:
    allowed = ("full_name", "phone", "birth_date", "position", "restaurant")
    if field not in allowed:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE users SET {field} = %s WHERE user_id = %s", (value, user_id))
            return cur.rowcount > 0


def db_is_blocked(user_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT is_blocked FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return bool(row and row[0])


def db_list_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, full_name, phone, position, restaurant, welcomed, is_blocked
                FROM users
                ORDER BY user_id
            """)
            return cur.fetchall()


def db_list_active_users(restaurant_key=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            if restaurant_key:
                cur.execute(
                    "SELECT user_id FROM users "
                    "WHERE is_blocked = FALSE AND full_name IS NOT NULL AND restaurant = %s",
                    (restaurant_key,)
                )
            else:
                cur.execute(
                    "SELECT user_id FROM users WHERE is_blocked = FALSE AND full_name IS NOT NULL"
                )
            return [r[0] for r in cur.fetchall()]


def db_delete_user(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
            return cur.rowcount > 0


def db_set_blocked(user_id: int, blocked: bool):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_blocked = %s WHERE user_id = %s", (blocked, user_id))
            return cur.rowcount > 0


def get_report_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = FALSE")
            active = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
            blocked = cur.fetchone()[0] or 0
    return {
        "total": total,
        "active": active,
        "blocked": blocked,
        "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
    }


def db_add_news(title: str, body: str, level: str, photo_file_id: str = None) -> int:
    if level not in ("urgent", "important", "normal"):
        level = "normal"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO news (title, body, important, level, photo_file_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (title, body, level != "normal", level, photo_file_id)
            )
            return cur.fetchone()[0]


def db_list_news():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, body, important, level, created_at, photo_file_id "
                "FROM news ORDER BY created_at DESC, id DESC"
            )
            return cur.fetchall()


def db_get_news(news_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, body, level, photo_file_id FROM news WHERE id = %s", (news_id,))
            return cur.fetchone()


def db_delete_news(news_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news WHERE id = %s", (news_id,))
            return cur.rowcount > 0


def db_update_news_photo(news_id: int, photo_file_id) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE news SET photo_file_id = %s WHERE id = %s", (photo_file_id, news_id))
            return cur.rowcount > 0


def db_list_standards():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, category, description, url, photo_file_id FROM standards ORDER BY id"
            )
            return cur.fetchall()


def db_add_standard(title: str, category: str, description: str, url: str = "", photo_file_id: str = None) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO standards (title, category, description, url, photo_file_id) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                (title, category, description, url or "", photo_file_id)
            )
            return cur.fetchone()[0]


def db_delete_standard(sid: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM standards WHERE id = %s", (sid,))
            return cur.rowcount > 0


def db_update_standard(sid: int, field: str, value: str) -> bool:
    if field not in ("title", "category", "description", "url"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE standards SET {field} = %s WHERE id = %s", (value, sid))
            return cur.rowcount > 0


def db_update_standard_photo(sid: int, photo_file_id) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE standards SET photo_file_id = %s WHERE id = %s", (photo_file_id, sid))
            return cur.rowcount > 0


def db_list_faq():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, question, answer, category FROM faq ORDER BY id")
            return cur.fetchall()


def db_add_faq(question: str, answer: str, category: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO faq (question, answer, category) VALUES (%s, %s, %s)", (question, answer, category))


def db_delete_faq(fid: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM faq WHERE id = %s", (fid,))
            return cur.rowcount > 0


def db_update_faq(fid: int, field: str, value: str) -> bool:
    if field not in ("question", "answer"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE faq SET {field} = %s WHERE id = %s", (value, fid))
            return cur.rowcount > 0


def db_add_bot_msg(user_id: int, message_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bot_messages (user_id, message_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, message_id)
            )


def db_get_and_trim_bot_msgs(user_id: int, keep: int = 1):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT message_id FROM bot_messages WHERE user_id = %s ORDER BY message_id DESC",
                (user_id,)
            )
            ids = [r[0] for r in cur.fetchall()]
            for mid in ids[keep:]:
                cur.execute("DELETE FROM bot_messages WHERE user_id = %s AND message_id = %s", (user_id, mid))
            return ids[keep:]


def db_add_user_msg(user_id: int, message_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO user_messages (user_id, message_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (user_id, message_id)
            )


def db_get_and_trim_user_msgs(user_id: int, keep: int = 1):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT message_id FROM user_messages WHERE user_id = %s ORDER BY message_id DESC",
                (user_id,)
            )
            ids = [r[0] for r in cur.fetchall()]
            for mid in ids[keep:]:
                cur.execute("DELETE FROM user_messages WHERE user_id = %s AND message_id = %s", (user_id, mid))
            return ids[keep:]
# ================== КЛАВИАТУРЫ ==================

def kb_main_menu(user_id: int):
    """Главное меню после регистрации (без кнопки «Профиль» и «Наши рестораны», как просили)."""
    is_admin = (ADMIN_ID is not None and user_id == ADMIN_ID)
    buttons = [
        [InlineKeyboardButton(text="📰 Новости", callback_data="news_list")],
        [InlineKeyboardButton(text="📚 Стандарты", callback_data="standards_list")],
        [InlineKeyboardButton(text="❓ FAQ", callback_data="faq_list")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🛠 Админка", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_restaurants_list():
    """Список ресторанов — только для регистрации (потом не показывается)."""
    rests = db_restaurants_all()
    rows = []
    for r in rests:
        if r["key"] == "office":
            continue
        rows.append([InlineKeyboardButton(text=r["name"], callback_data=f"reg_restaurant:{r['key']}")])
    rows.append([InlineKeyboardButton(text="⬅ Назад", callback_data="reg_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def kb_positions_list():
    buttons = []
    for p in POSITIONS:
        buttons.append([InlineKeyboardButton(text=p, callback_data=f"reg_position:{p}")])
    buttons.append([InlineKeyboardButton(text="⬅ Назад", callback_data="reg_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_news_list(news_rows):
    buttons = []
    for n in news_rows:
        news_id, title, _, important, level, _, _ = n
        icon = "🚨" if important else "📢"
        buttons.append([InlineKeyboardButton(text=f"{icon} {title}", callback_data=f"news_view:{news_id}")])
    buttons.append([InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_standards_list(rows):
    buttons = []
    for s in rows:
        sid, title, category, _, _, _ = s
        buttons.append([InlineKeyboardButton(text=f"📜 {title} ({category})", callback_data=f"standard_view:{sid}")])
    buttons.append([InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_faq_list(rows):
    buttons = []
    for f in rows:
        fid, question, _, _ = f
        buttons.append([InlineKeyboardButton(text=f"❓ {question}", callback_data=f"faq_view:{fid}")])
    buttons.append([InlineKeyboardButton(text="⬅ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_admin_panel():
    buttons = [
        [InlineKeyboardButton(text="👥 Пользователи (отчёт)", callback_data="admin_users")],
        [InlineKeyboardButton(text="📊 Отчёты", callback_data="admin_reports")],
        [InlineKeyboardButton(text="📝 Новости (добавить)", callback_data="admin_news_add")],
        [InlineKeyboardButton(text="📜 Стандарты (добавить)", callback_data="admin_standards_add")],
        [InlineKeyboardButton(text="❓ FAQ (добавить)", callback_data="admin_faq_add")],
        [InlineKeyboardButton(text="📍 Рестораны (статус)", callback_data="admin_rest_status")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def kb_admin_users_actions(user_id: int, is_blocked: bool):
    status_text = "✅ Разблокировать" if is_blocked else "🚫 Заблокировать"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=status_text, callback_data=f"admin_user_toggle:{user_id}")],
        [InlineKeyboardButton(text="🗑 Удалить доступ", callback_data=f"admin_user_delete:{user_id}")],
        [InlineKeyboardButton(text="⬅ Список пользователей", callback_data="admin_users")],
    ])


def kb_admin_rest_status(key: str, status_text: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🟢 Принудительно ОТКРЫТ", callback_data=f"admin_rest_force:{key}:open"),
            InlineKeyboardButton(text="🔴 Принудительно ЗАКРЫТ", callback_data=f"admin_rest_force:{key}:closed"),
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_rest_status")],
    ])


# ================== FSM (машина состояний) ==================

class RegState(StatesGroup):
    waiting_name = State()
    waiting_phone = State()
    waiting_birth = State()
    waiting_position = State()
    waiting_restaurant = State()


class NewsAddState(StatesGroup):
    waiting_title = State()
    waiting_body = State()
    waiting_level = State()  # urgent/important/normal


class StandardAddState(StatesGroup):
    waiting_title = State()
    waiting_category = State()
    waiting_desc = State()
    waiting_url = State()


class FAQAddState(StatesGroup):
    waiting_question = State()
    waiting_answer = State()
    waiting_category = State()


# ================== ОБРАБОТЧИКИ БОТА ==================

bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if db_is_blocked(user_id):
        await message.answer("Доступ к боту заблокирован администратором.")
        return

    # Если уже зарегистрирован — сразу главное меню
    profile = db_get(user_id)
    if profile and profile[5]:  # welcomed == True
        first_name = db_get_first_name(user_id) or "Сотрудник"
        kind, title, sub = greeting_for_user(profile[4] or "")  # birth_date
        if kind == "normal":
            text = f"Привет, {first_name}! Добро пожаловать в корпоративный бот Wokker."
        else:
            text = f"{title}\n{sub}"
        await message.answer(text, reply_markup=kb_main_menu(user_id))
        return

    # Иначе — регистрация
    await state.set_state(RegState.waiting_name)
    await message.answer(
        "Добро пожаловать в бот Wokker!\n"
        "Пожалуйста, представьтесь (ФИО):",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.callback_query(F.data == "reg_back")
async def cb_reg_back(callback: types.CallbackQuery, state: FSMContext):
    await cmd_start(callback.message, state)


@dp.callback_query(F.data.startswith("reg_restaurant:"))
async def cb_reg_restaurant(callback: types.CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    await state.update_data(restaurant_key=key)
    await callback.message.edit_text(
        "Выберите должность:",
        reply_markup=kb_positions_list()
    )


@dp.callback_query(F.data.startswith("reg_position:"))
async def cb_reg_position(callback: types.CallbackQuery, state: FSMContext):
    position = callback.data.split(":")[1]
    data = await state.get_data()
    first_name = data.get("first_name", "")
    full_name = data.get("full_name", first_name)
    phone = data.get("phone", "")
    birth_date = data.get("birth_date", "")
    restaurant_key = data.get("restaurant_key", "")

    db_save_profile(
        callback.from_user.id, full_name, phone, birth_date, position, restaurant_key, first_name
    )
    db_set_welcomed(callback.from_user.id, first_name)

    await state.clear()
    await callback.message.edit_text(
        f"Регистрация завершена, {first_name}!",
        reply_markup=kb_main_menu(callback.from_user.id)
    )


@dp.message(RegState.waiting_name)
async def reg_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Пожалуйста, введите полное имя (минимум 2 символа).")
        return
    await state.update_data(full_name=name, first_name=name.split()[0])
    await state.set_state(RegState.waiting_phone)
    await message.answer("Введите номер телефона (можно без +7, только цифры и пробелы):")


@dp.message(RegState.waiting_phone)
async def reg_phone(message: types.Message, state: FSMContext):
    phone = re.sub(r"[^0-9]", "", message.text)
    if len(phone) < 7:
        await message.answer("Номер слишком короткий. Пожалуйста, введите корректный номер.")
        return
    await state.update_data(phone=phone)
    await state.set_state(RegState.waiting_birth)
    await message.answer("Дата рождения (ДД.ММ.ГГГГ):")


@dp.message(RegState.waiting_birth)
async def reg_birth(message: types.Message, state: FSMContext):
    date_str = message.text.strip()
    try:
        datetime.strptime(date_str, "%d.%m.%Y")
    except ValueError:
        await message.answer("Неверный формат. Пожалуйста, используйте ДД.ММ.ГГГГ (например, 01.01.1990).")
        return
    await state.update_data(birth_date=date_str)
    await state.set_state(RegState.waiting_restaurant)
    await message.answer("Выберите ресторан:", reply_markup=kb_restaurants_list())


# --- Новости ---

@dp.callback_query(F.data == "news_list")
async def cb_news_list(callback: types.CallbackQuery):
    rows = db_list_news()
    if not rows:
        await callback.answer("Новостей пока нет.", show_alert=True)
        return
    await callback.message.edit_text("📰 Новости:", reply_markup=kb_news_list(rows))


@dp.callback_query(F.data.startswith("news_view:"))
async def cb_news_view(callback: types.CallbackQuery):
    news_id = int(callback.data.split(":")[1])
    row = db_get_news(news_id)
    if not row:
        await callback.answer("Новость не найдена.", show_alert=True)
        return
    title, body, level, photo_file_id = row
    text = f"<b>{title}</b>\n\n{body}"
    if photo_file_id:
        await callback.message.answer_photo(photo=photo_file_id, caption=text, parse_mode="HTML")
    else:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="news_list")]]))


# --- Стандарты ---

@dp.callback_query(F.data == "standards_list")
async def cb_standards_list(callback: types.CallbackQuery):
    rows = db_list_standards()
    if not rows:
        await callback.answer("Стандартов пока нет.", show_alert=True)
        return
    await callback.message.edit_text("📚 Стандарты:", reply_markup=kb_standards_list(rows))


@dp.callback_query(F.data.startswith("standard_view:"))
async def cb_standard_view(callback: types.CallbackQuery):
    sid = int(callback.data.split(":")[1])
    cur = None
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, category, description, url, photo_file_id FROM standards WHERE id = %s", (sid,))
            row = cur.fetchone()
    if not row:
        await callback.answer("Стандарт не найден.", show_alert=True)
        return
    title, category, desc, url, photo_file_id = row
    text = f"<b>{title} ({category})</b>\n\n{desc}"
    if url:
        text += f"\n\nСсылка: {url}"
    if photo_file_id:
        await callback.message.answer_photo(photo=photo_file_id, caption=text, parse_mode="HTML")
    else:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="standards_list")]]))


# --- FAQ ---

@dp.callback_query(F.data == "faq_list")
async def cb_faq_list(callback: types.CallbackQuery):
    rows = db_list_faq()
    if not rows:
        await callback.answer("FAQ пуст.", show_alert=True)
        return
    await callback.message.edit_text("❓ Часто задаваемые вопросы:", reply_markup=kb_faq_list(rows))


@dp.callback_query(F.data.startswith("faq_view:"))
async def cb_faq_view(callback: types.CallbackQuery):
    fid = int(callback.data.split(":")[1])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT question, answer, category FROM faq WHERE id = %s", (fid,))
            row = cur.fetchone()
    if not row:
        await callback.answer("Вопрос не найден.", show_alert=True)
        return
    q, a, c = row
    text = f"<b>❓ {q}</b>\n\n{a}"
    await callback.message.answer(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅ Назад", callback_data="faq_list")]]))


# --- Админка ---

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет доступа к админке.", show_alert=True)
        return
    await callback.message.edit_text("🛠 Панель администратора:", reply_markup=kb_admin_panel())


@dp.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    rows = db_list_users()
    if not rows:
        await callback.answer("Пользователей нет.", show_alert=True)
        return
    text_lines = []
    buttons = []
    for uid, name, phone, pos, rest, welcomed, blocked in rows:
        status_icon = "🚫" if blocked else "✅"
        name_short = (name or "—")[:20]
        text_lines.append(f"{status_icon} <b>{name_short}</b> | {pos or '—'} | {rest or '—'}")
        buttons.append([InlineKeyboardButton(text=f"⚙️ {name_short}", callback_data=f"admin_user_detail:{uid}")])
    text = "👥 Список пользователей:\n\n" + "\n".join(text_lines)
    kb = InlineKeyboardMarkup(inline_keyboard=buttons + [[InlineKeyboardButton
        # Продолжение kb_admin_panel...
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="main_menu")]
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- Продолжение обработчиков админки ---

@dp.callback_query(F.data.startswith("admin_user_detail:"))
async def cb_admin_user_detail(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    uid = int(callback.data.split(":")[1])
    profile = db_get(uid)
    if not profile:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    user_id, full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = profile
    first_name = db_get_first_name(uid) or "—"

    status_icon = "🚫" if is_blocked else "✅"
    text = (
        f"👤 Профиль пользователя\n\n"
        f"{status_icon} <b>{first_name}</b>\n"
        f"Полное имя: {full_name or '—'}\n"
        f"Телефон: {phone or '—'}\n"
        f"Дата рождения: {birth_date or '—'}\n"
        f"Должность: {position or '—'}\n"
        f"Ресторан: {restaurant or '—'}"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb_admin_users_actions(uid, is_blocked))


@dp.callback_query(F.data.startswith("admin_user_toggle:"))
async def cb_admin_user_toggle(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    uid = int(callback.data.split(":")[1])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT is_blocked FROM users WHERE user_id = %s", (uid,))
            row = cur.fetchone()
            if row:
                new_val = not row[0]
                cur.execute("UPDATE users SET is_blocked = %s WHERE user_id = %s", (new_val, uid))
    await cb_admin_user_detail(callback)


@dp.callback_query(F.data.startswith("admin_user_delete:"))
async def cb_admin_user_delete(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    uid = int(callback.data.split(":")[1])
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM bot_messages WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM user_messages WHERE user_id = %s", (uid,))
    await callback.answer("Пользователь удалён.", show_alert=True)
    await cb_admin_users(callback)


@dp.callback_query(F.data == "admin_reports")
async def cb_admin_reports(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    # Простой отчёт: сколько пользователей, сколько активных, сколько заблокированных
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE is_blocked = TRUE")
            blocked = cur.fetchone()[0]
            active = total - blocked

            cur.execute("SELECT COUNT(*) FROM news")
            news_count = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM restaurants")
            rest_count = cur.fetchone()[0]

    text = (
        "📊 Отчёт по системе\n\n"
        f"Всего пользователей: {total}\n"
        f"Активных: {active}\n"
        f"Заблокированных: {blocked}\n\n"
        f"Новостей: {news_count}\n"
        f"Точек ресторанов: {rest_count}"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ]))


@dp.callback_query(F.data == "admin_rest_status")
async def cb_admin_rest_status(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    rows = db_restaurants_all()
    buttons = []
    for r in rows:
        key = r["key"]
        name = r["name"]
        force_status = r.get("force_status", "")
        status_text = force_status or "Авто"
        buttons.append([
            InlineKeyboardButton(
                text=f"📍 {name} ({status_text})",
                callback_data=f"admin_rest_force_show:{key}"
            )
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    await callback.message.edit_text("📍 Управление статусами ресторанов:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data.startswith("admin_rest_force_show:"))
async def cb_admin_rest_force_show(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    key = callback.data.split(":")[1]
    r = db_restaurant_by_key(key)
    name = r["name"] if r else "Неизвестно"
    force_status = (r or {}).get("force_status") or "Авто"
    await callback.message.edit_text(
        f"📍 Ресторан: {name}\nТекущий принудительный статус: {force_status or 'Авто'}\n\nВыберите действие:",
        reply_markup=kb_admin_rest_status(key, force_status)
    )


@dp.callback_query(F.data.startswith("admin_rest_force:"))
async def cb_admin_rest_force(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    parts = callback.data.split(":")
    key, status = parts[1], parts[2]
    with get_conn() as conn:
        with conn.cursor() as cur:
            if status == "open":
                cur.execute("UPDATE restaurants SET force_status = 'open' WHERE key = %s", (key,))
            elif status == "closed":
                cur.execute("UPDATE restaurants SET force_status = 'closed' WHERE key = %s", (key,))
            else:
                cur.execute("UPDATE restaurants SET force_status = NULL WHERE key = %s", (key,))
    await cb_admin_rest_status(callback)


# --- Новости (админка) ---

@dp.callback_query(F.data == "admin_news_add")
async def cb_admin_news_add(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    await state.set_state(NewsAddState.waiting_title)
    await callback.message.edit_text("Введите заголовок новости:")


@dp.message(NewsAddState.waiting_title)
async def news_add_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(NewsAddState.waiting_body)
    await message.answer("Теперь введите текст новости:")


@dp.message(NewsAddState.waiting_body)
async def news_add_body(message: types.Message, state: FSMContext):
    await state.update_data(body=message.text)
    await state.set_state(NewsAddState.waiting_level)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚨 Срочный (urgent)", callback_data="news_level:urgent"),
            InlineKeyboardButton(text="⚠️ Важный (important)", callback_data="news_level:important"),
        ],
        [InlineKeyboardButton(text="ℹ Обычный (normal)", callback_data="news_level:normal")],
    ])
    await message.answer("Выберите уровень важности:", reply_markup=kb)


@dp.callback_query(F.data.startswith("news_level:"))
async def news_add_level(callback: types.CallbackQuery, state: FSMContext):
    level = callback.data.split(":")[1]
    data = await state.get_data()
    title = data["title"]
    body = data["body"]

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s)",
                (title, body, level == "urgent", level)
            )
    await state.clear()
    await callback.message.edit_text("✅ Новость добавлена!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin_panel")]
    ]))


# --- Вспомогательные функции (DB helpers) ---

def db_is_blocked(user_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT is_blocked FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row else False


def db_get(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id, full_name, phone, birth_date, position, restaurant, welcomed, is_blocked "
                "FROM users WHERE user_id = %s",
                (user_id,)
            )
            return cur.fetchone()


def db_get_first_name(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT first_name FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else None


def db_save_profile(user_id, full_name, phone, birth_date, position, restaurant_key, first_name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, full_name, phone, birth_date, position, restaurant, first_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    phone = EXCLUDED.phone,
                    birth_date = EXCLUDED.birth_date,
                    position = EXCLUDED.position,
                    restaurant = EXCLUDED.restaurant,
                    first_name = EXCLUDED.first_name
            """, (user_id, full_name, phone, birth_date, position, restaurant_key, first_name))


def db_set_welcomed(user_id, first_name):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET welcomed = TRUE, first_name = %s WHERE user_id = %s", (first_name, user_id))


def db_list_news():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, body, important, level, created_at, photo_file_id FROM news ORDER BY created_at DESC")
            return cur.fetchall()


def db_get_news(news_id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT title, body, level, photo_file_id FROM news WHERE id = %s", (news_id,))
            return cur.fetchone()


def db_list_standards():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, category, description, url, photo_file_id FROM standards")
            return cur.fetchall()


def db_list_faq():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, question, answer, category FROM faq")
            return cur.fetchall()


def db_list_users():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, full_name, phone, position, restaurant, welcomed, is_blocked FROM users ORDER BY user_id")
            return cur.fetchall()


def db_restaurants_all():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT key, name, address, hours, lat, lon, org, phone, force_status, sort FROM restaurants ORDER BY sort")
            rows = cur.fetchall()
            return [
                {
                    "key": r[0], "name": r[1], "address": r[2], "hours": r[3],
                    "lat": r[4], "lon": r[5], "org": r[6], "phone": r[7],
                    "force_status": r[8], "sort": r[9]
                }
                for r in rows
            ]


def db_restaurant_by_key(key: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM restaurants WHERE key = %s", (key,))
            r = cur.fetchone()
            if not r:
                return None
            cols = ["key", "name", "address", "hours", "lat", "lon", "org", "phone", "force_status", "sort"]
            return dict(zip(cols, r))


def greeting_for_user(birth_date_str: str):
    """Простая логика поздравлений по дню рождения (без внешних API)."""
    if not birth_date_str:
        return "normal", "", ""
    try:
        b = datetime.strptime(birth_date_str, "%d.%m.%Y")
        today = datetime.now(MOSCOW_TZ) if MOSCOW_TZ else datetime.now()
        if b.day == today.day and b.month == today.month:
            return "holiday", "🎂 С Днём Рождения!", "Поздравляем! Пусть день будет вкусным и спокойным."
    except Exception:
        pass
    return "normal", "", ""


# ================== ЗАПУСК ==================

async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
