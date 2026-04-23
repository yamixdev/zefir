"""Русская локализация логов чужих библиотек (aiogram, psycopg).

Вешается как logging.Filter на соответствующие логгеры — перехватывает
сообщение каждого LogRecord и прогоняет через таблицу regex-переводов.
Так мы не трогаем библиотеки и не ломаем их форматирование.
"""
import logging
import re

# (regex, replacement). Replacement поддерживает \1, \2 и т.д.
_TRANSLATIONS: list[tuple[re.Pattern, str]] = [
    # ── aiogram.event ──────────────────────────────────────────
    (
        re.compile(r"Update id=(\d+) is handled\. Duration (\d+) ms by bot id=(\d+)"),
        r"✅ Обновление \1 обработано за \2 мс (бот \3)",
    ),
    (
        re.compile(r"Update id=(\d+) is not handled\. Duration (\d+) ms by bot id=(\d+)"),
        r"⚠️ Обновление \1 пропущено (нет хендлера) за \2 мс (бот \3)",
    ),
    (
        re.compile(r"Cause exception while process update id=(\d+) by bot id=(\d+)"),
        r"❌ Исключение при обработке обновления \1 (бот \2)",
    ),
    (
        re.compile(r"Start polling"),
        r"▶️ Запускаю long polling",
    ),
    (
        re.compile(r"Polling stopped"),
        r"⏹ Polling остановлен",
    ),
    (
        re.compile(r"Run polling for bot @(\S+) id=(\d+) - '(.+)'"),
        r"▶️ Polling для @\1 (id=\2, имя '\3')",
    ),
    # ── psycopg.pool ───────────────────────────────────────────
    (
        re.compile(r"discarding closed connection:\s*(.+)"),
        r"🐘 Выкидываю мёртвый коннект: \1",
    ),
    (
        re.compile(r"error connecting in '(.+)':\s*(.+)"),
        r"🐘 Ошибка коннекта пула '\1': \2",
    ),
    (
        re.compile(r"connection failed:\s*(.+)"),
        r"🐘 Не удалось подключиться: \1",
    ),
    # ── aiohttp (на всякий случай) ─────────────────────────────
    (
        re.compile(r"Unclosed client session"),
        r"⚠️ Незакрытая HTTP-сессия",
    ),
]


class RussianLocalizer(logging.Filter):
    """Переводит известные английские сообщения на русский прямо в LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True

        for pattern, replacement in _TRANSLATIONS:
            if pattern.search(msg):
                record.msg = pattern.sub(replacement, msg)
                record.args = None  # msg уже отформатирован
                break
        return True


def install_ru_localization() -> None:
    """Вешает локализатор на все шумные внешние логгеры."""
    f = RussianLocalizer()
    for name in ("aiogram.event", "aiogram.dispatcher", "psycopg.pool", "psycopg", "aiohttp"):
        logging.getLogger(name).addFilter(f)
