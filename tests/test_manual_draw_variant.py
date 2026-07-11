"""Rules experiment (user 2026-07-10, v3) — GT_MANUAL_DRAW=1.

Variant rules under test:
  - NO turn-start auto-draw (and no turn-start empty-deck fatigue).
  - REST (on the reserved DRAW action slot) consumes the turn action for
    +1 mana AND +1 draw; PASS is separate and gives NO benefit
    (user clarification 2026-07-11, v4).
  - MAGIC casts do not consume the turn action — after the cast (and its
    react windows) play returns to the caster's ACTION phase.
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


def test_rest_is_legal_in_variant(variant, new_game_state, card_library):
    """v4: the DRAW slot is the REST action — legal in the variant."""
    actions = legal_actions(new_game_state, card_library)
    assert draw_action() in actions


def test_rest_grants_mana_and_draw(variant, new_game_state, card_library):
    state = new_game_state
    idx = state.active_player_idx
    mana_before = state.players[idx].current_mana
    hand_before = len(state.players[idx].hand)
    deck_before = len(state.players[idx].deck)
    state = resolve_action(state, draw_action(), card_library)
    assert state.players[idx].current_mana == min(mana_before + 1, MAX_MANA_CAP)
    assert len(state.players[idx].hand) == hand_before + 1
    assert len(state.players[idx].deck) == deck_before - 1


def test_rest_empty_deck_mana_only(variant, new_game_state, card_library):
    from dataclasses import replace

    state = new_game_state
    idx = state.active_player_idx
    players = list(state.players)
    players[idx] = replace(players[idx], deck=())
    state = replace(state, players=tuple(players))
    mana_before = state.players[idx].current_mana
    hand_before = len(state.players[idx].hand)
    hp_before = state.players[idx].hp
    state = resolve_action(state, draw_action(), card_library)
    assert state.players[idx].current_mana == mana_before + 1
    assert len(state.players[idx].hand) == hand_before  # no draw, no fatigue
    assert state.players[idx].hp == hp_before


def test_pass_grants_nothing(variant, new_game_state, card_library):
    """v4: PASS is the no-benefit skip — Rest is the rewarded one."""
    state = new_game_state
    idx = state.active_player_idx
    mana_before = state.players[idx].current_mana
    hand_before = len(state.players[idx].hand)
    state = resolve_action(state, pass_action(), card_library)
    assert state.players[idx].current_mana == mana_before
    assert len(state.players[idx].hand) == hand_before


def test_magic_cast_returns_to_caster(variant, new_game_state, card_library):
    """v3: a MAGIC cast does not consume the turn action — after its react
    windows resolve, play returns to the caster's ACTION phase on the
    SAME turn."""
    from dataclasses import replace

    from grid_tactics.enums import ActionType, TurnPhase
    from grid_tactics.react_stack import handle_react_action

    state = new_game_state
    caster = state.active_player_idx
    turn_before = state.turn_number
    rain_nid = card_library.get_numeric_id("acidic_rain")
    players = list(state.players)
    players[caster] = replace(players[caster], hand=(rain_nid,), current_mana=10)
    state = replace(state, players=tuple(players))

    plays = [
        a for a in legal_actions(state, card_library)
        if a.action_type == ActionType.PLAY_CARD
    ]
    assert plays, "Acidic Rain must be castable"
    state = resolve_action(state, plays[0], card_library)
    guard = 0
    while state.phase == TurnPhase.REACT and guard < 10:
        guard += 1
        state = handle_react_action(state, pass_action(), card_library)
    assert state.phase == TurnPhase.ACTION
    assert state.active_player_idx == caster, "turn must NOT flip after magic"
    assert state.turn_number == turn_before
    assert state.magic_free_action_pending is False
    # The caster still holds their action: PASS (at least) is legal.
    assert any(
        a.action_type == ActionType.PASS
        for a in legal_actions(state, card_library)
    )


def _drain_to_action(state, card_library):
    """Pass through react windows / bookend phases until an ACTION phase.
    React-window passes do NOT touch the Handshake streak."""
    from grid_tactics.enums import TurnPhase
    from grid_tactics.react_stack import (
        enter_end_of_turn,
        enter_start_of_turn,
        handle_react_action,
    )

    guard = 0
    while state.phase != TurnPhase.ACTION and guard < 20:
        guard += 1
        if state.phase == TurnPhase.REACT:
            state = handle_react_action(state, pass_action(), card_library)
        elif state.phase == TurnPhase.START_OF_TURN:
            state = enter_start_of_turn(state, card_library)
        elif state.phase == TurnPhase.END_OF_TURN:
            state = enter_end_of_turn(state, card_library)
    assert state.phase == TurnPhase.ACTION, f"stuck in {state.phase}"
    return state


def test_rest_counts_toward_handshake(variant, new_game_state, card_library):
    """v4 (user 2026-07-11): REST advances the Handshake streak like PASS —
    a rest answered by a rest (or pass) seals the Handshake."""
    state = new_game_state
    first = state.active_player_idx
    # First skip: REST — streak 1, no handshake yet.
    state = resolve_action(state, draw_action(), card_library)
    assert state.consecutive_passes == 1
    assert state.handshake_pending is False
    # Drain the after-action window; the turn flips to the opponent.
    state = _drain_to_action(state, card_library)
    assert state.active_player_idx == 1 - first
    # Opponent answers with a REST — Handshake seals, streak resets.
    state = resolve_action(state, draw_action(), card_library)
    assert state.handshake_pending is True
    assert state.consecutive_passes == 0


def test_non_rest_action_breaks_streak(variant, new_game_state, card_library):
    from dataclasses import replace

    from grid_tactics.enums import ActionType

    state = new_game_state
    state = resolve_action(state, pass_action(), card_library)
    assert state.consecutive_passes == 1
    state = _drain_to_action(state, card_library)
    # A magic cast (free action) is NOT a skip — it breaks the streak.
    caster = state.active_player_idx
    rain_nid = card_library.get_numeric_id("acidic_rain")
    players = list(state.players)
    players[caster] = replace(players[caster], hand=(rain_nid,), current_mana=10)
    state = replace(state, players=tuple(players))
    plays = [a for a in legal_actions(state, card_library)
             if a.action_type == ActionType.PLAY_CARD]
    state = resolve_action(state, plays[0], card_library)
    assert state.consecutive_passes == 0


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


def test_rest_and_pass_mutually_exclusive(variant, new_game_state, card_library):
    """v4.2 (user 2026-07-11): only ONE skip is offered at a time — REST
    before any magic is cast, never both."""
    actions = legal_actions(new_game_state, card_library)
    assert draw_action() in actions
    assert pass_action() not in actions


def test_magic_transforms_rest_into_pass(variant, new_game_state, card_library):
    """v4.2: after casting a MAGIC this turn, the returned action offers
    PASS instead of REST — no mana+draw skip on the free action."""
    from dataclasses import replace

    from grid_tactics.enums import ActionType, TurnPhase
    from grid_tactics.react_stack import handle_react_action

    state = new_game_state
    caster = state.active_player_idx
    rain_nid = card_library.get_numeric_id("acidic_rain")
    players = list(state.players)
    players[caster] = replace(players[caster], hand=(rain_nid,), current_mana=10)
    state = replace(state, players=tuple(players))
    plays = [a for a in legal_actions(state, card_library)
             if a.action_type == ActionType.PLAY_CARD]
    state = resolve_action(state, plays[0], card_library)
    guard = 0
    while state.phase == TurnPhase.REACT and guard < 10:
        guard += 1
        state = handle_react_action(state, pass_action(), card_library)
    assert state.phase == TurnPhase.ACTION
    assert state.magic_cast_this_turn is True
    actions = legal_actions(state, card_library)
    assert pass_action() in actions
    assert draw_action() not in actions, "REST must transform into PASS after a magic"


def test_rest_pass_transform_resets_next_turn(variant, new_game_state, card_library):
    """v4.2: magic_cast_this_turn is per-turn — the opponent's fresh turn
    (and the caster's next turn) offer REST again."""
    from dataclasses import replace

    from grid_tactics.enums import ActionType, TurnPhase
    from grid_tactics.react_stack import handle_react_action

    state = new_game_state
    caster = state.active_player_idx
    rain_nid = card_library.get_numeric_id("acidic_rain")
    players = list(state.players)
    players[caster] = replace(players[caster], hand=(rain_nid,), current_mana=10)
    state = replace(state, players=tuple(players))
    plays = [a for a in legal_actions(state, card_library)
             if a.action_type == ActionType.PLAY_CARD]
    state = resolve_action(state, plays[0], card_library)
    guard = 0
    while state.phase == TurnPhase.REACT and guard < 10:
        guard += 1
        state = handle_react_action(state, pass_action(), card_library)
    # Spend the returned action on the (transformed) PASS, then drain to
    # the opponent's ACTION phase.
    state = resolve_action(state, pass_action(), card_library)
    state = _drain_to_action(state, card_library)
    assert state.active_player_idx != caster
    assert state.magic_cast_this_turn is False
    actions = legal_actions(state, card_library)
    assert draw_action() in actions
    assert pass_action() not in actions
