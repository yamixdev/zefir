from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.config import config
from bot.keyboards.inline import main_menu, user_tickets_list, ticket_detail_user, ticket_back
from bot.models import create_ticket, get_user_tickets, get_ticket, get_user
from bot.services.ai_service import summarize_ticket

router = Router()


class TicketStates(StatesGroup):
    waiting_message = State()


# ── Create ticket ────────────────────────────────────────────────

@router.callback_query(F.data == "ticket:new")
async def cb_ticket_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TicketStates.waiting_message)
    await callback.message.edit_text(
        "📨 <b>Напиши своё сообщение для админа:</b>\n\n"
        "Я передам его Илье, а также кратко опишу суть.",
        reply_markup=ticket_back(),
    )
    await callback.answer()


@router.message(TicketStates.waiting_message)
async def process_ticket_message(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    user = message.from_user
    text = message.text or "(без текста)"

    # AI interprets the message
    ai_summary = await summarize_ticket(text)

    # Save ticket
    ticket_id = await create_ticket(user.id, text, ai_summary)

    # Confirm to user
    summary_line = f"\n\n🤖 <b>Моя интерпретация:</b> {ai_summary}\n<i>(могу ошибаться 😸)</i>" if ai_summary else ""
    await message.answer(
        f"✅ <b>Тикет #{ticket_id} создан!</b>\n\n"
        f"Мур! 🐱 Я получил твоё сообщение и передал Илье.{summary_line}\n\n"
        f"Админ ответит в ближайшее время.",
        reply_markup=main_menu(),
    )

    # Notify admins
    user_info = await get_user(user.id)
    username = user_info["username"] or f"user_{user.id}" if user_info else f"user_{user.id}"
    name = f'{user_info["first_name"] or ""} {user_info["last_name"] or ""}'.strip() if user_info else str(user.id)

    admin_text = (
        f"📨 <b>НОВЫЙ ТИКЕТ #{ticket_id}</b>\n\n"
        f"👤 <b>{name}</b> (@{username})\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"💬 <b>Сообщение:</b>\n{text}"
    )
    if ai_summary:
        admin_text += f"\n\n🤖 <b>AI-интерпретация:</b>\n{ai_summary}"

    from bot.keyboards.inline import admin_ticket_actions
    for admin_id in config.admins:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_ticket_actions(ticket_id))
        except Exception:
            pass


# ── View user's tickets ──────────────────────────────────────────

@router.callback_query(F.data == "ticket:my")
async def cb_my_tickets(callback: CallbackQuery):
    tickets = await get_user_tickets(callback.from_user.id)
    if not tickets:
        await callback.message.edit_text(
            "📭 <b>У тебя пока нет тикетов.</b>\n\nНапиши админу — создай первый!",
            reply_markup=main_menu(),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"📊 <b>Твои тикеты ({len(tickets)}):</b>",
        reply_markup=user_tickets_list(tickets),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ticket:view:"))
async def cb_view_ticket(callback: CallbackQuery):
    ticket_id = int(callback.data.split(":")[2])
    ticket = await get_ticket(ticket_id)

    if not ticket or ticket["user_id"] != callback.from_user.id:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    status_map = {"open": "🟡 Открыт", "in_progress": "🔵 В работе", "closed": "🟢 Закрыт"}
    status = status_map.get(ticket["status"], ticket["status"])

    text = (
        f"📋 <b>Тикет #{ticket['id']}</b>\n\n"
        f"📌 Статус: {status}\n"
        f"📅 Создан: {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}\n\n"
        f"💬 <b>Сообщение:</b>\n{ticket['message']}"
    )
    if ticket["ai_summary"]:
        text += f"\n\n🤖 <b>AI-интерпретация:</b>\n{ticket['ai_summary']}"
    if ticket["admin_reply"]:
        text += f"\n\n📩 <b>Ответ админа:</b>\n{ticket['admin_reply']}"

    await callback.message.edit_text(text, reply_markup=ticket_detail_user(ticket_id))
    await callback.answer()
