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
from aiogram import Bot, Dispatcher, types
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


# Стартовые данные ресторанов. Дальше всё редактируется через админку,
# этот список используется только для первичного заполнения таблицы.
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

# Стартовые стандарты и FAQ. Дальше всё редактируется через админку,
# этот список используется только для первичного заполнения таблиц.
STANDARDS = [
    {
        "id": 1,
        "title": "Правила открытия смены",
        "category": "Чек-листы",
        "description": "Что проверить перед открытием: оборудование, чистота, касса.",
        "url": "",
    },
    {
        "id": 2,
        "title": "Стандарт работы вокера",
        "category": "Технология",
        "description": "Пошаговый стандарт приготовления блюд на воке.",
        "url": "",
    },
    {
        "id": 3,
        "title": "Обработка жалоб гостей",
        "category": "Сервис",
        "description": "Как реагировать на претензии и когда звать управляющего.",
        "url": "",
    },
]

FAQ = [
    {
        "id": 1,
        "question": "Как посмотреть график смен?",
        "answer": "График вывешивается на информационной доске в ресторане и уточняется у управляющего сменой.",
        "category": "Работа",
    },
    {
        "id": 2,
        "question": "Куда сообщать о поломке оборудования?",
        "answer": "Напиши управляющему сменой. Если поломка серьёзная — он оформляет заявку в сервис.",
        "category": "Работа",
    },
    {
        "id": 3,
        "question": "Как поменять ресторан в профиле?",
        "answer": "Обратись к администратору — данные в профиле меняются только через админа.",
        "category": "Бот",
    },
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
        # Индексы для быстрых запросов
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
            for s in STANDARDS:
                cur.execute(
                    "INSERT INTO standards (title, category, description, url) VALUES (%s, %s, %s, %s)",
                    (s["title"], s["category"], s["description"], s["url"] or "")
                )
        cur.execute("SELECT COUNT(*) FROM faq")
        if cur.fetchone()[0] == 0:
            for f in FAQ:
                cur.execute(
                    "INSERT INTO faq (question, answer, category) VALUES (%s, %s, %s)",
                    (f["question"], f["answer"], f["category"])
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


# --- Журналы поздравлений (защита от дублей) ---

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


# --- Фоновые процессы ---

async def birthday_checker():
    """Раз в час: поздравляет сотрудников с днём рождения (по московскому времени). Обращение по имени."""
    while True:
        try:
            now = _moscow_now()
            year = now.year
            today_md = f"{now.day:02d}.{now.month:02d}"
            for user_id in db_list_active_users():
                row = db_get(user_id)
                if not row or not row[2]:
                    continue
                if row[2][:5] == today_md and not db_already_greeted(user_id, "birthday", year):
                    # Обращение по имени: сначала имя из Telegram, иначе первое слово из ФИО
                    name = db_get_first_name(user_id)
                    if not name:
                        name = (row[0] or "").split()[0] if row[0] else "коллега"
                    try:
                        await bot.send_message(
                            user_id,
                            f"🎂 <b>{name}, с Днём рождения!</b>\n\n"
                            "Команда Wokker поздравляет тебя! Пусть год будет лёгким, "
                            "смены — удачными, а гости — благодарными.\n"
                            "Хорошего праздника! 🥳",
                            parse_mode="HTML"
                        )
                        db_mark_greeted(user_id, "birthday", year)
                    except Exception as e:
                        logging.warning(f"Не удалось отправить поздравление {user_id}: {e}")
        except Exception as e:
            logging.error(f"birthday_checker: {e}")
        await asyncio.sleep(3600)


async def holiday_broadcaster():
    """Раз в час: проверяет, не наступил ли праздник, и рассылает его один раз в год."""
    while True:
        try:
            now = _moscow_now()
            hol = HOLIDAYS.get((now.month, now.day))
            if hol:
                kind = f"holiday:{now.month:02d}-{now.day:02d}"
                if not db_holiday_broadcast_done(kind, now.year):
                    title, text = hol
                    sent = 0
                    for user_id in db_list_active_users():
                        try:
                            name = db_get_first_name(user_id) or "коллега"
                            await bot.send_message(user_id, f"{title}\n\n{name}, {text}")
                            sent += 1
                        except Exception:
                            pass
                        await asyncio.sleep(0.05)
                    db_mark_holiday_broadcast(kind, now.year)
                    logging.info(f"Праздничная рассылка {kind}: отправлено {sent} сообщений")
        except Exception as e:
            logging.error(f"holiday_broadcaster: {e}")
        await asyncio.sleep(3600)


# ================== СТАТУС РЕСТОРАНОВ ПО РЕЖИМУ РАБОТЫ ==================

DAY_MAP = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
DAY_NAMES = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

# Кэш списка ресторанов для Mini App. Сбрасывается при любом изменении из админки.
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
    rows = db_restaurants_all()
    for r in rows:
        if r["key"] == key:
            return r
    return None


def db_restaurant_update(key: str, field: str, value: str) -> bool:
    if field not in RESTAURANT_DB_FIELDS:
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE restaurants SET {field} = %s WHERE key = %s", (value, key))
            updated = cur.rowcount > 0
        return updated


def db_restaurant_set_status(key: str, force_status) -> bool:
    if force_status not in (None, "open", "closed"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE restaurants SET force_status = %s WHERE key = %s",
                (force_status, key)
            )
            updated = cur.rowcount > 0
        return updated


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
    """Имя из Telegram (сохраняется при запуске/регистрации)."""
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
            updated = cur.rowcount > 0
        return updated


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
            deleted = cur.rowcount > 0
        return deleted


def db_set_blocked(user_id: int, blocked: bool):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_blocked = %s WHERE user_id = %s",
                (blocked, user_id)
            )
            updated = cur.rowcount > 0
        return updated


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


def db_add_news(title: str, body: str, level: str) -> int:
    if level not in ("urgent", "important", "normal"):
        level = "normal"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO news (title, body, important, level) VALUES (%s, %s, %s, %s) RETURNING id",
                (title, body, level != "normal", level)
            )
            news_id = cur.fetchone()[0]
        return news_id


def db_list_news():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, body, important, level, created_at FROM news ORDER BY created_at DESC, id DESC"
            )
            return cur.fetchall()


def db_get_news(news_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, body, level FROM news WHERE id = %s",
                (news_id,)
            )
            return cur.fetchone()


