"""Ratchanter conjure + aura tests.

Covers two locked behaviours:
  1. Conjure: deploying Ratchanter adds a "rat" card to the owner's hand.
  2. Aura: while a friendly Ratchanter is alive, every friendly "rat"
     receives +5/+5 (atk + current_health), plus +1/+1 per Dark Matter
     stack on the strongest friendly Ratchanter. The buff is continuous
     -- killing the Ratchanter strips the buff. Multiple Ratchanters do
     not stack; only the strongest applies.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.effect_resolver import resolve_effects_for_trigger
from grid_tactics.enums import PlayerSide, TriggerType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import recompute_ratchanter_aura
from grid_tactics.types import STARTING_HP


def _lib() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


def _empty_state(lib: CardLibrary) -> GameState:
    p1 = Player(side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=10,
                max_mana=10, hand=(), deck=(), graveyard=())
    p2 = Player(side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=10,
                max_mana=10, hand=(), deck=(), graveyard=())
    return GameState(
        board=Board.empty(),
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=0,
        minions=(),
        next_minion_id=1,
    )


def _put(state: GameState, m: MinionInstance) -> GameState:
    return replace(
        state,
        minions=state.minions + (m,),
        board=state.board.place(m.position[0], m.position[1], m.instance_id),
        next_minion_id=max(state.next_minion_id, m.instance_id + 1),
    )


# ---------------------------------------------------------------------------
# Conjure
# ---------------------------------------------------------------------------


def test_ratchanter_on_play_no_longer_conjures_to_hand():
    """Ratchanter's on_play conjure was replaced with an activated ability.

    Deploying Ratchanter must NOT add a rat card to the owner's hand any
    more — the rat is now summoned directly to the board via the activated
    ability (see test_activated_abilities.py).
    """
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")

    state = _empty_state(lib)
    rc = MinionInstance(
        instance_id=1, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    )
    state = _put(state, rc)

    state = resolve_effects_for_trigger(
        state, TriggerType.ON_PLAY, rc, lib, target_pos=None,
    )
    assert rat_id not in state.players[0].hand
    assert state.players[0].hand == ()
    assert state.players[1].hand == ()


# ---------------------------------------------------------------------------
# Aura
# ---------------------------------------------------------------------------


def test_aura_applies_5_5_with_zero_dark_matter():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib)
    rat = MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    )
    rc = MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    )
    state = _put(state, rat)
    state = _put(state, rc)

    state = recompute_ratchanter_aura(state, lib)
    new_rat = state.get_minion(1)
    assert new_rat.attack_bonus == 5
    assert new_rat.current_health == rat_def.health + 5
    assert new_rat.ratchanter_aura == 5


def test_aura_scales_with_dark_matter_stacks():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib)
    rat = MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    )
    rc = MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
        dark_matter_stacks=3,
    )
    state = _put(state, rat)
    state = _put(state, rc)

    state = recompute_ratchanter_aura(state, lib)
    new_rat = state.get_minion(1)
    assert new_rat.attack_bonus == 8  # 5 + 3
    assert new_rat.current_health == rat_def.health + 8
    assert new_rat.ratchanter_aura == 8


def test_aura_strips_when_ratchanter_dies():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = recompute_ratchanter_aura(state, lib)
    assert state.get_minion(1).attack_bonus == 5

    # Kill Ratchanter (drop to 0 hp), strip via recompute.
    rc = state.get_minion(2)
    state = replace(
        state,
        minions=tuple(
            replace(m, current_health=0) if m.instance_id == 2 else m
            for m in state.minions
        ),
    )
    state = recompute_ratchanter_aura(state, lib)
    new_rat = state.get_minion(1)
    assert new_rat.attack_bonus == 0
    assert new_rat.current_health == rat_def.health
    assert new_rat.ratchanter_aura == 0


def test_aura_does_not_buff_opponent_rats():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_2, position=(0, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    state = recompute_ratchanter_aura(state, lib)
    enemy_rat = state.get_minion(1)
    assert enemy_rat.attack_bonus == 0
    assert enemy_rat.ratchanter_aura == 0


def test_multiple_ratchanters_take_max_not_sum():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
        dark_matter_stacks=2,
    ))
    state = _put(state, MinionInstance(
        instance_id=3, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 3), current_health=30,
        dark_matter_stacks=5,
    ))
    state = recompute_ratchanter_aura(state, lib)
    rat = state.get_minion(1)
    assert rat.attack_bonus == 10  # max(5+2, 5+5) = 10, not 7+10
    assert rat.ratchanter_aura == 10


def test_aura_idempotent_on_repeated_recompute():
    lib = _lib()
    rat_id = lib.get_numeric_id("rat")
    rc_id = lib.get_numeric_id("ratchanter")
    rat_def = lib.get_by_card_id("rat")

    state = _empty_state(lib)
    state = _put(state, MinionInstance(
        instance_id=1, card_numeric_id=rat_id,
        owner=PlayerSide.PLAYER_1, position=(4, 0), current_health=rat_def.health,
    ))
    state = _put(state, MinionInstance(
        instance_id=2, card_numeric_id=rc_id,
        owner=PlayerSide.PLAYER_1, position=(4, 2), current_health=30,
    ))
    for _ in range(5):
        state = recompute_ratchanter_aura(state, lib)
    rat = state.get_minion(1)
    assert rat.attack_bonus == 5
    assert rat.current_health == rat_def.health + 5
    assert rat.ratchanter_aura == 5
