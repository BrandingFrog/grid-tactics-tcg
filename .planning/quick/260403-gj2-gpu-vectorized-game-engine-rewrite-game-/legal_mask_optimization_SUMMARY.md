# Legal Mask Vectorization Summary

## One-liner

Rewrote `compute_legal_mask_batch` to use pure tensor operations (scatter_, gather, broadcasting) instead of Python for-loops, achieving 19-43x speedup on CUDA with 1024 envs.

## Problem

`legal_actions.py` used `for i in range(N)` loops with `.item()` calls that synced GPU-CPU on every iteration. With 1024 envs, this took 277ms per call (78% of total training time).

## Solution

Replaced all batch-dimension Python loops with batched tensor operations:

1. **DRAW**: Single-line vectorized gather and boolean mask
2. **PLAY_CARD**: Build [N, MAX_HAND, 25] output tensor, flat-OR into mask slice
3. **MOVE**: Compute all [N, MAX_MINIONS, 4] destinations at once, scatter_ to mask
4. **ATTACK**: Full [N, 25, 25] pairwise distance check using precomputed CardTable distance matrices, scatter_ to mask
5. **SACRIFICE**: Vectorized row check with scatter_
6. **REACT**: Build [N, MAX_HAND, 26] output tensor, category-based boolean masking, flat-OR into mask slice

Key techniques:
- `torch.scatter_` for variable-index mask writing (replaces nonzero + advanced indexing)
- `torch.gather` for variable-index reads (board occupancy at computed positions)
- Precomputed deploy_masks[player][is_ranged] lookup table
- Batch react condition check returning dict of [N] bool masks
- Minimal `.any()` guards only for large tensor allocations (attack [N, 25, 25])

## Benchmarks (N=1024 envs, CUDA)

| Scenario | Before | After | Speedup |
|----------|--------|-------|---------|
| Initial state (action phase) | 277ms | 6.4ms | 43x |
| Mid-game (~3.2 minions) | 277ms | 14.3ms | 19x |
| React phase only | 277ms | 9.7ms | 29x |

### Per-function breakdown (mid-game):

| Function | Time |
|----------|------|
| play_card | 2.7ms |
| move | 0.9ms |
| attack | 1.4ms |
| sacrifice | 0.9ms |
| draw | 0.3ms |
| react | 8.6ms |

## Verification

All 22 existing tests pass:
- 18 tests in `test_tensor_engine.py` (card table, reset, stepping, legal masks)
- 4 tests in `test_tensor_verification.py` (cross-engine verification against Python engine, legal mask match, VecEnv integration)

The `test_legal_mask_match` test specifically verifies that the tensor engine legal mask matches the Python engine's `build_action_mask` output for every action index.

## Files Modified

- `src/grid_tactics/tensor_engine/legal_actions.py` -- Complete rewrite (352 insertions, 393 deletions)

## Commit

- `5fd4667`: perf: vectorize legal_actions.py -- eliminate all Python for-loops over batch

## Deviations from Plan

None -- plan executed as written.

## Known Stubs

None.

## Self-Check: PASSED
