import random
import logging
from psycopg.types.json import Jsonb

from bot.config import config
from bot.db import get_pool, with_db_retry
from bot.services.time_service import current_shop_rotation, format_msk, next_msk_midnight, today_msk


logger = logging.getLogger("зефирка.экономика")


RARITY_LABELS = {
    "trash": "серый",
    "common": "обычный",
    "uncommon": "необычный",
    "rare": "редкий",
    "epic": "эпический",
    "legendary": "легендарный",
}

RARITY_ICONS = {
    "trash": "⚪",
    "common": "🟢",
    "uncommon": "🔵",
    "rare": "🟣",
    "epic": "🟠",
    "legendary": "🌟",
}

RARITY_PRICE_LIMITS = {
    "trash": (5, 100),
    "common": (15, 300),
    "uncommon": (40, 800),
    "rare": (100, 2000),
    "epic": (250, 7000),
    "legendary": (700, 25000),
}

CATEGORY_LABELS = {
    "all": "всё",
    "food": "еда",
    "drink": "напитки",
    "care": "уход",
    "toy": "игрушки",
    "clothes": "одежда",
    "accessory": "аксессуары",
    "tech": "техника",
    "home": "домик",
    "key": "ключи",
    "collectible": "редкое",
}

ITEM_TYPE_LABELS = {
    "cosmetic": "косметика",
    "ai_bonus": "AI-бонус",
    "pet_boost": "буст питомца",
    "pet_consumable": "расходник для питомца",
    "pet_toy": "игрушка питомца",
    "home_item": "предмет домика",
    "case_key": "ключ от кейса",
    "unlock": "предмет открытия",
    "game_ticket": "игровой предмет",
    "collectible": "коллекционный предмет",
    "material": "материал",
}

_rng = random.SystemRandom()


def item_label(item: dict) -> str:
    icon = RARITY_ICONS.get(item.get("rarity"), "▫️")
    return f"{icon} {item['name']}"


def item_type_label(item_type: str | None) -> str:
    return ITEM_TYPE_LABELS.get(item_type or "", item_type or "предмет")


def item_action_hint(item: dict) -> str:
    item_type = item.get("item_type")
    effects = item.get("effect_json") or {}
    if item_type == "cosmetic":
        slot = effects.get("cosmetic_slot")
        return f"Косметика для питомца{f' · слот: {slot}' if slot else ''}. Не расходуется."
    if item_type in ("pet_consumable", "pet_boost"):
        return "Расходник для питомца. После применения исчезает и меняет состояние."
    if item_type == "pet_toy":
        return "Игрушка для питомца. Помогает настроению, опыту или мини-играм."
    if item_type == "home_item":
        room = effects.get("room")
        return f"Предмет домика{f' · комната: {room}' if room else ''}. Устанавливается в жилище."
    if item_type == "case_key":
        return "Ключ от кейса. Нужен для открытия сундуков и капсул."
    if item_type == "ai_bonus":
        return "Даёт дополнительные AI-запросы."
    if item_type == "unlock":
        return "Открывает новый слот или возможность, если выполнены условия."
    if item_type == "collectible":
        return "Коллекционный предмет. Можно хранить, продать или использовать в будущих обменах."
    if item_type == "material":
        return "Материал для обмена или будущего крафта."
    return "Можно оставить в коллекции или продать, если предмет продаётся."


def price_limits_for(item: dict) -> tuple[int, int]:
    return RARITY_PRICE_LIMITS.get(item.get("rarity"), (1, 10000))


async def _ensure_shop_rotation(conn) -> dict:
    rotation = current_shop_rotation()
    starts_at = rotation["starts_at"]
    ends_at = rotation["ends_at"]
    cur = await conn.execute(
        """
        INSERT INTO shop_rotations (rotation_key, starts_at, ends_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (rotation_key) DO NOTHING
        RETURNING rotation_key
        """,
        (rotation["key"], starts_at, ends_at),
    )
    if await cur.fetchone():
        logger.info(
            "🛒 Ротация магазина обновлена: key=%s, start_msk=%s, end_msk=%s",
            rotation["key"],
            format_msk(starts_at),
            format_msk(ends_at),
        )
    return rotation


