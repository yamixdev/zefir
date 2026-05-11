import random
from datetime import UTC
from psycopg.types.json import Jsonb

from bot.db import get_pool, with_db_retry
from bot.services.economy_service import _add_inventory, _log_event
from bot.services.time_service import today_msk, now_utc


PET_ACTIONS = {
    "feed": {"label": "дать перекус", "hunger": 10, "thirst": -2, "cleanliness": -1, "mood": 3, "energy": 0, "health": 0, "affection": 1, "xp": 7, "zefirki": 0},
    "drink": {"label": "напоить", "hunger": 0, "thirst": 14, "cleanliness": 0, "mood": 2, "energy": 1, "health": 1, "affection": 1, "xp": 5, "zefirki": 0},
    "wash": {"label": "помыть", "hunger": -2, "thirst": 0, "cleanliness": 24, "mood": -2, "energy": -3, "health": 2, "affection": 1, "xp": 8, "zefirki": 0},
    "pet": {"label": "погладить", "hunger": 0, "thirst": 0, "cleanliness": 0, "mood": 10, "energy": 3, "health": 0, "affection": 6, "xp": 6, "zefirki": 0},
    "play": {"label": "поиграть", "hunger": -5, "thirst": -5, "cleanliness": -3, "mood": 16, "energy": -10, "health": 0, "affection": 3, "xp": 12, "zefirki": 1},
    "sleep": {"label": "уложить спать", "hunger": -4, "thirst": -3, "cleanliness": 0, "mood": 5, "energy": 28, "health": 3, "affection": 1, "xp": 6, "zefirki": 0},
    "heal": {"label": "позаботиться", "hunger": -2, "thirst": -2, "cleanliness": 2, "mood": 2, "energy": -2, "health": 16, "affection": 4, "xp": 10, "zefirki": 0},
}

