from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ── Main menu ────────────────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📨 Написать админу", callback_data="ticket:new"))
    kb.row(
        InlineKeyboardButton(text="🐱 Зефир", callback_data="ai:start"),
        InlineKeyboardButton(text="⛅ Погода", callback_data="weather:ask"),
    )
    kb.row(InlineKeyboardButton(text="📊 Мои тикеты", callback_data="ticket:my"))
    return kb.as_markup()


# ── AI chat ──────────────────────────────────────────────────────

def ai_exit() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="ai:exit")]
    ])


# ── Tickets (user) ──────────────────────────────────────────────

def ticket_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")]
    ])


def user_tickets_list(tickets: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tickets:
        status_icon = {"open": "🟡", "in_progress": "🔵", "closed": "🟢"}.get(t["status"], "⚪")
        kb.row(InlineKeyboardButton(
            text=f'{status_icon} #{t["id"]} — {t["message"][:30]}...',
            callback_data=f"ticket:view:{t['id']}",
        ))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


def ticket_detail_user(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к тикетам", callback_data="ticket:my")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")],
    ])


# ── Weather ──────────────────────────────────────────────────────

def weather_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")]
    ])


# ── Admin panel ──────────────────────────────────────────────────

def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📋 Открытые тикеты", callback_data="adm:tickets"))
    kb.row(InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users"))
    kb.row(InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"))
    kb.row(InlineKeyboardButton(text="🔄 Сброс лимитов всем", callback_data="adm:reset_limits"))
    kb.row(InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast"))
    kb.row(InlineKeyboardButton(text="🏠 В обычный режим", callback_data="menu:main"))
    return kb.as_markup()


def admin_tickets_list(tickets: list, page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tickets:
        status_icon = {"open": "🟡", "in_progress": "🔵"}.get(t["status"], "⚪")
        name = t.get("first_name") or t.get("username") or str(t["user_id"])
        kb.row(InlineKeyboardButton(
            text=f'{status_icon} #{t["id"]} | {name}: {t["message"][:25]}',
            callback_data=f"adm:ticket:{t['id']}",
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:tickets:{page - 1}"))
    nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:tickets:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="adm:menu"))
    return kb.as_markup()


def admin_ticket_actions(ticket_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="💬 Ответить", callback_data=f"adm:reply:{ticket_id}"),
        InlineKeyboardButton(text="✅ Закрыть", callback_data=f"adm:close:{ticket_id}"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ К тикетам", callback_data="adm:tickets"))
    return kb.as_markup()


def admin_users_list(users: list, page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for u in users:
        name = u.get("first_name") or u.get("username") or str(u["user_id"])
        ban_mark = "🚫" if u["is_banned"] else ""
        kb.row(InlineKeyboardButton(
            text=f"{ban_mark} {name} (ID: {u['user_id']})",
            callback_data=f"adm:user:{u['user_id']}",
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:users:{page - 1}"))
    nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:users:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="adm:menu"))
    return kb.as_markup()


def admin_user_actions(user_id: int, is_banned: bool) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if is_banned:
        kb.row(InlineKeyboardButton(text="✅ Разбанить", callback_data=f"adm:unban:{user_id}"))
    else:
        kb.row(InlineKeyboardButton(text="🚫 Забанить", callback_data=f"adm:ban:{user_id}"))
    kb.row(InlineKeyboardButton(text="🔄 Сбросить лимит AI", callback_data=f"adm:resetlim:{user_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ К пользователям", callback_data="adm:users"))
    return kb.as_markup()


def confirm_action(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"adm:confirm:{action}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="adm:menu"),
        ]
    ])
