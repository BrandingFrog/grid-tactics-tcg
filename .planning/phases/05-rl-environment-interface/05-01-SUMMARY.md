---
phase: 05-rl-environment-interface
plan: 01
subsystem: rl
tags: [numpy, gymnasium, observation-encoding, action-space, action-masking, rl-environment]

# Dependency graph
requires:
  - phase: 04-game-loop-orchestration
    provides: Complete game engine with GameState, legal_actions(), resolve_action(), game loop
provides:
  - encode_observation() converting GameState to 292-float numpy array
  - ActionEncoder with encode/decode for all 7 action types to/from Discrete(1262)
  - build_action_mask() generating boolean mask from legal_actions()
  - compute_reward() with sparse win/loss/draw signal
  - OBSERVATION_SPEC documenting field offsets for API deserialization
affects: [05-02-gymnasium-env, 06-rl-training, 07-pettingzoo-aec]

# Tech tracking
tech-stack:
  added: [gymnasium 1.2.3]
  patterns: [position-based action encoding, perspective-relative observation, flat 1D observation vector, MaskablePPO-compatible action mask]

key-files:
  created:
    - src/grid_tactics/rl/__init__.py
    - src/grid_tactics/rl/observation.py
    - src/grid_tactics/rl/action_space.py
    - src/grid_tactics/rl/reward.py
    - tests/test_observation.py
    - tests/test_action_space.py
  modified: []

key-decisions:
  - "Position-based action encoding (not minion-ID-based) for stable integer mapping across game states"
  - "Minimal hand encoding (2 features: is_present, mana_cost) to reduce observation size and speed training"
  - "Type-annotated constants with int annotation for clarity and IDE support"

patterns-established:
  - "Observation encoder takes (state, library, observer_idx) and returns perspective-relative flat array"
  - "Action encoder uses board positions as parameters, never transient minion IDs"
  - "Action mask built exclusively from legal_actions() -- never recomputes legality"
  - "All observation values normalized to [-1, 1] range for neural network training"

requirements-completed: [RL-02, RL-03]

# Metrics
duration: 6min
completed: 2026-04-02
---

# Phase 5 Plan 1: Observation and Action Space Encoders Summary

**292-float observation encoder, Discrete(1262) action space with position-based encoding, and MaskablePPO-compatible action mask validated across 100 random game states**

## Performance

- **Duration:** 6 min
- **Started:** 2026-04-02T15:34:36Z
- **Completed:** 2026-04-02T15:41:02Z
- **Tasks:** 1
- **Files modified:** 6

## Accomplishments
- Observation encoder produces fixed 292-float32 array from any GameState with documented field offsets (OBSERVATION_SPEC)
- Action encoder maps all 7 action types (PLAY_CARD, MOVE, ATTACK, SACRIFICE, DRAW, PASS, PLAY_REACT) to/from integers in [0, 1262) with full round-trip fidelity
- Action mask matches legal_actions() output exactly across 100 random game states with varied board positions
- No opponent hidden info leakage -- observation encodes only opponent HP, mana, hand size, deck size
- Sparse reward function returns +1/-1/0 for win/loss/draw-or-in-progress
- All 478 tests pass (28 new RL tests + 450 existing engine tests, zero regressions)

## Task Commits

Each task was committed atomically (TDD flow):

1. **Task 1 RED: Failing tests** - `905364e` (test)
2. **Task 1 GREEN: Implementation** - `41b956f` (feat)

**Plan metadata:** pending (docs: complete plan)

## Files Created/Modified
- `src/grid_tactics/rl/__init__.py` - Package init exporting public API (7 exports)
- `src/grid_tactics/rl/observation.py` - encode_observation(), OBSERVATION_SIZE, OBSERVATION_SPEC
- `src/grid_tactics/rl/action_space.py` - ActionEncoder class, ACTION_SPACE_SIZE, build_action_mask()
- `src/grid_tactics/rl/reward.py` - compute_reward() sparse reward function
- `tests/test_observation.py` - 11 tests: shape, range, empty board, hidden info, perspective, minion encoding, spec
- `tests/test_action_space.py` - 17 tests: encode/decode all 7 types, mask shape/matching, always-legal, reward

## Decisions Made
- **Position-based action encoding:** Actions use board positions (not minion instance IDs) for stable integer mapping. Minion IDs are transient; positions are bounded (5x5 grid).
- **Minimal hand encoding (2 features/card):** Only is_present and mana_cost. Full card stats can be expanded later if agent needs richer hand information.
- **Merged PLAY_CARD variants:** Minion deploy and targeted magic share the same PLAY_CARD section (hand_idx * 25 + cell). The cell parameter means deploy position for minions and target position for magic. This keeps the action space compact at 1262.
- **Deferred DEPLOY_WITH_TARGET:** No starter cards have minion ON_PLAY SINGLE_TARGET effects, so the 3-parameter encoding is not needed yet. Will extend in Phase 8 card expansion.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test calling rng.choice(int) instead of rng.choice(sequence)**
- **Found during:** Task 1 (test_mask_matches_legal)
- **Issue:** Test passed `rng.choice(len(actions))` but GameRNG.choice() expects a sequence with len(), not an int
- **Fix:** Changed to `rng.choice(actions)` which returns a random element from the actions tuple
- **Files modified:** tests/test_action_space.py
- **Verification:** Test passes for all 100 random states
- **Committed in:** 41b956f (Task 1 GREEN commit)

**2. [Rule 1 - Bug] Fixed test calling resolve_action with extra rng argument**
- **Found during:** Task 1 (test_mask_matches_legal)
- **Issue:** Test called `resolve_action(state, action, library, rng)` but resolve_action takes only 3 args
- **Fix:** Removed rng argument: `resolve_action(state, action, library)`
- **Files modified:** tests/test_action_space.py
- **Verification:** Test passes for all 100 random states
- **Committed in:** 41b956f (Task 1 GREEN commit)

---

**Total deviations:** 2 auto-fixed (2 bugs in test code)
**Impact on plan:** Minor test code fixes. No impact on production code or scope.

## Issues Encountered
None beyond the test code bugs documented above.

## Known Stubs
None -- all modules are fully implemented with no placeholder data or TODO markers.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Observation encoder, action space encoder, and reward function are ready for the Gymnasium environment wrapper (Plan 02)
- All exports available via `from grid_tactics.rl import ...`
- Action mask interface is MaskablePPO-compatible (boolean numpy array)
- Plan 02 will build GridTacticsEnv(gymnasium.Env) using these modules

## Self-Check: PASSED

All 6 created files verified to exist. Both commit hashes (905364e, 41b956f) confirmed in git log.

---
*Phase: 05-rl-environment-interface*
*Completed: 2026-04-02*
