import random
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from bot.config import config
from bot.db import get_pool, with_db_retry
from bot.services.economy_service import _add_inventory, _log_event
from bot.services.game_logic import mines_cashout, mines_multiplier
from bot.services.time_service import today_msk


MS_SIZE = 4
MS_MINES = 3
MS_MINES_MIN = 2
MS_MINES_MAX = 10
TTT_WINS = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)

_rng = random.SystemRandom()


def _game_id(length: int = 8) -> str:
    return uuid.uuid4().hex[:length]


async def _spend_stake(conn, user_id: int, stake: int, game_id: str) -> bool:
    if stake <= 0:
        return True
    cur = await conn.execute(
        """
        UPDATE users
           SET zefirki = zefirki - %s
         WHERE user_id = %s AND zefirki >= %s
        RETURNING zefirki
        """,
        (stake, user_id, stake),
    )
    if not await cur.fetchone():
        return False
    await conn.execute(
        "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
        (user_id, -stake, "game_stake"),
    )
    await _log_event(conn, user_id, -stake, "game_stake", game_id=game_id)
    return True


async def _grant_zefirki(conn, user_id: int, amount: int, reason: str, game_id: str) -> None:
    if amount <= 0:
        return
    await conn.execute(
        "UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s",
        (amount, user_id),
    )
    await conn.execute(
        "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
        (user_id, amount, reason),
    )
    await _log_event(conn, user_id, amount, reason, game_id=game_id)


async def _balance(conn, user_id: int) -> int:
    cur = await conn.execute("SELECT zefirki FROM users WHERE user_id = %s", (user_id,))
    row = await cur.fetchone()
    return int(row["zefirki"]) if row else 0


async def _settlement(conn, user_id: int, result: str, stake: int, payout: int) -> dict:
    return {
        "user_id": user_id,
        "result": result,
        "stake": stake,
        "payout": payout,
        "delta": payout - stake,
        "balance_after": await _balance(conn, user_id),
    }


