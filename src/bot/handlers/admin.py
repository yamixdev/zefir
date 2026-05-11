import logging
import html

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.config import config

logger = logging.getLogger("зефирка.админ")
from bot.keyboards.inline import (
    admin_menu, admin_tickets_list, admin_ticket_actions,
    admin_users_list, admin_user_actions, confirm_action, main_menu,
    grant_user_list, grant_comment_choice, grant_cancel_kb,
    admin_ban_reasons, admin_incidents_list, admin_incident_actions,
    incident_user_close,
)
from bot.services.time_service import format_msk
from bot.models import (
    get_open_tickets, count_open_tickets, get_ticket, update_ticket_status,
    set_ticket_reply, get_all_users, get_user, set_ban,
    reset_ai_limits_all, reset_ai_limit_user, get_stats, get_users_count,
    mark_ticket_seen, get_last_menu_msg_id, set_last_menu_msg_id,
    grant_ai_bonus, get_online_users, get_user_activity, mark_bot_blocked,
    list_incidents, get_incident, close_incident,
)
from bot.utils import tg_safe

router = Router()

PAGE_SIZE = 10


class AdminStates(StatesGroup):
    waiting_reply = State()
    waiting_broadcast = State()
    waiting_grant_amount = State()
    waiting_grant_comment = State()
    waiting_ban_reason = State()
    waiting_incident_note = State()


BAN_REASONS = {
    "spam": "Спам / флуд",
    "abuse": "Абуз экономики или игровых механик",
    "toxicity": "Оскорбления или токсичное поведение",
}


# ── Admin command ────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    if not config.is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён.")
        return

    stats = await get_stats()
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "     👑 <b>ПАНЕЛЬ АДМИНА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"📨 Тикетов: <b>{stats['tickets_total']}</b> (открыто: <b>{stats['tickets_open']}</b>)\n"
        f"🤖 AI-сообщений: <b>{stats['ai_messages']}</b>\n\n"
        "Выбери действие:"
    )

    prev_id = await get_last_menu_msg_id(message.from_user.id)
    if prev_id:
        try:
            await bot.delete_message(message.chat.id, prev_id)
        except Exception:
            pass
    msg = await message.answer(text, reply_markup=admin_menu())
    await set_last_menu_msg_id(message.from_user.id, msg.message_id)


@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()

    stats = await get_stats()
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "     👑 <b>ПАНЕЛЬ АДМИНА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"📨 Тикетов: <b>{stats['tickets_total']}</b> (открыто: <b>{stats['tickets_open']}</b>)\n"
        f"🤖 AI-сообщений: <b>{stats['ai_messages']}</b>\n\n"
        "Выбери действие:"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_menu())
    except Exception:
        pass
    await callback.answer()


# ── Statistics ───────────────────────────────────────────────────

@router.callback_query(F.data == "adm:stats")
async def cb_stats(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    stats = await get_stats()
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "      📊 <b>СТАТИСТИКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Пользователей  ─  <b>{stats['users']}</b>\n"
        f"📨 Тикетов всего  ─  <b>{stats['tickets_total']}</b>\n"
        f"🟡 Открытых       ─  <b>{stats['tickets_open']}</b>\n"
        f"🤖 AI-сообщений   ─  <b>{stats['ai_messages']}</b>\n"
    )
    try:
        await callback.message.edit_text(text, reply_markup=admin_menu())
    except Exception:
        pass
    await callback.answer()


# ── Tickets list ─────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^adm:tickets(:\d+)?$"))
async def cb_tickets_list(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0
    offset = page * PAGE_SIZE

    tickets = await get_open_tickets(limit=PAGE_SIZE, offset=offset)
    total = await count_open_tickets()

    if not tickets:
        try:
            await callback.message.edit_text(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "      📋 <b>ТИКЕТЫ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📭 Открытых тикетов нет.\n"
                "Все обращения обработаны!",
                reply_markup=admin_menu(),
            )
        except Exception:
            pass
        await callback.answer()
        return

    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "      📋 <b>ТИКЕТЫ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Открытых: <b>{total}</b> | Стр. {page + 1}",
            reply_markup=admin_tickets_list(tickets, page),
        )
    except Exception:
        pass
    await callback.answer()


