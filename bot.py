import os
import asyncio
import logging
import json
import hmac
import hashlib
from datetime import datetime
from urllib.parse import quote, unquote

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("ОШИБКА: Переменная BOT_TOKEN не задана!")
    raise ValueError("BOT_TOKEN is not set")

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


def get_conn():
    return psycopg2.connect(DB_URL)


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
    conn.commit()
print("База данных подключена, таблица готова.")


# Поле "org" — путь карточки на Яндекс Картах (yandex.ru/maps/org/<org>).
# ВНИМАНИЕ: у части ресторанов номера-заглушки, помечены комментарием "ЗАГЛУШКА" — замени!
RESTAURANTS = [
    {
        "key": "mega_belaya_dacha",
        "name": "Мега Белая Дача",
        "address": "Московская область, Котельники, 1-й Покровский проезд, 5, ТРЦ Мега, этаж 1",
        "hours": "Пн–чт: 10:00–22:00\nПт–вс: 10:00–23:00",
        "lat": 55.6578,
        "lon": 37.8891,
        "org": "vokker/128833821207",
        "phone": "+79154790941",
    },
    {
        "key": "belyaevo",
        "name": "Беляево",
        "address": "Москва, ул. Миклухо-Маклая, 32А, ТЦ «Капитолий», этаж 2",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.6470,
        "lon": 37.5420,
        "org": "vokker/13122472923",
        "phone": "+74954445566",  # ЗАГЛУШКА — замени на реальный номер
    },
    {
        "key": "vernadka",
        "name": "Вернадка",
        "address": "Москва, проспект Вернадского, 6, ТЦ «Капитолий Вернадского», этаж 3",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.6840,
        "lon": 37.4980,
        "org": "vokker/91626648547",
        "phone": "+74957778899",  # ЗАГЛУШКА — замени на реальный номер
    },
    {
        "key": "erevan_plaza",
        "name": "Ереван Плаза",
        "address": "Москва, ул. Большая Тульская, д. 13, ТРЦ «Ереван Плаза», этаж 3",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.7030,
        "lon": 37.6210,
        "org": "vokker/102264079721",
        "phone": "+79060946146",
    },
    {
        "key": "kuzminki_mall",
        "name": "Кузьминки Молл",
        "address": "Москва, ул. Зеленодольская, д. 42, ТРЦ «Кузьминки Молл», этаж 3",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.6980,
        "lon": 37.7750,
        "org": "vokker/24262320480",
        "phone": "+79685370994",
    },
    {
        "key": "mega_teplyy_stan",
        "name": "Мега Тёплый стан",
        "address": "Москва, Калужское шоссе, 21-й километр, с1, ТЦ «Мега Тёплый Стан»",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.5790,
        "lon": 37.4870,
        "org": "vokker/1485953945",
        "phone": "+74959990011",  # ЗАГЛУШКА — замени на реальный номер
    },
    {
        "key": "mega_himki",
        "name": "Мега Химки",
        "address": "Московская обл., г. Химки, микрорайон ИКЕА, к1, ТЦ «Мега Химки», этаж 1",
        "hours": "Пн–чт, вс: 10:00–23:00\nПт–сб: 10:00–24:00",
        "lat": 55.8970,
        "lon": 37.4120,
        "org": "vokker/132066311330",
        "phone": "+74952223344",  # ЗАГЛУШКА — замени на реальный номер
    },
    {
        "key": "metropolis",
        "name": "Метрополис",
        "address": "Москва, Ленинградское ш., д. 16А, стр. 4, ТРЦ «Метрополис», этаж 3",
        "hours": "Пн–вс: 10:00–23:00",
        "lat": 55.8120,
        "lon": 37.5060,
        "org": "vokker/1298559872",
        "phone": "+74955556677",  # ЗАГЛУШКА — замени на реальный номер
    },
    {
        "key": "moskva_city",
        "name": "Москва-Сити",
        "address": "Москва, 1-й Красногвардейский пр., д. 22, стр. 1 (Neva Towers), этаж 2, фуд-корт",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.7490,
        "lon": 37.5380,
        "org": "vokker/25826174821",
        "phone": "+79154799170",
    },
    {
        "key": "okeaniya",
        "name": "Океания",
        "address": "Москва, Кутузовский пр., д. 57, ТРЦ «Океания», этаж 3",
        "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00",
        "lat": 55.7330,
        "lon": 37.4950,
        "org": "vokker/9739651477",
        "phone": "+79154786401",
    },
    {
        "key": "polkovaya",
        "name": "Полковая",
        "address": "Москва, ул. Полковая, д. 3, стр. 5, БЦ «Шереметьевский», этаж 1",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.8010,
        "lon": 37.5920,
        "org": "vokker/84984433800",
        "phone": "+74959876543",  # ЗАГЛУШКА — замени на реальный номер
    },
    {
        "key": "cdm",
        "name": "ЦДМ",
        "address": "Москва, Театральный пр., д. 5, стр. 1, «ЦДМ на Лубянке», этаж 6",
        "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00",
        "lat": 55.7580,
        "lon": 37.6230,
        "org": "vokker/31463245515",
        "phone": "+79685370989",
    },
    {
        "key": "tsvetnoy",
        "name": "Цветной",
        "address": "Москва, Цветной бульвар, д. 15, стр. 1, ТРЦ «Цветной», этаж 5",
        "hours": "Пн–сб: 10:00–22:00\nВс: 11:00–22:00",
        "lat": 55.7670,
        "lon": 37.6180,
        "org": "vokker/110848206544",
        "phone": "+74955544332",  # ЗАГЛУШКА — замени на реальный номер
    },
    {
        "key": "shchelkovskaya",
        "name": "Щёлковская",
        "address": "Москва, Щёлковское шоссе, 75, ТРЦ «Щёлковский», этаж 5",
        "hours": "Пн–чт, вс: 10:00–22:00\nПт–сб: 10:00–23:00",
        "lat": 55.8050,
        "lon": 37.7920,
        "org": "vokker/25844145312",
        "phone": "+79996652654",
    },
    {
        "key": "shuka",
        "name": "Щука",
        "address": "Москва, ул. Щукинская, д. 42, ТРК «Щука», этаж 4",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.8020,
        "lon": 37.4650,
        "org": "vokker/1357579873",
        "phone": "+74957766554",  # ЗАГЛУШКА — замени на реальный номер
    },
]

