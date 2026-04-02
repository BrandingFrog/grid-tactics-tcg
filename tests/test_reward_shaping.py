"""Tests for potential-based reward shaping.

Verifies:
- potential() returns values in [-1.0, 1.0]
- potential() is zero-sum for symmetric states
- potential() is higher when player has more HP, minions, mana, advancement
- compute_shaped_reward() implements F(s,s') = gamma*Phi(s') - Phi(s)
- Terminal shaped reward is dominated by +1/-1
- Existing compute_reward() behavior unchanged (regression)
"""

from __future__ import annotations

import pytest

from grid_tactics.enums import PlayerSide, TurnPhase
from grid_tactics.rl.reward import compute_reward, compute_shaped_reward, potential
from grid_tactics.types import STARTING_HP, STARTING_MANA


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def symmetric_state(make_game_state_with_minions, make_player, make_minion):
    """A state that is symmetric: both players have same HP, mana, no minions."""
    p1 = make_player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
    )
    p2 = make_player(
        side=PlayerSide.PLAYER_2,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
    )
    return make_game_state_with_minions(minions=(), players=(p1, p2))


@pytest.fixture
def asymmetric_state(make_game_state_with_minions, make_player, make_minion):
    """P1 has more HP and a minion advanced to row 3, P2 has nothing."""
    p1 = make_player(
        side=PlayerSide.PLAYER_1,
        hp=STARTING_HP,
        current_mana=5,
        max_mana=5,
    )
    p2 = make_player(
        side=PlayerSide.PLAYER_2,
        hp=10,
        current_mana=2,
        max_mana=5,
    )
    m1 = make_minion(
        instance_id=0,
        card_numeric_id=0,
        owner=PlayerSide.PLAYER_1,
        position=(3, 2),
        current_health=3,
    )
    return make_game_state_with_minions(minions=(m1,), players=(p1, p2))


@pytest.fixture
def terminal_win_state(make_game_state_with_minions, make_player):
    """Terminal state where player 0 won."""
    p1 = make_player(side=PlayerSide.PLAYER_1, hp=10, current_mana=3, max_mana=5)
    p2 = make_player(side=PlayerSide.PLAYER_2, hp=0, current_mana=0, max_mana=5)
    return make_game_state_with_minions(
        players=(p1, p2),
        is_game_over=True,
        winner=PlayerSide.PLAYER_1,
    )


# ---------------------------------------------------------------------------
# potential() tests
# ---------------------------------------------------------------------------


class TestPotential:
    """Tests for the potential function."""

    def test_potential_range_symmetric(self, symmetric_state):
        """Potential for a symmetric state is in [-1.0, 1.0]."""
        val = potential(symmetric_state, 0)
        assert -1.0 <= val <= 1.0

    def test_potential_range_asymmetric(self, asymmetric_state):
        """Potential for an asymmetric state is in [-1.0, 1.0]."""
        val = potential(asymmetric_state, 0)
        assert -1.0 <= val <= 1.0

    def test_potential_zero_sum_symmetric(self, symmetric_state):
        """Antisymmetric components cancel; mana is absolute so both positive."""
        p0 = potential(symmetric_state, 0)
        p1 = potential(symmetric_state, 1)
        # HP diff and board diff are antisymmetric (cancel to 0).
        # Mana component is absolute (my_mana/10) -- both players have mana=5
        # so both get +0.2 * 0.5 = +0.1 mana contribution.
        # With equal mana, p0 should equal p1 (both get same mana bonus,
        # and the antisymmetric components are 0 for both).
        assert abs(p0 - p1) < 0.01, f"Symmetric state should yield equal potentials: p0={p0}, p1={p1}"

    def test_potential_higher_with_more_hp(
        self, make_game_state_with_minions, make_player,
    ):
        """Player with more HP should have higher potential."""
        p1_high = make_player(side=PlayerSide.PLAYER_1, hp=20, current_mana=1, max_mana=1)
        p2_low = make_player(side=PlayerSide.PLAYER_2, hp=5, current_mana=1, max_mana=1)
        state = make_game_state_with_minions(players=(p1_high, p2_low))
        assert potential(state, 0) > potential(state, 1)

    def test_potential_higher_with_more_minions(
        self, make_game_state_with_minions, make_player, make_minion,
    ):
        """Player with more minions should have higher potential."""
        p1 = make_player(side=PlayerSide.PLAYER_1, hp=20, current_mana=1, max_mana=1)
        p2 = make_player(side=PlayerSide.PLAYER_2, hp=20, current_mana=1, max_mana=1)
        m1 = make_minion(instance_id=0, owner=PlayerSide.PLAYER_1, position=(0, 0))
        m2 = make_minion(instance_id=1, owner=PlayerSide.PLAYER_1, position=(0, 1))
        state = make_game_state_with_minions(minions=(m1, m2), players=(p1, p2))
        assert potential(state, 0) > potential(state, 1)

    def test_potential_higher_with_more_mana(
        self, make_game_state_with_minions, make_player,
    ):
        """Player with more mana should have higher potential."""
        p1 = make_player(side=PlayerSide.PLAYER_1, hp=20, current_mana=8, max_mana=10)
        p2 = make_player(side=PlayerSide.PLAYER_2, hp=20, current_mana=1, max_mana=10)
        state = make_game_state_with_minions(players=(p1, p2))
        assert potential(state, 0) > potential(state, 1)

    def test_potential_higher_with_advancement(
        self, make_game_state_with_minions, make_player, make_minion,
    ):
        """Player with minions further advanced should have higher potential."""
        p1 = make_player(side=PlayerSide.PLAYER_1, hp=20, current_mana=1, max_mana=1)
        p2 = make_player(side=PlayerSide.PLAYER_2, hp=20, current_mana=1, max_mana=1)
        # Player 0 has minion at row 3 (advanced), Player 1 has minion at row 3 (not advanced for them)
        m1 = make_minion(instance_id=0, owner=PlayerSide.PLAYER_1, position=(3, 0))
        m2 = make_minion(instance_id=1, owner=PlayerSide.PLAYER_2, position=(1, 4))
        state = make_game_state_with_minions(minions=(m1, m2), players=(p1, p2))
        # Player 0 minion at row 3 -> advancement = 3/4 = 0.75
        # Player 1 minion at row 1 -> advancement = (4-1)/4 = 0.75
        # Equal advancement; let's use a clearly different one
        m1_far = make_minion(instance_id=0, owner=PlayerSide.PLAYER_1, position=(4, 0))
        m2_near = make_minion(instance_id=1, owner=PlayerSide.PLAYER_2, position=(3, 4))
        state2 = make_game_state_with_minions(minions=(m1_far, m2_near), players=(p1, p2))
        # Player 0: row 4 -> 4/4 = 1.0
        # Player 1: row 3 -> (4-3)/4 = 0.25
        assert potential(state2, 0) > potential(state2, 1)


