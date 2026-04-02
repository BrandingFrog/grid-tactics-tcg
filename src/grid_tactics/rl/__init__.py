"""RL encoding modules -- observation, action space, and reward.

Translates between the game engine's Python objects and numpy arrays
suitable for RL training with Gymnasium and MaskablePPO.
"""

from grid_tactics.rl.action_space import (
    ACTION_SPACE_SIZE,
    ActionEncoder,
    build_action_mask,
)
from grid_tactics.rl.observation import (
    OBSERVATION_SIZE,
    OBSERVATION_SPEC,
    encode_observation,
)
from grid_tactics.rl.reward import compute_reward

__all__ = [
    "encode_observation",
    "OBSERVATION_SIZE",
    "OBSERVATION_SPEC",
    "ActionEncoder",
    "ACTION_SPACE_SIZE",
    "build_action_mask",
    "compute_reward",
]
