from __future__ import annotations

import json
import random
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from psycopg.types.json import Jsonb

from bot.config import config
from bot.db import get_pool, with_db_retry
from bot.services.game_logic import (
    RPS_CHOICES,
    dice_result,
    guess_hangman_letter,
    hand_value,
    is_blackjack,
    make_deck,
    make_hangman_state,
    mines_make_state,
    mines_open,
    rps_winner,
    ttt_apply_move,
    ttt_bot_move,
    ttt_winner,
)


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
RANKED_TYPES = {"ttt", "rps", "duel", "blackjack", "quiz"}


def new_session_id() -> str:
    return secrets.token_urlsafe(5).replace("-", "").replace("_", "")[:7].lower()


def player_name(user) -> tuple[str | None, str | None]:
    return getattr(user, "username", None), getattr(user, "first_name", None)


def display_name(player: dict) -> str:
    return player.get("first_name") or player.get("username") or str(player["user_id"])


def load_quiz_questions(count: int = 10) -> list[dict]:
    with (DATA_DIR / "quiz_questions.json").open("r", encoding="utf-8") as f:
        questions = json.load(f)
    random.shuffle(questions)
    return questions[:count]


def load_hangman_word() -> str:
    with (DATA_DIR / "hangman_words_ru.json").open("r", encoding="utf-8") as f:
        words = json.load(f)
    return random.choice(words)


async def _spend(conn, user_id: int, amount: int, reason: str, game_id: str) -> bool:
    if amount <= 0:
        return True
    cur = await conn.execute(
        """
        UPDATE users
           SET zefirki = zefirki - %s
         WHERE user_id = %s AND zefirki >= %s
        RETURNING zefirki
        """,
        (amount, user_id, amount),
    )
    if not await cur.fetchone():
        return False
    await conn.execute(
        "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
        (user_id, -amount, reason),
    )
    await conn.execute(
        """
        INSERT INTO economy_events (user_id, amount, reason, game_id)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, -amount, reason, game_id),
    )
    return True


async def _grant(conn, user_id: int, amount: int, reason: str, game_id: str) -> None:
    if amount <= 0:
        return
    await conn.execute("UPDATE users SET zefirki = zefirki + %s WHERE user_id = %s", (amount, user_id))
    await conn.execute(
        "INSERT INTO transactions (user_id, amount, reason) VALUES (%s, %s, %s)",
        (user_id, amount, reason),
    )
    await conn.execute(
        """
        INSERT INTO economy_events (user_id, amount, reason, game_id)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, amount, reason, game_id),
    )


async def _session_players(conn, session_id: str) -> list[dict]:
    cur = await conn.execute(
        """
        SELECT *
        FROM game_session_players
        WHERE session_id = %s
        ORDER BY seat
        """,
        (session_id,),
    )
    return await cur.fetchall()


async def _session_messages(conn, session_id: str) -> list[dict]:
    cur = await conn.execute(
        "SELECT * FROM game_session_messages WHERE session_id = %s",
        (session_id,),
    )
    return await cur.fetchall()


async def _chat_messages(conn, session_id: str, limit: int = 10) -> list[dict]:
    cur = await conn.execute(
        """
        SELECT *
        FROM (
            SELECT *
            FROM game_chat_messages
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        ) recent
        ORDER BY created_at ASC
        """,
        (session_id, limit),
    )
    return await cur.fetchall()


async def _full(conn, session: dict | None) -> dict | None:
    if not session:
        return None
    out = dict(session)
    out["players"] = await _session_players(conn, session["id"])
    out["messages"] = await _session_messages(conn, session["id"])
    out["chat"] = await _chat_messages(conn, session["id"])
    return out


def _expires(minutes: int | None = None) -> datetime:
    return datetime.now(UTC) + timedelta(minutes=minutes or config.game_session_timeout_minutes)


def _quiz_state(count: int, ranked: bool = False, questions: list[dict] | None = None) -> dict:
    return {
        "questions": questions if questions is not None else load_quiz_questions(count),
        "index": 0,
        "scores": {},
        "answered": {},
        "total_response_ms": {},
        "question_started_at": datetime.now(UTC).isoformat(),
        "tiebreakers": 0,
        "ranked": ranked,
    }


async def _schedule_duel_signal(conn, session_id: str, state: dict) -> None:
    signal_at_raw = state.get("signal_at")
    if not signal_at_raw:
        return
    signal_at = datetime.fromisoformat(signal_at_raw)
    await conn.execute(
        """
        UPDATE game_scheduled_events
           SET status = 'cancelled', processed_at = NOW()
         WHERE session_id = %s AND event_type = 'duel_signal' AND status = 'pending'
        """,
        (session_id,),
    )
    await conn.execute(
        """
        INSERT INTO game_scheduled_events (session_id, event_type, run_at, payload)
        VALUES (%s, 'duel_signal', %s, '{}'::jsonb)
        """,
        (session_id, signal_at),
    )


async def _cancel_scheduled_events(conn, session_id: str) -> None:
    await conn.execute(
        """
        UPDATE game_scheduled_events
           SET status = 'cancelled', processed_at = NOW()
         WHERE session_id = %s AND status = 'pending'
        """,
        (session_id,),
    )


