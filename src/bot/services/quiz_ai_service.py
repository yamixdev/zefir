from __future__ import annotations

import json
import logging

from bot.services.ai_service import chat_simple

logger = logging.getLogger("зефирка.квиз")


def _valid_question(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text = str(raw.get("text") or "").strip()
    options = raw.get("options")
    explanation = str(raw.get("explanation") or "").strip()
    try:
        correct = int(raw.get("correctIndex"))
    except Exception:
        return None
    if not text or not isinstance(options, list) or len(options) != 4 or correct not in range(4):
        return None
    clean_options = [str(opt).strip()[:120] for opt in options]
    if any(not opt for opt in clean_options):
        return None
    return {
        "text": text[:500],
        "options": clean_options,
        "correctIndex": correct,
        "explanation": explanation[:500] or "Ответ следует из формулировки вопроса.",
        "category": str(raw.get("category") or "ai")[:40],
        "ai_generated": True,
    }


async def generate_quiz_questions(count: int) -> list[dict]:
    count = max(1, min(int(count), 10))
    prompt = (
        "Сгенерируй вопросы для викторины Telegram-бота на русском. "
        "Нужны универсальные темы: логика, игры, интернет-культура, технологии, общие знания. "
        "Верни только JSON-массив без markdown. Каждый объект строго: "
        "text, options из 4 строк, correctIndex от 0 до 3, explanation, category. "
        f"Количество вопросов: {count}."
    )
    try:
        text = await chat_simple([], prompt)
        data = json.loads(text)
    except Exception as e:
        logger.warning("AI не сгенерировал валидный JSON для квиза: %s", e)
        return []
    if not isinstance(data, list):
        return []
    questions = []
    for item in data:
        valid = _valid_question(item)
        if valid:
            questions.append(valid)
        if len(questions) >= count:
            break
    return questions
