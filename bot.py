import os
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
import psycopg2
from psycopg2 import OperationalError, ProgrammingError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("❌ Переменная BOT_TOKEN не задана!")
    raise ValueError("BOT_TOKEN is not set")

ADMIN_ID = os.getenv("ADMIN_ID")
if ADMIN_ID:
    ADMIN_ID = int(ADMIN_ID)
else:
    logger.warning("⚠️ ADMIN_ID не задан — админ-панель отключена.")
    ADMIN_ID = None

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    logger.error("❌ Переменная DATABASE_URL не задана!")
    raise ValueError("DATABASE_URL is not set")


def get_conn():
    return psycopg2.connect(DB_URL)


def init_db():
    try:
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
                try:
                    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_blocked BOOLEAN DEFAULT FALSE")
                except ProgrammingError:
                    pass
            conn.commit()
        logger.info("✅ База данных подключена, таблица готова.")
    except OperationalError as e:
        logger.error(f"❌ Ошибка подключения к БД: {e}")
        raise


init_db()


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
        "phone": "+74954445566",
    },
    {
        "key": "vernadka",
        "name": "Вернадка",
        "address": "Москва, проспект Вернадского, 6, ТЦ «Капитолий Вернадского», этаж 3",
        "hours": "Пн–вс: 10:00–22:00",
        "lat": 55.6840,
        "lon": 37.4980,
        "org": "vokker/91626648547",
        "phone": "+74957778899",
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
        "phone": "+74959990011",
    },
    {
        "key": "mega_himki",
        "name": "Мега Химки",
        "address": "Московская обл., г. Химки, микрорайон ИКЕА, к1, ТЦ «Мега Химки», этаж 1",
        "hours": "Пн–чт, вс: 10:00–23:00\nПт–сб: 10:00–24:00",
        "lat": 55.8970,
        "lon": 37.4120,
        "org": "vokker/132066311330",
        "phone": "+74952223344",
    },
    {
        "key": "metropolis",
        "name": "Метрополис",
        "address": "Москва, Ленинградское ш., д. 16А, стр. 4, ТРЦ «Метрополис», этаж 3",
        "hours": "Пн–вс: 10:00–23:00",
        "lat": 55.8120,
        "lon": 37.5060,
        "org": "vokker/1298559872",
        "phone": "+74955556677",
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
        "phone": "+74959876543",
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
        "phone": "+74955544332",
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
        "phone": "+74957766554",
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
            return bool(row and row)


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


@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if db_is_blocked(user_id):
        await message.answer("Вы заблокированы.")
        return

    db_set_welcomed(user_id)
    user_data = db_get(user_id)
    if user_data and user_data:  # welcomed == True [3](https://github.com/dvkonstantinov/aiogram-food-bot)
        await message.answer("Добро пожаловать обратно!", reply_markup=FULL_MENU)
    else:
        await message.answer(
            "Привет! Для доступа к функционалу пройдите регистрацию.",
            reply_markup=REGISTER_ONLY
        )


@dp.callback_query(lambda c: c.data == "register")
async def process_register(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.message.edit_text("Введите ваше полное имя:")
    await state.set_state(Registration.full_name)


@dp.message(Registration.full_name)
async def process_full_name(message: types.Message, state: FSMContext):
    await state.update_data(full_name=message.text)
    await message.answer("Теперь укажите номер телефона (в формате +7...):")
    await state.set_state(Registration.phone)


@dp.message(Registration.phone)
async def process_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.text)
    await message.answer("Укажите дату рождения (ДД.ММ.ГГГГ):")
    await state.set_state(Registration.birth_date)


@dp.message(Registration.birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    data = await state.get_data()
    full_name = data["full_name"]
    phone = data["phone"]
    birth_date = message.text
    user_id = message.from_user.id

    db_save_profile(user_id, full_name, phone, birth_date)
    await state.clear()
    await message.answer("Регистрация завершена! Теперь у вас полный доступ.", reply_markup=FULL_MENU)


@dp.callback_query(lambda c: c.data == "show_profile")
async def show_profile(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_data = db_get(user_id)
    if not user_data:
        await callback_query.answer("Профиль не найден. Пройдите регистрацию.", show_alert=True)
        return

    full_name, phone, birth_date, welcomed, is_blocked = user_data
    text = (
        f"👤 Профиль\n"
        f"Имя: {full_name or 'Не указано'}\n"
        f"Телефон: {phone or 'Не указан'}\n"
        f"Дата рождения: {birth_date or 'Не указана'}\n"
        f"Статус: {'Активен' if not is_blocked else 'Заблокирован'}"
    )
    await callback_query.message.edit_text(text, reply_markup=FULL_MENU)


@dp.callback_query(lambda c: c.data == "restaurants")
async def show_restaurants(callback_query: types.CallbackQuery):
    text = "🏙️ Наши рестораны:\n\n"
    for r in RESTAURANTS:
        map_link = f"https://yandex.ru/maps/org/{r['org']}"
        text += (
            f"📍 {r['name']}\n"
            f"📍 Адрес: {r['address']}\n"
            f"⏰ Часы работы:\n{r['hours']}\n"
            f"📞 Телефон: {r['phone']}\n"
            f"🗺️ [Показать на карте]({map_link})\n\n"
        )
    await callback_query.message.edit_text(text, parse_mode="Markdown", reply_markup=FULL_MENU)


@dp.callback_query(lambda c: c.data == "standards")
async def show_standards(callback_query: types.CallbackQuery):
    await callback_query.answer("Раздел в разработке.", show_alert=True)


@dp.callback_query(lambda c: c.data == "faq")
async def show_faq(callback_query: types.CallbackQuery):
    await callback_query.answer("Раздел FAQ в разработке.", show_alert=True)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