def db_delete_news(news_id: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM news WHERE id = %s", (news_id,))
            deleted = cur.rowcount > 0
        return deleted


# --- Стандарты и FAQ (в базе, редактируются из админки) ---

def db_list_standards():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title, category, description, url FROM standards ORDER BY id")
            return cur.fetchall()


def db_add_standard(title: str, category: str, description: str, url: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO standards (title, category, description, url) VALUES (%s, %s, %s, %s)",
                (title, category, description, url)
            )


def db_delete_standard(sid: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM standards WHERE id = %s", (sid,))
            deleted = cur.rowcount > 0
        return deleted


def db_update_standard(sid: int, field: str, value: str) -> bool:
    if field not in ("title", "category", "description", "url"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE standards SET {field} = %s WHERE id = %s", (value, sid))
            updated = cur.rowcount > 0
        return updated


def db_list_faq():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, question, answer, category FROM faq ORDER BY id")
            return cur.fetchall()


def db_add_faq(question: str, answer: str, category: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO faq (question, answer, category) VALUES (%s, %s, %s)",
                (question, answer, category)
            )


def db_delete_faq(fid: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM faq WHERE id = %s", (fid,))
            deleted = cur.rowcount > 0
        return deleted


def db_update_faq(fid: int, field: str, value: str) -> bool:
    if field not in ("question", "answer"):
        return False
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE faq SET {field} = %s WHERE id = %s", (value, fid))
            updated = cur.rowcount > 0
        return updated


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
            to_delete = ids[keep:]
            for mid in to_delete:
                cur.execute(
                    "DELETE FROM bot_messages WHERE user_id = %s AND message_id = %s",
                    (user_id, mid)
                )
    return to_delete


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
            to_delete = ids[keep:]
            for mid in to_delete:
                cur.execute(
                    "DELETE FROM user_messages WHERE user_id = %s AND message_id = %s",
                    (user_id, mid)
                )
    return to_delete


bot = Bot(token=TOKEN)
dp = Dispatcher()


# ================== ОЧИСТКА ЧАТА ==================

async def cleanup_chat(user_id: int, keep: int = 1):
    for mid in db_get_and_trim_bot_msgs(user_id, keep=keep):
        try:
            await bot.delete_message(user_id, mid)
        except Exception:
            pass


async def delete_incoming(message: types.Message):
    if message is None:
        return
    user_id = message.from_user.id
    db_add_user_msg(user_id, message.message_id)
    for mid in db_get_and_trim_user_msgs(user_id, keep=1):
        try:
            await bot.delete_message(user_id, mid)
        except Exception:
            pass


async def send_tracked(chat_id: int, user_id: int, text: str, **kwargs) -> types.Message:
    msg = await bot.send_message(chat_id, text, **kwargs)
    db_add_bot_msg(user_id, msg.message_id)
    return msg


def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


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


class EditUser(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()


class RestEdit(StatesGroup):
    value = State()


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


# ================== ПРОВЕРКА MINI APP (initData) ==================

def _parse_user_field(pairs_dict: dict):
    try:
        return json.loads(unquote(pairs_dict.get("user", "{}")))
    except Exception as e:
        logging.warning(f"initData: не удалось разобрать user: {e}")
        return None


def validate_init_data(init_data: str):
    if not init_data:
        logging.warning("initData: пустая строка")
        return None

    try:
        pairs = []
        for pair in init_data.split("&"):
            if "=" not in pair:
                continue
            key, _, value = pair.partition("=")
            pairs.append((key, value))
        pairs_dict = dict(pairs)
    except Exception as e:
        logging.warning(f"initData: не удалось разобрать строку: {e}")
        return None

    received_hash = pairs_dict.get("hash")
    if not received_hash:
        logging.warning("initData: нет поля hash")
        return None

    secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs) if k != "hash")
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if hmac.compare_digest(computed_hash, received_hash):
        return _parse_user_field(pairs_dict)

    decoded_string = "\n".join(f"{k}={unquote(v)}" for k, v in sorted(pairs) if k != "hash")
    decoded_hash = hmac.new(secret_key, decoded_string.encode(), hashlib.sha256).hexdigest()

    if hmac.compare_digest(decoded_hash, received_hash):
        logging.warning("initData: подпись сошлась только для ДЕКОДИРОВАННОЙ строки")
        return _parse_user_field(pairs_dict)

    logging.warning("initData: ПОДПИСЬ НЕ СОВПАЛА ни в одном варианте — вероятнее всего, BOT_TOKEN не тот")
    return None


async def get_auth_user(request):
    """Единая проверка доступа для API Mini App."""
    try:
        payload = await request.json()
    except Exception:
        return None, 401
    user = validate_init_data(payload.get("initData", ""))
    if not user or not user.get("id"):
        return None, 401
    user_id = int(user["id"])
    if db_is_blocked(user_id):
        logging.info(f"API: заблокированный пользователь {user_id} пытался получить данные")
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
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def positions_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=pos, callback_data=f"pos:{idx}")]
        for idx, pos in enumerate(POSITIONS)
    ])


def positions_edit_kb(target_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=pos, callback_data=f"editsetpos:{target_id}:{idx}")]
        for idx, pos in enumerate(POSITIONS)
    ] + [[InlineKeyboardButton(text="🔙 К карточке", callback_data=f"adm_user:{target_id}")]])


def restaurants_pick_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r["name"], callback_data=f"restpick:{r['key']}")]
        for r in db_restaurants_all()
    ])


def restaurants_edit_kb(target_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r["name"], callback_data=f"editsetrest:{target_id}:{r['key']}")]
        for r in db_restaurants_all()
    ] + [[InlineKeyboardButton(text="🔙 К карточке", callback_data=f"adm_user:{target_id}")]])


def restaurant_name_by_key(key):
    r = db_restaurant(key)
    return r["name"] if r else key


def profile_text(row):
    full_name, phone, birth_date, position, restaurant = row[0], row[1], row[2], row[3], row[4]
    rest_name = restaurant_name_by_key(restaurant) if restaurant else "—"

    card = (
        "📋 <b>Твой профиль</b>\n"
        "──────────────────────────────\n"
        f"👤 ФИО: <b>{full_name}</b>\n"
        f"💼 Должность: {position or '—'}\n"
        f"📍 Ресторан: {rest_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}\n"
        "──────────────────────────────"
    )
    return card


def admin_menu_kb():
    users_n = len([r for r in db_list_users() if r[1]])
    news_n = len(db_list_news())
    std_n = len(db_list_standards())
    faq_n = len(db_list_faq())
    rest_n = len(db_restaurants_all()) - 1  # без ОФИСа
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📋 Пользователи ({users_n})", callback_data="adm_users")],
        [InlineKeyboardButton(text=f"🏪 Рестораны ({rest_n})", callback_data="adm_rests")],
        [InlineKeyboardButton(text=f"📰 Новости ({news_n})", callback_data="adm_news")],
        [InlineKeyboardButton(text=f"📚 Стандарты ({std_n})", callback_data="adm_std")],
        [InlineKeyboardButton(text=f"❓ Вопросы/ответы ({faq_n})", callback_data="adm_faq")],
        [InlineKeyboardButton(text="📊 Отчёты", callback_data="adm_reports")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_menu")],
    ])


# ================== ТЕКСТЫ И КЛАВИАТУРЫ: ПОЛЬЗОВАТЕЛИ ==================

LEVEL_LABELS = {
    "urgent": "🔴 Срочная",
    "important": "🟡 Важная",
    "normal": "🔵 Обычная",
}


def users_list_text(rows):
    if not rows:
        return "📋 Пока никто не зарегистрирован."
    lines = [f"📋 Всего пользователей: {len(rows)}\n"]
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        if not full_name:
            lines.append(f"• <code>{user_id}</code> — регистрация не завершена")
            continue
        mark = " 🚫" if is_blocked else ""
        rest = restaurant_name_by_key(restaurant) if restaurant else "—"
        lines.append(f"• <b>{full_name}</b>{mark} — {position or 'должность не указана'}, {rest}")
    lines.append("\nНажми на пользователя в списке ниже, чтобы посмотреть карточку.")
    return "\n".join(lines)


def users_list_kb(rows):
    kb = []
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        label = full_name if full_name else f"ID {user_id}"
        if is_blocked:
            label = "🚫 " + label
        kb.append([InlineKeyboardButton(text=label[:60], callback_data=f"adm_user:{user_id}")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def user_card_text(target_id: int, row) -> str:
    if not row:
        return "Пользователь не найден."
    full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row
    rest_name = restaurant_name_by_key(restaurant) if restaurant else "—"
    status = "🚫 Заблокирован" if is_blocked else "✅ Активен"
    return (
        f"👤 <b>Пользователь</b>\n"
        "──────────────────────────────\n"
        f"🆔 ID: <code>{target_id}</code>\n"
        f"👤 ФИО: <b>{full_name or '—'}</b>\n"
        f"💼 Должность: {position or '—'}\n"
        f"📍 Ресторан: {rest_name}\n"
        f"📞 Телефон: {phone or '—'}\n"
        f"🎂 Дата рождения: {birth_date or '—'}\n"
        f"📊 Статус: {status}"
    )


def user_edit_kb(target_id: int, is_blocked: bool = False) -> InlineKeyboardMarkup:
    ban_btn = (
        InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"adm_unban:{target_id}")
        if is_blocked
        else InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"adm_ban:{target_id}")
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ ФИО", callback_data=f"edit_field:{target_id}:full_name"),
            InlineKeyboardButton(text="📞 Телефон", callback_data=f"edit_field:{target_id}:phone"),
        ],
        [
            InlineKeyboardButton(text="🎂 Дата рождения", callback_data=f"edit_field:{target_id}:birth_date"),
            InlineKeyboardButton(text="💼 Должность", callback_data=f"edit_pos:{target_id}"),
        ],
        [InlineKeyboardButton(text="📍 Ресторан", callback_data=f"edit_rest:{target_id}")],
        [
            ban_btn,
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"adm_del:{target_id}"),
        ],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="adm_users")],
    ])


# ================== ТЕКСТЫ И КЛАВИАТУРЫ: НОВОСТИ ==================

def news_admin_text(rows):
    if not rows:
        return "📰 Новостей пока нет. Нажми «Добавить новость»."
    lines = ["📰 Опубликованные новости:\n"]
    for news_id, title, body, important, level, created_at in rows:
        lvl = level if level in LEVEL_LABELS else "normal"
        date_str = created_at.strftime("%d.%m.%Y") if created_at else ""
        lines.append(f"{LEVEL_LABELS[lvl]} <b>{title}</b> ({date_str})")
    return "\n".join(lines)


