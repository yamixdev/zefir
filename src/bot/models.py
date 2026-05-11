"""Все запросы к БД идут через пул из db.py.

Каждая функция обёрнута в `@with_db_retry` — на OperationalError/InterfaceError
(в т.ч. AdminShutdown после Neon autosuspend) пул пересоздаётся и запрос
повторяется один раз. Это покрывает race между `pool.check_connection`
и реальным `conn.execute`.
"""
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from bot.config import config
from bot.db import get_pool, with_db_retry


# ── Users ────────────────────────────────────────────────────────

WELCOME_ZEFIRKI = 100


@with_db_retry
async def upsert_user(user_id: int, username: str | None, first_name: str | None, last_name: str | None):
    """Создаёт/обновляет юзера. Новому начисляет welcome-бонус зефирок
    (RETURNING xmax=0 = этот ряд только что вставлен).
    """
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO users (user_id, username, first_name, last_name, zefirki)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE
                SET username   = COALESCE(%s, users.username),
                    first_name = COALESCE(%s, users.first_name),
                    last_name  = COALESCE(%s, users.last_name)
            RETURNING (xmax = 0) AS inserted
            """,
            (user_id, username, first_name, last_name, WELCOME_ZEFIRKI, username, first_name, last_name),
        )
        row = await cur.fetchone()
        if row and row["inserted"]:
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (user_id, WELCOME_ZEFIRKI, "welcome"),
            )


@with_db_retry
async def get_user(user_id: int):
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        return await cur.fetchone()


@with_db_retry
async def is_banned(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and user["is_banned"])


@with_db_retry
async def set_ban(
    user_id: int,
    banned: bool,
    reason_code: str | None = None,
    reason_text: str | None = None,
    banned_by: int | None = None,
):
    pool = await get_pool()
    async with pool.connection() as conn:
        if banned:
            await conn.execute(
                """
                UPDATE users
                   SET is_banned = TRUE,
                       ban_reason_code = %s,
                       ban_reason_text = %s,
                       banned_by = %s,
                       banned_at = NOW()
                 WHERE user_id = %s
                """,
                (reason_code, reason_text, banned_by, user_id),
            )
        else:
            await conn.execute(
                """
                UPDATE users
                   SET is_banned = FALSE,
                       ban_reason_code = NULL,
                       ban_reason_text = NULL,
                       banned_by = NULL,
                       banned_at = NULL
                 WHERE user_id = %s
                """,
                (user_id,),
            )


@with_db_retry
async def record_user_activity(
    user_id: int,
    event_type: str,
    action: str,
    chat_id: int | None = None,
    context: dict | None = None,
) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE users
                   SET last_active_at = NOW(),
                       last_action = %s,
                       last_chat_id = %s
                 WHERE user_id = %s
                """,
                (action[:255], chat_id, user_id),
            )
            await conn.execute(
                """
                INSERT INTO user_activity_events (user_id, event_type, action, chat_id, context)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, event_type[:50], action[:255], chat_id, Jsonb(context or {})),
            )


@with_db_retry
async def get_online_users(minutes: int = 15, limit: int = 30) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT user_id, username, first_name, last_name, is_banned,
                   last_active_at, last_action, last_chat_id, bot_blocked_at
            FROM users
            WHERE last_active_at >= NOW() - make_interval(mins => %s)
            ORDER BY last_active_at DESC
            LIMIT %s
            """,
            (minutes, limit),
        )
        return await cur.fetchall()


@with_db_retry
async def get_user_activity(user_id: int, limit: int = 20) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT *
            FROM user_activity_events
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        return await cur.fetchall()


@with_db_retry
async def mark_bot_blocked(user_id: int, blocked: bool) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE users SET bot_blocked_at = %s WHERE user_id = %s",
            (datetime.now(timezone.utc) if blocked else None, user_id),
        )


@with_db_retry
async def create_incident(
    title: str,
    message: str | None = None,
    traceback_text: str | None = None,
    user_id: int | None = None,
    chat_id: int | None = None,
    action: str | None = None,
    event_type: str = "auto",
) -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO bot_incidents
                (user_id, chat_id, event_type, action, title, message, traceback_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (user_id, chat_id, event_type, action, title[:255], message, traceback_text),
        )
        row = await cur.fetchone()
        return row["id"]


