"""Tests for the ActivatedAbility mechanic.

First user: Ratchanter — "Summon Rat (1)" — spend 1 mana and the turn
action to summon a fresh rat token to any empty tile in the activator's
own two rows. The summoned rat must immediately benefit from
Ratchanter's aura, and using the ability must consume the player's
turn action (flow through the standard react-window pipeline).
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


def _state_with_ratchanter(lib: CardLibrary, mana: int = 5) -> tuple[GameState, int]:
    rc_id = lib.get_numeric_id("ratchanter")
    p1 = Player(side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=mana,
                max_mana=10, hand=(), deck=(), graveyard=())
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
    assert ab.name == "Summon Rat"
    assert ab.mana_cost == 1
    assert ab.effect_type == "summon_token"
    assert ab.summon_card_id == "rat"
    assert ab.target == "own_side_empty"


def test_legal_actions_enumerates_when_player_has_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    actions = legal_actions(state, lib)
    activate = [a for a in actions if a.action_type == ActionType.ACTIVATE_ABILITY]
    # P1 own rows = (0, 1) -> 5 cols * 2 rows = 10 tiles, minus the
    # one occupied by Ratchanter at (0, 2) = 9 valid targets.
    assert len(activate) == 9
    for a in activate:
        assert a.minion_id == 1
        assert a.target_pos[0] in (0, 1)
        assert a.target_pos != (0, 2)


def test_legal_actions_does_not_enumerate_with_zero_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=0)
    actions = legal_actions(state, lib)
    activate = [a for a in actions if a.action_type == ActionType.ACTIVATE_ABILITY]
    assert activate == []


def test_legal_actions_only_empty_own_side_tiles():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    # Place an enemy on (1, 1) to confirm own-side filter ignores enemies
    # but excludes the occupied tile.
    enemy_id = lib.get_numeric_id("rat")
    enemy = MinionInstance(
        instance_id=99, card_numeric_id=enemy_id,
        owner=PlayerSide.PLAYER_2, position=(1, 1), current_health=10,
    )
    state = replace(
        state,
        minions=state.minions + (enemy,),
        board=state.board.place(1, 1, 99),
        next_minion_id=100,
    )
    actions = legal_actions(state, lib)
    activate = [a for a in actions if a.action_type == ActionType.ACTIVATE_ABILITY]
    targets = {a.target_pos for a in activate}
    assert (0, 2) not in targets   # Ratchanter
    assert (1, 1) not in targets   # enemy occupies it
    assert all(p[0] in (0, 1) for p in targets)
    assert len(targets) == 8


def test_activate_ability_summons_rat_and_deducts_mana():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    state, _ = _state_with_ratchanter(lib, mana=5)
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=(1, 0),
    )
    new_state = resolve_action(state, action, lib)
    # Mana deducted
    assert new_state.players[0].current_mana == 4
    # Rat exists at (1, 0), owned by P1
    rat = None
    for m in new_state.minions:
        if m.position == (1, 0):
            rat = m
            break
    assert rat is not None
    assert rat.card_numeric_id == rat_id
    assert rat.owner == PlayerSide.PLAYER_1


def test_summoned_rat_picks_up_ratchanter_aura():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=(1, 0),
    )
    new_state = resolve_action(state, action, lib)
    rat = None
    for m in new_state.minions:
        if m.position == (1, 0):
            rat = m
            break
    assert rat is not None
    # +5/+5 aura with zero Dark Matter stacks
    assert rat.attack_bonus == 5
    assert rat.ratchanter_aura == 5


def test_activate_ability_consumes_turn_action():
    """After activating, the game should be in REACT phase (the standard
    main-phase pipeline opens a react window for the opponent)."""
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=(1, 0),
    )
    new_state = resolve_action(state, action, lib)
    assert new_state.phase == TurnPhase.REACT
    assert new_state.react_player_idx == 1
    assert new_state.pending_action is not None
    assert new_state.pending_action.action_type == ActionType.ACTIVATE_ABILITY


def test_activate_ability_rejected_when_target_occupied():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=5)
    # Try to summon onto Ratchanter's own tile
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=(0, 2),
    )
    try:
        resolve_action(state, action, lib)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for occupied target tile")


def test_activate_ability_rejected_when_insufficient_mana():
    lib = _lib()
    state, _ = _state_with_ratchanter(lib, mana=0)
    action = Action(
        action_type=ActionType.ACTIVATE_ABILITY,
        minion_id=1,
        target_pos=(1, 0),
    )
    try:
        resolve_action(state, action, lib)
    except ValueError:
        return
    raise AssertionError("Expected ValueError for insufficient mana")
