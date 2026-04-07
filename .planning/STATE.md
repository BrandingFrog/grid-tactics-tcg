---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Online PvP Dueling
status: verifying
stopped_at: "Phase 14.3-01 complete (AnimationQueue infra). Next: 14.3-02 summon animation."
last_updated: "2026-04-07T15:41:00.000Z"
last_activity: 2026-04-07
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 7
  completed_plans: 7
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-04)

**Core value:** The reinforcement learning engine that discovers and validates game strategies
**Current focus:** Phase 13 — board-hand-ui

## Current Position

Phase: 14.3 (game-juice) — IN PROGRESS
Plan: 1 of N (animation queue infra) — COMPLETE
Status: 14.3-01 landed. Client-side AnimationQueue + applyStateFrame refactor in place. State frames for action transitions (summon/move/attack) are buffered behind animations; pending UIs (react banner, tutor modal, post-move-attack pick) are structurally gated because they live inside renderGame which only runs from applyStateFrame. Wave 1 animations are 0ms no-op stubs — gameplay identical to pre-14.3. Waves 2-4 plug real visuals into playAnimation branches.
Last activity: 2026-04-07 — Completed 14.3-01-PLAN.md

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 0 (v1.1)
- Average duration: --
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend (from v1.0):**

- Last 5 plans: 6min, 23min, 8min, 12min
- Trend: Variable (UI/integration plans take longer)

