"""GPU-vectorized game engine for Grid Tactics.

Runs N games simultaneously as PyTorch tensor operations, targeting
50-100x speedup over the Python engine for RL training.

STATUS: On hold (April 2026). Game rules are still changing rapidly
(new keywords, effects, react mechanics) and keeping this engine in
sync with the Python engine is costly. Code is preserved but not
actively maintained. Will be revisited once the card set stabilizes.
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
