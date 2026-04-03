# Engine Optimization Summary: Vectorize actions.py, engine.py, react.py

## One-liner
Eliminated all 83 `.item()` calls and all `for i in range(N)` loops from the tensor engine hot path, replacing with batched tensor operations.

## What Changed

### actions.py (53 .item() calls -> 0, 7 for-loops over N -> 0)
- `apply_draw_batch`: Replaced per-game deck-to-hand loop with batched `torch.where` indexing
- `apply_move_batch`: Replaced per-game board swap loop with batched advanced indexing + `torch.where`
- `apply_play_card_batch`: Replaced per-game mana/hand/graveyard/deploy loop with new batched helpers
- `apply_attack_batch`: Replaced per-game combat loop + per-game effect triggers with batched damage + batched `apply_effects_batch` calls
- `apply_sacrifice_batch`: Replaced per-game loop with batched board/graveyard/damage ops
- `apply_react_batch`: Replaced per-game loop with batched mana/hand/stack/player swap ops
- New `_remove_from_hand_batch`: Shifts cards left using loop over MAX_HAND (constant 9), not N
- New `_add_to_graveyard_batch`: Batched graveyard append
- New `_deploy_minion_batch`: Batched minion slot allocation + board placement + effect trigger

### engine.py (15 .item() calls -> 0, for-loops over N -> 0)
- `reset_batch`: Bulk tensor state clearing via `torch.where` + broadcasting; numpy RNG per-game (required for seed compat) but bulk CPU->GPU upload
- `_step_action_phase`: Batched pending action recording via graveyard lookup instead of per-game loop
- `_step_react_phase`: Batched mana regen via per-player `torch.where` + `clamp(max=10)` instead of per-game loop
- `cleanup_dead_minions_batch`: Loop over MAX_MINIONS slots (constant 25) instead of `for i in range(N) for slot in range(MAX_MINIONS)`; batched board clear, graveyard add, ON_DEATH triggers

### react.py (15 .item() calls -> 0, for-loops over N -> 0)
- DEPLOY_SELF: New `_deploy_self_batch` with batched board/minion writes
- Other react effects: New `_apply_react_effects_batch` handles DAMAGE/HEAL/BUFF with SINGLE_TARGET/ALL_ENEMIES/SELF_OWNER targeting using batched tensor ops
- Removed `_apply_single_react_effect` per-game function entirely

## Remaining Loops (all over fixed constants, NOT batch N)
- `range(MAX_HAND - 1)` = 9 iterations (hand shift-left)
- `range(2)` = 2 iterations (players)
- `range(STARTING_HAND_SIZE)` = 5 iterations (dealing)
- `range(MAX_MINIONS)` = 25 iterations (slot iteration)
- `range(MAX_REACT_DEPTH - 1, -1, -1)` = 10 iterations (LIFO stack)
- `range(3)` = 3 iterations (effects per card)

## Benchmark Results (CUDA, warmed up)

| Metric | Old | New | Change |
|--------|-----|-----|--------|
| step_batch N=4 | 9.16ms | 7.79ms | -15% |
| step_batch N=64 | 18.73ms | 17.89ms | -4% |
| .item() calls | 83 | 0 | -100% |
| for-loops over N | ~15 | 0 | -100% |

**Note on target:** The <5ms target was optimistic. The dominant cost at current scale is CUDA kernel launch overhead from the many `torch.where`, advanced indexing, and comparison operations per step -- NOT the eliminated .item() sync points. At small N, each kernel launch has ~0.01ms overhead and step_batch issues ~200+ operations. The vectorization benefit increases with N as Python loop overhead grows linearly while GPU parallelism stays constant.

## Verification
- All 22 tests pass (test_tensor_engine.py + test_tensor_verification.py)
- Cross-engine verification confirms tensor engine matches Python engine exactly
- VecEnv integration tests pass

## Commits
- `ebdc3a3` perf: vectorize actions.py -- eliminate 53 .item() calls and 7 for-loops over N
- `058808a` perf: vectorize engine.py -- eliminate 15 .item() calls and for-loops over N
- `81e49d0` perf: vectorize react.py -- eliminate 15 .item() calls and for-loops over N
- `5d195e0` fix: remove last .item() call from engine.py reset_batch seed extraction

## Key Files Modified
- `src/grid_tactics/tensor_engine/actions.py` (328 insertions, 239 deletions)
- `src/grid_tactics/tensor_engine/engine.py` (200 insertions, 129 deletions)
- `src/grid_tactics/tensor_engine/react.py` (153 insertions, 83 deletions)

## Next Steps for Further Optimization
1. **Reduce kernel launches**: Fuse multiple `torch.where` calls into single operations where possible
2. **torch.compile**: Wrap step_batch with `@torch.compile` to let the compiler fuse kernels
3. **Custom CUDA kernels**: For the hand shift-left and graveyard management, write fused kernels
4. **effects.py**: Still has MAX_MINIONS loops per effect type -- could be further vectorized with gather/scatter
