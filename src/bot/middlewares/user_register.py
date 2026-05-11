from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from bot.config import config
from bot.keyboards.inline import banned_main_menu
from bot.models import upsert_user, is_banned, record_user_activity


def _event_action(event: TelegramObject) -> tuple[str, str, int | None, dict]:
    if isinstance(event, Message):
        text = (event.text or event.caption or "").strip()
        command = text.split(maxsplit=1)[0] if text.startswith("/") else ""
        return "message", command or "message", event.chat.id, {"text": text[:120] if text else ""}
    if isinstance(event, CallbackQuery):
        return "callback", event.data or "callback", event.message.chat.id if event.message else None, {}
    return "event", event.__class__.__name__, None, {}


def _banned_allowed(event: TelegramObject, data: dict[str, Any]) -> bool:
    if isinstance(event, Message):
        text = (event.text or "").strip().lower()
        if text.startswith("/start"):
            return True
        # If a banned user is already typing a ticket/bug report, let the FSM handler finish it.
        return bool(data.get("raw_state"))
    if isinstance(event, CallbackQuery):
        cb_data = event.data or ""
        return cb_data in ("menu:main", "menu:contact", "incident:report", "incident:user_close") or cb_data.startswith("ticket:")
    return False


class UserRegisterMiddleware(BaseMiddleware):
    """Auto-register users in DB and block banned ones."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message) and event.from_user:
            user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            user = event.from_user

        if user:
            await upsert_user(
                user_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )
            event_type, action, chat_id, context = _event_action(event)
            await record_user_activity(user.id, event_type, action, chat_id, context)

            if await is_banned(user.id) and not config.is_admin(user.id):
                if _banned_allowed(event, data):
                    return await handler(event, data)
                if isinstance(event, Message):
                    await event.answer(
                        "🚫 Доступ к функциям бота ограничен.\n\n"
                        "Если считаешь, что это ошибка, напиши владельцу через кнопку ниже.",
                        reply_markup=banned_main_menu(),
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer("Доступ ограничен. Можно связаться с владельцем из главного меню.", show_alert=True)
                return

        return await handler(event, data)
