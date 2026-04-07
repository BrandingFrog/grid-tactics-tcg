"""Tests for the ActivatedAbility mechanic.

Ratchanter rework v2: "Conjure Common Rat" — spend 2 mana and the turn
action to (a) flat-buff every friendly Rat on the board and (b) tutor a
Common Rat out of the caster's deck via the Phase 14.2 pending_tutor
machinery. Using the ability must consume the player's turn action
(flow through the standard react-window pipeline).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import Action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HP


def _lib() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


def _state_with_ratchanter(
    lib: CardLibrary, mana: int = 5, deck: tuple = (),
) -> tuple[GameState, int]:
    rc_id = lib.get_numeric_id("ratchanter")
    p1 = Player(side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=mana,
                max_mana=10, hand=(), deck=deck, graveyard=())
    p2 = Player(side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=10,
                max_mana=10, hand=(), deck=(), graveyard=())
    rc = MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(0, 2), current_health=30,
    )
    board = Board.empty().place(0, 2, 1)
    state = GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=0,
        minions=(rc,),
        next_minion_id=2,
    )
    return state, rc_id


def test_card_def_loads_activated_ability():
    lib = _lib()
    rc = lib.get_by_card_id("ratchanter")
    assert rc.activated_ability is not None
    ab = rc.activated_ability
    assert ab.name == "Conjure Common Rat"
    assert ab.mana_cost == 2
    assert ab.effect_type == "conjure_rat_and_buff"
    assert ab.summon_card_id == "rat"
    assert ab.target == "none"


def test_legal_actions_enumerates_exactly_one_when_player_has_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    actions = legal_actions(state, lib)
    activate = [a for a in actions if a.action_type == ActionType.ACTIVATE_ABILITY]
    # Untargeted self-ability: exactly one action, target_pos=None.
    assert len(activate) == 1
    assert activate[0].minion_id == 1
    assert activate[0].target_pos is None


def test_legal_actions_does_not_enumerate_with_one_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=1)
    actions = legal_actions(state, lib)
    activate = [a for a in actions if a.action_type == ActionType.ACTIVATE_ABILITY]
    assert activate == []


def test_legal_actions_enumerates_with_exactly_two_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=2)
    actions = legal_actions(state, lib)
    activate = [a for a in actions if a.action_type == ActionType.ACTIVATE_ABILITY]
    assert len(activate) == 1


def test_activate_ability_deducts_two_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=None,
    )
    new_state = resolve_action(state, action, lib)
    assert new_state.players[0].current_mana == 3


def test_activate_ability_consumes_turn_action_when_no_deck_match():
    """With an empty deck, conjure is skipped and the standard react
    window opens immediately."""
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=None,
    )
    new_state = resolve_action(state, action, lib)
    assert new_state.phase == TurnPhase.REACT
    assert new_state.react_player_idx == 1
    assert new_state.pending_action is not None
    assert new_state.pending_action.action_type == ActionType.ACTIVATE_ABILITY


def test_activate_ability_enters_pending_tutor_with_rat_in_deck():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    state, _ = _state_with_ratchanter(lib, mana=5, deck=(rat_id,))
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=None,
    )
    new_state = resolve_action(state, action, lib)
    # Pending tutor must be set; react window deferred until select/decline.
    assert new_state.pending_tutor_player_idx == 0
    assert new_state.phase == TurnPhase.ACTION


def test_activate_ability_rejected_when_insufficient_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=1)
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=None,
    )
    try:
        resolve_action(state, action, lib)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for insufficient mana")
