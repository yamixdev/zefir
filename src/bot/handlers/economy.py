import asyncio
import html

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.models import get_zefirki_balance
from bot.services.economy_service import (
    CATEGORY_LABELS,
    RARITY_ICONS,
    RARITY_LABELS,
    buy_listing,
    cancel_listing,
    create_listing,
    get_case_rewards,
    get_case_key_counts,
    get_inventory,
    get_inventory_item,
    get_market_listing,
    get_my_listings,
    item_action_hint,
    item_label,
    item_type_label,
    list_cases,
    list_market,
    open_case,
    price_limits_for,
    use_inventory_item,
)
from bot.utils import render_clean_message, smart_edit

router = Router()


class EconomyStates(StatesGroup):
    waiting_listing_price = State()


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


PAGE_SIZE = 6

def _page_items(items: list[dict], page: int) -> list[dict]:
    start = max(0, page) * PAGE_SIZE
    return items[start:start + PAGE_SIZE]


def _inventory_kb(items: list[dict], category: str | None = None, page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Всё", callback_data="econ:inv"),
        InlineKeyboardButton(text="Еда", callback_data="econ:inv:c:food"),
        InlineKeyboardButton(text="Уход", callback_data="econ:inv:c:care"),
    )
    kb.row(
        InlineKeyboardButton(text="Игрушки", callback_data="econ:inv:c:toy"),
        InlineKeyboardButton(text="Одежда", callback_data="econ:inv:c:clothes"),
        InlineKeyboardButton(text="Редкое", callback_data="econ:inv:c:rare"),
    )
    kb.row(
        InlineKeyboardButton(text="Домик", callback_data="econ:inv:c:home"),
        InlineKeyboardButton(text="Ключи", callback_data="econ:inv:c:key"),
    )
    for item in _page_items(items, page):
        kb.row(InlineKeyboardButton(
            text=f"{item_label(item)} x{item['quantity']}",
            callback_data=f"econ:item:{item['id']}",
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"econ:inv:p:{category or 'all'}:{page - 1}"))
    if len(items) > (page + 1) * PAGE_SIZE:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"econ:inv:p:{category or 'all'}:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="🏪 Рынок", callback_data="econ:market"))
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


def _item_kb(item: dict) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if item["item_type"] == "cosmetic":
        kb.row(InlineKeyboardButton(text="🐾 Надеть на питомца", callback_data=f"pet:equip:{item['id']}"))
    if item["usable"]:
        kb.row(InlineKeyboardButton(text="✨ Использовать", callback_data=f"econ:use:{item['id']}"))
    if item["sellable"]:
        kb.row(InlineKeyboardButton(text="🏷 Выставить на рынок", callback_data=f"econ:sell:{item['id']}"))
    kb.row(InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv"))
    return kb.as_markup()


def _cases_kb(cases: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for case in cases:
        key = f" + {case['key_name']}" if case.get("key_name") else ""
        price = f"{_money(case['price'])} 🍬" if case["price"] else "ключ"
        kb.row(InlineKeyboardButton(
            text=f"📦 {case['name']} — {price}{key}",
            callback_data=f"econ:case:{case['id']}",
        ))
    kb.row(InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv"))
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


def _case_detail_kb(case_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔓 Крутить", callback_data=f"econ:open:{case_id}")],
        [InlineKeyboardButton(text="📦 Все кейсы", callback_data="econ:cases")],
        [InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun")],
    ])


def _case_open_kb(case_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Крутить ещё", callback_data=f"econ:open:{case_id}")],
        [InlineKeyboardButton(text="✅ Хватит", callback_data="econ:cases")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv")],
    ])


def _keys_line(keys: dict) -> str:
    bronze = int((keys.get("bronze_key") or {}).get("quantity") or 0)
    silver = int((keys.get("silver_key") or {}).get("quantity") or 0)
    gold = int((keys.get("gold_key") or {}).get("quantity") or 0)
    return f"Ключи: бронза <b>{bronze}</b> · серебро <b>{silver}</b> · золото <b>{gold}</b>"


def _market_kb(listings: list[dict], rarity: str | None = None, category: str | None = None, page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔎 Фильтры", callback_data="econ:market:filters"))
    for listing in listings:
        icon = RARITY_ICONS.get(listing["rarity"], "▫️")
        kb.row(InlineKeyboardButton(
            text=f"{icon} {listing['name']} — {_money(listing['price'])} 🍬",
            callback_data=f"econ:listing:{listing['id']}",
        ))
    nav = []
    key = f"r_{rarity}" if rarity else (f"c_{category}" if category else "all")
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"econ:market:p:{key}:{page - 1}"))
    if len(listings) >= PAGE_SIZE:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"econ:market:p:{key}:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(
        InlineKeyboardButton(text="Мои лоты", callback_data="econ:mylist"),
        InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv"),
    )
    return kb.as_markup()


def _market_filters_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="Еда", callback_data="econ:market:c:food"),
        InlineKeyboardButton(text="Одежда", callback_data="econ:market:c:clothes"),
        InlineKeyboardButton(text="Редкое", callback_data="econ:market:c:rare"),
    )
    kb.row(
        InlineKeyboardButton(text="Все", callback_data="econ:market"),
        InlineKeyboardButton(text="Редкие+", callback_data="econ:market:r:rare_plus"),
    )
    return kb.as_markup()


