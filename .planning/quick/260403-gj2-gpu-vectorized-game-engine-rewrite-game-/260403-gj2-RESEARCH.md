# GPU-Vectorized Game Engine - Research

**Researched:** 2026-04-03
**Domain:** GPU-accelerated game simulation, PyTorch tensor operations, RL training throughput
**Confidence:** MEDIUM-HIGH

## Summary

The Grid Tactics game engine currently runs at ~4,000 FPS per single environment (measured on the dev machine). The goal is to vectorize the engine so thousands of games run in parallel on GPU, targeting 50,000-100,000+ total FPS. This research evaluates three architectural approaches: (A) pure PyTorch tensor engine with `torch.compile`, (B) JAX-based rewrite following Pgx patterns, and (C) CPU-optimized C extension with PufferLib vectorization.

**The project uses SB3/MaskablePPO (locked decision in CLAUDE.md).** This constrains the approach significantly: JAX-native engines (Pgx, PureJaxRL) require a JAX training loop and cannot feed MaskablePPO directly. The recommended approach is a **pure PyTorch batched tensor engine** that implements the game logic entirely as tensor operations on GPU, wrapped in a custom VecEnv that provides the `action_masks()` interface MaskablePPO expects.

**Primary recommendation:** Write a new `TensorGameEngine` module that represents the full game state as a batch of PyTorch tensors (shape `[N, ...]`), implements `step()` and `legal_action_mask()` as pure tensor operations, then wrap it in a `TensorVecEnv` compatible with SB3's VecEnv API. Use `torch.compile` for kernel fusion. Target batch size 1024-4096 on the RTX 4060 Laptop (8 GB VRAM).

## Project Constraints (from CLAUDE.md)

