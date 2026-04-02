"""Tests for GameState dataclass."""

import json

import pytest

from grid_tactics.board import Board
from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HAND_SIZE, STARTING_HP, STARTING_MANA


# Standard test decks (40 cards each, per deck size rules)
DECK_P1 = tuple(range(1, 41))
DECK_P2 = tuple(range(101, 141))


class TestNewGame:
    """Tests for GameState.new_game() factory."""

    def test_new_game_creates_valid_state(self):
        """new_game creates a state with empty board, correct HP and mana."""
        state, rng = GameState.new_game(42, DECK_P1, DECK_P2)
        assert state.board == Board.empty()
        for player in state.players:
            assert player.hp == STARTING_HP
            assert player.current_mana == STARTING_MANA
            assert player.max_mana == STARTING_MANA

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