def _my_listings_kb(listings: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for listing in listings:
        kb.row(InlineKeyboardButton(
            text=f"❌ Снять #{listing['id']} — {listing['name']}",
            callback_data=f"econ:cancel:{listing['id']}",
        ))
    kb.row(InlineKeyboardButton(text="🏪 Рынок", callback_data="econ:market"))
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


@router.callback_query(F.data.regexp(r"^econ:inv(:c:\w+)?$|^econ:inv:p:\w+:\d+$"))
async def cb_inventory(callback: CallbackQuery):
    parts = callback.data.split(":")
    page = 0
    if len(parts) == 5 and parts[2] == "p":
        category = None if parts[3] == "all" else parts[3]
        page = int(parts[4])
    else:
        category = parts[3] if len(parts) == 4 else None
    items = await get_inventory(callback.from_user.id, category=category)
    title = CATEGORY_LABELS.get(category or "all", "всё")
    if not items:
        text = (
            "🎒 <b>Инвентарь</b>\n\n"
            f"Раздел: <b>{title}</b>\n\n"
            "Пока пусто. Открой кейс, выиграй мини-игру или купи предмет в магазине."
        )
    else:
        lines = [f"🎒 <b>Инвентарь</b> · {title}\n"]
        for item in _page_items(items, page):
            rarity = RARITY_LABELS.get(item["rarity"], item["rarity"])
            lines.append(f"{item_label(item)} x<b>{item['quantity']}</b> · <i>{rarity}</i>")
        if len(items) > PAGE_SIZE:
            lines.append(f"\nСтраница <b>{page + 1}</b>")
        text = "\n".join(lines)
    await smart_edit(callback, text, reply_markup=_inventory_kb(items, category, page))
    await callback.answer()


@router.message(Command("inventory"))
async def cmd_inventory(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    items = await get_inventory(message.from_user.id)
    if not items:
        text = "🎒 <b>Инвентарь</b>\n\nПока пусто."
    else:
        lines = ["🎒 <b>Инвентарь</b>\n"]
        for item in items[:20]:
            lines.append(f"{item_label(item)} x<b>{item['quantity']}</b>")
        text = "\n".join(lines)
    await render_clean_message(bot, message.chat.id, message.from_user.id, text, reply_markup=_inventory_kb(items))


@router.callback_query(F.data.startswith("econ:item:"))
async def cb_item_detail(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[2])
    item = await get_inventory_item(callback.from_user.id, item_id)
    if not item:
        await callback.answer("Предмет не найден в инвентаре", show_alert=True)
        return
    min_price, max_price = price_limits_for(item)
    action_hint = item_action_hint(item)
    text = (
        f"{item_label(item)}\n\n"
        f"Редкость: <b>{RARITY_LABELS.get(item['rarity'], item['rarity'])}</b>\n"
        f"Тип: <b>{html.escape(item_type_label(item['item_type']))}</b>\n"
        f"Действие: <b>{html.escape(action_hint)}</b>\n"
        f"Количество: <b>{item['quantity']}</b>\n"
        f"Базовая цена: <b>{_money(item['base_price'])}</b> 🍬\n"
        f"Рыночный диапазон: <b>{_money(min_price)}-{_money(max_price)}</b> 🍬\n\n"
        f"<i>{html.escape(item['description'] or '')}</i>"
    )
    await smart_edit(callback, text, reply_markup=_item_kb(item))
    await callback.answer()


@router.callback_query(F.data.startswith("econ:use:"))
async def cb_use_item(callback: CallbackQuery):
    item_id = int(callback.data.split(":")[2])
    result = await use_inventory_item(callback.from_user.id, item_id)
    if not result["ok"]:
        if result.get("error") == "not_usable":
            msg = "Этот предмет нельзя использовать."
        elif result.get("error") == "no_pet":
            msg = "Сначала выбери питомца."
        elif result.get("error") == "already_installed":
            msg = "Этот предмет уже стоит в домике."
        else:
            msg = "Предмет не найден."
        await callback.answer(msg, show_alert=True)
        return
    items = await get_inventory(callback.from_user.id)
    text = "🎒 <b>Инвентарь</b>\n\n"
    if items:
        text += "\n".join(f"{item_label(item)} x<b>{item['quantity']}</b>" for item in items[:20])
    else:
        text += "Пока пусто."
    await smart_edit(callback, text, reply_markup=_inventory_kb(items))
    await callback.answer(f"✨ {result['effect']}", show_alert=True)


@router.callback_query(F.data.startswith("econ:sell:"))
async def cb_sell_item(callback: CallbackQuery, state: FSMContext):
    item_id = int(callback.data.split(":")[2])
    item = await get_inventory_item(callback.from_user.id, item_id)
    if not item:
        await callback.answer("Предмет не найден", show_alert=True)
        return
    min_price, max_price = price_limits_for(item)
    await state.set_state(EconomyStates.waiting_listing_price)
    await state.update_data(item_id=item_id, prompt_msg_id=callback.message.message_id)
    await smart_edit(
        callback,
        f"🏷 <b>Продажа предмета</b>\n\n"
        f"{item_label(item)}\n"
        f"Комиссия рынка: <b>{config.market_commission_percent}%</b>, покупатель её не платит отдельно.\n"
        f"Цена должна быть от <b>{_money(min_price)}</b> до <b>{_money(max_price)}</b> 🍬.\n\n"
        "Напиши цену одним числом:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"econ:item:{item_id}")]
        ]),
    )
    await callback.answer()


