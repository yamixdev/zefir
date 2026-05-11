from __future__ import annotations

import html

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import config
from bot.keyboards.inline import admin_menu, main_menu
from bot.models import get_last_menu_msg_id, set_last_menu_msg_id
from bot.services.news_service import (
    clear_notice_message,
    create_news_post,
    get_latest_update,
    get_news,
    get_news_settings,
    hide_news,
    list_news,
    mark_news_seen,
    publish_news,
    set_news_mode,
)
from bot.services.time_service import format_msk
from bot.utils import render_clean_message, smart_edit

router = Router()


class NewsAdminStates(StatesGroup):
    waiting_kind = State()
    waiting_title = State()
    waiting_body = State()


def _kind_label(kind: str) -> str:
    return {"update": "Апдейт", "event": "Ивент", "news": "Новость"}.get(kind, "Новость")


def _mode_label(mode: str) -> str:
    return {"all": "все новости", "updates": "только апдейты", "off": "выключены"}.get(mode, "все новости")


def news_notice_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📰 Открыть новости", callback_data=f"news:view:{post_id}")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="news:settings")],
    ])


def _news_home_kb(posts: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for post in posts[:7]:
        kb.row(InlineKeyboardButton(
            text=f"{_kind_label(post['kind'])}: {post['title'][:38]}",
            callback_data=f"news:view:{post['id']}",
        ))
    kb.row(InlineKeyboardButton(text="⚙️ Настройки уведомлений", callback_data="news:settings"))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


def _news_settings_kb(mode: str) -> InlineKeyboardMarkup:
    def mark(value: str) -> str:
        return "✅ " if mode == value else ""

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{mark('all')}Все новости", callback_data="news:mode:all")],
        [InlineKeyboardButton(text=f"{mark('updates')}Только апдейты", callback_data="news:mode:updates")],
        [InlineKeyboardButton(text=f"{mark('off')}Отключить", callback_data="news:mode:off")],
        [InlineKeyboardButton(text="⬅️ Новости", callback_data="news:home")],
    ])


def _news_detail_kb(post_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Все новости", callback_data="news:home")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
    ])


def _news_home_text(posts: list[dict], mode: str) -> str:
    lines = [
        "📰 <b>Новости Зефирки</b>",
        f"Уведомления: <b>{_mode_label(mode)}</b>\n",
    ]
    if not posts:
        lines.append("Пока новостей нет.")
        return "\n".join(lines)
    lines.append("Последнее:")
    for post in posts[:5]:
        published = post.get("published_at")
        date = format_msk(published, "%d.%m") if published else "без даты"
        lines.append(f"• <b>{html.escape(post['title'])}</b> · {_kind_label(post['kind'])} · {date}")
    return "\n".join(lines)


def _news_detail_text(post: dict) -> str:
    published = post.get("published_at")
    date = f"{format_msk(published)} МСК" if published else "черновик"
    version = f"\nВерсия: <code>{html.escape(post['release_version'])}</code>" if post.get("release_version") else ""
    return (
        f"📰 <b>{html.escape(post['title'])}</b>\n"
        f"{_kind_label(post['kind'])} · {date}{version}\n\n"
        f"{html.escape(post['body'])}"
    )


async def _delete_news_notice(bot: Bot, user_id: int) -> None:
    settings = await get_news_settings(user_id)
    if settings.get("notice_msg_id"):
        try:
            await bot.delete_message(user_id, settings["notice_msg_id"])
        except Exception:
            pass
        await clear_notice_message(user_id, settings.get("notice_post_id"))


