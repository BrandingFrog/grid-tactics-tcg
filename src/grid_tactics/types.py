"""Type aliases and constants for grid geometry."""

# Grid dimensions (per D-01, D-02: fixed 5x5 grid, all columns equal)
GRID_ROWS: int = 5
GRID_COLS: int = 5
GRID_SIZE: int = GRID_ROWS * GRID_COLS  # 25 cells total

# Position is always (row, col) -- never (x, y) to avoid confusion
Position = tuple[int, int]

# Row ownership boundaries (per D-01)
PLAYER_1_ROWS: tuple[int, ...] = (0, 1)  # Rows 0-1 = Player 1
PLAYER_2_ROWS: tuple[int, ...] = (3, 4)  # Rows 3-4 = Player 2
NEUTRAL_ROW: int = 2  # Row 2 = No-man's-land

# Mana constants (per D-05 through D-08)
STARTING_MANA: int = 1
MANA_REGEN_PER_TURN: int = 1
MAX_MANA_CAP: int = 10

# Player constants (per D-09, D-10)
STARTING_HP: int = 100
STARTING_HAND_SIZE: int = 5  # legacy default
STARTING_HAND_P1: int = 3    # Player 1 (goes first) draws fewer
STARTING_HAND_P2: int = 4    # Player 2 (goes second) draws more to compensate

# ---------------------------------------------------------------------------
# Phase 2: Card system constants
# ---------------------------------------------------------------------------

# Card deck constraints (per D-12, D-13)
MAX_COPIES_PER_DECK: int = 3
MIN_DECK_SIZE: int = 30

# Card stat ranges (per D-19: stats in 1-5 range)
MIN_STAT: int = 1
MAX_STAT: int = 100

# Effect amount range (starter 1-5, extensible to 10 for Phase 8)
MAX_EFFECT_AMOUNT: int = 100

# ---------------------------------------------------------------------------
# Phase 3: Action system constants
# ---------------------------------------------------------------------------

# Auto-draw variant flag (D-15, ENG-08): when True, draw happens at turn
# start and DRAW is removed from legal actions
AUTO_DRAW_ENABLED: bool = False

# Safety cap to prevent infinite react chaining (research Pitfall 3)
MAX_REACT_STACK_DEPTH: int = 10

# Back-row deployment positions for ranged minions (D-09)
BACK_ROW_P1: int = 0  # Player 1's back row
BACK_ROW_P2: int = 4  # Player 2's back row

# ---------------------------------------------------------------------------
# Phase 4: Game loop constants
# ---------------------------------------------------------------------------

# Maximum turns before game is declared a draw (D-11)
DEFAULT_TURN_LIMIT: int = 100
