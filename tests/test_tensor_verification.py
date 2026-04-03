"""Cross-engine verification: tensor engine vs Python engine.

Runs N random games with identical seeds, stepping both engines with the
same random actions (encoded as integers, decoded back for Python engine),
and asserts state equivalence after every step.

NOTE: Both engines receive actions through the integer encoding/decoding
path, which means some information (like ON_PLAY SINGLE_TARGET for minion
deploys) is lost. This matches actual RL training behavior where the agent
only provides integer actions.
"""

import pytest
import torch
import numpy as np
from pathlib import Path

from grid_tactics.card_library import CardLibrary
from grid_tactics.game_state import GameState
from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import pass_action
from grid_tactics.legal_actions import legal_actions
from grid_tactics.rl.action_space import (
    ActionEncoder,
    build_action_mask,
    ACTION_SPACE_SIZE,
    PASS_IDX,
)
from grid_tactics.rl.observation import encode_observation
from grid_tactics.tensor_engine import TensorGameEngine, CardTable
from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
from grid_tactics.tensor_engine.observation import encode_observations_batch


@pytest.fixture
def setup():
    lib = CardLibrary.from_directory(Path("data/cards"))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    ct = CardTable.from_library(lib, device)
    all_ids = list(range(18))
    deck_tuple = tuple((all_ids * 3)[:40])
    deck_tensor = torch.tensor([(all_ids * 3)[:40]], device=device)
    return lib, ct, deck_tuple, deck_tensor, device


def _compare_state(py_state, tensor_state, game_idx, step_num, lib):
    """Compare Python GameState with tensor engine state for one game."""
    prefix = f"Step {step_num}, game {game_idx}"

    # Player HP
    for p in range(2):
        py_hp = py_state.players[p].hp
        t_hp = tensor_state.player_hp[game_idx, p].item()
        assert py_hp == t_hp, f"{prefix}: P{p} HP mismatch: py={py_hp}, tensor={t_hp}"

    # Player mana
    for p in range(2):
        py_mana = py_state.players[p].current_mana
        t_mana = tensor_state.player_mana[game_idx, p].item()
        assert py_mana == t_mana, f"{prefix}: P{p} mana mismatch: py={py_mana}, tensor={t_mana}"

    # Active player and phase
    assert py_state.active_player_idx == tensor_state.active_player[game_idx].item(), \
        f"{prefix}: active_player mismatch"
    assert py_state.phase.value == tensor_state.phase[game_idx].item(), \
        f"{prefix}: phase mismatch"

    # Turn number
    assert py_state.turn_number == tensor_state.turn_number[game_idx].item(), \
        f"{prefix}: turn_number mismatch"

    # Game over state
    assert py_state.is_game_over == tensor_state.is_game_over[game_idx].item(), \
        f"{prefix}: is_game_over mismatch"

    # Hand sizes
    for p in range(2):
        py_hand_size = len(py_state.players[p].hand)
        t_hand_size = tensor_state.hand_sizes[game_idx, p].item()
        assert py_hand_size == t_hand_size, \
            f"{prefix}: P{p} hand_size mismatch: py={py_hand_size}, tensor={t_hand_size}"

    # Minion count
    py_minion_count = len(py_state.minions)
    t_minion_count = tensor_state.minion_alive[game_idx].sum().item()
    assert py_minion_count == t_minion_count, \
        f"{prefix}: minion count mismatch: py={py_minion_count}, tensor={t_minion_count}"

    # Board occupancy
    for row in range(5):
        for col in range(5):
            py_cell = py_state.board.get(row, col)
            t_cell = tensor_state.board[game_idx, row, col].item()
            py_occupied = py_cell is not None
            t_occupied = t_cell >= 0
            assert py_occupied == t_occupied, \
                f"{prefix}: board ({row},{col}) occupancy mismatch: py={py_occupied}, tensor={t_occupied}"


