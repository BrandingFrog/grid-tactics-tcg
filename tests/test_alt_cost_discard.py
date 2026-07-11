"""Alternate discard cost (Dark Wyrm, user 2026-07-11).

A card with ``alt_cost_discard: N`` can be played EITHER for its printed
mana cost (no discards) OR for 0 mana by discarding N OTHER hand cards
(any tribe) to the Exhaust Pile. Unlike ``discard_cost_tribe`` (a
mandatory additional cost), this is a player choice; legal_actions
enumerates both modes when both are affordable. Not variant-gated.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.react_stack import handle_react_action
from grid_tactics.server.preset_deck import get_preset_deck


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture
def state_with_wyrm(library):
    """P1 hand: Dark Wyrm + 3 Common Rats, 5 mana."""
    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=3, deck_p1=deck, deck_p2=deck)
    wyrm = library.get_numeric_id("dark_wyrm")
    rat = library.get_numeric_id("rat")
    p = replace(state.players[0], hand=(wyrm, rat, rat, rat), current_mana=5)
    return replace(state, players=(p, state.players[1]))


def _wyrm_plays(state, library):
    return [
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.PLAY_CARD and a.card_index == 0
    ]


def _drain(state, library):
    guard = 0
    while state.phase == TurnPhase.REACT and guard < 10:
        guard += 1
        state = handle_react_action(state, pass_action(), library)
    return state


def test_dark_wyrm_definition(library):
    wyrm = library.get_by_card_id("dark_wyrm")
    assert wyrm.mana_cost == 5
    assert wyrm.attack == 33 and wyrm.health == 33
    assert wyrm.alt_cost_discard == 3
    assert wyrm.tribe == "Wyrm"
    from grid_tactics.cards import is_dark_mage
    assert not is_dark_mage(wyrm), "Dark Wyrm is a Wyrm, not a Dark Mage"


def test_both_modes_enumerated(state_with_wyrm, library):
    plays = _wyrm_plays(state_with_wyrm, library)
    assert any(not a.discard_card_indices for a in plays), "mana mode missing"
    assert any(a.discard_card_indices for a in plays), "alt mode missing"


def test_only_alt_mode_when_broke(state_with_wyrm, library):
    p = replace(state_with_wyrm.players[0], current_mana=0)
    state = replace(state_with_wyrm, players=(p, state_with_wyrm.players[1]))
    plays = _wyrm_plays(state, library)
    assert plays and all(a.discard_card_indices for a in plays)


def test_unplayable_without_mana_or_fodder(state_with_wyrm, library):
    p = state_with_wyrm.players[0]
    p = replace(p, hand=p.hand[:3], current_mana=0)  # wyrm + only 2 others
    state = replace(state_with_wyrm, players=(p, state_with_wyrm.players[1]))
    assert _wyrm_plays(state, library) == []


def test_alt_play_costs_cards_not_mana(state_with_wyrm, library):
    wyrm_nid = library.get_numeric_id("dark_wyrm")
    plays = _wyrm_plays(state_with_wyrm, library)
    alt = next(a for a in plays if a.discard_card_indices)
    state = _drain(resolve_action(state_with_wyrm, alt, library), library)
    p = state.players[0]
    assert p.current_mana == 5, "alt mode must not spend mana"
    assert len(p.exhaust) == 3, "3 discards go to the Exhaust Pile"
    assert any(m.card_numeric_id == wyrm_nid for m in state.minions)
    # Summon: Draw 1 fired — hand was emptied (wyrm + 3 rats), draw refills.
    assert len(p.hand) == 1


def test_mana_play_costs_mana_not_cards(state_with_wyrm, library):
    plays = _wyrm_plays(state_with_wyrm, library)
    mana_mode = next(a for a in plays if not a.discard_card_indices)
    state = _drain(resolve_action(state_with_wyrm, mana_mode, library), library)
    p = state.players[0]
    assert p.current_mana == 0, "mana mode spends the printed 5"
    assert len(p.exhaust) == 0, "no discards in mana mode"
    assert len(p.hand) == 4, "3 rats kept + 1 drawn by the summon"
