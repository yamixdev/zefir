import random
import uuid
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from bot.config import config
from bot.db import get_pool, with_db_retry
from bot.services.economy_service import _add_inventory, _log_event


MS_SIZE = 4
MS_MINES = 3
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


async def _remaining_pve_profit_cap(conn, user_id: int) -> int:
    cur = await conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS won
        FROM game_reward_logs
        WHERE user_id = %s AND reward_date = CURRENT_DATE
        """,
        (user_id,),
    )
    won = (await cur.fetchone())["won"]
    return max(config.game_daily_win_limit - won, 0)


async def _record_pve_profit(conn, user_id: int, amount: int, game_id: str) -> None:
    if amount <= 0:
        return
    await conn.execute(
        "INSERT INTO game_reward_logs (user_id, amount, game_id) VALUES (%s, %s, %s)",
        (user_id, amount, game_id),
    )


@with_db_retry
async def start_minesweeper(user_id: int, stake: int = 0) -> dict:
    stake = max(0, min(int(stake), 100))
    game_id = _game_id()
    cells = list(range(MS_SIZE * MS_SIZE))
    mines = sorted(_rng.sample(cells, MS_MINES))
    state = {"mines": mines, "revealed": []}

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
                profit = min(stake if stake else 5, cap)
                payout = stake + profit if stake else profit
                await _grant_zefirki(conn, user_id, payout, "game_win", game_id)
                await _record_pve_profit(conn, user_id, profit, game_id)
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
                profit = min((stake * 3) if stake else 10, cap)
                payout = stake + profit if stake else profit
                await _grant_zefirki(conn, user_id, payout, "game_win", game_id)
                await _record_pve_profit(conn, user_id, profit, game_id)
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
            revealed = set(state.get("revealed") or [])
            if index in revealed:
                return {"ok": True, "game": game, "state": state, "repeat": True}

            if index in mines:
                state["revealed"] = sorted(revealed | {index})
                await conn.execute(
                    "UPDATE pve_games SET status = 'lost', state = %s, updated_at = NOW() WHERE id = %s",
                    (Jsonb(state), game_id),
                )
                return {"ok": True, "status": "lost", "game": game, "state": state, "payout": 0}

            revealed.add(index)
            state["revealed"] = sorted(revealed)
            safe_total = MS_SIZE * MS_SIZE - MS_MINES
            if len(revealed) >= safe_total:
                cap = await _remaining_pve_profit_cap(conn, user_id)
                profit = min(game["stake"] if game["stake"] else 5, cap)
                payout = game["stake"] + profit if game["stake"] else profit
                await _grant_zefirki(conn, user_id, payout, "game_win", game_id)
                await _record_pve_profit(conn, user_id, profit, game_id)
                item = None
                if _rng.randint(1, 100) <= 12:
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
                return {"ok": True, "status": "won", "game": game, "state": state, "payout": payout, "profit": profit, "item": item}

            await conn.execute(
                "UPDATE pve_games SET state = %s, updated_at = NOW() WHERE id = %s",
                (Jsonb(state), game_id),
            )
            cur = await conn.execute("SELECT * FROM pve_games WHERE id = %s", (game_id,))
            updated = await cur.fetchone()
            return {"ok": True, "status": "active", "game": updated, "state": state}


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
                INSERT INTO game_rooms (id, game_type, creator_id, stake, turn_user_id)
                VALUES (%s, 'ttt', %s, %s, %s)
                RETURNING *
                """,
                (room_id, user_id, stake, user_id),
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
            ORDER BY gr.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return await cur.fetchall()


@with_db_retry
async def list_user_active_games(user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT * FROM pve_games
            WHERE user_id = %s AND status = 'active'
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
            ORDER BY created_at DESC
            LIMIT 10
            """,
            (user_id, user_id),
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
                   SET opponent_id = %s, status = 'active', updated_at = NOW()
                 WHERE id = %s
                RETURNING *
                """,
                (user_id, room_id),
            )
            return {"ok": True, "room": await cur.fetchone()}


def _ttt_winner(board: str) -> str | None:
    for combo in TTT_WINS:
        values = [board[i] for i in combo]
        if values[0] != "." and values.count(values[0]) == 3:
            return values[0]
    return None


async def _finish_ttt(conn, room: dict, winner_id: int | None, status: str) -> None:
    stake = room["stake"]
    if status == "draw" and stake > 0:
        await _grant_zefirki(conn, room["creator_id"], stake, "game_refund", room["id"])
        await _grant_zefirki(conn, room["opponent_id"], stake, "game_refund", room["id"])
    elif winner_id and stake > 0:
        await _grant_zefirki(conn, winner_id, stake * 2, "game_win", room["id"])


@with_db_retry
async def ttt_move(user_id: int, room_id: str, index: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_rooms WHERE id = %s FOR UPDATE", (room_id,))
            room = await cur.fetchone()
            if not room or room["status"] != "active":
                return {"ok": False, "error": "not_active"}
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
            await _finish_ttt(conn, finished_room, winner_id, status)
            cur = await conn.execute(
                """
                UPDATE game_rooms
                   SET board = %s,
                       status = %s,
                       winner_id = %s,
                       turn_user_id = %s,
                       updated_at = NOW()
                 WHERE id = %s
                RETURNING *
                """,
                (board, status, winner_id, next_turn, room_id),
            )
            return {"ok": True, "room": await cur.fetchone(), "status": status, "winner_id": winner_id}


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
            if user_id not in (room["creator_id"], room["opponent_id"]):
                return {"ok": False, "error": "not_player"}
            if room["turn_user_id"] == user_id:
                return {"ok": False, "error": "your_turn"}
            now = datetime.now(timezone.utc)
            if room["updated_at"] and now - room["updated_at"] < timedelta(minutes=config.ttt_turn_timeout_minutes):
                return {"ok": False, "error": "too_early", "room": room}
            await _finish_ttt(conn, room, user_id, "finished")
            cur = await conn.execute(
                """
                UPDATE game_rooms
                   SET status = 'finished', winner_id = %s, turn_user_id = NULL, updated_at = NOW()
                 WHERE id = %s
                RETURNING *
                """,
                (user_id, room_id),
            )
            return {"ok": True, "room": await cur.fetchone(), "winner_id": user_id}
