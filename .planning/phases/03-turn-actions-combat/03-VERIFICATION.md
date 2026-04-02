---
phase: 03-turn-actions-combat
verified: 2026-04-02T14:10:00Z
status: gaps_found
score: 13/14 must-haves verified
gaps:
  - truth: "legal_actions() never includes illegal actions (insufficient mana, occupied cells, out-of-range attacks)"
    status: failed
    reason: "When a MINION card has an ON_PLAY SINGLE_TARGET effect and there are no enemy minions on the board, legal_actions() emits deploy actions without target_pos. resolve_action() then raises ValueError because effect_resolver requires target_pos for SINGLE_TARGET effects. The fallback path at legal_actions.py:106-107 is incorrect."
    artifacts:
      - path: "src/grid_tactics/legal_actions.py"
        issue: "Lines 105-107: 'if not enemy_positions: actions.append(play_card_action(...))' produces unsound actions for SINGLE_TARGET ON_PLAY minions with no targets. Magic cards correctly skip (line 123), minions should do the same."
    missing:
      - "Remove the fallback at lines 105-107. When a MINION has ON_PLAY SINGLE_TARGET effects and no valid targets exist, skip those deploy positions entirely (consistent with magic card behaviour at line 123)."
human_verification:
  - test: "Verify that the ROADMAP.md progress table for Phase 3 is updated to reflect 3/3 plans complete and status Complete"
    expected: "Row for Phase 3 shows '3/3' and 'Complete' with a date"
    why_human: "ROADMAP.md currently shows '0/3 | Planned | -' for Phase 3 — this is a stale metadata entry, not a code issue. Updating it is a planning task."
---

# Phase 3: Turn Actions & Combat Verification Report

**Phase Goal:** Players can take actions (play cards, move minions, attack, draw) with correct rule enforcement and the system can enumerate all legal actions from any state
**Verified:** 2026-04-02T14:10:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | MinionInstance tracks current health separate from CardDefinition base health | VERIFIED | `minion.py`: `current_health: int` field; `is_alive` property; dataclasses.replace() used throughout |
| 2 | Action dataclass can represent all 6 action types with structured fields | VERIFIED | `actions.py`: frozen dataclass with 6 optional fields; 6 convenience constructors |
| 3 | GameState includes minions tuple, next_minion_id, and react state fields | VERIFIED | `game_state.py` lines 38-44: all 5 fields present with correct defaults |
| 4 | ActionType enum has values for PLAY_CARD, MOVE, ATTACK, DRAW, PASS, PLAY_REACT | VERIFIED | `enums.py` lines 72-84: all 6 values confirmed |
| 5 | A minion can be deployed to the correct zone (melee: friendly rows, ranged: back row only) | VERIFIED | `action_resolver.py` `_deploy_minion()`: D-08/D-09 zone validation; 29 action resolver tests pass |
| 6 | A minion can move in 4 orthogonal directions to an empty adjacent cell | VERIFIED | `action_resolver.py` `_apply_move()`: orthogonal adjacency check + empty cell check |
| 7 | Melee minions attack orthogonal adjacent targets; ranged attack up to N tiles orthogonal or 1 diagonal | VERIFIED | `action_resolver.py` `_can_attack()`: melee manhattan==1 + orthogonal; ranged orthogonal<=N or chebyshev==1 diagonal |
| 8 | Combat deals simultaneous damage (D-01) | VERIFIED | `action_resolver.py` `_apply_attack()` lines 365-369: both health values computed before replacement |
| 9 | Dead minions (health <= 0) removed after combat; on_death effects trigger | VERIFIED | `_cleanup_dead_minions()`: removes dead, triggers ON_DEATH in instance_id order |
| 10 | Drawing a card costs an action and removes top card from deck to hand | VERIFIED | `_apply_draw()`: calls `player.draw_card()` on active player |
| 11 | Pass is always a valid action | VERIFIED | `_apply_pass()` exists; `legal_actions()` always appends `pass_action()` |
| 12 | After an action, the opponent can play one react card per stack level with LIFO resolution | VERIFIED | `react_stack.py`: `handle_react_action()`, `resolve_react_stack()` with `reversed(state.react_stack)`; integration tests confirm |
| 13 | legal_actions() returns complete set of valid structured actions for ACTION phase | VERIFIED | `legal_actions.py`: enumerates PLAY_CARD/MOVE/ATTACK/DRAW/PASS; 27 tests + soundness test pass |
| 14 | legal_actions() never includes illegal actions | FAILED | Soundness failure: when `fire_imp` (ON_PLAY SINGLE_TARGET minion) is in hand with no enemy minions, `legal_actions()` emits 10 `PLAY_CARD` actions without `target_pos`. All 10 raise `ValueError: target_pos is required for SINGLE_TARGET effects` when passed to `resolve_action()`. |