def _next_player_id(players: list[dict], user_id: int) -> int | None:
    ids = [p["user_id"] for p in players]
    if not ids:
        return None
    if user_id not in ids:
        return ids[0]
    return ids[(ids.index(user_id) + 1) % len(ids)]


def _quiz_sorted_scores(session: dict) -> list[tuple[dict, int, int]]:
    state = session.get("state") or {}
    scores = state.get("scores") or {}
    response_ms = state.get("total_response_ms") or {}
    rows = []
    for player in session.get("players") or []:
        uid = str(player["user_id"])
        rows.append((player, int(scores.get(uid, 0)), int(response_ms.get(uid, 0))))
    return sorted(rows, key=lambda row: (-row[1], row[2], row[0]["seat"]))


def _quiz_final_places(session: dict, use_speed: bool = False) -> list[dict]:
    rows = _quiz_sorted_scores(session)
    out = []
    current_place = 0
    last_key = None
    for index, (player, score, response_ms) in enumerate(rows, start=1):
        key = (score, response_ms) if use_speed else (score,)
        if key != last_key:
            current_place = index
            last_key = key
        out.append({
            "user_id": player["user_id"],
            "place": current_place,
            "score": score,
            "response_ms": response_ms,
        })
    return out


def _quiz_top_ids(session: dict, use_speed: bool = False) -> list[int]:
    rows = _quiz_sorted_scores(session)
    if not rows:
        return []
    top_score = rows[0][1]
    if top_score <= 0:
        return []
    if not use_speed:
        return [row[0]["user_id"] for row in rows if row[1] == top_score]
    top_ms = rows[0][2]
    return [row[0]["user_id"] for row in rows if row[1] == top_score and row[2] == top_ms]


def _quiz_start_next_question(state: dict) -> dict:
    state["answered"] = {}
    state["question_started_at"] = datetime.now(UTC).isoformat()
    return state


def _quiz_add_tiebreaker_if_needed(session: dict, state: dict) -> tuple[bool, dict]:
    temp_session = dict(session)
    temp_session["state"] = state
    top_ids = _quiz_top_ids(temp_session)
    if len(top_ids) <= 1 or int(state.get("tiebreakers") or 0) >= 3:
        return False, state
    question = dict(load_quiz_questions(1)[0])
    question["tiebreaker"] = True
    questions = list(state.get("questions") or [])
    questions.append(question)
    state["questions"] = questions
    state["index"] = len(questions) - 1
    state["tiebreakers"] = int(state.get("tiebreakers") or 0) + 1
    state["tiebreaker_players"] = [str(uid) for uid in top_ids]
    return True, _quiz_start_next_question(state)


def _quiz_finish_state(session: dict, state: dict) -> tuple[int | None, str, dict]:
    temp_session = dict(session)
    temp_session["state"] = state
    state["final_places"] = _quiz_final_places(temp_session, use_speed=True)
    rows = _quiz_sorted_scores(temp_session)
    if not rows or rows[0][1] <= 0:
        return None, "draw", state
    top_ids = _quiz_top_ids(temp_session, use_speed=True)
    if len(top_ids) == 1:
        return top_ids[0], "finished", state
    return None, "draw", state


def _quiz_score_for_answer(state: dict, correct_place: int) -> tuple[int, int]:
    started_raw = state.get("question_started_at")
    try:
        started_at = datetime.fromisoformat(started_raw) if started_raw else datetime.now(UTC)
    except Exception:
        started_at = datetime.now(UTC)
    elapsed_ms = max(0, int((datetime.now(UTC) - started_at).total_seconds() * 1000))
    elapsed_sec = elapsed_ms / 1000
    speed_points = max(20, int(120 - elapsed_sec * 3))
    place_bonus = {1: 40, 2: 25, 3: 15}.get(correct_place, 5)
    idx = int(state.get("index") or 0)
    questions = state.get("questions") or [{}]
    multiplier = 2 if questions[min(idx, len(questions) - 1)].get("tiebreaker") else 1
    return (speed_points + place_bonus) * multiplier, elapsed_ms


def _blackjack_player_score(hand: list[dict]) -> int:
    value = hand_value(hand)
    if value > 21:
        return -1
    return 22 if is_blackjack(hand) else value


def _blackjack_final_places(state: dict) -> list[dict]:
    players = state.get("players") or {}
    rows = []
    for uid, player in players.items():
        rows.append((int(uid), _blackjack_player_score(player.get("hand") or [])))
    rows.sort(key=lambda row: (-row[1], row[0]))
    out = []
    current_place = 0
    last_score = None
    for index, (uid, score) in enumerate(rows, start=1):
        if score != last_score:
            current_place = index
            last_score = score
        out.append({"user_id": uid, "place": current_place, "score": max(0, score), "response_ms": 0})
    return out