def news_admin_kb(rows):
    kb = []
    for news_id, title, body, important, level, created_at in rows:
        short = (title or "Без названия")[:30]
        kb.append([
            InlineKeyboardButton(text=f"📢 {short}", callback_data=f"news_send:{news_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"news_del:{news_id}"),
        ])
    kb.append([InlineKeyboardButton(text="➕ Добавить новость", callback_data="news_add")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def news_important_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=LEVEL_LABELS["urgent"], callback_data="news_imp:urgent")],
        [InlineKeyboardButton(text=LEVEL_LABELS["important"], callback_data="news_imp:important")],
        [InlineKeyboardButton(text=LEVEL_LABELS["normal"], callback_data="news_imp:normal")],
    ])


async def broadcast_news(title: str, body: str, level: str, restaurant_key=None):
    """Рассылка новости: всем активным или только сотрудникам выбранного ресторана."""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Скрыть уведомление", callback_data="hide_notification")]
    ])
    icon = LEVEL_LABELS.get(level, LEVEL_LABELS["normal"])
    text = f"{icon} <b>{title}</b>\n\n{body}"
    sent, failed = 0, 0
    for user_id in db_list_active_users(restaurant_key):
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    if ADMIN_ID:
        target = restaurant_name_by_key(restaurant_key) if restaurant_key else "всем"
        try:
            await bot.send_message(
                ADMIN_ID,
                f"📬 Рассылка завершена.\n\n📰 «{title}»\n🎯 Аудитория: {target}\n"
                f"✅ Доставлено: {sent}\n❌ Не доставлено: {failed}"
            )
        except Exception:
            pass


# ================== АДМИНКА РЕСТОРАНОВ ==================

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
        f"🗺 Яндекс Карты: {r.get('org') or 'по адресу'}"
    )


def rest_card_kb(r: dict) -> InlineKeyboardMarkup:
    fs = r.get("force_status")
    if fs == "open":
        status_btn = InlineKeyboardButton(text="♻️ Вернуть авто-статус", callback_data=f"restset:{r['key']}:auto")
    elif fs == "closed":
        status_btn = InlineKeyboardButton(text="🟢 Открыть (вручную)", callback_data=f"restset:{r['key']}:open")
    else:
        status_btn = InlineKeyboardButton(text="🔴 Закрыть (вручную)", callback_data=f"restset:{r['key']}:closed")

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Название", callback_data=f"restedit:{r['key']}:name"),
            InlineKeyboardButton(text="✏️ Адрес", callback_data=f"restedit:{r['key']}:address"),
        ],
        [
            InlineKeyboardButton(text="✏️ Телефон", callback_data=f"restedit:{r['key']}:phone"),
            InlineKeyboardButton(text="✏️ Часы", callback_data=f"restedit:{r['key']}:hours"),
        ],
        [status_btn],
        [InlineKeyboardButton(text="🔙 К списку ресторанов", callback_data="adm_rests")],
    ])


def rests_list_kb(rests):
    kb = []
    for r in rests:
        status, _ = restaurant_status_for(r)
        icon = "🟢" if status == "open" else "🔴"
        kb.append([
            InlineKeyboardButton(
                text=f"{icon} {r['name']}",
                callback_data=f"restadm:{r['key']}"
            ),
            InlineKeyboardButton(
                text=("🔓" if r.get("force_status") == "closed" else "🔒"),
                callback_data=f"restset:{r['key']}:{'open' if r.get('force_status') == 'closed' else 'closed'}"
            ),
            InlineKeyboardButton(text="✏️", callback_data=f"restadm:{r['key']}"),
        ])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def rests_list_text(rests):
    if not rests:
        return "🏪 Список ресторанов пуст."
    lines = [f"🏪 Всего точек: {len(rests)}\n"]
    for r in rests:
        status, _ = restaurant_status_for(r)
        icon = "🟢" if status == "open" else "🔴"
        fs = r.get("force_status")
        mark = " (вручную)" if fs else ""
        lines.append(f"{icon} <b>{r['name']}</b>{mark} — {r.get('address') or '—'}")
    lines.append("\nНажми на точку — откроется карточка редактирования. 🔒/🔓 — быстрое закрытие/открытие.")
    return "\n".join(lines)


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    await send_tracked(
        message.chat.id, message.from_user.id,
        "🛠 <b>Админ-панель</b>\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=admin_menu_kb()
    )


@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.chat.id)
    stats = get_report_stats()
    rests = db_restaurants_all()
    counts = {}
    for r in db_list_users():
        if r[1]:
            rest_name = restaurant_name_by_key(r[4]) if r[4] else "Не указан"
            counts[rest_name] = counts.get(rest_name, 0) + 1
    rest_lines = "\n".join(f"• {k}: {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])) or "• пока нет данных"
    await send_tracked(
        message.chat.id, message.from_user.id,
        f"📊 <b>Сводка</b> ({stats['date']})\n\n"
        f"👥 Всего: {stats['total']} · ✅ активных: {stats['active']} · 🚫 заблокированных: {stats['blocked']}\n"
        f"🏪 Точек: {len(rests) - 1}\n\n"
        f"<b>По ресторанам:</b>\n{rest_lines}",
        parse_mode="HTML"
    )


@dp.callback_query(lambda c: c.data == "adm_rests")
async def adm_rests(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rests = db_restaurants_all()
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        rests_list_text(rests), parse_mode="HTML", reply_markup=rests_list_kb(rests)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("restadm:"))
async def rest_card_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    key = callback.data.split(":")[1]
    r = db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if not r:
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Ресторан не найден.")
        return
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("restset:"))
async def rest_set_status(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    _, key, new_status = callback.data.split(":")
    if new_status == "auto":
        new_status = None
    if db_restaurant_set_status(key, new_status):
        invalidate_rest_cache()
        r = db_restaurant(key)
        if r:
            await callback.answer("Статус обновлён")
            await cleanup_chat(callback.from_user.id)
            await send_tracked(
                callback.message.chat.id, callback.from_user.id,
                rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r)
            )
            return
    await callback.answer("Не удалось изменить статус", show_alert=True)


@dp.callback_query(lambda c: c.data and c.data.startswith("restedit:"))
async def rest_edit_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    _, key, field = callback.data.split(":")
    if field not in RESTAURANT_DB_FIELDS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    await state.set_state(RestEdit.value)
    await state.update_data(rest_key=key, rest_field=field)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"{FIELD_PROMPTS[field]}\n\nИли нажми «Отменить»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"restedit_cancel:{key}")]
        ])
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("restedit_cancel:"))
async def rest_edit_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer("Отменено")
    await state.clear()
    key = callback.data.split(":")[1]
    r = db_restaurant(key)
    await cleanup_chat(callback.from_user.id)
    if r:
        await send_tracked(
            callback.message.chat.id, callback.from_user.id,
            rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r)
        )


@dp.message(RestEdit.value)
async def rest_edit_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    rest_key = data.get("rest_key")
    rest_field = data.get("rest_field")
    if not rest_key or not rest_field:
        await state.clear()
        return

    value = (message.text or "").strip()

    # Валидация по полю
    if rest_field == "name":
        if len(value) < 2:
            await delete_incoming(message)
            await cleanup_chat(message.from_user.id)
            await send_tracked(message.chat.id, message.from_user.id, "Название слишком короткое. Попробуй ещё раз:")
            return
    elif rest_field == "address":
        if len(value) < 5:
            await delete_incoming(message)
            await cleanup_chat(message.from_user.id)
            await send_tracked(message.chat.id, message.from_user.id, "Адрес слишком короткий. Попробуй ещё раз:")
            return
    elif rest_field == "phone":
        if value.lower() in ("нет", "-", "—", ""):
            value = ""
        else:
            digits = value.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
            if not digits.isdigit() or len(digits) < 10:
                await delete_incoming(message)
                await cleanup_chat(message.from_user.id)
                await send_tracked(message.chat.id, message.from_user.id, "Это не похоже на номер. Пример: +79001234567. Или напиши «нет», чтобы скрыть.")
                return
    elif rest_field == "hours":
        if not re.search(r"\d{1,2}:\d{2}\s*[–\-—]\s*\d{1,2}:\d{2}", value):
            await delete_incoming(message)
            await cleanup_chat(message.from_user.id)
            await send_tracked(message.chat.id, message.from_user.id, "Не вижу времени в записи. Пример:\nПн–чт: 10:00–22:00\nПт–вс: 10:00–23:00")
            return
    elif rest_field == "org":
        if value.lower() in ("нет", "-", "—", ""):
            value = ""

    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.clear()

    db_restaurant_update(rest_key, rest_field, value)
    invalidate_rest_cache()
    await send_tracked(
        message.chat.id, message.from_user.id,
        f"✅ {FIELD_LABELS[rest_field]} обновлено: <b>{value if value else '—'}</b>",
        parse_mode="HTML"
    )
    r = db_restaurant(rest_key)
    if r:
        await send_tracked(
            message.chat.id, message.from_user.id,
            rest_card_text(r), parse_mode="HTML", reply_markup=rest_card_kb(r)
        )


