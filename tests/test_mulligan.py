"""Tests for the PREGAME mulligan engine helper (user 2026-07-08).

``apply_mulligan(state, player_idx, hand_indices, rng)`` is a pure
immutable-dataclass transform: remove the picked cards from hand, shuffle
them into the deck, draw the same number of replacements. Invariants:

  - hand size preserved, deck size preserved
  - multiset(hand + deck) preserved (no card created or destroyed)
  - empty pick is a no-op (same state object)
  - kept cards preserve their relative order; replacements append at end
  - duplicate / out-of-range indices raise ValueError
  - deck-short defensive branch draws what it can
"""
from collections import Counter
from dataclasses import replace

import pytest

from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.board import Board
from grid_tactics.game_state import GameState, apply_mulligan
from grid_tactics.player import Player
from grid_tactics.rng import GameRNG


DECK = tuple(range(40))


def _fresh_state(seed=42):
    state, rng = GameState.new_game(seed, DECK, DECK)
    return state, rng


def _multiset(player):
    return Counter(player.hand) + Counter(player.deck)


def test_empty_pick_is_noop():
    state, rng = _fresh_state()
    new_state, drawn = apply_mulligan(state, 0, [], rng)
    assert new_state is state
    assert drawn == ()


def test_full_hand_mulligan_invariants():
    state, rng = _fresh_state()
    for idx in (0, 1):
        before = state.players[idx]
        all_indices = list(range(len(before.hand)))
        new_state, drawn = apply_mulligan(state, idx, all_indices, rng)
        after = new_state.players[idx]
        assert len(after.hand) == len(before.hand)
        assert len(after.deck) == len(before.deck)
        assert _multiset(after) == _multiset(before)
        assert len(drawn) == len(before.hand)
        # Replacements are exactly the new hand (full redraw).
        assert after.hand == drawn
        # Other player untouched.
        other = new_state.players[1 - idx]
        assert other is state.players[1 - idx]


def test_partial_mulligan_keeps_order_and_appends_replacements():
    state, rng = _fresh_state()
    p2 = state.players[1]
    assert len(p2.hand) == 4  # P2 opening hand
    keep = (p2.hand[0], p2.hand[2])
    new_state, drawn = apply_mulligan(state, 1, [1, 3], rng)
    after = new_state.players[1]
    assert len(after.hand) == 4
    assert after.hand[:2] == keep          # kept cards keep relative order
    assert after.hand[2:] == drawn         # replacements append at end
    assert len(drawn) == 2
    assert _multiset(after) == _multiset(p2)


def test_returned_cards_enter_the_deck():
    state, rng = _fresh_state()
    p1 = state.players[0]
    returned = p1.hand[0]
    new_state, _ = apply_mulligan(state, 0, [0], rng)
    after = new_state.players[0]
    # The returned copy is somewhere in hand+deck (could be redrawn), and
    # total copies of it are conserved.
    before_copies = _multiset(p1)[returned]
    after_copies = _multiset(after)[returned]
    assert after_copies == before_copies


def test_duplicate_indices_raise():
    state, rng = _fresh_state()
    with pytest.raises(ValueError):
        apply_mulligan(state, 0, [0, 0], rng)


def test_out_of_range_indices_raise():
    state, rng = _fresh_state()
    with pytest.raises(ValueError):
        apply_mulligan(state, 0, [99], rng)
    with pytest.raises(ValueError):
        apply_mulligan(state, 0, [-1], rng)


def test_deck_short_case_draws_what_it_can():
    """With an EMPTY deck, mulliganing k cards shuffles them in and draws
    k straight back — hand is a permutation of itself, deck stays empty."""
    p1 = Player.new(PlayerSide.PLAYER_1, ())
    p1 = replace(p1, hand=(5, 7))
    p2 = Player.new(PlayerSide.PLAYER_2, ())
    state = GameState(
        board=Board.empty(),
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=0,
    )
    new_state, drawn = apply_mulligan(state, 0, [0, 1], GameRNG(0))
    after = new_state.players[0]
    assert sorted(after.hand) == [5, 7]
    assert after.deck == ()
    assert sorted(drawn) == [5, 7]


def test_deterministic_with_same_rng_seed():
    state, _ = _fresh_state(seed=7)
    a, drawn_a = apply_mulligan(state, 0, [0, 1], GameRNG(123))
    b, drawn_b = apply_mulligan(state, 0, [0, 1], GameRNG(123))
    assert drawn_a == drawn_b
    assert a.players[0].hand == b.players[0].hand
    assert a.players[0].deck == b.players[0].deck


def test_rng_default_is_seeded_from_state():
    state, _ = _fresh_state(seed=99)
    a, drawn_a = apply_mulligan(state, 0, [0])
    b, drawn_b = apply_mulligan(state, 0, [0])
    assert drawn_a == drawn_b
    assert a.players[0].deck == b.players[0].deck