def _blackjack_settlements(state: dict) -> tuple[int | None, str, list[dict], list[dict]]:
    dealer = state.get("dealer") or []
    dealer_score = _blackjack_player_score(dealer)
    winners: list[int] = []
    settlements: list[dict] = []
    for uid_raw, player in (state.get("players") or {}).items():
        uid = int(uid_raw)
        player_score = _blackjack_player_score(player.get("hand") or [])
        if player_score < 0:
            outcome = "lost"
            payout_multiplier = 0
        elif dealer_score < 0 or player_score > dealer_score:
            outcome = "won"
            payout_multiplier = 2
            winners.append(uid)
        elif player_score == dealer_score:
            outcome = "push"
            payout_multiplier = 1
        else:
            outcome = "lost"
            payout_multiplier = 0
        settlements.append({"user_id": uid, "outcome": outcome, "payout_multiplier": payout_multiplier})
    if len(winners) == 1:
        return winners[0], "finished", settlements, _blackjack_final_places(state)
    if winners:
        return None, "finished", settlements, _blackjack_final_places(state)
    if settlements and all(item["outcome"] == "push" for item in settlements):
        return None, "draw", settlements, _blackjack_final_places(state)
    return None, "finished", settlements, _blackjack_final_places(state)


async def _update_locked_session(
    conn,
    session_id: str,
    state: dict,
    current_turn_id: int | None,
) -> dict:
    cur = await conn.execute(
        """
        UPDATE game_sessions
           SET state = %s,
               current_turn_id = %s,
               updated_at = NOW(),
               expires_at = %s
         WHERE id = %s
        RETURNING *
        """,
        (Jsonb(state), current_turn_id, _expires(), session_id),
    )
    return await cur.fetchone()


async def _initial_state(game_type: str, players: list[dict], seed_state: dict | None = None, ranked: bool = False) -> tuple[dict, int | None]:
    ids = [p["user_id"] for p in players]
    seed_state = seed_state or {}
    if game_type == "ttt":
        return {"board": ".........", "marks": {str(ids[0]): "X", str(ids[1]): "O"}}, ids[0]
    if game_type == "ttt_bot":
        return {"board": ".........", "marks": {str(ids[0]): "X", "bot": "O"}}, ids[0]
    if game_type == "rps":
        return {"choices": {}}, None
    if game_type == "duel":
        signal_at = datetime.now(UTC) + timedelta(seconds=random.randint(2, 7))
        return {"phase": "waiting_signal", "signal_at": signal_at.isoformat()}, None
    if game_type == "dice":
        return {"rolls": {}}, None
    if game_type == "quiz":
        count = 15 if ranked else int(seed_state.get("quiz_count") or 10)
        count = max(1, min(count, 30))
        questions = load_quiz_questions(count)
        if len(questions) < count and config.quiz_ai_enabled and config.yandex_gpt_api_key:
            from bot.services.quiz_ai_service import generate_quiz_questions

            questions.extend(await generate_quiz_questions(count - len(questions)))
        return _quiz_state(count, ranked, questions), None
    if game_type == "hangman":
        return make_hangman_state(load_hangman_word()), None
    if game_type == "blackjack":
        deck = make_deck()
        player_states = {}
        dealer = [deck.pop(), deck.pop()]
        for p in players:
            player_states[str(p["user_id"])] = {
                "hand": [deck.pop(), deck.pop()],
                "status": "playing",
            }
        return {"deck": deck, "dealer": dealer, "players": player_states, "phase": "playing"}, ids[0]
    if game_type == "mines":
        boards = {str(p["user_id"]): mines_make_state() for p in players}
        return {"boards": boards}, None
    return {}, ids[0] if ids else None


