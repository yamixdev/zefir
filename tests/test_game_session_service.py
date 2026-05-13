import asyncio
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from bot.services.game_session_service import (
    activate_due_duel_signals,
    create_session,
    get_session,
    handle_session_action,
    join_session,
)

from conftest import create_user, fetch_one, fetch_value


@dataclass
class FakeUser:
    id: int
    username: str = "user"
    first_name: str = "User"


async def test_join_running_session_blocks_new_player(conn):
    await create_user(conn, 501, zefirki=100)
    await create_user(conn, 502, zefirki=100)
    await create_user(conn, 503, zefirki=100)

    created = await create_session("rps", FakeUser(501), 501, min_players=2, max_players=2)
    joined = await join_session(created["session"]["id"], FakeUser(502))
    late = await join_session(created["session"]["id"], FakeUser(503))
    reopen = await join_session(created["session"]["id"], FakeUser(501))

    assert joined["ok"] is True
    assert joined["session"]["status"] == "running"
    assert late["ok"] is False
    assert late["error"] == "already_started"
    assert reopen["ok"] is True
    assert reopen["already_in_session"] is True


async def test_parallel_rps_actions_do_not_lose_choices(conn):
    await create_user(conn, 511, zefirki=100)
    await create_user(conn, 512, zefirki=100)

    created = await create_session("rps", FakeUser(511), 511, min_players=2, max_players=2)
    session_id = created["session"]["id"]
    await join_session(session_id, FakeUser(512))

    await asyncio.gather(
        handle_session_action(session_id, 511, "rps", "rock"),
        handle_session_action(session_id, 512, "rps", "scissors"),
    )
    session = await get_session(session_id)

    assert session["status"] == "finished"
    assert session["winner_id"] == 511
    assert session["state"]["choices"] == {"511": "rock", "512": "scissors"}


async def test_duel_signal_is_activated_by_scheduled_event(conn):
    await create_user(conn, 521, zefirki=100)
    await create_user(conn, 522, zefirki=100)

    created = await create_session("duel", FakeUser(521), 521, min_players=2, max_players=2)
    session_id = created["session"]["id"]
    await join_session(session_id, FakeUser(522))
    await conn.execute(
        "UPDATE game_scheduled_events SET run_at = NOW() WHERE session_id = %s AND event_type = 'duel_signal'",
        (session_id,),
    )

    activated = await activate_due_duel_signals()
    session = await get_session(session_id)

    assert [item["id"] for item in activated] == [session_id]
    assert session["state"]["phase"] == "active"


async def test_blackjack_settles_each_player_against_dealer(conn):
    await create_user(conn, 531, zefirki=100)
    await create_user(conn, 532, zefirki=100)

    created = await create_session("blackjack", FakeUser(531), 531, stake=10, min_players=2, max_players=2)
    session_id = created["session"]["id"]
    await join_session(session_id, FakeUser(532))
    state = {
        "deck": [],
        "dealer": [{"rank": "10", "suit": "♠"}, {"rank": "K", "suit": "♣"}],
        "players": {
            "531": {"hand": [{"rank": "A", "suit": "♠"}, {"rank": "K", "suit": "♥"}], "status": "playing"},
            "532": {"hand": [{"rank": "10", "suit": "♦"}, {"rank": "8", "suit": "♣"}], "status": "stand"},
        },
        "phase": "playing",
    }
    await conn.execute(
        "UPDATE game_sessions SET state = %s, current_turn_id = %s WHERE id = %s",
        (Jsonb(state), 531, session_id),
    )

    result = await handle_session_action(session_id, 531, "bj", "stand")
    balance_winner = await fetch_value(conn, "SELECT zefirki FROM users WHERE user_id = 531")
    balance_loser = await fetch_value(conn, "SELECT zefirki FROM users WHERE user_id = 532")
    finished = await fetch_one(conn, "SELECT status, winner_id FROM game_sessions WHERE id = %s", (session_id,))

    assert result["ok"] is True
    assert result["finished"] is True
    assert finished["status"] == "finished"
    assert finished["winner_id"] == 531
    assert balance_winner == 110
    assert balance_loser == 90


async def test_bot_mode_cannot_create_ranked_session(conn):
    await create_user(conn, 541, zefirki=100)

    created = await create_session(
        "blackjack",
        FakeUser(541),
        541,
        ranked=True,
        mode="bot",
        autostart=True,
        min_players=1,
        max_players=1,
    )

    assert created["ok"] is True
    assert created["session"]["mode"] == "bot"
    assert created["session"]["ranked"] is False
