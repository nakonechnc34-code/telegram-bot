"""Роуты для AI-чата через DeepSeek."""

import logging
from aiohttp import web

import config
from ai.deepseek import chat_completion

logger = logging.getLogger(__name__)

# Простая in-memory история для каждого пользователя (в prod — Redis/DB)
_conversation_histories: dict[int, list[dict]] = {}


def _get_history(user_id: int, max_messages: int = 10) -> list[dict]:
    """Возвращает историю сообщений пользователя."""
    return _conversation_histories.get(user_id, [])[-max_messages:]


def _add_to_history(user_id: int, role: str, content: str) -> None:
    """Добавляет сообщение в историю пользователя."""
    if user_id not in _conversation_histories:
        _conversation_histories[user_id] = []
    _conversation_histories[user_id].append({"role": role, "content": content})
    # Ограничиваем размер истории
    if len(_conversation_histories[user_id]) > 20:
        _conversation_histories[user_id] = _conversation_histories[user_id][-20:]


def _clear_history(user_id: int) -> None:
    """Очищает историю пользователя."""
    _conversation_histories.pop(user_id, None)


@web.json_response
async def ai_chat(request: web.Request) -> web.Response:
    """
    POST /api/ai/chat
    body: {"message": "Привет", "mode": "default", "clear": false}
    """
    if not config.ENABLE_AI:
        return web.json_response(
            {"error": "AI-сервис не настроен"},
            status=503,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    user_message = body.get("message", "").strip()
    if not user_message:
        return web.json_response({"error": "Сообщение не может быть пустым"}, status=400)

    # Получаем user_id из сессии
    user = request.get("user", {})
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    user_id = user.get("user_id")
    mode = body.get("mode", "default")  # "default" или "faq"
    clear = body.get("clear", False)

    # Очистка истории по запросу
    if clear:
        _clear_history(user_id)

    # Получаем историю
    history = _get_history(user_id)

    try:
        response_text, tokens_used = await chat_completion(
            user_message=user_message,
            conversation_history=history,
            system_prompt=mode,
            temperature=0.7,
            max_tokens=500,
        )

        # Добавляем в историю
        _add_to_history(user_id, "user", user_message)
        _add_to_history(user_id, "assistant", response_text)

        return web.json_response({
            "response": response_text,
            "tokens_used": round(tokens_used, 2),
        })

    except RuntimeError as e:
        logger.warning("AI chat error for user %d: %s", user_id, e)
        return web.json_response({"error": str(e)}, status=500)
    except Exception:
        logger.exception("AI chat unexpected error for user %d", user_id)
        return web.json_response({"error": "Внутренняя ошибка AI-сервиса"}, status=500)


@web.json_response
async def ai_history(request: web.Request) -> web.Response:
    """
    GET /api/ai/history
    """
    user = request.get("user", {})
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    user_id = user.get("user_id")
    history = _get_history(user_id)

    return web.json_response({"history": history})


@web.json_response
async def ai_clear_history(request: web.Request) -> web.Response:
    """
    POST /api/ai/clear
    """
    user = request.get("user", {})
    if not user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    user_id = user.get("user_id")
    _clear_history(user_id)

    return web.json_response({"status": "cleared"})


# ============= РОУТЫ =============
routes = web.RouteTableDef()

@routes.post("/api/ai/chat")
async def ai_chat_route(request):
    return await ai_chat(request)

@routes.get("/api/ai/history")
async def ai_history_route(request):
    return await ai_history(request)

@routes.post("/api/ai/clear")
async def ai_clear_route(request):
    return await ai_clear_history(request)
