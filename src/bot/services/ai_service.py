"""Вызов Yandex Foundation Models Responses API напрямую через aiohttp.

Модель задаётся в Yandex AI Studio для конкретного prompt-а (сейчас: Alice AI LLM).
В API её передавать не нужно — Yandex берёт её из конфига prompt_id.
"""
import base64
import json
import logging
import time
from typing import AsyncGenerator

import aiohttp

from bot.config import config

logger = logging.getLogger("зефир.api")

YANDEX_URL = "https://ai.api.cloud.yandex.net/v1/responses"
YANDEX_OCR_URL = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
YANDEX_FOLDER_ID = "b1ghl0tltpae2u0jgpp5"
YANDEX_PROMPT_ID = "fvtdm4efjmavtbgr5qlc"
YANDEX_MODEL_NAME = "Alice AI LLM"  # справочно; реальная модель настроена в AI Studio


class AIError(Exception):
    """Сбой вызова AI — вызывающий код НЕ должен списывать лимит юзера."""


def _headers() -> dict:
    return {
        "Authorization": f"Api-Key {config.yandex_gpt_api_key}",
        "x-folder-id": YANDEX_FOLDER_ID,
        "Content-Type": "application/json",
    }


def _build_chat_input(history: list[dict], user_message: str) -> str:
    lines = []
    for msg in history:
        role_label = "Пользователь" if msg["role"] == "user" else "Зефир"
        lines.append(f"{role_label}: {msg['content']}")
    lines.append(f"Пользователь: {user_message}")
    lines.append("Зефир:")
    return "\n".join(lines)


def _extract_text(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    if data.get("output_text"):
        return str(data["output_text"]).strip()
    output = data.get("output")
    if isinstance(output, list):
        for item in output:
            if isinstance(item, dict) and item.get("type") == "message":
                for c in item.get("content", []):
                    if isinstance(c, dict) and c.get("type") == "output_text":
                        return (c.get("text") or "").strip()
    return ""


async def _call(input_text: str, stream: bool):
    """Открывает POST к Yandex. Возвращает (resp, session) — caller закрывает."""
    session = aiohttp.ClientSession()
    payload = {
        "prompt": {"id": YANDEX_PROMPT_ID},
        "input": input_text,
    }
    if stream:
        payload["stream"] = True
    try:
        resp = await session.post(YANDEX_URL, json=payload, headers=_headers())
        if resp.status >= 400:
            body = await resp.text()
            await resp.release()
            await session.close()
            logger.error("❌ Yandex API вернул HTTP %s: %s", resp.status, body[:300])
            raise AIError(f"HTTP {resp.status}")
        return resp, session
    except AIError:
        raise
    except Exception as e:
        await session.close()
        logger.error("❌ Не удалось подключиться к Yandex API: %s", e)
        raise AIError(str(e)) from e


async def summarize_ticket(message: str) -> str:
    """Кратко интерпретирует сообщение юзера для админа. Best-effort."""
    t0 = time.time()
    try:
        input_text = (
            "Пользователь написал сообщение админу. "
            "Кратко (1-2 предложения) интерпретируй, что он хочет. "
            "Отвечай от третьего лица.\n\n"
            f"Сообщение: {message}"
        )
        resp, session = await _call(input_text, stream=False)
        try:
            data = await resp.json()
        finally:
            await resp.release()
            await session.close()
        text = _extract_text(data)
        elapsed = int((time.time() - t0) * 1000)
        logger.info("🐱 AI-интерпретация тикета готова за %d мс", elapsed)
        return text
    except Exception as e:
        logger.error("❌ Ошибка AI при сжатии тикета: %s", e)
        return ""


async def chat_simple(history: list[dict], user_message: str) -> str:
    """Ответ без стриминга. Кидает AIError при сбое."""
    t0 = time.time()
    try:
        input_text = _build_chat_input(history, user_message)
        resp, session = await _call(input_text, stream=False)
        try:
            data = await resp.json()
        finally:
            await resp.release()
            await session.close()
        text = _extract_text(data)
        if not text:
            logger.error("❌ AI вернул пустой ответ: %s", str(data)[:200])
            raise AIError("empty response")
        elapsed = int((time.time() - t0) * 1000)
        logger.info("🐱 AI ответил (simple) за %d мс, %d символов", elapsed, len(text))
        return text
    except AIError:
        raise
    except Exception as e:
        logger.error("❌ Ошибка AI (simple): %s", e)
        raise AIError(str(e)) from e


async def chat_stream(history: list[dict], user_message: str) -> AsyncGenerator[str, None]:
    """Стриминг ответа. Yields аккумулированный текст. Кидает AIError при сбое."""
    t0 = time.time()
    input_text = _build_chat_input(history, user_message)
    resp, session = await _call(input_text, stream=True)

    full_text = ""
    chunks = 0
    try:
        async for raw in resp.content:
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue

            ctype = chunk.get("type", "")
            if ctype == "response.output_text.delta":
                delta = chunk.get("delta") or ""
                if delta:
                    full_text += delta
                    chunks += 1
                    yield full_text
            elif ctype == "response.completed":
                final = chunk.get("response") or {}
                final_text = _extract_text(final) or final.get("output_text") or ""
                if final_text and final_text != full_text:
                    full_text = final_text
                    yield full_text
            elif "output_text" in chunk and not full_text:
                # запасной формат ответа
                t = chunk.get("output_text") or ""
                if t:
                    full_text = t
                    yield full_text
    except Exception as e:
        logger.error("❌ Ошибка стриминга AI: %s", e)
        raise AIError(str(e)) from e
    finally:
        try:
            await resp.release()
        except Exception:
            pass
        try:
            await session.close()
        except Exception:
            pass

    if not full_text:
        logger.error("❌ Стрим AI закончился без текста")
        raise AIError("empty AI stream")

    elapsed = int((time.time() - t0) * 1000)
    logger.info("🐱 AI ответил (stream) за %d мс, %d символов, %d чанков",
                elapsed, len(full_text), chunks)


async def ocr_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """Распознать текст на фото через Yandex Vision OCR. Raises AIError при сбое.
    Возвращает пустую строку если текст не найден."""
    t0 = time.time()
    if mime_type not in ("image/jpeg", "image/png", "image/pdf", "application/pdf"):
        mime_type = "image/jpeg"

    payload = {
        "mimeType": mime_type,
        "languageCodes": ["ru", "en"],
        "model": "page",
        "content": base64.b64encode(image_bytes).decode("ascii"),
    }
    headers = {
        "Authorization": f"Api-Key {config.yandex_gpt_api_key}",
        "x-folder-id": YANDEX_FOLDER_ID,
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(YANDEX_OCR_URL, json=payload, headers=headers) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.error("❌ Yandex Vision вернул HTTP %s: %s", resp.status, body[:300])
                    raise AIError(f"OCR HTTP {resp.status}")
                data = await resp.json()
    except AIError:
        raise
    except Exception as e:
        logger.error("❌ Не удалось вызвать Yandex Vision: %s", e)
        raise AIError(str(e)) from e

    text = ""
    try:
        text = data["result"]["textAnnotation"]["fullText"]
    except (KeyError, TypeError):
        pass

    elapsed = int((time.time() - t0) * 1000)
    logger.info("👁 OCR готов за %d мс, символов: %d", elapsed, len(text or ""))
    return (text or "").strip()
