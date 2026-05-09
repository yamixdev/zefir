from bot.services.games_service import create_ttt_room, join_ttt_room, set_ttt_message, ttt_move

from conftest import create_user, fetch_one


async def test_ttt_room_flow_winner_and_message_ids(conn):
    creator_id = 401
    opponent_id = 402
    await create_user(conn, creator_id, zefirki=100)
    await create_user(conn, opponent_id, zefirki=100)

    created = await create_ttt_room(creator_id, stake=10)
    assert created["ok"] is True
    room_id = created["room"]["id"]

    room = await set_ttt_message(room_id, creator_id, creator_id, 111)
    assert room["creator_msg_id"] == 111

    joined = await join_ttt_room(opponent_id, room_id)
    assert joined["ok"] is True
    room = await set_ttt_message(room_id, opponent_id, opponent_id, 222)
    assert room["opponent_msg_id"] == 222

    assert (await ttt_move(creator_id, room_id, 0))["ok"] is True
    assert (await ttt_move(opponent_id, room_id, 3))["ok"] is True
    assert (await ttt_move(creator_id, room_id, 1))["ok"] is True
    assert (await ttt_move(opponent_id, room_id, 4))["ok"] is True
    finished = await ttt_move(creator_id, room_id, 2)

    room = await fetch_one(conn, "SELECT * FROM game_rooms WHERE id = %s", (room_id,))
    assert finished["ok"] is True
    assert finished["status"] == "finished"
    assert finished["winner_id"] == creator_id
    assert room["creator_msg_id"] == 111
    assert room["opponent_msg_id"] == 222
    assert room["winner_id"] == creator_id
