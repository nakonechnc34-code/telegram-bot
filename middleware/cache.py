"""Встроенный кэш для справочных данных."""
import time
import logging
from aiohttp import web
import config

_cache = {}
_cache_lock = __import__('threading').Lock()

logger = logging.getLogger(__name__)


def get_cached(key):
    """Получает значение из кэша если оно свежее."""
    with _cache_lock:
        if key in _cache:
            entry = _cache[key]
            now = time.time()
            if now - entry['created'] < entry['ttl']:
                return entry['data']
            # Кэш истёк — удаляем
            _cache.pop(key, None)
    return None


def set_cached(key, data, ttl):
    """Сохраняет значение в кэш."""
    with _cache_lock:
        _cache[key] = {
            'data': data,
            'ttl': ttl,
            'created': time.time()
        }


def clear_cache(key=None):
    """Очищает кэш (частично или полностью)."""
    with _cache_lock:
        if key:
            _cache.pop(key, None)
            logger.info(f"🧹 Cache cleared: {key}")
        else:
            count = len(_cache)
            _cache.clear()
            logger.info(f"🧹 Cache cleared: {count} entries")


async def health_cache_status(request):
    """Debug endpoint: показывает состояние кэша."""
    with _cache_lock:
        entries = []
        now = time.time()
        for key, entry in _cache.items():
            age = int(now - entry['created'])
            ttl = entry['ttl']
            status = 'ok' if age < ttl else 'expired'
            entries.append({'key': key, 'age': f'{age}s', 'ttl': f'{ttl}s', 'status': status})
    return web.json_response({'cache_entries': entries})
