"""Tests for SACRIFICE action type -- sacrifice minion on opponent's back row to deal damage.

Covers:
  - sacrifice_action convenience constructor
  - _apply_sacrifice handler: removes minion, deals damage, adds to graveyard
  - Sacrifice with attack_bonus deals boosted damage
  - Cannot sacrifice minion not on back row
  - Cannot sacrifice opponent's minion
  - Sacrifice appears in legal_actions when eligible
  - Sacrifice does NOT appear when no minion on back row
  - Sacrifice dispatched through resolve_action transitions to REACT
  - Full resolve_action SACRIFICE flow
"""

import pytest
from dataclasses import replace

from grid_tactics.enums import (
    ActionType,
    CardType,
    PlayerSide,
    TurnPhase,
)
from grid_tactics.cards import CardDefinition
from grid_tactics.card_library import CardLibrary
from grid_tactics.actions import Action, sacrifice_action
from grid_tactics.action_resolver import _apply_sacrifice, resolve_action
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.board import Board
from grid_tactics.player import Player
from grid_tactics.game_state import GameState
from grid_tactics.types import STARTING_HP


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------


def _make_test_library() -> CardLibrary:
    """Create a CardLibrary with test cards for sacrifice tests.

    Alphabetical ordering gives numeric IDs:
      0 = "test_melee"   (minion, 2 mana, atk=3, hp=5, range=0)
      1 = "test_ranged"  (minion, 3 mana, atk=2, hp=3, range=2)
    """
    cards = {
        "test_melee": CardDefinition(
            card_id="test_melee", name="Test Melee", card_type=CardType.MINION,
            mana_cost=2, attack=3, health=5, attack_range=0,
        ),
        "test_ranged": CardDefinition(
            card_id="test_ranged", name="Test Ranged", card_type=CardType.MINION,
            mana_cost=3, attack=2, health=3, attack_range=2,
        ),
    }
    return CardLibrary(cards)


def _make_state_with_minion_at(
    position, owner=PlayerSide.PLAYER_1, active_idx=0,
    attack_bonus=0, card_numeric_id=0,
    p1_hp=STARTING_HP, p2_hp=STARTING_HP,
    p1_hand=(), p2_hand=(),
    p1_deck=(0, 0, 0), p2_deck=(0, 0, 0),
):
    """Helper: create a GameState with one minion at the given position."""
    minion = MinionInstance(
        instance_id=0,
        card_numeric_id=card_numeric_id,
        owner=owner,
        position=position,
        current_health=5,
        attack_bonus=attack_bonus,
    )
    board = Board.empty().place(position[0], position[1], 0)
    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=p1_hp, current_mana=5, max_mana=5,
        hand=p1_hand, deck=p1_deck, graveyard=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=p2_hp, current_mana=5, max_mana=5,
        hand=p2_hand, deck=p2_deck, graveyard=(),
    )
    return GameState(
        board=board,
        players=(p1, p2),
        active_player_idx=active_idx,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=42,
        minions=(minion,),
        next_minion_id=1,
    )


# ---------------------------------------------------------------------------
# Tests: sacrifice_action constructor
# ---------------------------------------------------------------------------


class TestSacrificeActionConstructor:
    """Test the sacrifice_action convenience constructor."""

    def test_creates_correct_action_type(self):
        action = sacrifice_action(minion_id=42)
        assert action.action_type == ActionType.SACRIFICE

    def test_sets_minion_id(self):
        action = sacrifice_action(minion_id=7)
        assert action.minion_id == 7

    def test_other_fields_are_none(self):
        action = sacrifice_action(minion_id=3)
        assert action.card_index is None
        assert action.position is None
        assert action.target_id is None
        assert action.target_pos is None


# ---------------------------------------------------------------------------
# Tests: _apply_sacrifice
# ---------------------------------------------------------------------------