async def _add_inventory(conn, user_id: int, item_id: int, quantity: int = 1) -> None:
    await conn.execute(
        """
        INSERT INTO user_inventory (user_id, item_id, quantity)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, item_id) DO UPDATE
            SET quantity = user_inventory.quantity + EXCLUDED.quantity,
                updated_at = NOW()
        """,
        (user_id, item_id, quantity),
    )


async def _log_event(
    conn,
    user_id: int,
    amount: int,
    reason: str,
    item_id: int | None = None,
    listing_id: int | None = None,
    game_id: str | None = None,
    meta: dict | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO economy_events (user_id, amount, reason, item_id, listing_id, game_id, meta)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, amount, reason, item_id, listing_id, game_id, Jsonb(meta or {})),
    )


async def _balance_conn(conn, user_id: int) -> int:
    cur = await conn.execute("SELECT zefirki FROM users WHERE user_id = %s", (user_id,))
    row = await cur.fetchone()
    return row["zefirki"] if row else 0


@with_db_retry
async def get_items(active_only: bool = True, shop_only: bool = False) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        sql = "SELECT * FROM items"
        clauses = []
        if active_only:
            clauses.append("is_active = TRUE")
        if shop_only:
            clauses.append("is_shop_item = TRUE")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += """
            ORDER BY CASE rarity
                WHEN 'trash' THEN 1 WHEN 'common' THEN 2 WHEN 'uncommon' THEN 3
                WHEN 'rare' THEN 4 WHEN 'epic' THEN 5 WHEN 'legendary' THEN 6
                ELSE 99 END, base_price, id
        """
        cur = await conn.execute(sql)
        return await cur.fetchall()


@with_db_retry
async def get_inventory(user_id: int, category: str | None = None) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        params: list = [user_id]
        category_sql = ""
        if category and category != "all":
            if category == "rare":
                category_sql = " AND i.rarity IN ('rare', 'epic', 'legendary')"
            else:
                category_sql = " AND i.category = %s"
                params.append(category)
        cur = await conn.execute(
            f"""
            SELECT ui.quantity, i.*
            FROM user_inventory ui
            JOIN items i ON i.id = ui.item_id
            WHERE ui.user_id = %s AND ui.quantity > 0{category_sql}
            ORDER BY CASE i.rarity
                WHEN 'legendary' THEN 1 WHEN 'epic' THEN 2 WHEN 'rare' THEN 3
                WHEN 'uncommon' THEN 4 WHEN 'common' THEN 5 WHEN 'trash' THEN 6
                ELSE 99 END, i.name
            """,
            tuple(params),
        )
        return await cur.fetchall()


@with_db_retry
async def get_inventory_item(user_id: int, item_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT ui.quantity, i.*
            FROM user_inventory ui
            JOIN items i ON i.id = ui.item_id
            WHERE ui.user_id = %s AND ui.item_id = %s AND ui.quantity > 0
            """,
            (user_id, item_id),
        )
        return await cur.fetchone()


@with_db_retry
async def get_case_key_counts(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT i.id, i.code, i.name, COALESCE(ui.quantity, 0) AS quantity
            FROM items i
            LEFT JOIN user_inventory ui ON ui.item_id = i.id AND ui.user_id = %s
            WHERE i.code IN ('bronze_key', 'silver_key', 'gold_key') AND i.is_active = TRUE
            ORDER BY CASE i.code
                WHEN 'bronze_key' THEN 1
                WHEN 'silver_key' THEN 2
                WHEN 'gold_key' THEN 3
                ELSE 4
            END
            """,
            (user_id,),
        )
        rows = await cur.fetchall()
    return {row["code"]: dict(row) for row in rows}


