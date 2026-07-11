"""Earth Wyrm (user 2026-07-11): standard Wyrm chassis + Leap.

Same 5-mana 33/33 Summon-Draw-1 template as the rest of the cycle; the
twist is Rathopper's existing LEAP move (hop over occupied tiles to the
next empty one, forward in its own column).
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, EffectType, PlayerSide, TriggerType
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.server.preset_deck import get_preset_deck


@pytest.fixture(scope="module")
def library():
    return CardLibrary.from_directory(Path("data/cards"))


def test_definition(library):
    w = library.get_by_card_id("earth_wyrm")
    assert w.mana_cost == 5
    assert w.attack == 33 and w.health == 33
    assert w.tribe == "Wyrm"
    assert any(
        e.effect_type == EffectType.LEAP and e.trigger == TriggerType.ON_MOVE
        for e in w.effects
    )
    assert any(e.effect_type == EffectType.DRAW for e in w.effects)


def test_leap_over_blocker(library):
    """With a blocker directly ahead, a normal minion is stuck; Earth Wyrm's
    Leap enumerates the move to the empty tile beyond it."""
    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=17, deck_p1=deck, deck_p2=deck)
    wyrm_nid = library.get_numeric_id("earth_wyrm")
    rat_nid = library.get_numeric_id("rat")
    wyrm = MinionInstance(
        instance_id=1, card_numeric_id=wyrm_nid,
        owner=PlayerSide.PLAYER_1, position=(1, 2), current_health=33,
    )
    blocker = MinionInstance(
        instance_id=2, card_numeric_id=rat_nid,
        owner=PlayerSide.PLAYER_2, position=(2, 2), current_health=10,
    )
    board = state.board.place(1, 2, 1).place(2, 2, 2)
    state = replace(
        state, minions=(wyrm, blocker), board=board, next_minion_id=3,
    )
    moves = [
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.MOVE and a.minion_id == 1
    ]
    assert any(
        a.position == (3, 2) for a in moves
    ), "Leap must hop the blocker to the next empty tile"


def test_sacrifice_opens_wyrm_revive_excluding_earth_wyrm(library):
    """User 2026-07-11: 'on sacrifice you can revive any wyrm except earth
    wyrm.' Sacrificing Earth Wyrm on the enemy back row deals its 🗡️ to
    the face AND opens the revive picker filtered to non-Earth Wyrms."""
    from grid_tactics.action_resolver import resolve_action
    from grid_tactics.actions import Action
    from grid_tactics.legal_actions import revive_grave_matches

    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=19, deck_p1=deck, deck_p2=deck)
    ew_nid = library.get_numeric_id("earth_wyrm")
    dw_nid = library.get_numeric_id("dark_wyrm")
    rat_nid = library.get_numeric_id("rat")

    wyrm = MinionInstance(
        instance_id=1, card_numeric_id=ew_nid,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=33,
    )
    # Grave: another Earth Wyrm (excluded), a Dark Wyrm (pickable), a rat
    # (wrong tribe).
    p1 = replace(
        state.players[0], grave=(ew_nid, dw_nid, rat_nid),
    )
    state = replace(
        state,
        players=(p1, state.players[1]),
        minions=(wyrm,),
        board=state.board.place(4, 2, 1),
        next_minion_id=2,
    )
    opp_hp_before = state.players[1].hp
    state = resolve_action(
        state, Action(action_type=ActionType.SACRIFICE, minion_id=1), library,
    )
    assert state.players[1].hp == opp_hp_before - 33, "sacrifice damage lands"
    assert state.pending_revive_player_idx == 0, "revive picker opens"
    assert state.pending_revive_tribe == "Wyrm"
    assert state.pending_revive_exclude_card_id == "earth_wyrm"
    # Grave now also holds the sacrificed Earth Wyrm — still not pickable.
    matches = revive_grave_matches(state, library)
    pickable = {state.players[0].grave[i] for i in matches}
    assert pickable == {dw_nid}, "only the Dark Wyrm is revivable"
