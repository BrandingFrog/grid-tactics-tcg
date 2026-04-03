"""Batched reward computation.

Sparse reward: +1.0 win, -1.0 loss, 0.0 otherwise.
Matches the Python engine's compute_reward().
"""

from __future__ import annotations

import torch


def compute_rewards_batch(
    state,
    player_idx: torch.Tensor,  # [N] int32
) -> torch.Tensor:
    """Compute [N] float32 sparse reward for the given player perspective.

    +1.0 if player won, -1.0 if player lost, 0.0 otherwise (including draw).
    """
    is_over = state.is_game_over  # [N] bool
    winner = state.winner          # [N] int32 (-1=draw/none, 0=p1, 1=p2)

    is_win = is_over & (winner == player_idx)
    is_loss = is_over & (winner >= 0) & (winner != player_idx)

    reward = torch.zeros(player_idx.shape[0], dtype=torch.float32, device=player_idx.device)
    reward = torch.where(is_win, torch.tensor(1.0, device=player_idx.device), reward)
    reward = torch.where(is_loss, torch.tensor(-1.0, device=player_idx.device), reward)

    return reward
