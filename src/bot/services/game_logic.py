from __future__ import annotations

import random
from dataclasses import dataclass


RPS_CHOICES = {
    "rock": "камень",
    "scissors": "ножницы",
    "paper": "бумага",
}
RPS_BEATS = {
    "rock": "scissors",
    "scissors": "paper",
    "paper": "rock",
}

TTT_WINS = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)

CARD_SUITS = ("♠", "♥", "♦", "♣")
CARD_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


def rps_winner(choice_a: str, choice_b: str) -> int:
    """Return 0 for draw, 1 if A wins, 2 if B wins."""
    if choice_a == choice_b:
        return 0
    return 1 if RPS_BEATS.get(choice_a) == choice_b else 2


def ttt_winner(board: str) -> str | None:
    for combo in TTT_WINS:
        values = [board[i] for i in combo]
        if values[0] != "." and values.count(values[0]) == 3:
            return values[0]
    if "." not in board:
        return "draw"
    return None


def ttt_apply_move(board: str, index: int, mark: str) -> str:
    if index < 0 or index > 8 or board[index] != ".":
        raise ValueError("bad_cell")
    return board[:index] + mark + board[index + 1:]


def ttt_bot_move(board: str, bot_mark: str = "O", player_mark: str = "X") -> int | None:
    free = [i for i, cell in enumerate(board) if cell == "."]
    if not free:
        return None
    for mark in (bot_mark, player_mark):
        for idx in free:
            trial = ttt_apply_move(board, idx, mark)
            if ttt_winner(trial) == mark:
                return idx
    if 4 in free:
        return 4
    for idx in (0, 2, 6, 8):
        if idx in free:
            return idx
    return free[0]


def make_hangman_state(word: str) -> dict:
    normalized = word.strip().lower()
    return {
        "word": normalized,
        "used": [],
        "wrong": 0,
        "max_wrong": 6,
    }


def render_hangman_word(state: dict) -> str:
    used = set(state.get("used") or [])
    return " ".join(ch if ch in used or not ch.isalpha() else "_" for ch in state["word"])


def guess_hangman_letter(state: dict, letter: str) -> tuple[dict, str]:
    letter = letter.lower()[:1]
    if not letter:
        return state, "bad"
    used = list(state.get("used") or [])
    if letter in used:
        return state, "repeat"
    used.append(letter)
    state = dict(state)
    state["used"] = used
    if letter not in state["word"]:
        state["wrong"] = int(state.get("wrong") or 0) + 1
    if "_" not in render_hangman_word(state):
        return state, "won"
    if state["wrong"] >= state.get("max_wrong", 6):
        return state, "lost"
    return state, "active"


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    def label(self) -> str:
        return f"{self.rank}{self.suit}"


def make_deck() -> list[dict]:
    deck = [{"rank": rank, "suit": suit} for suit in CARD_SUITS for rank in CARD_RANKS]
    random.shuffle(deck)
    return deck


def hand_value(cards: list[dict]) -> int:
    total = 0
    aces = 0
    for card in cards:
        rank = card["rank"]
        if rank in ("J", "Q", "K"):
            total += 10
        elif rank == "A":
            total += 11
            aces += 1
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[dict]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def card_labels(cards: list[dict]) -> str:
    return " ".join(f"[{c['rank']}{c['suit']}]" for c in cards)


def dice_result(a: int, b: int) -> int:
    if a == b:
        return 0
    return 1 if a > b else 2


def mines_make_state(size: int = 4, mines_count: int = 3) -> dict:
    cells = list(range(size * size))
    return {
        "size": size,
        "mines": sorted(random.sample(cells, mines_count)),
        "revealed": [],
        "status": "active",
    }


def mines_open(state: dict, index: int) -> tuple[dict, str]:
    size = int(state.get("size") or 4)
    if index < 0 or index >= size * size:
        return state, "bad"
    state = dict(state)
    revealed = list(state.get("revealed") or [])
    if index in revealed:
        return state, "repeat"
    revealed.append(index)
    state["revealed"] = revealed
    if index in set(state.get("mines") or []):
        state["status"] = "lost"
        return state, "lost"
    safe_total = size * size - len(state.get("mines") or [])
    if len(revealed) >= safe_total:
        state["status"] = "won"
        return state, "won"
    return state, "active"


def mines_cell_label(state: dict, index: int, reveal_all: bool = False) -> str:
    mines = set(state.get("mines") or [])
    revealed = set(state.get("revealed") or [])
    if index in revealed:
        return "💥" if index in mines else "✅"
    if reveal_all and index in mines:
        return "💣"
    return "▫️"
