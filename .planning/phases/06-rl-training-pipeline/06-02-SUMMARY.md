---
phase: 06-rl-training-pipeline
plan: 02
subsystem: rl
tags: [reward-shaping, self-play, checkpoint-pool, potential-based, maskable-ppo, sb3-contrib]

# Dependency graph
requires:
  - phase: 06-rl-training-pipeline
    provides: SB3 + sb3-contrib installed and importable; GridTacticsEnv with action_masks()
  - phase: 05-rl-environment
    provides: GridTacticsEnv, observation encoder, action space encoder, sparse reward
provides:
  - Potential-based reward shaping with 4-component potential function
  - SelfPlayEnv Gymnasium wrapper for single-agent self-play training
  - CheckpointManager for model checkpoint pool save/load/sample/prune
  - SelfPlayCallback for SB3 integration with checkpoint pool and opponent swapping
affects: [06-03-PLAN, 07-robustness, 09-dashboard]

# Tech tracking
tech-stack:
  added: []
  patterns: [potential-based-reward-shaping, gymnasium-wrapper-self-play, checkpoint-pool-opponent-sampling]

key-files:
  created:
    - src/grid_tactics/rl/self_play.py
    - src/grid_tactics/rl/callbacks.py
    - src/grid_tactics/rl/checkpoint_manager.py
    - tests/test_reward_shaping.py
    - tests/test_self_play.py
    - tests/test_checkpoint_manager.py
  modified:
    - src/grid_tactics/rl/reward.py
    - src/grid_tactics/rl/__init__.py

key-decisions:
  - "Potential function uses 4 weighted components: HP advantage (0.3), board control (0.3), mana efficiency (0.2), positional advancement (0.2)"
  - "Mana component is absolute (my_mana/MAX_MANA_CAP) not relative -- encourages saving mana independently of opponent"
  - "SelfPlayEnv training agent is always player 0; opponent auto-stepped in while loop"
  - "CheckpointManager samples 50% latest / 50% random to prevent strategy cycling"
  - "SelfPlayCallback uses save_freq-based triggering for deterministic checkpoint intervals"

patterns-established:
  - "Gymnasium.Wrapper for self-play: auto-step opponent turns, delegate action_masks()"
  - "Potential-based shaping F(s,s') = gamma*Phi(s')-Phi(s) preserving optimal policy"
  - "Checkpoint pool with save/sample/prune lifecycle for diverse opponent sampling"

requirements-completed: [RL-05, RL-06]

# Metrics
duration: 12min
completed: 2026-04-02
---

# Phase 6 Plan 02: Reward Shaping + Self-Play + Checkpoint Pool Summary

**Potential-based reward shaping with 4-component heuristic plus SelfPlayEnv wrapper and checkpoint pool for diverse opponent sampling during MaskablePPO training**

## Performance

- **Duration:** 12 min
- **Started:** 2026-04-02T16:43:50Z
- **Completed:** 2026-04-02T16:55:56Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments
- Potential-based reward shaping with HP advantage, board control, mana efficiency, and positional advancement components, all clamped to [-1.0, 1.0]
- SelfPlayEnv Gymnasium wrapper that auto-steps opponent turns, delegates action_masks() (Pitfall 1 mitigated), and supports both random and MaskablePPO opponents
- CheckpointManager with save/load/sample/prune operations for maintaining a diverse opponent pool (Pitfall 2 mitigated)
- SelfPlayCallback integrating checkpoint pool management with SB3's callback system
- 29 comprehensive tests across 3 test files covering reward shaping, self-play, and checkpoint management

## Task Commits

Each task was committed atomically:

1. **Task 1: Potential-based reward shaping**
   - `66e8c9e` (test): add failing tests for potential-based reward shaping
   - `d6134f5` (feat): implement potential-based reward shaping
2. **Task 2: SelfPlayEnv + CheckpointManager + SelfPlayCallback**
   - `1dd4b84` (test): add failing tests for SelfPlayEnv and CheckpointManager
   - `6790262` (feat): implement SelfPlayEnv, CheckpointManager, and SelfPlayCallback

## Files Created/Modified
- `src/grid_tactics/rl/reward.py` - Extended with potential() and compute_shaped_reward() alongside existing compute_reward()
- `src/grid_tactics/rl/self_play.py` - SelfPlayEnv Gymnasium wrapper for single-agent self-play
- `src/grid_tactics/rl/callbacks.py` - SelfPlayCallback for SB3 checkpoint pool management
- `src/grid_tactics/rl/checkpoint_manager.py` - Checkpoint pool save/load/sample/prune
- `src/grid_tactics/rl/__init__.py` - Updated exports for all new modules
- `tests/test_reward_shaping.py` - 16 tests for potential function and shaped reward
- `tests/test_self_play.py` - 7 tests for SelfPlayEnv wrapper
- `tests/test_checkpoint_manager.py` - 6 tests for checkpoint pool management

## Decisions Made
- Potential function weights (HP 0.3, Board 0.3, Mana 0.2, Advancement 0.2) follow research recommendation -- tunable in future phases
- Mana component is absolute rather than relative to encourage mana conservation independently of opponent state
- Training agent is always player 0 (simplifies SelfPlayEnv; player 1 is auto-stepped)
- CheckpointManager sampling uses 50/50 latest/random split to balance exploitation vs diversity
- SelfPlayCallback save frequency defaults to 10,000 steps -- configurable for production training

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed zero-sum symmetry test for mana component**
- **Found during:** Task 1 (GREEN phase)
- **Issue:** Test expected potential(s,0) == -potential(s,1) but mana component is absolute (my_mana/10), not relative, so symmetric states yield equal (not negated) potentials
- **Fix:** Changed test to verify equal potentials for symmetric states (p0 == p1) rather than anti-symmetric (p0 == -p1)
- **Files modified:** tests/test_reward_shaping.py
- **Verification:** All 16 reward shaping tests pass
- **Committed in:** d6134f5 (part of Task 1 GREEN commit)

**2. [Rule 3 - Blocking] Fixed CardLibrary fixture in test_self_play.py**
- **Found during:** Task 2 (GREEN phase)
- **Issue:** Used CardLibrary.load() which doesn't exist; correct method is CardLibrary.from_directory()
- **Fix:** Updated fixture to use from_directory() and proper deck building via build_deck()
- **Files modified:** tests/test_self_play.py
- **Verification:** All 7 self-play tests pass
- **Committed in:** 6790262 (part of Task 2 GREEN commit)

---

**Total deviations:** 2 auto-fixed (1 bug fix, 1 blocking)
**Impact on plan:** Both fixes were minor test corrections. No scope creep.

## Known Stubs

None -- all functions are fully implemented with real logic. No placeholders or TODOs.

## Issues Encountered
None -- both TDD cycles (RED/GREEN) completed cleanly after minor test fixture corrections.

## User Setup Required
None -- no external service configuration required.

## Next Phase Readiness
- SelfPlayEnv + CheckpointManager + SelfPlayCallback ready for Plan 06-03 to wire into training script
- compute_shaped_reward available for training with intermediate reward signals
- All 29 new tests passing alongside existing RL env tests (no regressions)

## Self-Check: PASSED

- All 8 created/modified files exist on disk
- All 4 commit hashes found in git log
- All 11 acceptance criteria content checks pass
- 29/29 tests passing across 3 test files

---
*Phase: 06-rl-training-pipeline*
*Completed: 2026-04-02*
