"""Tests for all IntEnum classes in grid_tactics.enums.

Covers both Phase 1 enums (PlayerSide, TurnPhase) and Phase 2 card enums
(CardType, Element, EffectType, TriggerType, TargetType).
"""

from enum import IntEnum

import pytest

from grid_tactics.enums import (
    ActionType,
    CardType,
    EffectType,
    Element,
    PlayerSide,
    ReactCondition,
    ReactContext,
    TargetType,
    TriggerType,
    TurnPhase,
)
from grid_tactics.types import (
    GRID_COLS,
    GRID_ROWS,
    MAX_COPIES_PER_DECK,
    MAX_EFFECT_AMOUNT,
    MAX_MANA_CAP,
    MAX_STAT,
    MIN_DECK_SIZE,
    MIN_STAT,
    STARTING_HP,
    STARTING_MANA,
)


# ---------------------------------------------------------------------------
# Phase 1 enums -- regression tests
# ---------------------------------------------------------------------------


class TestPlayerSide:
    """Ensure Phase 1 PlayerSide enum still works after Phase 2 additions."""

    def test_values(self) -> None:
        assert PlayerSide.PLAYER_1 == 0
        assert PlayerSide.PLAYER_2 == 1

    def test_is_intenum(self) -> None:
        assert isinstance(PlayerSide.PLAYER_1, IntEnum)

    def test_name_lookup(self) -> None:
        assert PlayerSide["PLAYER_1"] is PlayerSide.PLAYER_1


class TestTurnPhase:
    """Ensure Phase 1 TurnPhase enum still works after Phase 2 additions."""

    def test_values(self) -> None:
        assert TurnPhase.ACTION == 0
        assert TurnPhase.REACT == 1

    def test_is_intenum(self) -> None:
        assert isinstance(TurnPhase.ACTION, IntEnum)

    def test_name_lookup(self) -> None:
        assert TurnPhase["ACTION"] is TurnPhase.ACTION

    def test_phase_14_7_02_new_values(self) -> None:
        """Phase 14.7-02: START_OF_TURN=2, END_OF_TURN=3 appended."""
        assert TurnPhase.START_OF_TURN == 2
        assert TurnPhase.END_OF_TURN == 3
        assert TurnPhase(2) is TurnPhase.START_OF_TURN
        assert TurnPhase(3) is TurnPhase.END_OF_TURN
        # Existing values must not shift (append-only invariant)
        assert TurnPhase.ACTION == 0
        assert TurnPhase.REACT == 1
        # Exactly 4 members total
        assert len(TurnPhase) == 4


class TestReactContext:
    """Phase 14.7-02: ReactContext tags why the current REACT window is open."""

    def test_member_count(self) -> None:
        assert len(ReactContext) == 6

    def test_values(self) -> None:
        assert ReactContext.AFTER_START_TRIGGER == 0
        assert ReactContext.AFTER_ACTION == 1
        assert ReactContext.AFTER_SUMMON_DECLARATION == 2
        assert ReactContext.AFTER_SUMMON_EFFECT == 3
        assert ReactContext.AFTER_DEATH_EFFECT == 4
        assert ReactContext.BEFORE_END_OF_TURN == 5

    def test_is_intenum(self) -> None:
        assert isinstance(ReactContext.AFTER_ACTION, IntEnum)

    def test_name_lookup(self) -> None:
        assert ReactContext["AFTER_ACTION"] is ReactContext.AFTER_ACTION


# ---------------------------------------------------------------------------
# Phase 2 enums -- card system
# ---------------------------------------------------------------------------


class TestCardType:
    """CardType IntEnum: MINION=0, MAGIC=1, REACT=2."""

    def test_minion_value(self) -> None:
        assert CardType.MINION == 0

    def test_magic_value(self) -> None:
        assert CardType.MAGIC == 1

    def test_react_value(self) -> None:
        assert CardType.REACT == 2

    def test_is_intenum(self) -> None:
        assert isinstance(CardType.MINION, IntEnum)
        assert isinstance(CardType.MAGIC, IntEnum)
        assert isinstance(CardType.REACT, IntEnum)

    def test_member_count(self) -> None:
        assert len(CardType) == 3

    def test_name_property(self) -> None:
        assert CardType.MINION.name == "MINION"
        assert CardType.MAGIC.name == "MAGIC"
        assert CardType.REACT.name == "REACT"

    def test_bracket_lookup(self) -> None:
        assert CardType["MINION"] is CardType.MINION
        assert CardType["MAGIC"] is CardType.MAGIC
        assert CardType["REACT"] is CardType.REACT


