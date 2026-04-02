"""Training entry point for MaskablePPO self-play training.

Provides three public functions:
  - create_model: Build a configured MaskablePPO instance
  - evaluate_vs_random: Measure agent win rate against random play
  - train_self_play: Full self-play training loop with persistence

This is the Phase 6 capstone module, wiring together:
  - GridTacticsEnv (Phase 5) and SelfPlayEnv (Plan 02)
  - MaskablePPO from sb3-contrib (D-01)
  - CheckpointManager + SelfPlayCallback (Plan 02)
  - GameResultWriter + TrainingRunWriter (Plan 01)
  - TensorBoard logging
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sb3_contrib import MaskablePPO
from stable_baselines3.common.callbacks import BaseCallback

from grid_tactics.card_library import CardLibrary
from grid_tactics.db.writer import GameResultWriter, TrainingRunWriter
from grid_tactics.rl.callbacks import SelfPlayCallback
from grid_tactics.rl.checkpoint_manager import CheckpointManager
from grid_tactics.rl.env import GridTacticsEnv
from grid_tactics.rl.observation import encode_observation
from grid_tactics.rl.reward import compute_reward
from grid_tactics.rl.self_play import SelfPlayEnv


def create_model(
    env: SelfPlayEnv,
    seed: int = 42,
    tensorboard_log: str | None = "data/tb_logs",
    **kwargs: Any,
) -> MaskablePPO:
    """Create a configured MaskablePPO model for Grid Tactics.

    Default hyperparameters follow research recommendations:
      learning_rate=3e-4, n_steps=2048, batch_size=64, n_epochs=10,
      gamma=0.99, gae_lambda=0.95, clip_range=0.2, ent_coef=0.01,
      vf_coef=0.5, max_grad_norm=0.5.

    Args:
        env: SelfPlayEnv wrapping GridTacticsEnv.
        seed: Random seed for reproducibility.
        tensorboard_log: Directory for TensorBoard logs, or None to disable.
        **kwargs: Override any MaskablePPO parameter.

    Returns:
        Configured MaskablePPO instance.
    """
    defaults: dict[str, Any] = {
        "learning_rate": 3e-4,
        "n_steps": 2048,
        "batch_size": 64,
        "n_epochs": 10,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.2,
        "ent_coef": 0.01,
        "vf_coef": 0.5,
        "max_grad_norm": 0.5,
        "verbose": 1,
        "seed": seed,
        "tensorboard_log": tensorboard_log,
    }
    defaults.update(kwargs)
    return MaskablePPO("MlpPolicy", env, **defaults)


def evaluate_vs_random(
    model: MaskablePPO,
    env_or_factory: SelfPlayEnv,
    n_games: int = 100,
    seed_start: int = 10000,
) -> float:
    """Evaluate a trained model against a random opponent.

    Plays n_games where the model is player 0 and the opponent
    plays random legal actions.

    Args:
        model: Trained MaskablePPO model.
        env_or_factory: SelfPlayEnv to use for evaluation.
        n_games: Number of games to play.
        seed_start: Starting seed (incremented per game).

    Returns:
        Win rate as a float in [0.0, 1.0].
    """
    env = env_or_factory
    # Ensure random opponent during evaluation
    original_policy = env.opponent_policy
    env.set_opponent(None)

    wins = 0
    for i in range(n_games):
        obs, info = env.reset(seed=seed_start + i)
        done = False
        while not done:
            mask = info.get("action_mask", env.action_masks())
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(int(action))
            done = terminated or truncated
        # Reward > 0 means training agent (player 0) won
        if reward > 0:
            wins += 1

    # Restore original opponent
    env.set_opponent(original_policy)
    return wins / n_games


# ---------------------------------------------------------------------------
# Game logging callback for SQLite persistence
# ---------------------------------------------------------------------------


class _GameLoggingCallback(BaseCallback):
    """SB3 callback that logs completed game episodes to SQLite.

    Tracks episode completions via the 'dones' signal in SB3's
    training loop and records each game result via GameResultWriter.

    Periodically evaluates the model against random and records
    win rate snapshots via TrainingRunWriter.
    """

    def __init__(
        self,
        game_writer: GameResultWriter,
        run_writer: TrainingRunWriter,
        run_id: str,
        eval_env: SelfPlayEnv,
        eval_freq: int = 20_000,
        eval_games: int = 50,
        verbose: int = 0,
    ) -> None:
        super().__init__(verbose)
        self.game_writer = game_writer
        self.run_writer = run_writer
        self.run_id = run_id
        self.eval_env = eval_env
        self.eval_freq = eval_freq
        self.eval_games = eval_games
        self._episode_count = 0

    def _on_step(self) -> bool:
        """Called at every training step.

        Checks for completed episodes and records game results.
        Periodically evaluates against random.

        Returns:
            True (never stops training early).
        """
        # Check for completed episodes
        dones = self.locals.get("dones", None)
        if dones is None:
            # Fallback: some SB3 versions use 'done'
            dones = self.locals.get("done", None)

        if dones is not None:
            for done in dones:
                if done:
                    self._episode_count += 1
                    # Record the completed game
                    env = self._get_underlying_env()
                    if env is not None and env.state is not None:
                        state = env.state
                        winner = None
                        if state.is_game_over and state.winner is not None:
                            winner = state.winner.value

                        self.game_writer.record_game(
                            run_id=self.run_id,
                            episode_num=self._episode_count,
                            winner=winner,
                            turn_count=state.turn_number,
                            p1_hp=state.players[0].hp,
                            p2_hp=state.players[1].hp,
                            training_player=0,
                        )

        # Periodic evaluation
        if (
            self.eval_freq > 0
            and self.n_calls % self.eval_freq == 0
            and self.model is not None
        ):
            win_rate = evaluate_vs_random(
                self.model,
                self.eval_env,
                n_games=self.eval_games,
            )
            self.run_writer.record_snapshot(
                run_id=self.run_id,
                timestep=self.n_calls,
                episode_num=self._episode_count,
                win_rate_100=win_rate,
            )
            if self.verbose >= 1:
                print(
                    f"[GameLogging] Step {self.n_calls}: "
                    f"win_rate={win_rate:.2%}, episodes={self._episode_count}"
                )

        return True

    def _get_underlying_env(self) -> GridTacticsEnv | None:
        """Extract the underlying GridTacticsEnv from the training env stack.

        The env stack is: DummyVecEnv -> Monitor -> SelfPlayEnv -> GridTacticsEnv.
        We need to unwrap through all layers to reach GridTacticsEnv.
        """
        try:
            env = self.training_env.envs[0]  # type: ignore[attr-defined]
            # Unwrap through Monitor/SelfPlayEnv layers to GridTacticsEnv
            while hasattr(env, "env"):
                env = env.env
            if isinstance(env, GridTacticsEnv):
                return env
            return None
        except (AttributeError, IndexError):
            return None

    @property
    def episode_count(self) -> int:
        """Return the number of completed episodes."""
        return self._episode_count


# ---------------------------------------------------------------------------
# Deck building helper
# ---------------------------------------------------------------------------


def _build_standard_deck(library: CardLibrary) -> tuple[int, ...]:
    """Build a balanced 40-card deck from the starter card pool.

    Uses 2 copies of each of the 18 cards (36 total), then adds
    a 3rd copy of the 4 cheapest cards to reach exactly 40.

    Args:
        library: CardLibrary with all card definitions.

    Returns:
        Tuple of 40 numeric card IDs.
    """
    from grid_tactics.types import MIN_DECK_SIZE

    card_ids = sorted(library._card_id_to_id.keys())
    counts: dict[str, int] = {cid: 2 for cid in card_ids}

    # Current total: 36 cards. Need MIN_DECK_SIZE (40) total.
    deficit = MIN_DECK_SIZE - sum(counts.values())

    # Add extra copies of cheapest cards to fill
    cards_by_cost = sorted(card_ids, key=lambda c: library.get_by_card_id(c).mana_cost)
    for cid in cards_by_cost:
        if deficit <= 0:
            break
        if counts[cid] < 3:  # MAX_COPIES_PER_DECK
            counts[cid] += 1
            deficit -= 1

    return library.build_deck(counts)


# ---------------------------------------------------------------------------
# Main training function
# ---------------------------------------------------------------------------


def train_self_play(
    total_timesteps: int = 100_000,
    db_path: Path = Path("data/training.db"),
    checkpoint_dir: Path = Path("data/checkpoints"),
    tensorboard_log: str | None = "data/tb_logs",
    use_shaped_reward: bool = True,
    save_freq: int = 10_000,
    eval_freq: int = 20_000,
    eval_games: int = 50,
    description: str = "",
    seed: int = 42,
) -> dict[str, Any]:
    """Run a full self-play training session with MaskablePPO.

    Sets up the complete training pipeline:
      1. Loads card library and builds standard deck
      2. Creates GridTacticsEnv wrapped in SelfPlayEnv
      3. Creates MaskablePPO model via create_model()
      4. Sets up CheckpointManager, SelfPlayCallback, GameLoggingCallback
      5. Records training run metadata to SQLite
      6. Trains for total_timesteps
      7. Evaluates final model against random opponent
      8. Saves final model and closes writers

    Args:
        total_timesteps: Total environment steps for training.
        db_path: SQLite database path for persistence.
        checkpoint_dir: Directory for checkpoint pool.
        tensorboard_log: TensorBoard log dir, or None to disable.
        use_shaped_reward: Whether to use potential-based reward shaping.
        save_freq: Checkpoint save frequency in steps.
        eval_freq: Evaluation frequency in steps (0 to disable).
        eval_games: Number of games per evaluation.
        description: Optional description for the training run.
        seed: Random seed for reproducibility.

    Returns:
        Dict with run_id, final_win_rate, model_path, db_path.
    """
    # --- Setup ---
    library = CardLibrary.from_directory(Path("data/cards"))
    deck = _build_standard_deck(library)

    base_env = GridTacticsEnv(library, deck, deck, seed=seed)
    env = SelfPlayEnv(
        base_env, opponent_policy=None, use_shaped_reward=use_shaped_reward,
    )

    model = create_model(env, seed=seed, tensorboard_log=tensorboard_log)

    checkpoint_manager = CheckpointManager(pool_dir=checkpoint_dir, pool_size=10)
    self_play_callback = SelfPlayCallback(
        checkpoint_manager=checkpoint_manager, save_freq=save_freq, verbose=1,
    )

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    # --- Persistence ---
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run_writer = TrainingRunWriter(db_path)
    game_writer = GameResultWriter(db_path, buffer_size=50)

    hyperparameters = {
        "total_timesteps": total_timesteps,
        "learning_rate": 3e-4,
        "n_steps": 2048,
        "batch_size": 64,
        "n_epochs": 10,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "clip_range": 0.2,
        "ent_coef": 0.01,
        "use_shaped_reward": use_shaped_reward,
        "seed": seed,
    }
    run_writer.start_run(run_id, hyperparameters, description)

    # Build evaluation env (separate from training env)
    eval_base_env = GridTacticsEnv(library, deck, deck, seed=seed + 1000)
    eval_env = SelfPlayEnv(
        eval_base_env, opponent_policy=None, use_shaped_reward=False,
    )

    game_logging_callback = _GameLoggingCallback(
        game_writer=game_writer,
        run_writer=run_writer,
        run_id=run_id,
        eval_env=eval_env,
        eval_freq=eval_freq,
        eval_games=eval_games,
        verbose=1,
    )

    # --- Training ---
    model.learn(
        total_timesteps=total_timesteps,
        callback=[self_play_callback, game_logging_callback],
    )

    # --- Cleanup ---
    # Save final model
    final_model_dir = checkpoint_dir / "final"
    final_model_dir.mkdir(parents=True, exist_ok=True)
    final_model_path = final_model_dir / f"{run_id}"
    model.save(str(final_model_path))

    # Evaluate final model
    final_win_rate = evaluate_vs_random(
        model, eval_env, n_games=eval_games, seed_start=50000,
    )

    # End training run
    run_writer.end_run(
        run_id,
        total_timesteps=total_timesteps,
        model_path=str(final_model_path) + ".zip",
    )

    # Flush remaining buffered game results
    game_writer.flush()

    return {
        "run_id": run_id,
        "final_win_rate": final_win_rate,
        "model_path": str(final_model_path) + ".zip",
        "db_path": str(db_path),
    }
