"""Sparse reward computation for RL training.

Returns +1.0 for win, -1.0 for loss, 0.0 for in-progress or draw.
Reward shaping can be added in later phases if needed.
"""

from __future__ import annotations

from grid_tactics.enums import PlayerSide
from grid_tactics.game_state import GameState


def compute_reward(state: GameState, player_idx: int) -> float:
    """Compute sparse reward from game state for the given player.

    Args:
        state: Current game state.
        player_idx: 0 or 1, which player's perspective.

    Returns:
        +1.0 if player won, -1.0 if player lost, 0.0 otherwise.
    """
    if not state.is_game_over:
        return 0.0

    if state.winner is None:
        # Draw
        return 0.0

    if state.winner == PlayerSide(player_idx):
        return 1.0
    else:
        return -1.0
