---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Online PvP Dueling
status: in_progress
stopped_at: "Phase 14.7 Plan 04 SHIPPED. Compound summon two-window dispatch now live: _deploy_minion no longer lands minions inline — it pushes a summon_declaration originator onto the react stack (phase=REACT, react_context=AFTER_SUMMON_DECLARATION, return=ACTION). Window A resolution (LIFO consumes the declaration entry) invokes resolve_summon_declaration_originator which: (a) lands the minion on the board, (b) if the minion has any ON_SUMMON effects, RESETS the react stack to a fresh summon_effect originator + re-sets phase=REACT with AFTER_SUMMON_EFFECT context (Window B), else drains out. resolve_react_stack gains a pre-resolution stack-identity snapshot + post-LIFO early-return: if state.react_stack is not the same tuple AND contains an originator, return state as-is (Window B opens naturally for opponent). Same function also gained a pending-modal hand-off: if originator resolution set pending_tutor_player_idx or pending_revive_player_idx, close the react window (phase=ACTION, clear react bookkeeping) WITHOUT advancing the turn — the modal owner is the correct next decision-maker. This also fixes a latent 14.7-01 bug where Ratmobile-style magic tutors advanced the turn before the caster picked. Window A negate is HARSH: mana + discard + destroy-ally costs all forfeit, minion does not land (per spec §4.2 / key_user_decisions #2). Window B negate is SOFT: effect cancelled, minion stays on board. Gargoyle Sorceress's two ON_SUMMON effects share one Window B (JSON-order). Minion ON_PLAY triggers are now orphaned — only ON_SUMMON fires through the compound pipeline (no real card uses trigger=on_play on a minion; grep-verified). resolve_action's terminal AFTER_ACTION REACT transition now short-circuits when state.phase is already REACT, so _deploy_minion's AFTER_SUMMON_DECLARATION context isn't overwritten. +7 unit tests (TestSummonCompoundWindows in test_react_stack.py), +4 integration tests + +1 random-games regression (test_integration.py), +2 sandbox round-trip tests (tests/server/test_sandbox_session.py). 6 deploy tests in test_action_resolver.py updated to drain Window A before asserting landed minion. All 6 Summon: minion JSONs flow correctly: 3 Diodebots' tutor chain, Eclipse Shade self-burn, Flame Wyrm draw, Gargoyle Sorceress buffs. Commits: 8b093af (feat Task 1) + 7639986 (test Task 2). Both pushed to master; Railway auto-deployed. Test posture: 784 non-RL tests pass (up from 745); baseline failures unchanged at 10 (1 spectator + 4 LEAP + 1 RL self-play + 4 tensor engine parity — all pre-existing and predating 14.7). Next: 14.7-05 (simultaneous-trigger priority queue + modal picker for multi-owner Start: / End: / Summon: effects)."
last_updated: "2026-04-18T23:00:00.000Z"
last_activity: 2026-04-18
progress:
  total_phases: 6
  completed_phases: 4
  total_plans: 23
  completed_plans: 16
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-04)

**Core value:** The reinforcement learning engine that discovers and validates game strategies
**Current focus:** Phase 13 — board-hand-ui

## Current Position

Phase: 14.7 (turn-structure-overhaul) — IN PROGRESS (Plans 01 + 02 + 03 + 04 of 10 shipped 2026-04-18)
Plan: 4 of 10 (Summon compound react windows) — COMPLETE
Next: 14.7-05 (simultaneous-trigger priority queue + modal picker) — 14.7-06 through 14.7-10 queued
Status: Plan 14.7-04 shipped: summon compound two-window dispatch is now live. _deploy_minion pushes a summon_declaration originator onto the react stack (Window A: AFTER_SUMMON_DECLARATION); on PASS-PASS, resolve_summon_declaration_originator lands the minion and — if ON_SUMMON effects exist — pushes a summon_effect originator to open Window B (AFTER_SUMMON_EFFECT). Window A negate = FULL forfeit (costs spent, minion doesn't land — spec §4.2 harsh-by-design). Window B negate = effect cancelled but minion stays. resolve_react_stack grew a stack-identity snapshot for compound-window hand-off + a pending-modal hand-off that fixes a latent 14.7-01 bug (Ratmobile-style tutor advancing turn before caster picks). 6 Summon: minion JSONs flow correctly: 3 Diodebots' tutor chain, Eclipse Shade self-burn, Flame Wyrm draw, Gargoyle Sorceress's two buffs share one Window B. Minion ON_PLAY triggers are orphaned (no card JSON uses them; only ON_SUMMON fires through compound pipeline). resolve_action's terminal AFTER_ACTION block now short-circuits when state.phase==REACT to respect originator handlers' inline react_context. +7 unit tests + +4 integration tests + +1 random-games regression (30 deterministic seeds, 150 iterations each) + +2 sandbox slot round-trip tests; 6 existing deploy tests updated to drain Window A before asserting landed minion. Commits: 8b093af (feat Task 1: _deploy_minion refactor + resolve helpers + 7 unit tests) + 7639986 (test Task 2: integration + random-games + sandbox round-trip). Both pushed to master; Railway auto-deployed. Test posture: 784 non-RL tests pass (up from 745); baseline failures unchanged at 10 (1 spectator + 4 LEAP + 1 RL self-play + 4 tensor engine parity — all pre-existing, predating 14.7). Hook points ready for 14.7-05 (Gargoyle's two-effect Window B is the insertion point for priority-queue modal picker) + 14.7-06 (fizzle markers in place for "cell occupied mid-chain" and "source minion died" edge cases) + 14.7-07 (ReactContext.AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT already drive react windows so the new OPPONENT_SUMMONS_MINION condition just needs matching logic).

### Phase 14.6 closeout context (retained for lookback)

Plan 03 sandbox interactive surface detail:
- `submitAction` at game.js:3328 with SANDBOX-EMIT-GATE-START at 3331 and SANDBOX-EMIT-GATE-END at 3337 -- single conditional `if (sandboxMode) socket.emit('sandbox_apply_action', actionData); else socket.emit('submit_action', actionData);`. Click handlers (onHandCardClick / onBoardCellClick / legacy minion menus) reuse the 14.6-02 global-swap unchanged. NO accessor shims were added.
- `showPileModal` at game.js:1884 extended with optional third arg `sandboxCtx = { pileType, playerIdx }`. Per-cell injection at game.js:1908 appends `makeSandboxMoveButton(playerIdx, nid, srcZone)` when sandboxMode && sandboxCtx are truthy. All existing 2-arg live-game callers work unchanged.
- `renderHand` at game.js:4850 per-card append loop at game.js:4894 gained an `if (sandboxMode && typeof makeSandboxMoveButton === 'function')` block that appends the Move-to button next to the existing card element. Play-from-hand click handler is unchanged.
- `renderSandboxStats` emits per-player pile-open buttons (sandbox-pile-btn, data-pile=grave/exhaust/deck_top, data-player=0|1) wired via post-innerHTML querySelectorAll to `showPileModal(title, ids, { pileType, playerIdx })`. The sandbox_state frame also emits data-player attrs + sandbox-player-row classes for deterministic Playwright targeting.
- New helpers inside the SANDBOX section (between SANDBOX-SECTION-START at 5047 and SANDBOX-SECTION-END at 5687): setupSandboxToolbar, makeSandboxMoveButton, openSandboxMovePopover, renderSandboxSlotList, sandboxEncodeShareCode, sandboxDecodeShareCode, escapeHtml, renderSandboxToolbarState. Plus SANDBOX_AUTOSAVE_KEY = 'gt_sandbox_autosave_v1', sandboxAddTargetIdx/sandboxAddZone/sandboxKnownSlots/_sandboxToolbarBound module globals.
- sandbox_state handler: autosaves to localStorage, calls renderSandboxToolbarState (updates history pill, toggles control highlight, disables undo/redo at depth 0, syncs cheat input values -- skipping document.activeElement to avoid clobbering user typing). sandbox_save_blob handler upgraded from stub to Blob + URL.createObjectURL file download. New sandbox_slot_list / sandbox_slot_saved / sandbox_slot_deleted listeners.
- initSandboxScreen: tries sandbox_load from localStorage (handle_sandbox_load auto-creates the session server-side), falls back to sandbox_create, then refreshes sandbox_list_slots.
- Share code uses TextEncoder + btoa + TextDecoder + atob. Verified `grep unescape\\(encodeURIComponent|decodeURIComponent\\(escape` is empty.
- Cheat inputs bind blur + keydown Enter only (verified: no `addEventListener('input',` call inside the cheat-input binding).
- NO flip/view-toggle/perspective-swap UI added. Verified `awk '/SANDBOX-SECTION-START/,/SANDBOX-SECTION-END/' | grep -iE 'flip|view-toggle|perspective.swap'` empty.
- view_filter.py byte-unchanged.
- Only one `socket.emit('submit_action'` in the file (verified by grep -c = 1).
- `node -c` passes.
- 62 sandbox backend tests + 15 pvp_server tests all green; no regressions.
Auto-fixed 4 deviations in 14.6-03: (1) sandbox pile access surfaced via renderSandboxStats pile-open buttons instead of adding a parallel pile bar, (2) showPileModal sandboxCtx arg added additively instead of forking a sandbox-only viewer, (3) initSandboxScreen restore path collapsed to single sandbox_load (avoids double-create race), (4) #screen-sandbox .sandbox-toolbar CSS flipped to flex-direction: column so the 4 rows stack vertically. Phase 14.5 (piles-and-hand-vis), 14.4 (spectator-mode), 14.6-01 (backend surface), 14.6-02 (frontend scaffold) remain fully shipped.