@router.message(Command("news"))
async def cmd_news(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    await _delete_news_notice(bot, message.from_user.id)
    posts = await list_news(limit=10)
    settings = await get_news_settings(message.from_user.id)
    if posts:
        await mark_news_seen(message.from_user.id, posts[0]["id"])
    await render_clean_message(
        bot,
        message.chat.id,
        message.from_user.id,
        _news_home_text(posts, settings["notify_mode"]),
        reply_markup=_news_home_kb(posts),
    )


@router.message(Command("updates"))
async def cmd_updates(message: Message, bot: Bot):
    try:
        await message.delete()
    except Exception:
        pass
    await _delete_news_notice(bot, message.from_user.id)
    post = await get_latest_update()
    if not post:
        await render_clean_message(
            bot,
            message.chat.id,
            message.from_user.id,
            "📰 <b>Апдейты</b>\n\nПока опубликованных апдейтов нет.",
            reply_markup=main_menu(),
        )
        return
    await mark_news_seen(message.from_user.id, post["id"])
    await render_clean_message(
        bot,
        message.chat.id,
        message.from_user.id,
        _news_detail_text(post),
        reply_markup=_news_detail_kb(post["id"]),
    )


@router.callback_query(F.data == "news:home")
async def cb_news_home(callback: CallbackQuery):
    await _delete_news_notice(callback.bot, callback.from_user.id)
    posts = await list_news(limit=10)
    settings = await get_news_settings(callback.from_user.id)
    if posts:
        await mark_news_seen(callback.from_user.id, posts[0]["id"])
    msg = await smart_edit(callback, _news_home_text(posts, settings["notify_mode"]), reply_markup=_news_home_kb(posts))
    if msg:
        await set_last_menu_msg_id(callback.from_user.id, msg.message_id)
    await callback.answer()


@router.callback_query(F.data.startswith("news:view:"))
async def cb_news_view(callback: CallbackQuery):
    await _delete_news_notice(callback.bot, callback.from_user.id)
    post_id = int(callback.data.split(":")[2])
    post = await get_news(post_id)
    if not post or post["status"] != "published":
        await callback.answer("Новость уже недоступна.", show_alert=True)
        return
    await mark_news_seen(callback.from_user.id, post_id)
    msg = await smart_edit(callback, _news_detail_text(post), reply_markup=_news_detail_kb(post_id))
    if msg:
        await set_last_menu_msg_id(callback.from_user.id, msg.message_id)
    await callback.answer()


@router.callback_query(F.data == "news:settings")
async def cb_news_settings(callback: CallbackQuery):
    settings = await get_news_settings(callback.from_user.id)
    text = (
        "⚙️ <b>Настройки новостей</b>\n\n"
        "Можно оставить все новости, получать только апдейты бота или отключить уведомления. "
        "Раздел новостей в главном меню останется доступен всегда."
    )
    await smart_edit(callback, text, reply_markup=_news_settings_kb(settings["notify_mode"]))
    await callback.answer()


@router.callback_query(F.data.startswith("news:mode:"))
async def cb_news_mode(callback: CallbackQuery):
    mode = callback.data.split(":")[2]
    settings = await set_news_mode(callback.from_user.id, mode)
    text = (
        "⚙️ <b>Настройки новостей</b>\n\n"
        "Можно оставить все новости, получать только апдейты бота или отключить уведомления. "
        "Раздел новостей в главном меню останется доступен всегда."
    )
    await smart_edit(callback, text, reply_markup=_news_settings_kb(settings["notify_mode"]))
    await callback.answer(f"Уведомления: {_mode_label(settings['notify_mode'])}", show_alert=True)


def _admin_news_menu(posts: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="➕ Создать новость", callback_data="adm:news:create"))
    for post in posts[:8]:
        status = "🟢" if post["status"] == "published" else ("⚫" if post["status"] == "hidden" else "📝")
        kb.row(InlineKeyboardButton(
            text=f"{status} #{post['id']} {post['title'][:34]}",
            callback_data=f"adm:news:view:{post['id']}",
        ))
    kb.row(InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="adm:menu"))
    return kb.as_markup()


