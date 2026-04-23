import logging

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.config import config
from bot.keyboards.inline import main_menu, user_tickets_list, ticket_detail_user, ticket_back
from bot.models import create_ticket, get_user_tickets, get_ticket, get_user, set_last_menu_msg_id
from bot.services.ai_service import summarize_ticket
from bot.utils import tg_safe

logger = logging.getLogger("зефирка.тикеты")
router = Router()


class TicketStates(StatesGroup):
    waiting_message = State()


# ── Create ticket ────────────────────────────────────────────────

@router.callback_query(F.data == "ticket:new")
async def cb_ticket_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TicketStates.waiting_message)
    try:
        await callback.message.edit_text(
            "📨 <b>Напиши своё сообщение для админа:</b>\n\n"
            "Я передам его Илье, а также кратко опишу суть.",
            reply_markup=ticket_back(),
        )
    except Exception:
        pass
    await state.update_data(prompt_msg_id=callback.message.message_id)
    await callback.answer()


@router.message(TicketStates.waiting_message)
async def process_ticket_message(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()

    chat_id = message.chat.id
    user = message.from_user
    text = (message.text or "").strip() or "(без текста)"

    # Delete user's input message
    try:
        await message.delete()
    except Exception:
        pass

    ai_summary = await summarize_ticket(text)
    ticket_id = await create_ticket(user.id, text, ai_summary)
    logger.info("📨 Новый тикет #%d от юзера %d: %s", ticket_id, user.id, text[:60])

    summary_line = (
        f"\n\n🤖 <b>Моя интерпретация:</b> {ai_summary}\n<i>(могу ошибаться 😸)</i>"
        if ai_summary else ""
    )
    confirm_text = (
        f"✅ <b>Тикет #{ticket_id} создан!</b>\n\n"
        f"Мур! 🐱 Я получил твоё сообщение и передал Илье.{summary_line}\n\n"
        f"Админ ответит в ближайшее время."
    )

    prompt_msg_id = data.get("prompt_msg_id")
    menu_msg_id = prompt_msg_id
    if prompt_msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=prompt_msg_id,
                text=confirm_text, reply_markup=main_menu(),
            )
        except Exception:
            sent = await bot.send_message(chat_id, confirm_text, reply_markup=main_menu())
            menu_msg_id = sent.message_id
    else:
        sent = await bot.send_message(chat_id, confirm_text, reply_markup=main_menu())
        menu_msg_id = sent.message_id

    if menu_msg_id:
        await set_last_menu_msg_id(user.id, menu_msg_id)

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
    admin_text = tg_safe(admin_text)

    from bot.keyboards.inline import admin_ticket_actions
    for admin_id in config.admins:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=admin_ticket_actions(ticket_id))
        except Exception as e:
            logger.warning("⚠️ Не смог уведомить админа %d о тикете #%d: %s", admin_id, ticket_id, e)


# ── View user's tickets ──────────────────────────────────────────

@router.callback_query(F.data == "ticket:my")
async def cb_my_tickets(callback: CallbackQuery):
    tickets = await get_user_tickets(callback.from_user.id)
    if not tickets:
        try:
            await callback.message.edit_text(
                "📭 <b>У тебя пока нет тикетов.</b>\n\nНапиши админу — создай первый!",
                reply_markup=main_menu(),
            )
        except Exception:
            pass
        await callback.answer()
        return

    try:
        await callback.message.edit_text(
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"   📊 <b>ТВОИ ТИКЕТЫ ({len(tickets)})</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📤 — отправлено, не открыто\n"
            "👁 — админ прочитал\n"
            "✅ — админ ответил",
            reply_markup=user_tickets_list(tickets),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ticket:view:"))
async def cb_view_ticket(callback: CallbackQuery):
    ticket_id = int(callback.data.split(":")[2])
    ticket = await get_ticket(ticket_id)

    if not ticket or ticket["user_id"] != callback.from_user.id:
        await callback.answer("Тикет не найден", show_alert=True)
        return

    if ticket["status"] == "closed":
        status = "✅ Отвечен" if ticket["admin_reply"] else "⚫ Закрыт"
    elif ticket.get("seen_at"):
        status = "👁 Просмотрено админом"
    else:
        status = "📤 Отправлено, ждёт просмотра"

    text = (
        f"📋 <b>Тикет #{ticket['id']}</b>\n\n"
        f"📌 Статус: {status}\n"
        f"📅 Создан: {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
    )
    if ticket.get("seen_at"):
        text += f"👁 Просмотрен: {ticket['seen_at'].strftime('%d.%m.%Y %H:%M')}\n"
    text += f"\n💬 <b>Сообщение:</b>\n{ticket['message']}"
    if ticket["ai_summary"]:
        text += f"\n\n🤖 <b>AI-интерпретация:</b>\n{ticket['ai_summary']}"
    if ticket["admin_reply"]:
        text += f"\n\n📩 <b>Ответ админа:</b>\n{ticket['admin_reply']}"

    try:
        await callback.message.edit_text(text, reply_markup=ticket_detail_user(ticket_id))
    except Exception:
        pass
    await callback.answer()
