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
    get_daily_freebie_status,
    get_shop_rotation_status,
    item_label,
    list_shop_offers,
)
from bot.services.time_service import format_msk
from bot.utils import render_clean_callback, render_clean_message

router = Router()


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _shop_kb(offers: list[dict], daily_status: dict | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if not daily_status or daily_status.get("available"):
        kb.row(InlineKeyboardButton(text="🎁 Халява дня", callback_data="shop:daily_info"))
    else:
        kb.row(InlineKeyboardButton(text="🎁 Халява дня · уже забрана", callback_data="shop:daily_info"))
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
    kb.row(
        InlineKeyboardButton(text="Домик", callback_data="shop:cat:home"),
        InlineKeyboardButton(text="Аксессуары", callback_data="shop:cat:accessory"),
        InlineKeyboardButton(text="Все", callback_data="shop:cat:all"),
    )
    for offer in offers[:8]:
        kb.row(InlineKeyboardButton(
            text=f"{RARITY_ICONS.get(offer['rarity'], '▫️')} {offer['name']} — {_money(offer['offer_price'])} 🍬",
            callback_data=f"shop:buy:{offer['offer_id']}",
        ))
    kb.row(InlineKeyboardButton(text="📦 Кейсы", callback_data="econ:cases"))
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


async def _shop_text(user_id: int, category: str | None = None) -> tuple[str, list[dict], dict]:
    offers = await list_shop_offers(category=category, limit=8)
    balance = await get_zefirki_balance(user_id)
    daily = await get_daily_freebie_status(user_id)
    rotation = await get_shop_rotation_status()
    cat = CATEGORY_LABELS.get(category or "all", "витрина")
    daily_line = "Дневная награда доступна." if daily["available"] else (
        f"Дневная награда уже забрана. Следующая после {format_msk(daily['next_claim_at'], '%d.%m %H:%M')} МСК."
    )
    lines = [
        f"🛒 <b>Магазин</b> · {cat}",
        "",
        f"Баланс: <b>{_money(balance)}</b> 🍬",
        f"Витрина обновлена: <b>{format_msk(rotation['starts_at'], '%d.%m %H:%M')}</b> МСК",
        f"Следующее обновление: <b>{format_msk(rotation['ends_at'], '%d.%m %H:%M')}</b> МСК",
        "Здесь покупаются еда, уход, игрушки, одежда и техника для питомцев.",
        daily_line,
    ]
    if offers:
        lines.append("\n<b>Предложения:</b>")
        for offer in offers[:8]:
            lines.append(
                f"{RARITY_ICONS.get(offer['rarity'], '▫️')} "
                f"<b>{html.escape(offer['name'])}</b> — <b>{_money(offer['offer_price'])}</b> 🍬"
            )
    else:
        lines.append("\nПока в этой категории пусто.")
    return "\n".join(lines), offers, daily


@router.callback_query(F.data == "shop:home")
async def cb_shop_home(callback: CallbackQuery):
    text, offers, daily = await _shop_text(callback.from_user.id)
    await render_clean_callback(callback, text, reply_markup=_shop_kb(offers, daily))
    await callback.answer()


@router.callback_query(F.data.startswith("shop:cat:"))
async def cb_shop_category(callback: CallbackQuery):
    category = callback.data.split(":")[2]
    text, offers, daily = await _shop_text(callback.from_user.id, category)
    await render_clean_callback(callback, text, reply_markup=_shop_kb(offers, daily))
    await callback.answer()


@router.message(Command("shop"))
async def cmd_shop(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    text, offers, daily = await _shop_text(message.from_user.id)
    await render_clean_message(bot, message.chat.id, message.from_user.id, text, reply_markup=_shop_kb(offers, daily))


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


@router.callback_query(F.data == "shop:daily_info")
async def cb_daily_info(callback: CallbackQuery):
    status = await get_daily_freebie_status(callback.from_user.id)
    if status["available"]:
        text = (
            "🎁 <b>Халява дня</b>\n\n"
            "Можно забрать немного зефирок и случайный магазинный предмет обычной или необычной редкости."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Забрать", callback_data="shop:daily")],
            [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop:home")],
        ])
    else:
        claim = status["claim"]
        item_line = f"\nПредмет: {item_label(claim)}" if claim and claim.get("item_id") else ""
        text = (
            "🎁 <b>Халява дня</b>\n\n"
            f"Сегодня получено: <b>+{_money(claim['amount'])}</b> 🍬{item_line}\n"
            f"Следующая награда после <b>{format_msk(status['next_claim_at'], '%d.%m %H:%M')}</b> МСК."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Магазин", callback_data="shop:home")],
        ])
    await render_clean_callback(callback, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "shop:daily")
async def cb_daily(callback: CallbackQuery):
    result = await claim_daily_freebie(callback.from_user.id)
    if not result["ok"]:
        await cb_daily_info(callback)
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
