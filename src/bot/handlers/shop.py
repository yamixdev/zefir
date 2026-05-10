import html

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models import get_zefirki_balance
from bot.services.economy_service import (
    CATEGORY_LABELS,
    RARITY_ICONS,
    buy_shop_offer,
    claim_daily_freebie,
    item_label,
    list_shop_offers,
)
from bot.utils import render_clean_callback, render_clean_message

router = Router()


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _shop_kb(offers: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎁 Забрать халяву дня", callback_data="shop:daily"))
    kb.row(
        InlineKeyboardButton(text="Еда", callback_data="shop:cat:food"),
        InlineKeyboardButton(text="Напитки", callback_data="shop:cat:drink"),
        InlineKeyboardButton(text="Уход", callback_data="shop:cat:care"),
    )
    kb.row(
        InlineKeyboardButton(text="Игрушки", callback_data="shop:cat:toy"),
        InlineKeyboardButton(text="Одежда", callback_data="shop:cat:clothes"),
        InlineKeyboardButton(text="Техника", callback_data="shop:cat:tech"),
    )
    for offer in offers[:5]:
        kb.row(InlineKeyboardButton(
            text=f"{RARITY_ICONS.get(offer['rarity'], '▫️')} {offer['name']} — {_money(offer['offer_price'])} 🍬",
            callback_data=f"shop:buy:{offer['offer_id']}",
        ))
    kb.row(InlineKeyboardButton(text="📦 Кейсы", callback_data="econ:cases"))
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


async def _shop_text(user_id: int, category: str | None = None) -> tuple[str, list[dict]]:
    offers = await list_shop_offers(category=category, limit=5)
    balance = await get_zefirki_balance(user_id)
    cat = CATEGORY_LABELS.get(category or "all", "витрина")
    lines = [
        f"🛒 <b>Магазин</b> · {cat}",
        "",
        f"Баланс: <b>{_money(balance)}</b> 🍬",
        "Здесь покупаются еда, уход, игрушки, одежда и техника для питомцев.",
    ]
    if offers:
        lines.append("\n<b>Предложения:</b>")
        for offer in offers[:5]:
            lines.append(
                f"{RARITY_ICONS.get(offer['rarity'], '▫️')} "
                f"<b>{html.escape(offer['name'])}</b> — <b>{_money(offer['offer_price'])}</b> 🍬"
            )
    else:
        lines.append("\nПока в этой категории пусто.")
    return "\n".join(lines), offers


@router.callback_query(F.data == "shop:home")
async def cb_shop_home(callback: CallbackQuery):
    text, offers = await _shop_text(callback.from_user.id)
    await render_clean_callback(callback, text, reply_markup=_shop_kb(offers))
    await callback.answer()


@router.callback_query(F.data.startswith("shop:cat:"))
async def cb_shop_category(callback: CallbackQuery):
    category = callback.data.split(":")[2]
    text, offers = await _shop_text(callback.from_user.id, category)
    await render_clean_callback(callback, text, reply_markup=_shop_kb(offers))
    await callback.answer()


@router.message(Command("shop"))
async def cmd_shop(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    text, offers = await _shop_text(message.from_user.id)
    await render_clean_message(bot, message.chat.id, message.from_user.id, text, reply_markup=_shop_kb(offers))


@router.callback_query(F.data.startswith("shop:buy:"))
async def cb_shop_buy(callback: CallbackQuery):
    offer_id = int(callback.data.split(":")[2])
    result = await buy_shop_offer(callback.from_user.id, offer_id)
    if not result["ok"]:
        if result.get("error") == "not_enough":
            await callback.answer(f"Не хватает зефирок. Баланс: {_money(result.get('balance', 0))}", show_alert=True)
        else:
            await callback.answer("Предложение уже недоступно.", show_alert=True)
        return
    item = result["item"]
    text = (
        "✅ <b>Покупка в магазине</b>\n\n"
        f"Куплено: {item_label(item)}\n"
        f"Баланс: <b>{_money(result['balance'])}</b> 🍬\n\n"
        "Предмет добавлен в инвентарь."
    )
    await render_clean_callback(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv")],
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop:home")],
    ]))
    await callback.answer()


@router.callback_query(F.data == "shop:daily")
async def cb_daily(callback: CallbackQuery):
    result = await claim_daily_freebie(callback.from_user.id)
    if not result["ok"]:
        await callback.answer("Сегодня уже забирал. Приходи завтра.", show_alert=True)
        return
    item_line = f"\nПредмет: {item_label(result['item'])}" if result.get("item") else ""
    text = (
        "🎁 <b>Халява дня</b>\n\n"
        f"Зефирки: <b>+{_money(result['amount'])}</b> 🍬"
        f"{item_line}"
    )
    await render_clean_callback(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop:home")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv")],
    ]))
    await callback.answer("Получено")
