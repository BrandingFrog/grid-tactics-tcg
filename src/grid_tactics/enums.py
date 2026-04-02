from enum import IntEnum


class PlayerSide(IntEnum):
    """Which player. IntEnum for efficient serialization and numpy compatibility."""

    PLAYER_1 = 0
    PLAYER_2 = 1


class TurnPhase(IntEnum):
    """Current phase within a turn. ACTION = active player acts, REACT = opponent may counter."""

    ACTION = 0
    REACT = 1