@with_db_retry
async def create_session(
    game_type: str,
    creator,
    chat_id: int,
    stake: int = 0,
    ranked: bool = False,
    min_players: int = 2,
    max_players: int = 2,
    mode: str = "pvp",
    autostart: bool = False,
    quiz_count: int | None = None,
) -> dict:
    user_id = creator.id
    username, first_name = player_name(creator)
    stake = 0 if ranked else max(0, min(int(stake), config.max_game_stake))
    ranked = bool(ranked and game_type in RANKED_TYPES)
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            for _ in range(8):
                session_id = new_session_id()
                cur = await conn.execute("SELECT 1 FROM game_sessions WHERE id = %s", (session_id,))
                if not await cur.fetchone():
                    break
            else:
                return {"ok": False, "error": "id_failed"}

            if not await _spend(conn, user_id, stake, "game_stake", session_id):
                return {"ok": False, "error": "not_enough"}

            status = "running" if autostart else "waiting"
            state = {"quiz_count": max(1, min(int(quiz_count or 10), 30))} if game_type == "quiz" else {}
            current_turn = None
            await conn.execute(
                """
                INSERT INTO game_sessions
                    (id, game_type, mode, status, creator_id, chat_id, stake, ranked, min_players, max_players,
                     current_turn_id, state, expires_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    game_type,
                    mode,
                    status,
                    user_id,
                    chat_id,
                    stake,
                    ranked,
                    min_players,
                    max_players,
                    current_turn,
                    Jsonb(state),
                    _expires(),
                ),
            )
            await conn.execute(
                """
                INSERT INTO game_session_players (session_id, user_id, username, first_name, seat)
                VALUES (%s, %s, %s, %s, 1)
                """,
                (session_id, user_id, username, first_name),
            )
            cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s", (session_id,))
            session = await cur.fetchone()
            if autostart:
                players = await _session_players(conn, session_id)
                state, current_turn = await _initial_state(game_type, players, state, ranked)
                cur = await conn.execute(
                    """
                    UPDATE game_sessions
                       SET state = %s, current_turn_id = %s, updated_at = NOW()
                     WHERE id = %s
                    RETURNING *
                    """,
                    (Jsonb(state), current_turn, session_id),
                )
                session = await cur.fetchone()
                if game_type == "duel":
                    await _schedule_duel_signal(conn, session_id, state)
            return {"ok": True, "session": await _full(conn, session)}


@with_db_retry
async def get_session(session_id: str) -> dict | None:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s", (session_id,))
        return await _full(conn, await cur.fetchone())


@with_db_retry
async def join_session(session_id: str, user) -> dict:
    user_id = user.id
    username, first_name = player_name(user)
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s FOR UPDATE", (session_id,))
            session = await cur.fetchone()
            if not session or session["status"] not in ("waiting", "running"):
                return {"ok": False, "error": "not_available"}
            if session["expires_at"] and session["expires_at"] < datetime.now(UTC):
                expired = await expire_session(conn, session)
                return {"ok": False, "error": "expired", "session": expired}

            players = await _session_players(conn, session_id)
            if any(p["user_id"] == user_id for p in players):
                return {"ok": True, "already_in_session": True, "session": await _full(conn, session)}
            if session["status"] != "waiting":
                return {"ok": False, "error": "already_started", "session": await _full(conn, session)}
            if len(players) >= session["max_players"]:
                return {"ok": False, "error": "full", "session": await _full(conn, session)}
            if session["ranked"] and session["game_type"] not in RANKED_TYPES:
                return {"ok": False, "error": "ranked_unavailable"}
            if not await _spend(conn, user_id, session["stake"], "game_stake", session_id):
                return {"ok": False, "error": "not_enough", "session": await _full(conn, session)}

            seat = len(players) + 1
            await conn.execute(
                """
                INSERT INTO game_session_players (session_id, user_id, username, first_name, seat)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (session_id, user_id, username, first_name, seat),
            )
            players = await _session_players(conn, session_id)
            should_autostart = len(players) >= session["min_players"] and session["min_players"] == session["max_players"]
            if should_autostart:
                state, current_turn = await _initial_state(session["game_type"], players, session.get("state") or {}, session["ranked"])
                cur = await conn.execute(
                    """
                    UPDATE game_sessions
                       SET status = 'running',
                           state = %s,
                           current_turn_id = %s,
                           updated_at = NOW(),
                           expires_at = %s
                     WHERE id = %s
                    RETURNING *
                    """,
                    (Jsonb(state), current_turn, _expires(), session_id),
                )
                session = await cur.fetchone()
                if session["game_type"] == "duel":
                    await _schedule_duel_signal(conn, session_id, state)
            else:
                cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s", (session_id,))
                session = await cur.fetchone()
            return {"ok": True, "session": await _full(conn, session)}


async def expire_session(conn, session: dict) -> dict:
    players = await _session_players(conn, session["id"])
    if session["stake"] > 0 and session["status"] in ("waiting", "running"):
        for player in players:
            await _grant(conn, player["user_id"], session["stake"], "game_refund", session["id"])
    cur = await conn.execute(
        """
        UPDATE game_sessions
           SET status = 'expired', result = 'timeout', updated_at = NOW()
         WHERE id = %s
        RETURNING *
        """,
        (session["id"],),
    )
    await _cancel_scheduled_events(conn, session["id"])
    return await _full(conn, await cur.fetchone())


