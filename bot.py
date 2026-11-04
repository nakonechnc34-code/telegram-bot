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

class Registration(StatesGroup):
    full_name = State()
    phone = State()
    birth_date = State()

# Хранилище анкет (в памяти: при перезапуске очищается)
users = {}
# Хранилище тех, кто уже видел приветствие
seen_welcome = set()

@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    current_state = await state.get_state()

    # Если пользователь в процессе регистрации — не сбрасываем состояние и не показываем меню.
    # Вместо этого показываем подсказку для текущего шага.
    if current_state:
        if current_state == Registration.full_name.state:
            await message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")
            return
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
            return
        elif current_state == Registration.birth_date.state:
            await message.answer(
                "Шаг 3 из 3.\nНапиши дату рождения в формате ДД.ММ.ГГГГ (например: 01.01.2000)",
                reply_markup=ReplyKeyboardRemove()
            )
            return

    # Если не в регистрации — обычная логика: приветствие 1 раз, потом меню
    await state.clear()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✍️ Зарегистрироваться", callback_data="register"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="show_profile"),
        ],
        [
            InlineKeyboardButton(text="🏙️ Наши рестораны", callback_data="restaurants"),
            InlineKeyboardButton(text="📚 Библиотека стандартов", callback_data="standards"),
        ],
        [
            InlineKeyboardButton(text="❓ Вопрос/ответ", callback_data="faq"),
        ]
    ])

    if user_id not in seen_welcome:
        seen_welcome.add(user_id)
        await message.answer(
            f"👋 {message.from_user.first_name}, добро пожаловать в Wokker!\n\n"
            "Мы готовим паназиатские блюда на воке — быстро и со вкусом.\n"
            "Нажми кнопку, чтобы продолжить."
        )
        await message.answer("Что хочешь сделать?", reply_markup=keyboard)
    else:
        await message.answer("Выбери действие:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "register")
async def start_registration(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(Registration.full_name)
    await callback.message.answer("Шаг 1 из 3.\nНапиши своё ФИО (например: Иванов Иван Иванович)")

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
            "Нажми «✍️ Зарегистрироваться» или напиши /start и выбери эту кнопку."
        )

# --- Новые кнопки: заглушки (можно позже заменить на реальную логику) ---

@dp.callback_query(lambda c: c.data == "restaurants")
async def show_restaurants(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "🏙️ Наши рестораны\n\n"
        "Скоро здесь появится список адресов, часы работы и карта.\n"
        "А пока загляни в профиль или зарегистрируйся!"
    )

@dp.callback_query(lambda c: c.data == "standards")
async def show_standards(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "📚 Библиотека стандартов\n\n"
        "Здесь будут инструкции, чек-листы и стандарты качества Wokker.\n"
        "Функционал в разработке — скоро всё появится!"
    )

@dp.callback_query(lambda c: c.data == "faq")
async def show_faq(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "❓ Вопрос/ответ\n\n"
        "Частые вопросы и ответы по работе с ботом и ресторанами.\n"
        "Раздел готовится к запуску — спасибо за терпение!"
    )
# --------------------------------------------------------------------

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

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())



