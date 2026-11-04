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
    
    # Кнопки: регистрация и профиль
    keyboard = InlineKeyboardMarkup(inline_keyboard=[