# ---------------------------------------------------------------------------
# compute_shaped_reward() tests
# ---------------------------------------------------------------------------


class TestShapedReward:
    """Tests for the shaped reward function."""

    def test_shaped_reward_formula(self, symmetric_state, asymmetric_state):
        """compute_shaped_reward matches mathematical definition."""
        gamma = 0.99
        player_idx = 0
        result = compute_shaped_reward(symmetric_state, asymmetric_state, player_idx, gamma)
        expected = (
            compute_reward(asymmetric_state, player_idx)
            + gamma * potential(asymmetric_state, player_idx)
            - potential(symmetric_state, player_idx)
        )
        assert abs(result - expected) < 1e-7, f"result={result}, expected={expected}"

    def test_shaped_reward_small_per_step(self, symmetric_state, asymmetric_state):
        """Non-terminal shaped reward should be small relative to +1/-1."""
        result = compute_shaped_reward(symmetric_state, asymmetric_state, 0)
        # Non-terminal base reward is 0, so shaped = potential difference only
        assert -0.5 < result < 0.5, f"Shaped reward too large: {result}"

    def test_terminal_shaping_dominated_by_terminal(
        self, symmetric_state, terminal_win_state,
    ):
        """Terminal shaped reward is dominated by +1.0 win signal."""
        result = compute_shaped_reward(symmetric_state, terminal_win_state, 0)
        # Base reward = +1.0, shaping adds a small potential difference
        assert result > 0.5, f"Terminal shaped reward should be > 0.5, got {result}"

    def test_terminal_shaping_loss(self, symmetric_state, terminal_win_state):
        """Losing player gets negative terminal shaped reward."""
        result = compute_shaped_reward(symmetric_state, terminal_win_state, 1)
        # Base reward = -1.0, shaping adds a small potential difference
        assert result < -0.5, f"Terminal shaped loss should be < -0.5, got {result}"

    def test_shaped_reward_default_gamma(self, symmetric_state, asymmetric_state):
        """Default gamma is 0.99."""
        result_default = compute_shaped_reward(symmetric_state, asymmetric_state, 0)
        result_explicit = compute_shaped_reward(symmetric_state, asymmetric_state, 0, gamma=0.99)
        assert abs(result_default - result_explicit) < 1e-7


# ---------------------------------------------------------------------------
# compute_reward() regression tests
# ---------------------------------------------------------------------------


class TestComputeRewardRegression:
    """Verify existing compute_reward is unchanged."""

    def test_compute_reward_in_progress(self, symmetric_state):
        """Non-terminal state returns 0.0."""
        assert compute_reward(symmetric_state, 0) == 0.0
        assert compute_reward(symmetric_state, 1) == 0.0

    def test_compute_reward_win(self, terminal_win_state):
        """Winner gets +1.0."""
        assert compute_reward(terminal_win_state, 0) == 1.0

    def test_compute_reward_loss(self, terminal_win_state):
        """Loser gets -1.0."""
        assert compute_reward(terminal_win_state, 1) == -1.0

    def test_compute_reward_draw(self, make_game_state_with_minions, make_player):
        """Draw returns 0.0."""
        p1 = make_player(side=PlayerSide.PLAYER_1, hp=0)
        p2 = make_player(side=PlayerSide.PLAYER_2, hp=0)
        state = make_game_state_with_minions(
            players=(p1, p2),
            is_game_over=True,
            winner=None,
        )
        assert compute_reward(state, 0) == 0.0
        assert compute_reward(state, 1) == 0.0
