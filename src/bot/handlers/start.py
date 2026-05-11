from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from bot.config import config
from bot.keyboards.inline import (
    banned_main_menu,
    fun_consent_back,
    fun_consent_menu,
    main_menu,
    contact_submenu,
    fun_submenu,
    utilities_submenu,
)
from bot.models import (
    accept_consent,
    get_last_menu_msg_id,
    set_last_menu_msg_id,
    get_zefirki_balance,
    is_banned,
)
from bot.services.consent import (
    FUN_CONSENT_EFFECTIVE_TEXT,
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
    "Выбери, куда идём:"
)

BANNED_TEXT = (
    "🚫 <b>Доступ к функциям бота ограничен.</b>\n\n"
    "Если считаешь, что это ошибка, можно связаться с владельцем."
)

CONTACT_TEXT = (
    "📨 <b>Связь с владельцем</b>\n\n"
    "Здесь можно написать владельцу бота: задать вопрос, "
    "сообщить о баге, предложить фичу.\n\n"
    "📤 — отправлено, 👁 — просмотрено, ✅ — отвечено"
)

FUN_TEXT = (
    "🎮 <b>Развлечения и утилиты</b>\n\n"
    "Основные игровые разделы собраны здесь. "
    "Утилиты вынесены отдельно, чтобы меню не превращалось в стену кнопок."
)

UTILS_TEXT = (
    "⚙️ <b>Утилиты</b>\n\n"
    "AI-чат, погода, конвертер валют и QR-код."
)

_HELP_HEAD = (
    "🆘 <b>Помощь по Зефирке</b>\n\n"
    "<b>Главное меню:</b>\n"
    "📨 <b>Связаться с владельцем</b> — тикеты, написать, посмотреть ответы\n"
    "📰 <b>Новости</b> — апдейты, события и настройки уведомлений\n"
    "🎮 <b>Развлечения и утилиты</b> — AI, погода, профиль и всё остальное\n\n"
    "<b>Команды (быстрые пути):</b>\n"
    "/start — главное меню\n"
    "/help — эта справка\n"
    "/news — новости, ивенты и апдейты\n"
    "/updates — последний апдейт бота\n"
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


async def _render_fresh_menu(bot: Bot, chat_id: int, user_id: int, text: str, reply_markup=None) -> None:
    """Удаляет ранее отправленное меню и шлёт свежее. Против спама /start."""
    prev_id = await get_last_menu_msg_id(user_id)
    if prev_id:
        try:
            await bot.delete_message(chat_id, prev_id)
        except Exception:
            pass
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup or main_menu())
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
    if await is_banned(message.from_user.id) and not config.is_admin(message.from_user.id):
        await _render_fresh_menu(bot, message.chat.id, message.from_user.id, BANNED_TEXT, banned_main_menu())
        return
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
    if await is_banned(callback.from_user.id) and not config.is_admin(callback.from_user.id):
        new_msg = await smart_edit(callback, BANNED_TEXT, reply_markup=banned_main_menu())
        if new_msg:
            await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
        await callback.answer()
        return
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


