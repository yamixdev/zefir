import asyncio
import json
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from bot.config import config
from bot.db import init_db, close_db
from bot.handlers import setup_routers
from bot.logging_ru import install_ru_localization
from bot.middlewares.user_register import UserRegisterMiddleware
from bot.middlewares.rate_limit import RateLimitMiddleware

logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
install_ru_localization()
logger = logging.getLogger("зефирка")

bot = Bot(
    token=config.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()
dp.include_router(setup_routers())

# Middlewares (outer = first to run)
dp.message.outer_middleware(UserRegisterMiddleware())
dp.callback_query.outer_middleware(UserRegisterMiddleware())
dp.message.outer_middleware(RateLimitMiddleware())


async def on_startup():
    await init_db()
    logger.info("🍬 Зефирка запущена, БД подключена")


async def on_shutdown():
    await close_db()
    await bot.session.close()
    logger.info("🔌 Зефирка остановлена, соединения закрыты")


# ── Yandex Cloud Functions handler ──────────────────────────────
async def _process_event(event: dict):
    await on_startup()
    try:
        body = json.loads(event.get("body", "{}"))
        update = Update.model_validate(body, context={"bot": bot})
        await dp.feed_update(bot, update)
    finally:
        await on_shutdown()


def handler(event, context):
    """Entry point for Yandex Cloud Functions."""
    asyncio.get_event_loop().run_until_complete(_process_event(event))
    return {
        "statusCode": 200,
        "body": json.dumps({"ok": True}),
        "headers": {"Content-Type": "application/json"},
    }


# ── Local polling for development ───────────────────────────────
async def main():
    await on_startup()
    # Remove webhook so polling works locally
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        import selectors
        asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(main())
