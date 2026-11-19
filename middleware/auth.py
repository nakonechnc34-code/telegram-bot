"""Middleware для аутентификации и авторизации."""
import time
import logging
from functools import wraps
from aiohttp import web

from utils.auth_helpers import get_auth_user, get_admin_user, denied, _sync_user_has_perm

logger = logging.getLogger(__name__)


def require_auth(handler):
    """Декоратор: требует авторизации пользователя."""
    @wraps(handler)
    async def wrapper(request):
        user, err = await get_auth_user(request)
        if err:
            return denied(err)
        request['user'] = user
        return await handler(request)
    return wrapper


def require_admin(handler):
    """Декоратор: требует прав администратора."""
    @wraps(handler)
    async def wrapper(request):
        user, err = await get_admin_user(request)
        if err:
            return denied(err)
        request['user'] = user
        return await handler(request)
    return wrapper


def require_perm(perm_key):
    """Фабрика декораторов: требует конкретное право."""
    def decorator(handler):
        @wraps(handler)
        async def wrapper(request):
            user = request.get('user')
            if not user:
                return web.json_response({"error": "unauthorized"}, status=401)
            if not _sync_user_has_perm(user, perm_key):
                return web.json_response({"error": "forbidden"}, status=403)
            return await handler(request)
        return wrapper
    return decorator


def require_super_admin(handler):
    """Декоратор: требует super_admin прав."""
    @wraps(handler)
    async def wrapper(request):
        user = request.get('user')
        if not user:
            return web.json_response({"error": "unauthorized"}, status=401)
        if not user.get("is_super_admin"):
            return web.json_response({"error": "forbidden"}, status=403)
        return await handler(request)
    return wrapper