class TestCrossEngineVerification:
    """Run identical games on both engines and compare state."""

    def test_random_games_match(self, setup):
        """Run 8 random games for 50 steps each, comparing state at every step.

        Both engines receive actions through the integer encoding/decoding
        path for consistency with actual RL training.
        """
        lib, ct, deck_tuple, deck_tensor, device = setup
        N = 8
        MAX_STEPS = 50
        encoder = ActionEncoder()

        seed_base = 42

        # Python engine: N separate games
        py_states = []
        for i in range(N):
            state, rng = GameState.new_game(seed_base + i, deck_tuple, deck_tuple)
            py_states.append(state)

        # Tensor engine: one batched engine
        engine = TensorGameEngine(
            N, ct, deck_tensor.expand(N, -1), deck_tensor.expand(N, -1), device,
            seeds=torch.arange(seed_base, seed_base + N, device=device),
        )
        engine.reset_batch()

        # Compare initial state
        for i in range(N):
            _compare_state(py_states[i], engine.state, i, 0, lib)

        rng = np.random.RandomState(12345)

        for step in range(MAX_STEPS):
            # For each game, pick a random legal action
            action_ints = []

            for i in range(N):
                if py_states[i].is_game_over:
                    action_ints.append(PASS_IDX)
                    continue

                py_legal = legal_actions(py_states[i], lib)
                if not py_legal:
                    action_ints.append(PASS_IDX)
                    continue

                chosen = py_legal[rng.randint(len(py_legal))]
                action_int = encoder.encode(chosen, py_states[i])
                action_ints.append(action_int)

            # Step Python engine using DECODED actions (same info as tensor engine)
            for i in range(N):
                if py_states[i].is_game_over:
                    continue
                try:
                    decoded = encoder.decode(action_ints[i], py_states[i], lib)
                    py_states[i] = resolve_action(py_states[i], decoded, lib)
                except (ValueError, KeyError, IndexError):
                    py_states[i] = resolve_action(py_states[i], pass_action(), lib)

            # Step tensor engine
            action_tensor = torch.tensor(action_ints, device=device, dtype=torch.int64)
            engine.step_batch(action_tensor)

            # Compare states
            for i in range(N):
                if not py_states[i].is_game_over:
                    _compare_state(py_states[i], engine.state, i, step + 1, lib)

    def test_legal_mask_match(self, setup):
        """Verify legal action masks match between Python and tensor engine."""
        lib, ct, deck_tuple, deck_tensor, device = setup
        N = 4
        encoder = ActionEncoder()
        seed = 99

        py_states = []
        for i in range(N):
            state, _ = GameState.new_game(seed + i, deck_tuple, deck_tuple)
            py_states.append(state)

        engine = TensorGameEngine(
            N, ct, deck_tensor.expand(N, -1), deck_tensor.expand(N, -1), device,
            seeds=torch.arange(seed, seed + N, device=device),
        )
        engine.reset_batch()

        # Compare masks at initial state
        tensor_masks = compute_legal_mask_batch(engine.state, ct)

        for i in range(N):
            py_mask = build_action_mask(py_states[i], lib, encoder)
            t_mask = tensor_masks[i].cpu().numpy()

            py_legal_indices = set(np.where(py_mask)[0])
            t_legal_indices = set(np.where(t_mask)[0])

            missing = py_legal_indices - t_legal_indices
            extra = t_legal_indices - py_legal_indices

            assert not missing, f"Game {i}: tensor engine missing legal actions: {missing}"
            assert not extra, f"Game {i}: tensor engine has extra legal actions: {extra}"


class TestVecEnvIntegration:
    def test_vecenv_smoke(self, setup):
        """Smoke test: TensorVecEnv works with random actions for 20 steps."""
        lib, ct, deck_tuple, deck_tensor, device = setup
        from grid_tactics.tensor_engine.vec_env import TensorVecEnv

        vec_env = TensorVecEnv(
            n_envs=4,
            card_table=ct,
            deck_p1=deck_tensor.expand(4, -1),
            deck_p2=deck_tensor.expand(4, -1),
            device=device,
        )
        obs = vec_env.reset()
        assert obs.shape == (4, 292)

        for _ in range(20):
            masks = vec_env._get_action_masks()
            actions = []
            for m in masks:
                legal = np.where(m)[0]
                actions.append(np.random.choice(legal) if len(legal) > 0 else 1001)
            obs, rewards, dones, infos = vec_env.step(np.array(actions))
            assert obs.shape == (4, 292)
            assert rewards.shape == (4,)
            assert dones.shape == (4,)

        vec_env.close()

    def test_vecenv_observation_shape(self, setup):
        """Verify VecEnv observations have correct shape and dtype."""
        _, ct, _, deck_tensor, device = setup
        from grid_tactics.tensor_engine.vec_env import TensorVecEnv

        vec_env = TensorVecEnv(
            n_envs=2,
            card_table=ct,
            deck_p1=deck_tensor.expand(2, -1),
            deck_p2=deck_tensor.expand(2, -1),
            device=device,
        )
        obs = vec_env.reset()
        assert obs.shape == (2, 292)
        assert obs.dtype == np.float32
        vec_env.close()
