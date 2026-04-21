import asyncio
import logging
import time

from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from bot.keyboards.inline import (
    ai_exit, ai_exit_confirm, main_menu, consent_menu, consent_back,
)
from bot.models import (
    check_ai_limit, increment_ai_usage,
    save_ai_message, get_ai_history,
    set_last_menu_msg_id,
    has_accepted_consent, accept_consent,
)
from bot.services.ai_service import chat_stream, chat_simple, ocr_image, AIError
from bot.services.consent import TOS_VERSION, TOS_TEXT, PRIVACY_TEXT, docs_hash

logger = logging.getLogger("зефир.чат")
router = Router()

EDIT_INTERVAL = 1.5
CLEANUP_DEPTH = 100
MAX_TG_FILE_MB = 20
MAX_FILE_CONTENT_CHARS = 10000
MAX_OCR_CHARS = 8000

TEXT_LIKE_EXT = {
    ".txt", ".md", ".rst", ".log",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".env",
    ".csv", ".tsv",
    ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".swift",
    ".rb", ".php", ".sh", ".bash", ".zsh", ".ps1",
    ".sql", ".xml",
}
TEXT_LIKE_MIME_PREFIX = ("text/",)
TEXT_LIKE_MIME = {"application/json", "application/xml", "application/x-yaml"}


class AIChatStates(StatesGroup):
    chatting = State()


# ── Helpers ─────────────────────────────────────────────────────

async def _bulk_clean_above(bot: Bot, chat_id: int, top_msg_id: int) -> None:
    """Fire-and-forget cleanup — one bulk call; failures are silent."""
    if top_msg_id <= 0:
        return
    start_id = max(1, top_msg_id - CLEANUP_DEPTH + 1)
    ids = list(range(start_id, top_msg_id + 1))
    try:
        await bot.delete_messages(chat_id, ids)
    except Exception as e:
        logger.debug("🧹 Фоновая очистка не удалась: %s", e)


async def _edit(bot: Bot, chat_id: int, msg_id: int | None, text: str, keyboard=None) -> int | None:
    """Edit AI message if msg_id set; else send new. Returns active msg id."""
    kb = keyboard if keyboard is not None else ai_exit()
    if msg_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb,
            )
            return msg_id
        except Exception:
            pass
    sent = await bot.send_message(chat_id, text, reply_markup=kb)
    return sent.message_id


def _welcome_text(remaining: int) -> str:
    return (
        "🐱 <b>Зефир на связи</b>\n\n"
        "Спрашивай о чём угодно — помогу разобраться 🐾\n\n"
        "🖼 <b>Фото</b> → прочитаю текст с картинки (OCR)\n"
        "<i>что ИЗОБРАЖЕНО — не вижу, только текст</i>\n"
        "📄 <b>Файл</b> (.py .txt .md .csv ...) → разберу содержимое\n"
        "<i>обработка займёт несколько секунд</i>\n\n"
        f"<i>💬 осталось {remaining}</i>"
    )


def _thinking_frame(preview: str) -> str:
    return f"<i>📝 {preview[:200]}</i>\n\n🐱 <i>думаю...</i>"


def _error_frame(preview: str, remaining: int) -> str:
    return (
        f"<i>📝 {preview[:200]}</i>\n\n"
        "😿 Не получилось ответить, попробуй ещё раз.\n"
        "<i>запрос не списался с лимита</i>\n\n"
        f"<i>💬 осталось {remaining}</i>"
    )


def _answer_frame(text: str, remaining: int) -> str:
    return f"🐱 {text}\n\n<i>💬 осталось {remaining}</i>"


# ── Consent flow ────────────────────────────────────────────────

def _consent_intro_text() -> str:
    return (
        "📋 <b>Перед общением с Зефиром</b>\n\n"
        "Я использую AI для ответов — твои сообщения уходят в Yandex Cloud, "
        "история сохраняется в БД (последние 30 сообщений для контекста).\n\n"
        "Прочитай пару строк и прими документы — это быстро 🐾"
    )


@router.callback_query(F.data == "ai:consent_show")
async def cb_consent_show(callback: CallbackQuery):
    try:
        await callback.message.edit_text(_consent_intro_text(), reply_markup=consent_menu())
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "ai:consent_tos")
async def cb_consent_tos(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            f"{TOS_TEXT}\n\n<i>Версия {TOS_VERSION}</i>",
            reply_markup=consent_back(),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "ai:consent_privacy")
async def cb_consent_privacy(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            f"{PRIVACY_TEXT}\n\n<i>Версия {TOS_VERSION}</i>",
            reply_markup=consent_back(),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "ai:consent_decline")
