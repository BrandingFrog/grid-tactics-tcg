"""Comprehensive tests for Board dataclass and grid geometry helpers."""

import pytest

from grid_tactics.board import Board
from grid_tactics.enums import PlayerSide
from grid_tactics.types import GRID_COLS, GRID_ROWS, GRID_SIZE


# -- Board creation --


class TestBoardCreation:
    def test_empty_board_all_none(self):
        """Board.empty() creates a 5x5 grid with all cells None."""
        board = Board.empty()
        assert len(board.cells) == GRID_SIZE
        assert all(cell is None for cell in board.cells)

    def test_board_is_frozen(self):
        """Assigning to board.cells raises FrozenInstanceError (or AttributeError)."""
        board = Board.empty()
        with pytest.raises(AttributeError):
            board.cells = (1,) * GRID_SIZE

    def test_cells_is_tuple(self):
        """Board.cells is a tuple, not a list."""
        board = Board.empty()
        assert isinstance(board.cells, tuple)


# -- Board.get --


class TestBoardGet:
    def test_get_valid_position(self):
        """Board.get(2,3) returns None on empty board."""
        board = Board.empty()
        assert board.get(2, 3) is None

    def test_get_invalid_position(self):
        """Board.get(5,0) raises ValueError for out-of-bounds."""
        board = Board.empty()
        with pytest.raises(ValueError):
            board.get(5, 0)

    def test_get_negative_row(self):
        """Board.get(-1,0) raises ValueError."""
        board = Board.empty()
        with pytest.raises(ValueError):
            board.get(-1, 0)

    def test_get_negative_col(self):
        """Board.get(0,-1) raises ValueError."""
        board = Board.empty()
        with pytest.raises(ValueError):
            board.get(0, -1)


# -- Board.place --


class TestBoardPlace:
    def test_place_minion(self):
        """Board.place(0,0,1) returns new Board with minion_id 1 at (0,0)."""
        board = Board.empty()
        new_board = board.place(0, 0, 1)
        assert new_board.get(0, 0) == 1

    def test_place_occupied_raises(self):
        """Placing on occupied cell raises ValueError (D-03: one minion per space)."""
        board = Board.empty().place(2, 2, 1)
        with pytest.raises(ValueError, match="already occupied"):
            board.place(2, 2, 2)

    def test_place_returns_new_board(self):
        """Original board unchanged after place() -- immutability."""
        board = Board.empty()
        new_board = board.place(0, 0, 1)
        assert board.get(0, 0) is None
        assert new_board.get(0, 0) == 1
        assert board is not new_board

    def test_place_out_of_bounds(self):
        """Board.place raises ValueError for out-of-bounds positions."""
        board = Board.empty()
        with pytest.raises(ValueError):
            board.place(5, 0, 1)

    def test_place_multiple_minions(self):
        """Multiple minions can be placed on different cells."""
        board = Board.empty()
        board = board.place(0, 0, 1)
        board = board.place(1, 1, 2)
        board = board.place(4, 4, 3)
        assert board.get(0, 0) == 1
        assert board.get(1, 1) == 2
        assert board.get(4, 4) == 3


# -- Board.remove --


class TestBoardRemove:
    def test_remove_minion(self):
        """Board.remove(r,c) clears cell to None."""
        board = Board.empty().place(1, 1, 42)
        cleared = board.remove(1, 1)
        assert cleared.get(1, 1) is None

    def test_remove_returns_new_board(self):
        """Original board unchanged after remove()."""
        board = Board.empty().place(1, 1, 42)
        cleared = board.remove(1, 1)
        assert board.get(1, 1) == 42
        assert cleared.get(1, 1) is None


# -- Row ownership --


class TestRowOwnership:
    def test_row_ownership_player1(self):
        """get_row_owner(0) and get_row_owner(1) return PlayerSide.PLAYER_1."""
        assert Board.get_row_owner(0) == PlayerSide.PLAYER_1
        assert Board.get_row_owner(1) == PlayerSide.PLAYER_1

    def test_row_ownership_neutral(self):
        """get_row_owner(2) returns None."""
        assert Board.get_row_owner(2) is None

    def test_row_ownership_player2(self):
        """get_row_owner(3) and get_row_owner(4) return PlayerSide.PLAYER_2."""
        assert Board.get_row_owner(3) == PlayerSide.PLAYER_2
        assert Board.get_row_owner(4) == PlayerSide.PLAYER_2


# -- Orthogonal adjacency --


