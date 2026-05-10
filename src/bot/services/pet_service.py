import random

from bot.db import get_pool, with_db_retry
from bot.services.economy_service import _add_inventory, _log_event


PET_ACTIONS = {
    "feed": {"label": "дать перекус", "hunger": 10, "thirst": -2, "cleanliness": -1, "mood": 3, "energy": 0, "health": 0, "affection": 1, "xp": 7, "zefirki": 1},
    "drink": {"label": "напоить", "hunger": 0, "thirst": 14, "cleanliness": 0, "mood": 2, "energy": 1, "health": 1, "affection": 1, "xp": 5, "zefirki": 1},
    "wash": {"label": "помыть", "hunger": -2, "thirst": 0, "cleanliness": 24, "mood": -2, "energy": -3, "health": 2, "affection": 1, "xp": 8, "zefirki": 2},
    "pet": {"label": "погладить", "hunger": 0, "thirst": 0, "cleanliness": 0, "mood": 10, "energy": 3, "health": 0, "affection": 6, "xp": 6, "zefirki": 1},
    "play": {"label": "поиграть", "hunger": -5, "thirst": -5, "cleanliness": -3, "mood": 16, "energy": -10, "health": 0, "affection": 3, "xp": 12, "zefirki": 4},
    "sleep": {"label": "уложить спать", "hunger": -4, "thirst": -3, "cleanliness": 0, "mood": 5, "energy": 28, "health": 3, "affection": 1, "xp": 6, "zefirki": 1},
    "heal": {"label": "позаботиться", "hunger": -2, "thirst": -2, "cleanliness": 2, "mood": 2, "energy": -2, "health": 16, "affection": 4, "xp": 10, "zefirki": 2},
}

PET_EVENTS = {
    "feed": [
        {"text": "Питомец аккуратно спрятал кусочек на потом. Выглядит довольным.", "mood": 3, "affection": 2, "xp": 4},
        {"text": "После перекуса питомец оживился и сам попросил маленькую тренировку.", "energy": -2, "mood": 4, "xp": 7, "zefirki": 1},
    ],
    "drink": [
        {"text": "Питомец устроил короткий забег до миски и обратно.", "thirst": 3, "energy": -2, "mood": 3, "xp": 5},
        {"text": "Вода явно пошла на пользу: питомец стал бодрее.", "health": 2, "energy": 3, "xp": 3},
    ],
    "wash": [
        {"text": "После ухода питомец нашёл удобное место и с важным видом позировал.", "cleanliness": 5, "mood": 3, "xp": 5},
        {"text": "Получилась маленькая уборочная миссия: питомец помог не разбросать вещи.", "cleanliness": 4, "affection": 2, "zefirki": 2, "xp": 4},
    ],
    "pet": [
        {"text": "Питомец устроился рядом и спокойно провёл с тобой пару минут.", "mood": 4, "affection": 4, "xp": 4},
        {"text": "Питомец заметно расслабился и стал больше доверять тебе.", "mood": 3, "affection": 5, "xp": 5},
    ],
    "play": [
        {"text": "Началась мини-игра: питомец ловко поймал игрушку на последней попытке.", "energy": -4, "mood": 5, "affection": 2, "xp": 9, "zefirki": 2},
        {"text": "Питомец сам придумал испытание на реакцию и справился лучше обычного.", "energy": -5, "mood": 4, "xp": 10, "zefirki": 3},
        {"text": "Игра перешла в короткую охоту за спрятанной ленточкой.", "energy": -3, "mood": 4, "cleanliness": -1, "xp": 8},
    ],
    "sleep": [
        {"text": "Сон получился спокойным, питомец проснулся мягче и бодрее.", "energy": 8, "health": 2, "mood": 3, "xp": 4},
        {"text": "Питомец быстро уснул и восстановил силы лучше обычного.", "energy": 10, "health": 1, "xp": 3},
    ],
    "heal": [
        {"text": "Забота сработала: питомец стал увереннее и спокойнее.", "health": 5, "mood": 3, "affection": 2, "xp": 5},
        {"text": "Питомец выдержал процедуру терпеливо и получил дополнительный опыт.", "health": 3, "affection": 3, "xp": 8},
    ],
}

SPECIES = {
    "cat": {"name": "Котик", "emoji": "🐱"},
    "dog": {"name": "Пёсель", "emoji": "🐶"},
    "squirrel": {"name": "Белочка", "emoji": "🐿"},
}

_rng = random.SystemRandom()


def _cap(value: int) -> int:
    return max(0, min(100, value))


