"""Manual-draw rules experiment (user 2026-07-10) — GT_MANUAL_DRAW=1.

Variant rules under test:
  - DRAW is a legal main-phase action (non-empty deck); consumes the action.
  - NO turn-start auto-draw (and no turn-start empty-deck fatigue).
  - PASS grants the passer +1 mana immediately (capped at MAX_MANA_CAP).
  - Handshake payout: BOTH players draw a card (no mana).

The rest of the suite runs the standard rules (env flag unset); every test
here flips the flag via monkeypatch.setenv — types.manual_draw_variant()
reads the env at call time.
"""

import pytest

from grid_tactics.actions import draw_action, pass_action
from grid_tactics.action_resolver import resolve_action
from grid_tactics.enums import ActionType
from grid_tactics.legal_actions import legal_actions
from grid_tactics.types import MAX_MANA_CAP, manual_draw_variant


@pytest.fixture
def variant(monkeypatch):
    monkeypatch.setenv("GT_MANUAL_DRAW", "1")
    assert manual_draw_variant()


@pytest.fixture
def game(new_game_state, card_library):
    return new_game_state, card_library


@pytest.fixture
def new_game_state(card_library):
    from grid_tactics.game_state import GameState
    from grid_tactics.server.preset_deck import get_preset_deck

    deck = get_preset_deck(card_library)
    state, _rng = GameState.new_game(seed=7, deck_p1=deck, deck_p2=deck)
    return state


@pytest.fixture
def card_library():
    from pathlib import Path

    from grid_tactics.card_library import CardLibrary

    return CardLibrary.from_directory(Path("data/cards"))


def test_draw_is_legal_in_variant(variant, new_game_state, card_library):
    actions = legal_actions(new_game_state, card_library)
    assert draw_action() in actions


def test_draw_is_not_legal_under_standard_rules(monkeypatch, new_game_state, card_library):
    monkeypatch.setenv("GT_MANUAL_DRAW", "0")
    actions = legal_actions(new_game_state, card_library)
    assert draw_action() not in actions


def test_draw_action_draws_one_card(variant, new_game_state, card_library):
    state = new_game_state
    idx = state.active_player_idx
    hand_before = len(state.players[idx].hand)
    deck_before = len(state.players[idx].deck)
    state = resolve_action(state, draw_action(), card_library)
    assert len(state.players[idx].hand) == hand_before + 1
    assert len(state.players[idx].deck) == deck_before - 1


def test_pass_grants_immediate_mana(variant, new_game_state, card_library):
    state = new_game_state
    idx = state.active_player_idx
    mana_before = state.players[idx].current_mana
    state = resolve_action(state, pass_action(), card_library)
    assert state.players[idx].current_mana >= min(mana_before + 1, MAX_MANA_CAP)


def test_pass_mana_capped(variant, new_game_state, card_library):
    from dataclasses import replace

    state = new_game_state
    idx = state.active_player_idx
    players = list(state.players)
    players[idx] = replace(players[idx], current_mana=MAX_MANA_CAP)
    state = replace(state, players=tuple(players))
    state = resolve_action(state, pass_action(), card_library)
    assert state.players[idx].current_mana == MAX_MANA_CAP


def test_no_turn_start_autodraw(variant, new_game_state, card_library):
    """After a full pass-through of a turn, the incoming player must NOT
    have auto-drawn: their hand only changes via explicit DRAW / handshake."""
    state = new_game_state
    p1 = state.active_player_idx
    p2 = 1 - p1
    p2_hand_before = len(state.players[p2].hand)
    # P1 passes; the server-side auto-advance is driven by resolve_action
    # chains in events.py, but the engine helpers flip the turn directly
    # when both react windows close. Simulate via the react_stack helpers.
    state = resolve_action(state, pass_action(), card_library)
    # Drain any react window with passes until it's P2's ACTION phase.
    from grid_tactics.enums import TurnPhase
    from grid_tactics.react_stack import handle_react_action
    from grid_tactics.react_stack import enter_end_of_turn

    guard = 0
    while state.active_player_idx != p2 or state.phase != TurnPhase.ACTION:
        guard += 1
        assert guard < 20, f"turn never flipped: phase={state.phase}"
        if state.phase == TurnPhase.REACT:
            state = handle_react_action(state, pass_action(), card_library)
        elif state.phase == TurnPhase.ACTION:
            state = enter_end_of_turn(state, card_library)
        else:
            from grid_tactics.react_stack import enter_start_of_turn
            state = enter_start_of_turn(state, card_library)
    # No auto-draw for the incoming player: hand unchanged (the handshake
    # didn't fire — only one pass).
    assert len(state.players[p2].hand) == p2_hand_before


def test_handshake_pays_out_draws_not_mana(variant, new_game_state, card_library):
    from grid_tactics.react_stack import _resolve_handshake_payout
    from dataclasses import replace

    state = replace(new_game_state, handshake_pending=True)
    hands_before = [len(p.hand) for p in state.players]
    mana_before = [p.current_mana for p in state.players]
    state = _resolve_handshake_payout(state)
    for i in (0, 1):
        assert len(state.players[i].hand) == hands_before[i] + 1
        assert state.players[i].current_mana == mana_before[i]
    assert state.handshake_pending is False
