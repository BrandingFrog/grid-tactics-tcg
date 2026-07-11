"""Metal Wyrm (user 2026-07-11): comeback cost reduction.

cost_reduction="behind_on_board" subtracts cost_reduction_amount while
the OPPONENT has a living minion and the owner has NONE — checked at
play time via effective_mana_cost (both legal_actions and the resolver's
payment route through it).
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, PlayerSide
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import effective_mana_cost, legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.server.preset_deck import get_preset_deck


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _state(library, *, my_minion=False, opp_minion=False, mana=5):
    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=11, deck_p1=deck, deck_p2=deck)
    wyrm = library.get_numeric_id("metal_wyrm")
    rat = library.get_numeric_id("rat")
    p = replace(state.players[0], hand=(wyrm,), current_mana=mana)
    state = replace(state, players=(p, state.players[1]))
    minions = []
    board = state.board
    next_id = state.next_minion_id
    if my_minion:
        minions.append(MinionInstance(
            instance_id=next_id, card_numeric_id=rat,
            owner=PlayerSide.PLAYER_1, position=(0, 0), current_health=10,
        ))
        board = board.place(0, 0, next_id)
        next_id += 1
    if opp_minion:
        minions.append(MinionInstance(
            instance_id=next_id, card_numeric_id=rat,
            owner=PlayerSide.PLAYER_2, position=(4, 4), current_health=10,
        ))
        board = board.place(4, 4, next_id)
        next_id += 1
    return replace(
        state, minions=tuple(minions), board=board, next_minion_id=next_id,
    )


def test_definition(library):
    w = library.get_by_card_id("metal_wyrm")
    assert w.mana_cost == 5
    assert w.attack == 33 and w.health == 33
    assert w.cost_reduction == "behind_on_board"
    assert w.cost_reduction_amount == 3
    assert w.tribe == "Wyrm"


def test_discount_when_behind(library):
    state = _state(library, opp_minion=True)
    w = library.get_by_card_id("metal_wyrm")
    assert effective_mana_cost(w, state, 0) == 2


def test_full_price_when_boards_equal_or_ahead(library):
    w = library.get_by_card_id("metal_wyrm")
    # Empty board on both sides: no discount.
    assert effective_mana_cost(w, _state(library), 0) == 5
    # Both have minions: no discount.
    assert effective_mana_cost(
        w, _state(library, my_minion=True, opp_minion=True), 0) == 5
    # Only I have a minion: no discount.
    assert effective_mana_cost(w, _state(library, my_minion=True), 0) == 5


def test_playable_at_two_mana_when_behind(library):
    state = _state(library, opp_minion=True, mana=2)
    plays = [a for a in legal_actions(state, library)
             if a.action_type == ActionType.PLAY_CARD]
    assert plays, "discounted Metal Wyrm must be playable at 2 mana"
    state = resolve_action(state, plays[0], library)
    assert state.players[0].current_mana == 0, "pays the DISCOUNTED cost"


def test_unplayable_at_two_mana_when_not_behind(library):
    state = _state(library, mana=2)
    plays = [a for a in legal_actions(state, library)
             if a.action_type == ActionType.PLAY_CARD]
    assert plays == []


def test_dead_minions_do_not_count(library):
    state = _state(library, opp_minion=True)
    # Kill the opponent's minion (0 HP awaiting cleanup) — discount gone.
    dead = replace(state.minions[0], current_health=0)
    state = replace(state, minions=(dead,))
    w = library.get_by_card_id("metal_wyrm")
    assert effective_mana_cost(w, state, 0) == 5
