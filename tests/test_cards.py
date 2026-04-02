"""Tests for EffectDefinition and CardDefinition frozen dataclasses.

Covers: creation, validation, immutability, type-specific fields,
multi-purpose cards, stat range enforcement.
"""

import pytest

from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.enums import (
    Attribute,
    CardType,
    EffectType,
    ReactCondition,
    TargetType,
    TriggerType,
)
from grid_tactics.types import MAX_EFFECT_AMOUNT, MAX_STAT, MIN_STAT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _damage_effect(amount: int = 3) -> EffectDefinition:
    """Create a standard damage effect for tests."""
    return EffectDefinition(
        effect_type=EffectType.DAMAGE,
        trigger=TriggerType.ON_PLAY,
        target=TargetType.SINGLE_TARGET,
        amount=amount,
    )


def _heal_effect(amount: int = 2) -> EffectDefinition:
    """Create a standard heal effect for tests."""
    return EffectDefinition(
        effect_type=EffectType.HEAL,
        trigger=TriggerType.ON_PLAY,
        target=TargetType.SELF_OWNER,
        amount=amount,
    )


def _minion_card(**overrides) -> CardDefinition:
    """Create a valid minion card with sensible defaults."""
    defaults = dict(
        card_id="test_minion",
        name="Test Minion",
        card_type=CardType.MINION,
        mana_cost=2,
        attack=3,
        health=2,
        attack_range=0,
    )
    defaults.update(overrides)
    return CardDefinition(**defaults)


def _magic_card(**overrides) -> CardDefinition:
    """Create a valid magic card with sensible defaults."""
    defaults = dict(
        card_id="test_magic",
        name="Test Magic",
        card_type=CardType.MAGIC,
        mana_cost=2,
        effects=(_damage_effect(),),
    )
    defaults.update(overrides)
    return CardDefinition(**defaults)


def _react_card(**overrides) -> CardDefinition:
    """Create a valid react card with sensible defaults."""
    defaults = dict(
        card_id="test_react",
        name="Test React",
        card_type=CardType.REACT,
        mana_cost=1,
        effects=(_heal_effect(),),
        react_condition=ReactCondition.ANY_ACTION,
    )
    defaults.update(overrides)
    return CardDefinition(**defaults)


# ---------------------------------------------------------------------------
# EffectDefinition
# ---------------------------------------------------------------------------


class TestEffectDefinition:
    """EffectDefinition frozen dataclass with amount validation."""

    def test_create_damage_effect(self) -> None:
        e = EffectDefinition(
            effect_type=EffectType.DAMAGE,
            trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET,
            amount=3,
        )
        assert e.effect_type == EffectType.DAMAGE
        assert e.trigger == TriggerType.ON_PLAY
        assert e.target == TargetType.SINGLE_TARGET
        assert e.amount == 3

    def test_create_heal_effect(self) -> None:
        e = EffectDefinition(
            effect_type=EffectType.HEAL,
            trigger=TriggerType.ON_PLAY,
            target=TargetType.SELF_OWNER,
            amount=2,
        )
        assert e.effect_type == EffectType.HEAL
        assert e.amount == 2

    def test_create_buff_attack_effect(self) -> None:
        e = EffectDefinition(
            effect_type=EffectType.BUFF_ATTACK,
            trigger=TriggerType.ON_ATTACK,
            target=TargetType.ADJACENT,
            amount=1,
        )
        assert e.effect_type == EffectType.BUFF_ATTACK

    def test_create_buff_health_effect(self) -> None:
        e = EffectDefinition(
            effect_type=EffectType.BUFF_HEALTH,
            trigger=TriggerType.ON_DAMAGED,
            target=TargetType.SELF_OWNER,
            amount=2,
        )
        assert e.effect_type == EffectType.BUFF_HEALTH

    def test_amount_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="amount"):
            EffectDefinition(
                effect_type=EffectType.DAMAGE,
                trigger=TriggerType.ON_PLAY,
                target=TargetType.SINGLE_TARGET,
                amount=0,
            )

    def test_amount_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="amount"):
            EffectDefinition(
                effect_type=EffectType.DAMAGE,
                trigger=TriggerType.ON_PLAY,
                target=TargetType.SINGLE_TARGET,
                amount=-1,
            )

    def test_amount_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="amount"):
            EffectDefinition(
                effect_type=EffectType.DAMAGE,
                trigger=TriggerType.ON_PLAY,
                target=TargetType.SINGLE_TARGET,
                amount=MAX_EFFECT_AMOUNT + 1,
            )

    def test_amount_at_max_succeeds(self) -> None:
        e = EffectDefinition(
            effect_type=EffectType.DAMAGE,
            trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET,
            amount=MAX_EFFECT_AMOUNT,
        )
        assert e.amount == MAX_EFFECT_AMOUNT

    def test_amount_at_min_succeeds(self) -> None:
        e = EffectDefinition(
            effect_type=EffectType.DAMAGE,
            trigger=TriggerType.ON_PLAY,
            target=TargetType.SINGLE_TARGET,
            amount=1,
        )
        assert e.amount == 1

    def test_frozen_cannot_assign(self) -> None:
        e = _damage_effect()
        with pytest.raises(AttributeError):
            e.amount = 5  # type: ignore[misc]

    def test_frozen_cannot_assign_effect_type(self) -> None:
        e = _damage_effect()
        with pytest.raises(AttributeError):
            e.effect_type = EffectType.HEAL  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CardDefinition -- Card Types
