import pytest

from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.types import (
    STARTING_HP,
    STARTING_MANA,
    GRID_SIZE,
    STARTING_HAND_SIZE,
)


@pytest.fixture
def make_player():
    """Factory fixture for creating Player instances with defaults."""

    def _make_player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=STARTING_MANA,
        max_mana=STARTING_MANA,
        hand=(),
        deck=(),
        graveyard=(),
    ):
        from grid_tactics.player import Player

        return Player(
            side=side,
            hp=hp,
            current_mana=current_mana,
            max_mana=max_mana,
            hand=hand,
            deck=deck,
            graveyard=graveyard,
        )

    return _make_player


@pytest.fixture
def empty_board():
    """An empty 5x5 board (all None)."""
    from grid_tactics.board import Board

    return Board.empty()


@pytest.fixture
def default_seed():
    """Standard seed for deterministic tests."""
    return 42