**Score:** 13/14 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/grid_tactics/minion.py` | MinionInstance frozen dataclass | VERIFIED | Frozen, slots=True, is_alive property, imports PlayerSide |
| `src/grid_tactics/actions.py` | Action frozen dataclass + 6 constructors | VERIFIED | All 6 constructors present, frozen, imports ActionType |
| `src/grid_tactics/enums.py` | ActionType IntEnum | VERIFIED | 6 values PLAY_CARD=0..PLAY_REACT=5 |
| `src/grid_tactics/types.py` | AUTO_DRAW_ENABLED, MAX_REACT_STACK_DEPTH | VERIFIED | Both constants present at Phase 3 section |
| `src/grid_tactics/game_state.py` | Extended GameState with minions, react fields | VERIFIED | 5 new fields with defaults; get_minion/get_minions_for_side; to_dict/from_dict updated |
| `src/grid_tactics/effect_resolver.py` | Declarative effect resolution engine | VERIFIED | resolve_effect + resolve_effects_for_trigger; all 4 EffectType x 4 TargetType combinations handled |
| `src/grid_tactics/action_resolver.py` | Action validation + application returning new GameState | VERIFIED | resolve_action dispatches all 5 main-phase types; delegates REACT to react handler |
| `src/grid_tactics/react_stack.py` | ReactEntry + handle_react_action + resolve_react_stack | VERIFIED | LIFO via reversed(); MAX_REACT_STACK_DEPTH enforced; mana regen on turn advance |
| `src/grid_tactics/legal_actions.py` | Complete legal action enumeration | PARTIAL | Enumerates correctly in most cases; soundness failure for SINGLE_TARGET ON_PLAY minions with no targets |
| `tests/test_integration.py` | End-to-end multi-turn action + react integration tests | VERIFIED | 10 tests: full turn cycle, react with shield_block, multi-react LIFO, mana flow, combat cleanup |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `minion.py` | `enums.py` | `from grid_tactics.enums import PlayerSide` | WIRED | Line 16, used in `owner: PlayerSide` field |
| `actions.py` | `enums.py` | `from grid_tactics.enums import ActionType` | WIRED | Line 22, used in `action_type: ActionType` field |
| `game_state.py` | `minion.py` | `from grid_tactics.minion import MinionInstance` | WIRED | Line 16, used in `minions: tuple[MinionInstance, ...]` |
| `action_resolver.py` | `game_state.py` | `def resolve_action(state, action, library) -> GameState` | WIRED | Function present line 451; parameter types confirmed |
| `action_resolver.py` | `effect_resolver.py` | calls `resolve_effect` / `resolve_effects_for_trigger` | WIRED | Static import line 26; local import line 312; called at lines 284, 313, 376, 384, 390, 439 |
| `action_resolver.py` | `card_library.py` | `library.get_by_id(...)` | WIRED | Lines 194, 351, 360 |
| `effect_resolver.py` | `minion.py` | `replace(minion, current_health=...)` | WIRED | Lines 80, 92, 110 |
| `legal_actions.py` | `game_state.py` | `def legal_actions(state: GameState, library: CardLibrary) -> tuple[Action, ...]` | WIRED | Line 46; parameter used throughout |
| `react_stack.py` | `effect_resolver.py` | `resolve_effect` called during stack resolution | WIRED | Lazy import line 178; called lines 189, 196 |
| `action_resolver.py` | `react_stack.py` | delegates PLAY_REACT to `handle_react_action` | WIRED | Lazy import line 481; called line 482 |
| `legal_actions.py` | `board.py` | `Board.get_orthogonal_adjacent(...)` for move enumeration | WIRED | Line 133 |
| `legal_actions.py` | `action_resolver.py` | imports `_can_attack` for attack range check | WIRED | Line 22 |

---

## Data-Flow Trace (Level 4)

Not applicable — all Phase 3 artifacts are pure game-logic modules (no UI rendering, no dashboard, no dynamic data display). They produce new GameState objects via deterministic function calls, not data fetches. Data-flow tracing is not relevant here.

---

## Behavioral Spot-Checks

| Behavior | Command Result | Status |
|----------|---------------|--------|
| legal_actions() returns non-empty set with PASS from initial state | 12 actions; types: DRAW, PASS, PLAY_CARD; PASS=True | PASS |
| All legal_actions resolve without error (soundness — initial state with cards in hand, no board minions) | 10 PLAY_CARD actions with target_pos=None raise ValueError for fire_imp SINGLE_TARGET ON_PLAY | FAIL |
| React window opens (phase=REACT) after action | state2.phase=REACT, react_player_idx=1 after PASS action | PASS |
| Turn advances after react PASS | state3.phase=ACTION, active_player_idx=1, turn_number=2 | PASS |
| Full test suite: 400 tests pass | 400 passed in 0.73s | PASS |

---

## Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ENG-03 | 03-01, 03-02, 03-03 | Each turn = single action followed by opponent react window | SATISFIED | `resolve_action()` transitions to REACT phase after every action; `handle_react_action()` implements the window; integration tests verify the full cycle |
| ENG-06 | 03-01, 03-02, 03-03 | Minions move in 4 directions; melee attacks adjacent; ranged attacks up to 2 orthogonal or 1 diagonal | SATISFIED | `_apply_move()`: orthogonal adjacency; `_can_attack()`: melee range=0 manhattan==1+orthogonal, ranged orthogonal<=N or diagonal chebyshev==1 |
| ENG-08 | 03-02, 03-03 | Drawing a card costs an action (configurable auto-draw flag) | PARTIAL | `_apply_draw()` costs an action (correct for default AUTO_DRAW_ENABLED=False). Constant `AUTO_DRAW_ENABLED` exists in types.py but is never checked in legal_actions.py or action_resolver.py — the auto-draw variant is not actually wired. Since the constant default is False and the current behaviour is correct for that case, this is a deferred wiring issue, not a runtime defect. |
| ENG-10 | 03-03 | Legal action enumeration returns all valid actions from any game state | PARTIAL | legal_actions() is complete for most states but has a soundness bug: SINGLE_TARGET ON_PLAY minions with no enemy targets generate invalid actions. The soundness test passes because it always provides enemies; the edge case (empty board + SINGLE_TARGET minion in hand) is uncovered. |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/grid_tactics/legal_actions.py` | 105-107 | Fallback generates PLAY_CARD with no target_pos for SINGLE_TARGET ON_PLAY minions when no enemies present | Blocker | Violates soundness contract: legal_actions() must return only actions that resolve without error |
| `src/grid_tactics/types.py` + `legal_actions.py` + `action_resolver.py` | types.py:46, absent in resolvers | AUTO_DRAW_ENABLED constant defined but never checked — auto-draw variant not wired | Warning | ENG-08 configurable variant is dead code; not a runtime defect at default=False |