# ---------------------------------------------------------------------------


class TestCardTypes:
    """CardDefinition creation for each card type."""

    def test_minion_creates_successfully(self) -> None:
        card = _minion_card()
        assert card.card_type == CardType.MINION
        assert card.attack == 3
        assert card.health == 2
        assert card.attack_range == 0
        assert card.mana_cost == 2

    def test_magic_creates_successfully(self) -> None:
        card = _magic_card()
        assert card.card_type == CardType.MAGIC
        assert card.attack is None
        assert card.health is None
        assert card.attack_range is None
        assert len(card.effects) == 1

    def test_react_creates_successfully(self) -> None:
        card = _react_card()
        assert card.card_type == CardType.REACT
        assert card.attack is None
        assert card.health is None
        assert len(card.effects) == 1

    def test_minion_with_effects(self) -> None:
        card = _minion_card(effects=(_damage_effect(),))
        assert len(card.effects) == 1
        assert card.effects[0].effect_type == EffectType.DAMAGE

    def test_minion_with_attribute_and_tribe(self) -> None:
        card = _minion_card(attribute=Attribute.FIRE, tribe="Imp")
        assert card.attribute == Attribute.FIRE
        assert card.tribe == "Imp"

    def test_magic_with_attack_raises(self) -> None:
        with pytest.raises(ValueError, match="Non-minion"):
            _magic_card(attack=2)

    def test_magic_with_health_raises(self) -> None:
        with pytest.raises(ValueError, match="Non-minion"):
            _magic_card(health=2)

    def test_react_with_attack_raises(self) -> None:
        with pytest.raises(ValueError, match="Non-minion"):
            _react_card(attack=2)

    def test_react_with_health_raises(self) -> None:
        with pytest.raises(ValueError, match="Non-minion"):
            _react_card(health=2)


# ---------------------------------------------------------------------------
# CardDefinition -- Minion required fields
# ---------------------------------------------------------------------------


class TestMinionFields:
    """Minion cards must have attack, health, and attack_range."""

    def test_missing_attack_raises(self) -> None:
        with pytest.raises(ValueError, match="attack"):
            CardDefinition(
                card_id="bad",
                name="Bad",
                card_type=CardType.MINION,
                mana_cost=2,
                health=2,
                attack_range=0,
            )

    def test_missing_health_raises(self) -> None:
        with pytest.raises(ValueError, match="health"):
            CardDefinition(
                card_id="bad",
                name="Bad",
                card_type=CardType.MINION,
                mana_cost=2,
                attack=3,
                attack_range=0,
            )

    def test_missing_attack_range_raises(self) -> None:
        with pytest.raises(ValueError, match="attack_range"):
            CardDefinition(
                card_id="bad",
                name="Bad",
                card_type=CardType.MINION,
                mana_cost=2,
                attack=3,
                health=2,
            )

    def test_minion_with_range_zero_melee(self) -> None:
        card = _minion_card(attack_range=0)
        assert card.attack_range == 0

    def test_minion_with_range_positive_ranged(self) -> None:
        card = _minion_card(attack_range=2)
        assert card.attack_range == 2

    def test_minion_with_negative_range_raises(self) -> None:
        with pytest.raises(ValueError, match="attack_range"):
            _minion_card(attack_range=-1)


# ---------------------------------------------------------------------------
# CardDefinition -- Stat validation
# ---------------------------------------------------------------------------


