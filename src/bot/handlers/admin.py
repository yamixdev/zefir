from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.config import config
from bot.keyboards.inline import (
    admin_menu, admin_tickets_list, admin_ticket_actions,
    admin_users_list, admin_user_actions, confirm_action, main_menu,
)
from bot.models import (
    get_open_tickets, count_open_tickets, get_ticket, update_ticket_status,
    set_ticket_reply, get_all_users, get_user, set_ban,
    reset_ai_limits_all, reset_ai_limit_user, get_stats, get_users_count,
)

router = Router()

PAGE_SIZE = 10


class AdminStates(StatesGroup):
    waiting_reply = State()      # waiting for ticket reply text
    waiting_broadcast = State()  # waiting for broadcast text


# ── Admin command ────────────────────────────────────────────────

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not config.is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён.")
        return
    await message.answer("👑 <b>Панель администратора</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "adm:menu")
async def cb_admin_menu(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text("👑 <b>Панель администратора</b>", reply_markup=admin_menu())
    await callback.answer()


# ── Statistics ───────────────────────────────────────────────────

@router.callback_query(F.data == "adm:stats")
async def cb_stats(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    stats = await get_stats()
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b>\n"
        f"📨 Тикетов всего: <b>{stats['tickets_total']}</b>\n"
        f"🟡 Открытых: <b>{stats['tickets_open']}</b>\n"
        f"🤖 AI-сообщений: <b>{stats['ai_messages']}</b>"
    )
    await callback.message.edit_text(text, reply_markup=admin_menu())
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
        await callback.message.edit_text(
            "📭 <b>Открытых тикетов нет.</b>", reply_markup=admin_menu()
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"📋 <b>Открытые тикеты ({total}):</b>",
        reply_markup=admin_tickets_list(tickets, page),
    )
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

    user = await get_user(ticket["user_id"])
    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() if user else str(ticket["user_id"])
    username = user["username"] or f"user_{ticket['user_id']}" if user else "?"

    status_map = {"open": "🟡 Открыт", "in_progress": "🔵 В работе", "closed": "🟢 Закрыт"}
    text = (
        f"📋 <b>Тикет #{ticket['id']}</b>\n\n"
        f"👤 {name} (@{username})\n"
        f"📌 Статус: {status_map.get(ticket['status'], ticket['status'])}\n"
        f"📅 {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}\n\n"
        f"💬 <b>Сообщение:</b>\n{ticket['message']}"
    )
    if ticket["ai_summary"]:
        text += f"\n\n🤖 <b>AI:</b> {ticket['ai_summary']}"
    if ticket["admin_reply"]:
        text += f"\n\n📩 <b>Ответ:</b> {ticket['admin_reply']}"

    await callback.message.edit_text(text, reply_markup=admin_ticket_actions(ticket_id))
    await callback.answer()


# ── Reply to ticket ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:reply:"))
async def cb_reply_start(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    ticket_id = int(callback.data.split(":")[2])
    await state.set_state(AdminStates.waiting_reply)
    await state.update_data(reply_ticket_id=ticket_id)
    await callback.message.edit_text(
        f"✍️ <b>Введи ответ на тикет #{ticket_id}:</b>",
    )
    await callback.answer()


@router.message(AdminStates.waiting_reply)
async def process_reply(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    ticket_id = data.get("reply_ticket_id")
    await state.clear()

    if not ticket_id:
        await message.answer("Ошибка: тикет не найден.", reply_markup=admin_menu())
        return

    ticket = await get_ticket(ticket_id)
    if not ticket:
        await message.answer("Тикет не найден.", reply_markup=admin_menu())
        return

    reply_text = message.text or ""
    await set_ticket_reply(ticket_id, reply_text)

    # Send reply to user
    try:
        await bot.send_message(
            ticket["user_id"],
            f"📩 <b>Ответ на тикет #{ticket_id}:</b>\n\n{reply_text}",
            reply_markup=main_menu(),
        )
    except Exception:
        pass

    # Confirm to admin (edit-safe: send new message to avoid stale edit)
    await message.answer(
        f"✅ Ответ на тикет #{ticket_id} отправлен.",
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

    # Refresh the ticket list
    tickets = await get_open_tickets(limit=PAGE_SIZE)
    total = await count_open_tickets()
    if tickets:
        await callback.message.edit_text(
            f"📋 <b>Открытые тикеты ({total}):</b>",
            reply_markup=admin_tickets_list(tickets),
        )
    else:
        await callback.message.edit_text("📭 <b>Открытых тикетов нет.</b>", reply_markup=admin_menu())


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
        await callback.message.edit_text("📭 <b>Пользователей нет.</b>", reply_markup=admin_menu())
        await callback.answer()
        return

    await callback.message.edit_text(
        f"👥 <b>Пользователи ({len(all_users)}):</b>",
        reply_markup=admin_users_list(page_users, page),
    )
    await callback.answer()


# ── User profile (admin) ────────────────────────────────────────

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

    name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🔖 @{user['username'] or '—'}\n"
        f"👤 {name}\n"
        f"🆔 <code>{user['user_id']}</code>\n"
        f"🚫 Бан: {'Да' if user['is_banned'] else 'Нет'}\n"
        f"🤖 AI использовано: {user['ai_messages_used']}\n"
        f"📅 Регистрация: {user['created_at'].strftime('%d.%m.%Y')}"
    )
    await callback.message.edit_text(text, reply_markup=admin_user_actions(user_id, user["is_banned"]))
    await callback.answer()


# ── Ban / Unban ──────────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm:ban:"))
async def cb_ban(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    user_id = int(callback.data.split(":")[2])
    await set_ban(user_id, True)
    await callback.answer("🚫 Пользователь забанен", show_alert=True)
    # Refresh profile
    user = await get_user(user_id)
    if user:
        name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🔖 @{user['username'] or '—'}\n"
            f"👤 {name}\n"
            f"🆔 <code>{user['user_id']}</code>\n"
            f"🚫 Бан: Да\n"
            f"🤖 AI использовано: {user['ai_messages_used']}\n"
            f"📅 Регистрация: {user['created_at'].strftime('%d.%m.%Y')}"
        )
        await callback.message.edit_text(text, reply_markup=admin_user_actions(user_id, True))


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
        name = f'{user["first_name"] or ""} {user["last_name"] or ""}'.strip() or "—"
        text = (
            f"👤 <b>Профиль</b>\n\n"
            f"🔖 @{user['username'] or '—'}\n"
            f"👤 {name}\n"
            f"🆔 <code>{user['user_id']}</code>\n"
            f"🚫 Бан: Нет\n"
            f"🤖 AI использовано: {user['ai_messages_used']}\n"
            f"📅 Регистрация: {user['created_at'].strftime('%d.%m.%Y')}"
        )
        await callback.message.edit_text(text, reply_markup=admin_user_actions(user_id, False))


# ── Reset AI limits ──────────────────────────────────────────────

@router.callback_query(F.data == "adm:reset_limits")
async def cb_reset_all_limits(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.message.edit_text(
        "🔄 <b>Сбросить AI-лимиты ВСЕМ пользователям?</b>",
        reply_markup=confirm_action("reset_all"),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:confirm:reset_all")
async def cb_confirm_reset_all(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await reset_ai_limits_all()
    await callback.answer("✅ Лимиты сброшены всем!", show_alert=True)
    await callback.message.edit_text("👑 <b>Панель администратора</b>", reply_markup=admin_menu())


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
    await callback.message.edit_text("📢 <b>Введи текст рассылки:</b>")
    await callback.answer()


@router.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return

    await state.clear()
    text = message.text or ""
    users = await get_all_users()

    sent = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], f"📢 <b>Рассылка:</b>\n\n{text}")
            sent += 1
        except Exception:
            pass

    await message.answer(
        f"✅ Рассылка отправлена: {sent}/{len(users)} пользователей.",
        reply_markup=admin_menu(),
    )