class TestElement:
    """Element IntEnum: WOOD=0, FIRE=1, EARTH=2, WATER=3, METAL=4, DARK=5, LIGHT=6."""

    def test_wood_value(self) -> None:
        assert Element.WOOD == 0

    def test_fire_value(self) -> None:
        assert Element.FIRE == 1

    def test_earth_value(self) -> None:
        assert Element.EARTH == 2

    def test_water_value(self) -> None:
        assert Element.WATER == 3

    def test_metal_value(self) -> None:
        assert Element.METAL == 4

    def test_dark_value(self) -> None:
        assert Element.DARK == 5

    def test_light_value(self) -> None:
        assert Element.LIGHT == 6

    def test_is_intenum(self) -> None:
        for member in Element:
            assert isinstance(member, IntEnum)

    def test_member_count(self) -> None:
        assert len(Element) == 7

    def test_bracket_lookup(self) -> None:
        assert Element["FIRE"] is Element.FIRE


class TestEffectType:
    """EffectType IntEnum: DAMAGE=0, HEAL=1, BUFF_ATTACK=2, BUFF_HEALTH=3 (per D-01)."""

    def test_damage_value(self) -> None:
        assert EffectType.DAMAGE == 0

    def test_heal_value(self) -> None:
        assert EffectType.HEAL == 1

    def test_buff_attack_value(self) -> None:
        assert EffectType.BUFF_ATTACK == 2

    def test_buff_health_value(self) -> None:
        assert EffectType.BUFF_HEALTH == 3

    def test_is_intenum(self) -> None:
        for member in EffectType:
            assert isinstance(member, IntEnum)

    def test_member_count(self) -> None:
        # Append-only enum. Current 20 members: the original 18 plus DRAW
        # and BURN_BONUS added by later phases.
        assert len(EffectType) == 20

    def test_bracket_lookup(self) -> None:
        assert EffectType["DAMAGE"] is EffectType.DAMAGE


class TestTriggerType:
    """TriggerType IntEnum: ON_PLAY=0, ON_DEATH=1, ON_ATTACK=2, ON_DAMAGED=3 (per D-02)."""

    def test_on_play_value(self) -> None:
        assert TriggerType.ON_PLAY == 0

    def test_on_death_value(self) -> None:
        assert TriggerType.ON_DEATH == 1

    def test_on_attack_value(self) -> None:
        assert TriggerType.ON_ATTACK == 2

    def test_on_damaged_value(self) -> None:
        assert TriggerType.ON_DAMAGED == 3

    def test_is_intenum(self) -> None:
        for member in TriggerType:
            assert isinstance(member, IntEnum)

    def test_member_count(self) -> None:
        # Phase 14.8-05: PASSIVE (=5) was DELETED. The enum is still
        # append-only — value 5 is BURNED, not reused — so tensor-engine
        # int encodings remain stable across the migration. Now 10 live
        # members: ON_PLAY=0, ON_DEATH=1, ON_ATTACK=2, ON_DAMAGED=3,
        # ON_MOVE=4, [5 burned], ON_DISCARD=6, AURA=7, ON_SUMMON=8,
        # ON_START_OF_TURN=9, ON_END_OF_TURN=10.
        assert len(TriggerType) == 10

    def test_passive_deleted(self) -> None:
        """Phase 14.8-05 regression guard: PASSIVE must NOT be a member.

        The enum value 5 is BURNED — not reused — to preserve tensor-engine
        encoding stability. CardLoader._parse_enum raises ValueError on
        any card JSON that still carries ``"trigger": "passive"``.
        """
        assert "PASSIVE" not in TriggerType.__members__
        # Bracket lookup raises KeyError on missing members.
        with pytest.raises(KeyError):
            TriggerType["PASSIVE"]
        # Integer lookup of the BURNED value 5 raises ValueError.
        with pytest.raises(ValueError):
            TriggerType(5)

    def test_bracket_lookup(self) -> None:
        assert TriggerType["ON_PLAY"] is TriggerType.ON_PLAY

    def test_phase_14_7_03_new_values(self) -> None:
        """Phase 14.7-03: ON_SUMMON=8, ON_START_OF_TURN=9, ON_END_OF_TURN=10."""
        assert TriggerType.ON_SUMMON == 8
        assert TriggerType.ON_START_OF_TURN == 9
        assert TriggerType.ON_END_OF_TURN == 10
        assert TriggerType(8) is TriggerType.ON_SUMMON
        assert TriggerType(9) is TriggerType.ON_START_OF_TURN
        assert TriggerType(10) is TriggerType.ON_END_OF_TURN
        # Existing values must not shift (append-only invariant). Values
        # are append-only even across deletion — PASSIVE's 5 slot is
        # burned, not reassigned.
        assert TriggerType.ON_PLAY == 0
        assert TriggerType.AURA == 7


