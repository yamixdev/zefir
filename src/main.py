import asyncio
import json
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, Update

from bot.config import config
from bot.db import init_db, close_db
from bot.handlers import setup_routers
from bot.logging_ru import install_ru_localization
from bot.middlewares.user_register import UserRegisterMiddleware
from bot.middlewares.rate_limit import RateLimitMiddleware
from bot.middlewares.fun_consent import FunConsentMiddleware

PUBLIC_COMMANDS = [
    BotCommand(command="start",   description="🏠 Главное меню"),
    BotCommand(command="help",    description="🆘 Помощь"),
    BotCommand(command="weather", description="⛅ Погода (опц. город)"),
    BotCommand(command="convert", description="💱 Конвертер: /convert 100 USD RUB"),
    BotCommand(command="rates",   description="📈 Курсы ЦБ РФ"),
    BotCommand(command="qr",      description="🔳 QR: /qr текст"),
    BotCommand(command="inventory", description="🎒 Инвентарь"),
    BotCommand(command="cases",   description="📦 Кейсы"),
    BotCommand(command="market",  description="🏪 Рынок"),
    BotCommand(command="shop",    description="🛒 Магазин"),
    BotCommand(command="pet",     description="🐾 Питомец"),
    BotCommand(command="games",   description="🎮 Игры"),
    BotCommand(command="join",    description="🚪 Войти в PvP-комнату: /join код"),
]

ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="admin", description="👑 Админ-панель"),
]

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
dp.message.outer_middleware(FunConsentMiddleware())
dp.callback_query.outer_middleware(FunConsentMiddleware())
dp.message.outer_middleware(RateLimitMiddleware())


_commands_set = False


async def _setup_commands():
    """Вызываем один раз на процесс (в YCF — на cold start)."""
    global _commands_set
    if _commands_set:
        return
    _commands_set = True
    try:
        await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeAllPrivateChats())
        for admin_id in config.admins:
            try:
                await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as e:
                logger.warning("🍬 Не смогла выставить команды админу %s: %s", admin_id, e)
    except Exception as e:
        logger.warning("🍬 Не смогла выставить команды: %s", e)


async def on_startup():
    await init_db()
    await _setup_commands()
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
