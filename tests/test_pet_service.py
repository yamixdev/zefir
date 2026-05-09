from bot.services.economy_service import grant_item, use_inventory_item
from bot.services.pet_service import create_pet, list_pets, perform_pet_action, set_active_pet

from conftest import create_user, fetch_one, fetch_value


async def test_pet_action_without_pet_does_not_auto_create_default_pet(conn):
    await create_user(conn, 301, zefirki=0)

    result = await perform_pet_action(301, "feed")

    assert result["ok"] is False
    assert result["error"] == "no_pet"
    assert await fetch_value(conn, "SELECT COUNT(*) FROM pets WHERE owner_id = 301") == 0


async def test_create_and_switch_active_pet(conn):
    await create_user(conn, 302, zefirki=0)

    cat = await create_pet(302, "cat")
    await conn.execute(
        "INSERT INTO pets (owner_id, species, name, active) VALUES (302, 'dog', 'Пёсель', FALSE)"
    )
    dog = await fetch_one(conn, "SELECT id FROM pets WHERE owner_id = 302 AND species = 'dog'")
    active = await set_active_pet(302, dog["id"])
    pets = await list_pets(302)

    assert cat["species"] == "cat"
    assert active["species"] == "dog"
    assert len(pets) == 2
    assert sum(1 for pet in pets if pet["active"]) == 1


async def test_pet_item_requires_active_pet_before_consuming_inventory(conn):
    await create_user(conn, 303, zefirki=0)
    item = await fetch_one(conn, "SELECT id FROM items WHERE code = 'cheap_food'")
    assert await grant_item(303, item["id"], 1, reason="test") is True

    missing_pet = await use_inventory_item(303, item["id"])
    quantity_after_fail = await fetch_value(
        conn,
        "SELECT quantity FROM user_inventory WHERE user_id = 303 AND item_id = %s",
        (item["id"],),
    )

    await create_pet(303, "cat")
    used = await use_inventory_item(303, item["id"])

    assert missing_pet["ok"] is False
    assert missing_pet["error"] == "no_pet"
    assert quantity_after_fail == 1
    assert used["ok"] is True
    assert await fetch_value(
        conn,
        "SELECT quantity FROM user_inventory WHERE user_id = 303 AND item_id = %s",
        (item["id"],),
    ) == 0
