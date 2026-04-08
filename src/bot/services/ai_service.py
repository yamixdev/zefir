import asyncio
import logging
from typing import AsyncGenerator

import openai

from bot.config import config

logger = logging.getLogger(__name__)

_client: openai.AsyncOpenAI | None = None


def _get_client() -> openai.AsyncOpenAI:
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(
            api_key=config.yandex_gpt_api_key,
            base_url=config.yandex_gpt_base_url,
            project=config.yandex_gpt_project,
        )
    return _client


async def summarize_ticket(message: str) -> str:
    """Ask AI to briefly interpret a user's message for the admin."""
    try:
        client = _get_client()
        response = await client.responses.create(
            prompt={"id": config.yandex_gpt_prompt_id},
            input=(
                f"Пользователь написал сообщение админу. "
                f"Кратко (1-2 предложения) интерпретируй, что он хочет. "
                f"Отвечай от третьего лица.\n\n"
                f"Сообщение: {message}"
            ),
        )
        return response.output_text.strip()
    except Exception as e:
        logger.error("AI summarize error: %s", e)
        return ""


async def chat_stream(history: list[dict], user_message: str) -> AsyncGenerator[str, None]:
    """Stream a response from Zefir (AI cat). Yields accumulated text chunks."""
    try:
        client = _get_client()

        messages_text = ""
        for msg in history:
            role_label = "Пользователь" if msg["role"] == "user" else "Зефир"
            messages_text += f"{role_label}: {msg['content']}\n"
        messages_text += f"Пользователь: {user_message}\nЗефир:"

        response = await client.responses.create(
            prompt={"id": config.yandex_gpt_prompt_id},
            input=messages_text,
            stream=True,
        )

        full_text = ""
        async for event in response:
            if hasattr(event, "delta") and event.delta:
                full_text += event.delta
                yield full_text
            elif hasattr(event, "output_text") and event.output_text:
                full_text = event.output_text
                yield full_text

        if not full_text:
            yield "Мур... что-то пошло не так, попробуй ещё раз 😿"

    except Exception as e:
        logger.error("AI chat stream error: %s", e)
        yield "Мур... произошла ошибка, попробуй позже 😿"


async def chat_simple(history: list[dict], user_message: str) -> str:
    """Non-streaming fallback for AI chat."""
    try:
        client = _get_client()

        messages_text = ""
        for msg in history:
            role_label = "Пользователь" if msg["role"] == "user" else "Зефир"
            messages_text += f"{role_label}: {msg['content']}\n"
        messages_text += f"Пользователь: {user_message}\nЗефир:"

        response = await client.responses.create(
            prompt={"id": config.yandex_gpt_prompt_id},
            input=messages_text,
        )
        return response.output_text.strip() or "Мур... не знаю что сказать 😿"
    except Exception as e:
        logger.error("AI chat error: %s", e)
        return "Мур... произошла ошибка, попробуй позже 😿"
