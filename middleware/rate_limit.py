"""Middleware для rate-limiting API запросов."""
from ipaddress import ip_address
import time
import logging
import threading
from aiohttp import web
import config

_request_rates = {}
_rate_lock = threading.Lock()

logger = logging.getLogger(__name__)


def get_client_ip(request):
    # remote читается из транспорта aiohttp. Заголовок проверяется только за доверенным прокси.
    try:
        peer = ip_address(request.remote or "")
    except ValueError:
        return "unknown"
    peer = getattr(peer, "ipv4_mapped", None) or peer
    if any(peer in network for network in config.TRUSTED_PROXY_NETWORKS):
        forwarded = request.headers.getall("X-Forwarded-For", [])
        if len(forwarded) == 1:
            try:
                client = ip_address(forwarded[0].rsplit(",", 1)[-1].strip())
                if getattr(client, "scope_id", None) is None:
                    return str(getattr(client, "ipv4_mapped", None) or client)
            except ValueError:
                pass
    return str(peer)

def _check_rate(ip, limit, window):
    now = time.time()
    with _rate_lock:
        timestamps = [t for t in _request_rates.get(ip, []) if now - t < window]
        if len(timestamps) >= limit:
            _request_rates[ip] = timestamps
            return False
        timestamps.append(now)
        _request_rates[ip] = timestamps

        if len(_request_rates) > 1000:
            stale_ips = [k for k, v in _request_rates.items() if not v or now - v[-1] >= window]
            for k in stale_ips:
                _request_rates.pop(k, None)
        return True


@web.middleware
async def api_rate_middleware(request, handler):
    if request.method == "GET" and request.path in ('/', '/api/health', '/favicon.ico'):
        return await handler(request)

    if request.method == "POST":
        ip = get_client_ip(request)
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