@dp.callback_query(lambda c: c.data == "adm_menu")
async def adm_menu(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        "🛠 Админ-панель",
        reply_markup=admin_menu_kb()
    )


@dp.callback_query(lambda c: c.data == "adm_users")
async def adm_users(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    rows = db_list_users()
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        users_list_text(rows), parse_mode="HTML", reply_markup=users_list_kb(rows)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("adm_user:"))
async def adm_user_card(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    target_id = int(callback.data.split(":")[1])
    row = db_get(target_id)
    await cleanup_chat(callback.from_user.id)
    if not row:
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Пользователь не найден.")
        return
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        user_card_text(target_id, row), parse_mode="HTML",
        reply_markup=user_edit_kb(target_id, bool(row[6]))
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("edit_field:"))
async def edit_field_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    _, target_id, field = callback.data.split(":")
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
    await state.update_data(edit_target=int(target_id))
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"{prompt}\n\nИли нажми «Отменить», чтобы ничего не менять:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"edit_cancel:{target_id}")]
        ])
    )


@dp.message(EditUser.full_name)
async def edit_full_name(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    name = (message.text or "").strip()
    if len(name.split()) < 2:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Нужны минимум имя и фамилия через пробел. Попробуй ещё раз:")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    data = await state.get_data()
    target_id = data.get("edit_target")
    await state.clear()
    db_update_user(target_id, "full_name", name)
    await send_tracked(message.chat.id, message.from_user.id, f"✅ ФИО обновлено: <b>{name}</b>", parse_mode="HTML")
    row = db_get(target_id)
    await send_tracked(message.chat.id, message.from_user.id,
                       user_card_text(target_id, row), parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, bool(row[6])))


@dp.message(EditUser.phone)
async def edit_phone(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    digits = (message.text or "").replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or len(digits) < 10:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Это не похоже на номер. Попробуй ещё раз, например: +79001234567")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    data = await state.get_data()
    target_id = data.get("edit_target")
    await state.clear()
    db_update_user(target_id, "phone", message.text.strip())
    await send_tracked(message.chat.id, message.from_user.id, f"✅ Телефон обновлён: <b>{message.text.strip()}</b>", parse_mode="HTML")
    row = db_get(target_id)
    await send_tracked(message.chat.id, message.from_user.id,
                       user_card_text(target_id, row), parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, bool(row[6])))


@dp.message(EditUser.birth_date)
async def edit_birth_date(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        birth_date = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
        if birth_date.year < 1900 or birth_date > datetime.now().date():
            raise ValueError
    except ValueError:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Такой даты не бывает. Напиши ещё раз в формате ДД.ММ.ГГГГ:")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    data = await state.get_data()
    target_id = data.get("edit_target")
    await state.clear()
    db_update_user(target_id, "birth_date", birth_date.strftime("%d.%m.%Y"))
    await send_tracked(message.chat.id, message.from_user.id, f"✅ Дата рождения обновлена: <b>{birth_date.strftime('%d.%m.%Y')}</b>", parse_mode="HTML")
    row = db_get(target_id)
    await send_tracked(message.chat.id, message.from_user.id,
                       user_card_text(target_id, row), parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, bool(row[6])))


@dp.callback_query(lambda c: c.data and c.data.startswith("edit_cancel:"))
async def edit_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer("Отменено")
    await state.clear()
    target_id = int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    row = db_get(target_id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       user_card_text(target_id, row), parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, bool(row[6])))


@dp.callback_query(lambda c: c.data and c.data.startswith("edit_pos:"))
async def edit_pos_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    target_id = int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        "💼 Выбери новую должность:", reply_markup=positions_edit_kb(target_id)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("editsetpos:"))
async def edit_pos_set(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    _, target_id, idx = callback.data.split(":")
    target_id = int(target_id)
    position = POSITIONS[int(idx)]
    db_update_user(target_id, "position", position)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"✅ Должность обновлена: <b>{position}</b>", parse_mode="HTML")
    row = db_get(target_id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       user_card_text(target_id, row), parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, bool(row[6])))


@dp.callback_query(lambda c: c.data and c.data.startswith("edit_rest:"))
async def edit_rest_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    target_id = int(callback.data.split(":")[1])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        "📍 Выбери новый ресторан (в списке есть и ОФИС):", reply_markup=restaurants_edit_kb(target_id)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("editsetrest:"))
async def edit_rest_set(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    _, target_id, key = callback.data.split(":")
    target_id = int(target_id)
    db_update_user(target_id, "restaurant", key)
    rest_name = restaurant_name_by_key(key)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       f"✅ Ресторан обновлён: <b>{rest_name}</b>", parse_mode="HTML")
    row = db_get(target_id)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       user_card_text(target_id, row), parse_mode="HTML",
                       reply_markup=user_edit_kb(target_id, bool(row[6])))


@dp.callback_query(lambda c: c.data and c.data.startswith("adm_ban:"))
async def adm_ban(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("Нельзя заблокировать самого себя", show_alert=True)
        return
    if db_set_blocked(target_id, True):
        await callback.answer("Заблокирован")
        try:
            await bot.send_message(target_id, "⛔ Доступ к боту ограничен. Обратитесь к администратору.")
        except Exception:
            pass
    else:
        await callback.answer("Пользователь не найден", show_alert=True)
    row = db_get(target_id)
    if row:
        await cleanup_chat(callback.from_user.id)
        await send_tracked(
            callback.message.chat.id, callback.from_user.id,
            user_card_text(target_id, row), parse_mode="HTML",
            reply_markup=user_edit_kb(target_id, True)
        )


@dp.callback_query(lambda c: c.data and c.data.startswith("adm_unban:"))
async def adm_unban(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    if db_set_blocked(target_id, False):
        await callback.answer("Разблокирован")
    else:
        await callback.answer("Пользователь не найден", show_alert=True)
    row = db_get(target_id)
    if row:
        await cleanup_chat(callback.from_user.id)
        await send_tracked(
            callback.message.chat.id, callback.from_user.id,
            user_card_text(target_id, row), parse_mode="HTML",
            reply_markup=user_edit_kb(target_id, False)
        )


@dp.callback_query(lambda c: c.data and c.data.startswith("adm_del:"))
async def adm_del_ask(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("Нельзя удалить самого себя", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"adm_del_yes:{target_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="adm_users"),
        ]
    ])
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"🗑 Удалить пользователя <code>{target_id}</code> из базы?\n\n"
        "Он сможет зарегистрироваться заново. Если нужно закрыть доступ — используй блокировку.",
        parse_mode="HTML",
        reply_markup=confirm_kb
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("adm_del_yes:"))
async def adm_del_yes(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    if db_delete_user(target_id):
        await callback.answer("Удалён")
        await cleanup_chat(callback.from_user.id)
        await send_tracked(
            callback.message.chat.id, callback.from_user.id,
            f"🗑 Пользователь <code>{target_id}</code> удалён.", parse_mode="HTML"
        )
    else:
        await callback.answer("Пользователь не найден", show_alert=True)


# ================== АДМИНКА НОВОСТЕЙ ==================

@dp.callback_query(lambda c: c.data == "adm_news")
async def adm_news(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = db_list_news()
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        news_admin_text(rows), parse_mode="HTML", reply_markup=news_admin_kb(rows)
    )


@dp.callback_query(lambda c: c.data == "news_add")
async def news_add_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.set_state(NewsAdmin.title)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        "✍️ Шаг 1 из 3.\nНапиши заголовок новости:"
    )


