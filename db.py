# db.py
import asyncio
import logging
import threading
from contextlib import contextmanager
from psycopg2.pool import ThreadedConnectionPool
from config import DB_URL

_pool = None
_pool_lock = threading.Lock()

_async_pool = None
_async_pool_lock = asyncio.Lock()


def init_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(2, 20, DB_URL)


@contextmanager
def get_conn():
    init_pool()
    conn = _pool.getconn()
    try:
        with conn:
            yield conn
    finally:
        _pool.putconn(conn)


async def _run(fn, *args):
    """Запускает синхронную функцию (работу с БД) в отдельном потоке."""
    return await asyncio.to_thread(fn, *args)


# ============= ASYNCPG POOL (для sales.py) =============
async def init_async_pool():
    global _async_pool
    if _async_pool is None:
        async with _async_pool_lock:
            if _async_pool is None:
                import asyncpg
                _async_pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
                logging.info("✅ asyncpg pool initialized")


def get_pool(app=None):
    """Возвращает asyncpg-пул. Параметр app — для совместимости."""
    return _async_pool


async def close_async_pool():
    global _async_pool
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None


def _run_migration(sql_query, label):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_query)
        return True
    except Exception as e:
        logging.error(f"Миграция '{label}': {type(e).__name__}: {str(e)[:150]}")
        return False


def close_pool():
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