def _level_for_xp(xp: int) -> int:
    return max(1, xp // 100 + 1)


@with_db_retry
async def get_pet(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT p.*, i.name AS cosmetic_name, i.rarity AS cosmetic_rarity
            FROM pets p
            LEFT JOIN items i ON i.id = p.cosmetic_item_id
            WHERE p.owner_id = %s AND p.active = TRUE
            """,
            (user_id,),
        )
        return await cur.fetchone()


@with_db_retry
async def list_pets(user_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT p.*, i.name AS cosmetic_name, i.rarity AS cosmetic_rarity
            FROM pets p
            LEFT JOIN items i ON i.id = p.cosmetic_item_id
            WHERE p.owner_id = %s
            ORDER BY p.active DESC, p.created_at, p.id
            """,
            (user_id,),
        )
        return await cur.fetchall()


@with_db_retry
async def create_pet(user_id: int, species: str, name: str | None = None) -> dict:
    if species not in SPECIES:
        species = "cat"
    default_name = name or SPECIES[species]["name"]
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM pets WHERE owner_id = %s AND species = %s",
                (user_id, species),
            )
            existing_species = await cur.fetchone()
            cur = await conn.execute(
                "SELECT * FROM pets WHERE owner_id = %s ORDER BY active DESC, created_at LIMIT 1",
                (user_id,),
            )
            any_pet = await cur.fetchone()

            if any_pet and not existing_species:
                return any_pet

            await conn.execute("UPDATE pets SET active = FALSE WHERE owner_id = %s", (user_id,))
            cur = await conn.execute(
                """
                INSERT INTO pets (owner_id, user_id, species, name, active)
                VALUES (%s, %s, %s, %s, TRUE)
                ON CONFLICT (owner_id, species) DO UPDATE
                    SET active = TRUE,
                        updated_at = NOW()
                RETURNING *
                """,
                (user_id, user_id if not any_pet else None, species, default_name),
            )
            pet = await cur.fetchone()
    return await get_pet(user_id) or pet


@with_db_retry
async def get_or_create_pet(user_id: int) -> dict | None:
    return await get_pet(user_id)


@with_db_retry
async def set_active_pet(user_id: int, pet_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                "SELECT id FROM pets WHERE id = %s AND owner_id = %s",
                (pet_id, user_id),
            )
            if not await cur.fetchone():
                return None
            await conn.execute("UPDATE pets SET active = FALSE WHERE owner_id = %s", (user_id,))
            await conn.execute(
                "UPDATE pets SET active = TRUE, updated_at = NOW() WHERE id = %s",
                (pet_id,),
            )
    return await get_pet(user_id)


async def _active_pet_for_update(conn, user_id: int) -> dict | None:
    cur = await conn.execute(
        "SELECT * FROM pets WHERE owner_id = %s AND active = TRUE FOR UPDATE",
        (user_id,),
    )
    return await cur.fetchone()


async def _reaction(conn, species: str, action: str, pet: dict) -> str:
    mood = "happy" if pet["mood"] >= 75 else "sad" if pet["mood"] <= 35 else "normal"
    cur = await conn.execute(
        """
        SELECT text FROM pet_reactions
        WHERE species = %s AND action = %s AND mood IN (%s, 'normal')
        ORDER BY CASE WHEN mood = %s THEN 0 ELSE 1 END, random()
        LIMIT 1
        """,
        (species, action, mood, mood),
    )
    row = await cur.fetchone()
    if row:
        return row["text"]
    return "Питомец спокойно реагирует и остаётся рядом."


async def _maybe_pet_event(conn, user_id: int, action: str, pet: dict) -> tuple[dict, dict | None]:
    events = PET_EVENTS.get(action) or []
    if not events or _rng.randint(1, 100) > 24:
        return pet, None

    event = dict(_rng.choice(events))
    new_xp = pet["xp"] + int(event.get("xp") or 0)
    new_level = _level_for_xp(new_xp)
    cur = await conn.execute(
        """
        UPDATE pets
           SET xp = %s,
               level = %s,
               hunger = %s,
               thirst = %s,
               cleanliness = %s,
               mood = %s,
               energy = %s,
               health = %s,
               affection = %s,
               updated_at = NOW()
         WHERE id = %s
         RETURNING *
        """,
        (
            new_xp,
            new_level,
            _cap(pet["hunger"] + int(event.get("hunger") or 0)),
            _cap(pet["thirst"] + int(event.get("thirst") or 0)),
            _cap(pet["cleanliness"] + int(event.get("cleanliness") or 0)),
            _cap(pet["mood"] + int(event.get("mood") or 0)),
            _cap(pet["energy"] + int(event.get("energy") or 0)),
            _cap(pet["health"] + int(event.get("health") or 0)),
            _cap(pet["affection"] + int(event.get("affection") or 0)),
            pet["id"],
        ),
    )
    updated = await cur.fetchone()

    zefirki = int(event.get("zefirki") or 0)
    if zefirki > 0:
        await conn.execute(
            "UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s",
            (zefirki, user_id),
        )
        await conn.execute(
            "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
            (user_id, zefirki, "pet_event"),
        )
        await _log_event(conn, user_id, zefirki, "pet_event", meta={"action": action})

    event["level_up"] = new_level > pet["level"]
    return updated, event


@with_db_retry
async def rename_pet(user_id: int, name: str) -> dict | None:
    name = name.strip()[:24]
    if not name:
        return None
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE pets SET name = %s, updated_at = NOW() WHERE owner_id = %s AND active = TRUE",
            (name, user_id),
        )
    return await get_pet(user_id)