class TestApplySacrifice:
    """Test the _apply_sacrifice handler."""

    def test_removes_minion_from_board(self):
        """After sacrifice, the minion's board cell is empty."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2))  # P1 minion on P2 back row
        action = sacrifice_action(minion_id=0)

        new_state = _apply_sacrifice(state, action, lib)
        assert new_state.board.get(4, 2) is None

    def test_removes_minion_from_minions_tuple(self):
        """After sacrifice, the minion is removed from state.minions."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2))
        action = sacrifice_action(minion_id=0)

        new_state = _apply_sacrifice(state, action, lib)
        assert len(new_state.minions) == 0

    def test_deals_base_attack_as_damage(self):
        """Sacrifice deals the card's base attack as damage to opponent."""
        lib = _make_test_library()
        # card_numeric_id=0 is test_melee with attack=3
        state = _make_state_with_minion_at((4, 2), card_numeric_id=0)
        action = sacrifice_action(minion_id=0)

        new_state = _apply_sacrifice(state, action, lib)
        # P1 is active (idx 0), so opponent is P2 (idx 1)
        assert new_state.players[1].hp == STARTING_HP - 3

    def test_deals_effective_attack_with_bonus(self):
        """Sacrifice includes attack_bonus in damage calculation."""
        lib = _make_test_library()
        # test_melee attack=3, attack_bonus=2 -> effective attack = 5
        state = _make_state_with_minion_at((4, 2), card_numeric_id=0, attack_bonus=2)
        action = sacrifice_action(minion_id=0)

        new_state = _apply_sacrifice(state, action, lib)
        assert new_state.players[1].hp == STARTING_HP - 5

    def test_adds_card_to_owner_graveyard(self):
        """Sacrificed minion's card goes to the owner's graveyard."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2), card_numeric_id=0)
        action = sacrifice_action(minion_id=0)

        new_state = _apply_sacrifice(state, action, lib)
        # Owner is P1 (idx 0)
        assert 0 in new_state.players[0].graveyard

    def test_p2_minion_sacrifices_on_p1_back_row(self):
        """P2 minion at row 0 (P1 back row) can sacrifice, dealing damage to P1."""
        lib = _make_test_library()
        # card_numeric_id=1 is test_ranged with attack=2
        state = _make_state_with_minion_at(
            (0, 2), owner=PlayerSide.PLAYER_2, active_idx=1, card_numeric_id=1,
        )
        action = sacrifice_action(minion_id=0)

        new_state = _apply_sacrifice(state, action, lib)
        # P2 is active (idx 1), opponent is P1 (idx 0)
        assert new_state.players[0].hp == STARTING_HP - 2
        assert new_state.board.get(0, 2) is None

    def test_cannot_sacrifice_minion_not_on_back_row(self):
        """Sacrificing a minion NOT on opponent's back row raises ValueError."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((2, 2))  # Middle row, not back row
        action = sacrifice_action(minion_id=0)

        with pytest.raises(ValueError, match="back row"):
            _apply_sacrifice(state, action, lib)

    def test_cannot_sacrifice_opponent_minion(self):
        """Sacrificing an opponent's minion raises ValueError."""
        lib = _make_test_library()
        # P2 minion on P1's back row, but P1 is active
        state = _make_state_with_minion_at(
            (0, 2), owner=PlayerSide.PLAYER_2, active_idx=0,
        )
        action = sacrifice_action(minion_id=0)

        with pytest.raises(ValueError, match="opponent"):
            _apply_sacrifice(state, action, lib)

    def test_minion_not_found_raises(self):
        """Sacrificing a non-existent minion raises ValueError."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2))
        action = sacrifice_action(minion_id=999)  # Does not exist

        with pytest.raises(ValueError, match="not found"):
            _apply_sacrifice(state, action, lib)


# ---------------------------------------------------------------------------
# Tests: legal_actions with SACRIFICE
# ---------------------------------------------------------------------------


class TestSacrificeLegalActions:
    """Test that SACRIFICE appears in legal_actions when eligible."""

    def test_sacrifice_appears_for_p1_minion_on_p2_back_row(self):
        """P1 minion on row 4 -> sacrifice is in legal actions."""
        lib = _make_test_library()
        state = _make_state_with_minion_at(
            (4, 2), p1_deck=(0, 0, 0),
        )
        actions = legal_actions(state, lib)
        sacrifice_actions = [a for a in actions if a.action_type == ActionType.SACRIFICE]
        assert len(sacrifice_actions) == 1
        assert sacrifice_actions[0].minion_id == 0

    def test_sacrifice_appears_for_p2_minion_on_p1_back_row(self):
        """P2 minion on row 0 -> sacrifice is in legal actions when P2 is active."""
        lib = _make_test_library()
        state = _make_state_with_minion_at(
            (0, 2), owner=PlayerSide.PLAYER_2, active_idx=1,
            p2_deck=(0, 0, 0),
        )
        actions = legal_actions(state, lib)
        sacrifice_actions = [a for a in actions if a.action_type == ActionType.SACRIFICE]
        assert len(sacrifice_actions) == 1
        assert sacrifice_actions[0].minion_id == 0

    def test_no_sacrifice_when_not_on_back_row(self):
        """Minion on row 2 (neutral) -> no sacrifice in legal actions."""
        lib = _make_test_library()
        state = _make_state_with_minion_at(
            (2, 2), p1_deck=(0, 0, 0),
        )
        actions = legal_actions(state, lib)
        sacrifice_actions = [a for a in actions if a.action_type == ActionType.SACRIFICE]
        assert len(sacrifice_actions) == 0

    def test_no_sacrifice_for_opponent_minion(self):
        """P2's minion on P1's back row is not eligible for P1's sacrifice."""
        lib = _make_test_library()
        state = _make_state_with_minion_at(
            (0, 2), owner=PlayerSide.PLAYER_2, active_idx=0,
            p1_deck=(0, 0, 0),
        )
        actions = legal_actions(state, lib)
        sacrifice_actions = [a for a in actions if a.action_type == ActionType.SACRIFICE]
        assert len(sacrifice_actions) == 0


# ---------------------------------------------------------------------------
# Tests: resolve_action with SACRIFICE
# ---------------------------------------------------------------------------


class TestSacrificeResolveAction:
    """Test SACRIFICE dispatched through resolve_action."""

    def test_sacrifice_transitions_to_react_phase(self):
        """Sacrifice action should transition to REACT phase like other actions."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2))
        action = sacrifice_action(minion_id=0)

        new_state = resolve_action(state, action, lib)
        assert new_state.phase == TurnPhase.REACT

    def test_sacrifice_sets_pending_action(self):
        """Sacrifice should set pending_action for react window."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2))
        action = sacrifice_action(minion_id=0)

        new_state = resolve_action(state, action, lib)
        assert new_state.pending_action == action

    def test_sacrifice_damage_applied_through_resolve(self):
        """Full flow: resolve_action -> sacrifice -> opponent takes damage."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2), card_numeric_id=0)
        action = sacrifice_action(minion_id=0)

        new_state = resolve_action(state, action, lib)
        assert new_state.players[1].hp == STARTING_HP - 3

    def test_sacrifice_sets_react_player(self):
        """After sacrifice, react_player_idx should be the opponent."""
        lib = _make_test_library()
        state = _make_state_with_minion_at((4, 2))
        action = sacrifice_action(minion_id=0)

        new_state = resolve_action(state, action, lib)
        assert new_state.react_player_idx == 1  # opponent of P1 (idx 0)
