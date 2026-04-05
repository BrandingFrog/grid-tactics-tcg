---
phase: 12-state-serialization-game-flow
plan: 02
subsystem: server/game-flow
tags: [pvp, websocket, game-flow, integration-tests, view-filter]
dependency_graph:
  requires: [12-01]
  provides: [submit_action_handler, game_start_filtered, complete_game_flow]
  affects: [events.py, game_state.py, test_game_flow.py]
tech_stack:
  added: []
  patterns: [auto-pass-loop, decision-maker-routing, filtered-emission]
key_files:
  created:
    - tests/test_game_flow.py
  modified:
    - src/grid_tactics/server/events.py
    - src/grid_tactics/game_state.py
decisions:
  - "Auto-pass loop in submit_action handles zero-legal-action fatigue bleed server-side"
  - "Decision-maker routing: REACT phase uses react_player_idx, ACTION phase uses active_player_idx"
  - "card_defs sent at game_start so clients can render card names without separate API call"
metrics:
  duration: 5min
  completed: 2026-04-05
  tasks: 2
  files: 3
requirements: [SERVER-03, VIEW-02, VIEW-03]
---

# Phase 12 Plan 02: Game Flow Events and Integration Tests Summary

Complete PvP game flow over WebSocket with submit_action handler, filtered game_start, auto-pass, and 20 integration tests proving end-to-end gameplay works.

## What Was Done

### Task 1: submit_action handler and game_start filter fix (c70cd35)

Extended `src/grid_tactics/server/events.py` from 95 lines to 239 lines with:

1. **Fixed game_start** to use view filter -- opponent hand/deck hidden, seed stripped, card_defs included, legal_actions for active player only
2. **Added helper functions**: `_build_card_defs()`, `_emit_state_to_players()`, `_emit_game_over()` for consistent filtered emission
3. **submit_action handler** with full validation pipeline:
   - Token lookup from SID -> room_code -> game session -> player_idx
   - Game-over check ("Game is already over")
   - Decision-maker routing (REACT uses react_player_idx, ACTION uses active_player_idx)
   - Turn validation ("Not your turn")
   - Payload reconstruction via reconstruct_action (catches malformed input)
   - Legal action validation under session.lock
   - resolve_action application
   - Auto-pass loop for zero-legal-action states (fatigue bleed)
   - Filtered state_update emission to both players
   - game_over emission when game ends

### Task 2: Integration tests for complete game flow (5e664a9)

Created `tests/test_game_flow.py` with 20 tests (615 lines) organized into 6 test classes:

| Class | Tests | Coverage |
|-------|-------|----------|
| TestGameStartFiltered | 6 | VIEW-01: own hand visible, opponent hidden, no seed, decks hidden, card_defs, legal_actions |
| TestActionValidation | 5 | VIEW-02: legal accepted, illegal rejected, malformed rejected, wrong turn, post-game |
| TestLegalActionsInUpdates | 2 | VIEW-03: decision-maker gets actions, non-decision gets empty |
| TestBothReceiveUpdates | 3 | SERVER-03: both get state_update, react phase routing, state filtering |
| TestReactCardVisibility | 1 | D-03: graveyard visible to both players after react |
| TestCompleteGame | 3 | Full game to game_over with winner, filtered final state, state_updates throughout |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ReactEntry not JSON-serializable in GameState.to_dict() (8b8ba38)**
- **Found during:** Task 2 (integration testing)
- **Issue:** `GameState.to_dict()` serialized `react_stack` as `list(self.react_stack)` which just converts the tuple of ReactEntry dataclass objects to a list -- ReactEntry is not JSON-serializable
- **Fix:** Convert each ReactEntry to a dict with `player_idx`, `card_index`, `card_numeric_id`, `target_pos` fields during serialization
- **Files modified:** `src/grid_tactics/game_state.py`
- **Commit:** 8b8ba38

## Decisions Made

1. **Auto-pass loop server-side**: When a player has zero legal actions after an action resolves, the server automatically submits PASS actions (fatigue bleed) until either the game ends or legal actions become available. This prevents the client from needing to handle the zero-action state.

2. **Decision-maker routing**: REACT phase routes legal_actions to `react_player_idx`, ACTION phase to `active_player_idx`. This is computed in both `_emit_state_to_players` and the turn-validation check in `submit_action`.

3. **card_defs at game_start**: All card definitions (name, type, mana cost, attack, health, range, element) are sent once at game_start to avoid per-action lookups. Maps numeric_id to card info dict.

## Verification Results

```
66 passed in 1.54s
  - tests/test_view_filter.py: 24 passed
  - tests/test_game_flow.py: 20 passed
  - tests/test_pvp_server.py: 15 passed
  - tests/test_fatigue_fix.py: 7 passed
```

All Phase 11 tests pass (no regression). All Phase 12 tests pass.

## Known Stubs

None -- all functionality is fully wired.

## Requirements Satisfied

- **SERVER-03**: Both players receive filtered state_update after every action (proven by TestBothReceiveUpdates)
- **VIEW-02**: Illegal, malformed, and wrong-turn actions rejected with error events (proven by TestActionValidation)
- **VIEW-03**: Every state_update includes legal_actions for decision-maker, empty for other (proven by TestLegalActionsInUpdates)
- **VIEW-01**: game_start and all state_updates use view filter (proven by TestGameStartFiltered + TestBothReceiveUpdates.test_state_update_is_filtered)

## Self-Check: PASSED

- [x] src/grid_tactics/server/events.py exists
- [x] tests/test_game_flow.py exists
- [x] src/grid_tactics/game_state.py exists
- [x] .planning/phases/12-state-serialization-game-flow/12-02-SUMMARY.md exists
- [x] Commit c70cd35 found (Task 1)
- [x] Commit 8b8ba38 found (Bug fix)
- [x] Commit 5e664a9 found (Task 2)
