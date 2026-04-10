"""Tests for state invariant validation."""

import pytest
from dataclasses import replace

from grid_tactics.board import Board
from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.player import Player
from grid_tactics.types import (
    GRID_SIZE,
    MAX_MANA_CAP,
    STARTING_HAND_SIZE,
    STARTING_HP,
    STARTING_MANA,
)
from grid_tactics.validation import is_valid_state, validate_state


# Standard test decks
DECK_P1 = tuple(range(1, 41))
DECK_P2 = tuple(range(101, 141))


class TestValidateStateValid:
    """Tests for valid game states."""

    def test_valid_new_game(self):
        """validate_state on a new_game state returns empty list."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        errors = validate_state(state)
        assert errors == []

    def test_is_valid_state_true(self):
        """Valid state returns True."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        assert is_valid_state(state) is True


class TestValidateStateBoardErrors:
    """Tests for board-related validation errors."""

    def test_invalid_board_size(self):
        """Board with wrong number of cells detected."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        # Create a board with wrong number of cells
        bad_board = Board(cells=tuple(None for _ in range(10)))
        bad_state = GameState(
            board=bad_board,
            players=state.players,
            active_player_idx=state.active_player_idx,
            phase=state.phase,
            turn_number=state.turn_number,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        assert any("cells" in e.lower() or "board" in e.lower() for e in errors)

    def test_duplicate_minion_ids_on_board(self):
        """Two cells with same minion_id flagged."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        # Place same minion ID in two different cells
        cells = list(state.board.cells)
        cells[0] = 42
        cells[1] = 42  # duplicate!
        bad_board = Board(cells=tuple(cells))
        bad_state = GameState(
            board=bad_board,
            players=state.players,
            active_player_idx=state.active_player_idx,
            phase=state.phase,
            turn_number=state.turn_number,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        assert any("duplicate" in e.lower() for e in errors)


class TestValidateStatePlayerErrors:
    """Tests for player-related validation errors."""

    def test_invalid_active_player_idx(self):
        """active_player_idx=2 flagged as error."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        bad_state = GameState(
            board=state.board,
            players=state.players,
            active_player_idx=2,
            phase=state.phase,
            turn_number=state.turn_number,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        assert any("active_player_idx" in e for e in errors)

    def test_invalid_turn_number(self):
        """turn_number=0 flagged as error."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        bad_state = GameState(
            board=state.board,
            players=state.players,
            active_player_idx=state.active_player_idx,
            phase=state.phase,
            turn_number=0,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        assert any("turn_number" in e for e in errors)

    def test_mana_exceeds_cap(self):
        """current_mana=11 flagged as error."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        bad_player = Player(
            side=PlayerSide.PLAYER_1,
            hp=STARTING_HP,
            current_mana=MAX_MANA_CAP + 1,  # 11
            max_mana=STARTING_MANA,
            hand=state.players[0].hand,
            deck=state.players[0].deck,
            grave=(),
        )
        bad_state = GameState(
            board=state.board,
            players=(bad_player, state.players[1]),
            active_player_idx=state.active_player_idx,
            phase=state.phase,
            turn_number=state.turn_number,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        assert any("current_mana" in e for e in errors)

    def test_negative_mana(self):
        """current_mana=-1 flagged as error."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        bad_player = Player(
            side=PlayerSide.PLAYER_1,
            hp=STARTING_HP,
            current_mana=-1,
            max_mana=STARTING_MANA,
            hand=state.players[0].hand,
            deck=state.players[0].deck,
            grave=(),
        )
        bad_state = GameState(
            board=state.board,
            players=(bad_player, state.players[1]),
            active_player_idx=state.active_player_idx,
            phase=state.phase,
            turn_number=state.turn_number,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        assert any("current_mana" in e for e in errors)

    def test_max_mana_exceeds_cap(self):
        """max_mana exceeding MAX_MANA_CAP flagged as error."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        bad_player = Player(
            side=PlayerSide.PLAYER_1,
            hp=STARTING_HP,
            current_mana=STARTING_MANA,
            max_mana=MAX_MANA_CAP + 1,
            hand=state.players[0].hand,
            deck=state.players[0].deck,
            grave=(),
        )
        bad_state = GameState(
            board=state.board,
            players=(bad_player, state.players[1]),
            active_player_idx=state.active_player_idx,
            phase=state.phase,
            turn_number=state.turn_number,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        assert any("max_mana" in e for e in errors)

    def test_is_valid_state_false(self):
        """Invalid state returns False."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        bad_state = GameState(
            board=state.board,
            players=state.players,
            active_player_idx=5,
            phase=state.phase,
            turn_number=state.turn_number,
            seed=state.seed,
        )
        assert is_valid_state(bad_state) is False

    def test_multiple_errors_returned(self):
        """Multiple validation errors are all returned."""
        state, _ = GameState.new_game(42, DECK_P1, DECK_P2)
        bad_player = Player(
            side=PlayerSide.PLAYER_1,
            hp=STARTING_HP,
            current_mana=-1,
            max_mana=MAX_MANA_CAP + 1,
            hand=state.players[0].hand,
            deck=state.players[0].deck,
            grave=(),
        )
        bad_state = GameState(
            board=state.board,
            players=(bad_player, state.players[1]),
            active_player_idx=3,
            phase=state.phase,
            turn_number=0,
            seed=state.seed,
        )
        errors = validate_state(bad_state)
        # Should have at least 3 errors: active_player_idx, turn_number, mana
        assert len(errors) >= 3
