---
phase: 12-state-serialization-game-flow
plan: 01
subsystem: server
tags: [view-filter, action-codec, serialization, hidden-information, socketio]

# Dependency graph
requires:
  - phase: 11-server-foundation-room-system
    provides: Flask-SocketIO server, GameState.to_dict(), Action dataclass
provides:
  - filter_state_for_player() for per-player hidden info filtering
  - serialize_action() / reconstruct_action() for JSON wire transport
  - AUTO_DRAW_ENABLED guard on turn-transition auto-draw
affects: [12-02-PLAN, Phase 13 UI, Phase 14 react window UI]

# Tech tracking
tech-stack:
  added: []
  patterns: [deep-copy-and-filter for view security, compact JSON serialization with None omission]

key-files:
  created:
    - src/grid_tactics/server/view_filter.py
    - src/grid_tactics/server/action_codec.py
  modified:
    - src/grid_tactics/react_stack.py
    - tests/test_view_filter.py

key-decisions:
  - "Deep copy state dict before filtering to guarantee no mutation of shared state"
  - "Omit None fields in serialized actions for compact wire format"
  - "Guard auto-draw with existing AUTO_DRAW_ENABLED flag rather than new flag"

patterns-established:
  - "View filter pattern: copy.deepcopy(state_dict) then mutate copy for per-player views"
  - "Action codec pattern: serialize_action/reconstruct_action for all Action wire transport"

requirements-completed: [VIEW-01]

# Metrics
duration: 3min
completed: 2026-04-05
---

# Phase 12 Plan 01: View Filter, Action Codec, and Auto-Draw Fix Summary

**Per-player view filter hiding opponent hand/both decks/seed, bidirectional Action JSON codec, and AUTO_DRAW_ENABLED guard on turn transitions**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-05T10:20:16Z
- **Completed:** 2026-04-05T10:23:49Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- filter_state_for_player() strips opponent hand (preserving count), both decks (preserving count), and seed from state dicts
- serialize_action/reconstruct_action round-trip all 7 ActionType variants with compact JSON (None fields omitted, tuples to lists)
- Auto-draw bug in react_stack.py fixed by guarding with AUTO_DRAW_ENABLED check -- turn transitions no longer draw cards when disabled
- 24 new unit tests (13 view filter, 10 action codec, 1 auto-draw), all passing alongside 7 existing fatigue tests

## Task Commits

Each task was committed atomically:

1. **Task 1: View filter module and action codec with unit tests** - `e6b788a` (test: RED) + `ad5df46` (feat: GREEN)
2. **Task 2: Fix auto-draw bug in react_stack.py** - `be95072` (fix)

## Files Created/Modified
- `src/grid_tactics/server/view_filter.py` - Per-player state filtering (hides opponent hand, both decks, seed)
- `src/grid_tactics/server/action_codec.py` - Action to/from JSON conversion with validation
- `src/grid_tactics/react_stack.py` - Added AUTO_DRAW_ENABLED guard on turn-transition auto-draw
- `tests/test_view_filter.py` - 24 tests for view filter, action codec, and auto-draw fix

## Decisions Made
- Deep copy state dict before filtering to guarantee no mutation of shared game state objects
- Omit None-valued fields in serialized actions for compact JSON wire format
- Convert tuple positions to lists for JSON compatibility (reconstructed back to tuples on receive)
- Guard auto-draw with existing AUTO_DRAW_ENABLED flag (currently False) rather than introducing a new flag

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all functionality is fully wired.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- view_filter.py ready for Plan 02's game_start emission and submit_action handler
- action_codec.py ready for Plan 02's action deserialization from client
- AUTO_DRAW_ENABLED guard prevents rule violations during PvP turn transitions
- All 31 tests pass (24 new + 7 fatigue regression)

## Self-Check: PASSED

All 4 files exist. All 3 commits verified in git log.

---
*Phase: 12-state-serialization-game-flow*
*Completed: 2026-04-05*