async def _remaining_pve_profit_cap(conn, user_id: int) -> int:
    reward_date = today_msk()
    cur = await conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS won
        FROM game_reward_logs
        WHERE user_id = %s AND COALESCE(reward_date_msk, reward_date) = %s
        """,
        (user_id, reward_date),
    )
    won = (await cur.fetchone())["won"]
    return max(config.game_daily_win_limit - won, 0)


async def _record_pve_profit(conn, user_id: int, amount: int, game_id: str) -> None:
    if amount <= 0:
        return
    await conn.execute(
        "INSERT INTO game_reward_logs (user_id, amount, reward_date, reward_date_msk, game_id) VALUES (%s, %s, %s, %s, %s)",
        (user_id, amount, today_msk(), today_msk(), game_id),
    )


def _normalize_mines_count(stake: int, mines_count: int | None) -> int:
    if stake <= 0:
        return MS_MINES
    return max(MS_MINES_MIN, min(int(mines_count or MS_MINES), MS_MINES_MAX))


def minesweeper_summary(game: dict, state: dict | None = None) -> dict:
    state = state or game.get("state") or {}
    stake = int(game.get("stake") or 0)
    mines_count = int(state.get("mines_count") or len(state.get("mines") or []) or MS_MINES)
    opened = len(state.get("revealed") or [])
    current_multiplier = mines_multiplier(MS_SIZE, mines_count, opened, config.mines_rtp) if stake > 0 and opened > 0 else 0
    current_payout = mines_cashout(stake, current_multiplier)
    safe_total = MS_SIZE * MS_SIZE - mines_count
    if opened < safe_total:
        next_multiplier = mines_multiplier(MS_SIZE, mines_count, opened + 1, config.mines_rtp) if stake > 0 else 0
        next_payout = mines_cashout(stake, next_multiplier)
    else:
        next_multiplier = current_multiplier
        next_payout = current_payout
    return {
        "stake": stake,
        "mines_count": mines_count,
        "opened": opened,
        "safe_total": safe_total,
        "current_multiplier": current_multiplier,
        "current_payout": current_payout,
        "current_profit": max(current_payout - stake, 0),
        "next_multiplier": next_multiplier,
        "next_payout": next_payout,
        "next_profit": max(next_payout - stake, 0),
    }


async def _maybe_game_key_drop(conn, user_id: int, game_id: str, stake: int) -> dict | None:
    if stake <= 0:
        return None
    roll = _rng.randint(1, 100)
    key_code = None
    if roll <= 5:
        key_code = "gold_key"
    elif roll <= 12:
        key_code = "silver_key"
    elif roll <= 22:
        key_code = "bronze_key"
    if not key_code:
        return None
    cur = await conn.execute(
        "SELECT * FROM items WHERE code = %s AND is_active = TRUE",
        (key_code,),
    )
    item = await cur.fetchone()
    if item:
        await _add_inventory(conn, user_id, item["id"], 1)
        await _log_event(conn, user_id, 0, "game_key_drop", item_id=item["id"], game_id=game_id)
    return item


@with_db_retry
async def start_minesweeper(user_id: int, stake: int = 0, mines_count: int | None = None) -> dict:
    stake = max(0, min(int(stake), 100))
    mines_count = _normalize_mines_count(stake, mines_count)
    game_id = _game_id()
    cells = list(range(MS_SIZE * MS_SIZE))
    mines = sorted(_rng.sample(cells, mines_count))
    state = {"mines": mines, "mines_count": mines_count, "revealed": []}

    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            if not await _spend_stake(conn, user_id, stake, game_id):
                return {"ok": False, "error": "not_enough"}
            cur = await conn.execute(
                """
                INSERT INTO pve_games (id, user_id, game_type, stake, state)
                VALUES (%s, %s, 'minesweeper', %s, %s)
                RETURNING *
                """,
                (game_id, user_id, stake, Jsonb(state)),
            )
            return {"ok": True, "game": await cur.fetchone()}


@with_db_retry
async def play_dice(user_id: int, stake: int = 0) -> dict:
    stake = max(0, min(int(stake), 100))
    game_id = _game_id()
    player = _rng.randint(1, 6)
    bot = _rng.randint(1, 6)
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            if not await _spend_stake(conn, user_id, stake, game_id):
                return {"ok": False, "error": "not_enough"}
            status = "draw" if player == bot else "won" if player > bot else "lost"
            payout = 0
            profit = 0
            if status == "draw" and stake > 0:
                payout = stake
                await _grant_zefirki(conn, user_id, payout, "game_refund", game_id)
            elif status == "won":
                cap = await _remaining_pve_profit_cap(conn, user_id)
                profit = min(stake, cap) if stake > 0 else 0
                payout = stake + profit if stake else profit
                if payout > 0:
                    await _grant_zefirki(conn, user_id, payout, "game_win", game_id)
                await _record_pve_profit(conn, user_id, profit, game_id)
            item = await _maybe_game_key_drop(conn, user_id, game_id, stake) if status == "won" else None
            await conn.execute(
                """
                INSERT INTO pve_games (id, user_id, game_type, stake, status, state)
                VALUES (%s, %s, 'dice', %s, %s, %s)
                """,
                (game_id, user_id, stake, status, Jsonb({"player": player, "bot": bot})),
            )
            return {
                "ok": True,
                "game_id": game_id,
                "status": status,
                "player": player,
                "bot": bot,
                "payout": payout,
                "profit": profit,
                "delta": payout - stake,
                "balance": await _balance(conn, user_id),
                "item": item,
            }


@with_db_retry
async def play_guess_number(user_id: int, guess: int, stake: int = 0) -> dict:
    stake = max(0, min(int(stake), 100))
    guess = max(1, min(int(guess), 5))
    secret = _rng.randint(1, 5)
    game_id = _game_id()
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            if not await _spend_stake(conn, user_id, stake, game_id):
                return {"ok": False, "error": "not_enough"}
            status = "won" if guess == secret else "lost"
            payout = 0
            profit = 0
            if status == "won":
                cap = await _remaining_pve_profit_cap(conn, user_id)
                profit = min(stake * 3, cap) if stake > 0 else 0
                payout = stake + profit if stake else profit
                if payout > 0:
                    await _grant_zefirki(conn, user_id, payout, "game_win", game_id)
                await _record_pve_profit(conn, user_id, profit, game_id)
            item = await _maybe_game_key_drop(conn, user_id, game_id, stake) if status == "won" else None
            await conn.execute(
                """
                INSERT INTO pve_games (id, user_id, game_type, stake, status, state)
                VALUES (%s, %s, 'guess', %s, %s, %s)
                """,
                (game_id, user_id, stake, status, Jsonb({"guess": guess, "secret": secret})),
            )
            return {
                "ok": True,
                "game_id": game_id,
                "status": status,
                "guess": guess,
                "secret": secret,
                "payout": payout,
                "profit": profit,
                "delta": payout - stake,
                "balance": await _balance(conn, user_id),
                "item": item,
            }


def _adjacent_mines(index: int, mines: list[int]) -> int:
    row, col = divmod(index, MS_SIZE)
    count = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if 0 <= nr < MS_SIZE and 0 <= nc < MS_SIZE and nr * MS_SIZE + nc in mines:
                count += 1
    return count


@with_db_retry
async def open_minesweeper_cell(user_id: int, game_id: str, index: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                "SELECT * FROM pve_games WHERE id = %s FOR UPDATE",
                (game_id,),
            )
            game = await cur.fetchone()
            if not game or game["user_id"] != user_id or game["status"] != "active":
                return {"ok": False, "error": "not_active"}
            if index < 0 or index >= MS_SIZE * MS_SIZE:
                return {"ok": False, "error": "bad_cell"}

            state = game["state"]
            mines = list(state["mines"])
            mines_count = int(state.get("mines_count") or len(mines) or MS_MINES)
            revealed = set(state.get("revealed") or [])
            if index in revealed:
                return {"ok": True, "game": game, "state": state, "repeat": True}

            if index in mines:
                state["revealed"] = sorted(revealed | {index})
                await conn.execute(
                    "UPDATE pve_games SET status = 'lost', state = %s, updated_at = NOW() WHERE id = %s",
                    (Jsonb(state), game_id),
                )
                return {"ok": True, "status": "lost", "game": game, "state": state, "payout": 0, "delta": -game["stake"], "balance": await _balance(conn, user_id), "summary": minesweeper_summary(game, state)}

            revealed.add(index)
            state["revealed"] = sorted(revealed)
            safe_total = MS_SIZE * MS_SIZE - mines_count
            if len(revealed) >= safe_total:
                cap = await _remaining_pve_profit_cap(conn, user_id)
                summary = minesweeper_summary(game, state)
                raw_profit = summary["current_profit"]
                profit = min(raw_profit, cap) if game["stake"] > 0 else 0
                payout = game["stake"] + profit if game["stake"] else profit
                if payout > 0:
                    await _grant_zefirki(conn, user_id, payout, "game_win", game_id)
                await _record_pve_profit(conn, user_id, profit, game_id)
                item = await _maybe_game_key_drop(conn, user_id, game_id, game["stake"])
                if item is None and game["stake"] > 0 and _rng.randint(1, 100) <= 12:
                    cur = await conn.execute(
                        """
                        SELECT * FROM items
                        WHERE is_active = TRUE AND item_type IN ('game_ticket', 'collectible')
                        ORDER BY random()
                        LIMIT 1
                        """
                    )
                    item = await cur.fetchone()
                    if item:
                        await _add_inventory(conn, user_id, item["id"], 1)
                        await _log_event(conn, user_id, 0, "game_item", item_id=item["id"], game_id=game_id)
                await conn.execute(
                    "UPDATE pve_games SET status = 'won', state = %s, updated_at = NOW() WHERE id = %s",
                    (Jsonb(state), game_id),
                )
                return {
                    "ok": True,
                    "status": "won",
                    "game": game,
                    "state": state,
                    "payout": payout,
                    "profit": profit,
                    "delta": payout - game["stake"],
                    "balance": await _balance(conn, user_id),
                    "item": item,
                    "summary": minesweeper_summary(game, state),
                }

            await conn.execute(
                "UPDATE pve_games SET state = %s, updated_at = NOW() WHERE id = %s",
                (Jsonb(state), game_id),
            )
            cur = await conn.execute("SELECT * FROM pve_games WHERE id = %s", (game_id,))
            updated = await cur.fetchone()
            return {"ok": True, "status": "active", "game": updated, "state": state, "summary": minesweeper_summary(updated, state), "balance": await _balance(conn, user_id)}


@with_db_retry
async def cashout_minesweeper(user_id: int, game_id: str, close_only: bool = False) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM pve_games WHERE id = %s FOR UPDATE", (game_id,))
            game = await cur.fetchone()
            if not game or game["user_id"] != user_id or game["status"] != "active":
                return {"ok": False, "error": "not_active"}
            state = dict(game["state"] or {})
            summary = minesweeper_summary(game, state)
            stake = int(game["stake"] or 0)
            opened = int(summary["opened"])
            status = "cancelled"
            payout = 0
            profit = 0
            result = "cancelled"
            if stake > 0 and opened == 0:
                payout = stake
                result = "refund"
                await _grant_zefirki(conn, user_id, payout, "game_refund", game_id)
            elif stake > 0 and opened > 0:
                cap = await _remaining_pve_profit_cap(conn, user_id)
                profit = min(summary["current_profit"], cap)
                payout = stake + profit
                status = "cashed_out"
                result = "cashout"
                await _grant_zefirki(conn, user_id, payout, "game_win" if profit else "game_refund", game_id)
                await _record_pve_profit(conn, user_id, profit, game_id)
            state["cashout"] = {
                "result": result,
                "payout": payout,
                "profit": profit,
                "delta": payout - stake,
            }
            await conn.execute(
                "UPDATE pve_games SET status = %s, state = %s, updated_at = NOW() WHERE id = %s",
                (status, Jsonb(state), game_id),
            )
            cur = await conn.execute("SELECT * FROM pve_games WHERE id = %s", (game_id,))
            updated = await cur.fetchone()
            return {
                "ok": True,
                "status": status,
                "result": result,
                "game": updated,
                "state": state,
                "payout": payout,
                "profit": profit,
                "delta": payout - stake,
                "balance": await _balance(conn, user_id),
                "summary": summary,
                "closed": close_only,
            }


def minesweeper_cell_text(index: int, state: dict, reveal_all: bool = False) -> str:
    mines = list(state.get("mines") or [])
    revealed = set(state.get("revealed") or [])
    if index in mines and reveal_all:
        return "💥"
    if index not in revealed:
        return "▫️"
    count = _adjacent_mines(index, mines)
    return "0️⃣" if count == 0 else f"{count}️⃣"


@with_db_retry
async def create_ttt_room(user_id: int, stake: int = 0) -> dict:
    stake = max(0, min(int(stake), 500))
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            for _ in range(5):
                room_id = _game_id()
                cur = await conn.execute("SELECT 1 FROM game_rooms WHERE id = %s", (room_id,))
                if not await cur.fetchone():
                    break
            else:
                return {"ok": False, "error": "id_failed"}

            if not await _spend_stake(conn, user_id, stake, room_id):
                return {"ok": False, "error": "not_enough"}
            cur = await conn.execute(
                """
                INSERT INTO game_rooms (id, game_type, creator_id, stake, turn_user_id, expires_at)
                VALUES (%s, 'ttt', %s, %s, %s, NOW() + make_interval(mins => %s))
                RETURNING *
                """,
                (room_id, user_id, stake, user_id, config.stale_game_timeout_minutes),
            )
            return {"ok": True, "room": await cur.fetchone()}


@with_db_retry
async def list_waiting_ttt_rooms(limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT gr.*, u.username, u.first_name
            FROM game_rooms gr
            JOIN users u ON u.user_id = gr.creator_id
            WHERE gr.game_type = 'ttt' AND gr.status = 'waiting'
              AND COALESCE(gr.expires_at, gr.updated_at + make_interval(mins => %s)) > NOW()
            ORDER BY gr.created_at DESC
            LIMIT %s
            """,
            (config.stale_game_timeout_minutes, limit),
        )
        return await cur.fetchall()


