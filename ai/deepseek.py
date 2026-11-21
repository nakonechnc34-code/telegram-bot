"""Клиент для API DeepSeek через aiohttp."""

import asyncio
import logging
import aiohttp
import config

logger = logging.getLogger(__name__)

# Короткие системные промпты для экономии токенов
_SYSTEM_PROMPTS = {
    "default": (
        "Ты — ассистент Wokker. Отвечай кратко и по делу на русском языке. "
        "Если вопрос не относится к работе, общепитам или компании — скажи: "
        "\"Я помогаю с вопросами по работе и компании. Спроси что-нибудь связанное с обязанностями, стандартами или обучением.\""
    ),
    "faq": (
        "Ты — корпоративный помощник Wokker. Отвечай строго на основе предоставленного контекста. "
        "Если ответа нет в контексте — скажи: \"У меня нет точного ответа на этот вопрос. Обратитесь к администратору.\""
        "Отвечай кратко, на русском языке."
    ),
}


async def chat_completion(
    user_message: str,
    conversation_history: list[dict] | None = None,
    system_prompt: str = "default",
    temperature: float = 0.7,
    max_tokens: int = 500,
) -> tuple[str, float]:
    """
    Отправляет сообщение в DeepSeek и получает ответ.

    Args:
        user_message: Текст от пользователя.
        conversation_history: Список сообщений [("user", "..."), ("assistant", "..."), ...].
        system_prompt: Ключ системного промпта ("default", "faq" или произвольный текст).
        temperature: Креативность (0.0–2.0).
        max_tokens: Максимум токенов в ответе.

    Returns:
        Tuple of (ответ_бота, затраченные_токены).
    """
    if not config.ENABLE_AI:
        raise RuntimeError("DeepSeek API не настроен. Проверьте DEEPSEEK_API_KEY.")

    # Формируем системный промпт
    if system_prompt in _SYSTEM_PROMPTS:
        sys_prompt = _SYSTEM_PROMPTS[system_prompt]
    else:
        sys_prompt = system_prompt

    # Собираем сообщения
    messages: list[dict] = [{"role": "system", "content": sys_prompt}]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    url = f"{config.DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    error_body = await resp.text()
                    logger.error("DeepSeek API error %d: %s", resp.status, error_body[:500])
                    raise RuntimeError(f"DeepSeek API error {resp.status}: {error_body[:200]}")

                data = await resp.json()

                # Извлекаем ответ
                assistant_msg = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                tokens_used = usage.get("total_tokens", 0)

                logger.info("DeepSeek: %d input_tokens, %d output_tokens", usage.get("prompt_tokens", 0), tokens_used)
                return assistant_msg, float(tokens_used)

    except asyncio.TimeoutError:
        logger.error("DeepSeek API timeout")
        raise RuntimeError("Сервис ответа недоступен. Попробуйте позже.")
    except aiohttp.ClientError as e:
        logger.error("DeepSeek API connection error: %s", e)
        raise RuntimeError("Ошибка подключения к AI-сервису.")
    except (KeyError, IndexError) as e:
        logger.error("DeepSeek API unexpected response format: %s", e)
        raise RuntimeError("Ошибка обработки ответа от AI.")