@with_db_retry
async def grant_item(user_id: int, item_id: int, quantity: int, reason: str = "admin") -> bool:
    if quantity <= 0:
        return False
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            if not await cur.fetchone():
                return False
            cur = await conn.execute("SELECT id FROM items WHERE id = %s", (item_id,))
            if not await cur.fetchone():
                return False
            await _add_inventory(conn, user_id, item_id, quantity)
            await _log_event(conn, user_id, 0, reason, item_id=item_id, meta={"quantity": quantity})
    return True


@with_db_retry
async def admin_grant_zefirki(user_id: int, amount: int, reason: str = "admin") -> int | None:
    if amount == 0:
        return None
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            if amount > 0:
                cur = await conn.execute(
                    "UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s RETURNING zefirki",
                    (amount, user_id),
                )
            else:
                cur = await conn.execute(
                    "SELECT zefirki FROM users WHERE user_id = %s FOR UPDATE",
                    (user_id,),
                )
                current = await cur.fetchone()
                if not current:
                    return None
                amount = -min(abs(amount), current["zefirki"])
                if amount == 0:
                    return current["zefirki"]
                cur = await conn.execute(
                    """
                    UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s
                    RETURNING zefirki
                    """,
                    (amount, user_id),
                )
            row = await cur.fetchone()
            if not row:
                return None
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (user_id, amount, reason),
            )
            await _log_event(conn, user_id, amount, reason)
            return row["zefirki"]


@with_db_retry
async def list_cases(include_inactive: bool = False) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        sql = """
            SELECT c.*, i.code AS key_code, i.name AS key_name, i.rarity AS key_rarity
            FROM cases c
            LEFT JOIN items i ON i.id = c.required_key_item_id
        """
        if not include_inactive:
            sql += " WHERE c.is_active = TRUE"
        sql += " ORDER BY c.sort_order, c.price, c.id"
        cur = await conn.execute(sql)
        return await cur.fetchall()


async def get_case_rewards(case_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT cr.weight, i.*
            FROM case_rewards cr
            JOIN items i ON i.id = cr.item_id
            WHERE cr.case_id = %s AND i.is_active = TRUE AND cr.weight > 0
            ORDER BY cr.weight DESC, i.rarity, i.name
            """,
            (case_id,),
        )
        rows = await cur.fetchall()
        total = sum(r["weight"] for r in rows) or 1
        out = []
        for row in rows:
            item = dict(row)
            item["chance"] = row["weight"] * 100 / total
            out.append(item)
        return out


@with_db_retry
async def set_case_active(case_id: int, active: bool) -> bool:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "UPDATE cases SET is_active = %s WHERE id = %s RETURNING id",
            (active, case_id),
        )
        return await cur.fetchone() is not None


@with_db_retry
async def open_case(user_id: int, case_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                SELECT c.*, k.code AS key_code, k.name AS key_name
                FROM cases c
                LEFT JOIN items k ON k.id = c.required_key_item_id
                WHERE c.id = %s AND c.is_active = TRUE
                """,
                (case_id,),
            )
            case = await cur.fetchone()
            if not case:
                return {"ok": False, "error": "case_not_found"}

            cur = await conn.execute(
                """
                SELECT cr.weight, i.*
                FROM case_rewards cr
                JOIN items i ON i.id = cr.item_id
                WHERE cr.case_id = %s AND i.is_active = TRUE AND cr.weight > 0
                """,
                (case_id,),
            )
            rewards = await cur.fetchall()
            if not rewards:
                return {"ok": False, "error": "empty_case", "case": case}

            if case.get("required_key_item_id"):
                cur = await conn.execute(
                    """
                    UPDATE user_inventory
                       SET quantity = quantity - 1, updated_at = NOW()
                     WHERE user_id = %s AND item_id = %s AND quantity > 0
                    RETURNING quantity
                    """,
                    (user_id, case["required_key_item_id"]),
                )
                if not await cur.fetchone():
                    return {
                        "ok": False,
                        "error": "no_key",
                        "balance": await _balance_conn(conn, user_id),
                        "case": case,
                    }

            balance_row = None
            if case["price"] > 0:
                cur = await conn.execute(
                    """
                    UPDATE users
                       SET zefirki = zefirki - %s
                     WHERE user_id = %s AND zefirki >= %s
                    RETURNING zefirki
                    """,
                    (case["price"], user_id, case["price"]),
                )
                balance_row = await cur.fetchone()
                if not balance_row:
                    if case.get("required_key_item_id"):
                        await _add_inventory(conn, user_id, case["required_key_item_id"], 1)
                    return {
                        "ok": False,
                        "error": "not_enough",
                        "balance": await _balance_conn(conn, user_id),
                        "case": case,
                    }

            total = sum(r["weight"] for r in rewards)
            pick = _rng.randint(1, total)
            acc = 0
            reward = rewards[-1]
            for candidate in rewards:
                acc += candidate["weight"]
                if pick <= acc:
                    reward = candidate
                    break

            await _add_inventory(conn, user_id, reward["id"], 1)
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (user_id, -case["price"], "case"),
            )
            await _log_event(
                conn,
                user_id,
                -case["price"],
                "case_open",
                item_id=reward["id"],
                meta={
                    "case_id": case_id,
                    "case": case["code"],
                    "required_key_item_id": case.get("required_key_item_id"),
                },
            )

            return {
                "ok": True,
                "case": case,
                "item": reward,
                "balance": balance_row["zefirki"] if balance_row else await _balance_conn(conn, user_id),
            }


