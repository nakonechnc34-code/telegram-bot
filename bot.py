import asyncio
import os
import sqlite3
import threading
import http.server
import socketserver
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
    ReplyKeyboardRemove,
)

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Переменная BOT_TOKEN не задана! Добавь её в настройках хостинга.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- База данных SQLite ---
DB_PATH = "wokker.db"
db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        full_name TEXT,
        phone TEXT,
        birth_date TEXT,
        welcomed INTEGER DEFAULT 0
    )
""")
db.commit()

def db_get(user_id: int):
    cur = db.execute("SELECT full_name, phone, birth_date, welcomed FROM users WHERE user_id = ?", (user_id,))
    return cur.fetchone()

def db_set_welcomed(user_id: int):
    db.execute("INSERT INTO users (user_id, welcomed) VALUES (?, 1) ON CONFLICT(user_id) DO UPDATE SET welcomed = 1", (user_id,))
    db.commit()

def db_save_profile(user_id: int, full_name: str, phone: str, birth_date: str):
    db.execute(
        "INSERT INTO users (user_id, full_name, phone, birth_date, welcomed) VALUES (?, ?, ?, ?, 1) "
        "ON CONFLICT(user_id) DO UPDATE SET full_name = ?, phone = ?, birth_date = ?, welcomed = 1",
        (user_id, full_name, phone, birth_date, full_name, phone, birth_date)
    )
    db.commit()

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
    current_state = await state.get_state()

    if current_state:
        if current_state == Registration.full_name.state:
            await message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")
        elif current_state == Registration.phone.state:
            phone_kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            )
            await message.answer(
                "Шаг 2 из 3.\nОтправь свой номер телефона — можно кнопкой ниже.",
                reply_markup=phone_kb
            )
        elif current_state == Registration.birth_date.state:
            await message.answer(
                "Шаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
                reply_markup=ReplyKeyboardRemove()
            )
        return

    await state.clear()
    row = db_get(user_id)

    if row and row:
        await message.answer("Выбери действие:", reply_markup=FULL_MENU)
        return

    if row and row: [3](https://web.learnmodernpython.com/build-a-service-health-checker-python-requests-and-apscheduler/)
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
    await callback.answer()
    await state.set_state(Registration.full_name)
    await callback.message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")

@dp.callback_query(lambda c: c.data == "show_profile")
async def show_profile_callback(callback: types.CallbackQuery):
    await callback.answer()
    row = db_get(callback.from_user.id)
    if row and row:
        await callback.message.answer(
            "Твой профиль:\n\n"
            f"👤 ФИО: {row}\n"
            f"📞 Телефон: {row}\n" [1](https://render.com/docs/troubleshooting-deploys)
            f"🎂 Дата рождения: {row}" [2](https://us-pycon-2019-tutorial.readthedocs.io/aiohttp_server.html)
        )
    else:
        await callback.message.answer("Ты ещё не зарегистрирован.\nНажми «✍️ Зарегистрироваться».")

@dp.callback_query(lambda c: c.data == "restaurants")
async def show_restaurants(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "🏙️ Наши рестораны\n\n"
        "Скоро здесь появится список адресов, часы работы и карта."
    )

@dp.callback_query(lambda c: c.data == "standards")
async def show_standards(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "📚 Библиотека стандартов\n\n"
        "Здесь будут инструкции, чек-листы и стандарты качества Wokker."
    )

@dp.callback_query(lambda c: c.data == "faq")
async def show_faq(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "❓ Вопрос/ответ\n\n"
        "Частые вопросы и ответы по работе с ботом и ресторанами."
    )

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

    phone_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await state.set_state(Registration.phone)
    await message.answer(
        "Шаг 2 из 3.\nОтправь свой номер телефона — можно кнопкой ниже.",
        reply_markup=phone_kb
    )

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

# --- БЛОК ДЛЯ RENDER (ВЕБ-СЕРВЕР) ---

def run_http_server(port):
    """Запускает простой HTTP сервер, который отвечает 'OK' на любой запрос."""
    class HealthHandler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        
        def log_message(self, format, *args):
            # Отключаем спам в логах от самого сервера, чтобы не засорять
            pass

    with socketserver.TCPServer(("0.0.0.0", port), HealthHandler) as httpd:
        print(f"✅ Health Check server started on port {port}")
        httpd.serve_forever()

async def main():
    # 1. Сначала запускаем веб-сервер в отдельном потоке
    # Render должен увидеть, что порт занят, ДО того как начнет проверять health check
    port = int(os.getenv("PORT", 10000))
    server_thread = threading.Thread(target=run_http_server, args=(port,), daemon=True)
    server_thread.start()
    
    # Небольшая пауза, чтобы сервер точно успел стартовать (на Render это критично)
    await asyncio.sleep(2)
    
    # 2. Запускаем бота
    print("🚀 Starting bot polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
