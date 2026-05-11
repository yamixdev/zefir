from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


# ── Main menu (2 двери) ─────────────────────────────────────────

def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📨 Связаться с владельцем", callback_data="menu:contact"))
    kb.row(InlineKeyboardButton(text="📰 Новости", callback_data="news:home"))
    kb.row(InlineKeyboardButton(text="🎮 Развлечения и утилиты", callback_data="menu:fun"))
    return kb.as_markup()


def banned_main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📨 Связаться с владельцем", callback_data="menu:contact"))
    return kb.as_markup()


def contact_submenu() -> InlineKeyboardMarkup:
    """Подменю «Связаться с владельцем»."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="✉️ Написать владельцу", callback_data="ticket:new"))
    kb.row(InlineKeyboardButton(text="🛠 Сообщить о баге", callback_data="incident:report"))
    kb.row(InlineKeyboardButton(text="📊 Мои тикеты", callback_data="ticket:my"))
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


def fun_submenu() -> InlineKeyboardMarkup:
    """Подменю «Развлечения и утилиты». Порядок от самого важного."""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎮 Игры", callback_data="games:home"))
    kb.row(
        InlineKeyboardButton(text="🐾 Питомцы", callback_data="pet:home"),
        InlineKeyboardButton(text="🛒 Магазин", callback_data="shop:home"),
    )
    kb.row(
        InlineKeyboardButton(text="🏪 Рынок", callback_data="econ:market"),
        InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv"),
    )
    kb.row(
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile:me"),
        InlineKeyboardButton(text="⚙️ Утилиты", callback_data="menu:utils"),
    )
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


def utilities_submenu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🐱 Зефир (AI)", callback_data="ai:start"),
        InlineKeyboardButton(text="⛅ Погода", callback_data="weather:ask"),
    )
    kb.row(
        InlineKeyboardButton(text="💱 Конвертер", callback_data="conv:start"),
        InlineKeyboardButton(text="🔳 QR-код", callback_data="qr:start"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ В развлечения", callback_data="menu:fun"))
    return kb.as_markup()


def fun_consent_menu(target: str = "fun") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Пользовательское соглашение", callback_data=f"funconsent:tos:{target}")],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", callback_data=f"funconsent:privacy:{target}")],
        [
            InlineKeyboardButton(text="✅ Принимаю", callback_data=f"funconsent:accept:{target}"),
            InlineKeyboardButton(text="❌ Отказаться", callback_data="funconsent:decline"),
        ],
    ])


def fun_consent_back(target: str = "fun") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К выбору", callback_data=f"funconsent:show:{target}")],
    ])


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
    kb.row(
        InlineKeyboardButton(text="🎒 Инвентарь", callback_data="econ:inv"),
        InlineKeyboardButton(text="🐾 Питомец", callback_data="pet:home"),
    )
    kb.row(
        InlineKeyboardButton(text="📊 Подробнее", callback_data="profile:me:details"),
        InlineKeyboardButton(text="⬅️ Развлечения", callback_data="menu:fun"),
    )
    return kb.as_markup()


def profile_details_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="🏪 Рынок", callback_data="econ:market"),
        InlineKeyboardButton(text="🛒 Магазин", callback_data="shop:home"),
    )
    kb.row(
        InlineKeyboardButton(text="🐱 AI", callback_data="ai:start"),
        InlineKeyboardButton(text="📬 Тикеты", callback_data="ticket:my"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ Профиль", callback_data="profile:me"))
    return kb.as_markup()


# ── Profile (admin / owner) ─────────────────────────────────────

def admin_profile_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="👑 Админ-панель", callback_data="adm:menu"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="profile:admin:stats"),
    )
    kb.row(
        InlineKeyboardButton(text="🍬 Экономика", callback_data="adm:econ"),
        InlineKeyboardButton(text="📋 Тикеты", callback_data="adm:tickets"),
    )
    kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return kb.as_markup()


def admin_profile_stats_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="👥 Юзеры", callback_data="adm:users"),
        InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast"),
    )
    kb.row(
        InlineKeyboardButton(text="🔄 Сброс лимитов", callback_data="adm:reset_limits"),
        InlineKeyboardButton(text="🍬 Экономика", callback_data="adm:econ"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ Профиль", callback_data="profile:admin"))
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
    kb.row(
        InlineKeyboardButton(text="🟢 Онлайн", callback_data="adm:online"),
        InlineKeyboardButton(text="🚨 Инциденты", callback_data="adm:incidents"),
    )
    kb.row(InlineKeyboardButton(text="📰 Новости", callback_data="adm:news"))
    kb.row(InlineKeyboardButton(text="🍬 Экономика", callback_data="adm:econ"))
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
    kb.row(
        InlineKeyboardButton(text="🧾 Действия", callback_data=f"adm:activity:{user_id}"),
        InlineKeyboardButton(text="📡 Проверить ЧС", callback_data=f"adm:probe:{user_id}"),
    )
    if is_banned:
        kb.row(InlineKeyboardButton(text="✅ Разбанить", callback_data=f"adm:unban:{user_id}"))
    else:
        kb.row(InlineKeyboardButton(text="🚫 Забанить", callback_data=f"adm:ban_menu:{user_id}"))
    kb.row(InlineKeyboardButton(text="⬅️ К пользователям", callback_data="adm:users"))
    return kb.as_markup()


def admin_ban_reasons(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 · Спам / флуд", callback_data=f"adm:ban_reason:{user_id}:spam")],
        [InlineKeyboardButton(text="2 · Абуз экономики", callback_data=f"adm:ban_reason:{user_id}:abuse")],
        [InlineKeyboardButton(text="3 · Оскорбления / токсичность", callback_data=f"adm:ban_reason:{user_id}:toxicity")],
        [InlineKeyboardButton(text="✍️ Своя причина", callback_data=f"adm:ban_custom:{user_id}")],
        [InlineKeyboardButton(text="⬅️ К пользователю", callback_data=f"adm:user:{user_id}")],
    ])


def admin_incidents_list(incidents: list, page: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for incident in incidents:
        kb.row(InlineKeyboardButton(
            text=f"#{incident['id']} · {incident['title'][:34]}",
            callback_data=f"adm:incident:{incident['id']}",
        ))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"adm:incidents:{page - 1}"))
    if len(incidents) >= 10:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"adm:incidents:{page + 1}"))
    if nav:
        kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ Админ-панель", callback_data="adm:menu"))
    return kb.as_markup()


def admin_incident_actions(incident_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="✅ Исправлено", callback_data=f"adm:incident_close:{incident_id}:fixed"),
        InlineKeyboardButton(text="⚫ Не исправлено", callback_data=f"adm:incident_close:{incident_id}:wontfix"),
    )
    kb.row(InlineKeyboardButton(text="⬅️ Инциденты", callback_data="adm:incidents"))
    return kb.as_markup()


def incident_user_close() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Закрыть", callback_data="incident:user_close")]
    ])


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
