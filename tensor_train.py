"""GPU-native tensor training — bypasses SB3's slow rollout collection.

Collects rollouts entirely on GPU using the tensor engine, then feeds
batches to MaskablePPO for gradient updates. This is 100-1000x faster
than SB3's built-in VecEnv loop.

Usage on RunPod:
    PYTHONPATH=src TRAIN_STEPS=100000000 python tensor_train.py
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.distributions import Categorical

# Training config
TOTAL_STEPS = int(os.environ.get("TRAIN_STEPS", "100_000_000"))
N_ENVS = int(os.environ.get("TRAIN_ENVS", "0"))  # 0 = auto-tune
N_STEPS = int(os.environ.get("N_STEPS", "0"))     # 0 = auto-tune
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "0"))  # 0 = auto-tune
N_EPOCHS = int(os.environ.get("N_EPOCHS", "10"))
LR = float(os.environ.get("LR", "3e-4"))
GAMMA = float(os.environ.get("GAMMA", "0.99"))
GAE_LAMBDA = float(os.environ.get("GAE_LAMBDA", "0.95"))
CLIP_RANGE = float(os.environ.get("CLIP_RANGE", "0.2"))
ENT_COEF = float(os.environ.get("ENT_COEF", "0.01"))
VF_COEF = float(os.environ.get("VF_COEF", "0.5"))
MAX_GRAD_NORM = float(os.environ.get("MAX_GRAD_NORM", "0.5"))
EVAL_FREQ = int(os.environ.get("EVAL_FREQ", "10_000_000"))
SEED = int(os.environ.get("TRAIN_SEED", "42"))

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def auto_tune(card_table, deck_1d):
    """Find optimal N_ENVS to maximize FPS within VRAM budget.

    Leaves 30% VRAM headroom for training buffers and gradient computation.
    Tests powers of 2 from 256 up, stops when VRAM exceeds budget or FPS drops.
    """
    from grid_tactics.tensor_engine.engine import TensorGameEngine
    from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
    from grid_tactics.tensor_engine.observation import encode_observations_batch, OBSERVATION_SIZE
    from grid_tactics.tensor_engine.constants import ACTION_SPACE_SIZE

    total_vram = torch.cuda.get_device_properties(0).total_memory
    vram_budget = int(total_vram * 0.70)  # leave 30% for training

    print("\n--- Auto-tuning ---")
    print(f"  VRAM total: {total_vram / 1e9:.1f} GB, budget: {vram_budget / 1e9:.1f} GB")

    # Small policy for benchmarking
    policy = PolicyNetwork(OBSERVATION_SIZE, ACTION_SPACE_SIZE).to(device)

    best_n = 256
    best_fps = 0
    results = []

    for n in [256, 512, 1024, 2048, 4096, 8192, 16384, 32768]:
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()

        try:
            deck = deck_1d.unsqueeze(0).expand(n, -1).to(device)
            engine = TensorGameEngine(n, card_table, deck, deck, device=device)
            engine.reset_batch()
            actions = torch.zeros(n, dtype=torch.long, device=device)

            # Warmup
            for _ in range(3):
                state = engine.state
                obs = encode_observations_batch(state, card_table, state.active_player)
                mask = compute_legal_mask_batch(state, card_table).bool()
                with torch.no_grad():
                    logits, val = policy(obs, mask)
                    actions = torch.distributions.Categorical(logits=logits).sample()
                engine.step_batch(actions)
            torch.cuda.synchronize()

            # Benchmark
            steps = 0
            start = time.perf_counter()
            for _ in range(20):
                state = engine.state
                obs = encode_observations_batch(state, card_table, state.active_player)
                mask = compute_legal_mask_batch(state, card_table).bool()
                with torch.no_grad():
                    logits, val = policy(obs, mask)
                    actions = torch.distributions.Categorical(logits=logits).sample()
                engine.step_batch(actions)
                game_over = state.is_game_over
                if game_over.any():
                    engine.reset_batch(mask=game_over)
                steps += n
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - start
            fps = steps / elapsed

            peak_vram = torch.cuda.max_memory_allocated()
            # Estimate total with training buffers: rollout_buf ≈ n_steps * n * (obs+mask+5floats)
            n_steps_est = max(64, 1_048_576 // n)  # target ~1M steps per rollout
            buf_est = n_steps_est * n * (OBSERVATION_SIZE * 4 + ACTION_SPACE_SIZE + 5 * 4)
            total_est = peak_vram + buf_est

            fits = total_est < vram_budget
            results.append((n, fps, peak_vram, total_est, fits))
            print(f"  n={n:>6}: {fps:>10,.0f} FPS | engine VRAM: {peak_vram/1e6:.0f}MB | est total: {total_est/1e6:.0f}MB | {'OK' if fits else 'OVER'}")

            if fits and fps > best_fps:
                best_fps = fps
                best_n = n
            elif not fits:
                break  # VRAM exceeded, stop

            del engine, deck, obs, mask, logits, val, actions
        except (torch.cuda.OutOfMemoryError, RuntimeError) as e:
            print(f"  n={n:>6}: OOM ({e})")
            break

    del policy
    torch.cuda.empty_cache()

    # Pick n_steps to target ~1M steps per rollout
    n_steps = max(64, min(512, 1_048_576 // best_n))
    batch_size = min(best_n, 8192)

    print(f"\n  Selected: N_ENVS={best_n}, N_STEPS={n_steps}, BATCH={batch_size}")
    print(f"  Peak FPS: {best_fps:,.0f}")
    print(f"  Rollout size: {best_n * n_steps:,} steps per update")
    print("--- Auto-tune complete ---\n")

    return best_n, n_steps, batch_size


class PolicyNetwork(torch.nn.Module):
    """MLP policy + value network with action masking."""

    def __init__(self, obs_size: int, action_size: int, hidden: list[int] = [512, 512, 256]):
        super().__init__()
        layers = []
        prev = obs_size
        for h in hidden:
            layers.extend([torch.nn.Linear(prev, h), torch.nn.ReLU()])
            prev = h
        self.shared = torch.nn.Sequential(*layers)
        self.policy_head = torch.nn.Linear(prev, action_size)
        self.value_head = torch.nn.Linear(prev, 1)

    def forward(self, obs, action_mask=None):
        features = self.shared(obs)
        logits = self.policy_head(features)
        if action_mask is not None:
            # Mask illegal actions with large negative value
            logits = logits.masked_fill(~action_mask, -1e8)
        values = self.value_head(features).squeeze(-1)
        return logits, values

    def get_action_and_value(self, obs, action_mask=None, action=None):
        logits, values = self(obs, action_mask)
        dist = Categorical(logits=logits)
        if action is None:
            action = dist.sample()
        log_prob = dist.log_prob(action)
        entropy = dist.entropy()
        return action, log_prob, entropy, values


def evaluate_vs_random(policy, engine_cls, card_table, deck, n_games=200):
    """Quick eval: play n_games against random, return win rate."""
    from grid_tactics.tensor_engine.engine import TensorGameEngine
    from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
    from grid_tactics.tensor_engine.observation import encode_observations_batch, OBSERVATION_SIZE
    from grid_tactics.tensor_engine.constants import PASS_IDX

    engine = TensorGameEngine(n_games, card_table, deck[:n_games], deck[:n_games], device=device)
    engine.reset_batch()

    done = torch.zeros(n_games, dtype=torch.bool, device=device)
    wins = torch.zeros(n_games, dtype=torch.float32, device=device)

    for _ in range(400):  # max turns
        if done.all():
            break

        state = engine.state
        active = state.active_player
        legal = compute_legal_mask_batch(state, card_table)

        # Player 0 uses policy, player 1 uses random
        is_p0 = (active == 0) & ~done
        is_p1 = (active == 1) & ~done

        actions = torch.zeros(n_games, dtype=torch.long, device=device)

        if is_p0.any():
            obs = encode_observations_batch(state, card_table, state.active_player)
            obs_p0 = obs[is_p0]
            mask_p0 = legal[is_p0]
            with torch.no_grad():
                logits, _ = policy(obs_p0, mask_p0.bool())
                dist = Categorical(logits=logits)
                actions[is_p0] = dist.sample()

        if is_p1.any():
            mask_p1 = legal[is_p1].float()
            mask_p1 = mask_p1 / mask_p1.sum(dim=-1, keepdim=True).clamp(min=1)
            actions[is_p1] = torch.multinomial(mask_p1, 1).squeeze(-1)

        engine.step_batch(actions)

        # Check game over
        new_done = (state.player_hp[:, 0] <= 0) | (state.player_hp[:, 1] <= 0) | (state.turn_number >= 200)
        just_done = new_done & ~done
        if just_done.any():
            wins[just_done & (state.player_hp[:, 0] > state.player_hp[:, 1])] = 1.0
        done = new_done

    return wins.mean().item()


def main():
    torch.manual_seed(SEED)

    # Setup
    from grid_tactics.card_library import CardLibrary
    from grid_tactics.rl.training import _build_standard_deck
    from grid_tactics.tensor_engine.card_table import CardTable
    from grid_tactics.tensor_engine.engine import TensorGameEngine
    from grid_tactics.tensor_engine.legal_actions import compute_legal_mask_batch
    from grid_tactics.tensor_engine.observation import encode_observations_batch, OBSERVATION_SIZE
    from grid_tactics.tensor_engine.constants import ACTION_SPACE_SIZE

    library = CardLibrary.from_directory(Path("data/cards"))
    deck_tuple = _build_standard_deck(library)
    deck_1d = torch.tensor(deck_tuple, dtype=torch.int32)
    card_table = CardTable.from_library(library, device=device)

    # Auto-tune if not specified
    global N_ENVS, N_STEPS, BATCH_SIZE
    if N_ENVS == 0 or N_STEPS == 0 or BATCH_SIZE == 0:
        auto_n, auto_steps, auto_batch = auto_tune(card_table, deck_1d)
        if N_ENVS == 0:
            N_ENVS = auto_n
        if N_STEPS == 0:
            N_STEPS = auto_steps
        if BATCH_SIZE == 0:
            BATCH_SIZE = auto_batch

    print("=" * 60)
    print("  GRID TACTICS — GPU Tensor Training")
    print(f"  GPU: {torch.cuda.get_device_name(0)}")
    print(f"  Steps: {TOTAL_STEPS:,}")
    print(f"  Envs: {N_ENVS}")
    print(f"  Rollout: {N_STEPS} steps x {N_ENVS} envs = {N_STEPS * N_ENVS:,} per update")
    print(f"  Batch: {BATCH_SIZE}")
    print("=" * 60)

    deck = deck_1d.unsqueeze(0).expand(N_ENVS, -1).to(device)
    engine = TensorGameEngine(N_ENVS, card_table, deck, deck, device=device)

    # Policy
    policy = PolicyNetwork(OBSERVATION_SIZE, ACTION_SPACE_SIZE).to(device)
    optimizer = torch.optim.Adam(policy.parameters(), lr=LR, eps=1e-5)

    print(f"  Policy params: {sum(p.numel() for p in policy.parameters()):,}")
    print()

    # Rollout buffers (all on GPU)
    obs_buf = torch.zeros(N_STEPS, N_ENVS, OBSERVATION_SIZE, device=device)
    act_buf = torch.zeros(N_STEPS, N_ENVS, dtype=torch.long, device=device)
    logp_buf = torch.zeros(N_STEPS, N_ENVS, device=device)
    rew_buf = torch.zeros(N_STEPS, N_ENVS, device=device)
    done_buf = torch.zeros(N_STEPS, N_ENVS, device=device)
    val_buf = torch.zeros(N_STEPS, N_ENVS, device=device)
    mask_buf = torch.zeros(N_STEPS, N_ENVS, ACTION_SPACE_SIZE, dtype=torch.bool, device=device)

    # Initialize
    engine.reset_batch()
    global_step = 0
    num_updates = TOTAL_STEPS // (N_STEPS * N_ENVS)
    start_time = time.perf_counter()

    out_dir = Path("/root/output")
    out_dir.mkdir(exist_ok=True)
    snapshots = []

    for update in range(1, num_updates + 1):
        # --- Rollout collection (all on GPU, no Python per-env loop) ---
        for step in range(N_STEPS):
            state = engine.state
            obs = encode_observations_batch(state, card_table, state.active_player)
            legal = compute_legal_mask_batch(state, card_table).bool()

            with torch.no_grad():
                action, log_prob, _, value = policy.get_action_and_value(obs, legal)

            # Auto-step opponent turns with random actions
            active = state.active_player
            is_opponent = (active == 1)
            if is_opponent.any():
                opp_legal = legal[is_opponent].float()
                opp_legal = opp_legal / opp_legal.sum(dim=-1, keepdim=True).clamp(min=1)
                action[is_opponent] = torch.multinomial(opp_legal, 1).squeeze(-1)

            engine.step_batch(action)

            # Reward: +1 win, -1 loss, 0 ongoing
            new_state = engine.state
            game_over = (new_state.player_hp[:, 0] <= 0) | (new_state.player_hp[:, 1] <= 0) | (new_state.turn_number >= 200)
            reward = torch.zeros(N_ENVS, device=device)
            reward[game_over & (new_state.player_hp[:, 0] > new_state.player_hp[:, 1])] = 1.0
            reward[game_over & (new_state.player_hp[:, 0] < new_state.player_hp[:, 1])] = -1.0

            obs_buf[step] = obs
            act_buf[step] = action
            logp_buf[step] = log_prob
            rew_buf[step] = reward
            done_buf[step] = game_over.float()
            val_buf[step] = value
            mask_buf[step] = legal

            # Reset finished games
            if game_over.any():
                engine.reset_batch(mask=game_over)

        global_step += N_STEPS * N_ENVS

        # --- GAE computation ---
        with torch.no_grad():
            next_obs = encode_observations_batch(engine.state, card_table, engine.state.active_player)
            next_legal = compute_legal_mask_batch(engine.state, card_table).bool()
            _, next_value = policy(next_obs, next_legal)

        advantages = torch.zeros_like(rew_buf)
        last_gae = 0
        for t in reversed(range(N_STEPS)):
            if t == N_STEPS - 1:
                next_non_terminal = 1.0 - done_buf[t]
                next_val = next_value
            else:
                next_non_terminal = 1.0 - done_buf[t]
                next_val = val_buf[t + 1]
            delta = rew_buf[t] + GAMMA * next_val * next_non_terminal - val_buf[t]
            advantages[t] = last_gae = delta + GAMMA * GAE_LAMBDA * next_non_terminal * last_gae
        returns = advantages + val_buf

        # --- PPO update ---
        b_obs = obs_buf.reshape(-1, OBSERVATION_SIZE)
        b_actions = act_buf.reshape(-1)
        b_logprobs = logp_buf.reshape(-1)
        b_advantages = advantages.reshape(-1)
        b_returns = returns.reshape(-1)
        b_masks = mask_buf.reshape(-1, ACTION_SPACE_SIZE)

        b_advantages = (b_advantages - b_advantages.mean()) / (b_advantages.std() + 1e-8)

        buffer_size = N_STEPS * N_ENVS
        batch_indices = torch.randperm(buffer_size, device=device)

        total_pg_loss = 0
        total_v_loss = 0
        total_entropy = 0
        n_batches = 0

        for epoch in range(N_EPOCHS):
            for start_idx in range(0, buffer_size, BATCH_SIZE):
                end_idx = min(start_idx + BATCH_SIZE, buffer_size)
                idx = batch_indices[start_idx:end_idx]

                _, new_logprob, entropy, new_value = policy.get_action_and_value(
                    b_obs[idx], b_masks[idx], b_actions[idx]
                )

                ratio = (new_logprob - b_logprobs[idx]).exp()
                adv = b_advantages[idx]

                pg_loss1 = -adv * ratio
                pg_loss2 = -adv * ratio.clamp(1 - CLIP_RANGE, 1 + CLIP_RANGE)
                pg_loss = torch.max(pg_loss1, pg_loss2).mean()

                v_loss = F.mse_loss(new_value, b_returns[idx])

                loss = pg_loss + VF_COEF * v_loss - ENT_COEF * entropy.mean()

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(policy.parameters(), MAX_GRAD_NORM)
                optimizer.step()

                total_pg_loss += pg_loss.item()
                total_v_loss += v_loss.item()
                total_entropy += entropy.mean().item()
                n_batches += 1

        # --- Logging ---
        elapsed = time.perf_counter() - start_time
        fps = global_step / elapsed
        avg_pg = total_pg_loss / n_batches
        avg_vl = total_v_loss / n_batches
        avg_ent = total_entropy / n_batches

        if update % 5 == 1 or update == num_updates:
            print(
                f"update {update:>5}/{num_updates} | "
                f"steps {global_step:>12,} | "
                f"fps {fps:>10,.0f} | "
                f"pg_loss {avg_pg:>8.4f} | "
                f"v_loss {avg_vl:>8.4f} | "
                f"entropy {avg_ent:>6.3f} | "
                f"elapsed {elapsed:>7.1f}s"
            )

        # --- Evaluation ---
        if global_step % EVAL_FREQ < N_STEPS * N_ENVS:
            win_rate = evaluate_vs_random(policy, TensorGameEngine, card_table, deck)
            print(f"  >>> EVAL @ {global_step:,}: win_rate = {win_rate:.1%}")
            snapshots.append({
                "timestep": global_step,
                "win_rate": win_rate,
                "pg_loss": avg_pg,
                "v_loss": avg_vl,
                "entropy": avg_ent,
                "fps": fps,
            })
            # Save snapshot to JSON for dashboard
            (out_dir / "snapshots.json").write_text(json.dumps(snapshots, indent=2))

    # --- Save ---
    total_time = time.perf_counter() - start_time
    final_fps = TOTAL_STEPS / total_time

    torch.save(policy.state_dict(), out_dir / "tensor_policy.pt")

    summary = {
        "total_steps": TOTAL_STEPS,
        "n_envs": N_ENVS,
        "elapsed_s": total_time,
        "fps": final_fps,
        "gpu": torch.cuda.get_device_name(0),
        "snapshots": snapshots,
    }
    (out_dir / "tensor_summary.json").write_text(json.dumps(summary, indent=2))

    print()
    print("=" * 60)
    print(f"  TRAINING COMPLETE")
    print(f"  {TOTAL_STEPS:,} steps in {total_time:.1f}s ({final_fps:,.0f} steps/sec)")
    print(f"  Model: {out_dir / 'tensor_policy.pt'}")
    if snapshots:
        print(f"  Final win rate: {snapshots[-1]['win_rate']:.1%}")
    print("=" * 60)


if __name__ == "__main__":
    main()
