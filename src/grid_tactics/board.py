"""Board dataclass representing the 5x5 game grid with geometry helpers."""

from dataclasses import dataclass, replace
from typing import Optional

from grid_tactics.enums import PlayerSide
from grid_tactics.types import (
    GRID_COLS,
    GRID_ROWS,
    GRID_SIZE,
    NEUTRAL_ROW,
    PLAYER_1_ROWS,
    PLAYER_2_ROWS,
    Position,
)


@dataclass(frozen=True, slots=True)
class Board:
    """Immutable 5x5 grid board. Cells store Optional[int] minion IDs.

    The grid uses row-major flat storage: index = row * GRID_COLS + col.
    All mutating operations return a new Board instance.
    """

    cells: tuple[Optional[int], ...]  # length 25, row-major

    @classmethod
    def empty(cls) -> "Board":
        """Create an empty board with all cells set to None."""
        return cls(cells=tuple(None for _ in range(GRID_SIZE)))

    def _index(self, row: int, col: int) -> int:
        """Convert (row, col) to flat index, raising ValueError if out of bounds."""
        if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
            raise ValueError(f"Position ({row}, {col}) out of bounds")
        return row * GRID_COLS + col

    def get(self, row: int, col: int) -> Optional[int]:
        """Return the cell value at (row, col). None for empty, int for minion_id."""
        return self.cells[self._index(row, col)]

    def place(self, row: int, col: int, minion_id: int) -> "Board":
        """Return a new Board with minion_id placed at (row, col).

        Raises ValueError if the cell is already occupied (D-03: one minion per space)
        or if the position is out of bounds.
        """
        idx = self._index(row, col)
        if self.cells[idx] is not None:
            raise ValueError(f"Cell ({row}, {col}) is already occupied")
        new_cells = list(self.cells)
        new_cells[idx] = minion_id
        return replace(self, cells=tuple(new_cells))

    def remove(self, row: int, col: int) -> "Board":
        """Return a new Board with the cell at (row, col) cleared to None."""
        idx = self._index(row, col)
        new_cells = list(self.cells)
        new_cells[idx] = None
        return replace(self, cells=tuple(new_cells))

    @staticmethod
    def is_valid_position(pos: Position) -> bool:
        """Return True if pos is within the 5x5 grid bounds."""
        r, c = pos
        return 0 <= r < GRID_ROWS and 0 <= c < GRID_COLS

    @staticmethod
    def get_row_owner(row: int) -> Optional[PlayerSide]:
        """Return the player who owns the given row, or None for neutral (D-01).

        Rows 0-1: Player 1, Row 2: neutral, Rows 3-4: Player 2.
        """
        if row in PLAYER_1_ROWS:
            return PlayerSide.PLAYER_1
        elif row in PLAYER_2_ROWS:
            return PlayerSide.PLAYER_2
        else:
            return None

    @staticmethod
    def get_orthogonal_adjacent(pos: Position) -> tuple[Position, ...]:
        """Return valid 4-direction (up/down/left/right) neighbors of pos (D-04)."""
        r, c = pos
        candidates = ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
        return tuple(p for p in candidates if Board.is_valid_position(p))

    @staticmethod
    def get_diagonal_adjacent(pos: Position) -> tuple[Position, ...]:
        """Return valid diagonal neighbors of pos."""
        r, c = pos
        candidates = ((r - 1, c - 1), (r - 1, c + 1), (r + 1, c - 1), (r + 1, c + 1))
        return tuple(p for p in candidates if Board.is_valid_position(p))

    @staticmethod
    def get_all_adjacent(pos: Position) -> tuple[Position, ...]:
        """Return all valid neighbors (orthogonal + diagonal) of pos."""
        return Board.get_orthogonal_adjacent(pos) + Board.get_diagonal_adjacent(pos)

    @staticmethod
    def manhattan_distance(a: Position, b: Position) -> int:
        """Return Manhattan distance: |r1-r2| + |c1-c2|."""
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    @staticmethod
    def chebyshev_distance(a: Position, b: Position) -> int:
        """Return Chebyshev distance: max(|r1-r2|, |c1-c2|)."""
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

    @staticmethod
    def get_positions_for_side(side: PlayerSide) -> tuple[Position, ...]:
        """Return all grid positions belonging to the given player's side."""
        rows = PLAYER_1_ROWS if side == PlayerSide.PLAYER_1 else PLAYER_2_ROWS
        return tuple((r, c) for r in rows for c in range(GRID_COLS))

    def get_occupied_positions(self) -> tuple[Position, ...]:
        """Return positions of all occupied cells."""
        return tuple(
            (i // GRID_COLS, i % GRID_COLS)
            for i, cell in enumerate(self.cells)
            if cell is not None
        )
