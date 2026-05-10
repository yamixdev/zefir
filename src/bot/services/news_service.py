from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.config import config
from bot.db import get_pool, with_db_retry


NEWS_MODES = {"all", "updates", "off"}
NEWS_KINDS = {"news", "event", "update"}


def normalize_mode(mode: str | None) -> str:
    return mode if mode in NEWS_MODES else "all"


def normalize_kind(kind: str | None) -> str:
    return kind if kind in NEWS_KINDS else "news"


async def _ensure_settings(conn, user_id: int) -> dict:
    cur = await conn.execute(
        """
        INSERT INTO user_news_settings (user_id)
        VALUES (%s)
        ON CONFLICT (user_id) DO NOTHING
        RETURNING *
        """,
        (user_id,),
    )
    row = await cur.fetchone()
    if row:
        return row
    cur = await conn.execute("SELECT * FROM user_news_settings WHERE user_id = %s", (user_id,))
    return await cur.fetchone()


@with_db_retry
async def get_news_settings(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        return await _ensure_settings(conn, user_id)


@with_db_retry
async def set_news_mode(user_id: int, mode: str) -> dict:
    mode = normalize_mode(mode)
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO user_news_settings (user_id, notify_mode, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET notify_mode = EXCLUDED.notify_mode,
                    updated_at = NOW()
            RETURNING *
            """,
            (user_id, mode),
        )
        return await cur.fetchone()


@with_db_retry
async def list_news(kind: str | None = None, limit: int = 10, include_drafts: bool = False) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        params: list = []
        where = "TRUE" if include_drafts else "status = 'published'"
        if kind:
            where += " AND kind = %s"
            params.append(normalize_kind(kind))
        params.append(limit)
        cur = await conn.execute(
            f"""
            SELECT *
            FROM news_posts
            WHERE {where}
            ORDER BY COALESCE(published_at, created_at) DESC, id DESC
            LIMIT %s
            """,
            params,
        )
        return await cur.fetchall()


@with_db_retry
async def get_news(post_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM news_posts WHERE id = %s", (post_id,))
        return await cur.fetchone()


@with_db_retry
async def get_latest_update() -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT *
            FROM news_posts
            WHERE status = 'published' AND kind = 'update'
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """
        )
        return await cur.fetchone()


@with_db_retry
async def create_news_post(
    *,
    kind: str,
    title: str,
    body: str,
    created_by: int,
    release_version: str | None = None,
) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            INSERT INTO news_posts (kind, title, body, created_by, release_version)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (normalize_kind(kind), title.strip()[:160], body.strip(), created_by, release_version),
        )
        return await cur.fetchone()


@with_db_retry
async def publish_news(post_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            UPDATE news_posts
               SET status = 'published',
                   published_at = COALESCE(published_at, NOW()),
                   notification_until = COALESCE(notification_until, NOW() + make_interval(hours => %s)),
                   updated_at = NOW()
             WHERE id = %s
            RETURNING *
            """,
            (config.news_notification_hours, post_id),
        )
        return await cur.fetchone()


@with_db_retry
async def hide_news(post_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            UPDATE news_posts
               SET status = 'hidden',
                   updated_at = NOW()
             WHERE id = %s
            RETURNING *
            """,
            (post_id,),
        )
        return await cur.fetchone()


@with_db_retry
async def get_pending_notice(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        settings = await _ensure_settings(conn, user_id)
        mode = normalize_mode(settings.get("notify_mode"))
        if mode == "off":
            return None
        where_kind = "AND kind = 'update'" if mode == "updates" else ""
        cur = await conn.execute(
            f"""
            SELECT *
            FROM news_posts
            WHERE status = 'published'
              AND notify = TRUE
              AND notification_until >= NOW()
              {where_kind}
              AND (id > COALESCE(%s, 0))
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """,
            (settings.get("last_seen_post_id"),),
        )
        post = await cur.fetchone()
        if not post:
            return None
        if settings.get("notice_post_id") == post["id"] and settings.get("notice_msg_id"):
            return None
        return post


@with_db_retry
async def remember_notice_message(user_id: int, post_id: int, message_id: int) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO user_news_settings (user_id, notice_post_id, notice_msg_id, notice_sent_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET notice_post_id = EXCLUDED.notice_post_id,
                    notice_msg_id = EXCLUDED.notice_msg_id,
                    notice_sent_at = NOW(),
                    updated_at = NOW()
            """,
            (user_id, post_id, message_id),
        )


@with_db_retry
async def get_notice_message(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        settings = await _ensure_settings(conn, user_id)
        if not settings.get("notice_msg_id"):
            return None
        return settings


@with_db_retry
async def clear_notice_message(user_id: int, seen_post_id: int | None = None) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        if seen_post_id:
            await conn.execute(
                """
                INSERT INTO user_news_settings (user_id, last_seen_post_id, notice_post_id, notice_msg_id, notice_sent_at, updated_at)
                VALUES (%s, %s, NULL, NULL, NULL, NOW())
                ON CONFLICT (user_id) DO UPDATE
                    SET last_seen_post_id = GREATEST(COALESCE(user_news_settings.last_seen_post_id, 0), EXCLUDED.last_seen_post_id),
                        notice_post_id = NULL,
                        notice_msg_id = NULL,
                        notice_sent_at = NULL,
                        updated_at = NOW()
                """,
                (user_id, seen_post_id),
            )
        else:
            await conn.execute(
                """
                UPDATE user_news_settings
                   SET notice_post_id = NULL,
                       notice_msg_id = NULL,
                       notice_sent_at = NULL,
                       updated_at = NOW()
                 WHERE user_id = %s
                """,
                (user_id,),
            )


@with_db_retry
async def mark_news_seen(user_id: int, post_id: int) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO user_news_settings (user_id, last_seen_post_id, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE
                SET last_seen_post_id = GREATEST(COALESCE(user_news_settings.last_seen_post_id, 0), EXCLUDED.last_seen_post_id),
                    updated_at = NOW()
            """,
            (user_id, post_id),
        )


def notice_is_stale(settings: dict) -> bool:
    sent_at = settings.get("notice_sent_at")
    if not sent_at:
        return False
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - sent_at > timedelta(hours=config.news_notification_hours)
