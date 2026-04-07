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
        # Audit-followup: STARTING_HP scaled 20 -> 100. To exercise the cap
        # we need to start near the new ceiling.
        state = _make_state_with_minions([], p1_hp=STARTING_HP - 2)
        effect = EffectDefinition(
            effect_type=EffectType.HEAL, trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER, amount=5,
        )
        new_state = resolve_effect(
            state, effect, caster_pos=(0, 0),
            caster_owner=PlayerSide.PLAYER_1, library=lib,
        )
        assert new_state.players[0].hp == STARTING_HP  # capped


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


# ===========================================================================
# Phase 14.2: pending_tutor lifecycle tests
# ===========================================================================


def _make_tutor_test_library(tutor_target):
    """Build a CardLibrary with a tutor caster + diverse deck candidates.

    Cards (sorted alphabetically by card_id for deterministic numeric IDs):
      0 = "magic_metal_blast" (magic, element=metal, no tribe)
      1 = "minion_robot_metal" (minion, tribe=Robot, element=metal)
      2 = "minion_robot_water" (minion, tribe=Robot, element=water)
      3 = "minion_zombie_metal" (minion, tribe=Zombie, element=metal)
      4 = "tutor_caster" (minion with TUTOR on_play, tutor_target=<param>)
    """
    from grid_tactics.enums import Element

    tutor_effect = EffectDefinition(
        effect_type=EffectType.TUTOR,
        trigger=TriggerType.ON_PLAY,
        target=TargetType.SELF_OWNER,
        amount=1,
    )
    cards = {
        "magic_metal_blast": CardDefinition(
            card_id="magic_metal_blast",
            name="Metal Blast",
            card_type=CardType.MAGIC,
            mana_cost=1,
            element=Element.METAL,
        ),
        "minion_robot_metal": CardDefinition(
            card_id="minion_robot_metal",
            name="Robot Metal",
            card_type=CardType.MINION,
            mana_cost=2,
            attack=2,
            health=3,
            attack_range=0,
            tribe="Robot",
            element=Element.METAL,
        ),
        "minion_robot_water": CardDefinition(
            card_id="minion_robot_water",
            name="Robot Water",
            card_type=CardType.MINION,
            mana_cost=2,
            attack=1,
            health=3,
            attack_range=0,
            tribe="Robot",
            element=Element.WATER,
        ),
        "minion_zombie_metal": CardDefinition(
            card_id="minion_zombie_metal",
            name="Zombie Metal",
            card_type=CardType.MINION,
            mana_cost=2,
            attack=2,
            health=2,
            attack_range=0,
            tribe="Zombie",
            element=Element.METAL,
        ),
        "tutor_caster": CardDefinition(
            card_id="tutor_caster",
            name="Tutor Caster",
            card_type=CardType.MINION,
            mana_cost=1,
            attack=1,
            health=1,
            attack_range=0,
            effects=(tutor_effect,),
            tutor_target=tutor_target,
        ),
    }
    return CardLibrary(cards)


def _make_tutor_state(library, deck_card_ids, p1_hand=()):
    """Build a GameState where P1's deck contains the listed card_ids."""
    deck = tuple(library.get_numeric_id(cid) for cid in deck_card_ids)
    p1 = Player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
        hand=tuple(library.get_numeric_id(c) for c in p1_hand),
        deck=deck,
        graveyard=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
        hand=(),
        deck=(),
        graveyard=(),
    )
    return GameState(
        board=Board.empty(),
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=42,
    )


