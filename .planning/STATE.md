---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Online PvP Dueling
status: in_progress
stopped_at: "Phase 14.8 Plan 04b SHIPPED (2026-04-21). Behaviorally-significant client plan — all 19 EngineEvent types now route through fully-implemented playEvent slot handlers (10 from 04a + 9 new in 04b: playReactWindowOpened pushes to slotState.spellStageChain LIFO; playReactWindowClosed pops and fires _spellStageOnReactClosed when chain empties + stage visually up; playPhaseChanged branches on payload.new (START_OF_TURN → _flashPhaseLed('start',900), END_OF_TURN → _flashPhaseLed('end',900)); playTurnFlipped reuses _runTurnFlipVisuals verbatim; playTriggerBlip reuses _fireTriggerBlipAnimation verbatim; playPendingModalOpened sets slotState.pendingModalKind=payload.modal_kind + 5min safety deadline + spawns .event-queue-blocking informational scrim (opacity 0.04, pointer-events:none, z-index 5); playPendingModalResolved clears + removes scrim; playFizzle scans gameState.board for source_minion_id → anchors .fizzle-puff (💨 glyph, 350ms scale+fade-up CSS keyframe) to that tile, falls back to screen center; playGameOver reuses showGameOver({winner, final_state: window.__lastFinalState||gameState})). Each handler honors animation_duration_ms via _evDurationOr with per-handler fallbacks (chain push 600ms, close 400ms, banner 1500ms matching CSS, blip 900ms, fizzle 350ms, modal/game_over 0ms). 4 ad-hoc gate families DELETED (~480 net lines from game.js): (1) sandbox frame queue with drainer/applier/4 _SB_HOLD_* visual budgets, (2) post-stage-frame buffer + _hideSpellStage flush logic, (3) pending-trigger-blip defer-behind-spell-stage, (4) pending-turn-banner same-turn-dedupe + defer + _showTurnBannerOrDefer. All 11 verify-gated symbols return grep -c 0: _sandboxFrameQueue, _pendingPostStageFrame, _pendingTriggerBlip, _pendingTurnBanner, enqueueSandboxFrame, _drainSandboxFrameQueue, _applySandboxFrame, _flushPendingPostStageFrame, _showTurnBannerOrDefer, _lastBannerTurnKey, applyStateFrameSelective. Snapshot path REDUCED to pure snapshot-cache: onStateUpdate is now 4 lines (extract+applyStateFrame), socket.on('sandbox_state',...) is now 22 lines inline (sandboxState write + gameState sync if sandboxMode + autosave + renderSandboxToolbarState + renderSandbox; no queue, no derive-* dispatch). _applyStateFrameImmediate stripped of inline turn-banner + trigger-blip dispatch (~40 lines removed). commitEventToDom extended for phase_changed (re-renders both #phase-badge and #sandbox-phase-badge via _setPhaseLeds) + game_over (defensive no-op). 7 detect-*/derive-* helpers annotated with uniform `// DEAD CODE post-14.8-04b — plan 14.8-05 will delete` prefix + 1-line replacement reference (detectSpellCast/SpellStageClose/ReactWindowClose, deriveAnimationJob/CardFlyJobs/DrawJobs/PlayerHpDeltaAnims) — meets ≥7 verify gate. CSS additions: .fizzle-puff (💨 350ms keyframe) + .event-queue-blocking scrim (35 lines net). KEY DECISION: only 3 of 7 plan-documented pending_modal kinds are wired today (tutor_select, trigger_pick, death_target_pick — the ones the engine actually emits). The other 4 (conjure_deploy, revive_place, magic_cast_originator, post_move_attack) are opened by snapshot-path sync* handlers reading pending_* state fields and DON'T currently emit EVT_PENDING_MODAL_OPENED — per failure_handling, ship the simpler kinds + flag complex for plan 05 attention. The handler is generic (sets pendingModalKind=payload.modal_kind) so the 4 unemitted kinds will gate automatically once engine emission is added. KEY DECISION: spell-stage chain handler tracks chain depth in slotState.spellStageChain but does NOT drive the visible card slam-in. The actual _showSpellStage call is still triggered by snapshot path's detectSpellCast (reading prev→next grave/react_stack diff). This is a deliberate partial migration: 04b owns chain-close logic; plan 05 will own the chain-open card identity once card_played event payload is wired. Rationale: react_window_opened's payload carries react_context but NOT the specific card_numeric_id; moving slam-in to event-driven requires either payload extension or coordinating with card_played event arrival order. KEY DECISION: applyStateFrameSelective shim (described in plan body) NOT implemented — by reducing onStateUpdate + sandbox_state to pure state-commit, the snapshot path naturally stops invoking detect-* dispatch. Simpler than the selective-suppress shim. KEY DECISION: 5-minute pending-modal safety deadline is defensive only (matching EVT_PENDING_MODAL_RESOLVED should arrive within tens of ms of user input for normal flows; deadline exists for server crash / tab close / socket drop edge cases — without it the eventQueue would silently halt forever on these abnormal paths). Commits: b20b70d (feat Task 1: 9 harder slot handlers + commitEventToDom extension + .fizzle-puff/.event-queue-blocking CSS) + 1e02c79 (refactor Task 2: 4-gate deletion + onStateUpdate reduction + sandbox_state inline commit + 7 DEAD CODE markers — net -479 lines across -599 deletions / +120 inline replacements). Test posture: node -c game.js clean, python server import clean, tests/server + tests/test_event_serialization + tests/test_phase_contracts 108/108 passed, broader engine+server suite (excluding RL/tensor/training/e2e) 1060 passed / 17 failed / 27 skipped — EXACT baseline match from plan 04a (same 17 documented pre-existing failures: 8 react_stack TestStartOfTurn/TestPhase14_7_05, 7 game_loop TypeError, 1 spectator, 1 game_flow ordering bug). No Rule 1/2/3 auto-fixes triggered. Hook points for plan 14.8-04c (visual UAT): every animation now flows through eventQueue (no double-rendering against parallel snapshot-driven path); window.__eventQueueDebug exposes queue/running/lastSeenSeq/slotState (spellStageChain/pendingModalKind/pendingModalDeadline) for live introspection; reset mismatch test = trigger sandbox_reset mid-animation (queue clears + re-anchors at seq=0). Hook points for plan 14.8-05 (snapshot deletion): 7 DEAD CODE markers grep -c==7 enable bulk regex deletion; applyStateFrame + _applyStateFrameImmediate still commit DOM via renderGame/renderSandbox — plan 05 either moves these into commitEventToDom or deletes state_update/sandbox_state subscriptions entirely; legacy state.last_trigger_blip field still dual-written by engine — plan 05 deletes the field write; pending_modal_opened emission gap (4 kinds) needs engine extension; commitEventToDom is 50% filled (phase_changed + game_over wired) — plan 05 fills mana/phase/legal_actions sync that snapshot path commits. Hook points for plan 14.8-06 (UAT/strict-mode flip): M1 react_window symmetry placeholder can un-skip after 04c UAT; strict-mode contract enforcement default flip can land once 04c confirms no client regressions (engine-side violations already 0 per plan 02 invariant test). Previous: Phase 14.8 Plan 04a SHIPPED (2026-04-21). First client-side plan of Phase 14.8 — eventQueue infrastructure + 19-case dispatcher + 10 simpler slot handlers wired into game.js. New globals near AnimationQueue: eventQueue (EngineEvent[]), eventRunning (re-entry gate), lastSeenSeq (-1 sentinel; monotone dedupe ref tied to server's session.next_event_seq from plan 03b M3), slotState (spellStageChain + pendingModalKind + pendingModalDeadline reserved for plan 04b). resetEventQueue() clears all four; called from 6 sites matching server-side seq=0 reset boundaries: onGameStart (live PvP fresh-game/rematch), sandboxActivate (sandbox screen entry — first sandbox_create/sandbox_load), sandboxDeactivate (defensive on screen exit), sandbox-reset-btn click (matches SandboxSession.reset()), sandbox-load-file reader.onload + sandbox-paste-btn click + sandbox-slot-load-btn click (all match SandboxSession.load_dict()). onEngineEvents(payload) bound once in initSocket via socket.on('engine_events', onEngineEvents) — single subscription covers both live PvP and sandbox (same Socket.IO transport). Dedupes via ev.seq <= lastSeenSeq with console.warn skip; pushes accepted events into eventQueue; stashes payload.final_state + legal_actions into window.__lastFinalState / __lastLegalActions for error-recovery snapshot fallback; kicks drainEventQueue. drainEventQueue shifts one event, sets eventRunning=true, calls playEvent(ev, onSlotDone) wrapped in try/catch (handler crash → log + advance; no deadlock); slot's done callback sets eventRunning=false → commitEventToDom(ev) → re-enters drain. Modal gate at top: if slotState.pendingModalKind !== null return — reserved for 04b's pending_modal_opened/resolved pair. commitEventToDom is a STUB in 04a (snapshot path commits state authoritatively; patching twice would race; stub kept for plan 04b/05). playEvent dispatcher with all 19 case branches: 10 routed to fully-implemented handlers (playMinionSummoned, playMinionDied, playMinionHpChange, playMinionMoved, playAttackResolved, playCardDrawn, playCardPlayed, playCardDiscarded, playInstant for mana_change, playPlayerHpChange); 9 stubbed with `console.warn(\"[eventQueue] <type>: stub — implemented in 04b\") + setTimeout(done, 0)` (react_window_opened, react_window_closed, phase_changed, turn_flipped, trigger_blip, pending_modal_opened, pending_modal_resolved, fizzle, game_over). Default branch warns on unknown event type. window.__eventQueueDebug exposes queue/running/lastSeenSeq/slotState/reset() for browser devtools. The 10 simpler handlers refactor existing animation primitives (Phase 14.3 Wave 2/3/4/7 + 14.5-06 Wave 6 + 14.7-09 burn-tick popup variants) — playMinionSummoned/Moved/AttackResolved/CardDrawn enqueue jobs into the existing animQueue with stateAfter=gameState (already post-event from snapshot path) + stateApplied=true so the inner playSummonAnimation/etc. doesn't crash on undefined frame; playMinionHpChange routes to showFloatingPopup with cause-based variant (heal/burn-tick/combat-damage); playPlayerHpChange spawns inline damage-popup span over the hp stat element + hp-flash class. Each handler honors animation_duration_ms from the EngineEvent (default lookup in engine_events.py:DEFAULT_DURATION_MS) via _evDurationOr(ev, fallback) helper; chains done() at the wall-clock duration so the queue paces subsequent events correctly even when chained behind a snapshot-driven animation. Two helpers added: _evDurationOr (clamps animation_duration_ms with per-handler fallback), _evTileForPos (single CSS lookup for .board-cell[data-row][data-col]). KEY DECISION: snapshot path STAYS COMPLETELY INTACT in 04a. The plan body describes an applyStateFrameSelective shim that would suppress detect-* helpers in applyStateFrame for the 10 covered event types, but the existing detect logic is INLINE in _applyStateFrameImmediate (heal/burn HP popups at line ~3171, fatigue nudge, turn banner trigger, trigger blip dispatch) — not factored into named detect-* helpers. Refactoring is itself plan 04b/05 work. Plan failure_handling explicitly licenses the double-render tradeoff: server emits state_update FIRST and engine_events SECOND in the same socket flush → snapshot path's animation jobs queue ahead of event-driven ones in the SAME animQueue → they run sequentially, not in parallel (visible posture: 'snapshot anims, then event anims, in order' — twice as long but not overlapping). 4 ad-hoc gates UNTOUCHED per plan must_haves: _sandboxFrameQueue + _drainSandboxFrameQueue + _applySandboxFrame + _flushPendingPostStageFrame + _pendingPostStageFrame + _pendingTriggerBlip + _pendingTurnBanner + _showTurnBannerOrDefer all still wired through socket.on('sandbox_state', ...) + applyStateFrame; eventQueue runs alongside; deletion is plan 04b's job after all 19 handlers are wired. Two deviations from plan body: (1) applyStateFrameSelective shim NOT implemented (deferred to 04b/05 per failure_handling — see KEY DECISION above); (2) .event-queue-blocking CSS scrim NOT added (plan 04b's pending_modal_opened handler will land it together). Otherwise plan executed exactly as written; no Rule 1/2/3 auto-fixes triggered (existing engine + server tests passed first try, node -c game.js clean from first save). Commits: 67b268e (feat Task 1: eventQueue infrastructure + dispatcher + socket wire — globals + resetEventQueue + onEngineEvents + drainEventQueue + commitEventToDom stub + playEvent 19-case dispatcher + playInstant + 10 stubbed playXyz handlers + window.__eventQueueDebug + socket.on bind in initSocket + 6 sandbox-reset call sites) + 0e47ebc (feat Task 2: implement 10 simpler slot handlers — playMinionSummoned/Died/HpChange/Moved + playAttackResolved + playCardDrawn/Played/Discarded + playPlayerHpChange + _evDurationOr + _evTileForPos helpers; reuses Phase 14.3/14.5/14.7-09 animation primitives via enqueueAnimation pushes). Both commits pending push (user pushes manually per milestone). Test posture: tests/test_event_serialization.py 21/21 passed; tests/server 68/68 passed; broader engine+server suite (excluding RL/tensor/training/e2e) 1060 passed / 17 failed / 27 skipped — exact baseline match from plan 03b (same 17 documented pre-existing failures: 8 react_stack TestStartOfTurn/TestPhase14_7_05, 7 game_loop TypeError, 1 spectator, 1 game_flow ordering bug). node -c src/grid_tactics/server/static/game.js clean. Server import (python -c 'import grid_tactics.server.app') clean. game.js +410 lines net. Hook points for plan 14.8-04b: (1) 9 stubbed handlers ready for replacement — each currently console.warn + setTimeout(done, 0); replace bodies, remove warns; (2) slotState fields reserved (spellStageChain LIFO stack for spell-stage chain handler, pendingModalKind to gate drain, pendingModalDeadline safety timeout); (3) 4 ad-hoc gates ready for deletion once 04b's turn_flipped + spell-stage chain + trigger_blip handlers are live; (4) commitEventToDom stub waiting for plan 04b/05 to fill in event-driven DOM mutations once snapshot path is suppressed; (5) modal gate `if (slotState.pendingModalKind !== null) return;` ready for pending_modal_opened set / pending_modal_resolved clear. Hook points for plan 04c (visual UAT): 10 covered events should produce visible animations matching existing snapshot-driven ones (currently double-renders sequentially — 04b expected to fix before UAT); 9 stubbed events log warnings (UAT can verify warnings gone after 04b); window.__eventQueueDebug exposes live state for inspection; mismatch test = trigger sandbox reset mid-action (eventQueue should clear and re-anchor at seq=0 without dropping next event). Hook points for plan 14.8-05 (snapshot deletion): applyStateFrame + _applyStateFrameImmediate + inline detect-* logic become DEAD code once 04b suppresses them; socket.on('state_update'/'sandbox_state') deletable once server stops emitting them per plan 03b's dual-emit hook; commitEventToDom stub becomes the place to land any residual mana / legal_actions / pending-modal sync that snapshot path used to handle. Previous: Phase 14.8 Plan 03b SHIPPED (2026-04-21). Server-side engine_events Socket.IO emit live for both live PvP (handle_submit_action) AND sandbox (handle_sandbox_apply_action + 8 sandbox edit handlers refactored to apply_sandbox_edit). M3 next_event_seq field added to BOTH GameSession (live PvP) and SandboxSession (sandbox) — monotonic event seq across the full session lifetime; per-call EventStream(next_seq=session.next_event_seq) seeds from the counter, persists stream.next_seq back when finished. Reset semantics: GameSession.next_event_seq resets to 0 on rematch (request_rematch builds fresh GameSession); SandboxSession._next_event_seq resets to 0 on reset() and load_dict() so loaded saves / fresh empty state start the counter at 0. Plan 04b's lastSeenSeq dedup depends on this stable monotone reference. The 9c414f9 per-frame sandbox emit hack from Phase 14.7-09 is DECOMMISSIONED — apply_action returns the full event list across user action + every drained auto-PASS as ONE EventStream; ONE engine_events socket frame per call regardless of drain depth (verified by test_sandbox_auto_drain_emits_events_once_at_end_not_per_frame). Pacing moves from socket-frame cadence to event animation_duration_ms (plan 04a/b client consumption); the transient-signal regressions 9c414f9 worked around (last_trigger_blip clobber, REACT-phase entries / exits) are now handled by dedicated EVT_TRIGGER_BLIP / EVT_REACT_WINDOW_OPENED/CLOSED / EVT_PHASE_CHANGED events from plan 03a. SandboxSession.apply_sandbox_edit(verb, payload) → list[EngineEvent] verb dispatch helper for 14 sandbox verbs (cheat_mana, cheat_hp, set_active, add_card_to_zone, move_card_between_zones, place_on_board, import_deck, undo, redo, reset, load, load_slot, save_slot, set_player_field) — orchestrator decision #5 made concrete: sandbox cheats produce events tagged contract_source='sandbox:<verb>', bypass phase-contract assertions but flow through SAME EventStream pipeline so client uses ONE rendering pipeline. view_filter.filter_engine_events_for_viewer(events, viewer_idx, *, god_mode=False): EVT_CARD_DRAWN strips card_numeric_id/card_id/stable_id/name for opponent (count is public per Phase 14.5); EVT_PENDING_MODAL_OPENED strips options for non-picker (replaced with option_count); god_mode=True bypasses ALL redaction (sandbox + spectator-god per Phase 14.4 contract). Owner-key resolution uses EXPLICIT 'is None' checks NOT 'or'-chains because P1 = owner_idx=0 is FALSY in Python — caught on first run by test_per_viewer_filter_hides_opponent_pending_modal_options and documented as a footgun comment. Live PvP _emit_state_to_players + _fanout_state_to_spectators gain optional events kwarg; when provided emit NEW 'engine_events' Socket.IO message per viewer ALONGSIDE existing 'state_update' (dual-emit pattern for back-compat — old clients ignore new frame, plan 14.8-05 drops the legacy snapshot once all clients switch). Auto-advance loop in handle_submit_action threads ONE EventStream through resolve_action + every enter_start_of_turn / enter_end_of_turn + every drained PASS resolve_action; single seq-ordered stream covers entire user-visible chain regardless of how many engine calls compose it. session.next_event_seq written back exactly once on success. Commits: b39d615 (feat Task 1: M3 + sandbox EventStream + per-viewer event filter — GameSession.next_event_seq + SandboxSession._next_event_seq + apply_action returns events + apply_sandbox_edit verb dispatch + filter_engine_events_for_viewer) + e1f306b (feat Task 2: wire engine_events Socket.IO emit + 21 tests — handle_submit_action EventStream wiring + engine_events emission alongside state_update/sandbox_state + 8 sandbox edit handlers refactored to apply_sandbox_edit + 9c414f9 per-frame hack removed + 21 new tests). Test posture: tests/test_event_serialization.py 21/21 passed; focused subset (server + engine_events + view_filter + pvp + phase_contracts + invariants + new tests) 280 passed / 27 skipped; broader engine+server+integration suite (excluding RL/tensor/training/e2e) 1060 passed / 17 failed / 27 skipped — failure count matches documented baseline (16 from plan 03a + 1 game_flow ordering bug also from plan 03a baseline that surfaces only when test_event_serialization runs before test_game_flow due to socketio test client state interactions; reproduced on baseline by stashing my changes and running same test order — pre-existing, NOT caused by this plan). Three Rule 1 auto-fixes during execution: (1) react_stack.py missing EVT_PENDING_MODAL_OPENED import — plan 03a referenced the constant at lines 465 + 484 inside drain_pending_trigger_queue but didn't import it; surfaced only when 03b wired event_collector to actually flow into that path; (2) view_filter.py owner-key resolution `or`-chain bug (P1=0 falsy in Python); (3) tests/test_event_serialization.py action codec format — corrected from {'action': ...} wrapped to flat dict per reconstruct_action signature. Hook points for plan 14.8-04a (client eventQueue): engine_events payload shape {events:[...], final_state:<snapshot>, legal_actions:[...], your_player_idx:int, is_spectator?:bool, is_sandbox?:bool}; final_state matches state_update.state for client reconciliation; requires_decision=True on EVT_PENDING_MODAL_OPENED gates the eventQueue until matching RESOLVED event arrives; triggered_by_seq lets client visualize trigger nesting. Hook points for plan 14.8-04b (lastSeenSeq dedup): Session.next_event_seq + SandboxSession._next_event_seq are the monotone references; reset semantics wired (rematch / reset / load). Hook points for plan 14.8-05 (strict-mode flip + legacy field deletion): once clients consume engine_events exclusively, drop state_update + sandbox_state emits + state.last_trigger_blip dual-write. Hook points for plan 14.8-06 (UAT): un-skip M1 react_window symmetry placeholder once 04a/b ship. Save/load handlers NOT refactored to apply_sandbox_edit (saves are side-effect-only, loads use load_dict which already resets seq counter — 14 verbs covered, 2 intentional pass-throughs from the soft-target 16). Previous: Phase 14.8 Plan 03a SHIPPED (2026-04-21). Engine event stream wire format live: new `src/grid_tactics/engine_events.py` module (370 lines) defines EngineEvent frozen dataclass + EventStream collector + 19 EVT_* constants + DEFAULT_DURATION_MS table. All 19 event types from research §'Event types proposed' enumerated explicitly in ALL_EVENT_TYPES frozenset: minion_summoned / minion_died / minion_hp_change / minion_moved / attack_resolved / card_drawn / card_played / card_discarded / mana_change / player_hp_change / react_window_opened / react_window_closed / phase_changed / turn_flipped / trigger_blip / pending_modal_opened / pending_modal_resolved / fizzle / game_over. event_collector: Optional[EventStream] = None kwarg threaded through 30+ engine call sites across action_resolver.py + react_stack.py + effect_resolver.py (resolve_action + _cleanup_dead_minions + _check_game_over + resolve_effect + resolve_effects_for_trigger + _resolve_conjure + _enter_pending_tutor + tick_status_effects + drain_pending_trigger_queue + fire_start/end_of_turn_triggers + _resolve_trigger_and_open_react_window + _close_end_of_turn_and_flip + enter_start/end_of_turn + close_*_react_* + handle_react_action + _play_react + resolve_react_stack + resolve_summon_*_originator). Back-compat invariant preserved via default None: 970 plan-02 baseline tests pass unchanged. All 19 event types emit from at least one engine site (verified via grep+frozenset audit): minion_summoned from resolve_summon_declaration_originator (post-Window-A land); minion_died from _cleanup_dead_minions (one per dead minion, instance_id order); minion_hp_change from tick_status_effects (burn ticks); minion_moved/attack_resolved/card_drawn/card_played from resolve_action per-handler branches; card_discarded/mana_change/player_hp_change via DIFF-BASED emission (snapshot pre-action / sweep post-dispatch — covers all 8 action handlers uniformly with ONE emission point, reduces instrumentation churn ~10x); react_window_opened from _resolve_trigger_and_open_react_window + enter_start/end_of_turn (INCL. shortcut path per orchestrator decision #3: zero-duration opened+closed pair fires when no triggers exist for symmetry); react_window_closed from close_start/end_react_* + enter_start/end_of_turn shortcut paths + resolve_react_stack tail; phase_changed from enter_start/end_of_turn + close_start_react_and_enter_action; turn_flipped from _close_end_of_turn_and_flip; trigger_blip from _resolve_trigger_and_open_react_window (DUAL-write with state.last_trigger_blip field during migration; plan 14.8-05 deletes field); pending_modal_opened from _enter_pending_tutor + drain_pending_trigger_queue (requires_decision=True gates client eventQueue); pending_modal_resolved from resolve_action death_target_pick handler; fizzle from _resolve_trigger_and_open_react_window fizzle path; game_over from _check_game_over. EventStream public API: EventStream(next_seq=session.next_event_seq) per resolve_action call, stream.collect(type, contract_source, payload, *, animation_duration_ms=None, requires_decision=False), stream.push_parent(seq)/pop_parent() for inline-trigger nesting (research pitfall #4), stream.to_dict_list() for socket fanout. Plan 03b's Session.next_event_seq slot consumes this verbatim. Commits: d7c7c68 (feat Task 1a: engine_events module + 14 unit tests) + dce9a02 (feat Task 1b: threading + emission + 6 integration tests). Test posture: 990 passed / 16 failed / 27 skipped under shadow mode — NET +20 over plan 14.8-02 baseline 970/16. The 16 remaining failures are pre-existing baseline (8 react_stack TestStartOfTurn/TestPhase14_7_05, 7 game_loop TypeError, 1 spectator, 1 game_flow ordering bug). Engine subset (test_react_stack + test_action_resolver + test_effect_resolver + test_phase_contracts + test_phase_contract_invariants + test_engine_events) 312 passed / 8 failed / 27 skipped. Coverage gaps for plan 03b: conjure_deploy / revive_place / decline_post_move_attack / magic_cast_originator pending modals aren't emitting events yet (their pending fields ARE set) — documented in SUMMARY with emission-site table. Hook points for plan 03b: (1) Session.next_event_seq slot initializes to 0, seeds each EventStream per call, persists back after; (2) socket fanout loop `for ev in stream.events: socket.emit('engine_event', ev.to_dict())`; (3) sandbox cheats (cheat_mana/undo/etc.) emit events tagged contract_source='sandbox:<verb>' via same EventStream protocol — bypasses contract assertion but flows through same wire format; (4) pending-modal coverage gaps listed above. Hook points for plan 04a: wire format is LOCKED — EngineEvent fields stable; per-event payload schemas can be defined per type without touching engine. triggered_by_seq lets client visualize trigger nesting; requires_decision=True at OPENED events gates eventQueue until matching RESOLVED event arrives. animation_duration_ms=0 marks shortcut events treated as instant. Previous: Phase 14.8 Plan 02 SHIPPED (2026-04-21). Pytest invariant test live: tests/test_phase_contract_invariants.py (132 items, 105 passing + 27 skipped + 1 M1 placeholder). 102 plan-01 baseline shadow-mode violations driven to ZERO in one iteration pass (well under the 20-violation budget gate that would have spawned plan 02b). 6 unique violation patterns resolved: (1) smoking-gun #1 — resolve_summon_declaration_originator re-tagged from action:play_card → NEW system:resolve_summon_declaration source (REACT-only); (2) smoking-gun #2 — system:enter_end_of_turn widened to allow REACT (called from resolve_react_stack tail before phase reset); (3) system:enter_start_of_turn widened to allow ACTION (turn_flip leaves phase=ACTION); (4) system:turn_flip widened to allow REACT (close_end_react doesn't reset phase before flip); (5) trigger:on_start_of_turn / trigger:on_end_of_turn widened to allow REACT (picker-modal-resume drain runs at REACT); (6) trigger_kind → contract_source translation map in _resolve_trigger_and_open_react_window (plan-01 short-form 'end_of_turn' → 'on_end_of_turn' per PHASE_CONTRACTS key naming). 2 test fixtures aligned with production phase: test_status_effects burn-tick uses START_OF_TURN; test_effect_resolver fizzle uses END_OF_TURN. ViolationCapture context manager + format_violations helper added to phase_contracts.py for test inspection of shadow-mode warnings. conftest.py default flipped to CONTRACT_ENFORCEMENT_MODE=shadow via os.environ.setdefault at module load — all future test runs catch new mistags as WARNINGs immediately, invariant test fails any PR that introduces unexpected violations. Module-level default remains 'off' for back-compat (non-test consumers like RunPod training). M1 react_window symmetry placeholder added as SKIPPED test — un-skips in plan 14.8-06 once EngineEvent stream from 03a/b is live. Test posture: 970 passed / 16 failed under shadow-mode default (NET +1 over mode=off baseline 969/17 — status-effects fix resolved one previously-flaky test). Engine subset (test_react_stack/action_resolver/effect_resolver) shadow-mode violations: 102 → 0. Broader engine+server suite (excluding RL/tensor/e2e) shadow-mode real engine violations: 7392 → 0 (11 remaining are intentional test-driven assertions in test_phase_contract_invariants.py + test_phase_contracts.py — proving the contract assertion fires as expected). The 16 remaining failures are pre-existing baseline: 8 react_stack TestPhase14_7_05/TestStartOfTurnTriggers, 7 game_loop TypeError, 1 events spectator, 1 game_flow ordering bug — all unchanged from plan 01. Commits: 4d0e868 (Task 1: invariant test scaffolding + ViolationCapture + table coverage + M1 placeholder) + 906043c (Task 2: drive 102 violations to zero + flip conftest default + iterate-and-fix loop). Hook points for next plans: (1) plan 14.8-03a event emitter — contract sources are now self-consistent across the engine; emitter taps subscribing to assertion call sites have stable identifiers; (2) plan 14.8-05 strict-mode flip becomes a one-line config change — invariant test guarantees zero engine violations exist; (3) plan 14.8-06 UAT un-skips the M1 placeholder once EngineEvent stream is live; (4) ViolationCapture is the canonical pattern for any future test that needs to assert engine behavior under shadow mode. Previous: Phase 14.8 Plan 01 SHIPPED (2026-04-21). Foundation for phase-contract enforcement: PHASE_CONTRACTS table (41 entries across 5 categories), OutOfPhaseError soft exception, assert_phase_contract single entry point, get_enforcement_mode env-var driven (off|shadow|strict, default off). 53 call sites tagged across effect_resolver / react_stack / action_resolver. 5 helpers extended with contract_source kwarg. REQUIREMENTS.md CONTRACT-01..08 seeded. 19 passing tests (16 unit + 3 integration). Default mode = off so 905 existing engine+server tests pass unchanged; 24 pre-existing failures still present (8 react_stack TestStartOfTurnTriggers/TestPhase14_7_05, 8 game_loop TypeError, 2 tensor parity, 6 training, 1 spectator). Shadow-mode dry run: 102 violation WARNINGs surfaced for plan 14.8-02 to drive to zero. Smoking guns: action:play_card phase=REACT from resolve_summon_declaration_originator + system:enter_end_of_turn phase=REACT from enter_end_of_turn called in resolve_react_stack tail. Commits: 0683634 (Task 1) + 1447d0e (Task 2). No production behavior change. Previous: Phase 14.7 Plan 06 SHIPPED (2026-04-19). Fizzle rule live: effects whose targets/sources are no longer valid at resolution time silently no-op per spec §7.3. New `_validate_target_at_resolve_time(state, effect, source_pos, source_minion_id, target_pos) -> bool` helper in effect_resolver.py gates SINGLE_TARGET (no alive minion at target_pos), ADJACENT (source_minion_id dead/missing), SELF_OWNER (same) — OPPONENT_PLAYER and area effects (ALL_ENEMIES/ALL_ALLIES/ALL_MINIONS) never fizzle via the gate. `resolve_effect` gained keyword-only `source_minion_id` kwarg; fizzle gate runs BEFORE the TargetType dispatch and returns the EXACT incoming state object on fizzle (identity-preserving so callers detect no-op via `state is prev_state`). Updated callers passing source_minion_id: `resolve_effects_for_trigger` (minion.instance_id), `resolve_summon_effect_originator` (entry.source_minion_id), `_fire_passive_effects` (legacy defensive, m.instance_id). Magic/react/death callers leave source_minion_id=None (death triggers: source IS dead by definition — gate checks target only). `_resolve_trigger_and_open_react_window` detects fizzle via state identity after resolve_effect, pops the trigger WITHOUT opening a react window (no dead-air prompt), re-drains via `drain_pending_trigger_queue`. trigger_kind dispatch: on_death → source_minion_id=None; start_of_turn/end_of_turn/on_summon → source_minion_id=trigger.source_minion_id. 22 new tests: 16 in test_effect_resolver.py (TestFizzleRulePhase14_7_06 — per-TargetType + per-EffectType DAMAGE/DESTROY/BUFF_ATTACK/BUFF_HEALTH/HEAL/APPLY_BURNING + regression guards), 4 in test_react_stack.py (TestPhase14_7_06_TriggerFizzle — drain-level behavior), 2 in test_integration.py (TestFizzleRulePhase14_7_06Integration — §7.4 fizzle variant + synthetic mid-drain source-death). §7.4 fizzle variant integration test: P1 RGB Lasercannon + P2 Giant Rat A die simultaneously, P2 has ONE plain Rat (promote candidate), P1 turn-priority picks that rat for RGB's DESTROY modal, Giant Rat A's PROMOTE then has 0 candidates and silently no-ops — proves the strategic pre-empt from spec §7.4. Second integration test uses synthetic in-memory CardLibrary with a 'Stinger' minion (on_end_of_turn ADJACENT damage) to prove source-death fizzle: two stingers adjacent, P1 picks stinger A first, stinger A kills stinger B, stinger B's queued trigger fizzles (source dead), bystander unharmed. Commits: d4978c5 (feat Task 1: _validate_target_at_resolve_time + resolve_effect gate + 16 unit tests) + 10afe1c (test Task 2: drain-level fizzle + 2 integration tests). Both pushed to master; Railway auto-deployed. Test posture: 132 passed across test_effect_resolver + test_react_stack + test_integration (+22 new). Broader engine+server suite: ~852 passed, 2 pre-existing baseline failures unchanged (1 spectator, 1 intermittent LEAP in test_game_flow). Auto-fixed 2 in-progress issues: (a) EffectDefinition requires `amount` positional arg — added `amount=0` explicitly to DESTROY/APPLY_BURNING test constructors; (b) owner_idx vs MinionInstance.owner mismatch in test_fizzle_pops_trigger_and_advances_to_next_queue_entry — aligned minion owner to PLAYER_2 when owner_idx=1. Decision: kept `_fire_passive_effects` function in place (plan suggested considering removal). Audit confirmed zero card JSONs use `trigger:passive` (grep empty post-14.7-03 retag). Safer to leave dead code + thread source_minion_id defensively than delete without 14.7-10 migration test scaffolding. Hook points for next plans: 14.7-09 (turn banner: fizzled triggers never open a react window, so banner never sees a 'fizzled' window dispatch — simplifies banner logic); 14.7-10 (cleanup: fizzle gate is centralized in _validate_target_at_resolve_time for audit, source_minion_id threading gives a consistent invariant; consider pruning PendingDeathWork/pending_death_queue now that priority queue + fizzle gate cover its use cases). Previous: Phase 14.7 Plan 05b SHIPPED (2026-04-19 evening). _cleanup_dead_minions migrated to the turn-player-first PendingTrigger priority queue established in 14.7-05. ON_DEATH effects now enqueue into pending_trigger_queue_turn / pending_trigger_queue_other (spec §7.2: turn player's deaths resolve before opponent's). _resolve_trigger_and_open_react_window gained an on_death branch: DESTROY/SINGLE_TARGET + PROMOTE-with-2+-candidates open the existing pending_death_target modal (preserved verbatim, orthogonal to the ordering-level picker modal); other on_death effects resolve inline and open AFTER_DEATH_EFFECT react window. Module-level _cleanup_skip_drain reentrancy guard with try/finally prevents nested drain when chain-reaction cleanup happens inside an outer resolution (outer pops its entry, drain-recheck in resolve_react_stack handles chain entries). resolve_react_stack gained identity-based (`state is not _pre_cleanup_state`) AFTER_DEATH_EFFECT early-exit — prevents closing a freshly-opened death-trigger window. Existing callers (conjure/tutor/post-move/main paths) gained picker + phase==REACT defensive checks so they don't clobber cleanup-opened windows. Spec §4.3 / §7.4 worked example (RGB Lasercannon + Giant Rat simultaneous deaths with turn-player-first resolution + PROMOTE of remaining Rat) works end-to-end — integration test added. Sandbox to_dict/load_dict round-trips on_death PendingTriggers (no serializer change needed — 14.7-05 schema already supports the trigger_kind string). Pre-14.7 ordering tests (test_on_death_effects_trigger_in_instance_id_order, test_active_player_deaths_fire_before_opponent, test_ordering_tiebreak_by_instance_id, test_chain_death_damage_kills_another_minion_with_on_death) updated in-place via a new _drain_all_death_triggers helper (PASS + TRIGGER_PICK drain) — asserts same end-state, no xfails added. PendingDeathWork / pending_death_queue kept as defensive no-op (apply_death_target_pick's queue-advance is now orthogonal to the new priority queue; can be pruned in 14.7-10). Commits: 6800264 (feat Task 1: _cleanup_dead_minions refactor + _resolve_trigger_and_open_react_window on_death branch + 4 callers' defensive checks + updated pre-14.7 ordering tests + 5 new TestDeathTriggerPriorityQueue unit tests) + 890c4bc (test Task 2: §4.3 worked example + sandbox round-trip). Both pushed to master; Railway auto-deployed. Test posture: 223 passed across test_action_resolver + test_react_stack + test_integration + test_effect_resolver + test_sandbox_session (+7 new tests: 5 unit + 1 integration + 1 sandbox). Broader engine+server suite: 828 passed, 2 pre-existing baseline failures (1 spectator, 1 intermittent LEAP bug in test_game_flow that's pre-existing — documented in SUMMARY). Auto-fixed 2 issues in-progress: (a) initial state-phase check was too eager and got stuck in a PASS loop at ~iter 385 of a full game simulation — fixed via state identity check (caught by standalone simulation script before test suite run); (b) chain-reaction nested drain would see outer entry still at queue[0] + chain entry and open picker modal mid-resolution — fixed via _cleanup_skip_drain reentrancy guard so outer resolver pops first. Hook points for next plans: 14.7-06 (fizzle: liveness check at top of _resolve_trigger_and_open_react_window for on_death source_minion_id — the source is now dead at resolution time by design, existing has_target silent no-op path is a template); 14.7-09 (turn banner: react_context == AFTER_DEATH_EFFECT is the dispatch key; source card info via pending_trigger_queue_*[0].source_card_numeric_id before the drain pops); 14.7-10 (cleanup: consider pruning PendingDeathWork shape, auditing all _cleanup callers for the defensive check pattern, investigating pre-existing LEAP flakiness). Previous: Phase 14.7 Plan 07 SHIPPED. React-condition matching is now react_context-aware. Three append-only ReactCondition values added: OPPONENT_SUMMONS_MINION=15, OPPONENT_START_OF_TURN=16, OPPONENT_END_OF_TURN=17 (forward-compat; no card JSON uses them yet). _check_react_condition (src/grid_tactics/legal_actions.py) rewritten end-to-end from ~94 lines to ~225 lines with explicit react_context dispatch: (a) AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT match OPPONENT_SUMMONS_MINION (new), OPPONENT_PLAYS_MINION (back-compat alias), element conditions against the summon originator, OPPONENT_PLAYS_REACT (counter-react), ANY_ACTION — AND REJECT OPPONENT_PLAYS_MAGIC / OPPONENT_ATTACKS / etc. (b) AFTER_START_TRIGGER matches OPPONENT_START_OF_TURN (new) + counter-react + ANY_ACTION. (c) BEFORE_END_OF_TURN matches OPPONENT_END_OF_TURN (new) + counter-react + ANY_ACTION. (d) AFTER_ACTION / None preserves full pre-14.7 behavior (magic_cast originator detection for 14.7-01 deferred magic; pending_action fallback for MOVE/ATTACK/SACRIFICE/DISCARD/element/DISCARD). (e) Counter-react branch preserved: a non-originator react on top matches OPPONENT_PLAYS_REACT, OPPONENT_PLAYS_MAGIC (for Prohibition counter-reacts), element conditions. **Behavioral change:** Prohibition (OPPONENT_PLAYS_MAGIC) is no longer in legal_actions during summon windows — previously a summon would have offered Prohibition as a legal react even though the card text says 'magic only' (the old code fell through to matching pending_action PLAY_CARD). Confirmed via new test_prohibition_not_legal_during_summon_declaration. Existing pre-14.7-07 integration tests (test_prohibition_on_window_a_negates_full_summon_and_tutor, test_prohibition_on_window_b_preserves_minion_cancels_tutor from 14.7-04) continue to pass because they call resolve_action(play_react_action(...)) directly, bypassing legal_actions — _play_react doesn't re-validate the condition. No action taken; those tests exercise the code-level negate resolution, not player-visible legality. card_loader reflective enum lookup (enum_cls[value.upper()]) auto-picks the three new strings; no REACT_CONDITIONS allowlist edit needed (none exists). No card JSON retagged — forward-compat only. Commits: 604b64a (feat Task 1: enum + _check_react_condition + 22 unit tests) + 5648759 (test Task 2: 3 integration tests including in-memory synthetic CardLibrary). Both pushed to master; Railway auto-deployed. Test posture: 884 non-RL/non-tensor tests pass (+25 new: 5 enum, 4 card_loader, 13 legal_actions, 3 integration). Baseline failures unchanged at 8 (1 spectator, 4 LEAP game_loop, 2 rl_env REVIVE_PLACE unhandled, 1 RL self-play — all pre-existing and predating 14.7). No deviations — plan executed exactly as written. Hook points for next plans: 14.7-05b (Death: priority migration — no coupling), 14.7-06 (fizzle — no coupling), 14.7-09 (turn banner — react_context is the single source of truth for window-type, banner dispatch can branch on it directly). Future card designs: JSON cards can now use react_condition='opponent_summons_minion' / 'opponent_start_of_turn' / 'opponent_end_of_turn' with zero additional code changes."
last_updated: "2026-04-21T10:18:00.000Z"
last_activity: 2026-04-21
progress:
  total_phases: 7
  completed_phases: 4
  total_plans: 30
  completed_plans: 27
  percent: 90
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-04)

