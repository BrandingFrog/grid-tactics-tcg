"""Tests for all IntEnum classes in grid_tactics.enums.

Covers both Phase 1 enums (PlayerSide, TurnPhase) and Phase 2 card enums
(CardType, Element, EffectType, TriggerType, TargetType).
"""

from enum import IntEnum

import pytest

from grid_tactics.enums import (
    CardType,
    EffectType,
    Element,
    PlayerSide,
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
        assert len(EffectType) == 7  # DAMAGE, HEAL, BUFF_ATTACK, BUFF_HEALTH, NEGATE, DEPLOY_SELF, RALLY_FORWARD

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
        assert len(TriggerType) == 5  # ON_PLAY, ON_DEATH, ON_ATTACK, ON_DAMAGED, ON_MOVE

    def test_bracket_lookup(self) -> None:
        assert TriggerType["ON_PLAY"] is TriggerType.ON_PLAY


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
        assert len(TargetType) == 4

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
        assert MIN_DECK_SIZE == 40

    def test_min_stat(self) -> None:
        assert MIN_STAT == 1

    def test_max_stat(self) -> None:
        assert MAX_STAT == 5

    def test_max_effect_amount(self) -> None:
        assert MAX_EFFECT_AMOUNT == 10


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
        assert STARTING_HP == 20
