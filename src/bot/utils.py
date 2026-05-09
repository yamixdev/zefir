from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

TG_MESSAGE_LIMIT = 4096


def tg_safe(text: str, maxlen: int = 4000) -> str:
    """Обрезать текст до лимита Telegram (4096), оставив запас под HTML-хвосты."""
    if len(text) <= maxlen:
        return text
    return text[:maxlen - 30] + "\n\n...(обрезано)"


async def smart_edit(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Эквивалент callback.message.edit_text, но работает под фото-сообщениями.

    `edit_text` не может превратить фото (например, QR) обратно в текст —
    Telegram вернёт ошибку. Поэтому если под кнопкой лежит медиа, удаляем
    сообщение и шлём свежее. Для обычных текстовых — обычный edit.
    """
    msg = callback.message
    if msg is None:
        return None
    if msg.text is not None:
        try:
            return await msg.edit_text(text, reply_markup=reply_markup)
        except Exception:
            pass
    try:
        await msg.delete()
    except Exception:
        pass
    return await callback.bot.send_message(msg.chat.id, text, reply_markup=reply_markup)


async def render_clean_message(
    bot: Bot,
    chat_id: int,
    user_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Удаляет предыдущий активный интерфейс и отправляет новый."""
    from bot.models import get_last_menu_msg_id, set_last_menu_msg_id

    prev_id = await get_last_menu_msg_id(user_id)
    if prev_id:
        try:
            await bot.delete_message(chat_id, prev_id)
        except Exception:
            pass
    msg = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await set_last_menu_msg_id(user_id, msg.message_id)
    return msg


async def render_clean_callback(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message | None:
    """Обновляет текущий интерфейс и запоминает его как активный."""
    from bot.models import set_last_menu_msg_id

    msg = await smart_edit(callback, text, reply_markup=reply_markup)
    if msg:
        await set_last_menu_msg_id(callback.from_user.id, msg.message_id)
    return msg
