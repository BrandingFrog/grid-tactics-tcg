---
phase: 03-turn-actions-combat
plan: 03
subsystem: game-engine
tags: [react-stack, legal-actions, LIFO, react-window, action-masking, turn-cycle, chaining, integration]

# Dependency graph
requires:
  - phase: 01-game-state-foundation
    provides: Board with adjacency/distance helpers, Player with mana/hand/HP operations, GameState frozen dataclass
  - phase: 02-card-system
    provides: CardDefinition, EffectDefinition, CardLibrary with numeric ID lookup, CardType.REACT, is_multi_purpose
  - phase: 03-turn-actions-combat plan 01
    provides: ActionType enum, MinionInstance dataclass, Action dataclass with PLAY_REACT, GameState react fields
  - phase: 03-turn-actions-combat plan 02
    provides: resolve_effect, resolve_effects_for_trigger, resolve_action, _can_attack, _cleanup_dead_minions
provides:
  - ReactEntry frozen dataclass for react stack entries
  - handle_react_action() processing PLAY_REACT and PASS during react window
  - resolve_react_stack() with LIFO resolution order (D-06) and turn advancement
  - legal_actions() returning complete valid action set for any GameState (D-19, ENG-10)
  - ACTION phase enumeration: PLAY_CARD (D-08/D-09 deploy zones), MOVE, ATTACK (D-03), DRAW, PASS
  - REACT phase enumeration: react-eligible cards + multi-purpose react + PASS
  - Full react chaining: act -> react -> counter-react -> pass -> LIFO resolve (D-04 through D-07)
  - resolve_action() updated to delegate REACT phase to handle_react_action
  - Integration tests proving complete turn cycle with multi-turn gameplay
affects: [04-game-loop, 05-rl-environment, 07-self-play-robustness]

# Tech tracking
tech-stack:
  added: []
  patterns: [React stack LIFO chaining with counter-react opportunity switching, Legal action enumeration dispatching on TurnPhase, Soundness verification pattern (all legal_actions resolve without error)]

key-files:
  created:
    - src/grid_tactics/react_stack.py
    - src/grid_tactics/legal_actions.py
    - tests/test_react_stack.py
    - tests/test_legal_actions.py
    - tests/test_integration.py
  modified:
    - src/grid_tactics/action_resolver.py
    - tests/test_action_resolver.py

key-decisions:
  - "React stack entries use frozen dataclass with card_numeric_id for effect lookup during resolution"
  - "Resolve_action is the single entry point: delegates to handle_react_action during REACT phase via lazy import"
  - "React LIFO resolution uses reversed() iteration over react_stack tuple"
  - "Mana regeneration happens for the new active player at turn start (after react resolves)"
  - "legal_actions enumerates all target positions for single-target effects (enemy minions for magic/react)"
  - "React cards during legal_actions enumerate both friendly and enemy minion targets (for buffs like shield_block)"

patterns-established:
  - "React stack pattern: entries pushed as tuple append, resolved in reversed order (LIFO)"
  - "Phase-based action dispatch: resolve_action delegates based on state.phase"
  - "Legal action enumeration: phase-specific helper functions with shared target resolution"
  - "Soundness testing pattern: verify every action from legal_actions() can be resolved without ValueError"

requirements-completed: [ENG-03, ENG-06, ENG-08, ENG-10]

# Metrics
duration: 11min
completed: 2026-04-02
---

# Phase 3 Plan 3: React Window Stack with LIFO Chaining, legal_actions() Enumeration, and Integration Tests Summary

**React stack with LIFO resolution and counter-react chaining, complete legal_actions() enumeration for ACTION and REACT phases, and integration tests proving multi-turn gameplay with correct state transitions**

## Performance

- **Duration:** 11 min
- **Started:** 2026-04-02T13:32:17Z
- **Completed:** 2026-04-02T13:44:09Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- ReactEntry frozen dataclass and react window handler with LIFO stack resolution (D-04 through D-07)
- Full react chaining: act -> react -> counter-react -> pass -> LIFO resolve with dead minion cleanup
- legal_actions() returns complete, sound set of valid actions for any state (ENG-10)
- ACTION phase enumerates PLAY_CARD (melee/ranged deploy zones), MOVE, ATTACK, DRAW, PASS
- REACT phase enumerates react-eligible cards + multi-purpose react cards + PASS
- resolve_action() updated as single entry point, delegating REACT phase to handle_react_action
- Multi-purpose cards (dark_sentinel) playable as react using react_mana_cost and react_effect
- Soundness verified: every action from legal_actions() resolves without error
- 56 new tests (19 react_stack + 27 legal_actions + 10 integration), zero regressions on 344 existing tests

