"""RL modules -- observation, action space, reward, environment, and self-play.

Translates between the game engine's Python objects and numpy arrays
suitable for RL training with Gymnasium and MaskablePPO.
"""

from grid_tactics.rl.action_space import (
    ACTION_SPACE_SIZE,
    ActionEncoder,
    build_action_mask,
)
from grid_tactics.rl.callbacks import SelfPlayCallback
from grid_tactics.rl.checkpoint_manager import CheckpointManager
from grid_tactics.rl.env import GridTacticsEnv
from grid_tactics.rl.observation import (
    OBSERVATION_SIZE,
    OBSERVATION_SPEC,
    encode_observation,
)
from grid_tactics.rl.reward import compute_reward, compute_shaped_reward, potential
from grid_tactics.rl.self_play import SelfPlayEnv
from grid_tactics.rl.training import create_model, evaluate_vs_random, train_self_play

__all__ = [
    "encode_observation",
    "OBSERVATION_SIZE",
    "OBSERVATION_SPEC",
    "ActionEncoder",
    "ACTION_SPACE_SIZE",
    "build_action_mask",
    "compute_reward",
    "compute_shaped_reward",
    "potential",
    "GridTacticsEnv",
    "SelfPlayEnv",
    "SelfPlayCallback",
    "CheckpointManager",
    "create_model",
    "train_self_play",
    "evaluate_vs_random",
]