**Core value:** The reinforcement learning engine that discovers and validates game strategies
**Current focus:** Phase 13 — board-hand-ui

## Current Position

Phase: 14.8 (phase-contract-enforcement) — IN PROGRESS (Plans 01 + 02 + 03a + 03b + 04a + 04b SHIPPED 2026-04-21)
Plan: 04b of ~7 (9 harder slot handlers + DELETE 4 ad-hoc gates + reduce snapshot path to pure cache + mark 7 detect-* helpers DEAD CODE — behaviorally-significant client plan completing the eventQueue migration) — COMPLETE
Next: 14.8-04c (visual UAT — exercise all 19 events end-to-end in sandbox + live PvP; window.__eventQueueDebug introspection; reset-mismatch tests; verify no double-rendering, no console warns from stubs, all spell-stage chain / turn banner / trigger blip / pending modal / fizzle / game-over visuals fire correctly)

Progress: ██████████████████░░ 90% (27/30 plans)

Status: Plan 14.8-04b shipped: behaviorally-significant client plan COMPLETE. All 19 EngineEvent types now have fully-implemented playEvent slot handlers. The 4 ad-hoc defer/buffer gates (sandbox frame queue, post-stage-frame, pending trigger blip, pending turn banner) DELETED — game.js net -479 lines. Snapshot path reduced to pure state-cache (onStateUpdate is 4 lines; sandbox_state handler is 22 inline lines). 7 detect-*/derive-* helpers marked DEAD CODE for plan 05 deletion. CSS additions: .fizzle-puff (💨 keyframe) + .event-queue-blocking informational scrim. 3 of 7 documented pending_modal kinds (tutor_select, trigger_pick, death_target_pick) wired today; the other 4 (conjure_deploy, revive_place, magic_cast_originator, post_move_attack) will gate automatically once engine emission is added (handler is generic). Spell-stage chain handler tracks chain depth in slotState.spellStageChain but visible card slam-in still driven by snapshot path's detectSpellCast (deliberate partial migration — plan 05 owns chain-open card identity). Verify gates all pass: node -c game.js clean, all 11 deleted symbols return grep -c 0, 7 DEAD CODE markers (≥7), 9 harder handler functions exist, no stub messages remain. Test posture: 1060 passed / 17 failed / 27 skipped — EXACT baseline match from plan 04a. Commits: b20b70d (feat Task 1: 9 harder slot handlers + commitEventToDom extension + .fizzle-puff/.event-queue-blocking CSS) + 1e02c79 (refactor Task 2: 4-gate deletion + onStateUpdate reduction + sandbox_state inline commit + 7 DEAD CODE markers). Both pending push (user pushes manually per milestone). Hook points for plan 04c (visual UAT): every animation flows through eventQueue with no double-rendering; window.__eventQueueDebug exposes spellStageChain/pendingModalKind/pendingModalDeadline live; reset mismatch test = trigger sandbox_reset mid-animation. Hook points for plan 14.8-05: 7 DEAD CODE markers enable bulk regex deletion; legacy state.last_trigger_blip dual-write deletable; pending_modal_opened emission gap (4 kinds) needs engine extension; commitEventToDom is 50% filled (phase_changed + game_over wired). Previous: Plan 14.8-01 shipped: foundation for "comprehensive phase-contract enforcement" is in place. New `src/grid_tactics/phase_contracts.py` module exports PHASE_CONTRACTS dict (41 entries across 5 categories: trigger, status, action, system, sandbox), PENDING_REQUIREMENTS dict (10 pending-bound action sources), OutOfPhaseError soft-failure exception, assert_phase_contract single enforcement entry point, get_enforcement_mode env-var driven (off|shadow|strict, default off, cached at module load with _reset_mode_cache for tests). 53 call sites tagged across effect_resolver.py (11) / react_stack.py (18) / action_resolver.py (23). 5 helper functions extended with contract_source kwarg (default None for back-compat): resolve_effect, resolve_effects_for_trigger, _resolve_conjure, _apply_effect_to_minion, _apply_effect_to_player. REQUIREMENTS.md gained CONTRACT-01..08. 19 passing tests in tests/test_phase_contracts.py (16 unit + 3 integration). 905 engine+server tests pass (+2 net from foundation tests); 24 pre-existing failures unchanged. Shadow-mode dry run on engine subset surfaces 102 contract-violation WARNINGs — the working baseline that plan 14.8-02 drives to zero. Two dominant smoking-gun patterns: (1) `action:play_card phase=REACT` from `resolve_summon_declaration_originator` (compound summon Window A → Window B); (2) `system:enter_end_of_turn phase=REACT` from `enter_end_of_turn` called inside `resolve_react_stack`'s tail. Both are documented inline as smoking guns for plan 14.8-02 disposition. Commits: 0683634 (Task 1: phase_contracts module + REQUIREMENTS) + 1447d0e (Task 2: 53 tag sites + 3 integration tests). Default mode = off so all existing CI runs unchanged. Per orchestrator decisions locked into plan: ContractSource string-tagged not IntEnum; OutOfPhaseError is soft (server catches, emits error event without crashing); sandbox is 5th category with prefix bypass; ON_DEATH allows (ACTION, REACT, START_OF_TURN, END_OF_TURN) explicitly (NOT wildcard); ON_PLAY allows (ACTION, REACT) explicitly; pending-bound actions check pending field FIRST then phase as fallback; pending-bound modeled as action: with requires_pending field, NOT a 6th category; PASSIVE intentionally absent (slated for deletion in plan 14.8-05). Hook points for 14.8-02: (1) `expected_trigger_sources()` and `expected_action_sources()` helpers in phase_contracts.py are the source of truth for enum coverage; (2) `_reset_mode_cache()` is the test fixture entry; (3) the smoking-gun list in 14.8-01-SUMMARY.md tells 14.8-02 exactly where to start its disposition pass; (4) shadow-mode WARNING messages include `source=`/`phase=`/`allowed=`/`pending_required=`/`unknown_source=`/`stack=` fields for structured parsing. Previous: Phase 14.7 (turn-structure-overhaul) completed plans 01-09 (plan 10 cleanup remains queued). `_showTurnBanner` 1.5s CSS overlay fires on every turn_number advance (multiplayer AND sandbox paths). `last_trigger_blip` transient GameState field carries animation payload `{trigger_kind, source_minion_id, source_position, target_position, effect_kind}` from `_resolve_trigger_and_open_react_window` to the client; cleared at top of every resolve_action so it's non-None for exactly one frame (lifecycle tested via `test_last_trigger_blip_cleared_on_next_frame`). Client `_fireTriggerBlipAnimation` pulses source tile + spawns center icon (⏰/⏳/💀/💚/💥/🔥/✨) + pulses target tile. Spell-stage now closes on ANY react window end via `detectReactWindowClose` (not just magic casts). Playwright UAT against live Railway v0.12.17 surfaced 4 issues — 3 auto-fixed as Rule 1/2 deviations, 1 resolved downstream: (A) sandbox `apply_action` auto-drain clobbered `last_trigger_blip` + REACT-phase transitions — fixed via `on_frame` callback in `SandboxSession.apply_action` that emits one `sandbox_state` per intermediate resolve_action call; (B) `_showTurnBanner` only wired in `applyStateFrame` (multiplayer) but not in `sandbox_state` handler (sandbox) — fixed by inline wiring in the sandbox handler; (C) `.turn-banner` CSS class collision with existing HUD flex row at game.css ~1116 — fixed by renaming new overlay to `.turn-transition-banner` / `-line1` / `-line2` / `@keyframes turn-transition-banner-in`; (D) font/size inheritance resolved as downstream of C. Commits: `92981da` (Task 1 — banner helper + CSS + applyStateFrame wire), `c11b9a2` (Task 2 — engine field + react_stack write + view_filter passthrough + client animation + 3 tests), `9c414f9` (Issue A fix — sandbox per-frame emission), `260b134` (Issues B + C fix — sandbox banner/blip wiring + CSS class rename). All pushed to master; Railway auto-deployed to v0.12.19. Test posture: 206 passed across test_game_state + test_view_filter + test_react_stack + tests/server/ (+new lifecycle + round-trip + view_filter enrich tests); broader suite unchanged baseline failures (training deckable-validation + tensor parity + 1 spectator — all predate 14.7-09). `node -c game.js` OK. 30 UAT screenshots in `.planning/debug/14.7-09-uat/` document the failure modes. Re-UAT deferred to orchestrator per standard 14.x posture (post-fix deploy ready; acid-test scenario is prohibition-react-chain for Issue A downstream). Hook points for 14.7-10: (1) `on_frame` callback pattern is the template for any future batch-apply / undo-redo paths that might clobber transient fields; (2) dual-path visual-wiring check (applyStateFrame + sandbox_state handler) is the lesson for any future state-transition-driven visuals; (3) CSS class collision audit (grep before adding new classes) is the lesson for new visual primitives. Previous: Plan 14.7-06 shipped: fizzle rule live. Effects whose targets/sources are no longer valid at resolution time silently no-op per spec §7.3. `_validate_target_at_resolve_time` helper in effect_resolver.py gates SINGLE_TARGET / ADJACENT / SELF_OWNER (OPPONENT_PLAYER + area effects never fizzle). `resolve_effect` gained keyword-only `source_minion_id` kwarg; fizzle gate runs BEFORE TargetType dispatch and returns the EXACT state object on fizzle (identity-preserving). Callers passing source_minion_id: resolve_effects_for_trigger, resolve_summon_effect_originator, _fire_passive_effects (legacy defensive). Magic/react/death callers leave it None (death triggers: source IS dead by definition — gate checks target only). `_resolve_trigger_and_open_react_window` detects fizzle via `state is prev_state`, pops the trigger WITHOUT opening a react window (no dead-air prompt), re-drains. 22 new tests: 16 effect_resolver (TestFizzleRulePhase14_7_06), 4 react_stack (TestPhase14_7_06_TriggerFizzle), 2 integration (TestFizzleRulePhase14_7_06Integration — §7.4 RGB-eats-only-promote-target + synthetic mid-drain source-death via in-memory Stinger CardLibrary). Commits: d4978c5 + 10afe1c. Test posture: 132 passed in verification suite; broader engine+server ~852 passed; baseline 2 unchanged. Previous: Plan 14.7-05b shipped: _cleanup_dead_minions migrated to turn-player-first PendingTrigger priority queue. ON_DEATH effects enqueue into pending_trigger_queue_{turn,other} (spec §7.2 turn-player-first). _resolve_trigger_and_open_react_window gained on_death branch: DESTROY/SINGLE_TARGET + PROMOTE-with-2+-candidates open existing pending_death_target modal (preserved verbatim); other effects resolve inline and open AFTER_DEATH_EFFECT react window. Module-level _cleanup_skip_drain reentrancy guard with try/finally prevents nested drain during chain-reaction cleanup. resolve_react_stack gained identity-based AFTER_DEATH_EFFECT early-exit (`state is not _pre_cleanup_state`). Spec §4.3 / §7.4 worked example works end-to-end. Sandbox round-trip test validates on_death PendingTriggers. Pre-14.7 ordering tests updated in-place via _drain_all_death_triggers helper. Commits: 6800264 + 890c4bc. Test posture: 223 passed in core test files + 5 new TestDeathTriggerPriorityQueue unit tests + 1 integration test + 1 sandbox round-trip = 7 new tests. Baseline failures unchanged at 8. Previous: Plan 14.7-07 shipped: react-condition matching is now react_context-aware. Three new ReactCondition values (OPPONENT_SUMMONS_MINION=15 / OPPONENT_START_OF_TURN=16 / OPPONENT_END_OF_TURN=17) appended forward-compat; _check_react_condition rewritten to dispatch on state.react_context. Prohibition (OPPONENT_PLAYS_MAGIC) is now correctly filtered OUT of legal_actions during AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT — a pre-14.7-07 subtle bug where a summon window would include Prohibition (matching via pending_action PLAY_CARD fallback). card_loader auto-picks new strings via reflective lookup; no JSON retagged. Existing TestSummonCompoundWindowsIntegration tests (14.7-04) continue to pass because _play_react bypasses legal_actions filtering. Commits: 604b64a (Task 1: enum + dispatch + 22 unit tests) + 5648759 (Task 2: 3 integration tests with in-memory synthetic CardLibrary). No deviations, plan executed exactly as written. Test posture: 884 non-RL tests pass (+25 new); baseline 8 failures unchanged. Previous: Plan 14.7-05 shipped: simultaneous-trigger priority queue + modal picker is now live for START_OF_TURN and END_OF_TURN triggers. PendingTrigger dataclass + 3 GameState fields + full serializer round-trip. fire_{start,end}_of_turn_triggers now enqueue into pending_trigger_queue_{turn,other} via _enqueue_turn_phase_triggers + drain_pending_trigger_queue. Drain algo: turn queue drains first (spec §7.2); >=2 sets picker_idx (opens modal); 1 auto-resolves; 0 falls through to other queue. _resolve_trigger_and_open_react_window is shared pop-and-open helper (used by auto-resolve AND TRIGGER_PICK handler — _apply_trigger_pick moves picked entry to front of queue then delegates, single-source-of-truth pop). Critical drain-recheck hook in resolve_react_stack sits AFTER _cleanup_dead_minions + is_game_over check, BEFORE return_phase dispatch — test_two_triggers_second_fires_after_first regression validates ordering. ActionType.TRIGGER_PICK=17 (reuses PLAY_CARD slot space, stride=GRID_SIZE, mirror of TUTOR_SELECT) + DECLINE_TRIGGER=18 (reuses PASS slot 1001). RL action space encode+decode wired, decode prioritizes trigger_picker (phase-agnostic gate). Server: enrich_pending_trigger_for_viewer mirrors 14.2 tutor asymmetric pattern (picker sees full options, opponent sees only picker_idx + queue_length). Registered at all 8 events.py fanout sites. Client: syncPendingTriggerPickerUI + showTriggerPickerModal reuse renderDeckBuilderCard + .tutor-modal CSS verbatim per user directive "we want to use existing modals". Sandbox god-mode always opens modal. _cleanup_dead_minions UNCHANGED — scope-fenced; Death: migration is 14.7-05b. Commits: eeda694 (feat Task 1) + 2cd7e66 (feat Task 2) + cc6ba84 (feat Task 3). All pushed to master; Railway auto-deployed. Test posture: 546 engine + server tests pass (+14 new across 5 files: 3 enum, 3 serialization, 6 drain/modal, 3 view_filter, 1 sandbox round-trip + test_action_type_count bumped). Auto-fixed 3 deviations: (a) double-pop in TRIGGER_PICK caught by test_trigger_pick_resolves_first_then_second (refactored _apply_trigger_pick to move-to-front), (b) RL action space unaware of TRIGGER_PICK/DECLINE_TRIGGER (added encode+decode following TUTOR pattern), (c) test_action_type_count bumped 17→19. Hook points for 14.7-05b: same queue pattern / same drain-recheck insertion point — on_death triggers can migrate using the same machinery. 14.7-06 (fizzle): insert liveness check at top of _resolve_trigger_and_open_react_window. 14.7-07 (OPPONENT_START/END conditions): react_context tags AFTER_START_TRIGGER / BEFORE_END_OF_TURN are already flowing to the window; react_condition matching just needs new enum values. 14.7-09 (blip UI): pending_trigger_picker_options payload already carries source_card_numeric_id + captured_position per entry for source→target blip anchors.

