"""Status effect tests — boolean burn semantics.

Burn is a non-stacking BOOLEAN status. Turn-structure redesign 2026-07:
a burning minion takes BURN_DAMAGE in the DECAY phase (end of turn),
scoped per minion by ``burn_scope`` (default "owner" = the owner's Decay
phase). Re-applying burn is a no-op. is_burning persists until the
minion dies (no cleanse).
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
from grid_tactics.minion import BURN_DAMAGE, MinionInstance
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


def _make_state(minions, active_idx=0, phase=TurnPhase.ACTION) -> GameState:
    board = Board.empty()
    for m in minions:
        board = board.place(m.position[0], m.position[1], m.instance_id)
    p1 = Player(side=PlayerSide.PLAYER_1, hp=STARTING_HP, current_mana=5,
                max_mana=5, hand=(), deck=(), grave=())
    p2 = Player(side=PlayerSide.PLAYER_2, hp=STARTING_HP, current_mana=5,
                max_mana=5, hand=(), deck=(), grave=())
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=active_idx,
        phase=phase,
        turn_number=1,
        seed=42,
        minions=tuple(minions),
        next_minion_id=max((m.instance_id for m in minions), default=-1) + 1,
    )


def test_apply_burning_sets_bool():
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
        amount=1,
    )
    new_state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib,
        target_pos=(3, 0),
    )
    assert new_state.get_minion(0).is_burning is True
    assert new_state.get_minion(1).is_burning is False


def test_apply_burning_is_idempotent():
    lib = _make_lib()
    target = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
        position=(3, 0), current_health=10, is_burning=True,
    )
    state = _make_state([target])
    eff = EffectDefinition(
        effect_type=EffectType.APPLY_BURNING,
        trigger=TriggerType.ON_ATTACK,
        target=TargetType.SINGLE_TARGET,
        amount=1,
    )
    new_state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib,
        target_pos=(3, 0),
    )
    # Still burning, no double damage, no stacks
    assert new_state.get_minion(0).is_burning is True
    assert new_state.get_minion(0).current_health == 10


def test_burn_ticks_only_in_owners_decay_and_persists():
    lib = _make_lib()
    # Burning P1 minion (default burn_scope="owner"). Active player is
    # P1 → the tick fires in P1's DECAY phase.
    m = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
        position=(2, 2), current_health=20, is_burning=True,
    )
    # Turn-structure redesign 2026-07: tick_status_effects asserts
    # status:burn ⇒ END_OF_TURN (Decay phase). The function only ever
    # runs from enter_end_of_turn in production. Use the proper phase
    # here so the contract assertion is satisfied.
    state = _make_state([m], active_idx=0, phase=TurnPhase.END_OF_TURN)

    s1 = tick_status_effects(state, lib)
    m1 = s1.get_minion(0)
    assert m1.current_health == 20 - BURN_DAMAGE
    # Burning persists
    assert m1.is_burning is True

    # Now flip active to P2 — the owner-scoped tick must NOT fire on
    # P1's minion in P2's Decay phase.
    s_p2 = replace(s1, active_player_idx=1)
    s2 = tick_status_effects(s_p2, lib)
    m2 = s2.get_minion(0)
    assert m2.current_health == 20 - BURN_DAMAGE  # unchanged
    assert m2.is_burning is True


def test_burn_lethal_kills_minion():
    lib = _make_lib()
    m = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
        position=(2, 2), current_health=BURN_DAMAGE, is_burning=True,
    )
    state = _make_state([m], active_idx=0, phase=TurnPhase.END_OF_TURN)
    new_state = tick_status_effects(state, lib)
    assert new_state.get_minion(0) is None


# ---------------------------------------------------------------------------
# Per-card burn scoping from card data (turn-structure redesign spec 7.2)
# ---------------------------------------------------------------------------


def test_apply_burning_default_scope_is_owner():
    """No `scope` on the effect (the standard Burn keyword) -> the applied
    burn ticks in the minion OWNER's Decay phase (burn_scope="owner")."""
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
    new_state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib,
        target_pos=(3, 0),
    )
    assert new_state.get_minion(0).is_burning is True
    assert new_state.get_minion(0).burn_scope == "owner"


def test_apply_burning_with_card_scope_sets_burn_scope():
    """An effect carrying scope="every" ("every turn" wording) stamps the
    scope onto the burned minion so the tick fires in EVERY Decay phase."""
    lib = _make_lib()
    target = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
        position=(3, 0), current_health=30,
    )
    state = _make_state([target])
    eff = EffectDefinition(
        effect_type=EffectType.APPLY_BURNING,
        trigger=TriggerType.ON_ATTACK,
        target=TargetType.SINGLE_TARGET,
        amount=1,
        scope="every",
    )
    state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib,
        target_pos=(3, 0),
    )
    assert state.get_minion(0).burn_scope == "every"

    # And the scope is live: the minion ticks in BOTH players' Decay phases.
    s = replace(state, phase=TurnPhase.END_OF_TURN, active_player_idx=0)
    s = tick_status_effects(s, lib)
    assert s.get_minion(0).current_health == 30 - BURN_DAMAGE
    s = replace(s, active_player_idx=1)
    s = tick_status_effects(s, lib)
    assert s.get_minion(0).current_health == 30 - 2 * BURN_DAMAGE


def test_burn_aura_effect_scope_opponent():
    """EffectType.BURN (aura form) also stamps the card scope."""
    lib = _make_lib()
    target = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
        position=(3, 0), current_health=10,
    )
    state = _make_state([target])
    eff = EffectDefinition(
        effect_type=EffectType.BURN,
        trigger=TriggerType.ON_SUMMON,
        target=TargetType.SINGLE_TARGET,
        amount=5,
        scope="opponent",
    )
    new_state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib,
        target_pos=(3, 0),
    )
    assert new_state.get_minion(0).is_burning is True
    assert new_state.get_minion(0).burn_scope == "opponent"


def test_reapplying_burn_keeps_existing_scope():
    """Burn is a no-op on an already-burning minion — including its scope
    (no refresh, no re-stamp)."""
    lib = _make_lib()
    target = MinionInstance(
        instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
        position=(3, 0), current_health=10,
        is_burning=True, burn_scope="every",
    )
    state = _make_state([target])
    eff = EffectDefinition(
        effect_type=EffectType.APPLY_BURNING,
        trigger=TriggerType.ON_ATTACK,
        target=TargetType.SINGLE_TARGET,
        amount=1,
        scope="opponent",
    )
    new_state = resolve_effect(
        state, eff, caster_pos=(0, 0),
        caster_owner=PlayerSide.PLAYER_1, library=lib,
        target_pos=(3, 0),
    )
    assert new_state.get_minion(0).burn_scope == "every"
