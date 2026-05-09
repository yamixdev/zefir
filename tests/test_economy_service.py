from bot.config import config
from bot.services.economy_service import (
    buy_listing,
    cancel_listing,
    create_listing,
    grant_item,
    open_case,
)

from conftest import create_user, fetch_one, fetch_value


async def test_open_case_spends_currency_grants_one_item_and_logs(conn):
    await create_user(conn, 101, zefirki=500)
    case = await fetch_one(conn, "SELECT id, price FROM cases WHERE code = 'starter'")

    result = await open_case(101, case["id"])

    assert result["ok"] is True
    assert result["balance"] == 500 - case["price"]
    assert await fetch_value(conn, "SELECT COALESCE(SUM(quantity), 0) FROM user_inventory WHERE user_id = 101") == 1
    assert await fetch_value(conn, "SELECT COUNT(*) FROM economy_events WHERE user_id = 101 AND reason = 'case_open'") == 1


async def test_market_listing_buy_cancel_commission_and_double_buy(conn):
    seller_id = 201
    buyer_id = 202
    await create_user(conn, seller_id, zefirki=0)
    await create_user(conn, buyer_id, zefirki=500)
    item = await fetch_one(conn, "SELECT id FROM items WHERE code = 'ribbon'")
    assert await grant_item(seller_id, item["id"], 2, reason="test") is True

    first = await create_listing(seller_id, item["id"], 100)
    assert first["ok"] is True
    bought = await buy_listing(buyer_id, first["listing"]["id"])
    assert bought["ok"] is True
    assert bought["seller_income"] == 100 * (100 - config.market_commission_percent) // 100

    repeat = await buy_listing(303, first["listing"]["id"])
    assert repeat["ok"] is False
    assert repeat["error"] == "not_available"

    seller_balance = await fetch_value(conn, "SELECT zefirki FROM users WHERE user_id = %s", (seller_id,))
    buyer_balance = await fetch_value(conn, "SELECT zefirki FROM users WHERE user_id = %s", (buyer_id,))
    buyer_items = await fetch_value(
        conn,
        "SELECT quantity FROM user_inventory WHERE user_id = %s AND item_id = %s",
        (buyer_id, item["id"]),
    )
    assert seller_balance == bought["seller_income"]
    assert buyer_balance == 400
    assert buyer_items == 1

    second = await create_listing(seller_id, item["id"], 100)
    assert second["ok"] is True
    cancelled = await cancel_listing(seller_id, second["listing"]["id"])
    assert cancelled["ok"] is True
    seller_items = await fetch_value(
        conn,
        "SELECT quantity FROM user_inventory WHERE user_id = %s AND item_id = %s",
        (seller_id, item["id"]),
    )
    assert seller_items == 1