@router.callback_query(F.data == "menu:utils")
async def cb_utils(callback: CallbackQuery):
    new_msg = await smart_edit(callback, UTILS_TEXT, reply_markup=utilities_submenu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer()


def _consent_target(callback_data: str | None) -> str:
    parts = (callback_data or "").split(":", 2)
    return parts[2] if len(parts) == 3 and parts[2] else "fun"


async def _render_after_fun_consent(callback: CallbackQuery, target: str, state: FSMContext | None = None) -> None:
    if target.startswith("join_"):
        from bot.handlers.games import (
            _games_home_kb,
            _remember_session_message,
            _remember_ttt_message,
            _session_kb,
            _session_text,
            _sync_session_messages,
            _sync_ttt_player,
            _ttt_kb,
            _ttt_text,
        )
        from bot.services.game_session_service import get_session, join_session
        from bot.services.games_service import join_ttt_room

        room_id = target.removeprefix("join_")
        session = await get_session(room_id)
        if session:
            result = await join_session(room_id, callback.from_user)
            if result["ok"]:
                session = result["session"]
                msg = await smart_edit(callback, _session_text(session, callback.from_user.id), reply_markup=_session_kb(session, callback.from_user.id))
                if msg:
                    await _remember_session_message(session, callback.from_user.id, msg)
                    await set_last_menu_msg_id(callback.from_user.id, msg.message_id)
                await _sync_session_messages(callback.bot, session)
                return
            errors = {
                "not_available": "Комната уже недоступна или не найдена.",
                "expired": "Комната закрыта из-за бездействия.",
                "full": "Комната уже заполнена.",
                "already_started": "Игра уже началась.",
                "not_enough": "Не хватает зефирок для ставки.",
            }
            msg = await smart_edit(callback, f"❌ {errors.get(result.get('error'), 'Не удалось войти в комнату.')}", reply_markup=_games_home_kb())
            if msg:
                await set_last_menu_msg_id(callback.from_user.id, msg.message_id)
            return
        result = await join_ttt_room(callback.from_user.id, room_id)
        if result["ok"]:
            room = result["room"]
            msg = await smart_edit(callback, _ttt_text(room, callback.from_user.id), reply_markup=_ttt_kb(room))
            if msg:
                room = await _remember_ttt_message(room, callback.from_user.id, msg)
                await set_last_menu_msg_id(callback.from_user.id, msg.message_id)
            other_id = room.get("opponent_id") if callback.from_user.id == room["creator_id"] else room["creator_id"]
            if other_id and not result.get("already_in_room"):
                await _sync_ttt_player(callback.bot, room, other_id)
            return
        errors = {
            "not_available": "Комната уже недоступна или не найдена.",
            "not_enough": "Не хватает зефирок для ставки.",
        }
        msg = await smart_edit(callback, f"❌ {errors.get(result.get('error'), 'Не удалось войти в комнату.')}", reply_markup=_games_home_kb())
        if msg:
            await set_last_menu_msg_id(callback.from_user.id, msg.message_id)
        return

    if target == "market":
        from bot.handlers.economy import _market_kb, _money
        from bot.services.economy_service import RARITY_ICONS, list_market
        import html

        listings = await list_market(limit=10)
        if listings:
            lines = ["🏪 <b>Рынок</b>\n"]
            for item in listings:
                lines.append(
                    f"#{item['id']} · {RARITY_ICONS.get(item['rarity'], '▫️')} "
                    f"<b>{html.escape(item['name'])}</b> — <b>{_money(item['price'])}</b> 🍬"
                )
            text = "\n".join(lines)
        else:
            text = "🏪 <b>Рынок</b>\n\nАктивных лотов пока нет."
        msg = await smart_edit(callback, text, reply_markup=_market_kb(listings))
    elif target == "shop":
        from bot.handlers.shop import _shop_kb, _shop_text

        text, offers, daily = await _shop_text(callback.from_user.id)
        msg = await smart_edit(callback, text, reply_markup=_shop_kb(offers, daily))
    elif target == "inventory":
        from bot.handlers.economy import _inventory_kb, item_label
        from bot.services.economy_service import get_inventory

        items = await get_inventory(callback.from_user.id)
        text = "🎒 <b>Инвентарь</b>\n\n"
        text += "\n".join(f"{item_label(item)} x<b>{item['quantity']}</b>" for item in items[:20]) if items else "Пока пусто."
        msg = await smart_edit(callback, text, reply_markup=_inventory_kb(items))
    elif target == "cases":
        from bot.handlers.economy import _cases_kb, _money
        from bot.models import get_zefirki_balance
        from bot.services.economy_service import list_cases

        cases = await list_cases()
        balance = await get_zefirki_balance(callback.from_user.id)
        msg = await smart_edit(
            callback,
            f"📦 <b>Кейсы</b>\n\nБаланс: <b>{_money(balance)}</b> 🍬",
            reply_markup=_cases_kb(cases),
        )
    elif target == "pet":
        from bot.handlers.pet import _pet_kb, _pet_text, _species_kb
        from bot.services.pet_service import get_pet, list_pets

        pet = await get_pet(callback.from_user.id)
        pets = await list_pets(callback.from_user.id)
        if pet:
            msg = await smart_edit(callback, _pet_text(pet), reply_markup=_pet_kb(pets))
        else:
            msg = await smart_edit(
                callback,
                "🐾 <b>Выбор питомца</b>\n\nДля начала выбери первого спутника.",
                reply_markup=_species_kb(),
            )
    elif target == "games":
        from bot.handlers.games import _games_home_kb

        msg = await smart_edit(
            callback,
            "🎮 <b>Игры</b>\n\nВыбирай режим: с ботом или с игроками.",
            reply_markup=_games_home_kb(),
        )
    elif target.startswith("game_"):
        from bot.handlers.games import GAME_LABELS, _mode_kb

        game_type = target.removeprefix("game_")
        msg = await smart_edit(
            callback,
            f"👥 <b>{GAME_LABELS.get(game_type, game_type)}</b>\n\nВыбери режим комнаты.",
            reply_markup=_mode_kb(game_type),
        )
    elif target == "weather" and state:
        from bot.handlers.weather import WeatherStates, _ask_kb

        msg = await smart_edit(callback, "⛅ <b>Погода</b>\n\nВведи название города:", reply_markup=_ask_kb())
        await state.set_state(WeatherStates.waiting_city)
        if msg:
            await state.update_data(prompt_msg_id=msg.message_id)
    elif target == "convert" and state:
        from bot.handlers.currency import _pick_keyboard

        await state.clear()
        msg = await smart_edit(
            callback,
            "💱 <b>Конвертер валют</b>\n\nКурсы от ЦБ РФ, обновляются раз в сутки.\n\n<b>Из какой валюты</b> конвертируем?",
            reply_markup=_pick_keyboard("from"),
        )
    elif target == "qr" and state:
        from bot.handlers.qr import QRStates, MAX_QR_LEN, _ask_kb

        msg = await smart_edit(
            callback,
            "🔳 <b>QR-генератор</b>\n\n"
            "Пришли текст или ссылку — сделаю QR-код.\n"
            f"<i>До {MAX_QR_LEN} символов.</i>",
            reply_markup=_ask_kb(),
        )
        await state.set_state(QRStates.waiting_text)
        if msg:
            await state.update_data(prompt_msg_id=msg.message_id)
    elif target in {"utils", "ai"}:
        msg = await smart_edit(callback, UTILS_TEXT, reply_markup=utilities_submenu())
    elif target == "profile":
        from bot.keyboards.inline import profile_menu

        msg = await smart_edit(callback, "👤 <b>Профиль</b>\n\nОткрой профиль из меню ниже.", reply_markup=profile_menu())
    else:
        msg = await smart_edit(callback, FUN_TEXT, reply_markup=fun_submenu())
    if msg:
        await set_last_menu_msg_id(callback.from_user.id, msg.message_id)


@router.callback_query(F.data.startswith("funconsent:show"))
async def cb_fun_consent_show(callback: CallbackQuery):
    target = _consent_target(callback.data)
    new_msg = await smart_edit(callback, FUN_CONSENT_INTRO, reply_markup=fun_consent_menu(target))
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("funconsent:tos"))
async def cb_fun_consent_tos(callback: CallbackQuery):
    target = _consent_target(callback.data)
    await smart_edit(
        callback,
        f"{FUN_TOS_TEXT}\n\n<i>{FUN_CONSENT_EFFECTIVE_TEXT}</i>",
        reply_markup=fun_consent_back(target),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("funconsent:privacy"))
async def cb_fun_consent_privacy(callback: CallbackQuery):
    target = _consent_target(callback.data)
    await smart_edit(
        callback,
        f"{FUN_PRIVACY_TEXT}\n\n<i>{FUN_CONSENT_EFFECTIVE_TEXT}</i>",
        reply_markup=fun_consent_back(target),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("funconsent:accept"))
async def cb_fun_consent_accept(callback: CallbackQuery, state: FSMContext):
    target = _consent_target(callback.data)
    await accept_consent(callback.from_user.id, FUN_CONSENT_VERSION, fun_docs_hash())
    await _render_after_fun_consent(callback, target, state)
    await callback.answer("Соглашение принято")


@router.callback_query(F.data == "funconsent:decline")
async def cb_fun_consent_decline(callback: CallbackQuery):
    text = await _welcome_text(callback.from_user.id, callback.from_user.first_name)
    new_msg = await smart_edit(callback, text, reply_markup=main_menu())
    if new_msg:
        await set_last_menu_msg_id(callback.from_user.id, new_msg.message_id)
    await callback.answer("Развлечения закрыты до принятия соглашения")