@with_db_retry
async def equip_pet_cosmetic(user_id: int, item_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            pet = await _active_pet_for_update(conn, user_id)
            if not pet:
                return {"ok": False, "error": "no_pet"}
            cur = await conn.execute(
                """
                SELECT ui.quantity, i.*
                FROM user_inventory ui
                JOIN items i ON i.id = ui.item_id
                WHERE ui.user_id = %s AND ui.item_id = %s AND ui.quantity > 0
                """,
                (user_id, item_id),
            )
            item = await cur.fetchone()
            if not item:
                return {"ok": False, "error": "no_item"}
            if item["item_type"] != "cosmetic":
                return {"ok": False, "error": "not_cosmetic", "item": item}
            await conn.execute(
                "UPDATE pets SET cosmetic_item_id = %s, updated_at = NOW() WHERE id = %s",
                (item_id, pet["id"]),
            )
            await _log_event(conn, user_id, 0, "pet_cosmetic", item_id=item_id)
    return {"ok": True, "pet": await get_pet(user_id), "item": item}


@with_db_retry
async def perform_pet_action(user_id: int, action: str) -> dict:
    cfg = PET_ACTIONS.get(action)
    if not cfg:
        return {"ok": False, "error": "unknown_action"}

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            pet = await _active_pet_for_update(conn, user_id)
            if not pet:
                return {"ok": False, "error": "no_pet"}

            if action in ("play", "wash", "heal") and pet["energy"] < 10:
                return {"ok": False, "error": "low_energy", "pet": pet, "action": cfg}

            cur = await conn.execute(
                """
                INSERT INTO pet_actions (user_id, action)
                VALUES (%s, %s)
                ON CONFLICT (user_id, action, action_date) DO NOTHING
                RETURNING action
                """,
                (user_id, action),
            )
            if not await cur.fetchone():
                return {"ok": False, "error": "already_done", "pet": pet, "action": cfg}

            new_xp = pet["xp"] + cfg["xp"]
            new_level = _level_for_xp(new_xp)
            new_hunger = _cap(pet["hunger"] + cfg["hunger"])
            new_thirst = _cap(pet["thirst"] + cfg["thirst"])
            new_cleanliness = _cap(pet["cleanliness"] + cfg["cleanliness"])
            new_mood = _cap(pet["mood"] + cfg["mood"])
            new_energy = _cap(pet["energy"] + cfg["energy"])
            new_health = _cap(pet["health"] + cfg["health"])
            new_affection = _cap(pet["affection"] + cfg["affection"])

            cur = await conn.execute(
                """
                UPDATE pets
                   SET xp = %s,
                       level = %s,
                       hunger = %s,
                       thirst = %s,
                       cleanliness = %s,
                       mood = %s,
                       energy = %s,
                        health = %s,
                        affection = %s,
                        last_action_at = NOW(),
                        updated_at = NOW()
                 WHERE id = %s
                 RETURNING *
                """,
                (
                    new_xp,
                    new_level,
                    new_hunger,
                    new_thirst,
                    new_cleanliness,
                    new_mood,
                    new_energy,
                    new_health,
                    new_affection,
                    pet["id"],
                ),
            )
            updated = await cur.fetchone()
            base_level_up = new_level > pet["level"]
            updated, event = await _maybe_pet_event(conn, user_id, action, updated)
            reaction = await _reaction(conn, updated["species"], action, updated)

            reward = cfg["zefirki"]
            if reward > 0:
                await conn.execute(
                    "UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s",
                    (reward, user_id),
                )
                await conn.execute(
                    "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                    (user_id, reward, "pet"),
                )
                await _log_event(conn, user_id, reward, "pet_action", meta={"action": action})

            item = None
            if _rng.randint(1, 100) <= 10:
                cur = await conn.execute(
                    """
                    SELECT * FROM items
                    WHERE is_active = TRUE AND rarity IN ('common', 'uncommon')
                    ORDER BY random()
                    LIMIT 1
                    """
                )
                item = await cur.fetchone()
                if item:
                    await _add_inventory(conn, user_id, item["id"], 1)
                    await _log_event(conn, user_id, 0, "pet_item", item_id=item["id"], meta={"action": action})

            result_pet = dict(updated)
            if updated.get("cosmetic_item_id"):
                cur = await conn.execute(
                    "SELECT name, rarity FROM items WHERE id = %s",
                    (updated["cosmetic_item_id"],),
                )
                cosmetic = await cur.fetchone()
                if cosmetic:
                    result_pet["cosmetic_name"] = cosmetic["name"]
                    result_pet["cosmetic_rarity"] = cosmetic["rarity"]

            return {
                "ok": True,
                "pet": result_pet,
                "action": cfg,
                "zefirki": reward,
                "item": item,
                "reaction": reaction,
                "event": event,
                "level_up": base_level_up or bool(event and event.get("level_up")),
            }