@with_db_retry
async def list_incidents(status: str | None = "open", limit: int = 20, offset: int = 0) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        params: list = []
        where = ""
        if status:
            where = "WHERE bi.status = %s"
            params.append(status)
        params.extend([limit, offset])
        cur = await conn.execute(
            f"""
            SELECT bi.*, u.username, u.first_name
            FROM bot_incidents bi
            LEFT JOIN users u ON u.user_id = bi.user_id
            {where}
            ORDER BY bi.created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return await cur.fetchall()


@with_db_retry
async def get_incident(incident_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT bi.*, u.username, u.first_name
            FROM bot_incidents bi
            LEFT JOIN users u ON u.user_id = bi.user_id
            WHERE bi.id = %s
            """,
            (incident_id,),
        )
        return await cur.fetchone()


@with_db_retry
async def close_incident(
    incident_id: int,
    status: str,
    admin_note: str | None,
    closed_by: int,
) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            UPDATE bot_incidents
               SET status = %s,
                   admin_note = %s,
                   closed_by = %s,
                   closed_at = NOW(),
                   updated_at = NOW()
             WHERE id = %s
             RETURNING *
            """,
            (status, admin_note, closed_by, incident_id),
        )
        return await cur.fetchone()


@with_db_retry
async def get_all_users():
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM users ORDER BY created_at DESC")
        return await cur.fetchall()


@with_db_retry
async def get_users_count() -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM users")
        row = await cur.fetchone()
        return row["cnt"]


@with_db_retry
async def get_new_users_count(hours: int = 24) -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE created_at >= NOW() - make_interval(hours => %s)",
            (hours,),
        )
        row = await cur.fetchone()
        return row["cnt"]


@with_db_retry
async def get_banned_count() -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_banned = TRUE")
        row = await cur.fetchone()
        return row["cnt"]


@with_db_retry
async def get_last_menu_msg_id(user_id: int) -> int | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT last_menu_msg_id FROM users WHERE user_id = %s", (user_id,)
        )
        row = await cur.fetchone()
        return row["last_menu_msg_id"] if row else None


@with_db_retry
async def set_last_menu_msg_id(user_id: int, msg_id: int | None):
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE users SET last_menu_msg_id = %s WHERE user_id = %s",
            (msg_id, user_id),
        )


@with_db_retry
async def get_top_ai_users(limit: int = 5):
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT user_id, username, first_name, ai_messages_used
            FROM users
            WHERE ai_messages_used > 0
            ORDER BY ai_messages_used DESC
            LIMIT %s
            """,
            (limit,),
        )
        return await cur.fetchall()


# ── Zefirki (внутренняя валюта) ─────────────────────────────────

@with_db_retry
async def get_zefirki_balance(user_id: int) -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT zefirki FROM users WHERE user_id = %s", (user_id,))
        row = await cur.fetchone()
        return row["zefirki"] if row else 0


@with_db_retry
async def grant_zefirki(user_id: int, amount: int, reason: str) -> int:
    """Начисляет зефирки, пишет транзакцию. Возвращает новый баланс.
    Amount > 0 обязательно — для списания используй spend_zefirki.
    """
    if amount <= 0:
        raise ValueError("grant_zefirki: amount must be positive")
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s RETURNING zefirki",
            (amount, user_id),
        )
        row = await cur.fetchone()
        if not row:
            return 0
        await conn.execute(
            "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
            (user_id, amount, reason),
        )
        return row["zefirki"]


