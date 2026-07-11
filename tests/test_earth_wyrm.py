"""Earth Wyrm (user 2026-07-11): standard Wyrm chassis + Leap.

Same 5-mana 33/33 Summon-Draw-1 template as the rest of the cycle; the
twist is Rathopper's existing LEAP move (hop over occupied tiles to the
next empty one, forward in its own column).
"""

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, EffectType, PlayerSide, TriggerType, TurnPhase
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


def test_leap_sacrifice_fires_the_revive_too(library):
    """Audit 2026-07-11: Earth Wyrm's signature line — a Leap sacrifice
    (all-enemy path to past the back row) is the SAME SACRIFICE action,
    so the ON_SACRIFICE revive must fire from mid-board as well."""
    from grid_tactics.action_resolver import resolve_action
    from grid_tactics.actions import Action

    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=29, deck_p1=deck, deck_p2=deck)
    ew_nid = library.get_numeric_id("earth_wyrm")
    dw_nid = library.get_numeric_id("dark_wyrm")
    rat_nid = library.get_numeric_id("rat")

    wyrm = MinionInstance(
        instance_id=1, card_numeric_id=ew_nid,
        owner=PlayerSide.PLAYER_1, position=(2, 3), current_health=33,
    )
    blockers = tuple(
        MinionInstance(
            instance_id=i + 2, card_numeric_id=rat_nid,
            owner=PlayerSide.PLAYER_2, position=(r, 3), current_health=10,
        )
        for i, r in enumerate((3, 4))
    )
    board = state.board.place(2, 3, 1).place(3, 3, 2).place(4, 3, 3)
    p1 = replace(state.players[0], grave=(dw_nid,))
    state = replace(
        state, players=(p1, state.players[1]),
        minions=(wyrm,) + blockers, board=board, next_minion_id=4,
    )
    state = resolve_action(
        state, Action(action_type=ActionType.SACRIFICE, minion_id=1), library,
    )
    assert state.pending_revive_player_idx == 0, (
        "Leap sacrifice must open the Wyrm revive"
    )


def test_sacrifice_revive_preserves_opponent_sacrifices_react(library):
    """Audit fix 2026-07-11: the revive resume must keep the ORIGINAL
    SACRIFICE pending_action so OPPONENT_SACRIFICES reacts (Surgefed
    Sparkbot) still trigger after the revive gate clears."""
    from grid_tactics.action_resolver import resolve_action
    from grid_tactics.actions import Action

    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=31, deck_p1=deck, deck_p2=deck)
    ew_nid = library.get_numeric_id("earth_wyrm")
    dw_nid = library.get_numeric_id("dark_wyrm")
    sb_nid = library.get_numeric_id("surgefed_sparkbot")

    wyrm = MinionInstance(
        instance_id=1, card_numeric_id=ew_nid,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=33,
    )
    p1 = replace(state.players[0], grave=(dw_nid,))
    # P2 holds Surgefed Sparkbot (react: opponent sacrifices while you
    # control no minions) and controls no minions.
    p2 = replace(state.players[1], hand=(sb_nid,), current_mana=10)
    state = replace(
        state, players=(p1, p2), minions=(wyrm,),
        board=state.board.place(4, 2, 1), next_minion_id=2,
    )
    state = resolve_action(
        state, Action(action_type=ActionType.SACRIFICE, minion_id=1), library,
    )
    assert state.pending_revive_player_idx == 0
    # Resolve the revive: place the Dark Wyrm.
    place = next(
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.REVIVE_PLACE
    )
    state = resolve_action(state, place, library)
    # The AFTER_ACTION window opens for P2 — the SACRIFICE must still be
    # the pending action so the OPPONENT_SACRIFICES react is offered.
    assert state.phase == TurnPhase.REACT
    assert state.pending_action is not None
    assert state.pending_action.action_type == ActionType.SACRIFICE
    reacts = [
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.PLAY_REACT
    ]
    assert reacts, "Surgefed Sparkbot's sacrifice react must be offered"


def test_revived_wyrm_fires_its_summon_draw(library):
    """MCQ decision 2026-07-11: revive counts as summon — a Dark Wyrm
    revived by Earth Wyrm's sacrifice draws its Summon card."""
    from grid_tactics.action_resolver import resolve_action
    from grid_tactics.actions import Action

    deck = get_preset_deck(library)
    state, _ = GameState.new_game(seed=41, deck_p1=deck, deck_p2=deck)
    ew_nid = library.get_numeric_id("earth_wyrm")
    dw_nid = library.get_numeric_id("dark_wyrm")
    wyrm = MinionInstance(
        instance_id=1, card_numeric_id=ew_nid,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=33,
    )
    p1 = replace(state.players[0], grave=(dw_nid,), hand=())
    state = replace(
        state, players=(p1, state.players[1]), minions=(wyrm,),
        board=state.board.place(4, 2, 1), next_minion_id=2,
    )
    state = resolve_action(
        state, Action(action_type=ActionType.SACRIFICE, minion_id=1), library,
    )
    place = next(
        a for a in legal_actions(state, library)
        if a.action_type == ActionType.REVIVE_PLACE
    )
    hand_before = len(state.players[0].hand)
    state = resolve_action(state, place, library)
    assert any(m.card_numeric_id == dw_nid for m in state.minions)
    assert len(state.players[0].hand) == hand_before + 1, (
        "the revived Dark Wyrm's Summon: Draw 1 must fire"
    )
