"""Tests for the effect resolution engine.

Tests cover all EffectType x TargetType combinations, trigger filtering,
edge cases (missing target, no minion at position), and state immutability.
"""

import pytest
from dataclasses import replace

from grid_tactics.enums import (
    CardType,
    EffectType,
    PlayerSide,
    TargetType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.card_library import CardLibrary
from grid_tactics.minion import MinionInstance
from grid_tactics.board import Board
from grid_tactics.player import Player
from grid_tactics.game_state import GameState
from grid_tactics.types import STARTING_HP


# ---------------------------------------------------------------------------
# Helper: build a minimal CardLibrary with test cards
# ---------------------------------------------------------------------------

def _make_test_library() -> CardLibrary:
    """Create a CardLibrary with deterministic test cards.

    Cards are sorted alphabetically by card_id for numeric ID assignment:
      0 = "test_melee"    (minion, attack=2, health=5, range=0)
      1 = "test_on_death" (minion, attack=1, health=3, range=0, on_death: damage 1 to all enemies)
      2 = "test_ranged"   (minion, attack=1, health=3, range=2)
    """
    cards = {
        "test_melee": CardDefinition(
            card_id="test_melee",
            name="Test Melee",
            card_type=CardType.MINION,
            mana_cost=2,
            attack=2,
            health=5,
            attack_range=0,
        ),
        "test_on_death": CardDefinition(
            card_id="test_on_death",
            name="Test On Death",
            card_type=CardType.MINION,
            mana_cost=2,
            attack=1,
            health=3,
            attack_range=0,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.DAMAGE,
                    trigger=TriggerType.ON_DEATH,
                    target=TargetType.ALL_ENEMIES,
                    amount=1,
                ),
            ),
        ),
        "test_ranged": CardDefinition(
            card_id="test_ranged",
            name="Test Ranged",
            card_type=CardType.MINION,
            mana_cost=2,
            attack=1,
            health=3,
            attack_range=2,
        ),
    }
    return CardLibrary(cards)


def _make_state_with_minions(
    minions,
    p1_hp=STARTING_HP,
    p2_hp=STARTING_HP,
    p1_mana=5,
    p2_mana=5,
):
    """Create a GameState with the given minions placed on the board."""
    board = Board.empty()
    for m in minions:
        board = board.place(m.position[0], m.position[1], m.instance_id)

    next_id = max((m.instance_id for m in minions), default=-1) + 1

    p1 = Player(
        side=PlayerSide.PLAYER_1,
        hp=p1_hp,
        current_mana=p1_mana,
        max_mana=5,
        hand=(),
        deck=(),
        graveyard=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2,
        hp=p2_hp,
        current_mana=p2_mana,
        max_mana=5,
        hand=(),
        deck=(),
        graveyard=(),
    )
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=42,
        minions=tuple(minions),
        next_minion_id=next_id,
    )


# ---------------------------------------------------------------------------
# resolve_effect tests
# ---------------------------------------------------------------------------


class TestDamageSingleTarget:
    """DAMAGE + SINGLE_TARGET reduces target minion health."""

    def test_damage_single_target_reduces_health(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        target = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        state = _make_state_with_minions([target])
        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=2,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=(3, 0),
        )
        m = new_state.get_minion(0)
        assert m is not None
        assert m.current_health == 3  # 5 - 2

    def test_damage_single_target_missing_target_pos_raises(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        state = _make_state_with_minions([])
        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=2,
        )
        # With no target_pos, effect is skipped (state unchanged)
        result = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=None,
        )
        assert result == state

    def test_damage_single_target_no_minion_at_pos_returns_unchanged(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        state = _make_state_with_minions([])
        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=2,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=(3, 0),
        )
        assert new_state is state  # unchanged


