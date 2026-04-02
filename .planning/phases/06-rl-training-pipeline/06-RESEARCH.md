# Phase 6: RL Training Pipeline - Research

**Researched:** 2026-04-02
**Domain:** MaskablePPO training, self-play, reward shaping, SQLite data persistence
**Confidence:** HIGH

## Summary

Phase 6 builds the first trained RL agent and the data pipeline that feeds the stats dashboard. The existing GridTacticsEnv (Phase 5) is Gymnasium-compatible with `action_masks()` already implemented -- MaskablePPO can train against it directly. The core work is: (1) installing the RL training stack (SB3 + sb3-contrib + PyTorch -- currently NOT installed), (2) implementing a self-play wrapper that swaps opponent policies from a checkpoint pool, (3) adding potential-based reward shaping on top of the existing sparse +1/-1/0 signal, (4) creating SQLite persistence for game results and training metadata, and (5) wiring TensorBoard logging.

The existing environment has observation_space Box(292,) and action_space Discrete(1262). MaskablePPO's `MlpPolicy` (default 2-layer MLP with [64,64] hidden units) is the correct starting point -- the 5x5 grid is small enough that a flat MLP can learn basic strategy before justifying CNN complexity. Self-play requires a custom `SelfPlayCallback` + `SelfPlayEnv` wrapper because SB3 has no built-in self-play; the PettingZoo Connect Four tutorial provides the reference pattern but must be extended with an opponent pool to prevent strategy cycling (Pitfall 5). SQLite schema must be dashboard-ready for Phase 9 (Streamlit reads directly from SQLite).

**Primary recommendation:** Start with MlpPolicy + sparse rewards to validate the pipeline end-to-end, then layer in reward shaping and opponent pool in subsequent plans. Install SB3 stack as the first task since nothing else works without it.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** MaskablePPO from sb3-contrib for training (decided in project setup)
- **D-02:** Self-play: both sides controlled by RL agents, periodic checkpoint saving
- **D-03:** Agent should beat random play convincingly after training
- **D-04:** Potential-based reward shaping with intermediate signals: damage dealt, board control, mana efficiency
- **D-05:** Base reward: +1 win, -1 loss, 0 ongoing (already implemented in Phase 5)
- **D-06:** Shaping must use potential-based formulation to preserve optimal policy
- **D-07:** SQLite database for game results: winner, scores, deck compositions, game length, card actions
- **D-08:** Training run metadata: hyperparameters, timestamps, episode counts, win rates over time
- **D-09:** Data must be queryable for the stats dashboard (Phase 9 will read from SQLite)

### Claude's Discretion
- MaskablePPO hyperparameters (learning rate, batch size, n_steps, etc.)
- Self-play implementation (vs frozen opponent, vs latest, vs pool)
- SQLite schema design
- Checkpoint frequency
- Training duration for initial validation
- Reward shaping weights and potential function design

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RL-04 | MaskablePPO training via SB3 sb3-contrib | MaskablePPO API researched; env already has action_masks(); MlpPolicy recommended for initial training |
| RL-05 | Self-play training loop with both players as RL agents | Self-play wrapper pattern from PettingZoo Connect Four; opponent pool design for collapse prevention |
| RL-06 | Reward shaping with intermediate signals using potential-based shaping | Potential-based formulation F(s,s') = gamma*Phi(s') - Phi(s) preserves optimal policy; potential function design for damage/board control/mana |
| DATA-01 | Game results persisted to SQLite (winner, scores, deck compositions, game length, card actions) | SQLite schema designed with dashboard-ready queries; WAL mode for concurrent read/write |
| DATA-02 | Training run metadata stored for comparison across experiments | Training runs table with hyperparameters, timestamps, win rate snapshots |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Language:** Python for game engine and RL
- **RL focus:** Core strategy discovery is the priority
- **Testing:** Each development step validated with RL to confirm strategic depth
- **Workflow:** Use GSD entry points; do not make direct repo edits outside GSD workflow
- **Stack:** SB3 + sb3-contrib for RL, SQLite for persistence, TensorBoard for monitoring
- **Quality:** pytest, mypy (strict), ruff for code quality

## Standard Stack

### Core (must install -- NOT currently in venv)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| stable-baselines3 | >=2.8,<3.0 | PPO algorithm implementation | Community standard for single-machine RL; already decided in STACK.md |
| sb3-contrib | >=2.8,<3.0 | MaskablePPO for action masking | Required by D-01; handles Discrete(1262) with heavy masking |
| torch | (pulled by SB3) | Neural network backend | SB3 dependency; do NOT install separately |
| tensorboard | >=2.18 | Training metric visualization | Ships with SB3[extra]; zero-config integration |