### Phase 14.6 closeout (2026-04-11)

Plan 04 delivered the Playwright E2E coverage, UAT (satisfied via automated tests per user directive "proceed if passed"), and ROADMAP/STATE/REQUIREMENTS closeout. Commit trail:

- 099113c test(14.6-04): Playwright E2E smoke test (Task 1 — initial 10-test file)
- ca09eae fix(14.6): rebuild sandbox screen to mirror live game layout (orchestrator repair — 3 stacked bugs from Plan 14.6-02)
- baa239e test(14.6): rewrite 5-test e2e suite for new DOM (orchestrator repair — 5 tests of increasing complexity, all green)

The orchestrator repair happened after Task 1 returned the UAT checkpoint. User reported the sandbox screen was visually broken; investigation surfaced 3 stacked bugs in Plan 14.6-02: (a) `.sandbox-container { height: 100% }` of a `.screen { display: block }` with no height collapsed; (b) `#sandbox-board` had only class `sandbox-board`, so `.game-board` grid CSS never applied AND `#screen-sandbox .sandbox-board { display: flex }` actively overrode any grid layout — renderBoard's 25 cells had no layout; (c) `#pileModal` was nested inside `#screen-game`, so opening a pile from the sandbox was impossible (ancestor display:none). User then directed: "make the sandbox screen look identical to the play screen but instead of the chat tab we have the sandbox control tab." Commit ca09eae rebuilt #screen-sandbox to mirror #screen-game's `.game-layout` 3-column grid exactly — same `.game-main` middle column (room-bar, P2 info-bar, P2 hand face-up, 5x5 board, P1 info-bar, P1 hand), same `.game-sidebar` right column but holding the sandbox toolbar instead of Log/Chat.

**This INVERTS the original Phase 14.6 CONTEXT D1 decision.** D1 specified "P1 hand on TOP, P2 hand on BOTTOM" as the fixed god-view layout. The final shipped layout puts P2 (opponent seat) on top and P1 (self seat) on bottom — matching the live play screen's god-view layout. The layout remains FIXED (no flip/view-toggle button, no perspective-swap control) and both hands are face-up (still full god view). Rationale for override: user wanted visual consistency with the live play screen so the sandbox reads as a superset of the normal game UI rather than a parallel layout. The Playwright test `test_sandbox_layout_is_fixed_god_view` asserts `#sandbox-hand-p0.y < #sandbox-board.y < #sandbox-hand-p1.y` — i.e. P1 above the board, P2 below — which contradicts the earlier D1 text but matches the final DOM mount ordering. DOM mount IDs were kept (#sandbox-hand-p0 = P1, #sandbox-hand-p1 = P2) even though visual positioning via the `.game-main` grid reverses them. Plaintext rule: the DOM mount's `data-player` attribute is authoritative for which player's hand renders where.

Playwright suite (`tests/e2e/test_sandbox_smoke.py`) — 5 tests of increasing complexity, all pass in 10.9s against localhost:5000:
1. `test_sandbox_screen_renders` — DEV-01: sandbox tab opens, toolbar + search + zone select + slot name inputs visible, both hands empty.
2. `test_sandbox_layout_is_fixed_god_view` — DEV-01: DOM vertical ordering asserts fixed god view, no flip button anywhere.
3. `test_sandbox_search_and_add_to_hand` — DEV-02: search → click result → P1 Hand 1, P2 Hand 0 (per-player-row assertion).
4. `test_sandbox_cheat_mana` — DEV-06: cheat input commits mana to 9, P1 Mana 9 reflected in stats row.
5. `test_sandbox_server_slot_roundtrip` — DEV-08: save named slot → list → load → delete round trip via Socket.IO.

Audits (both PASS):
- `git diff bee1aad..HEAD -- src/grid_tactics/server/view_filter.py` → empty (byte-unchanged across the entire phase).
- `git ls-files data/sandbox_saves/` → exactly `data/sandbox_saves/.gitkeep`. `.gitignore` contains `data/sandbox_saves/*` and `!data/sandbox_saves/.gitkeep`.

All 9 roadmap success criteria PASS. DEV-01 through DEV-09 marked Complete in REQUIREMENTS.md traceability table. Phase 14.6 marked `[x]` complete (2026-04-11) in ROADMAP.md with 4/4 plans.

Last activity: 2026-04-18 — Completed 14.7-04-PLAN.md (Summon compound react windows: _deploy_minion pushes summon_declaration originator, Window A resolves → land minion + open Window B iff ON_SUMMON effects, Window B resolves → fire ON_SUMMON via magic_cast-pattern dispatch. Harsh Window A negate, soft Window B negate. Pending-modal hand-off fixes latent 14.7-01 Ratmobile-tutor-during-react turn-advance bug. 6 Summon: minion JSONs flow correctly; minion ON_PLAY triggers orphaned.). Previous: 14.7-03 (Start/End/Summon triggered effects pipeline), 14.7-02 (3-phase turn state machine), 14.7-01 (Deferred magic resolution).

Progress: [░░░░░░░░░░] 0%

### Phase 14.7 Plan 02 closeout (2026-04-18)

Plan 14.7-02 shipped as the second plan of Phase 14.7 — pure state-machine wiring for the 3-phase turn model. No observable behavior change today; all pre-14.7 call paths still hit the legacy AFTER_ACTION → turn-advance path via react_return_phase=None defaulting. Commit trail:

- d2e6303 feat(14.7-02): add TurnPhase.START_OF_TURN/END_OF_TURN + ReactContext enum (Task 1)
- d842ab7 feat(14.7-02): wire 3-phase turn state machine + react_return_phase dispatch (Task 2)

Both commits pushed to master; Railway auto-deployed. The placeholder enter_start_of_turn / enter_end_of_turn helpers give 14.7-03 clean hook points for ON_START_OF_TURN / ON_END_OF_TURN trigger firing and REACT window opening. The _close_end_of_turn_and_flip helper deduplicated the turn-advance tail between resolve_react_stack and the pending_death_target resume path — 14.7-03's tail redistribution (moving burn-tick / passive into enter_start_of_turn) will only need to touch one place.

Test posture: 727+16 = 743 non-RL tests pass. Pre-existing baseline failures at 6 (unchanged):
- 1 spectator (test_events::test_spectator_receives_state_update)
- 4 LEAP game_loop (test_run_game_different_seeds, test_win_via_low_hp_game, test_both_players_can_win, test_smoke_1000_games)
- 1 RL self_play (test_random_opponent_plays_legal — ActionType 14 unrecognized; predates 14.7)

Reusable infrastructure for later 14.7 plans:
- 14.7-03: enter_start_of_turn / enter_end_of_turn placeholder bodies get real trigger-firing + REACT opening. Callers don't change.
- 14.7-03: ReactContext already has AFTER_START_TRIGGER + BEFORE_END_OF_TURN members — 14.7-03 just uses them.
- 14.7-03: React windows from start/end triggers set react_return_phase=START_OF_TURN / END_OF_TURN; resolve_react_stack already routes correctly.
- 14.7-04 (summon compound windows): ReactContext.AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT already reserved.

### Phase 14.7 Plan 03 closeout (2026-04-18)

Plan 14.7-03 shipped as the third plan of Phase 14.7 — Start/End/Summon triggered effects pipeline. First plan of the phase that produces observable gameplay changes (prior plans were pure infrastructure). Commit trail:

- b9e5af2 feat(14.7-03): add ON_SUMMON/ON_START_OF_TURN/ON_END_OF_TURN triggers + retag 9 cards (Task 1)
- 4dca00b feat(14.7-03): wire Start/End trigger firing + react windows + advance_to_next_turn (Task 2)

Both commits pushed to master; Railway auto-deployed. The 14.7-02 placeholder helpers (enter_start_of_turn, enter_end_of_turn) are now populated with real trigger firing + REACT window opening. Shortcut-when-no-triggers policy (only open a REACT window when triggers fire) kept the ~40 direct resolve_react_stack test callers passing without xfails.

