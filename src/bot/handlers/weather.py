"""Погода: выбор города → выбор периода → карточка.

Flow:
  fun_submenu → weather:ask (ввод города)
  → если OWM /geo вернул 0 — «не нашли»
  → если 1 — сразу меню периодов
  → если >1 — кнопки выбора кандидата (weather:pick:<idx>)
  → меню периодов: сейчас / 5 дней / 7 дней

Кандидаты и выбранный город храним в FSM data (lat/lon не влезают
в callback_data, поэтому ходим через индекс).
"""
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.services.weather_service import format_5day, format_7day, format_current, geocode

router = Router()


class WeatherStates(StatesGroup):
    waiting_city = State()


def _ask_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:fun")],
    ])


def _candidates_kb(cands: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=f"📍 {c['label']}", callback_data=f"weather:pick:{i}")]
        for i, c in enumerate(cands)
    ]
    rows.append([InlineKeyboardButton(text="🔁 Другой город", callback_data="weather:ask")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _periods_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌤 Сейчас", callback_data="weather:period:now"),
            InlineKeyboardButton(text="📅 5 дней", callback_data="weather:period:5d"),
            InlineKeyboardButton(text="📆 7 дней", callback_data="weather:period:7d"),
        ],
        [InlineKeyboardButton(text="🔁 Другой город", callback_data="weather:ask")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:fun")],
    ])


def _result_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🌤 Сейчас", callback_data="weather:period:now"),
            InlineKeyboardButton(text="📅 5 дней", callback_data="weather:period:5d"),
            InlineKeyboardButton(text="📆 7 дней", callback_data="weather:period:7d"),
        ],
        [InlineKeyboardButton(text="🔁 Другой город", callback_data="weather:ask")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:fun")],
    ])


async def _show_periods(bot: Bot, chat_id: int, msg_id: int, selected: dict):
    text = (
        f"⛅ <b>Погода — {selected['label']}</b>\n\n"
        "Выбери период:"
    )
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=_periods_kb(),
        )
    except Exception:
        pass


@router.callback_query(F.data == "weather:ask")
async def cb_weather_ask(callback: CallbackQuery, state: FSMContext):
    await state.set_state(WeatherStates.waiting_city)
    await state.update_data(prompt_msg_id=callback.message.message_id)
    try:
        await callback.message.edit_text(
            "⛅ <b>Погода</b>\n\nВведи название города:",
            reply_markup=_ask_kb(),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(Command("weather"))
async def cmd_weather(message: Message, state: FSMContext, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    args = (message.text or "").split(maxsplit=1)
    if len(args) > 1:
        await _process_city(bot, message.chat.id, args[1].strip(), state, prompt_msg_id=None)
    else:
        await state.set_state(WeatherStates.waiting_city)
        msg = await bot.send_message(
            message.chat.id,
            "⛅ <b>Погода</b>\n\nВведи название города:",
            reply_markup=_ask_kb(),
        )
        await state.update_data(prompt_msg_id=msg.message_id)


@router.message(WeatherStates.waiting_city)
async def msg_city(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    chat_id = message.chat.id
    city = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass
    await _process_city(bot, chat_id, city, state, prompt_msg_id)


async def _process_city(bot: Bot, chat_id: int, city: str, state: FSMContext, prompt_msg_id: int | None):
    if not city:
        return
    cands = await geocode(city, limit=5)
    if not cands:
        text = (
            f"❌ Не нашёл город «{city}».\n\n"
            "Попробуй написать по-другому или указать страну: "
            "<code>Париж, Франция</code>"
        )
        await _show(bot, chat_id, prompt_msg_id, text, _ask_kb(), state)
        return

    if len(cands) == 1:
        selected = cands[0]
        await state.update_data(selected=selected, prompt_msg_id=prompt_msg_id)
        await state.set_state(None)  # stay in FSM data, не ждём город
        text = f"⛅ <b>Погода — {selected['label']}</b>\n\nВыбери период:"
        await _show(bot, chat_id, prompt_msg_id, text, _periods_kb(), state)
        return

    # Несколько кандидатов — храним и просим выбрать
    await state.update_data(candidates=cands, prompt_msg_id=prompt_msg_id)
    await state.set_state(None)
    text = (
        f"🔎 Нашёл несколько вариантов для «{city}».\n\n"
        "Какой имеешь в виду?"
    )
    await _show(bot, chat_id, prompt_msg_id, text, _candidates_kb(cands), state)


async def _show(bot: Bot, chat_id: int, msg_id: int | None, text: str, kb: InlineKeyboardMarkup, state: FSMContext):
    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb,
            )
            return
        except Exception:
            pass
    msg = await bot.send_message(chat_id, text, reply_markup=kb)
    await state.update_data(prompt_msg_id=msg.message_id)


@router.callback_query(F.data.startswith("weather:pick:"))
async def cb_pick(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[2])
    data = await state.get_data()
    cands = data.get("candidates") or []
    if idx < 0 or idx >= len(cands):
        await callback.answer("Кандидат не найден, начни заново", show_alert=True)
        return
    selected = cands[idx]
    await state.update_data(selected=selected)
    await _show_periods(callback.bot, callback.message.chat.id, callback.message.message_id, selected)
    await callback.answer()


@router.callback_query(F.data.startswith("weather:period:"))
async def cb_period(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[2]
    data = await state.get_data()
    selected = data.get("selected")
    if not selected:
        await callback.answer("Сначала выбери город", show_alert=True)
        await cb_weather_ask(callback, state)
        return

    await callback.answer("Гружу прогноз…")
    lat, lon, label = selected["lat"], selected["lon"], selected["label"]
    if period == "now":
        text = await format_current(lat, lon, label)
    elif period == "5d":
        text = await format_5day(lat, lon, label)
    elif period == "7d":
        text = await format_7day(lat, lon, label)
    else:
        text = "❌ Неизвестный период."

    try:
        await callback.message.edit_text(text, reply_markup=_result_kb())
    except Exception:
        pass