@with_db_retry
async def spend_zefirki(user_id: int, amount: int, reason: str) -> tuple[bool, int]:
    """Списывает зефирки. Returns (ok, new_balance).
    ok=False если баланс меньше amount — списание не произойдёт.
    Атомарно: проверка и списание в одном UPDATE.
    """
    if amount <= 0:
        raise ValueError("spend_zefirki: amount must be positive")
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            UPDATE users
               SET zefirki = zefirki - %s
             WHERE user_id = %s AND zefirki >= %s
            RETURNING zefirki
            """,
            (amount, user_id, amount),
        )
        row = await cur.fetchone()
        if not row:
            balance = await get_zefirki_balance_conn(conn, user_id)
            return False, balance
        await conn.execute(
            "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
            (user_id, -amount, reason),
        )
        return True, row["zefirki"]


async def get_zefirki_balance_conn(conn, user_id: int) -> int:
    """Версия без декоратора — для переиспользования внутри других запросов."""
    cur = await conn.execute("SELECT zefirki FROM users WHERE user_id = %s", (user_id,))
    row = await cur.fetchone()
    return row["zefirki"] if row else 0


@with_db_retry
async def get_recent_transactions(user_id: int, limit: int = 10):
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT amount, reason, created_at
              FROM transactions
             WHERE user_id = %s
          ORDER BY created_at DESC
             LIMIT %s
            """,
            (user_id, limit),
        )
        return await cur.fetchall()


# ── AI Limits ────────────────────────────────────────────────────

@with_db_retry
async def check_ai_limit(user_id: int) -> tuple[bool, int]:
    """Returns (allowed, remaining). Resets counter if period expired. Includes ai_bonus."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)

    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT ai_messages_used, ai_bonus, ai_limit_reset_at FROM users WHERE user_id = %s",
            (user_id,),
        )
        user = await cur.fetchone()
        if not user:
            return False, 0

        bonus = user["ai_bonus"] or 0

        if user["ai_limit_reset_at"] is None or now >= user["ai_limit_reset_at"]:
            new_reset = now + timedelta(hours=config.ai_limit_hours)
            await conn.execute(
                "UPDATE users SET ai_messages_used = 0, ai_limit_reset_at = %s WHERE user_id = %s",
                (new_reset, user_id),
            )
            return True, config.ai_daily_limit + bonus

        used = user["ai_messages_used"]
        remaining = config.ai_daily_limit + bonus - used
        return remaining > 0, max(remaining, 0)


@with_db_retry
async def get_ai_limit_info(user_id: int) -> dict:
    """Returns {used, bonus, remaining, reset_at} without mutation."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT ai_messages_used, ai_bonus, ai_limit_reset_at FROM users WHERE user_id = %s",
            (user_id,),
        )
        user = await cur.fetchone()
    if not user:
        return {"used": 0, "bonus": 0, "remaining": config.ai_daily_limit, "reset_at": None}
    used = user["ai_messages_used"]
    bonus = user["ai_bonus"] or 0
    return {
        "used": used,
        "bonus": bonus,
        "remaining": max(config.ai_daily_limit + bonus - used, 0),
        "reset_at": user["ai_limit_reset_at"],
    }


@with_db_retry
async def increment_ai_usage(user_id: int):
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE users SET ai_messages_used = ai_messages_used + 1 WHERE user_id = %s", (user_id,)
        )


@with_db_retry
async def reset_ai_limits_all():
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    new_reset = now + timedelta(hours=config.ai_limit_hours)
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE users SET ai_messages_used = 0, ai_limit_reset_at = %s", (new_reset,)
        )


@with_db_retry
async def reset_ai_limit_user(user_id: int):
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    new_reset = now + timedelta(hours=config.ai_limit_hours)
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE users SET ai_messages_used = 0, ai_limit_reset_at = %s WHERE user_id = %s",
            (new_reset, user_id),
        )


@with_db_retry
async def has_accepted_consent(user_id: int, version: str) -> bool:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM user_consents WHERE user_id = %s AND doc_version = %s LIMIT 1",
            (user_id, version),
        )
        return (await cur.fetchone()) is not None