### Already Installed

| Library | Version | Purpose |
|---------|---------|---------|
| gymnasium | 1.2.3 | RL environment API |
| numpy | 2.4.4 | Array operations |
| grid-tactics-tcg | 0.1.0 (editable) | Game engine |

### Supporting (stdlib -- no install needed)

| Library | Purpose |
|---------|---------|
| sqlite3 | Game result persistence, training metadata |
| json | Hyperparameter serialization |
| time/datetime | Timestamps for runs |
| pathlib | File path management |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| MlpPolicy (initial) | CNN custom extractor | CNN adds complexity; 292-dim flat obs works fine with MLP; add CNN only if MLP plateaus |
| TensorBoard | Weights & Biases | W&B is better for experiment comparison but adds external dependency; TensorBoard is zero-config with SB3 |
| sqlite3 (stdlib) | SQLAlchemy | ORM overhead unnecessary for simple schema; raw SQL is clearer for this use case |

**Installation:**
```bash
# From project root, in .venv
pip install "stable-baselines3[extra]>=2.8,<3.0" "sb3-contrib>=2.8,<3.0"
```

Note: `stable-baselines3[extra]` includes TensorBoard. PyTorch is pulled as a transitive dependency. This is a large install (~2GB with PyTorch).

## Architecture Patterns

### Recommended Project Structure
```
src/grid_tactics/rl/
    __init__.py
    env.py               # (existing) GridTacticsEnv
    observation.py        # (existing) encode_observation()
    action_space.py       # (existing) ActionEncoder, build_action_mask()
    reward.py             # (extend) compute_reward() + potential-based shaping
    self_play.py          # (new) SelfPlayEnv wrapper, opponent pool
    training.py           # (new) train_agent() entry point, hyperparameters
    callbacks.py          # (new) SelfPlayCallback, CheckpointPoolCallback
    checkpoint_manager.py # (new) save/load/sample from checkpoint pool
data/
    training.db           # (new) SQLite database
    checkpoints/          # (new) model checkpoint files
    tb_logs/              # (new) TensorBoard logs
src/grid_tactics/db/
    __init__.py
    schema.py             # (new) SQLite schema creation + migration
    writer.py             # (new) write game results, training metadata
    reader.py             # (new) query interface (used by Phase 9 dashboard)
```

### Pattern 1: SelfPlayEnv Wrapper

**What:** A Gymnasium env wrapper that plays the opponent side using a frozen policy loaded from the checkpoint pool. The training agent only sees its own turns.

**When to use:** Always during self-play training.

**Example:**
```python
import gymnasium
import numpy as np
from sb3_contrib import MaskablePPO

class SelfPlayEnv(gymnasium.Wrapper):
    """Wraps GridTacticsEnv for single-agent self-play training.

    When it is the opponent's turn, the wrapper automatically queries
    the opponent policy and steps the underlying env until it is the
    training agent's turn again.
    """

    def __init__(self, env, opponent_policy=None):
        super().__init__(env)
        self.opponent_policy = opponent_policy  # MaskablePPO or None (random)
        self.training_player_idx = 0  # Training agent is always player 0

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        # If opponent moves first, auto-step
        if self._is_opponent_turn():
            obs, info = self._opponent_step(obs, info)
        return obs, info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        if terminated or truncated:
            return obs, reward, terminated, truncated, info
        # Auto-play opponent turns
        while self._is_opponent_turn() and not (terminated or truncated):
            obs, opp_reward, terminated, truncated, info = self._opponent_step_inner()
            # Accumulate: we want training agent's reward
            reward += 0  # opponent reward is irrelevant to training agent
        return obs, reward, terminated, truncated, info

    def _is_opponent_turn(self):
        return self.env._current_player_idx() != self.training_player_idx

    def _opponent_step_inner(self):
        mask = self.env.action_masks()
        if self.opponent_policy is None:
            # Random opponent: sample uniformly from legal actions
            legal = np.where(mask)[0]
            action = int(np.random.choice(legal))
        else:
            obs = self.env.observation_space.sample()  # get current obs
            action, _ = self.opponent_policy.predict(
                self.env._get_obs(), action_masks=mask, deterministic=False
            )
            action = int(action)
        return self.env.step(action)
```

### Pattern 2: Potential-Based Reward Shaping

**What:** Add shaped reward F(s, s') = gamma * Phi(s') - Phi(s) where Phi is a potential function over game states. This preserves the optimal policy (proven by Ng et al., 1999).

**When to use:** After base sparse training is validated, to accelerate convergence.

