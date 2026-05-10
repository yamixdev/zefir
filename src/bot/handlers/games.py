import asyncio
import html
import random
from datetime import UTC, datetime

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.games_service import (
    MS_SIZE,
    cancel_ttt_room,
    create_ttt_room,
    join_ttt_room,
    list_user_active_games,
    list_waiting_ttt_rooms,
    minesweeper_cell_text,
    open_minesweeper_cell,
    play_dice,
    play_guess_number,
    set_ttt_message,
    start_minesweeper,
    ttt_move,
)
from bot.services.game_logic import (
    RPS_CHOICES,
    card_labels,
    dice_result,
    guess_hangman_letter,
    hand_value,
    is_blackjack,
    mines_cell_label,
    mines_open,
    render_hangman_word,
    rps_winner,
    ttt_apply_move,
    ttt_bot_move,
    ttt_winner,
)
from bot.services.game_session_service import (
    add_chat_message,
    activate_due_duel_signals,
    cancel_session,
    create_session,
    display_name,
    expire_session_by_id,
    finish_session,
    get_session,
    handle_session_action,
    join_session,
    load_quiz_questions,
    list_my_sessions,
    list_open_sessions,
    set_session_message,
    start_session,
)
from bot.services.rating_service import claim_season_reward, get_ranked_leaderboard
from bot.utils import render_clean_message, smart_edit

router = Router()


class GameStates(StatesGroup):
    waiting_room_code = State()
    waiting_game_message = State()


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _games_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤖 С ботом", callback_data="games:bot"),
            InlineKeyboardButton(text="👥 С игроками", callback_data="games:pvp"),
        ],
        [
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="games:rating"),
            InlineKeyboardButton(text="📜 Активные", callback_data="games:active"),
        ],
        [InlineKeyboardButton(text="🚪 Войти по коду", callback_data="game:ttt:join_code")],
        [InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun")],
    ])


def _bot_games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💣 Сапёр", callback_data="games:bot:ms"),
            InlineKeyboardButton(text="🎲 Кости", callback_data="games:bot:dice"),
        ],
        [
            InlineKeyboardButton(text="⭕ Крестики-нолики", callback_data="gamebot:ttt"),
            InlineKeyboardButton(text="🔢 Угадай число", callback_data="games:bot:guess"),
        ],
        [InlineKeyboardButton(text="🃏 Blackjack", callback_data="games:bot:bj")],
        [InlineKeyboardButton(text="⬅️ Игры", callback_data="games:home")],
    ])


def _pvp_games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭕ Крестики", callback_data="games:pvp:create:ttt"),
            InlineKeyboardButton(text="🪨 RPS", callback_data="games:pvp:create:rps"),
        ],
        [
            InlineKeyboardButton(text="🤠 Дуэль", callback_data="games:pvp:create:duel"),
            InlineKeyboardButton(text="🎲 Кости", callback_data="games:pvp:create:dice"),
        ],
        [
            InlineKeyboardButton(text="💣 Сапёр", callback_data="games:pvp:create:mines"),
            InlineKeyboardButton(text="🧠 Викторина", callback_data="games:pvp:create:quiz"),
        ],
        [
            InlineKeyboardButton(text="🔤 Виселица", callback_data="games:pvp:create:hangman"),
            InlineKeyboardButton(text="🃏 Blackjack", callback_data="games:pvp:create:blackjack"),
        ],
        [InlineKeyboardButton(text="🚪 Открытые комнаты", callback_data="games:sessions:list")],
        [InlineKeyboardButton(text="🔑 Ввести код", callback_data="game:ttt:join_code")],
        [InlineKeyboardButton(text="⬅️ Игры", callback_data="games:home")],
    ])


GAME_LABELS = {
    "ttt": "Крестики-нолики",
    "rps": "Камень-ножницы-бумага",
    "duel": "Быстрая дуэль",
    "dice": "Кости",
    "mines": "Сапёр-дуэль",
    "quiz": "Викторина",
    "hangman": "Виселица",
    "blackjack": "Blackjack",
    "ttt_bot": "Крестики-нолики с ботом",
}


RANKED_TYPES = {"ttt", "rps", "duel", "blackjack", "quiz"}


def _mode_kb(game_type: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="Без ставки", callback_data=f"games:create:{game_type}:free")]]
    rows.append([InlineKeyboardButton(text="Со ставкой", callback_data=f"games:create:{game_type}:stake")])
    if game_type in RANKED_TYPES:
        rows.append([InlineKeyboardButton(text="🏆 Ranked", callback_data=f"games:create:{game_type}:ranked")])
    rows.append([InlineKeyboardButton(text="⬅️ Игры с игроками", callback_data="games:pvp")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _stake_kb(game_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="25 🍬", callback_data=f"games:create:{game_type}:stake:25"),
            InlineKeyboardButton(text="50 🍬", callback_data=f"games:create:{game_type}:stake:50"),
            InlineKeyboardButton(text="100 🍬", callback_data=f"games:create:{game_type}:stake:100"),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"games:pvp:create:{game_type}")],
    ])


def _quiz_count_kb(mode: str, stake: int = 0) -> InlineKeyboardMarkup:
    token = f"stake:{stake}" if mode == "stake" else mode
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="10", callback_data=f"games:create:quiz:{token}:count:10"),
            InlineKeyboardButton(text="15", callback_data=f"games:create:quiz:{token}:count:15"),
            InlineKeyboardButton(text="20", callback_data=f"games:create:quiz:{token}:count:20"),
            InlineKeyboardButton(text="30", callback_data=f"games:create:quiz:{token}:count:30"),
        ],
        [InlineKeyboardButton(text="⬅️ Режим", callback_data="games:pvp:create:quiz")],
    ])


def _bot_stake_kb(kind: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без ставки", callback_data=f"games:botrun:{kind}:0")],
        [
            InlineKeyboardButton(text="25 🍬", callback_data=f"games:botrun:{kind}:25"),
            InlineKeyboardButton(text="50 🍬", callback_data=f"games:botrun:{kind}:50"),
            InlineKeyboardButton(text="100 🍬", callback_data=f"games:botrun:{kind}:100"),
        ],
        [InlineKeyboardButton(text="⬅️ С ботом", callback_data="games:bot")],
    ])


def _bot_blackjack_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Без ставки", callback_data="gamebot:blackjack:0")],
        [
            InlineKeyboardButton(text="25 🍬", callback_data="gamebot:blackjack:25"),
            InlineKeyboardButton(text="50 🍬", callback_data="gamebot:blackjack:50"),
            InlineKeyboardButton(text="100 🍬", callback_data="gamebot:blackjack:100"),
        ],
        [InlineKeyboardButton(text="⬅️ С ботом", callback_data="games:bot")],
    ])


@router.callback_query(F.data == "games:home")
async def cb_games_home(callback: CallbackQuery):
    text = (
        "🎮 <b>Игры</b>\n\n"
        "Выбирай режим: с ботом, с игроками или ranked-таблицу. "
        "Ставки включаются отдельным шагом, чтобы меню не было перегружено."
    )
    await smart_edit(callback, text, reply_markup=_games_home_kb())
    await callback.answer()


@router.callback_query(F.data == "games:bot")
async def cb_games_bot(callback: CallbackQuery):
    text = (
        "🤖 <b>Игры с ботом</b>\n\n"
        "Сапёр и кости можно запускать без ставки или на зефирки. "
        "Крестики-нолики идут без ставки, Blackjack можно запустить отдельно."
    )
    await smart_edit(callback, text, reply_markup=_bot_games_kb())
    await callback.answer()


