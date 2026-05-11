from bot.services.game_logic import (
    guess_hangman_letter,
    hand_value,
    mines_cashout,
    make_hangman_state,
    mines_make_state,
    mines_multiplier,
    mines_open,
    mines_survival_probability,
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


def test_mines_multiplier_uses_probability_and_rtp():
    low_risk = mines_multiplier(size=4, mines_count=2, opened_safe=1, rtp=0.92)
    high_risk = mines_multiplier(size=4, mines_count=10, opened_safe=1, rtp=0.92)
    deeper = mines_multiplier(size=4, mines_count=5, opened_safe=3, rtp=0.92)
    first = mines_multiplier(size=4, mines_count=5, opened_safe=1, rtp=0.92)

    assert mines_survival_probability(size=4, mines_count=5, opened_safe=0) == 1.0
    assert high_risk > low_risk
    assert deeper > first
    assert mines_cashout(50, first) == int(50 * first)