Observable gameplay impact:
- Fallen Paladin now heals 2🤍 at its owner's turn start (was "end of turn" semantically, but rules wording already matched)
- Emberplague Rat applies is_burning to adjacent enemies at its owner's turn end (was firing at owner's turn start; rules text said "end of turn" so flavor-code alignment fixed)
- Dark Matter Battery deals damage-equal-to-its-DM-stacks to opponent at its owner's turn end (was "end of turn" flavor already; code alignment fixed)
- 6 Summon: minions (Diodebots tutor + Eclipse Shade self-burn + Flame Wyrm draw + Gargoyle Sorceress buffs) retagged on_play -> on_summon. Behavior preserved through a one-line bridge in _deploy_minion that fires both ON_PLAY and ON_SUMMON. 14.7-04 replaces the bridge with compound two-window dispatch.

Data/code symmetry audit:
- No card JSON uses `trigger: "passive"` anymore (grep verified empty).
- TriggerType.PASSIVE kept in the enum and _fire_passive_effects kept as a LEGACY no-op in case a future card re-introduces the trigger.
- GLOSSARY.md and game.js KEYWORD_GLOSSARY already had Start:/End:/Summon: entries in lock-step (added in earlier plan work per CLAUDE.md sync convention). No edits required.

Test posture: 745 non-RL tests pass (up from 727 pre-plan). Baseline failures unchanged at 10 (1 spectator + 4 LEAP game_loop + 1 RL self-play + 4 tensor engine parity — all pre-existing and predating 14.7). Added 22 new tests (+1 enums, +10 card_loader, +11 react_stack).

Reusable infrastructure for later 14.7 plans:
- 14.7-04 (summon compound windows): 6 Summon: minion JSONs already retagged on_summon. ReactContext.AFTER_SUMMON_DECLARATION/AFTER_SUMMON_EFFECT reserved since 14.7-02. `_deploy_minion` bridge provides a well-isolated single site for 14.7-04 to replace with the two-window handler.
- 14.7-05 (simultaneous priority + modal): fire_start_of_turn_triggers / fire_end_of_turn_triggers use (row, col) ordering today; 14.7-05 replaces with priority queue + modal for multi-owner simultaneous triggers.
- 14.7-06 (fizzle rule): triggers resolve blindly today; 14.7-06 adds fizzle checks inside fire_*_triggers helpers.
- 14.7-07 (react condition matching): shortcut-when-no-triggers gate (`_has_triggers_for`) is the clean extension point — 14.7-07 will also return True when opponent has react cards matching OPPONENT_START_OF_TURN / OPPONENT_END_OF_TURN.

### Phase 14.7 Plan 04 closeout (2026-04-18)

Plan 14.7-04 shipped as the fourth plan of Phase 14.7 — summon compound react windows (spec §4.2). Replaces the temporary 14.7-03 `_deploy_minion` bridge that fired both ON_PLAY and ON_SUMMON at deploy time. Commit trail:

- 8b093af feat(14.7-04): compound summon windows (declaration + effect) — Task 1
- 7639986 test(14.7-04): integration coverage + random-games regression + sandbox round trip — Task 2

Both commits pushed to master; Railway auto-deployed.

Observable gameplay impact:
- Deploying a minion now opens TWO sequential react windows. Window A is the declaration react (AFTER_SUMMON_DECLARATION): opponent can play a react that negates the summon entirely. Negate = mana + discard + destroy-ally costs are FORFEIT and the minion does NOT land (harsh by design per spec §4.2 / key_user_decisions #2). Window B is the on-summon-effect react (AFTER_SUMMON_EFFECT): opponent can negate the effect only; minion stays on the board if negated.
- All 6 retagged Summon: minions flow correctly through the new pipeline: 3 Diodebots (tutor chain — Blue → Red → Green), Eclipse Shade (self-burn), Flame Wyrm (draw), Gargoyle Sorceress (buff_attack + buff_health share ONE Window B).
- A minion with NO on_summon effects opens only Window A (no redundant dead-air Window B).
- The `_deploy_minion` bridge from 14.7-03 is GONE: minion ON_PLAY triggers are now orphaned. Only ON_SUMMON fires through the compound pipeline. Grep verified no real card uses trigger=on_play on a minion.

Engine changes:
- `_deploy_minion` pushes a `summon_declaration` originator onto state.react_stack and sets phase=REACT, react_context=AFTER_SUMMON_DECLARATION, react_return_phase=ACTION. Minion does NOT land here.
- New helpers in react_stack.py: `resolve_summon_declaration_originator` (lands minion + pushes Window B if ON_SUMMON effects) and `resolve_summon_effect_originator` (fires ON_SUMMON effects via the same TUTOR/REVIVE/regular dispatch as magic_cast).
- `resolve_react_stack` extended with: (a) pre-resolution stack-identity snapshot for compound-window hand-off, (b) summon_declaration / summon_effect originator dispatch branches, (c) compound-window early-return check (stack replaced + phase=REACT + originator present → return state as-is so Window B opens for opponent), (d) pending-modal hand-off (TUTOR/REVIVE set pending state → close react window in ACTION phase without turn-advance).

Side-effect bug fix — 14.7-01 pending-modal-during-react:
- Pre-14.7-04: when a magic_cast originator's TUTOR fired during stack resolution (e.g. Ratmobile's tutor), the pending_tutor state was set BUT the turn still advanced to P2 before the caster picked their tutor target. The pending_tutor gate in resolve_action caught it anyway (phase-agnostic), but the active_player_idx was wrong. The Window B flow exposed this because phase=REACT blocked TUTOR_SELECT routing entirely.
- Fix (reused for both): resolve_react_stack's post-LIFO pending-modal check now returns phase=ACTION with react bookkeeping cleared WITHOUT turn-advance. Modal owner is the correct next decision-maker.

resolve_action early-return fix:
- The terminal AFTER_ACTION REACT transition at the end of resolve_action was overwriting `_deploy_minion`'s inline react_context=AFTER_SUMMON_DECLARATION. Now it short-circuits when state.phase is already REACT.

Test posture:
- 784 non-RL tests pass (up from 745 for 14.7-03).
- Baseline failures unchanged at 10 (1 spectator + 4 LEAP game_loop + 1 RL self-play + 4 tensor engine parity — all pre-existing, predating 14.7).
- 6 existing action_resolver deploy tests updated to drain Window A (PASS) before asserting on the landed minion; `test_on_play_effect_triggers_after_deploy` updated to pin the new reality that minion ON_PLAY is orphaned.
- New coverage: +7 unit tests (TestSummonCompoundWindows in test_react_stack.py — window-A-opens, negate-forfeits-cost, pass-lands+opens-B, window-B-negate-preserves-minion, no-on-summon-skips-B, Gargoyle compound-effects-together, to/from_dict round trip), +4 integration tests + +1 random-games regression (TestSummonCompoundWindowsIntegration + TestRandomGamesDoNotCrash in test_integration.py — Diodebot full tutor flow, Prohibition-on-A negates everything, Prohibition-on-B preserves minion, Eclipse Shade self-burn, 30-seed random agent), +2 sandbox slot round-trip tests (Window A + Window B state survives save/load).

Reusable infrastructure for later 14.7 plans:
- 14.7-05 (simultaneous priority + modal): Gargoyle Sorceress's two ON_SUMMON effects are the prototype for multi-effect Window B. Current code resolves them in JSON order via `effect_payload` tuple iteration inside `resolve_summon_effect_originator`. 14.7-05 replaces with priority-queue modal picker.
- 14.7-06 (fizzle rule): two explicit fizzle markers already in place — "cell no longer empty mid-chain" in `resolve_summon_declaration_originator` + "source minion died between declaration and effect" in `resolve_summon_effect_originator`. 14.7-06 formalizes these per §7.
- 14.7-07 (OPPONENT_SUMMONS_MINION react condition): ReactContext.AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT already drive REACT windows; ReactEntry.source_minion_id already carries the summoner's instance_id. 14.7-07 only needs to add the ReactCondition enum value and the matching predicate.
- 14.7-10 (test migration): the "play minion + PASS-PASS through Window A+B" test template in TestSummonCompoundWindowsIntegration is the reference pattern.

Non-goals / limits documented by this plan:
- Death is NOT compound in this plan. Existing pending_death_queue + modal semantics unchanged. If user experience surfaces a need, 14.7-07 may add OPPONENT_DEATH_EFFECT as a react condition.
- Tensor engine remains on hold (per CLAUDE.md).
- test_game_flow.py suite exhibits pre-existing flakiness when run as part of the full suite (1–3 failures depending on run; always passes in isolation). Likely Socket.IO test-client state between parallel Flask apps. Not blocking; predates 14.7-04.

### Phase 14.7 Plan 01 closeout (2026-04-18)

