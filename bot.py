import asyncio
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Токен берём из переменных окружения — НЕ вставляем в код!
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("Переменная BOT_TOKEN не задана! Добавь её в настройках хостинга.")

bot = Bot(token=TOKEN)
dp = Dispatcher()

keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Нажми меня!", callback_data="pressed")]
])

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я твой бот. Я уже работаю!", reply_markup=keyboard)

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Я умею:\n"
        "— отвечать на /start\n"
        "— показывать эту справку (/help)\n"
        "— повторять то, что ты пишешь\n"
        "— реагировать на кнопку 🙂"
    )

@dp.callback_query(lambda c: c.data == "pressed")
async def process_callback(callback_query: types.CallbackQuery):
    await callback_query.answer("Ты нажал кнопку! 🎉")

@dp.message()
async def echo_handler(message: types.Message):
    if message.text:
        await message.answer(f"Ты написал: {message.text}")

# ------- Хитрость против «засыпания»: маленький веб-сервер -------
class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"I am alive")

    def log_message(self, *args):
        pass  # чтобы логи не засорялись

def run_http():
    port = int(os.getenv("PORT", 10000))  # Render подставляет свой PORT
    HTTPServer(("0.0.0.0", port), PingHandler).serve_forever()

threading.Thread(target=run_http, daemon=True).start()
# -------------------------------------------------------------------

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())  # на сервере — asyncio.run, а не await