### Phase 14.8 Plan 04b closeout (2026-04-21)

Plan 14.8-04b shipped as the sixth plan of Phase 14.8 — the behaviorally-significant client plan completing the eventQueue migration. All 19 EngineEvent types now route through fully-implemented playEvent slot handlers; the 4 ad-hoc defer/buffer gates that grew up over Phase 14.7-09 are DELETED; onStateUpdate + sandbox_state handler reduced to pure snapshot-cache role. Snapshot path still alive (applyStateFrame + renderGame/renderSandbox commit DOM from state) but no longer drives animations — plan 05 deletes it. Commit trail:

- `b20b70d` feat(14.8-04b): 9 harder slot handlers + fizzle/scrim CSS (Task 1 — playReactWindowOpened pushes to slotState.spellStageChain LIFO; playReactWindowClosed pops + fires _spellStageOnReactClosed when chain empties + stage visually up; playPhaseChanged branches on payload.new for _flashPhaseLed; playTurnFlipped reuses _runTurnFlipVisuals verbatim; playTriggerBlip reuses _fireTriggerBlipAnimation verbatim; playPendingModalOpened sets pendingModalKind + 5min safety deadline + spawns .event-queue-blocking scrim; playPendingModalResolved clears + removes scrim; playFizzle scans gameState.board for source_minion_id → anchors .fizzle-puff (💨 350ms keyframe) to that tile or center; playGameOver reuses showGameOver; commitEventToDom extended for phase_changed (LED re-render) + game_over (defensive); CSS .fizzle-puff + .event-queue-blocking — game.css +35 lines)
- `1e02c79` refactor(14.8-04b): delete 4 ad-hoc gates + mark detect-* dead code (Task 2 — DELETED ~480 lines of sandbox frame queue + drainer/applier + _SB_HOLD_* visual budgets + post-stage-frame buffer + _hideSpellStage flush logic + pending-trigger-blip defer + pending-turn-banner same-turn-dedupe + _showTurnBannerOrDefer + _lastBannerTurnKey + applyStateFrameSelective references; REDUCED onStateUpdate to 4 lines (extract+applyStateFrame); INLINED sandbox_state socket handler as 22-line minimal commit (sandboxState write + autosave + renderSandbox); STRIPPED inline turn-banner + trigger-blip dispatch from _applyStateFrameImmediate; ANNOTATED 7 detect-*/derive-* helpers with `// DEAD CODE post-14.8-04b — plan 14.8-05 will delete` prefix)