@dp.message(NewsAdmin.title)
async def news_add_title(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    if not message.text:
        await send_tracked(message.chat.id, message.from_user.id, "Заголовок должен быть текстом. Напиши ещё раз:")
        return
    title = message.text.strip()
    if len(title) > 100:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком длинный заголовок (максимум 100 символов). Сократи:")
        return
    await state.update_data(title=title)
    await state.set_state(NewsAdmin.body)
    await send_tracked(message.chat.id, message.from_user.id, f"Заголовок: <b>{title}</b> ✅\n\n✍️ Шаг 2 из 3.\nНапиши текст новости:", parse_mode="HTML")


@dp.message(NewsAdmin.body)
async def news_add_body(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    if not message.text:
        await send_tracked(message.chat.id, message.from_user.id, "Текст новости должен быть текстом. Напиши ещё раз:")
        return
    body = message.text.strip()
    if len(body) > 2000:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком длинный текст (максимум 2000 символов). Сократи:")
        return
    await state.update_data(body=body)
    await state.set_state(NewsAdmin.important)
    await send_tracked(
        message.chat.id, message.from_user.id,
        "Текст записан ✅\n\n✍️ Шаг 3 из 3.\nКакую пометку поставить?",
        reply_markup=news_important_kb()
    )


@dp.callback_query(NewsAdmin.important, lambda c: c.data and c.data.startswith("news_imp:"))
async def news_add_finish(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    level = callback.data.split(":")[1]
    if level not in LEVEL_LABELS:
        level = "normal"
    data = await state.get_data()
    title = data.get("title", "")
    body = data.get("body", "")
    await state.clear()

    try:
        db_add_news(title, body, level)
    except Exception as e:
        logging.error(f"Ошибка сохранения новости: {e}")
        await send_tracked(
            callback.message.chat.id, callback.from_user.id,
            "❌ Не удалось сохранить новость. Попробуй позже."
        )
        return

    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"✅ Новость опубликована!\n\n{LEVEL_LABELS[level]} — <b>{title}</b>\n{body}\n\n"
        "Она уже видна сотрудникам во вкладке «Новости».\n"
        "Чтобы разослать уведомление — нажми «📢 Разослать» рядом с новостью.",
        parse_mode="HTML"
    )
    rows = db_list_news()
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        news_admin_text(rows), parse_mode="HTML", reply_markup=news_admin_kb(rows)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("news_del:"))
async def news_del(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    news_id = int(callback.data.split(":")[1])
    if db_delete_news(news_id):
        await callback.answer("Новость удалена")
    else:
        await callback.answer("Новость не найдена", show_alert=True)
    await cleanup_chat(callback.from_user.id)
    rows = db_list_news()
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        news_admin_text(rows), parse_mode="HTML", reply_markup=news_admin_kb(rows)
    )


# --- Адресная рассылка: всем или одному ресторану ---

@dp.callback_query(lambda c: c.data and c.data.startswith("news_send:"))
async def news_send_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    news_id = int(callback.data.split(":")[1])
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        "📬 Кому разослать это уведомление?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌍 Всем сотрудникам", callback_data=f"news_send_all:{news_id}")],
            [InlineKeyboardButton(text="📍 Только одному ресторану", callback_data=f"news_send_rest:{news_id}")],
            [InlineKeyboardButton(text="🔙 К списку новостей", callback_data="adm_news")],
        ])
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("news_send_all:"))
async def news_send_all(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    news_id = int(callback.data.split(":")[1])
    row = db_get_news(news_id)
    if not row:
        await callback.answer("Новость не найдена", show_alert=True)
        return
    title, body, level = row
    asyncio.create_task(broadcast_news(title, body, level))
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"✅ Рассылка «{title}» запущена для всех. По завершении придёт отчёт."
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("news_send_rest:"))
async def news_send_rest(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    news_id = int(callback.data.split(":")[1])
    await callback.answer()
    kb = [
        [InlineKeyboardButton(text=r["name"], callback_data=f"news_send_restdo:{news_id}:{r['key']}")]
        for r in db_restaurants_all()
    ]
    kb.append([InlineKeyboardButton(text="🔙 К выбору аудитории", callback_data=f"news_send:{news_id}")])
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        "📍 Выбери ресторан — получат только его сотрудники:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("news_send_restdo:"))
async def news_send_restdo(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    _, news_id, key = callback.data.split(":")
    row = db_get_news(int(news_id))
    if not row:
        await callback.answer("Новость не найдена", show_alert=True)
        return
    title, body, level = row
    asyncio.create_task(broadcast_news(title, body, level, restaurant_key=key))
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"✅ Рассылка «{title}» запущена для {restaurant_name_by_key(key)}. Отчёт придёт по завершении."
    )


@dp.callback_query(lambda c: c.data == "hide_notification")
async def hide_notification(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception as e:
        logging.warning(f"Не удалось скрыть уведомление для {callback.from_user.id}: {e}")
    await callback.answer("Уведомление скрыто")


# ================== АДМИНКА: СТАНДАРТЫ ==================

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
        f"Ссылка: {url or '—'}"
    )


def std_card_kb(sid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Название", callback_data=f"std_edit:{sid}:title"),
            InlineKeyboardButton(text="✏️ Категория", callback_data=f"std_edit:{sid}:category"),
        ],
        [
            InlineKeyboardButton(text="✏️ Описание", callback_data=f"std_edit:{sid}:description"),
            InlineKeyboardButton(text="✏️ Ссылка", callback_data=f"std_edit:{sid}:url"),
        ],
        [InlineKeyboardButton(text="🗑 Удалить стандарт", callback_data=f"std_del:{sid}")],
        [InlineKeyboardButton(text="🔙 К списку стандартов", callback_data="adm_std")],
    ])


def std_admin_kb(rows):
    kb = []
    for sid, title, category, description, url in rows:
        kb.append([
            InlineKeyboardButton(text=f"📚 {title[:28]}", callback_data=f"std_card:{sid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"std_del:{sid}"),
        ])
    kb.append([InlineKeyboardButton(text="➕ Добавить стандарт", callback_data="std_add")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@dp.callback_query(lambda c: c.data == "adm_std")
async def adm_std(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = db_list_standards()
    text = "📚 Стандарты — редактируй отсюда, деплой не нужен.\n\n" + (
        "\n".join(f"• {t}" for _, t, _, _, _ in rows) or "Пока пусто."
    )
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       text, parse_mode="HTML", reply_markup=std_admin_kb(rows))


@dp.callback_query(lambda c: c.data and c.data.startswith("std_card:"))
async def std_card_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    sid = int(callback.data.split(":")[1])
    rows = [r for r in db_list_standards() if r[0] == sid]
    await cleanup_chat(callback.from_user.id)
    if not rows:
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Стандарт не найден.")
        return
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       std_card_text(rows[0]), parse_mode="HTML", reply_markup=std_card_kb(sid))


@dp.callback_query(lambda c: c.data and c.data.startswith("std_edit:"))
async def std_edit_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    _, sid, field = callback.data.split(":")
    if field not in STD_FIELDS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    await state.set_state(StdEdit.value)
    await state.update_data(std_id=int(sid), std_field=field)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"{STD_FIELDS[field][1]}\n\nИли нажми «Отменить»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"std_card:{sid}")]
        ])
    )


@dp.message(StdEdit.value)
async def std_edit_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    sid, field = data.get("std_id"), data.get("std_field")
    if sid is None or field not in STD_FIELDS:
        await state.clear()
        return
    value = (message.text or "").strip()
    if field == "url" and value.lower() in ("нет", "-", "—", ""):
        value = ""
    elif len(value) < 2:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко. Попробуй ещё раз:")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.clear()
    db_update_standard(sid, field, value)
    await send_tracked(message.chat.id, message.from_user.id, "✅ Обновлено.")
    rows = [r for r in db_list_standards() if r[0] == sid]
    if rows:
        await send_tracked(message.chat.id, message.from_user.id,
                           std_card_text(rows[0]), parse_mode="HTML", reply_markup=std_card_kb(sid))


@dp.callback_query(lambda c: c.data and c.data.startswith("std_del:"))
async def std_del(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    sid = int(callback.data.split(":")[1])
    db_delete_standard(sid)
    await callback.answer("Удалено")
    await cleanup_chat(callback.from_user.id)
    rows = db_list_standards()
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "📚 Стандарты:\n\n" + ("\n".join(f"• {t}" for _, t, _, _, _ in rows) or "Пока пусто."),
                       parse_mode="HTML", reply_markup=std_admin_kb(rows))


@dp.callback_query(lambda c: c.data == "std_add")
async def std_add_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.set_state(StdAdmin.title)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "📚 Новый стандарт.\nШаг 1 из 3. Название:")


