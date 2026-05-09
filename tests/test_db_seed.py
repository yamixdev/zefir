from bot.db import init_db

from conftest import fetch_one, fetch_value


async def test_init_db_is_idempotent_and_preserves_admin_flags(conn):
    before = await fetch_value(conn, "SELECT COUNT(*) FROM pet_reactions")

    item = await fetch_one(conn, "SELECT id FROM items WHERE code = 'ribbon'")
    await conn.execute("UPDATE items SET is_active = FALSE WHERE id = %s", (item["id"],))
    await conn.execute(
        "UPDATE shop_offers SET is_active = FALSE WHERE item_id = %s AND is_daily = TRUE",
        (item["id"],),
    )

    await init_db()
    await init_db()

    after = await fetch_value(conn, "SELECT COUNT(*) FROM pet_reactions")
    flags = await fetch_one(
        conn,
        """
        SELECT i.is_active AS item_active, so.is_active AS offer_active
        FROM items i
        JOIN shop_offers so ON so.item_id = i.id AND so.is_daily = TRUE
        WHERE i.id = %s
        """,
        (item["id"],),
    )
    migrations = await fetch_value(conn, "SELECT COUNT(*) FROM schema_migrations")

    assert after == before
    assert flags["item_active"] is False
    assert flags["offer_active"] is False
    assert migrations >= 2