class TestStatValidation:
    """Stat range validation per D-19: stats in [MIN_STAT, MAX_STAT] range."""

    def test_attack_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="attack"):
            _minion_card(attack=0)

    def test_attack_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="attack"):
            _minion_card(attack=MAX_STAT + 1)

    def test_attack_at_min_ok(self) -> None:
        card = _minion_card(attack=MIN_STAT)
        assert card.attack == MIN_STAT

    def test_attack_at_max_ok(self) -> None:
        card = _minion_card(attack=MAX_STAT)
        assert card.attack == MAX_STAT

    def test_health_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="health"):
            _minion_card(health=0)

    def test_health_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="health"):
            _minion_card(health=MAX_STAT + 1)

    def test_health_at_min_ok(self) -> None:
        card = _minion_card(health=MIN_STAT)
        assert card.health == MIN_STAT

    def test_health_at_max_ok(self) -> None:
        card = _minion_card(health=MAX_STAT)
        assert card.health == MAX_STAT

    def test_mana_cost_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="mana_cost"):
            _minion_card(mana_cost=0)

    def test_mana_cost_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="mana_cost"):
            _minion_card(mana_cost=MAX_STAT + 1)

    def test_mana_cost_at_min_ok(self) -> None:
        card = _minion_card(mana_cost=MIN_STAT)
        assert card.mana_cost == MIN_STAT

    def test_mana_cost_at_max_ok(self) -> None:
        card = _minion_card(mana_cost=MAX_STAT)
        assert card.mana_cost == MAX_STAT

    def test_react_mana_cost_below_min_raises(self) -> None:
        with pytest.raises(ValueError, match="react_mana_cost"):
            _minion_card(
                react_effect=_heal_effect(),
                react_mana_cost=0,
            )

    def test_react_mana_cost_above_max_raises(self) -> None:
        with pytest.raises(ValueError, match="react_mana_cost"):
            _minion_card(
                react_effect=_heal_effect(),
                react_mana_cost=MAX_STAT + 1,
            )

    def test_react_mana_cost_at_min_ok(self) -> None:
        card = _minion_card(
            react_effect=_heal_effect(),
            react_mana_cost=MIN_STAT,
        )
        assert card.react_mana_cost == MIN_STAT

    def test_react_mana_cost_at_max_ok(self) -> None:
        card = _minion_card(
            react_effect=_heal_effect(),
            react_mana_cost=MAX_STAT,
        )
        assert card.react_mana_cost == MAX_STAT


# ---------------------------------------------------------------------------
# CardDefinition -- Multi-purpose cards (D-06, D-07, D-08)
# ---------------------------------------------------------------------------


class TestMultiPurpose:
    """Multi-purpose card validation: react_effect + react_mana_cost."""

    def test_multi_purpose_creates_successfully(self) -> None:
        card = _minion_card(
            react_effect=_heal_effect(),
            react_mana_cost=2,
        )
        assert card.react_effect is not None
        assert card.react_mana_cost == 2

    def test_is_multi_purpose_true(self) -> None:
        card = _minion_card(
            react_effect=_heal_effect(),
            react_mana_cost=2,
        )
        assert card.is_multi_purpose is True

    def test_is_multi_purpose_false_no_react(self) -> None:
        card = _minion_card()
        assert card.is_multi_purpose is False

    def test_react_effect_without_cost_raises(self) -> None:
        with pytest.raises(ValueError, match="react_effect and react_mana_cost must both"):
            _minion_card(react_effect=_heal_effect())

    def test_react_cost_without_effect_raises(self) -> None:
        with pytest.raises(ValueError, match="react_effect and react_mana_cost must both"):
            _minion_card(react_mana_cost=2)

    def test_non_minion_with_react_effect_raises(self) -> None:
        with pytest.raises(ValueError, match="Only minions can be multi-purpose"):
            CardDefinition(
                card_id="bad_magic",
                name="Bad Magic",
                card_type=CardType.MAGIC,
                mana_cost=2,
                react_effect=_heal_effect(),
                react_mana_cost=1,
            )

    def test_non_minion_react_with_react_effect_raises(self) -> None:
        with pytest.raises(ValueError, match="Only minions can be multi-purpose"):
            CardDefinition(
                card_id="bad_react",
                name="Bad React",
                card_type=CardType.REACT,
                mana_cost=1,
                react_condition=ReactCondition.ANY_ACTION,
                react_effect=_heal_effect(),
                react_mana_cost=1,
            )


# ---------------------------------------------------------------------------
# CardDefinition -- Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    """CardDefinition and EffectDefinition are frozen dataclasses."""

    def test_card_definition_frozen(self) -> None:
        card = _minion_card()
        with pytest.raises(AttributeError):
            card.attack = 5  # type: ignore[misc]

    def test_card_definition_frozen_name(self) -> None:
        card = _minion_card()
        with pytest.raises(AttributeError):
            card.name = "Changed"  # type: ignore[misc]

    def test_card_definition_frozen_mana_cost(self) -> None:
        card = _minion_card()
        with pytest.raises(AttributeError):
            card.mana_cost = 99  # type: ignore[misc]

    def test_effect_definition_frozen(self) -> None:
        e = _damage_effect()
        with pytest.raises(AttributeError):
            e.amount = 99  # type: ignore[misc]