@with_db_retry
async def cancel_session(session_id: str, user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s FOR UPDATE", (session_id,))
            session = await cur.fetchone()
            if not session or session["creator_id"] != user_id or session["status"] != "waiting":
                return {"ok": False, "error": "not_allowed"}
            players = await _session_players(conn, session_id)
            for player in players:
                await _grant(conn, player["user_id"], session["stake"], "game_refund", session_id)
            cur = await conn.execute(
                """
                UPDATE game_sessions
                   SET status = 'cancelled', result = 'cancelled', updated_at = NOW()
                 WHERE id = %s
                RETURNING *
                """,
                (session_id,),
            )
            await _cancel_scheduled_events(conn, session_id)
            return {"ok": True, "session": await _full(conn, await cur.fetchone())}


@with_db_retry
async def expire_session_by_id(session_id: str) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s FOR UPDATE", (session_id,))
            session = await cur.fetchone()
            if not session:
                return {"ok": False, "error": "not_found"}
            if session["status"] not in ("waiting", "running"):
                return {"ok": True, "session": await _full(conn, session)}
            return {"ok": True, "session": await expire_session(conn, session)}


@with_db_retry
async def update_session(session_id: str, state: dict, current_turn_id: int | None = None) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            UPDATE game_sessions
               SET state = %s,
                   current_turn_id = %s,
                   updated_at = NOW(),
                   expires_at = %s
             WHERE id = %s
            RETURNING *
            """,
            (Jsonb(state), current_turn_id, _expires(), session_id),
        )
        return await _full(conn, await cur.fetchone())


@with_db_retry
async def start_session(session_id: str, user_id: int) -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s FOR UPDATE", (session_id,))
            session = await cur.fetchone()
            if not session or session["status"] != "waiting":
                return {"ok": False, "error": "not_available"}
            if session["creator_id"] != user_id:
                return {"ok": False, "error": "not_creator", "session": await _full(conn, session)}
            players = await _session_players(conn, session_id)
            if len(players) < session["min_players"]:
                return {"ok": False, "error": "not_enough_players", "session": await _full(conn, session)}
            state, current_turn = await _initial_state(session["game_type"], players, session.get("state") or {}, session["ranked"])
            cur = await conn.execute(
                """
                UPDATE game_sessions
                   SET status = 'running',
                       state = %s,
                       current_turn_id = %s,
                       updated_at = NOW(),
                       expires_at = %s
                 WHERE id = %s
                RETURNING *
                """,
                (Jsonb(state), current_turn, _expires(), session_id),
            )
            session = await cur.fetchone()
            if session["game_type"] == "duel":
                await _schedule_duel_signal(conn, session_id, state)
            return {"ok": True, "session": await _full(conn, session)}


@with_db_retry
async def finish_session(session_id: str, winner_id: int | None, result: str = "finished") -> dict:
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s FOR UPDATE", (session_id,))
            session = await cur.fetchone()
            if not session:
                return {"ok": False, "error": "not_found"}
            if session["status"] in ("finished", "draw", "cancelled", "expired"):
                return {"ok": True, "session": await _full(conn, session)}
            players = await _session_players(conn, session_id)
            is_draw = result == "draw"
            if session["stake"] > 0:
                if is_draw:
                    for player in players:
                        await _grant(conn, player["user_id"], session["stake"], "game_refund", session_id)
                elif winner_id:
                    multiplier = 2 if session["mode"] == "bot" and session["game_type"] == "blackjack" else len(players)
                    await _grant(conn, winner_id, session["stake"] * multiplier, "game_win", session_id)
            if session["ranked"] and session["game_type"] in RANKED_TYPES:
                if session["game_type"] == "quiz" and len(players) >= 2:
                    from bot.services.rating_service import apply_ranked_placements

                    placements = (session.get("state") or {}).get("final_places") or []
                    if placements:
                        await apply_ranked_placements(session_id, session["game_type"], placements)
                elif len(players) == 2:
                    from bot.services.rating_service import apply_ranked_result

                    await apply_ranked_result(
                        session_id,
                        session["game_type"],
                        players[0]["user_id"],
                        players[1]["user_id"],
                        winner_id,
                        is_draw,
                    )
            status = "draw" if is_draw else "finished"
            cur = await conn.execute(
                """
                UPDATE game_sessions
                   SET status = %s,
                       winner_id = %s,
                       result = %s,
                       current_turn_id = NULL,
                       updated_at = NOW()
                 WHERE id = %s
                RETURNING *
                """,
                (status, winner_id, result, session_id),
            )
            await _cancel_scheduled_events(conn, session_id)
            return {"ok": True, "session": await _full(conn, await cur.fetchone())}


async def _finish_locked(
    conn,
    session: dict,
    players: list[dict],
    winner_id: int | None,
    result: str = "finished",
    settlements: list[dict] | None = None,
) -> dict:
    session_id = session["id"]
    is_draw = result == "draw"
    if session["stake"] > 0:
        if settlements:
            for settlement in settlements:
                payout = session["stake"] * int(settlement.get("payout_multiplier") or 0)
                if payout:
                    await _grant(conn, settlement["user_id"], payout, "game_win" if payout > session["stake"] else "game_refund", session_id)
        elif is_draw:
            for player in players:
                await _grant(conn, player["user_id"], session["stake"], "game_refund", session_id)
        elif winner_id:
            await _grant(conn, winner_id, session["stake"] * len(players), "game_win", session_id)

    await _cancel_scheduled_events(conn, session_id)
    status = "draw" if is_draw else "finished"
    cur = await conn.execute(
        """
        UPDATE game_sessions
           SET status = %s,
               winner_id = %s,
               result = %s,
               current_turn_id = NULL,
               updated_at = NOW()
         WHERE id = %s
        RETURNING *
        """,
        (status, winner_id, result, session_id),
    )
    return await cur.fetchone()


async def _apply_ranked_after_finish(session: dict) -> None:
    if not session or not session.get("ranked") or session.get("game_type") not in RANKED_TYPES:
        return
    players = session.get("players") or []
    if session["game_type"] in ("quiz", "blackjack") and len(players) >= 2:
        placements = (session.get("state") or {}).get("final_places") or []
        if placements:
            from bot.services.rating_service import apply_ranked_placements

            await apply_ranked_placements(session["id"], session["game_type"], placements)
        return
    if len(players) == 2:
        from bot.services.rating_service import apply_ranked_result

        await apply_ranked_result(
            session["id"],
            session["game_type"],
            players[0]["user_id"],
            players[1]["user_id"],
            session.get("winner_id"),
            session.get("status") == "draw",
        )


@with_db_retry
async def handle_session_action(session_id: str, user_id: int, action: str, value: str) -> dict:
    finished = False
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s FOR UPDATE", (session_id,))
            session = await cur.fetchone()
            if not session or session["status"] not in ("waiting", "running"):
                return {"ok": False, "error": "finished", "answer": "Эта игра уже завершена.", "alert": True}
            if session.get("expires_at") and session["expires_at"] < datetime.now(UTC):
                expired = await expire_session(conn, session)
                return {"ok": False, "error": "expired", "session": expired, "answer": "Игра закрыта из-за бездействия.", "alert": True}

            players = await _session_players(conn, session_id)
            if not any(p["user_id"] == user_id for p in players):
                return {"ok": False, "error": "not_player", "session": await _full(conn, session), "answer": "Ты не участник этой игры.", "alert": True}
            if session["status"] != "running":
                return {"ok": False, "error": "not_running", "session": await _full(conn, session), "answer": "Игра ещё не началась.", "alert": True}

            state = dict(session.get("state") or {})
            game_type = session["game_type"]
            answer = "Готово"
            alert = False

            if action == "ttt" and game_type in ("ttt", "ttt_bot"):
                if session.get("current_turn_id") != user_id:
                    return {"ok": False, "error": "not_turn", "session": await _full(conn, session), "answer": "Сейчас не твой ход.", "alert": True}
                try:
                    board = ttt_apply_move(state.get("board", "........."), int(value), "X" if game_type == "ttt_bot" else state["marks"][str(user_id)])
                except (ValueError, KeyError):
                    return {"ok": False, "error": "bad_cell", "session": await _full(conn, session), "answer": "Клетка занята.", "alert": True}
                winner = ttt_winner(board)
                if game_type == "ttt_bot" and not winner:
                    bot_idx = ttt_bot_move(board)
                    if bot_idx is not None:
                        board = ttt_apply_move(board, bot_idx, "O")
                        winner = ttt_winner(board)
                state["board"] = board
                if winner:
                    session = await _update_locked_session(conn, session_id, state, None)
                    if winner == "draw":
                        session = await _finish_locked(conn, session, players, None, "draw")
                    elif game_type == "ttt_bot":
                        session = await _finish_locked(conn, session, players, user_id if winner == "X" else None, "finished")
                    else:
                        winner_id = next(int(uid) for uid, mark in state["marks"].items() if mark == winner)
                        session = await _finish_locked(conn, session, players, winner_id, "finished")
                    finished = True
                    answer = "Игра завершена"
                else:
                    next_turn = user_id if game_type == "ttt_bot" else _next_player_id(players, user_id)
                    session = await _update_locked_session(conn, session_id, state, next_turn)

            elif action == "rps" and game_type == "rps":
                if value not in RPS_CHOICES:
                    return {"ok": False, "error": "bad_choice", "session": await _full(conn, session), "answer": "Такого выбора нет.", "alert": True}
                choices = dict(state.get("choices") or {})
                choices[str(user_id)] = value
                state["choices"] = choices
                session = await _update_locked_session(conn, session_id, state, None)
                answer = "Выбор принят"
                if len(choices) >= 2:
                    a, b = players[0], players[1]
                    result = rps_winner(choices[str(a["user_id"])], choices[str(b["user_id"])])
                    winner_id = None if result == 0 else (a["user_id"] if result == 1 else b["user_id"])
                    session = await _finish_locked(conn, session, players, winner_id, "draw" if result == 0 else "finished")
                    finished = True

            elif action == "duel" and game_type == "duel":
                phase = state.get("phase")
                other = next((p for p in players if p["user_id"] != user_id), None)
                if phase != "active":
                    session = await _finish_locked(conn, session, players, other["user_id"] if other else None, "finished")
                    finished = True
                    answer = "Ранний выстрел. Ты проиграл."
                    alert = True
                else:
                    session = await _finish_locked(conn, session, players, user_id, "finished")
                    finished = True
                    answer = "Выстрел принят"

            elif action == "dice" and game_type == "dice":
                rolls = dict(state.get("rolls") or {})
                if str(user_id) in rolls:
                    return {"ok": False, "error": "already_rolled", "session": await _full(conn, session), "answer": "Ты уже бросил кости.", "alert": True}
                rolls[str(user_id)] = random.randint(1, 6)
                state["rolls"] = rolls
                session = await _update_locked_session(conn, session_id, state, None)
                answer = "Бросок принят"
                if len(rolls) >= len(players):
                    a, b = players[0], players[1]
                    result = dice_result(rolls[str(a["user_id"])], rolls[str(b["user_id"])])
                    winner_id = None if result == 0 else (a["user_id"] if result == 1 else b["user_id"])
                    session = await _finish_locked(conn, session, players, winner_id, "draw" if result == 0 else "finished")
                    finished = True

            elif action == "quiz" and game_type == "quiz":
                questions = state.get("questions") or []
                idx = int(state.get("index") or 0)
                answered = dict(state.get("answered") or {})
                uid = str(user_id)
                tiebreaker_players = set(state.get("tiebreaker_players") or [])
                if tiebreaker_players and uid not in tiebreaker_players:
                    return {"ok": False, "error": "not_tiebreaker", "session": await _full(conn, session), "answer": "Сейчас tie-break только для игроков с ничьей.", "alert": True}
                if uid in answered:
                    return {"ok": False, "error": "already_answered", "session": await _full(conn, session), "answer": "Ты уже отвечал на этот вопрос.", "alert": True}
                if idx >= len(questions):
                    return {"ok": False, "error": "quiz_done", "session": await _full(conn, session), "answer": "Викторина уже закончилась.", "alert": True}
                q = questions[idx]
                scores = dict(state.get("scores") or {})
                response_ms = dict(state.get("total_response_ms") or {})
                correct = int(value) == int(q["correctIndex"])
                points = 0
                elapsed_ms = 0
                if correct:
                    correct_place = 1 + sum(1 for item in answered.values() if item.get("correct"))
                    points, elapsed_ms = _quiz_score_for_answer(state, correct_place)
                    scores[uid] = int(scores.get(uid, 0)) + points
                    response_ms[uid] = int(response_ms.get(uid, 0)) + elapsed_ms
                answered[uid] = {"choice": int(value), "correct": correct, "points": points, "elapsed_ms": elapsed_ms}
                state.update({"answered": answered, "scores": scores, "total_response_ms": response_ms})
                active_players = tiebreaker_players or {str(p["user_id"]) for p in players}
                if active_players.issubset(set(answered.keys())):
                    state["index"] = idx + 1
                    state.pop("tiebreaker_players", None)
                    _quiz_start_next_question(state)
                session = await _update_locked_session(conn, session_id, state, None)
                if int(state.get("index") or 0) >= len(questions):
                    temp = dict(session)
                    temp["players"] = players
                    added, state = _quiz_add_tiebreaker_if_needed(temp, state)
                    if added:
                        session = await _update_locked_session(conn, session_id, state, None)
                        return {"ok": True, "session": await _full(conn, session), "answer": "Ничья за первое место. Запущен tie-break."}
                    winner_id, result_status, state = _quiz_finish_state(temp, state)
                    session = await _update_locked_session(conn, session_id, state, None)
                    session = await _finish_locked(conn, session, players, winner_id, result_status)
                    finished = True
                    answer = "Викторина завершена"
                else:
                    answer = "Правильно" if correct else "Ответ принят"

            elif action == "quiznext" and game_type == "quiz":
                if session["creator_id"] != user_id:
                    return {"ok": False, "error": "not_creator", "session": await _full(conn, session), "answer": "Следующий вопрос может включить создатель комнаты.", "alert": True}
                questions = state.get("questions") or []
                idx = int(state.get("index") or 0)
                if idx >= len(questions):
                    return {"ok": False, "error": "quiz_done", "session": await _full(conn, session), "answer": "Викторина уже заканчивается.", "alert": True}
                state["index"] = idx + 1
                state.pop("tiebreaker_players", None)
                _quiz_start_next_question(state)
                temp = dict(session)
                temp["players"] = players
                if int(state.get("index") or 0) >= len(questions):
                    added, state = _quiz_add_tiebreaker_if_needed(temp, state)
                    if not added:
                        winner_id, result_status, state = _quiz_finish_state(temp, state)
                        session = await _update_locked_session(conn, session_id, state, None)
                        session = await _finish_locked(conn, session, players, winner_id, result_status)
                        finished = True
                        answer = "Викторина завершена"
                    else:
                        session = await _update_locked_session(conn, session_id, state, None)
                        answer = "Запущен tie-break."
                else:
                    session = await _update_locked_session(conn, session_id, state, None)

            elif action == "hm" and game_type == "hangman":
                state, status = guess_hangman_letter(state, value)
                session = await _update_locked_session(conn, session_id, state, None)
                if status == "repeat":
                    return {"ok": False, "error": "repeat", "session": await _full(conn, session), "answer": "Эта буква уже была.", "alert": True}
                if status in ("won", "lost"):
                    winner_id = user_id if status == "won" else None
                    session = await _finish_locked(conn, session, players, winner_id, "finished" if winner_id else "draw")
                    finished = True
                    answer = "Виселица завершена"

            elif action == "bj" and game_type == "blackjack":
                if session.get("current_turn_id") != user_id:
                    return {"ok": False, "error": "not_turn", "session": await _full(conn, session), "answer": "Сейчас не твой ход.", "alert": True}
                pst = state.get("players") or {}
                me = pst.get(str(user_id))
                if not me:
                    return {"ok": False, "error": "bad_state", "session": await _full(conn, session), "answer": "Твоей руки нет в этой партии.", "alert": True}
                deck = state.get("deck") or []
                if value == "hit":
                    if not deck:
                        return {"ok": False, "error": "empty_deck", "session": await _full(conn, session), "answer": "Колода закончилась.", "alert": True}
                    me["hand"].append(deck.pop())
                    if hand_value(me["hand"]) > 21:
                        me["status"] = "busted"
                    elif is_blackjack(me["hand"]):
                        me["status"] = "blackjack"
                elif value == "stand":
                    me["status"] = "stand"
                else:
                    return {"ok": False, "error": "bad_action", "session": await _full(conn, session), "answer": "Действие недоступно.", "alert": True}
                pst[str(user_id)] = me
                state["deck"] = deck
                state["players"] = pst
                active_ids = [int(uid) for uid, p in pst.items() if p.get("status") == "playing"]
                if active_ids:
                    next_turn = active_ids[0] if user_id not in active_ids else _next_player_id([p for p in players if p["user_id"] in active_ids], user_id)
                    if next_turn not in active_ids:
                        next_turn = active_ids[0]
                    session = await _update_locked_session(conn, session_id, state, next_turn)
                else:
                    dealer = state.get("dealer") or []
                    while hand_value(dealer) < 17 and deck:
                        dealer.append(deck.pop())
                    state["dealer"] = dealer
                    state["phase"] = "finished"
                    winner_id, result_status, settlements, final_places = _blackjack_settlements(state)
                    state["settlements"] = settlements
                    state["final_places"] = final_places
                    session = await _update_locked_session(conn, session_id, state, None)
                    session = await _finish_locked(conn, session, players, winner_id, result_status, settlements=settlements)
                    finished = True
                    answer = "Blackjack завершён"

            elif action == "mine" and game_type == "mines":
                boards = dict(state.get("boards") or {})
                board = boards.get(str(user_id))
                if not board or board.get("status") != "active":
                    return {"ok": False, "error": "field_done", "session": await _full(conn, session), "answer": "Твоё поле уже завершено.", "alert": True}
                board, status = mines_open(board, int(value))
                boards[str(user_id)] = board
                state["boards"] = boards
                session = await _update_locked_session(conn, session_id, state, None)
                if status == "repeat":
                    return {"ok": False, "error": "repeat", "session": await _full(conn, session), "answer": "Эта клетка уже открыта.", "alert": True}
                if status == "lost":
                    winner = next((p["user_id"] for p in players if p["user_id"] != user_id), None)
                    session = await _finish_locked(conn, session, players, winner, "finished")
                    finished = True
                    return {"ok": True, "session": await _full(conn, session), "finished": True, "answer": "Мина. Игра завершена.", "alert": True}
                if status == "won":
                    session = await _finish_locked(conn, session, players, user_id, "finished")
                    finished = True
                    answer = "Поле очищено!"

            else:
                return {"ok": False, "error": "unavailable", "session": await _full(conn, session), "answer": "Действие недоступно.", "alert": True}

            full_session = await _full(conn, session)

    if finished:
        await _apply_ranked_after_finish(full_session)
        full_session = await get_session(session_id)
    return {"ok": True, "session": full_session, "finished": finished, "answer": answer, "alert": alert}


@with_db_retry
async def activate_due_duel_signals(limit: int = 20) -> list[dict]:
    activated: list[dict] = []
    pool = await get_pool()
    async with pool.connection() as conn:
        async with conn.transaction():
            cur = await conn.execute(
                """
                SELECT *
                FROM game_scheduled_events
                WHERE status = 'pending'
                  AND event_type = 'duel_signal'
                  AND run_at <= NOW()
                ORDER BY run_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (limit,),
            )
            events = await cur.fetchall()
            for event in events:
                cur = await conn.execute("SELECT * FROM game_sessions WHERE id = %s FOR UPDATE", (event["session_id"],))
                session = await cur.fetchone()
                if not session or session["status"] != "running" or session["game_type"] != "duel":
                    await conn.execute(
                        "UPDATE game_scheduled_events SET status = 'cancelled', processed_at = NOW() WHERE id = %s",
                        (event["id"],),
                    )
                    continue
                state = dict(session.get("state") or {})
                if state.get("phase") == "waiting_signal":
                    state["phase"] = "active"
                    cur = await conn.execute(
                        """
                        UPDATE game_sessions
                           SET state = %s, updated_at = NOW()
                         WHERE id = %s
                        RETURNING *
                        """,
                        (Jsonb(state), session["id"]),
                    )
                    session = await cur.fetchone()
                    activated.append(await _full(conn, session))
                await conn.execute(
                    "UPDATE game_scheduled_events SET status = 'processed', processed_at = NOW() WHERE id = %s",
                    (event["id"],),
                )
    return activated


