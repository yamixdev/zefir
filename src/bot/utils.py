TG_MESSAGE_LIMIT = 4096


def tg_safe(text: str, maxlen: int = 4000) -> str:
    """Обрезать текст до лимита Telegram (4096), оставив запас под HTML-хвосты."""
    if len(text) <= maxlen:
        return text
    return text[:maxlen - 30] + "\n\n...(обрезано)"
