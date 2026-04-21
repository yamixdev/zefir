from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards.inline import main_menu
from bot.models import get_last_menu_msg_id, set_last_menu_msg_id

router = Router()

WELCOME_TEXT = (
    "👋 <b>Привет, {name}!</b>\n\n"
    "Я — бот-агент Зефира! 🐱\n\n"
    "<b>Что я умею:</b>\n"
    "📨 Принимать сообщения и передавать админу\n"
    "🐱 Общаться с тобой как умный кот Зефир (AI)\n"
    "⛅ Показывать погоду в любом городе\n"
    "👤 Показывать твой профиль и статус тикетов\n\n"
    "Выбери действие:"
)

HELP_TEXT = (
    "🆘 <b>Помощь</b>\n\n"
    "<b>Кнопки меню:</b>\n"
    "📨 <b>Написать админу</b> — создать тикет\n"
    "🐱 <b>Зефир</b> — поболтать с AI-котом\n"
    "⛅ <b>Погода</b> — прогноз в любом городе\n"
    "👤 <b>Мой профиль</b> — лимиты AI, статус тикетов\n"
    "📊 <b>Мои тикеты</b> — история обращений\n\n"
    "<b>Команды:</b>\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/weather [город] — быстрая погода\n"
    "/admin — панель админа"
)


async def _render_fresh_menu(bot: Bot, chat_id: int, user_id: int, text: str) -> None:
    """Delete previously tracked menu message, send a new one, track its id."""
    prev_id = await get_last_menu_msg_id(user_id)
    if prev_id:
        try:
            await bot.delete_message(chat_id, prev_id)
        except Exception:
            pass
    msg = await bot.send_message(chat_id, text, reply_markup=main_menu())
    await set_last_menu_msg_id(user_id, msg.message_id)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    name = message.from_user.first_name or "друг"
    await _render_fresh_menu(bot, message.chat.id, message.from_user.id, WELCOME_TEXT.format(name=name))


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    await _render_fresh_menu(bot, message.chat.id, message.from_user.id, HELP_TEXT)


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery):
    name = callback.from_user.first_name or "друг"
    try:
        await callback.message.edit_text(
            WELCOME_TEXT.format(name=name), reply_markup=main_menu()
        )
        await set_last_menu_msg_id(callback.from_user.id, callback.message.message_id)
    except Exception:
        pass
    await callback.answer()
