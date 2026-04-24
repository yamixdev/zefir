"""Конвертер валют.

Flow:
  fun_submenu → callback conv:start
  → меню FROM (сетка популярных валют)
  → conv:from:<CODE> → просит ввести сумму (FSM)
  → пользователь пишет сумму → меню TO
  → conv:to:<CODE> → считает и показывает результат
  → «Ещё раз» возвращает на меню FROM
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.currency_service import POPULAR, convert, flag, get_rates
from bot.utils import smart_edit

router = Router()


class CurrencyStates(StatesGroup):
    waiting_amount = State()


def _pick_keyboard(action: str, exclude: str | None = None) -> InlineKeyboardMarkup:
    """action: 'from' или 'to'. exclude — не показывать эту валюту (нет смысла USD→USD)."""
    kb = InlineKeyboardBuilder()
    row: list[InlineKeyboardButton] = []
    for icon, code in POPULAR:
        if exclude and code == exclude:
            continue
        row.append(InlineKeyboardButton(text=f"{icon} {code}", callback_data=f"conv:{action}:{code}"))
        if len(row) == 3:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:fun"))
    return kb.as_markup()


def _back_to_from() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Ещё раз", callback_data="conv:start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:fun")],
    ])


def _format_amount(x: float) -> str:
    if abs(x) >= 100:
        return f"{x:,.2f}".replace(",", " ")
    if abs(x) >= 1:
        return f"{x:,.4f}".rstrip("0").rstrip(".").replace(",", " ")
    return f"{x:.6f}".rstrip("0").rstrip(".")


@router.callback_query(F.data == "conv:start")
async def cb_conv_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    text = (
        "💱 <b>Конвертер валют</b>\n\n"
        "Курсы от ЦБ РФ, обновляются раз в сутки.\n\n"
        "<b>Из какой валюты</b> конвертируем?"
    )
    await smart_edit(callback, text, reply_markup=_pick_keyboard("from"))
    await callback.answer()


@router.callback_query(F.data.startswith("conv:from:"))
async def cb_conv_from(callback: CallbackQuery, state: FSMContext):
    code = callback.data.split(":")[2]
    rates = await get_rates()
    if code not in rates:
        await callback.answer("Валюта не найдена", show_alert=True)
        return

    await state.set_state(CurrencyStates.waiting_amount)
    await state.update_data(
        src=code,
        prompt_msg_id=callback.message.message_id,
    )

    text = (
        f"💱 <b>Конвертер валют</b>\n\n"
        f"Из: {flag(code)} <b>{code}</b>\n\n"
        "Введи <b>сумму</b> цифрами (например, <code>100</code> или <code>99.9</code>):"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К выбору валюты", callback_data="conv:start")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        pass
    await callback.answer()


@router.message(CurrencyStates.waiting_amount)
async def msg_amount(message: Message, state: FSMContext, bot: Bot):
    raw = (message.text or "").strip().replace(",", ".").replace(" ", "")
    try:
        await message.delete()
    except Exception:
        pass

    try:
        amount = float(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        data = await state.get_data()
        prompt_id = data.get("prompt_msg_id")
        if prompt_id:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⬅️ К выбору валюты", callback_data="conv:start")],
            ])
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id, message_id=prompt_id,
                    text="❌ Не понял число. Введи цифрами, например <code>100</code>:",
                    reply_markup=kb,
                )
            except Exception:
                pass
        return

    data = await state.get_data()
    src = data.get("src")
    prompt_id = data.get("prompt_msg_id")
    await state.update_data(amount=amount)

    text = (
        f"💱 <b>Конвертер валют</b>\n\n"
        f"Сумма: <b>{_format_amount(amount)}</b> {flag(src)} <b>{src}</b>\n\n"
        "<b>В какую валюту</b> переводим?"
    )
    if prompt_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id, message_id=prompt_id,
                text=text, reply_markup=_pick_keyboard("to", exclude=src),
            )
            return
        except Exception:
            pass
    msg = await bot.send_message(message.chat.id, text, reply_markup=_pick_keyboard("to", exclude=src))
    await state.update_data(prompt_msg_id=msg.message_id)


@router.callback_query(F.data.startswith("conv:to:"))
async def cb_conv_to(callback: CallbackQuery, state: FSMContext):
    dst = callback.data.split(":")[2]
    data = await state.get_data()
    src = data.get("src")
    amount = data.get("amount")

    if not src or amount is None:
        await cb_conv_start(callback, state)
        return

    result = await convert(amount, src, dst)
    await state.clear()

    if result is None:
        text = "❌ Не удалось получить курс. Попробуй позже."
    else:
        text = (
            "💱 <b>Конвертер валют</b>\n\n"
            f"<b>{_format_amount(amount)}</b> {flag(src)} {src}\n"
            "= \n"
            f"<b>{_format_amount(result)}</b> {flag(dst)} {dst}\n\n"
            "<i>Курс ЦБ РФ на сегодня</i>"
        )

    try:
        await callback.message.edit_text(text, reply_markup=_back_to_from())
    except Exception:
        pass
    await callback.answer()


@router.message(Command("convert"))
async def cmd_convert(message: Message, command: CommandObject, bot: Bot):
    """Быстрая конвертация: /convert 100 USD RUB"""
    try:
        await message.delete()
    except Exception:
        pass
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Меню конвертера", callback_data="conv:start")],
        [InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun")],
    ])
    args = (command.args or "").split()
    if len(args) != 3:
        await bot.send_message(
            message.chat.id,
            "💱 <b>Конвертер</b>\n\n"
            "Формат: <code>/convert 100 USD RUB</code>\n"
            "Или используй меню.",
            reply_markup=kb,
        )
        return
    try:
        amount = float(args[0].replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await bot.send_message(message.chat.id, "❌ Сумма должна быть положительным числом.", reply_markup=kb)
        return
    src = args[1].upper()
    dst = args[2].upper()
    result = await convert(amount, src, dst)
    if result is None:
        await bot.send_message(
            message.chat.id,
            f"❌ Не знаю одну из валют ({src} или {dst}). Попробуй через меню.",
            reply_markup=kb,
        )
        return
    text = (
        "💱 <b>Конвертер валют</b>\n\n"
        f"<b>{_format_amount(amount)}</b> {flag(src)} {src}\n"
        "= \n"
        f"<b>{_format_amount(result)}</b> {flag(dst)} {dst}\n\n"
        "<i>Курс ЦБ РФ на сегодня</i>"
    )
    await bot.send_message(message.chat.id, text, reply_markup=kb)


@router.message(Command("rates"))
async def cmd_rates(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    rates = await get_rates()
    lines = ["💱 <b>Курсы ЦБ РФ</b>\n"]
    for _, code in POPULAR:
        if code == "RUB" or code not in rates:
            continue
        c = rates[code]
        lines.append(f"{flag(code)} <b>{code}</b> — {_format_amount(c.rate_rub)} ₽")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💱 Конвертер", callback_data="conv:start")],
        [InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun")],
    ])
    await bot.send_message(message.chat.id, "\n".join(lines), reply_markup=kb)
