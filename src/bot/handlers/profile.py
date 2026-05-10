import asyncio
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.config import config
from bot.keyboards.inline import (
    admin_profile_menu,
    admin_profile_stats_menu,
    profile_details_menu,
    profile_menu,
)
from bot.models import (
    get_user, get_ai_limit_info, get_user_ticket_stats,
    get_stats, get_new_users_count, get_banned_count, get_top_ai_users,
    get_zefirki_balance, get_recent_transactions,
)
from bot.services.economy_service import get_my_listings
from bot.services.games_service import list_user_active_games
from bot.services.game_session_service import list_my_sessions
from bot.services.pet_service import get_pet, SPECIES


_REASON_LABELS = {
    "welcome": "🎁 Приветственный бонус",
    "daily": "📅 Ежедневный бонус",
    "referral": "👥 Приглашение друга",
    "ticket": "📨 Тикет владельцу",
    "shop": "🛒 Покупка в магазине",
    "case": "📦 Открытие кейса",
    "market": "💱 Сделка на рынке",
    "game_stake": "🎮 Ставка в игре",
    "game_win": "🏆 Выигрыш",
    "game_refund": "↩️ Возврат ставки",
    "pet": "🐾 Питомец",
    "admin": "👑 От владельца",
    "admin_item": "🎁 Предмет от владельца",
}


def _reason_label(reason: str) -> str:
    return _REASON_LABELS.get(reason, reason)


def _money(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _format_tx(tx: dict) -> str:
    sign = "+" if tx["amount"] >= 0 else ""
    return f"{sign}{_money(tx['amount'])} 🍬 — {_reason_label(tx['reason'])}"

router = Router()


def _format_reset_timer(reset_at) -> str:
    if reset_at is None:
        return "—"
    now = datetime.now(timezone.utc)
    delta = reset_at - now
    total = int(delta.total_seconds())
    if total <= 0:
        return "сейчас будет сброс"
    h, rem = divmod(total, 3600)
    m = rem // 60
    if h > 0:
        return f"{h} ч {m} мин"
    return f"{m} мин"


async def _daily_available(user_id: int) -> bool:
    from bot.db import get_pool

    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM daily_claims WHERE user_id = %s AND claim_date = CURRENT_DATE",
            (user_id,),
        )
        return await cur.fetchone() is None


def _pet_line(pet: dict | None) -> str:
    if not pet:
        return "🐾 Питомец: <b>не выбран</b>"
    sp = SPECIES.get(pet.get("species"), SPECIES["cat"])
    return f"🐾 {sp['emoji']} <b>{pet['name']}</b> · ур. <b>{pet['level']}</b>"


def _user_profile_text(
    user: dict,
    ai_info: dict,
    tstats: dict,
    zefirki: int,
    pet: dict | None,
    daily_available: bool,
    active_games_count: int,
    active_listings_count: int,
) -> str:
    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
    username = f"@{user['username']}" if user.get("username") else "—"
    daily = "доступна" if daily_available else "забрана"

    return (
        "👤 <b>Профиль</b>\n\n"
        f"👤 <b>{name}</b>\n"
        f"🔖 {username}\n"
        f"🍬 Баланс: <b>{_money(zefirki)}</b>\n"
        f"{_pet_line(pet)}\n"
        f"🎁 Халява дня: <b>{daily}</b>\n\n"
        f"🎮 Активные игры: <b>{active_games_count}</b>\n"
        f"🏪 Активные лоты: <b>{active_listings_count}</b>\n"
        f"🤖 AI: <b>{ai_info['remaining']}</b> доступно\n"
        f"📬 Тикеты: <b>{tstats['replied']}</b>/<b>{tstats['total']}</b> отвечено"
    )


def _user_profile_details_text(user: dict, ai_info: dict, tstats: dict, zefirki: int, txs: list) -> str:
    reset_str = _format_reset_timer(ai_info["reset_at"])
    bonus_line = f"\n🎁 Бонус от владельца: <b>+{ai_info['bonus']}</b>" if ai_info.get("bonus") else ""
    tx_block = "\n".join(_format_tx(tx) for tx in txs[:5]) if txs else "операций пока нет"
    return (
        "📊 <b>Подробности профиля</b>\n\n"
        f"🍬 Баланс: <b>{_money(zefirki)}</b>\n"
        f"🤖 AI: <b>{ai_info['used']}</b>/<b>{config.ai_daily_limit}</b>, "
        f"доступно <b>{ai_info['remaining']}</b>{bonus_line}\n"
        f"⏱ Сброс AI: <b>{reset_str}</b>\n\n"
        f"📬 Тикеты: всего <b>{tstats['total']}</b>, "
        f"новых <b>{tstats['sent']}</b>, просмотрено <b>{tstats['seen']}</b>, "
        f"отвечено <b>{tstats['replied']}</b>\n\n"
        "<b>Последние операции:</b>\n"
        f"{tx_block}"
    )


