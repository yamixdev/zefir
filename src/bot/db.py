import asyncpg

from bot.config import config

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(config.database_url, min_size=1, max_size=5)
    return _pool


async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id   BIGINT PRIMARY KEY,
                username  VARCHAR(255),
                first_name VARCHAR(255),
                last_name VARCHAR(255),
                is_banned BOOLEAN DEFAULT FALSE,
                ai_messages_used INT DEFAULT 0,
                ai_limit_reset_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '12 hours',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id          SERIAL PRIMARY KEY,
                user_id     BIGINT REFERENCES users(user_id),
                message     TEXT NOT NULL,
                ai_summary  TEXT,
                status      VARCHAR(20) DEFAULT 'open',
                admin_reply TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS ai_conversations (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT REFERENCES users(user_id),
                role       VARCHAR(10) NOT NULL,
                content    TEXT NOT NULL,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)


async def close_db():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