class TestPendingTutorEntry:
    """_enter_pending_tutor sets pending state without moving cards."""

    def test_tutor_on_play_enters_pending_state_with_matches(self):
        from grid_tactics.effect_resolver import _enter_pending_tutor

        lib = _make_tutor_test_library(tutor_target="minion_robot_metal")
        # Deck has 2 copies of robot_metal at indices 0 and 2
        state = _make_tutor_state(
            lib, ["minion_robot_metal", "minion_robot_water", "minion_robot_metal"]
        )
        caster_def = lib.get_by_card_id("tutor_caster")
        new_state = _enter_pending_tutor(
            state, caster_def, PlayerSide.PLAYER_1, lib,
        )
        assert new_state.pending_tutor_player_idx == 0
        assert new_state.pending_tutor_matches == (0, 2)
        # Deck unchanged, hand unchanged
        assert new_state.players[0].deck == state.players[0].deck
        assert new_state.players[0].hand == ()

    def test_tutor_on_play_no_matches_no_pending(self):
        from grid_tactics.effect_resolver import _enter_pending_tutor

        lib = _make_tutor_test_library(tutor_target="minion_robot_metal")
        state = _make_tutor_state(lib, ["minion_robot_water", "minion_zombie_metal"])
        caster_def = lib.get_by_card_id("tutor_caster")
        new_state = _enter_pending_tutor(
            state, caster_def, PlayerSide.PLAYER_1, lib,
        )
        assert new_state.pending_tutor_player_idx is None
        assert new_state.pending_tutor_matches == ()
        assert new_state is state  # unchanged short-circuit

    def test_tutor_selector_dict_tribe(self):
        from grid_tactics.effect_resolver import _enter_pending_tutor

        lib = _make_tutor_test_library(tutor_target={"tribe": "Robot"})
        # Deck: zombie, robot_metal, robot_water -> 2 robots at idx 1, 2
        state = _make_tutor_state(
            lib, ["minion_zombie_metal", "minion_robot_metal", "minion_robot_water"]
        )
        new_state = _enter_pending_tutor(
            state, lib.get_by_card_id("tutor_caster"), PlayerSide.PLAYER_1, lib,
        )
        assert new_state.pending_tutor_matches == (1, 2)

    def test_tutor_selector_dict_element(self):
        from grid_tactics.effect_resolver import _enter_pending_tutor

        lib = _make_tutor_test_library(tutor_target={"element": "metal"})
        # robot_metal (METAL), robot_water (WATER), zombie_metal (METAL)
        state = _make_tutor_state(
            lib, ["minion_robot_metal", "minion_robot_water", "minion_zombie_metal"]
        )
        new_state = _enter_pending_tutor(
            state, lib.get_by_card_id("tutor_caster"), PlayerSide.PLAYER_1, lib,
        )
        assert new_state.pending_tutor_matches == (0, 2)

    def test_tutor_selector_dict_card_type(self):
        from grid_tactics.effect_resolver import _enter_pending_tutor

        lib = _make_tutor_test_library(tutor_target={"card_type": "minion"})
        state = _make_tutor_state(
            lib, ["magic_metal_blast", "minion_robot_metal", "magic_metal_blast"]
        )
        new_state = _enter_pending_tutor(
            state, lib.get_by_card_id("tutor_caster"), PlayerSide.PLAYER_1, lib,
        )
        assert new_state.pending_tutor_matches == (1,)

    def test_tutor_selector_dict_multi_key_and(self):
        from grid_tactics.effect_resolver import _enter_pending_tutor

        lib = _make_tutor_test_library(
            tutor_target={"tribe": "Robot", "element": "metal"}
        )
        state = _make_tutor_state(
            lib,
            [
                "minion_robot_metal",   # match
                "minion_robot_water",   # robot but not metal
                "minion_zombie_metal",  # metal but not robot
                "minion_robot_metal",   # match
            ],
        )
        new_state = _enter_pending_tutor(
            state, lib.get_by_card_id("tutor_caster"), PlayerSide.PLAYER_1, lib,
        )
        assert new_state.pending_tutor_matches == (0, 3)

    def test_tutor_pending_mutex_with_post_move_attack(self):
        """Defense in depth: cannot enter pending_tutor while post-move pending set."""
        from grid_tactics.effect_resolver import _enter_pending_tutor

        lib = _make_tutor_test_library(tutor_target="minion_robot_metal")
        state = _make_tutor_state(lib, ["minion_robot_metal"])
        state = replace(state, pending_post_move_attacker_id=99)
        with pytest.raises(AssertionError):
            _enter_pending_tutor(
                state, lib.get_by_card_id("tutor_caster"), PlayerSide.PLAYER_1, lib,
            )