@with_db_retry
async def list_user_active_games(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT * FROM pve_games
            WHERE user_id = %s AND status = 'active' AND game_type <> 'minesweeper'
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (user_id,),
        )
        pve = await cur.fetchall()
        cur = await conn.execute(
            """
            SELECT * FROM game_rooms
            WHERE status IN ('waiting', 'active') AND (creator_id = %s OR opponent_id = %s)
              AND COALESCE(expires_at, updated_at + make_interval(mins => %s)) > NOW()
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (user_id, user_id, config.stale_game_timeout_minutes),
        )
        rooms = await cur.fetchall()
        return {"pve": pve, "rooms": rooms}


@with_db_retry
async def set_ttt_message(room_id: str, user_id: int, chat_id: int, message_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT creator_id, opponent_id FROM game_rooms WHERE id = %s",
            (room_id,),
        )
        room = await cur.fetchone()
        if not room:
            return None
        if user_id == room["creator_id"]:
            cur = await conn.execute(
                """
                UPDATE game_rooms
                   SET creator_chat_id = %s,
                       creator_msg_id = %s
                 WHERE id = %s
                 RETURNING *
                """,
                (chat_id, message_id, room_id),
            )
        elif user_id == room["opponent_id"]:
            cur = await conn.execute(
                """
                UPDATE game_rooms
                   SET opponent_chat_id = %s,
                       opponent_msg_id = %s
                 WHERE id = %s
                 RETURNING *
                """,
                (chat_id, message_id, room_id),
            )
        else:
            return None
        return await cur.fetchone()


@with_db_retry
async def join_ttt_room(user_id: int, room_id: str) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_rooms WHERE id = %s FOR UPDATE", (room_id,))
            room = await cur.fetchone()
            if not room:
                return {"ok": False, "error": "not_available"}
            if room["status"] in ("waiting", "active") and _room_is_expired(room):
                expired = await _expire_ttt_room(conn, room)
                return {"ok": False, "error": "expired", "room": expired}
            if user_id in (room["creator_id"], room["opponent_id"]) and room["status"] in ("waiting", "active"):
                return {"ok": True, "room": room, "already_in_room": True}
            if room["status"] != "waiting":
                return {"ok": False, "error": "not_available"}
            if room["creator_id"] == user_id:
                return {"ok": True, "room": room, "already_in_room": True}
            if not await _spend_stake(conn, user_id, room["stake"], room_id):
                return {"ok": False, "error": "not_enough", "room": room}
            cur = await conn.execute(
                """
                UPDATE game_rooms
                   SET opponent_id = %s,
                       status = 'active',
                       updated_at = NOW(),
                       expires_at = NOW() + make_interval(mins => %s)
                 WHERE id = %s
                RETURNING *
                """,
                (user_id, config.stale_game_timeout_minutes, room_id),
            )
            return {"ok": True, "room": await cur.fetchone()}


def _ttt_winner(board: str) -> str | None:
    for combo in TTT_WINS:
        values = [board[i] for i in combo]
        if values[0] != "." and values.count(values[0]) == 3:
            return values[0]
    return None


def _room_is_expired(room: dict) -> bool:
    now = datetime.now(timezone.utc)
    expires_at = room.get("expires_at")
    if expires_at:
        return expires_at <= now
    return bool(room.get("updated_at") and now - room["updated_at"] >= timedelta(minutes=config.stale_game_timeout_minutes))


async def _finish_ttt(conn, room: dict, winner_id: int | None, status: str) -> list[dict]:
    stake = room["stake"]
    settlements: list[dict] = []
    if status == "draw" and stake > 0:
        await _grant_zefirki(conn, room["creator_id"], stake, "game_refund", room["id"])
        await _grant_zefirki(conn, room["opponent_id"], stake, "game_refund", room["id"])
        settlements.append(await _settlement(conn, room["creator_id"], "draw", stake, stake))
        settlements.append(await _settlement(conn, room["opponent_id"], "draw", stake, stake))
    elif winner_id and stake > 0:
        await _grant_zefirki(conn, winner_id, stake * 2, "game_win", room["id"])
        for uid in (room["creator_id"], room["opponent_id"]):
            if uid:
                payout = stake * 2 if uid == winner_id else 0
                settlements.append(await _settlement(conn, uid, "won" if uid == winner_id else "lost", stake, payout))
    else:
        for uid in (room["creator_id"], room.get("opponent_id")):
            if uid:
                settlements.append(await _settlement(conn, uid, "draw" if status == "draw" else "won" if uid == winner_id else "lost", stake, 0))
    return settlements


async def _expire_ttt_room(conn, room: dict) -> dict:
    settlements: list[dict] = []
    if room["stake"] > 0:
        for uid in (room["creator_id"], room.get("opponent_id")):
            if uid:
                await _grant_zefirki(conn, uid, room["stake"], "game_refund", room["id"])
                settlements.append(await _settlement(conn, uid, "expired", room["stake"], room["stake"]))
    else:
        for uid in (room["creator_id"], room.get("opponent_id")):
            if uid:
                settlements.append(await _settlement(conn, uid, "expired", 0, 0))
    cur = await conn.execute(
        """
        UPDATE game_rooms
           SET status = 'expired',
               turn_user_id = NULL,
               updated_at = NOW()
         WHERE id = %s
         RETURNING *
        """,
        (room["id"],),
    )
    expired = await cur.fetchone()
    expired = dict(expired)
    expired["settlements"] = settlements
    return expired


@with_db_retry
async def ttt_move(user_id: int, room_id: str, index: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_rooms WHERE id = %s FOR UPDATE", (room_id,))
            room = await cur.fetchone()
            if not room or room["status"] != "active":
                return {"ok": False, "error": "not_active"}
            if _room_is_expired(room):
                expired = await _expire_ttt_room(conn, room)
                return {"ok": False, "error": "expired", "room": expired}
            if user_id not in (room["creator_id"], room["opponent_id"]):
                return {"ok": False, "error": "not_player", "room": room}
            if room["turn_user_id"] != user_id:
                return {"ok": False, "error": "not_turn", "room": room}
            if index < 0 or index > 8 or room["board"][index] != ".":
                return {"ok": False, "error": "bad_cell", "room": room}

            mark = "X" if user_id == room["creator_id"] else "O"
            board = room["board"][:index] + mark + room["board"][index + 1:]
            winner_mark = _ttt_winner(board)
            winner_id = None
            status = "active"
            next_turn = room["opponent_id"] if user_id == room["creator_id"] else room["creator_id"]

            if winner_mark:
                winner_id = room["creator_id"] if winner_mark == "X" else room["opponent_id"]
                status = "finished"
                next_turn = None
            elif "." not in board:
                status = "draw"
                next_turn = None

            finished_room = dict(room)
            finished_room["board"] = board
            settlements = await _finish_ttt(conn, finished_room, winner_id, status)
            cur = await conn.execute(
                """
                UPDATE game_rooms
                   SET board = %s,
                       status = %s,
                       winner_id = %s,
                       turn_user_id = %s,
                       updated_at = NOW(),
                       expires_at = NOW() + make_interval(mins => %s)
                 WHERE id = %s
                RETURNING *
                """,
                (board, status, winner_id, next_turn, config.stale_game_timeout_minutes, room_id),
            )
            updated = await cur.fetchone()
            updated = dict(updated)
            updated["settlements"] = settlements
            return {"ok": True, "room": updated, "status": status, "winner_id": winner_id, "settlements": settlements}


@with_db_retry
async def cancel_ttt_room(user_id: int, room_id: str) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_rooms WHERE id = %s FOR UPDATE", (room_id,))
            room = await cur.fetchone()
            if not room or room["status"] != "waiting" or room["creator_id"] != user_id:
                return {"ok": False}
            if room["stake"] > 0:
                await _grant_zefirki(conn, user_id, room["stake"], "game_refund", room_id)
            await conn.execute(
                "UPDATE game_rooms SET status = 'cancelled', updated_at = NOW() WHERE id = %s",
                (room_id,),
            )
            return {"ok": True}


@with_db_retry
async def claim_ttt_timeout(user_id: int, room_id: str) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_rooms WHERE id = %s FOR UPDATE", (room_id,))
            room = await cur.fetchone()
            if not room or room["status"] != "active":
                return {"ok": False, "error": "not_active"}
            if _room_is_expired(room):
                expired = await _expire_ttt_room(conn, room)
                return {"ok": False, "error": "expired", "room": expired}
            if user_id not in (room["creator_id"], room["opponent_id"]):
                return {"ok": False, "error": "not_player"}
            if room["turn_user_id"] == user_id:
                return {"ok": False, "error": "your_turn"}
            now = datetime.now(timezone.utc)
            if room["updated_at"] and now - room["updated_at"] < timedelta(minutes=config.ttt_turn_timeout_minutes):
                return {"ok": False, "error": "too_early", "room": room}
            settlements = await _finish_ttt(conn, room, user_id, "finished")
            cur = await conn.execute(
                """
                UPDATE game_rooms
                   SET status = 'finished', winner_id = %s, turn_user_id = NULL, updated_at = NOW()
                 WHERE id = %s
                RETURNING *
                """,
                (user_id, room_id),
            )
            updated = await cur.fetchone()
            updated = dict(updated)
            updated["settlements"] = settlements
            return {"ok": True, "room": updated, "winner_id": user_id, "settlements": settlements}


@with_db_retry
async def expire_stale_ttt_rooms(limit: int = 50) -> list[dict]:
    expired: list[dict] = []
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                SELECT *
                FROM game_rooms
                WHERE status IN ('waiting', 'active')
                  AND COALESCE(expires_at, updated_at + make_interval(mins => %s)) <= NOW()
                ORDER BY COALESCE(expires_at, updated_at) ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (config.stale_game_timeout_minutes, limit),
            )
            rooms = await cur.fetchall()
            for room in rooms:
                expired.append(await _expire_ttt_room(conn, room))
    return expired
