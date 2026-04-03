---
phase: quick-260403-gj2
plan: 01
subsystem: tensor-engine
tags: [gpu, pytorch, vectorization, rl-training, game-engine]
dependency_graph:
  requires: [game-engine, card-library, rl-env]
  provides: [tensor-game-engine, tensor-vec-env, card-table]
  affects: [rl-training-pipeline]
tech_stack:
  added: [torch.compile-compatible-tensors]
  patterns: [batched-tensor-ops, fixed-size-padding, branchless-game-logic, table-driven-effects]
key_files:
  created:
    - src/grid_tactics/tensor_engine/__init__.py
    - src/grid_tactics/tensor_engine/constants.py
    - src/grid_tactics/tensor_engine/card_table.py
    - src/grid_tactics/tensor_engine/state.py
    - src/grid_tactics/tensor_engine/effects.py
    - src/grid_tactics/tensor_engine/actions.py
    - src/grid_tactics/tensor_engine/react.py
    - src/grid_tactics/tensor_engine/legal_actions.py
    - src/grid_tactics/tensor_engine/observation.py
    - src/grid_tactics/tensor_engine/reward.py
    - src/grid_tactics/tensor_engine/engine.py
    - src/grid_tactics/tensor_engine/vec_env.py
    - tests/test_tensor_engine.py
    - tests/test_tensor_verification.py
  modified: []
decisions:
  - "Used int32 throughout (not int16) for GPU compatibility and avoiding dtype promotion"
  - "Per-game numpy RNG shuffle to match Python engine deck ordering exactly"
  - "resolve_react_stack_batch takes resolve_mask to prevent cross-game effect leakage in mixed-phase batches"
  - "Minion ON_PLAY SINGLE_TARGET effects pass target=-1 since action encoding doesn't capture separate effect target for deploys"
  - "Cross-engine verification uses decoded actions matching actual RL training behavior"
metrics:
  duration: "34min"
  completed: "2026-04-03"
---

# Quick Task 260403-gj2: GPU-Vectorized Game Engine Summary

**One-liner:** Complete PyTorch tensor engine running N games simultaneously with CardTable lookup, all 7 action types, react stack LIFO resolution, legal action masks, observation encoding, and SB3-compatible TensorVecEnv.

## What Was Built

### Core Tensor Engine (12 modules, ~2,600 lines)

**TensorGameState** (`state.py`): All game state as batched int32 tensors with leading dim N. Fixed-size padding with -1 sentinel for hands (10), decks (40), graveyards (80), minion slots (25), react stack (10). Provides `clone()` for branch computation.

**CardTable** (`card_table.py`): GPU-resident card property lookup loaded from CardLibrary. 18 cards with all stats, effects (up to 3 per card), react properties, multi-purpose flags. Precomputed grid geometry: adjacency (25x8x2), Manhattan distance (25x25), Chebyshev distance (25x25), orthogonal mask (25x25). Adding cards = adding rows.

**Effects** (`effects.py`): Table-driven batched effect resolution for DAMAGE, HEAL, BUFF_ATTACK, BUFF_HEALTH across all target types (SINGLE_TARGET, ALL_ENEMIES, ADJACENT, SELF_OWNER). Loops over MAX_EFFECTS_PER_CARD (3), not over batch.

**Actions** (`actions.py`): All 7 action types: PLAY_CARD (minion deploy + magic), MOVE, ATTACK (simultaneous damage + ON_ATTACK/ON_DAMAGED triggers), SACRIFICE, DRAW, PASS, PLAY_REACT. Action decoding from [0, 1262) integer space.

**React** (`react.py`): LIFO stack resolution with NEGATE chaining and DEPLOY_SELF for multi-purpose cards. Fixed 10-iteration loop with masking. resolve_mask parameter prevents cross-game leakage.

**Engine** (`engine.py`): TensorGameEngine orchestrator with `reset_batch()` and `step_batch()`. Full game loop: action dispatch, dead minion cleanup (two-pass with ON_DEATH triggers), game-over detection, phase transitions, turn advancement with mana regen.

**Legal Actions** (`legal_actions.py`): [N, 1262] bool mask computation for both ACTION and REACT phases. Covers all deployment rules (melee rows 0-1/3-4, ranged back row only), attack range validation (melee orthogonal, ranged orthogonal+diagonal), sacrifice eligibility, draw availability, react condition checking.

**Observation** (`observation.py`): [N, 292] float32 encoding matching Python encoder exactly: 25 cells x 10 features, 10 hand slots x 2 features, resources, opponent visible, game context, react context.

**Reward** (`reward.py`): Sparse +1/-1/0 reward matching Python engine.

**VecEnv** (`vec_env.py`): SB3-compatible TensorVecEnv with `action_masks()` support. Handles self-play opponent stepping internally (random or model policy), auto-reset for finished games.

### Test Suite (22 tests)

- CardTable: 6 tests (card types, stats, effects, react eligibility, distances)
- Reset: 4 tests (initial state, hands, board, minions)
- Stepping: 4 tests (draw, pass, mana regen, multiple turns)
- Legal masks: 4 tests (initial actions, draw legality, PASS in phases)
- Cross-engine: 2 tests (8 games x 50 steps state comparison, legal mask equivalence)
- VecEnv: 2 tests (20-step smoke test, observation shape/dtype)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] React stack resolved wrong games in mixed-phase batches**
- **Found during:** Task 3 cross-engine verification
- **Issue:** `resolve_react_stack_batch` operated on ALL games, so when some games passed in REACT while others pushed react cards, the just-pushed cards were immediately resolved
- **Fix:** Added `resolve_mask` parameter; engine passes `is_pass` mask
- **Files modified:** `react.py`, `engine.py`
- **Commit:** fbe10bb

**2. [Rule 1 - Bug] Minion ON_PLAY effects used deploy position as effect target**
- **Found during:** Task 3 cross-engine verification
- **Issue:** `_deploy_minion` passed `target_flat` (deploy cell) to `apply_effects_batch`, causing ON_PLAY SINGLE_TARGET DAMAGE to hit the deployed minion itself
- **Fix:** Pass target=-1 since action space encoding doesn't capture separate effect target for minion deploys (matches decoded-action behavior in RL training)
- **Files modified:** `actions.py`
- **Commit:** fbe10bb

## Decisions Made

1. **int32 throughout** -- Avoids dtype promotion overhead on GPU. Memory difference is negligible (~24 MB at N=4096 vs ~12 MB with int16).

2. **Per-game numpy RNG for deck shuffling** -- Ensures identical starting conditions as the Python engine given the same seed, critical for cross-engine verification.

3. **Decoded-action comparison for cross-engine tests** -- Both engines receive actions through the integer encoding path, matching actual RL training behavior. Some information (ON_PLAY target for minion deploys) is intentionally lost, as it is in real training.

4. **Per-game Python loops for complex actions** -- Actions like PLAY_CARD and ATTACK use per-game loops for correctness in V1. This is acceptable because the batch dimension parallelism comes from running many games, not from vectorizing within-game logic.

## Known Stubs

None -- all modules are fully implemented with complete game logic.

## Self-Check: PASSED

- All 14 created files exist on disk
- All 3 task commits verified (f1ea1a8, 364bed9, fbe10bb)
- All 22 tests pass (7.96s)
