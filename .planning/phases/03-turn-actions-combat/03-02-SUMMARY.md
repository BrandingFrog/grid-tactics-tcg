---
phase: 03-turn-actions-combat
plan: 02
subsystem: game-engine
tags: [effect-resolver, action-resolver, combat, simultaneous-damage, deployment-zones, dead-minion-cleanup, react-transition]

# Dependency graph
requires:
  - phase: 01-game-state-foundation
    provides: Board with adjacency/distance helpers, Player with mana/hand/HP operations, GameState frozen dataclass
  - phase: 02-card-system
    provides: CardDefinition, EffectDefinition, CardLibrary with numeric ID lookup
  - phase: 03-turn-actions-combat plan 01
    provides: ActionType enum, MinionInstance dataclass, Action dataclass, GameState extended with minion/react fields
provides:
  - resolve_effect() dispatching on EffectType x TargetType for declarative effect resolution
  - resolve_effects_for_trigger() filtering effects by trigger type and chaining resolutions
  - resolve_action() validating and applying all 5 main-phase actions (PASS, DRAW, MOVE, PLAY_CARD, ATTACK)
  - Simultaneous combat damage (D-01) with effective attack calculation (base + bonus)
  - Dead minion cleanup (D-02) with on_death effect triggering in instance_id order
  - Attack range validation (D-03) for melee and ranged
  - Deployment zone enforcement (D-08 melee, D-09 ranged)
  - Phase transition to REACT after every action (D-13)
affects: [03-03-PLAN, 04-game-loop, 05-rl-environment]

# Tech tracking
tech-stack:
  added: []
  patterns: [Declarative effect resolution dispatching on EffectType x TargetType, Action handler pattern with per-type _apply functions, Dead minion cleanup as post-action step with on_death triggering]

key-files:
  created:
    - src/grid_tactics/effect_resolver.py
    - src/grid_tactics/action_resolver.py
    - tests/test_effect_resolver.py
    - tests/test_action_resolver.py
  modified: []

key-decisions:
  - "SELF_OWNER target dispatches DAMAGE/HEAL to player HP, BUFF_ATTACK/BUFF_HEALTH to caster minion"
  - "Magic cards use virtual caster context (no board position) for effect resolution"
  - "Dead minion cards go to owner's graveyard tuple during cleanup"
  - "On_death effects resolve on post-removal state (dead minions already removed before effects trigger)"

patterns-established:
  - "Effect resolver pattern: dispatch on TargetType to find targets, then on EffectType to apply modification"
  - "Action resolver pattern: validate -> apply handler -> cleanup dead -> transition to REACT"
  - "_replace_minion and _replace_player helpers for immutable tuple updates"
  - "Attack range validation: melee=orthogonal adjacent, ranged=orthogonal up to N OR diagonal adjacent"

requirements-completed: [ENG-03, ENG-06, ENG-08]

# Metrics
duration: 8min
completed: 2026-04-02
---

# Phase 3 Plan 2: Effect Resolution Engine and Action Resolver Summary

**Declarative effect resolver handling all EffectType x TargetType combinations, plus action resolver validating and applying PASS/DRAW/MOVE/PLAY_CARD/ATTACK with simultaneous combat, dead minion cleanup, and REACT phase transitions**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-02T13:21:52Z
- **Completed:** 2026-04-02T13:29:43Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Declarative effect resolver handling DAMAGE/HEAL/BUFF_ATTACK/BUFF_HEALTH across SINGLE_TARGET/ALL_ENEMIES/ADJACENT/SELF_OWNER targets
- Action resolver with full validation and application of all 5 main-phase actions
- Simultaneous combat damage (D-01) with effective attack (base + attack_bonus)
- Dead minion cleanup after every action (D-02) with on_death effects in instance_id order
- Correct deployment zones: melee to any friendly row (D-08), ranged to back row only (D-09)
- All actions transition to REACT phase with react_player_idx set to opponent (D-13)
- 47 new tests (18 effect resolver + 29 action resolver), zero regressions on 297 existing tests

## Task Commits

Each task was committed atomically:

1. **Task 1: Create effect resolution engine** - `32c046f` (feat)
2. **Task 2: Create action resolver for main-phase actions** - `ec31d5e` (feat)

_Both tasks used TDD: tests written first (RED), then implementation (GREEN)._

## Files Created/Modified
- `src/grid_tactics/effect_resolver.py` - Declarative effect resolution with resolve_effect and resolve_effects_for_trigger
- `src/grid_tactics/action_resolver.py` - Action validation and application with resolve_action entry point
- `tests/test_effect_resolver.py` - 18 tests for all effect/target combinations and edge cases
- `tests/test_action_resolver.py` - 29 tests for all action types, validation, cleanup, and transitions

## Decisions Made
- SELF_OWNER target type routes DAMAGE/HEAL effects to the owning player's HP, and BUFF_ATTACK/BUFF_HEALTH to the caster's minion at caster_pos -- this distinguishes "self-damage" from "self-buff"
- Magic cards use a virtual caster context (position from action.position or fallback to (0,0)) since they have no board presence
- Dead minion cards are added to their owner's graveyard during cleanup (the card was already removed from hand when deployed; cleanup only moves the card_numeric_id)
- On_death effects resolve on the post-removal state -- dead minions are removed first, then their effects trigger, preventing dead minions from being targeted by their own death effects

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all effect resolution and action handling is fully implemented with no placeholder values.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Effect resolver and action resolver are ready for Plan 03-03 (react window and legal action enumeration)
- resolve_action transitions to REACT phase, which Plan 03-03 will handle with react stack processing
- All 344 tests pass with zero regressions
- The action resolver's _can_attack helper encodes the full range validation rules (D-03) for legal_actions enumeration

## Self-Check: PASSED

- All 4 created files verified present on disk
- Both task commits (32c046f, ec31d5e) found in git log
- All acceptance criteria grep patterns matched
- Full test suite: 344 passed, 0 failed

---
*Phase: 03-turn-actions-combat*
*Completed: 2026-04-02*