@router.message(EconomyStates.waiting_listing_price)
async def msg_listing_price(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    item_id = data.get("item_id")
    prompt_msg_id = data.get("prompt_msg_id")
    try:
        await message.delete()
    except Exception:
        pass
    try:
        price = int((message.text or "").strip())
    except ValueError:
        price = 0
    result = await create_listing(message.from_user.id, item_id, price)
    if not result["ok"]:
        item = result.get("item")
        if result.get("error") == "bad_price" and item:
            text = (
                f"❌ Неверная цена для {item_label(item)}.\n\n"
                f"Диапазон: <b>{_money(result['min_price'])}-{_money(result['max_price'])}</b> 🍬.\n"
                "Напиши другую цену:"
            )
        else:
            text = "❌ Не получилось выставить предмет. Возможно, его уже нет в инвентаре."
        if prompt_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id,
                    message_id=prompt_msg_id,
                    text=text,
                )
            except Exception:
                pass
        return

    await state.clear()
    listing = result["listing"]
    item = result["item"]
    text = (
        "✅ <b>Лот выставлен</b>\n\n"
        f"{item_label(item)}\n"
        f"Цена: <b>{_money(listing['price'])}</b> 🍬\n"
        f"После комиссии ты получишь: "
        f"<b>{_money(listing['price'] * (100 - config.market_commission_percent) // 100)}</b> 🍬"
    )
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_msg_id,
                text=text,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏪 Рынок", callback_data="econ:market")],
                    [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv")],
                ]),
            )
        except Exception:
            pass


