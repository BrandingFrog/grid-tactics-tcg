"""Tests for MinionInstance dataclass."""

import dataclasses

import pytest

from grid_tactics.enums import ActionType, PlayerSide
from grid_tactics.minion import MinionInstance
from grid_tactics.types import AUTO_DRAW_ENABLED, MAX_REACT_STACK_DEPTH


class TestActionTypeEnum:
    """Tests for ActionType IntEnum values."""

    def test_action_type_values(self):
        """ActionType has all 6 expected values."""
        assert ActionType.PLAY_CARD == 0
        assert ActionType.MOVE == 1
        assert ActionType.ATTACK == 2
        assert ActionType.DRAW == 3
        assert ActionType.PASS == 4
        assert ActionType.PLAY_REACT == 5

    def test_action_type_count(self):
        """ActionType count after Phase 14.x additions.

        Audit-followup test sweep: PLAY_CARD, MOVE, ATTACK, DRAW, PASS,
        PLAY_REACT, SACRIFICE, TRANSFORM, DECLINE_POST_MOVE_ATTACK,
        TUTOR_SELECT, DECLINE_TUTOR, ACTIVATE_ABILITY,
        CONJURE_DEPLOY, DECLINE_CONJURE, DEATH_TARGET_PICK.
        """
        assert len(ActionType) == 15

    def test_action_type_is_int(self):
        """ActionType values are ints (IntEnum pattern)."""
        assert isinstance(ActionType.PLAY_CARD, int)
        assert isinstance(ActionType.PASS, int)


class TestPhase3Constants:
    """Tests for Phase 3 constants in types.py."""

    def test_auto_draw_enabled_default(self):
        """AUTO_DRAW_ENABLED defaults to False (per D-15)."""
        assert AUTO_DRAW_ENABLED is False

    def test_max_react_stack_depth(self):
        """MAX_REACT_STACK_DEPTH is 10 (safety cap per research Pitfall 3)."""
        assert MAX_REACT_STACK_DEPTH == 10


class TestMinionInstanceConstruction:
    """Tests for MinionInstance creation and field values."""

    def test_basic_construction(self):
        """MinionInstance can be created with all required fields."""
        m = MinionInstance(
            instance_id=1,
            card_numeric_id=5,
            owner=PlayerSide.PLAYER_1,
            position=(0, 2),
            current_health=3,
        )
        assert m.instance_id == 1
        assert m.card_numeric_id == 5
        assert m.owner == PlayerSide.PLAYER_1
        assert m.position == (0, 2)
        assert m.current_health == 3

    def test_attack_bonus_default(self):
        """attack_bonus defaults to 0."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=3,
        )
        assert m.attack_bonus == 0

    def test_attack_bonus_custom(self):
        """attack_bonus can be set to a non-zero value."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=3,
            attack_bonus=2,
        )
        assert m.attack_bonus == 2


class TestMinionIsAlive:
    """Tests for the is_alive property."""

    def test_alive_positive_health(self):
        """is_alive returns True when current_health > 0."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=5,
        )
        assert m.is_alive is True

    def test_dead_zero_health(self):
        """is_alive returns False when current_health == 0."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=0,
        )
        assert m.is_alive is False

    def test_dead_negative_health(self):
        """is_alive returns False when current_health < 0."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=-2,
        )
        assert m.is_alive is False

    def test_alive_one_health(self):
        """is_alive returns True when current_health == 1 (edge case)."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=1,
        )
        assert m.is_alive is True


class TestMinionImmutability:
    """Tests for frozen dataclass behavior."""

    def test_frozen_raises_on_assignment(self):
        """Cannot assign attributes on a frozen MinionInstance."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=3,
        )
        with pytest.raises(AttributeError):
            m.current_health = 1  # type: ignore[misc]

    def test_frozen_raises_on_position(self):
        """Cannot reassign position on a frozen MinionInstance."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=3,
        )
        with pytest.raises(AttributeError):
            m.position = (1, 1)  # type: ignore[misc]


class TestMinionReplace:
    """Tests for dataclasses.replace() on MinionInstance."""

    def test_replace_health(self):
        """dataclasses.replace() creates a new instance with modified health."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=5,
        )
        m2 = dataclasses.replace(m, current_health=3)
        assert m2.current_health == 3
        assert m.current_health == 5  # original unchanged

    def test_replace_position(self):
        """dataclasses.replace() creates a new instance with modified position."""
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=0,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=3,
        )
        m2 = dataclasses.replace(m, position=(2, 3))
        assert m2.position == (2, 3)
        assert m.position == (0, 0)  # original unchanged


class TestMinionEquality:
    """Tests for equality between MinionInstance instances."""

    def test_equal_instances(self):
        """Two MinionInstances with the same fields are equal."""
        m1 = MinionInstance(0, 0, PlayerSide.PLAYER_1, (0, 0), 3)
        m2 = MinionInstance(0, 0, PlayerSide.PLAYER_1, (0, 0), 3)
        assert m1 == m2

    def test_different_instances(self):
        """MinionInstances with different fields are not equal."""
        m1 = MinionInstance(0, 0, PlayerSide.PLAYER_1, (0, 0), 3)
        m2 = MinionInstance(1, 0, PlayerSide.PLAYER_1, (0, 0), 3)
        assert m1 != m2
