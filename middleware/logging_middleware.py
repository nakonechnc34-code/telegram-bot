"""Middleware для логирования запросов."""
import time
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

async def request_logging_middleware(request, handler):
    """Middleware: логирует каждый HTTP запрос."""
    start = time.time()
    response = None
    status = '?'
    
    try:
        response = await handler(request)
        status = response.status
        return response
    except Exception as e:
        # Если хэндлер упал, ставим 500 и пробрасываем ошибку в error_middleware
        status = 500
        raise e
    finally:
        duration = time.time() - start
        path = request.path
        
        # Пропускаем логирование статики
        if not (path.startswith('/static/') or path in ('/favicon.ico', '/.well-known/assetlinks.json')):
            user = request.get('user')
            user_id = user.get('user_id', '-') if user else '-'
            
            logger.info(
                "%s %-8s %-40s %s %.3fs user=%s",
                request.remote or '-',
                request.method,
                path,
                status,
                duration,
                user_id
            )