@with_db_retry
async def create_listing(user_id: int, item_id: int, price: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM items WHERE id = %s AND is_active = TRUE", (item_id,))
            item = await cur.fetchone()
            if not item:
                return {"ok": False, "error": "item_not_found"}
            if not item["sellable"]:
                return {"ok": False, "error": "not_sellable", "item": item}

            min_price, max_price = price_limits_for(item)
            if price < min_price or price > max_price:
                return {
                    "ok": False,
                    "error": "bad_price",
                    "item": item,
                    "min_price": min_price,
                    "max_price": max_price,
                }

            cur = await conn.execute(
                """
                UPDATE user_inventory
                   SET quantity = quantity - 1, updated_at = NOW()
                 WHERE user_id = %s AND item_id = %s AND quantity > 0
                RETURNING quantity
                """,
                (user_id, item_id),
            )
            if not await cur.fetchone():
                return {"ok": False, "error": "no_item", "item": item}

            cur = await conn.execute(
                """
                INSERT INTO market_listings (seller_id, item_id, price)
                VALUES (%s, %s, %s)
                RETURNING *
                """,
                (user_id, item_id, price),
            )
            listing = await cur.fetchone()
            await _log_event(conn, user_id, 0, "market_list", item_id=item_id, listing_id=listing["id"], meta={"price": price})
            return {"ok": True, "listing": listing, "item": item}


@with_db_retry
async def list_market(
    rarity: str | None = None,
    category: str | None = None,
    limit: int = 10,
    offset: int = 0,
) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        params: list = []
        where = "ml.status = 'active' AND i.is_active = TRUE"
        if rarity:
            if rarity == "rare_plus":
                where += " AND i.rarity IN ('rare', 'epic', 'legendary')"
            else:
                where += " AND i.rarity = %s"
                params.append(rarity)
        if category and category != "all":
            if category == "rare":
                where += " AND i.rarity IN ('rare', 'epic', 'legendary')"
            else:
                where += " AND i.category = %s"
                params.append(category)
        params.extend([limit, offset])
        cur = await conn.execute(
            f"""
            SELECT ml.*, i.name, i.rarity, i.item_type, i.category, i.base_price, u.username, u.first_name
            FROM market_listings ml
            JOIN items i ON i.id = ml.item_id
            JOIN users u ON u.user_id = ml.seller_id
            WHERE {where}
            ORDER BY ml.created_at DESC
            LIMIT %s OFFSET %s
            """,
            tuple(params),
        )
        return await cur.fetchall()


@with_db_retry
async def get_suspicious_market_events(limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT ml.*, i.name, i.rarity, i.base_price
            FROM market_listings ml
            JOIN items i ON i.id = ml.item_id
            WHERE ml.status IN ('active', 'sold')
              AND ml.price >= GREATEST(i.base_price * 4, 500)
            ORDER BY ml.price DESC, ml.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return await cur.fetchall()


@with_db_retry
async def get_top_balances(limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT user_id, username, first_name, zefirki
            FROM users
            ORDER BY zefirki DESC
            LIMIT %s
            """,
            (limit,),
        )
        return await cur.fetchall()


@with_db_retry
async def get_top_market_sellers(limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT ml.seller_id AS user_id, u.username, u.first_name,
                   COUNT(*) AS sold_count, COALESCE(SUM(ml.price), 0) AS gross
            FROM market_listings ml
            JOIN users u ON u.user_id = ml.seller_id
            WHERE ml.status = 'sold'
            GROUP BY ml.seller_id, u.username, u.first_name
            ORDER BY gross DESC
            LIMIT %s
            """,
            (limit,),
        )
        return await cur.fetchall()


@with_db_retry
async def get_my_listings(user_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT ml.*, i.name, i.rarity
            FROM market_listings ml
            JOIN items i ON i.id = ml.item_id
            WHERE ml.seller_id = %s AND ml.status = 'active'
            ORDER BY ml.created_at DESC
            LIMIT 20
            """,
            (user_id,),
        )
        return await cur.fetchall()


@with_db_retry
async def get_market_listing(listing_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT ml.*, i.name, i.description, i.rarity, i.item_type, i.category, i.base_price,
                   u.username, u.first_name
            FROM market_listings ml
            JOIN items i ON i.id = ml.item_id
            JOIN users u ON u.user_id = ml.seller_id
            WHERE ml.id = %s AND i.is_active = TRUE
            """,
            (listing_id,),
        )
        return await cur.fetchone()


@with_db_retry
async def buy_listing(buyer_id: int, listing_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                SELECT ml.*, i.name, i.rarity, i.is_active
                FROM market_listings ml
                JOIN items i ON i.id = ml.item_id
                WHERE ml.id = %s
                FOR UPDATE
                """,
                (listing_id,),
            )
            listing = await cur.fetchone()
            if not listing or listing["status"] != "active":
                return {"ok": False, "error": "not_available"}
            if not listing.get("is_active", True):
                return {"ok": False, "error": "item_disabled", "listing": listing}
            if listing["seller_id"] == buyer_id:
                return {"ok": False, "error": "own_listing", "listing": listing}

            price = listing["price"]
            cur = await conn.execute(
                """
                UPDATE users
                   SET zefirki = zefirki - %s
                 WHERE user_id = %s AND zefirki >= %s
                RETURNING zefirki
                """,
                (price, buyer_id, price),
            )
            buyer_balance = await cur.fetchone()
            if not buyer_balance:
                return {"ok": False, "error": "not_enough", "balance": await _balance_conn(conn, buyer_id)}

            seller_income = price * (100 - config.market_commission_percent) // 100
            fee = price - seller_income
            await conn.execute(
                "UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s",
                (seller_income, listing["seller_id"]),
            )
            await _add_inventory(conn, buyer_id, listing["item_id"], 1)
            await conn.execute(
                """
                UPDATE market_listings
                   SET status = 'sold', buyer_id = %s, closed_at = NOW()
                 WHERE id = %s
                """,
                (buyer_id, listing_id),
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (buyer_id, -price, "market"),
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (listing["seller_id"], seller_income, "market"),
            )
            await _log_event(conn, buyer_id, -price, "market_buy", item_id=listing["item_id"], listing_id=listing_id)
            await _log_event(
                conn,
                listing["seller_id"],
                seller_income,
                "market_sell",
                item_id=listing["item_id"],
                listing_id=listing_id,
                meta={"fee": fee, "gross": price},
            )
            return {
                "ok": True,
                "listing": listing,
                "buyer_balance": buyer_balance["zefirki"],
                "seller_income": seller_income,
                "fee": fee,
            }


@with_db_retry
async def cancel_listing(user_id: int, listing_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM market_listings WHERE id = %s FOR UPDATE",
                (listing_id,),
            )
            listing = await cur.fetchone()
            if not listing or listing["seller_id"] != user_id or listing["status"] != "active":
                return {"ok": False}
            await conn.execute(
                "UPDATE market_listings SET status = 'cancelled', closed_at = NOW() WHERE id = %s",
                (listing_id,),
            )
            await _add_inventory(conn, user_id, listing["item_id"], 1)
            await _log_event(conn, user_id, 0, "market_cancel", item_id=listing["item_id"], listing_id=listing_id)
            return {"ok": True, "listing": listing}


@with_db_retry
async def use_inventory_item(user_id: int, item_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                SELECT ui.quantity, i.*
                FROM user_inventory ui
                JOIN items i ON i.id = ui.item_id
                WHERE ui.user_id = %s AND ui.item_id = %s
                FOR UPDATE
                """,
                (user_id, item_id),
            )
            item = await cur.fetchone()
            if not item or item["quantity"] <= 0:
                return {"ok": False, "error": "no_item"}
            if not item["usable"]:
                return {"ok": False, "error": "not_usable", "item": item}

            effect = ""
            effects = item.get("effect_json") or {}
            pet = None
            if item["item_type"] in ("pet_boost", "pet_consumable", "pet_toy"):
                cur = await conn.execute(
                    "SELECT * FROM pets WHERE owner_id = %s AND active = TRUE FOR UPDATE",
                    (user_id,),
                )
                pet = await cur.fetchone()
                if not pet:
                    return {"ok": False, "error": "no_pet", "item": item}

            await conn.execute(
                """
                UPDATE user_inventory
                   SET quantity = quantity - 1, updated_at = NOW()
                 WHERE user_id = %s AND item_id = %s
                """,
                (user_id, item_id),
            )

            if item["item_type"] == "ai_bonus":
                ai_bonus = int(effects.get("ai_bonus", 10))
                await conn.execute(
                    "UPDATE users SET ai_bonus = COALESCE(ai_bonus, 0) + %s WHERE user_id = %s",
                    (ai_bonus, user_id),
                )
                effect = f"+{ai_bonus} AI-запросов"
            elif item["item_type"] in ("pet_boost", "pet_consumable", "pet_toy"):
                await conn.execute(
                    """
                    UPDATE pets
                       SET hunger = LEAST(GREATEST(hunger + %s, 0), 100),
                           thirst = LEAST(GREATEST(thirst + %s, 0), 100),
                           cleanliness = LEAST(GREATEST(cleanliness + %s, 0), 100),
                           mood = LEAST(GREATEST(mood + %s, 0), 100),
                           energy = LEAST(GREATEST(energy + %s, 0), 100),
                           health = LEAST(GREATEST(health + %s, 0), 100),
                           affection = LEAST(GREATEST(affection + %s, 0), 100),
                            xp = xp + %s,
                            level = GREATEST(level, ((xp + %s) / 100) + 1),
                            updated_at = NOW()
                     WHERE id = %s
                    """,
                    (
                        int(effects.get("hunger", 0)),
                        int(effects.get("thirst", 0)),
                        int(effects.get("cleanliness", 0)),
                        int(effects.get("mood", 0)),
                        int(effects.get("energy", 0)),
                        int(effects.get("health", 0)),
                        int(effects.get("affection", 0)),
                        int(effects.get("xp", 0)),
                        int(effects.get("xp", 0)),
                        pet["id"],
                    ),
                )
                effect = "питомец отреагировал на предмет"
            elif item["item_type"] == "home_item":
                room = (effects.get("room") or "kitchen")
                if room == "all":
                    room = "playroom"
                cur = await conn.execute(
                    """
                    INSERT INTO pet_homes (user_id)
                    VALUES (%s)
                    ON CONFLICT (user_id) DO UPDATE SET updated_at = pet_homes.updated_at
                    RETURNING user_id
                    """,
                    (user_id,),
                )
                await cur.fetchone()
                cur = await conn.execute(
                    """
                    INSERT INTO pet_home_items (user_id, room, item_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, room, item_id) DO NOTHING
                    RETURNING item_id
                    """,
                    (user_id, room, item_id),
                )
                installed = await cur.fetchone()
                if not installed:
                    await _add_inventory(conn, user_id, item_id, 1)
                    return {"ok": False, "error": "already_installed", "item": item, "room": room}
                effect = f"предмет установлен в домик: {room}"
            else:
                effect = "предмет использован"

            await _log_event(conn, user_id, 0, "item_use", item_id=item_id, meta={"effect": effect})
            return {"ok": True, "item": item, "effect": effect}


@with_db_retry
async def list_shop_offers(category: str | None = None, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        rotation = await _ensure_shop_rotation(conn)
        params: list = []
        where = "so.is_active = TRUE AND i.is_active = TRUE"
        if category and category != "all":
            where += " AND i.category = %s"
            params.append(category)
        params.extend([rotation["key"], limit])
        cur = await conn.execute(
            f"""
            SELECT so.id AS offer_id, so.price AS offer_price, so.title, so.is_daily, i.*
            FROM shop_offers so
            JOIN items i ON i.id = so.item_id
            WHERE {where}
            ORDER BY md5(%s || ':' || so.id::text)
            LIMIT %s
            """,
            tuple(params),
        )
        return await cur.fetchall()


@with_db_retry
async def get_shop_offer(offer_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT so.id AS offer_id, so.price AS offer_price, so.title, so.is_daily, i.*
            FROM shop_offers so
            JOIN items i ON i.id = so.item_id
            WHERE so.id = %s AND so.is_active = TRUE AND i.is_active = TRUE
            """,
            (offer_id,),
        )
        return await cur.fetchone()


@with_db_retry
async def get_shop_rotation_status() -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        return await _ensure_shop_rotation(conn)


@with_db_retry
async def buy_shop_offer(user_id: int, offer_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                SELECT so.id AS offer_id, so.price AS offer_price, i.*
                FROM shop_offers so
                JOIN items i ON i.id = so.item_id
                WHERE so.id = %s AND so.is_active = TRUE AND i.is_active = TRUE
                FOR UPDATE
                """,
                (offer_id,),
            )
            offer = await cur.fetchone()
            if not offer:
                return {"ok": False, "error": "not_found"}
            price = offer["offer_price"]
            cur = await conn.execute(
                """
                UPDATE users
                   SET zefirki = zefirki - %s
                 WHERE user_id = %s AND zefirki >= %s
                RETURNING zefirki
                """,
                (price, user_id, price),
            )
            balance = await cur.fetchone()
            if not balance:
                return {"ok": False, "error": "not_enough", "balance": await _balance_conn(conn, user_id)}
            await _add_inventory(conn, user_id, offer["id"], 1)
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (user_id, -price, "shop"),
            )
            await _log_event(conn, user_id, -price, "shop_buy", item_id=offer["id"], meta={"offer_id": offer_id})
            return {"ok": True, "item": offer, "balance": balance["zefirki"]}


@with_db_retry
async def claim_daily_freebie(user_id: int) -> dict:
    claim_date = today_msk()
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                INSERT INTO daily_claims (user_id, claim_date, amount)
                VALUES (%s, %s, 0)
                ON CONFLICT (user_id, claim_date) DO NOTHING
                RETURNING user_id
                """,
                (user_id, claim_date),
            )
            if not await cur.fetchone():
                return {"ok": False, "error": "already_claimed"}

            amount = _rng.randint(15, 45)
            cur = await conn.execute(
                """
                SELECT * FROM items
                WHERE is_active = TRUE AND is_shop_item = TRUE AND rarity IN ('common', 'uncommon')
                ORDER BY random()
                LIMIT 1
                """
            )
            item = await cur.fetchone()
            await conn.execute("UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s", (amount, user_id))
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (user_id, amount, "daily"),
            )
            if item:
                await _add_inventory(conn, user_id, item["id"], 1)
            await conn.execute(
                "UPDATE daily_claims SET amount = %s, item_id = %s WHERE user_id = %s AND claim_date = %s",
                (amount, item["id"] if item else None, user_id, claim_date),
            )
            await _log_event(conn, user_id, amount, "daily_claim", item_id=item["id"] if item else None)
            logger.info("🎁 Daily получен: user_id=%s, date_msk=%s, amount=%s", user_id, claim_date, amount)
            return {"ok": True, "amount": amount, "item": item}


@with_db_retry
async def get_daily_freebie_status(user_id: int) -> dict:
    claim_date = today_msk()
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT dc.*, i.name, i.rarity, i.item_type, i.category
            FROM daily_claims dc
            LEFT JOIN items i ON i.id = dc.item_id
            WHERE dc.user_id = %s AND dc.claim_date = %s
            """,
            (user_id, claim_date),
        )
        claim = await cur.fetchone()
        return {
            "available": claim is None,
            "claim": claim,
            "next_claim_at": next_msk_midnight(),
        }


@with_db_retry
async def set_item_active(item_id: int, active: bool) -> bool:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                "UPDATE items SET is_active = %s WHERE id = %s RETURNING id",
                (active, item_id),
            )
            if not await cur.fetchone():
                return False
            if not active:
                cur = await conn.execute(
                    """
                    UPDATE market_listings
                       SET status = 'cancelled', closed_at = NOW()
                     WHERE item_id = %s AND status = 'active'
                    RETURNING id, seller_id
                    """,
                    (item_id,),
                )
                for listing in await cur.fetchall():
                    await _add_inventory(conn, listing["seller_id"], item_id, 1)
                    await _log_event(
                        conn,
                        listing["seller_id"],
                        0,
                        "market_cancel_item_disabled",
                        item_id=item_id,
                        listing_id=listing["id"],
                    )
        return True