Plan 14.7-01 shipped as the first plan of Phase 14.7 — the broader Turn Structure Overhaul. This plan was pulled ahead and delivered as an INDEPENDENTLY SHIPPABLE fix per user directive (the Acidic Rain bug has been biting them repeatedly). Commit trail:

- 6592857 feat(14.7-01): defer magic ON_PLAY effects via cast_mode originator (Task 1)
- 855c962 test(14.7-01): add Acidic-Rain-vs-Prohibition integration coverage (Task 2)

Both commits pushed to master; Railway auto-deployed. The originator pattern established here is re-usable by future 14.7 plans:
- 14.7-02 (start-of-turn/end-of-turn react windows) — reuses `origin_kind` field with new values "start_of_turn" / "end_of_turn"
- 14.7-04 (summon compound windows) — reuses `source_minion_id` field to carry the summoning minion
- 14.7-10 (test migration) — reuses the "cast + originator-on-stack + PASS-resolves" test template

Test posture: 727 non-RL tests pass; 5 pre-existing baseline failures remain untouched (4 LEAP-related in test_game_loop, 1 spectator in test_events). Full plan-verification set (153 tests) all green.

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
| Phase 14.6-sandbox-mode P01 | ~25min | 4 tasks | 8 files |
| Phase 14.6-sandbox-mode P02 | ~20min | 2 tasks | 3 files |
| Phase 14.6-sandbox-mode P03 | ~30min | 2 tasks | 3 files |
| Phase 14.7-turn-structure-overhaul P01 | ~45min | 2 tasks | 5 files |
| Phase 14.7-turn-structure-overhaul P02 | ~30min | 2 tasks | 7 files |
| Phase 14.7-turn-structure-overhaul P03 | ~45min | 2 tasks | 11 files |
| Phase 14.7-turn-structure-overhaul P04 | ~50min | 2 tasks | 6 files |

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
- [Phase 14.3-02]: Summon animation = 600ms scale-in (2x→1x, springy cubic-bezier) + 350ms grid shake. animatingTiles registry { "r,c": kind } is the Wave 3/4 reuse target; renderBoard tags .board-cell with anim-<kind> generically.
- [Phase 14.3-02]: runQueue gained a job.stateApplied opt-out flag. Animations that need the new state visible during the animation (summon) call applyStateFrame themselves and set the flag; animations that need the old state to persist (future attack) leave the flag false and let runQueue apply post-animation.
- [Phase 14.3-02]: deriveAnimationJob for PLAY_CARD now verifies a minion actually appeared at pa.position in next.minions before emitting 'summon'. Guards magic-with-position cards from being misclassified.
- [Phase 14.3-02]: Last session: 2026-04-07T15:55:00.000Z — Stopped at: Completed 14.3-02-PLAN.md (summon animation). Next: 14.3-03 move animation.
- [Phase 14.3-04]: Damage/killed info is server-authoritative via last_action payload (view_filter.enrich_last_action), computed from (prev_state, new_state, action). Client never diffs minion HP. Schema: {type, attacker_pos, target_pos, damage, killed}.
- [Phase 14.3-04]: Attack animation does NOT set job.stateApplied — runQueue's default applyStateFrame fires after done(), guaranteeing killed minions disappear AFTER the strike, never before. (Opposite of summon, which applies state at start.)
- [Phase 14.3-04]: Animate the inner .board-minion element (not .board-cell) so cell borders/highlights stay put while the minion lunges. Strike delta is 0.7*vector (lands on target edge), pullback is -0.3*vector.
- [Phase 14.3-04]: deriveAnimationJob branches on last_action.type === 'ATTACK' first; falls back to pending_action diff for summon/move/early frames. Keeps Wave 2 summon path intact.
- [Phase 14.3-04]: Wave 3 (move animation) and Wave 4 (attack) were executed out of dependency order — 14.3-04 only depends on 14.3-01, not 14.3-03.
- [Phase 14.3-03]: Move animation applies state MID-flight (PHASE C) via job.stateApplied=true, same opt-out pattern as summon and OPPOSITE of attack. Source tile is the original DOM .board-minion node lifted+translated; PHASE C re-renders the board so source clears and destination fills atomically at the moment of landing.
- [Phase 14.3-03]: animatingTiles[destKey] = 'move-drop' is set BEFORE applyStateFrame so the freshly-rendered destination .board-cell picks up .anim-move-drop on first paint. The drop is a CSS @keyframes (not a transition) so it fires reliably on a brand-new DOM node.
- [Phase 14.3-03]: getTileDelta(fromPos, toPos) extracted as shared helper returning {dx,dy,fromCell,toCell}. Reusable for any future pos-to-pos animation. Wave 4 attack predates this and still inlines getBoundingClientRect math — left untouched to avoid retrofitting shipped code.
- [Phase 14.3-03]: deriveAnimationJob prefers last_action.type==='MOVE' (server-authoritative attacker_pos/target_pos from enrich_last_action) before falling back to pending_action.source_position/target_position diff. Mirrors the ATTACK precedence added in 14.3-04.
- [Phase 14.3-07]: Single popup pathway — showFloatingPopup(tileEl, text, variant) with 5 variants (combat-damage / heal / burn-tick / buff / debuff). Wave 4's inline .damage-popup is replaced; combat damage now routes through showFloatingPopup with the '⚔️ -X' glyph.
- [Phase 14.3-07]: Heal + burn-tick popups fire from a prev/next minion HP diff at the TOP of applyStateFrame (before gameState mutation). Heal = any current_health increase; burn-tick = HP decrease AND prev.active_player_idx !== next.active_player_idx AND prev.burning_stacks > 0. Matches the engine tick semantics from 14.3-06.
- [Phase 14.3-07]: Burn-tick popup anchors to the PREV tile (via getTileElForMinion(prevMinion)) so lethal burns still show the number before renderGame removes the minion.
- [Phase 14.3-07]: Persistent badges (🔥 / ⬆️+N / ⬇️-N) live as innerHTML inside renderBoardMinion's returned string, not appended post-hoc to the cell — matches the existing string-build style and survives renderBoard re-renders without DOM tracking.
- [Phase 14.3-07]: Luckiest Guy loaded via Google Fonts <link> in <head>; applied ONLY to .floating-popup. body font is unchanged.
- [Phase 14.3-07]: Recipe for new status popup = 1 CSS variant + 1 diff hook in applyStateFrame. No queue, animation infra, or render surgery needed. Phase 14.3 grew from 5 plans to 7 (waves 6 burning + 7 popups added mid-phase); Wave 5 closeout still owes a STATE.md/ROADMAP.md amendment.
- [Phase 14.3-07]: Task 4 visual verification deferred to post-deploy Playwright E2E against Railway (same posture as 14.1-04 / 14.2-04 / 14.3-01 / 14.3-04).
- [Phase 14.3-05]: Phase 14.1 melee move+attack chain ALREADY chains naturally — no client code changes needed. The melee chain submits as TWO sequential server actions (MOVE then ATTACK) per the 14.1 design (one logical action via pending_post_move_attacker_id, one react window). Each action emits its own state_update frame with its own last_action, so the existing AnimationQueue plays move-animation then attack-animation in order with no synthesis. Plan's Option A (client-side intermediate state) and Option B (server pre_attack_pos) are unnecessary.
- [Phase 14.3-05]: Phase 14.3 grew from the planned 5 plans to 7 mid-execution (waves 6 burning + 7 popups inserted). Wave 5 (this closeout) landed last. ROADMAP and STATE now reflect 7/7. Future-server contract: view_filter.enrich_last_action's `last_action` field (added Wave 4) is part of the client animation contract — preserve attacker_pos / target_pos / damage / killed schema.
- [Phase 14.3-05]: Phase 14.3 client-side AnimationQueue is now the single point of state application; all pending UIs (react window, tutor modal from 14.2, post-move-attack picker from 14.1) gate STRUCTURALLY behind queue drain via applyStateFrame — no explicit isAnimating() guards needed.
- [Phase 14.3-05]: Task 3 (visual smoke test) deferred to post-deploy Playwright E2E against Railway (same posture as 14.1-04 / 14.2-04 / 14.3-01 / 14.3-04 / 14.3-07).
- [Phase 14.4]: Spectator mode locked: god-mode optional (per-spectator, not per-room), perspective fixed to Player 1 in non-god mode (perspective toggle deferred), mid-game join supported via synthetic game_start, multi-spectator per room supported, spectators chat into the main room (no separate spectator-only channel).
- [Phase 14.4-01]: Spectator storage = RoomManager._room_spectators manager-level dict (NOT on WaitingRoom or GameSession) — survives start_game's WaitingRoom pop without touching either dataclass. _token_role classifies any token as 'player' | 'spectator'.
- [Phase 14.4-02]: filter_state_for_spectator is a PURE function in view_filter.py — no room_manager coupling. god_mode=True deep-copies full state; non-god delegates to filter_state_for_player(perspective_idx=0) inheriting opponent-hand stripping + deck hiding + seed removal. Always stamps is_spectator / spectator_god_mode / spectator_perspective top-level flags.
- [Phase 14.4-03]: Spectator state fanout via dedicated helpers (_fanout_state_to_spectators / _fanout_game_start_to_spectators) called from existing player-emit paths. Action gating done at the TOP of submit_action (before room/session lookup) so the error is unambiguous. Disconnect handler ONLY cleans spectators — player-sid churn is Phase 15 territory. Spectator payload mirrors player schema (state, legal_actions=[], your_player_idx=0) plus is_spectator:True discriminator so the client reuses its state_update reducer.
- [Phase 14.4-04]: Client routes spectators through the existing applyStateFrame → renderGame pipeline (NOT a separate renderSpectatorView branch) — preserves Phase 14.3 animation contract for free. isSpectator + spectatorGodMode re-synced from every frame (onSpectatorJoined + onGameStart + _applyStateFrameImmediate) — reconnection/late-join safe, no drift. Dual-hand god view reuses renderHandCard verbatim with labeled dividers (no new DOM container). renderHandCard(..., isMyTurn && !isSpectator) prevents "my turn" glow leaking onto spectator hands.
- [Phase 14.4-05]: Task 4 (multi-tab visual smoke test) deferred to post-deploy Playwright E2E against Railway (same posture as prior 14.x closeouts). Automated coverage = tests/test_room_manager.py (8 tests, always run) + tests/test_events.py (6 tests, gated on flask_socketio via conftest collect_ignore_glob).