async def cb_consent_decline(callback: CallbackQuery):
    name = callback.from_user.first_name or "друг"
    try:
        await callback.message.edit_text(
            f"🐾 Окей, {name}, без обид.\n\n"
            "Можешь пользоваться другими функциями — погода, тикеты админу "
            "и прочее без AI работают без всяких соглашений.",
            reply_markup=main_menu(),
        )
        await set_last_menu_msg_id(callback.from_user.id, callback.message.message_id)
    except Exception:
        pass
    await callback.answer("Вернулись в меню")


@router.callback_query(F.data == "ai:consent_accept")
async def cb_consent_accept(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    await accept_consent(user_id, TOS_VERSION, docs_hash())
    logger.info("📜 Юзер %d принял документы (v%s)", user_id, TOS_VERSION)
    # Прямо входим в AI
    await _enter_ai_mode(callback, state, bot)


# ── Entry / exit ────────────────────────────────────────────────

async def _enter_ai_mode(callback: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = callback.message.chat.id
    menu_msg_id = callback.message.message_id
    user_id = callback.from_user.id

    _, remaining = await check_ai_limit(user_id)

    ai_msg_id = menu_msg_id
    try:
        await callback.message.edit_text(_welcome_text(remaining), reply_markup=ai_exit())
    except Exception:
        sent = await bot.send_message(chat_id, _welcome_text(remaining), reply_markup=ai_exit())
        ai_msg_id = sent.message_id

    await state.set_state(AIChatStates.chatting)
    await state.update_data(ai_msg_id=ai_msg_id)
    if not callback.message or callback.message.message_id == menu_msg_id:
        await callback.answer("🐱 Зефир на связи!")

    logger.info("🐱 Юзер %d вошёл в режим Зефира", user_id)
    asyncio.create_task(_bulk_clean_above(bot, chat_id, ai_msg_id - 1))


@router.callback_query(F.data == "ai:start")
async def cb_ai_start(callback: CallbackQuery, state: FSMContext, bot: Bot):
    user_id = callback.from_user.id
    if not await has_accepted_consent(user_id, TOS_VERSION):
        try:
            await callback.message.edit_text(_consent_intro_text(), reply_markup=consent_menu())
        except Exception:
            pass
        await callback.answer()
        return

    await _enter_ai_mode(callback, state, bot)


@router.callback_query(F.data == "ai:exit_ask", AIChatStates.chatting)
async def cb_ai_exit_ask(callback: CallbackQuery):
    try:
        await callback.message.edit_text(
            "⚠️ <b>Выйти из чата?</b>\n\n"
            "Переписка очистится, но Зефир тебя не забудет — "
            "история разговора сохранится в памяти 🐱",
            reply_markup=ai_exit_confirm(),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "ai:exit_no", AIChatStates.chatting)
async def cb_ai_exit_no(callback: CallbackQuery):
    _, remaining = await check_ai_limit(callback.from_user.id)
    try:
        await callback.message.edit_text(_welcome_text(remaining), reply_markup=ai_exit())
    except Exception:
        pass
    await callback.answer("Остаёмся 🐱")


@router.callback_query(F.data == "ai:exit_yes", AIChatStates.chatting)
async def cb_ai_exit_yes(callback: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = callback.message.chat.id
    ai_msg_id = callback.message.message_id
    user_id = callback.from_user.id

    await state.clear()
    await callback.answer("🐱 Зефир отдыхает")

    try:
        await bot.delete_message(chat_id, ai_msg_id)
    except Exception:
        pass

    name = callback.from_user.first_name or "друг"
    new_menu = await bot.send_message(
        chat_id,
        f"👋 <b>Зефир отдыхает</b> 😸\nВозвращайся, {name}!",
        reply_markup=main_menu(),
    )
    await set_last_menu_msg_id(user_id, new_menu.message_id)


# ── Shared AI turn ──────────────────────────────────────────────

async def _run_ai_turn(
    user_id: int,
    chat_id: int,
    prompt_text: str,
    history_entry: str,
    preview: str,
    state: FSMContext,
    bot: Bot,
) -> None:
    data = await state.get_data()
    ai_msg_id = data.get("ai_msg_id")

    allowed, _ = await check_ai_limit(user_id)
    if not allowed:
        new_id = await _edit(
            bot, chat_id, ai_msg_id,
            "😿 <b>Лимит исчерпан</b>\n\n"
            "Обновится через 12 часов. Подожди немного!",
        )
        await state.update_data(ai_msg_id=new_id)
        return

    await save_ai_message(user_id, "user", history_entry)
    history_rows = await get_ai_history(user_id)
    if (history_rows and history_rows[-1]["role"] == "user"
            and history_rows[-1]["content"] == history_entry):
        history_rows = history_rows[:-1]
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]

    thinking_id = await _edit(bot, chat_id, ai_msg_id, _thinking_frame(preview))
    ai_msg_id = thinking_id
    await state.update_data(ai_msg_id=ai_msg_id)

    async def _show_error():
        _, rem = await check_ai_limit(user_id)
        new_id = await _edit(bot, chat_id, ai_msg_id, _error_frame(preview, rem))
        await state.update_data(ai_msg_id=new_id)

    final_text = ""
    try:
        last_edit_time = 0.0
        async for accumulated_text in chat_stream(history, prompt_text):
            final_text = accumulated_text
            now = time.time()
            if now - last_edit_time >= EDIT_INTERVAL:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id, message_id=ai_msg_id,
                        text=f"🐱 {final_text}",
                        reply_markup=ai_exit(),
                    )
                    last_edit_time = now
                except Exception:
                    pass
    except AIError:
        try:
            final_text = await chat_simple(history, prompt_text)
        except AIError:
            await _show_error()
            return

    if not final_text:
        await _show_error()
        return

    await increment_ai_usage(user_id)
    await save_ai_message(user_id, "assistant", final_text)

    _, new_remaining = await check_ai_limit(user_id)
    try:
        await bot.edit_message_text(
            chat_id=chat_id, message_id=ai_msg_id,
            text=_answer_frame(final_text, new_remaining),
            reply_markup=ai_exit(),
        )
    except Exception as e:
        logger.warning("Не смог применить финальный edit: %s", e)


# ── Text ────────────────────────────────────────────────────────

@router.message(AIChatStates.chatting, F.text)
async def process_ai_text(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_text = (message.text or "").strip()

    try:
        await message.delete()
    except Exception:
        pass

    if not user_text:
        return

    logger.info("💬 Юзер %d пишет Зефиру: %s", user_id, user_text[:80])

    await _run_ai_turn(
        user_id=user_id, chat_id=chat_id,
        prompt_text=user_text,
        history_entry=user_text,
        preview=user_text,
        state=state, bot=bot,
    )


# ── Photo ───────────────────────────────────────────────────────

@router.message(AIChatStates.chatting, F.photo)
async def process_ai_photo(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    caption = (message.caption or "").strip()

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    ai_msg_id = data.get("ai_msg_id")

    photo = message.photo[-1]
    size_mb = (photo.file_size or 0) / 1024 / 1024
    logger.info("📷 Юзер %d прислал фото %.2f МБ (caption: %s)",
                user_id, size_mb, caption[:60])

    if photo.file_size and photo.file_size > MAX_TG_FILE_MB * 1024 * 1024:
        await _edit(bot, chat_id, ai_msg_id,
            f"📷 <b>Фото слишком большое</b>\n\n"
            f"Максимум {MAX_TG_FILE_MB} МБ — лимит Telegram для ботов.\n"
            "Сожми и пришли ещё раз 🐾")
        return

    await _edit(bot, chat_id, ai_msg_id, _thinking_frame("📷 читаю текст с картинки..."))

    try:
        bio = await bot.download(photo.file_id)
        image_bytes = bio.read() if bio else b""
    except Exception as e:
        logger.error("❌ Не смог скачать фото: %s", e)
        await _edit(bot, chat_id, ai_msg_id, "😿 Не смог скачать фото. Попробуй ещё раз.")
        return

    try:
        ocr_text = await ocr_image(image_bytes, "image/jpeg")
    except AIError:
        await _edit(bot, chat_id, ai_msg_id,
            "😿 <b>OCR не сработал</b>\n\n"
            "Не смог прочитать текст. Попробуй другое фото "
            "или опиши словами.\n\n<i>запрос не списался с лимита</i>")
        return

    ocr_text = ocr_text[:MAX_OCR_CHARS]

    if not ocr_text:
        prompt_text = (
            "СИСТЕМНАЯ ИНФОРМАЦИЯ: Пользователь прислал фото, но система OCR "
            "не распознала на нём текст. Ты НЕ можешь видеть изображения — "
            "только читать текст с них. Честно объясни юзеру, что видеть "
            "картинки не умеешь, и предложи: либо описать содержимое словами, "
            "либо прислать скриншот с текстом/кодом. Не извиняйся многословно — "
            "одно-два предложения.\n\n"
            f"Комментарий пользователя к фото: {caption or '(без комментария)'}"
        )
    else:
        prompt_text = (
            f"Пользователь прислал фото. Распознанный текст с картинки:\n"
            f"---\n{ocr_text}\n---\n\n"
            f"Комментарий пользователя: {caption or '(без комментария)'}"
        )

    history_entry = f"[📷 Фото] {caption or '(без комментария)'}"
    preview = f"📷 {caption[:100]}" if caption else "📷 Фото"

    await _run_ai_turn(
        user_id=user_id, chat_id=chat_id,
        prompt_text=prompt_text,
        history_entry=history_entry,
        preview=preview,
        state=state, bot=bot,
    )


# ── Document ────────────────────────────────────────────────────

def _is_text_like(doc) -> bool:
    mime = (doc.mime_type or "").lower()
    if any(mime.startswith(p) for p in TEXT_LIKE_MIME_PREFIX):
        return True
    if mime in TEXT_LIKE_MIME:
        return True
    name = (doc.file_name or "").lower()
    for ext in TEXT_LIKE_EXT:
        if name.endswith(ext):
            return True
    return False


@router.message(AIChatStates.chatting, F.document)
async def process_ai_document(message: Message, state: FSMContext, bot: Bot):
    user_id = message.from_user.id
    chat_id = message.chat.id
    caption = (message.caption or "").strip()
    doc = message.document

    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    ai_msg_id = data.get("ai_msg_id")

    size_mb = (doc.file_size or 0) / 1024 / 1024
    logger.info("📄 Юзер %d прислал файл %s (%.2f МБ, mime=%s)",
                user_id, doc.file_name, size_mb, doc.mime_type)

    if doc.file_size and doc.file_size > MAX_TG_FILE_MB * 1024 * 1024:
        await _edit(bot, chat_id, ai_msg_id,
            f"📄 <b>Файл слишком большой</b>\n\n"
            f"Максимум {MAX_TG_FILE_MB} МБ — жёсткий лимит Telegram.\n"
            "Обрежь или заархивируй 🐾")
        return

    if not _is_text_like(doc):
        await _edit(bot, chat_id, ai_msg_id,
            f"📄 <b>Не текстовый файл</b>\n\n"
            f"Читаю только текст: .txt .md .py .csv .json и т.д.\n"
            f"Твой файл: <b>{doc.file_name}</b> ({doc.mime_type or 'тип неизвестен'})\n\n"
            "<i>фото — отправь как картинку, не как файл</i>")
        return

    await _edit(bot, chat_id, ai_msg_id,
        _thinking_frame(f"📄 читаю {doc.file_name}..."))

    try:
        bio = await bot.download(doc.file_id)
        raw = bio.read() if bio else b""
    except Exception as e:
        logger.error("❌ Не смог скачать файл %s: %s", doc.file_name, e)
        await _edit(bot, chat_id, ai_msg_id, "😿 Не смог скачать файл. Попробуй ещё раз.")
        return

    try:
        content = raw.decode("utf-8", errors="replace")
    except Exception:
        content = raw.decode("latin-1", errors="replace")

    content_full_len = len(content)
    content = content[:MAX_FILE_CONTENT_CHARS]
    truncated_note = (
        f"\n[файл обрезан — показано {MAX_FILE_CONTENT_CHARS} из {content_full_len} символов]"
        if content_full_len > MAX_FILE_CONTENT_CHARS else ""
    )

    prompt_text = (
        f"Пользователь прислал файл '{doc.file_name}' ({doc.mime_type or 'тип неизвестен'}). "
        f"Содержимое:\n---\n{content}\n---{truncated_note}\n\n"
        f"Вопрос/комментарий пользователя: {caption or '(без комментария — разбери и опиши/помоги)'}"
    )

    history_entry = f"[📄 {doc.file_name}] {caption or '(без комментария)'}"
    preview = f"📄 {doc.file_name}" + (f" · {caption[:80]}" if caption else "")

    await _run_ai_turn(
        user_id=user_id, chat_id=chat_id,
        prompt_text=prompt_text,
        history_entry=history_entry,
        preview=preview,
        state=state, bot=bot,
    )


# ── Unsupported types ───────────────────────────────────────────

@router.message(
    AIChatStates.chatting,
    F.voice | F.video | F.video_note | F.audio | F.sticker | F.animation,
)
async def process_ai_unsupported(message: Message, state: FSMContext, bot: Bot):
    chat_id = message.chat.id
    try:
        await message.delete()
    except Exception:
        pass

    data = await state.get_data()
    ai_msg_id = data.get("ai_msg_id")

    await _edit(bot, chat_id, ai_msg_id,
        "🐱 <b>Не умею</b>\n\n"
        "Понимаю: текст · фото · текстовые файлы.\n"
        "Голос, видео, стикеры — пока мимо 🐾")


# ── Fallback ────────────────────────────────────────────────────

@router.message(AIChatStates.chatting)
async def process_ai_fallback(message: Message, state: FSMContext, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass

    chat_id = message.chat.id
    data = await state.get_data()
    ai_msg_id = data.get("ai_msg_id")

    await _edit(bot, chat_id, ai_msg_id,
        "🐱 <b>Хм</b>\n\nНе понял что это. Пришли текст, фото или файл 🐾")
