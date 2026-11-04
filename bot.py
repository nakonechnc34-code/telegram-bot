import asyncio
import os
import threading
from datetime import datetime
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
    ReplyKeyboardRemove,
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

# Хранилище анкет (в памяти: при перезапуске очищается)
users = {}

# --- Приветствие при /start ---
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✍️ Зарегистрироваться", callback_data="register"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile"),
        ]
    ])

    await message.answer(
        f"Привет, {message.from_user.first_name}! 👋\n\n"
        "Я твой бот. Чтобы пользоваться всеми функциями, пройди короткую регистрацию.\n"
        "Или сразу посмотри свой профиль, если уже регистрировался.\n\n"
        "Выбери действие:"
    )
    await message.answer("Меню:", reply_markup=keyboard)

# --- Начало регистрации по кнопке ---
@dp.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Registration.full_name)
    await callback.message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")

# --- Показать профиль по кнопке ---
@dp.callback_query(lambda c: c.data == "show_profile")
async def show_profile_callback(callback: types.CallbackQuery):
    await callback.answer()
    data = users.get(callback.from_user.id)
    if data:
        await callback.message.answer(
            "Твой профиль:\n\n"
            f"👤 ФИО: {data['full_name']}\n"
            f"📞 Телефон: {data['phone']}\n"
            f"🎂 Дата рождения: {data['birth_date']}"
        )
    else:
        await callback.message.answer(
            "Ты ещё не зарегистрирован.\n"
            "Напиши /start и нажми «✍️ Зарегистрироваться»."
        )

# --- Ввод ФИО ---
@dp.message(Registration.full_name)
async def process_name(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Напиши ФИО именно текстом 🙂")
        return
    name = message.text.strip()
    if len(name.split()) < 2:
        await message.answer("Похоже, этого мало 🙂 Напиши хотя бы имя и фамилию через пробел.")
        return
    await state.update_data(full_name=name)

    # Запрос контакта работает ТОЛЬКО через обычную клавиатуру
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
    # Убираем клавиатуру с кнопкой контакта
    await message.answer(
        "Отлично, номер получен ✅\nШаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
        reply_markup=ReplyKeyboardRemove()
    )

# --- Ввод телефона текстом ---
@dp.message(Registration.phone)
async def process_phone_text(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Отправь номер текстом или кнопкой 🙂")
        return
    digits = message.text.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or len(digits) < 10:
        await message.answer("Это не похоже на номер. Попробуй ещё раз, например: +79001234567")
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(Registration.birth_date)
    await message.answer(
        "Номер записал ✅\nШаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
        reply_markup=ReplyKeyboardRemove()
    )

# --- Ввод даты рождения и финал ---
@dp.message(Registration.birth_date)
async def process_birth_date(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Напиши дату именно текстом 🙂")
        return
    try:
        birth_date = datetime.strptime(message.text.strip(), "%d.%m.%Y").date()
        if birth_date.year < 1900 or birth_date > datetime.now().date():
            raise ValueError
    except ValueError:
        await message.answer("Такой даты не бывает 🙂 Проверь и напиши ещё раз: ДД.ММ.ГГГГ")
        return

    data = await state.update_data(birth_date=birth_date.strftime("%d.%m.%Y"))
    users[message.from_user.id] = data
    await state.clear()

    await message.answer(
        "Регистрация завершена! 🎉\n\n"
        f"👤 ФИО: {data['full_name']}\n"
        f"📞 Телефон: {data['phone']}\n"
        f"🎂 Дата рождения: {data['birth_date']}\n\n"
        "Теперь можешь в любой момент открыть меню (/start) и нажать «👤 Профиль»."
    )

# --- Команда /profile ---
@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    data = users.get(message.from_user.id)
    if data:
        await message.answer(
            f"Твой профиль:\n\n"
            f"👤 ФИО: {data['full_name']}\n"
            f"📞 Телефон: {data['phone']}\n"
            f"🎂 Дата рождения: {data['birth_date']}"
        )
    else:
        await message.answer("Ты ещё не зарегистрирован. Напиши /start и нажми «✍️ Зарегистрироваться».")

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


