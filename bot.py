import os
import asyncio
import logging
from datetime import datetime

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
)
import psycopg2

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("❌ ОШИБКА: Переменная BOT_TOKEN не задана!")
    raise ValueError("BOT_TOKEN is not set")

ADMIN_ID = os.getenv("ADMIN_ID")
if not ADMIN_ID:
    print("⚠️ ПРЕДУПРЕЖДЕНИЕ: Переменная ADMIN_ID не задана — админ-панель отключена.")
    ADMIN_ID = None
else:
    ADMIN_ID = int(ADMIN_ID)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("❌ ОШИБКА: Переменная DATABASE_URL не задана!")
    raise ValueError("DATABASE_URL is not set")

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
                welcomed BOOLEAN DEFAULT FALSE,
                is_blocked BOOLEAN DEFAULT FALSE
            )
        """)
        cur.execute("""
            ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE
        """)
    conn.commit()
print("🗄️ База данных подключена, таблица готова.")

RESTAURANTS = [
    {
        "key": "mega_belaya_dacha",
        "name": "Мега Белая Дача",
        "address": "г. Котельники, 1-й Покровский проезд, д. 5, ТЦ «Мега Белая Дача»",
        "hours": "10:00–22:00",
        "lat": 55.6578,
        "lon": 37.8891,
    },
    {
        "key": "belyaevo",
        "name": "Беляево",
        "address": "Москва, ул. Профсоюзная, д. ХХ, ТЦ «Беляево»",
        "hours": "10:00–23:00",
        "lat": 55.6470,
        "lon": 37.5420,
    },
    {
        "key": "vernadka",
        "name": "Вернадка",
        "address": "Москва, пр. Вернадского, д. ХХ",
        "hours": "09:00–22:00",
        "lat": 55.6840,
        "lon": 37.4980,
    },
    {
        "key": "erevan_plaza",
        "name": "Ереван Плаза",
        "address": "Москва, ул. Большая Тульская, д. 13, ТРЦ «Ереван Плаза»",
        "hours": "10:00–23:00",
        "lat": 55.7030,
        "lon": 37.6210,
    },
    {
        "key": "kuzminki_mall",
        "name": "Кузьминки Молл",
        "address": "Москва, Волгоградский пр., д. ХХ, ТРЦ «Кузьминки Молл»",
        "hours": "10:00–22:00",
        "lat": 55.6980,
        "lon": 37.7750,
    },
    {
        "key": "mega_teplyy_stan",
        "name": "Мега Тёплый стан",
        "address": "Москва, Калужское шоссе, 21-й км, ТЦ «Мега Тёплый Стан»",
        "hours": "10:00–23:00",
        "lat": 55.5790,
        "lon": 37.4870,
    },
    {
        "key": "mega_himki",
        "name": "Мега Химки",
        "address": "Московская обл., г. Химки, Ленинградское шоссе, 23-й км, ТЦ «Мега Химки»",
        "hours": "10:00–23:00",
        "lat": 55.8970,
        "lon": 37.4120,
    },
    {
        "key": "metropolis",
        "name": "Метрополис",
        "address": "Москва, Ленинградское ш., д. 16А, ТРЦ «Метрополис»",
        "hours": "10:00–23:00",
        "lat": 55.8120,
        "lon": 37.5060,
    },
    {
        "key": "moskva_city",
        "name": "Москва-Сити",
        "address": "Москва, Пресненская наб., д. 2, ММДЦ «Москва-Сити»",
        "hours": "10:00–23:00",
        "lat": 55.7490,
        "lon": 37.5380,
    },
    {
        "key": "okeaniya",
        "name": "Океания",
        "address": "Москва, Кутузовский пр., д. 57, ТРЦ «Океания»",
        "hours": "10:00–22:00",
        "lat": 55.7330,
        "lon": 37.4950,
    },
    {
        "key": "polkovaya",
        "name": "Полковая",
        "address": "Москва, ул. Полковая, д. ХХ",
        "hours": "09:00–21:00",
        "lat": 55.8010,
        "lon": 37.5920,
    },
    {
        "key": "cdm",
        "name": "ЦДМ",
        "address": "Москва, Театральный пр., д. 5, стр. 1, «ЦДМ на Лубянке»",
        "hours": "10:00–22:00",
        "lat": 55.7580,
        "lon": 37.6230,
    },
    {
        "key": "tsvetnoy",
        "name": "Цветной",
        "address": "Москва, Цветной бульвар, д. 15, ТРЦ «Цветной»",
        "hours": "10:00–23:00",
        "lat": 55.7670,
        "lon": 37.6180,
    },
    {
        "key": "shchelkovskaya",
        "name": "Щёлковская",
        "address": "Москва, Щёлковское ш., д. ХХ",
        "hours": "10:00–22:00",
        "lat": 55.8050,
        "lon": 37.7920,
    },
    {
        "key": "shuka",
        "name": "Щука",
        "address": "Москва, ул. Щукинская, д. 42, ТРЦ «Щука»",
        "hours": "10:00–23:00",
        "lat": 55.8020,
        "lon": 37.4650,
    },
]

def db_get(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT full_name, phone, birth_date, welcomed, is_blocked FROM users WHERE user_id = %s",
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

def db_save_profile(user_id: int, full_name: str, phone: str, birth_date: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (user_id, full_name, phone, birth_date, welcomed) "
                "VALUES (%s, %s, %s, %s, TRUE) "
                "ON CONFLICT (user_id) DO UPDATE SET "
                "full_name = %s, phone = %s, birth_date = %s, welcomed = TRUE",
                (user_id, full_name, phone, birth_date, full_name, phone, birth_date)
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
                SELECT user_id, full_name, phone, welcomed, is_blocked
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

bot = Bot(token=TOKEN)
dp = Dispatcher()

def is_admin(user_id: int) -> bool:
    return ADMIN_ID is not None and user_id == ADMIN_ID

class Registration(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()

FULL_MENU = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile")],
    [InlineKeyboardButton(text="🏙️ Наши рестораны", callback_data="restaurants")],
    [InlineKeyboardButton(text="📚 Библиотека стандартов", callback_data="standards")],
    [InlineKeyboardButton(text="❓ Вопрос/ответ", callback_data="faq")],
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

def profile_text(row):
    full_name, phone, birth_date = row[0], row[1], row[2]
    return (
        "Твой профиль:\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}"
    )

def map_link(lat: float, lon: float) -> str:
    return f"https://yandex.ru/maps/?ll={lon},{lat}&z=17"

def back_to_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Назад в главное меню", callback_data="back_to_menu")]
    ])

def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="adm_users")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm_menu")],
    ])

def users_list_kb(rows):
    kb = []
    for user_id, full_name, phone, welcomed, is_blocked in rows:
        if is_blocked:
            icon = "🚫"
            action = ("✅ Разбанить", f"adm_unban:{user_id}")
        else:
            icon = "✅" if full_name else "⏳"
            action = ("🚫 Забанить", f"adm_ban:{user_id}")
        kb.append([
            InlineKeyboardButton(text=f"{icon} {full_name or 'Без имени'} · {phone or user_id}", callback_data="noop"),
            InlineKeyboardButton(text=action[0], callback_data=action[1]),
            InlineKeyboardButton(text="🗑", callback_data=f"adm_del:{user_id}"),
        ])
    kb.append([InlineKeyboardButton(text="🔙 В админ-меню", callback_data="adm_menu")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def users_list_text(rows):
    if not rows:
        return "📭 Пока никто не зарегистрирован."
    lines = [f"📋 Всего записей: {len(rows)}\n"]
    for user_id, full_name, phone, welcomed, is_blocked in rows:
        status = "🚫 заблокирован" if is_blocked else ("✅" if full_name else "⏳ не завершил")
        lines.append(
            f"{status} <code>{user_id}</code>\n"
            f"   👤 {full_name or '—'} · 📞 {phone or '—'}\n"
        )
    return "\n".join(lines)

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

@dp.callback_query(lambda c: c.data and c.data.startswith("adm_ban:"))
async def adm_ban(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    if target_id == ADMIN_ID:
        await callback.answer("😅 Нельзя заблокировать самого себя", show_alert=True)
        return
