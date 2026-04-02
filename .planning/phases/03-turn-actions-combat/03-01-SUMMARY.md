---
phase: 03-turn-actions-combat
plan: 01
subsystem: game-engine
tags: [dataclass, enum, minion, action, game-state, frozen, immutable]

# Dependency graph
requires:
  - phase: 01-game-state-foundation
    provides: Board, Player, GameState frozen dataclasses, enums, types
  - phase: 02-card-system
    provides: CardDefinition, EffectDefinition, CardLibrary, card enums
provides:
  - ActionType IntEnum with 6 action types (PLAY_CARD, MOVE, ATTACK, DRAW, PASS, PLAY_REACT)
  - MinionInstance frozen dataclass tracking runtime minion state
  - Action frozen dataclass with 6 convenience constructors
  - GameState extended with minions, next_minion_id, react_stack, react_player_idx, pending_action
  - AUTO_DRAW_ENABLED and MAX_REACT_STACK_DEPTH constants
  - make_minion and make_game_state_with_minions test fixtures
affects: [03-02-PLAN, 03-03-PLAN, 04-game-loop, 05-rl-environment]

# Tech tracking
tech-stack:
  added: []
  patterns: [MinionInstance runtime copy pattern separate from CardDefinition template, Action structured tuple with convenience constructors]

key-files:
  created:
    - src/grid_tactics/minion.py
    - src/grid_tactics/actions.py
    - tests/test_minion.py
    - tests/test_actions.py
  modified:
    - src/grid_tactics/enums.py
    - src/grid_tactics/types.py
    - src/grid_tactics/game_state.py
    - tests/conftest.py
    - tests/test_game_state.py

key-decisions:
  - "ActionType uses IntEnum matching existing enum pattern for numpy compatibility"
  - "GameState extended with defaults for backward compatibility -- existing code unchanged"
  - "MinionInstance tracks current_health and attack_bonus separate from CardDefinition base stats"
  - "Action uses Optional fields rather than subclasses for simplicity across 6 action types"

patterns-established:
  - "MinionInstance as runtime copy: CardDefinition is static template, MinionInstance is per-game instance with mutable (via replace) state"
  - "Convenience constructor functions: module-level functions (pass_action, draw_action, etc.) wrapping Action() for cleaner call sites"
  - "Backward-compatible GameState extension: new fields use defaults so existing from_dict handles old dicts"

requirements-completed: [ENG-03, ENG-06]

# Metrics
duration: 4min
completed: 2026-04-02
---

# Phase 3 Plan 1: Phase 3 Data Contracts Summary

**ActionType enum, MinionInstance runtime dataclass, Action structured dataclass, and GameState extended with minion/react fields -- all frozen, immutable, with backward-compatible defaults**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-02T13:14:25Z
- **Completed:** 2026-04-02T13:19:04Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- ActionType IntEnum with 6 values (PLAY_CARD, MOVE, ATTACK, DRAW, PASS, PLAY_REACT) added to enums.py
- MinionInstance frozen dataclass with is_alive property, tracks current_health and attack_bonus separate from CardDefinition
- Action frozen dataclass with 6 convenience constructor functions for all action types
- GameState extended with minions, next_minion_id, react_stack, react_player_idx, pending_action -- all with defaults for backward compatibility
- get_minion() and get_minions_for_side() helper methods on GameState
- to_dict/from_dict updated to handle Phase 3 fields including backward-compatible deserialization
- AUTO_DRAW_ENABLED, MAX_REACT_STACK_DEPTH, BACK_ROW_P1, BACK_ROW_P2 constants in types.py
- make_minion and make_game_state_with_minions test fixtures in conftest.py
- 57 new tests (18 minion + 20 action + 19 game state extension), zero regressions on 240 existing tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend enums and types, create MinionInstance dataclass** - `71a712f` (feat)
2. **Task 2: Create Action dataclass and extend GameState with minion/react fields** - `07edadf` (feat)

_Both tasks used TDD: tests written first (RED), then implementation (GREEN)._

## Files Created/Modified
- `src/grid_tactics/enums.py` - Added ActionType IntEnum with 6 values
- `src/grid_tactics/types.py` - Added AUTO_DRAW_ENABLED, MAX_REACT_STACK_DEPTH, BACK_ROW_P1, BACK_ROW_P2 constants
- `src/grid_tactics/minion.py` - NEW: MinionInstance frozen dataclass with is_alive property
- `src/grid_tactics/actions.py` - NEW: Action frozen dataclass with 6 convenience constructors
- `src/grid_tactics/game_state.py` - Extended with minions/react fields, get_minion/get_minions_for_side helpers, updated serialization
- `tests/conftest.py` - Added make_minion and make_game_state_with_minions fixtures
- `tests/test_minion.py` - NEW: 18 tests for ActionType, constants, MinionInstance
- `tests/test_actions.py` - NEW: 20 tests for Action construction, immutability, convenience constructors
- `tests/test_game_state.py` - Added 19 tests for Phase 3 GameState extensions

## Decisions Made
- ActionType uses IntEnum matching existing enum pattern (PlayerSide, TurnPhase, CardType) for numpy array compatibility in RL phase
- GameState extended with defaults (empty tuples, None, 0) so all existing code continues to work unchanged -- from_dict handles dicts without Phase 3 fields
- MinionInstance tracks current_health and attack_bonus separately from CardDefinition base stats (runtime copy pattern from research recommendation)
- Action uses a single dataclass with Optional fields rather than per-type subclasses -- simpler for 6 action types, all fields are Optional except action_type

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all data contracts are fully implemented with no placeholder values.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- MinionInstance and Action dataclasses are ready for Plan 03-02 (action resolution engine)
- GameState minion/react fields provide the state contract for the action resolver and react stack
- Test fixtures (make_minion, make_game_state_with_minions) are ready for Plan 03-02 and 03-03 test suites
- All 297 tests pass with zero regressions

## Self-Check: PASSED

- All 10 created/modified files verified present on disk
- Both task commits (71a712f, 07edadf) found in git log
- All acceptance criteria grep patterns matched
- Full test suite: 297 passed, 0 failed

---
*Phase: 03-turn-actions-combat*
*Completed: 2026-04-02*
