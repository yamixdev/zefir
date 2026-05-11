from __future__ import annotations

from datetime import timedelta
from math import pow

from bot.config import config
from bot.db import get_pool, with_db_retry
from bot.services.time_service import now_msk


async def _active_season(conn) -> dict:
    cur = await conn.execute(
        "SELECT * FROM rating_seasons WHERE status = 'active' ORDER BY starts_at DESC LIMIT 1"
    )
    season = await cur.fetchone()
    if season:
        return season
    start = now_msk()
    end = start + timedelta(days=config.ranked_season_days)
    cur = await conn.execute(
        """
        INSERT INTO rating_seasons (code, starts_at, ends_at, status)
        VALUES (%s, %s, %s, 'active')
        RETURNING *
        """,
        (f"season-{start:%Y%m%d}", start, end),
    )
    return await cur.fetchone()


async def _ensure_rating(conn, season_id: int, user_id: int) -> dict:
    cur = await conn.execute(
        """
        INSERT INTO user_ratings (season_id, user_id, elo)
        VALUES (%s, %s, %s)
        ON CONFLICT (season_id, user_id) DO NOTHING
        RETURNING *
        """,
        (season_id, user_id, config.ranked_start_elo),
    )
    row = await cur.fetchone()
    if row:
        return row
    cur = await conn.execute(
        "SELECT * FROM user_ratings WHERE season_id = %s AND user_id = %s",
        (season_id, user_id),
    )
    return await cur.fetchone()


def _elo_delta(elo_a: int, elo_b: int, score_a: float) -> tuple[int, int]:
    expected_a = 1 / (1 + pow(10, (elo_b - elo_a) / 400))
    expected_b = 1 - expected_a
    new_a = round(elo_a + config.ranked_k_factor * (score_a - expected_a))
    new_b = round(elo_b + config.ranked_k_factor * ((1 - score_a) - expected_b))
    return max(100, new_a), max(100, new_b)


