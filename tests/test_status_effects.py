"""Phase 14.3-06: status effect tests (burning).

Covers apply / tick / lethal / decrement-to-zero / additive stacking.
"""

from __future__ import annotations

from dataclasses import replace

from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.effect_resolver import resolve_effect
from grid_tactics.enums import (
    CardType,
    EffectType,
    PlayerSide,
    TargetType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.minion import BURN_DPT, MinionInstance
from grid_tactics.player import Player
from grid_tactics.react_stack import tick_status_effects
from grid_tactics.types import STARTING_HP


def _make_lib() -> CardLibrary:
    return CardLibrary({
        "test_minion": CardDefinition(
            card_id="test_minion",
            name="Test Minion",
            card_type=CardType.MINION,
            mana_cost=1,
            attack=1,
            health=10,
            attack_range=0,
        ),
    })


def _make_state(minions) -> GameState:
    board = Board.empty()
    for m in minions:
        board = board.place(m.position[0], m.position[1], m.instance_id)
    p1 = Player(side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=5,
                max_mana=5, hand=(), deck=(), graveyard=())
    p2 = Player(side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=5,
                max_mana=5, hand=(), deck=(), graveyard=())
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=42,
        minions=tuple(minions),
        next_minion_id=max((m.instance_id for m in minions), default=-1) + 1,
    )


def test_apply_burning_via_effect():
    lib = _make_lib()
    target = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
        position=(3, 0), current_health=10,
    )
    bystander = MinionInstance(
        instance_id=1, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
        position=(3, 4), current_health=10,
    )
    state = _make_state([target, bystander])
    eff = EffectDefinition(
        effect_type=EffectType.APPLY_BURNING,
        trigger=TriggerType.ON_ATTACK,
        target=TargetType.SINGLE_TARGET,
        amount=2,
    )
    new_state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib,
        target_pos=(3, 0),
    )
    assert new_state.get_minion(0).burning_stacks == 2
    assert new_state.get_minion(1).burning_stacks == 0


def test_burn_ticks_at_turn_flip():
    lib = _make_lib()
    m = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
        position=(2, 2), current_health=5, burning_stacks=2,
    )
    state = _make_state([m])

    s1 = tick_status_effects(state, lib)
    m1 = s1.get_minion(0)
    assert m1.current_health == 5 - 2 * BURN_DPT  # 3
    assert m1.burning_stacks == 1

    s2 = tick_status_effects(s1, lib)
    m2 = s2.get_minion(0)
    assert m2.current_health == 3 - 1 * BURN_DPT  # 2
    assert m2.burning_stacks == 0

    s3 = tick_status_effects(s2, lib)
    m3 = s3.get_minion(0)
    assert m3.current_health == 2  # no further damage
    assert m3.burning_stacks == 0


def test_burn_lethal_kills_minion():
    lib = _make_lib()
    m = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
        position=(2, 2), current_health=1, burning_stacks=1,
    )
    state = _make_state([m])
    new_state = tick_status_effects(state, lib)
    # Minion routed through death cleanup -> removed from minions tuple
    assert new_state.get_minion(0) is None


def test_burn_stacks_additive():
    lib = _make_lib()
    target = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
        position=(3, 0), current_health=10,
    )
    state = _make_state([target])
    eff = EffectDefinition(
        effect_type=EffectType.APPLY_BURNING,
        trigger=TriggerType.ON_ATTACK,
        target=TargetType.SINGLE_TARGET,
        amount=1,
    )
    state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib, target_pos=(3, 0),
    )
    state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib, target_pos=(3, 0),
    )
    assert state.get_minion(0).burning_stacks == 2
