"""Rest rules experiment (user 2026-07-10, v2) — GT_MANUAL_DRAW=1.

Variant rules under test:
  - NO turn-start auto-draw (and no turn-start empty-deck fatigue).
  - DRAW is NOT a legal action (the v1 Draw button/action was removed the
    same day) — PASS is the rest action instead.
  - PASS (rest): the passer gains +1 mana (capped at MAX_MANA_CAP) AND
    draws a card (overdraw-burns on a full hand; empty deck skips it).
  - Handshake payout: BOTH players gain +1 mana AND draw a card.

The rest of the suite runs the standard rules (env flag unset); every test
here flips the flag via monkeypatch.setenv — types.manual_draw_variant()
reads the env at call time.
"""

import pytest

from grid_tactics.actions import draw_action, pass_action
from grid_tactics.action_resolver import resolve_action
from grid_tactics.legal_actions import legal_actions
from grid_tactics.types import MAX_MANA_CAP, manual_draw_variant


@pytest.fixture
def variant(monkeypatch):
    monkeypatch.setenv("GT_MANUAL_DRAW", "1")
    assert manual_draw_variant()


@pytest.fixture
def card_library():
    from pathlib import Path

    from grid_tactics.card_library import CardLibrary

    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture
def new_game_state(card_library):
    from grid_tactics.game_state import GameState
    from grid_tactics.server.preset_deck import get_preset_deck

    deck = get_preset_deck(card_library)
    state, _rng = GameState.new_game(seed=7, deck_p1=deck, deck_p2=deck)
    return state


def test_draw_is_not_legal_even_in_variant(variant, new_game_state, card_library):
    actions = legal_actions(new_game_state, card_library)
    assert draw_action() not in actions


def test_pass_rest_grants_mana_and_draw(variant, new_game_state, card_library):
    state = new_game_state
    idx = state.active_player_idx
    mana_before = state.players[idx].current_mana
    hand_before = len(state.players[idx].hand)
    deck_before = len(state.players[idx].deck)
    state = resolve_action(state, pass_action(), card_library)
    assert state.players[idx].current_mana == min(mana_before + 1, MAX_MANA_CAP)
    assert len(state.players[idx].hand) == hand_before + 1
    assert len(state.players[idx].deck) == deck_before - 1


def test_pass_rest_mana_capped_still_draws(variant, new_game_state, card_library):
    from dataclasses import replace

    state = new_game_state
    idx = state.active_player_idx
    players = list(state.players)
    players[idx] = replace(players[idx], current_mana=MAX_MANA_CAP)
    state = replace(state, players=tuple(players))
    hand_before = len(state.players[idx].hand)
    state = resolve_action(state, pass_action(), card_library)
    assert state.players[idx].current_mana == MAX_MANA_CAP
    assert len(state.players[idx].hand) == hand_before + 1


def test_pass_rest_empty_deck_mana_only(variant, new_game_state, card_library):
    from dataclasses import replace

    state = new_game_state
    idx = state.active_player_idx
    players = list(state.players)
    players[idx] = replace(players[idx], deck=())
    state = replace(state, players=tuple(players))
    mana_before = state.players[idx].current_mana
    hand_before = len(state.players[idx].hand)
    hp_before = state.players[idx].hp
    state = resolve_action(state, pass_action(), card_library)
    assert state.players[idx].current_mana == mana_before + 1
    assert len(state.players[idx].hand) == hand_before  # no draw, no fatigue
    assert state.players[idx].hp == hp_before


def test_no_turn_start_autodraw(variant, new_game_state, card_library):
    """The incoming player must NOT auto-draw at turn start; only their own
    rest / handshake draws touch their hand."""
    from grid_tactics.enums import TurnPhase
    from grid_tactics.react_stack import (
        enter_end_of_turn,
        enter_start_of_turn,
        handle_react_action,
    )

    state = new_game_state
    p1 = state.active_player_idx
    p2 = 1 - p1
    p2_hand_before = len(state.players[p2].hand)
    state = resolve_action(state, pass_action(), card_library)
    guard = 0
    while state.active_player_idx != p2 or state.phase != TurnPhase.ACTION:
        guard += 1
        assert guard < 20, f"turn never flipped: phase={state.phase}"
        if state.phase == TurnPhase.REACT:
            state = handle_react_action(state, pass_action(), card_library)
        elif state.phase == TurnPhase.ACTION:
            state = enter_end_of_turn(state, card_library)
        else:
            state = enter_start_of_turn(state, card_library)
    # Only one pass happened (no handshake) — P2's hand unchanged.
    assert len(state.players[p2].hand) == p2_hand_before


def test_handshake_pays_out_mana_and_draw_for_both(variant, new_game_state, card_library):
    from dataclasses import replace

    from grid_tactics.react_stack import _resolve_handshake_payout

    state = replace(new_game_state, handshake_pending=True)
    hands_before = [len(p.hand) for p in state.players]
    mana_before = [p.current_mana for p in state.players]
    state = _resolve_handshake_payout(state)
    for i in (0, 1):
        assert len(state.players[i].hand) == hands_before[i] + 1
        assert state.players[i].current_mana == min(mana_before[i] + 1, MAX_MANA_CAP)
    assert state.handshake_pending is False