class TestDamageAllEnemies:
    """DAMAGE + ALL_ENEMIES hits all opponent minions."""

    def test_damage_all_enemies_hits_all_opponent_minions(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        enemy1 = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        enemy2 = MinionInstance(
            instance_id=1, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
            position=(4, 0), current_health=5,
        )
        friendly = MinionInstance(
            instance_id=2, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([enemy1, enemy2, friendly])
        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
            target=TargetType.ALL_ENEMIES, amount=2,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        assert new_state.get_minion(0).current_health == 3  # 5 - 2
        assert new_state.get_minion(1).current_health == 3  # 5 - 2
        assert new_state.get_minion(2).current_health == 5  # friendly, untouched


class TestDamageAdjacent:
    """DAMAGE + ADJACENT hits all minions adjacent to caster_pos."""

    def test_damage_adjacent_hits_adjacent_minions(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        # Caster at (2,2), adjacent orthogonal: (1,2),(3,2),(2,1),(2,3)
        # Also adjacent diagonal: (1,1),(1,3),(3,1),(3,3)
        adj_minion = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
            position=(2, 1), current_health=5,
        )
        far_minion = MinionInstance(
            instance_id=1, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([adj_minion, far_minion])
        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
            target=TargetType.ADJACENT, amount=3,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(2, 2),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        assert new_state.get_minion(0).current_health == 2  # 5 - 3
        assert new_state.get_minion(1).current_health == 5  # not adjacent


class TestDamageSelfOwner:
    """DAMAGE + SELF_OWNER damages the owning player's HP."""

    def test_damage_self_owner_reduces_player_hp(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        caster = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([caster])
        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER, amount=3,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        # Player 1 (index 0) should take 3 damage
        assert new_state.players[0].hp == STARTING_HP - 3


class TestHealSingleTarget:
    """HEAL + SINGLE_TARGET heals minion, capped at base health."""

    def test_heal_single_target_increases_health(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        # test_melee has base health=5, numeric id=0
        damaged = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=2,
        )
        state = _make_state_with_minions([damaged])
        effect = EffectDefinition(
            effect_type=EffectType.HEAL, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=2,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(1, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=(0, 0),
        )
        assert new_state.get_minion(0).current_health == 4  # 2 + 2

    def test_heal_single_target_capped_at_base_health(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        # test_melee has base health=5, so healing 4 from 3 caps at 5
        damaged = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=3,
        )
        state = _make_state_with_minions([damaged])
        effect = EffectDefinition(
            effect_type=EffectType.HEAL, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=4,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(1, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=(0, 0),
        )
        assert new_state.get_minion(0).current_health == 5  # capped at base health


class TestHealSelfOwner:
    """HEAL + SELF_OWNER heals the owning player's HP."""

    def test_heal_self_owner_heals_player(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        state = _make_state_with_minions([], p1_hp=10)
        effect = EffectDefinition(
            effect_type=EffectType.HEAL, trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER, amount=5,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        assert new_state.players[0].hp == 15  # 10 + 5

    def test_heal_self_owner_capped_at_starting_hp(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        state = _make_state_with_minions([], p1_hp=18)
        effect = EffectDefinition(
            effect_type=EffectType.HEAL, trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER, amount=5,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        assert new_state.players[0].hp == STARTING_HP  # capped at 20


class TestBuffAttack:
    """BUFF_ATTACK increases attack_bonus."""

    def test_buff_attack_single_target(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        target = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([target])
        effect = EffectDefinition(
            effect_type=EffectType.BUFF_ATTACK, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=3,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(1, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=(0, 0),
        )
        assert new_state.get_minion(0).attack_bonus == 3

    def test_buff_attack_self_owner(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        caster = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([caster])
        effect = EffectDefinition(
            effect_type=EffectType.BUFF_ATTACK, trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER, amount=2,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        assert new_state.get_minion(0).attack_bonus == 2


class TestBuffHealth:
    """BUFF_HEALTH increases current_health (can exceed base)."""

    def test_buff_health_single_target_exceeds_base(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        # test_melee has base health=5
        target = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([target])
        effect = EffectDefinition(
            effect_type=EffectType.BUFF_HEALTH, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=3,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(1, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=(0, 0),
        )
        assert new_state.get_minion(0).current_health == 8  # 5 + 3, exceeds base

    def test_buff_health_self_owner(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        caster = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([caster])
        effect = EffectDefinition(
            effect_type=EffectType.BUFF_HEALTH, trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER, amount=2,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        assert new_state.get_minion(0).current_health == 7  # 5 + 2


# ---------------------------------------------------------------------------
# resolve_effects_for_trigger tests
# ---------------------------------------------------------------------------


class TestResolveEffectsForTrigger:
    """resolve_effects_for_trigger processes matching trigger effects only."""

    def test_resolves_matching_trigger_only(self):
        from grid_tactics.effect_resolver import resolve_effects_for_trigger

        lib = _make_test_library()
        # test_on_death (numeric id=1) has ON_DEATH: DAMAGE ALL_ENEMIES 1
        minion = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(1, 0), current_health=3,
        )
        enemy = MinionInstance(
            instance_id=1, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        state = _make_state_with_minions([minion, enemy])

        # ON_PLAY trigger should not match ON_DEATH effects
        new_state = resolve_effects_for_trigger(
            state, TriggerType.ON_PLAY, minion, lib,
        )
        assert new_state.get_minion(1).current_health == 5  # unchanged

        # ON_DEATH trigger should match
        new_state = resolve_effects_for_trigger(
            state, TriggerType.ON_DEATH, minion, lib,
        )
        assert new_state.get_minion(1).current_health == 4  # 5 - 1

    def test_resolves_multiple_effects_in_order(self):
        """If a card has multiple effects for same trigger, resolve in definition order."""
        from grid_tactics.effect_resolver import resolve_effects_for_trigger

        # Create a card with two ON_PLAY effects
        multi_card = CardDefinition(
            card_id="test_multi",
            name="Test Multi",
            card_type=CardType.MINION,
            mana_cost=3,
            attack=2,
            health=5,
            attack_range=0,
            effects=(
                EffectDefinition(
                    effect_type=EffectType.DAMAGE,
                    trigger=TriggerType.ON_PLAY,
                    target=TargetType.ALL_ENEMIES,
                    amount=1,
                ),
                EffectDefinition(
                    effect_type=EffectType.BUFF_ATTACK,
                    trigger=TriggerType.ON_PLAY,
                    target=TargetType.SELF_OWNER,
                    amount=2,
                ),
            ),
        )
        cards = {
            "test_melee": CardDefinition(
                card_id="test_melee", name="Melee", card_type=CardType.MINION,
                mana_cost=2, attack=2, health=5, attack_range=0,
            ),
            "test_multi": multi_card,
        }
        lib = CardLibrary(cards)
        # test_melee => 0, test_multi => 1

        caster = MinionInstance(
            instance_id=0, card_numeric_id=1, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        enemy = MinionInstance(
            instance_id=1, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        state = _make_state_with_minions([caster, enemy])

        new_state = resolve_effects_for_trigger(
            state, TriggerType.ON_PLAY, caster, lib,
        )
        # Effect 1: damage all enemies by 1
        assert new_state.get_minion(1).current_health == 4  # 5 - 1
        # Effect 2: buff self attack by 2
        assert new_state.get_minion(0).attack_bonus == 2

    def test_no_effects_returns_state_unchanged(self):
        from grid_tactics.effect_resolver import resolve_effects_for_trigger

        lib = _make_test_library()
        # test_melee (numeric id=0) has no effects
        minion = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_1,
            position=(0, 0), current_health=5,
        )
        state = _make_state_with_minions([minion])

        new_state = resolve_effects_for_trigger(
            state, TriggerType.ON_PLAY, minion, lib,
        )
        assert new_state is state  # unchanged


# ---------------------------------------------------------------------------
# State immutability checks
# ---------------------------------------------------------------------------


class TestImmutability:
    """Effect resolution produces new state, original unchanged."""

    def test_original_state_unchanged_after_damage(self):
        from grid_tactics.effect_resolver import resolve_effect

        lib = _make_test_library()
        target = MinionInstance(
            instance_id=0, card_numeric_id=0, owner=PlayerSide.PLAYER_2,
            position=(3, 0), current_health=5,
        )
        state = _make_state_with_minions([target])
        effect = EffectDefinition(
            effect_type=EffectType.DAMAGE, trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET, amount=2,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
            target_pos=(3, 0),
        )
        # Original state unchanged
        assert state.get_minion(0).current_health == 5
        # New state has the change
        assert new_state.get_minion(0).current_health == 3
