"""Middleware для rate-limiting API запросов."""
import time
import logging
from aiohttp import web
import config

_request_rates = {}
_rate_lock = __import__('threading').Lock()

logger = logging.getLogger(__name__)


def _check_rate(ip, limit, window):
    """Проверяет rate limit для IP. Возвращает True если разрешено."""
    now = time.time()
    with _rate_lock:
        if ip not in _request_rates:
            _request_rates[ip] = []
        # Очищаем старые записи
        _request_rates[ip] = [t for t in _request_rates[ip] if now - t < window]
        if len(_request_rates[ip]) >= limit:
            return False
        _request_rates[ip].append(now)
        return True


async def api_rate_middleware(request, handler):
    """Middleware: ограничивает количество POST-запросов с одного IP."""
    # Пропускаем health-check и статические роуты
    if request.method == "GET" and request.path in ('/', '/api/health', '/favicon.ico'):
        return await handler(request)

    if request.method == "POST":
        ip = request.remote or "unknown"
        limit = config.API_RATE_LIMIT_PER_MINUTE
        window = 60  # 1 минута

        if not _check_rate(ip, limit, window):
            logger.warning(f"Rate limit exceeded for {ip} on {request.path}")
            return web.json_response(
                {"error": "too_many_requests"},
                status=429,
                headers={"Retry-After": "60"}
            )

    return await handler(request)
