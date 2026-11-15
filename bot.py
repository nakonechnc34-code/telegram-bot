import os
import asyncio
import logging
from aiohttp import web

# Импортируем наши новые модули
import config
from db import init_pool, close_pool, _run, init_db_and_seed
from routes.auth import routes as auth_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Создаем приложение
app = web.Application(client_max_size=20 * 1024 * 1024)

# Подключаем роуты
app.add_routes(auth_routes)

# Простые страницы пока оставим тут (позже вынесем)
async def handle_health(request):
    return web.Response(text="OK")
app.router.add_get("/api/health", handle_health)


async def main():
    port = int(os.getenv("PORT", 8080))
    
    # Инициализация БД
    init_pool()
    if os.getenv("RUN_MIGRATIONS", "true").lower() == "true":
        # (Вызов миграций мы временно отключили или оставили в db.py)
        pass 

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    
    logging.info(f"✅ Server on port {port}")
    logging.info(f"👤 Admin: {config.ADMIN_LOGIN}")

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        close_pool()

if __name__ == "__main__":
    asyncio.run(main())
