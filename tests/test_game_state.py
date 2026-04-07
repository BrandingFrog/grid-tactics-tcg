"""Tests for GameState dataclass."""

import dataclasses
import json

import pytest

from grid_tactics.actions import Action, pass_action
from grid_tactics.board import Board
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HAND_SIZE, STARTING_HP, STARTING_MANA


# Standard test decks (40 cards each, per deck size rules)
DECK_P1 = tuple(range(1, 41))
DECK_P2 = tuple(range(101, 141))


class TestNewGame:
    """Tests for GameState.new_game() factory."""

    def test_new_game_creates_valid_state(self):
        """new_game creates a state with empty board, correct HP and mana.

        Both players start their first action with STARTING_MANA. P2's
        first-turn regen is suppressed in react_stack so both players
        get the same mana on their first action (P1 turn 1, P2 turn 2).
        """
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.board == Board.empty()
        for player in state.players:
            assert player.hp == STARTING_HP
            assert player.max_mana == STARTING_MANA
            assert player.current_mana == STARTING_MANA

    def test_new_game_starting_hands(self):
        """Each player has STARTING_HAND_SIZE (5) cards in hand."""
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert len(state.players[0].hand) == STARTING_HAND_SIZE
        assert len(state.players[1].hand) == STARTING_HAND_SIZE

    def test_new_game_deck_reduced(self):
        """Each player's deck has len(original) - STARTING_HAND_SIZE cards."""
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert len(state.players[0].deck) == len(DECK_P1) - STARTING_HAND_SIZE
        assert len(state.players[1].deck) == len(DECK_P2) - STARTING_HAND_SIZE

    def test_new_game_turn_1(self):
        """New game starts at turn 1, ACTION phase, player 0 active."""
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.turn_number == 1
        assert state.phase == TurnPhase.ACTION
        assert state.active_player_idx == 0

    def test_new_game_deterministic_same_seed(self):
        """Same seed produces identical GameState (ENG-11)."""
        state1, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state2, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state1 == state2

    def test_new_game_deterministic_different_seed(self):
        """Different seeds produce different deck orderings."""
        state1, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state2, _ = GameState.new_game(99, DECK_P1, DECK_P2)
        # Decks and/or hands should differ
        assert (
            state1.players[0].hand != state2.players[0].hand
            or state1.players[0].deck != state2.players[0].deck
        )

    def test_seed_stored(self):
        """state.seed equals the seed passed to new_game."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.seed == 42

    def test_new_game_player_sides(self):
        """Player 1 has PLAYER_1 side, Player 2 has PLAYER_2 side."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.players[0].side == PlayerSide.PLAYER_1
        assert state.players[1].side == PlayerSide.PLAYER_2


class TestGameStateImmutability:
    """Tests for frozen dataclass behavior."""

    def test_game_state_is_frozen(self):
        """Attribute assignment raises FrozenInstanceError."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        with pytest.raises(AttributeError):
            state.turn_number = 5  # type: ignore[misc]

    def test_game_state_is_frozen_board(self):
        """Cannot reassign board field."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        with pytest.raises(AttributeError):
            state.board = Board.empty()  # type: ignore[misc]


class TestProperties:
    """Tests for active/inactive player properties."""

    def test_active_player_property(self):
        """active_player returns correct player based on active_player_idx."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.active_player == state.players[0]
        assert state.active_player.side == PlayerSide.PLAYER_1

    def test_inactive_player_property(self):
        """inactive_player returns the other player."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.inactive_player == state.players[1]
        assert state.inactive_player.side == PlayerSide.PLAYER_2


class TestSerialization:
    """Tests for to_dict/from_dict round-trip."""

    def test_to_dict_round_trip(self):
        """to_dict() then from_dict() produces equal GameState."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored == state

    def test_to_dict_is_json_serializable(self):
        """json.dumps(state.to_dict()) does not raise."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_from_dict_reconstructs_types(self):
        """from_dict correctly reconstructs enums and tuples."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert isinstance(restored.phase, TurnPhase)
        assert isinstance(restored.players[0].side, PlayerSide)
        assert isinstance(restored.players[0].hand, tuple)
        assert isinstance(restored.board.cells, tuple)


# ---------------------------------------------------------------------------
# Phase 3: Extended GameState tests
# ---------------------------------------------------------------------------


class TestGameStatePhase3Defaults:
    """Tests for the Phase 3 fields and their default values."""

    def test_new_game_empty_minions(self):
        """new_game() returns state with empty minions tuple."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.minions == ()

    def test_new_game_next_minion_id_zero(self):
        """new_game() returns state with next_minion_id=0."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.next_minion_id == 0

    def test_new_game_empty_react_stack(self):
        """new_game() returns state with empty react_stack."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.react_stack == ()

    def test_new_game_react_player_idx_none(self):
        """new_game() returns state with react_player_idx=None."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.react_player_idx is None

    def test_new_game_pending_action_none(self):
        """new_game() returns state with pending_action=None."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.pending_action is None


