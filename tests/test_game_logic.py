from bot.services.game_logic import (
    guess_hangman_letter,
    hand_value,
    make_hangman_state,
    mines_make_state,
    mines_open,
    render_hangman_word,
    rps_winner,
    ttt_apply_move,
    ttt_bot_move,
    ttt_winner,
)


def test_rps_winner_logic():
    assert rps_winner("rock", "scissors") == 1
    assert rps_winner("scissors", "rock") == 2
    assert rps_winner("paper", "paper") == 0


def test_blackjack_hand_value_with_aces():
    assert hand_value([{"rank": "A", "suit": "♠"}, {"rank": "K", "suit": "♥"}]) == 21
    assert hand_value([
        {"rank": "A", "suit": "♠"},
        {"rank": "9", "suit": "♥"},
        {"rank": "A", "suit": "♦"},
    ]) == 21
    assert hand_value([
        {"rank": "A", "suit": "♠"},
        {"rank": "9", "suit": "♥"},
        {"rank": "A", "suit": "♦"},
        {"rank": "5", "suit": "♣"},
    ]) == 16


def test_hangman_reveal_and_repeat():
    state = make_hangman_state("бот")
    assert render_hangman_word(state) == "_ _ _"
    state, status = guess_hangman_letter(state, "б")
    assert status == "active"
    assert render_hangman_word(state) == "б _ _"
    _, status = guess_hangman_letter(state, "б")
    assert status == "repeat"


def test_ttt_winner_and_bot_block():
    board = "XX......."
    assert ttt_bot_move(board, bot_mark="O", player_mark="X") == 2
    won = ttt_apply_move("XX.......", 2, "X")
    assert ttt_winner(won) == "X"


def test_mines_open_lost_or_active():
    state = mines_make_state(size=2, mines_count=1)
    mine = state["mines"][0]
    state, status = mines_open(state, mine)
    assert status == "lost"
    assert state["status"] == "lost"
