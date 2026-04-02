"""Reward computation for RL training.

Provides:
- compute_reward: Sparse +1.0 win, -1.0 loss, 0.0 in-progress/draw.
- potential: Heuristic potential function for reward shaping.
- compute_shaped_reward: Potential-based reward shaping F(s,s') = gamma*Phi(s')-Phi(s).

The potential-based formulation preserves the optimal policy (Ng et al., 1999).
"""

from __future__ import annotations

from grid_tactics.enums import PlayerSide
from grid_tactics.game_state import GameState
from grid_tactics.types import MAX_MANA_CAP, STARTING_HP


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


# ---------------------------------------------------------------------------
# Potential-based reward shaping (D-04, D-06)
# ---------------------------------------------------------------------------

# Component weights (per research recommendation)
_HP_WEIGHT: float = 0.3
_BOARD_WEIGHT: float = 0.3
_MANA_WEIGHT: float = 0.2
_ADVANCEMENT_WEIGHT: float = 0.2


def potential(state: GameState, player_idx: int) -> float:
    """Compute heuristic potential function for reward shaping.

    Higher value means a better position for the given player.
    Uses 4 components weighted to stay in [-1.0, 1.0]:
      - HP advantage (0.3): normalized HP difference
      - Board control (0.3): minion count advantage
      - Mana efficiency (0.2): current mana availability
      - Positional advancement (0.2): average minion advancement toward opponent back row

    Args:
        state: Current game state.
        player_idx: 0 or 1, which player's perspective.

    Returns:
        Float in [-1.0, 1.0] representing positional evaluation.
    """
    me = state.players[player_idx]
    opp = state.players[1 - player_idx]

    # HP advantage: (my_hp - opp_hp) / (STARTING_HP * 2)
    hp_diff = (me.hp - opp.hp) / (STARTING_HP * 2)

    # Board control: (my_minions - opp_minions) / 10.0
    my_minions = len(state.get_minions_for_side(PlayerSide(player_idx)))
    opp_minions = len(state.get_minions_for_side(PlayerSide(1 - player_idx)))
    board_diff = (my_minions - opp_minions) / 10.0

    # Mana efficiency: my_current_mana / MAX_MANA_CAP
    mana_norm = me.current_mana / MAX_MANA_CAP

    # Positional advancement: average row progress toward opponent back row
    advancement = 0.0
    for m in state.get_minions_for_side(PlayerSide(player_idx)):
        if player_idx == 0:
            # Player 0 advances toward row 4
            advancement += m.position[0] / 4.0
        else:
            # Player 1 advances toward row 0
            advancement += (4 - m.position[0]) / 4.0
    advancement /= max(my_minions, 1)

    raw = (
        _HP_WEIGHT * hp_diff
        + _BOARD_WEIGHT * board_diff
        + _MANA_WEIGHT * mana_norm
        + _ADVANCEMENT_WEIGHT * advancement
    )

    # Clamp to [-1.0, 1.0]
    return max(-1.0, min(1.0, raw))


def compute_shaped_reward(
    prev_state: GameState,
    new_state: GameState,
    player_idx: int,
    gamma: float = 0.99,
) -> float:
    """Compute potential-based shaped reward.

    Implements F(s,s') = gamma * Phi(s') - Phi(s) added to the base
    sparse reward. This formulation preserves the optimal policy
    (Ng et al., 1999, per D-06).

    Args:
        prev_state: State before the action.
        new_state: State after the action.
        player_idx: 0 or 1, which player's perspective.
        gamma: Discount factor (default 0.99).

    Returns:
        base_reward + gamma * potential(new) - potential(prev).
    """
    base = compute_reward(new_state, player_idx)
    shaping = gamma * potential(new_state, player_idx) - potential(prev_state, player_idx)
    return base + shaping
