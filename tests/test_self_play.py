"""Tests for SelfPlayEnv wrapper.

Uses real GridTacticsEnv with CardLibrary from data/cards.
Verifies action mask delegation, random opponent, obs perspective,
auto-stepping opponent, and set_opponent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.rl.action_space import ACTION_SPACE_SIZE
from grid_tactics.rl.env import GridTacticsEnv
from grid_tactics.rl.observation import OBSERVATION_SIZE
from grid_tactics.rl.self_play import SelfPlayEnv


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"


@pytest.fixture
def library():
    """Load CardLibrary from data/cards."""
    return CardLibrary.from_directory(DATA_DIR)


@pytest.fixture
def deck(library):
    """Build a valid 40-card deck for testing."""
    card_counts = {
        "fire_imp": 3,
        "shadow_stalker": 3,
        "dark_assassin": 3,
        "light_cleric": 3,
        "wind_archer": 3,
        "dark_sentinel": 3,
        "holy_paladin": 3,
        "iron_guardian": 3,
        "shadow_knight": 3,
        "stone_golem": 1,
        "fireball": 3,
        "holy_light": 3,
        "dark_drain": 3,
        "shield_block": 3,
    }
    return library.build_deck(card_counts)


@pytest.fixture
def base_env(library, deck):
    """Create a base GridTacticsEnv."""
    return GridTacticsEnv(library=library, deck_p1=deck, deck_p2=deck, seed=42)


@pytest.fixture
def self_play_env(base_env):
    """SelfPlayEnv with random opponent."""
    return SelfPlayEnv(base_env, opponent_policy=None, use_shaped_reward=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSelfPlayEnv:
    """Tests for the SelfPlayEnv wrapper."""

    def test_action_masks_delegated(self, self_play_env):
        """SelfPlayEnv.action_masks() returns same as underlying env."""
        self_play_env.reset(seed=42)
        self_play_mask = self_play_env.action_masks()
        underlying_mask = self_play_env.env.action_masks()
        np.testing.assert_array_equal(self_play_mask, underlying_mask)

    def test_random_opponent_plays_legal(self, self_play_env):
        """Run 10 episodes with random opponent -- no crashes."""
        for episode in range(10):
            obs, info = self_play_env.reset(seed=episode)
            done = False
            steps = 0
            while not done and steps < 500:
                mask = self_play_env.action_masks()
                legal = np.where(mask)[0]
                action = int(np.random.choice(legal))
                obs, reward, terminated, truncated, info = self_play_env.step(action)
                done = terminated or truncated
                steps += 1

    def test_reset_returns_obs_for_training_agent(self, self_play_env):
        """reset() returns obs with correct shape."""
        obs, info = self_play_env.reset(seed=42)
        assert obs.shape == (OBSERVATION_SIZE,)
        assert obs.dtype == np.float32

    def test_step_auto_plays_opponent(self, self_play_env):
        """After training agent steps, it should be training agent's turn again."""
        obs, info = self_play_env.reset(seed=42)
        mask = self_play_env.action_masks()
        legal = np.where(mask)[0]
        action = int(legal[0])
        obs, reward, terminated, truncated, info = self_play_env.step(action)
        if not (terminated or truncated):
            # After step, it should be the training agent's turn
            assert self_play_env.env._current_player_idx() == self_play_env.training_player_idx

    def test_set_opponent(self, self_play_env):
        """set_opponent changes the opponent policy."""
        assert self_play_env.opponent_policy is None
        self_play_env.set_opponent("dummy_policy")
        assert self_play_env.opponent_policy == "dummy_policy"

    def test_shaped_reward_integration(self, base_env):
        """SelfPlayEnv with shaped reward returns non-zero reward for non-terminal steps."""
        env = SelfPlayEnv(base_env, opponent_policy=None, use_shaped_reward=True)
        obs, info = env.reset(seed=42)
        mask = env.action_masks()
        legal = np.where(mask)[0]
        action = int(legal[0])
        obs, reward, terminated, truncated, info = env.step(action)
        # Shaped reward can be 0 for some steps, but over many steps
        # it should produce some non-zero values
        rewards = [reward]
        for _ in range(20):
            if terminated or truncated:
                break
            mask = env.action_masks()
            legal = np.where(mask)[0]
            action = int(np.random.choice(legal))
            obs, reward, terminated, truncated, info = env.step(action)
            rewards.append(reward)
        # At least some rewards should be non-zero (shaped reward adds potential difference)
        non_zero = [r for r in rewards if abs(r) > 1e-7]
        assert len(non_zero) > 0, f"All shaped rewards were zero: {rewards}"

    def test_observation_space_preserved(self, self_play_env):
        """SelfPlayEnv preserves observation and action spaces."""
        assert self_play_env.observation_space.shape == (OBSERVATION_SIZE,)
        assert self_play_env.action_space.n == ACTION_SPACE_SIZE