@dp.message(StdAdmin.title)
async def std_add_title(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    title = (message.text or "").strip()
    if len(title) < 3:
        await send_tracked(message.chat.id, message.from_user.id, "Название слишком короткое. Ещё раз:")
        return
    await state.update_data(title=title)
    await state.set_state(StdAdmin.category)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Название: <b>{title}</b> ✅\nШаг 2 из 3. Категория:", parse_mode="HTML")


@dp.message(StdAdmin.category)
async def std_add_category(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    category = (message.text or "").strip()
    await state.update_data(category=category)
    await state.set_state(StdAdmin.description)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Категория: <b>{category}</b> ✅\nШаг 3 из 3. Описание стандарта:", parse_mode="HTML")


@dp.message(StdAdmin.description)
async def std_add_desc(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    description = (message.text or "").strip()
    if len(description) < 5:
        await send_tracked(message.chat.id, message.from_user.id, "Описание слишком короткое. Ещё раз:")
        return
    data = await state.get_data()
    await state.clear()
    db_add_standard(data.get("title", ""), data.get("category", ""), description)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"✅ Стандарт добавлен: <b>{data.get('title')}</b>", parse_mode="HTML")
    rows = db_list_standards()
    await send_tracked(message.chat.id, message.from_user.id,
                       "📚 Стандарты:\n\n" + ("\n".join(f"• {t}" for _, t, _, _, _ in rows) or "Пока пусто."),
                       parse_mode="HTML", reply_markup=std_admin_kb(rows))


# ================== АДМИНКА: FAQ ==================

FAQ_FIELDS = {
    "question": ("Вопрос", "✏️ Напиши новый текст вопроса:"),
    "answer": ("Ответ", "✏️ Напиши новый текст ответа:"),
}


def faq_card_kb(fid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Вопрос", callback_data=f"faq_edit:{fid}:question")],
        [InlineKeyboardButton(text="✏️ Ответ", callback_data=f"faq_edit:{fid}:answer")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"faq_del:{fid}")],
        [InlineKeyboardButton(text="🔙 К списку вопросов", callback_data="adm_faq")],
    ])


def faq_admin_kb(rows):
    kb = []
    for fid, question, answer, category in rows:
        kb.append([
            InlineKeyboardButton(text=f"❓ {question[:28]}", callback_data=f"faq_edit_show:{fid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"faq_del:{fid}"),
        ])
    kb.append([InlineKeyboardButton(text="➕ Добавить вопрос", callback_data="faq_add")])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@dp.callback_query(lambda c: c.data == "adm_faq")
async def adm_faq(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await cleanup_chat(callback.from_user.id)
    rows = db_list_faq()
    text = "❓ Вопросы/ответы:\n\n" + ("\n".join(f"• {q}" for _, q, _, _ in rows) or "Пока пусто.")
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       text, parse_mode="HTML", reply_markup=faq_admin_kb(rows))


@dp.callback_query(lambda c: c.data and c.data.startswith("faq_edit_show:"))
async def faq_card_view(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    fid = int(callback.data.split(":")[1])
    rows = [r for r in db_list_faq() if r[0] == fid]
    await cleanup_chat(callback.from_user.id)
    if not rows:
        await send_tracked(callback.message.chat.id, callback.from_user.id, "❌ Вопрос не найден.")
        return
    _, question, answer, _ = rows[0]
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"❓ <b>{question}</b>\n\n💬 {answer}",
        parse_mode="HTML", reply_markup=faq_card_kb(fid)
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("faq_edit:"))
async def faq_edit_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    _, fid, field = callback.data.split(":")
    if field not in FAQ_FIELDS:
        await callback.answer("Неизвестное поле", show_alert=True)
        return
    await state.set_state(FaqEdit.value)
    await state.update_data(faq_id=int(fid), faq_field=field)
    await cleanup_chat(callback.from_user.id)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"{FAQ_FIELDS[field][1]}\n\nИли нажми «Отменить»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить", callback_data=f"faq_edit_show:{fid}")]
        ])
    )