Both commits pending push (user pushes manually per milestone).

Client changes (game.js net -479 lines: Task 1 +311 / Task 2 -599/+120; CSS +35 lines):

- **9 harder slot handlers** — every handler honors animation_duration_ms via _evDurationOr; reuses Phase 14.7-09 / 14-PLAY-03 visual primitives (no rewrites). playReactWindowOpened LIFO chain push (visible card slam-in still driven by snapshot path's detectSpellCast — chain handler only paces queue), playReactWindowClosed pops + closes stage when empty, playPhaseChanged + commitEventToDom phase_changed branch re-render LED, playTurnFlipped reuses _runTurnFlipVisuals (END LED → banner + START LED), playTriggerBlip reuses _fireTriggerBlipAnimation (source pulse → glyph → target pulse), playPendingModalOpened sets pendingModalKind to gate drainEventQueue + spawns .event-queue-blocking scrim + 5min safety deadline, playPendingModalResolved clears + removes scrim, playFizzle 💨 puff at source-minion tile (or center), playGameOver showGameOver overlay
- **4 ad-hoc gates DELETED** — verify-gated grep -c == 0 for: _sandboxFrameQueue, _pendingPostStageFrame, _pendingTriggerBlip, _pendingTurnBanner, enqueueSandboxFrame, _drainSandboxFrameQueue, _applySandboxFrame, _flushPendingPostStageFrame, _showTurnBannerOrDefer, _lastBannerTurnKey, applyStateFrameSelective (all 11 symbols)
- **Snapshot path → snapshot-cache** — onStateUpdate is now 4 lines, sandbox_state handler is 22-line inline commit (no queue, no derive-*, no pacing); _applyStateFrameImmediate stripped of inline turn-banner + trigger-blip dispatch (~40 lines removed)
- **DEAD CODE markers** — uniform `// DEAD CODE post-14.8-04b — plan 14.8-05 will delete` prefix on 7 helpers (detectSpellCast/SpellStageClose/ReactWindowClose, deriveAnimationJob/CardFlyJobs/DrawJobs/PlayerHpDeltaAnims) — meets ≥7 verify gate
- **commitEventToDom extended** — phase_changed re-renders both #phase-badge + #sandbox-phase-badge via _setPhaseLeds; game_over is defensive no-op (slot handler already opens overlay)

KEY DECISION: only 3 of 7 plan-documented pending_modal kinds wired today (tutor_select, trigger_pick, death_target_pick — what the engine emits). The other 4 (conjure_deploy, revive_place, magic_cast_originator, post_move_attack) are opened by snapshot-path sync* handlers reading pending_* state fields and DON'T currently emit EVT_PENDING_MODAL_OPENED. Per plan failure_handling: ship simpler kinds + flag complex for plan 05. The handler is generic (sets pendingModalKind=payload.modal_kind to gate drain) so the 4 unemitted kinds will gate automatically once engine emission is added.

KEY DECISION: spell-stage chain handler tracks chain depth in slotState.spellStageChain but does NOT drive the visible card slam-in. The actual _showSpellStage call is still triggered by snapshot path's detectSpellCast (reading prev→next grave/react_stack diff). Deliberate partial migration: 04b owns chain-close logic; plan 05 will own chain-open card identity once card_played event payload is wired to drive it. Rationale: react_window_opened payload carries react_context but NOT the specific card_numeric_id.

KEY DECISION: applyStateFrameSelective shim (described in plan body) NOT implemented — by reducing onStateUpdate + sandbox_state to pure state-commit, the snapshot path naturally stops invoking detect-*. Simpler than the selective-suppress shim the plan body described.

KEY DECISION: 5-minute pending-modal safety deadline is defensive only. Matching EVT_PENDING_MODAL_RESOLVED should arrive within tens of ms of user input for normal flows; deadline exists for server crash / tab close / socket drop edge cases.

KEY DECISION: _showTurnBanner's internal _lastBannerTurnKey dedupe guard DELETED. Dedupe is now lastSeenSeq-based at the eventQueue level — each EVT_TURN_FLIPPED carries unique seq; repeats dropped before reaching playTurnFlipped.

KEY DECISION: _hideSpellStage's post-stage-frame flush logic DELETED. Previously coordinated via _pendingPostStageFrame / _pendingTriggerBlip / _pendingTurnBanner globals + sandbox frame queue drain. With eventQueue, server emits react_window_close → trigger_blip → turn_flip in seq order, each handler calls done() only when animation completes, FIFO discipline reproduces user-expected ordering without any deferral.

Test posture:

- node -c src/grid_tactics/server/static/game.js: clean
- python -c 'import grid_tactics.server.app': clean
- tests/server + tests/test_event_serialization + tests/test_phase_contracts: 108/108 passed
- Broader engine+server suite (excluding RL/tensor/training/e2e): 1060 passed / 17 failed / 27 skipped — EXACT baseline match from plan 04a (same 17 documented pre-existing failures: 8 react_stack TestStartOfTurn/TestPhase14_7_05, 7 game_loop TypeError, 1 spectator, 1 game_flow ordering bug)

Decisions (also captured in 14.8-04b-SUMMARY.md frontmatter):

1. Only 3 of 7 pending_modal kinds wired (engine emits today); other 4 will gate automatically once engine extension lands. Generic handler.
2. Spell-stage chain handler is partial migration: owns chain-close, plan 05 owns chain-open card identity.
3. applyStateFrameSelective shim never needed — direct snapshot-path reduction is cleaner.
4. 5-min pending-modal safety deadline for abnormal cases only.
5. _lastBannerTurnKey dedupe replaced by lastSeenSeq.
6. _hideSpellStage post-stage flush replaced by FIFO ordering.
7. detect-*/derive-* helpers retained but DEAD CODE marked — bulk deletion in plan 05.
8. Fizzle source anchor via gameState.board scan; center fallback for off-board source.
9. commitEventToDom 50% filled (phase_changed + game_over); plan 05 fills mana/phase/legal_actions sync.

### Phase 14.8 Plan 04a closeout (2026-04-21)

Plan 14.8-04a shipped as the fifth plan of Phase 14.8 — first client-side plan. eventQueue infrastructure + 19-case dispatcher + 10 simpler slot handlers wired into game.js. Snapshot path (state_update / sandbox_state / applyStateFrame) and 4 ad-hoc gates STAY ALIVE; eventQueue runs alongside. Double-rendering for 10 covered events is the accepted tradeoff per plan failure_handling. Plan 04b finishes 9 harder handlers + deletes 4 gates; plan 05 deletes snapshot path. Commit trail:

- `67b268e` feat(14.8-04a): eventQueue infrastructure + dispatcher + socket wire (Task 1 — globals near AnimationQueue + resetEventQueue + onEngineEvents + drainEventQueue + commitEventToDom stub + playEvent 19-case dispatcher + playInstant + 10 stubbed playXyz + window.__eventQueueDebug + socket.on('engine_events', onEngineEvents) bind in initSocket + 6 sandbox-reset call sites)
- `0e47ebc` feat(14.8-04a): implement 10 simpler slot handlers (Task 2 — playMinionSummoned/Died/HpChange/Moved + playAttackResolved + playCardDrawn/Played/Discarded + playPlayerHpChange + _evDurationOr + _evTileForPos helpers; reuses Phase 14.3 Wave 2/3/4/7 + 14.5-06 Wave 6 + 14.7-09 burn-tick popup variants via enqueueAnimation pushes)

Both commits pending push (user pushes manually per milestone).

Client changes (game.js +410 lines net):

- **eventQueue / eventRunning / lastSeenSeq / slotState globals** — Inserted near AnimationQueue declaration (~line 2456) so it's adjacent to Phase 14.3 animation infrastructure. eventQueue holds inbound EngineEvent dicts in seq order; eventRunning gates re-entry; lastSeenSeq starts at -1 sentinel; slotState reserves spellStageChain (LIFO stack of opened-but-not-closed react windows), pendingModalKind (null while no modal; gates drain), pendingModalDeadline (safety timeout fallback) for plan 04b.
- **resetEventQueue()** — Single helper clears queue + eventRunning + lastSeenSeq + slotState. Called from 6 client-side sites matching server-side counter resets: onGameStart (live PvP fresh-game/rematch via RoomManager.request_rematch building new GameSession), sandboxActivate (sandbox screen entry — first sandbox_create or sandbox_load creates fresh SandboxSession), sandboxDeactivate (defensive on screen exit), sandbox-reset-btn click (matches SandboxSession.reset()), sandbox-load-file reader.onload (matches SandboxSession.load_dict() via JSON file load), sandbox-paste-btn click (load_dict via share-code paste), sandbox-slot-load-btn click (load_dict via server-saved slot). Without these matches, the next first event after a reset would arrive with seq=0 ≤ lastSeenSeq=N from prior session and be silently dropped.
- **onEngineEvents(payload)** — Bound once in initSocket via `socket.on('engine_events', onEngineEvents)` — single subscription covers both live PvP and sandbox (same Socket.IO transport; payload.is_sandbox flag is informational). Iterates payload.events, dedupes via `if (ev.seq <= lastSeenSeq) console.warn + return`, pushes accepted events into eventQueue, stashes payload.final_state + legal_actions into window.__lastFinalState / __lastLegalActions for error-recovery snapshot fallback, kicks drainEventQueue.
- **drainEventQueue()** — Shifts one event from queue head, sets eventRunning=true, calls playEvent(ev, onSlotDone) wrapped in try/catch (handler crash → console.error + eventRunning=false + drainEventQueue() re-entry; no deadlock). Slot's done callback re-enters: eventRunning=false → commitEventToDom(ev) → drainEventQueue(). Modal gate at top: `if (slotState.pendingModalKind !== null) return;` — reserved for plan 04b's pending_modal_opened/resolved pair.
- **commitEventToDom(ev)** — STUB in 04a. The plan body shows it patching mana / phase / legal_actions per event, but those mutations are owned by the snapshot path (state_update emits the full state) — patching twice would race. Stub kept so plan 04b/05 has a clean hook point once snapshot path is removed.
- **playEvent(ev, done) dispatcher** — Switch with all 19 case branches. 10 routed to playMinionSummoned / playMinionDied / playMinionHpChange / playMinionMoved / playAttackResolved / playCardDrawn / playCardPlayed / playCardDiscarded / playInstant (mana_change) / playPlayerHpChange. 9 stubbed with `console.warn(\"[eventQueue] <type>: stub — implemented in 04b\") + setTimeout(done, 0)`: react_window_opened, react_window_closed, phase_changed, turn_flipped, trigger_blip, pending_modal_opened, pending_modal_resolved, fizzle, game_over. Default branch warns on unknown event type.
- **playInstant(ev, done)** — Zero-duration fallback for events whose state is committed by snapshot path (mana_change in 04a). Just setTimeout(done, 0).
- **window.__eventQueueDebug** — Mirrors window.__animDebug pattern. Exposes queue / running / lastSeenSeq / slotState getters + reset() hook for browser devtools.

10 simpler slot handlers — each honors animation_duration_ms via `_evDurationOr(ev, fallback)` helper (clamps with per-handler default), pushes/spawns the visual, chains done() at wall-clock duration:

| Handler | Visual | Wall duration | Reuse |
|---------|--------|---------------|-------|
| playMinionSummoned | enqueueAnimation type='summon' | 600ms | Phase 14.3 Wave 2 (playSummonAnimation: tile-class + grid-shake) |
| playMinionDied | none in 04a | 0ms | Snapshot path's burn-death detection + 04b trigger_blip |
| playMinionHpChange | showFloatingPopup at position tile (heal/burn-tick/combat-damage variant via cause field) | 400ms | Phase 14.3 Wave 7 + 14.7-09 burn-tick popup |
| playMinionMoved | enqueueAnimation type='move' | 350ms | Phase 14.3-03 (playMoveAnimation: lift → translate → drop) |
| playAttackResolved | enqueueAnimation type='attack' (looks up attacker_pos via gameState; derives damage from defender_hp_before/after) | 500ms | Phase 14.3 Wave 4 (melee/ranged split via attack_range) |
| playCardDrawn | enqueueAnimation type='draw_own' (own + card_numeric_id present) or 'draw_opp' (face-down) | 350ms | Phase 14.5-06 Wave 6 |
| playCardPlayed | none in 04a | 0ms | Spell stage (04b) + summon (above) |
| playCardDiscarded | none in 04a | 0ms | Snapshot path's deriveCardFlyJobs (event arrives post-render — source rect is gone) |
| mana_change (via playInstant) | none | 0ms | Snapshot path commits the new mana |
| playPlayerHpChange | inline damage-popup span over hp stat element + hp-flash class | 400ms | Mirrors derivePlayerHpDeltaAnims / playHpDamagePopup |

KEY DECISION: snapshot path STAYS COMPLETELY INTACT in 04a. The plan body describes an applyStateFrameSelective shim that would suppress detect-* helpers in applyStateFrame for the 10 covered event types, but the existing detect logic is INLINE in _applyStateFrameImmediate (heal/burn HP popups at line ~3171, fatigue nudge, turn banner trigger, trigger blip dispatch) — not factored into named detect-* helpers. Refactoring is itself plan 04b/05 work. Plan failure_handling explicitly licenses the double-render tradeoff: server emits state_update FIRST and engine_events SECOND in the same socket flush → snapshot path's animation jobs queue ahead of event-driven ones in the SAME animQueue → they run sequentially, not in parallel (visible posture: 'snapshot anims, then event anims, in order' — twice as long but not overlapping).

4 ad-hoc gates UNTOUCHED per plan must_haves: _sandboxFrameQueue + _drainSandboxFrameQueue + _applySandboxFrame + _flushPendingPostStageFrame + _pendingPostStageFrame + _pendingTriggerBlip + _pendingTurnBanner + _showTurnBannerOrDefer all still wired through socket.on('sandbox_state', ...) + applyStateFrame. Deletion is plan 04b's job after all 19 handlers are wired.

Two deviations from plan body:

1. **applyStateFrameSelective shim NOT implemented** (deferred to 04b/05 per failure_handling — see KEY DECISION above). The plan's intent (eventQueue suppresses snapshot path for 10 covered events) is preserved; the implementation defers the actual suppression mechanism to plan 04b/05 where the detect-* helpers can be properly factored out.
2. **`.event-queue-blocking` CSS scrim NOT added** — plan body describes a low-opacity overlay added during pending_modal_opened to gate input. Since pending_modal_opened is a stubbed handler in 04a, the scrim has no consumer yet. Plan 04b adds the scrim when it implements the modal gate.

Otherwise plan executed exactly as written. No Rule 1 / Rule 2 / Rule 3 auto-fixes triggered — engine + server tests passed first try and node -c game.js was clean from first save.

Test posture:

- node -c src/grid_tactics/server/static/game.js: clean (no syntax errors)
- python -c 'import grid_tactics.server.app': clean
- tests/test_event_serialization.py: 21/21 passed
- tests/server: 68/68 passed
- Broader engine+server suite (excluding RL/tensor/training/e2e): 1060 passed / 17 failed / 27 skipped — exact baseline match from plan 03b. Same 17 documented pre-existing failures: 8 react_stack TestStartOfTurn/TestPhase14_7_05, 7 game_loop TypeError, 1 spectator, 1 game_flow ordering bug.

Decisions (also captured in 14.8-04a-SUMMARY.md frontmatter):

1. Snapshot path stays alive in 04a — eventQueue runs alongside; double-rendering accepted per plan failure_handling.
2. Event-driven AnimationQueue jobs pass stateAfter=gameState (already post-event from snapshot path which fires first) so existing playSummonAnimation/playMoveAnimation wrappers don't crash on undefined frame; inner applyStateFrame call becomes idempotent noop diff + re-render.
3. playMinionDied, playCardPlayed, playCardDiscarded are zero-duration in 04a — visuals are already covered by snapshot path or arrive from later events (trigger_blip in 04b for death, react_window_opened/closed for spell-stage-handled card_played).
4. playCardDrawn routes to draw_own/draw_opp based on viewer + card_numeric_id presence (view_filter strips identity for opponent draws on live PvP path).
5. playAttackResolved looks up attacker_pos via gameState (event payload only carries attacker_id); skip visual gracefully if attacker died and is no longer in gameState (rare race during chain reactions).
6. playMinionHpChange uses ev.payload.cause to color-route: cause='burn' → 🔥 + orange burn-tick; positive delta → 💚 + green heal; otherwise → ⚔️ + red combat-damage.
7. Handler error isolation via try/catch in drainEventQueue — handler crash logs error and advances queue (no deadlock).
8. 9 harder handlers stubbed with per-type console.warn — browser devtools shows one warning per event type per fire by design (makes migration boundary visible). Plan 04b removes warns as it implements each.
9. resetEventQueue() called BEFORE socket.emit at sandbox-reset / sandbox-load / paste / slot-load sites so client-side anchor matches server-side _next_event_seq=0 reset.

Hook points for plan 14.8-04b (9 harder handlers + 4-gate deletion):

1. 9 stubbed handlers ready for replacement — each currently console.warn + setTimeout(done, 0); replace bodies, remove warns.
2. slotState fields reserved (spellStageChain LIFO stack for spell-stage chain handler, pendingModalKind to gate drain, pendingModalDeadline safety timeout).
3. 4 ad-hoc gates ready for deletion once 04b's turn_flipped + spell-stage chain + trigger_blip handlers are live: _sandboxFrameQueue + _drainSandboxFrameQueue + enqueueSandboxFrame + _applySandboxFrame + _pendingPostStageFrame + _flushPendingPostStageFrame + _pendingTriggerBlip + _pendingTurnBanner + _showTurnBannerOrDefer.
4. commitEventToDom stub waiting for plan 04b/05 to fill in event-driven DOM mutations once snapshot path is suppressed.
5. Modal gate `if (slotState.pendingModalKind !== null) return;` ready to receive pending_modal_opened set / pending_modal_resolved clear.

Hook points for plan 04c (visual UAT): 10 covered events should produce visible animations matching existing snapshot-driven ones (currently double-renders sequentially — 04b expected to fix before UAT); 9 stubbed events log warnings (UAT can verify warnings gone after 04b); window.__eventQueueDebug exposes live queue / running / lastSeenSeq for inspection; mismatch test = trigger sandbox reset mid-action (eventQueue should clear and re-anchor at seq=0 without dropping next event).

Hook points for plan 14.8-05 (snapshot deletion): applyStateFrame + _applyStateFrameImmediate + inline detect-* logic become DEAD code once 04b suppresses them and eventQueue handlers drive everything; socket.on('state_update', ...) and socket.on('sandbox_state', ...) deletable once server stops emitting them per plan 03b's dual-emit hook; commitEventToDom stub becomes the place to land any residual mana / legal_actions / pending-modal sync that snapshot path used to handle.

### Phase 14.8 Plan 03b closeout (2026-04-21)

Plan 14.8-03b shipped as the fourth plan of Phase 14.8 — server-side engine_events Socket.IO emit + M3 next_event_seq field on both Session classes. Commit trail:

- `b39d615` feat(14.8-03b): next_event_seq M3 + sandbox EventStream + per-viewer event filter (Task 1 — GameSession.next_event_seq + SandboxSession._next_event_seq + apply_action returns events + apply_sandbox_edit verb dispatch + filter_engine_events_for_viewer)
- `e1f306b` feat(14.8-03b): wire engine_events Socket.IO emit + 21 tests (Task 2 — handle_submit_action EventStream wiring + engine_events emission alongside state_update/sandbox_state + 8 sandbox edit handlers refactored + 9c414f9 per-frame hack removed + 21 new tests)

Both commits pending push (user pushes manually per milestone).

Server changes:

- **NEW field on `GameSession` (M3)** — `next_event_seq: int = 0` initialized in `__init__`. Each `EventStream(next_seq=session.next_event_seq)` per `submit_action` seeds from the counter; after success `stream.next_seq` is written back. Resets to 0 on rematch implicitly via `RoomManager.request_rematch` building a fresh GameSession.
- **NEW field on `SandboxSession` (M3)** — `_next_event_seq: int = 0`. Same per-call / write-back pattern. Resets to 0 EXPLICITLY in `reset()` and `load_dict()` so loaded saves / fresh empty state start the counter at 0 — the client treats it as a brand-new session and re-anchors `lastSeenSeq`.
- **`SandboxSession.apply_action` refactored** — Returns `list[EngineEvent]` instead of None. Constructs ONE EventStream per call seeded from `_next_event_seq`, threads it through every `resolve_action` (user action + every drained auto-PASS), persists `stream.next_seq` back. The 9c414f9 `on_frame` per-frame callback parameter is preserved as a back-compat shim but no longer used by the server (handler passes `None`).
- **NEW `SandboxSession.apply_sandbox_edit(verb, payload)`** — Verb dispatch helper for 14 sandbox-edit verbs (cheat_mana, cheat_hp, set_active, add_card_to_zone, move_card_between_zones, place_on_board, import_deck, undo, redo, reset, load, load_slot, save_slot, set_player_field). Each verb maps to one or more EVT_* event types tagged `contract_source='sandbox:<verb>'`. Bypasses phase-contract assertions (sandbox: prefix) but flows through the SAME EventStream pipeline as engine actions — orchestrator decision #5 made concrete.
- **NEW `view_filter.filter_engine_events_for_viewer(events, viewer_idx, *, god_mode=False)`** — Per-viewer EngineEvent filter. EVT_CARD_DRAWN strips card identity (numeric_id, card_id, stable_id, name) for opponent; EVT_PENDING_MODAL_OPENED strips options (replaces with option_count) for non-picker. god_mode=True bypasses ALL redaction (sandbox + spectator-god). Owner-key resolution uses EXPLICIT `is None` checks NOT `or`-chains because P1=0 is FALSY in Python.
- **`server/events.py` rewiring** — `_emit_state_to_players` + `_emit_sandbox_state` + `_fanout_state_to_spectators` gain optional `events` kwarg; emit NEW `engine_events` Socket.IO message per viewer ALONGSIDE existing `state_update` / `sandbox_state` (dual-emit for back-compat — old clients ignore the new frame). `handle_submit_action` constructs ONE EventStream per call, threads through `resolve_action` + every `enter_start_of_turn` / `enter_end_of_turn` + drained PASSes inside the auto-advance loop. `handle_sandbox_apply_action` REMOVES the 9c414f9 per-frame on_frame hack — apply_action returns events, ONE engine_events socket emit per call regardless of drain depth. 8 sandbox edit handlers refactored to call `apply_sandbox_edit` and emit engine_events.
- **`react_stack.py` (Rule 1 fix)** — Pre-existing bug from plan 03a: `EVT_PENDING_MODAL_OPENED` referenced at lines 465 + 484 inside `drain_pending_trigger_queue` but not imported. Surfaced only when 03b wired event_collector to actually flow into that path. Added to imports.

Per-Viewer Filter Coverage:

| Event Type                | Owner Field Checked         | Redaction                                      |
|---------------------------|------------------------------|------------------------------------------------|
| EVT_CARD_DRAWN            | player_idx / owner_idx / owner | card_numeric_id / card_id / stable_id / name → None |
| EVT_PENDING_MODAL_OPENED  | owner_idx / picker_idx / player_idx (explicit None checks) | options → None; option_count = len(options) |
| EVT_CARD_DISCARDED        | (face-up info, no redaction) | None                                           |
| EVT_TRIGGER_BLIP          | (public board event)         | None                                           |
| All other events          | (public)                     | None — pass through by reference               |

god_mode=True bypasses ALL redaction.

Test posture:

- tests/test_event_serialization.py NEW (21 tests, ~580 lines): 2 round-trip + 6 per-viewer filter (incl. P1=0 owner edge case) + 5 sandbox emission (incl. ONE-emit-per-apply_action architectural fix verification) + 2 live PvP emission + 6 M3 monotonicity (init=0, monotone-strictly-increasing across mixed apply_action/apply_sandbox_edit, reset semantics on reset() and load_dict())
- Focused subset (server + engine_events + view_filter + pvp + phase_contracts + invariants + new tests): 280 passed / 27 skipped
- Broader engine+server suite excluding RL/tensor/training/e2e: 1060 passed / 17 failed / 27 skipped — failure count matches documented baseline (16 from plan 03a + 1 game_flow ordering bug also from plan 03a baseline that surfaces only when test_event_serialization runs before test_game_flow due to socketio test client state interactions; reproduced on baseline by stashing changes — pre-existing, NOT caused by this plan)
- NET +21 tests passing over plan 14.8-03a baseline

Decisions (all captured in SUMMARY frontmatter):

1. Per-call EventStream pattern identical for live PvP and sandbox.
2. ONE EventStream per submit_action / apply_action call covers entire chain (auto-advance loop, drained PASSes).
3. 9c414f9 per-frame emit hack DECOMMISSIONED. Pacing moves to event animation_duration_ms.
4. Sandbox edit verbs flow through apply_sandbox_edit with `contract_source='sandbox:<verb>'` (orchestrator decision #5 concrete).
5. filter_engine_events_for_viewer uses EXPLICIT `is None` checks NOT `or`-chains (P1=0 falsy footgun).
6. god_mode bypass returns input unchanged (no copy needed — frozen dataclass invariant).
7. Dual-emit pattern for back-compat: both legacy snapshot AND new event stream fire.
8. Save/load handlers NOT refactored (saves are side-effect-only; loads use load_dict which already resets seq counter — 14 verbs covered, 2 intentional pass-throughs from soft-target 16).

Hook points for plan 14.8-04a (client eventQueue):

1. **engine_events payload shape:** `{events: [...], final_state: <snapshot>, legal_actions: [...], your_player_idx: int, is_spectator?: bool, is_sandbox?: bool}`. Events list is per-viewer-filtered EngineEvent.to_dict() output in seq order.
2. **final_state matches state_update.state** — client uses it as post-event reconciliation point.
3. **requires_decision=True** on EVT_PENDING_MODAL_OPENED gates eventQueue until matching RESOLVED arrives.
4. **triggered_by_seq** on nested-trigger events lets client visualize trigger nesting.

Hook points for plan 14.8-04b (lastSeenSeq dedup):

1. Session.next_event_seq + SandboxSession._next_event_seq are the monotone references.
2. Reset semantics wired: rematch (live PvP) / reset/load (sandbox).

Hook points for plan 14.8-05 (strict-mode flip + legacy field deletion):

1. Drop state_update + sandbox_state emits once clients consume engine_events exclusively.
2. Drop state.last_trigger_blip dual-write (also from plan 03a).
3. Flip CONTRACT_ENFORCEMENT_MODE=strict.

Hook points for plan 14.8-06 (UAT): un-skip M1 react_window symmetry placeholder once 04a/b ship.

### Phase 14.8 Plan 03a closeout (2026-04-21)

Plan 14.8-03a shipped as the third plan of Phase 14.8 — engine event stream wire format (EngineEvent + EventStream primitives + 19 event types + event_collector kwarg threaded through engine). Commit trail:

- `d7c7c68` feat(14.8-03a): engine_events module + EngineEvent + EventStream + 19 event types (Task 1a — module + 14 unit tests)
- `dce9a02` feat(14.8-03a): thread event_collector kwarg through engine + emit 19 event types (Task 1b — threading + emission + 6 integration tests)

Both commits pending push (user will push manually per milestone).

Engine changes:
- **NEW `src/grid_tactics/engine_events.py` (370 lines)** — EngineEvent frozen dataclass (type, contract_source, seq, payload, animation_duration_ms, triggered_by_seq, requires_decision) + EventStream collector (monotonic seq, push/pop_parent for inline-trigger nesting, to_dict_list for socket fanout) + 19 EVT_* constants enumerated explicitly + ALL_EVENT_TYPES frozenset + DEFAULT_DURATION_MS table (calibrated to existing game.css timings, e.g., EVT_TURN_FLIPPED=1500ms matches banner CSS, EVT_TRIGGER_BLIP=900ms matches blip CSS).
- **`src/grid_tactics/effect_resolver.py`** — event_collector kwarg added to resolve_effect, resolve_effects_for_trigger, _enter_pending_tutor, _resolve_conjure. EVT_PENDING_MODAL_OPENED emits inside _enter_pending_tutor with requires_decision=True.
- **`src/grid_tactics/react_stack.py`** — event_collector kwarg added to 13 functions: tick_status_effects, drain_pending_trigger_queue, fire_start/end_of_turn_triggers, _resolve_trigger_and_open_react_window, _close_end_of_turn_and_flip, enter_start/end_of_turn, close_start/end_react_*, handle_react_action, _play_react, resolve_react_stack, resolve_summon_declaration/effect_originator. Emissions: EVT_MINION_HP_CHANGE (burn ticks), EVT_TURN_FLIPPED (_close_end_of_turn_and_flip), EVT_PHASE_CHANGED (enter_start/end_of_turn + close_start_react_and_enter_action), EVT_REACT_WINDOW_OPENED (_resolve_trigger_and_open_react_window + enter_start/end_of_turn INCL. shortcut path per orchestrator decision #3), EVT_REACT_WINDOW_CLOSED (close_start/end_react_* + enter_start/end shortcut + resolve_react_stack tail), EVT_TRIGGER_BLIP (_resolve_trigger_and_open_react_window, DUAL-write with state.last_trigger_blip field during migration), EVT_FIZZLE (fizzle path), EVT_MINION_SUMMONED (resolve_summon_declaration_originator post-Window-A), EVT_PENDING_MODAL_OPENED (drain_pending_trigger_queue 2+-entry branches), EVT_CARD_PLAYED + EVT_MANA_CHANGE (_play_react).
- **`src/grid_tactics/action_resolver.py`** — event_collector kwarg added to resolve_action + _cleanup_dead_minions + _check_game_over (3 functions). DIFF-BASED emission sweep at end of resolve_action dispatch: snapshot pre-action mana/hp/grave_len tuples, sweep at end, emit EVT_MANA_CHANGE / EVT_PLAYER_HP_CHANGE / EVT_CARD_DISCARDED for any delta. Covers all 8 action handlers (PASS/DRAW/MOVE/PLAY_CARD/ATTACK/SACRIFICE/TRANSFORM/ACTIVATE_ABILITY) uniformly with ONE emission point — reduces instrumentation churn ~10x vs per-handler approach. Per-action emissions: EVT_CARD_DRAWN (DRAW), EVT_MINION_MOVED (MOVE with from/to snapshot), EVT_CARD_PLAYED (PLAY_CARD), EVT_ATTACK_RESOLVED (ATTACK with combatant snapshots — attacker_id/defender_id/hp_before/hp_after/killed flags). EVT_MINION_DIED in _cleanup_dead_minions (one per dead minion, instance_id order). EVT_GAME_OVER in _check_game_over (winner+reason payload). EVT_PENDING_MODAL_RESOLVED in death_target_pick handler.

All emissions wrapped in `if event_collector is not None:` so back-compat invariant holds: production callers (none yet pass a collector) see zero behavior change.

Event Type → Emission Site Coverage (all 19 types verified emitting from at least one site via grep+frozenset audit):

| Event Type | Engine Site | Contract Source |
|---|---|---|
| minion_summoned | resolve_summon_declaration_originator | system:resolve_summon_declaration |
| minion_died | _cleanup_dead_minions | system:cleanup_dead_minions |
| minion_hp_change | tick_status_effects (burn) | status:burn |
| minion_moved | resolve_action MOVE | action:move |
| attack_resolved | resolve_action ATTACK | action:attack |
| card_drawn | resolve_action DRAW | action:draw |
| card_played | resolve_action PLAY_CARD + _play_react | action:play_card / action:play_react |
| card_discarded | resolve_action grave-diff sweep | action:{action_type} |
| mana_change | resolve_action mana-diff sweep + _play_react | action:{action_type} |
| player_hp_change | resolve_action hp-diff sweep | action:{action_type} |
| react_window_opened | _resolve_trigger_and_open_react_window + enter_start/end_of_turn (incl. shortcut) | system:enter_react |
| react_window_closed | close_*_react_* + enter_start/end_of_turn shortcut + resolve_react_stack tail | system:close_react_window |
| phase_changed | enter_start/end_of_turn + close_start_react_and_enter_action | system:enter_start/end_of_turn / system:close_react_window |
| turn_flipped | _close_end_of_turn_and_flip | system:turn_flip |
| trigger_blip | _resolve_trigger_and_open_react_window (DUAL-write) | derived from trigger.trigger_kind |
| pending_modal_opened | _enter_pending_tutor + drain_pending_trigger_queue | trigger:on_play / system:drain_triggers |
| pending_modal_resolved | resolve_action death_target_pick handler | action:death_target_pick |
| fizzle | _resolve_trigger_and_open_react_window fizzle path | derived from trigger.trigger_kind |
| game_over | _check_game_over | system:check_game_over |

Test posture:
- tests/test_engine_events.py NEW (20 tests): 14 unit (dataclass roundtrip + frozen invariant + stream monotonicity + parent nesting + type coverage + unknown-type rejection + starting seq offset) + 6 integration (default-silent path + engine emission spot checks + seq monotonic across call + seq preserved across calls + shortcut path symmetry per decision #3).
- Engine subset (test_react_stack + test_action_resolver + test_effect_resolver + test_phase_contracts + test_phase_contract_invariants + test_engine_events): 312 passed / 8 failed (8 pre-existing baseline) / 27 skipped.
- Broader engine+server suite excluding RL/tensor/training/e2e: 990 passed / 16 failed (16 pre-existing baseline) / 27 skipped — NET +20 tests passing over plan 14.8-02 baseline 970/16.
- Zero regressions: same 16 baseline failures (8 react_stack TestStartOfTurn/Phase14_7_05, 7 game_loop TypeError, 1 spectator, 1 game_flow ordering bug) documented across plans 14.8-01 → 14.8-02 → 14.8-03a unchanged.

Decisions (all captured in SUMMARY frontmatter):
1. EventStream is per-call, not per-game. Session owns persistent next_event_seq; each resolve_action gets fresh stream seeded with that counter; after call, session writes stream.next_seq back. Monotonic seq across game lifetime.
2. EngineEvent is frozen dataclass — wire format stable for call duration; prevents accidental mutation.
3. 19 event types enumerated via ALL_EVENT_TYPES frozenset — EventStream.collect rejects unknown via AssertionError so typos surface in tests.
4. DIFF-BASED emission for player-state changes (mana/hp/grave) — snapshot at top of resolve_action, sweep at end of dispatch. Covers all 8 action handlers uniformly with ONE emission site. ~10x less instrumentation than per-handler approach.
5. Shortcut-path emits zero-duration window-open + window-close pair (orchestrator decision #3). Client treats animation_duration_ms=0 as instant; symmetry simplifies the client's reduce loop — every START/END transition produces SAME event sequence regardless of trigger presence.
6. Trigger-blip DUAL-write during migration — _resolve_trigger_and_open_react_window writes BOTH state.last_trigger_blip (Phase 14.7-09 legacy) AND emits EVT_TRIGGER_BLIP. Plan 14.8-05 deletes the field.
7. Pending-modal events use requires_decision=True on OPENED + False on RESOLVED — client's eventQueue (plan 04a) gates the queue at OPENED until matching RESOLVED arrives.
8. Lazy import of EVT_* constants inside if event_collector is not None: blocks in heavy threading sites (e.g. _play_react) to keep cold path zero-cost.

Coverage gaps documented for plan 03b: conjure_deploy / revive_place / decline_post_move_attack / magic_cast_originator pending-modal events NOT yet emitted (pending fields ARE set). Plan 03b's server-side wiring will surface via same emission protocol. Not a blocker — tutor + trigger_pick + death_target cover the highest-traffic modal paths and validate the pattern.

Hook points for plan 14.8-03b (server-side wiring):
1. Session.next_event_seq slot: initialize to 0, seed each EventStream(next_seq=...) per resolve_action call, persist back after call.
2. Socket fanout: `for ev in stream.events: socket.emit("engine_event", ev.to_dict())` — or batch via `stream.to_dict_list()`.
3. Sandbox event emission: cheats (cheat_mana, undo, etc.) emit events tagged `contract_source="sandbox:<verb>"` via same EventStream protocol — bypasses contract assertion but flows through same wire format.
4. Pending-modal coverage gaps listed above (4 modal kinds not emitting yet).

Hook points for plan 14.8-04a (client eventQueue):
- Wire format is LOCKED. EngineEvent fields stable.
- Per-event payload schemas can be defined per type without engine changes.
- triggered_by_seq lets client visualize trigger nesting.
- requires_decision=True at OPENED events gates eventQueue until matching RESOLVED event arrives.
- animation_duration_ms=0 marks shortcut events treated as instant (orchestrator decision #3).

Hook points for plan 14.8-05 (strict-mode flip + delete legacy fields):
- Trigger-blip dual-write makes the migration explicit — deletes state.last_trigger_blip field write in _resolve_trigger_and_open_react_window once clients consume EVT_TRIGGER_BLIP (plan 04b ships).

Hook points for plan 14.8-06 (UAT):
- Un-skip the M1 react_window symmetry placeholder in test_phase_contract_invariants.py — shortcut-path emission is wired and tested by test_react_window_opened_emitted_on_shortcut_path.

### Phase 14.7 Plan 09 closeout (2026-04-19)

Plan 14.7-09 shipped as the eighth plan of Phase 14.7 — visual layer (turn banner + spell-stage generalization + start/end/death trigger blips). Commit trail:

- `92981da` feat(14.7-09): `_showTurnBanner` overlay helper + spell-stage generalization — `.turn-transition-banner` CSS keyframes, applyStateFrame wiring on turn_number advance, `detectReactWindowClose` drives spell-stage close across all react_contexts (Task 1)
- `c11b9a2` feat(14.7-09): `last_trigger_blip` engine field + transient-lifecycle clear + `_resolve_trigger_and_open_react_window` write + view_filter passthrough + client `_fireTriggerBlipAnimation` + CSS + 3 tests (Task 2)
- `9c414f9` fix(14.7-09): sandbox auto-drain emits per-frame via new `on_frame` callback in `SandboxSession.apply_action` — transient `last_trigger_blip` + REACT-phase transitions now reach the client (Issue A)
- `260b134` fix(14.7-09): CSS class rename (`.turn-banner` → `.turn-transition-banner` to resolve collision with HUD flex row at game.css ~1116) + sandbox_state handler wired to fire banner + blip inline (Issues B + C; Issue D resolved downstream)

All four commits pushed to master; Railway auto-deployed to v0.12.19.

Engine changes:
- `GameState.last_trigger_blip: Optional[dict] = None` — transient field with lifecycle: SET inside one resolve_action call (by `_resolve_trigger_and_open_react_window` before opening a react window), CLEARED at the top of the NEXT resolve_action call. Non-None for exactly ONE frame. Dict shape: `{trigger_kind, source_minion_id, source_position: [r,c], target_position: [r,c]|None, effect_kind}`. Round-trips through to_dict/from_dict as-is (JSON-native).
- `resolve_action`: added 2-line clear-at-top that sets `last_trigger_blip=None` if it was set (lifecycle guarantee).
- `_resolve_trigger_and_open_react_window` (react_stack.py): writes the blip payload into `state` just before the final `replace(..., phase=TurnPhase.REACT, ...)` return. Non-intrusive inline addition.
- view_filter: unchanged — `last_trigger_blip` flows through via `state.to_dict()` which was already raw-copying GameState fields.

Server / sandbox changes:
- `SandboxSession.apply_action(action, on_frame=None)`: optional callback fires AFTER each `resolve_action` call (user action + every drained PASS). When provided, each intermediate state emits its own frame. `_last_prev_state` + `_last_action` are updated per drain step (paired with `pass_action()`) so `enrich_last_action.attacker_pos` stays accurate — PASS frames have no attacker_pos → no spurious animation replay. Default `on_frame=None` preserves legacy behavior for all existing callers (tests, direct apply_action).
- `handle_sandbox_apply_action` (events.py): passes `_emit_sandbox_state` as the callback so the client receives one sandbox_state per intermediate state. The trailing single emit was removed (it's redundant — the final drain emit already fires via on_frame).

Client changes:
- `_showTurnBanner(turnNumber, activePlayerIdx)` at game.js ~3381 — creates a DOM overlay with `.turn-transition-banner` class, two stacked lines (`TURN N` / `PLAYER N`), auto-removes after 1.8s. Removes any prior banner first to handle rapid turn flips.
- `_fireTriggerBlipAnimation(blip)` at game.js ~3430 — pulses source tile with `.anim-trigger-source`, spawns center icon via `.trigger-blip-center-icon`, pulses target tile with `.anim-trigger-target`.
- `_triggerBlipIcon(blip)` at game.js ~3416 — selects center glyph based on trigger_kind (on_death=💀, start_of_turn=⏰, end_of_turn=⏳) with effect_kind fallbacks (heal=💚, damage=💥, apply_burning=🔥, ✨).
- `applyStateFrame` (multiplayer) at game.js ~2878 — fires banner on turn_number advance; fires blip on `last_trigger_blip` change.
- `sandbox_state` handler (sandbox) at game.js ~7180 — mirrors the same two checks inline, using `prevForFly` as the previous state.
- CSS at game.css ~316: `.turn-transition-banner` / `-line1` / `-line2` + `@keyframes turn-transition-banner-in` (1.5s fade-in + scale-bounce + hold + fade-out); at ~356 `.anim-trigger-source` / `.anim-trigger-target` tile-pulse keyframes + `.trigger-blip-center-icon` + `@keyframes trigger-blip-in`.

UAT posture (standard 14.x):
- First UAT pass on v0.12.17 FAILED with 4 issues (A, B, C HIGH + D LOW).
- All 4 auto-fixed in one continuation session as Rule 1/2 deviations.
- Re-UAT deferred to orchestrator. v0.12.19 is live on Railway; re-run checklist items #2/#3/#4/#5/#7. Acid-test scenario: prohibition-react-chain in sandbox (validates multi-frame emission + spell-stage close together).
- 30 UAT artifacts in `.planning/debug/14.7-09-uat/` document first-pass failure modes.

Test posture:
- Plan verification suite (test_game_state + test_view_filter + test_react_stack + tests/server/): 206 passed in 2.5s.
- Broader non-RL/non-tensor suite: no regressions attributable to this plan. Pre-existing baseline failures unchanged (training deckable-validation, tensor parity, 1 spectator).
- Sandbox session tests: GREEN — `on_frame=None` default keeps legacy tests passing.
- JS compile (`node -c game.js`): OK.

Decisions:
1. CSS class rename over specificity hacks — `.turn-transition-banner` is atomic + audit-proof; the HUD `.turn-banner` rule is untouched shipped behavior.
2. Sandbox per-frame emission via optional callback (not a drain-queue redesign) — keeps legacy callers / tests unchanged, only opts in from the event handler.
3. Sandbox handler wires banner + blip inline (not via refactor to route through applyStateFrame) — keeps god-view separate from view_filter path. Future state-transition-driven visuals will need the same dual-site wiring.
4. Banner + blip both fire-and-forget (never gate AnimationQueue) — banner is pure visual noise above state; blip frames are already serialized by the engine's trigger-queue drain.

Hook points for 14.7-10:
- Transient-field lifecycle is the template for future ephemeral state (set once, clear next frame, emit per-call on bulk paths).
- Dual-path visual-wiring check is a codebase invariant worth testing (grep: any state-transition visual effect should appear in BOTH applyStateFrame AND sandbox_state handler).
- CSS class collision audit should be part of the plan verification step for any new visual primitives.

### Phase 14.7 Plan 06 closeout (2026-04-19)

Plan 14.7-06 shipped as the seventh plan of Phase 14.7 — fizzle rule per spec §7.3. Pure engine plan; no UI / server changes; no card JSON retagged. Commit trail:

- d4978c5 feat(14.7-06): fizzle rule — effects silently no-op when target invalid (Task 1 — helper + resolve_effect gate + 16 unit tests)
- 10afe1c test(14.7-06): fizzle wired into trigger queue drain + integration (Task 2 — 4 drain-level react_stack tests + 2 integration tests)

Both commits pushed to master; Railway auto-deployed.

Engine changes:
- `_validate_target_at_resolve_time(state, effect, source_pos, source_minion_id, target_pos) -> bool` module-level helper added to `src/grid_tactics/effect_resolver.py`. Dispatches on TargetType:
  - SINGLE_TARGET → False if no alive minion at target_pos (missing OR current_health<=0)
  - ADJACENT → False if source_minion_id points to dead/missing minion (None passes through for magic/aura callers)
  - SELF_OWNER → False if source_minion_id points to dead/missing minion (None passes through for magic-player callers)
  - OPPONENT_PLAYER / ALL_ENEMIES / ALL_ALLIES / ALL_MINIONS → never fizzle via this helper (area handlers no-op naturally on empty target sets)
- `resolve_effect` gained keyword-only `source_minion_id: Optional[int] = None` argument. Fizzle gate runs BEFORE the TargetType dispatch: on fizzle, returns the EXACT incoming state object (identity-preserving) so callers can detect no-op via `state is prev_state`.
- Internal callers updated to pass source_minion_id:
  - `resolve_effects_for_trigger` (effect_resolver.py) → passes `minion.instance_id`
  - `resolve_summon_effect_originator` (react_stack.py) → passes `entry.source_minion_id` (the just-landed minion)
  - `_fire_passive_effects` (react_stack.py, LEGACY no-op) → passes `m.instance_id` defensively
- Magic-cast, react-card, and death-effect callers leave `source_minion_id=None`:
  - `apply_death_target_pick` fallback + `resolve_death_effects_or_enter_modal` fallback → source IS dead for on_death triggers (by definition)
  - All react_stack.py magic-cast originator dispatches + react-card resolve paths → source is a player/card, not a minion
  - action_resolver.py: `_apply_discard_effects` + `dark_matter_buff` activated ability → magic/activated paths

Drain-level wiring:
- `_resolve_trigger_and_open_react_window` in `react_stack.py` now:
  - Sets `fizzle_source_id = None if trigger.trigger_kind == "on_death" else trigger.source_minion_id` (death triggers skip source-liveness check — source IS dead by definition)
  - Captures `prev_state = state` before calling `resolve_effect`
  - Detects fizzle via `state is prev_state` (identity check) after the call
  - On fizzle: pops the trigger from the appropriate queue (turn vs other) and calls `drain_pending_trigger_queue` to continue — NO react window is opened
  - On non-fizzle: proceeds with the pre-existing cleanup + is_game_over + react-window-open path

Behavioral change (intentional):
- Triggered effects now correctly fizzle when their target is gone at resolution time. Before 14.7-06, `resolve_effect` would blindly no-op at the handler level (e.g. `_resolve_single_target` returned state unchanged when no minion at target_pos) — but this no-op wasn't identity-preserving, meaning the react window would still open for a "nothing happened" effect. After 14.7-06, the identity-preserving fizzle gate makes the no-op detectable, so the drain skips the react window and re-drains immediately. Net result: fewer dead-air prompts, correct §7.4 semantics.
- The fizzle affects TWO user-visible paths:
  1. An on_death SINGLE_TARGET (RGB Lasercannon's DESTROY) opens its modal before fizzle check — so if the user picks an invalid target (shouldn't happen via client enumeration), `apply_death_target_pick`'s validation raises. Fizzle applies to the on_death trigger's effect resolution INSIDE `_resolve_trigger_and_open_react_window`, where the target_pos was pre-captured on the PendingTrigger (or is None → no fizzle, falls through to handler no-op).
  2. A start/end-of-turn ADJACENT / SELF_OWNER trigger whose source died mid-drain (killed by a sibling trigger via chain-reaction) now silently fizzles instead of resolving with stale position data.

§7.4 worked-example status:
- The original `test_rgb_lasercannon_vs_giant_rat_turn_player_priority` from 14.7-05b continues to pass verbatim — promotes Giant Rat because 2 rats are available.
- New `test_rgb_destroy_eliminates_only_promote_target_giant_rat_fizzles` in test_integration.py proves the FIZZLE variant: same setup but with only ONE rat on P2's side. P1 turn-priority picks that rat for RGB's DESTROY, then Giant Rat A's PROMOTE has 0 candidates → silently no-ops. Full end-to-end: attack → modal → DEATH_TARGET_PICK → react window PASS → drain-recheck → fizzle → queues empty.

Test posture:
- Plan verification suite (test_effect_resolver + test_react_stack + test_integration): 132 passed (all green). +22 new tests.
- Broader non-RL/non-tensor engine+server suite: ~852 passed. Baseline 2 failures unchanged (1 spectator, 1 intermittent LEAP in test_game_flow — both predating 14.7-06).
- New test classes:
  - TestFizzleRulePhase14_7_06 (16 tests) in test_effect_resolver.py — per-TargetType + per-EffectType fizzle shapes + regression guards (identity preservation, magic-path source_minion_id=None behavior)
  - TestPhase14_7_06_TriggerFizzle (4 tests) in test_react_stack.py — drain-level behavior (no REACT on fizzle, pops+re-drains, multi-entry queue progression, identity-preservation regression)
  - TestFizzleRulePhase14_7_06Integration (2 tests) in test_integration.py — §7.4 fizzle variant + synthetic Stinger ADJACENT-damage mid-drain source-death

Decision: kept `_fire_passive_effects` function in place.
- Plan suggested considering removal. Audit confirmed zero card JSONs use `"trigger": "passive"` (grep empty after 14.7-03 retag of Fallen Paladin / Emberplague Rat / Dark Matter Battery to on_start_of_turn / on_end_of_turn).
- Safer to leave dead code + thread source_minion_id defensively (m.instance_id) than delete without the 14.7-10 migration-test scaffolding. 14.7-10 can audit + prune.

Reusable infrastructure for later 14.7 plans:
- 14.7-09 (turn banner UI): Fizzled triggers never open a react window, so the banner never needs a "fizzled" dispatch branch. Banner can assume every AFTER_DEATH_EFFECT / AFTER_START_TRIGGER / BEFORE_END_OF_TURN window corresponds to a non-trivial resolved effect.
- 14.7-10 (cleanup): Fizzle gate is centralized in `_validate_target_at_resolve_time` — single surface for audits. source_minion_id threading gives 14.7-10 a consistent invariant to verify across all resolve_effect callers. PendingDeathWork / pending_death_queue pruning is still the main 14.7-10 target; fizzle gate overlaps zero with those shapes.
- Future card design: new minion cards with on_death / on_start_of_turn / on_end_of_turn effects targeting SINGLE_TARGET / ADJACENT / SELF_OWNER will automatically get fizzle coverage — no card-specific code changes needed.

Auto-fixed in-progress issues:
- (a) Missing `amount=0` on DESTROY/APPLY_BURNING test EffectDefinition constructors — EffectDefinition is a frozen dataclass requiring `amount: int` as a positional argument with no default. Added explicitly.
- (b) owner_idx vs MinionInstance.owner mismatch in `test_fizzle_pops_trigger_and_advances_to_next_queue_entry` — OPPONENT_PLAYER damages the player opposite to the trigger's owner. Aligned the synthetic Card B's source MinionInstance.owner to PLAYER_2 to match owner_idx=1, and updated the assertion to check `players[0].hp` (P1 is the opponent when Card B owner is P2).

### Phase 14.7 Plan 07 closeout (2026-04-19)

Plan 14.7-07 shipped as the sixth plan of Phase 14.7 — react-condition matching via ReactContext. Pure engine plan; no UI / server changes; no card JSON retagged. Commit trail:

- 604b64a feat(14.7-07): react_context-aware react_condition matching + 3 new conditions (Task 1 — enum extension + _check_react_condition rewrite + 22 unit tests across 3 files)
- 5648759 test(14.7-07): integration coverage for Prohibition gating + synthetic cards (Task 2 — 3 end-to-end tests with in-memory CardLibrary)

Both commits pushed to master; Railway auto-deployed.

Engine changes:
- `ReactCondition` IntEnum extended with three append-only values: `OPPONENT_SUMMONS_MINION=15`, `OPPONENT_START_OF_TURN=16`, `OPPONENT_END_OF_TURN=17`. Block-commented as "14.7-07: react_context-aware conditions ... forward-compat expressivity for future cards; existing cards unchanged." Card JSON loader auto-picks them up via reflective `enum_cls[value.upper()]` — no allowlist edit required (and no REACT_CONDITIONS allowlist exists in the codebase).
- `_check_react_condition` (src/grid_tactics/legal_actions.py lines 722-947) rewritten from ~94 lines to ~225 lines with explicit dispatch table as docstring. New control flow:
  1. `ANY_ACTION` short-circuit → always True.
  2. Context-tagged conditions (14.7-07) checked FIRST, before the counter-react branch, so they match even during counter-react chains inside the same window: OPPONENT_SUMMONS_MINION matches AFTER_SUMMON_DECLARATION + AFTER_SUMMON_EFFECT; OPPONENT_START_OF_TURN matches AFTER_START_TRIGGER; OPPONENT_END_OF_TURN matches BEFORE_END_OF_TURN.
  3. Counter-react branch (non-originator on top of stack): OPPONENT_PLAYS_REACT → True; OPPONENT_PLAYS_MAGIC → matches MAGIC/REACT top cards (preserves Prohibition-vs-Prohibition counter); element conditions → match top card's element.
  4. Summon-window gate (AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT): OPPONENT_PLAYS_MINION → True (back-compat alias for OPPONENT_SUMMONS_MINION); element conditions → match the summon originator's element; everything else → False (magic / attacks don't match summon windows).
  5. Start/End/Death windows: everything else → False (only the 14.7-07 context conditions + ANY_ACTION + counter-react match).
  6. AFTER_ACTION / None fall-through: preserves full pre-14.7 behavior. OPPONENT_PLAYS_MAGIC checks for magic_cast originator on stack (14.7-01 deferred magic) THEN falls back to pending_action PLAY_CARD in grave[-1]. Other conditions use pending_action (MOVE/ATTACK/SACRIFICE/DISCARD/element via magic_cast originator OR pending PLAY_CARD).

Behavioral change (intentional):
- **Prohibition (OPPONENT_PLAYS_MAGIC) is now correctly filtered OUT of legal_actions during summon windows.** Pre-14.7-07, the old `if state.react_stack: last_react = state.react_stack[-1]` branch would see the summon_declaration originator on top, fail the magic-check (origin_kind='summon_declaration'), then fall through to pending_action which was a PLAY_CARD — matching via `grave[-1].card_type == MAGIC` would fail since minion cards don't go to grave, BUT the old code would `return False` at that point. So actually old code ALSO returned False here? Let me verify: the old code's "if state.react_stack" branch short-circuited back to False for OPPONENT_PLAYS_MAGIC unless `last_card.card_type == MAGIC or REACT`. A summon_declaration originator's card is a MINION → False. So the OLD behavior was ALREADY to filter Prohibition out — the 14.7-07 change codifies this via explicit context dispatch rather than relying on the fall-through luck. The new integration test test_prohibition_not_legal_during_summon_declaration makes this explicit and prevents future regressions.
- What IS actually new in behavior: the new context-tagged conditions (OPPONENT_SUMMONS_MINION etc.) exist and work. No card uses them yet, so this is purely forward-compat surface area.

Integration test subtlety:
- Pre-existing 14.7-04 tests `test_prohibition_on_window_a_negates_full_summon_and_tutor` and `test_prohibition_on_window_b_preserves_minion_cancels_tutor` continue to pass. They call `resolve_action(state, play_react_action(...))` directly, bypassing legal_actions. `_play_react` (in react_stack.py) doesn't re-validate the react_condition — it only checks mana, stack depth, card type. So those tests exercise the code-level effect resolution: "IF Prohibition were somehow played in a summon window (which legal_actions would not allow), would the negate effect still resolve correctly?" — answer: yes. Left as-is; they're harmless and provide defensive coverage.

Test posture:
- Plan verification suite (183 tests): test_enums + test_card_loader + test_legal_actions + test_integration — all GREEN.
- Broader non-RL/non-tensor suite: 884 passed. Baseline 8 failures unchanged (1 spectator, 4 LEAP game_loop, 2 rl_env REVIVE_PLACE unhandled, 1 RL self-play — all pre-existing and predating 14.7).
- +25 new tests: 5 enum (TestReactConditionPhase14_7_07), 4 card_loader (TestPhase1477NewReactConditions), 13 legal_actions (TestCheckReactConditionPhase1477), 3 integration (TestReactConditionPhase1477Integration).
- No card JSON uses the three new condition strings (verified via grep — forward-compat only).

Reusable infrastructure for later 14.7 plans:
- 14.7-05b (Death: priority migration): no coupling. Death triggers use a separate queue pipeline; once they fire the react window, its react_context will be AFTER_DEATH_EFFECT, which already returns False for all legacy conditions (only ANY_ACTION + counter-react + future death-trigger conditions match). Plan 14.7-07 added no new conditions for death — future plans can add OPPONENT_MINION_DIES etc. when designed.
- 14.7-06 (fizzle): no coupling. Liveness re-check happens inside the resolve path, not the legal_actions gate.
- 14.7-09 (turn banner UI): react_context is the single source of truth for "why is this window open." Banner text can dispatch on it directly via state.react_context (already serialized in GameState.to_dict). No server changes needed.
- Future card design: a JSON card can use `"react_condition": "opponent_summons_minion"` / `"opponent_start_of_turn"` / `"opponent_end_of_turn"` and it Just Works — no engine changes, no card_loader edits.

### Phase 14.7 Plan 04 closeout context (retained for lookback)

Plan 14.7-04 shipped: summon compound two-window dispatch is now live. _deploy_minion pushes a summon_declaration originator onto the react stack (Window A: AFTER_SUMMON_DECLARATION); on PASS-PASS, resolve_summon_declaration_originator lands the minion and — if ON_SUMMON effects exist — pushes a summon_effect originator to open Window B (AFTER_SUMMON_EFFECT). Window A negate = FULL forfeit (costs spent, minion doesn't land — spec §4.2 harsh-by-design). Window B negate = effect cancelled but minion stays. resolve_react_stack grew a stack-identity snapshot for compound-window hand-off + a pending-modal hand-off that fixes a latent 14.7-01 bug (Ratmobile-style tutor advancing turn before caster picks). 6 Summon: minion JSONs flow correctly: 3 Diodebots' tutor chain, Eclipse Shade self-burn, Flame Wyrm draw, Gargoyle Sorceress's two buffs share one Window B. Minion ON_PLAY triggers are orphaned (no card JSON uses them; only ON_SUMMON fires through compound pipeline). resolve_action's terminal AFTER_ACTION block now short-circuits when state.phase==REACT to respect originator handlers' inline react_context. Commits: 8b093af (feat Task 1: _deploy_minion refactor + resolve helpers + 7 unit tests) + 7639986 (test Task 2).

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

Last activity: 2026-04-19 — Completed 14.7-06-PLAN.md (Fizzle rule. `_validate_target_at_resolve_time` helper + `resolve_effect` source_minion_id kwarg + fizzle gate. Effects with stale SINGLE_TARGET / dead ADJACENT/SELF_OWNER source silently no-op at resolution time per spec §7.3. `_resolve_trigger_and_open_react_window` detects fizzle via state identity, pops trigger without opening react window, re-drains. 22 new tests (16 effect_resolver + 4 react_stack + 2 integration including §7.4 fizzle variant). Commits: d4978c5 + 10afe1c.). Previous: Completed 14.7-05b-PLAN.md (Death: priority migration. _cleanup_dead_minions now enqueues ON_DEATH effects into pending_trigger_queue_{turn,other} (spec §7.2 turn-player-first). _resolve_trigger_and_open_react_window gained on_death branch with pending_death_target modal integration. Module-level _cleanup_skip_drain reentrancy guard. Identity-based AFTER_DEATH_EFFECT early-exit in resolve_react_stack. Spec §4.3 / §7.4 worked example works end-to-end. Sandbox round-trip validated. Pre-14.7 ordering tests updated in-place via _drain_all_death_triggers helper. 7 new tests (5 unit + 1 integration + 1 sandbox). Commits: 6800264 + 890c4bc.). Previous: Completed 14.7-07-PLAN.md (React-condition matching via ReactContext. 3 new ReactCondition enum values appended — OPPONENT_SUMMONS_MINION=15 / OPPONENT_START_OF_TURN=16 / OPPONENT_END_OF_TURN=17 — forward-compat; no card JSON uses them yet. _check_react_condition rewritten to dispatch on state.react_context: AFTER_SUMMON_DECLARATION / AFTER_SUMMON_EFFECT match the new OPPONENT_SUMMONS_MINION + back-compat OPPONENT_PLAYS_MINION + element conditions; AFTER_START_TRIGGER → OPPONENT_START_OF_TURN; BEFORE_END_OF_TURN → OPPONENT_END_OF_TURN; AFTER_ACTION / None preserves pre-14.7 pending_action + magic_cast originator flow. Prohibition (OPPONENT_PLAYS_MAGIC) correctly filtered OUT of legal_actions during summon windows. card_loader auto-picks new strings via reflective lookup; no allowlist edit. +25 tests (5 enum, 4 card_loader, 13 legal_actions, 3 integration with in-memory synthetic CardLibrary). No deviations. Commits: 604b64a + 5648759.). Previous: 14.7-05 (Simultaneous-trigger priority queue + modal picker), 14.7-08 (Melee two react windows), 14.7-04 (Summon compound react windows), 14.7-03 (Start/End/Summon triggered effects pipeline), 14.7-02 (3-phase turn state machine), 14.7-01 (Deferred magic resolution).

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

### Phase 14.7 Plan 08 closeout (2026-04-19)

Plan 14.7-08 shipped out-of-order (plan sequencing in 14.7 is wave-based: 14.7-08 depends only on 14.7-02 which was satisfied back on 2026-04-18). This plan supersedes Phase 14.1's combined-single-react-window decision per spec v2 §4.1 and key_user_decisions #1. Commit trail:

- eed9f7f feat(14.7-08): melee move+attack opens TWO independent react windows (Task 1 — engine rewiring + 4 migrated tests + 7 new unit tests)
- 8009ae0 test(14.7-08): UI phase gate + full-chain integration coverage (Task 2 — game.js phase gate + 2 integration tests)

Both commits pushed to master; Railway auto-deployed.

Observable gameplay impact:
- Moving a melee minion into in-range state now opens a react window **immediately** — before the player chooses ATTACK or DECLINE. Opponent gets first pass on the move itself.
- If the attacker chooses ATTACK, a second react window opens after the damage exchange (standard post-attack behavior; already existed in 14.1 but was the only window).
- If the attacker DECLINEs, the turn advances directly. No phantom REACT window wasted on a non-action.
- Ranged minions unchanged: move → single react window → turn advances.

Engine changes:
- `_apply_move` unchanged for the pending flag setting (still `pending_post_move_attacker_id = minion.instance_id` when range=0 + in-range enemies). The REACT transition happens at the caller site (`resolve_action`'s MOVE fall-through), which now detects pending + melee and enters REACT with `react_context=AFTER_ACTION` / `react_return_phase=ACTION` instead of returning inline in ACTION.
- `resolve_react_stack` AFTER_ACTION dispatch: checks `pending_post_move_attacker_id` BEFORE clearing bookkeeping + calling `enter_end_of_turn`. If set, clears react bookkeeping (stack, player, context, return_phase, pending_action) but KEEPS pending and returns to ACTION for the sub-action.
- `resolve_action` pending_post_move gate (line ~1773): split ATTACK vs DECLINE handling. ATTACK opens the second AFTER_ACTION window (standard path). DECLINE short-circuits to `enter_end_of_turn(state, library)` — no REACT transition, no second window.
- `pending_death_target` resume path (action_resolver.py ~line 1454): pending_post_move no longer returns inline in ACTION; falls through to the REACT transition so the post-move window opens even when cleanup yielded a death modal.
- `legal_actions`: the pending-post-move enumeration branch is now gated on `phase==ACTION`. During the post-move REACT window, the reacting player gets standard REACT-phase enumeration (PASS + legal react cards), not the attack-or-decline menu meant for the caster.

Client changes:
- `syncPendingPostMoveAttackUI` in game.js: gates the attack-pick-mode + Decline button on `gameState.phase === 0` (ACTION). During the post-move REACT window the picker UI hides and reappears when the window closes. Prevents premature Decline button clicks that would be rejected by the server.

Test migration posture:
- Four pre-existing 14.1 tests in `TestPendingPostMoveAttack` encoded the superseded single-window assumption. Migrated in-place (no xfails, no deletions):
  * `test_melee_move_sets_pending_state_when_target_in_range` now asserts `phase == REACT` + `react_context == AFTER_ACTION` + `react_return_phase == ACTION` + `react_player_idx == 1`.
  * `test_pending_attack_resolves_combat_and_clears_state` got a single-PASS drain of W1 before the ATTACK.
  * `test_pending_decline_clears_state_with_one_react` renamed to `test_pending_decline_skips_second_react_window`; asserts `active_player_idx == 1` + `phase == ACTION` (turn advanced to P2) instead of `phase == REACT`.
  * `test_pending_state_blocks_unrelated_actions` + `test_pending_attack_only_with_pending_attacker` got drain-W1 steps so the gate tests run against the between-windows ACTION phase.

New coverage:
- +7 unit tests (`TestMeleeTwoReactWindows` in test_action_resolver.py): opens-window-1, opens-window-2-on-attack, skips-window-2-on-decline, ranged-unchanged, no-targets-single-window, legal_actions-during-window (react-only), legal_actions-between-windows (attack-or-decline-only).
- +2 integration tests (`TestMeleeTwoReactWindowsIntegration` in test_integration.py): Common Rat vs Common Rat full chain (move → W1 → PASS → ACTION → ATTACK → W2 → PASS → P2 turn) and DECLINE variant (move → W1 → PASS → DECLINE → P2 turn direct).

Test posture:
- Plan verification suite (207 tests) GREEN: test_action_resolver + test_react_stack + test_legal_actions + test_integration + test_view_filter.
- Broader engine suite (336 tests) GREEN: adds game_state + effect_resolver + pvp_server + game_flow + sacrifice + status_effects.
- Sandbox session tests (66/66) GREEN. Pending flag survives save/load (no schema change).
- Baseline failures unchanged at 10 (1 spectator + 4 LEAP + 1 RL self-play + 4 tensor engine parity — all pre-existing and predating 14.7).
- `node -c game.js`: OK.

Reusable infrastructure for later 14.7 plans:
- 14.7-07 (ReactCondition matching): the post-move window uses `react_context=AFTER_ACTION` and pending_action is the MOVE. A future `OPPONENT_MOVES_MINION` condition can match without engine wiring — just add the enum value and predicate.
- 14.7-09 (turn banner): client already receives phase + pending_post_move_attacker_id. A banner can distinguish "Post-move react" (pending set + phase=REACT) from "Post-attack react" (pending cleared + phase=REACT) without server changes.
- 14.7-10 (test migration): the in-place migration pattern (drain W1 via single PASS before asserting between-window state) is the reference for any remaining 14.1-era tests.

Non-goals / limits documented by this plan:
- Tensor engine untouched (on hold per CLAUDE.md). Tensor engine's 14.1-02 parity work already stale; 14.7-08 defers its re-alignment.
- pending_post_move_attacker_id serialization unchanged (field predates 14.7-08). Sandbox save/load works unchanged.
- Prohibition (OPPONENT_PLAYS_MAGIC) is not legal in the post-move window — MOVE is not a magic play. Filtered correctly via existing `_check_react_condition`. No 14.7-07 changes required by this plan.

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

Last session: 2026-04-21T08:29:32Z — Completed 14.8-03b (server-side engine_events Socket.IO emit + M3 next_event_seq on both Session classes + sandbox apply_sandbox_edit verb dispatch + per-viewer event filter + 9c414f9 per-frame hack decommissioned + 21 new tests). Two commits b39d615 + e1f306b pending push. Previous: 2026-04-21T09:18:00Z — Completed 14.8-03a (engine event stream wire format). 2026-04-21 earlier — Completed 14.8-02 (drive 102 shadow-mode violations to zero) and 14.8-01 (PHASE_CONTRACTS foundation). 2026-04-18T23:58:00.000Z — Completed 14.7-05 (simultaneous-trigger priority queue + modal picker for START_OF_TURN / END_OF_TURN). 2026-04-19 — Completed 14.7-08 (Melee two react windows). 2026-04-18T23:00:00.000Z — Completed 14.7-04 (summon compound two-window dispatch). 2026-04-18T21:45:00.000Z — Completed 14.7-03 (Start/End/Summon triggered effects pipeline + react windows). 14.7-02: 2026-04-18T18:48:00.000Z — 3-phase turn state machine. 14.7-01: 2026-04-18T18:15:00.000Z — Deferred magic resolution via cast_mode originator.
Stopped at: Plan 14.8-03b SHIPPED. Two commits (b39d615 Task 1 feat: M3 + sandbox EventStream + per-viewer event filter; e1f306b Task 2 feat: wire engine_events Socket.IO emit + 21 tests) pending push. Server-side engine_events Socket.IO emission live for both live PvP (handle_submit_action) and sandbox (handle_sandbox_apply_action + 8 sandbox edit handlers). M3 next_event_seq field on BOTH GameSession (live PvP) and SandboxSession (sandbox) — monotonic event seq across the full session lifetime; per-call EventStream(next_seq=session.next_event_seq) seeds + writes back. Reset semantics: GameSession resets to 0 on rematch (request_rematch builds fresh GameSession); SandboxSession resets explicitly in reset() and load_dict(). 9c414f9 per-frame sandbox emit hack DECOMMISSIONED — apply_action returns event list across user action + all drained PASSes as ONE EventStream; ONE engine_events socket frame per call regardless of drain depth. SandboxSession.apply_sandbox_edit(verb, payload) verb dispatch helper for 14 sandbox verbs — orchestrator decision #5 made concrete. view_filter.filter_engine_events_for_viewer with explicit `is None` checks (NOT `or`-chains) for owner-key resolution — P1=0 falsy footgun caught on first run. Dual-emit pattern preserves back-compat: both legacy state_update/sandbox_state AND new engine_events fire from same handler. Three Rule 1 auto-fixes: (1) react_stack.py missing EVT_PENDING_MODAL_OPENED import — pre-existing bug from plan 03a surfaced when 03b wired event_collector to flow into drain_pending_trigger_queue path; (2) view_filter.py owner-key `or`-chain bug; (3) tests/test_event_serialization.py action codec format. Test posture: tests/test_event_serialization.py 21/21 passed; focused subset 280 passed / 27 skipped; broader suite 1060 passed / 17 failed (16 + 1 documented baseline) / 27 skipped. NET +21 tests passing over plan 03a baseline. Next: 14.8-04a (client eventQueue — defines per-event payload schemas + socket.on('engine_events', ...) consumer + reduce loop with requires_decision gating; unblocked by server-side emit being live).

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
