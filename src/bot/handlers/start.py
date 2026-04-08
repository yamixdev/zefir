from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery

from bot.keyboards.inline import main_menu

router = Router()

WELCOME_TEXT = (
    "👋 <b>Привет, {name}!</b>\n\n"
    "Я — бот-агент Зефира! 🐱\n\n"
    "<b>Что я умею:</b>\n"
    "📨 Принимать сообщения и передавать админу\n"
    "🐱 Общаться с тобой как умный кот Зефир (AI)\n"
    "⛅ Показывать погоду в любом городе\n"
    "📊 Отслеживать статус твоих обращений\n\n"
    "Выбери действие:"
)

HELP_TEXT = (
    "🆘 <b>Помощь</b>\n\n"
    "<b>Кнопки меню:</b>\n"
    "📨 <b>Написать админу</b> — создать тикет\n"
    "🐱 <b>Зефир</b> — поболтать с AI-котом\n"
    "⛅ <b>Погода</b> — прогноз в любом городе\n"
    "📊 <b>Мои тикеты</b> — история обращений\n\n"
    "<b>Команды:</b>\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/weather [город] — быстрая погода\n"
    "/admin — панель админа"
)


@router.message(CommandStart())
async def cmd_start(message: Message):
    name = message.from_user.first_name or "друг"
    await message.answer(WELCOME_TEXT.format(name=name), reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT, reply_markup=main_menu())


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery):
    name = callback.from_user.first_name or "друг"
    await callback.message.edit_text(
        WELCOME_TEXT.format(name=name), reply_markup=main_menu()
    )
    await callback.answer()
