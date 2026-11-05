import os
import asyncio
import logging
from datetime import datetime
from urllib.parse import quote

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
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE")
    conn.commit()
print("База данных подключена, таблица готова.")


# Поле "org" — путь карточки на Яндекс Картах (yandex.ru/maps/org/<org>).
# Поле "phone" — номер в формате tel:.
# ВНИМАНИЕ: у 8 ресторанов номера-заглушки, помечены комментарием "ЗАГЛУШКА" — замени!
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


def map_link(restaurant) -> str:
    if restaurant.get("org"):
        return f"https://yandex.ru/maps/org/{restaurant['org']}"
    # Кодируем кириллицу, иначе Telegram отклонит кнопку (BUTTON_URL_INVALID)
    query = quote(f"Воккер {restaurant['address']}", safe="")
    return f"https://yandex.ru/maps/?text={query}"


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

    # Телефон идёт обычным текстом — Telegram сам делает его кликабельным,
    # и по нажатию откроется набор номера. Кнопку с tel: Telegram не принимает
    # (BUTTON_URL_INVALID), поэтому кнопки звонка здесь нет.
    phone_line = f"📞 Позвонить: {restaurant['phone']}\n\n" if restaurant.get("phone") else ""

    text = (
        f"<b>{restaurant['name']}</b>\n\n"
        f"📍 Адрес: {restaurant['address']}\n"
        f"🕒 Часы работы:\n{restaurant['hours']}\n\n"
        f"{phone_line}"
        f"🗺 На карте: {map_link(restaurant)}"
    )

    # В кнопках только https-ссылки — их Telegram принимает без ошибок
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
            await message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")
        elif current_state == Registration.phone.state:
            await message.answer("Шаг 2 из 3.\nОтправь свой номер телефона — можно кнопкой ниже.", reply_markup=phone_kb())
        elif current_state == Registration.birth_date.state:
            await message.answer(
                "Шаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
                reply_markup=ReplyKeyboardRemove()
            )
        return

    await state.clear()
    row = db_get(user_id)

    if row and row[0]:
        await message.answer("Выбери действие:", reply_markup=FULL_MENU)
        return

    if row and row[3]:
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
    await callback.message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")


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
        "📚 Библиотека стандартов\n\nЗдесь будут инструкции, чек-листы и стандарты качества Wokker."
    )


@dp.callback_query(lambda c: c.data == "faq")
async def show_faq(callback: types.CallbackQuery):
    await callback.answer()
    if db_is_blocked(callback.from_user.id):
        await callback.message.answer("⛔ Доступ к боту ограничен.")
        return
    await callback.message.answer(
        "❓ Вопрос/ответ\n\nЧастые вопросы и ответы по работе с ботом и ресторанами."
    )


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
    await message.answer("Шаг 2 из 3.\nОтправь свой номер телефона — можно кнопкой ниже.", reply_markup=phone_kb())


@dp.message(Registration.phone, lambda m: m.contact is not None)
async def process_phone_button(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Registration.birth_date)
    await message.answer(
        "Отлично, номер получен ✅\nШаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
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
        "Номер записан ✅\nШаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
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

    data = await state.get_data()
    full_name = data.get("full_name", "")
    phone = data.get("phone", "")
    db_save_profile(message.from_user.id, full_name, phone, birth_date.strftime("%d.%m.%Y"))
    await state.clear()

    await message.answer(
        "Регистрация завершена! 🎉\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date.strftime('%d.%m.%Y')}\n\n"
        "Теперь можешь в любой момент открыть меню (/start)."
    )
    await message.answer("Выбери действие:", reply_markup=FULL_MENU)

    if ADMIN_ID:
        username = f"@{message.from_user.username}" if message.from_user.username else "нет username"
        try:
            await bot.send_message(
                ADMIN_ID,
                "🔔 Новая регистрация!\n\n"
                f"👤 ФИО: {full_name}\n"
                f"📞 Телефон: {phone}\n"
                f"🎂 Дата рождения: {birth_date.strftime('%d.%m.%Y')}\n"
                f"🆔 Telegram ID: <code>{message.from_user.id}</code>\n"
                f"🔗 Username: {username}\n"
                f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Не удалось отправить уведомление админу: {e}")


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


async def health_check_server():
    app = web.Application()

    async def handle(request):
        return web.Response(text="OK")

    app.router.add_get('/', handle)
    port = int(os.environ.get('PORT', 8080))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Health Check server is LIVE on port {port}")
    return runner


async def main():
    runner = await health_check_server()
    print("STARTING BOT SCRIPT...")
    bot_task = asyncio.create_task(dp.start_polling(bot))
    print("Bot polling started. Waiting for updates...")
    try:
        await asyncio.gather(bot_task)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
