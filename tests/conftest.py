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


# ---------------------------------------------------------------------------
# Phase 3: Minion and action fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def make_minion():
    """Factory fixture for creating MinionInstance instances with defaults."""

    def _make_minion(
        instance_id=0,
        card_numeric_id=0,
        owner=PlayerSide.PLAYER_1,
        position=(0, 0),
        current_health=3,
        attack_bonus=0,
    ):
        from grid_tactics.minion import MinionInstance

        return MinionInstance(
            instance_id=instance_id,
            card_numeric_id=card_numeric_id,
            owner=owner,
            position=position,
            current_health=current_health,
            attack_bonus=attack_bonus,
        )

    return _make_minion


@pytest.fixture
def make_game_state_with_minions(make_player, empty_board, make_minion):
    """Factory fixture for creating GameState with minions on the board.

    Creates a GameState with the given minions placed on the board and
    tracked in the minions tuple.
    """

    def _make_game_state_with_minions(minions=None, **kwargs):
        from grid_tactics.game_state import GameState

        if minions is None:
            minions = ()

        # Build board with minions placed
        board = empty_board
        for m in minions:
            board = board.place(m.position[0], m.position[1], m.instance_id)

        # Determine next_minion_id from existing minions
        next_id = max((m.instance_id for m in minions), default=-1) + 1

        defaults = dict(
            board=board,
            players=(make_player(), make_player(side=PlayerSide.PLAYER_2)),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=1,
            seed=42,
            minions=tuple(minions),
            next_minion_id=next_id,
        )
        defaults.update(kwargs)
        return GameState(**defaults)

    return _make_game_state_with_minions
