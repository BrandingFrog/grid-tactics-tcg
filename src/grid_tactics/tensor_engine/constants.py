"""Tensor engine constants -- fixed sizes for padded tensor structures.

All variable-length game structures use fixed-size tensors with sentinel
values (-1) and size counters. This avoids dynamic shapes that would
break torch.compile.
"""

from grid_tactics.types import (
    BACK_ROW_P1,
    BACK_ROW_P2,
    DEFAULT_TURN_LIMIT,
    GRID_COLS,
    GRID_ROWS,
    GRID_SIZE,
    MAX_MANA_CAP,
    MAX_REACT_STACK_DEPTH,
    MAX_STAT,
    MIN_DECK_SIZE,
    STARTING_HAND_SIZE,
    STARTING_HP,
    STARTING_MANA,
)

# Fixed sizes for padded tensors
MAX_HAND: int = 10
MAX_DECK: int = 40  # MIN_DECK_SIZE
MAX_GRAVEYARD: int = 80  # 2 decks worth
MAX_MINIONS: int = 25  # 5x5 grid
MAX_EFFECTS_PER_CARD: int = 3
MAX_REACT_DEPTH: int = MAX_REACT_STACK_DEPTH  # 10

# Action space layout (must match rl/action_space.py exactly)
ACTION_SPACE_SIZE: int = 1287
PLAY_CARD_BASE: int = 0       # 250 slots: hand(10) * grid(25)
MOVE_BASE: int = 250           # 100 slots: source(25) * dir(4)
ATTACK_BASE: int = 350         # 625 slots: source(25) * target(25)
SACRIFICE_BASE: int = 975      # 25 slots: source(25)
DRAW_IDX: int = 1000
PASS_IDX: int = 1001
REACT_BASE: int = 1002         # 260 slots: hand(10) * target_or_none(26)
ACTIVATE_BASE: int = 1262      # 25 slots: source(25), one per board tile

# Sentinel value for empty slots
EMPTY: int = -1
