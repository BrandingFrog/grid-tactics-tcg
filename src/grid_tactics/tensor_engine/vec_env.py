"""TensorVecEnv -- SB3-compatible VecEnv backed by GPU tensor game engine.

All N environments step simultaneously. Observations and action masks
are returned as numpy arrays (SB3 expects numpy).
Handles self-play internally: training player is always player 0.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import gymnasium
import numpy as np
import torch

from stable_baselines3.common.vec_env import VecEnv
from stable_baselines3.common.vec_env.base_vec_env import VecEnvStepReturn

from grid_tactics.tensor_engine.card_table import CardTable
from grid_tactics.tensor_engine.constants import (
    ACTION_SPACE_SIZE,
    PASS_IDX,
)
from grid_tactics.tensor_engine.engine import TensorGameEngine
from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
from grid_tactics.tensor_engine.observation import (
    OBSERVATION_SIZE,
    encode_observations_batch,
)
from grid_tactics.tensor_engine.reward import compute_rewards_batch


class TensorVecEnv(VecEnv):
    """SB3-compatible VecEnv backed by GPU tensor game engine.

    Training player is always player 0. Opponent turns are auto-stepped
    using opponent_policy (if provided) or random legal actions.

    Args:
        n_envs: Number of parallel environments.
        card_table: GPU-resident card lookup table.
        deck_p1: [N, DECK_SIZE] tensor for player 1 decks.
        deck_p2: [N, DECK_SIZE] tensor for player 2 decks.
        device: torch device (cuda or cpu).
        opponent_policy: Optional SB3 model for opponent actions.
    """

    def __init__(
        self,
        n_envs: int,
        card_table: CardTable,
        deck_p1: torch.Tensor,
        deck_p2: torch.Tensor,
        device: str | torch.device = 'cuda',
        opponent_policy=None,
    ):
        self.device = torch.device(device) if isinstance(device, str) else device
        self.card_table = card_table
        self.opponent_policy = opponent_policy
        self._pending_actions: Optional[np.ndarray] = None

        self.engine = TensorGameEngine(
            n_envs=n_envs,
            card_table=card_table,
            deck_p1=deck_p1,
            deck_p2=deck_p2,
            device=self.device,
        )

        observation_space = gymnasium.spaces.Box(
            low=-1.0, high=1.5,
            shape=(OBSERVATION_SIZE,),
            dtype=np.float32,
        )
        action_space = gymnasium.spaces.Discrete(ACTION_SPACE_SIZE)

        super().__init__(n_envs, observation_space, action_space)

    def reset(self) -> np.ndarray:
        """Reset all environments, return observations."""
        self.engine.reset_batch()
        self._auto_step_opponents()
        return self._get_obs()

    def step_async(self, actions: np.ndarray) -> None:
        """Store actions for step_wait."""
        self._pending_actions = actions

    def step_wait(self) -> VecEnvStepReturn:
        """Apply actions and return (obs, rewards, dones, infos)."""
        action_t = torch.tensor(
            self._pending_actions, device=self.device, dtype=torch.int64,
        )

        # Step the engine
        self.engine.step_batch(action_t)

        # Auto-step opponent turns
        self._auto_step_opponents()

        # Compute rewards for training player (player 0)
        rewards = compute_rewards_batch(
            self.engine.state,
            torch.zeros(self.num_envs, device=self.device, dtype=torch.int32),
        )

        # Detect done games
        dones = self.engine.state.is_game_over.cpu().numpy()

        # Auto-reset finished games
        done_mask = self.engine.state.is_game_over
        if done_mask.any():
            self.engine.reset_batch(mask=done_mask)
            self._auto_step_opponents()

        # Get observations
        obs = self._get_obs()

        # Build infos with action_masks
        masks_np = self._get_action_masks()
        infos = []
        for i in range(self.num_envs):
            info: dict[str, Any] = {"action_mask": masks_np[i]}
            infos.append(info)

        return obs, rewards.cpu().numpy(), dones, infos

    def _auto_step_opponents(self):
        """Step opponent turns until it's training player's turn or game over."""
        for _ in range(200):  # Safety limit
            s = self.engine.state
            # Determine which games have opponent's turn
            is_action_opp = (s.phase == 0) & (s.active_player != 0) & ~s.is_game_over
            is_react_opp = (s.phase == 1) & (s.react_player != 0) & ~s.is_game_over
            is_opp_turn = is_action_opp | is_react_opp

            if not is_opp_turn.any():
                break

            # Get opponent actions
            opp_actions = self._get_opponent_actions(is_opp_turn)
            self.engine.step_batch(opp_actions)

    def _get_opponent_actions(self, opp_mask: torch.Tensor) -> torch.Tensor:
        """Get actions for opponent turns."""
        masks = compute_legal_mask_batch(self.engine.state, self.card_table)

        if self.opponent_policy is None:
            # Random: sample from legal actions
            actions = torch.full(
                (self.num_envs,), PASS_IDX,
                device=self.device, dtype=torch.int64,
            )
            for i in range(self.num_envs):
                if opp_mask[i]:
                    legal = masks[i].nonzero(as_tuple=True)[0]
                    if len(legal) > 0:
                        idx = torch.randint(len(legal), (1,), device=self.device)
                        actions[i] = legal[idx]
            return actions
        else:
            # Use opponent model
            s = self.engine.state
            # Determine observer for observation encoding
            observer = torch.where(
                s.phase == 0,
                s.active_player,
                s.react_player,
            )
            obs = encode_observations_batch(s, self.card_table, observer)
            obs_np = obs.cpu().numpy()
            masks_np = masks.cpu().numpy()
            model_actions, _ = self.opponent_policy.predict(
                obs_np, action_masks=masks_np, deterministic=False,
            )
            actions = torch.tensor(
                model_actions, device=self.device, dtype=torch.int64,
            )
            actions[~opp_mask] = PASS_IDX
            return actions

    def _get_obs(self) -> np.ndarray:
        """Get observations for training player (player 0)."""
        observer = torch.zeros(
            self.num_envs, device=self.device, dtype=torch.int32,
        )
        obs = encode_observations_batch(
            self.engine.state, self.card_table, observer,
        )
        return obs.cpu().numpy()

    def _get_action_masks(self) -> np.ndarray:
        """Get action masks as numpy array [N, 1262]."""
        masks = compute_legal_mask_batch(self.engine.state, self.card_table)
        return masks.cpu().numpy()

    def env_method(
        self,
        method_name: str,
        *method_args,
        indices: Optional[Sequence[int]] = None,
        **method_kwargs,
    ):
        if method_name == 'action_masks':
            masks = self._get_action_masks()
            idx_list = indices if indices is not None else list(range(self.num_envs))
            return [masks[i] for i in idx_list]
        return [None] * (len(indices) if indices else self.num_envs)

    def get_attr(self, attr_name: str, indices=None):
        if attr_name == 'action_masks':
            return self.env_method('action_masks', indices=indices)
        return [None] * (len(indices) if indices else self.num_envs)

    def set_attr(self, attr_name: str, value, indices=None):
        pass

    def set_opponent(self, policy):
        """Set the opponent policy for self-play."""
        self.opponent_policy = policy

    def close(self):
        pass

    def seed(self, seed=None):
        pass

    def env_is_wrapped(self, wrapper_class, indices=None):
        return [False] * self.num_envs