@router.callback_query(F.data == "games:pvp")
async def cb_games_pvp(callback: CallbackQuery):
    text = (
        "👥 <b>Игры с игроками</b>\n\n"
        "Выбери игру, затем режим: без ставки, со ставкой или ranked. "
        "После создания отправь другу код комнаты."
    )
    await smart_edit(callback, text, reply_markup=_pvp_games_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("games:bot:"))
async def cb_bot_pick(callback: CallbackQuery):
    kind = callback.data.split(":")[2]
    if kind == "guess":
        text = "🔢 <b>Угадай число</b>\n\nВыбери число от 1 до 5. Игра без ставки."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1", callback_data="game:guess:1:0"),
                InlineKeyboardButton(text="2", callback_data="game:guess:2:0"),
                InlineKeyboardButton(text="3", callback_data="game:guess:3:0"),
                InlineKeyboardButton(text="4", callback_data="game:guess:4:0"),
                InlineKeyboardButton(text="5", callback_data="game:guess:5:0"),
            ],
            [InlineKeyboardButton(text="⬅️ С ботом", callback_data="games:bot")],
        ])
    elif kind == "bj":
        text = (
            "🃏 <b>Blackjack с ботом</b>\n\n"
            "Цель — набрать ближе к 21, но не больше. Дилер добирает карты до 17.\n\n"
            "<b>Честность:</b> колода перемешивается случайно при старте партии. "
            "В коде нет подкрутки под игрока или админа, повлиять на карты вручную нельзя.\n\n"
            "<b>Ставка:</b> победа выплачивает x2, ничья возвращает ставку, проигрыш сжигает ставку."
        )
        kb = _bot_blackjack_kb()
    else:
        label = "Сапёр" if kind == "ms" else "Кости"
        text = f"🤖 <b>{label}</b>\n\nВыбери режим запуска."
        kb = _bot_stake_kb(kind)
    await smart_edit(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("games:botrun:"))
async def cb_bot_run(callback: CallbackQuery):
    _, _, kind, stake_raw = callback.data.split(":")
    stake = int(stake_raw)
    if kind == "ms":
        result = await start_minesweeper(callback.from_user.id, stake)
        if not result["ok"]:
            await callback.answer("Не хватает зефирок для ставки.", show_alert=True)
            return
        game = result["game"]
        text = (
            "💣 <b>Сапёр</b>\n\n"
            f"Ставка: <b>{_money(game['stake'])}</b> 🍬\n"
            "Поле 4x4, внутри 3 мины. Открой все безопасные клетки."
        )
        await smart_edit(callback, text, reply_markup=_ms_kb(game))
    elif kind == "dice":
        result = await play_dice(callback.from_user.id, stake)
        if not result["ok"]:
            await callback.answer("Не хватает зефирок для ставки.", show_alert=True)
            return
        status = {"won": "🏆 Победа", "lost": "😿 Проигрыш", "draw": "🤝 Ничья"}[result["status"]]
        text = (
            f"🎲 <b>Кости</b>\n\n"
            f"Ты: <b>{result['player']}</b>\n"
            f"Бот: <b>{result['bot']}</b>\n\n"
            f"{status}\n"
            f"Выплата: <b>{_money(result['payout'])}</b> 🍬"
        )
        await smart_edit(callback, text, reply_markup=_bot_games_kb())
    await callback.answer()


@router.callback_query(F.data == "gamebot:ttt")
async def cb_ttt_bot_new(callback: CallbackQuery):
    result = await create_session(
        "ttt_bot",
        callback.from_user,
        callback.message.chat.id,
        min_players=1,
        max_players=1,
        mode="bot",
        autostart=True,
    )
    if not result["ok"]:
        await callback.answer("Не удалось создать игру.", show_alert=True)
        return
    session = result["session"]
    msg = await smart_edit(callback, _session_text(session, callback.from_user.id), reply_markup=_session_kb(session, callback.from_user.id))
    if msg:
        await _remember_session_message(session, callback.from_user.id, msg)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^gamebot:blackjack:\d+$"))
async def cb_blackjack_bot_new(callback: CallbackQuery):
    stake = int(callback.data.split(":")[2])
    result = await create_session(
        "blackjack",
        callback.from_user,
        callback.message.chat.id,
        stake=stake,
        min_players=1,
        max_players=1,
        mode="bot",
        autostart=True,
    )
    if not result["ok"]:
        await callback.answer("Не хватает зефирок для ставки." if result.get("error") == "not_enough" else "Не удалось создать игру.", show_alert=True)
        return
    session = result["session"]
    msg = await smart_edit(callback, _session_text(session, callback.from_user.id), reply_markup=_session_kb(session, callback.from_user.id))
    if msg:
        await _remember_session_message(session, callback.from_user.id, msg)
    await callback.answer("Blackjack начался")


@router.callback_query(F.data.startswith("games:pvp:create:"))
async def cb_pvp_create_pick(callback: CallbackQuery):
    game_type = callback.data.split(":")[3]
    text = (
        f"👥 <b>{GAME_LABELS.get(game_type, game_type)}</b>\n\n"
        "Выбери режим комнаты. Ranked идёт без зефирочных ставок."
    )
    await smart_edit(callback, text, reply_markup=_mode_kb(game_type))
    await callback.answer()