def _admin_news_detail_kb(post: dict) -> InlineKeyboardMarkup:
    rows = []
    if post["status"] != "published":
        rows.append([InlineKeyboardButton(text="🚀 Опубликовать", callback_data=f"adm:news:publish:{post['id']}")])
    if post["status"] != "hidden":
        rows.append([InlineKeyboardButton(text="🙈 Скрыть", callback_data=f"adm:news:hide:{post['id']}")])
    rows.append([InlineKeyboardButton(text="⬅️ Новости", callback_data="adm:news")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "adm:news")
async def cb_admin_news(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.clear()
    posts = await list_news(limit=20, include_drafts=True)
    text = "📰 <b>Новости</b>\n\nСоздавай апдейты, ивенты и обычные новости. Публикация не рассылает всем сразу."
    await smart_edit(callback, text, reply_markup=_admin_news_menu(posts))
    await callback.answer()


@router.callback_query(F.data == "adm:news:create")
async def cb_admin_news_create(callback: CallbackQuery, state: FSMContext):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(NewsAdminStates.waiting_kind)
    await state.update_data(prompt_msg_id=callback.message.message_id)
    await callback.message.edit_text(
        "📰 <b>Новая новость</b>\n\nНапиши тип: <code>update</code>, <code>event</code> или <code>news</code>.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="adm:news")]]),
    )
    await callback.answer()


@router.message(NewsAdminStates.waiting_kind)
async def msg_admin_news_kind(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    kind = (message.text or "").strip().lower()
    if kind not in {"update", "event", "news"}:
        kind = "news"
    data = await state.get_data()
    await state.update_data(news_kind=kind)
    await state.set_state(NewsAdminStates.waiting_title)
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["prompt_msg_id"],
        text=f"📰 <b>{_kind_label(kind)}</b>\n\nТеперь напиши короткий заголовок.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="adm:news")]]),
    )


@router.message(NewsAdminStates.waiting_title)
async def msg_admin_news_title(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    title = " ".join((message.text or "").split())[:160]
    data = await state.get_data()
    await state.update_data(news_title=title or "Обновление Зефирки")
    await state.set_state(NewsAdminStates.waiting_body)
    await bot.edit_message_text(
        chat_id=message.chat.id,
        message_id=data["prompt_msg_id"],
        text="📰 <b>Текст новости</b>\n\nНапиши, что изменилось. Можно несколькими строками.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="adm:news")]]),
    )


@router.message(NewsAdminStates.waiting_body)
async def msg_admin_news_body(message: Message, state: FSMContext, bot: Bot):
    if not config.is_admin(message.from_user.id):
        await state.clear()
        return
    try:
        await message.delete()
    except Exception:
        pass
    data = await state.get_data()
    await state.clear()
    body = (message.text or "").strip()[:3000] or "Подробности скоро появятся."
    kind = data.get("news_kind") or "news"
    title = data.get("news_title") or "Новость"
    release_version = config.bot_release_version if kind == "update" else None
    post = await create_news_post(
        kind=kind,
        title=title,
        body=body,
        created_by=message.from_user.id,
        release_version=release_version,
    )
    text = "📝 <b>Черновик создан</b>\n\n" + _news_detail_text(post)
    prompt_msg_id = data.get("prompt_msg_id")
    if prompt_msg_id:
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=prompt_msg_id,
            text=text,
            reply_markup=_admin_news_detail_kb(post),
        )


@router.callback_query(F.data.startswith("adm:news:view:"))
async def cb_admin_news_view(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    post_id = int(callback.data.split(":")[3])
    post = await get_news(post_id)
    if not post:
        await callback.answer("Новость не найдена", show_alert=True)
        return
    await smart_edit(callback, _news_detail_text(post), reply_markup=_admin_news_detail_kb(post))
    await callback.answer()


@router.callback_query(F.data.startswith("adm:news:publish:"))
async def cb_admin_news_publish(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    post_id = int(callback.data.split(":")[3])
    post = await publish_news(post_id)
    if not post:
        await callback.answer("Новость не найдена", show_alert=True)
        return
    await smart_edit(callback, _news_detail_text(post), reply_markup=_admin_news_detail_kb(post))
    await callback.answer("Опубликовано", show_alert=True)


@router.callback_query(F.data.startswith("adm:news:hide:"))
async def cb_admin_news_hide(callback: CallbackQuery):
    if not config.is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    post_id = int(callback.data.split(":")[3])
    post = await hide_news(post_id)
    if not post:
        await callback.answer("Новость не найдена", show_alert=True)
        return
    await smart_edit(callback, _news_detail_text(post), reply_markup=_admin_news_detail_kb(post))
    await callback.answer("Скрыто", show_alert=True)
