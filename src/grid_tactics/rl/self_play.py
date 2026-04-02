"""Self-play environment wrapper for RL training.

SelfPlayEnv wraps GridTacticsEnv so that the training agent only sees
its own turns. The opponent's turns are auto-played using either a
frozen policy from the checkpoint pool or random legal actions.

Key design decisions:
- action_masks() delegates to underlying env (Pitfall 1 mitigation)
- Supports shaped reward via compute_shaped_reward when enabled
- Training agent is always player 0
- Opponent can be swapped mid-training via set_opponent()
"""

from __future__ import annotations

from typing import Any

import gymnasium
import numpy as np

from grid_tactics.rl.env import GridTacticsEnv
from grid_tactics.rl.observation import encode_observation
from grid_tactics.rl.reward import compute_reward, compute_shaped_reward


class SelfPlayEnv(gymnasium.Wrapper):
    """Gymnasium wrapper for single-agent self-play training.

    Wraps GridTacticsEnv so the training agent (player 0) only takes
    actions on its own turns. Opponent turns are auto-stepped using
    the configured opponent policy.

    Attributes:
        training_player_idx: Always 0 -- training agent is player 0.
        opponent_policy: MaskablePPO instance or None for random opponent.
        use_shaped_reward: Whether to use potential-based reward shaping.
        gamma: Discount factor for shaped reward computation.
    """

    def __init__(
        self,
        env: GridTacticsEnv,
        opponent_policy: object | None = None,
        use_shaped_reward: bool = False,
        gamma: float = 0.99,
    ) -> None:
        """Initialize the self-play wrapper.

        Args:
            env: GridTacticsEnv to wrap.
            opponent_policy: MaskablePPO model for opponent, or None for random.
            use_shaped_reward: If True, use compute_shaped_reward instead of compute_reward.
            gamma: Discount factor for potential-based reward shaping.
        """
        super().__init__(env)
        self.training_player_idx: int = 0
        self.opponent_policy = opponent_policy
        self.use_shaped_reward = use_shaped_reward
        self.gamma = gamma
        self._prev_state = None

    def action_masks(self) -> np.ndarray:
        """Return the current action mask.

        Delegates directly to the underlying env's action_masks() method.
        This ensures MaskablePPO sees the correct legal actions (Pitfall 1).

        Returns:
            Boolean array of shape (ACTION_SPACE_SIZE,).
        """
        return self.env.action_masks()

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset the environment and auto-step opponent if needed.

        Args:
            seed: RNG seed for the new game.
            options: Unused, present for Gymnasium API compatibility.

        Returns:
            (observation, info) from the training agent's perspective.
        """
        obs, info = self.env.reset(seed=seed, options=options)
        self._prev_state = self.env.state

        # If opponent moves first, auto-step until it's training agent's turn
        if self._is_opponent_turn():
            obs, info = self._auto_step_opponent()

        return obs, info

    def step(
        self,
        action: int,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Apply training agent's action and auto-step opponent.

        1. Store prev_state for potential-based shaping
        2. Step training agent's action in the underlying env
        3. If shaped reward enabled and not terminal, compute shaped reward
        4. Auto-step opponent turns until training agent's turn or game ends
        5. If game ended during opponent's turn, compute final reward

        Args:
            action: Integer action from the training agent.

        Returns:
            (obs, reward, terminated, truncated, info) from training agent's perspective.
        """
        prev_state = self.env.state

        # Step the training agent's action
        obs, reward, terminated, truncated, info = self.env.step(action)

        # Compute reward for the training agent
        if terminated or truncated:
            reward = compute_reward(self.env.state, self.training_player_idx)
            if truncated:
                reward = 0.0
        elif self.use_shaped_reward:
            reward = compute_shaped_reward(
                prev_state, self.env.state, self.training_player_idx, self.gamma,
            )
        else:
            reward = compute_reward(self.env.state, self.training_player_idx)

        # Auto-play opponent turns
        if not (terminated or truncated):
            while self._is_opponent_turn():
                opp_obs, opp_reward, terminated, truncated, info = self._opponent_step()
                if terminated or truncated:
                    # Game ended during opponent's turn
                    reward = compute_reward(self.env.state, self.training_player_idx)
                    if truncated:
                        reward = 0.0
                    break

        # Update prev_state for next call
        self._prev_state = self.env.state

        # Build final observation from training agent's perspective
        if not (terminated or truncated):
            obs = encode_observation(
                self.env.state, self.env.library, self.training_player_idx,
            )
            info["action_mask"] = self.env.action_masks()

        return obs, float(reward), terminated, truncated, info

    def set_opponent(self, policy: object) -> None:
        """Swap the opponent policy mid-training.

        Args:
            policy: New MaskablePPO model for the opponent, or None for random.
        """
        self.opponent_policy = policy

    def _is_opponent_turn(self) -> bool:
        """Check if it's the opponent's turn.

        Returns:
            True if the current player is not the training agent.
        """
        if self.env.state is None or self.env.state.is_game_over:
            return False
        return self.env._current_player_idx() != self.training_player_idx

    def _opponent_act(self) -> int:
        """Select an action for the opponent.

        If opponent_policy is None, samples uniformly from legal actions.
        Otherwise, uses the opponent model's predict method.

        Returns:
            Integer action for the opponent.
        """
        mask = self.env.action_masks()

        if self.opponent_policy is None:
            # Random opponent: uniform sample from legal actions
            legal = np.where(mask)[0]
            return int(np.random.choice(legal))
        else:
            # Use opponent model
            obs = encode_observation(
                self.env.state, self.env.library,
                self.env._current_player_idx(),
            )
            action, _ = self.opponent_policy.predict(  # type: ignore[attr-defined]
                obs, action_masks=mask, deterministic=False,
            )
            return int(action)

    def _opponent_step(
        self,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Execute one opponent action.

        Returns:
            (obs, reward, terminated, truncated, info) from the underlying env.
        """
        action = self._opponent_act()
        return self.env.step(action)

    def _auto_step_opponent(
        self,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Auto-step opponent until it's training agent's turn or game ends.

        Used during reset() when the opponent moves first.

        Returns:
            (obs, info) after opponent turns complete.
        """
        obs = None
        info = {}
        while self._is_opponent_turn():
            obs, reward, terminated, truncated, info = self._opponent_step()
            if terminated or truncated:
                break
        if obs is None:
            # Shouldn't happen, but safety fallback
            obs = encode_observation(
                self.env.state, self.env.library, self.training_player_idx,
            )
            info = {"action_mask": self.env.action_masks()}
        return obs, info
