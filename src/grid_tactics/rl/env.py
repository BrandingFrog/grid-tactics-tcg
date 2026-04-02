"""Gymnasium environment wrapping the Grid Tactics game engine.

Provides GridTacticsEnv, a fully Gymnasium-compatible environment that
integrates observation encoding, action space encoding, action masking,
and reward computation for RL training with MaskablePPO.

Both players act through the same environment interface with alternating
perspectives (following the PettingZoo Connect Four single-agent pattern).
Observation is always from the perspective of whoever acts next.
Reward is from the perspective of the player who just acted.
"""

from __future__ import annotations

from typing import Any

import gymnasium
import numpy as np

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.rl.action_space import (
    ACTION_SPACE_SIZE,
    PASS_IDX,
    ActionEncoder,
    build_action_mask,
)
from grid_tactics.rl.observation import OBSERVATION_SIZE, encode_observation
from grid_tactics.rl.reward import compute_reward
from grid_tactics.types import DEFAULT_TURN_LIMIT


class GridTacticsEnv(gymnasium.Env):
    """Gymnasium environment for Grid Tactics card game.

    Wraps the game engine with Gymnasium-compatible reset()/step()/action_masks()
    interface. Both players are controlled through a single agent alternating
    perspectives -- the observation always encodes the state from the viewpoint
    of the player who must act next.

    Attributes:
        metadata: Gymnasium metadata dict.
        observation_space: Box space of shape (292,) with range [-1, 1].
        action_space: Discrete(1262) covering all action types.
    """

    metadata: dict[str, Any] = {"render_modes": []}

    def __init__(
        self,
        library: CardLibrary,
        deck_p1: tuple[int, ...],
        deck_p2: tuple[int, ...],
        seed: int = 42,
        turn_limit: int = DEFAULT_TURN_LIMIT,
    ) -> None:
        """Initialize the Grid Tactics environment.

        Args:
            library: CardLibrary with all card definitions.
            deck_p1: Player 1's deck as tuple of card numeric IDs.
            deck_p2: Player 2's deck as tuple of card numeric IDs.
            seed: Default RNG seed for game initialization.
            turn_limit: Maximum turns before game is truncated.
        """
        super().__init__()

        self.library = library
        self.deck_p1 = deck_p1
        self.deck_p2 = deck_p2
        self._seed = seed
        self.turn_limit = turn_limit

        # Action encoder for mapping between Action objects and integers
        self.action_encoder = ActionEncoder()

        # Gymnasium spaces
        self.observation_space = gymnasium.spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(OBSERVATION_SIZE,),
            dtype=np.float32,
        )
        self.action_space = gymnasium.spaces.Discrete(ACTION_SPACE_SIZE)

        # Game state (initialized on reset)
        self.state: GameState | None = None
        self.rng = None
        # Terminal state preserved across auto-reset (for logging callbacks)
        self.last_terminal_state: GameState | None = None

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset the environment to a new game.

        Args:
            seed: If provided, use this seed for the new game.
                  Otherwise use the default seed from __init__.
            options: Unused, present for Gymnasium API compatibility.

        Returns:
            Tuple of (observation, info) where info contains "action_mask".
        """
        super().reset(seed=seed)

        game_seed = seed if seed is not None else self._seed
        self.state, self.rng = GameState.new_game(
            game_seed, self.deck_p1, self.deck_p2,
        )

        player_idx = self._current_player_idx()
        obs = encode_observation(self.state, self.library, player_idx)
        mask = build_action_mask(self.state, self.library, self.action_encoder)

        return obs, {"action_mask": mask}

    def step(
        self,
        action_int: int,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Apply an action and advance the game state.

        The action is decoded from the integer action space, applied to the
        game state, and the resulting observation is encoded from the
        perspective of the next player to act.

        Args:
            action_int: Integer in [0, ACTION_SPACE_SIZE) representing the action.

        Returns:
            Tuple of (observation, reward, terminated, truncated, info).
            Reward is from the perspective of the player who just acted.
        """
        assert self.state is not None, "Must call reset() before step()"

        # Determine who is acting before the action resolves
        acting_player_idx = self._current_player_idx()

        # Decode and apply action.
        # If the action is illegal (e.g., check_env samples from unmasked space),
        # gracefully fall back to PASS to maintain Gymnasium API compatibility.
        try:
            action = self.action_encoder.decode(action_int, self.state, self.library)
            self.state = resolve_action(self.state, action, self.library)
        except (ValueError, KeyError, IndexError):
            # Illegal action: fall back to PASS
            action = pass_action()
            self.state = resolve_action(self.state, action, self.library)

        # Check termination conditions
        terminated = self.state.is_game_over
        truncated = not terminated and self.state.turn_number > self.turn_limit

        # Preserve terminal state for logging (SB3 auto-resets before callbacks run)
        if terminated or truncated:
            self.last_terminal_state = self.state

        # Compute reward for the player who just acted
        reward = compute_reward(self.state, acting_player_idx)

        # If truncated (turn limit exceeded), treat as draw for reward
        if truncated:
            reward = 0.0

        # Build observation and mask
        if terminated or truncated:
            # Terminal state: observation from last acting player's perspective
            obs = encode_observation(
                self.state, self.library, acting_player_idx,
            )
            # Terminal mask: all zeros (no actions available)
            mask = np.zeros(ACTION_SPACE_SIZE, dtype=np.bool_)
        else:
            # Non-terminal: observation from next acting player's perspective
            next_player_idx = self._current_player_idx()
            obs = encode_observation(
                self.state, self.library, next_player_idx,
            )
            mask = build_action_mask(
                self.state, self.library, self.action_encoder,
            )

        return obs, float(reward), terminated, truncated, {"action_mask": mask}

    def action_masks(self) -> np.ndarray:
        """Return the current action mask.

        Returns a boolean array of shape (ACTION_SPACE_SIZE,) where True
        indicates a legal action. This method is used by sb3-contrib's
        MaskablePPO to filter illegal actions during training.

        Returns:
            np.ndarray of shape (ACTION_SPACE_SIZE,) with dtype np.bool_.
        """
        assert self.state is not None, "Must call reset() before action_masks()"
        return build_action_mask(self.state, self.library, self.action_encoder)

    def _current_player_idx(self) -> int:
        """Determine which player should act in the current state.

        Returns:
            0 or 1, the index of the player who must make a decision.
        """
        if self.state.phase == TurnPhase.ACTION:
            return self.state.active_player_idx
        elif self.state.phase == TurnPhase.REACT:
            return self.state.react_player_idx
        else:
            # Fallback: active player
            return self.state.active_player_idx