@with_db_retry
async def accept_consent(user_id: int, version: str, doc_hash: str):
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO user_consents (user_id, doc_version, doc_hash)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, doc_version) DO NOTHING
            """,
            (user_id, version, doc_hash),
        )


@with_db_retry
async def grant_ai_bonus(user_id: int, amount: int) -> int:
    """Adds `amount` to user's ai_bonus. Returns new bonus value."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE users SET ai_bonus = COALESCE(ai_bonus, 0) + %s WHERE user_id = %s RETURNING ai_bonus",
            (amount, user_id),
        )
        row = await cur.fetchone()
    return row["ai_bonus"] if row else amount


# ── Tickets ──────────────────────────────────────────────────────

@with_db_retry
async def create_ticket(user_id: int, message: str, ai_summary: str | None = None) -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO tickets (user_id, message, ai_summary)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (user_id, message, ai_summary),
        )
        row = await cur.fetchone()
    return row["id"]


@with_db_retry
async def get_ticket(ticket_id: int):
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,))
        return await cur.fetchone()


@with_db_retry
async def mark_ticket_seen(ticket_id: int):
    """Set seen_at if not yet set (admin opened the ticket)."""
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tickets SET seen_at = NOW() WHERE id = %s AND seen_at IS NULL",
            (ticket_id,),
        )


@with_db_retry
async def get_user_tickets(user_id: int, limit: int = 10):
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT * FROM tickets WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit),
        )
        return await cur.fetchall()


@with_db_retry
async def get_user_ticket_stats(user_id: int) -> dict:
    """Returns counts by derived status: sent, seen, replied, total."""
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE status != 'closed' AND seen_at IS NULL) AS sent,
                COUNT(*) FILTER (WHERE status != 'closed' AND seen_at IS NOT NULL) AS seen,
                COUNT(*) FILTER (WHERE status = 'closed' AND admin_reply IS NOT NULL) AS replied,
                COUNT(*) AS total
            FROM tickets
            WHERE user_id = %s
            """,
            (user_id,),
        )
        return await cur.fetchone()


@with_db_retry
async def get_open_tickets(limit: int = 20, offset: int = 0):
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT t.*, u.username, u.first_name
            FROM tickets t JOIN users u ON t.user_id = u.user_id
            WHERE t.status IN ('open', 'in_progress')
            ORDER BY t.created_at DESC
            LIMIT %s OFFSET %s
            """,
            (limit, offset),
        )
        return await cur.fetchall()


@with_db_retry
async def count_open_tickets() -> int:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM tickets WHERE status IN ('open', 'in_progress')")
        row = await cur.fetchone()
        return row["cnt"]


@with_db_retry
async def update_ticket_status(ticket_id: int, status: str):
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tickets SET status = %s, updated_at = NOW() WHERE id = %s",
            (status, ticket_id),
        )


@with_db_retry
async def set_ticket_reply(ticket_id: int, reply: str):
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE tickets SET admin_reply = %s, status = 'closed', updated_at = NOW() WHERE id = %s",
            (reply, ticket_id),
        )


# ── AI Conversations ────────────────────────────────────────────

@with_db_retry
async def save_ai_message(user_id: int, role: str, content: str):
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO ai_conversations (user_id, role, content) VALUES (%s, %s, %s)",
            (user_id, role, content),
        )


@with_db_retry
async def get_ai_history(user_id: int, limit: int | None = None):
    if limit is None:
        limit = config.ai_history_limit
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT role, content FROM ai_conversations
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (user_id, limit),
        )
        rows = await cur.fetchall()
    return list(reversed(rows))


@with_db_retry
async def clear_ai_history(user_id: int):
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM ai_conversations WHERE user_id = %s", (user_id,))


# ── Stats ────────────────────────────────────────────────────────

@with_db_retry
async def get_stats() -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM users")
        users = (await cur.fetchone())["cnt"]
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM tickets")
        tickets_total = (await cur.fetchone())["cnt"]
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM tickets WHERE status IN ('open', 'in_progress')")
        tickets_open = (await cur.fetchone())["cnt"]
        cur = await conn.execute("SELECT COUNT(*) AS cnt FROM ai_conversations")
        ai_msgs = (await cur.fetchone())["cnt"]
    return {
        "users": users,
        "tickets_total": tickets_total,
        "tickets_open": tickets_open,
        "ai_messages": ai_msgs,
    }