class TestGameStateWithMinions:
    """Tests for GameState with minions added via replace()."""

    def test_replace_adds_minions(self):
        """dataclasses.replace() can add minions to the state."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(
            instance_id=0,
            card_numeric_id=5,
            owner=PlayerSide.PLAYER_1,
            position=(0, 0),
            current_health=3,
        )
        new_state = dataclasses.replace(state, minions=(m,), next_minion_id=1)
        assert len(new_state.minions) == 1
        assert new_state.minions[0] == m
        assert new_state.next_minion_id == 1

    def test_replace_preserves_other_fields(self):
        """Adding minions via replace() does not alter other fields."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(0, 0, PlayerSide.PLAYER_1, (0, 0), 3)
        new_state = dataclasses.replace(state, minions=(m,))
        assert new_state.board == state.board
        assert new_state.players == state.players
        assert new_state.turn_number == state.turn_number


class TestGetMinion:
    """Tests for GameState.get_minion() helper."""

    def test_get_existing_minion(self):
        """get_minion returns the MinionInstance with matching instance_id."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m1 = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        m2 = MinionInstance(1, 6, PlayerSide.PLAYER_2, (4, 4), 4)
        state = dataclasses.replace(state, minions=(m1, m2))
        assert state.get_minion(0) == m1
        assert state.get_minion(1) == m2

    def test_get_nonexistent_minion(self):
        """get_minion returns None for non-existent instance_id."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.get_minion(99) is None

    def test_get_minion_empty_state(self):
        """get_minion returns None on a state with no minions."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.get_minion(0) is None


class TestGetMinionsForSide:
    """Tests for GameState.get_minions_for_side() helper."""

    def test_get_minions_for_player_1(self):
        """get_minions_for_side returns only Player 1's minions."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m1 = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        m2 = MinionInstance(1, 6, PlayerSide.PLAYER_2, (4, 4), 4)
        m3 = MinionInstance(2, 7, PlayerSide.PLAYER_1, (1, 1), 2)
        state = dataclasses.replace(state, minions=(m1, m2, m3))
        result = state.get_minions_for_side(PlayerSide.PLAYER_1)
        assert len(result) == 2
        assert m1 in result
        assert m3 in result

    def test_get_minions_for_empty_side(self):
        """get_minions_for_side returns empty tuple if no minions for that side."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m1 = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        state = dataclasses.replace(state, minions=(m1,))
        result = state.get_minions_for_side(PlayerSide.PLAYER_2)
        assert result == ()

    def test_get_minions_for_side_no_minions(self):
        """get_minions_for_side returns empty tuple on empty state."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.get_minions_for_side(PlayerSide.PLAYER_1) == ()


class TestSerializationPhase3:
    """Tests for to_dict/from_dict with Phase 3 fields."""

    def test_round_trip_with_minions(self):
        """to_dict/from_dict round-trip preserves minions."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3, attack_bonus=1)
        board = state.board.place(0, 0, 0)
        state = dataclasses.replace(
            state,
            board=board,
            minions=(m,),
            next_minion_id=1,
        )
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.minions == state.minions
        assert restored.next_minion_id == state.next_minion_id
        assert restored.minions[0].attack_bonus == 1

    def test_round_trip_with_pending_action(self):
        """to_dict/from_dict round-trip preserves pending_action."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        action = Action(ActionType.MOVE, minion_id=1, position=(2, 3))
        state = dataclasses.replace(state, pending_action=action)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.pending_action == action
        assert restored.pending_action.action_type == ActionType.MOVE
        assert restored.pending_action.minion_id == 1
        assert restored.pending_action.position == (2, 3)

    def test_round_trip_no_pending_action(self):
        """to_dict/from_dict round-trip preserves None pending_action."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.pending_action is None

    def test_round_trip_with_react_fields(self):
        """to_dict/from_dict round-trip preserves react fields."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        state = dataclasses.replace(state, react_player_idx=1)
        d = state.to_dict()
        restored = GameState.from_dict(d)
        assert restored.react_player_idx == 1

    def test_round_trip_json_serializable_with_minions(self):
        """json.dumps works with Phase 3 fields populated."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        m = MinionInstance(0, 5, PlayerSide.PLAYER_1, (0, 0), 3)
        board = state.board.place(0, 0, 0)
        state = dataclasses.replace(state, board=board, minions=(m,))
        d = state.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    def test_from_dict_backward_compatible(self):
        """from_dict handles dicts without Phase 3 fields (backward compat)."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        d = {
            "board": list(state.board.cells),
            "players": [
                {
                    "side": int(p.side),
                    "hp": p.hp,
                    "current_mana": p.current_mana,
                    "max_mana": p.max_mana,
                    "hand": list(p.hand),
                    "deck": list(p.deck),
                    "graveyard": list(p.graveyard),
                }
                for p in state.players
            ],
            "active_player_idx": state.active_player_idx,
            "phase": int(state.phase),
            "turn_number": state.turn_number,
            "seed": state.seed,
        }
        restored = GameState.from_dict(d)
        assert restored.minions == ()
        assert restored.next_minion_id == 0
        assert restored.react_stack == ()
        assert restored.react_player_idx is None
        assert restored.pending_action is None