@router.callback_query(F.data == "profile:me")
async def cb_profile_me(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    ai_info, tstats, zefirki, pet, daily_available, active_games, active_sessions, active_listings = await asyncio.gather(
        get_ai_limit_info(user_id),
        get_user_ticket_stats(user_id),
        get_zefirki_balance(user_id),
        get_pet(user_id),
        _daily_available(user_id),
        list_user_active_games(user_id),
        list_my_sessions(user_id),
        get_my_listings(user_id),
    )

    text = _user_profile_text(
        user,
        ai_info,
        tstats,
        zefirki,
        pet,
        daily_available,
        len(active_games["pve"]) + len(active_games["rooms"]) + len(active_sessions),
        len(active_listings),
    )
    try:
        await callback.message.edit_text(text, reply_markup=profile_menu())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "profile:me:details")
async def cb_profile_me_details(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = await get_user(user_id)
    if not user:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    ai_info = await get_ai_limit_info(user_id)
    tstats = await get_user_ticket_stats(user_id)
    zefirki = await get_zefirki_balance(user_id)
    txs = await get_recent_transactions(user_id, limit=5)
    try:
        await callback.message.edit_text(
            _user_profile_details_text(user, ai_info, tstats, zefirki, txs),
            reply_markup=profile_details_menu(),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "profile:admin")
async def cb_profile_admin(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not config.is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user = await get_user(user_id)
    if not user:
        await callback.answer("Профиль не найден", show_alert=True)
        return

    ai_info = await get_ai_limit_info(user_id)
    tstats = await get_user_ticket_stats(user_id)
    zefirki = await get_zefirki_balance(user_id)

    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
    username = f"@{user['username']}" if user.get("username") else "—"
    reset_str = _format_reset_timer(ai_info["reset_at"])
    bonus_line = f" · бонус <b>+{ai_info['bonus']}</b>" if ai_info.get("bonus") else ""

    text = (
        "👑 <b>Профиль владельца</b>\n\n"
        f"👤 <b>{name}</b>\n"
        f"🔖 {username}\n"
        f"🆔 <code>{user['user_id']}</code>\n"
        f"📅 С {user['created_at'].strftime('%d.%m.%Y')}\n\n"
        f"🍬 Баланс: <b>{_money(zefirki)}</b>\n"
        f"🤖 AI: <b>{ai_info['remaining']}</b> доступно, сброс: <b>{reset_str}</b>{bonus_line}\n"
        f"📬 Твои тикеты: <b>{tstats['replied']}</b>/<b>{tstats['total']}</b> отвечено"
    )

    try:
        await callback.message.edit_text(text, reply_markup=admin_profile_menu())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "profile:admin:stats")
async def cb_profile_admin_stats(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not config.is_admin(user_id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    stats = await get_stats()
    new_24h = await get_new_users_count(24)
    banned = await get_banned_count()
    top_ai = await get_top_ai_users(5)

    top_lines = []
    for i, u in enumerate(top_ai, 1):
        uname = u.get("first_name") or u.get("username") or str(u["user_id"])
        top_lines.append(f"{i}. {uname} — <b>{u['ai_messages_used']}</b>")
    top_block = "\n".join(top_lines) if top_lines else "пока пусто"

    text = (
        "📊 <b>Статистика бота</b>\n\n"
        f"👥 Всего юзеров: <b>{stats['users']}</b>\n"
        f"🆕 За 24 часа: <b>{new_24h}</b>\n"
        f"🚫 Забанено: <b>{banned}</b>\n"
        f"📨 Тикетов: <b>{stats['tickets_total']}</b>, открыто <b>{stats['tickets_open']}</b>\n"
        f"🤖 AI-сообщений: <b>{stats['ai_messages']}</b>\n\n"
        "<b>Топ по AI:</b>\n"
        f"{top_block}"
    )

    try:
        await callback.message.edit_text(text, reply_markup=admin_profile_stats_menu())
    except Exception:
        pass
    await callback.answer()
