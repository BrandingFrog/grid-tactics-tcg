"""Tests for CheckpointManager -- checkpoint pool save/load/sample/prune.

Uses tmp_path fixture and a real MaskablePPO with a tiny DummyEnv
for save/load round-trips.
"""

from __future__ import annotations

import numpy as np
import pytest

from grid_tactics.rl.checkpoint_manager import CheckpointManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dummy_model(tmp_path):
    """Create a minimal MaskablePPO model for checkpoint testing."""
    import gymnasium
    from sb3_contrib import MaskablePPO

    class DummyEnv(gymnasium.Env):
        """Tiny env for fast model creation."""

        def __init__(self):
            super().__init__()
            self.observation_space = gymnasium.spaces.Box(
                low=-1.0, high=1.0, shape=(4,), dtype=np.float32,
            )
            self.action_space = gymnasium.spaces.Discrete(2)

        def reset(self, **kwargs):
            return np.zeros(4, dtype=np.float32), {}

        def step(self, action):
            return np.zeros(4, dtype=np.float32), 0.0, True, False, {}

        def action_masks(self):
            return np.ones(2, dtype=np.bool_)

    env = DummyEnv()
    model = MaskablePPO("MlpPolicy", env, n_steps=8, batch_size=8, verbose=0)
    return model


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckpointManager:
    """Tests for checkpoint pool management."""

    def test_save_creates_file(self, tmp_path):
        """save(model, step) creates a .zip file in pool_dir."""
        model = _make_dummy_model(tmp_path)
        mgr = CheckpointManager(pool_dir=tmp_path / "pool", pool_size=5)
        path = mgr.save(model, step=100)
        assert path.exists()
        assert path.suffix == ".zip"
        assert "100" in path.stem

    def test_sample_returns_latest(self, tmp_path):
        """With one checkpoint, sample always returns it."""
        model = _make_dummy_model(tmp_path)
        mgr = CheckpointManager(pool_dir=tmp_path / "pool", pool_size=5)
        mgr.save(model, step=100)
        for _ in range(10):
            result = mgr.sample()
            assert result is not None
            assert "100" in result.stem

    def test_sample_empty_returns_none(self, tmp_path):
        """With no checkpoints, sample returns None."""
        mgr = CheckpointManager(pool_dir=tmp_path / "pool", pool_size=5)
        assert mgr.sample() is None

    def test_sample_distribution(self, tmp_path):
        """With 5 checkpoints, sampling mixes latest and historical."""
        model = _make_dummy_model(tmp_path)
        mgr = CheckpointManager(pool_dir=tmp_path / "pool", pool_size=10)
        for step in [100, 200, 300, 400, 500]:
            mgr.save(model, step=step)

        latest_count = 0
        n_samples = 200
        for _ in range(n_samples):
            path = mgr.sample(latest_ratio=0.5)
            assert path is not None
            if "500" in path.stem:
                latest_count += 1

        # With 50% latest ratio, expect roughly 50-90% latest (includes cases
        # where random also picks latest). Should definitely be > 30%.
        assert latest_count > n_samples * 0.3, (
            f"Latest selected {latest_count}/{n_samples} times, "
            f"expected > {n_samples * 0.3}"
        )

    def test_prune_keeps_pool_size(self, tmp_path):
        """save 15, prune with pool_size=10, verify 10 remain (newest)."""
        model = _make_dummy_model(tmp_path)
        mgr = CheckpointManager(pool_dir=tmp_path / "pool", pool_size=10)
        for step in range(100, 1600, 100):
            mgr.save(model, step=step)

        assert len(mgr.list_checkpoints()) == 15
        mgr.prune()
        remaining = mgr.list_checkpoints()
        assert len(remaining) == 10

        # Verify the newest 10 are kept (steps 600-1500)
        steps = [int(p.stem.split("_")[1]) for p in remaining]
        assert min(steps) == 600
        assert max(steps) == 1500

    def test_list_checkpoints_sorted(self, tmp_path):
        """list_checkpoints returns paths sorted by step ascending."""
        model = _make_dummy_model(tmp_path)
        mgr = CheckpointManager(pool_dir=tmp_path / "pool", pool_size=10)
        for step in [300, 100, 500, 200, 400]:
            mgr.save(model, step=step)

        paths = mgr.list_checkpoints()
        steps = [int(p.stem.split("_")[1]) for p in paths]
        assert steps == sorted(steps)