@router.callback_query(F.data == "econ:cases")
async def cb_cases(callback: CallbackQuery):
    cases = await list_cases()
    balance = await get_zefirki_balance(callback.from_user.id)
    keys = await get_case_key_counts(callback.from_user.id)
    text = (
        "📦 <b>Кейсы</b>\n\n"
        f"Баланс: <b>{_money(balance)}</b> 🍬\n"
        f"{_keys_line(keys)}\n"
        "Обычные кейсы открываются за зефирки. Сундуки требуют ключ и выдают один предмет."
    )
    await smart_edit(callback, text, reply_markup=_cases_kb(cases))
    await callback.answer()


@router.message(Command("cases"))
async def cmd_cases(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    cases = await list_cases()
    balance = await get_zefirki_balance(message.from_user.id)
    keys = await get_case_key_counts(message.from_user.id)
    await render_clean_message(
        bot,
        message.chat.id,
        message.from_user.id,
        f"📦 <b>Кейсы</b>\n\nБаланс: <b>{_money(balance)}</b> 🍬\n{_keys_line(keys)}",
        reply_markup=_cases_kb(cases),
    )


@router.callback_query(F.data.startswith("econ:case:"))
async def cb_case_detail(callback: CallbackQuery):
    case_id = int(callback.data.split(":")[2])
    cases = await list_cases()
    case = next((c for c in cases if c["id"] == case_id), None)
    if not case:
        await callback.answer("Кейс недоступен", show_alert=True)
        return
    rewards = await get_case_rewards(case_id)
    keys = await get_case_key_counts(callback.from_user.id)
    key_count = 0
    if case.get("key_code"):
        key_count = int((keys.get(case["key_code"]) or {}).get("quantity") or 0)
    if rewards:
        loot_lines = ["\n<b>Внутри:</b>"]
        for reward in rewards:
            loot_lines.append(
                f"{item_label(reward)} · <i>{RARITY_LABELS.get(reward['rarity'], reward['rarity'])}</i> · "
                f"{reward['chance']:.1f}%"
            )
        loot_text = "\n".join(loot_lines)
    else:
        loot_text = "\n<b>Внутри:</b>\nПока нет активного лута."
    key_text = "не нужен"
    if case.get("key_name"):
        key_text = f"{case['key_name']} · у тебя {key_count} шт."
    text = (
        f"📦 <b>{html.escape(case['name'])}</b>\n\n"
        f"{html.escape(case['description'] or '')}\n\n"
        f"Цена: <b>{_money(case['price'])}</b> 🍬\n"
        f"Ключ: <b>{html.escape(key_text)}</b>"
        f"{loot_text}"
    )
    await smart_edit(callback, text, reply_markup=_case_detail_kb(case_id))
    await callback.answer()


@router.callback_query(F.data.startswith("econ:open:"))
async def cb_open_case(callback: CallbackQuery):
    case_id = int(callback.data.split(":")[2])
    result = await open_case(callback.from_user.id, case_id)
    if not result["ok"]:
        if result.get("error") == "not_enough":
            await callback.answer(
                f"Не хватает зефирок. Баланс: {_money(result.get('balance', 0))}",
                show_alert=True,
            )
        elif result.get("error") == "no_key":
            case = result.get("case") or {}
            keys = await get_case_key_counts(callback.from_user.id)
            key_count = int((keys.get(case.get("key_code")) or {}).get("quantity") or 0)
            await callback.answer(
                f"Нужен ключ: {case.get('key_name') or 'ключ от кейса'}. У тебя: {key_count}.",
                show_alert=True,
            )
        else:
            await callback.answer("Кейс недоступен", show_alert=True)
        return
    item = result["item"]
    case = result["case"]
    for frame in ("📦 Кейс дрожит...", "✨ Лента крутится...", "🎁 Почти выпало..."):
        try:
            await smart_edit(callback, f"<b>{frame}</b>")
            await asyncio.sleep(0.35)
        except Exception:
            break
    text = (
        f"📦 <b>{html.escape(case['name'])}</b> открыт!\n\n"
        f"Выпало: {item_label(item)}\n"
        f"Редкость: <b>{RARITY_LABELS.get(item['rarity'], item['rarity'])}</b>\n\n"
        f"Баланс: <b>{_money(result['balance'])}</b> 🍬"
    )
    await smart_edit(callback, text, reply_markup=_case_open_kb(case_id))
    await callback.answer("Предмет добавлен в инвентарь")


@router.callback_query(F.data == "econ:market:filters")
async def cb_market_filters(callback: CallbackQuery):
    await smart_edit(
        callback,
        "🔎 <b>Фильтры рынка</b>\n\nВыбери категорию или редкость.",
        reply_markup=_market_filters_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^econ:market((:r|:c):\w+)?$|^econ:market:p:(all|[rc]_\w+):\d+$"))
async def cb_market(callback: CallbackQuery):
    parts = callback.data.split(":")
    rarity = None
    category = None
    page = 0
    if len(parts) == 5 and parts[2] == "p":
        key = parts[3]
        if key.startswith("r_"):
            rarity = key[2:]
        elif key.startswith("c_"):
            category = key[2:]
        page = int(parts[-1])
    elif len(parts) == 4:
        rarity = parts[3] if parts[2] == "r" else None
        category = parts[3] if parts[2] == "c" else None
    listings = await list_market(rarity=rarity, category=category, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
    if not listings:
        text = "🏪 <b>Рынок</b>\n\nАктивных лотов пока нет."
    else:
        lines = ["🏪 <b>Рынок</b>\n"]
        for listing in listings:
            seller = listing.get("first_name") or listing.get("username") or str(listing["seller_id"])
            lines.append(
                f"#{listing['id']} · {RARITY_ICONS.get(listing['rarity'], '▫️')} "
                f"<b>{html.escape(listing['name'])}</b> — <b>{_money(listing['price'])}</b> 🍬 · {html.escape(seller)}"
            )
        text = "\n".join(lines)
    if page:
        text += f"\n\nСтраница <b>{page + 1}</b>"
    await smart_edit(callback, text, reply_markup=_market_kb(listings, rarity, category, page))
    await callback.answer()


@router.callback_query(F.data.startswith("econ:listing:"))
async def cb_listing_detail(callback: CallbackQuery):
    listing_id = int(callback.data.split(":")[2])
    listing = await get_market_listing(listing_id)
    if not listing or listing["status"] != "active":
        await callback.answer("Лот уже недоступен", show_alert=True)
        return
    seller = listing.get("first_name") or listing.get("username") or str(listing["seller_id"])
    text = (
        f"🏷 <b>Лот #{listing['id']}</b>\n\n"
        f"{RARITY_ICONS.get(listing['rarity'], '▫️')} <b>{html.escape(listing['name'])}</b>\n"
        f"Тип: <b>{html.escape(listing['category'])}</b>\n"
        f"Продавец: <b>{html.escape(seller)}</b>\n"
        f"Цена: <b>{_money(listing['price'])}</b> 🍬\n\n"
        f"<i>{html.escape(listing.get('description') or '')}</i>"
    )
    if listing["seller_id"] == callback.from_user.id:
        text += "\n\n<i>Это твой лот. Купить его нельзя, можно только снять с рынка.</i>"
        rows = [
            [InlineKeyboardButton(text="❌ Снять лот", callback_data=f"econ:cancel:{listing_id}")],
            [InlineKeyboardButton(text="⬅️ Рынок", callback_data="econ:market")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="✅ Купить", callback_data=f"econ:buy:{listing_id}")],
            [InlineKeyboardButton(text="⬅️ Рынок", callback_data="econ:market")],
        ]
    await smart_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.message(Command("market"))
async def cmd_market(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    listings = await list_market(limit=10)
    text = "🏪 <b>Рынок</b>\n\n"
    if listings:
        text += "\n".join(
            f"#{l['id']} · {RARITY_ICONS.get(l['rarity'], '▫️')} <b>{html.escape(l['name'])}</b> — <b>{_money(l['price'])}</b> 🍬"
            for l in listings
        )
    else:
        text += "Активных лотов пока нет."
    await render_clean_message(bot, message.chat.id, message.from_user.id, text, reply_markup=_market_kb(listings))


@router.callback_query(F.data.startswith("econ:buy:"))
async def cb_buy_listing(callback: CallbackQuery):
    listing_id = int(callback.data.split(":")[2])
    result = await buy_listing(callback.from_user.id, listing_id)
    if not result["ok"]:
        errors = {
            "not_available": "Лот уже недоступен.",
            "item_disabled": "Предмет отключён владельцем, лот больше нельзя купить.",
            "own_listing": "Свой лот купить нельзя.",
            "not_enough": f"Не хватает зефирок. Баланс: {_money(result.get('balance', 0))}",
        }
        await callback.answer(errors.get(result.get("error"), "Покупка не удалась."), show_alert=True)
        return
    listing = result["listing"]
    text = (
        "✅ <b>Покупка успешна</b>\n\n"
        f"Ты купил: {RARITY_ICONS.get(listing['rarity'], '▫️')} <b>{html.escape(listing['name'])}</b>\n"
        f"Потрачено: <b>{_money(listing['price'])}</b> 🍬\n"
        f"Баланс: <b>{_money(result['buyer_balance'])}</b> 🍬"
    )
    await smart_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv")],
        [InlineKeyboardButton(text="🏪 Рынок", callback_data="econ:market")],
    ]))
    await callback.answer()


