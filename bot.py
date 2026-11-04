import asyncio
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Переменная BOT_TOKEN не задана! Добавь её в настройках хостинга.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Шаги регистрации ---
class Registration(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()

# Сюда сохраняем анкеты (в памяти: при перезапуске очищается)
users = {}

# --- Приветствие при /start ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я твой бот. Чтобы ты мог пользоваться мной на полную, "
        "давай познакомимся — пройди короткую регистрацию.\n\n"
        "Нажми кнопку ниже, чтобы начать 👇"
    )
    await message.answer(
        "Регистрация",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Зарегистрироваться", callback_data="register")]
        ])
    )

# --- Начало регистрации по кнопке ---
@dp.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Registration.full_name)
    await callback.message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")

# --- Ввод ФИО ---
@dp.message(Registration.full_name)
async def process_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name.split()) < 2:
        await message.answer("Похоже, этого мало 🙂 Напиши хотя бы имя и фамилию через пробел.")
        return
    await state.update_data(full_name=name)
    # Кнопка «поделиться телефоном» — Telegram сам передаст номер
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

# --- Ввод телефона (кнопкой) ---
@dp.message(Registration.phone, lambda m: m.contact is not None)
async def process_phone_button(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Registration.birth_date)
    await message.answer(
        "Отлично, номер получен ✅\nШаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)"
    )

# --- Ввод телефона текстом ---
@dp.message(Registration.phone)
async def process_phone_text(message: types.Message, state: FSMContext):
    digits = message.text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or len(digits) < 10:
        await message.answer("Это не похоже на номер. Попробуй ещё раз, например: +79001234567")
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(Registration.birth_date)
    await message.answer(
        "Номер записал ✅\nШаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)"
    )

# --- Ввод даты рождения и финал ---
@dp.message(Registration.birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    parts = message.text.strip().split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts) or len(parts[2]) != 4:
        await message.answer("Не понял дату 🤔 Напиши в формате ДД.ММ.ГГГГ, например: 01.01.2000")
        return
    day, month, year = map(int, parts)
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2026):
        await message.answer("Такой даты не бывает 🙂 Проверь и напиши ещё раз: ДД.ММ.ГГГГ")
        return

    data = await state.update_data(birth_date=message.text.strip())
    users[message.from_user.id] = data
    await state.clear()

    await message.answer(
        "Регистрация завершена! 🎉\n\n"
        f"👤 ФИО: {data['full_name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"🎂 Дата рождения: {data['birth_date']}\n\n"
        "Если что-то указал неверно — напиши /start и пройдём регистрацию заново."
    )

# --- Помощь ---
@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Я умею:\n"
        "— /start — приветствие и регистрация\n"
        "— /help — эта справка\n"
        "— /profile — показать твою анкету (если зарегистрирован)"
    )

# --- Показать анкету ---
@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    data = users.get(message.from_user.id)
    if data:
        await message.answer(
            f"Твоя анкета:\n\n"
            f"👤 ФИО: {data['full_name']}\n"
            f"📞 Телефон: {data['phone']}\n"
            f"🎂 Дата рождения: {data['birth_date']}"
        )
    else:
        await message.answer("Ты ещё не зарегистрирован. Напиши /start, чтобы исправить это 🙂")

# --- Веб-сервер от «засыпания» (не трогаем) ---
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"I am alive")

    def log_message(self, *args):
        pass

def run_http():
    port = int(os.getenv("PORT", 10000))
    HTTPServer(("0.0.0.0", port), PingHandler).serve_forever()

threading.Thread(target=run_http, daemon=True).start()

# --- Запуск ---
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
