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
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from torch.distributions import Categorical

# --- Patch version (increment when rules/cards/deck change) ---
PATCH_VERSION = "0.8A"  # draw as action, no pass, fatigue bleed 10/20/30, 30 card deck, curriculum

# --- Supabase reporting (optional, skipped if env vars missing) ---
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SECRET_KEY", "") or os.environ.get("SUPABASE_ANON_KEY", "")
_sb = None

def _init_supabase():
    global _sb
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("  [supabase] No credentials — reporting disabled")
        return
    try:
        from supabase import create_client
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"  [supabase] Connected to {SUPABASE_URL}")
    except ImportError:
        print("  [supabase] supabase-py not installed — reporting disabled")
    except Exception as e:
        print(f"  [supabase] Connection failed: {e}")

def _sb_upsert_run(run_id, data):
    if not _sb:
        return
    try:
        _sb.table("training_runs").upsert({"run_id": run_id, **data}).execute()
    except Exception as e:
        print(f"  [supabase] run upsert failed: {e}")

def _sb_insert_snapshot(data):
    if not _sb:
        return
    try:
        _sb.table("training_snapshots").insert(data).execute()
    except Exception as e:
        print(f"  [supabase] snapshot insert failed: {e}")

def _sb_insert_game_results(rows):
    if not _sb or not rows:
        return
    try:
        # Batch insert in chunks of 200
        for i in range(0, len(rows), 200):
            _sb.table("game_results").insert(rows[i:i+200]).execute()
    except Exception as e:
        print(f"  [supabase] game_results insert failed: {e}")

def _sb_upsert_card_stats(rows):
    if not _sb or not rows:
        return
    try:
        _sb.table("card_stats").upsert(rows).execute()
    except Exception as e:
        print(f"  [supabase] card_stats upsert failed: {e}")

def _sb_upload_model_if_best(state_dict, patch_version, win_rate, run_id):
    """Upload model only if this run achieved the best win rate for this patch."""
    if not _sb:
        return
    try:
        # Check current best win rate from DB
        result = _sb.table("training_runs").select("final_win_rate, run_id").eq("patch_version", patch_version).not_.is_("final_win_rate", "null").order("final_win_rate", desc=True).limit(1).execute()
        current_best = result.data[0]["final_win_rate"] if result.data else 0
        current_best_run = result.data[0]["run_id"] if result.data else None

        if win_rate >= current_best or current_best_run == run_id:
            import io
            buf = io.BytesIO()
            torch.save(state_dict, buf)
            buf.seek(0)
            path = f"models/policy_{patch_version}.pt"
            try:
                _sb.storage.from_("deploys").remove([path])
            except Exception:
                pass
            _sb.storage.from_("deploys").upload(path, buf.getvalue(), file_options={"content-type": "application/octet-stream"})
            print(f"  [supabase] NEW BEST MODEL uploaded ({win_rate:.1%} > {current_best:.1%}): {path}")
        else:
            print(f"  [supabase] Not uploading — win rate {win_rate:.1%} < current best {current_best:.1%}")
    except Exception as e:
        print(f"  [supabase] Model upload failed: {e}")

def _sb_download_model(patch_version, device):
    """Download previous model weights from Supabase Storage if they exist."""
    if not _sb:
        return None
    try:
        import io
        path = f"models/policy_{patch_version}.pt"
        data = _sb.storage.from_("deploys").download(path)
        if data:
            buf = io.BytesIO(data)
            state_dict = torch.load(buf, map_location=device, weights_only=True)
            print(f"  [supabase] Loaded previous model: {path}")
            return state_dict
    except Exception as e:
        print(f"  [supabase] No previous model found (starting fresh): {e}")
    return None


