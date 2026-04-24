from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards.inline import main_menu, contact_submenu, fun_submenu
from bot.models import get_last_menu_msg_id, set_last_menu_msg_id, get_zefirki_balance

router = Router()

WELCOME_TEXT = (
    "👋 <b>Привет, {name}!</b>\n\n"
    "Я — <b>Зефирка</b> 🍬\n"
    "мульти-функциональный помощник с AI, утилитами и мини-играми.\n\n"
    "💰 Твои зефирки: <b>{zefirki}</b>\n\n"
    "Выбери куда идём:"
)

CONTACT_TEXT = (
    "📨 <b>Связь с владельцем</b>\n\n"
    "Здесь можно написать владельцу бота: задать вопрос, "
    "сообщить о баге, предложить фичу.\n\n"
    "📤 — отправлено, 👁 — просмотрено, ✅ — отвечено"
)

FUN_TEXT = (
    "🎮 <b>Развлечения и утилиты</b>\n\n"
    "🐱 <b>Зефир (AI)</b> — общение с умным котом\n"
    "⛅ <b>Погода</b> — прогноз сейчас / 5 / 7 дней\n"
    "💱 <b>Конвертер валют</b> — курсы ЦБ РФ\n"
    "🔳 <b>QR-код</b> — генератор из текста/ссылки\n"
    "👤 <b>Мой профиль</b> — статистика, зефирки, лимиты\n\n"
    "<i>Скоро: напоминалки, сканер QR из фото, мини-игра с питомцем…</i>"
)

HELP_TEXT = (
    "🆘 <b>Помощь по Зефирке</b>\n\n"
    "<b>Главное меню — две двери:</b>\n"
    "📨 <b>Связаться с владельцем</b> — тикеты, написать, посмотреть ответы\n"
    "🎮 <b>Развлечения и утилиты</b> — AI, погода, профиль и всё остальное\n\n"
    "<b>Команды (быстрые пути):</b>\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/weather [город] — быстрая погода\n"
    "/convert 100 USD RUB — разовая конвертация\n"
    "/rates — курсы валют ЦБ РФ\n"
    "/qr &lt;текст&gt; — QR-код одной строкой\n"
    "/admin — панель владельца\n\n"
    "<i>Или тыкай кнопки — так удобнее.</i>\n\n"
    "💰 За активность начисляются <b>зефирки</b> — внутренняя валюта, "
    "которую можно тратить на бонусы и игровые штуки."
)


async def _render_fresh_menu(bot: Bot, chat_id: int, user_id: int, text: str) -> None:
    """Удаляет ранее отправленное меню и шлёт свежее. Против спама /start."""
    prev_id = await get_last_menu_msg_id(user_id)
    if prev_id:
        try:
            await bot.delete_message(chat_id, prev_id)
        except Exception:
            pass
    msg = await bot.send_message(chat_id, text, reply_markup=main_menu())
    await set_last_menu_msg_id(user_id, msg.message_id)


async def _welcome_text(user_id: int, first_name: str | None) -> str:
    zefirki = await get_zefirki_balance(user_id)
    name = first_name or "друг"
    return WELCOME_TEXT.format(name=name, zefirki=zefirki)


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    text = await _welcome_text(message.from_user.id, message.from_user.first_name)
    await _render_fresh_menu(bot, message.chat.id, message.from_user.id, text)


@router.message(Command("help"))
async def cmd_help(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    prev_id = await get_last_menu_msg_id(message.from_user.id)
    if prev_id:
        try:
            await bot.delete_message(message.chat.id, prev_id)
        except Exception:
            pass
    msg = await bot.send_message(message.chat.id, HELP_TEXT, reply_markup=main_menu())
    await set_last_menu_msg_id(message.from_user.id, msg.message_id)


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery):
    text = await _welcome_text(callback.from_user.id, callback.from_user.first_name)
    try:
        await callback.message.edit_text(text, reply_markup=main_menu())
        await set_last_menu_msg_id(callback.from_user.id, callback.message.message_id)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "menu:contact")
async def cb_contact(callback: CallbackQuery):
    try:
        await callback.message.edit_text(CONTACT_TEXT, reply_markup=contact_submenu())
        await set_last_menu_msg_id(callback.from_user.id, callback.message.message_id)
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "menu:fun")
async def cb_fun(callback: CallbackQuery):
    try:
        await callback.message.edit_text(FUN_TEXT, reply_markup=fun_submenu())
        await set_last_menu_msg_id(callback.from_user.id, callback.message.message_id)
    except Exception:
        pass
    await callback.answer()
