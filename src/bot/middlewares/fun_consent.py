from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.keyboards.inline import fun_consent_menu
from bot.models import has_accepted_consent, set_last_menu_msg_id
from bot.services.consent import FUN_CONSENT_INTRO, FUN_CONSENT_VERSION


FUN_CALLBACK_PREFIXES = (
    "profile:", "econ:", "shop:", "pet:", "games:", "game:",
    "ai:", "weather:", "conv:", "qr:",
)
FUN_COMMANDS = {
    "inventory", "cases", "market", "shop", "pet", "games", "join",
    "weather", "convert", "rates", "qr",
}
EXEMPT_CALLBACK_PREFIXES = ("funconsent:", "menu:", "ticket:", "adm:")


def _command_name(text: str | None) -> str | None:
    if not text or not text.startswith("/"):
        return None
    raw = text.split(maxsplit=1)[0][1:]
    return raw.split("@", 1)[0].lower()


class FunConsentMiddleware(BaseMiddleware):
    """Blocks entertainment features until the user accepts game docs."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user_id: int | None = None
        needs_consent = False

        if isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            cb_data = event.data or ""
            if cb_data == "menu:fun":
                needs_consent = True
            elif cb_data.startswith("profile:admin"):
                needs_consent = False
            elif cb_data.startswith(EXEMPT_CALLBACK_PREFIXES):
                needs_consent = False
            elif cb_data.startswith(FUN_CALLBACK_PREFIXES):
                needs_consent = True
        elif isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            cmd = _command_name(event.text)
            needs_consent = cmd in FUN_COMMANDS

        if not needs_consent or not user_id:
            return await handler(event, data)

        if await has_accepted_consent(user_id, FUN_CONSENT_VERSION):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            try:
                msg = await event.message.edit_text(FUN_CONSENT_INTRO, reply_markup=fun_consent_menu())
                await set_last_menu_msg_id(user_id, msg.message_id)
            except Exception:
                pass
            await event.answer()
            return

        if isinstance(event, Message):
            try:
                await event.delete()
            except Exception:
                pass
            msg = await event.bot.send_message(event.chat.id, FUN_CONSENT_INTRO, reply_markup=fun_consent_menu())
            await set_last_menu_msg_id(user_id, msg.message_id)
            return

        return await handler(event, data)
