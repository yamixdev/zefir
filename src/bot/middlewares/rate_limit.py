import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.config import config

# In-memory cooldown tracker (resets on cold start, which is fine for serverless)
_last_message: dict[int, float] = {}


class RateLimitMiddleware(BaseMiddleware):
    """Throttle messages: 1 message per cooldown_sec per user."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.from_user:
            return await handler(event, data)

        user_id = event.from_user.id

        # Admins bypass cooldown
        if config.is_admin(user_id):
            return await handler(event, data)

        now = time.time()
        last = _last_message.get(user_id, 0)

        if now - last < config.message_cooldown_sec:
            return  # silently drop

        _last_message[user_id] = now
        return await handler(event, data)