@router.callback_query(F.data.regexp(r"^games:create:\w+:stake$"))
async def cb_pvp_stake_pick(callback: CallbackQuery):
    game_type = callback.data.split(":")[2]
    await smart_edit(
        callback,
        f"🍬 <b>{GAME_LABELS.get(game_type, game_type)}</b>\n\nВыбери ставку.",
        reply_markup=_stake_kb(game_type),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^games:create:\w+:(free|ranked|stake:\d+)$"))
async def cb_pvp_create(callback: CallbackQuery):
    parts = callback.data.split(":")
    game_type = parts[2]
    mode = parts[3]
    stake = int(parts[4]) if mode == "stake" and len(parts) > 4 else 0
    ranked = mode == "ranked"
    if game_type == "quiz" and not ranked:
        await smart_edit(
            callback,
            "🧠 <b>Викторина</b>\n\nСколько вопросов будет в комнате?",
            reply_markup=_quiz_count_kb(mode, stake),
        )
        await callback.answer()
        return
    quiz_count = 15 if game_type == "quiz" and ranked else None
    min_players = 1 if game_type in {"quiz", "hangman", "blackjack"} else 2
    max_players = 6 if game_type in {"quiz", "hangman", "blackjack"} else 2
    if ranked:
        min_players = 2
        max_players = 6 if game_type == "quiz" else 2
    result = await create_session(
        game_type,
        callback.from_user,
        callback.message.chat.id,
        stake=stake,
        ranked=ranked,
        min_players=min_players,
        max_players=max_players,
        quiz_count=quiz_count,
    )
    if not result["ok"]:
        await callback.answer("Не хватает зефирок для ставки." if result.get("error") == "not_enough" else "Не удалось создать комнату.", show_alert=True)
        return
    session = result["session"]
    msg = await smart_edit(callback, _session_text(session, callback.from_user.id), reply_markup=_session_kb(session, callback.from_user.id))
    if msg:
        await _remember_session_message(session, callback.from_user.id, msg)
    await callback.answer(f"Комната создана: {session['id']}", show_alert=True)


@router.callback_query(F.data.regexp(r"^games:create:quiz:(free|stake:\d+):count:\d+$"))
async def cb_pvp_create_quiz_count(callback: CallbackQuery):
    parts = callback.data.split(":")
    token = parts[3]
    stake = int(parts[4]) if token == "stake" else 0
    count = int(parts[-1])
    result = await create_session(
        "quiz",
        callback.from_user,
        callback.message.chat.id,
        stake=stake,
        ranked=False,
        min_players=1,
        max_players=6,
        quiz_count=count,
    )
    if not result["ok"]:
        await callback.answer("Не хватает зефирок для ставки." if result.get("error") == "not_enough" else "Не удалось создать комнату.", show_alert=True)
        return
    session = result["session"]
    msg = await smart_edit(callback, _session_text(session, callback.from_user.id), reply_markup=_session_kb(session, callback.from_user.id))
    if msg:
        await _remember_session_message(session, callback.from_user.id, msg)
    await callback.answer(f"Комната создана: {session['id']}", show_alert=True)


@router.callback_query(F.data == "games:sessions:list")
async def cb_sessions_list(callback: CallbackQuery):
    sessions = await list_open_sessions(limit=10)
    kb = InlineKeyboardBuilder()
    if not sessions:
        text = "🚪 <b>Открытые комнаты</b>\n\nПока пусто. Создай свою комнату."
    else:
        lines = ["🚪 <b>Открытые комнаты</b>\n"]
        for session in sessions:
            label = GAME_LABELS.get(session["game_type"], session["game_type"])
            owner = session.get("first_name") or session.get("username") or str(session["creator_id"])
            mode = "ranked" if session["ranked"] else (f"{_money(session['stake'])} 🍬" if session["stake"] else "без ставки")
            lines.append(f"<code>{session['id']}</code> · {label} · {owner} · {mode}")
            kb.row(InlineKeyboardButton(text=f"Войти {session['id']} · {label}", callback_data=f"game:{session['id']}:join:x"))
        text = "\n".join(lines)
    kb.row(InlineKeyboardButton(text="⬅️ Игры с игроками", callback_data="games:pvp"))
    await smart_edit(callback, text, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data == "games:rating")
async def cb_games_rating(callback: CallbackQuery):
    data = await get_ranked_leaderboard(10)
    season = data["season"]
    rows = data["rows"]
    lines = [
        "🏆 <b>Ranked-рейтинг</b>",
        f"Сезон до: <b>{season['ends_at'].strftime('%d.%m.%Y')}</b>",
        f"Награды доступны после сезона при {config.ranked_min_reward_games}+ играх.\n",
    ]
    if not rows:
        lines.append("Пока рейтинга нет.")
    for row in rows:
        name = row.get("first_name") or row.get("username") or str(row["user_id"])
        lines.append(
            f"{row['place']}. <b>{html.escape(name)}</b> — <b>{row['elo']}</b> ELO "
            f"({row['wins']}/{row['losses']}/{row['draws']})"
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Забрать награду сезона", callback_data="games:rating:claim")],
        [InlineKeyboardButton(text="⬅️ Игры", callback_data="games:home")],
    ])
    await smart_edit(callback, "\n".join(lines), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "games:rating:claim")
async def cb_games_rating_claim(callback: CallbackQuery):
    result = await claim_season_reward(callback.from_user.id)
    if not result["ok"]:
        errors = {
            "no_finished_season": "Сезон ещё не закончился.",
            "not_eligible": "Нужно сыграть минимум 3 ranked-игры за сезон.",
            "already_claimed": "Ты уже забрал награду за этот сезон.",
        }
        await callback.answer(errors.get(result.get("error"), "Награда пока недоступна."), show_alert=True)
        return
    item_line = f"\nПредмет: <b>{html.escape(result['item']['name'])}</b>" if result.get("item") else ""
    await callback.answer(f"Получено: +{_money(result['amount'])} 🍬", show_alert=True)
    await smart_edit(
        callback,
        f"🎁 <b>Награда сезона</b>\n\nЗефирки: <b>+{_money(result['amount'])}</b> 🍬{item_line}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏆 Рейтинг", callback_data="games:rating")]]),
    )


@router.callback_query(F.data == "games:active")
async def cb_games_active(callback: CallbackQuery):
    data = await list_user_active_games(callback.from_user.id)
    sessions = await list_my_sessions(callback.from_user.id)
    lines = ["📜 <b>Мои активные игры</b>\n"]
    if not data["pve"] and not data["rooms"] and not sessions:
        lines.append("Активных игр нет.")
    for session in sessions:
        label = GAME_LABELS.get(session["game_type"], session["game_type"])
        mode = "ranked" if session["ranked"] else (f"{_money(session['stake'])} 🍬" if session["stake"] else "без ставки")
        lines.append(f"🎮 <code>{session['id']}</code> · {label} · {session['status']} · {mode}")
    for game in data["pve"]:
        lines.append(f"🤖 {game['game_type']} #{game['id']} · ставка {_money(game['stake'])} 🍬")
    for room in data["rooms"]:
        lines.append(f"👥 {room['game_type']} #{room['id']} · {room['status']} · ставка {_money(room['stake'])} 🍬")
    await smart_edit(callback, "\n".join(lines), reply_markup=_games_home_kb())
    await callback.answer()