*Updated after each plan completion*
| Phase 11 P01 | 4min | 2 tasks | 7 files |
| Phase 11 P02 | 22min | 2 tasks | 5 files |
| Phase 12-state-serialization-game-flow P01 | 3min | 2 tasks | 4 files |
| Phase 12-state-serialization-game-flow P02 | 5min | 2 tasks | 3 files |
| Phase 13-board-hand-ui P01 | 5min | 2 tasks | 4 files |
| Phase 13-board-hand-ui P02 | 5min | 2 tasks | 3 files |
| Phase 13-board-hand-ui P03 | 6min | 1 tasks | 1 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.1 Roadmap]: 5 phases (11-15) derived from 15 requirements across 5 categories (SERVER, VIEW, UI, PLAY, POLISH)
- [v1.1 Roadmap]: Server tested programmatically before browser UI (Phases 11-12 headless, 13-15 browser)
- [v1.1 Roadmap]: View filtering in Phase 12 before UI in Phase 13 -- security guarantee before rendering
- [v1.1 Roadmap]: React window UI separated from base board UI (Phase 14 vs 13) to keep Phase 13 scoped
- [v1.1 Roadmap]: Session tokens (not socket IDs) established in Phase 11 for Phase 15 reconnection
- [Phase 11]: Fatigue counts stored as tuple[int,int] in frozen GameState for concurrent game safety
- [Phase 11]: Flask-SocketIO async_mode=threading (no eventlet/gevent)
- [Phase 11]: Preset deck uses all 21 cards: 9 at 2 copies + 12 at 1 copy = 30 total
- [Phase 11]: 6-char uppercase alphanumeric room codes via secrets.choice (36^6 combos)
- [Phase 11]: UUID4 session tokens for player identity (not socket IDs) for Phase 15 reconnection
- [Phase 11]: register_events() pattern: module-level room_manager, closures for Socket.IO handlers
- [Phase 11]: Two-level locking: global RoomManager lock + per-WaitingRoom lock for ready race condition
- [Phase 12-state-serialization-game-flow]: Deep copy state dict before filtering for view security
- [Phase 12-state-serialization-game-flow]: Compact action JSON: omit None fields, convert tuples to lists
- [Phase 12-state-serialization-game-flow]: Auto-pass loop in submit_action handles zero-legal-action fatigue bleed server-side
- [Phase 12-state-serialization-game-flow]: Decision-maker routing: REACT phase uses react_player_idx, ACTION uses active_player_idx
- [Phase 12-state-serialization-game-flow]: card_defs sent at game_start so clients can render card names without separate API call
- [Phase 13-board-hand-ui]: Flask static_folder set relative to app.py via os.path for portable path resolution
- [Phase 13-board-hand-ui]: All CardDefinition fields serialized in card_defs for full UI rendering including effects as list of dicts
- [Phase 13-board-hand-ui]: Deck extraction in handle_ready placed before set_ready() to ensure deck stored before start_game
- [Phase 13-board-hand-ui]: get_card_defs Socket.IO handler added to events.py for deck builder pre-game card loading
- [Phase 13-board-hand-ui]: Perspective flip reverses display row iteration order only, never modifies data coordinates
- [Phase 13-board-hand-ui]: JS enum arrays (EFFECT_TYPE_NAMES, TRIGGER_NAMES, TARGET_NAMES) must mirror Python IntEnum values exactly
- [Phase 14.1-01]: Action-space [0:1262] preserved; DECLINE_POST_MOVE_ATTACK reuses PASS slot 1001 when pending_post_move_attacker_id is set
- [Phase 14.1-01]: pending_post_move_attacker_id lives on GameState (not Action) for snapshot/tensor mirror friendliness
- [Phase 14.1-01]: Melee move + attack/decline = ONE logical action = ONE react window (fires after pending clears)
- [Phase 14.1-01]: Pending state only set when at least one in-range enemy exists (no point asking a question with no answers)
- [Phase 14.1-02]: Tensor pending = `pending_post_move_attacker: IntTensor[N]` with -1 sentinel; None ↔ -1 maps to Python `pending_post_move_attacker_id`
- [Phase 14.1-02]: DECLINE has no dedicated action int — `_step_action_phase` reinterprets PASS (slot 1001) as DECLINE when pending >= 0, and excludes those games from fatigue
- [Phase 14.1-02]: React phase transition in tensor engine gated on `pending_post_move_attacker < 0` (mirrors Python)
- [Phase 14.1-02]: No python<->tensor state bridge exists; parity verified via shared observable invariants, not state diff
- [Phase 14.1-03]: legal_actions branches on pending_post_move_attacker_id BEFORE the ACTION/REACT phase check; pending state is orthogonal to phase
- [Phase 14.1-03]: ActionEncoder maps DECLINE_POST_MOVE_ATTACK -> slot 1001 and decode disambiguates from PASS via state.pending_post_move_attacker_id
- [Phase 14.1-03]: Tensor mask uses post-hoc override (zero pending games then re-enable attack+slot 1001) rather than threading pending through every sub-helper
- [Phase 14.1-03]: Tensor override uses 4-cardinal adjacency (not full pairwise distance table) — valid because Wave 1 only sets pending for melee minions
- [Phase 14.1-04]: Server pre-computes pending_attack_range_tiles + pending_attack_valid_targets; client never duplicates range geometry
- [Phase 14.1-04]: UI mode auto-enters from `pending_post_move_attacker_id != null` in state frames (same pattern as react-window) — reconnection-safe
- [Phase 14.1-04]: Two distinct CSS layers (.attack-range-footprint soft hint vs .attack-valid-target bright pulse) — combining them would hide threat geometry or muddle clickability
- [Phase 14.1-04]: Task 4 visual verification deferred to post-deploy Playwright E2E against Railway (same pattern as prior bug-fix waves)
- [2026-04-07]: Melee minions (attack_range == 0) chain move+attack as one action via post-move pending state. Ranged minions do not chain. One react window per logical action. Action-space layout [0:1262] preserved; slot 1001 reused as DECLINE_POST_MOVE_ATTACK when pending.
- [Phase 14.2-01]: Tutor on_play no longer auto-picks; enters pending_tutor state. Caster must TUTOR_SELECT (match index into pending_tutor_matches) or DECLINE_TUTOR. One react window fires AFTER pending clears.
- [Phase 14.2-01]: Action-space [0:1262] preserved. TUTOR_SELECT reuses PLAY_CARD[0:250] slots while pending_tutor set; DECLINE_TUTOR reuses slot 1001 (PASS), same trick as 14.1's DECLINE_POST_MOVE_ATTACK. Mutually exclusive with pending_post_move (asserted).
- [Phase 14.2-01]: tutor_target schema extended: accepts string (card_id shorthand, back-compat) OR dict selector with subset of {tribe, element, card_type} (AND semantics, case-insensitive). Loader rejects unknown keys at load time.
- [Phase 14.2-01]: pending_tutor lives on GameState (pending_tutor_player_idx, pending_tutor_matches) — same snapshot/tensor-friendly pattern as 14.1's pending_post_move_attacker_id.
- [Phase 14.2-02]: Tensor pending_tutor = `pending_tutor_player: int32[N]` (-1 sentinel) + `pending_tutor_matches: int32[N,K=8]` (-1 padded). dtype int32 chosen for uniformity with rest of engine over plan-suggested int8/int16; memory cost negligible.
- [Phase 14.2-02]: K=8 deck-match slots; loud AssertionError on overflow rather than silent truncation. Current worst case is 6 (Blue Diodebot tutoring red_diodebot).
- [Phase 14.2-02]: Tutor selector dict encoded into CardTable as 4 columns (`tutor_has_target`, `tutor_selector_tribe_id/element/card_type`) with `-1`=any, `>=0`=required, `-2`=unknown-value sentinel that guarantees no match.
- [Phase 14.2-02]: TUTOR_SELECT in tensor engine = PLAY_CARD action with `hand_idx` reinterpreted as match-slot index; DECLINE_TUTOR = PASS slot 1001. Both peeled out via `normal_mask = mask & ~has_pending_tutor_pre` so standard handlers never see pending-tutor games.
- [Phase 14.2-02]: React phase transition gated on BOTH `pending_post_move_attacker < 0` AND `pending_tutor_player < 0`. Mutex asserted in both `_step_action_phase` and `_apply_tutor`.
- [Phase 14.2-02]: No python<->tensor state-diff bridge (per 14.1-02 precedent); parity verified via shared observable invariants + Python sanity test.
- [Phase 14.2-04]: pending_tutor serialization is per-viewer enrichment AFTER filter_state_for_player. Caster receives resolved match list (numeric_id + deck_idx + match_idx) plus total-copies-owned across deck+hand+board. Opponent receives only pending_tutor_player_idx + pending_tutor_match_count. Avoids leaking deck contents while preserving the standard view-filter security boundary.
- [Phase 14.2-04]: Tutor-pick modal reuses renderDeckBuilderCard verbatim (passing count=-1 to suppress quantity badge). Single card-rendering source of truth — full art, stats, effects, element/tribe — no stripped-down tile.
- [Phase 14.2-04]: Modal sync mirrors 14.1's syncPendingPostMoveAttackUI pattern — driven by pending_tutor_player_idx in state frames, idempotent open/close, reconnection-safe. Background click does NOT dismiss; Skip button is the only explicit decline path.
- [Phase 14.2-04]: Opponent sees a passive 'Opponent is tutoring…' toast, never the modal — preserves caster's hidden information.
- [Phase 14.2-04]: TUTOR_SELECT/DECLINE_TUTOR client wire format reuses existing action codec verbatim ({action_type:9, card_index:match_idx} / {action_type:10}) — no codec changes.
- [Phase 14.2-04]: Task 3 visual verification deferred to post-deploy Playwright E2E against Railway (same pattern as 14.1-04 and prior bug-fix waves).
- [Phase 14.2-03]: Python legal_actions returns Action tuples (not a 1262 bool mask); the bool mask is built downstream by build_action_mask via ActionEncoder. Wave 3 routes pending_tutor through this seam: legal_actions emits TUTOR_SELECT/DECLINE_TUTOR Action objects, and ActionEncoder is extended to encode/decode them.
- [Phase 14.2-03]: TUTOR_SELECT encoder convention — match_idx packed onto card_index, slot = PLAY_CARD_BASE + match_idx * GRID_SIZE (cell sub-index pinned to 0). Decode disambiguates from PLAY_CARD via state.pending_tutor_player_idx.
- [Phase 14.2-03]: Encoder decode order — pending_tutor checked BEFORE pending_post_move_attacker (safe because the two pendings are mutex-asserted in legal_actions itself).
- [Phase 14.2-03]: Tensor pending_tutor override mirrors 14.1-03's post-hoc pattern — zero pending rows, scatter PLAY_CARD slots [PLAY_CARD_BASE + i*GRID_SIZE for i<n_matches] + PASS_IDX. n_matches computed as (pending_tutor_matches >= 0).sum(dim=-1).
- [Phase 14.2-05]: tutor_target accepts either a card_id string OR a selector dict with tribe/element/card_type keys (AND semantics, case-insensitive). Loader rejects unknown keys at load time.
- [Phase 14.2-05]: Tutor on_play enters a pending_tutor state; player picks from a modal or declines via Skip. Exactly one react window fires after the pending state resolves.
- [Phase 14.2-05]: Decline-allowed is the default behavior for pending_tutor; tunable to forced-pick if balance testing later suggests it.
- [Phase 14.2-05]: Action-space [0:1262] preserved across 14.2; TUTOR_SELECT reuses PLAY_CARD[0:K] slots and DECLINE_TUTOR reuses slot 1001 (PASS) only while pending_tutor is set. Mutually exclusive with pending_post_move_attacker.
- [Phase 14.3-01]: Client AnimationQueue is serial callback-style (not Promises). Job = {type, payload, stateAfter, legalActionsAfter}. applyStateFrame is the single point of state application; renderGame (and therefore all pending-UI sync) only runs from applyStateFrame.
- [Phase 14.3-01]: Pending-UI gating is STRUCTURAL, not guarded. React banner / tutor modal / post-move-attack picker live inside renderGame → applyStateFrame → runQueue post-animation callback. No explicit isAnimating() guard needed on sync calls.
- [Phase 14.3-01]: Non-action frames (first frame, noop diffs) bypass the queue via direct applyStateFrame — keeps lobby/meta/react-open-close responsive. Only summon/move/attack diffs from next.pending_action enqueue.
- [Phase 14.3-01]: Wave 1 playAnimation branches are all setTimeout(done, 0) stubs. Waves 2-4 replace branches with real visuals; contract is "call done() when animation finishes".

### Pending Todos

None yet.

### Blockers/Concerns

- Known issue: RL checkpoints are now STALE after the cumulative 14.1 + 14.2 encoding reinterpretations (post-move-attack pending state + tutor selector schema + pending_tutor slot reuse). Loadable but behaviorally outdated. Retraining deferred; not blocking gameplay.
- Research flag: Phase 15 reconnection -- cookie vs localStorage, token expiry, and state resend edge cases may surface
- Research flag: Phase 15 timer cancellation -- start_background_task() cancellation is MEDIUM confidence per research
- Gap: Preset deck composition (card copy counts for 30-card deck) must be decided in Phase 11

## Session Continuity

Last session: 2026-04-07T15:41:00.000Z
Stopped at: Completed 14.3-01-PLAN.md (AnimationQueue infra). Next: 14.3-02 summon animation plugs into playAnimation 'summon' branch.
Resume file: None
