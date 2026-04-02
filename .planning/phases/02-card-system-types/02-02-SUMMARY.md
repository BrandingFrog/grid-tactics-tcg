---
phase: 02-card-system-types
plan: 02
subsystem: game-engine
tags: [json, card-loader, card-library, deck-validation, starter-cards, data-driven]

# Dependency graph
requires:
  - phase: 02-card-system-types
    plan: 01
    provides: "CardDefinition, EffectDefinition frozen dataclasses; CardType, Attribute, EffectType, TriggerType, TargetType IntEnums; card constants"
provides:
  - "CardLoader static class converting per-card JSON files to CardDefinition objects"
  - "CardLibrary registry with O(1) lookup by numeric ID and string card_id"
  - "Deterministic numeric ID assignment sorted alphabetically by card_id"
  - "Deck validation enforcing D-12 (max 3 copies) and D-13 (min 40 cards)"
  - "build_deck helper creating validated deck tuples from card_id/count mappings"
  - "18 starter card JSON files in data/cards/ covering all card types and attributes"
affects: [phase-03-actions, phase-05-rl-environment, phase-06-rl-training, phase-08-card-expansion]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CardLoader with static load_card method and enum string-to-IntEnum parsing"
    - "CardLibrary as singleton registry loaded from directory at startup"
    - "Per-card JSON files in data/cards/ with human-readable field names"
    - "JSON 'range' field mapped to 'attack_range' parameter in CardDefinition"
    - "Validation at load time with descriptive ValueError messages"

key-files:
  created:
    - src/grid_tactics/card_loader.py
    - src/grid_tactics/card_library.py
    - data/cards/minion_fire_imp.json
    - data/cards/minion_shadow_knight.json
    - data/cards/minion_stone_golem.json
    - data/cards/minion_wind_archer.json
    - data/cards/minion_holy_paladin.json
    - data/cards/minion_dark_assassin.json
    - data/cards/minion_flame_wyrm.json
    - data/cards/minion_light_cleric.json
    - data/cards/minion_iron_guardian.json
    - data/cards/minion_shadow_stalker.json
    - data/cards/magic_fireball.json
    - data/cards/magic_dark_drain.json
    - data/cards/magic_holy_light.json
    - data/cards/magic_inferno.json
    - data/cards/react_shield_block.json
    - data/cards/react_counter_spell.json
    - data/cards/react_dark_mirror.json
    - data/cards/minion_dark_sentinel.json
    - tests/test_card_loader.py
    - tests/test_card_library.py
  modified: []

key-decisions:
  - "CardLoader validates all enum fields at load time with case-insensitive parsing and descriptive error messages"
  - "CardLibrary assigns deterministic numeric IDs via sorted alphabetical card_id ordering"
  - "Starter pool attributes: Fire:4, Dark:5, Light:4, Neutral:4 (all 4 attributes represented)"
  - "Mana curve: 1-cost:2, 2-cost:6, 3-cost:5, 4-cost:3, 5-cost:2 for balanced play"

patterns-established:
  - "Data-driven card pipeline: JSON file -> CardLoader -> CardDefinition -> CardLibrary"
  - "from_directory classmethod pattern for batch loading game data"
  - "validate_deck returning error lists (not raising) for composable validation"
  - "build_deck as convenience wrapper with ValueError on invalid input"

requirements-completed: [CARD-01, CARD-02, ENG-04, ENG-05, ENG-12]

# Metrics
duration: 5min
completed: 2026-04-02
---

# Phase 2 Plan 2: Card Loading and Starter Pool Summary

**CardLoader/CardLibrary JSON pipeline with 18 starter cards (10 minion, 4 magic, 3 react, 1 multi-purpose) and deck validation enforcing D-12/D-13 rules**

## Performance

- **Duration:** 5 min
- **Started:** 2026-04-02T12:11:50Z
- **Completed:** 2026-04-02T12:16:45Z
- **Tasks:** 2
- **Files modified:** 22

