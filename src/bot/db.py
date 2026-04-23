"""Подключение к PostgreSQL через pool.

На Neon free tier endpoint автосуспендится после 5 минут бездействия.
`check=AsyncConnectionPool.check_connection` делает `SELECT 1` перед
выдачей соединения. Но даже с ним бывает race: check прошёл, а коннект
умер до `execute`. Поэтому поверх пула стоит `with_db_retry` — ловит
OperationalError/InterfaceError, инвалидирует пул и повторяет запрос.

`min_size=0` — в serverless не держим idle-коннекты, открываем по запросу.
"""
import logging
from functools import wraps

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from bot.config import config

logger = logging.getLogger("зефирка.бд")

_pool: AsyncConnectionPool | None = None

RETRIABLE_DB_ERRORS = (
    psycopg.OperationalError,
    psycopg.InterfaceError,
)


async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=config.database_url,
            min_size=0,
            max_size=5,
            max_idle=300,
            open=False,
            check=AsyncConnectionPool.check_connection,
            kwargs={"row_factory": dict_row, "autocommit": True},
        )
        await _pool.open(wait=True, timeout=10)
        logger.info("🐘 Пул подключений к БД инициализирован")
    return _pool


def with_db_retry(fn):
    """Ретрай на мёртвых коннектах Neon после autosuspend.

    На OperationalError/InterfaceError (включая AdminShutdown) —
    закрывает пул, открывает новый и повторяет запрос один раз.
    """
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except RETRIABLE_DB_ERRORS as e:
            logger.warning(
                f"🐘 Коннект сдох в {fn.__name__} — пересоздаю пул и повторяю: {e.__class__.__name__}"
            )
            await close_db()
            return await fn(*args, **kwargs)
    return wrapper


@with_db_retry
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
            ALTER TABLE users ADD COLUMN IF NOT EXISTS zefirki INT DEFAULT 0;

            CREATE TABLE IF NOT EXISTS transactions (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                amount     INT NOT NULL,
                reason     VARCHAR(100) NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_transactions_user_created
                ON transactions (user_id, created_at DESC);

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
