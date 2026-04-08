from datetime import datetime, timedelta, timezone

from bot.config import config
from bot.db import get_pool


# ── Users ────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str | None, first_name: str | None, last_name: str | None):
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO users (user_id, username, first_name, last_name)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE
            SET username   = COALESCE($2, users.username),
                first_name = COALESCE($3, users.first_name),
                last_name  = COALESCE($4, users.last_name)
        """,
        user_id, username, first_name, last_name,
    )


async def get_user(user_id: int):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)


async def is_banned(user_id: int) -> bool:
    user = await get_user(user_id)
    return bool(user and user["is_banned"])


async def set_ban(user_id: int, banned: bool):
    pool = await get_pool()
    await pool.execute("UPDATE users SET is_banned = $2 WHERE user_id = $1", user_id, banned)


async def get_all_users():
    pool = await get_pool()
    return await pool.fetch("SELECT * FROM users ORDER BY created_at DESC")


async def get_users_count() -> int:
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM users")


# ── AI Limits ────────────────────────────────────────────────────

async def check_ai_limit(user_id: int) -> tuple[bool, int]:
    """Returns (allowed, remaining). Resets counter if period expired."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)

    user = await pool.fetchrow(
        "SELECT ai_messages_used, ai_limit_reset_at FROM users WHERE user_id = $1", user_id
    )
    if not user:
        return False, 0

    # Reset if period expired
    if user["ai_limit_reset_at"] is None or now >= user["ai_limit_reset_at"]:
        new_reset = now + timedelta(hours=config.ai_limit_hours)
        await pool.execute(
            "UPDATE users SET ai_messages_used = 0, ai_limit_reset_at = $2 WHERE user_id = $1",
            user_id, new_reset,
        )
        return True, config.ai_daily_limit

    used = user["ai_messages_used"]
    remaining = config.ai_daily_limit - used
    return remaining > 0, max(remaining, 0)


async def increment_ai_usage(user_id: int):
    pool = await get_pool()
    await pool.execute(
        "UPDATE users SET ai_messages_used = ai_messages_used + 1 WHERE user_id = $1", user_id
    )


async def reset_ai_limits_all():
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    new_reset = now + timedelta(hours=config.ai_limit_hours)
    await pool.execute(
        "UPDATE users SET ai_messages_used = 0, ai_limit_reset_at = $1", new_reset
    )


async def reset_ai_limit_user(user_id: int):
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    new_reset = now + timedelta(hours=config.ai_limit_hours)
    await pool.execute(
        "UPDATE users SET ai_messages_used = 0, ai_limit_reset_at = $2 WHERE user_id = $1",
        user_id, new_reset,
    )


# ── Tickets ──────────────────────────────────────────────────────

async def create_ticket(user_id: int, message: str, ai_summary: str | None = None) -> int:
    pool = await get_pool()
    return await pool.fetchval(
        """
        INSERT INTO tickets (user_id, message, ai_summary)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        user_id, message, ai_summary,
    )


async def get_ticket(ticket_id: int):
    pool = await get_pool()
    return await pool.fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)


async def get_user_tickets(user_id: int, limit: int = 10):
    pool = await get_pool()
    return await pool.fetch(
        "SELECT * FROM tickets WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
        user_id, limit,
    )


async def get_open_tickets(limit: int = 20, offset: int = 0):
    pool = await get_pool()
    return await pool.fetch(
        """
        SELECT t.*, u.username, u.first_name
        FROM tickets t JOIN users u ON t.user_id = u.user_id
        WHERE t.status IN ('open', 'in_progress')
        ORDER BY t.created_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit, offset,
    )


async def count_open_tickets() -> int:
    pool = await get_pool()
    return await pool.fetchval("SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'in_progress')")


async def update_ticket_status(ticket_id: int, status: str):
    pool = await get_pool()
    await pool.execute(
        "UPDATE tickets SET status = $2, updated_at = NOW() WHERE id = $1",
        ticket_id, status,
    )


async def set_ticket_reply(ticket_id: int, reply: str):
    pool = await get_pool()
    await pool.execute(
        "UPDATE tickets SET admin_reply = $2, status = 'closed', updated_at = NOW() WHERE id = $1",
        ticket_id, reply,
    )


# ── AI Conversations ────────────────────────────────────────────

async def save_ai_message(user_id: int, role: str, content: str):
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO ai_conversations (user_id, role, content) VALUES ($1, $2, $3)",
        user_id, role, content,
    )


async def get_ai_history(user_id: int, limit: int = 10):
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT role, content FROM ai_conversations
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id, limit,
    )
    return list(reversed(rows))


async def clear_ai_history(user_id: int):
    pool = await get_pool()
    await pool.execute("DELETE FROM ai_conversations WHERE user_id = $1", user_id)


# ── Stats ────────────────────────────────────────────────────────

async def get_stats() -> dict:
    pool = await get_pool()
    users = await pool.fetchval("SELECT COUNT(*) FROM users")
    tickets_total = await pool.fetchval("SELECT COUNT(*) FROM tickets")
    tickets_open = await pool.fetchval("SELECT COUNT(*) FROM tickets WHERE status IN ('open', 'in_progress')")
    ai_msgs = await pool.fetchval("SELECT COUNT(*) FROM ai_conversations")
    return {
        "users": users,
        "tickets_total": tickets_total,
        "tickets_open": tickets_open,
        "ai_messages": ai_msgs,
    }
