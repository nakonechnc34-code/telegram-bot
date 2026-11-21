"""Middleware для rate-limiting API запросов."""
import os
import time
import logging
import threading
from aiohttp import web
import config

_request_rates = {}
_rate_lock = threading.Lock()

logger = logging.getLogger(__name__)


def _get_client_ip(request):
    if os.getenv("TRUST_PROXY", "").lower() in ("1", "true", "yes"):
        xff = request.headers.get("X-Forwarded-For", "").strip()
        if xff:
            first_ip = xff.split(",")[0].strip()
            if first_ip:
                return first_ip
    return request.remote or "unknown"


def _check_rate(ip, limit, window):
    """Проверяет rate limit для IP. Возвращает True если разрешено."""
    now = time.time()
    with _rate_lock:
        timestamps = [t for t in _request_rates.get(ip, []) if now - t < window]
        if len(timestamps) >= limit:
            _request_rates[ip] = timestamps
            return False
        timestamps.append(now)
        _request_rates[ip] = timestamps

        # Периодически удаляем пустые списки неактивных IP
        if len(_request_rates) > 1000:
            stale_ips = [k for k, v in _request_rates.items() if not v or now - v[-1] >= window]
            for k in stale_ips:
                _request_rates.pop(k, None)
        return True


@web.middleware
async def api_rate_middleware(request, handler):
    """Middleware: ограничивает количество POST-запросов с одного IP."""
    if request.method == "GET" and request.path in ('/', '/api/health', '/favicon.ico'):
        return await handler(request)

    if request.method == "POST":
        ip = _get_client_ip(request)
        limit = config.API_RATE_LIMIT_PER_MINUTE
        window = 60

        if not _check_rate(ip, limit, window):
            logger.warning(f"Rate limit exceeded for {ip} on {request.path}")
            return web.json_response(
                {"error": "too_many_requests"},
                status=429,
                headers={"Retry-After": "60"}
            )

    return await handler(request)
