import asyncio
import html
import json
import logging
import sys
import traceback

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, ErrorEvent, Update

from bot.config import config
from bot.db import init_db, close_db
from bot.handlers import setup_routers
from bot.logging_ru import install_ru_localization
from bot.middlewares.user_register import UserRegisterMiddleware
from bot.middlewares.rate_limit import RateLimitMiddleware
from bot.middlewares.fun_consent import FunConsentMiddleware
from bot.middlewares.news_notice import NewsNoticeMiddleware
from bot.services.time_service import today_msk, now_msk

PUBLIC_COMMANDS = [
    BotCommand(command="start",   description="🏠 Главное меню"),
    BotCommand(command="help",    description="🆘 Помощь"),
    BotCommand(command="news",    description="📰 Новости и апдейты"),
    BotCommand(command="updates", description="🆕 Последний апдейт"),
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
dp.message.outer_middleware(NewsNoticeMiddleware())
dp.callback_query.outer_middleware(NewsNoticeMiddleware())
dp.message.outer_middleware(FunConsentMiddleware())
dp.callback_query.outer_middleware(FunConsentMiddleware())
dp.message.outer_middleware(RateLimitMiddleware())


def _error_context(update: Update) -> tuple[int | None, int | None, str | None]:
    message = update.message or update.edited_message
    if message and message.from_user:
        text = (message.text or message.caption or "").strip()
        action = text.split(maxsplit=1)[0] if text.startswith("/") else "message"
        return message.from_user.id, message.chat.id, action
    callback = update.callback_query
    if callback and callback.from_user:
        chat_id = callback.message.chat.id if callback.message else callback.from_user.id
        return callback.from_user.id, chat_id, callback.data or "callback"
    return None, None, None


async def on_error(event: ErrorEvent, bot: Bot):
    tb = "".join(traceback.format_exception(type(event.exception), event.exception, event.exception.__traceback__))
    user_id, chat_id, action = _error_context(event.update)
    logger.error(
        "🚨 Ошибка в обработке update user=%s action=%s",
        user_id,
        action,
        exc_info=(type(event.exception), event.exception, event.exception.__traceback__),
    )
    from bot.keyboards.inline import admin_incident_actions
    from bot.models import create_incident

    incident_id = await create_incident(
        title=event.exception.__class__.__name__,
        message=str(event.exception),
        traceback_text=tb[-5000:],
        user_id=user_id,
        chat_id=chat_id,
        action=action,
        event_type="auto",
    )
    if chat_id:
        try:
            await bot.send_message(
                chat_id,
                f"⚠️ Произошла ошибка. Инцидент #{incident_id} передан владельцу, я постараюсь не потерять контекст.",
            )
        except Exception:
            pass
    admin_text = (
        f"🚨 <b>Инцидент #{incident_id}</b>\n\n"
        f"Ошибка: <b>{event.exception.__class__.__name__}</b>\n"
        f"Пользователь: <code>{user_id or '—'}</code>\n"
        f"Действие: <code>{html.escape(action or '—')}</code>\n\n"
        "Подробности в логах хостинга и карточке инцидента."
    )
    for admin_id in config.admins:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_incident_actions(incident_id))
        except Exception:
            pass
    return True


dp.errors.register(on_error)


_commands_set = False
_started = False


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
    global _started
    if _started:
        return
    await init_db()
    await _setup_commands()
    _started = True
    logger.info("🍬 Зефирка запущена, БД подключена; app_date_msk=%s now_msk=%s", today_msk(), now_msk().strftime("%d.%m.%Y %H:%M"))


async def on_shutdown():
    global _started
    await close_db()
    await bot.session.close()
    _started = False
    logger.info("🔌 Зефирка остановлена, соединения закрыты")


# ── Yandex Cloud Functions handler ──────────────────────────────
def _timer_payload_from_event(event: dict) -> dict:
    try:
        messages = event.get("messages") or []
        payload = ((messages[0] or {}).get("details") or {}).get("payload")
    except Exception:
        payload = None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload.strip():
        try:
            return json.loads(payload)
        except Exception:
            return {}
    return {}


def _body_payload_from_event(event: dict) -> dict:
    body_raw = event.get("body") or "{}"
    try:
        body = json.loads(body_raw)
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


def _job_token_from_event(event: dict) -> str:
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    qs = event.get("queryStringParameters") or {}
    body = _body_payload_from_event(event)
    timer_payload = _timer_payload_from_event(event)
    auth = str(headers.get("authorization") or "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return str(
        headers.get("x-game-jobs-token")
        or qs.get("token")
        or body.get("token")
        or timer_payload.get("token")
        or ""
    )


def _is_game_jobs_event(event: dict) -> bool:
    path = str(event.get("path") or event.get("url") or "")
    body = _body_payload_from_event(event)
    timer_payload = _timer_payload_from_event(event)
    return (
        path.endswith("/game-jobs")
        or body.get("job") == "game_events"
        or timer_payload.get("job") == "game_events"
    )


async def _process_event(event: dict):
    await on_startup()
    if _is_game_jobs_event(event):
        if not config.game_jobs_token or _job_token_from_event(event) != config.game_jobs_token:
            return {"statusCode": 403, "body": json.dumps({"ok": False, "error": "forbidden"})}
        from bot.handlers.games import process_due_game_events

        processed = await process_due_game_events(bot)
        logger.info("🎮 Game jobs обработаны: date_msk=%s processed=%s", today_msk(), processed)
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True, "processed": processed}),
            "headers": {"Content-Type": "application/json"},
        }
    else:
        body = json.loads(event.get("body", "{}"))
        update = Update.model_validate(body, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {
            "statusCode": 200,
            "body": json.dumps({"ok": True}),
            "headers": {"Content-Type": "application/json"},
        }


def handler(event, context):
    """Entry point for Yandex Cloud Functions."""
    return asyncio.get_event_loop().run_until_complete(_process_event(event))


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
