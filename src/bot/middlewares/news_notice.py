from __future__ import annotations

import logging

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message

from bot.services.news_service import (
    clear_notice_message,
    get_notice_message,
    get_pending_notice,
    notice_is_stale,
    remember_notice_message,
)

logger = logging.getLogger("зефирка.новости")


class NewsNoticeMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        result = None
        if user and not getattr(user, "is_bot", False):
            bot: Bot | None = data.get("bot")
            if bot:
                is_news_action = self._is_news_action(event)
                await self._cleanup_existing_notice(bot, user.id, mark_seen=not is_news_action)
                result = await handler(event, data)
                if self._can_show_notice(event, data) and not is_news_action:
                    await self._send_pending_notice(bot, user.id)
                return result
        return await handler(event, data)

    def _is_news_action(self, event) -> bool:
        if isinstance(event, CallbackQuery):
            return bool((event.data or "").startswith(("news:", "adm:news")))
        if isinstance(event, Message):
            text = (event.text or "").strip().lower()
            return text.startswith(("/news", "/updates"))
        return False

    def _can_show_notice(self, event, data) -> bool:
        if data.get("raw_state"):
            # Do not inject news while the user is typing a code, price, pet name, etc.
            return False
        if isinstance(event, CallbackQuery):
            data_raw = event.data or ""
            return data_raw in ("menu:main", "news:notice:open")
        if isinstance(event, Message):
            text = (event.text or "").strip().lower()
            return text.startswith("/start")
        return False

    async def _cleanup_existing_notice(self, bot: Bot, user_id: int, mark_seen: bool) -> None:
        settings = await get_notice_message(user_id)
        if not settings:
            return
        should_delete = mark_seen or notice_is_stale(settings)
        if not should_delete:
            return
        seen_post_id = settings.get("notice_post_id") if mark_seen else None
        try:
            await bot.delete_message(user_id, settings["notice_msg_id"])
        except Exception:
            pass
        await clear_notice_message(user_id, seen_post_id)

    async def _send_pending_notice(self, bot: Bot, user_id: int) -> None:
        post = await get_pending_notice(user_id)
        if not post:
            return
        kind = {"update": "обновление", "event": "ивент", "news": "новость"}.get(post["kind"], "новость")
        text = (
            f"📰 <b>Есть {kind}</b>\n\n"
            f"<b>{post['title']}</b>\n"
            "Открыть можно командой /news или кнопкой ниже.\n\n"
            "<i>Уведомления можно настроить в Новости → Настройки.</i>"
        )
        from bot.handlers.news import news_notice_kb

        try:
            msg = await bot.send_message(user_id, text, reply_markup=news_notice_kb(post["id"]))
            await remember_notice_message(user_id, post["id"], msg.message_id)
        except Exception as e:
            logger.debug("Не смог отправить уведомление о новости %s юзеру %s: %s", post["id"], user_id, e)
