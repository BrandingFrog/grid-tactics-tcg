"""SB3 callbacks for self-play training.

SelfPlayCallback saves model checkpoints to a pool at regular intervals
and swaps the opponent in the SelfPlayEnv from the checkpoint pool.
"""

from __future__ import annotations

from stable_baselines3.common.callbacks import BaseCallback

from grid_tactics.rl.checkpoint_manager import CheckpointManager


class SelfPlayCallback(BaseCallback):
    """SB3 callback for checkpoint pool management during self-play.

    At every save_freq steps:
    1. Saves the current model to the checkpoint pool
    2. Prunes old checkpoints exceeding pool size
    3. Samples an opponent from the pool and sets it on the SelfPlayEnv

    Attributes:
        checkpoint_manager: Manager for the checkpoint pool.
        save_freq: Save/swap frequency in training steps.
    """

    def __init__(
        self,
        checkpoint_manager: CheckpointManager,
        save_freq: int = 10_000,
        verbose: int = 0,
    ) -> None:
        """Initialize the self-play callback.

        Args:
            checkpoint_manager: CheckpointManager instance for pool operations.
            save_freq: How often (in steps) to save checkpoints and swap opponents.
            verbose: Verbosity level (0=silent, 1=info).
        """
        super().__init__(verbose)
        self.checkpoint_manager = checkpoint_manager
        self.save_freq = save_freq

    def _on_step(self) -> bool:
        """Called at every training step.

        At save_freq intervals: save checkpoint, prune pool, swap opponent.

        Returns:
            True (never stops training early).
        """
        if self.n_calls % self.save_freq == 0:
            # Save current model to pool
            self.checkpoint_manager.save(self.model, self.n_calls)

            # Prune old checkpoints
            self.checkpoint_manager.prune()

            # Sample opponent from pool and set on env
            path = self.checkpoint_manager.sample()
            if path is not None:
                self._swap_opponent(path)

            if self.verbose >= 1:
                pool_count = len(self.checkpoint_manager.list_checkpoints())
                print(
                    f"[SelfPlayCallback] Step {self.n_calls}: "
                    f"saved checkpoint, pool size={pool_count}"
                )

        return True

    def _swap_opponent(self, checkpoint_path) -> None:
        """Load a checkpoint and set as opponent in all SelfPlayEnv instances.

        Handles both DummyVecEnv (direct access) and SubprocVecEnv (env_method).

        Args:
            checkpoint_path: Path to the checkpoint .zip file.
        """
        try:
            from sb3_contrib import MaskablePPO
            from stable_baselines3.common.vec_env import SubprocVecEnv

            opponent = MaskablePPO.load(str(checkpoint_path), device="cpu")

            if isinstance(self.training_env, SubprocVecEnv):
                # SubprocVecEnv: can't send a model object across processes.
                # Instead, send the checkpoint path and let each env load it.
                self.training_env.env_method(
                    "_load_opponent_from_path",
                    str(checkpoint_path),
                )
            else:
                # DummyVecEnv: direct access to env objects
                for vec_env in self.training_env.envs:  # type: ignore[attr-defined]
                    env = vec_env
                    # Unwrap through Monitor wrapper if present
                    while hasattr(env, "env") and not hasattr(env, "set_opponent"):
                        env = env.env
                    if hasattr(env, "set_opponent"):
                        env.set_opponent(opponent)
        except Exception as e:
            if self.verbose >= 1:
                print(f"[SelfPlayCallback] Failed to swap opponent: {e}")