# ── Ticket detail ────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:ticket:"))
async def cb_ticket_detail(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[2])
    ticket = await get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    # Mark ticket as seen by admin (idempotent)
    if ticket["status"] != "closed":
        await mark_ticket_seen(ticket_id)
        ticket = await get_ticket(ticket_id)

    user = await get_user(ticket["user_id"])
    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() if user else str(ticket["user_id"])
    username = user["username"] or f"user_{ticket['user_id']}" if user else "?"

    status_map = {"open": "🟡 Открыт", "in_progress": "🔵 В работе", "closed": "🟢 Закрыт"}
    text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"   📋 <b>ТИКЕТ #{ticket['id']}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{name}</b> (@{username})\n"
        f"🆔 <code>{ticket['user_id']}</code>\n"
        f"📌 {status_map.get(ticket['status'], ticket['status'])}\n"
        f"📅 {format_msk(ticket['created_at'])} МСК\n\n"
        f"💬 <b>Сообщение:</b>\n<i>{ticket['message']}</i>"
    )
    if ticket["ai_summary"]:
        text += f"\n\n🤖 <b>AI:</b>\n<i>{ticket['ai_summary']}</i>"
    if ticket["admin_reply"]:
        text += f"\n\n📩 <b>Ваш ответ:</b>\n<i>{ticket['admin_reply']}</i>"

    try:
        await callback.message.edit_text(text, reply_markup=admin_ticket_actions(ticket_id))
    except Exception:
        pass
    await callback.answer()


# ── Reply to ticket ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:reply:"))
async def cb_reply_start(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.waiting_reply)
    # Запоминаем id сообщения с тикетом чтобы потом свернуть его в "✅ Отвечено"
    await state.update_data(
        reply_ticket_id=ticket_id,
        reply_source_chat_id=callback.message.chat.id,
        reply_source_msg_id=callback.message.message_id,
    )
    try:
        await callback.message.edit_text(
            f"✍️ <b>Ответ на #{ticket_id}</b>\n\n"
            "Введи текст ответа пользователю:",
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminStates.waiting_reply)
async def process_reply(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    source_chat_id = data.get("reply_source_chat_id")
    source_msg_id = data.get("reply_source_msg_id")
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    if not ticket_id:
        await message.answer("Ошибка: тикет не найден.", reply_markup=admin_menu())
        return

    ticket = await get_ticket(ticket_id)
    if not ticket:
        await message.answer("Тикет не найден.", reply_markup=admin_menu())
        return

    reply_text = message.text or ""
    await set_ticket_reply(ticket_id, reply_text)
    logger.info("✅ Админ %d ответил на тикет #%d: %s",
                message.from_user.id, ticket_id, reply_text[:60])

    # ── Отправляем ответ юзеру и удаляем его старое меню ────────
    user_reply_text = tg_safe(
        f"📩 <b>Ответ на тикет #{ticket_id}</b>\n\n{reply_text}"
    )
    prev_menu_id = await get_last_menu_msg_id(ticket["user_id"])
    try:
        if prev_menu_id:
            try:
                await bot.delete_message(ticket["user_id"], prev_menu_id)
            except Exception:
                pass
        sent = await bot.send_message(
            ticket["user_id"], user_reply_text, reply_markup=main_menu(),
        )
        await set_last_menu_msg_id(ticket["user_id"], sent.message_id)
    except Exception as e:
        logger.warning("⚠️ Не смог доставить ответ юзеру %d на тикет #%d: %s",
                       ticket["user_id"], ticket_id, e)

    # ── Сворачиваем у админа оригинальный тикет в "✅ Отвечено" ─
    collapsed = tg_safe(
        f"✅ <b>Тикет #{ticket_id} отвечен</b>\n\n"
        f"<i>Твой ответ:</i>\n{reply_text}"
    )
    if source_chat_id and source_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=source_chat_id, message_id=source_msg_id,
                text=collapsed, reply_markup=admin_menu(),
            )
            return
        except Exception:
            pass
    # Fallback если edit не прошёл (например, сообщение уже удалено)
    await message.answer(collapsed, reply_markup=admin_menu())

    await message.answer(
        f"✅ Ответ на тикет #{ticket_id} отправлен!",
        reply_markup=admin_menu(),
    )


