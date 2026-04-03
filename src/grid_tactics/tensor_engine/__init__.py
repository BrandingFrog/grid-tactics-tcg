"""GPU-vectorized game engine for Grid Tactics.

Runs N games simultaneously as PyTorch tensor operations, targeting
50-100x speedup over the Python engine for RL training.
"""

from grid_tactics.tensor_engine.card_table import CardTable
from grid_tactics.tensor_engine.engine import TensorGameEngine
from grid_tactics.tensor_engine.state import TensorGameState
from grid_tactics.tensor_engine.vec_env import TensorVecEnv

__all__ = [
    "CardTable",
    "TensorGameEngine",
    "TensorGameState",
    "TensorVecEnv",
]