PET_EVENTS = {
    "feed": [
        {"text": "Питомец аккуратно спрятал кусочек на потом. Выглядит довольным.", "mood": 3, "affection": 2, "xp": 4},
        {"text": "После перекуса питомец оживился и сам попросил маленькую тренировку.", "energy": -2, "mood": 4, "xp": 7},
    ],
    "drink": [
        {"text": "Питомец устроил короткий забег до миски и обратно.", "thirst": 3, "energy": -2, "mood": 3, "xp": 5},
        {"text": "Вода явно пошла на пользу: питомец стал бодрее.", "health": 2, "energy": 3, "xp": 3},
    ],
    "wash": [
        {"text": "После ухода питомец нашёл удобное место и с важным видом позировал.", "cleanliness": 5, "mood": 3, "xp": 5},
        {"text": "Получилась маленькая уборочная миссия: питомец помог не разбросать вещи.", "cleanliness": 4, "affection": 2, "xp": 4},
    ],
    "pet": [
        {"text": "Питомец устроился рядом и спокойно провёл с тобой пару минут.", "mood": 4, "affection": 4, "xp": 4},
        {"text": "Питомец заметно расслабился и стал больше доверять тебе.", "mood": 3, "affection": 5, "xp": 5},
    ],
    "play": [
        {"text": "Началась мини-игра: питомец ловко поймал игрушку на последней попытке.", "energy": -4, "mood": 5, "affection": 2, "xp": 9},
        {"text": "Питомец сам придумал испытание на реакцию и справился лучше обычного.", "energy": -5, "mood": 4, "xp": 10},
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

ROOMS = {
    "kitchen": "кухня",
    "bedroom": "спальня",
    "playroom": "игровая",
    "bathroom": "ванная",
    "yard": "двор",
}

PET_MINIGAMES = {
    "catch": {"name": "Поймай игрушку", "energy": -8, "mood": 10, "xp": 16},
    "find": {"name": "Найди лакомство", "energy": -5, "hunger": 6, "mood": 7, "xp": 12},
    "reaction": {"name": "Тренировка реакции", "energy": -10, "mood": 8, "xp": 20},
}

_rng = random.SystemRandom()


def _cap(value: int) -> int:
    return max(0, min(100, value))


def _level_for_xp(xp: int) -> int:
    return max(1, xp // 100 + 1)


def _aware(value):
    if value is None:
        return now_utc()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _pet_state_line(pet: dict) -> str:
    if pet["energy"] <= 25:
        return "отдыхает и экономит силы"
    if pet["hunger"] <= 30:
        return "ищет, чем перекусить"
    if pet["thirst"] <= 30:
        return "поглядывает на миску с водой"
    if pet["cleanliness"] <= 30:
        return "просится в ванную"
    if pet["mood"] <= 35:
        return "скучает и ждёт внимания"
    if pet["room"] == "playroom":
        return "занят игрушками"
    if pet["room"] == "bedroom":
        return "устроился поудобнее"
    if pet["room"] == "yard":
        return "смотрит, что происходит во дворе"
    return "спокойно занимается своими делами"


async def _ensure_home(conn, user_id: int) -> dict:
    cur = await conn.execute(
        """
        INSERT INTO pet_homes (user_id)
        VALUES (%s)
        ON CONFLICT (user_id) DO UPDATE SET updated_at = pet_homes.updated_at
        RETURNING *
        """,
        (user_id,),
    )
    return await cur.fetchone()


async def _apply_decay_locked(conn, pet: dict) -> dict:
    last = _aware(pet.get("last_decay_at") or pet.get("updated_at") or pet.get("created_at"))
    now = now_utc()
    hours = int((now - last).total_seconds() // 3600)
    if hours < 1:
        return pet

    hours = min(hours, 72)
    hunger = _cap(pet["hunger"] - hours * 3)
    thirst = _cap(pet["thirst"] - hours * 4)
    cleanliness = _cap(pet["cleanliness"] - hours * 2)
    energy = _cap(pet["energy"] + hours * 5)
    mood_loss = hours * (2 if hunger > 25 and thirst > 25 and cleanliness > 25 else 4)
    mood = _cap(pet["mood"] - mood_loss)
    health_loss = max(0, hours - 8) if min(hunger, thirst, cleanliness) < 20 else 0
    health = _cap(pet["health"] - health_loss)

    cur = await conn.execute(
        """
        UPDATE pets
           SET hunger = %s,
               thirst = %s,
               cleanliness = %s,
               mood = %s,
               energy = %s,
               health = %s,
               last_decay_at = %s,
               updated_at = NOW()
         WHERE id = %s
         RETURNING *
        """,
        (hunger, thirst, cleanliness, mood, energy, health, now, pet["id"]),
    )
    updated = await cur.fetchone()
    if hours >= 3:
        await conn.execute(
            """
            INSERT INTO pet_status_events (user_id, pet_id, event_type, text, meta)
            VALUES (%s, %s, 'decay', %s, %s)
            """,
            (
                pet["owner_id"],
                pet["id"],
                f"Питомец провёл без ухода около {hours} ч. Состояние обновилось.",
                Jsonb({"hours": hours}),
            ),
        )
    return updated


async def _decorate_pet(conn, pet: dict | None) -> dict | None:
    if not pet:
        return None
    result = dict(pet)
    if result.get("cosmetic_item_id"):
        cur = await conn.execute(
            "SELECT name, rarity FROM items WHERE id = %s",
            (result["cosmetic_item_id"],),
        )
        cosmetic = await cur.fetchone()
        if cosmetic:
            result["cosmetic_name"] = cosmetic["name"]
            result["cosmetic_rarity"] = cosmetic["rarity"]
    cur = await conn.execute(
        "SELECT * FROM pet_homes WHERE user_id = %s",
        (result["owner_id"],),
    )
    home = await cur.fetchone()
    result["home_level"] = home["level"] if home else 1
    result["room_label"] = ROOMS.get(result.get("room"), "комната")
    result["state_text"] = _pet_state_line(result)
    return result


@with_db_retry
async def get_pet(user_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            await _ensure_home(conn, user_id)
            cur = await conn.execute(
                "SELECT * FROM pets WHERE owner_id = %s AND active = TRUE FOR UPDATE",
                (user_id,),
            )
            pet = await cur.fetchone()
            if pet:
                pet = await _apply_decay_locked(conn, pet)
            return await _decorate_pet(conn, pet)


@with_db_retry
async def list_pets(user_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        await _ensure_home(conn, user_id)
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
            await _ensure_home(conn, user_id)
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
            cur = await conn.execute(
                "SELECT COUNT(*) AS cnt, COALESCE(MAX(level), 1) AS max_level FROM pets WHERE owner_id = %s",
                (user_id,),
            )
            pet_stats = await cur.fetchone()

            if any_pet and not existing_species:
                count = int(pet_stats["cnt"] or 0)
                max_level = int(pet_stats["max_level"] or 1)
                required_code = "second_pet_license" if count == 1 else "big_home_contract"
                required_level = 8 if count == 1 else 15
                if count >= 3 or max_level < required_level:
                    return any_pet
                cur = await conn.execute(
                    """
                    SELECT ui.quantity, i.id
                    FROM user_inventory ui
                    JOIN items i ON i.id = ui.item_id
                    WHERE ui.user_id = %s AND i.code = %s AND ui.quantity > 0
                    FOR UPDATE
                    """,
                    (user_id, required_code),
                )
                unlock = await cur.fetchone()
                if not unlock:
                    return any_pet
                await conn.execute(
                    """
                    UPDATE user_inventory
                       SET quantity = quantity - 1, updated_at = NOW()
                     WHERE user_id = %s AND item_id = %s
                    """,
                    (user_id, unlock["id"]),
                )
                await _log_event(conn, user_id, 0, "pet_unlock", item_id=unlock["id"], meta={"species": species})

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
    await _ensure_home(conn, user_id)
    cur = await conn.execute(
        "SELECT * FROM pets WHERE owner_id = %s AND active = TRUE FOR UPDATE",
        (user_id,),
    )
    pet = await cur.fetchone()
    if pet:
        pet = await _apply_decay_locked(conn, pet)
    return pet


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
            if pet.get("cosmetic_item_id") == item_id:
                result_pet = dict(pet)
                result_pet["cosmetic_name"] = item["name"]
                result_pet["cosmetic_rarity"] = item["rarity"]
                return {"ok": False, "error": "already_equipped", "pet": result_pet, "item": item}
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
    action_date = today_msk()

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
                INSERT INTO pet_actions (user_id, action, action_date)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, action, action_date) DO NOTHING
                RETURNING action
                """,
                (user_id, action, action_date),
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
            drop_roll = _rng.randint(1, 100)
            if drop_roll <= 32:
                key_code = None
                if drop_roll <= 5:
                    key_code = "gold_key"
                elif drop_roll <= 12:
                    key_code = "silver_key"
                elif drop_roll <= 22:
                    key_code = "bronze_key"
                key_filter = "code = %s" if key_code else "rarity IN ('common', 'uncommon')"
                params = (key_code,) if key_code else ()
                cur = await conn.execute(
                    f"""
                    SELECT * FROM items
                    WHERE is_active = TRUE AND {key_filter}
                    ORDER BY random()
                    LIMIT 1
                    """,
                    params,
                )
                item = await cur.fetchone()
                if item:
                    await _add_inventory(conn, user_id, item["id"], 1)
                    await _log_event(conn, user_id, 0, "pet_item", item_id=item["id"], meta={"action": action})

            result_pet = await _decorate_pet(conn, updated)

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


@with_db_retry
async def get_pet_home(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        home = await _ensure_home(conn, user_id)
        cur = await conn.execute(
            """
            SELECT phi.room, i.*
            FROM pet_home_items phi
            JOIN items i ON i.id = phi.item_id
            WHERE phi.user_id = %s
            ORDER BY phi.room, i.rarity, i.name
            """,
            (user_id,),
        )
        items = await cur.fetchall()
        cur = await conn.execute(
            """
            SELECT * FROM pet_status_events
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (user_id,),
        )
        events = await cur.fetchall()
        return {"home": home, "items": items, "events": events, "rooms": ROOMS}


@with_db_retry
async def move_pet_room(user_id: int, room: str) -> dict:
    if room not in ROOMS:
        return {"ok": False, "error": "bad_room"}
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            pet = await _active_pet_for_update(conn, user_id)
            if not pet:
                return {"ok": False, "error": "no_pet"}
            await _ensure_home(conn, user_id)
            cur = await conn.execute(
                "UPDATE pets SET room = %s, updated_at = NOW() WHERE id = %s RETURNING *",
                (room, pet["id"]),
            )
            pet = await cur.fetchone()
            await conn.execute(
                """
                UPDATE pet_homes
                   SET active_room = %s, updated_at = NOW()
                 WHERE user_id = %s
                """,
                (room, user_id),
            )
            await conn.execute(
                """
                INSERT INTO pet_status_events (user_id, pet_id, event_type, text, meta)
                VALUES (%s, %s, 'room', %s, %s)
                """,
                (user_id, pet["id"], f"Питомец перешёл в комнату: {ROOMS[room]}.", Jsonb({"room": room})),
            )
            return {"ok": True, "pet": await _decorate_pet(conn, pet)}


@with_db_retry
async def install_home_item(user_id: int, item_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            await _ensure_home(conn, user_id)
            cur = await conn.execute(
                """
                SELECT ui.quantity, i.*
                FROM user_inventory ui
                JOIN items i ON i.id = ui.item_id
                WHERE ui.user_id = %s AND ui.item_id = %s AND ui.quantity > 0
                FOR UPDATE
                """,
                (user_id, item_id),
            )
            item = await cur.fetchone()
            if not item:
                return {"ok": False, "error": "no_item"}
            if item["item_type"] != "home_item":
                return {"ok": False, "error": "not_home_item", "item": item}
            effect = item.get("effect_json") or {}
            room = effect.get("room") or "kitchen"
            if room == "all":
                room = "playroom"
            if room not in ROOMS:
                room = "kitchen"
            cur = await conn.execute(
                """
                INSERT INTO pet_home_items (user_id, room, item_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, room, item_id) DO NOTHING
                RETURNING item_id
                """,
                (user_id, room, item_id),
            )
            if not await cur.fetchone():
                return {"ok": False, "error": "already_installed", "item": item, "room": room}
            await conn.execute(
                """
                UPDATE user_inventory
                   SET quantity = quantity - 1, updated_at = NOW()
                 WHERE user_id = %s AND item_id = %s
                """,
                (user_id, item_id),
            )
            await _log_event(conn, user_id, 0, "home_item_install", item_id=item_id, meta={"room": room})
            return {"ok": True, "item": item, "room": room}


@with_db_retry
async def play_pet_minigame(user_id: int, game_code: str | None = None) -> dict:
    if game_code not in PET_MINIGAMES:
        game_code = _rng.choice(list(PET_MINIGAMES.keys()))
    cfg = PET_MINIGAMES[game_code]
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            pet = await _active_pet_for_update(conn, user_id)
            if not pet:
                return {"ok": False, "error": "no_pet"}
            if pet["energy"] < 12:
                return {"ok": False, "error": "low_energy", "pet": await _decorate_pet(conn, pet)}
            score = (
                pet["level"] * 4
                + pet["mood"]
                + pet["affection"]
                + pet["energy"]
                + _rng.randint(1, 60)
            )
            result = "great" if score >= 210 else "good" if score >= 155 else "ok"
            mult = {"great": 2, "good": 1, "ok": 0}[result]
            xp_gain = cfg["xp"] + mult * 8
            mood_gain = cfg["mood"] + mult * 3
            new_xp = pet["xp"] + xp_gain
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
                       affection = %s,
                       last_action_at = NOW(),
                       updated_at = NOW()
                 WHERE id = %s
                 RETURNING *
                """,
                (
                    new_xp,
                    new_level,
                    _cap(pet["hunger"] - 4),
                    _cap(pet["thirst"] - 5),
                    _cap(pet["cleanliness"] - 2),
                    _cap(pet["mood"] + mood_gain),
                    _cap(pet["energy"] + cfg["energy"]),
                    _cap(pet["affection"] + 2 + mult),
                    pet["id"],
                ),
            )
            updated = await cur.fetchone()
            reaction = await _reaction(conn, updated["species"], "minigame", updated)
            item = None
            if result == "great":
                roll = _rng.randint(1, 100)
                key_code = "gold_key" if roll <= 5 else "silver_key" if roll <= 12 else "bronze_key" if roll <= 22 else None
                if key_code:
                    cur = await conn.execute("SELECT * FROM items WHERE code = %s AND is_active = TRUE", (key_code,))
                    item = await cur.fetchone()
                    if item:
                        await _add_inventory(conn, user_id, item["id"], 1)
                        await _log_event(conn, user_id, 0, "pet_minigame_key", item_id=item["id"], meta={"game": game_code})
            await conn.execute(
                """
                INSERT INTO pet_status_events (user_id, pet_id, event_type, text, meta)
                VALUES (%s, %s, 'minigame', %s, %s)
                """,
                (
                    user_id,
                    pet["id"],
                    f"{cfg['name']}: результат {result}.",
                    Jsonb({"game": game_code, "result": result, "score": score}),
                ),
            )
            return {
                "ok": True,
                "pet": await _decorate_pet(conn, updated),
                "game": cfg,
                "result": result,
                "xp": xp_gain,
                "reaction": reaction,
                "item": item,
                "level_up": new_level > pet["level"],
            }