## Task Commits

Each task was committed atomically:

1. **Task 1: ReactEntry dataclass and react window handler** - `170a8c0` (feat)
2. **Task 2: legal_actions() enumeration and integration tests** - `9b803dd` (feat)

_Both tasks used TDD: tests written first (RED), then implementation (GREEN)._

## Files Created/Modified
- `src/grid_tactics/react_stack.py` - ReactEntry dataclass, handle_react_action, resolve_react_stack with LIFO
- `src/grid_tactics/legal_actions.py` - legal_actions() with ACTION/REACT phase enumeration
- `src/grid_tactics/action_resolver.py` - Updated resolve_action to delegate REACT phase to react handler
- `tests/test_react_stack.py` - 19 tests for react stack construction, chaining, resolution, effects
- `tests/test_legal_actions.py` - 27 tests for deploy zones, magic targets, move/attack range, react phase, soundness
- `tests/test_integration.py` - 10 tests for full turn cycles, react interaction, multi-turn, mana flow
- `tests/test_action_resolver.py` - Updated test_wrong_phase_raises to test_react_phase_delegates_to_react_handler

## Decisions Made
- ReactEntry uses card_numeric_id (not card_index) for effect lookup during resolution, since card_index is relative to the hand at time of play
- resolve_action is the single entry point for all actions; it delegates to handle_react_action via lazy import to avoid circular dependencies
- React stack resolves with reversed() iteration (LIFO per D-06) -- last react played resolves first
- Mana regeneration occurs for the new active player at turn start (after react stack resolves)
- legal_actions for react phase enumerates both friendly and enemy minion targets for single-target effects (enables buff-type react cards like shield_block targeting own minions)
- React cards are excluded from ACTION phase legal_actions; non-react cards excluded from REACT phase

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test_wrong_phase_raises in test_action_resolver.py**
- **Found during:** Task 1 (implementing react handler delegation)
- **Issue:** Existing test expected ValueError when resolve_action called during REACT phase, but the new behavior correctly delegates to handle_react_action instead
- **Fix:** Changed test to verify delegation behavior (test_react_phase_delegates_to_react_handler) and added react_player_idx parameter to _make_state helper
- **Files modified:** tests/test_action_resolver.py
- **Committed in:** 170a8c0

**2. [Rule 1 - Bug] Fixed integration test assertions for iron_guardian on_damaged effect**
- **Found during:** Task 2 (integration tests)
- **Issue:** Test expected defender health 5 after shield_block, but iron_guardian's on_damaged trigger adds +1 health, making actual value 6
- **Fix:** Updated assertion with correct calculation: 5 - 2(damage) + 1(on_damaged) + 2(shield_block) = 6
- **Files modified:** tests/test_integration.py
- **Committed in:** 9b803dd

**3. [Rule 1 - Bug] Used shadow_knight instead of fire_imp for deployment tests**
- **Found during:** Task 2 (integration tests)
- **Issue:** fire_imp has ON_PLAY single_target effect requiring target_pos, but deployment tests deployed without targets
- **Fix:** Switched to shadow_knight (no ON_PLAY effects) for tests that just need a deployable minion
- **Files modified:** tests/test_integration.py
- **Committed in:** 9b803dd

---

**Total deviations:** 3 auto-fixed (3 bugs)
**Impact on plan:** All auto-fixes were test correctness issues. No scope creep. Implementation matched plan exactly.

## Known Stubs

None - all react stack handling and legal action enumeration is fully implemented with no placeholder values.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 3 is now complete: all action types implemented, react window working, legal actions enumerable
- legal_actions() is ready for Phase 5 RL action masking (returns the boolean mask data)
- resolve_action() is the single entry point for Phase 4 game loop
- All 400 tests pass with zero regressions
- Complete turn cycle proven: action -> react window -> LIFO resolve -> turn advance with mana regen

## Self-Check: PASSED

- All 7 created/modified files verified present on disk
- Both task commits (170a8c0, 9b803dd) found in git log
- All acceptance criteria grep patterns matched
- Full test suite: 400 passed, 0 failed

---
*Phase: 03-turn-actions-combat*
*Completed: 2026-04-02*