- **Language:** Python for game engine and RL
- **RL framework:** SB3 with MaskablePPO (locked -- no switch to JAX/PureJaxRL)
- **Card data:** JSON-driven card definitions (data/cards/*.json)
- **Game rules:** 5x5 grid, action-per-turn, mana banking, react window, sacrifice-to-damage
- **Testing:** pytest for game rules, coverage required
- **Dependencies:** PyTorch 2.6+ (installed), NumPy 2.x, Gymnasium 1.2

## Current Engine Analysis

### Measured Performance
| Metric | Value |
|--------|-------|
| Single env FPS | ~4,000 steps/sec |
| DummyVecEnv(1) FPS | ~3,700 steps/sec |
| SubprocVecEnv(n) | ~190 FPS (per cloud training logs -- IPC overhead dominates) |
| Observation size | 292 float32 |
| Action space | Discrete(1262) |
| Avg game length | ~200 turns (with turn limit 500) |

### Bottleneck Analysis
The current engine is not slow per-se on a single core. The bottleneck is **parallelism**: SB3's SubprocVecEnv serializes Python objects across processes, which is catastrophically slow for small fast environments. DummyVecEnv runs sequentially. Neither approach uses GPU for game logic.

### Current State Size
Each game tracks:
- Board: 25 cells (Optional[int])
- Players x2: HP, mana, max_mana, hand (up to ~35 cards), deck (up to 40), graveyard
- Minions: variable count (up to ~25 on a 5x5 grid), each with 6 fields
- React state: stack (up to 10 entries), pending action, react_player_idx
- Game metadata: turn, phase, active player, winner, is_game_over

## Architecture Approaches Evaluated

### Approach A: Pure PyTorch Tensor Engine (RECOMMENDED)

**What:** Rewrite all game logic as batched PyTorch tensor operations. Game state is a collection of tensors with leading batch dimension N. All branching replaced with `torch.where()`, `torch.scatter()`, and masked operations.

**Why recommended:**
1. Stays in PyTorch ecosystem (SB3 compatibility preserved)
2. `torch.compile` fuses operations into optimized CUDA kernels
3. No framework switch (JAX would require rewriting the training loop)
4. Observations and action masks are already tensors -- zero-copy to SB3

**Expected performance:** 20,000-80,000 FPS with batch sizes 1024-4096 on RTX 4060 Laptop. Larger GPUs (A100, RTX 4090) would reach 100,000+ FPS. These estimates are based on:
- Pgx achieves 100,000+ steps/sec for chess-complexity games on A100
- Grid Tactics is simpler than chess (5x5 grid, ~20 piece types vs 64 cells, 12 types)
- RTX 4060 Laptop has ~45% the CUDA cores of A100 but similar tensor core efficiency for int/float32

**Risk:** MEDIUM. Tensor-ifying the react stack (LIFO resolution with NEGATE chaining) is architecturally complex. Must be done carefully to avoid correctness bugs.

### Approach B: JAX/Pgx-Style Rewrite

**What:** Port the game engine to JAX using `jax.vmap` for auto-vectorization, following Pgx's architectural patterns.

**Why not recommended:**
1. SB3/MaskablePPO is PyTorch-only -- would need a bridge layer that negates speed gains
2. JAX's functional paradigm requires complete rewrite (no incremental migration)
3. Adds JAX as a dependency (CUDA compatibility issues with PyTorch co-installation)
4. Team has no JAX experience (based on codebase)

**Performance:** Would be 2-5x faster than PyTorch equivalent due to XLA compilation, but the SB3 integration overhead would eat most gains.

### Approach C: C/Cython Extension + PufferLib

**What:** Rewrite game engine in C/Cython for raw CPU speed, use PufferLib for optimized CPU vectorization with asynchronous stepping.

**Why not recommended:**
1. C code loses the rapid iteration capability Python provides (critical for card balance iteration)
2. PufferLib is CPU-bound -- still limited by CPU parallelism, not GPU throughput
3. Significant maintenance burden for a project in active game design iteration
4. PufferLib's SB3 integration is a wrapper, not native -- adds complexity

**Performance:** 100,000-500,000 FPS on CPU (PufferLib's stated range for pure Python envs), but ceiling is lower than GPU approach.

## Recommended Architecture: PyTorch Tensor Engine

### Tensor State Representation

All game state encoded as fixed-size tensors with batch dimension `N`:

```python
@dataclass
class TensorGameState:
    """All game state as batched GPU tensors. Shape [N, ...] where N = batch_size."""

    # Board: which minion occupies each cell (-1 = empty, else slot index)
    board: torch.Tensor           # [N, 5, 5] int16

    # Player state
    player_hp: torch.Tensor       # [N, 2] int16
    player_mana: torch.Tensor     # [N, 2] int16
    player_max_mana: torch.Tensor # [N, 2] int16

    # Hands: fixed-size padded. Card numeric ID per slot, -1 = empty.
    hands: torch.Tensor           # [N, 2, MAX_HAND] int16
    hand_sizes: torch.Tensor      # [N, 2] int8

    # Decks: fixed-size padded (deck_size = 40, no more after start)
    decks: torch.Tensor           # [N, 2, MAX_DECK] int16
    deck_sizes: torch.Tensor      # [N, 2] int8
    deck_tops: torch.Tensor       # [N, 2] int8  (index of next card to draw)

    # Graveyards: fixed-size padded
    graveyards: torch.Tensor      # [N, 2, MAX_GRAVEYARD] int16
    graveyard_sizes: torch.Tensor # [N, 2] int8

    # Minion slots: fixed max minions on board (25 max for 5x5 grid)
    minion_card_id: torch.Tensor  # [N, MAX_MINIONS] int16
    minion_owner: torch.Tensor    # [N, MAX_MINIONS] int8   (0/1 or -1=empty)
    minion_row: torch.Tensor      # [N, MAX_MINIONS] int8
    minion_col: torch.Tensor      # [N, MAX_MINIONS] int8
    minion_health: torch.Tensor   # [N, MAX_MINIONS] int8
    minion_atk_bonus: torch.Tensor # [N, MAX_MINIONS] int8
    minion_alive: torch.Tensor    # [N, MAX_MINIONS] bool
    num_minions: torch.Tensor     # [N] int8

    # Turn state
    active_player: torch.Tensor   # [N] int8  (0 or 1)
    phase: torch.Tensor           # [N] int8  (0=ACTION, 1=REACT)
    turn_number: torch.Tensor     # [N] int16
    is_game_over: torch.Tensor    # [N] bool
    winner: torch.Tensor          # [N] int8  (-1=none, 0=p1, 1=p2)

    # React state
    react_player: torch.Tensor    # [N] int8
    react_stack_depth: torch.Tensor  # [N] int8
    react_stack: torch.Tensor     # [N, MAX_REACT_DEPTH, 4] int16
    pending_action_type: torch.Tensor  # [N] int8
```

### Card Definition Table (Static, Shared)

Card definitions stored as a single lookup tensor on GPU:

```python
class CardTable:
    """Static card property lookup table on GPU. Shape [NUM_CARDS, NUM_PROPERTIES]."""

    # Properties per card (indexed by card_numeric_id):
    card_type: torch.Tensor     # [NUM_CARDS] int8  (0=minion,1=magic,2=react)
    mana_cost: torch.Tensor     # [NUM_CARDS] int8
    attack: torch.Tensor        # [NUM_CARDS] int8  (0 for non-minion)
    health: torch.Tensor        # [NUM_CARDS] int8  (0 for non-minion)
    attack_range: torch.Tensor  # [NUM_CARDS] int8  (0 for non-minion)
    attribute: torch.Tensor     # [NUM_CARDS] int8

    # Effect table: up to MAX_EFFECTS_PER_CARD effects per card
    effect_type: torch.Tensor     # [NUM_CARDS, MAX_EFFECTS] int8
    effect_trigger: torch.Tensor  # [NUM_CARDS, MAX_EFFECTS] int8
    effect_target: torch.Tensor   # [NUM_CARDS, MAX_EFFECTS] int8
    effect_amount: torch.Tensor   # [NUM_CARDS, MAX_EFFECTS] int8
    num_effects: torch.Tensor     # [NUM_CARDS] int8

    # React properties
    react_condition: torch.Tensor    # [NUM_CARDS] int8
    react_effect_type: torch.Tensor  # [NUM_CARDS] int8
    react_mana_cost: torch.Tensor    # [NUM_CARDS] int8
    is_multi_purpose: torch.Tensor   # [NUM_CARDS] bool
```

**Key insight for thousands of cards:** Adding new cards is just adding rows to the CardTable tensors. No code changes needed. The engine indexes into these tables using `card_numeric_id` via `torch.gather` / `torch.index_select`. This is O(1) regardless of card count.

### Branchless Game Logic Pattern

All conditional logic must be replaced with tensor operations. Example patterns:

```python
# PATTERN: Conditional update (if condition then update, else keep)
# Python: if player.mana >= cost: player.mana -= cost
new_mana = state.player_mana[batch, player] - cost
can_afford = state.player_mana[batch, player] >= cost
state.player_mana[batch, player] = torch.where(can_afford, new_mana, state.player_mana[batch, player])

# PATTERN: Masked scatter (apply effect to targets matching a condition)
# Python: for minion in minions: if minion.owner != caster_owner: minion.health -= damage
is_enemy = state.minion_owner != caster_owner.unsqueeze(-1)  # [N, MAX_MINIONS]
is_alive = state.minion_alive                                 # [N, MAX_MINIONS]
targets = is_enemy & is_alive                                  # [N, MAX_MINIONS]
state.minion_health = state.minion_health - damage.unsqueeze(-1) * targets.int()

# PATTERN: Board lookup (find minion at position)
# Use the board tensor as an index: board[row][col] = minion_slot_index
# Then index into minion arrays: minion_health[board[row][col]]

# PATTERN: Action dispatch (different logic per action type)
# Instead of if/elif chain, compute ALL action results, then select via action_type mask
result_play = _apply_play_card_batch(state, actions, card_table)
result_move = _apply_move_batch(state, actions)
result_attack = _apply_attack_batch(state, actions, card_table)
result_draw = _apply_draw_batch(state)
# ... then merge using torch.where based on action_type
is_play = (actions.action_type == ActionType.PLAY_CARD)
state = torch_where_state(is_play, result_play, state)
# etc.
```

### Effect Resolution via Table Lookup

**This is the key modularity mechanism.** Effects are NOT hardcoded per card. Instead:

```python
def apply_effects_batch(
    state: TensorGameState,
    card_ids: torch.Tensor,       # [N] which card was played
    trigger: int,                  # TriggerType enum value
    caster_owners: torch.Tensor,  # [N] int8
    target_positions: torch.Tensor,  # [N, 2] row,col or -1,-1
    card_table: CardTable,
) -> TensorGameState:
    """Apply all effects of the given trigger for the given cards, batched."""

    for effect_idx in range(MAX_EFFECTS_PER_CARD):
        # Look up effect properties for each game in the batch
        etype = card_table.effect_type[card_ids, effect_idx]    # [N]
        etrigger = card_table.effect_trigger[card_ids, effect_idx]  # [N]
        etarget = card_table.effect_target[card_ids, effect_idx]  # [N]
        eamount = card_table.effect_amount[card_ids, effect_idx]  # [N]

        # Only apply if trigger matches and effect exists
        active = (etrigger == trigger) & (effect_idx < card_table.num_effects[card_ids])

        # Dispatch by effect type (all computed, selected via mask)
        state = _apply_damage_batch(state, active & (etype == EffectType.DAMAGE),
                                     etarget, eamount, caster_owners, target_positions)
        state = _apply_heal_batch(state, active & (etype == EffectType.HEAL),
                                   etarget, eamount, caster_owners, target_positions)
        state = _apply_buff_batch(state, active & (etype == EffectType.BUFF_ATTACK),
                                   etarget, eamount, caster_owners, target_positions)
        # ... etc

    return state
```

**Adding a new effect type** (e.g., `FREEZE`, `TELEPORT`) means:
1. Add the effect type to the enum
2. Add an `_apply_freeze_batch()` function
3. Add one more dispatch line in `apply_effects_batch()`
4. Define the effect in JSON card data

No changes to the core engine loop, state representation, or action system.

### React System Vectorization

The react stack is the hardest part to vectorize because it involves:
1. Turn alternation (who reacts changes per game)
2. LIFO stack resolution with NEGATE chaining
3. Variable stack depth across batch

**Recommended approach:** Model the react phase as a **fixed-iteration loop** with early masking:

```python
def resolve_react_stack_batch(state: TensorGameState, card_table: CardTable) -> TensorGameState:
    """Resolve react stacks across all games in batch."""

    for depth in range(MAX_REACT_DEPTH - 1, -1, -1):  # LIFO order
        # Only process games that have stack entries at this depth
        active = state.react_stack_depth > depth  # [N] bool

        # Check if this entry was negated by a prior resolution
        negated = ...  # tracked via a negation mask tensor

        should_resolve = active & ~negated

        # Look up card and resolve effects
        card_id = state.react_stack[arange_N, depth, 0]  # card_numeric_id
        # ... resolve effects using apply_effects_batch
        # ... handle NEGATE by marking next entry
```

This runs the same number of iterations for all games (MAX_REACT_DEPTH = 10), but masks out inactive games. With max depth of 10, this is at most 10 passes through the effect resolution -- acceptable overhead.

### SB3 Integration: TensorVecEnv

The vectorized engine wraps into SB3's VecEnv interface:

```python
class TensorVecEnv(VecEnv):
    """SB3-compatible VecEnv backed by GPU tensor game engine.

    All N environments step simultaneously in a single GPU kernel call.
    Observations and action masks are returned as numpy arrays (SB3 expects numpy).
    """

    def __init__(self, n_envs: int, card_table: CardTable, ...):
        self.n_envs = n_envs
        self.engine = TensorGameEngine(n_envs, card_table, device='cuda')
        # SB3 spaces
        self.observation_space = ...
        self.action_space = ...

    def step_wait(self) -> VecEnvStepReturn:
        # Apply all N actions simultaneously on GPU
        self.engine.step_batch(self._actions)
        # Encode observations (GPU tensor ops)
        obs = self.engine.encode_observations()  # [N, 292] on GPU
        masks = self.engine.legal_action_masks()  # [N, 1262] on GPU
        # Transfer to CPU for SB3 (unavoidable with current SB3 architecture)
        return obs.cpu().numpy(), rewards.cpu().numpy(), dones.cpu().numpy(), infos

    def env_method(self, method_name, *args, **kwargs):
        if method_name == 'action_masks':
            return [self.engine.legal_action_masks().cpu().numpy()]
```

**Critical SB3 constraint:** MaskablePPO expects `action_masks()` to return numpy arrays. The GPU-to-CPU transfer is unavoidable per step. However, this transfer is tiny (N * 1262 bools ~ 5 MB for N=4096) and overlaps with other computation.

### Proposed Project Structure

```
src/grid_tactics/
    tensor_engine/
        __init__.py
        state.py          # TensorGameState dataclass
        card_table.py      # CardTable from JSON definitions
        engine.py          # TensorGameEngine: step_batch, reset_batch
        actions.py         # Batched action application (play, move, attack, etc.)
        effects.py         # Batched effect resolution (damage, heal, buff)
        legal_actions.py   # Batched legal action mask computation
        react.py           # Batched react stack handling
        observation.py     # Batched observation encoding
        reward.py          # Batched reward computation
        vec_env.py         # TensorVecEnv (SB3 VecEnv wrapper)
        self_play.py       # TensorSelfPlayVecEnv (opponent policy integration)
    # ... existing code preserved for testing/validation
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| RNG for batch games | Custom PRNG | `torch.Generator` per-game or `torch.randint` with batch seeds | PyTorch's GPU RNG is hardware-optimized. Custom PRNG on GPU is slow. |
| Distance computation | Per-pair loops | `torch.cdist` or precomputed distance matrices | Manhattan/Chebyshev distance between all pairs is a single tensor op |
| Adjacency checking | Runtime computation | Precomputed adjacency tensor `[25, 25]` bool | Static 5x5 grid -- precompute once, index forever |
| Legal action enumeration | Per-game Python loops | Batch tensor mask computation | The entire legal action mask for N games is one kernel |
| Observation encoding | Per-game Python function | Batch gather/scatter on state tensors | Already tensors -- just reshape and normalize |

## Common Pitfalls

### Pitfall 1: Python Control Flow in Hot Path
**What goes wrong:** Using Python `if/else` or `for` loops over the batch dimension. GPU sits idle waiting for Python interpreter.
**Why it happens:** Natural to port existing Python logic line-by-line.
**How to avoid:** Every operation must be a tensor operation on the full batch. Use `torch.where()` for conditionals, `torch.scatter()` for conditional updates, and fixed-iteration loops with masks for variable-depth structures.
**Warning signs:** Profiler shows GPU utilization < 50%. FPS does not scale with batch size.

### Pitfall 2: Excessive GPU-CPU Round Trips
**What goes wrong:** Transferring tensors to CPU for each sub-step (e.g., checking game over, computing legal actions between action resolution and react).
**Why it happens:** Desire to reuse existing Python validation code.
**How to avoid:** Keep ALL game logic on GPU. Only transfer to CPU at the VecEnv boundary (observations, rewards, dones, action masks). One round trip per step(), not per sub-operation.
**Warning signs:** `torch.cuda.synchronize()` calls in the hot path. FPS bottlenecked by transfer.

### Pitfall 3: Dynamic Tensor Shapes
**What goes wrong:** Trying to use variable-length tensors for hands, decks, react stacks. PyTorch recompiles with `torch.compile` on shape changes.
**Why it happens:** Direct translation of Python tuples with variable lengths.
**How to avoid:** ALL tensors are fixed-size with padding and a separate size/count tensor. Hands are `[N, 2, MAX_HAND]` with `hand_sizes[N, 2]`. Decks are `[N, 2, MAX_DECK]` with `deck_tops[N, 2]`. Empty slots use sentinel values (-1 for card IDs, 0 for stats).
**Warning signs:** `torch.compile` recompilation warnings. Shapes change between calls.

### Pitfall 4: Correctness Regression
**What goes wrong:** Tensor engine produces different game outcomes than the Python engine. Bugs are hard to find because you can't step through 4096 games.
**Why it happens:** Subtle differences in effect resolution order, edge cases in react stacking, or off-by-one in tensor indexing.
**How to avoid:** Build a verification harness that runs both engines on the same inputs and compares outputs. Run thousands of games with random actions and assert state equivalence at every step. This is the most critical testing strategy.
**Warning signs:** Different win rates between Python and tensor engines. Assertion failures in the comparison harness.

### Pitfall 5: Memory Explosion at Large Batch Sizes
**What goes wrong:** Running out of VRAM with large batch sizes because intermediate tensors are not freed.
**Why it happens:** Each `torch.where()` creates a new tensor. Effect resolution creates many intermediates.
**How to avoid:** Use in-place operations where safe (`.masked_fill_()`, `[mask] = value`). Profile VRAM usage with `torch.cuda.memory_allocated()`. Start with batch size 1024 and scale up. The RTX 4060 Laptop has 8 GB -- budget ~2 GB for game state, ~4 GB for model + training buffers.
**Warning signs:** CUDA out-of-memory errors. VRAM usage grows linearly with operations per step.

### Pitfall 6: Auto-Reset Complexity
**What goes wrong:** Games finish at different times in the batch. Need to auto-reset finished games while keeping others running.
**Why it happens:** This is inherent to batched environments.
**How to avoid:** After every step, check `is_game_over` mask. For finished games, call `reset_games(mask)` which reinitializes only the masked subset of the state tensors. Use `torch.where(done_mask.unsqueeze(-1), initial_state, current_state)` for selective reset.

### Pitfall 7: Self-Play Opponent Integration
**What goes wrong:** Opponent turns require a model forward pass mid-step, breaking the pure-tensor pipeline.
**Why it happens:** SelfPlayEnv currently steps the opponent synchronously.
**How to avoid:** In the tensor engine, handle both players simultaneously. Each step advances the game by one action. The VecEnv reports to SB3 only when it's the training player's turn. Opponent actions are gathered by running the opponent model on the subset of games where it's the opponent's turn, then those actions are applied in the same batch step. This keeps everything on GPU.

## Performance Estimates

### Memory Budget (RTX 4060 Laptop, 8 GB VRAM)

| Component | Per Game (bytes) | N=1024 | N=4096 |
|-----------|-----------------|--------|--------|
| Board (5x5 int16) | 50 | 50 KB | 200 KB |
| Players (HP/mana/etc, 2 players) | 24 | 24 KB | 96 KB |
| Hands (2 x 10 int16) | 40 | 40 KB | 160 KB |
| Decks (2 x 40 int16) | 160 | 160 KB | 640 KB |
| Minions (25 slots x 8 bytes) | 200 | 200 KB | 800 KB |
| React state | 100 | 100 KB | 400 KB |
| Turn/phase/metadata | 20 | 20 KB | 80 KB |
| **Total state** | **~600** | **~600 KB** | **~2.4 MB** |
| Observation buffer (292 x float32) | 1,168 | 1.1 MB | 4.5 MB |
| Action mask buffer (1262 x bool) | 1,262 | 1.2 MB | 4.9 MB |
| Card table (18 cards, static) | ~500 | 500 B | 500 B |
| **Total GPU memory** | | **~3 MB** | **~12 MB** |

Game state memory is trivial. The model (MlpPolicy) uses ~10 MB. Training buffers (rollout, value targets) scale with n_steps * batch_size. With n_steps=512 and N=4096, rollout buffers need ~512 * 4096 * 292 * 4 = ~2.3 GB. **Total estimate: ~3-4 GB for N=4096.** Fits comfortably in 8 GB VRAM.

### FPS Estimates

| Configuration | Estimated FPS | Basis |
|---------------|--------------|-------|
| Current Python, single env | 4,000 | Measured |
| Tensor engine, N=1024, RTX 4060 | 30,000-60,000 | Conservative: Pgx-equivalent games on smaller GPU |
| Tensor engine, N=4096, RTX 4060 | 50,000-100,000 | GPU utilization improves with batch size |
| Tensor engine, N=4096, RTX 4090 | 100,000-200,000 | 2-3x the CUDA cores of 4060 Laptop |
| Tensor engine, N=8192, A100 | 200,000-500,000 | Pgx-class hardware, larger batch |

**Confidence: MEDIUM.** These are estimates based on Pgx benchmarks for similar-complexity games. Grid Tactics has more complex logic than Go (effects, react stack) but a smaller state space (5x5 vs 19x19). Actual performance depends heavily on how efficiently the tensor operations are fused by `torch.compile`.

### Cloud Training Impact

At 100,000 FPS (tensor engine on cloud GPU) vs current ~190 FPS (SubprocVecEnv):
- **500x speedup** in environment throughput
- A 10M step training run: from ~14.6 hours to ~1.7 minutes (env time only)
- Training will become **model-bound** (policy forward/backward pass) rather than env-bound
- This enables rapid hyperparameter sweeps, card balance testing, and meta-strategy discovery

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| CPU SubprocVecEnv | GPU-native tensor environments | 2023-2025 (Pgx, Brax, IsaacGym) | 100-1000x throughput |
| JAX-only GPU envs | PyTorch `torch.compile` + `vmap` | 2024-2025 | PyTorch now competitive for GPU envs |
| Per-env Python step | Batched tensor step on GPU | 2022-2024 | Eliminates Python overhead |
| PettingZoo AEC for multi-agent | Single-agent alternating + batch | Common pattern | Simpler integration with SB3 |

## Key Technical Decisions

### Decision 1: PyTorch over JAX
**Chosen:** PyTorch with `torch.compile`
**Rationale:** SB3/MaskablePPO is PyTorch-native. JAX would require either (a) a cross-framework bridge that eliminates speed gains, or (b) abandoning SB3 for a JAX RL library, which conflicts with the locked project decisions.
**Trade-off:** JAX would be ~2-5x faster for the env alone, but the integration cost makes it a net loss.

### Decision 2: Fixed-Size Padded Tensors
**Chosen:** All variable-length structures use fixed-size tensors with sentinel values and size counters.
**Rationale:** `torch.compile` requires static shapes. Dynamic shapes cause recompilation and prevent kernel fusion. The padding overhead is minimal (tens of KB per game).

### Decision 3: Branchless Effect Resolution via Table Lookup
**Chosen:** Card effects are a tensor lookup table, not Python polymorphism.
**Rationale:** Adding new cards = adding rows to the table. Adding new effect types = adding one dispatch function. This scales to thousands of cards with zero performance impact (table lookups are O(1) on GPU).

### Decision 4: Parallel Self-Play Integration
**Chosen:** Opponent actions computed in the same batch step, not a separate Python call.
**Rationale:** Moving between GPU and CPU for opponent actions would halve throughput. Instead, the VecEnv internally manages both players and only exposes the training player's turns to SB3.

### Decision 5: Verification Harness
**Chosen:** Build a parallel correctness checker that runs both engines.
**Rationale:** Game rule bugs in the tensor engine corrupt training silently. The existing Python engine is the ground truth. A comparison harness is essential for confidence.

## Implementation Phases (Suggested)

### Phase 1: Core State and Table (Days 1-2)
- `TensorGameState` dataclass with all fixed-size tensors
- `CardTable` loaded from JSON card definitions
- `reset_batch()` function to initialize N games
- Unit tests: state shapes, card table correctness

### Phase 2: Simple Actions (Days 3-5)
- `apply_pass_batch()`, `apply_draw_batch()`, `apply_move_batch()`
- Dead minion cleanup as tensor operations
- Turn advancement (mana regen, player swap)
- Verification: compare with Python engine on 1000 random games

### Phase 3: Complex Actions (Days 6-8)
- `apply_play_card_batch()` (minion deploy + magic casting)
- `apply_attack_batch()` (simultaneous damage)
- `apply_sacrifice_batch()`
- Effect resolution via table lookup
- Verification: compare on 10,000 random games

### Phase 4: React System (Days 9-11)
- React stack push/pop as tensor operations
- NEGATE chaining
- Stack resolution (LIFO) with batched effect application
- Verification: targeted react-heavy test scenarios

### Phase 5: Legal Action Mask (Days 12-13)
- Full legal action mask computation as tensor ops
- This is the most complex single function (1262-element mask per game)
- Verification: compare masks with Python engine for every state

### Phase 6: Observation and Reward (Day 14)
- Observation encoding as tensor ops (already nearly tensor-native)
- Reward computation (trivial in tensor form)
- `torch.compile` optimization of the full step

### Phase 7: VecEnv Integration (Days 15-16)
- `TensorVecEnv` implementing SB3's `VecEnv` API
- `TensorSelfPlayVecEnv` with opponent policy integration
- Auto-reset for finished games
- Integration test with MaskablePPO training

### Phase 8: Optimization (Days 17-18)
- Profile with `torch.profiler`
- Identify and eliminate GPU-CPU round trips
- Tune batch size for target GPU
- Performance benchmarking and comparison

## Open Questions

1. **`torch.compile` with complex control flow:**
   - What we know: `torch.compile` handles `torch.where` well but may struggle with the nested effect resolution loop
   - What's unclear: Whether the react stack resolution compiles efficiently
   - Recommendation: Implement first, then profile. Fall back to eager mode for the react subsystem if needed.

2. **Self-play opponent model on GPU:**
   - What we know: SB3 model inference can run on GPU
   - What's unclear: Whether running the opponent model mid-step causes synchronization issues with the batch
   - Recommendation: Profile both approaches -- (a) opponent as a separate forward pass, (b) combined batch with both player actions

3. **Deterministic RNG across batch:**
   - What we know: Current engine uses per-game `GameRNG` with numpy
   - What's unclear: How to maintain per-game deterministic sequences on GPU
   - Recommendation: Use `torch.Generator` per game or pre-generate random sequences as tensors

4. **Keeping the Python engine in sync:**
   - What we know: Card definitions and game rules must be identical
   - What's unclear: Whether the Python engine should be maintained as the "reference" or deprecated
   - Recommendation: Keep Python engine as reference/test oracle. Both read from the same JSON card definitions.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PyTorch | Tensor engine | Yes | 2.6.0+cu124 | -- |
| CUDA | GPU execution | Yes | 12.4 | CPU fallback (no speedup) |
| GPU | Parallel games | Yes | RTX 4060 Laptop, 8 GB | CPU-only mode |
| SB3 | Training loop | Yes | 2.8.x | -- |
| sb3-contrib | MaskablePPO | Yes | 2.8.x | -- |
| numpy | VecEnv interface | Yes | 2.x | -- |

**Missing dependencies:** None. All required tools are available.

**Note:** PyTorch 2.6 supports `torch.compile`. Upgrading to 2.10+ would provide better `torch.compile` performance and `vmap` improvements, but is not strictly required.

## Code Examples

### Batched Move Action
```python
# Source: Derived from architectural analysis of current engine
def apply_move_batch(
    state: TensorGameState,
    action_mask: torch.Tensor,  # [N] bool -- which games are doing MOVE
    source_flat: torch.Tensor,  # [N] int -- source position (0-24)
    direction: torch.Tensor,    # [N] int -- 0=up,1=down,2=left,3=right
) -> TensorGameState:
    """Apply MOVE action to all games where action_mask is True."""
    # Direction deltas: [4, 2] tensor
    deltas = torch.tensor([[-1,0],[1,0],[0,-1],[0,1]], device=state.board.device)
    dr = deltas[direction, 0]  # [N]
    dc = deltas[direction, 1]  # [N]

    src_row = source_flat // 5  # [N]
    src_col = source_flat % 5   # [N]
    dst_row = src_row + dr      # [N]
    dst_col = src_col + dc      # [N]

    # Find minion at source in the board tensor
    src_minion = state.board[torch.arange(N), src_row, src_col]  # [N] minion slot index

    # Clear source, set destination (only for active games)
    new_board = state.board.clone()
    active = action_mask
    new_board[torch.arange(N)[active], src_row[active], src_col[active]] = -1
    new_board[torch.arange(N)[active], dst_row[active], dst_col[active]] = src_minion[active]

    # Update minion position in minion arrays
    # ... (scatter update using src_minion as index into minion_row/minion_col)

    return replace(state, board=new_board, ...)
```

### Batched Legal Action Mask (Sketch)
```python
def compute_legal_action_mask_batch(
    state: TensorGameState,
    card_table: CardTable,
) -> torch.Tensor:
    """Compute [N, 1262] bool legal action mask for all games."""
    N = state.board.shape[0]
    mask = torch.zeros(N, 1262, dtype=torch.bool, device=state.board.device)

    # PASS is always legal (index 1001)
    # (except during ACTION phase per current rules -- only legal via react/draw)
    # ... Actually current engine: PASS is NOT legal in ACTION phase.
    # Only legal in REACT phase.
    is_react = state.phase == 1
    mask[:, 1001] = is_react

    # DRAW: legal if deck is non-empty and in ACTION phase
    is_action = state.phase == 0
    active_p = state.active_player  # [N]
    has_deck = state.deck_sizes[torch.arange(N), active_p] > state.deck_tops[torch.arange(N), active_p]
    mask[:, 1000] = is_action & has_deck

    # PLAY_CARD: for each hand slot, check card type, mana, deploy positions
    # This is the most complex part -- requires iterating over hand slots
    for hand_idx in range(MAX_HAND_SIZE):
        card_id = state.hands[torch.arange(N), active_p, hand_idx]  # [N]
        has_card = card_id >= 0  # [N]
        cost = card_table.mana_cost[card_id.clamp(min=0)]  # [N]
        can_afford = state.player_mana[torch.arange(N), active_p] >= cost
        is_minion = card_table.card_type[card_id.clamp(min=0)] == 0
        # ... compute valid positions per card type
        # ... set mask bits for PLAY_CARD_BASE + hand_idx * 25 + cell

    # MOVE, ATTACK, SACRIFICE: iterate over board positions
    # ... similar pattern with position-based indexing

    return mask
```

## Sources

### Primary (HIGH confidence)
- Current codebase analysis: `src/grid_tactics/` -- all game logic files read and analyzed
- Measured baseline: 4,000 FPS single env, 3,700 DummyVecEnv (benchmarked locally)
- GPU available: RTX 4060 Laptop, 8 GB VRAM, CUDA 12.4, PyTorch 2.6

### Secondary (MEDIUM confidence)
- [Pgx paper (arXiv:2303.17503)](https://arxiv.org/abs/2303.17503) -- Architecture patterns for GPU-vectorized game engines, 10-100x speedup claims
- [Pgx GitHub](https://github.com/sotetsuk/pgx) -- JAX-based vectorized game env implementation patterns
- [PufferLib 2.0](https://rlj.cs.umass.edu/2025/papers/RLJ_RLC_2025_151.pdf) -- 1M steps/sec on RTX 4090, CPU vectorization patterns
- [SB3 MaskablePPO docs](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) -- action_masks() interface requirements
- [SB3 SubprocVecEnv + MaskablePPO issue](https://github.com/DLR-RM/stable-baselines3/issues/1793) -- Vectorization constraints
- [PyTorch vmap docs](https://docs.pytorch.org/docs/stable/generated/torch.vmap.html) -- Batch transformation API
- [TorchRL vectorized envs](https://docs.pytorch.org/rl/main/reference/envs_vectorized.html) -- PyTorch-native env parallelization

### Tertiary (LOW confidence)
- FPS estimates for RTX 4060 derived by scaling Pgx A100 numbers -- needs validation via prototyping
- `torch.compile` effectiveness for game logic -- no direct benchmarks found, needs empirical measurement
- Self-play opponent integration pattern -- architectural design, not yet validated

## Metadata

**Confidence breakdown:**
- Architecture (tensor state): HIGH -- well-established pattern (Pgx, Brax, IsaacGym)
- Performance estimates: MEDIUM -- based on analogous systems, not measured on this specific game
- SB3 integration: HIGH -- VecEnv API is documented, MaskablePPO action_masks() is straightforward
- React system vectorization: MEDIUM -- no prior art for this specific mechanic, architectural design only
- Card modularity: HIGH -- table lookup pattern is standard and proven

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (stable domain, PyTorch/SB3 APIs unlikely to change)