### Phase 14.7 Plan 02 — 3-phase turn state machine (2026-04-18)

- d2e6303 feat(14.7-02): add TurnPhase.START_OF_TURN/END_OF_TURN + ReactContext enum
- d842ab7 feat(14.7-02): wire 3-phase turn state machine + react_return_phase dispatch

Key decisions:
- [Phase 14.7-02]: TurnPhase extended append-only (START_OF_TURN=2, END_OF_TURN=3). ACTION=0 / REACT=1 pinned so numpy/tensor int encodings stay stable even though tensor engine is on hold.
- [Phase 14.7-02]: ReactContext is a SEPARATE IntEnum from TurnPhase. Six values: AFTER_START_TRIGGER=0, AFTER_ACTION=1, AFTER_SUMMON_DECLARATION=2, AFTER_SUMMON_EFFECT=3, AFTER_DEATH_EFFECT=4, BEFORE_END_OF_TURN=5. Phase and context are orthogonal — a REACT window can open in many contexts. Conflating them onto TurnPhase would muddle concerns.
- [Phase 14.7-02]: GameState gains react_context + react_return_phase (both Optional, default None). Full to_dict/from_dict round-trip with legacy-dict-compat (older dicts without these keys load as None via `d.get("react_context")`).
- [Phase 14.7-02]: react_return_phase=None defaults to TurnPhase.ACTION in resolve_react_stack. This preserves byte-identical pre-14.7 behavior at every call site that doesn't set the field. Backward compat is a DEFAULT, not an if-branch.
- [Phase 14.7-02]: Four phase-transition helpers exported from react_stack.py: enter_start_of_turn, enter_end_of_turn, close_start_react_and_enter_action, close_end_react_and_advance_turn. enter_start_of_turn / enter_end_of_turn are PLACEHOLDERS in 14.7-02 (pass straight through). 14.7-03 hooks trigger firing + REACT opening BETWEEN the phase flip and the passthrough — callers don't change.
- [Phase 14.7-02]: _close_end_of_turn_and_flip helper is THE single source of truth for the end-of-turn tail (discard flip + active-player flip + turn increment + tick_status_effects + _fire_passive_effects + mana regen + auto-draw). resolve_react_stack's main path and the pending_death_target resume path in action_resolver.py now share this helper. 14.7-03's redistribution of burn-tick / passive into enter_start_of_turn touches only this one function.
- [Phase 14.7-02]: All 6 `phase=TurnPhase.REACT` sites in action_resolver.py now tag react_context=AFTER_ACTION / react_return_phase=ACTION uniformly. Sites: _cast_magic originator push (L665), pending_death_target resume ACTION branch (L1441), conjure_deploy post-action opener (L1572), tutor-resolve opener (L1712), melee post-move opener (L1780), generic after-action opener (L1858).
- [Phase 14.7-02]: legal_actions returns () for START_OF_TURN / END_OF_TURN. events.py submit_action auto-advance loop INTERCEPTS those phases at the loop boundary and calls the helpers directly. resolve_action does NOT accept START/END phase inputs (would raise ValueError). Safety counter AUTO_ADVANCE_MAX=50 catches infinite-loop regressions; today's 14.7-02 never iterates more than 2-3 times per turn.
- [Phase 14.7-02]: Rule-1 bug fix captured inside _close_end_of_turn_and_flip: the OLD main resolve_react_stack tail silently skipped the discarded_this_turn → discarded_last_turn flip for the outgoing player; the pending_death_target resume path DID flip it. Centralizing fixed this silently. Prohibition's discarded_last_turn gate is the only reader — now gets consistent data regardless of which tail path ran.
- [Phase 14.7-02]: view_filter.py BYTE-UNCHANGED. Confirmed via grep. filter_state_for_player uses copy.deepcopy on to_dict output so new int fields (react_context / react_return_phase) flow through transparently, same as any phase/turn_number-style int.
- [Phase 14.7-02]: test_react_stack gained 12 new tests in 5 classes: TurnPhaseNewValues (2), ReactReturnPhaseDispatch (3 — None default / START / END), PhaseTransitionHelpers (4 — one per helper), ActionResolverSetsReactContext (1 — magic cast via acidic_rain), LegalActionsStartEndPhases (2 — START / END empty). test_enums gained +5 tests, test_game_state gained +4. All green.

### Phase 14.7 Plan 04 — Summon compound react windows (2026-04-18)

- 8b093af feat(14.7-04): compound summon windows (declaration + effect)
- 7639986 test(14.7-04): integration coverage + random-games regression + sandbox round trip

Key decisions:
- [Phase 14.7-04]: Minion deployment is now a COMPOUND two-window event. Window A (AFTER_SUMMON_DECLARATION) opens immediately after _deploy_minion validates; negate = mana + discard + destroy-ally costs all FORFEIT, minion does NOT land (spec §4.2 harsh-by-design, pinned by test_summon_window_a_negate_loses_cost_and_summon). Window B (AFTER_SUMMON_EFFECT) opens after the minion lands iff it has any ON_SUMMON effects; negate = effect cancelled but minion STAYS on board (pinned by test_summon_window_b_negate_cancels_effect_not_minion). No dead-air Window B for minions without on-summon effects.
- [Phase 14.7-04]: Chose the 14.7-01 ReactEntry originator pattern over a separate `pending_sub_actions` field (RESEARCH §4 option A). One queue, re-uses serializer, composes naturally with LIFO NEGATE. Documented deviation from RESEARCH §4 in this plan's SUMMARY.
- [Phase 14.7-04]: `origin_kind` gets two new string values: "summon_declaration" (Window A) + "summon_effect" (Window B). Both flow through the same to_dict/from_dict path as magic_cast; zero schema changes.
- [Phase 14.7-04]: Stack-identity snapshot (`_pre_resolution_stack = state.react_stack`) is the Window A → Window B hand-off signal. `resolve_summon_declaration_originator` RESETS state.react_stack to a fresh (summon_effect,) tuple (LIFO loop already consumed the old entries). After the loop, resolve_react_stack compares `state.react_stack is not _pre_resolution_stack` and returns early if an originator is now on the stack. Locally scoped, avoids adding new GameState fields, survives tuple equality.
- [Phase 14.7-04]: Gargoyle Sorceress's two ON_SUMMON effects resolve under ONE Window B in JSON-order via the `effect_payload` tuple. 14.7-05 will layer a priority-queue modal picker on top for simultaneous-trigger edge cases — this plan's single-fire-per-window semantics are the baseline.
- [Phase 14.7-04]: Minion ON_PLAY triggers are ORPHANED. Only ON_SUMMON fires through the compound pipeline. No real card JSON currently uses trigger=on_play on a minion (grep-verified). Future minions that want on-deploy effects must tag ON_SUMMON.
- [Phase 14.7-04]: `resolve_action`'s terminal AFTER_ACTION REACT-transition block now short-circuits when state.phase is already REACT. Necessary because `_deploy_minion` (and `_cast_magic`) set their own react_context inline; without this guard, the outer block was clobbering AFTER_SUMMON_DECLARATION to AFTER_ACTION.
- [Phase 14.7-04]: Pending-modal hand-off added to resolve_react_stack. If originator resolution fires a TUTOR or REVIVE (sets pending_tutor_player_idx / pending_revive_player_idx), close the react window (phase=ACTION, clear react_stack + bookkeeping) WITHOUT turn-advance. Modal owner is the correct next decision-maker. Fixes a pre-14.7-04 latent 14.7-01 bug where Ratmobile-style magic tutors advanced the turn before the caster picked (the phase-agnostic pending_tutor gate in resolve_action caught actions but active_player_idx was wrong).
- [Phase 14.7-04]: 2 fizzle markers documented for 14.7-06: (a) `resolve_summon_declaration_originator` silently fizzles if the target cell is no longer empty by the time Window A resolves (another effect occupied it mid-chain), (b) `resolve_summon_effect_originator` falls back to `source_pos=(0,0)` if the source minion died between declaration and effect resolution. True §7 fizzle handling lands in 14.7-06.
- [Phase 14.7-04]: 6 deploy tests in test_action_resolver.py updated to drain Window A (PASS) before asserting on the landed minion. `test_on_play_effect_triggers_after_deploy` flipped its assertion to pin the new reality (minion ON_PLAY orphaned). No count change — behavior documentation only.
- [Phase 14.7-04]: Sandbox save/load round-trip tests synthesize Window A / B state directly via GameState.to_dict + SandboxSession.load_dict, then save-and-reload via the file-backed slot API. Chosen over driving apply_action because no current card has react_condition OPPONENT_PLAYS_MINION (lands in 14.7-07); sandbox auto-drain would close the window before snapshot. Serializer is the contract being tested.
- [Phase 14.7-04]: Test posture: 784 non-RL tests pass (up from 745). +7 unit tests (TestSummonCompoundWindows), +4 integration tests + +1 random-games regression (30-seed deterministic agent, 150 iterations each), +2 sandbox round-trip tests. Baseline failures unchanged at 10.

