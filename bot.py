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

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# --- Токен бота ---
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    print("❌ ОШИБКА: Переменная BOT_TOKEN не задана!")
    raise ValueError("BOT_TOKEN is not set")

# --- ID администратора (кому слать уведомления) ---
ADMIN_ID = os.getenv("ADMIN_ID")
if not ADMIN_ID:
    print("⚠️ ПРЕДУПРЕЖДЕНИЕ: Переменная ADMIN_ID не задана — уведомления о регистрации отключены.")
    ADMIN_ID = None
else:
    ADMIN_ID = int(ADMIN_ID)

# --- Подключение к базе (Supabase) ---
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("❌ ОШИБКА: Переменная DATABASE_URL не задана!")
    raise ValueError("DATABASE_URL is not set")

def get_conn():
    return psycopg2.connect(DB_URL)

# Создаём таблицу при старте, если её ещё нет
with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                birth_date TEXT,
                welcomed BOOLEAN DEFAULT FALSE
            )
        """)
    conn.commit()
print("🗄️ База данных подключена, таблица готова.")

def db_get(user_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT full_name, phone, birth_date, welcomed FROM users WHERE user_id = %s",
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

# --- Бот и диспетчер ---
bot = Bot(token=TOKEN)
dp = Dispatcher()

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
    """Собирает красивый текст профиля из строки базы.
    row — кортеж: (full_name, phone, birth_date, welcomed)"""
    full_name, phone, birth_date = row[0], row[1], row[2]
    return (
        "Твой профиль:\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}"
    )

async def notify_admin_about_registration(user: types.User, full_name: str, phone: str, birth_date: str):
    """Отправляет админу уведомление о новой регистрации."""
    if not ADMIN_ID:
        return
    username = f"@{user.username}" if user.username else "нет username"
    text = (
        "🔔 Новая регистрация!\n\n"
        f"👤 ФИО: {full_name}\n"
        f"📞 Телефон: {phone}\n"
        f"🎂 Дата рождения: {birth_date}\n"
        f"🆔 Telegram ID: <code>{user.id}</code>\n"
        f"🔗 Username: {username}\n"
        f"🕐 Время: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    try:
        await bot.send_message(ADMIN_ID, text, parse_mode="HTML")
        print(f"📨 Уведомление о регистрации отправлено админу ({user.id})")
    except Exception as e:
        # Не роняем бота, если уведомление не ушло
        print(f"⚠️ Не удалось отправить уведомление админу: {e}")

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    current_state = await state.get_state()

    # Если пользователь в середине регистрации — подсказываем, на каком он шаге
    if current_state:
        if current_state == Registration.full_name.state:
            await message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")
        elif current_state == Registration.phone.state:
            await message.answer("Шаг 2 из 3.\nОтправь свой номер телефона — можно кнопкой ниже.", reply_markup=phone_kb())
        elif current_state == Registration.birth_date.state:
            await message.answer("Шаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)", reply_markup=ReplyKeyboardRemove())
        return

    await state.clear()
    row = db_get(user_id)

    # Уже зарегистрирован (ФИО заполнено) — сразу полное меню
    if row and row[0]:
        await message.answer("Выбери действие:", reply_markup=FULL_MENU)
        return

    # Был в боте, но регистрацию не завершил
    if row and row[3]:
        await message.answer("Сначала заверши регистрацию 👇", reply_markup=REGISTER_ONLY)
        return

    # Первый визит
    db_set_welcomed(user_id)
    await message.answer(
        f"👋 {message.from_user.first_name}, добро пожаловать в Wokker!\n\n"
        "Мы готовим паназиатские блюда на воке — быстро и со вкусом.\n"
        "Для начала зарегистрируйся 👇"
    )
    await message.answer("Что хочешь сделать? Пока доступна только регистрация.", reply_markup=REGISTER_ONLY)

@dp.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Registration.full_name)
    await callback.message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")

@dp.callback_query(lambda c: c.data == "show_profile")
async def show_profile_callback(callback: types.CallbackQuery):
    await callback.answer()
    row = db_get(callback.from_user.id)
    if row and row[0]:
        await callback.message.answer(profile_text(row))
    else:
        await callback.message.answer("Ты ещё не зарегистрирован.\nНажми /start и «✍️ Зарегистрироваться».")

@dp.callback_query(lambda c: c.data == "restaurants")
async def show_restaurants(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("🏙️ Наши рестораны\n\nСкоро здесь появится список адресов, часы работы и карта.")

@dp.callback_query(lambda c: c.data == "standards")
async def show_standards(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("📚 Библиотека стандартов\n\nЗдесь будут инструкции, чек-листы и стандарты качества Wokker.")

@dp.callback_query(lambda c: c.data == "faq")
async def show_faq(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("❓ Вопрос/ответ\n\nЧастые вопросы и ответы по работе с ботом и ресторанами.")

@dp.message(Registration.full_name)
async def process_name(message: types.Message, state: FSMContext):
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

    # Уведомляем админа о новой регистрации
    await notify_admin_about_registration(
        message.from_user, full_name, phone, birth_date.strftime("%d.%m.%Y")
    )

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    row = db_get(message.from_user.id)
    if row and row[0]:
        await message.answer(profile_text(row))
    else:
        await message.answer("Ты ещё не зарегистрирован. Напиши /start и нажми «✍️ Зарегистрироваться».")

# --- HTTP-сервер для Render (health check) ---
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
    print(f"✅ Health Check server is LIVE on port {port}")
    return runner

async def main():
    runner = await health_check_server()
    print("📦 STARTING BOT SCRIPT...")
    bot_task = asyncio.create_task(dp.start_polling(bot))
    print("🚀 Bot polling started. Waiting for updates...")
    try:
        await asyncio.gather(bot_task)
    finally:
        await runner.cleanup()
        await bot.session.close()

if __name__ == '__main__':
    asyncio.run(main())