**Key formulation:**
```python
def potential(state, player_idx):
    """Heuristic potential function: higher = better position for player."""
    me = state.players[player_idx]
    opp = state.players[1 - player_idx]

    # Component weights (Claude's discretion -- tune these)
    hp_weight = 0.3
    board_weight = 0.3
    mana_weight = 0.2
    minion_weight = 0.2

    # HP advantage (normalized)
    hp_diff = (me.hp - opp.hp) / 40.0  # STARTING_HP * 2

    # Board control: count of my minions vs opponent's
    my_minions = len(state.get_minions_for_side(PlayerSide(player_idx)))
    opp_minions = len(state.get_minions_for_side(PlayerSide(1 - player_idx)))
    board_diff = (my_minions - opp_minions) / 10.0

    # Mana efficiency: having mana available is good
    mana_norm = me.current_mana / 10.0  # MAX_MANA_CAP

    # Minion position advancement (closer to opponent's back row)
    advancement = 0.0
    for m in state.get_minions_for_side(PlayerSide(player_idx)):
        if player_idx == 0:
            advancement += m.position[0] / 4.0  # row 4 is opponent's back
        else:
            advancement += (4 - m.position[0]) / 4.0
    advancement /= max(my_minions, 1)

    return (hp_weight * hp_diff +
            board_weight * board_diff +
            mana_weight * mana_norm +
            minion_weight * advancement)


def shaped_reward(prev_state, new_state, player_idx, gamma=0.99):
    """Potential-based reward shaping: F = gamma*Phi(s') - Phi(s)."""
    base = compute_reward(new_state, player_idx)
    shaping = gamma * potential(new_state, player_idx) - potential(prev_state, player_idx)
    return base + shaping
```

### Pattern 3: MaskablePPO Training Entry Point

**What:** Clean training function with sensible defaults.

**Example:**
```python
from sb3_contrib import MaskablePPO

def create_model(env, seed=42, tensorboard_log="data/tb_logs"):
    """Create MaskablePPO model with recommended hyperparameters."""
    return MaskablePPO(
        "MlpPolicy",
        env,
        learning_rate=3e-4,
        n_steps=2048,
        batch_size=64,
        n_epochs=10,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.01,     # Slight entropy bonus for exploration
        vf_coef=0.5,
        max_grad_norm=0.5,
        verbose=1,
        seed=seed,
        tensorboard_log=tensorboard_log,
    )
```

### Pattern 4: SB3 Callback for Checkpoint Pool

**What:** Custom callback that saves model checkpoints to a pool at regular intervals and optionally swaps the opponent in the SelfPlayEnv.

**Example:**
```python
from stable_baselines3.common.callbacks import BaseCallback

class SelfPlayCallback(BaseCallback):
    """Save checkpoints to pool and update opponent policy."""

    def __init__(self, save_freq=10_000, pool_dir="data/checkpoints",
                 pool_size=10, verbose=0):
        super().__init__(verbose)
        self.save_freq = save_freq
        self.pool_dir = Path(pool_dir)
        self.pool_size = pool_size
        self.pool_dir.mkdir(parents=True, exist_ok=True)

    def _on_step(self):
        if self.n_calls % self.save_freq == 0:
            path = self.pool_dir / f"checkpoint_{self.n_calls}"
            self.model.save(str(path))
            # Prune old checkpoints if pool exceeds size
            self._prune_pool()
            # Update opponent in env
            self._swap_opponent()
        return True

    def _swap_opponent(self):
        """Sample opponent from pool: 50% latest, 50% random historical."""
        checkpoints = sorted(self.pool_dir.glob("checkpoint_*.zip"))
        if not checkpoints:
            return
        if np.random.random() < 0.5 or len(checkpoints) == 1:
            opponent_path = checkpoints[-1]  # latest
        else:
            opponent_path = np.random.choice(checkpoints[:-1])
        opponent = MaskablePPO.load(str(opponent_path))
        # Update env's opponent reference
        env = self.training_env.envs[0]  # unwrap
        if hasattr(env, 'opponent_policy'):
            env.opponent_policy = opponent
```

### Pattern 5: SQLite Schema (Dashboard-Ready)

**What:** Schema designed for Phase 9 Streamlit dashboard queries.