@dp.message(FaqEdit.value)
async def faq_edit_value(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    fid, field = data.get("faq_id"), data.get("faq_field")
    if fid is None or field not in FAQ_FIELDS:
        await state.clear()
        return
    value = (message.text or "").strip()
    if len(value) < 3:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко. Попробуй ещё раз:")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.clear()
    db_update_faq(fid, field, value)
    rows = [r for r in db_list_faq() if r[0] == fid]
    if rows:
        _, question, answer, _ = rows[0]
        await send_tracked(message.chat.id, message.from_user.id,
                           f"✅ Обновлено.\n\n❓ <b>{question}</b>\n\n💬 {answer}",
                           parse_mode="HTML", reply_markup=faq_card_kb(fid))


@dp.callback_query(lambda c: c.data and c.data.startswith("faq_del:"))
async def faq_del(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    fid = int(callback.data.split(":")[1])
    db_delete_faq(fid)
    await callback.answer("Удалено")
    await cleanup_chat(callback.from_user.id)
    rows = db_list_faq()
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "❓ Вопросы/ответы:\n\n" + ("\n".join(f"• {q}" for _, q, _, _ in rows) or "Пока пусто."),
                       parse_mode="HTML", reply_markup=faq_admin_kb(rows))


@dp.callback_query(lambda c: c.data == "faq_add")
async def faq_add_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await state.set_state(FaqAdmin.question)
    await send_tracked(callback.message.chat.id, callback.from_user.id,
                       "❓ Новый вопрос.\nШаг 1 из 2. Текст вопроса:")


@dp.message(FaqAdmin.question)
async def faq_add_question(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    question = (message.text or "").strip()
    if len(question) < 5:
        await send_tracked(message.chat.id, message.from_user.id, "Слишком коротко для вопроса. Ещё раз:")
        return
    await state.update_data(question=question)
    await state.set_state(FaqAdmin.answer)
    await send_tracked(message.chat.id, message.from_user.id,
                       f"Вопрос: <b>{question}</b> ✅\nШаг 2 из 2. Текст ответа:", parse_mode="HTML")


@dp.message(FaqAdmin.answer)
async def faq_add_answer(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    answer = (message.text or "").strip()
    if len(answer) < 3:
        await send_tracked(message.chat.id, message.from_user.id, "Ответ слишком короткий. Ещё раз:")
        return
    data = await state.get_data()
    await state.clear()
    db_add_faq(data.get("question", ""), answer)
    await send_tracked(message.chat.id, message.from_user.id, "✅ Вопрос добавлен — он уже виден в приложении.")
    rows = db_list_faq()
    await send_tracked(message.chat.id, message.from_user.id,
                       "❓ Вопросы/ответы:\n\n" + ("\n".join(f"• {q}" for _, q, _, _ in rows) or "Пока пусто."),
                       parse_mode="HTML", reply_markup=faq_admin_kb(rows))


@dp.callback_query(lambda c: c.data == "adm_reports")
async def adm_reports(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    stats = get_report_stats()
    rows = db_list_users()
    positions_count = {}
    restaurants_count = {}
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        if full_name:
            positions_count[position or "Не указана"] = positions_count.get(position or "Не указана", 0) + 1
            rest_name = restaurant_name_by_key(restaurant) if restaurant else "Не указан"
            restaurants_count[rest_name] = restaurants_count.get(rest_name, 0) + 1

    positions_block = "\n".join(
        f"• {k}: {v}" for k, v in sorted(positions_count.items(), key=lambda x: -x[1])
    ) or "• пока нет данных"
    restaurants_block = "\n".join(
        f"• {k}: {v}" for k, v in sorted(restaurants_count.items(), key=lambda x: -x[1])
    ) or "• пока нет данных"

    text = (
        f"📊 <b>Отчёт</b> (на {stats['date']})\n\n"
        f"👥 Всего пользователей: {stats['total']}\n"
        f"✅ Активных: {stats['active']}\n"
        f"🚫 Заблокированных: {stats['blocked']}\n\n"
        f"<b>По должностям:</b>\n{positions_block}\n\n"
        f"<b>По ресторанам:</b>\n{restaurants_block}"
    )
    await send_tracked(callback.message.chat.id, callback.from_user.id, text, parse_mode="HTML")


@dp.callback_query(lambda c: c.data == "noop")
async def adm_noop(callback: types.CallbackQuery):
    if is_admin(callback.from_user.id):
        await callback.answer()
    else:
        await callback.answer("⛔ Недоступно", show_alert=True)


# ================== РЕГИСТРАЦИЯ ==================

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    if db_is_blocked(user_id):
        await delete_incoming(message)
        await cleanup_chat(user_id)
        await send_tracked(message.chat.id, user_id, "⛔ Доступ к боту ограничен. Обратитесь к администратору.")
        return

    await delete_incoming(message)
    await cleanup_chat(user_id)

    current_state = await state.get_state()
    if current_state:
        if current_state == Registration.full_name.state:
            await send_tracked(message.chat.id, user_id, "Шаг 1 из 5.\nНапиши своё ФИО (например: Иванов Иван Иванович)")
        elif current_state == Registration.phone.state:
            await send_tracked(
                message.chat.id, user_id,
                "Шаг 2 из 5.\nОтправь свой номер телефона — можно кнопкой ниже.",
                reply_markup=phone_kb()
            )
        elif current_state == Registration.birth_date.state:
            await send_tracked(
                message.chat.id, user_id,
                "Шаг 3 из 5.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
                reply_markup=ReplyKeyboardRemove()
            )
        elif current_state == Registration.position.state:
            await send_tracked(
                message.chat.id, user_id,
                "Шаг 4 из 5.\nВыбери свою должность:", reply_markup=positions_kb()
            )
        elif current_state == Registration.restaurant.state:
            await send_tracked(
                message.chat.id, user_id,
                "Шаг 5 из 5.\nВыбери свой ресторан:", reply_markup=restaurants_pick_kb()
            )
        elif current_state == NewsAdmin.title.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши заголовок новости:")
        elif current_state == NewsAdmin.body.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши текст новости:")
        elif current_state == NewsAdmin.important.state:
            await send_tracked(message.chat.id, user_id, "Выбери пометку:", reply_markup=news_important_kb())
        elif current_state == EditUser.full_name.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши новое ФИО:")
        elif current_state == EditUser.phone.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши новый номер телефона:")
        elif current_state == EditUser.birth_date.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши новую дату рождения (ДД.ММ.ГГГГ):")
        elif current_state == RestEdit.value.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши новое значение — или нажми «Отменить» в карточке:")
        elif current_state == StdAdmin.title.state:
            await send_tracked(message.chat.id, user_id, "📚 Шаг 1 из 3. Название стандарта:")
        elif current_state == StdAdmin.category.state:
            await send_tracked(message.chat.id, user_id, "📚 Шаг 2 из 3. Категория:")
        elif current_state == StdAdmin.description.state:
            await send_tracked(message.chat.id, user_id, "📚 Шаг 3 из 3. Описание стандарта:")
        elif current_state == StdEdit.value.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши новое значение — или нажми «Отменить» в карточке:")
        elif current_state == FaqAdmin.question.state:
            await send_tracked(message.chat.id, user_id, "❓ Шаг 1 из 2. Текст вопроса:")
        elif current_state == FaqAdmin.answer.state:
            await send_tracked(message.chat.id, user_id, "❓ Шаг 2 из 2. Текст ответа:")
        elif current_state == FaqEdit.value.state:
            await send_tracked(message.chat.id, user_id, "✍️ Напиши новое значение — или нажми «Отменить» в карточке:")
        return

    await state.clear()
    row = db_get(user_id)

    if row and row[0]:
        # Обновляем имя на всякий случай (если пользователь поменял его в Telegram)
        db_set_welcomed(user_id, message.from_user.first_name)
        await send_tracked(message.chat.id, user_id, "Выбери действие:", reply_markup=FULL_MENU)
        return

    if row and row[5]:
        await send_tracked(message.chat.id, user_id, "Сначала заверши регистрацию 👇", reply_markup=REGISTER_ONLY)
        return

    db_set_welcomed(user_id, message.from_user.first_name)
    await send_tracked(
        message.chat.id, user_id,
        f"👋 {message.from_user.first_name}, добро пожаловать в Wokker!\n\n"
        "Мы готовим паназиатские блюда на воке — быстро и со вкусом.\n"
        "Для начала зарегистрируйся 👇"
    )
    await send_tracked(
        message.chat.id, user_id,
        "Что хочешь сделать? Пока доступна только регистрация.",
        reply_markup=REGISTER_ONLY
    )


@dp.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    if db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    await state.set_state(Registration.full_name)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        "Шаг 1 из 5.\nНапиши своё ФИО (например: Иванов Иван Иванович)"
    )


@dp.message(Registration.full_name)
async def process_name(message: types.Message, state: FSMContext):
    if db_is_blocked(message.from_user.id):
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ к боту ограничен.")
        await state.clear()
        return
    if not message.text:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Пожалуйста, отправь именно текст с ФИО.")
        return
    name = message.text.strip()
    if len(name.split()) < 2:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Похоже, этого мало. Напиши хотя бы имя и фамилию через пробел.")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.update_data(full_name=name)
    await state.set_state(Registration.phone)
    await send_tracked(
        message.chat.id, message.from_user.id,
        "Шаг 2 из 5.\nОтправь свой номер телефона — можно кнопкой ниже.",
        reply_markup=phone_kb()
    )


@dp.message(Registration.phone, lambda m: m.contact is not None)
async def process_phone_button(message: types.Message, state: FSMContext):
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Registration.birth_date)
    await send_tracked(
        message.chat.id, message.from_user.id,
        "Отлично, номер получен ✅\nШаг 3 из 5.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(Registration.phone)
async def process_phone_text(message: types.Message, state: FSMContext):
    if not message.text:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Отправь номер текстом или нажми кнопку «Поделиться номером».")
        return
    digits = message.text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or len(digits) < 10:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Это не похоже на номер. Попробуй ещё раз, например: +79001234567")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.update_data(phone=message.text.strip())
    await state.set_state(Registration.birth_date)
    await send_tracked(
        message.chat.id, message.from_user.id,
        "Номер записан ✅\nШаг 3 из 5.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(Registration.birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    if db_is_blocked(message.from_user.id):
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ к боту ограничен.")
        await state.clear()
        return
    if not message.text:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Пожалуйста, отправь дату текстом в формате ДД.ММ.ГГГГ.")
        return
    try:
        birth_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        if birth_date.year < 1900 or birth_date > datetime.now().date():
            raise ValueError
    except ValueError:
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "Такой даты не бывает. Проверь и напиши ещё раз: ДД.ММ.ГГГГ")
        return

    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    await state.update_data(birth_date=birth_date.strftime("%d.%m.%Y"))
    await state.set_state(Registration.position)
    await send_tracked(
        message.chat.id, message.from_user.id,
        "Дата записана ✅\nШаг 4 из 5.\nВыбери свою должность 👇",
        reply_markup=ReplyKeyboardRemove()
    )
    await send_tracked(message.chat.id, message.from_user.id, "Выбери должность из списка:", reply_markup=positions_kb())


@dp.callback_query(Registration.position, lambda c: c.data and c.data.startswith("pos:"))
async def process_position(callback: types.CallbackQuery, state: FSMContext):
    if db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        await state.clear()
        return
    await callback.answer()
    await cleanup_chat(callback.from_user.id)
    idx = int(callback.data.split(":")[1])
    position = POSITIONS[idx]
    await state.update_data(position=position)
    await state.set_state(Registration.restaurant)
    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"Должность: <b>{position}</b> ✅\n\nШаг 5 из 5.\nВыбери свой ресторан 👇",
        parse_mode="HTML",
        reply_markup=restaurants_pick_kb()
    )


@dp.callback_query(Registration.restaurant, lambda c: c.data and c.data.startswith("restpick:"))
async def process_restaurant_pick(callback: types.CallbackQuery, state: FSMContext):
    if db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        await state.clear()
        return
    await callback.answer()
    key = callback.data.split(":")[1]
    restaurant = db_restaurant(key)
    if not restaurant:
        await callback.answer("Ресторан не найден, выбери из списка", show_alert=True)
        return

    await cleanup_chat(callback.from_user.id)

    data = await state.get_data()
    full_name = data.get("full_name", "")
    phone = data.get("phone", "")
    birth_date = data.get("birth_date", "")
    position = data.get("position", "")

    try:
        db_save_profile(callback.from_user.id, full_name, phone, birth_date, position,
                        restaurant["key"], callback.from_user.first_name)
    except Exception as e:
        logging.error(f"Ошибка сохранения профиля для {callback.from_user.id}: {e}")
        await send_tracked(
            callback.message.chat.id, callback.from_user.id,
            "❌ Произошла ошибка при сохранении. Попробуй позже или напиши администратору."
        )
        await state.clear()
        return

    await state.clear()

    await send_tracked(
        callback.message.chat.id, callback.from_user.id,
        f"🎉 <b>{callback.from_user.first_name}, регистрация завершена!</b>\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}\n"
        f"💼 Должность: {position}\n"
        f"📍 Ресторан: {restaurant['name']}\n\n"
        "Открой приложение — там профиль, рестораны, новости, стандарты и вопросы/ответы:",
        parse_mode="HTML",
        reply_markup=FULL_MENU
    )

    if ADMIN_ID:
        username = f"@{callback.from_user.username}" if callback.from_user.username else "нет username"
        try:
            await bot.send_message(
                ADMIN_ID,
                "🔔 Новая регистрация!\n\n"
                f"👤 ФИО: {full_name}\n"
                f"📞 Телефон: {phone}\n"
                f"🎂 Дата рождения: {birth_date}\n"
                f"💼 Должность: {position}\n"
                f"📍 Ресторан: {restaurant['name']}\n"
                f"🆔 Telegram ID: <code>{callback.from_user.id}</code>\n"
                f"🔗 Username: {username}\n"
                f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу: {e}")


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    if db_is_blocked(message.from_user.id):
        await delete_incoming(message)
        await cleanup_chat(message.from_user.id)
        await send_tracked(message.chat.id, message.from_user.id, "⛔ Доступ к боту ограничен.")
        return
    await delete_incoming(message)
    await cleanup_chat(message.from_user.id)
    row = db_get(message.from_user.id)
    if row and row[0]:
        await send_tracked(message.chat.id, message.from_user.id, profile_text(row), parse_mode="HTML")
    else:
        await send_tracked(
            message.chat.id, message.from_user.id,
            "Ты ещё не зарегистрирован. Напиши /start и нажми «✍️ Зарегистрироваться»."
        )


# ================== ВЕБ-СЕРВЕР (API + Mini App) ==================

def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def denied_response(status: int):
    if status == 403:
        return web.json_response({"error": "blocked"}, status=403, dumps=json_dumps)
    return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)


AVATAR_CACHE = {}
AVATAR_TTL = 600


def avatar_cache_get(user_id):
    entry = AVATAR_CACHE.get(user_id)
    if not entry:
        return None
    data, ctype, saved_at = entry
    if datetime.now().timestamp() - saved_at > AVATAR_TTL:
        AVATAR_CACHE.pop(user_id, None)
        return None
    return data, ctype


async def handle_index(request):
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "index.html")
    if os.path.exists(index_path):
        resp = web.FileResponse(index_path)
        # Кэш HTML на 5 минут: повторное открытие приложения почти мгновенное.
        # Свежесть данных это не затрагивает — они приходят через API.
        resp.headers["Cache-Control"] = "public, max-age=300"
        return resp
    return web.Response(text="Mini App: файл frontend/index.html не найден", status=404)


def build_restaurants_payload():
    out = []
    for r in db_restaurants_for_app():
        status, status_text = restaurant_status_for(r)
        out.append({
            "key": r["key"],
            "name": r["name"],
            "address": r["address"],
            "hours": r["hours"],
            "org": r["org"],
            "phone": r.get("phone") or "",
            "sort": r.get("sort") if r.get("sort") is not None else 100,
            "status": status,
            "status_text": status_text,
        })
    return out


async def handle_bootstrap(request):
    """Один запрос для всего стартового экрана: профиль, поздравление, новости,
    рестораны, стандарты и FAQ. Вместо пяти обращений — одно."""
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)

    row = db_get(user_id)
    profile = None
    if row and row[0]:
        full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row
        profile = {
            "full_name": full_name,
            "first_name": db_get_first_name(user_id) or (full_name.split()[0] if full_name else ""),
            "phone": phone,
            "birth_date": birth_date,
            "position": position or "—",
            "restaurant": restaurant_name_by_key(restaurant) if restaurant else "—",
        }

    now = _moscow_now()
    kind, title, sub = greeting_for_user(row[2] if row else None, now)

    news_list = [
        {
            "id": news_id,
            "title": t,
            "text": b,
            "date": d.strftime("%d.%m.%Y") if d else "",
            "important": bool(imp),
            "level": lv or "normal",
        }
        for news_id, t, b, imp, lv, d in db_list_news()
    ]

    standards_list = [
        {"id": sid, "title": t, "category": c, "description": d, "url": u}
        for sid, t, c, d, u in db_list_standards()
    ]
    faq_list = [
        {"id": fid, "question": q, "answer": a, "category": c}
        for fid, q, a, c in db_list_faq()
    ]

    return web.json_response({
        "profile": profile,
        "greeting": {"kind": kind, "title": title, "sub": sub},
        "news": news_list,
        "restaurants": build_restaurants_payload(),
        "standards": standards_list,
        "faq": faq_list,
    }, dumps=json_dumps)


