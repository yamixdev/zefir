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