class TestTutorSelectorLoaderValidation:
    """Loader rejects unknown selector keys at load time."""

    def test_tutor_selector_unknown_key_rejected_at_load(self):
        from grid_tactics.card_loader import CardLoader

        with pytest.raises(ValueError, match="unknown selector key"):
            CardLoader._parse_tutor_target(
                {"tutor_target": {"foo": "bar"}}, "fake_card"
            )


class TestPendingTutorResolution:
    """resolve_action handles TUTOR_SELECT and DECLINE_TUTOR."""

    def _make_pending_state(self):
        lib = _make_tutor_test_library(tutor_target="minion_robot_metal")
        # Deck has 4 cards; matches at indices [1, 3]
        state = _make_tutor_state(
            lib,
            [
                "minion_robot_water",
                "minion_robot_metal",
                "minion_zombie_metal",
                "minion_robot_metal",
            ],
        )
        # Manually enter pending state (simulating just-played caster)
        state = replace(
            state,
            pending_tutor_player_idx=0,
            pending_tutor_matches=(1, 3),
        )
        return state, lib

    def test_tutor_select_moves_chosen_card_and_clears_pending(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType, TurnPhase

        state, lib = self._make_pending_state()
        original_deck = state.players[0].deck
        chosen_card = original_deck[3]  # match index 1 -> deck idx 3

        action = Action(action_type=ActionType.TUTOR_SELECT, card_index=1)
        new_state = resolve_action(state, action, lib)

        # Card moved deck -> hand
        assert chosen_card in new_state.players[0].hand
        assert len(new_state.players[0].deck) == len(original_deck) - 1
        # Pending cleared
        assert new_state.pending_tutor_player_idx is None
        assert new_state.pending_tutor_matches == ()
        # React window now fired (single one for the play)
        assert new_state.phase == TurnPhase.REACT
        assert new_state.react_player_idx == 1

    def test_decline_tutor_clears_pending_keeps_deck(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType, TurnPhase

        state, lib = self._make_pending_state()
        original_deck = state.players[0].deck

        action = Action(action_type=ActionType.DECLINE_TUTOR)
        new_state = resolve_action(state, action, lib)

        assert new_state.players[0].deck == original_deck
        assert new_state.players[0].hand == ()
        assert new_state.pending_tutor_player_idx is None
        assert new_state.pending_tutor_matches == ()
        assert new_state.phase == TurnPhase.REACT

    def test_tutor_select_invalid_match_index_raises(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType

        state, lib = self._make_pending_state()
        # 2 matches; index 5 is out of range
        with pytest.raises(ValueError, match="invalid match index"):
            resolve_action(
                state, Action(action_type=ActionType.TUTOR_SELECT, card_index=5), lib
            )

    def test_pending_tutor_blocks_unrelated_actions(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType

        state, lib = self._make_pending_state()
        for at in (
            ActionType.MOVE,
            ActionType.PLAY_CARD,
            ActionType.ATTACK,
            ActionType.SACRIFICE,
            ActionType.PASS,
        ):
            with pytest.raises(ValueError, match="Pending tutor"):
                resolve_action(state, Action(action_type=at), lib)

    def test_tutor_select_outside_pending_state_illegal(self):
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType

        lib = _make_tutor_test_library(tutor_target="minion_robot_metal")
        state = _make_tutor_state(lib, ["minion_robot_metal"])
        # No pending set
        with pytest.raises(ValueError, match="only legal during pending_tutor"):
            resolve_action(
                state, Action(action_type=ActionType.TUTOR_SELECT, card_index=0), lib
            )
        with pytest.raises(ValueError, match="only legal during pending_tutor"):
            resolve_action(
                state, Action(action_type=ActionType.DECLINE_TUTOR), lib
            )
