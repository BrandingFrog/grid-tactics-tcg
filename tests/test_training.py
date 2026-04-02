"""Integration tests for the RL training pipeline.

Tests create_model, train_self_play, and evaluate_vs_random from
training.py -- the Phase 6 capstone module that wires MaskablePPO,
SelfPlayEnv, callbacks, and SQLite persistence into a complete pipeline.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.rl.env import GridTacticsEnv
from grid_tactics.rl.self_play import SelfPlayEnv
from grid_tactics.rl.training import (
    create_model,
    evaluate_vs_random,
    train_self_play,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env() -> SelfPlayEnv:
    """Build a SelfPlayEnv with starter deck for testing."""
    library = CardLibrary.from_directory(Path("data/cards"))
    # Build a 40-card deck: 2 copies of each of 18 cards = 36, + 4 extras
    card_ids = sorted(library._card_id_to_id.keys())
    counts: dict[str, int] = {cid: 2 for cid in card_ids}
    # Add extra copies to hit 40 (pick first 4 cards for a 3rd copy)
    for cid in card_ids[:4]:
        counts[cid] = 3
    deck = library.build_deck(counts)
    base_env = GridTacticsEnv(library, deck, deck, seed=42)
    return SelfPlayEnv(base_env, opponent_policy=None, use_shaped_reward=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_model():
    """create_model returns a MaskablePPO with correct spaces."""
    from sb3_contrib import MaskablePPO

    env = _make_env()
    model = create_model(env, tensorboard_log=None)
    assert isinstance(model, MaskablePPO)
    assert model.observation_space == env.observation_space
    assert model.action_space == env.action_space


def test_minimal_training():
    """model.learn(512 steps) completes without crashing."""
    env = _make_env()
    model = create_model(env, tensorboard_log=None)
    model.learn(total_timesteps=512)


def test_model_save_load(tmp_path: Path):
    """Save and load a model, verify predict still works."""
    import numpy as np
    from sb3_contrib import MaskablePPO

    env = _make_env()
    model = create_model(env, tensorboard_log=None)
    save_path = tmp_path / "test_model"
    model.save(str(save_path))

    loaded = MaskablePPO.load(str(save_path))
    obs, info = env.reset()
    mask = info["action_mask"]
    action, _ = loaded.predict(obs, action_masks=mask, deterministic=True)
    assert 0 <= int(action) < env.action_space.n


def test_evaluate_vs_random():
    """evaluate_vs_random returns a float win rate in [0, 1]."""
    env = _make_env()
    model = create_model(env, tensorboard_log=None)
    win_rate = evaluate_vs_random(model, env, n_games=5, seed_start=10000)
    assert isinstance(win_rate, float)
    assert 0.0 <= win_rate <= 1.0


def test_train_self_play_creates_db(tmp_path: Path):
    """train_self_play creates SQLite DB with training_runs and game_results rows."""
    db_path = tmp_path / "test_training.db"
    checkpoint_dir = tmp_path / "checkpoints"

    result = train_self_play(
        total_timesteps=1024,
        db_path=db_path,
        checkpoint_dir=checkpoint_dir,
        tensorboard_log=None,
        use_shaped_reward=True,
        save_freq=512,
        eval_freq=0,  # disable periodic eval for speed
        eval_games=5,
        seed=42,
    )

    assert "run_id" in result
    assert "model_path" in result
    assert db_path.exists()

    # Verify training_runs table has a row
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        runs = conn.execute("SELECT * FROM training_runs").fetchall()
        assert len(runs) >= 1
        run = runs[0]
        assert run["run_id"] == result["run_id"]
        assert run["total_timesteps"] is not None

        # Verify game_results has some rows
        games = conn.execute("SELECT COUNT(*) as cnt FROM game_results").fetchone()
        assert games["cnt"] >= 1
    finally:
        conn.close()


@pytest.mark.slow
def test_beats_random(tmp_path: Path):
    """After training, agent beats random play with > 60% win rate.

    This is the Phase 6 capstone validation (D-03).
    Trains for 100K+ timesteps which may take several minutes.
    """
    db_path = tmp_path / "beats_random.db"
    checkpoint_dir = tmp_path / "checkpoints"

    result = train_self_play(
        total_timesteps=500_000,
        db_path=db_path,
        checkpoint_dir=checkpoint_dir,
        tensorboard_log=None,
        use_shaped_reward=True,
        save_freq=50_000,
        eval_freq=0,  # skip periodic eval; we'll evaluate after
        eval_games=100,
        seed=42,
    )

    assert result["final_win_rate"] >= 0.60, (
        f"Agent win rate {result['final_win_rate']:.2%} is below 60% threshold"
    )