@with_db_retry
async def set_session_message(session_id: str, user_id: int, chat_id: int, message_id: int) -> None:
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO game_session_messages (session_id, user_id, chat_id, message_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (session_id, user_id) DO UPDATE
                SET chat_id = EXCLUDED.chat_id,
                    message_id = EXCLUDED.message_id,
                    updated_at = NOW()
            """,
            (session_id, user_id, chat_id, message_id),
        )


@with_db_retry
async def add_chat_message(session_id: str, user_id: int, display: str, text: str) -> dict | None:
    safe = " ".join((text or "").split())[:120]
    if not safe:
        return await get_session(session_id)
    pool = await get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO game_chat_messages (session_id, user_id, display_name, text)
            VALUES (%s, %s, %s, %s)
            """,
            (session_id, user_id, display[:64], safe),
        )
        await conn.execute(
            """
            DELETE FROM game_chat_messages
            WHERE id IN (
                SELECT id FROM game_chat_messages
                WHERE session_id = %s
                ORDER BY created_at DESC
                OFFSET 10
            )
            """,
            (session_id,),
        )
    return await get_session(session_id)


@with_db_retry
async def list_open_sessions(game_type: str | None = None, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        params: list = []
        where = "status = 'waiting'"
        if game_type:
            where += " AND game_type = %s"
            params.append(game_type)
        params.append(limit)
        cur = await conn.execute(
            f"""
            SELECT gs.*, u.username, u.first_name
            FROM game_sessions gs
            JOIN users u ON u.user_id = gs.creator_id
            WHERE {where}
            ORDER BY gs.created_at DESC
            LIMIT %s
            """,
            params,
        )
        return await cur.fetchall()


@with_db_retry
async def list_my_sessions(user_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            SELECT gs.*
            FROM game_sessions gs
            JOIN game_session_players gsp ON gsp.session_id = gs.id
            WHERE gsp.user_id = %s AND gs.status IN ('waiting', 'running')
            ORDER BY gs.updated_at DESC
            LIMIT 10
            """,
            (user_id,),
        )
        return await cur.fetchall()
