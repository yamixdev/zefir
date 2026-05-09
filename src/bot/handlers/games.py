from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.services.games_service import (
    MS_SIZE,
    cancel_ttt_room,
    claim_ttt_timeout,
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
from bot.utils import render_clean_message, smart_edit

router = Router()


class GameStates(StatesGroup):
    waiting_room_code = State()


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _games_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤖 Игры с ботом", callback_data="games:bot")],
        [InlineKeyboardButton(text="👥 Игры с игроками", callback_data="games:pvp")],
        [InlineKeyboardButton(text="🚪 Войти по коду", callback_data="game:ttt:join_code")],
        [InlineKeyboardButton(text="📜 Мои активные игры", callback_data="games:active")],
        [InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun")],
    ])


def _bot_games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💣 Сапёр 0", callback_data="game:ms:new:0"),
            InlineKeyboardButton(text="💣 Сапёр 10", callback_data="game:ms:new:10"),
        ],
        [
            InlineKeyboardButton(text="🎲 Кости 0", callback_data="game:dice:0"),
            InlineKeyboardButton(text="🎲 Кости 10", callback_data="game:dice:10"),
        ],
        [
            InlineKeyboardButton(text="🔢 Угадай 1", callback_data="game:guess:1:0"),
            InlineKeyboardButton(text="🔢 Угадай 3", callback_data="game:guess:3:0"),
            InlineKeyboardButton(text="🔢 Угадай 5", callback_data="game:guess:5:0"),
        ],
        [InlineKeyboardButton(text="⬅️ Игры", callback_data="games:home")],
    ])


def _pvp_games_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭕ Создать 0 🍬", callback_data="game:ttt:new:0"),
            InlineKeyboardButton(text="⭕ Создать 25 🍬", callback_data="game:ttt:new:25"),
        ],
        [InlineKeyboardButton(text="🚪 Открытые комнаты", callback_data="game:ttt:list")],
        [InlineKeyboardButton(text="🔑 Ввести код", callback_data="game:ttt:join_code")],
        [InlineKeyboardButton(text="⬅️ Игры", callback_data="games:home")],
    ])


@router.callback_query(F.data == "games:home")
async def cb_games_home(callback: CallbackQuery):
    text = (
        "🎮 <b>Игры</b>\n\n"
        "💣 <b>Сапёр</b> — игра против бота. Выигрыш по ставке: возврат ставки + прибыль, "
        f"прибыль ограничена <b>{_money(config.game_daily_win_limit)}</b> 🍬 в день.\n\n"
        "⭕ <b>Крестики-нолики</b> — PvP-комнаты. Можно играть бесплатно или на ставку."
    )
    await smart_edit(callback, text, reply_markup=_games_home_kb())
    await callback.answer()


@router.callback_query(F.data == "games:bot")
async def cb_games_bot(callback: CallbackQuery):
    text = (
        "🤖 <b>Игры с ботом</b>\n\n"
        "Можно играть без ставки или на зефирки. Выигрыш ограничен дневным лимитом, чтобы экономика жила дольше."
    )
    await smart_edit(callback, text, reply_markup=_bot_games_kb())
    await callback.answer()


@router.callback_query(F.data == "games:pvp")
async def cb_games_pvp(callback: CallbackQuery):
    text = (
        "👥 <b>Игры с игроками</b>\n\n"
        "Создай комнату, отправь другу код или зайди в открытую комнату. До входа второго игрока комнату можно отменить."
    )
    await smart_edit(callback, text, reply_markup=_pvp_games_kb())
    await callback.answer()


@router.callback_query(F.data == "games:active")
async def cb_games_active(callback: CallbackQuery):
    data = await list_user_active_games(callback.from_user.id)
    lines = ["📜 <b>Мои активные игры</b>\n"]
    if not data["pve"] and not data["rooms"]:
        lines.append("Активных игр нет.")
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
    elif room["status"] == "active":
        rows.append([InlineKeyboardButton(text="⏱ Забрать победу по таймауту", callback_data=f"game:ttt:claim:{room['id']}")])
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
    if result["ok"]:
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
    await _sync_ttt_player(callback.bot, room, room["creator_id"])
    await callback.answer("Ты вошёл в комнату")


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


@router.callback_query(F.data.startswith("game:ttt:claim:"))
async def cb_ttt_claim(callback: CallbackQuery):
    room_id = callback.data.split(":")[3]
    result = await claim_ttt_timeout(callback.from_user.id, room_id)
    if not result["ok"]:
        errors = {
            "too_early": f"Таймаут хода ещё не прошёл ({config.ttt_turn_timeout_minutes} мин).",
            "your_turn": "Сейчас твой ход, таймаут забрать нельзя.",
            "not_active": "Игра не активна.",
        }
        await callback.answer(errors.get(result.get("error"), "Победу забрать нельзя."), show_alert=True)
        return
    room = result["room"]
    msg = await smart_edit(callback, _ttt_text(room, callback.from_user.id), reply_markup=_ttt_kb(room))
    room = await _remember_ttt_message(room, callback.from_user.id, msg)
    other_id = room["opponent_id"] if callback.from_user.id == room["creator_id"] else room["creator_id"]
    await _sync_ttt_player(callback.bot, room, other_id)
    await callback.answer("Победа по таймауту засчитана", show_alert=True)


@router.callback_query(F.data.startswith("game:noop:"))
async def cb_game_noop(callback: CallbackQuery):
    await callback.answer()