### Phase 14.7 Plan 01 — Deferred magic resolution (2026-04-18)

- 6592857 feat(14.7-01): defer magic ON_PLAY effects via cast_mode originator
- 855c962 test(14.7-01): add Acidic-Rain-vs-Prohibition integration coverage

Key decisions:
- [Phase 14.7-01]: Magic cast is now DEFERRED. Costs (mana/HP/destroy-ally/discard) resolve on play; ON_PLAY effects captured as a cast_mode originator at the BOTTOM of the react stack; chain resolves LIFO; Prohibition on top of the originator cancels the cast entirely (scorched-earth — mana is spent regardless, by design).
- [Phase 14.7-01]: ReactEntry gained 6 additive originator fields (`is_originator: bool`, `origin_kind: Optional[str]`, `source_minion_id: Optional[int]`, `effect_payload: Optional[tuple]`, `destroyed_attack: int`, `destroyed_dm: int`) — all default-valued for backward compat. Legacy react-entry construction in `_play_react` unchanged.
- [Phase 14.7-01]: `effect_payload` uses tuple-of-tuples (NOT dict) to keep the frozen dataclass hashable-friendly. Each entry is `(effect_idx, target_pos_or_None, caster_owner_int)`. Effect_idx indexes into `card_def.effects`, so the originator only needs the card_numeric_id + effect indices — no full effect objects stored.
- [Phase 14.7-01]: `origin_kind: Optional[str]` chose str-typed (not IntEnum) for extensibility. 14.7-02 will add "start_of_turn" / "end_of_turn"; 14.7-04 will add "summon_declaration". The sentinel `None` means "legacy react card" (no originator).
- [Phase 14.7-01]: `_cast_magic` sets `phase=REACT` and `react_player_idx=1-active` INSIDE the function. The subsequent unconditional phase transition at the end of `resolve_action` (action_resolver.py:1849-1853) does the same thing — no-op when reached, but `_cast_magic` is now self-contained so future refactors can't accidentally break it.
- [Phase 14.7-01]: NEGATE handling required ZERO code change in react_stack.py. The existing `negated_indices.add(i + 1)` at line 324 already handles originator cancellation correctly: when Prohibition sits atop a magic_cast originator, Prohibition appears at LIFO index 0, the originator at LIFO index 1, and `add(1)` negates the originator exactly as intended.
- [Phase 14.7-01]: view_filter.py is BYTE-UNCHANGED. Confirmed by reading the file: `filter_state_for_player` uses `copy.deepcopy(state_dict)` where state_dict is already produced by `to_dict()`; new ReactEntry fields flow through transparently for per-player filtering.
- [Phase 14.7-01]: legal_actions._react_phase_actions gained a docstring paragraph noting that `state.react_stack[0]` may now be a magic_cast originator, but has NO functional change. `_check_react_condition` treats the stack's most-recent entry uniformly, and an originator's card_def is MAGIC so OPPONENT_PLAYS_MAGIC matches it exactly (enables Prohibition).
- [Phase 14.7-01]: Scale_with bonus is captured at cast time on the originator (`destroyed_attack` + `destroyed_dm`) and re-applied during resolution. This matches the old inline `_cast_magic` semantics exactly — destroy-ally effects still benefit from the sacrificed minion's attack/DM even though the sacrifice already resolved before the react window opened.
- [Phase 14.7-01]: Test posture: 727 non-RL tests pass; 5 pre-existing baseline failures untouched (4 LEAP game_loop smoke, 1 spectator in test_events). `_play_to_completion` iteration cap bumped 500→1500 to accommodate deferred resolution (each magic cast now uses 2 loop iterations). Side-benefit: pre-existing `test_complete_game` at the 500 cap now passes too.

### Phase 14.5 Wave 4 (2026-04-08)

- 8788c43 refactor(14.5-04): extract shared renderCardFrame for hand/deck/tooltip

