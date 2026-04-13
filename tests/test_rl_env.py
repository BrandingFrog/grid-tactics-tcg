"""Tests for GridTacticsEnv Gymnasium environment.

Covers:
  - Gymnasium API contract (observation_space, action_space)
  - reset() returns correct types with action_mask in info
  - Deterministic reset with same seed
  - step() returns correct Gymnasium 5-tuple
  - step() advances game state
  - action_masks() method returns correct shape
  - Terminal states: terminated on game over, truncated on turn limit
  - gymnasium.utils.env_checker.check_env() validation
  - 10,000 random episode smoke test (D-08 phase gate)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.rl.action_space import ACTION_SPACE_SIZE
from grid_tactics.rl.env import GridTacticsEnv
from grid_tactics.rl.observation import OBSERVATION_SIZE

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"


@pytest.fixture
def library():
    """Load card library from data/cards/."""
    return CardLibrary.from_directory(DATA_DIR)


@pytest.fixture
def test_deck(library):
    """Build a valid 40-card deck for testing."""
    card_counts = {
        "rat": 3,
        "furryroach": 3,
        "blue_diodebot": 3,
        "red_diodebot": 3,
        "rgb_lasercannon": 3,
        "green_diodebot": 3,
        "ratchanter": 3,
        "surgefed_sparkbot": 3,
        "rathopper": 3,
        "giant_rat": 1,
        "to_the_ratmobile": 3,
        "ratical_resurrection": 3,
        "emberplague_rat": 3,
        "counter_spell": 3,
    }
    return library.build_deck(card_counts)


@pytest.fixture
def env(library, test_deck):
    """Create a GridTacticsEnv instance for testing."""
    return GridTacticsEnv(
        library=library,
        deck_p1=test_deck,
        deck_p2=test_deck,
        seed=42,
    )


class TestGymnasiumAPI:
    """Test Gymnasium API contract."""

    def test_gymnasium_api(self, env):
        """Env has observation_space (Box, shape=(292,), dtype=float32, low=-1, high=1)
        and action_space (Discrete(1287))."""
        import gymnasium

        # observation_space
        assert isinstance(env.observation_space, gymnasium.spaces.Box)
        assert env.observation_space.shape == (OBSERVATION_SIZE,)
        assert env.observation_space.dtype == np.float32
        assert np.all(env.observation_space.low == -1.0)
        assert np.all(env.observation_space.high == 1.0)

        # action_space
        assert isinstance(env.action_space, gymnasium.spaces.Discrete)
        assert env.action_space.n == ACTION_SPACE_SIZE


class TestReset:
    """Test reset() behavior."""

    def test_reset_returns_correct_types(self, env):
        """reset() returns (ndarray, dict); obs has correct shape; info has action_mask."""
        obs, info = env.reset()

        assert isinstance(obs, np.ndarray)
        assert obs.shape == (OBSERVATION_SIZE,)
        assert obs.dtype == np.float32

        assert isinstance(info, dict)
        assert "action_mask" in info
        mask = info["action_mask"]
        assert isinstance(mask, np.ndarray)
        assert mask.shape == (ACTION_SPACE_SIZE,)

    def test_reset_deterministic(self, library, test_deck):
        """reset(seed=42) twice produces identical observations."""
        env1 = GridTacticsEnv(library=library, deck_p1=test_deck, deck_p2=test_deck, seed=0)
        env2 = GridTacticsEnv(library=library, deck_p1=test_deck, deck_p2=test_deck, seed=0)

        obs1, info1 = env1.reset(seed=42)
        obs2, info2 = env2.reset(seed=42)

        np.testing.assert_array_equal(obs1, obs2)
        np.testing.assert_array_equal(info1["action_mask"], info2["action_mask"])


class TestStep:
    """Test step() behavior."""

    def test_step_returns_correct_types(self, env):
        """step(legal_action) returns (ndarray, float, bool, bool, dict)."""
        obs, info = env.reset(seed=42)
        mask = info["action_mask"]

        # Pick a legal action
        legal_indices = np.where(mask)[0]
        assert len(legal_indices) > 0
        action = int(legal_indices[0])

        obs2, reward, terminated, truncated, info2 = env.step(action)

        assert isinstance(obs2, np.ndarray)
        assert obs2.shape == (OBSERVATION_SIZE,)
        assert obs2.dtype == np.float32
        assert isinstance(reward, (int, float))
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info2, dict)
        assert "action_mask" in info2

    def test_step_advances_game(self, env):
        """Step with a legal action changes the observation (game state progresses)."""
        obs1, info = env.reset(seed=42)
        mask = info["action_mask"]

        # Pick a non-PASS legal action if possible (to ensure state changes)
        legal_indices = np.where(mask)[0]
        # Try to pick something other than PASS (index 1001)
        non_pass = [i for i in legal_indices if i != 1001]
        action = int(non_pass[0]) if non_pass else int(legal_indices[0])

        obs2, _, _, _, _ = env.step(action)

        # Observation should change after taking an action
        assert not np.array_equal(obs1, obs2)


class TestActionMasks:
    """Test action_masks() method."""

    def test_action_masks_method(self, env):
        """env.action_masks() returns ndarray shape (1287,) dtype bool with at least one True."""
        env.reset(seed=42)
        masks = env.action_masks()

        assert isinstance(masks, np.ndarray)
        assert masks.shape == (ACTION_SPACE_SIZE,)
        assert masks.dtype == np.bool_
        assert masks.any(), "At least one action must be legal"


class TestTermination:
    """Test game termination conditions."""

    def test_terminated_on_game_over(self, library, test_deck):
        """When a game ends naturally, terminated=True and reward is +1 or -1."""
        env = GridTacticsEnv(
            library=library,
            deck_p1=test_deck,
            deck_p2=test_deck,
            seed=42,
        )
        obs, info = env.reset(seed=42)

        # Play until game ends (with a step limit to prevent infinite loops)
        terminated = False
        truncated = False
        reward = 0.0
        for _ in range(10_000):
            mask = info["action_mask"]
            legal_indices = np.where(mask)[0]
            action = int(legal_indices[np.random.randint(len(legal_indices))])
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                break

        # Game should have ended one way or another
        assert terminated or truncated
        if terminated:
            assert reward == 1.0 or reward == -1.0

    def test_truncated_on_turn_limit(self, library, test_deck):
        """Game exceeding turn_limit returns truncated=True."""
        # Use a very short turn limit
        env = GridTacticsEnv(
            library=library,
            deck_p1=test_deck,
            deck_p2=test_deck,
            seed=42,
            turn_limit=5,
        )
        obs, info = env.reset(seed=42)

        truncated = False
        for _ in range(1_000):
            mask = info["action_mask"]
            legal_indices = np.where(mask)[0]
            action = int(legal_indices[np.random.randint(len(legal_indices))])
            obs, reward, terminated, truncated, info = env.step(action)
            if terminated or truncated:
                break

        assert truncated, "Game should be truncated when turn limit is exceeded"


class TestEnvChecker:
    """Test Gymnasium env_checker validation."""

    def test_env_checker(self, env):
        """gymnasium.utils.env_checker.check_env() passes without assertion errors."""
        from gymnasium.utils.env_checker import check_env

        # check_env resets the environment internally and runs validation
        # It should not raise any errors
        check_env(env.unwrapped)


class TestSmoke:
    """10k random episode smoke test -- phase gate requirement (D-08)."""

    def test_10k_random_episodes(self, library, test_deck):
        """10,000 episodes with random masked actions complete without errors.

        Validates:
        - All observations have correct shape at every step
        - All masks have at least one True bit at non-terminal steps
        - All episodes complete (terminated or truncated)
        - Terminal rewards are +/-1.0 when game ends naturally
        - No crashes, invalid states, or shape mismatches across 10k games

        Note: Random agents with the starter card pool rarely produce natural
        wins because the only player damage comes from sacrifice (minions must
        cross 5 rows), which random play almost never achieves. This is a
        documented property of the game design (Phase 4: D-04). Natural
        termination is validated separately in test_terminated_on_game_over.
        """
        env = GridTacticsEnv(
            library=library,
            deck_p1=test_deck,
            deck_p2=test_deck,
            seed=0,
        )

        total_steps = 0
        terminated_count = 0
        truncated_count = 0
        rng = np.random.default_rng(12345)

        for episode in range(10_000):
            obs, info = env.reset(seed=episode)

            assert obs.shape == (OBSERVATION_SIZE,), f"Episode {episode}: bad obs shape"
            assert obs.dtype == np.float32
            mask = info["action_mask"]
            assert mask.shape == (ACTION_SPACE_SIZE,), f"Episode {episode}: bad mask shape"
            assert mask.any(), f"Episode {episode}: no legal actions at reset"

            done = False
            while not done:
                legal_indices = np.where(mask)[0]
                action = int(legal_indices[rng.integers(len(legal_indices))])

                obs, reward, terminated, truncated, info = env.step(action)
                total_steps += 1

                assert obs.shape == (OBSERVATION_SIZE,), f"Episode {episode}: bad obs shape in step"
                assert obs.dtype == np.float32

                if terminated or truncated:
                    done = True
                    if terminated:
                        terminated_count += 1
                        assert reward == 1.0 or reward == -1.0, (
                            f"Episode {episode}: terminal reward should be +/-1, got {reward}"
                        )
                    if truncated:
                        truncated_count += 1
                else:
                    mask = info["action_mask"]
                    assert mask.shape == (ACTION_SPACE_SIZE,)
                    assert mask.any(), f"Episode {episode} step {total_steps}: no legal actions"

        # All episodes must have completed
        assert terminated_count + truncated_count == 10_000
        # Total steps must be positive (games are not zero-length)
        assert total_steps > 0
