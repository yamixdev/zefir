"""Подключение к PostgreSQL через pool.

На Neon free tier endpoint автосуспендится после 5 минут бездействия.
Одиночное соединение после этого ломается — pool перехватывает `broken`
коннекты и пересоздаёт их прозрачно.
"""
import logging

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.config import config

logger = logging.getLogger("зефир.бд")

_pool: AsyncConnectionPool | None = None


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=config.database_url,
            min_size=1,
            max_size=5,
            max_idle=300,
            open=False,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        await _pool.open(wait=True, timeout=10)
        logger.info("🐘 Пул подключений к БД инициализирован")
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   BIGINT PRIMARY KEY,
                username  VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                is_banned BOOLEAN DEFAULT FALSE,
                ai_messages_used INT DEFAULT 0,
                ai_bonus INT DEFAULT 0,
                ai_limit_reset_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '12 hours',
                last_menu_msg_id BIGINT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE users ADD COLUMN IF NOT EXISTS last_menu_msg_id BIGINT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_bonus INT DEFAULT 0;

            CREATE TABLE IF NOT EXISTS tickets (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id),
                message     TEXT NOT NULL,
                ai_summary  TEXT,
                status      VARCHAR(20) DEFAULT 'open',
                admin_reply TEXT,
                seen_at     TIMESTAMPTZ,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            ALTER TABLE tickets ADD COLUMN IF NOT EXISTS seen_at TIMESTAMPTZ;

            CREATE TABLE IF NOT EXISTS ai_conversations (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                role       VARCHAR(10) NOT NULL,
                content    TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS user_consents (
                user_id     BIGINT NOT NULL,
                doc_version TEXT NOT NULL,
                doc_hash    TEXT NOT NULL,
                accepted_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, doc_version)
            );
        """)


async def close_db():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("🐘 Пул подключений закрыт")