```sql
-- Training runs: one row per training session
CREATE TABLE IF NOT EXISTS training_runs (
    run_id          TEXT PRIMARY KEY,    -- UUID or timestamp-based
    started_at      TEXT NOT NULL,       -- ISO 8601
    ended_at        TEXT,
    total_timesteps INTEGER,
    hyperparameters TEXT NOT NULL,       -- JSON blob
    model_path      TEXT,               -- path to saved model
    description     TEXT,
    git_commit      TEXT
);

-- Game results: one row per completed game episode
CREATE TABLE IF NOT EXISTS game_results (
    game_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES training_runs(run_id),
    episode_num     INTEGER NOT NULL,
    seed            INTEGER,
    winner          INTEGER,            -- 0=player1, 1=player2, NULL=draw
    turn_count      INTEGER NOT NULL,
    p1_final_hp     INTEGER NOT NULL,
    p2_final_hp     INTEGER NOT NULL,
    p1_deck_hash    TEXT,               -- hash of deck composition for grouping
    p2_deck_hash    TEXT,
    game_duration_ms REAL,
    timestamp       TEXT NOT NULL        -- ISO 8601
);

-- Deck compositions: maps deck hashes to card lists
CREATE TABLE IF NOT EXISTS deck_compositions (
    deck_hash       TEXT PRIMARY KEY,
    card_counts     TEXT NOT NULL        -- JSON: {"fire_imp": 3, "fireball": 3, ...}
);

-- Card actions: per-game card usage stats (aggregated, not per-step)
CREATE TABLE IF NOT EXISTS card_actions (
    game_id         INTEGER NOT NULL REFERENCES game_results(game_id),
    player          INTEGER NOT NULL,   -- 0 or 1
    card_numeric_id INTEGER NOT NULL,
    times_played    INTEGER DEFAULT 0,
    total_damage    INTEGER DEFAULT 0,
    times_killed    INTEGER DEFAULT 0,
    PRIMARY KEY (game_id, player, card_numeric_id)
);

-- Win rate snapshots: periodic aggregates during training
CREATE TABLE IF NOT EXISTS win_rate_snapshots (
    snapshot_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL REFERENCES training_runs(run_id),
    timestep        INTEGER NOT NULL,
    episode_num     INTEGER NOT NULL,
    win_rate_100    REAL,               -- win rate over last 100 games
    win_rate_1000   REAL,               -- win rate over last 1000 games
    avg_game_length REAL,
    avg_reward      REAL,
    timestamp       TEXT NOT NULL
);

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_game_results_run ON game_results(run_id);
CREATE INDEX IF NOT EXISTS idx_game_results_winner ON game_results(winner);
CREATE INDEX IF NOT EXISTS idx_win_rate_run ON win_rate_snapshots(run_id, timestep);
CREATE INDEX IF NOT EXISTS idx_card_actions_game ON card_actions(game_id);
```

### Anti-Patterns to Avoid

- **Training without action masking:** MaskablePPO MUST detect `action_masks()` on the env. If the SelfPlayEnv wrapper strips it, training will silently use unmasked PPO and waste compute on illegal actions.
- **Always-latest opponent:** Using only the current policy as opponent causes strategy cycling (Pitfall 5). Always use a checkpoint pool with historical sampling.
- **Non-potential-based shaping:** Adding raw intermediate rewards (e.g., +0.1 per damage dealt) changes the optimal policy. Only use the F(s,s') = gamma*Phi(s') - Phi(s) formulation (D-06).
- **Writing to SQLite per step:** Buffered batch writes only. Writing per game step creates massive I/O overhead and bloated databases.
- **Storing full game trajectories for all games:** Store per-game summaries always; store full trajectories only for selected games (e.g., interesting wins, close games).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PPO algorithm | Custom PPO | `MaskablePPO` from sb3-contrib | 1000s of lines of validated code; handles GAE, clipping, masking |
| Training loop | Custom train loop | `model.learn(total_timesteps=N, callback=...)` | SB3 handles rollout collection, advantage estimation, gradient updates |
| TensorBoard logging | Custom metric writer | `tensorboard_log="path"` kwarg on model | SB3 logs reward, loss, episode length automatically |
| Checkpoint saving | Custom serialization | `model.save()` / `MaskablePPO.load()` | Handles PyTorch state dict + hyperparameters + normalizer state |
| Action masking | Manual probability zeroing | `action_masks()` method on env | MaskablePPO uses it automatically during rollout collection |

**Key insight:** SB3's callback system (`BaseCallback`, `CheckpointCallback`, `EvalCallback`) provides all hooks needed for self-play pool management. Do not bypass `model.learn()` with a custom training loop.

## Common Pitfalls

### Pitfall 1: SelfPlayEnv Strips action_masks()
**What goes wrong:** The wrapper around GridTacticsEnv does not expose `action_masks()`, so MaskablePPO silently falls back to standard PPO without masking.
**Why it happens:** `gymnasium.Wrapper` does not automatically delegate custom methods.
**How to avoid:** Explicitly define `action_masks()` on SelfPlayEnv that delegates to `self.env.action_masks()`.
**Warning signs:** Training loss spikes erratically; agent attempts impossible actions.