Key decisions:
- [Phase 14.5-04]: Single shared `renderCardFrame(c, opts)` HTML builder is the source of truth for all full-size card rendering. `renderDeckBuilderCard` and `renderHandCard` are thin wrappers (7 and 12 lines). Tooltip preview path already routed through `renderDeckBuilderCard`, inherits the refactor for free.
- [Phase 14.5-04]: Hand cards stamped with BOTH `.card-frame-full` (base layout) and `.card-frame-hand` (state-modifier hook). Keeps all existing state selectors working unchanged (`.card-playable`, `.card-selected-hand`, `.card-react-playable`, mobile width override). Dead `.card-frame-hand` base rule + `.card-art-hand` base rule deleted from CSS (verbatim duplicates of `.card-frame-full` / `.card-art-full`) to prevent silent drift.
- [Phase 14.5-04]: `showReactDeploy` opt-in flag preserves the original asymmetry — deck builder shows "▶ Deploy" hint for multi-purpose react cards, hand suppresses.
- [Phase 14.5-04]: Task 2 visual smoke test deferred to post-deploy Playwright E2E (same posture as 14.1-04 / 14.2-04 / 14.3-01/04/07 / 14.4-05). Structural review confirmed: data attrs preserved, context classes preserved, dim logic preserved, tooltip path preserved, mobile media query still valid.
- [Phase 14.5-07]: Phase 14.5 closeout — `from_deck` flag on MinionInstance gates graveyard population; tokens vanish silently on death. Exhaust pile introduced alongside graveyard for discard-for-cost mechanics (summon_sacrifice_tribe). Uniform card rendering via shared `renderCardFrame` — one source of truth for hand / deck builder / tooltip. Pile buttons are symmetric — both players see own and opponent ⚰️ / 🌀 with live counts and clickable modals. Draw animations triggered structurally via multiset hand diff in `onStateUpdate`, never per-action-site.
- [Phase 14.5-07]: Task 2 (multi-tab visual UAT) deferred to post-deploy Playwright E2E against Railway, same posture as every prior 14.x closeout.
- [Phase 14.6-01]: SandboxSession is the entire sandbox API — a thin per-tab harness that wraps the existing immutable engine. Every state mutator rebuilds frozen Player + GameState via dataclasses.replace (15 callsites). NO new state classes, NO copies of engine code, NO in-place mutation, NO RNG attribute on the session. apply_action validates via legal_actions() and resolves via resolve_action() — same engine the real game uses.
- [Phase 14.6-01]: Empty starting state built via _empty_state classmethod (Board.empty + Player.new(side, ())) — NOT GameState.new_game, which unconditionally draws STARTING_HAND_P1/P2 cards via Player.draw_card and crashes on empty decks (player.py:111-114).
- [Phase 14.6-01]: Five zones supported uniformly: hand / deck_top / deck_bottom / graveyard / exhaust. deck_top means index 0 (next-draw side) of Player.deck; deck_bottom means appended. Zone-as-attribute helper maps deck_top/deck_bottom → "deck", graveyard → "grave", hand/exhaust unchanged.
- [Phase 14.6-01]: set_player_field is FULL CHEAT MODE — validates field name against PLAYER_FIELDS allow-list (current_mana / max_mana / hp) but does NOT validate value against any game rule. Negative HP, 9999 mana, etc. all allowed. The whole point of sandbox is god-mode scratch space.
- [Phase 14.6-01]: undo_depth / redo_depth are PUBLIC read-only properties wrapping internal deques. HISTORY_MAX=64 satisfies DEV-09 (>=50). Whole-state snapshots stored (frozen dataclass references — no deep copy needed).
- [Phase 14.6-01]: Slot-name validation is exactly ONE regex (^[a-zA-Z0-9_-]{1,64}$) plus ONE os.path.basename identity check. NO sanitization library, NO Unicode normalization, NO retry. Bad names raise; user picks a different name. Slot persistence reuses to_dict / load_dict verbatim — NO new serialization format, NO schema migration code.
- [Phase 14.6-01]: RoomManager._sandboxes is a parallel dict keyed by SID (NOT session token). Sandboxes have no session-token concept — one per browser tab, no multi-user sharing. The dict + create/get/remove helpers are purely additive; existing room/game/spectator code paths byte-unchanged.
- [Phase 14.6-01]: Sandbox handlers NEVER call filter_state_for_player or filter_state_for_spectator — sandbox is god view always. _emit_sandbox_state is the single source of truth for state emission and reads sandbox.undo_depth / sandbox.redo_depth public properties only, never the underscore-prefixed deques.
- [Phase 14.6-01]: Legacy sandbox_add_card (hand-only) is REPLACED by sandbox_add_card_to_zone, NOT registered alongside. 16 sandbox_* handlers total: create, apply_action, add_card_to_zone, move_card, import_deck, set_player_field, set_active_player, undo, redo, reset, save, load, save_slot, load_slot, list_slots, delete_slot.
- [Phase 14.6-01]: Disconnect cleanup runs unconditionally for SID — sandbox users have no session token, so the prior token-gated early-return would have leaked sandboxes. Spectator path remains functionally identical (token-gated as before). Restructure documented as Rule 1 deviation in 14.6-01-SUMMARY.
- [Phase 14.6-01]: Tests live under tests/server/ subdirectory (new — existing repo is flat tests/). Used create_app(testing=True) instead of importing a non-existent global `app`, matching existing tests/test_pvp_server.py pattern. isolated_slot_dir fixture monkeypatches sandbox_session.SLOT_DIR to tmp_path so slot tests never touch the real data/sandbox_saves/.
- [Phase 14.6-01]: legal_actions does NOT include PASS unconditionally during ACTION phase despite the stale module docstring — fatigue bleed at the GameSession layer handles the no-actions case via auto-PASS in submit_action. Tests adapted to drive apply_action via the engine's legal_actions tuple (DRAW becomes legal once a deck card is seeded) rather than assuming PASS is always present.
- [Phase 14.6-02]: renderBoard/renderHand opts refactor is ADDITIVE and backward-compatible. Pattern: `function fn(opts) { opts = opts || {}; var target = opts.mount || document.getElementById('legacy-id'); var state = opts.state || gameState; var idx = (opts.perspectiveIdx != null) ? opts.perspectiveIdx : myPlayerIdx; ... }`. Every legacy zero-arg call site remains byte-identical. No signature change to any other render function.
- [Phase 14.6-02]: renderHand.opts.godView renders ONLY ownerIdx face-up (single-hand mount). The spectator dual-hand branch (isSpectator && spectatorGodMode) is UNCHANGED for the live-game spectator path — sandbox calls renderHand twice with distinct mounts instead of using a dual-hand code path.
- [Phase 14.6-02]: Global-swap pattern for screen-isolation. sandboxActivate snapshots 5 live globals (gameState, myPlayerIdx, legalActions, isSpectator, spectatorGodMode) + animatingTiles into _sandboxPreSnapshot, reassigns them to sandbox values, and sandboxDeactivate restores. The opts-refactored renderers take mount targets via opts so they render into sandbox DOM while the globals are sandbox-owned. Makes plan 14.6-03's click-handler reuse trivial — no 50+ global-read refactor needed.
- [Phase 14.6-02]: sandbox_card_defs is ADDITIVELY mirrored into both cardDefs AND allCardDefs. cardDefs is the primary render-time lookup (renderBoardMinion / renderHandCard read it); allCardDefs is only set when null. Plan originally mirrored only allCardDefs but renderers read from cardDefs — the additive merge (only set keys not already present) avoids both the missing-render bug and the stomping risk. Auto-fixed as Rule 2 deviation.
- [Phase 14.6-02]: Null-state guards added to renderBoard/renderHand opts path and to renderSandboxStats. The sandbox can fire renderSandbox between sandboxActivate and the first sandbox_state frame (Socket.IO ordering). Legacy zero-arg callers are unaffected because live-game code never renders before game_start. Auto-fixed as Rule 2 deviation.
- [Phase 14.6-02]: Anchor comments are CONTRACTUAL: // === SANDBOX-SECTION-START === (line 5017), // === SANDBOX-STATE-HANDLER-START === (line 5111), // === SANDBOX-STATE-HANDLER-END === (line 5127), // === SANDBOX-SECTION-END === (line 5209). Plan 14.6-03 greps these anchors for insertion points — line numbers will drift, anchors will not. Nested SANDBOX-STATE-HANDLER envelope lets 14.6-03 target the state handler specifically.
- [Phase 14.6-02]: Sandbox layout is FIXED at the DOM level: #sandbox-hand-p0 (P1) before #sandbox-board before #sandbox-hand-p1 (P2). No flip / view-toggle / perspective-swap controls exist anywhere. The plan 14.6-03 "Controlling: P1/P2" button mutates state.active_player_idx server-side; it does NOT change which DOM mount renders which player's hand.
- [Phase 14.6-02]: Browser smoke test performed via python-socketio client + curl against live pvp_server.py (Playwright MCP tool not available in this execution session). The round trip covers the full Flask + Socket.IO path a browser would exercise, validates the HP/mana/hand/deck/turn payload, and confirms the DOM markup served to clients. JS additionally validated via `node -c`.

### Pending Todos

None yet.

### Blockers/Concerns

- Known issue: RL checkpoints are now TRIPLY STALE — (1) 14.1/14.2 encoding reinterpretations (post-move-attack pending + tutor selector + pending_tutor slot reuse), (2) 8bd61e1 ACTION_SPACE_SIZE 1262→1287, (3) 14.5-02 tensor pile semantics (minion plays no longer added to graveyard on cast; exhaust pile introduced; tokens vanish silently via from_deck gate; new minion_from_deck + exhausts + exhaust_sizes GPU fields). Loadable but any observation derived from graveyard contents diverges silently. Retraining required before tournament/eval. Not blocking gameplay. **Confirmed at Phase 14.5 closeout (2026-04-08): retrain-or-continue-from-scratch decision belongs to next RL cycle.**
- Research flag: Phase 15 reconnection -- cookie vs localStorage, token expiry, and state resend edge cases may surface
- Research flag: Phase 15 timer cancellation -- start_background_task() cancellation is MEDIUM confidence per research
- Gap: Preset deck composition (card copy counts for 30-card deck) must be decided in Phase 11

## Session Continuity

Last session: 2026-04-18T23:00:00.000Z — Completed 14.7-04 (summon compound two-window dispatch: _deploy_minion pushes summon_declaration originator, Window A resolves → minion lands + Window B opens iff ON_SUMMON effects, Window B resolves → fires effects; harsh A-negate forfeits costs, soft B-negate preserves minion; latent 14.7-01 pending-modal-during-react bug fixed as side-effect; all 6 Summon: minion JSONs flow correctly). Previous: 2026-04-18T21:45:00.000Z — Completed 14.7-03 (Start/End/Summon triggered effects pipeline + react windows + advance_to_next_turn test helper). 14.7-02: 2026-04-18T18:48:00.000Z — 3-phase turn state machine. 14.7-01: 2026-04-18T18:15:00.000Z — Deferred magic resolution via cast_mode originator.
Stopped at: Plan 14.7-04 SHIPPED. Two commits (8b093af Task 1 feat + 7639986 Task 2 test) pushed to master; Railway auto-deployed. Compound summon two-window dispatch live: `summon_declaration` + `summon_effect` originator branches in resolve_react_stack, with stack-identity snapshot for Window A → Window B hand-off, and pending-modal hand-off for TUTOR/REVIVE fired during stack resolution. Test posture: 784 non-RL tests pass (up from 745 for 14.7-03); 10 baseline failures unchanged. Fizzle markers in place for 14.7-06 (cell occupied mid-chain, source minion died between windows). Hook points ready for 14.7-05 (Gargoyle Sorceress multi-effect Window B is the priority-picker insertion point), 14.7-07 (ReactContext values already distinguish Window A/B so new OPPONENT_SUMMONS_MINION condition just needs matching logic), and 14.7-10 (TestSummonCompoundWindowsIntegration is the reference test pattern). Next: 14.7-05 (simultaneous-trigger priority queue + modal picker for multi-owner Start: / End: / Summon: effects).

