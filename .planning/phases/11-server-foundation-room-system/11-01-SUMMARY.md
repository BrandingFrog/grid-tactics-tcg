---
phase: 11-server-foundation-room-system
plan: 01
subsystem: server
tags: [flask, socketio, websocket, fatigue-fix, game-state, concurrent-safety]

# Dependency graph
requires: []
provides:
  - "GameState.fatigue_counts field for concurrent-safe fatigue tracking"
  - "Flask-SocketIO app factory (create_app) for server plans"
  - "Validated 30-card preset deck (PRESET_DECK_COUNTS, get_preset_deck)"
  - "pvp optional dependency group in pyproject.toml"
affects: [11-02, 12-view-filtering, server, tensor-engine]

# Tech tracking
tech-stack:
  added: [Flask-SocketIO 5.6, simple-websocket 1.1, python-socketio, python-engineio]
  patterns: [state-based-fatigue, app-factory, preset-deck-validation]

key-files:
  created:
    - src/grid_tactics/server/__init__.py
    - src/grid_tactics/server/app.py
    - src/grid_tactics/server/preset_deck.py
    - tests/test_fatigue_fix.py
  modified:
    - src/grid_tactics/game_state.py
    - src/grid_tactics/action_resolver.py
    - pyproject.toml

key-decisions:
  - "Fatigue counts stored as tuple[int, int] in frozen GameState, not mutable dict"
  - "Flask-SocketIO async_mode=threading for simplicity (no eventlet/gevent)"
  - "Preset deck: 9 cards at 2 copies + 12 at 1 copy = 30 total, all 21 cards used"

patterns-established:
  - "State-based fatigue: fatigue_counts in GameState ensures concurrent game safety"
  - "App factory pattern: create_app(testing=False) for Flask+SocketIO"
  - "Preset deck pattern: PRESET_DECK_COUNTS dict validated via CardLibrary.build_deck()"

requirements-completed: [SERVER-01, SERVER-02]

# Metrics
duration: 4min
completed: 2026-04-05
---

# Phase 11 Plan 01: Server Foundation Summary

**Concurrent-safe fatigue tracking in GameState, Flask-SocketIO app factory, and validated 30-card preset deck for PvP server foundation**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-05T07:33:21Z
- **Completed:** 2026-04-05T07:38:01Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Eliminated `_fatigue = {}` module-level global dict from action_resolver.py, replacing it with `fatigue_counts: tuple[int, int]` in the frozen GameState dataclass -- guarantees concurrent game independence
- Installed Flask-SocketIO 5.6 with simple-websocket transport and created the server package with app factory pattern
- Built and validated a 30-card preset deck using all 21 cards in the library (9 at 2 copies, 12 at 1 copy)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix _fatigue global dict (TDD RED)** - `e4111f2` (test)
2. **Task 1: Fix _fatigue global dict (TDD GREEN)** - `603ef72` (feat)
3. **Task 2: Flask-SocketIO deps + server skeleton** - `dcdb44c` (feat)

_TDD task had RED (failing tests) and GREEN (implementation) commits._

## Files Created/Modified
- `src/grid_tactics/game_state.py` - Added fatigue_counts field, to_dict/from_dict serialization
- `src/grid_tactics/action_resolver.py` - Removed _fatigue global, rewrote _apply_pass to use state
- `tests/test_fatigue_fix.py` - 7 tests: defaults, escalation, independence, serialization, no global
- `pyproject.toml` - Added pvp optional dependency group
- `src/grid_tactics/server/__init__.py` - Server package marker
- `src/grid_tactics/server/app.py` - Flask app factory with SocketIO, threading async mode
- `src/grid_tactics/server/preset_deck.py` - PRESET_DECK_COUNTS dict + get_preset_deck() function

## Decisions Made
- Fatigue counts stored as tuple[int, int] in frozen GameState (not dict) -- immutability consistent with existing patterns
- Flask-SocketIO async_mode set to "threading" -- simplest option, avoids eventlet/gevent monkey-patching complexity
- Preset deck uses all 21 cards in the library, prioritizing cheap/versatile cards at 2 copies

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Two pre-existing test failures in test_action_resolver.py (test_ranged_attack_orthogonal_distance_2, test_ranged_attack_diagonal_adjacent) exist in the uncommitted working tree. These are NOT caused by plan 01 changes -- they relate to attack range logic in uncommitted modifications. Logged as out-of-scope.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None - all code is fully wired and functional.

## Next Phase Readiness
- GameState.fatigue_counts ready for concurrent PvP games
- Flask app factory ready for Plan 02 to add SocketIO event handlers (room create/join)
- Preset deck ready for programmatic test clients
- Server package at src/grid_tactics/server/ ready for room.py, events.py additions

## Self-Check: PASSED

All 7 files verified present. All 3 commits verified in git log. All content assertions confirmed (fatigue_counts in GameState, _fatigue global removed, Flask-SocketIO in pyproject.toml, create_app in app.py, PRESET_DECK_COUNTS in preset_deck.py).

---
*Phase: 11-server-foundation-room-system*
*Completed: 2026-04-05*
