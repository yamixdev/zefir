import html

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.keyboards.inline import admin_menu
from bot.models import get_user
from bot.services.economy_service import (
    RARITY_ICONS,
    admin_grant_zefirki,
    get_economy_stats,
    get_items,
    get_recent_economy_events,
    get_suspicious_market_events,
    get_top_balances,
    get_top_market_sellers,
    grant_item,
    item_label,
    list_cases,
    list_shop_offers,
    set_case_active,
    set_item_active,
    update_item_shop_price,
)

router = Router()


class AdminEconomyStates(StatesGroup):
    waiting_zefirki = State()
    waiting_item = State()
    waiting_price = State()


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _econ_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Статы", callback_data="adm:econ:stats"),
            InlineKeyboardButton(text="🧾 Журнал", callback_data="adm:econ:recent"),
        ],
        [InlineKeyboardButton(text="⚠️ Подозрительные лоты", callback_data="adm:econ:suspicious")],
        [
            InlineKeyboardButton(text="🛒 Магазин", callback_data="adm:econ:shop"),
            InlineKeyboardButton(text="📦 Кейсы", callback_data="adm:econ:cases"),
        ],
        [
            InlineKeyboardButton(text="🏆 Топы", callback_data="adm:econ:tops"),
            InlineKeyboardButton(text="📚 Предметы", callback_data="adm:econ:items"),
        ],
        [
            InlineKeyboardButton(text="🍬 Выдать зефирки", callback_data="adm:econ:zef"),
            InlineKeyboardButton(text="🎁 Выдать предмет", callback_data="adm:econ:item"),
        ],
        [InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="adm:menu")],
    ])


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:econ")]
    ])


def _event_line(event: dict) -> str:
    sign = "+" if event["amount"] > 0 else ""
    item = f" · {html.escape(event['item_name'])}" if event.get("item_name") else ""
    return (
        f"#{event['id']} · <code>{event['user_id']}</code> · "
        f"<b>{sign}{event['amount']}</b> · {html.escape(event['reason'])}{item}"
    )


