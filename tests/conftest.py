import os

import psycopg
import pytest
from psycopg.rows import dict_row


async def _reset_public_schema(database_url: str) -> None:
    conn = await psycopg.AsyncConnection.connect(database_url, autocommit=True)
    async with conn:
        await conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.execute("CREATE SCHEMA public")


@pytest.fixture
def test_database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return url


@pytest.fixture
async def db(test_database_url, monkeypatch):
    from bot.config import config
    from bot.db import close_db, init_db

    await close_db()
    monkeypatch.setattr(config, "database_url", test_database_url)
    await _reset_public_schema(test_database_url)
    await init_db()
    yield
    await close_db()


@pytest.fixture
async def conn(db):
    from bot.db import get_pool

    pool = await get_pool()
    async with pool.connection() as connection:
        yield connection


async def create_user(conn, user_id: int, zefirki: int = 0) -> None:
    await conn.execute(
        """
        INSERT INTO users (user_id, username, first_name, zefirki)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE
            SET zefirki = EXCLUDED.zefirki
        """,
        (user_id, f"user{user_id}", f"User {user_id}", zefirki),
    )


async def fetch_one(conn, sql: str, params: tuple = ()):
    cur = await conn.execute(sql, params)
    return await cur.fetchone()


async def fetch_value(conn, sql: str, params: tuple = ()):
    row = await fetch_one(conn, sql, params)
    if not row:
        return None
    return next(iter(row.values()))