@router.message(Command("games"))
async def cmd_games(message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    text = (
        "🎮 <b>Игры</b>\n\n"
        "Выбирай сапёра против бота или PvP-комнату в крестики-нолики."
    )
    await render_clean_message(bot, message.chat.id, message.from_user.id, text, reply_markup=_games_home_kb())


@router.message(Command("rps", "duel", "quiz", "hangman", "blackjack"))
async def cmd_quick_game(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    cmd = (message.text or "").split(maxsplit=1)[0].lstrip("/").split("@", 1)[0].lower()
    game_type = {"rps": "rps", "duel": "duel", "quiz": "quiz", "hangman": "hangman", "blackjack": "blackjack"}[cmd]
    await render_clean_message(
        bot,
        message.chat.id,
        message.from_user.id,
        f"👥 <b>{GAME_LABELS[game_type]}</b>\n\nВыбери режим комнаты.",
        reply_markup=_mode_kb(game_type),
    )


def _is_session_player(session: dict, user_id: int) -> bool:
    return any(p["user_id"] == user_id for p in session.get("players", []))


def _session_player(session: dict, user_id: int) -> dict | None:
    return next((p for p in session.get("players", []) if p["user_id"] == user_id), None)


def _players_text(session: dict) -> str:
    players = session.get("players", [])
    if not players:
        return "Игроков пока нет."
    return "\n".join(f"{i}. {html.escape(display_name(p))}" for i, p in enumerate(players, 1))


def _session_mode_text(session: dict) -> str:
    if session.get("ranked"):
        return "🏆 ranked"
    if session.get("stake"):
        return f"ставка {_money(session['stake'])} 🍬"
    return "без ставки"


def _chat_text(session: dict) -> str:
    chat = session.get("chat") or []
    if not chat:
        return ""
    lines = ["\n<b>Сообщения:</b>"]
    for msg in chat[-10:]:
        lines.append(f"{html.escape(msg['display_name'])}: {html.escape(msg['text'])}")
    return "\n".join(lines)


def _rps_name(choice: str | None) -> str:
    return {
        "rock": "🪨 Камень",
        "scissors": "✂️ Ножницы",
        "paper": "📄 Бумага",
    }.get(choice or "", "выбирает")


def _quiz_sorted_scores(session: dict) -> list[tuple[dict, int, int]]:
    state = session.get("state") or {}
    scores = state.get("scores") or {}
    response_ms = state.get("total_response_ms") or {}
    rows = []
    for player in session.get("players") or []:
        uid = str(player["user_id"])
        rows.append((player, int(scores.get(uid, 0)), int(response_ms.get(uid, 0))))
    return sorted(rows, key=lambda row: (-row[1], row[2], row[0]["seat"]))


def _quiz_final_places(session: dict, use_speed: bool = False) -> list[dict]:
    rows = _quiz_sorted_scores(session)
    out = []
    current_place = 0
    last_key = None
    for index, (player, score, response_ms) in enumerate(rows, start=1):
        key = (score, response_ms) if use_speed else (score,)
        if key != last_key:
            current_place = index
            last_key = key
        out.append({
            "user_id": player["user_id"],
            "place": current_place,
            "score": score,
            "response_ms": response_ms,
        })
    return out


def _quiz_top_ids(session: dict, use_speed: bool = False) -> list[int]:
    rows = _quiz_sorted_scores(session)
    if not rows:
        return []
    top_score = rows[0][1]
    if top_score <= 0:
        return []
    if not use_speed:
        return [row[0]["user_id"] for row in rows if row[1] == top_score]
    top_ms = rows[0][2]
    return [row[0]["user_id"] for row in rows if row[1] == top_score and row[2] == top_ms]


def _session_text(session: dict, viewer_id: int) -> str:
    label = GAME_LABELS.get(session["game_type"], session["game_type"])
    if session["status"] == "waiting":
        return (
            f"🎮 <b>{label}</b>\n\n"
            f"Код комнаты: <code>{session['id']}</code> или <code>/join {session['id']}</code>\n"
            f"Режим: <b>{_session_mode_text(session)}</b>\n\n"
            f"<b>Игроки:</b>\n{_players_text(session)}\n\n"
            f"Нужно игроков: <b>{session['min_players']}</b>"
        )
    if session["status"] in ("finished", "draw", "cancelled", "expired"):
        status = {
            "finished": "🏁 Игра окончена",
            "draw": "🤝 Ничья",
            "cancelled": "Комната отменена",
            "expired": "⏳ Игра закрыта из-за бездействия",
        }.get(session["status"], "Игра завершена")
        winner = ""
        if session.get("winner_id"):
            player = _session_player(session, session["winner_id"])
            winner = f"\nПобедитель: <b>{html.escape(display_name(player)) if player else session['winner_id']}</b>"
        if session["game_type"] == "quiz":
            places = (session.get("state") or {}).get("final_places") or _quiz_final_places(session)
            if places:
                by_id = {p["user_id"]: p for p in session.get("players") or []}
                rows = ["\n\n<b>Итоги:</b>"]
                for place in places:
                    player = by_id.get(place["user_id"])
                    name = html.escape(display_name(player)) if player else str(place["user_id"])
                    rows.append(f"{place['place']}. {name} — <b>{place['score']}</b>")
                winner += "\n".join(rows)
        return f"🎮 <b>{label}</b>\n\n{status}{winner}{_chat_text(session)}"

    state = session.get("state") or {}
    players = session.get("players") or []
    text = f"🎮 <b>{label}</b> · <code>{session['id']}</code>\nРежим: <b>{_session_mode_text(session)}</b>\n\n"
    if session["game_type"] in ("ttt", "ttt_bot"):
        board = state.get("board", ".........")
        turn = session.get("current_turn_id")
        lines = [" ".join(_ttt_mark(board[r * 3 + c]) for c in range(3)) for r in range(3)]
        text += "\n".join(lines)
        if session["game_type"] == "ttt_bot":
            text += "\n\nТы играешь за ❌. Бот играет за ⭕."
        if turn:
            player = _session_player(session, turn)
            text += f"\n\nХодит: <b>{html.escape(display_name(player)) if player else turn}</b>"
    elif session["game_type"] == "rps":
        choices = state.get("choices") or {}
        for player in players:
            chosen = "✅ выбрал" if str(player["user_id"]) in choices else "⏳ думает"
            text += f"{html.escape(display_name(player))}: {chosen}\n"
        if len(choices) >= 2:
            text += "\nОба выбора получены."
    elif session["game_type"] == "duel":
        phase = state.get("phase")
        if phase != "active":
            text += "🤠 Дуэль начинается...\nНе нажимай раньше сигнала. Жди: <b>СТРЕЛЯЙ!</b>"
        else:
            text += "🔥 <b>СТРЕЛЯЙ!</b>"
    elif session["game_type"] == "dice":
        rolls = state.get("rolls") or {}
        for player in players:
            val = rolls.get(str(player["user_id"]))
            text += f"{html.escape(display_name(player))}: <b>{val}</b>\n" if val else f"{html.escape(display_name(player))}: ждёт броска\n"
    elif session["game_type"] == "quiz":
        questions = state.get("questions") or []
        idx = int(state.get("index") or 0)
        scores = state.get("scores") or {}
        answered = state.get("answered") or {}
        if idx < len(questions):
            q = questions[idx]
            tag = " · tie-break" if q.get("tiebreaker") else ""
            ai_tag = " · AI" if q.get("ai_generated") else ""
            text += f"Вопрос <b>{idx + 1}/{len(questions)}</b>{tag}{ai_tag}\n{html.escape(q['text'])}\n\n"
            for i, option in enumerate(q["options"]):
                text += f"{chr(65 + i)}. {html.escape(option)}\n"
            text += f"\nОтветили: <b>{len(answered)}/{len(players)}</b>\n"
        if scores:
            text += "\n<b>Очки:</b>\n"
            for player, score, _ in _quiz_sorted_scores(session):
                marker = " · ответил" if str(player["user_id"]) in answered else ""
                text += f"{html.escape(display_name(player))}: <b>{score}</b>{marker}\n"
    elif session["game_type"] == "hangman":
        text += (
            f"Слово: <b>{render_hangman_word(state)}</b>\n"
            f"Ошибки: <b>{state.get('wrong', 0)}/{state.get('max_wrong', 6)}</b>\n"
            f"Буквы: {', '.join((state.get('used') or [])) or 'нет'}"
        )
    elif session["game_type"] == "blackjack":
        dealer = state.get("dealer") or []
        phase = state.get("phase")
        shown_dealer = dealer if phase == "finished" else dealer[:1]
        text += f"Дилер: {card_labels(shown_dealer)}"
        if phase == "finished":
            text += f" = <b>{hand_value(dealer)}</b>"
        else:
            text += " [?]"
        text += "\n\n"
        pst = state.get("players") or {}
        for player in players:
            pstate = pst.get(str(player["user_id"]), {})
            hand = pstate.get("hand") or []
            text += f"{html.escape(display_name(player))}: {card_labels(hand)} = <b>{hand_value(hand)}</b> · {pstate.get('status', 'playing')}\n"
        if session.get("current_turn_id"):
            player = _session_player(session, session["current_turn_id"])
            text += f"\nХодит: <b>{html.escape(display_name(player)) if player else session['current_turn_id']}</b>"
    elif session["game_type"] == "mines":
        board = (state.get("boards") or {}).get(str(viewer_id))
        if board:
            size = int(board.get("size") or 4)
            reveal = board.get("status") in ("lost", "won") or session["status"] != "running"
            text += "Твоё поле:\n"
            for r in range(size):
                text += " ".join(mines_cell_label(board, r * size + c, reveal) for c in range(size)) + "\n"
            text += "\nПервый, кто очистит поле, побеждает. Мина — поражение."
    text += _chat_text(session)
    return text


def _session_kb(session: dict, viewer_id: int) -> InlineKeyboardMarkup:
    if session["status"] == "waiting":
        rows = []
        if not _is_session_player(session, viewer_id):
            rows.append([InlineKeyboardButton(text="✅ Присоединиться", callback_data=f"game:{session['id']}:join:x")])
        if session["creator_id"] == viewer_id and len(session.get("players", [])) >= session["min_players"]:
            rows.append([InlineKeyboardButton(text="▶️ Начать", callback_data=f"game:{session['id']}:start:x")])
        if session["creator_id"] == viewer_id:
            rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data=f"game:{session['id']}:cancel:x")])
        rows.append([InlineKeyboardButton(text="⬅️ Игры", callback_data="games:home")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    if session["status"] != "running":
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 Игры", callback_data="games:home")]])

    rows = []
    state = session.get("state") or {}
    game_type = session["game_type"]
    if game_type in ("ttt", "ttt_bot"):
        board = state.get("board", ".........")
        for r in range(3):
            row = []
            for c in range(3):
                idx = r * 3 + c
                row.append(InlineKeyboardButton(text=_ttt_mark(board[idx]), callback_data=f"game:{session['id']}:ttt:{idx}"))
            rows.append(row)
    elif game_type == "rps":
        rows.append([
            InlineKeyboardButton(text="🪨 Камень", callback_data=f"game:{session['id']}:rps:rock"),
            InlineKeyboardButton(text="✂️ Ножницы", callback_data=f"game:{session['id']}:rps:scissors"),
        ])
        rows.append([InlineKeyboardButton(text="📄 Бумага", callback_data=f"game:{session['id']}:rps:paper")])
    elif game_type == "duel":
        rows.append([InlineKeyboardButton(text="🔫 Стрелять", callback_data=f"game:{session['id']}:duel:shoot")])
    elif game_type == "dice":
        rows.append([InlineKeyboardButton(text="🎲 Бросить", callback_data=f"game:{session['id']}:dice:roll")])
    elif game_type == "quiz":
        questions = state.get("questions") or []
        idx = int(state.get("index") or 0)
        if idx < len(questions):
            rows.append([
                InlineKeyboardButton(text=chr(65 + i), callback_data=f"game:{session['id']}:quiz:{i}")
                for i in range(len(questions[idx]["options"]))
            ])
            if str(viewer_id) in (state.get("answered") or {}):
                rows.append([InlineKeyboardButton(text="🧠 Уточнить ответ", callback_data=f"game:{session['id']}:quizai:x")])
            if session["creator_id"] == viewer_id:
                rows.append([InlineKeyboardButton(text="➡️ Следующий вопрос", callback_data=f"game:{session['id']}:quiznext:x")])
    elif game_type == "hangman":
        letters = list("абвгдежзийклмнопрстуфхцчшщьыэюя")
        for i in range(0, len(letters), 6):
            rows.append([
                InlineKeyboardButton(text=letter.upper(), callback_data=f"game:{session['id']}:hm:{letter}")
                for letter in letters[i:i + 6]
            ])
    elif game_type == "blackjack":
        if session.get("current_turn_id") == viewer_id:
            rows.append([
                InlineKeyboardButton(text="➕ Взять", callback_data=f"game:{session['id']}:bj:hit"),
                InlineKeyboardButton(text="✋ Стоп", callback_data=f"game:{session['id']}:bj:stand"),
            ])
    elif game_type == "mines":
        board = (state.get("boards") or {}).get(str(viewer_id))
        if board and board.get("status") == "active":
            size = int(board.get("size") or 4)
            for r in range(size):
                rows.append([
                    InlineKeyboardButton(text=mines_cell_label(board, r * size + c), callback_data=f"game:{session['id']}:mine:{r * size + c}")
                    for c in range(size)
                ])
    if session.get("mode") != "bot":
        rows.append([InlineKeyboardButton(text="💬 Сообщение", callback_data=f"game:{session['id']}:chat:x")])
    rows.append([InlineKeyboardButton(text="🎮 Игры", callback_data="games:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _remember_session_message(session: dict, user_id: int, msg) -> None:
    if msg and hasattr(msg, "chat") and hasattr(msg, "message_id"):
        await set_session_message(session["id"], user_id, msg.chat.id, msg.message_id)


async def _sync_session_messages(bot: Bot, session: dict) -> None:
    fresh = await get_session(session["id"]) or session
    for msg_ref in fresh.get("messages") or []:
        try:
            await bot.edit_message_text(
                chat_id=msg_ref["chat_id"],
                message_id=msg_ref["message_id"],
                text=_session_text(fresh, msg_ref["user_id"]),
                reply_markup=_session_kb(fresh, msg_ref["user_id"]),
            )
        except Exception as e:
            if "message is not modified" in str(e).lower():
                continue
            try:
                sent = await bot.send_message(
                    msg_ref["chat_id"],
                    _session_text(fresh, msg_ref["user_id"]),
                    reply_markup=_session_kb(fresh, msg_ref["user_id"]),
                )
                await set_session_message(fresh["id"], msg_ref["user_id"], sent.chat.id, sent.message_id)
            except Exception:
                pass


def _next_player_id(session: dict, user_id: int) -> int | None:
    players = session.get("players") or []
    ids = [p["user_id"] for p in players]
    if not ids:
        return None
    if user_id not in ids:
        return ids[0]
    return ids[(ids.index(user_id) + 1) % len(ids)]


async def _finish_and_sync(callback: CallbackQuery, session_id: str, winner_id: int | None, result: str = "finished") -> dict:
    done = await finish_session(session_id, winner_id, result)
    session = done["session"]
    await _sync_session_messages(callback.bot, session)
    return session


async def process_due_game_events(bot: Bot, limit: int = 20) -> int:
    sessions = await activate_due_duel_signals(limit=limit)
    for session in sessions:
        await _sync_session_messages(bot, session)
    return len(sessions)


def _quiz_start_next_question(state_data: dict) -> dict:
    state_data["answered"] = {}
    state_data["question_started_at"] = datetime.now(UTC).isoformat()
    return state_data


def _quiz_add_tiebreaker_if_needed(session: dict, state_data: dict) -> tuple[bool, dict]:
    temp_session = dict(session)
    temp_session["state"] = state_data
    top_ids = _quiz_top_ids(temp_session)
    if len(top_ids) <= 1 or int(state_data.get("tiebreakers") or 0) >= 3:
        return False, state_data

    question = load_quiz_questions(1)[0]
    question = dict(question)
    question["tiebreaker"] = True
    questions = list(state_data.get("questions") or [])
    questions.append(question)
    state_data["questions"] = questions
    state_data["index"] = len(questions) - 1
    state_data["tiebreakers"] = int(state_data.get("tiebreakers") or 0) + 1
    state_data["tiebreaker_players"] = [str(uid) for uid in top_ids]
    _quiz_start_next_question(state_data)
    return True, state_data


def _quiz_finish_state(session: dict, state_data: dict) -> tuple[int | None, str, dict]:
    temp_session = dict(session)
    temp_session["state"] = state_data
    state_data["final_places"] = _quiz_final_places(temp_session, use_speed=True)
    rows = _quiz_sorted_scores(temp_session)
    if not rows or rows[0][1] <= 0:
        return None, "draw", state_data
    top_ids = _quiz_top_ids(temp_session, use_speed=True)
    if len(top_ids) == 1:
        return top_ids[0], "finished", state_data
    # Absolute tie after all tiebreakers: keep it a draw.
    return None, "draw", state_data


def _quiz_score_for_answer(state_data: dict, correct_place: int) -> tuple[int, int]:
    started_raw = state_data.get("question_started_at")
    try:
        started_at = datetime.fromisoformat(started_raw) if started_raw else datetime.now(UTC)
    except Exception:
        started_at = datetime.now(UTC)
    elapsed_ms = max(0, int((datetime.now(UTC) - started_at).total_seconds() * 1000))
    elapsed_sec = elapsed_ms / 1000
    speed_points = max(20, int(120 - elapsed_sec * 3))
    place_bonus = {1: 40, 2: 25, 3: 15}.get(correct_place, 5)
    multiplier = 2 if (state_data.get("questions") or [{}])[int(state_data.get("index") or 0)].get("tiebreaker") else 1
    return (speed_points + place_bonus) * multiplier, elapsed_ms


@router.callback_query(F.data.regexp(r"^game:[a-z0-9]{5,10}:(join|start|cancel|chat):"))
async def cb_session_control(callback: CallbackQuery, state: FSMContext):
    _, session_id, action, _ = callback.data.split(":", 3)
    if action == "join":
        result = await join_session(session_id, callback.from_user)
        if not result["ok"]:
            errors = {
                "not_available": "Комната уже недоступна.",
                "expired": "Комната закрыта из-за бездействия.",
                "full": "Комната уже заполнена.",
                "already_started": "Игра уже началась.",
                "not_enough": "Не хватает зефирок для ставки.",
            }
            await callback.answer(errors.get(result.get("error"), "Не удалось войти."), show_alert=True)
            return
        session = result["session"]
        msg = await smart_edit(callback, _session_text(session, callback.from_user.id), reply_markup=_session_kb(session, callback.from_user.id))
        if msg:
            await _remember_session_message(session, callback.from_user.id, msg)
        await _sync_session_messages(callback.bot, session)
        await callback.answer("Ты уже в этой комнате" if result.get("already_in_session") else "Ты вошёл в комнату")
        return
    if action == "start":
        result = await start_session(session_id, callback.from_user.id)
        if not result["ok"]:
            await callback.answer("Начать может создатель, когда игроков достаточно.", show_alert=True)
            return
        await _sync_session_messages(callback.bot, result["session"])
        await callback.answer("Игра началась")
        return
    if action == "cancel":
        result = await cancel_session(session_id, callback.from_user.id)
        if not result["ok"]:
            await callback.answer("Отменить может только создатель до старта.", show_alert=True)
            return
        await _sync_session_messages(callback.bot, result["session"])
        await callback.answer("Комната отменена")
        return
    if action == "chat":
        session = await get_session(session_id)
        if not session or not _is_session_player(session, callback.from_user.id):
            await callback.answer("Ты не участник этой игры.", show_alert=True)
            return
        await state.set_state(GameStates.waiting_game_message)
        await state.update_data(session_id=session_id, prompt_msg_id=callback.message.message_id)
        await smart_edit(
            callback,
            f"💬 <b>Сообщение на доску</b>\n\nНапиши текст до 120 символов для комнаты <code>{session_id}</code>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data=f"game:{session_id}:noop:x")]]),
        )
        await callback.answer()


@router.callback_query(F.data.regexp(r"^game:[a-z0-9]{5,10}:(ttt|rps|duel|dice|quiz|quiznext|quizai|hm|bj|mine):"))
async def cb_session_action(callback: CallbackQuery):
    _, session_id, action, value = callback.data.split(":", 3)
    if action == "quizai":
        session = await get_session(session_id)
        if not session or session["game_type"] != "quiz":
            await callback.answer("Эта игра уже завершена.", show_alert=True)
            return
        if not _is_session_player(session, callback.from_user.id):
            await callback.answer("Ты не участник этой игры.", show_alert=True)
            return
        state_data = dict(session.get("state") or {})
        questions = state_data.get("questions") or []
        idx = int(state_data.get("index") or 0)
        answered = state_data.get("answered") or {}
        if str(callback.from_user.id) not in answered:
            await callback.answer("Сначала выбери ответ.", show_alert=True)
            return
        if idx >= len(questions):
            await callback.answer("Вопрос уже закрыт.", show_alert=True)
            return
        q = questions[idx]
        fallback = q.get("explanation") or "Пояснение для этого вопроса пока не добавлено."
        if config.quiz_ai_enabled and config.yandex_gpt_api_key:
            try:
                from bot.services.ai_service import chat_simple

                prompt = (
                    "Коротко и понятно объясни правильный ответ на вопрос викторины. "
                    "Не меняй результат игры, не спорь с вариантами, максимум 2 предложения.\n\n"
                    f"Вопрос: {q['text']}\n"
                    f"Варианты: {q['options']}\n"
                    f"Правильный вариант: {q['options'][int(q['correctIndex'])]}\n"
                    f"Пояснение из базы: {fallback}"
                )
                fallback = await chat_simple([], prompt)
            except Exception:
                pass
        await callback.answer(fallback[:190], show_alert=True)
        return

    result = await handle_session_action(session_id, callback.from_user.id, action, value)
    session = result.get("session")
    if session:
        await _sync_session_messages(callback.bot, session)
    await callback.answer(result.get("answer", "Готово"), show_alert=result.get("alert", False))


@router.callback_query(F.data.regexp(r"^game:[a-z0-9]{5,10}:noop:"))
async def cb_session_noop(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    session_id = callback.data.split(":")[1]
    session = await get_session(session_id)
    if session:
        await smart_edit(callback, _session_text(session, callback.from_user.id), reply_markup=_session_kb(session, callback.from_user.id))
    await callback.answer()


@router.message(GameStates.waiting_game_message)
async def msg_game_chat(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    session_id = data.get("session_id")
    prompt_msg_id = data.get("prompt_msg_id")
    try:
        await message.delete()
    except Exception:
        pass
    if prompt_msg_id:
        try:
            await bot.delete_message(message.chat.id, prompt_msg_id)
        except Exception:
            pass
    session = await get_session(session_id)
    await state.clear()
    if not session or not _is_session_player(session, message.from_user.id):
        return
    player = _session_player(session, message.from_user.id)
    session = await add_chat_message(session_id, message.from_user.id, display_name(player), message.text or "")
    if session:
        sent = await bot.send_message(message.chat.id, _session_text(session, message.from_user.id), reply_markup=_session_kb(session, message.from_user.id))
        await _remember_session_message(session, message.from_user.id, sent)
        await _sync_session_messages(bot, session)


def _ms_kb(game: dict, reveal_all: bool = False) -> InlineKeyboardMarkup:
    state = game["state"]
    rows = []
    for r in range(MS_SIZE):
        row = []
        for c in range(MS_SIZE):
            idx = r * MS_SIZE + c
            row.append(InlineKeyboardButton(
                text=minesweeper_cell_text(idx, state, reveal_all),
                callback_data=f"game:ms:o:{game['id']}:{idx}",
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🎮 Игры", callback_data="games:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data.startswith("game:ms:new:"))
async def cb_ms_new(callback: CallbackQuery):
    stake = int(callback.data.split(":")[3])
    result = await start_minesweeper(callback.from_user.id, stake)
    if not result["ok"]:
        await callback.answer("Не хватает зефирок для ставки.", show_alert=True)
        return
    game = result["game"]
    text = (
        "💣 <b>Сапёр</b>\n\n"
        f"Ставка: <b>{_money(game['stake'])}</b> 🍬\n"
        "Поле 4x4, внутри 3 мины. Открой все безопасные клетки."
    )
    await smart_edit(callback, text, reply_markup=_ms_kb(game))
    await callback.answer()


@router.callback_query(F.data.startswith("game:ms:o:"))
async def cb_ms_open(callback: CallbackQuery):
    _, _, _, game_id, idx = callback.data.split(":")
    result = await open_minesweeper_cell(callback.from_user.id, game_id, int(idx))
    if not result["ok"]:
        await callback.answer("Игра уже завершена или недоступна.", show_alert=True)
        return
    game = dict(result["game"])
    game["state"] = result["state"]
    status = result.get("status", game.get("status"))
    reveal_all = status in ("won", "lost")
    if status == "lost":
        text = "💥 <b>Мина!</b>\n\nСтавка сгорела. Можно попробовать ещё раз."
    elif status == "won":
        item_line = ""
        if result.get("item"):
            item_line = f"\n🎁 Предмет: <b>{result['item']['name']}</b>"
        text = (
            "🏆 <b>Победа в сапёре!</b>\n\n"
            f"Выплата: <b>{_money(result.get('payout', 0))}</b> 🍬\n"
            f"Прибыль к дневному лимиту: <b>{_money(result.get('profit', 0))}</b> 🍬"
            f"{item_line}"
        )
    else:
        text = "💣 <b>Сапёр</b>\n\nПродолжай открывать безопасные клетки."
    await smart_edit(callback, text, reply_markup=_ms_kb(game, reveal_all=reveal_all))
    await callback.answer()


@router.callback_query(F.data.startswith("game:dice:"))
async def cb_dice(callback: CallbackQuery):
    stake = int(callback.data.split(":")[2])
    result = await play_dice(callback.from_user.id, stake)
    if not result["ok"]:
        await callback.answer("Не хватает зефирок для ставки.", show_alert=True)
        return
    status = {"won": "🏆 Победа", "lost": "😿 Проигрыш", "draw": "🤝 Ничья"}[result["status"]]
    text = (
        f"🎲 <b>Кости</b>\n\n"
        f"Ты: <b>{result['player']}</b>\n"
        f"Бот: <b>{result['bot']}</b>\n\n"
        f"{status}\n"
        f"Выплата: <b>{_money(result['payout'])}</b> 🍬"
    )
    await smart_edit(callback, text, reply_markup=_bot_games_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("game:guess:"))
async def cb_guess(callback: CallbackQuery):
    _, _, guess, stake = callback.data.split(":")
    result = await play_guess_number(callback.from_user.id, int(guess), int(stake))
    if not result["ok"]:
        await callback.answer("Не хватает зефирок для ставки.", show_alert=True)
        return
    status = "🏆 Угадал" if result["status"] == "won" else "😿 Не угадал"
    text = (
        "🔢 <b>Угадай число</b>\n\n"
        f"Твой выбор: <b>{result['guess']}</b>\n"
        f"Выпало: <b>{result['secret']}</b>\n\n"
        f"{status}\n"
        f"Выплата: <b>{_money(result['payout'])}</b> 🍬"
    )
    await smart_edit(callback, text, reply_markup=_bot_games_kb())
    await callback.answer()


def _ttt_mark(mark: str) -> str:
    return {"X": "❌", "O": "⭕", ".": "▫️"}.get(mark, "▫️")


def _ttt_kb(room: dict) -> InlineKeyboardMarkup:
    rows = []
    board = room["board"]
    disabled_suffix = "x"
    for r in range(3):
        row = []
        for c in range(3):
            idx = r * 3 + c
            cb = f"game:ttt:m:{room['id']}:{idx}" if room["status"] == "active" else f"game:noop:{disabled_suffix}"
            row.append(InlineKeyboardButton(text=_ttt_mark(board[idx]), callback_data=cb))
        rows.append(row)
    if room["status"] == "waiting":
        rows.append([InlineKeyboardButton(text="❌ Отменить комнату", callback_data=f"game:ttt:cancel:{room['id']}")])
    rows.append([InlineKeyboardButton(text="🎮 Игры", callback_data="games:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _ttt_text(room: dict, viewer_id: int | None = None) -> str:
    stake = room["stake"]
    text = (
        f"⭕ <b>Крестики-нолики #{room['id']}</b>\n\n"
        f"Код для друга: <code>{room['id']}</code> или <code>/join {room['id']}</code>\n"
        f"Ставка: <b>{_money(stake)}</b> 🍬\n"
        f"❌ Создатель: <code>{room['creator_id']}</code>\n"
    )
    if room.get("opponent_id"):
        text += f"⭕ Игрок 2: <code>{room['opponent_id']}</code>\n"
    if room["status"] == "waiting":
        text += "\nЖдём второго игрока."
    elif room["status"] == "active":
        mark = "❌" if room["turn_user_id"] == room["creator_id"] else "⭕"
        text += f"\nХодит: <b>{mark}</b> <code>{room['turn_user_id']}</code>"
    elif room["status"] == "draw":
        text += "\n🤝 Ничья. Ставки возвращены."
    elif room["status"] == "finished":
        text += f"\n🏆 Победитель: <code>{room['winner_id']}</code>"
    elif room["status"] == "cancelled":
        text += "\nКомната отменена."
    return text


async def _remember_ttt_message(room: dict, user_id: int, msg) -> dict:
    if not msg or not hasattr(msg, "message_id") or not hasattr(msg, "chat"):
        return room
    updated = await set_ttt_message(room["id"], user_id, msg.chat.id, msg.message_id)
    return updated or room


async def _sync_ttt_player(bot: Bot, room: dict, user_id: int) -> dict:
    if user_id == room["creator_id"]:
        chat_id = room.get("creator_chat_id") or user_id
        message_id = room.get("creator_msg_id")
    elif user_id == room.get("opponent_id"):
        chat_id = room.get("opponent_chat_id") or user_id
        message_id = room.get("opponent_msg_id")
    else:
        return room

    if message_id:
        try:
            msg = await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=_ttt_text(room, user_id),
                reply_markup=_ttt_kb(room),
            )
            if hasattr(msg, "message_id"):
                return await _remember_ttt_message(room, user_id, msg)
            return room
        except Exception as e:
            if "message is not modified" in str(e).lower():
                return room
            pass
    sent = await bot.send_message(chat_id, _ttt_text(room, user_id), reply_markup=_ttt_kb(room))
    return await _remember_ttt_message(room, user_id, sent)


@router.callback_query(F.data.startswith("game:ttt:new:"))
async def cb_ttt_new(callback: CallbackQuery):
    stake = int(callback.data.split(":")[3])
    result = await create_ttt_room(callback.from_user.id, stake)
    if not result["ok"]:
        await callback.answer("Не хватает зефирок для ставки.", show_alert=True)
        return
    room = result["room"]
    msg = await smart_edit(callback, _ttt_text(room, callback.from_user.id), reply_markup=_ttt_kb(room))
    await _remember_ttt_message(room, callback.from_user.id, msg)
    await callback.answer(f"Комната создана: {room['id']}", show_alert=True)


@router.callback_query(F.data == "game:ttt:join_code")
async def cb_ttt_join_code(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GameStates.waiting_room_code)
    await state.update_data(prompt_msg_id=callback.message.message_id)
    await smart_edit(
        callback,
        "🔑 <b>Вход по коду</b>\n\nНапиши код комнаты. Я удалю твоё сообщение и открою игру.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="games:pvp")]
        ]),
    )
    await callback.answer()


@router.message(GameStates.waiting_room_code)
async def msg_ttt_join_code(message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    room_id = (message.text or "").strip().lower()
    try:
        await message.delete()
    except Exception:
        pass
    session = await get_session(room_id)
    if session:
        result = await join_session(room_id, message.from_user)
        await state.clear()
        if not result["ok"]:
            text = "❌ Не удалось войти. Комната не найдена, закрыта или не хватает зефирок."
            kb = _games_home_kb()
        else:
            session = result["session"]
            text = _session_text(session, message.from_user.id)
            kb = _session_kb(session, message.from_user.id)
        if prompt_msg_id:
            try:
                edited = await bot.edit_message_text(chat_id=message.chat.id, message_id=prompt_msg_id, text=text, reply_markup=kb)
                if result["ok"]:
                    await _remember_session_message(session, message.from_user.id, edited)
                    await _sync_session_messages(bot, session)
            except Exception:
                sent = await bot.send_message(message.chat.id, text, reply_markup=kb)
                if result["ok"]:
                    await _remember_session_message(session, message.from_user.id, sent)
                    await _sync_session_messages(bot, session)
        return
    result = await join_ttt_room(message.from_user.id, room_id)
    await state.clear()
    if not result["ok"]:
        text = "❌ Не удалось войти. Комната не найдена, закрыта или не хватает зефирок."
        kb = _pvp_games_kb()
    else:
        room = result["room"]
        text = _ttt_text(room, message.from_user.id)
        kb = _ttt_kb(room)
    if prompt_msg_id:
        try:
            edited = await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_msg_id,
                text=text,
                reply_markup=kb,
            )
            if result["ok"]:
                room = await _remember_ttt_message(room, message.from_user.id, edited)
        except Exception:
            sent = await bot.send_message(message.chat.id, text, reply_markup=kb)
            if result["ok"]:
                room = await _remember_ttt_message(room, message.from_user.id, sent)
    if result["ok"] and not result.get("already_in_room"):
        await _sync_ttt_player(bot, room, room["creator_id"])


@router.message(Command("join"))
async def cmd_join_room(message, command: CommandObject, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    room_id = (command.args or "").strip().lower()
    if not room_id:
        await render_clean_message(
            bot,
            message.chat.id,
            message.from_user.id,
            "🚪 <b>Вход в PvP-комнату</b>\n\nФормат: <code>/join код_комнаты</code>",
            reply_markup=_games_home_kb(),
        )
        return
    session = await get_session(room_id)
    if session:
        result = await join_session(room_id, message.from_user)
        if not result["ok"]:
            errors = {
                "not_available": "Комната уже недоступна или не найдена.",
                "expired": "Комната закрыта из-за бездействия.",
                "full": "Комната уже заполнена.",
                "already_started": "Игра уже началась.",
                "not_enough": "Не хватает зефирок для ставки.",
            }
            await render_clean_message(bot, message.chat.id, message.from_user.id, errors.get(result.get("error"), "Не удалось войти."), reply_markup=_games_home_kb())
            return
        session = result["session"]
        msg = await render_clean_message(bot, message.chat.id, message.from_user.id, _session_text(session, message.from_user.id), reply_markup=_session_kb(session, message.from_user.id))
        await _remember_session_message(session, message.from_user.id, msg)
        await _sync_session_messages(bot, session)
        return
    result = await join_ttt_room(message.from_user.id, room_id)
    if not result["ok"]:
        errors = {
            "not_available": "Комната уже недоступна или не найдена.",
            "own_room": "Нельзя войти в свою комнату.",
            "not_enough": "Не хватает зефирок для ставки.",
        }
        await render_clean_message(
            bot,
            message.chat.id,
            message.from_user.id,
            errors.get(result.get("error"), "Не удалось войти."),
            reply_markup=_games_home_kb(),
        )
        return
    room = result["room"]
    msg = await render_clean_message(bot, message.chat.id, message.from_user.id, _ttt_text(room, message.from_user.id), reply_markup=_ttt_kb(room))
    room = await _remember_ttt_message(room, message.from_user.id, msg)
    if not result.get("already_in_room"):
        await _sync_ttt_player(bot, room, room["creator_id"])


@router.callback_query(F.data == "game:ttt:list")
async def cb_ttt_list(callback: CallbackQuery):
    rooms = await list_waiting_ttt_rooms()
    kb = InlineKeyboardBuilder()
    if rooms:
        lines = ["🚪 <b>Открытые комнаты</b>\n"]
        for room in rooms:
            owner = room.get("first_name") or room.get("username") or str(room["creator_id"])
            lines.append(f"#{room['id']} · {owner} · ставка <b>{_money(room['stake'])}</b> 🍬")
            kb.row(InlineKeyboardButton(
                text=f"Войти #{room['id']} ({_money(room['stake'])} 🍬)",
                callback_data=f"game:ttt:join:{room['id']}",
            ))
        text = "\n".join(lines)
    else:
        text = "🚪 <b>Открытые комнаты</b>\n\nПока нет комнат. Создай свою."
    kb.row(InlineKeyboardButton(text="🎮 Игры", callback_data="games:home"))
    await smart_edit(callback, text, reply_markup=kb.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("game:ttt:join:"))
async def cb_ttt_join(callback: CallbackQuery):
    room_id = callback.data.split(":")[3]
    result = await join_ttt_room(callback.from_user.id, room_id)
    if not result["ok"]:
        errors = {
            "not_available": "Комната уже недоступна.",
            "own_room": "Нельзя войти в свою комнату.",
            "not_enough": "Не хватает зефирок для ставки.",
        }
        await callback.answer(errors.get(result.get("error"), "Не удалось войти."), show_alert=True)
        return
    room = result["room"]
    msg = await smart_edit(callback, _ttt_text(room, callback.from_user.id), reply_markup=_ttt_kb(room))
    room = await _remember_ttt_message(room, callback.from_user.id, msg)
    if not result.get("already_in_room"):
        await _sync_ttt_player(callback.bot, room, room["creator_id"])
    await callback.answer("Ты уже в этой комнате" if result.get("already_in_room") else "Ты вошёл в комнату")


@router.callback_query(F.data.startswith("game:ttt:m:"))
async def cb_ttt_move(callback: CallbackQuery):
    _, _, _, room_id, idx = callback.data.split(":")
    result = await ttt_move(callback.from_user.id, room_id, int(idx))
    if not result["ok"]:
        errors = {
            "not_active": "Игра не активна.",
            "not_player": "Ты не участник этой комнаты.",
            "not_turn": "Сейчас не твой ход.",
            "bad_cell": "Клетка занята.",
        }
        await callback.answer(errors.get(result.get("error"), "Ход недоступен."), show_alert=True)
        return
    room = result["room"]
    msg = await smart_edit(callback, _ttt_text(room, callback.from_user.id), reply_markup=_ttt_kb(room))
    room = await _remember_ttt_message(room, callback.from_user.id, msg)
    other_id = room["opponent_id"] if callback.from_user.id == room["creator_id"] else room["creator_id"]
    await _sync_ttt_player(callback.bot, room, other_id)
    await callback.answer("Ход принят")


@router.callback_query(F.data.startswith("game:ttt:cancel:"))
async def cb_ttt_cancel(callback: CallbackQuery):
    room_id = callback.data.split(":")[3]
    result = await cancel_ttt_room(callback.from_user.id, room_id)
    text = (
        "🎮 <b>Игры</b>\n\n"
        "Выбирай сапёра против бота или PvP-комнату в крестики-нолики."
    )
    await smart_edit(callback, text, reply_markup=_games_home_kb())
    await callback.answer("Комната отменена, ставка возвращена." if result["ok"] else "Нельзя отменить комнату.", show_alert=True)


@router.callback_query(F.data.startswith("game:noop:"))
async def cb_game_noop(callback: CallbackQuery):
    await callback.answer()