# ── Close ticket ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:close:"))
async def cb_close_ticket(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[2])
    await update_ticket_status(ticket_id, "closed")
    await callback.answer(f"Тикет #{ticket_id} закрыт ✅", show_alert=True)

    # Refresh ticket list
    tickets = await get_open_tickets(limit=PAGE_SIZE)
    total = await count_open_tickets()
    if tickets:
        try:
            await callback.message.edit_text(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "      📋 <b>ТИКЕТЫ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Открытых: <b>{total}</b>",
                reply_markup=admin_tickets_list(tickets),
            )
        except Exception:
            pass
    else:
        try:
            await callback.message.edit_text(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "      📋 <b>ТИКЕТЫ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📭 Все тикеты закрыты!",
                reply_markup=admin_menu(),
            )
        except Exception:
            pass


# ── Users list ───────────────────────────────────────────────────

@router.callback_query(F.data.regexp(r"^adm:users(:\d+)?$"))
async def cb_users_list(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    all_users = await get_all_users()
    start = page * PAGE_SIZE
    page_users = all_users[start:start + PAGE_SIZE]

    if not page_users:
        try:
            await callback.message.edit_text(
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "      👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📭 Пользователей пока нет.",
                reply_markup=admin_menu(),
            )
        except Exception:
            pass
        await callback.answer()
        return

    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "      👥 <b>ПОЛЬЗОВАТЕЛИ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Всего: <b>{len(all_users)}</b> | Стр. {page + 1}",
            reply_markup=admin_users_list(page_users, page),
        )
    except Exception:
        pass
    await callback.answer()


# ── User profile (admin) ────────────────────────────────────────

def _user_profile_text(user: dict) -> str:
    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
    ban_status = "🔴 Заблокирован" if user["is_banned"] else "🟢 Активен"
    bonus = user.get("ai_bonus") or 0
    bonus_line = f"🎁 AI-бонус: <b>+{bonus}</b>\n" if bonus else ""
    link = f'<a href="tg://user?id={user["user_id"]}">Открыть профиль Telegram</a>'
    blocked = user.get("bot_blocked_at")
    blocked_line = f"\n🚫 Бот в ЧС: <b>{format_msk(blocked)}</b> МСК" if blocked else ""
    active = user.get("last_active_at")
    active_line = f"\n🟢 Последняя активность: <b>{format_msk(active)}</b> МСК" if active else ""
    reason_line = ""
    if user["is_banned"] and user.get("ban_reason_text"):
        reason_line = f"\nПричина: <i>{html.escape(user['ban_reason_text'])}</i>"
    return (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "      👤 <b>ПРОФИЛЬ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>{name}</b>\n"
        f"🔖 @{user['username'] or '—'}\n"
        f"🆔 <code>{user['user_id']}</code>\n\n"
        f"🔗 {link}\n"
        f"📌 Статус: {ban_status}{reason_line}{active_line}{blocked_line}\n"
        f"🤖 AI использовано: <b>{user['ai_messages_used']}</b> из <b>{config.ai_daily_limit}</b>\n"
        f"{bonus_line}"
        f"📅 Регистрация: {format_msk(user['created_at'], '%d.%m.%Y')}"
    )