Previous session (2026-04-07T20:45:00.000Z): Card-effects-and-action-flow audit followups complete. Tensor-engine parity for LEAP (CardTable.leap_amount precompute + _compute_move_mask LEAP override + apply_move_batch leap landing) and PASSIVE pipeline (CardTable.passive_burn_amount/passive_heal_amount + engine._fire_passive_effects_batch at turn flip, mirroring Python react_stack._fire_passive_effects). Bug-4 design clarification: BURN handler now stacks `int(effect.amount)` per tick so Emberplague's JSON amount=5 takes effect; tensor side already uses passive_burn_amount from the same JSON field. ActionEncoder _encode_move/_decode_move now leap-aware (collapse multi-step forward to unit cardinal on encode, walk over blockers on decode). 42 stale-assertion test failures swept to zero — pure test maintenance, no engine behavior changes. tests/conftest.py grew collect_ignore_glob for RL/tensor/server test files when torch/sb3/flask_socketio missing (single source of truth for ML-dep gating). Final: 538 passed, 4 skipped, 0 failed locally. Next: Phase 15 Resilience & Polish.
Resume file: None

### Audit followup commits (2026-04-07)
- 91d157c fix(audit-followup): tensor LEAP parity + ActionEncoder leap-aware decode
- c60fda7 fix(audit-followup): tensor PASSIVE pipeline parity (burn aura + heal)
- c289bbd fix(audit-followup): BURN aura honors JSON amount (Bug 4 clarification)
- db40f9e test(audit-followup): sweep 42 stale assertions to match current engine

### Tensor parity + Dark Matter sweep (2026-04-08)

Greenfield sweep against the tensor engine with the Python engine as
source of truth. Inventory found that 4 of 7 brief items (burn boolean,
effective_attack==0 gate, PASSIVE pipeline owner-gate, LEAP) were
ALREADY implemented from prior audit followups. Cleared the remaining 3
+ added the Dark Matter source card.

Cleared debt:
- 69432ce fix(tensor): max_health_bonus + dark_matter_stacks tensor fields
  (HEAL caps now use card.health + max_health_bonus, mirroring Python
  _apply_heal_to_minion; both fields reset on game reset and on minion
  deploy; PASSIVE_HEAL also caps at the effective max)
- 8bd61e1 feat: ACTIVATE_ABILITY action space slots [1262:1287]
  (ACTION_SPACE_SIZE bumped 1262 → 1287; Python ActionEncoder gained
  encode/decode for ACTIVATE_ABILITY using activator pos; tensor engine
  gained apply_activate_ability_batch hardcoded Ratchanter dispatch
  + _compute_activate_ability_mask + CardTable is_rat / ratchanter_card_id
  / rat_card_id columns; engine wires the new dispatch in
  _step_action_phase. Test harness bumped to assert 1287.)
- 4254370 feat: Dark Matter Infusion magic card + GRANT_DARK_MATTER
  (2-mana DARK magic, single_target on_play, +1 dark_matter_stacks;
  EffectType.GRANT_DARK_MATTER = 16 append-only; Python and tensor
  effect handlers; closes the synergy loop with Ratchanter)

**RL checkpoint invalidation:** All RL checkpoints trained against the
prior 1262-slot action space are invalidated by 8bd61e1. They remain
loadable as binary blobs but the action head is the wrong shape. Plan
a fresh training run before resuming any tournament/eval work.

**Pre-existing checkpoint staleness from 14.1 / 14.2 (line 175 above)
still applies on top of this** — checkpoints predating both audits are
doubly stale.

Test posture: 573 passed, 4 skipped before and after each commit.
Tensor-specific tests are conftest-gated on torch/sb3 availability and
were not exercised in this sweep — that gating is unchanged. The new
Ratchanter / Dark Matter / max_health_bonus tensor paths therefore have
no direct unit tests yet; the existing Python ratchanter_aura and
activated_abilities tests cover the source-of-truth behavior.

### Phase 14.5 Wave 2 — tensor parity (2026-04-08)

- 5157016 feat(14.5-02): add from_deck + exhaust tensors to GPU state
- 9f284e5 feat(14.5-02): wire from_deck + exhaust through tensor play/death paths

Key decisions:
- [Phase 14.5-02]: TensorGameState gains `minion_from_deck` [N, MAX_MINIONS] bool, `exhausts` + `exhaust_sizes` [N, 2, MAX_GRAVEYARD] / [N, 2] int32. All three cleared in reset_batch, propagated by clone(), cleared on death-slot vacation.
- [Phase 14.5-02]: Default `minion_from_deck = False`, set True on every normal deploy. Chosen over default-True-set-False-on-token because there is no tensor token-spawn path today — False default is the safe baseline for any future token code path.
- [Phase 14.5-02]: `apply_play_card_batch` no longer unconditionally appends every play to the graveyard. Only magic plays (`ctype == 1`) route to graveyard on cast. Minion plays leave hand via remove-only and enter graveyard later via death cleanup gated on from_deck. Fixes the same double-count bug the Python engine had before Wave 1.
- [Phase 14.5-02]: Death cleanup clones `dead_from_deck` alongside the existing dead_* snapshots per cleanup pass and gates `is_p` on `slot_from_deck`. The snapshot (not live tensor) is needed because two-pass cleanup could race against slot reuse within the same pass.
- [Phase 14.5-02]: `_apply_summon_sacrifice_batch` routes discards through new `_add_to_exhaust_batch` helper instead of graveyard. On-board `apply_sacrifice_batch` also gates graveyard append on from_deck for symmetry (defensive — no token currently reaches the back row).
- [Phase 14.5-02]: react play path (`apply_react_batch`) and Ratchanter activate path (`apply_activate_ability_batch`) left untouched — react one-shots correctly go to graveyard; conjured rats come from deck via pending_tutor so legitimately from_deck=True.
- [Phase 14.5-02]: No tensor-side unit tests added — conftest gates on torch/sb3 availability and the only cross-engine parity test (`test_random_games_match`) is on the pre-existing hand_size-mismatch baseline-failure list. Stash-verified zero regressions: tensor tests before diff = after diff = 27 passed / 7 failed (identical set).

### Phase 14.5 Wave 1 (2026-04-08)

- fea4fbb feat(14.5-01): add MinionInstance.from_deck + Player.exhaust fields
- aa93005 feat(14.5-01): wire from_deck propagation + exhaust for discard-for-cost
- 9758728 test(14.5-01): graveyard/exhaust/token-exclusion coverage

Key decisions:
- [Phase 14.5-01]: from_deck is a flag on MinionInstance, set True by default on hand-origin PLAY_CARD and explicitly False on the activated summon_token token spawn path. Tokens vanish on death (no graveyard entry). Ratchanter conjure path is unaffected — it uses pending_tutor → deck search, so those rats are legitimately from_deck=True.
- [Phase 14.5-01]: Three verbs for hand removal — remove_from_hand (no pile, minion plays), discard_from_hand (graveyard, magic/react one-shots), exhaust_from_hand (exhaust, summon_sacrifice_tribe cost). Explicit at each call site.
- [Phase 14.5-01]: Rule 1 bug fix — pre-existing flow routed minion plays to graveyard via discard_from_hand, double-counting with the death-cleanup append. Split fixed; one stale test assertion updated.
- [Phase 14.5-01]: Dormant `_resolve_conjure` effect path (CONJURE EffectType) left untouched — no current card uses it. Future card would need per-hand-card origin tracking.
- [Phase 14.5-01]: Tensor engine NOT touched — Wave 2 will port the same split (graveyards stop receiving minion plays, new exhausts + exhaust_sizes tensors, death-cleanup gated on from_deck).

Pre-existing baseline failures confirmed unchanged (stash-verified):
- test_action_space::test_always_has_legal
- test_card_library::TestStarterPoolDeck::test_build_valid_deck (fallen_paladin)
- test_fatigue_fix::test_fatigue_escalates
- test_observation::test_observation_range[_player2]
- test_rl_env::test_env_checker
- test_tensor_engine::test_card_count + TestReset + TestStepping (multiple)
- test_tensor_engine_parity::test_tensor_tutor_pending_entry
- test_tensor_verification::test_random_games_match (hand_size mismatch)

Out of scope (not done, by design):
- Generic activated-ability dispatch (only Ratchanter exists; TODO note
  left in tensor actions.py / card_table.py for the second card)
- Obsidian vault sync
- Tensor-side unit tests for the new paths (deferred until torch/sb3
  conftest gating changes)