POSITIONS = [
    "Холодный Цех",
    "Жарщик",
    "Управляющий сменой",
    "Территориальный управляющий",
]

# ================== КОНТЕНТ ДЛЯ ПРИЛОЖЕНИЯ ==================
# Наполняй списками — они отдаются приложению через API.

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


# ================== БАЗА ДАННЫХ ==================

def db_get(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT full_name, phone, birth_date, position, restaurant, welcomed, is_blocked "
                "FROM users WHERE user_id = %s",
                (user_id,)
            )
            return cur.fetchone()


def db_set_welcomed(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id, welcomed) VALUES (%s, TRUE) "
                "ON CONFLICT (user_id) DO UPDATE SET welcomed = TRUE",
                (user_id,)
            )
        conn.commit()


def db_save_profile(user_id: int, full_name: str, phone: str, birth_date: str, position: str, restaurant):
    # Страховка: если случайно передали словарь ресторана — берём из него ключ
    if isinstance(restaurant, dict):
        restaurant = restaurant.get("key", "")
    if restaurant is not None:
        restaurant = str(restaurant)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (user_id, full_name, phone, birth_date, position, restaurant, welcomed)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (user_id) DO UPDATE SET
                full_name = %s, phone = %s, birth_date = %s, position = %s, restaurant = %s, welcomed = TRUE
                """,
                (user_id, full_name, phone, birth_date, position, restaurant,
                 full_name, phone, birth_date, position, restaurant)
            )
        conn.commit()


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


def db_delete_user(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()
        return cur.rowcount > 0


def db_set_blocked(user_id: int, blocked: bool):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_blocked = %s WHERE user_id = %s",
                (blocked, user_id)
            )
        conn.commit()
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


bot = Bot(token=TOKEN)
dp = Dispatcher()


def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID


class Registration(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()
    position = State()
    restaurant = State()


# ================== ПРОВЕРКА MINI APP (initData) ==================

def validate_init_data(init_data: str):
    """Проверяет подпись initData из Mini App. Возвращает dict пользователя или None."""
    if not init_data:
        return None
    try:
        pairs = {}
        for pair in init_data.split("&"):
            key, _, value = pair.partition("=")
            pairs[key] = value
    except Exception:
        return None
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed_hash, received_hash):
        return None
    try:
        # поле user приходит URL-кодированным — декодируем перед разбором JSON
        return json.loads(unquote(pairs.get("user", "{}")))
    except Exception:
        return None


# ================== КЛАВИАТУРЫ ==================

FULL_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📱 Открыть приложение Wokker", web_app=WebAppInfo(url=MINI_APP_URL))],
    [InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile")],
    [InlineKeyboardButton(text="🏙️ Наши рестораны (списком)", callback_data="restaurants")],
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


def restaurants_pick_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r["name"], callback_data=f"restpick:{r['key']}")]
        for r in RESTAURANTS
    ])


def restaurant_name_by_key(key):
    rest = next((r for r in RESTAURANTS if r["key"] == key), None)
    return rest["name"] if rest else key


def profile_text(row):
    full_name, phone, birth_date, position, restaurant = row[0], row[1], row[2], row[3], row[4]
    rest_name = restaurant_name_by_key(restaurant) if restaurant else "—"
    return (
        "Твой профиль:\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}\n"
        f"💼 Должность: {position or '—'}\n"
        f"📍 Ресторан: {rest_name}"
    )


def map_link(restaurant) -> str:
    if restaurant.get("org"):
        return f"https://yandex.ru/maps/org/{restaurant['org']}"
    query = quote(f"Воккер {restaurant['address']}", safe="")
    return f"https://yandex.ru/maps/?text={query}"


def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="adm_users")],
        [InlineKeyboardButton(text="📊 Отчёты", callback_data="adm_reports")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_menu")],
    ])


def users_list_kb(rows):
    kb = []
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        if is_blocked:
            icon = "🚫"
            action_text = "✅ Разбанить"
            action_data = f"adm_unban:{user_id}"
        else:
            icon = "✅" if full_name else "⏳"
            action_text = "🚫 Забанить"
            action_data = f"adm_ban:{user_id}"
        kb.append([
            InlineKeyboardButton(
                text=f"{icon} {full_name or 'Без имени'} · {phone or user_id}",
                callback_data="noop"
            ),
            InlineKeyboardButton(text=action_text, callback_data=action_data),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_del:{user_id}"),
        ])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def users_list_text(rows):
    if not rows:
        return "📭 Пока никто не зарегистрирован."
    lines = [f"📋 Всего записей: {len(rows)}\n"]
    for user_id, full_name, phone, position, restaurant, welcomed, is_blocked in rows:
        status = "🚫 заблокирован" if is_blocked else ("✅" if full_name else "⏳ не завершил")
        rest_name = restaurant_name_by_key(restaurant) if restaurant else "—"
        lines.append(
            f"{status} <code>{user_id}</code>\n"
            f"   👤 {full_name or '—'} · 📞 {phone or '—'}\n"
            f"   💼 {position or '—'} · 📍 {rest_name}\n"
        )
    return "\n".join(lines)


# ================== АДМИНКА ==================

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "🛠 <b>Админ-панель</b>\n\nВыбери действие:",
        parse_mode="HTML",
        reply_markup=admin_menu_kb()
    )


@dp.callback_query(lambda c: c.data == "adm_menu")
async def adm_menu(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer("🛠 Админ-панель", reply_markup=admin_menu_kb())


@dp.callback_query(lambda c: c.data == "adm_users")
async def adm_users(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
    rows = db_list_users()
    await callback.message.answer(users_list_text(rows), parse_mode="HTML", reply_markup=users_list_kb(rows))


@dp.callback_query(lambda c: c.data == "adm_reports")
async def adm_reports(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await callback.answer()
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
    await callback.message.answer(text, parse_mode="HTML")


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
    rows = db_list_users()
    try:
        await callback.message.edit_text(users_list_text(rows), parse_mode="HTML", reply_markup=users_list_kb(rows))
    except Exception:
        pass


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
    rows = db_list_users()
    try:
        await callback.message.edit_text(users_list_text(rows), parse_mode="HTML", reply_markup=users_list_kb(rows))
    except Exception:
        pass


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
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"adm_del_yes:{target_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="adm_users"),
        ]
    ])
    await callback.message.answer(
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
        await callback.message.answer(f"🗑 Пользователь <code>{target_id}</code> удалён.", parse_mode="HTML")
    else:
        await callback.answer("Пользователь не найден", show_alert=True)


@dp.callback_query(lambda c: c.data == "noop")
async def adm_noop(callback: types.CallbackQuery):
    if is_admin(callback.from_user.id):
        await callback.answer()
    else:
        await callback.answer("⛔ Недоступно", show_alert=True)


# ================== РЕСТОРАНЫ (в боте, как запасной вариант) ==================

def restaurants_menu_kb():
    kb = []
    for r in RESTAURANTS:
        kb.append([InlineKeyboardButton(text=r["name"], callback_data=f"rest_info:{r['key']}")])
    kb.append([InlineKeyboardButton(text="← Назад в главное меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@dp.callback_query(lambda c: c.data == "restaurants")
async def show_restaurants_menu(callback: types.CallbackQuery):
    await callback.answer()
    if db_is_blocked(callback.from_user.id):
        await callback.message.answer("⛔ Доступ к боту ограничен.")
        return
    await callback.message.answer(
        "🏙️ <b>Наши рестораны</b>\n\nВыбери точку из списка:",
        parse_mode="HTML",
        reply_markup=restaurants_menu_kb()
    )


@dp.callback_query(lambda c: c.data and c.data.startswith("rest_info:"))
async def show_restaurant_info(callback: types.CallbackQuery):
    await callback.answer()
    if db_is_blocked(callback.from_user.id):
        await callback.message.answer("⛔ Доступ к боту ограничен.")
        return

    key = callback.data.split(":")[1]
    restaurant = next((r for r in RESTAURANTS if r["key"] == key), None)
    if not restaurant:
        await callback.answer("Ресторан не найден", show_alert=True)
        return

    phone_line = f"📞 Позвонить: {restaurant['phone']}\n\n" if restaurant.get("phone") else ""

    text = (
        f"<b>{restaurant['name']}</b>\n\n"
        f"📍 Адрес: {restaurant['address']}\n"
        f"🕒 Часы работы:\n{restaurant['hours']}\n\n"
        f"{phone_line}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺 Открыть на Яндекс Картах", url=map_link(restaurant))],
        [InlineKeyboardButton(text="← Назад к списку ресторанов", callback_data="restaurants")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
    ])

    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logging.exception(f"edit_text не сработал: {e}")
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)


# ================== РЕГИСТРАЦИЯ ==================

@dp.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery):
    await callback.answer()
    row = db_get(callback.from_user.id)
    if row and row[0]:
        await callback.message.answer("Выбери действие:", reply_markup=FULL_MENU)
    else:
        await callback.message.answer("Что хочешь сделать?", reply_markup=REGISTER_ONLY)


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    if db_is_blocked(user_id):
        await message.answer("⛔ Доступ к боту ограничен. Обратитесь к администратору.")
        return

    current_state = await state.get_state()
    if current_state:
        if current_state == Registration.full_name.state:
            await message.answer("Шаг 1 из 5.\nНапиши своё ФИО (например: Иванов Иван Иванович)")
        elif current_state == Registration.phone.state:
            await message.answer("Шаг 2 из 5.\nОтправь свой номер телефона — можно кнопкой ниже.", reply_markup=phone_kb())
        elif current_state == Registration.birth_date.state:
            await message.answer(
                "Шаг 3 из 5.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
                reply_markup=ReplyKeyboardRemove()
            )
        elif current_state == Registration.position.state:
            await message.answer("Шаг 4 из 5.\nВыбери свою должность:", reply_markup=positions_kb())
        elif current_state == Registration.restaurant.state:
            await message.answer("Шаг 5 из 5.\nВыбери свой ресторан:", reply_markup=restaurants_pick_kb())
        return

    await state.clear()
    row = db_get(user_id)

    if row and row[0]:
        await message.answer("Выбери действие:", reply_markup=FULL_MENU)
        return

    if row and row[5]:
        await message.answer("Сначала заверши регистрацию 👇", reply_markup=REGISTER_ONLY)
        return

    db_set_welcomed(user_id)
    await message.answer(
        f"👋 {message.from_user.first_name}, добро пожаловать в Wokker!\n\n"
        "Мы готовим паназиатские блюда на воке — быстро и со вкусом.\n"
        "Для начала зарегистрируйся 👇"
    )
    await message.answer("Что хочешь сделать? Пока доступна только регистрация.", reply_markup=REGISTER_ONLY)


@dp.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    if db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        return
    await callback.answer()
    await state.set_state(Registration.full_name)
    await callback.message.answer("Шаг 1 из 5.\nНапиши своё ФИО (например: Иванов Иван Иванович)")


@dp.message(Registration.full_name)
async def process_name(message: types.Message, state: FSMContext):
    if db_is_blocked(message.from_user.id):
        await message.answer("⛔ Доступ к боту ограничен.")
        await state.clear()
        return
    if not message.text:
        await message.answer("Пожалуйста, отправь именно текст с ФИО.")
        return
    name = message.text.strip()
    if len(name.split()) < 2:
        await message.answer("Похоже, этого мало. Напиши хотя бы имя и фамилию через пробел.")
        return
    await state.update_data(full_name=name)
    await state.set_state(Registration.phone)
    await message.answer("Шаг 2 из 5.\nОтправь свой номер телефона — можно кнопкой ниже.", reply_markup=phone_kb())


@dp.message(Registration.phone, lambda m: m.contact is not None)
async def process_phone_button(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Registration.birth_date)
    await message.answer(
        "Отлично, номер получен ✅\nШаг 3 из 5.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(Registration.phone)
async def process_phone_text(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь номер текстом или нажми кнопку «Поделиться номером».")
        return
    digits = message.text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or len(digits) < 10:
        await message.answer("Это не похоже на номер. Попробуй ещё раз, например: +79001234567")
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(Registration.birth_date)
    await message.answer(
        "Номер записан ✅\nШаг 3 из 5.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
        reply_markup=ReplyKeyboardRemove()
    )


@dp.message(Registration.birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    if db_is_blocked(message.from_user.id):
        await message.answer("⛔ Доступ к боту ограничен.")
        await state.clear()
        return
    if not message.text:
        await message.answer("Пожалуйста, отправь дату текстом в формате ДД.ММ.ГГГГ.")
        return
    try:
        birth_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        if birth_date.year < 1900 or birth_date > datetime.now().date():
            raise ValueError
    except ValueError:
        await message.answer("Такой даты не бывает. Проверь и напиши ещё раз: ДД.ММ.ГГГГ")
        return

    await state.update_data(birth_date=birth_date.strftime("%d.%m.%Y"))
    await state.set_state(Registration.position)
    await message.answer(
        "Дата записана ✅\nШаг 4 из 5.\nВыбери свою должность 👇",
        reply_markup=ReplyKeyboardRemove()
    )
    await message.answer("Выбери должность из списка:", reply_markup=positions_kb())


@dp.callback_query(Registration.position, lambda c: c.data and c.data.startswith("pos:"))
async def process_position(callback: types.CallbackQuery, state: FSMContext):
    if db_is_blocked(callback.from_user.id):
        await callback.answer("Доступ ограничен", show_alert=True)
        await state.clear()
        return
    await callback.answer()
    idx = int(callback.data.split(":")[1])
    position = POSITIONS[idx]
    await state.update_data(position=position)
    await state.set_state(Registration.restaurant)
    await callback.message.answer(
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
    restaurant = next((r for r in RESTAURANTS if r["key"] == key), None)
    if not restaurant:
        await callback.answer("Ресторан не найден, выбери из списка", show_alert=True)
        return

    data = await state.get_data()
    full_name = data.get("full_name", "")
    phone = data.get("phone", "")
    birth_date = data.get("birth_date", "")
    position = data.get("position", "")

    # 1. Сохраняем профиль. Если база упала — сообщаем и не оставляем пользователя в тишине.
    try:
        db_save_profile(callback.from_user.id, full_name, phone, birth_date, position, restaurant["key"])
    except Exception as e:
        logging.error(f"Ошибка сохранения профиля для {callback.from_user.id}: {e}")
        await callback.message.answer(
            "❌ Произошла ошибка при сохранении. Попробуй позже или напиши администратору."
        )
        await state.clear()
        return

    await state.clear()

    # 2. Сообщение об успехе с кнопкой запуска приложения (FULL_MENU содержит web_app-кнопку)
    await callback.message.answer(
        "🎉 <b>Регистрация завершена!</b>\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}\n"
        f"💼 Должность: {position}\n"
        f"📍 Ресторан: {restaurant['name']}\n\n"
        "Открой приложение — там профиль, рестораны, стандарты и вопросы/ответы:",
        parse_mode="HTML",
        reply_markup=FULL_MENU
    )

    # 3. Уведомление админу — отдельно, чтобы сбой отправки не ломал регистрацию
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


@dp.callback_query(lambda c: c.data == "show_profile")
async def show_profile_callback(callback: types.CallbackQuery):
    await callback.answer()
    if db_is_blocked(callback.from_user.id):
        await callback.message.answer("⛔ Доступ к боту ограничен.")
        return
    row = db_get(callback.from_user.id)
    if row and row[0]:
        await callback.message.answer(profile_text(row))
    else:
        await callback.message.answer("Ты ещё не зарегистрирован.\nНажми /start и «✍️ Зарегистрироваться».")


@dp.callback_query(lambda c: c.data == "standards")
async def show_standards(callback: types.CallbackQuery):
    await callback.answer()
    if db_is_blocked(callback.from_user.id):
        await callback.message.answer("⛔ Доступ к боту ограничен.")
        return
    await callback.message.answer(
        "📚 Библиотека стандартов\n\nОткрой мини-приложение — там полный список документов.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=MINI_APP_URL))],
        ])
    )


@dp.callback_query(lambda c: c.data == "faq")
async def show_faq(callback: types.CallbackQuery):
    await callback.answer()
    if db_is_blocked(callback.from_user.id):
        await callback.message.answer("⛔ Доступ к боту ограничен.")
        return
    await callback.message.answer(
        "❓ Вопрос/ответ\n\nОткрой мини-приложение — там база вопросов и форма для своего вопроса.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=MINI_APP_URL))],
        ])
    )


@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    if db_is_blocked(message.from_user.id):
        await message.answer("⛔ Доступ к боту ограничен.")
        return
    row = db_get(message.from_user.id)
    if row and row[0]:
        await message.answer(profile_text(row))
    else:
        await message.answer("Ты ещё не зарегистрирован. Напиши /start и нажми «✍️ Зарегистрироваться».")


# ================== ВЕБ-СЕРВЕР (API + Mini App) ==================

def json_dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)


async def handle_index(request):
    """Отдаёт главную страницу Mini App из frontend/index.html."""
    index_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend", "index.html")
    if os.path.exists(index_path):
        return web.FileResponse(index_path)
    return web.Response(text="Mini App: файл frontend/index.html не найден", status=404)


async def handle_restaurants(request):
    return web.json_response(RESTAURANTS, dumps=json_dumps)


async def handle_standards(request):
    return web.json_response(STANDARDS, dumps=json_dumps)


async def handle_faq(request):
    return web.json_response(FAQ, dumps=json_dumps)


async def handle_profile(request):
    """Возвращает профиль сотрудника. Требует валидный initData из Mini App."""
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)

    user = validate_init_data(payload.get("initData", ""))
    if not user or not user.get("id"):
        return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)

    user_id = int(user["id"])
    if db_is_blocked(user_id):
        return web.json_response({"error": "blocked"}, status=403, dumps=json_dumps)

    row = db_get(user_id)
    if not row or not row[0]:
        return web.json_response({"registered": False}, dumps=json_dumps)

    full_name, phone, birth_date, position, restaurant, welcomed, is_blocked = row
    return web.json_response({
        "registered": True,
        "profile": {
            "full_name": full_name,
            "phone": phone,
            "birth_date": birth_date,
            "position": position or "—",
            "restaurant": restaurant_name_by_key(restaurant) if restaurant else "—",
            "tg_id": user_id,
        },
    }, dumps=json_dumps)


async def handle_questions(request):
    """Принимает вопрос сотрудника из мини-приложения и пересылает админу."""
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid_json"}, status=400, dumps=json_dumps)

    user = validate_init_data(payload.get("initData", ""))
    if not user or not user.get("id"):
        return web.json_response({"error": "unauthorized"}, status=401, dumps=json_dumps)

    question_text = (payload.get("question") or "").strip()
    if not question_text or len(question_text) > 1000:
        return web.json_response({"error": "invalid_question"}, status=400, dumps=json_dumps)

    user_id = int(user["id"])
    if db_is_blocked(user_id):
        return web.json_response({"error": "blocked"}, status=403, dumps=json_dumps)

    if ADMIN_ID:
        row = db_get(user_id)
        who = row[0] if row and row[0] else user.get("username", "—")
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
app.router.add_get("/api/restaurants", handle_restaurants)
app.router.add_get("/api/standards", handle_standards)
app.router.add_get("/api/faq", handle_faq)
app.router.add_post("/api/profile", handle_profile)
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

    print("STARTING BOT SCRIPT...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