@with_db_retry
async def update_item_shop_price(item_id: int, price: int | None) -> bool:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                UPDATE items
                   SET shop_price = %s,
                       is_shop_item = %s
                 WHERE id = %s
                RETURNING id
                """,
                (price, price is not None and price > 0, item_id),
            )
            if not await cur.fetchone():
                return False
            if price is not None and price > 0:
                await conn.execute(
                    """
                    INSERT INTO shop_offers (item_id, price, title, is_daily, is_active)
                    SELECT id, %s, name, TRUE, TRUE FROM items WHERE id = %s
                    ON CONFLICT (item_id) WHERE is_daily = TRUE DO UPDATE
                        SET price = EXCLUDED.price,
                            title = EXCLUDED.title,
                            is_active = TRUE
                    """,
                    (price, item_id),
                )
            else:
                await conn.execute(
                    "UPDATE shop_offers SET is_active = FALSE WHERE item_id = %s AND is_daily = TRUE",
                    (item_id,),
                )
        return True


@with_db_retry
async def get_recent_economy_events(user_id: int | None = None, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        if user_id:
            cur = await conn.execute(
                """
                SELECT ee.*, i.name AS item_name
                FROM economy_events ee
                LEFT JOIN items i ON i.id = ee.item_id
                WHERE ee.user_id = %s
                ORDER BY ee.created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
        else:
            cur = await conn.execute(
                """
                SELECT ee.*, i.name AS item_name
                FROM economy_events ee
                LEFT JOIN items i ON i.id = ee.item_id
                ORDER BY ee.created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
        return await cur.fetchall()


@with_db_retry
async def get_economy_stats() -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        stats = {}
        for key, sql in {
            "items": "SELECT COUNT(*) AS cnt FROM items",
            "inventory": "SELECT COALESCE(SUM(quantity), 0) AS cnt FROM user_inventory",
            "shop_offers": "SELECT COUNT(*) AS cnt FROM shop_offers WHERE is_active = TRUE",
            "active_listings": "SELECT COUNT(*) AS cnt FROM market_listings WHERE status = 'active'",
            "sold_listings": "SELECT COUNT(*) AS cnt FROM market_listings WHERE status = 'sold'",
            "events": "SELECT COUNT(*) AS cnt FROM economy_events",
        }.items():
            cur = await conn.execute(sql)
            stats[key] = (await cur.fetchone())["cnt"]
        return stats