### Pitfall 2: Self-Play Strategy Cycling
**What goes wrong:** Agent learns rock-paper-scissors cycling: strategy A beats B, B beats C, C beats A. Win rate oscillates without improvement.
**Why it happens:** Training against only the latest opponent creates non-stationary distribution.
**How to avoid:** Maintain checkpoint pool of 10+ historical models. Sample opponent: 50% latest, 50% random from pool. Track win rate against FIXED baselines (random agent).
**Warning signs:** Win rate against random baseline drops; training reward oscillates periodically.

### Pitfall 3: Reward Shaping Dominates Sparse Signal
**What goes wrong:** Agent maximizes potential-based bonus (e.g., board control) but loses games because it never sacrifices minions for damage.
**Why it happens:** Potential function weights too large relative to terminal +1/-1 signal.
**How to avoid:** Keep potential function output in [-0.1, 0.1] range so terminal reward dominates. Test: remove shaping and verify agent still wins above random.
**Warning signs:** High shaped reward but low win rate; agent avoids terminal actions.

### Pitfall 4: PyTorch Installation Fails on Windows
**What goes wrong:** `pip install stable-baselines3[extra]` fails or installs CPU-only PyTorch.
**Why it happens:** PyTorch has platform-specific wheels; Windows may need CUDA toolkit separately.
**How to avoid:** Install CPU-only PyTorch explicitly if no GPU: `pip install torch --index-url https://download.pytorch.org/whl/cpu` before SB3. Or accept the default (which includes CUDA on most systems).
**Warning signs:** ImportError on torch; extremely slow training (CPU is fine for this project's scale).

### Pitfall 5: SQLite Write Contention Under Future Parallelization
**What goes wrong:** When Phase 7 adds vectorized envs, multiple processes writing to SQLite simultaneously causes lock contention.
**Why it happens:** SQLite uses file-level locking.
**How to avoid:** Use WAL mode (`PRAGMA journal_mode=WAL`). Buffer writes: accumulate N game results in memory, batch-insert.
**Warning signs:** `sqlite3.OperationalError: database is locked`.

### Pitfall 6: Game Results Don't Match Training Agent's Perspective
**What goes wrong:** Winner field in game_results stores the player index (0 or 1), but the training agent alternates between player 0 and player 1 across episodes. Dashboard shows misleading 50/50 win rates.
**Why it happens:** SelfPlayEnv may randomly assign training agent to either side.
**How to avoid:** Always record which player index the TRAINING agent was, alongside the winner. Add `training_player` column to game_results.

## Code Examples

### Example 1: Minimal MaskablePPO Training (Validation)

```python
"""Minimal training script to validate the pipeline end-to-end."""
from pathlib import Path
from sb3_contrib import MaskablePPO
from grid_tactics.card_library import CardLibrary
from grid_tactics.rl.env import GridTacticsEnv

DATA_DIR = Path("data/cards")
library = CardLibrary.from_directory(DATA_DIR)

# Build a standard deck
deck = library.build_deck({
    "fire_imp": 3, "shadow_stalker": 3, "dark_assassin": 3,
    "light_cleric": 3, "wind_archer": 3, "dark_sentinel": 3,
    "holy_paladin": 3, "holy_light": 3, "dark_drain": 3,
    "iron_guardian": 3, "fireball": 3, "shield_block": 3,
    "shadow_knight": 3, "stone_golem": 1,
})

env = GridTacticsEnv(library=library, deck_p1=deck, deck_p2=deck, seed=42)

# MaskablePPO detects action_masks() method automatically
model = MaskablePPO("MlpPolicy", env, verbose=1, tensorboard_log="data/tb_logs")
model.learn(total_timesteps=10_000)
model.save("data/checkpoints/initial_test")
```

### Example 2: Evaluating Agent vs Random

```python
"""Evaluate trained agent against random opponent."""
import numpy as np
from sb3_contrib import MaskablePPO

def evaluate_vs_random(model, env, n_games=100):
    wins = 0
    for i in range(n_games):
        obs, info = env.reset(seed=1000 + i)
        done = False
        while not done:
            mask = info["action_mask"]
            # Training agent acts
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(int(action))
            done = terminated or truncated

            if done:
                if reward > 0:
                    wins += 1
                break

            # Random opponent acts
            mask = info["action_mask"]
            legal = np.where(mask)[0]
            action = int(np.random.choice(legal))
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            if done and reward < 0:  # opponent won, training agent lost
                pass  # don't count as win

    return wins / n_games
```

### Example 3: SQLite Writer with Batch Insert

```python
"""Buffered SQLite writer for game results."""
import sqlite3
import json
from datetime import datetime, timezone

class GameResultWriter:
    def __init__(self, db_path, buffer_size=100):
        self.db_path = db_path
        self.buffer_size = buffer_size
        self._buffer = []
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            # Execute schema creation SQL here

    def record_game(self, run_id, episode_num, seed, winner,
                    turn_count, p1_hp, p2_hp, **kwargs):
        self._buffer.append({
            "run_id": run_id,
            "episode_num": episode_num,
            "seed": seed,
            "winner": winner,
            "turn_count": turn_count,
            "p1_final_hp": p1_hp,
            "p2_final_hp": p2_hp,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        })
        if len(self._buffer) >= self.buffer_size:
            self.flush()

    def flush(self):
        if not self._buffer:
            return
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                """INSERT INTO game_results
                   (run_id, episode_num, seed, winner, turn_count,
                    p1_final_hp, p2_final_hp, timestamp)
                   VALUES (:run_id, :episode_num, :seed, :winner,
                           :turn_count, :p1_final_hp, :p2_final_hp, :timestamp)""",
                self._buffer,
            )
        self._buffer.clear()
```

## MaskablePPO API Details

### How Action Masks Work with GridTacticsEnv

GridTacticsEnv already implements `action_masks()` (returns `np.ndarray` of shape `(1262,)` with dtype `bool_`). MaskablePPO detects this method automatically when `use_masking=True` (default). No `ActionMasker` wrapper is needed because the method is defined directly on the env.

**Critical:** The SelfPlayEnv wrapper MUST delegate `action_masks()`:
```python
def action_masks(self):
    return self.env.action_masks()
```

### MaskablePPO Key Parameters

| Parameter | Recommended | Why |
|-----------|-------------|-----|
| `policy` | `"MlpPolicy"` | Flat 292-dim obs; MLP is sufficient for initial training |
| `learning_rate` | `3e-4` | SB3 default; well-tested starting point |
| `n_steps` | `2048` | Collect 2048 steps per rollout; good balance of variance/efficiency |
| `batch_size` | `64` | Standard mini-batch size for PPO |
| `n_epochs` | `10` | Number of optimization epochs per rollout |
| `gamma` | `0.99` | Standard discount factor |
| `ent_coef` | `0.01` | Small entropy bonus encourages exploration of action space |
| `tensorboard_log` | `"data/tb_logs"` | Automatic metric logging |
| `seed` | `42` | Reproducibility |

### Predict with Masks (for evaluation and opponent play)

```python
action, _states = model.predict(
    observation,
    action_masks=mask_array,  # np.ndarray, shape (1262,), bool
    deterministic=True,       # True for evaluation, False for training opponent
)
```

## Self-Play Design

### Recommended: Frozen Opponent from Pool

**Phase 6 scope:** Start simple, evolve to pool.

1. **Plan 1 (basic):** Train vs random opponent. Validate MaskablePPO learns anything.
2. **Plan 2 (self-play):** Train vs frozen copy of current policy. Add SelfPlayEnv wrapper.
3. **Plan 3 (pool):** Add checkpoint pool with historical sampling. Periodic evaluation vs random baseline.

### Opponent Pool Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Pool size | 10 | Keep last 10 checkpoints; enough diversity without excessive disk usage |
| Save frequency | Every 10,000 timesteps | ~5 games worth of experience per checkpoint |
| Latest ratio | 0.5 | 50% latest, 50% random historical -- balances stability and diversity |
| Evaluation frequency | Every 20,000 timesteps | Evaluate vs random baseline; track absolute strength |
| Win threshold for pool | 0.55 | Only save to pool if win rate > 55% vs current pool (prevents adding weak checkpoints) |

### Game Counting

In the single-agent SelfPlayEnv pattern, each `env.reset()` to `terminated/truncated` constitutes ONE game played by the training agent. The opponent's moves happen inside `env.step()` (auto-stepped by wrapper). To count games, increment a counter in the wrapper's `reset()` method and use SB3 callbacks to log it.

## Potential-Based Reward Shaping Details

### Mathematical Foundation

For MDP M with reward R, the shaped MDP M' with reward R' = R + F is:
- F(s, s') = gamma * Phi(s') - Phi(s)
- Where Phi: S -> R is the potential function

**Guarantee:** The optimal policy in M' is identical to the optimal policy in M (Ng et al., 1999).

### Potential Function Components

| Component | Formula | Weight | Signal |
|-----------|---------|--------|--------|
| HP advantage | `(my_hp - opp_hp) / 40.0` | 0.3 | Damage dealt/received |
| Board control | `(my_minions - opp_minions) / 10.0` | 0.3 | Unit advantage |
| Mana efficiency | `my_mana / 10.0` | 0.2 | Resource management |
| Positional advance | `avg_row_progress / 4.0` | 0.2 | Progress toward sacrifice |

**Scale target:** Total potential output in [-1.0, 1.0] range. With gamma=0.99, the shaped reward per step will be in [-0.1, 0.1], keeping terminal +1/-1 dominant.

### Implementation Note

The SelfPlayEnv wrapper must store `prev_state` before each `env.step()` call to compute the potential difference. The existing `compute_reward()` in `reward.py` should be extended (not replaced) -- add a `compute_shaped_reward()` function alongside.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Penalty for invalid actions | Action masking (MaskablePPO) | 2021+ (sb3-contrib) | 10x faster convergence, no wasted samples on illegal actions |
| Always-latest opponent | Checkpoint pool / league training | AlphaStar (2019) | Prevents strategy cycling, more robust agents |
| Dense reward engineering | Potential-based shaping | Ng et al. (1999), applied broadly by 2020 | Preserves optimal policy while accelerating learning |
| Custom training loops | SB3 `model.learn()` with callbacks | SB3 1.0+ (2021) | Reliable, well-tested, less bug surface |

## Open Questions

1. **Training duration for beating random**
   - What we know: PettingZoo Connect Four example uses 20,480 timesteps. Grid Tactics is significantly more complex (1262 actions vs ~7, 292-dim obs vs ~84).
   - What's unclear: How many timesteps needed for basic strategy emergence.
   - Recommendation: Start with 100K timesteps, monitor TensorBoard. If no improvement by 500K, investigate reward signal / env bugs.

2. **MLP vs CNN for board spatial patterns**
   - What we know: Architecture research recommends CNN for spatial reasoning. But obs is flat 292-dim, and 5x5 is very small.
   - What's unclear: Whether MLP can learn positional play (tank-in-front-of-ranged).
   - Recommendation: MLP first (Phase 6). If agent shows no spatial strategy, add CNN feature extractor in Phase 7 or 8.

3. **Random agents cannot produce natural wins**
   - What we know: Phase 5 documented that random play almost never achieves sacrifice (crossing 5 rows). Games end by turn limit.
   - What's unclear: Whether MaskablePPO will discover sacrifice strategy from sparse rewards alone.
   - Recommendation: Potential-based shaping with positional advancement component directly incentivizes moving toward opponent's back row.

4. **SelfPlayEnv observation perspective**
   - What we know: GridTacticsEnv already alternates perspective -- observation is always from the active player's view.
   - What's unclear: In SelfPlayEnv where the training agent is always player 0, does the observation correctly flip when it's the training agent's turn after opponent auto-step?
   - Recommendation: Write explicit unit test: verify obs[my_resources] matches player 0's state after opponent auto-step.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime | Yes | 3.12.10 | -- |
| numpy | All RL code | Yes | 2.4.4 | -- |
| gymnasium | Environment API | Yes | 1.2.3 | -- |
| stable-baselines3 | MaskablePPO training | **No** | -- | Must install |
| sb3-contrib | MaskablePPO | **No** | -- | Must install |
| torch | Neural network | **No** | -- | Pulled by SB3 |
| tensorboard | Metric logging | **No** | -- | Pulled by SB3[extra] |
| sqlite3 | Data persistence | Yes | stdlib | -- |

**Missing dependencies with no fallback:**
- stable-baselines3, sb3-contrib, torch -- MUST be installed before any training can occur. First task in the plan.

**Missing dependencies with fallback:**
- None -- all missing items are required.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `pytest tests/ -x --timeout=30` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RL-04 | MaskablePPO trains without errors for N steps | integration | `pytest tests/test_training.py::test_maskable_ppo_trains -x` | Wave 0 |
| RL-04 | Model save/load roundtrip | unit | `pytest tests/test_training.py::test_model_save_load -x` | Wave 0 |
| RL-05 | SelfPlayEnv wrapper delegates action_masks() | unit | `pytest tests/test_self_play.py::test_action_masks_delegated -x` | Wave 0 |
| RL-05 | Self-play wrapper auto-steps opponent turns | integration | `pytest tests/test_self_play.py::test_opponent_auto_step -x` | Wave 0 |
| RL-05 | Checkpoint pool save/load/sample | unit | `pytest tests/test_checkpoint_manager.py -x` | Wave 0 |
| RL-06 | Potential function returns values in expected range | unit | `pytest tests/test_reward.py::test_potential_range -x` | Wave 0 |
| RL-06 | Shaped reward = base + gamma*Phi(s') - Phi(s) | unit | `pytest tests/test_reward.py::test_shaped_reward_formula -x` | Wave 0 |
| RL-06 | Shaped reward is zero-sum at terminal states | unit | `pytest tests/test_reward.py::test_terminal_shaping -x` | Wave 0 |
| DATA-01 | SQLite schema creation without errors | unit | `pytest tests/test_db.py::test_schema_creation -x` | Wave 0 |
| DATA-01 | Game result write and read roundtrip | unit | `pytest tests/test_db.py::test_game_result_roundtrip -x` | Wave 0 |
| DATA-01 | Batch insert flushes correctly | unit | `pytest tests/test_db.py::test_batch_flush -x` | Wave 0 |
| DATA-02 | Training metadata write and query | unit | `pytest tests/test_db.py::test_training_metadata -x` | Wave 0 |
| DATA-02 | Win rate snapshot recording | unit | `pytest tests/test_db.py::test_win_rate_snapshot -x` | Wave 0 |
| D-03 | Trained agent beats random >60% (smoke) | integration | `pytest tests/test_training.py::test_beats_random -x --timeout=300` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x --timeout=60 -q`
- **Per wave merge:** `pytest tests/ -v --timeout=300`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_training.py` -- covers RL-04 (MaskablePPO trains, model save/load, beats random)
- [ ] `tests/test_self_play.py` -- covers RL-05 (SelfPlayEnv wrapper, opponent auto-step, mask delegation)
- [ ] `tests/test_checkpoint_manager.py` -- covers RL-05 (checkpoint pool save/load/sample)
- [ ] `tests/test_reward.py` -- extend existing file for RL-06 (potential function, shaped reward formula)
- [ ] `tests/test_db.py` -- covers DATA-01, DATA-02 (schema, write, read, batch, metadata)
- [ ] Framework install: `pip install "stable-baselines3[extra]>=2.8,<3.0" "sb3-contrib>=2.8,<3.0"` -- required before training tests

## Sources

### Primary (HIGH confidence)
- [sb3-contrib MaskablePPO docs](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) -- API, parameters, action mask detection
- [PettingZoo SB3 Connect Four tutorial](https://pettingzoo.farama.org/tutorials/sb3/connect_four/) -- Self-play wrapper pattern, SB3ActionMaskWrapper
- [SB3 Custom Policy Networks](https://stable-baselines3.readthedocs.io/en/master/guide/custom_policy.html) -- BaseFeaturesExtractor, policy_kwargs
- [SB3 Callbacks](https://stable-baselines3.readthedocs.io/en/master/guide/callbacks.html) -- CheckpointCallback, BaseCallback for self-play
- Existing codebase: `src/grid_tactics/rl/env.py`, `observation.py`, `action_space.py`, `reward.py` -- Phase 5 completed RL environment

### Secondary (MEDIUM confidence)
- [Hugging Face Deep RL Course: Self-Play](https://huggingface.co/learn/deep-rl-course/unit7/self-play) -- Opponent pool parameters, training loop structure
- [Potential-Based Reward Shaping](https://gibberblot.github.io/rl-notes/single-agent/reward-shaping.html) -- F(s,s') = gamma*Phi(s') - Phi(s) formulation
- [Mastering Reinforcement Learning - Reward Shaping](https://medium.com/@sophiezhao_2990/potential-based-reward-shaping-in-reinforcement-learning-05da05cfb84a) -- Implementation guidance
- [sb3-contrib source: ppo_mask.py](https://github.com/Stable-Baselines-Team/stable-baselines3-contrib/blob/master/sb3_contrib/ppo_mask/ppo_mask.py) -- action mask retrieval internals

### Tertiary (LOW confidence)
- Training duration estimates (100K-500K timesteps) -- extrapolated from Connect Four example, not verified for this game's complexity

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- SB3/sb3-contrib versions verified on PyPI; env already compatible
- Architecture: HIGH -- patterns derived from official tutorials + existing codebase analysis
- Self-play: MEDIUM -- PettingZoo example is simple; opponent pool is custom but follows established patterns
- Reward shaping: HIGH -- mathematical formulation well-established; implementation is straightforward
- SQLite schema: MEDIUM -- custom design for this project; dashboard requirements inferred from REQUIREMENTS.md
- Pitfalls: HIGH -- documented in project's PITFALLS.md and verified against official docs

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable domain; SB3 API unlikely to change within 30 days)