## Accomplishments
- CardLoader static class that parses per-card JSON files into CardDefinition frozen dataclasses with case-insensitive enum conversion and descriptive validation errors at load time
- CardLibrary registry providing O(1) lookup by both numeric ID (for Player.hand/Board.cells) and string card_id, with deterministic alphabetical ID assignment
- Deck validation (validate_deck) enforcing max 3 copies per card (D-12) and minimum 40 cards (D-13), plus build_deck convenience helper
- 18 balanced starter cards in data/cards/ with varied mana curve (1-5 cost), all 4 attributes, melee/ranged mix, and 1 multi-purpose card (dark_sentinel)
- 42 new tests (16 CardLoader + 17 CardLibrary unit + 9 integration) with zero regressions across full 240-test suite

## Task Commits

Each task was committed atomically:

1. **Task 1: CardLoader and CardLibrary with deck validation** - `a61efa5` (test: RED), `c50441e` (feat: GREEN)
2. **Task 2: Create 18 starter card JSON files** - `6ab7117` (feat: cards + integration tests)

_TDD Task 1 has two commits (test then implementation)_

## Files Created/Modified
- `src/grid_tactics/card_loader.py` - CardLoader static class: JSON file -> CardDefinition with enum parsing and validation
- `src/grid_tactics/card_library.py` - CardLibrary registry: from_directory, get_by_id, get_by_card_id, validate_deck, build_deck
- `data/cards/minion_fire_imp.json` - 1-cost Fire Imp with on_play damage
- `data/cards/minion_shadow_knight.json` - 3-cost Dark vanilla beater
- `data/cards/minion_stone_golem.json` - 4-cost Neutral tank
- `data/cards/minion_wind_archer.json` - 2-cost Neutral ranged (range 2)
- `data/cards/minion_holy_paladin.json` - 3-cost Light healer
- `data/cards/minion_dark_assassin.json` - 2-cost Dark glass cannon with on_attack damage
- `data/cards/minion_flame_wyrm.json` - 5-cost Fire AoE on deploy (range 1)
- `data/cards/minion_light_cleric.json` - 2-cost Light adjacent healer (range 1)
- `data/cards/minion_iron_guardian.json` - 3-cost Neutral self-buffing tank
- `data/cards/minion_shadow_stalker.json` - 1-cost Dark with on_death damage
- `data/cards/magic_fireball.json` - 3-cost Fire single-target 4 damage
- `data/cards/magic_dark_drain.json` - 2-cost Dark drain (2 damage + 2 heal)
- `data/cards/magic_holy_light.json` - 2-cost Light 3 heal
- `data/cards/magic_inferno.json` - 4-cost Fire AoE 2 damage
- `data/cards/react_shield_block.json` - 1-cost Light +2 health buff
- `data/cards/react_counter_spell.json` - 2-cost Neutral 3 reactive damage
- `data/cards/react_dark_mirror.json` - 1-cost Dark mirror (1 damage + 1 heal)
- `data/cards/minion_dark_sentinel.json` - 3-cost Dark multi-purpose (minion OR react 2 damage for 2 mana)
- `tests/test_card_loader.py` - 16 tests: valid loading, validation errors, edge cases
- `tests/test_card_library.py` - 26 tests: lookups, deterministic IDs, deck validation, starter pool integration

## Decisions Made
- CardLoader validates all required fields and enum values at load time (not at play time) to prevent silent data corruption
- Numeric IDs assigned deterministically via sorted alphabetical card_id ordering -- simple and reproducible
- Attribute distribution chose 4 neutral cards (counter_spell, iron_guardian, stone_golem, wind_archer) rather than 3, giving slightly more neutral options for balanced deck building
- Mana curve weighted toward 2-3 cost cards (11 of 18) for dynamic early/mid-game pacing with expensive 4-5 cost finishers

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Complete card data pipeline operational: JSON files -> CardLoader -> CardDefinition -> CardLibrary
- Phase 3 (actions/combat) can access card definitions via CardLibrary.from_directory("data/cards")
- Phase 5 (RL environment) can encode card data into observation arrays using numeric IDs
- All 18 starter cards loadable and validated, 40-card deck constructible from pool
- Imports available: `from grid_tactics.card_loader import CardLoader` and `from grid_tactics.card_library import CardLibrary`

## Known Stubs

None - all code is fully functional with no placeholder data or TODOs.

## Self-Check: PASSED

All 22 files verified present. All 3 commit hashes verified in git log.