---

## Human Verification Required

### 1. ROADMAP.md Progress Table

**Test:** Open `.planning/ROADMAP.md` and find the Phase 3 row in the progress table.
**Expected:** Should show `3/3 | Complete | 2026-04-02` (or similar completed date).
**Why human:** The current table shows `0/3 | Planned | -` — this is stale metadata from before plans executed. Not a code defect, but a documentation accuracy issue. A human should update the roadmap table to reflect actual completion.

---

## Gaps Summary

One gap blocks full goal achievement:

**Soundness violation in legal_actions():** The `_action_phase_actions()` function has an asymmetric policy for SINGLE_TARGET effects. For magic cards (lines 122-124), when there are no enemy minions to target, the card is correctly excluded from legal actions. For minion cards (lines 105-107), the current code emits a deploy action WITHOUT `target_pos` as a fallback when no enemies are present. This action is not valid — `resolve_action()` will raise `ValueError` when the ON_PLAY SINGLE_TARGET effect tries to resolve without a target.

**Root cause:** The comment "If no enemies, still allow deploy without target" is wrong — a minion with a mandatory SINGLE_TARGET ON_PLAY effect cannot be deployed without a target. The magic card path (correctly skip when no valid targets) should be applied consistently.

**Fix:** Remove lines 105-107 from `legal_actions.py`. The loop at lines 101-104 already handles the case where enemies exist. When the loop produces no entries (no enemy targets), the deploy positions for that card should simply not appear in legal actions — exactly as magic cards behave.

**Scope:** Narrow fix (2-3 lines deleted from legal_actions.py). No changes needed to action_resolver.py or effect_resolver.py — their behaviour is already correct.

---

_Verified: 2026-04-02T14:10:00Z_
_Verifier: Claude (gsd-verifier)_
