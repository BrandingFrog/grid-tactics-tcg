"""Tests for Action dataclass and convenience constructors."""

import dataclasses

import pytest

from grid_tactics.actions import (
    Action,
    attack_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
)
from grid_tactics.enums import ActionType


class TestActionConstruction:
    """Tests for Action creation with all 6 action types."""

    def test_pass_action(self):
        """Action(ActionType.PASS) creates a valid pass action."""
        a = Action(action_type=ActionType.PASS)
        assert a.action_type == ActionType.PASS
        assert a.card_index is None
        assert a.position is None
        assert a.minion_id is None
        assert a.target_id is None
        assert a.target_pos is None

    def test_draw_action(self):
        """Action(ActionType.DRAW) creates a valid draw action."""
        a = Action(action_type=ActionType.DRAW)
        assert a.action_type == ActionType.DRAW

    def test_move_action(self):
        """Action(ActionType.MOVE, minion_id=1, position=(2,3)) creates a move action."""
        a = Action(action_type=ActionType.MOVE, minion_id=1, position=(2, 3))
        assert a.action_type == ActionType.MOVE
        assert a.minion_id == 1
        assert a.position == (2, 3)

    def test_attack_action(self):
        """Action(ActionType.ATTACK, minion_id=1, target_id=2) creates an attack action."""
        a = Action(action_type=ActionType.ATTACK, minion_id=1, target_id=2)
        assert a.action_type == ActionType.ATTACK
        assert a.minion_id == 1
        assert a.target_id == 2

    def test_play_card_action(self):
        """Action(ActionType.PLAY_CARD, card_index=0, position=(0,2)) creates deploy action."""
        a = Action(action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 2))
        assert a.action_type == ActionType.PLAY_CARD
        assert a.card_index == 0
        assert a.position == (0, 2)

    def test_play_react_action(self):
        """Action(ActionType.PLAY_REACT, card_index=2) creates a react play action."""
        a = Action(action_type=ActionType.PLAY_REACT, card_index=2)
        assert a.action_type == ActionType.PLAY_REACT
        assert a.card_index == 2


class TestActionImmutability:
    """Tests for frozen dataclass behavior."""

    def test_frozen_raises_on_assignment(self):
        """Cannot assign attributes on a frozen Action."""
        a = Action(action_type=ActionType.PASS)
        with pytest.raises(AttributeError):
            a.action_type = ActionType.DRAW  # type: ignore[misc]

    def test_frozen_raises_on_position(self):
        """Cannot reassign position on a frozen Action."""
        a = Action(action_type=ActionType.MOVE, minion_id=1, position=(0, 0))
        with pytest.raises(AttributeError):
            a.position = (1, 1)  # type: ignore[misc]


class TestActionEquality:
    """Tests for equality between Action instances."""

    def test_equal_actions(self):
        """Two Actions with the same fields are equal."""
        a1 = Action(ActionType.PASS)
        a2 = Action(ActionType.PASS)
        assert a1 == a2

    def test_different_actions(self):
        """Actions with different types are not equal."""
        a1 = Action(ActionType.PASS)
        a2 = Action(ActionType.DRAW)
        assert a1 != a2

    def test_different_fields_same_type(self):
        """Actions with same type but different fields are not equal."""
        a1 = Action(ActionType.MOVE, minion_id=1, position=(0, 0))
        a2 = Action(ActionType.MOVE, minion_id=2, position=(0, 0))
        assert a1 != a2


class TestConvenienceConstructors:
    """Tests for module-level convenience constructor functions."""

    def test_pass_action_func(self):
        """pass_action() produces Action(ActionType.PASS)."""
        a = pass_action()
        assert a.action_type == ActionType.PASS
        assert a == Action(ActionType.PASS)

    def test_draw_action_func(self):
        """draw_action() produces Action(ActionType.DRAW)."""
        a = draw_action()
        assert a.action_type == ActionType.DRAW
        assert a == Action(ActionType.DRAW)

    def test_move_action_func(self):
        """move_action(minion_id, position) produces correct Action."""
        a = move_action(minion_id=1, position=(2, 3))
        assert a.action_type == ActionType.MOVE
        assert a.minion_id == 1
        assert a.position == (2, 3)

    def test_attack_action_func(self):
        """attack_action(minion_id, target_id) produces correct Action."""
        a = attack_action(minion_id=1, target_id=2)
        assert a.action_type == ActionType.ATTACK
        assert a.minion_id == 1
        assert a.target_id == 2

    def test_play_card_action_func(self):
        """play_card_action(card_index, position) produces correct Action."""
        a = play_card_action(card_index=0, position=(0, 2))
        assert a.action_type == ActionType.PLAY_CARD
        assert a.card_index == 0
        assert a.position == (0, 2)

    def test_play_card_action_no_position(self):
        """play_card_action(card_index) works without position (for magic cards)."""
        a = play_card_action(card_index=3)
        assert a.action_type == ActionType.PLAY_CARD
        assert a.card_index == 3
        assert a.position is None

    def test_play_card_action_with_target_pos(self):
        """play_card_action with target_pos for targeted magic."""
        a = play_card_action(card_index=1, target_pos=(2, 3))
        assert a.action_type == ActionType.PLAY_CARD
        assert a.card_index == 1
        assert a.target_pos == (2, 3)

    def test_play_react_action_func(self):
        """play_react_action(card_index) produces correct Action."""
        a = play_react_action(card_index=2)
        assert a.action_type == ActionType.PLAY_REACT
        assert a.card_index == 2

    def test_play_react_action_with_target(self):
        """play_react_action with target_pos for targeted react."""
        a = play_react_action(card_index=1, target_pos=(3, 1))
        assert a.action_type == ActionType.PLAY_REACT
        assert a.card_index == 1
        assert a.target_pos == (3, 1)
