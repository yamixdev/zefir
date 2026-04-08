import asyncio
import logging
import time

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.keyboards.inline import ai_exit, main_menu
from bot.models import (
    check_ai_limit, increment_ai_usage,
    save_ai_message, get_ai_history, clear_ai_history,
)
from bot.services.ai_service import chat_stream, chat_simple

logger = logging.getLogger(__name__)
router = Router()

EDIT_INTERVAL = 1.5  # seconds between message edits (Telegram rate limit protection)


class AIChatStates(StatesGroup):
    chatting = State()


@router.callback_query(F.data == "ai:start")
async def cb_ai_start(callback: CallbackQuery, state: FSMContext):
    allowed, remaining = await check_ai_limit(callback.from_user.id)

    await state.set_state(AIChatStates.chatting)
    await callback.message.edit_text(
        "🐱 <b>Привет! Я Зефир — умный кот!</b>\n\n"
        "Можешь спрашивать меня о чём угодно, я постараюсь помочь.\n"
        f"💬 Осталось сообщений: <b>{remaining}</b>\n\n"
        "Просто напиши мне!",
        reply_markup=ai_exit(),
    )
    await callback.answer()


@router.callback_query(F.data == "ai:exit")
async def cb_ai_exit(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        f"👋 Зефир ушёл отдыхать 😸\n\n"
        f"Возвращайся когда захочешь, {name}!",
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.message(AIChatStates.chatting)
async def process_ai_message(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    user_text = message.text or ""

    if not user_text:
        return

    # Check limits
    allowed, remaining = await check_ai_limit(user_id)
    if not allowed:
        await message.answer(
            "😿 <b>Лимит сообщений исчерпан!</b>\n\n"
            "Лимит обновится через 12 часов. Подожди немного!",
            reply_markup=ai_exit(),
        )
        return

    # Save user message
    await save_ai_message(user_id, "user", user_text)
    await increment_ai_usage(user_id)

    # Get history
    history_rows = await get_ai_history(user_id, limit=10)
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    # Send placeholder
    placeholder = await message.answer("🐱 Зефир думает...")

    # Try streaming
    try:
        last_edit_time = 0.0
        final_text = ""

        async for accumulated_text in chat_stream(history, user_text):
            final_text = accumulated_text
            now = time.time()
            if now - last_edit_time >= EDIT_INTERVAL:
                try:
                    await bot.edit_message_text(
                        text=f"🐱 {final_text}",
                        chat_id=message.chat.id,
                        message_id=placeholder.message_id,
                        reply_markup=ai_exit(),
                    )
                    last_edit_time = now
                except Exception:
                    pass  # Telegram may reject identical edits

        # Final edit with complete text
        if final_text:
            try:
                _, new_remaining = await check_ai_limit(user_id)
                await bot.edit_message_text(
                    text=f"🐱 {final_text}\n\n<i>💬 Осталось: {new_remaining}</i>",
                    chat_id=message.chat.id,
                    message_id=placeholder.message_id,
                    reply_markup=ai_exit(),
                )
            except Exception:
                pass

            await save_ai_message(user_id, "assistant", final_text)

    except Exception as e:
        logger.error("Streaming failed, falling back to simple: %s", e)
        # Fallback to non-streaming
        response = await chat_simple(history, user_text)
        _, new_remaining = await check_ai_limit(user_id)
        try:
            await bot.edit_message_text(
                text=f"🐱 {response}\n\n<i>💬 Осталось: {new_remaining}</i>",
                chat_id=message.chat.id,
                message_id=placeholder.message_id,
                reply_markup=ai_exit(),
            )
        except Exception:
            await message.answer(
                f"🐱 {response}\n\n<i>💬 Осталось: {new_remaining}</i>",
                reply_markup=ai_exit(),
            )
        await save_ai_message(user_id, "assistant", response)
