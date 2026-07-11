"""Light Wyrm (user 2026-07-11): per-discarded-Wyrm discount + summon
from the Exhaust Pile.

- cost_reduction='wyrms_discarded': -1 per Wyrm-tribe card in the owner's
  Exhaust Pile (including Light Wyrm copies — 'it includes itself').
- playable_from_exhaust + exhaust_play_discount=2: while in the Exhaust
  Pile it may be summoned from there for effective cost - 2 (floor 0),
  consuming the turn action and running the normal summon flow.
- The user's example: Dark Wyrm's alt cost discards Light Wyrm + 2 other
  Wyrms -> Light Wyrm costs 5-3 = 2, and 2-2 = 0 from the Exhaust Pile.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import Action, pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import effective_mana_cost, legal_actions
from grid_tactics.react_stack import handle_react_action
from grid_tactics.server.preset_deck import get_preset_deck


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def _state(library, *, hand=(), exhaust=(), mana=5):
    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=23, deck_p1=deck, deck_p2=deck)
    p = replace(
        state.players[0], hand=tuple(hand), exhaust=tuple(exhaust),
        current_mana=mana,
    )
    return replace(state, players=(p, state.players[1]))


def _drain(state, library):
    guard = 0
    while state.phase == TurnPhase.REACT and guard < 10:
        guard += 1
        state = handle_react_action(state, pass_action(), library)
    return state


def test_definition(library):
    w = library.get_by_card_id("light_wyrm")
    assert w.mana_cost == 5
    assert w.attack == 33 and w.health == 33
    assert w.cost_reduction == "wyrms_discarded"
    assert w.playable_from_exhaust is True
    assert w.exhaust_play_discount == 2


def test_cost_scales_with_discarded_wyrms(library):
    lw = library.get_by_card_id("light_wyrm")
    lw_nid = library.get_numeric_id("light_wyrm")
    dw_nid = library.get_numeric_id("dark_wyrm")
    rat_nid = library.get_numeric_id("rat")
    # Empty exhaust: full price.
    assert effective_mana_cost(lw, _state(library), 0, library) == 5
    # 2 Wyrms + a rat discarded: -2 (rat doesn't count).
    st = _state(library, exhaust=(dw_nid, rat_nid, dw_nid))
    assert effective_mana_cost(lw, st, 0, library) == 3
    # Its own copies count ('it includes itself').
    st = _state(library, exhaust=(lw_nid, dw_nid, dw_nid))
    assert effective_mana_cost(lw, st, 0, library) == 2
    # Floor at 0.
    st = _state(library, exhaust=(lw_nid,) * 7)
    assert effective_mana_cost(lw, st, 0, library) == 0


def test_dark_wyrm_line_makes_it_free_from_exhaust(library):
    """The user's exact example: LW + 2 Wyrms in exhaust -> 5-3 = 2, then
    -2 from-exhaust discount -> the PLAY_FROM_EXHAUST is legal at 0 mana
    and pays nothing."""
    lw_nid = library.get_numeric_id("light_wyrm")
    dw_nid = library.get_numeric_id("dark_wyrm")
    fw_nid = library.get_numeric_id("flame_wyrm")
    state = _state(library, exhaust=(lw_nid, dw_nid, fw_nid), mana=0)
    plays = [
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.PLAY_FROM_EXHAUST
    ]
    assert plays, "must be summonable from the Exhaust Pile at 0 mana"
    assert all(state.players[0].exhaust[a.card_index] == lw_nid for a in plays)

    state = _drain(resolve_action(state, plays[0], library), library)
    p = state.players[0]
    assert p.current_mana == 0, "the summon was free"
    assert lw_nid not in p.exhaust, "Light Wyrm left the Exhaust Pile"
    assert any(m.card_numeric_id == lw_nid for m in state.minions)
    # Summon: Draw 1 fired through the normal flow.
    assert len(p.hand) == 1


def test_exhaust_play_pays_reduced_cost(library):
    """Only Light Wyrm itself in exhaust: cost 5-1(own copy)-2 = 2."""
    lw_nid = library.get_numeric_id("light_wyrm")
    state = _state(library, exhaust=(lw_nid,), mana=2)
    plays = [
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.PLAY_FROM_EXHAUST
    ]
    assert plays
    state = _drain(resolve_action(state, plays[0], library), library)
    assert state.players[0].current_mana == 0


def test_not_playable_from_exhaust_without_mana(library):
    lw_nid = library.get_numeric_id("light_wyrm")
    state = _state(library, exhaust=(lw_nid,), mana=1)  # needs 2
    plays = [
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.PLAY_FROM_EXHAUST
    ]
    assert plays == []


def test_other_cards_not_playable_from_exhaust(library):
    rat_nid = library.get_numeric_id("rat")
    state = _state(library, exhaust=(rat_nid,), mana=10)
    plays = [
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.PLAY_FROM_EXHAUST
    ]
    assert plays == []
