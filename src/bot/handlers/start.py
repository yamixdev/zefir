from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from bot.config import config
from bot.keyboards.inline import (
    fun_consent_back,
    fun_consent_menu,
    main_menu,
    contact_submenu,
    fun_submenu,
)
from bot.models import (
    accept_consent,
    get_last_menu_msg_id,
    set_last_menu_msg_id,
    get_zefirki_balance,
)
from bot.services.consent import (
    FUN_CONSENT_INTRO,
    FUN_CONSENT_VERSION,
    FUN_PRIVACY_TEXT,
    FUN_TOS_TEXT,
    fun_docs_hash,
)
from bot.utils import smart_edit

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
    "🎒 <b>Инвентарь</b> — предметы, редкости, использование\n"
    "📦 <b>Кейсы</b> — награды за зефирки\n"
    "🏪 <b>Рынок</b> — торговля предметами с комиссией\n"
    "🐾 <b>Питомец</b> — уход, опыт и ежедневные награды\n"
    "🎮 <b>Игры</b> — сапёр и PvP-комнаты\n"
    "🐱 <b>Зефир (AI)</b> — общение с умным котом\n"
    "⛅ <b>Погода</b> — прогноз сейчас / 5 / 7 дней\n"
    "💱 <b>Конвертер валют</b> — курсы ЦБ РФ\n"
    "🔳 <b>QR-код</b> — генератор из текста/ссылки\n"
    "👤 <b>Мой профиль</b> — статистика, зефирки, лимиты"
)

_HELP_HEAD = (
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
    "/inventory — инвентарь\n"
    "/cases — кейсы\n"
    "/shop — магазин\n"
    "/market — рынок\n"
    "/pet — питомец\n"
    "/games — игры\n"
    "/join &lt;код&gt; — войти в PvP-комнату"
)

_HELP_ADMIN = "\n/admin — панель владельца"

_HELP_TAIL = (
    "\n\n<i>Или тыкай кнопки — так удобнее.</i>\n\n"
    "💰 За активность начисляются <b>зефирки</b> — внутренняя валюта, "
    "которую можно тратить на бонусы и игровые штуки."
)


def _help_text(user_id: int) -> str:
    return _HELP_HEAD + (_HELP_ADMIN if config.is_admin(user_id) else "") + _HELP_TAIL


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
    msg = await bot.send_message(
        message.chat.id,
        _help_text(message.from_user.id),
        reply_markup=main_menu(),
    )
    await set_last_menu_msg_id(message.from_user.id, msg.message_id)


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery):
    text = await _welcome_text(callback.from_user.id, callback.from_user.first_name)
    new_msg = await smart_edit(callback, text, reply_markup=main_menu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer()


@router.callback_query(F.data == "menu:contact")
async def cb_contact(callback: CallbackQuery):
    new_msg = await smart_edit(callback, CONTACT_TEXT, reply_markup=contact_submenu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer()


@router.callback_query(F.data == "menu:fun")
async def cb_fun(callback: CallbackQuery):
    new_msg = await smart_edit(callback, FUN_TEXT, reply_markup=fun_submenu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer()


@router.callback_query(F.data == "funconsent:show")
async def cb_fun_consent_show(callback: CallbackQuery):
    new_msg = await smart_edit(callback, FUN_CONSENT_INTRO, reply_markup=fun_consent_menu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer()


@router.callback_query(F.data == "funconsent:tos")
async def cb_fun_consent_tos(callback: CallbackQuery):
    await smart_edit(
        callback,
        f"{FUN_TOS_TEXT}\n\n<i>Версия {FUN_CONSENT_VERSION}</i>",
        reply_markup=fun_consent_back(),
    )
    await callback.answer()


@router.callback_query(F.data == "funconsent:privacy")
async def cb_fun_consent_privacy(callback: CallbackQuery):
    await smart_edit(
        callback,
        f"{FUN_PRIVACY_TEXT}\n\n<i>Версия {FUN_CONSENT_VERSION}</i>",
        reply_markup=fun_consent_back(),
    )
    await callback.answer()


@router.callback_query(F.data == "funconsent:accept")
async def cb_fun_consent_accept(callback: CallbackQuery):
    await accept_consent(callback.from_user.id, FUN_CONSENT_VERSION, fun_docs_hash())
    new_msg = await smart_edit(callback, FUN_TEXT, reply_markup=fun_submenu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer("Документы приняты")


@router.callback_query(F.data == "funconsent:decline")
async def cb_fun_consent_decline(callback: CallbackQuery):
    text = await _welcome_text(callback.from_user.id, callback.from_user.first_name)
    new_msg = await smart_edit(callback, text, reply_markup=main_menu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer("Развлечения закрыты до принятия документов")
