from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.keyboards.inline import fun_consent_menu
from bot.models import has_accepted_consent, set_last_menu_msg_id
from bot.services.consent import FUN_CONSENT_INTRO, FUN_CONSENT_VERSION


FUN_CALLBACK_PREFIXES = (
    "profile:", "econ:", "shop:", "pet:", "games:", "game:", "gamebot:",
    "ai:", "weather:", "conv:", "qr:",
)
FUN_COMMANDS = {
    "inventory", "cases", "market", "shop", "pet", "games", "join",
    "weather", "convert", "rates", "qr",
    "rps", "duel", "quiz", "hangman", "blackjack",
}
EXEMPT_CALLBACK_PREFIXES = ("funconsent:", "menu:", "ticket:", "adm:")


def _target_from_callback_data(cb_data: str) -> str:
    if cb_data == "menu:fun":
        return "fun"
    if cb_data == "menu:utils":
        return "utils"
    if cb_data.startswith("game:ttt:join:"):
        room_id = cb_data.rsplit(":", 1)[-1]
        safe_code = "".join(ch for ch in room_id.lower() if ch.isalnum())[:16]
        return f"join_{safe_code}" if safe_code else "games"
    parts = cb_data.split(":")
    if len(parts) >= 3 and parts[0] == "game" and parts[2] == "join":
        safe_code = "".join(ch for ch in parts[1].lower() if ch.isalnum())[:16]
        return f"join_{safe_code}" if safe_code else "games"
    if cb_data.startswith(("games:", "game:", "gamebot:")):
        return "games"
    if cb_data.startswith("econ:market"):
        return "market"
    if cb_data.startswith(("econ:listing:", "econ:buy:", "econ:mylist")):
        return "market"
    if cb_data.startswith(("econ:inv", "econ:item:", "econ:use:", "econ:sell:")):
        return "inventory"
    if cb_data.startswith("econ:cases") or cb_data.startswith(("econ:case:", "econ:open:")):
        return "cases"
    if cb_data.startswith("shop:"):
        return "shop"
    if cb_data.startswith("pet:"):
        return "pet"
    if cb_data.startswith("ai:"):
        return "ai"
    if cb_data.startswith("weather:"):
        return "weather"
    if cb_data.startswith("conv:"):
        return "convert"
    if cb_data.startswith("qr:"):
        return "qr"
    if cb_data.startswith("profile:"):
        return "profile"
    return "fun"


def _target_from_message(text: str | None) -> str:
    cmd = _command_name(text)
    args = ""
    if text and " " in text:
        args = text.split(maxsplit=1)[1].strip()
    if cmd == "join" and args:
        safe_code = "".join(ch for ch in args.lower() if ch.isalnum())[:16]
        return f"join_{safe_code}" if safe_code else "join"
    return {
        "inventory": "inventory",
        "cases": "cases",
        "market": "market",
        "shop": "shop",
        "pet": "pet",
        "games": "games",
        "join": "join",
        "rps": "game_rps",
        "duel": "game_duel",
        "quiz": "game_quiz",
        "hangman": "game_hangman",
        "blackjack": "game_blackjack",
        "weather": "weather",
        "convert": "convert",
        "rates": "convert",
        "qr": "qr",
    }.get(cmd or "", "fun")


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
        target = "fun"

        if isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            cb_data = event.data or ""
            if cb_data in ("menu:fun", "menu:utils"):
                needs_consent = True
                target = _target_from_callback_data(cb_data)
            elif cb_data.startswith("profile:admin"):
                needs_consent = False
            elif cb_data.startswith(EXEMPT_CALLBACK_PREFIXES):
                needs_consent = False
            elif cb_data.startswith(FUN_CALLBACK_PREFIXES):
                needs_consent = True
                target = _target_from_callback_data(cb_data)
        elif isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            cmd = _command_name(event.text)
            needs_consent = cmd in FUN_COMMANDS
            if needs_consent:
                target = _target_from_message(event.text)

        if not needs_consent or not user_id:
            return await handler(event, data)

        if await has_accepted_consent(user_id, FUN_CONSENT_VERSION):
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            try:
                msg = await event.message.edit_text(FUN_CONSENT_INTRO, reply_markup=fun_consent_menu(target))
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
            msg = await event.bot.send_message(event.chat.id, FUN_CONSENT_INTRO, reply_markup=fun_consent_menu(target))
            await set_last_menu_msg_id(user_id, msg.message_id)
            return

        return await handler(event, data)
