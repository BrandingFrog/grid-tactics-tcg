---
phase: 04-win-condition-game-loop
plan: 01
subsystem: game-engine
tags: [sacrifice, win-detection, draw-detection, action-type, game-over]

# Dependency graph
requires:
  - phase: 03-turn-actions-combat
    provides: ActionType enum, Action dataclass, resolve_action, legal_actions, react_stack
provides:
  - SACRIFICE ActionType (value 6) with full action pipeline
  - _apply_sacrifice handler removing minion, dealing player damage, updating graveyard
  - _check_game_over detecting win/draw after every action and react resolution
  - GameState winner/is_game_over fields with serialization
  - SACRIFICE enumeration in legal_actions for eligible minions
  - Game-over guard returning only PASS when game is finished
affects: [04-02-PLAN, 05-rl-environment]

# Tech tracking
tech-stack:
  added: []
  patterns: [game-over-check-after-cleanup, sacrifice-on-back-row, terminal-state-short-circuit]

key-files:
  created:
    - tests/test_sacrifice.py
    - tests/test_win_detection.py
  modified:
    - src/grid_tactics/enums.py
    - src/grid_tactics/actions.py
    - src/grid_tactics/game_state.py
    - src/grid_tactics/action_resolver.py
    - src/grid_tactics/legal_actions.py
    - src/grid_tactics/react_stack.py
    - tests/test_minion.py

key-decisions:
  - "Win check after cleanup but before react transition: sacrifice damage checked immediately, game ends before react window if lethal"
  - "Game-over in react resolution: skip turn advance and mana regen, return terminal state with react state cleared"
  - "is_game_over guard at top of legal_actions: returns only PASS for finished games regardless of phase"

patterns-established:
  - "Game-over check pattern: _check_game_over called after _cleanup_dead_minions in both action_resolver and react_stack"
  - "Terminal state short-circuit: resolve_action returns immediately when is_game_over=True, skipping react transition"
  - "Sacrifice action pattern: minion_id only (no position needed), back-row validation in handler"

requirements-completed: [ENG-07, ENG-09]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 04 Plan 01: Sacrifice Action and Win/Draw Detection Summary

**SACRIFICE action type with back-row validation and per-action win/draw detection wired into both main-phase and react resolution**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T14:11:17Z
- **Completed:** 2026-04-02T14:16:11Z
- **Tasks:** 1 (TDD: RED + GREEN)
- **Files modified:** 9

## Accomplishments
- SACRIFICE = 6 added to ActionType enum with full action pipeline (constructor, handler, legal enumeration, resolve dispatch)
- Win/draw detection via _check_game_over after every action resolution and react stack resolution
- GameState extended with winner (Optional[PlayerSide]) and is_game_over (bool) with backward-compatible defaults and serialization
- 37 new tests covering sacrifice mechanics, win/draw detection, serialization, and legal_actions game-over guard

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Failing tests for sacrifice and win detection** - `6bbf7dc` (test)
2. **Task 1 (GREEN): Implement SACRIFICE and win/draw detection** - `7debd40` (feat)

_TDD task: test commit followed by implementation commit._

## Files Created/Modified
- `src/grid_tactics/enums.py` - Added SACRIFICE = 6 to ActionType
- `src/grid_tactics/actions.py` - Added sacrifice_action() convenience constructor
- `src/grid_tactics/game_state.py` - Added winner/is_game_over fields with to_dict/from_dict support
- `src/grid_tactics/action_resolver.py` - Added _apply_sacrifice, _check_game_over, wired SACRIFICE into dispatch
- `src/grid_tactics/legal_actions.py` - Added SACRIFICE enumeration and is_game_over guard
- `src/grid_tactics/react_stack.py` - Added _check_game_over call after react resolution
- `tests/test_sacrifice.py` - 20 tests for sacrifice mechanics and legal_actions
- `tests/test_win_detection.py` - 17 tests for win/draw detection and serialization
- `tests/test_minion.py` - Updated ActionType count assertion (6 -> 7)

## Decisions Made
- Win check placed after dead minion cleanup but before react transition, so lethal damage ends the game immediately
- React resolution game-over skips turn advance and mana regen, returning a clean terminal state
- is_game_over guard at top of legal_actions ensures no actions possible in finished games

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated ActionType count assertion in test_minion.py**
- **Found during:** Task 1 GREEN (implementation)
- **Issue:** test_minion.py asserted len(ActionType) == 6, but adding SACRIFICE made it 7
- **Fix:** Changed assertion to len(ActionType) == 7
- **Files modified:** tests/test_minion.py
- **Verification:** All 438 tests pass
- **Committed in:** 7debd40 (part of GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix in existing test)
**Impact on plan:** Trivial count assertion update. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all sacrifice and win/draw functionality is fully wired with no placeholder data.

## Next Phase Readiness
- SACRIFICE action type is fully functional following the established ActionType/Action/resolve_action/legal_actions pattern
- Win detection triggers after every action resolution (main phase and react phase)
- Ready for plan 04-02 (full game loop / turn system) to build on top of game-over detection
- Ready for Phase 5 RL environment to observe game termination via is_game_over/winner

---
*Phase: 04-win-condition-game-loop*
*Completed: 2026-04-02*
