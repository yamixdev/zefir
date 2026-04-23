from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ── Main menu (2 двери) ─────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📨 Связаться с владельцем", callback_data="menu:contact"))
    kb.row(InlineKeyboardButton(text="🎮 Развлечения и утилиты", callback_data="menu:fun"))
    return kb.as_markup()


def contact_submenu() -> InlineKeyboardMarkup:
    """Подменю «Связаться с владельцем»."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✉️ Написать владельцу", callback_data="ticket:new"))
    kb.row(InlineKeyboardButton(text="📊 Мои тикеты", callback_data="ticket:my"))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


def fun_submenu() -> InlineKeyboardMarkup:
    """Подменю «Развлечения и утилиты». Сюда будут добавляться новые фичи."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🐱 Зефир (AI)", callback_data="ai:start"))
    kb.row(InlineKeyboardButton(text="⛅ Погода", callback_data="weather:ask"))
    kb.row(InlineKeyboardButton(text="👤 Мой профиль", callback_data="profile:me"))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


# ── AI chat ──────────────────────────────────────────────────────

def ai_exit() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚪 Выйти из чата", callback_data="ai:exit_ask")]
    ])


# ── Consent (перед AI) ──────────────────────────────────────────

def consent_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Соглашение", callback_data="ai:consent_tos")],
        [InlineKeyboardButton(text="🔒 Конфиденциальность", callback_data="ai:consent_privacy")],
        [
            InlineKeyboardButton(text="✅ Принимаю", callback_data="ai:consent_accept"),
            InlineKeyboardButton(text="❌ Отказаться", callback_data="ai:consent_decline"),
        ],
    ])


def consent_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="← Назад", callback_data="ai:consent_show")],
    ])


def ai_exit_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, выйти", callback_data="ai:exit_yes"),
            InlineKeyboardButton(text="🐱 Остаться", callback_data="ai:exit_no"),
        ]
    ])


# ── Tickets (user) ──────────────────────────────────────────────

def _ticket_icon(t: dict) -> str:
    status = t.get("status")
    if status == "closed":
        return "✅" if t.get("admin_reply") else "⚫"
    return "👁" if t.get("seen_at") else "📤"


def ticket_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")]
    ])


def user_tickets_list(tickets: list) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tickets:
        kb.row(InlineKeyboardButton(
            text=f'{_ticket_icon(t)} #{t["id"]} — {t["message"][:30]}...',
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


# ── Profile (user) ───────────────────────────────────────────────

def profile_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📊 Мои тикеты", callback_data="ticket:my"))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


# ── Profile (admin / owner) ─────────────────────────────────────

def admin_profile_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="adm:menu"))
    kb.row(
        InlineKeyboardButton(text="📋 Открытые тикеты", callback_data="adm:tickets"),
        InlineKeyboardButton(text="👥 Юзеры", callback_data="adm:users"),
    )
    kb.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast"),
        InlineKeyboardButton(text="🔄 Сброс лимитов", callback_data="adm:reset_limits"),
    )
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


# ── Admin panel ──────────────────────────────────────────────────

def admin_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="📋 Тикеты", callback_data="adm:tickets"),
        InlineKeyboardButton(text="👥 Юзеры", callback_data="adm:users"),
    )
    kb.row(
        InlineKeyboardButton(text="🎁 Начислить AI", callback_data="adm:grant_menu"),
        InlineKeyboardButton(text="🔄 Сброс всем", callback_data="adm:reset_limits"),
    )
    kb.row(
        InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast"),
        InlineKeyboardButton(text="👑 Мой профиль", callback_data="profile:admin"),
    )
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


def admin_tickets_list(tickets: list, page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for t in tickets:
        icon = "👁" if t.get("seen_at") else "📤"
        name = t.get("first_name") or t.get("username") or str(t["user_id"])
        kb.row(InlineKeyboardButton(
            text=f'{icon} #{t["id"]} | {name}: {t["message"][:25]}',
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
    kb.row(
        InlineKeyboardButton(text="🎁 Начислить AI", callback_data=f"adm:grant_pick:{user_id}"),
        InlineKeyboardButton(text="🔄 Сбросить AI", callback_data=f"adm:resetlim:{user_id}"),
    )
    if is_banned:
        kb.row(InlineKeyboardButton(text="✅ Разбанить", callback_data=f"adm:unban:{user_id}"))
    else:
        kb.row(InlineKeyboardButton(text="🚫 Забанить", callback_data=f"adm:ban:{user_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ К пользователям", callback_data="adm:users"))
    return kb.as_markup()


# ── Grant AI limit flow ─────────────────────────────────────────

def grant_user_list(users: list, page: int = 0, admin_id: int | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if page == 0 and admin_id:
        kb.row(InlineKeyboardButton(
            text="🎁 Начислить себе",
            callback_data=f"adm:grant_pick:{admin_id}",
        ))
    for u in users:
        name = u.get("first_name") or u.get("username") or str(u["user_id"])
        bonus = u.get("ai_bonus") or 0
        suffix = f" (+{bonus})" if bonus > 0 else ""
        kb.row(InlineKeyboardButton(
            text=f"👤 {name}{suffix}",
            callback_data=f"adm:grant_pick:{u['user_id']}",
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:grant_menu:{page - 1}"))
    nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:grant_menu:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="❌ Отмена", callback_data="adm:menu"))
    return kb.as_markup()


def grant_comment_choice() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✍️ Добавить комментарий", callback_data="adm:grant_with_comment"),
            InlineKeyboardButton(text="⏭ Без комментария", callback_data="adm:grant_no_comment"),
        ],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:menu")],
    ])


def grant_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:menu")],
    ])


def confirm_action(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"adm:confirm:{action}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="adm:menu"),
        ]
    ])