class TestTargetType:
    """TargetType IntEnum: SINGLE_TARGET=0, ALL_ENEMIES=1, ADJACENT=2, SELF_OWNER=3 (per D-03)."""

    def test_single_target_value(self) -> None:
        assert TargetType.SINGLE_TARGET == 0

    def test_all_enemies_value(self) -> None:
        assert TargetType.ALL_ENEMIES == 1

    def test_adjacent_value(self) -> None:
        assert TargetType.ADJACENT == 2

    def test_self_owner_value(self) -> None:
        assert TargetType.SELF_OWNER == 3

    def test_is_intenum(self) -> None:
        for member in TargetType:
            assert isinstance(member, IntEnum)

    def test_member_count(self) -> None:
        # Append-only. 7 members: SINGLE_TARGET, ALL_ENEMIES, ADJACENT,
        # SELF_OWNER, OPPONENT_PLAYER, ALL_ALLIES, ALL_MINIONS.
        assert len(TargetType) == 7

    def test_bracket_lookup(self) -> None:
        assert TargetType["SINGLE_TARGET"] is TargetType.SINGLE_TARGET


# ---------------------------------------------------------------------------
# Card constants from types.py
# ---------------------------------------------------------------------------


class TestCardConstants:
    """Card-related constants in types.py."""

    def test_max_copies_per_deck(self) -> None:
        assert MAX_COPIES_PER_DECK == 3

    def test_min_deck_size(self) -> None:
        # 40-card preset deck.
        assert MIN_DECK_SIZE == 40

    def test_min_stat(self) -> None:
        assert MIN_STAT == 1

    def test_max_stat(self) -> None:
        # Raised to 100 to accommodate late-game DM-scaled values and HP pools.
        assert MAX_STAT == 100

    def test_max_effect_amount(self) -> None:
        # Audit-followup: effect amount cap raised to 100 (HP scale)
        assert MAX_EFFECT_AMOUNT == 100


# ---------------------------------------------------------------------------
# Phase 1 constants -- regression tests
# ---------------------------------------------------------------------------


class TestPhase1Constants:
    """Ensure existing Phase 1 constants unchanged after Phase 2 additions."""

    def test_grid_rows(self) -> None:
        assert GRID_ROWS == 5

    def test_grid_cols(self) -> None:
        assert GRID_COLS == 5

    def test_starting_mana(self) -> None:
        assert STARTING_MANA == 1

    def test_max_mana_cap(self) -> None:
        assert MAX_MANA_CAP == 10

    def test_starting_hp(self) -> None:
        # Audit-followup: HP scaled 20 -> 100
        assert STARTING_HP == 100


class TestReactConditionPhase14_7_07:
    """Phase 14.7-07: three react_context-aware conditions appended."""

    def test_new_values(self) -> None:
        # Append-only after OPPONENT_ENDS_TURN=14
        assert ReactCondition.OPPONENT_SUMMONS_MINION == 15
        assert ReactCondition.OPPONENT_START_OF_TURN == 16
        assert ReactCondition.OPPONENT_END_OF_TURN == 17

    def test_round_trip_by_value(self) -> None:
        assert ReactCondition(15) is ReactCondition.OPPONENT_SUMMONS_MINION
        assert ReactCondition(16) is ReactCondition.OPPONENT_START_OF_TURN
        assert ReactCondition(17) is ReactCondition.OPPONENT_END_OF_TURN

    def test_name_lookup(self) -> None:
        assert ReactCondition["OPPONENT_SUMMONS_MINION"] is ReactCondition.OPPONENT_SUMMONS_MINION
        assert ReactCondition["OPPONENT_START_OF_TURN"] is ReactCondition.OPPONENT_START_OF_TURN
        assert ReactCondition["OPPONENT_END_OF_TURN"] is ReactCondition.OPPONENT_END_OF_TURN

    def test_preserves_existing_values(self) -> None:
        # Append-only invariant: 0..14 unchanged
        assert ReactCondition.OPPONENT_PLAYS_MAGIC == 0
        assert ReactCondition.OPPONENT_PLAYS_MINION == 1
        assert ReactCondition.ANY_ACTION == 4
        assert ReactCondition.OPPONENT_ENDS_TURN == 14

    def test_member_count(self) -> None:
        # 15 original (0..14) + 3 new (15..17) = 18 total
        assert len(ReactCondition) == 18


class TestActionTypePhase14_7_05:
    """Phase 14.7-05: TRIGGER_PICK / DECLINE_TRIGGER appended to ActionType."""

    def test_trigger_pick_value(self) -> None:
        # Append-only: TRIGGER_PICK is 17 (after DECLINE_REVIVE=16)
        assert ActionType.TRIGGER_PICK == 17

    def test_decline_trigger_value(self) -> None:
        # Append-only: DECLINE_TRIGGER is 18
        assert ActionType.DECLINE_TRIGGER == 18

    def test_preserves_existing_values(self) -> None:
        # Sanity check: the 0..16 slice is unchanged (action space stability)
        assert ActionType.PLAY_CARD == 0
        assert ActionType.PASS == 4
        assert ActionType.DECLINE_REVIVE == 16