async def handle_restaurants(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)

    now_ts = time.time()
    if REST_CACHE["data"] is None or now_ts - REST_CACHE["ts"] > REST_CACHE_TTL:
        REST_CACHE["data"] = build_restaurants_payload()
        REST_CACHE["ts"] = now_ts

    return web.json_response(REST_CACHE["data"], dumps=json_dumps)


async def handle_greeting(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    row = db_get(user_id)
    birth_date = row[2] if row else None
    kind, title, sub = greeting_for_user(birth_date)
    return web.json_response({"kind": kind, "title": title, "sub": sub}, dumps=json_dumps)


async def handle_news(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    rows = db_list_news()
    news_list = [
        {
            "id": news_id,
            "title": title,
            "text": body,
            "date": created_at.strftime("%d.%m.%Y") if created_at else "",
            "important": bool(important),
            "level": level or "normal",
        }
        for news_id, title, body, important, level, created_at in rows
    ]
    return web.json_response(news_list, dumps=json_dumps)


async def handle_standards(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    data = [
        {"id": sid, "title": t, "category": c, "description": d, "url": u}
        for sid, t, c, d, u in db_list_standards()
    ]
    return web.json_response(data, dumps=json_dumps)


async def handle_faq(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)
    data = [
        {"id": fid, "question": q, "answer": a, "category": c}
        for fid, q, a, c in db_list_faq()
    ]
    return web.json_response(data, dumps=json_dumps)


async def handle_profile(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)

    row = db_get(user_id)
    if not row or not row[0]:
        return web.json_response({"registered": False}, dumps=json_dumps)

    full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row
    return web.json_response({
        "registered": True,
        "profile": {
            "full_name": full_name,
            "first_name": db_get_first_name(user_id) or (full_name.split()[0] if full_name else ""),
            "phone": phone,
            "birth_date": birth_date,
            "position": position or "—",
            "restaurant": restaurant_name_by_key(restaurant) if restaurant else "—",
            "tg_id": user_id,
        },
    }, dumps=json_dumps)


async def handle_avatar(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)

    cached = avatar_cache_get(user_id)
    if cached:
        data, content_type = cached
        return web.Response(body=data, content_type=content_type)

    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if not photos.total_count:
            return web.Response(status=204)
        file_id = photos.photos[0][-1].file_id
        file = await bot.get_file(file_id)
        tg_url = f"https://api.telegram.org/file/bot{TOKEN}/{file.file_path}"

        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(tg_url) as r:
                data = await r.read()
                content_type = r.content_type or "image/jpeg"

        AVATAR_CACHE[user_id] = (data, content_type, datetime.now().timestamp())
        return web.Response(body=data, content_type=content_type)
    except Exception as e:
        logging.warning(f"Не удалось получить фото профиля для {user_id}: {e}")
        return web.Response(status=204)


async def handle_questions(request):
    user_id, err = await get_auth_user(request)
    if err:
        return denied_response(err)

    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)

    question_text = (payload.get("question") or "").strip()
    if not question_text or len(question_text) > 1000:
        return web.json_response({"error": "invalid_question"}, status=400, dumps=json_dumps)

    if ADMIN_ID:
        row = db_get(user_id)
        who = row[0] if row and row[0] else "—"
        try:
            await bot.send_message(
                ADMIN_ID,
                "❓ Новый вопрос из приложения\n\n"
                f"👤 {who} (<code>{user_id}</code>)\n"
                f"💬 {question_text}",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.warning(f"Не удалось отправить вопрос админу: {e}")

    return web.json_response({"ok": True}, dumps=json_dumps)


async def handle_health(request):
    return web.Response(text="OK")


app = web.Application()
app.router.add_get("/", handle_index)
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
    logging.info(f"Web server (API + Mini App) running on port {port}")

    # Фоновые процессы поздравлений
    asyncio.create_task(birthday_checker())
    asyncio.create_task(holiday_broadcaster())

    print("STARTING BOT SCRIPT...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
        if _pool:
            _pool.closeall()


if __name__ == "__main__":
    asyncio.run(main())
