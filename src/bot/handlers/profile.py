from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.config import config
from bot.keyboards.inline import profile_menu, admin_profile_menu
from bot.models import (
    get_user, get_ai_limit_info, get_user_ticket_stats,
    get_stats, get_new_users_count, get_banned_count, get_top_ai_users,
    get_zefirki_balance, get_recent_transactions,
)


_REASON_LABELS = {
    "welcome": "🎁 Приветственный бонус",
    "daily": "📅 Ежедневный бонус",
    "referral": "👥 Приглашение друга",
    "ticket": "📨 Тикет владельцу",
    "shop": "🛒 Покупка в магазине",
    "case": "📦 Открытие кейса",
    "market": "💱 Сделка на рынке",
    "admin": "👑 От владельца",
}


def _reason_label(reason: str) -> str:
    return _REASON_LABELS.get(reason, reason)


def _format_tx(tx: dict) -> str:
    sign = "+" if tx["amount"] >= 0 else ""
    return f"  {sign}{tx['amount']} — {_reason_label(tx['reason'])}"

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


def _user_profile_text(user: dict, ai_info: dict, tstats: dict, zefirki: int, txs: list) -> str:
    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
    username = f"@{user['username']}" if user.get("username") else "—"
    reset_str = _format_reset_timer(ai_info["reset_at"])
    bonus_line = f"🎁 Бонус от владельца: <b>+{ai_info['bonus']}</b>\n" if ai_info.get("bonus") else ""

    tx_block = "\n".join(_format_tx(tx) for tx in txs[:5]) if txs else "  — пока пусто —"

    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "       👤 <b>МОЙ ПРОФИЛЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{name}</b>\n"
        f"🔖 {username}\n"
        f"🆔 <code>{user['user_id']}</code>\n"
        f"📅 С нами с {user['created_at'].strftime('%d.%m.%Y')}\n\n"
        "━━━ <b>💰 Зефирки</b> ━━━\n"
        f"Баланс: <b>{zefirki}</b> 🍬\n"
        "<i>Последние операции:</i>\n"
        f"{tx_block}\n\n"
        "━━━ <b>🤖 Зефир (AI)</b> ━━━\n"
        f"Использовано: <b>{ai_info['used']}</b> из <b>{config.ai_daily_limit}</b>\n"
        f"{bonus_line}"
        f"Доступно: <b>{ai_info['remaining']}</b>\n"
        f"Сброс через: <b>{reset_str}</b>\n\n"
        "━━━ <b>📬 Мои тикеты</b> ━━━\n"
        f"Всего: <b>{tstats['total']}</b>\n"
        f"📤 Отправлено: <b>{tstats['sent']}</b>\n"
        f"👁 Просмотрено: <b>{tstats['seen']}</b>\n"
        f"✅ Отвечено: <b>{tstats['replied']}</b>"
    )


@router.callback_query(F.data == "profile:me")
async def cb_profile_me(callback: CallbackQuery):
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
            _user_profile_text(user, ai_info, tstats, zefirki, txs),
            reply_markup=profile_menu(),
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
    stats = await get_stats()
    new_24h = await get_new_users_count(24)
    banned = await get_banned_count()
    top_ai = await get_top_ai_users(5)
    zefirki = await get_zefirki_balance(user_id)

    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
    username = f"@{user['username']}" if user.get("username") else "—"
    reset_str = _format_reset_timer(ai_info["reset_at"])
    bonus_line = f"🎁 Свой бонус: <b>+{ai_info['bonus']}</b>\n" if ai_info.get("bonus") else ""

    top_lines = []
    for i, u in enumerate(top_ai, 1):
        uname = u.get("first_name") or u.get("username") or str(u["user_id"])
        top_lines.append(f"  {i}. {uname} — <b>{u['ai_messages_used']}</b>")
    top_block = "\n".join(top_lines) if top_lines else "  — пока пусто —"

    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "   👑 <b>ПРОФИЛЬ ВЛАДЕЛЬЦА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{name}</b>\n"
        f"🔖 {username}\n"
        f"🆔 <code>{user['user_id']}</code>\n"
        f"🏆 Статус: <b>Владелец бота</b>\n"
        f"📅 С {user['created_at'].strftime('%d.%m.%Y')}\n\n"
        "━━━ <b>💰 Твой баланс</b> ━━━\n"
        f"Зефирки: <b>{zefirki}</b> 🍬\n\n"
        "━━━ <b>🤖 Твой AI</b> ━━━\n"
        f"Использовано: <b>{ai_info['used']}</b> из <b>{config.ai_daily_limit}</b>\n"
        f"{bonus_line}"
        f"Доступно: <b>{ai_info['remaining']}</b>\n"
        f"Сброс через: <b>{reset_str}</b>\n\n"
        "━━━ <b>📬 Твои тикеты</b> ━━━\n"
        f"Всего: <b>{tstats['total']}</b> | "
        f"📤 <b>{tstats['sent']}</b> | "
        f"👁 <b>{tstats['seen']}</b> | "
        f"✅ <b>{tstats['replied']}</b>\n\n"
        "━━━ <b>🌐 Статистика бота</b> ━━━\n"
        f"👥 Всего юзеров: <b>{stats['users']}</b>\n"
        f"🆕 За 24 часа: <b>{new_24h}</b>\n"
        f"🚫 Забанено: <b>{banned}</b>\n"
        f"📨 Тикетов: <b>{stats['tickets_total']}</b> (открыто: <b>{stats['tickets_open']}</b>)\n"
        f"🤖 AI-сообщений: <b>{stats['ai_messages']}</b>\n\n"
        "━━━ <b>🔥 Топ по AI</b> ━━━\n"
        f"{top_block}"
    )

    try:
        await callback.message.edit_text(text, reply_markup=admin_profile_menu())
    except Exception:
        pass
    await callback.answer()