class GameTracker:
    """Tracks per-card plays and game results on GPU, flushes to Supabase periodically."""

    def __init__(self, num_cards, n_envs, device, run_id, card_names):
        self.num_cards = num_cards
        self.n_envs = n_envs
        self.device = device
        self.run_id = run_id
        self.card_names = card_names  # numeric_id -> card_id string

        # Per-card counters: [num_cards] — accumulated across all games
        self.card_plays = torch.zeros(num_cards, dtype=torch.long, device=device)       # times played (p0)
        self.card_wins = torch.zeros(num_cards, dtype=torch.long, device=device)        # wins when played
        self.card_losses = torch.zeros(num_cards, dtype=torch.long, device=device)      # losses when played

        # Per-game card tracking: [N_ENVS, num_cards] — cards played THIS game by p0
        self.game_card_mask = torch.zeros(n_envs, num_cards, dtype=torch.bool, device=device)

        # Per-game damage tracking: [N_ENVS, 2] per source
        self.pass_dmg = torch.zeros(n_envs, 2, dtype=torch.long, device=device)
        self.combat_dmg = torch.zeros(n_envs, 2, dtype=torch.long, device=device)
        self.sacrifice_dmg = torch.zeros(n_envs, 2, dtype=torch.long, device=device)

        # Per-game minion combat tracking: [N_ENVS, 2]
        self.minion_dmg_dealt = torch.zeros(n_envs, 2, dtype=torch.long, device=device)  # dmg dealt to enemy minions
        self.minions_killed = torch.zeros(n_envs, 2, dtype=torch.long, device=device)    # enemy minions killed

        # Game result buffer (flushed periodically)
        self.game_results_buf = []
        self.episode_counter = 0
        self.total_games = 0
        self.flush_freq = 500  # flush every N buffered games
        self.sample_rate = 100  # only log 1 in N games to avoid DB bloat

    def record_minion_combat(self, state_before, state_after):
        """Track minion damage dealt and kills by comparing minion HP before/after."""
        for p in range(2):
            enemy = 1 - p
            # Enemy minions that were alive before
            was_alive = state_before.minion_alive & (state_before.minion_owner == enemy)
            still_alive = state_after.minion_alive & (state_after.minion_owner == enemy)

            # HP lost by enemy minions (summed across all slots)
            hp_before = state_before.minion_health * was_alive.long()
            hp_after = state_after.minion_health * still_alive.long()
            dmg = (hp_before - hp_after).clamp(min=0).sum(dim=1)
            self.minion_dmg_dealt[:, p] += dmg.long()

            # Kills: was alive, now not alive
            kills = (was_alive & ~still_alive).sum(dim=1)
            self.minions_killed[:, p] += kills.long()

    def record_damage(self, action, state_before, state_after):
        """Track damage sources by comparing HP before/after a step."""
        from grid_tactics.tensor_engine.constants import PASS_IDX, SACRIFICE_BASE, DRAW_IDX

        a = action.long()
        ap = state_before.active_player

        # Pass damage: action == PASS_IDX, active player loses 5hp
        is_pass = (a == PASS_IDX)
        if is_pass.any():
            for p in range(2):
                is_p_pass = is_pass & (ap == p)
                self.pass_dmg[:, p] += 5 * is_p_pass.long()

        # Sacrifice damage: action in SACRIFICE range, opponent takes damage
        is_sac = (a >= SACRIFICE_BASE) & (a < DRAW_IDX)
        if is_sac.any():
            hp_before = state_before.player_hp.clone()
            hp_after = state_after.player_hp
            for p in range(2):
                dmg = (hp_before[:, p] - hp_after[:, p]).clamp(min=0)
                self.sacrifice_dmg[:, p] += dmg.long() * is_sac.long()

        # Combat damage: HP change not from pass or sacrifice
        hp_diff_0 = (state_before.player_hp[:, 0] - state_after.player_hp[:, 0]).clamp(min=0)
        hp_diff_1 = (state_before.player_hp[:, 1] - state_after.player_hp[:, 1]).clamp(min=0)
        is_not_pass = ~is_pass
        is_not_sac = ~is_sac
        other = is_not_pass & is_not_sac
        self.combat_dmg[:, 0] += hp_diff_0.long() * other.long()
        self.combat_dmg[:, 1] += hp_diff_1.long() * other.long()

    def record_action(self, action, state, card_table):
        """Record card plays from actions. Call each step during rollout."""
        from grid_tactics.tensor_engine.constants import PLAY_CARD_BASE, MOVE_BASE, REACT_BASE, GRID_SIZE, MAX_HAND

        a = action.long()
        active = state.active_player  # [N]
        is_p0 = (active == 0)

        # PLAY_CARD actions [0:250]: hand_idx = (a - PLAY_CARD_BASE) // GRID_SIZE
        is_play = (a >= PLAY_CARD_BASE) & (a < MOVE_BASE) & is_p0
        if is_play.any():
            hand_idx = ((a[is_play] - PLAY_CARD_BASE) // GRID_SIZE).long()
            # Look up card_numeric_id from hand
            play_envs = torch.where(is_play)[0]
            card_ids = state.hands[play_envs, 0, hand_idx]  # player 0's hand
            valid = card_ids >= 0
            if valid.any():
                valid_cards = card_ids[valid].long()
                self.card_plays.scatter_add_(0, valid_cards, torch.ones(valid_cards.shape[0], dtype=torch.long, device=self.device))
                # Mark in per-game mask
                self.game_card_mask[play_envs[valid], valid_cards] = True

        # REACT actions [1002:1262]: hand_idx = (a - REACT_BASE) // 26
        is_react = (a >= REACT_BASE) & is_p0
        if is_react.any():
            hand_idx = ((a[is_react] - REACT_BASE) // 26).long().clamp(0, MAX_HAND - 1)
            react_envs = torch.where(is_react)[0]
            card_ids = state.hands[react_envs, 0, hand_idx]
            valid = card_ids >= 0
            if valid.any():
                valid_cards = card_ids[valid].long()
                self.card_plays.scatter_add_(0, valid_cards, torch.ones(valid_cards.shape[0], dtype=torch.long, device=self.device))
                self.game_card_mask[react_envs[valid], valid_cards] = True

    def record_game_over(self, game_over, state, reward):
        """Record completed games. Call when game_over mask is True."""
        if not game_over.any():
            return

        go_idx = torch.where(game_over)[0]
        hp0 = state.player_hp[go_idx, 0].cpu()
        hp1 = state.player_hp[go_idx, 1].cpu()
        turns = state.turn_number[go_idx].cpu()
        rew = reward[go_idx].cpu()

        # Update card win/loss counters
        won = (rew > 0)
        lost = (rew < 0)
        cards_played = self.game_card_mask[go_idx]  # [num_finished, num_cards]

        if won.any():
            win_cards = cards_played[won]  # [num_wins, num_cards]
            self.card_wins += win_cards.sum(dim=0).long()
        if lost.any():
            loss_cards = cards_played[lost]
            self.card_losses += loss_cards.sum(dim=0).long()

        # Buffer game results for Supabase (sampled to avoid DB bloat)
        for i in range(len(go_idx)):
            self.episode_counter += 1
            if self.episode_counter % self.sample_rate != 0:
                continue
            winner = 0 if rew[i] > 0 else (1 if rew[i] < 0 else None)
            idx = go_idx[i]
            self.game_results_buf.append({
                "run_id": self.run_id,
                "episode_num": self.episode_counter,
                "winner": winner,
                "turn_count": int(turns[i]),
                "p1_hp": int(hp0[i]),
                "p2_hp": int(hp1[i]),
                "p1_pass_dmg": int(self.pass_dmg[idx, 0].item()),
                "p2_pass_dmg": int(self.pass_dmg[idx, 1].item()),
                "p1_combat_dmg": int(self.combat_dmg[idx, 0].item()),
                "p2_combat_dmg": int(self.combat_dmg[idx, 1].item()),
                "p1_sacrifice_dmg": int(self.sacrifice_dmg[idx, 0].item()),
                "p2_sacrifice_dmg": int(self.sacrifice_dmg[idx, 1].item()),
                "p1_minion_dmg_dealt": int(self.minion_dmg_dealt[idx, 0].item()),
                "p2_minion_dmg_dealt": int(self.minion_dmg_dealt[idx, 1].item()),
                "p1_minions_killed": int(self.minions_killed[idx, 0].item()),
                "p2_minions_killed": int(self.minions_killed[idx, 1].item()),
                "patch_version": PATCH_VERSION,
            })

        self.total_games += len(go_idx)

        # Reset per-game tracking for finished games
        self.game_card_mask[go_idx] = False
        self.pass_dmg[go_idx] = 0
        self.combat_dmg[go_idx] = 0
        self.sacrifice_dmg[go_idx] = 0
        self.minion_dmg_dealt[go_idx] = 0
        self.minions_killed[go_idx] = 0

        # Flush if buffer is large enough
        if len(self.game_results_buf) >= self.flush_freq:
            self.flush_games()

    def flush_games(self):
        """Send buffered game results to Supabase."""
        if self.game_results_buf:
            _sb_insert_game_results(self.game_results_buf)
            self.game_results_buf = []

    def flush_card_stats(self):
        """Compute and send card stats to Supabase."""
        plays = self.card_plays.cpu()
        wins = self.card_wins.cpu()
        losses = self.card_losses.cpu()

        rows = []
        for i in range(self.num_cards):
            p = int(plays[i])
            if p == 0:
                continue
            w = int(wins[i])
            l = int(losses[i])
            total_decided = w + l
            wr = w / total_decided if total_decided > 0 else 0.5
            total_plays = int(plays.sum())
            pick_rate = p / total_plays if total_plays > 0 else 0

            rows.append({
                "run_id": self.run_id,
                "card_id": self.card_names.get(i, f"card_{i}"),
                "times_played": p,
                "win_rate": round(wr, 4),
                "pick_rate": round(pick_rate, 4),
                "patch_version": PATCH_VERSION,
            })

        _sb_upsert_card_stats(rows)


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
        new_done = (state.player_hp[:, 0] <= 0) | (state.player_hp[:, 1] <= 0) | (state.turn_number >= 100)
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
    from grid_tactics.types import STARTING_HP

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

    # --- Supabase: register training run + load previous model ---
    _init_supabase()

    # Try to continue from previous training
    prev_weights = _sb_download_model(PATCH_VERSION, device)
    if prev_weights is not None:
        try:
            policy.load_state_dict(prev_weights)
            print("  Continuing from previous model!")
        except Exception as e:
            print(f"  Model shape mismatch (new arch?), starting fresh: {e}")
    else:
        print("  Starting fresh (no previous model)")
    print()
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    _sb_upsert_run(run_id, {
        "run_name": f"v{PATCH_VERSION}-{gpu_name.split()[-1]}-{N_ENVS}env",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "total_timesteps": TOTAL_STEPS,
        "gpu_name": gpu_name,
        "method": "tensor-ppo",
        "seed": SEED,
        "n_envs": N_ENVS,
        "n_steps": N_STEPS,
        "batch_size": BATCH_SIZE,
        "patch_version": PATCH_VERSION,
        "hyperparameters": json.dumps({
            "lr": LR, "gamma": GAMMA, "gae_lambda": GAE_LAMBDA,
            "clip_range": CLIP_RANGE, "ent_coef": ENT_COEF,
            "vf_coef": VF_COEF, "n_epochs": N_EPOCHS,
        }),
    })

    # --- Game & card tracker ---
    card_names = {i: library._id_to_card_id[i] for i in range(library.card_count)}
    tracker = GameTracker(library.card_count, N_ENVS, device, run_id, card_names)

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

            # Track card plays BEFORE stepping (state has current hand)
            tracker.record_action(action, state, card_table)

            state_before_hp = engine.state.player_hp.clone()
            minion_hp_before = engine.state.minion_health.clone()
            minion_alive_before = engine.state.minion_alive.clone()
            minion_owner_before = engine.state.minion_owner.clone()
            engine.step_batch(action)

            # Track damage sources
            tracker.record_damage(action, type('S', (), {'player_hp': state_before_hp, 'active_player': state.active_player})(), engine.state)
            tracker.record_minion_combat(
                type('S', (), {'minion_alive': minion_alive_before, 'minion_owner': minion_owner_before, 'minion_health': minion_hp_before})(),
                engine.state
            )

            # Reward: win/loss + shaped rewards to teach gameplay flow
            new_state = engine.state
            game_over = (new_state.player_hp[:, 0] <= 0) | (new_state.player_hp[:, 1] <= 0) | (new_state.turn_number >= 100)
            reward = torch.zeros(N_ENVS, device=device)
            reward[game_over & (new_state.player_hp[:, 0] > new_state.player_hp[:, 1])] = 1.0
            reward[game_over & (new_state.player_hp[:, 0] < new_state.player_hp[:, 1])] = -1.0

            # --- CURRICULUM-BASED SHAPED REWARDS ---
            # Phase 1 (0-20M steps): Learn to deploy and advance
            # Phase 2 (20-50M steps): Learn to fight and kill
            # Phase 3 (50M+ steps): Learn to sacrifice and win, shaping fades
            ongoing = ~game_over
            is_p0_turn = (state.active_player == 0)
            p0 = ongoing & is_p0_turn
            a = action.long()

            from grid_tactics.tensor_engine.constants import (
                PLAY_CARD_BASE, MOVE_BASE, ATTACK_BASE, SACRIFICE_BASE,
                DRAW_IDX, PASS_IDX, REACT_BASE
            )

            # Curriculum phase based on global step
            progress = min(global_step / TOTAL_STEPS, 1.0)  # 0.0 to 1.0
            phase1 = 1.0 if progress < 0.2 else max(0, 1.0 - (progress - 0.2) / 0.3)  # fades 0.2-0.5
            phase2 = min(1.0, max(0, (progress - 0.1) / 0.2))  # ramps 0.1-0.3
            phase3 = min(1.0, max(0, (progress - 0.3) / 0.2))  # ramps 0.3-0.5

            # === PHASE 1: Deploy + Advance (strong early, fades) ===
            is_play = (a >= PLAY_CARD_BASE) & (a < MOVE_BASE)
            reward += 0.05 * phase1 * (p0 & is_play).float()

            is_move = (a >= MOVE_BASE) & (a < ATTACK_BASE)
            reward += 0.05 * phase1 * (p0 & is_move).float()

            # Empty board penalty (always on)
            my_minions = (new_state.minion_alive & (new_state.minion_owner == 0)).sum(dim=1)
            reward -= 0.02 * (my_minions == 0).float() * p0.float()

            # No pass penalty -- pass only happens via fatigue (no legal actions)

            # === PHASE 2: Combat (ramps up, stays) ===
            is_attack = (a >= ATTACK_BASE) & (a < SACRIFICE_BASE)
            reward += 0.05 * phase2 * (p0 & is_attack).float()

            old_enemy_alive = state.minion_alive & (state.minion_owner == 1)
            new_enemy_alive = new_state.minion_alive & (new_state.minion_owner == 1)
            enemy_kills = (old_enemy_alive.sum(dim=1) - new_enemy_alive.sum(dim=1)).clamp(min=0)
            reward += 0.1 * phase2 * enemy_kills.float() * p0.float()

            # === PHASE 3: Win condition (ramps up, dominates) ===
            is_sac = (a >= SACRIFICE_BASE) & (a < DRAW_IDX)
            reward += 0.5 * phase3 * (p0 & is_sac).float()

            # Positional bonus: minions in enemy territory (scales with phase3)
            for row in range(5):
                row_bonus = (row - 2) * 0.003 * (phase2 + phase3) / 2
                my_in_row = (
                    new_state.minion_alive & (new_state.minion_owner == 0) & (new_state.minion_row == row)
                ).sum(dim=1).float()
                reward += row_bonus * my_in_row * p0.float()

            # HP advantage (always on, scales up)
            old_hp_diff = state_before_hp[:, 0] - state_before_hp[:, 1]
            new_hp_diff = new_state.player_hp[:, 0] - new_state.player_hp[:, 1]
            hp_delta = (new_hp_diff - old_hp_diff).float() / STARTING_HP
            reward += hp_delta * (0.005 + 0.015 * phase3) * ongoing.float()

            # Track game results
            tracker.record_game_over(game_over, new_state, reward)

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

        # Update run progress in Supabase
        gpu_util = 0.0
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                gpu_util = float(result.stdout.strip().split("\n")[0])
        except Exception:
            pass

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
            _sb_upsert_run(run_id, {
                "current_steps": global_step,
                "current_fps": fps,
                "gpu_util": gpu_util,
            })

        # --- Evaluation ---
        if global_step % EVAL_FREQ < N_STEPS * N_ENVS:
            win_rate = evaluate_vs_random(policy, TensorGameEngine, card_table, deck)
            print(f"  >>> EVAL @ {global_step:,}: win_rate = {win_rate:.1%}")
            snap = {
                "timestep": global_step,
                "win_rate": win_rate,
                "pg_loss": avg_pg,
                "v_loss": avg_vl,
                "entropy": avg_ent,
                "fps": fps,
            }
            snapshots.append(snap)
            # Save snapshot to JSON for dashboard
            (out_dir / "snapshots.json").write_text(json.dumps(snapshots, indent=2))
            # Push to Supabase
            _sb_insert_snapshot({
                "run_id": run_id,
                "timestep": global_step,
                "win_rate": win_rate,
                "pg_loss": avg_pg,
                "v_loss": avg_vl,
                "entropy": avg_ent,
                "fps": fps,
                "gpu_util": gpu_util,
                "patch_version": PATCH_VERSION,
            })
            # Flush card stats and remaining game results at each eval
            tracker.flush_games()
            tracker.flush_card_stats()
            print(f"  >>> Games tracked: {tracker.total_games:,} | Cards with data: {(tracker.card_plays > 0).sum().item()}")

    # --- Final flush ---
    tracker.flush_games()
    tracker.flush_card_stats()

    # --- Save ---
    total_time = time.perf_counter() - start_time
    final_fps = TOTAL_STEPS / total_time

    torch.save(policy.state_dict(), out_dir / "tensor_policy.pt")

    # Upload model only if this run's win rate is the best so far
    final_wr = snapshots[-1]["win_rate"] if snapshots else 0
    _sb_upload_model_if_best(policy.state_dict(), PATCH_VERSION, final_wr, run_id)

    summary = {
        "total_steps": TOTAL_STEPS,
        "n_envs": N_ENVS,
        "elapsed_s": total_time,
        "fps": final_fps,
        "gpu": torch.cuda.get_device_name(0),
        "snapshots": snapshots,
    }
    (out_dir / "tensor_summary.json").write_text(json.dumps(summary, indent=2))

    # Mark run complete in Supabase
    _sb_upsert_run(run_id, {
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "current_steps": TOTAL_STEPS,
        "current_fps": final_fps,
        "final_win_rate": snapshots[-1]["win_rate"] if snapshots else None,
        "model_path": str(out_dir / "tensor_policy.pt"),
    })

    print()
    print("=" * 60)
    print(f"  TRAINING COMPLETE")
    print(f"  {TOTAL_STEPS:,} steps in {total_time:.1f}s ({final_fps:,.0f} steps/sec)")
    print(f"  Model: {out_dir / 'tensor_policy.pt'}")
    if snapshots:
        print(f"  Final win rate: {snapshots[-1]['win_rate']:.1%}")
    print(f"  Supabase: {'connected' if _sb else 'disabled'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