@with_db_retry
async def apply_ranked_result(
    session_id: str,
    game_type: str,
    user_a: int,
    user_b: int,
    winner_id: int | None,
    is_draw: bool = False,
) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            season = await _active_season(conn)
            existing = await conn.execute(
                "SELECT * FROM ranked_game_results WHERE session_id = %s",
                (session_id,),
            )
            found = await existing.fetchone()
            if found:
                return {"ok": True, "duplicate": True, "season": season}

            rating_a = await _ensure_rating(conn, season["id"], user_a)
            rating_b = await _ensure_rating(conn, season["id"], user_b)

            if is_draw:
                score_a = 0.5
            else:
                score_a = 1.0 if winner_id == user_a else 0.0
            new_a, new_b = _elo_delta(rating_a["elo"], rating_b["elo"], score_a)

            await conn.execute(
                """
                UPDATE user_ratings
                   SET elo = %s,
                       wins = wins + %s,
                       losses = losses + %s,
                       draws = draws + %s,
                       games = games + 1,
                       updated_at = NOW()
                 WHERE season_id = %s AND user_id = %s
                """,
                (
                    new_a,
                    0 if is_draw else int(winner_id == user_a),
                    0 if is_draw else int(winner_id == user_b),
                    int(is_draw),
                    season["id"],
                    user_a,
                ),
            )
            await conn.execute(
                """
                UPDATE user_ratings
                   SET elo = %s,
                       wins = wins + %s,
                       losses = losses + %s,
                       draws = draws + %s,
                       games = games + 1,
                       updated_at = NOW()
                 WHERE season_id = %s AND user_id = %s
                """,
                (
                    new_b,
                    0 if is_draw else int(winner_id == user_b),
                    0 if is_draw else int(winner_id == user_a),
                    int(is_draw),
                    season["id"],
                    user_b,
                ),
            )
            await conn.execute(
                """
                INSERT INTO ranked_game_results
                    (season_id, session_id, game_type, user_a, user_b, winner_id, is_draw, old_a, old_b, new_a, new_b)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    season["id"],
                    session_id,
                    game_type,
                    user_a,
                    user_b,
                    winner_id,
                    is_draw,
                    rating_a["elo"],
                    rating_b["elo"],
                    new_a,
                    new_b,
                ),
            )
            return {
                "ok": True,
                "season": season,
                "old_a": rating_a["elo"],
                "old_b": rating_b["elo"],
                "new_a": new_a,
                "new_b": new_b,
            }


@with_db_retry
async def apply_ranked_placements(session_id: str, game_type: str, placements: list[dict]) -> dict:
    """Apply ELO for a multiplayer ranked result through pairwise comparisons."""
    clean = [
        {"user_id": int(p["user_id"]), "place": int(p["place"])}
        for p in placements
        if p.get("user_id") is not None and p.get("place") is not None
    ]
    if len(clean) < 2:
        return {"ok": False, "error": "not_enough_players"}

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            season = await _active_season(conn)
            cur = await conn.execute(
                "SELECT 1 FROM ranked_game_results WHERE session_id = %s LIMIT 1",
                (session_id,),
            )
            if await cur.fetchone():
                return {"ok": True, "duplicate": True, "season": season}

            ratings = {
                row["user_id"]: row
                for row in [
                    await _ensure_rating(conn, season["id"], p["user_id"])
                    for p in clean
                ]
            }
            deltas = {p["user_id"]: 0 for p in clean}
            pairs = []

            for i, a in enumerate(clean):
                for b in clean[i + 1:]:
                    if a["place"] == b["place"]:
                        score_a = 0.5
                        winner_id = None
                        is_draw = True
                    elif a["place"] < b["place"]:
                        score_a = 1.0
                        winner_id = a["user_id"]
                        is_draw = False
                    else:
                        score_a = 0.0
                        winner_id = b["user_id"]
                        is_draw = False

                    old_a = ratings[a["user_id"]]["elo"]
                    old_b = ratings[b["user_id"]]["elo"]
                    new_a, new_b = _elo_delta(old_a, old_b, score_a)
                    deltas[a["user_id"]] += new_a - old_a
                    deltas[b["user_id"]] += new_b - old_b
                    pairs.append((a["user_id"], b["user_id"], winner_id, is_draw, old_a, old_b, new_a, new_b))

            top_place = min(p["place"] for p in clean)
            top_count = sum(1 for p in clean if p["place"] == top_place)
            for player in clean:
                uid = player["user_id"]
                old = ratings[uid]["elo"]
                new_elo = max(100, old + deltas[uid])
                game_win = int(player["place"] == top_place and top_count == 1)
                game_draw = int(player["place"] == top_place and top_count > 1)
                game_loss = int(player["place"] != top_place)
                await conn.execute(
                    """
                    UPDATE user_ratings
                       SET elo = %s,
                           wins = wins + %s,
                           losses = losses + %s,
                           draws = draws + %s,
                           games = games + 1,
                           updated_at = NOW()
                     WHERE season_id = %s AND user_id = %s
                    """,
                    (new_elo, game_win, game_loss, game_draw, season["id"], uid),
                )

            for user_a, user_b, winner_id, is_draw, old_a, old_b, new_a, new_b in pairs:
                await conn.execute(
                    """
                    INSERT INTO ranked_game_results
                        (season_id, session_id, game_type, user_a, user_b, winner_id, is_draw, old_a, old_b, new_a, new_b)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (session_id, user_a, user_b) DO NOTHING
                    """,
                    (
                        season["id"],
                        session_id,
                        game_type,
                        user_a,
                        user_b,
                        winner_id,
                        is_draw,
                        old_a,
                        old_b,
                        new_a,
                        new_b,
                    ),
                )
            return {"ok": True, "season": season}


@with_db_retry
async def get_ranked_leaderboard(limit: int = 10) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        season = await _active_season(conn)
        cur = await conn.execute(
            """
            SELECT ur.*, u.username, u.first_name,
                   ROW_NUMBER() OVER (ORDER BY ur.elo DESC, ur.games DESC, ur.updated_at ASC) AS place
            FROM user_ratings ur
            JOIN users u ON u.user_id = ur.user_id
            WHERE ur.season_id = %s
            ORDER BY ur.elo DESC, ur.games DESC, ur.updated_at ASC
            LIMIT %s
            """,
            (season["id"], limit),
        )
        return {"season": season, "rows": await cur.fetchall()}


def season_rewards_available(season: dict) -> bool:
    return bool(season.get("finalized_at") or season["ends_at"] <= now_msk())


@with_db_retry
async def finalize_active_season(admin_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            season = await _active_season(conn)
            cur = await conn.execute(
                """
                UPDATE rating_seasons
                   SET finalized_at = COALESCE(finalized_at, NOW()),
                       finalized_by = COALESCE(finalized_by, %s),
                       status = CASE WHEN ends_at <= NOW() THEN 'finished' ELSE status END
                 WHERE id = %s
                 RETURNING *
                """,
                (admin_id, season["id"]),
            )
            return {"ok": True, "season": await cur.fetchone()}


def reward_for_place(place: int, elo: int, games: int) -> tuple[int, str | None]:
    if place == 1:
        return 1000, "season_crown_legend"
    if place <= 3:
        return 600, "season_medal_epic"
    if place <= 10:
        return 300, "season_badge_rare"
    base = max(25, min(250, 25 + (elo - 900) // 4 + games * 3))
    return base, None


@with_db_retry
async def claim_season_reward(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                SELECT *
                FROM rating_seasons
                WHERE ends_at <= NOW() OR finalized_at IS NOT NULL
                ORDER BY COALESCE(finalized_at, ends_at) DESC
                LIMIT 1
                """
            )
            season = await cur.fetchone()
            if not season:
                return {"ok": False, "error": "no_finished_season"}
            if not season_rewards_available(season):
                return {"ok": False, "error": "season_active"}

            cur = await conn.execute(
                """
                SELECT ranked.*
                FROM (
                    SELECT ur.*,
                           ROW_NUMBER() OVER (ORDER BY ur.elo DESC, ur.games DESC, ur.updated_at ASC) AS place
                    FROM user_ratings ur
                    WHERE ur.season_id = %s
                ) ranked
                WHERE ranked.user_id = %s
                """,
                (season["id"], user_id),
            )
            rating = await cur.fetchone()
            if not rating or rating["games"] < config.ranked_min_reward_games:
                return {"ok": False, "error": "not_eligible"}
            if rating["reward_claimed"]:
                return {"ok": False, "error": "already_claimed"}

            cur = await conn.execute(
                """
                UPDATE user_ratings
                   SET reward_claimed = TRUE, updated_at = NOW()
                 WHERE season_id = %s AND user_id = %s AND reward_claimed = FALSE
                RETURNING reward_claimed
                """,
                (season["id"], user_id),
            )
            if not await cur.fetchone():
                return {"ok": False, "error": "already_claimed"}

            amount, item_code = reward_for_place(rating["place"], rating["elo"], rating["games"])
            item = None
            if item_code:
                cur = await conn.execute("SELECT * FROM items WHERE code = %s", (item_code,))
                item = await cur.fetchone()
                if item:
                    await conn.execute(
                        """
                        INSERT INTO user_inventory (user_id, item_id, quantity)
                        VALUES (%s, %s, 1)
                        ON CONFLICT (user_id, item_id) DO UPDATE
                            SET quantity = user_inventory.quantity + 1,
                                updated_at = NOW()
                        """,
                        (user_id, item["id"]),
                    )
            await conn.execute(
                "UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s",
                (amount, user_id),
            )
            await conn.execute(
                "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
                (user_id, amount, "ranked_reward"),
            )
            await conn.execute(
                """
                INSERT INTO economy_events (user_id, amount, reason, item_id, meta)
                VALUES (%s, %s, 'ranked_reward', %s, %s::jsonb)
                """,
                (
                    user_id,
                    amount,
                    item["id"] if item else None,
                    f'{{"season_id": {season["id"]}, "place": {rating["place"]}}}',
                ),
            )
            return {"ok": True, "amount": amount, "item": item, "rating": rating, "season": season}