class TestOrthogonalAdjacent:
    def test_orthogonal_corner_00(self):
        """Corner (0,0) has exactly [(0,1), (1,0)]."""
        result = set(Board.get_orthogonal_adjacent((0, 0)))
        assert result == {(0, 1), (1, 0)}

    def test_orthogonal_corner_44(self):
        """Corner (4,4) has exactly [(3,4), (4,3)]."""
        result = set(Board.get_orthogonal_adjacent((4, 4)))
        assert result == {(3, 4), (4, 3)}

    def test_orthogonal_edge(self):
        """Edge (0,2) has exactly 3 neighbors."""
        result = set(Board.get_orthogonal_adjacent((0, 2)))
        assert result == {(0, 1), (0, 3), (1, 2)}

    def test_orthogonal_interior(self):
        """Interior (2,2) has exactly 4 neighbors."""
        result = set(Board.get_orthogonal_adjacent((2, 2)))
        assert result == {(1, 2), (3, 2), (2, 1), (2, 3)}

    def test_orthogonal_all_25_positions(self):
        """Every position returns only valid in-bounds neighbors."""
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                neighbors = Board.get_orthogonal_adjacent((r, c))
                for nr, nc in neighbors:
                    assert 0 <= nr < GRID_ROWS, f"Row {nr} out of bounds for neighbor of ({r},{c})"
                    assert 0 <= nc < GRID_COLS, f"Col {nc} out of bounds for neighbor of ({r},{c})"
                    # Must be exactly 1 step in one direction
                    assert abs(nr - r) + abs(nc - c) == 1, (
                        f"({nr},{nc}) is not orthogonally adjacent to ({r},{c})"
                    )


# -- Diagonal adjacency --


class TestDiagonalAdjacent:
    def test_diagonal_corner_00(self):
        """Corner (0,0) has exactly [(1,1)]."""
        result = set(Board.get_diagonal_adjacent((0, 0)))
        assert result == {(1, 1)}

    def test_diagonal_corner_44(self):
        """Corner (4,4) has exactly [(3,3)]."""
        result = set(Board.get_diagonal_adjacent((4, 4)))
        assert result == {(3, 3)}

    def test_diagonal_interior(self):
        """Interior (2,2) has exactly 4 diagonal neighbors."""
        result = set(Board.get_diagonal_adjacent((2, 2)))
        assert result == {(1, 1), (1, 3), (3, 1), (3, 3)}


# -- All adjacent (combined) --


class TestAllAdjacent:
    def test_all_adjacent_combines(self):
        """get_all_adjacent returns orthogonal + diagonal combined."""
        ortho = set(Board.get_orthogonal_adjacent((2, 2)))
        diag = set(Board.get_diagonal_adjacent((2, 2)))
        all_adj = set(Board.get_all_adjacent((2, 2)))
        assert all_adj == ortho | diag

    def test_all_adjacent_corner(self):
        """Corner (0,0) has 3 total neighbors: 2 ortho + 1 diag."""
        result = Board.get_all_adjacent((0, 0))
        assert len(result) == 3


# -- Distance functions --


class TestDistances:
    def test_manhattan_distance(self):
        """Manhattan distance: |r1-r2| + |c1-c2|."""
        assert Board.manhattan_distance((0, 0), (4, 4)) == 8
        assert Board.manhattan_distance((0, 0), (0, 0)) == 0
        assert Board.manhattan_distance((0, 0), (2, 3)) == 5
        assert Board.manhattan_distance((1, 2), (3, 4)) == 4

    def test_chebyshev_distance(self):
        """Chebyshev distance: max(|r1-r2|, |c1-c2|)."""
        assert Board.chebyshev_distance((0, 0), (4, 4)) == 4
        assert Board.chebyshev_distance((0, 0), (1, 1)) == 1
        assert Board.chebyshev_distance((0, 0), (0, 0)) == 0
        assert Board.chebyshev_distance((1, 0), (3, 0)) == 2


# -- Position queries --


class TestPositionQueries:
    def test_positions_for_player1(self):
        """get_positions_for_side(P1) returns 10 positions in rows 0-1."""
        positions = Board.get_positions_for_side(PlayerSide.PLAYER_1)
        assert len(positions) == 10
        for r, c in positions:
            assert r in (0, 1)
            assert 0 <= c < GRID_COLS

    def test_positions_for_player2(self):
        """get_positions_for_side(P2) returns 10 positions in rows 3-4."""
        positions = Board.get_positions_for_side(PlayerSide.PLAYER_2)
        assert len(positions) == 10
        for r, c in positions:
            assert r in (3, 4)
            assert 0 <= c < GRID_COLS

    def test_occupied_positions(self):
        """After placing 3 minions, get_occupied_positions returns those 3 positions."""
        board = Board.empty()
        board = board.place(0, 0, 1)
        board = board.place(2, 3, 2)
        board = board.place(4, 4, 3)
        occupied = set(board.get_occupied_positions())
        assert occupied == {(0, 0), (2, 3), (4, 4)}

    def test_occupied_positions_empty_board(self):
        """Empty board has no occupied positions."""
        board = Board.empty()
        assert len(board.get_occupied_positions()) == 0


# -- is_valid_position --


class TestIsValidPosition:
    def test_is_valid_position(self):
        """True for valid positions, False for invalid."""
        assert Board.is_valid_position((0, 0)) is True
        assert Board.is_valid_position((4, 4)) is True
        assert Board.is_valid_position((2, 2)) is True

    def test_is_valid_position_out_of_bounds(self):
        """False for out-of-bounds positions."""
        assert Board.is_valid_position((-1, 0)) is False
        assert Board.is_valid_position((5, 0)) is False
        assert Board.is_valid_position((0, 5)) is False
        assert Board.is_valid_position((0, -1)) is False
