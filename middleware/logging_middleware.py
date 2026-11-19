"""Middleware для логирования запросов."""
import time
import logging
from aiohttp import web

logger = logging.getLogger(__name__)


async def request_logging_middleware(request, handler):
    """Middleware: логирует каждый HTTP запрос."""
    start = time.time()
    try:
        response = await handler(request)
        return response
    finally:
        duration = time.time() - start
        method = request.method
        path = request.path
        # Для GET роутов не логируем статику
        if path.startswith('/static/') or path in ('/favicon.ico', '/.well-known/assetlinks.json'):
            return
        # Логируем с информацией о пользователе если есть
        user_id = request.get('user', {}).get('user_id', '-') if 'user' in request else '-'
        logger.info(
            "%s %-8s %-40s %d %.3fs user=%s",
            request.remote or '-',
            method,
            path,
            response.status if hasattr(response, 'status') else '?',
            duration,
            user_id
        )
