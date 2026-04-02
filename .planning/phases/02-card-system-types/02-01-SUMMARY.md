---
phase: 02-card-system-types
plan: 01
subsystem: game-engine
tags: [dataclasses, enum, intenum, card-types, frozen-dataclass, validation]

# Dependency graph
requires:
  - phase: 01-game-state-foundation
    provides: "IntEnum pattern (PlayerSide, TurnPhase), frozen dataclass pattern (Board, Player), types.py constants"
provides:
  - "CardType, Attribute, EffectType, TriggerType, TargetType IntEnums in enums.py"
  - "Card constants (MAX_COPIES_PER_DECK, MIN_DECK_SIZE, MIN_STAT, MAX_STAT, MAX_EFFECT_AMOUNT) in types.py"
  - "EffectDefinition frozen dataclass with amount validation"
  - "CardDefinition frozen dataclass with type-specific validation and multi-purpose support"
affects: [02-02-PLAN, phase-03-actions, phase-05-rl-environment, phase-08-card-expansion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "EffectDefinition as declarative data -- resolution engine in Phase 3"
    - "CardDefinition __post_init__ validation for type-specific field enforcement"
    - "attack_range field naming to avoid shadowing builtin range()"
    - "is_multi_purpose property for react_effect + react_mana_cost check"

key-files:
  created:
    - src/grid_tactics/cards.py
    - tests/test_enums.py
    - tests/test_cards.py
  modified:
    - src/grid_tactics/enums.py
    - src/grid_tactics/types.py

key-decisions:
  - "Used attack_range instead of range to avoid shadowing Python builtin"
  - "Effect amount validated 1-10 (extensible for Phase 8) not 1-5 like other stats"
  - "Non-minion cards explicitly reject attack/health fields for clean type separation"

patterns-established:
  - "__post_init__ validation pattern for frozen dataclasses with type-specific rules"
  - "Declarative effect data objects (EffectDefinition) separate from resolution logic"
  - "Multi-purpose card pattern via optional react_effect + react_mana_cost pair"

requirements-completed: [ENG-04, ENG-05, ENG-12]

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 2 Plan 1: Card System Types Summary

**Card type enums (CardType/Attribute/EffectType/TriggerType/TargetType), stat constants, and frozen dataclasses (EffectDefinition, CardDefinition) with comprehensive type-specific validation**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-02T12:05:36Z
- **Completed:** 2026-04-02T12:09:29Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- 5 new IntEnum classes (CardType, Attribute, EffectType, TriggerType, TargetType) extending enums.py with numpy-compatible card system enums
- Card constants (MAX_COPIES_PER_DECK=3, MIN_DECK_SIZE=40, MIN_STAT=1, MAX_STAT=5, MAX_EFFECT_AMOUNT=10) in types.py
- EffectDefinition frozen dataclass with amount range validation [1, MAX_EFFECT_AMOUNT]
- CardDefinition frozen dataclass with type-specific validation: minions require attack/health/attack_range; non-minions reject those fields; multi-purpose (react_effect + react_mana_cost) only for minions
- 104 new tests (51 enum + 53 card) with zero regressions across full 198-test suite

## Task Commits

Each task was committed atomically:

1. **Task 1: Card enums and type constants** - `242d467` (test: RED), `cc617a0` (feat: GREEN)
2. **Task 2: EffectDefinition and CardDefinition frozen dataclasses** - `dec0faa` (test: RED), `93ee483` (feat: GREEN)

_TDD tasks have two commits each (test then implementation)_

## Files Created/Modified
- `src/grid_tactics/enums.py` - Extended with CardType, Attribute, EffectType, TriggerType, TargetType IntEnums
- `src/grid_tactics/types.py` - Extended with MAX_COPIES_PER_DECK, MIN_DECK_SIZE, MIN_STAT, MAX_STAT, MAX_EFFECT_AMOUNT
- `src/grid_tactics/cards.py` - New: EffectDefinition and CardDefinition frozen dataclasses with __post_init__ validation
- `tests/test_enums.py` - New: 51 tests covering all 7 enum classes and card constants
- `tests/test_cards.py` - New: 53 tests covering effect/card creation, validation, immutability, multi-purpose

## Decisions Made
- Used `attack_range` instead of `range` for the minion range field to avoid shadowing Python's builtin `range()` function
- Effect amount range set to [1, 10] rather than [1, 5] to support Phase 8 extensibility while starter cards use 1-5
- Non-minion cards explicitly reject attack/health fields (raise ValueError) for clean type separation rather than silently ignoring them

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Card type system complete, ready for Plan 02-02 (card loader, card library, starter card pool)
- All enums and dataclasses importable: `from grid_tactics.cards import CardDefinition, EffectDefinition`
- CardDefinition uses `from grid_tactics.types import MIN_STAT, MAX_STAT, MAX_EFFECT_AMOUNT` for validation ranges

## Known Stubs

None - all code is fully functional with no placeholder data or TODOs.

## Self-Check: PASSED

All 6 files verified present. All 4 commit hashes verified in git log.

---
*Phase: 02-card-system-types*
*Completed: 2026-04-02*