@router.callback_query(F.data.startswith("adm:user:"))
async def cb_user_detail(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    user_id = int(callback.data.split(":")[2])
    user = await get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return

    try:
        await callback.message.edit_text(
            _user_profile_text(user),
            reply_markup=admin_user_actions(user_id, user["is_banned"]),
        )
    except Exception:
        pass
    await callback.answer()


# ── Ban / Unban ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:ban_menu:"))
async def cb_ban_menu(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        "🚫 <b>Бан пользователя</b>\n\nВыбери причину. Она сохранится в профиле пользователя.",
        reply_markup=admin_ban_reasons(user_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:ban_reason:"))
async def cb_ban_reason(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, _, user_id_raw, reason_code = callback.data.split(":", 3)
    user_id = int(user_id_raw)
    reason_text = BAN_REASONS.get(reason_code, reason_code)
    await state.clear()
    await set_ban(user_id, True, reason_code=reason_code, reason_text=reason_text, banned_by=callback.from_user.id)
    await callback.answer("🚫 Пользователь забанен", show_alert=True)
    user = await get_user(user_id)
    if user:
        try:
            await callback.message.edit_text(
                _user_profile_text(user),
                reply_markup=admin_user_actions(user_id, True),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("adm:ban_custom:"))
async def cb_ban_custom(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.waiting_ban_reason)
    await state.update_data(ban_user_id=user_id, ban_prompt_msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "✍️ <b>Своя причина бана</b>\n\nНапиши короткую причину для админ-журнала:",
        reply_markup=admin_ban_reasons(user_id),
    )
    await callback.answer()


@router.message(AdminStates.waiting_ban_reason)
async def process_custom_ban_reason(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    user_id = int(data.get("ban_user_id") or 0)
    prompt_msg_id = data.get("ban_prompt_msg_id")
    reason = (message.text or "").strip()[:300] or "Своя причина"
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    if not user_id:
        return
    await set_ban(user_id, True, reason_code="custom", reason_text=reason, banned_by=message.from_user.id)
    user = await get_user(user_id)
    if prompt_msg_id and user:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=prompt_msg_id,
                text=_user_profile_text(user),
                reply_markup=admin_user_actions(user_id, True),
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("adm:unban:"))
async def cb_unban(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    await set_ban(user_id, False)
    await callback.answer("✅ Пользователь разбанен", show_alert=True)
    user = await get_user(user_id)
    if user:
        try:
            await callback.message.edit_text(
                _user_profile_text(user),
                reply_markup=admin_user_actions(user_id, False),
            )
        except Exception:
            pass


@router.callback_query(F.data == "adm:online")
async def cb_admin_online(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    users = await get_online_users(minutes=15, limit=30)
    lines = ["🟢 <b>Сейчас онлайн</b>\n", "Активность за последние 15 минут.\n"]
    if not users:
        lines.append("Сейчас активных пользователей нет.")
    for user in users:
        name = user.get("first_name") or user.get("username") or str(user["user_id"])
        at = format_msk(user["last_active_at"], "%H:%M") if user.get("last_active_at") else "—"
        action = html.escape(user.get("last_action") or "—")
        blocked = " · ЧС" if user.get("bot_blocked_at") else ""
        lines.append(f"• <a href=\"tg://user?id={user['user_id']}\">{html.escape(name)}</a> · {at} · {action}{blocked}")
    await callback.message.edit_text("\n".join(lines), reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(F.data.startswith("adm:activity:"))
async def cb_admin_activity(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    events = await get_user_activity(user_id, limit=20)
    lines = [f"🧾 <b>Действия пользователя</b>\n\n🆔 <code>{user_id}</code>\n"]
    if not events:
        lines.append("Журнала действий пока нет.")
    for event in events:
        at = format_msk(event["created_at"], "%d.%m %H:%M")
        lines.append(f"• {at} · {html.escape(event['event_type'])} · {html.escape(event['action'])}")
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=admin_user_actions(user_id, (await get_user(user_id))["is_banned"]),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("adm:probe:"))
async def cb_probe_user(callback: CallbackQuery, bot: Bot):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    try:
        msg = await bot.send_message(user_id, ".")
        try:
            await bot.delete_message(user_id, msg.message_id)
        except TelegramBadRequest:
            pass
        await mark_bot_blocked(user_id, False)
        await callback.answer("Сообщение доставилось, бот не в ЧС.", show_alert=True)
    except TelegramForbiddenError:
        await mark_bot_blocked(user_id, True)
        await callback.answer("Пользователь заблокировал бота или недоступен.", show_alert=True)
    except Exception as e:
        await callback.answer(f"Не удалось проверить: {e.__class__.__name__}", show_alert=True)
    user = await get_user(user_id)
    if user:
        await callback.message.edit_text(_user_profile_text(user), reply_markup=admin_user_actions(user_id, user["is_banned"]))


@router.callback_query(F.data.regexp(r"^adm:incidents(:\d+)?$"))
async def cb_incidents(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0
    incidents = await list_incidents(status="open", limit=10, offset=page * 10)
    text = "🚨 <b>Инциденты</b>\n\n"
    text += "Открытых инцидентов нет." if not incidents else f"Открытые ошибки и баг-репорты · стр. {page + 1}"
    await callback.message.edit_text(text, reply_markup=admin_incidents_list(incidents, page))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:incident:"))
async def cb_incident_detail(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    incident_id = int(callback.data.split(":")[2])
    incident = await get_incident(incident_id)
    if not incident:
        await callback.answer("Инцидент не найден", show_alert=True)
        return
    user_line = "—"
    if incident.get("user_id"):
        name = incident.get("first_name") or incident.get("username") or str(incident["user_id"])
        user_line = f'<a href="tg://user?id={incident["user_id"]}">{html.escape(name)}</a> · <code>{incident["user_id"]}</code>'
    tb = (incident.get("traceback_text") or "").strip()
    if len(tb) > 1400:
        tb = tb[:1400] + "\n..."
    text = (
        f"🚨 <b>Инцидент #{incident['id']}</b>\n\n"
        f"Статус: <b>{html.escape(incident['status'])}</b>\n"
        f"Тип: <b>{html.escape(incident['event_type'])}</b>\n"
        f"Пользователь: {user_line}\n"
        f"Действие: <code>{html.escape(incident.get('action') or '—')}</code>\n"
        f"Дата: <b>{format_msk(incident['created_at'])}</b> МСК\n\n"
        f"<b>{html.escape(incident['title'])}</b>\n"
        f"{html.escape(incident.get('message') or '')}"
    )
    if tb:
        text += f"\n\n<pre>{html.escape(tb)}</pre>"
    await callback.message.edit_text(text, reply_markup=admin_incident_actions(incident_id))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:incident_close:"))
async def cb_incident_close_start(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    _, _, incident_id, status = callback.data.split(":")
    await state.set_state(AdminStates.waiting_incident_note)
    await state.update_data(incident_id=int(incident_id), incident_status=status, incident_msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "✍️ <b>Закрытие инцидента</b>\n\n"
        "Напиши короткий комментарий. Если комментарий не нужен, отправь точку.",
    )
    await callback.answer()


@router.message(AdminStates.waiting_incident_note)
async def process_incident_note(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass
    incident_id = int(data.get("incident_id") or 0)
    status_raw = data.get("incident_status") or "fixed"
    status = "fixed" if status_raw == "fixed" else "wontfix"
    note = (message.text or "").strip()
    if note == ".":
        note = ""
    incident = await close_incident(incident_id, status, note, message.from_user.id)
    if incident and incident.get("user_id"):
        label = "исправлен" if status == "fixed" else "закрыт"
        user_text = (
            f"🛠 <b>Инцидент #{incident_id} {label}</b>\n\n"
            f"{html.escape(note) if note else 'Спасибо, что помог найти проблему.'}"
        )
        try:
            await bot.send_message(incident["user_id"], user_text, reply_markup=incident_user_close())
        except Exception:
            pass
    await message.answer(f"✅ Инцидент #{incident_id} закрыт.", reply_markup=admin_menu())


# ── Reset AI limits ──────────────────────────────────────────────

@router.callback_query(F.data == "adm:reset_limits")
async def cb_reset_all_limits(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "      🔄 <b>СБРОС ЛИМИТОВ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Сбросить AI-лимиты <b>ВСЕМ</b> пользователям?\n"
            f"Это обнулит счётчики и даст новые {config.ai_daily_limit} сообщений.",
            reply_markup=confirm_action("reset_all"),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "adm:confirm:reset_all")
async def cb_confirm_reset_all(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await reset_ai_limits_all()
    await callback.answer("✅ Лимиты сброшены всем!", show_alert=True)

    stats = await get_stats()
    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "     👑 <b>ПАНЕЛЬ АДМИНА</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Пользователей: <b>{stats['users']}</b>\n"
            f"📨 Тикетов: <b>{stats['tickets_total']}</b> (открыто: <b>{stats['tickets_open']}</b>)\n"
            f"🤖 AI-сообщений: <b>{stats['ai_messages']}</b>\n\n"
            "✅ <b>Лимиты сброшены!</b>\nВыбери действие:",
            reply_markup=admin_menu(),
        )
    except Exception:
        pass


@router.callback_query(F.data.startswith("adm:resetlim:"))
async def cb_reset_user_limit(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    await reset_ai_limit_user(user_id)
    await callback.answer(f"✅ Лимит сброшен для {user_id}", show_alert=True)


# ── Broadcast ────────────────────────────────────────────────────

@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast_start(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_broadcast)
    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "      📢 <b>РАССЫЛКА</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Введи текст рассылки.\n"
            "Он будет отправлен <b>всем</b> пользователям бота.",
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return

    await state.clear()
    text = message.text or ""

    try:
        await message.delete()
    except Exception:
        pass

    users = await get_all_users()

    broadcast_text = tg_safe(
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "      📢 <b>ОБЪЯВЛЕНИЕ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{text}"
    )
    sent = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], broadcast_text)
            sent += 1
        except Exception:
            pass

    logger.info("📢 Рассылка: доставлено %d из %d", sent, len(users))
    await message.answer(
        f"✅ Рассылка завершена: <b>{sent}/{len(users)}</b> пользователей.",
        reply_markup=admin_menu(),
    )


# ── Grant AI bonus flow ──────────────────────────────────────────

GRANT_PAGE_SIZE = 10


def _user_display_name(user: dict) -> str:
    return user.get("first_name") or user.get("username") or str(user["user_id"])


@router.callback_query(F.data.regexp(r"^adm:grant_menu(:\d+)?$"))
async def cb_grant_menu(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 else 0

    all_users = await get_all_users()
    start = page * GRANT_PAGE_SIZE
    page_users = all_users[start:start + GRANT_PAGE_SIZE]

    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "    🎁 <b>НАЧИСЛИТЬ AI-ЛИМИТ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Выбери юзера, которому хочешь начислить запросы к Зефиру.\n"
            f"<i>Стр. {page + 1}</i>",
            reply_markup=grant_user_list(page_users, page, admin_id=callback.from_user.id),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("adm:grant_pick:"))
async def cb_grant_pick(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    target_id = int(callback.data.split(":")[2])
    target = await get_user(target_id)
    if not target:
        await callback.answer("Юзер не найден", show_alert=True)
        return

    name = _user_display_name(target)
    current_bonus = target.get("ai_bonus") or 0

    await state.set_state(AdminStates.waiting_grant_amount)
    await state.update_data(grant_target_id=target_id, grant_prompt_msg_id=callback.message.message_id)

    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "    🎁 <b>НАЧИСЛЕНИЕ AI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Юзер: <b>{name}</b>\n"
            f"🆔 <code>{target_id}</code>\n"
            f"Текущий бонус: <b>+{current_bonus}</b>\n\n"
            "Сколько запросов начислить?\n"
            "<i>Напиши число (например, 50)</i>",
            reply_markup=grant_cancel_kb(),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminStates.waiting_grant_amount)
async def process_grant_amount(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        await message.delete()
    except Exception:
        pass

    raw = (message.text or "").strip()
    try:
        amount = int(raw)
    except ValueError:
        amount = 0

    data = await state.get_data()
    prompt_msg_id = data.get("grant_prompt_msg_id")
    target_id = data.get("grant_target_id")

    if amount <= 0 or amount > 10000:
        err_text = (
            "❌ Нужно целое число от 1 до 10000.\n"
            "<i>Попробуй ещё раз:</i>"
        )
        if prompt_msg_id:
            try:
                await bot.edit_message_text(
                    chat_id=message.chat.id, message_id=prompt_msg_id,
                    text=err_text, reply_markup=grant_cancel_kb(),
                )
            except Exception:
                pass
        return

    await state.update_data(grant_amount=amount)
    await state.set_state(None)  # keep data, exit input state — wait for callback

    target = await get_user(target_id) if target_id else None
    name = _user_display_name(target) if target else str(target_id)

    confirm_text = (
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "    🎁 <b>ПОДТВЕРЖДЕНИЕ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>{name}</b> получит: <b>+{amount}</b> запросов к Зефиру.\n\n"
        "Хочешь добавить комментарий для юзера?"
    )
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=message.chat.id, message_id=prompt_msg_id,
                text=confirm_text, reply_markup=grant_comment_choice(),
            )
        except Exception:
            pass


@router.callback_query(F.data == "adm:grant_no_comment")
async def cb_grant_no_comment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await _execute_grant(callback, state, bot, comment=None)


@router.callback_query(F.data == "adm:grant_with_comment")
async def cb_grant_with_comment(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminStates.waiting_grant_comment)
    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "    ✍️ <b>КОММЕНТАРИЙ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Напиши сообщение, которое юзер увидит вместе с начислением.\n"
            "<i>Можно коротко: «за помощь с тестированием» и т.д.</i>",
            reply_markup=grant_cancel_kb(),
        )
    except Exception:
        pass
    await callback.answer()


@router.message(AdminStates.waiting_grant_comment)
async def process_grant_comment(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return

    comment = (message.text or "").strip()
    try:
        await message.delete()
    except Exception:
        pass

    await _execute_grant_msg(message.chat.id, message.from_user.id, state, bot, comment=comment or None)


async def _execute_grant(callback: CallbackQuery, state: FSMContext, bot: Bot, comment: str | None):
    await _execute_grant_msg(callback.message.chat.id, callback.from_user.id, state, bot, comment)
    await callback.answer("🎁 Начислено!")


async def _execute_grant_msg(chat_id: int, admin_id: int, state: FSMContext, bot: Bot, comment: str | None):
    data = await state.get_data()
    target_id = data.get("grant_target_id")
    amount = data.get("grant_amount")
    prompt_msg_id = data.get("grant_prompt_msg_id")
    await state.clear()

    if not target_id or not amount:
        return

    new_bonus = await grant_ai_bonus(target_id, amount)
    target = await get_user(target_id)
    name = _user_display_name(target) if target else str(target_id)

    logger.info(
        "🎁 Админ %d начислил юзеру %d (%s) +%d к AI (теперь бонус=%d)%s",
        admin_id, target_id, name, amount, new_bonus,
        f", коммент: {comment[:40]}" if comment else "",
    )

    # Result for admin
    result_lines = [
        "━━━━━━━━━━━━━━━━━━━━━━",
        "    ✅ <b>НАЧИСЛЕНО</b>",
        "━━━━━━━━━━━━━━━━━━━━━━\n",
        f"Юзер: <b>{name}</b>",
        f"Начислено: <b>+{amount}</b> запросов",
        f"Новый бонус: <b>+{new_bonus}</b>",
    ]
    if comment:
        result_lines.append(f"\n✍️ Коммент: <i>{comment}</i>")
    result_text = "\n".join(result_lines)

    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=prompt_msg_id,
                text=result_text, reply_markup=admin_menu(),
            )
        except Exception:
            await bot.send_message(chat_id, result_text, reply_markup=admin_menu())
    else:
        await bot.send_message(chat_id, result_text, reply_markup=admin_menu())

    # Notify the target user — удаляем его старое меню, новое = это уведомление
    notif_lines = [
        f"🎁 <b>Подарок от админа</b>\n",
        f"Тебе начислено: <b>+{amount}</b> запросов к Зефиру 🐱",
    ]
    if comment:
        notif_lines.append(f"\n✍️ Сообщение от админа:\n<i>{comment}</i>")
    else:
        notif_lines.append("\n<i>Без комментария — админ был в лаконичном настроении 😺</i>")
    notif_text = "\n".join(notif_lines)

    prev_menu_id = await get_last_menu_msg_id(target_id)
    try:
        if prev_menu_id:
            try:
                await bot.delete_message(target_id, prev_menu_id)
            except Exception:
                pass
        sent = await bot.send_message(target_id, notif_text, reply_markup=main_menu())
        await set_last_menu_msg_id(target_id, sent.message_id)
    except Exception as e:
        logger.warning("⚠️ Не смог уведомить юзера %d о начислении: %s", target_id, e)
