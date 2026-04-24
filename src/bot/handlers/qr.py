"""QR-генератор.

Flow:
  fun_submenu → qr:start → просит ввести текст/URL
  → пользователь пишет → отдаём QR как фото + кнопки.

QR-декодер из фото — отдельно в Фазе 3 (через Yandex Vision BARCODE_DETECTION).
"""
from aiogram import Router, F, Bot
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.services.qr_service import make_qr_png
from bot.utils import smart_edit

router = Router()

MAX_QR_LEN = 2000  # версия 40 QR = ~2953 символов, с запасом


class QRStates(StatesGroup):
    waiting_text = State()


def _qr_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔁 Ещё QR", callback_data="qr:start")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:fun")],
    ])


def _ask_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:fun")],
    ])


@router.callback_query(F.data == "qr:start")
async def cb_qr_start(callback: CallbackQuery, state: FSMContext):
    text = (
        "🔳 <b>QR-генератор</b>\n\n"
        "Пришли текст или ссылку — сделаю QR-код.\n"
        f"<i>До {MAX_QR_LEN} символов.</i>"
    )
    # Под QR-фото нельзя edit_text — smart_edit удалит фото и пришлёт свежее меню
    new_msg = await smart_edit(callback, text, reply_markup=_ask_kb())
    prompt_id = new_msg.message_id if new_msg else callback.message.message_id
    await state.set_state(QRStates.waiting_text)
    await state.update_data(prompt_msg_id=prompt_id)
    await callback.answer()


@router.message(QRStates.waiting_text)
async def msg_qr_text(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    prompt_id = data.get("prompt_msg_id")
    chat_id = message.chat.id
    text = (message.text or "").strip()

    try:
        await message.delete()
    except Exception:
        pass

    if not text:
        return
    if len(text) > MAX_QR_LEN:
        if prompt_id:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=prompt_id,
                    text=f"❌ Слишком длинно — {len(text)} символов. Максимум {MAX_QR_LEN}.",
                    reply_markup=_ask_kb(),
                )
            except Exception:
                pass
        return

    await state.clear()

    # Удаляем prompt перед отправкой фото — «меню-чистка» из инвариантов
    if prompt_id:
        try:
            await bot.delete_message(chat_id, prompt_id)
        except Exception:
            pass

    png = make_qr_png(text)
    preview = text if len(text) <= 100 else text[:97] + "..."
    await bot.send_photo(
        chat_id,
        photo=BufferedInputFile(png, filename="qr.png"),
        caption=f"🔳 <b>QR готов</b>\n\n<code>{preview}</code>",
        reply_markup=_qr_back(),
    )


@router.message(Command("qr"))
async def cmd_qr(message: Message, command: CommandObject, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    text = (command.args or "").strip()
    if not text:
        await bot.send_message(
            message.chat.id,
            "🔳 <b>QR-генератор</b>\n\nИспользуй: <code>/qr текст или ссылка</code>",
            reply_markup=_qr_back(),
        )
        return
    if len(text) > MAX_QR_LEN:
        await bot.send_message(
            message.chat.id,
            f"❌ Слишком длинно — {len(text)} символов. Максимум {MAX_QR_LEN}.",
            reply_markup=_qr_back(),
        )
        return
    png = make_qr_png(text)
    preview = text if len(text) <= 100 else text[:97] + "..."
    await bot.send_photo(
        message.chat.id,
        photo=BufferedInputFile(png, filename="qr.png"),
        caption=f"🔳 <b>QR готов</b>\n\n<code>{preview}</code>",
        reply_markup=_qr_back(),
    )