@router.callback_query(F.data == "adm:econ")
async def cb_admin_economy(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    stats = await get_economy_stats()
    text = (
        "🍬 <b>Экономика</b>\n\n"
        f"Предметов: <b>{stats['items']}</b>\n"
        f"Офферов магазина: <b>{stats.get('shop_offers', 0)}</b>\n"
        f"В инвентарях: <b>{stats['inventory']}</b>\n"
        f"Активных лотов: <b>{stats['active_listings']}</b>\n"
        f"Проданных лотов: <b>{stats['sold_listings']}</b>\n"
        f"Событий: <b>{stats['events']}</b>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=_econ_menu_kb())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "adm:econ:suspicious")
async def cb_admin_econ_suspicious(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    listings = await get_suspicious_market_events(limit=15)
    if not listings:
        text = "⚠️ <b>Подозрительные лоты</b>\n\nПока ничего подозрительного."
    else:
        lines = ["⚠️ <b>Подозрительные лоты</b>\n"]
        for listing in listings:
            lines.append(
                f"#{listing['id']} · {RARITY_ICONS.get(listing['rarity'], '▫️')} "
                f"{html.escape(listing['name'])} · <b>{_money(listing['price'])}</b> 🍬 "
                f"(база: {_money(listing['base_price'])}) · {html.escape(listing['status'])}"
            )
        text = "\n".join(lines)
    try:
        await callback.message.edit_text(text, reply_markup=_econ_menu_kb())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "adm:econ:stats")
async def cb_admin_econ_stats(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    stats = await get_economy_stats()
    text = (
        "📊 <b>Статистика экономики</b>\n\n"
        f"Предметов в каталоге: <b>{stats['items']}</b>\n"
        f"Активных офферов: <b>{stats.get('shop_offers', 0)}</b>\n"
        f"Предметов у игроков: <b>{stats['inventory']}</b>\n"
        f"Активных лотов: <b>{stats['active_listings']}</b>\n"
        f"Проданных лотов: <b>{stats['sold_listings']}</b>\n"
        f"Записей аудита: <b>{stats['events']}</b>\n\n"
        f"Комиссия рынка: <b>{config.market_commission_percent}%</b>"
    )
    try:
        await callback.message.edit_text(text, reply_markup=_econ_menu_kb())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "adm:econ:tops")
async def cb_admin_tops(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    balances = await get_top_balances(5)
    sellers = await get_top_market_sellers(5)
    lines = ["🏆 <b>Экономические топы</b>\n", "<b>Баланс:</b>"]
    for u in balances:
        name = u.get("first_name") or u.get("username") or str(u["user_id"])
        lines.append(f"• {html.escape(name)} · <b>{_money(u['zefirki'])}</b> 🍬")
    lines.append("\n<b>Рынок:</b>")
    if sellers:
        for u in sellers:
            name = u.get("first_name") or u.get("username") or str(u["user_id"])
            lines.append(f"• {html.escape(name)} · {u['sold_count']} продаж · {_money(u['gross'])} 🍬")
    else:
        lines.append("пока пусто")
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=_econ_menu_kb())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "adm:econ:shop")
async def cb_admin_shop(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    offers = await list_shop_offers(limit=20)
    lines = ["🛒 <b>Магазин</b>\n"]
    kb = InlineKeyboardBuilder()
    for offer in offers:
        lines.append(f"#{offer['offer_id']} · {html.escape(offer['name'])} · {_money(offer['offer_price'])} 🍬")
    kb.row(InlineKeyboardButton(text="📚 Все предметы", callback_data="adm:econ:items"))
    kb.row(InlineKeyboardButton(text="⬅️ Экономика", callback_data="adm:econ"))
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "adm:econ:items")
async def cb_admin_items(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    items = await get_items(active_only=False)
    lines = ["📚 <b>Предметы</b>\n"]
    kb = InlineKeyboardBuilder()
    for item in items[:20]:
        status = "✅" if item["is_active"] else "⛔"
        shop = f" · магазин {_money(item['shop_price'])} 🍬" if item.get("shop_price") else ""
        lines.append(f"{status} <code>{item['id']}</code> · {item_label(item)}{shop}")
        kb.row(
            InlineKeyboardButton(
                text=f"{'Выкл' if item['is_active'] else 'Вкл'} #{item['id']}",
                callback_data=f"adm:econ:item_toggle:{item['id']}:{0 if item['is_active'] else 1}",
            ),
            InlineKeyboardButton(text=f"Цена #{item['id']}", callback_data=f"adm:econ:item_price:{item['id']}"),
        )
    kb.row(InlineKeyboardButton(text="⬅️ Экономика", callback_data="adm:econ"))
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("adm:econ:item_toggle:"))
async def cb_admin_item_toggle(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, _, _, item_id, active = callback.data.split(":")
    await set_item_active(int(item_id), active == "1")
    await callback.answer("Предмет обновлён", show_alert=True)
    await cb_admin_items(callback)


@router.callback_query(F.data.startswith("adm:econ:item_price:"))
async def cb_admin_item_price(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    item_id = int(callback.data.split(":")[3])
    await state.set_state(AdminEconomyStates.waiting_price)
    await state.update_data(item_id=item_id, prompt_msg_id=callback.message.message_id)
    try:
        await callback.message.edit_text(
            f"🛒 <b>Цена магазина для #{item_id}</b>\n\n"
            "Напиши новую цену числом. 0 выключит продажу в магазине.",
            reply_markup=_cancel_kb(),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminEconomyStates.waiting_price)
async def msg_admin_item_price(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    try:
        await message.delete()
    except Exception:
        pass
    try:
        price = int((message.text or "").strip())
    except ValueError:
        return
    item_id = data.get("item_id")
    ok = await update_item_shop_price(item_id, price if price > 0 else None)
    await state.clear()
    text = "✅ Цена обновлена." if ok else "❌ Предмет не найден."
    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_msg_id,
                text=text,
                reply_markup=_econ_menu_kb(),
            )
        except Exception:
            pass


@router.callback_query(F.data == "adm:econ:recent")
async def cb_admin_econ_recent(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    events = await get_recent_economy_events(limit=15)
    text = "🧾 <b>Последние операции</b>\n\n" + ("\n".join(_event_line(e) for e in events) if events else "Пока пусто.")
    try:
        await callback.message.edit_text(text, reply_markup=_econ_menu_kb())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "adm:econ:zef")
async def cb_admin_grant_zef(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminEconomyStates.waiting_zefirki)
    await state.update_data(prompt_msg_id=callback.message.message_id)
    try:
        await callback.message.edit_text(
            "🍬 <b>Выдать зефирки</b>\n\n"
            "Формат: <code>user_id amount</code>\n"
            "Пример: <code>123456789 250</code>\n"
            "Для списания можно указать отрицательное число.",
            reply_markup=_cancel_kb(),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminEconomyStates.waiting_zefirki)
async def msg_admin_grant_zef(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    try:
        await message.delete()
    except Exception:
        pass
    parts = (message.text or "").split()
    if len(parts) != 2:
        return
    try:
        user_id = int(parts[0])
        amount = int(parts[1])
    except ValueError:
        return
    user = await get_user(user_id)
    if not user:
        return
    balance = await admin_grant_zefirki(user_id, amount)
    await state.clear()
    text = (
        "✅ <b>Зефирки изменены</b>\n\n"
        f"Юзер: <code>{user_id}</code>\n"
        f"Операция: <b>{amount:+}</b> 🍬\n"
        f"Баланс: <b>{_money(balance or 0)}</b> 🍬"
    )
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_msg_id,
                text=text,
                reply_markup=_econ_menu_kb(),
            )
        except Exception:
            pass


@router.callback_query(F.data == "adm:econ:item")
async def cb_admin_grant_item(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    items = await get_items(active_only=True)
    item_lines = [
        f"<code>{i['id']}</code> · {RARITY_ICONS.get(i['rarity'], '▫️')} {html.escape(i['name'])}"
        for i in items[:20]
    ]
    await state.set_state(AdminEconomyStates.waiting_item)
    await state.update_data(prompt_msg_id=callback.message.message_id)
    try:
        await callback.message.edit_text(
            "🎁 <b>Выдать предмет</b>\n\n"
            "Формат: <code>user_id item_id qty</code>\n"
            "Пример: <code>123456789 2 1</code>\n\n"
            "<b>Предметы:</b>\n" + "\n".join(item_lines),
            reply_markup=_cancel_kb(),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminEconomyStates.waiting_item)
async def msg_admin_grant_item(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    prompt_msg_id = data.get("prompt_msg_id")
    try:
        await message.delete()
    except Exception:
        pass
    parts = (message.text or "").split()
    if len(parts) != 3:
        return
    try:
        user_id, item_id, qty = map(int, parts)
    except ValueError:
        return
    ok = await grant_item(user_id, item_id, qty, reason="admin_item")
    await state.clear()
    text = (
        "✅ <b>Предмет выдан</b>\n\n"
        f"Юзер: <code>{user_id}</code>\n"
        f"Item ID: <code>{item_id}</code>\n"
        f"Количество: <b>{qty}</b>"
        if ok else "❌ Не удалось выдать предмет."
    )
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_msg_id,
                text=text,
                reply_markup=_econ_menu_kb(),
            )
        except Exception:
            pass


@router.callback_query(F.data == "adm:econ:cases")
async def cb_admin_cases(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    cases = await list_cases(include_inactive=True)
    kb = InlineKeyboardBuilder()
    lines = ["📦 <b>Кейсы</b>\n"]
    for case in cases:
        status = "✅" if case["is_active"] else "⛔"
        lines.append(f"{status} <code>{case['id']}</code> · {html.escape(case['name'])} · {_money(case['price'])} 🍬")
        kb.row(InlineKeyboardButton(
            text=f"{'Выключить' if case['is_active'] else 'Включить'} {case['name']}",
            callback_data=f"adm:econ:case:{case['id']}:{0 if case['is_active'] else 1}",
        ))
    kb.row(InlineKeyboardButton(text="⬅️ Экономика", callback_data="adm:econ"))
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("adm:econ:case:"))
async def cb_admin_case_toggle(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, _, _, case_id, active = callback.data.split(":")
    await set_case_active(int(case_id), active == "1")
    cases = await list_cases(include_inactive=True)
    kb = InlineKeyboardBuilder()
    lines = ["📦 <b>Кейсы</b>\n"]
    for case in cases:
        status = "✅" if case["is_active"] else "⛔"
        lines.append(f"{status} <code>{case['id']}</code> · {html.escape(case['name'])} · {_money(case['price'])} 🍬")
        kb.row(InlineKeyboardButton(
            text=f"{'Выключить' if case['is_active'] else 'Включить'} {case['name']}",
            callback_data=f"adm:econ:case:{case['id']}:{0 if case['is_active'] else 1}",
        ))
    kb.row(InlineKeyboardButton(text="⬅️ Экономика", callback_data="adm:econ"))
    try:
        await callback.message.edit_text("\n".join(lines), reply_markup=kb.as_markup())
    except Exception:
        pass
    await callback.answer("Кейс обновлён", show_alert=True)
