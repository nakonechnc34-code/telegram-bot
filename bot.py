import os
import logging
from typing import Optional, Dict, Any

import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Логирование ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- Инициализация бота ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Не задан BOT_TOKEN в переменных окружения!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- Рестораны (обнови данные под свои точки) ---
RESTAURANTS: list[Dict[str, Any]] = [
    {
        "key": "mega_belaya_dacha",
        "name": "Мега Белая Дача",
        "address": "Московская область, Котельники, 1-й Покровский проезд, 5, ТРЦ Мега, этаж 1",
        "hours": "Пн–чт: 10:00–22:00\nПт–вс: 10:00–23:00",
        "lat": 55.6578,
        "lon": 37.8891,
        "phone": "+79154790941",
        "photo_url": "https://via.placeholder.com/800x400?text=Mega+Belaya+Dacha",
    },
    {
        "key": "another_restaurant",
        "name": "Другой ресторан",
        "address": "Москва, ул. Примерная, 10",
        "hours": "Ежедневно: 09:00–21:00",
        "lat": 55.7558,
        "lon": 37.6176,
        "phone": "+79991234567",
        "photo_url": None,
    },
]

# --- Клавиатуры ---
def get_restaurants_list_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for r in RESTAURANTS:
        builder.button(text=r["name"], callback_data=f"rest_info:{r['key']}")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def get_restaurant_keyboard(restaurant: dict) -> InlineKeyboardMarkup:
    buttons = []

    # Кнопка «Позвонить»
    if restaurant.get("phone"):
        phone_clean = (
            restaurant["phone"]
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )
        buttons.append(InlineKeyboardButton(text="📞 Позвонить", url=f"tel:{phone_clean}"))

    # Кнопка «Показать на карте»
    if "lat" in restaurant and "lon" in restaurant:
        yandex_url = f"https://yandex.ru/maps/?mode=search&ll={restaurant['lon']},{restaurant['lat']}&z=17"
        buttons.append(InlineKeyboardButton(text="🗺 Показать на карте", url=yandex_url))

    # Кнопка «Назад»
    buttons.append(InlineKeyboardButton(text="← Назад к списку", callback_data="restaurants_list"))

    return InlineKeyboardMarkup(inline_keyboard=[buttons])

# --- Обработчики ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    text = (
        "👋 Привет! Я бот ресторана.\n\n"
        "Выбери ресторан из списка, чтобы узнать адрес, часы работы, позвонить или посмотреть точку на карте."
    )
    await message.answer(text, reply_markup=get_restaurants_list_keyboard())

@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🏠 Главное меню\n\nВыбери ресторан:",
        reply_markup=get_restaurants_list_keyboard(),
    )
    await callback.answer()

@dp.callback_query(F.data == "restaurants_list")
async def cb_restaurants_list(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🍽 Рестораны:\nВыбери нужный:",
        reply_markup=get_restaurants_list_keyboard(),
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("rest_info:"))
async def show_restaurant_info(callback: types.CallbackQuery):
    key = callback.data.split(":")[1]
    restaurant = next((r for r in RESTAURANTS if r["key"] == key), None)
    if not restaurant:
        await callback.answer("Ресторан не найден", show_alert=True)
        return

    text = (
        f"🍽 <b>{restaurant['name']}</b>\n\n"
        f"📍 <b>Адрес:</b> {restaurant['address']}\n"
        f"⏰ <b>Часы работы:</b>\n{restaurant['hours']}\n"
    )

    if restaurant.get("photo_url"):
        await callback.message.answer_photo(
            photo=restaurant["photo_url"],
            caption=text,
            reply_markup=get_restaurant_keyboard(restaurant),
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            text=text,
            reply_markup=get_restaurant_keyboard(restaurant),
            parse_mode="HTML",
        )

    await callback.answer()

@dp.message()
async def handle_text(message: types.Message):
    if not message.text:
        return
    text_lower = message.text.lower()
    faq = {
        "доставка": "Зона доставки зависит от ресторана. Напиши название точки — подскажу детали.",
        "возврат": "Возврат оформляется через поддержку. Напиши номер заказа и проблему.",
        "часы": "Часы работы указаны в карточке каждого ресторана.",
        "адрес": "Выбери ресторан из меню — там есть адрес и кнопка «Показать на карте».",
    }
    for keyword, answer in faq.items():
        if keyword in text_lower:
            await message.answer(answer)
            return
    await message.answer("Я пока не понимаю этот вопрос. Попробуй выбрать кнопку в меню или напиши /start.")

@dp.errors()
async def global_error_handler(event, error: Exception):
    logger.exception("Глобальная ошибка обработки: %s", error)
    return True

# --- Health check (для Amvera) ---
async def health_check_handler(request):
    return web.json_response({"status": "ok", "service": "telegram-bot"})

async def on_startup(bot: Bot):
    logger.info("Бот запущен и готов к работе.")

async def on_shutdown(bot: Bot):
    await bot.session.close()
    logger.info("Бот остановлен.")

async def main():
    port = int(os.environ.get("PORT", 8080))
    app = web.Application()
    app.router.add_get("/health", health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server is LIVE on port {port}")

    await dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