@router.callback_query(F.data == "econ:mylist")
async def cb_my_listings(callback: CallbackQuery):
    listings = await get_my_listings(callback.from_user.id)
    if not listings:
        text = "🏷 <b>Мои лоты</b>\n\nУ тебя нет активных лотов."
    else:
        lines = ["🏷 <b>Мои лоты</b>\n"]
        for listing in listings:
            lines.append(f"#{listing['id']} · {html.escape(listing['name'])} — <b>{_money(listing['price'])}</b> 🍬")
        text = "\n".join(lines)
    await smart_edit(callback, text, reply_markup=_my_listings_kb(listings))
    await callback.answer()


@router.callback_query(F.data.startswith("econ:cancel:"))
async def cb_cancel_listing(callback: CallbackQuery):
    listing_id = int(callback.data.split(":")[2])
    result = await cancel_listing(callback.from_user.id, listing_id)
    listings = await get_my_listings(callback.from_user.id)
    if not listings:
        text = "🏷 <b>Мои лоты</b>\n\nУ тебя нет активных лотов."
    else:
        lines = ["🏷 <b>Мои лоты</b>\n"]
        for listing in listings:
            lines.append(f"#{listing['id']} · {html.escape(listing['name'])} — <b>{_money(listing['price'])}</b> 🍬")
        text = "\n".join(lines)
    await smart_edit(callback, text, reply_markup=_my_listings_kb(listings))
    await callback.answer("Лот снят" if result["ok"] else "Лот не найден", show_alert=True)
