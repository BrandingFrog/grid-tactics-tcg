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
STARTING_HP: int = 20
STARTING_HAND_SIZE: int = 5
