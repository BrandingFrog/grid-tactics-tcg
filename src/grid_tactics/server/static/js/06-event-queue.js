// =============================================
// Section: AnimationQueue (Phase 14.3)
// =============================================
//
// Serializes state-update application behind animations so pending UIs
// (react window, tutor modal, post-move-attack pick) never open mid-animation.
//
// Job shape: { type: 'summon'|'move'|'attack'|'noop', payload: {...},
//              stateAfter: <frame>, legalActionsAfter: <list>, durationMs: <int> }
//
// Contract:
//   enqueueAnimation(job)  — push + kick the queue
//   runQueue()             — shifts next job, runs playAnimation, then
//                            applyStateFrame(job.stateAfter, job.legalActionsAfter)
//   playAnimation(job,done)— Wave 1: all branches are setTimeout(done,0) no-ops.
//                            Waves 2-4 replace branches with real visuals.
//   applyStateFrame(frame,legal) — single point of state application; calls
//                            renderGame() which drives all pending UI sync.
//   isAnimating()          — true while a job is running OR queue has pending jobs

var animQueue = [];
var animRunning = false;
// Registry of tiles currently animating: { "<row>,<col>": "summon"|"move"|... }
// Read by renderBoard() to apply the matching .anim-* class to .board-cell.
// Wave 3/4 (move/attack) will reuse this same registry.
var animatingTiles = {};
// Timing overhaul (2026-07-08, F10f): wall-clock start time per animating
// tile ("<row>,<col>" -> Date.now()). renderBoard applies a NEGATIVE
// animation-delay from this so a mid-animation re-render resumes the
// keyframe instead of restarting it (summon scale-in used to replay).
var _animTileStart = {};

// ============================================================
// Phase 14.8-04a/04b: Unified Event Queue. The 4 ad-hoc defer/buffer
// gates (sandbox frame queue, pending-post-stage frame, pending trigger
// blip, pending turn banner) have been DELETED in plan 04b — every
// animation + DOM mutation now flows through this queue's 19 slot
// handlers.
//
// In plan 04a the eventQueue runs ALONGSIDE the legacy snapshot path
// (state_update / sandbox_state). Snapshot still updates DOM; eventQueue
// adds animations on top. Double-rendering for the 10 covered events is
// the accepted tradeoff for a safe migration; plan 05 deletes the snapshot
// path entirely.
//
// Wire format: server emits one `engine_events` Socket.IO frame per
// resolve_action / apply_action / apply_sandbox_edit call. Payload shape
// (from plan 14.8-03b):
//   { events: [ EngineEvent.to_dict(), ... ],
//     final_state: <snapshot, same as state_update.state>,
//     legal_actions: [...],
//     your_player_idx: int,
//     is_spectator?: bool, is_sandbox?: bool }
//
// Each EngineEvent dict:
//   { type, contract_source, seq, payload, animation_duration_ms,
//     triggered_by_seq, requires_decision }
//
// Plan 04a implements 10 simpler slot handlers fully:
//   minion_summoned, minion_died, minion_hp_change, minion_moved,
//   attack_resolved, card_drawn, card_played, card_discarded,
//   mana_change, player_hp_change
// 9 harder handlers are stubbed (call done immediately) and finished
// in plan 04b: react_window_opened, react_window_closed, phase_changed,
// turn_flipped, trigger_blip, pending_modal_opened/resolved, fizzle,
// game_over.
// ============================================================

var eventQueue = [];          // EngineEvent[]
var eventRunning = false;     // a slot handler is currently animating
var lastSeenSeq = -1;         // monotonic guard against re-delivery / out-of-order
                              // Server's session.next_event_seq (plan 03b M3)
                              // drives this; -1 sentinel = "no events seen yet";
                              // reset to -1 on game_start / sandbox_state initial
                              // emit / sandbox reset / sandbox load.
var slotState = {
    spellStageChain: [],      // LIFO stack of opened-but-not-closed react windows (used by 04b)
    pendingModalKind: null,   // non-null while awaiting user input (used by 04b)
    pendingModalDeadline: 0,  // safety timeout fallback (used by 04b)
    // Phase 14.8-05: cache the most recent "originator" (card_played or
    // trigger_blip) so playReactWindowOpened can slam the originator onto
    // the spell stage LEFT slot when its event fires. The engine emits the
    // originator event JUST BEFORE react_window_opened on the same frame —
    // we stash the card identity + player idx here and consume it when
    // the window opens. Cleared after consumption so a stale originator
    // never leaks into a later unrelated react window.
    lastOriginator: null,     // {numericId, playerIdx} or null
    // Timing overhaul (2026-07-08, F8): the event dispatched immediately
    // BEFORE the one currently playing. playMinionDied consults it to skip
    // the death animation when the preceding attack_resolved's lunge
    // already covered the kill (attacker/defender_killed on the same id).
    prevDispatchedEvent: null,
    lastDispatchedEvent: null,
};

// Phase 14.8-05b: guard so the post-drain wholesale commit of
// window.__lastFinalState fires AT MOST ONCE per onEngineEvents frame.
// Reset to false when new events arrive; set to true after the queue drains
// and the final_state snapshot is applied. Without this guard, the snapshot
// would be re-applied every time drainEventQueue is called with an empty
// queue (which happens on every modal open/close, etc.).
var _drainFinalApplied = false;

function resetEventQueue() {
    // Called on game_start, sandbox_state initial open, sandbox reset, sandbox load.
    eventQueue.length = 0;
    eventRunning = false;
    lastSeenSeq = -1;
    slotState.spellStageChain.length = 0;
    slotState.pendingModalKind = null;
    slotState.pendingModalDeadline = 0;
    slotState.lastOriginator = null;
    slotState.prevDispatchedEvent = null;
    slotState.lastDispatchedEvent = null;
    _drainFinalApplied = false;
    // Audit fix (2026-07-06): a stale spell stage (left up by leave-game /
    // game-over mid-react) must not survive into the next game.
    if (typeof _resetSpellStageHard === 'function') _resetSpellStageHard();
    // Log lifecycle matches the queue lifecycle (game_start, sandbox open/
    // reset/load): stale turn counter + minion-name registry from a prior
    // game must not poison the new session's log.
    if (typeof clearGameLog === 'function') clearGameLog();
}

// Timing audit (2026-07-06): shared gates. isEventQueueBusy — animations
// still draining, the DOM shows an older state than gameState/legalActions.
// canActNow — the player may actually act: queue idle, they hold legal
// actions, and any open react window is THEIRS. Affordance renderers
// (playable glow, board highlights) and click handlers consult these so
// nothing lights up or engages until it is genuinely the player's moment.
function isEventQueueBusy() {
    // Timing overhaul (2026-07-08, F1): also report busy while the
    // AnimationQueue is mid-flight — board animations (move/attack/summon)
    // run through animQueue and the DOM lags gameState until they finish.
    var animBusy = (typeof isAnimating === 'function')
        ? isAnimating()
        : (animRunning || animQueue.length > 0);
    return eventRunning || eventQueue.length > 0 || animBusy;
}
function canActNow() {
    if (typeof sandboxMode !== 'undefined' && sandboxMode) return true;
    if (isEventQueueBusy()) return false;
    if (!legalActions || legalActions.length === 0) return false;
    if (gameState && gameState.phase === 1
            && gameState.react_player_idx != null
            && myPlayerIdx != null
            && gameState.react_player_idx !== myPlayerIdx) return false;
    return true;
}

function onEngineEvents(payload) {
    if (!payload || !Array.isArray(payload.events)) return;
    var hadEvents = payload.events.length > 0;
    // Timing audit (2026-07-06): a new batch means the board is about to
    // animate — any open minion menu / selection / targeting mode was built
    // against the outgoing state. Tear it down before the drain starts.
    if (hadEvents && !(typeof sandboxMode !== 'undefined' && sandboxMode)) {
        try {
            if (typeof hideMinionActionMenu === 'function') hideMinionActionMenu();
            if (typeof clearSelection === 'function') clearSelection();
            // Pass/Skip button must not linger through the drain (user
            // 2026-07-08) — hide it now; renderActionBar rebuilds at drain-end.
            if (typeof hideActionBarButtons === 'function') hideActionBarButtons();
        } catch (e) { /* defensive */ }
    }
    payload.events.forEach(function(ev) {
        if (typeof ev.seq !== 'number') return;
        if (ev.seq <= lastSeenSeq) {
            // Duplicate or out-of-order — skip
            console.warn("Skipping out-of-order event seq=" + ev.seq + " (last=" + lastSeenSeq + ")");
            return;
        }
        lastSeenSeq = ev.seq;
        // Timing audit (2026-07-06): events are logged at DISPATCH time in
        // drainEventQueue — one line per animation beat, in seq order (the
        // queue is FIFO) — not here at enqueue, which spoiled the whole
        // batch seconds ahead of the animations. The seq guard above still
        // dedupes reconnect replays before anything is queued or logged.
        eventQueue.push(ev);
    });
    // Phase 14.8-05b: stash final_state + arm the post-drain commit. The
    // post-action state_update / sandbox_state wire format is gone (plan 05
    // deleted it), so final_state is the authoritative post-chain snapshot.
    // Each event's slot handler + commitEventToDom does its per-beat
    // incremental work; when the queue drains fully, we apply final_state
    // wholesale as a catch-all for anything the incremental path didn't
    // cover (summons, deaths, card moves, hand/graveyard counts).
    if (payload.final_state) {
        window.__lastFinalState = payload.final_state;
        window.__lastLegalActions = payload.legal_actions || [];
        // Also stash per-sandbox fields so the post-drain commit can
        // preserve view_idx / undo / redo depths when we reassign state.
        window.__lastSandboxMeta = {
            active_view_idx: payload.active_view_idx,
            undo_depth: payload.undo_depth,
            redo_depth: payload.redo_depth,
            is_sandbox: !!payload.is_sandbox,
        };
    }
    // Arm the wholesale-apply guard so the next full drain commits
    // final_state once. If this frame carried zero events (pure state
    // snapshot via engine_events — rare post-05), we still want to commit
    // it so the DOM reflects the new state.
    if (hadEvents || payload.final_state) {
        _drainFinalApplied = false;
    }
    drainEventQueue();
}

function drainEventQueue() {
    if (eventRunning) return;
    if (slotState.pendingModalKind !== null) {
        // Modal is open — wait for user input. Deadlock fix: the
        // pending_modal_resolved event that clears this gate travels through
        // THIS SAME queue, so a blanket early-return could never dequeue it
        // and the client would freeze forever on the first tutor /
        // trigger-pick / death-pick modal. Three-part recovery:
        //   (1) enforce the safety deadline (was written but never read);
        //   (2) if a pending_modal_resolved is anywhere in the queue, keep
        //       draining — its handler clears the gate when it plays;
        //   (3) otherwise commit the stashed final_state ONCE so the
        //       pending_* fields reach gameState and the modal UI (the
        //       syncPending*UI handlers in renderGame) can actually open,
        //       then park until user input produces the resolved event.
        var modalDeadlinePassed = slotState.pendingModalDeadline > 0
            && Date.now() > slotState.pendingModalDeadline;
        var resolvedQueued = false;
        for (var qi = 0; qi < eventQueue.length; qi++) {
            if (eventQueue[qi] && eventQueue[qi].type === 'pending_modal_resolved') {
                resolvedQueued = true;
                break;
            }
        }
        if (modalDeadlinePassed) {
            console.warn('[eventQueue] pending modal deadline passed — force-clearing gate');
            slotState.pendingModalKind = null;
            slotState.pendingModalDeadline = 0;
            try {
                var staleScrim = document.getElementById('event-queue-blocking-scrim');
                if (staleScrim && staleScrim.parentNode) {
                    staleScrim.parentNode.removeChild(staleScrim);
                }
            } catch (e) { /* defensive */ }
            // Fall through to the normal drain below.
        } else if (!resolvedQueued) {
            if (!_drainFinalApplied && window.__lastFinalState) {
                _drainFinalApplied = true;
                try {
                    _commitFinalStateSnapshot(window.__lastFinalState);
                } catch (e) {
                    console.error("[eventQueue] _commitFinalStateSnapshot failed", e);
                }
            }
            return;
        }
        // resolvedQueued: fall through — keep draining so the queued
        // pending_modal_resolved event can play and clear the gate.
    }
    if (eventQueue.length === 0) {
        // Phase 14.8-05b: queue fully drained — commit the wholesale
        // final_state snapshot as catch-all for fields the per-event
        // commitEventToDom didn't incrementally cover (hand/graveyard
        // counts, new/dead minions, card_played hand removal, etc.). The
        // _drainFinalApplied guard ensures this fires AT MOST ONCE per
        // engine_events frame (reset on onEngineEvents). Without this,
        // the paladin scenario regression happens: HP stays at 30 forever
        // because the snapshot-path was deleted in plan 05 but no
        // replacement state-commit path was wired up.
        if (!_drainFinalApplied && window.__lastFinalState) {
            _drainFinalApplied = true;
            try {
                _commitFinalStateSnapshot(window.__lastFinalState);
            } catch (e) {
                console.error("[eventQueue] _commitFinalStateSnapshot failed", e);
            }
        }
        return;
    }
    var ev = eventQueue.shift();
    eventRunning = true;
    slotState.prevDispatchedEvent = slotState.lastDispatchedEvent || null;
    slotState.lastDispatchedEvent = ev;
    // Log at the beat (timing audit 2026-07-06): the line lands as the
    // animation starts, so log order + timestamps track the visuals. A
    // throwing formatter must never break the drain.
    try { logEngineEvent(ev); } catch (e) { console.warn('[gameLog] format error', e); }
    try {
        playEvent(ev, function onSlotDone() {
            eventRunning = false;
            try { commitEventToDom(ev); } catch (e) { /* defensive */ }
            drainEventQueue();
        });
    } catch (err) {
        console.error("playEvent failed for type=" + (ev && ev.type), err);
        eventRunning = false;
        drainEventQueue();
    }
}

// Phase 14.8-05b: Wholesale commit of the authoritative post-chain state
// snapshot stashed on window.__lastFinalState by onEngineEvents. Called
// ONCE per engine_events frame after the eventQueue fully drains. Safe at
// that point because all per-beat animations have already run — the final
// state is what the DOM should match when everything is done. Catches
// fields the per-event incremental commitEventToDom path didn't cover
// (hand/graveyard counts, new/dead minions, pending-modal state).
function _commitFinalStateSnapshot(finalState) {
    if (!finalState) return;
    if (sandboxMode) {
        sandboxState = finalState;
        // Sandbox is god-mode — gameState mirrors sandboxState when the
        // sandbox tab is active. Keep them in lockstep.
        gameState = finalState;
        myPlayerIdx = 0;
        if (window.__lastLegalActions) {
            sandboxLegalActions = window.__lastLegalActions;
            legalActions = window.__lastLegalActions;
        }
        // Restore sandbox meta (undo/redo depths, active_view_idx) so the
        // toolbar buttons reflect the post-commit state.
        var meta = window.__lastSandboxMeta;
        if (meta) {
            if (typeof meta.active_view_idx === 'number') {
                sandboxActiveViewIdx = meta.active_view_idx;
            }
            if (typeof meta.undo_depth === 'number') {
                sandboxUndoDepth = meta.undo_depth;
            }
            if (typeof meta.redo_depth === 'number') {
                sandboxRedoDepth = meta.redo_depth;
            }
        }
        // Autosave (mirrors the sandbox_state socket handler's behavior).
        try {
            localStorage.setItem(SANDBOX_AUTOSAVE_KEY, JSON.stringify({
                state: sandboxState,
                active_view_idx: sandboxActiveViewIdx,
            }));
        } catch (e) { /* quota exceeded — ignore */ }
        if (typeof renderSandboxToolbarState === 'function') {
            try { renderSandboxToolbarState(); } catch (e) { /* defensive */ }
        }
        if (typeof renderSandbox === 'function') {
            try { renderSandbox(); } catch (e) { /* defensive */ }
        }
        // Phase 14.8-05c: renderSandbox replaces hand DOM nodes wholesale,
        // which nukes any card-react-playable / card-playable classes that
        // playReactWindowOpened (or the initial hand render) applied. Re-
        // apply the playable-state classes now so clicks during the just-
        // opened react window land on correctly-highlighted cards.
        if (typeof updateHandHighlights === 'function') {
            try { updateHandHighlights(); } catch (e) { /* defensive */ }
        }
    } else {
        gameState = finalState;
        if (window.__lastLegalActions) legalActions = window.__lastLegalActions;
        if (typeof renderGame === 'function') {
            try { renderGame(); } catch (e) { /* defensive */ }
        }
        if (typeof updateHandHighlights === 'function') {
            try { updateHandHighlights(); } catch (e) { /* defensive */ }
        }
    }

    // Defensive recovery: reconcile leaked spell-stage chain entries.
    // Some server paths close a react window WITHOUT emitting
    // react_window_closed (tutor/revive hand-off, trigger drain-recheck,
    // melee pending_post_move), so playReactWindowClosed never pops the
    // matching entry. Each leak leaves slotState.spellStageChain /
    // _spellStage.chain non-empty, which keeps isSpellStageAnimating()
    // true FOREVER and gates all input (soft-lock). The authoritative
    // final_state knows better: if the server shows no active react
    // window (phase != REACT and react_stack empty), force-clear the
    // chain tracker and kick the visual resolve instead of wedging.
    try {
        var fsPhase = finalState.phase;
        var fsInReact = (fsPhase === 1) || (fsPhase === 'REACT');  // TurnPhase.REACT
        var fsStackEmpty = !finalState.react_stack
            || finalState.react_stack.length === 0;
        if (!fsInReact && fsStackEmpty) {
            if (slotState.spellStageChain.length > 0) {
                console.warn('[eventQueue] clearing '
                    + slotState.spellStageChain.length
                    + ' leaked spell-stage chain entries '
                    + '(server shows no open react window)');
                slotState.spellStageChain.length = 0;
            }
            if (typeof _spellStage !== 'undefined' && _spellStage
                && !_spellStage.resolving
                && ((_spellStage.chain && _spellStage.chain.length > 0)
                    || _spellStageBusy
                    || (_spellStageQueue && _spellStageQueue.length > 0))) {
                // Resolve (or defer-resolve, if slam-ins are still queued)
                // the stranded visual stage so it can never gate input
                // past this commit.
                _spellStageOnReactClosed();
            }
        }
    } catch (e) { /* defensive — recovery must never break the commit */ }
}

// Handshake-offer surfaces (user 2026-07-08): pod palm flag + a banner at
// the top of the tooltip sidebar so players not watching the board see it.
function _setPassOffer(idx) {
    _passOfferedBy = idx;
    try {
        if (typeof renderSelfInfo === 'function' && gameState && gameState.players) {
            renderSelfInfo();
            renderOpponentInfo();
        }
    } catch (e) { /* defensive */ }
    var sidebar = document.querySelector('#screen-game .game-tooltip-sidebar');
    var note = document.getElementById('pass-offer-note');
    if (idx == null || !sidebar) {
        if (note) note.remove();
        return;
    }
    var mine = (myPlayerIdx != null && idx === myPlayerIdx);
    var txt = mine
        ? '🫴 You passed — Handshake offered'
        : '🫴 ' + (opponentName || 'Opponent') + ' passed — pass to Handshake 🤝';
    if (!note) {
        note = document.createElement('div');
        note.id = 'pass-offer-note';
        sidebar.insertBefore(note, sidebar.firstChild);
    }
    note.textContent = txt;
}

function commitEventToDom(ev) {
    // Per-event state-commit + re-render hook. Plan 04a kept this a no-op
    // because the snapshot path (state_update / sandbox_state) committed
    // all state wholesale after every action. Plan 05 DELETED the snapshot
    // path but left commitEventToDom still effectively a no-op for 17 of
    // the 19 event types — so HP / turn / mana / phase / position changes
    // never hit the DOM until the next FULL engine_events frame arrived.
    //
    // Plan 05b fix (hybrid):
    //   * For events with clean payload deltas (hp/mana/turn/phase/move),
    //     apply the incremental field update to the live state ref
    //     (gameState + sandboxState) and trigger a targeted re-render so
    //     the DOM reflects THIS event's outcome at its scheduled beat.
    //   * For complex events (summon/die/card_*/attack/react_window_*),
    //     NO per-event commit here — they're covered by the wholesale
    //     _commitFinalStateSnapshot that fires ONCE when the queue drains.
    //
    // This preserves per-beat visibility for the paladin scenario (HP
    // ticks 30→32 at the trigger_blip beat, turn flips 1→2 at the
    // turn_flipped beat) while keeping complex-state-delta logic in ONE
    // place (the wholesale post-drain commit).
    if (!ev || !ev.type) return;

    // Pick the live state ref. In sandbox mode, sandboxState IS gameState
    // (assigned by the sandbox_state socket handler + _commitFinalStateSnapshot),
    // but we update both defensively so any future decoupling still works.
    var sbMode = (typeof sandboxMode !== 'undefined' && sandboxMode);
    var live = sbMode ? sandboxState : gameState;
    if (!live) {
        // No state to commit into yet (pre-game_start / pre-sandbox_create).
        return;
    }

    var payload = ev.payload || {};
    var needsBoardRerender = false;
    var needsStatsRerender = false;

    switch (ev.type) {
        case "minion_hp_change":
            // Payload: {instance_id, new_hp, delta, owner_idx, position, cause}
            if (_commitMinionHp(live, payload)) {
                if (sbMode) {
                    gameState = sandboxState;  // keep sandbox gameState alias in sync
                }
                needsBoardRerender = true;
            }
            break;

        case "player_hp_change":
            // Payload: {player_idx, prev, new, delta}
            if (_commitPlayerField(live, payload.player_idx, 'hp', payload['new'])) {
                if (sbMode) gameState = sandboxState;
                needsStatsRerender = true;
            }
            break;

        case "mana_change":
            // Payload: {player_idx, prev, new, delta}
            if (_commitPlayerField(live, payload.player_idx, 'current_mana', payload['new'])) {
                if (sbMode) gameState = sandboxState;
                needsStatsRerender = true;
            }
            break;

        case "dark_matter_change":
            // Payload: {player_idx, prev, new, delta, source} — DM pool
            // redesign (2026-07). Public info, committed for both viewers.
            if (_commitPlayerField(live, payload.player_idx, 'dark_matter', payload['new'])) {
                if (sbMode) gameState = sandboxState;
                needsStatsRerender = true;
            }
            break;

        case "turn_flipped":
            // Payload: {prev_turn, new_turn, new_active_idx}
            if (typeof payload.new_turn === 'number') {
                live.turn_number = payload.new_turn;
            }
            if (typeof payload.new_active_idx === 'number') {
                live.active_player_idx = payload.new_active_idx;
            }
            if (sbMode) gameState = sandboxState;
            needsStatsRerender = true;
            break;

        case "phase_changed":
            // Payload: {prev, new} — phase NAMES (TurnPhase.name strings,
            // e.g. "ACTION"/"REACT"). gameState.phase is an INT per
            // game_state.to_dict (int(self.phase)), and every phase
            // comparison in the client is numeric (isReactWindow, skip-react
            // button, sandbox hand-click guard, phase LEDs). Committing the
            // raw string broke all of them until the frame drained —
            // normalize to the wire int and skip the commit if unmapped.
            var normalizedPhase = _normalizePhaseValue(payload['new']);
            if (normalizedPhase !== null) {
                live.phase = normalizedPhase;
                if (sbMode) gameState = sandboxState;
            }
            try {
                var liveBadge = document.getElementById('phase-badge');
                var sbBadge = document.getElementById('sandbox-phase-badge');
                if (liveBadge && gameState) {
                    _setPhaseLeds(liveBadge, gameState.phase, gameState.react_return_phase);
                }
                if (sbBadge && sandboxState) {
                    _setPhaseLeds(sbBadge, sandboxState.phase, sandboxState.react_return_phase);
                }
            } catch (e) { /* defensive — phase LED is purely visual */ }
            break;

        case "minion_moved":
            if (_passOfferedBy != null) _setPassOffer(null);
            // Payload: {instance_id, from, to, owner_idx}
            if (_commitMinionPos(live, payload)) {
                if (sbMode) gameState = sandboxState;
                needsBoardRerender = true;
            }
            break;

        // Timing audit (2026-07-06): combat HP commits AT the strike beat —
        // attack_resolved used to leave the defender's badge at its
        // pre-attack value until drain end.
        case "attack_resolved":
            if (_passOfferedBy != null) _setPassOffer(null);
            var _hpA = false;
            if (typeof payload.defender_hp_after === 'number') {
                _hpA = _commitMinionHp(live, { instance_id: payload.defender_id, new_hp: payload.defender_hp_after }) || _hpA;
            }
            if (typeof payload.attacker_hp_after === 'number') {
                _hpA = _commitMinionHp(live, { instance_id: payload.attacker_id, new_hp: payload.attacker_hp_after }) || _hpA;
            }
            if (_hpA) {
                if (sbMode) gameState = sandboxState;
                needsBoardRerender = true;
            }
            break;

        // Timing audit (2026-07-06): the dead minion leaves the board AT its
        // death beat — it used to linger at 0 HP until the drain-end commit.
        case "minion_died":
            if (live && Array.isArray(live.minions) && payload.instance_id != null) {
                var _len = live.minions.length;
                live.minions = live.minions.filter(function(m) {
                    return !m || m.instance_id !== payload.instance_id;
                });
                if (live.minions.length !== _len) {
                    if (sbMode) gameState = sandboxState;
                    needsBoardRerender = true;
                }
            }
            break;

        // Timing audit (2026-07-07): the PLAYED card leaves the hand at its
        // beat — the wholesale players-commit that used to refresh it
        // incidentally was removed (it slammed pod numbers to end-of-chain
        // values), which left the card sitting in hand until drain end.
        case "pass_declared":
            _setPassOffer(payload.streak === 1 ? payload.player_idx : null);
            break;
        case "card_played":
            if (_passOfferedBy != null) _setPassOffer(null);
            if (live && live.players && live.players[payload.owner_idx]) {
                var _pp = live.players[payload.owner_idx];
                if (Array.isArray(_pp.hand) && typeof payload.card_index === 'number'
                        && _pp.hand[payload.card_index] === payload.card_numeric_id) {
                    _pp.hand.splice(payload.card_index, 1);
                } else if (Array.isArray(_pp.hand)) {
                    var _hi = _pp.hand.indexOf(payload.card_numeric_id);
                    if (_hi !== -1) _pp.hand.splice(_hi, 1);
                } else if (typeof _pp.hand_count === 'number' && _pp.hand_count > 0) {
                    _pp.hand_count--;
                }
                try {
                    if (!sbMode && payload.owner_idx === myPlayerIdx
                            && typeof renderHand === 'function') renderHand();
                    if (!sbMode && payload.owner_idx !== myPlayerIdx
                            && typeof renderOppHandRow === 'function') {
                        var _oc = (_pp.hand_count != null) ? _pp.hand_count
                            : (_pp.hand ? _pp.hand.length : 0);
                        renderOppHandRow(_oc, _pp.hand_elements || null);
                    }
                } catch (e) { /* defensive */ }
                needsStatsRerender = true;
            }
            break;

        // Timing audit (2026-07-06): pile / deck / hand counters tick at
        // their beats instead of jumping at drain end.
        case "card_drawn":
            if (live && live.players && live.players[payload.player_idx]) {
                var _pd = live.players[payload.player_idx];
                // Timing overhaul (2026-07-08, F3): conjured / declined-
                // conjure cards do NOT come from the deck — skip the deck
                // decrement for those sources or the pile under-counts
                // until drain end. Old payloads carry no source and keep
                // the decrement (turn-start / tutor draws all deck-sourced).
                // PREGAME (2026-07-08): mulligan replacement draws arrive
                // AFTER a game_start whose state already reflects the
                // post-mulligan deck — decrementing again would under-count
                // the pile, so gate 'mulligan' like the conjure sources.
                var _fromDeck = (payload.source !== 'conjure'
                    && payload.source !== 'decline_conjure'
                    && payload.source !== 'mulligan');
                if (_fromDeck) {
                    if (typeof _pd.deck_count === 'number' && _pd.deck_count > 0) _pd.deck_count--;
                    else if (Array.isArray(_pd.deck) && _pd.deck.length) _pd.deck.pop();
                }
                needsStatsRerender = true;
            }
            break;
        case "card_discarded":
            if (live && live.players && live.players[payload.player_idx]) {
                var _pg = live.players[payload.player_idx];
                if (Array.isArray(_pg.grave) && payload.card_numeric_id != null) _pg.grave.push(payload.card_numeric_id);
                else if (typeof _pg.grave_count === 'number') _pg.grave_count++;
                // Timing overhaul (2026-07-08, F3): the discarded card also
                // leaves the HAND at this beat — but ONLY when it is
                // actually found in the hand array. This event fires for
                // grave adds that never touched the hand (magic-to-grave
                // already spliced at card_played, minion deaths,
                // sacrifice), so a blind hand_count decrement is unsafe.
                // A tagged death/sacrifice grave add must ALSO never eat an
                // unrelated hand COPY of the same card — skip the splice
                // outright for those causes (new optional engine field;
                // old payloads carry no cause and rely on the in-hand check).
                var _pileOnly = (payload.cause === 'death'
                    || payload.cause === 'sacrifice');
                if (!_pileOnly
                        && Array.isArray(_pg.hand) && payload.card_numeric_id != null) {
                    var _di = _pg.hand.indexOf(payload.card_numeric_id);
                    if (_di !== -1) {
                        _pg.hand.splice(_di, 1);
                        try {
                            if (!sbMode && payload.player_idx === myPlayerIdx
                                    && typeof renderHand === 'function') renderHand();
                            if (!sbMode && payload.player_idx !== myPlayerIdx
                                    && typeof renderOppHandRow === 'function') {
                                var _dc = (_pg.hand_count != null) ? _pg.hand_count
                                    : (_pg.hand ? _pg.hand.length : 0);
                                renderOppHandRow(_dc, _pg.hand_elements || null);
                            }
                        } catch (e) { /* defensive */ }
                    }
                }
                needsStatsRerender = true;
            }
            break;
        case "card_burned":
            if (live && live.players && live.players[payload.player_idx]) {
                var _pe = live.players[payload.player_idx];
                if (Array.isArray(_pe.exhaust) && payload.card_numeric_id != null) _pe.exhaust.push(payload.card_numeric_id);
                else if (typeof _pe.exhaust_count === 'number') _pe.exhaust_count++;
                // Timing overhaul (2026-07-08, F3): every from-deck burn
                // source ticks the deck pile at its beat, not just the
                // turn-start overdraw. discard_cost / conjure burns come
                // from the hand, not the deck — excluded.
                var _burnFromDeck = (payload.source === 'turn_start'
                    || payload.source === 'handshake'
                    || payload.source === 'card_effect'
                    || payload.source === 'tutor');
                if (typeof _pe.deck_count === 'number' && _pe.deck_count > 0 && _burnFromDeck) _pe.deck_count--;
                // discard_cost burns exhaust a card FROM THE HAND (paid cost
                // of playing another card, new engine payload 2026-07-08).
                // Splice only on an exact in-hand match — never blind, and
                // never for other sources (a turn-start overdraw burn must
                // not eat an unrelated hand copy of the same card).
                if (payload.source === 'discard_cost'
                        && Array.isArray(_pe.hand) && payload.card_numeric_id != null) {
                    var _bi = _pe.hand.indexOf(payload.card_numeric_id);
                    if (_bi !== -1) {
                        _pe.hand.splice(_bi, 1);
                        try {
                            if (!sbMode && payload.player_idx === myPlayerIdx
                                    && typeof renderHand === 'function') renderHand();
                            if (!sbMode && payload.player_idx !== myPlayerIdx
                                    && typeof renderOppHandRow === 'function') {
                                var _bc = (_pe.hand_count != null) ? _pe.hand_count
                                    : (_pe.hand ? _pe.hand.length : 0);
                                renderOppHandRow(_bc, _pe.hand_elements || null);
                            }
                        } catch (e) { /* defensive */ }
                    }
                }
                needsStatsRerender = true;
            }
            break;

        // Complex events — no incremental commit here. The wholesale
        // _commitFinalStateSnapshot that runs when the queue drains still
        // picks up the authoritative post-chain state as the catch-all.
        //   minion_summoned / card_played / react_window_opened /
        //   react_window_closed / trigger_blip / pending_modal_* /
        //   fizzle / game_over
        default:
            break;
    }

    // Targeted re-render. Avoid applyStateFrame (which has burn-death
    // detection + heal popups that would double-fire since the slot
    // handlers already show popups). Board re-render is O(25) cells —
    // negligible per event.
    if (needsBoardRerender) {
        if (sbMode) {
            if (typeof renderSandbox === 'function') {
                try { renderSandbox(); } catch (e) { /* defensive */ }
            }
        } else {
            if (typeof renderBoard === 'function') {
                try { renderBoard(); } catch (e) { /* defensive */ }
            }
        }
    }
    if (needsStatsRerender) {
        // Timing overhaul (2026-07-08, F3): the visible pile cells + deck
        // extrusion tick at each draw/discard/burn beat instead of jumping
        // wholesale at drain end.
        try {
            if (typeof updatePileButtonCounts === 'function') updatePileButtonCounts();
        } catch (e) { /* defensive */ }
        if (sbMode) {
            if (typeof renderSandboxStats === 'function') {
                try { renderSandboxStats(); } catch (e) { /* defensive */ }
            }
            if (typeof renderRoomBar === 'function') {
                try { renderRoomBar(); } catch (e) { /* defensive */ }
            }
        } else {
            if (typeof renderRoomBar === 'function') {
                try { renderRoomBar(); } catch (e) { /* defensive */ }
            }
            if (typeof renderSelfInfo === 'function') {
                try { renderSelfInfo(); } catch (e) { /* defensive */ }
            }
            if (typeof renderOpponentInfo === 'function') {
                try { renderOpponentInfo(); } catch (e) { /* defensive */ }
            }
            if (typeof renderPlayerAvatars === 'function') {
                try { renderPlayerAvatars(); } catch (e) { /* defensive */ }
            }
        }
    }
}

// Phase 14.8-05b helper: mutate-in-place minion current_health by
// instance_id. Returns true if a minion was found + updated, false if no
// matching minion (already dead / never summoned / stale event).
function _commitMinionHp(state, payload) {
    if (!state || !state.minions || !payload) return false;
    var id = payload.instance_id;
    var newHp = payload.new_hp;
    if (id == null || typeof newHp !== 'number') return false;
    for (var i = 0; i < state.minions.length; i++) {
        var m = state.minions[i];
        if (m && m.instance_id === id) {
            m.current_health = newHp;
            return true;
        }
    }
    return false;
}

// Phase 14.8-05b helper: mutate-in-place minion position by instance_id.
function _commitMinionPos(state, payload) {
    if (!state || !state.minions || !payload || !payload.to) return false;
    var id = payload.instance_id;
    if (id == null) return false;
    for (var i = 0; i < state.minions.length; i++) {
        var m = state.minions[i];
        if (m && m.instance_id === id) {
            // Accept both [r,c] and {row, col} shapes from payload.to
            if (Array.isArray(payload.to)) {
                m.position = payload.to.slice();
            } else if (payload.to.row != null && payload.to.col != null) {
                m.position = [payload.to.row, payload.to.col];
            } else {
                return false;
            }
            return true;
        }
    }
    return false;
}

// EVT_PHASE_CHANGED payloads carry TurnPhase NAMES ("ACTION"/"REACT"/
// "START_OF_TURN"/"END_OF_TURN") while gameState.phase is the wire INT
// everywhere else (game_state.to_dict). Map name → int so numeric phase
// comparisons never see a string. Returns null when unmappable.
var _PHASE_NAME_TO_INT = {
    ACTION: 0,
    REACT: 1,
    START_OF_TURN: 2,
    END_OF_TURN: 3,
};
function _normalizePhaseValue(v) {
    if (typeof v === 'number') return v;
    if (typeof v === 'string' && _PHASE_NAME_TO_INT.hasOwnProperty(v)) {
        return _PHASE_NAME_TO_INT[v];
    }
    return null;
}

// Phase 14.8-05b helper: mutate-in-place player field by idx.
function _commitPlayerField(state, playerIdx, field, value) {
    if (!state || !state.players) return false;
    if (playerIdx == null || typeof value !== 'number') return false;
    var p = state.players[playerIdx];
    if (!p) return false;
    p[field] = value;
    return true;
}

function playEvent(ev, done) {
    // Dispatcher — maps event type to slot handler. Each handler MUST call
    // done() when its animation completes (or immediately for instant events).
    // Plan 04a implements 10 handlers; plan 04b finishes the rest.
    switch (ev.type) {
        case "minion_summoned":          return playMinionSummoned(ev, done);
        case "minion_died":              return playMinionDied(ev, done);
        case "minion_hp_change":         return playMinionHpChange(ev, done);
        case "minion_moved":             return playMinionMoved(ev, done);
        case "minion_transformed":       return playMinionTransformed(ev, done);
        case "minion_sacrificed":
            if (_passOfferedBy != null) _setPassOffer(null);
            return playMinionSacrificed(ev, done);
        case "attack_resolved":          return playAttackResolved(ev, done);
        case "card_drawn":               return playCardDrawn(ev, done);
        case "card_played":              return playCardPlayed(ev, done);
        case "card_discarded":           return playCardDiscarded(ev, done);
        case "mana_change":              return playManaChange(ev, done);
        case "player_hp_change":         return playPlayerHpChange(ev, done);
        // Dark Matter pool redesign (2026-07): a player's DM pool changed.
        case "dark_matter_change":       return playDarkMatterChange(ev, done);
        // Phase 14.8-04b: 9 harder handlers fully implemented.
        case "react_window_opened":      return playReactWindowOpened(ev, done);
        case "react_window_closed":      return playReactWindowClosed(ev, done);
        case "phase_changed":            return playPhaseChanged(ev, done);
        case "turn_flipped":             return playTurnFlipped(ev, done);
        case "trigger_blip":             return playTriggerBlip(ev, done);
        case "pending_modal_opened":     return playPendingModalOpened(ev, done);
        case "pending_modal_resolved":   return playPendingModalResolved(ev, done);
        case "fizzle":                   return playFizzle(ev, done);
        case "game_over":                return playGameOver(ev, done);
        // Turn-structure redesign (2026-07): new engine events. Aliases are
        // accepted defensively so the client renders them regardless of the
        // final EVT_* wire name the engine lane settles on.
        case "pass_declared":            return playPassDeclared(ev, done);
        case "handshake":
        case "handshake_resolved":       return playHandshake(ev, done);
        case "card_burned":              // EVT_CARD_BURNED — the real wire name
        case "overdraw_burn":
        case "card_overdrawn":
        case "card_exhausted":           return playOverdrawBurn(ev, done);
        // NOTE: the engine has no fatigue event type — fatigue arrives as
        // player_hp_change with payload.cause === "fatigue" and the skull
        // nudge fires from playPlayerHpChange. These aliases stay wired
        // defensively in case a dedicated event type is ever added.
        case "fatigue":
        case "fatigue_damage":           return playFatigueDamage(ev, done);
        default:
            console.warn("[eventQueue] Unknown event type: " + ev.type);
            return setTimeout(done, 0);
    }
}

function playInstant(ev, done) {
    // Zero-duration events (e.g. mana_change). Snapshot path commits the
    // underlying state; this slot just yields immediately.
    setTimeout(done, 0);
}

// ----- 10 simpler slot handlers (Task 2) ---------------------------
//
// Post-04b posture: the legacy snapshot path (state_update / sandbox_state
// → applyStateFrame → derive-* helpers) is still alive but no longer drives
// animations. The 4 ad-hoc gates that used to pace per-frame visuals have
// been deleted; every animation now flows through the eventQueue. The
// snapshot path remains as a pure state-cache for reconnect / initial-join
// / error-recovery parity; plan 14.8-05 deletes it entirely.
//
// For event-driven jobs we pass `stateAfter = gameState` so the existing
// playSummonAnimation/playMoveAnimation wrappers don't crash on an
// undefined frame. NOTE (post-plan-05): the snapshot path that used to
// pre-apply post-event state is GONE — handlers that need the DOM to show
// this event's outcome during their animation must incrementally commit
// it themselves (playMinionSummoned pushes the new minion, playCardDrawn
// appends the drawn card, commitEventToDom covers hp/mana/phase/move).
// The post-drain _commitFinalStateSnapshot remains the catch-all.

function _evDurationOr(ev, fallback) {
    if (ev && typeof ev.animation_duration_ms === 'number' && ev.animation_duration_ms >= 0) {
        return ev.animation_duration_ms;
    }
    return fallback;
}

function _evTileForPos(pos) {
    if (!pos) return null;
    return document.querySelector(
        '.board-cell[data-row="' + pos[0] + '"][data-col="' + pos[1] + '"]'
    );
}

function playMinionSummoned(ev, done) {
    // Payload: {instance_id, card_numeric_id, owner_idx, position}
    var payload = ev && ev.payload;
    if (!payload || !payload.position) { setTimeout(done, 0); return; }
    // Phase 14.8 fix: the snapshot path that used to pre-apply the
    // post-summon state was DELETED in plan 05, and commitEventToDom does
    // no incremental commit for minion_summoned — so at animation time
    // gameState is still PRE-summon and the scale-in used to play over an
    // EMPTY cell, with the minion popping in seconds later at the
    // post-drain commit. Incrementally commit the summoned minion into
    // the live state NOW so playSummonAnimation's applyStateFrame renders
    // the actual minion during its scale-in. Prefer the authoritative
    // minion object from final_state (full stats); fall back to
    // constructing one from the event payload + cardDefs.
    try {
        var live = (typeof sandboxMode !== 'undefined' && sandboxMode)
            ? sandboxState : gameState;
        if (live && live.minions && payload.instance_id != null) {
            var alreadyPresent = false;
            for (var mi = 0; mi < live.minions.length; mi++) {
                if (live.minions[mi]
                    && live.minions[mi].instance_id === payload.instance_id) {
                    alreadyPresent = true;
                    break;
                }
            }
            if (!alreadyPresent) {
                var newMinion = null;
                var fs = window.__lastFinalState;
                if (fs && fs.minions) {
                    for (var fi = 0; fi < fs.minions.length; fi++) {
                        if (fs.minions[fi]
                            && fs.minions[fi].instance_id === payload.instance_id) {
                            newMinion = JSON.parse(JSON.stringify(fs.minions[fi]));
                            // The minion may have moved/changed later in the
                            // chain — at THIS beat it stands where the event
                            // says it was summoned, at its BASE stats
                            // (timing audit 2026-07-06: end-of-chain HP /
                            // buffs used to show during the scale-in; later
                            // hp_change / buff beats commit the changes).
                            newMinion.position = payload.position.slice();
                            var _def = cardDefs && cardDefs[payload.card_numeric_id];
                            if (_def) {
                                if (typeof _def.health === 'number') newMinion.current_health = _def.health;
                                newMinion.attack_bonus = 0;
                                newMinion.is_burning = false;
                            }
                            break;
                        }
                    }
                }
                if (!newMinion && payload.card_numeric_id != null) {
                    var def = cardDefs && cardDefs[payload.card_numeric_id];
                    if (def) {
                        newMinion = {
                            instance_id: payload.instance_id,
                            card_numeric_id: payload.card_numeric_id,
                            owner: payload.owner_idx,
                            position: payload.position.slice(),
                            current_health: def.health,
                            attack_bonus: 0,
                            is_burning: false,
                            dark_matter_stacks: 0,
                            max_health_bonus: 0,
                            from_deck: true,
                        };
                    }
                }
                if (newMinion) {
                    live.minions.push(newMinion);
                    if (typeof sandboxMode !== 'undefined' && sandboxMode) {
                        gameState = sandboxState;  // keep sandbox alias in sync
                    }
                }
            }
        }
    } catch (e) { /* defensive — worst case the summon pops in at drain end */ }
    // Enqueue into the existing AnimationQueue so the summon animation
    // chains after any snapshot-driven animations. stateApplied=true so
    // runQueue doesn't re-apply an undefined state after the animation.
    // The inner playSummonAnimation ALSO calls applyStateFrame at START —
    // we pass the live gameState (post-event thanks to the incremental
    // commit above) so that call renders the minion mid scale-in.
    //
    // Phase 14.8 fix: the eventQueue's `done` MUST be paced by the actual
    // animQueue completion of THIS job, not a fixed 600ms guess. The
    // animQueue can have earlier jobs (card_fly, an in-flight attack)
    // queued ahead of this summon — if we fire done() at 600ms while the
    // summon is still waiting in the animQueue, the eventQueue races
    // forward to turn_flipped / phase_changed and the user sees the turn
    // banner bloom BEFORE the minion has appeared on the board. The
    // summon then pops in 1-2s later, after the turn has already passed.
    // Hard-cap the wait so a runaway animQueue never wedges the eventQueue.
    var settled = false;
    var settle = function() {
        if (settled) return;
        settled = true;
        done();
    };
    enqueueAnimation({
        type: 'summon',
        payload: {
            pos: payload.position,
            card_id: payload.card_numeric_id,
        },
        stateAfter: gameState,
        legalActionsAfter: legalActions,
        _fromEventQueue: true,
        onDone: settle,
    });
    // Safety cap (3 s): if the animQueue gets wedged, never let one summon
    // freeze the eventQueue forever.
    setTimeout(settle, Math.max(_evDurationOr(ev, 600), 3000));
}

function playMinionDied(ev, done) {
    // Payload: {instance_id, card_numeric_id, owner_idx, position, from_deck,
    //           cause?}  (cause is a new optional engine field — old payloads
    //           carry no cause; the is_burning fallback covers them.)
    // Timing overhaul (2026-07-08, F8): deaths get a real visual beat.
    //   * burn deaths → cinder animation on the still-rendered tile (the
    //     live-state minion + its DOM node are both still present here —
    //     commitEventToDom removes them only at done()).
    //   * other deaths → quick fade on the .board-minion + a card_fly ghost
    //     from the tile to the owner's grave pile cell.
    //   * 0ms fast path when the immediately-preceding attack_resolved
    //     already killed this minion — the lunge impact covered it.
    var payload = (ev && ev.payload) || {};
    var iid = payload.instance_id;
    try {
        var pe = slotState.prevDispatchedEvent;
        if (pe && pe.type === 'attack_resolved' && pe.payload && iid != null) {
            var pp = pe.payload;
            if ((pp.defender_killed && pp.defender_id === iid)
                || (pp.attacker_killed && pp.attacker_id === iid)) {
                setTimeout(done, 0);
                return;
            }
        }
    } catch (e) { /* defensive — fall through to the full animation */ }

    // Look up the live minion (still in state during this handler).
    var minion = null;
    try {
        var live = (typeof sandboxMode !== 'undefined' && sandboxMode)
            ? sandboxState : gameState;
        if (live && live.minions && iid != null) {
            for (var mi = 0; mi < live.minions.length; mi++) {
                if (live.minions[mi] && live.minions[mi].instance_id === iid) {
                    minion = live.minions[mi];
                    break;
                }
            }
        }
    } catch (e) { /* defensive */ }

    var isBurn = payload.cause === 'burn' || !!(minion && minion.is_burning);
    if (isBurn && minion) {
        var burnSettled = false;
        var burnSettle = function() {
            if (burnSettled) return;
            burnSettled = true;
            done();
        };
        try {
            playBurnDeathAnimation(minion, burnSettle);
        } catch (e) { burnSettle(); }
        // Safety cap so a swallowed animation can never wedge the queue.
        setTimeout(burnSettle, 1500);
        return;
    }

    // Non-burn death: fade the sprite + fly a ghost to the grave pile cell.
    try {
        var pos = payload.position || (minion && minion.position) || null;
        var tile = _evTileForPos(pos);
        var minionEl = tile && tile.querySelector('.board-minion');
        if (minionEl) {
            var rect = minionEl.getBoundingClientRect();
            minionEl.style.transition = 'opacity 400ms ease, transform 400ms ease';
            minionEl.style.opacity = '0';
            minionEl.style.transform = 'scale(0.7)';
            if (payload.card_numeric_id != null) {
                var ownIdx = (typeof sandboxMode !== 'undefined' && sandboxMode)
                    ? 0 : myPlayerIdx;
                enqueueAnimation({
                    type: 'card_fly',
                    fromRect: rect,
                    toZone: (payload.owner_idx === ownIdx) ? 'grave_own' : 'grave_opp',
                    cardNumericId: payload.card_numeric_id,
                    stateApplied: true,
                    _fromEventQueue: true,
                });
            }
        }
    } catch (e) { /* defensive — worst case the minion just disappears */ }
    setTimeout(done, Math.max(_evDurationOr(ev, 650), 650));
}

function playMinionHpChange(ev, done) {
    // Payload: {instance_id, new_hp, delta, owner_idx, position, cause}
    var payload = ev && ev.payload;
    if (!payload) { setTimeout(done, 0); return; }
    var tile = _evTileForPos(payload.position);
    var delta = payload.delta;
    if (tile && typeof delta === 'number' && delta !== 0) {
        var text, variant;
        if (delta > 0) {
            text = '💚 +' + delta;
            variant = 'heal';
        } else if (payload.cause === 'burn') {
            text = '🔥 ' + delta;  // already negative
            variant = 'burn-tick';
        } else {
            text = '⚔️ ' + delta;
            variant = 'combat-damage';
        }
        try { showFloatingPopup(tile, text, variant); } catch (e) { /* defensive */ }
    }
    setTimeout(done, _evDurationOr(ev, 400));
}

function playMinionMoved(ev, done) {
    // Payload: {instance_id, from, to, owner_idx}
    var payload = ev && ev.payload;
    if (!payload || !payload.from || !payload.to) { setTimeout(done, 0); return; }
    // Timing overhaul (2026-07-08, F1): commit the new position into the
    // live state BEFORE enqueueing (mirrors playMinionSummoned's up-front
    // commit). playMoveAnimation's Phase C calls applyStateFrame(gameState)
    // to render the minion at the DESTINATION for the drop keyframe — with
    // done() now gated on the actual animation end (onDone bridge below),
    // commitEventToDom's position write would land too late and Phase C
    // would re-render the minion still at the SOURCE.
    try {
        var live = (typeof sandboxMode !== 'undefined' && sandboxMode)
            ? sandboxState : gameState;
        if (_commitMinionPos(live, payload)
                && typeof sandboxMode !== 'undefined' && sandboxMode) {
            gameState = sandboxState;  // keep sandbox alias in sync
        }
    } catch (e) { /* defensive — worst case the drop plays on a bare tile */ }
    // Single-clock pacing (F1): done() fires when the move job's visual
    // actually completes, not on a fixed wire guess — earlier animQueue
    // jobs can delay this job's start.
    var settled = false;
    var settle = function() {
        if (settled) return;
        settled = true;
        done();
    };
    enqueueAnimation({
        type: 'move',
        payload: {
            from: payload.from,
            to: payload.to,
        },
        stateAfter: gameState,
        legalActionsAfter: legalActions,
        _fromEventQueue: true,
        onDone: settle,
    });
    // Safety cap: a wedged animQueue must never freeze the eventQueue.
    setTimeout(settle, Math.max(_evDurationOr(ev, 350), 3000));
}

// minion_transformed — EVT_MINION_TRANSFORMED (2026-07 card audit,
// Reanimated Bones). Payload: {instance_id, from_card_numeric_id,
// to_card_numeric_id, position, owner_idx, new_hp}. Post-plan-05 there
// is no snapshot path to pre-apply the swap, so commit it into the live
// state NOW, re-render so the tile shows the NEW form at this beat, and
// flash the tile so the swap reads as an event instead of a silent
// repaint at the post-drain snapshot commit.
function playMinionTransformed(ev, done) {
    var payload = ev && ev.payload;
    if (!payload) { setTimeout(done, 0); return; }
    var sbMode = (typeof sandboxMode !== 'undefined' && sandboxMode);
    try {
        var live = sbMode ? sandboxState : gameState;
        if (live && live.minions && payload.instance_id != null) {
            for (var i = 0; i < live.minions.length; i++) {
                var m = live.minions[i];
                if (m && m.instance_id === payload.instance_id) {
                    if (payload.to_card_numeric_id != null) {
                        m.card_numeric_id = payload.to_card_numeric_id;
                    }
                    if (typeof payload.new_hp === 'number') {
                        m.current_health = payload.new_hp;
                    }
                    break;
                }
            }
            if (sbMode) gameState = sandboxState;  // keep sandbox alias in sync
        }
        if (sbMode) {
            if (typeof renderSandbox === 'function') renderSandbox();
        } else {
            if (typeof renderBoard === 'function') renderBoard();
        }
    } catch (e) { /* defensive — worst case the swap lands at drain end */ }
    // Swap flash on the tile (engine DEFAULT_DURATION_MS = 600).
    var duration = _evDurationOr(ev, 600);
    try {
        var tile = _evTileForPos(payload.position);
        if (tile) {
            // 'summon' is a phantom SFX key (not in SFX_FILES) — use the
            // real card_play cue (timing overhaul 2026-07-08, F10c).
            playSfx('card_play');
            var flash = document.createElement('div');
            flash.className = 'transform-flash';
            tile.appendChild(flash);
            setTimeout(function() {
                if (flash.parentNode) flash.parentNode.removeChild(flash);
            }, duration + 100);
        }
    } catch (e) { /* defensive — flash is purely visual */ }
    setTimeout(done, duration);
}

function playAttackResolved(ev, done) {
    // Payload: {attacker_id, defender_id, target_pos, attacker_hp_before/after,
    //           defender_hp_before/after, attacker_killed, defender_killed}
    var payload = ev && ev.payload;
    if (!payload || !payload.target_pos) { setTimeout(done, 0); return; }
    // Look up attacker's live position via gameState (snapshot already
    // applied). If not found (already dead / off-board), skip the visual.
    var attackerPos = null;
    if (gameState && gameState.minions && payload.attacker_id != null) {
        for (var i = 0; i < gameState.minions.length; i++) {
            var m = gameState.minions[i];
            if (m && m.instance_id === payload.attacker_id) {
                attackerPos = m.position;
                break;
            }
        }
    }
    // No attacker on the board (already dead / off-board): no visual —
    // fast-bail at 0ms (timing overhaul 2026-07-08, F1 — this path used
    // to burn a full 500ms doing nothing).
    if (!attackerPos) {
        setTimeout(done, 0);
        return;
    }
    var damage = (payload.defender_hp_before != null && payload.defender_hp_after != null)
        ? Math.max(0, payload.defender_hp_before - payload.defender_hp_after)
        : 0;
    // Single-clock pacing (F1): gate done() on the attack job's actual
    // completion (onDone bridge), with a safety-cap timeout.
    var settled = false;
    var settle = function() {
        if (settled) return;
        settled = true;
        done();
    };
    enqueueAnimation({
        type: 'attack',
        payload: {
            attackerPos: attackerPos,
            targetPos: payload.target_pos,
            damage: damage,
            killed: !!payload.defender_killed,
        },
        stateAfter: gameState,
        legalActionsAfter: legalActions,
        _fromEventQueue: true,
        onDone: settle,
    });
    setTimeout(settle, Math.max(_evDurationOr(ev, 500), 3000));
}

function playCardDrawn(ev, done) {
    // Payload: {player_idx} (plus optional card_numeric_id when viewer is the
    // drawer per view_filter redaction).
    var payload = ev && ev.payload;
    if (!payload) { setTimeout(done, 0); return; }
    // Single-clock pacing (F1): gate done() on the draw job's actual
    // completion (onDone bridge) with a safety cap, mirroring
    // playMinionSummoned.
    var settled = false;
    var settle = function() {
        if (settled) return;
        settled = true;
        done();
    };
    var playerIdx = payload.player_idx;
    var isOwn = sandboxMode
        ? true  // sandbox sees both hands
        : (playerIdx === myPlayerIdx);
    if (isOwn && payload.card_numeric_id != null) {
        // Phase 14.8 fix: under the post-plan-05 pipeline the hand DOM is
        // only rebuilt by the post-drain final-state commit, so at
        // animation time the "last hand child" fallback pointed at the
        // last card of the PRE-draw hand — the fly-in hid an unrelated
        // card for ~800ms and the actually-drawn card popped in seconds
        // later with no animation. Incrementally append the drawn card to
        // the live hand, re-render, and target the real new slot. The
        // final_state hand length caps the append so paths that already
        // synced players wholesale (counter-react chain refresh) never
        // double-append.
        var newSlotIdx = -1;
        try {
            var live = sandboxMode ? sandboxState : gameState;
            var livePlayer = live && live.players && live.players[playerIdx];
            if (livePlayer && Array.isArray(livePlayer.hand)) {
                var fsHand = null;
                var fs = window.__lastFinalState;
                if (fs && fs.players && fs.players[playerIdx]
                    && Array.isArray(fs.players[playerIdx].hand)) {
                    fsHand = fs.players[playerIdx].hand;
                }
                if (fsHand === null || livePlayer.hand.length < fsHand.length) {
                    livePlayer.hand.push(payload.card_numeric_id);
                    newSlotIdx = livePlayer.hand.length - 1;
                    if (sandboxMode) {
                        gameState = sandboxState;  // keep sandbox alias in sync
                        if (typeof renderSandbox === 'function') renderSandbox();
                    } else if (playerIdx === myPlayerIdx
                               && typeof renderHand === 'function') {
                        renderHand();
                    }
                    if (typeof updateHandHighlights === 'function') {
                        try { updateHandHighlights(); } catch (e) { /* defensive */ }
                    }
                }
            }
        } catch (e) { /* defensive — fall back to last-child targeting */ }
        enqueueAnimation({
            type: 'draw_own',
            cardNumericId: payload.card_numeric_id,
            fromPos: 'deck',
            toSlotIndex: newSlotIdx,  // -1 falls back to last hand child
            stateApplied: true,
            _fromEventQueue: true,
            onDone: settle,
        });
    } else {
        // Element card backs (2026-07): the view filter attaches the drawn
        // card's ELEMENT (and only that) to opponent card_drawn events so
        // the pop-in back can carry the tint. Accept both key spellings.
        var elVal = (payload.element != null) ? payload.element : payload.card_element;
        // Incrementally commit the opponent hand-size delta + element list
        // and re-render the row NOW (mirrors the own-draw fix above): the
        // final-state snapshot only lands post-drain, so without this the
        // pop-in would target the PRE-draw last back. The final_state
        // hand_count caps the increment so wholesale-synced paths never
        // double-append.
        try {
            if (!sandboxMode && gameState && gameState.players) {
                var liveOpp = gameState.players[playerIdx];
                if (liveOpp && liveOpp.hand_count != null) {
                    var fsCount = null;
                    var fs2 = window.__lastFinalState;
                    if (fs2 && fs2.players && fs2.players[playerIdx]) {
                        var fsp = fs2.players[playerIdx];
                        fsCount = (fsp.hand_count != null)
                            ? fsp.hand_count
                            : (Array.isArray(fsp.hand) ? fsp.hand.length : null);
                    }
                    if (fsCount === null || liveOpp.hand_count < fsCount) {
                        liveOpp.hand_count = (liveOpp.hand_count | 0) + 1;
                        if (Array.isArray(liveOpp.hand_elements)) {
                            liveOpp.hand_elements.push(elVal != null ? elVal : null);
                        }
                        renderOppHandRow(liveOpp.hand_count, _playerHandElements(liveOpp));
                    }
                }
            }
        } catch (e) { /* defensive — fall back to last-back targeting */ }
        enqueueAnimation({
            type: 'draw_opp',
            element: (elVal != null) ? elVal : null,
            stateApplied: true,
            _fromEventQueue: true,
            onDone: settle,
        });
    }
    // Safety cap: never let a wedged animQueue freeze the eventQueue.
    setTimeout(settle, Math.max(_evDurationOr(ev, 350), 3000));
}

function playCardPlayed(ev, done) {
    // Payload: {card_numeric_id, card_index, owner_idx, target_pos, position,
    //           is_react?}
    // Visual is covered by spell stage in/out (react_window_opened/closed, 04b)
    // for magic/react cards, and by minion_summoned for minions.
    // Phase 14.8-05: stash the originator so playReactWindowOpened (which
    // the engine emits RIGHT AFTER this event in the same frame for
    // action-triggered react windows) can slam the card onto the spell
    // stage LEFT slot. See slotState.lastOriginator comment.
    var payload = (ev && ev.payload) || {};
    if (payload.card_numeric_id != null) {
        slotState.lastOriginator = {
            numericId: payload.card_numeric_id,
            playerIdx: (payload.owner_idx != null
                ? payload.owner_idx
                : payload.player_idx),
            source: 'card_played',
        };
    }
    // Phase 14.8-05c: counter-react chain extension. When is_react=true
    // AND the spell stage is already up, slam the react card onto the
    // stage's NEXT slot (the conveyor) without emitting a new window-
    // opened event (which would create a phantom chain entry the engine
    // never closes — LIFO resolves fire ONE react_window_closed for the
    // whole window). Refresh legal actions + hand highlights so the
    // opposing player's counter-counter react card becomes clickable.
    if (payload.is_react && payload.card_numeric_id != null) {
        try {
            var ownerIdx = payload.owner_idx != null
                ? payload.owner_idx
                : payload.player_idx;
            // Step 0: hide the source card in the hand IMMEDIATELY so the
            // user doesn't see a duplicate during the slam (the original
            // sitting in the fan + the slam clone flying to the stage).
            // We use visibility:hidden instead of display:none so the
            // hand fan layout doesn't shift mid-slam — the gap stays
            // until the deferred render collapses it cleanly.
            try {
                var srcContainerId = sandboxMode
                    ? ('sandbox-hand-p' + ownerIdx)
                    : (ownerIdx === myPlayerIdx ? 'hand-container' : 'oppHandRow');
                var srcContainer = document.getElementById(srcContainerId);
                if (srcContainer) {
                    var srcCards = srcContainer.querySelectorAll('.card-frame[data-numeric-id="' + payload.card_numeric_id + '"]');
                    if (srcCards.length > 0) {
                        // Hide the FIRST matching card (multiple copies in
                        // hand all match — picking the first is fine for
                        // the visual; the deferred render fixes counts).
                        srcCards[0].style.visibility = 'hidden';
                    }
                }
            } catch (_) { /* defensive */ }
            // Step 1: slam the card from hand to stage. Source rect is the
            // hand container, so we MUST do this BEFORE re-rendering the
            // hand — otherwise the rect of an empty hand makes the slam
            // animation read like the card flies from nowhere.
            if (typeof _showSpellStage === 'function') {
                _showSpellStage(payload.card_numeric_id, ownerIdx);
            }
            // Phase 14.8-05c: consume the originator we just stashed above
            // so the matching playReactWindowOpened (engine emits one for
            // every counter-react chain extension) doesn't re-slam the
            // same card. Without this, the user sees the LAST react card
            // briefly duplicated on its owner's stack right before the
            // LIFO resolve.
            slotState.lastOriginator = null;
            // Step 2: legal actions + state refresh (cheap, no DOM
            // disruption). The opposing player's counter-counter react
            // card needs to highlight as react-playable.
            if (window.__lastLegalActions) {
                legalActions = window.__lastLegalActions;
                if (sandboxMode) { sandboxLegalActions = window.__lastLegalActions; }
            }
            var fs = window.__lastFinalState;
            if (fs) {
                var live = sandboxMode ? sandboxState : gameState;
                if (live) {
                    if (typeof fs.phase === 'number') live.phase = fs.phase;
                    if (typeof fs.react_player_idx !== 'undefined') live.react_player_idx = fs.react_player_idx;
                    if (typeof fs.react_context !== 'undefined') live.react_context = fs.react_context;
                    // Timing audit (2026-07-06): do NOT wholesale-commit
                    // fs.players here — it is the END-OF-CHAIN snapshot and
                    // slammed every pod/pile number to future values mid-
                    // drain. Only current_mana syncs (react cost checks);
                    // everything else commits at its own beat / drain end.
                    if (Array.isArray(fs.players) && Array.isArray(live.players)) {
                        for (var pi = 0; pi < live.players.length; pi++) {
                            if (fs.players[pi] && live.players[pi]) {
                                live.players[pi].current_mana = fs.players[pi].current_mana;
                            }
                        }
                    }
                    if (sandboxMode && gameState) {
                        gameState.phase = live.phase;
                        gameState.react_player_idx = live.react_player_idx;
                        gameState.react_context = live.react_context;
                    }
                }
            }
            // Step 3: defer the hand re-render until AFTER the slam-in
            // animation completes (~520ms slam + brief settle = ~600ms).
            // Re-rendering immediately would visually snap the hand
            // mid-slam — the user sees the card fly out AND the
            // remaining cards re-fan at the same instant which reads as
            // a jarring shuffle. Deferring lets the slam land cleanly,
            // then the hand collapses afterwards.
            setTimeout(function() {
                try {
                    // Timing audit (2026-07-06): targeted refresh only — a
                    // full renderGame here re-lit future-frame affordances
                    // and re-synced modal UI mid-drain. The hand collapse
                    // (what this defer exists for) + react-glow refresh is
                    // all the counter-react decision needs.
                    if (sandboxMode && typeof renderSandbox === 'function') {
                        renderSandbox();
                    } else if (!sandboxMode && typeof renderHand === 'function') {
                        renderHand();
                    }
                    if (typeof updateHandHighlights === 'function') updateHandHighlights();
                } catch (_) { /* defensive */ }
            }, 600);
        } catch (e) { /* defensive */ }
    }
    setTimeout(done, _evDurationOr(ev, 0));
}

function playCardDiscarded(ev, done) {
    // Payload: {player_idx, card_numeric_id, cause?}
    // Timing overhaul (2026-07-08, F9b): when the discarded card is visibly
    // in the viewer's hand, capture its slot rect NOW (BEFORE the F3 beat
    // commit splices the hand at done()) and fly a ghost hand→grave. The
    // event also fires for non-hand grave adds (magic resolution, deaths,
    // sacrifice) — those find no hand slot and pass through at 0ms.
    var payload = (ev && ev.payload) || {};
    if (payload.card_numeric_id == null) { setTimeout(done, 0); return; }
    // Death / sacrifice grave adds are pile-only — the card was on the
    // BOARD, so flying a matching hand copy would be wrong (F8 risk note).
    // Their visuals are owned by playMinionDied / the transcend animation.
    if (payload.cause === 'death' || payload.cause === 'sacrifice') {
        setTimeout(done, 0);
        return;
    }
    var slotEl = null;
    try {
        var containerId = sandboxMode
            ? ('sandbox-hand-p' + payload.player_idx)
            : ((payload.player_idx === myPlayerIdx) ? 'hand-container' : null);
        var container = containerId && document.getElementById(containerId);
        if (container) {
            var matches = container.querySelectorAll(
                '.card-frame[data-numeric-id="' + payload.card_numeric_id + '"]');
            for (var si = 0; si < matches.length; si++) {
                if (matches[si].style.visibility !== 'hidden') {
                    slotEl = matches[si];
                    break;
                }
            }
        }
    } catch (e) { /* defensive */ }
    if (!slotEl) { setTimeout(done, 0); return; }
    var settled = false;
    var settle = function() {
        if (settled) return;
        settled = true;
        done();
    };
    try {
        var rect = slotEl.getBoundingClientRect();
        // Hide the source slot so the user doesn't see the card in hand AND
        // the flying ghost. The F3 commit + renderHand at done() collapses
        // the gap cleanly.
        slotEl.style.visibility = 'hidden';
        var ownIdx = sandboxMode ? 0 : myPlayerIdx;
        enqueueAnimation({
            type: 'card_fly',
            fromRect: rect,
            toZone: (payload.player_idx === ownIdx) ? 'grave_own' : 'grave_opp',
            cardNumericId: payload.card_numeric_id,
            stateApplied: true,
            _fromEventQueue: true,
            onDone: settle,
        });
    } catch (e) { settle(); return; }
    setTimeout(settle, Math.max(_evDurationOr(ev, 0), 3000));
}

function playPlayerHpChange(ev, done) {
    // Payload: {player_idx, prev, new, delta, cause?}
    var payload = ev && ev.payload;
    if (!payload || typeof payload.delta !== 'number') { setTimeout(done, 0); return; }
    var delta = payload.delta;
    // Fatigue (turn-structure redesign 2026-07): the engine emits empty-deck
    // turn-start fatigue as player_hp_change with cause="fatigue" — there is
    // NO dedicated fatigue event type. Fire the DECK EMPTY — FATIGUE skull
    // nudge here and hold the queue long enough for it to register.
    if (payload.cause === 'fatigue') {
        try {
            triggerFatigueNudge(delta < 0 ? -delta : null, payload.player_idx);
        } catch (e) { /* defensive — nudge is purely visual */ }
    }
    // Only negatives get the damage popup (heals on player HP are rare and
    // covered by green shield popup on the HP stat — snapshot path handles).
    if (delta < 0) {
        var el = document.getElementById(_hpStatElementId(payload.player_idx));
        if (el) {
            var rect = el.getBoundingClientRect();
            var pop = document.createElement('div');
            pop.className = 'damage-popup hp-damage-popup';
            pop.style.position = 'fixed';
            pop.style.left = (rect.left + rect.width / 2 - 20) + 'px';
            pop.style.top = (rect.top - 8) + 'px';
            pop.textContent = String(delta);
            document.body.appendChild(pop);
            el.classList.add('hp-flash');
            setTimeout(function() {
                if (pop.parentNode) pop.parentNode.removeChild(pop);
                el.classList.remove('hp-flash');
            }, 950);
        }
    }
    // Fatigue paces longer than a plain HP tick so the skull nudge lands
    // before the next queued event (turn banner etc.) plays over it.
    if (payload.cause === 'fatigue') {
        setTimeout(done, Math.max(_evDurationOr(ev, 400), 1200));
        return;
    }
    setTimeout(done, _evDurationOr(ev, 400));
}

// ----- 9 harder slot handlers (Plan 14.8-04b, Task 1) ----------------
//
// Each handler below replaces the stubbed console.warn + setTimeout(done, 0)
// from plan 04a. The implementations REUSE existing animation primitives
// introduced by Phase 14.7-09 (turn banner, trigger blip, spell stage chain,
// phase-LED flash) and Phase 14-PLAY-03 (game-over overlay) rather than
// reimplementing them — DRY per plan 04b failure_handling.
//
// Each handler respects `ev.animation_duration_ms` via _evDurationOr so the
// eventQueue paces subsequent events at the wall-clock speed the server
// declared. DEFAULT_DURATION_MS table (engine_events.py) populates the
// field for events that don't override.

// react_window_opened — push the newly-opened window onto a client-side
// spell-stage chain AND slam the originator card onto the stage LEFT slot.
// Piggy-backs on the existing _spellStage LIFO so the visual stacking
// (caster cards LEFT, opponent reacts RIGHT, resolve-pop bottom-to-top) is
// preserved verbatim from Phase 14.7-09.
//
// Payload: {react_context, react_player_idx, return_phase, shortcut?}
//
// The event doesn't carry the specific card that opened the window (the
// engine emits it separately as card_played or trigger_blip just BEFORE
// this event in the same EventStream). Phase 14.8-05 consumes the
// slotState.lastOriginator stash populated by those preceding handlers —
// a small piece of inter-handler coupling, but it keeps the engine's
// event-shape work (plan 03a) unchanged while giving the client the
// visual it needs.
//
// Shortcut-path (AFTER_START_TRIGGER with no triggers fired — plan 03b
// orchestrator decision #3) emits a zero-duration react_window_opened +
// react_window_closed pair with no preceding originator. We detect the
// shortcut flag in the payload and skip the stage open entirely for
// those — no originator to show, no visible react window needed.
function playReactWindowOpened(ev, done) {
    var payload = (ev && ev.payload) || {};
    slotState.spellStageChain.push({
        react_context: payload.react_context || null,
        react_player_idx: payload.react_player_idx,
        return_phase: payload.return_phase || null,
        source_event_seq: ev.seq,
    });
    // Zero-duration shortcut path: no originator, no visible stage. Pace
    // the queue at 0ms and let the matching react_window_closed pop the
    // chain entry immediately.
    if (payload.shortcut) {
        setTimeout(done, _evDurationOr(ev, 0));
        return;
    }
    // Consume the stashed originator from the preceding card_played /
    // trigger_blip and slam it onto the spell stage LEFT slot. If no
    // originator is stashed (engine path that doesn't emit one, or out-
    // of-order delivery somehow), log but continue — the chain tracker
    // still increments so close_react_window pops the right entry.
    var origin = slotState.lastOriginator;
    slotState.lastOriginator = null;  // consume
    // Timing overhaul (2026-07-08, F6/F7): three-way branch on the
    // originator. Trigger-sourced windows skip the spell-stage ceremony
    // entirely — the ~500ms blip + effect popup ARE the visual, and the
    // stage now slams a card only when a player actually PLAYS a react
    // (playCardPlayed's is_react branch opens it independently, so
    // counter-play is unaffected). Only a real slam earns the 1500ms gate.
    var slammed = false;
    if (origin && origin.numericId != null
            && origin.source === 'trigger_blip') {
        // No stage for passive triggers — fall through to done(0) below.
    } else if (origin && origin.numericId != null) {
        try {
            _showSpellStage(origin.numericId, origin.playerIdx);
            slammed = true;
        } catch (e) {
            // Defensive — a broken render must not crash the eventQueue.
            console.warn('playReactWindowOpened: _showSpellStage threw', e);
        }
    } else {
        // Debug hint — helpful when chasing "spell stage didn't show"
        // regressions. Single-line console log (no scary warnings for
        // expected shortcut-path gaps).
        try {
            console.debug(
                '[eventQueue] react_window_opened with no stashed originator ' +
                '(react_context=' + payload.react_context + ')'
            );
        } catch (_) { /* console.debug not defined */ }
    }
    // Phase 14.8-05c: A react window just opened and the user is about to
    // decide. If we wait for the full queue drain to apply the fresh
    // final_state + legal_actions (plan 14.8-05b's post-drain commit),
    // the user's click during the spell-stage animation sees STALE
    // legalActions — e.g. the counter-react PLAY_REACT for their card is
    // missing, so onHandCardClick's react branch finds no match and the
    // click falls through. The spell-stage click-through then lands on
    // the floating SKIP REACT button which fires a PASS, collapsing the
    // chain. Re-sync legalActions + phase + react_player_idx on
    // sandboxState / gameState NOW so clicks find the match.
    try {
        if (window.__lastLegalActions) {
            legalActions = window.__lastLegalActions;
            if (sandboxMode) { sandboxLegalActions = window.__lastLegalActions; }
        }
        var fs = window.__lastFinalState;
        if (fs) {
            var live = sandboxMode ? sandboxState : gameState;
            if (live) {
                // Only rewrite the fields that gate react-click eligibility.
                // Full wholesale state apply stays on the post-drain path so
                // minion renders don't flicker.
                if (typeof fs.phase === 'number') live.phase = fs.phase;
                if (typeof fs.react_player_idx !== 'undefined') live.react_player_idx = fs.react_player_idx;
                if (typeof fs.react_context !== 'undefined') live.react_context = fs.react_context;
                if (sandboxMode && gameState) {
                    gameState.phase = live.phase;
                    gameState.react_player_idx = live.react_player_idx;
                    gameState.react_context = live.react_context;
                }
            }
        }
        // Re-render the hand so card-react-playable marks the correct
        // cards. updateHandHighlights() reads legalActions + gameState.
        if (typeof updateHandHighlights === 'function') updateHandHighlights();
    } catch (e) { /* defensive */ }
    // Pacing (F6/F7b): a real slam paces at the stage-per-card beat
    // (520ms fly + 1000ms hold) — deliberately IGNORING the wire duration
    // (playHandshake pattern: the wire says 600ms, which would advance the
    // queue mid-slam). No slam → nothing to watch → 0ms pass-through.
    if (slammed) {
        var _perCard = (typeof SPELL_STAGE_PER_CARD_MS === 'number')
            ? SPELL_STAGE_PER_CARD_MS : 1500;
        setTimeout(done, _perCard);
    } else {
        setTimeout(done, 0);
    }
}

// react_window_closed — pop the topmost chain entry. When the chain drains
// to empty AND the spell stage is still visually up, kick off the LIFO
// resolve-pop + hide. Reuses the existing _spellStageOnReactClosed helper.
function playReactWindowClosed(ev, done) {
    // Pop chain entry. Defensive against underflow (server emits an
    // EVT_REACT_WINDOW_CLOSED even for shortcut-path symmetry when no
    // triggers fired — chain may already be empty).
    if (slotState.spellStageChain.length > 0) {
        slotState.spellStageChain.pop();
    }
    // Timing overhaul (2026-07-08): a shortcut pair never slammed anything —
    // never wait on a stage resolve here (a previous window's resolve may
    // still be animating and would otherwise re-gate this close ~1.5s).
    if ((ev && ev.payload && ev.payload.shortcut) === true) {
        setTimeout(done, 0);
        return;
    }
    // Only close the stage if the chain is empty AND the stage is visibly
    // up. Otherwise the next react_window_closed in the chain is about to
    // pop and we'd be prematurely closing.
    var chainEmpty = slotState.spellStageChain.length === 0;
    var stageUp = (typeof isSpellStageAnimating === 'function')
        ? isSpellStageAnimating() : false;
    // Audit fix (2026-07-06): the REACT WINDOW banner + Skip React pill
    // used to linger until the drain-end renderGame, seconds after the
    // window actually closed. Clear them the moment the chain empties.
    if (chainEmpty && typeof document !== 'undefined') {
        var rbClosed = document.getElementById('react-banner');
        if (rbClosed) rbClosed.remove();
        var fsbClosed = document.getElementById('floating-skip-react-btn');
        if (fsbClosed) fsbClosed.hidden = true;
    }
    if (chainEmpty && stageUp) {
        setTimeout(_spellStageOnReactClosed, 0);
        // Phase 14.8-05c: the LIFO resolve runs out-of-band via setTimeout
        // chains in _doSpellStageResolve (700ms intro + 550ms per card +
        // 250ms exit). Without waiting for it, the eventQueue races
        // straight to turn_flipped and the banner blooms while cards are
        // still popping off the stage — exactly the user-reported "turn 2
        // happens during react window" symptom.
        //
        // Phase 14.8 fix: the resolve may not START immediately —
        // _spellStageOnReactClosed defers while slam-ins are still queued
        // (_spellStageBusy / _spellStageQueue non-empty), and each queued
        // slam takes SPELL_STAGE_PER_CARD_MS before the LIFO pop begins.
        // Queued cards are also not yet in _spellStage.chain, so count
        // them for the per-card pop as well; otherwise done() fires
        // 1.5-3s early and the turn banner plays over the resolving stage.
        var pendingIn = _spellStageQueue.length + (_spellStageBusy ? 1 : 0);
        var totalCards = _spellStage.chain.length + _spellStageQueue.length;
        var resolveDur = (pendingIn * SPELL_STAGE_PER_CARD_MS)
            + 700 + (totalCards * 550) + 250;
        setTimeout(done, Math.max(_evDurationOr(ev, 400), resolveDur));
        return;
    }
    setTimeout(done, _evDurationOr(ev, 400));
}

// phase_changed — flash the matching phase LED and re-render the phase
// indicator. Zero-duration by default (the LED flash is fire-and-forget);
// commitEventToDom handles the actual indicator refresh.
//
// Payload: {prev, new}
function playPhaseChanged(ev, done) {
    var payload = (ev && ev.payload) || {};
    var nextPhase = payload['new'];
    // Engine TurnPhase names (from .name): "ACTION", "REACT",
    // "START_OF_TURN", "END_OF_TURN". Our LED keys are 'start' / 'end' /
    // 'action'; REACT flashes nothing (react badge handled separately).
    try {
        if (nextPhase === 'START_OF_TURN') {
            _flashPhaseLed('start', 900);
        } else if (nextPhase === 'END_OF_TURN') {
            _flashPhaseLed('end', 900);
        }
        // ACTION / REACT: no extra flash needed — commitEventToDom's
        // _setPhaseLeds call updates the indicator from current state.
    } catch (e) { /* defensive — phase LED is purely visual */ }
    // Timing overhaul (2026-07-08, F7e): when this Rally/Decay phase will
    // actually DO something (a trigger blip or a burn tick is queued before
    // the next phase_changed), announce it with a compact 600ms chip so the
    // upcoming beats read as "RALLY" / "DECAY" instead of unexplained
    // popups. Empty phases keep the 0ms pass-through.
    if (nextPhase === 'START_OF_TURN' || nextPhase === 'END_OF_TURN') {
        var hasWork = false;
        try {
            for (var qi = 0; qi < eventQueue.length; qi++) {
                var qe = eventQueue[qi];
                if (!qe) continue;
                if (qe.type === 'phase_changed') break;
                if (qe.type === 'trigger_blip'
                        || (qe.type === 'minion_hp_change'
                            && qe.payload && qe.payload.cause === 'burn')) {
                    hasWork = true;
                    break;
                }
            }
        } catch (e) { /* defensive */ }
        if (hasWork) {
            try {
                var chip = document.createElement('div');
                chip.className = 'phase-flow-chip';
                chip.textContent = (nextPhase === 'START_OF_TURN') ? 'RALLY' : 'DECAY';
                _stageMount().appendChild(chip);
                setTimeout(function() {
                    if (chip.parentNode) chip.parentNode.removeChild(chip);
                }, 700);
            } catch (e) { /* defensive — chip is purely visual */ }
            setTimeout(done, 600);
            return;
        }
    }
    setTimeout(done, _evDurationOr(ev, 0));
}

// turn_flipped — show the TURN N / PLAYER M banner. Reuses the
// _runTurnFlipVisuals helper (END LED flash → banner bloom → START LED
// flash) verbatim from Phase 14.7-09. Duration defaults to 1500ms per
// DEFAULT_DURATION_MS[EVT_TURN_FLIPPED] in engine_events.py (matches the
// CSS turn-transition-banner-in keyframe timing).
//
// Payload: {prev_turn, new_turn, new_active_idx}
function playTurnFlipped(ev, done) {
    var payload = (ev && ev.payload) || {};
    var newTurn = payload.new_turn;
    var newActiveIdx = payload.new_active_idx;
    if (typeof newTurn === 'number' && typeof newActiveIdx === 'number') {
        try {
            _runTurnFlipVisuals(newTurn, newActiveIdx);
        } catch (e) { /* defensive — banner is purely visual */ }
    }
    // Pace the queue at the full END→banner→START cycle (~1800ms total).
    // Using _evDurationOr gives the server the final word but we fall back
    // to 1500ms to let the banner bloom fully before the next event fires.
    setTimeout(done, _evDurationOr(ev, 1500));
}

// trigger_blip — source tile pulse → center glyph → target tile pulse.
// Reuses _fireTriggerBlipAnimation verbatim from Phase 14.7-09.
//
// Payload: {trigger_kind, source_minion_id, source_position,
//           target_position, effect_kind}
function playTriggerBlip(ev, done) {
    var payload = ev && ev.payload;
    if (payload) {
        try {
            _fireTriggerBlipAnimation(payload);
        } catch (e) { /* defensive — blip must never throw */ }
        // Phase 14.8-05: stash the originator (the triggering minion's card)
        // so playReactWindowOpened can slam the source minion's card onto
        // the spell-stage LEFT slot for trigger-driven react windows
        // (AFTER_START_TRIGGER / BEFORE_END_OF_TURN / AFTER_DEATH_EFFECT).
        // The engine doesn't emit source_card_numeric_id in the blip today
        // (only source_minion_id + source_position), so we look the card up
        // from gameState.minions. Best-effort — if the minion already died,
        // fall through without populating lastOriginator (the stage will
        // open empty-LEFT which is visually tolerable for now).
        try {
            var liveState = (typeof sandboxMode !== 'undefined' && sandboxMode)
                ? sandboxState : gameState;
            var srcId = payload.source_minion_id;
            var srcMinion = null;
            if (srcId != null && liveState && liveState.minions) {
                for (var mi = 0; mi < liveState.minions.length; mi++) {
                    if (liveState.minions[mi] &&
                        liveState.minions[mi].instance_id === srcId) {
                        srcMinion = liveState.minions[mi];
                        break;
                    }
                }
            }
            if (srcMinion && srcMinion.card_numeric_id != null) {
                slotState.lastOriginator = {
                    numericId: srcMinion.card_numeric_id,
                    playerIdx: srcMinion.owner,
                    source: 'trigger_blip',
                };
            }
        } catch (e) { /* defensive */ }
    }
    setTimeout(done, _evDurationOr(ev, 900));
}

// pending_modal_opened — sets slotState.pendingModalKind so drainEventQueue
// pauses until a matching pending_modal_resolved arrives. The actual modal
// (tutor picker / trigger picker / death-target picker / etc.) is opened
// by the snapshot path's sync* handlers, which read the pending_* fields
// set on gameState. Our job here is ONLY to gate the queue so subsequent
// events (HP popups, turn banner, etc.) wait for user input.
//
// Payload shape varies by modal_kind. Currently-emitted kinds:
//   * tutor_select      — effect_resolver.py:_enter_pending_tutor
//   * trigger_pick      — react_stack.py:drain_pending_trigger_queue (2 sites)
//   * death_target_pick — action_resolver.py death-pick handler
//
// Not-yet-emitted (documented in plan 04b but engine doesn't emit them
// today — snapshot path's sync* functions handle them from state fields):
//   * conjure_deploy, revive_place, magic_cast_originator, post_move_attack
// These will gate the queue the same way once the engine emits for them.
function playPendingModalOpened(ev, done) {
    var payload = (ev && ev.payload) || {};
    slotState.pendingModalKind = payload.modal_kind || 'unknown';
    // Safety deadline: 5 minutes. If a pending_modal_resolved never arrives
    // (server crash, socket drop, user tab-close), clear the gate so the
    // queue doesn't deadlock. The actual modal will still be open on the
    // DOM side — the user can dismiss via snapshot path or reconnect.
    slotState.pendingModalDeadline = Date.now() + 5 * 60 * 1000;
    // Add a visual scrim hinting "queue paused" — purely informational
    // (pointer-events: none). Removed by playPendingModalResolved.
    try {
        if (!document.getElementById('event-queue-blocking-scrim')) {
            var scrim = document.createElement('div');
            scrim.id = 'event-queue-blocking-scrim';
            scrim.className = 'event-queue-blocking';
            _stageMount().appendChild(scrim);
        }
    } catch (e) { /* defensive */ }
    // Call done() immediately — the gate is set, drainEventQueue's early
    // return handles the actual wait.
    setTimeout(done, _evDurationOr(ev, 0));
}

// pending_modal_resolved — clear the gate and kick the drain. The modal
// DOM cleanup is owned by the snapshot path's sync* handlers (they read
// gameState.pending_* fields and close when null).
function playPendingModalResolved(ev, done) {
    slotState.pendingModalKind = null;
    slotState.pendingModalDeadline = 0;
    try {
        var scrim = document.getElementById('event-queue-blocking-scrim');
        if (scrim && scrim.parentNode) scrim.parentNode.removeChild(scrim);
    } catch (e) { /* defensive */ }
    // Timing audit (2026-07-06): the opponent-waiting toasts/banners used to
    // linger until the drain-end renderGame — tear them down AT this beat so
    // "Opponent is tutoring…" ends exactly when the pick resolves.
    try {
        var kind = (ev && ev.payload && ev.payload.modal_kind) || slotState.pendingModalKind || '';
        var toasts = document.querySelectorAll('.tutor-toast');
        toasts.forEach(function(t) {
            if (t.id === 'conn-lost-toast') return;
            t.classList.add('fade-out');
            setTimeout(function() { if (t.parentNode) t.remove(); }, 400);
        });
        if (kind === 'tutor_select' && typeof closeTutorModal === 'function') closeTutorModal();
        if (kind === 'trigger_pick' && typeof closeTriggerPickerModal === 'function') closeTriggerPickerModal();
    } catch (e) { /* defensive */ }
    setTimeout(done, _evDurationOr(ev, 0));
}

// fizzle — brief puff of smoke at the source tile (or screen center if no
// position). Used when an ON_DEATH / ON_START_OF_TURN / ON_END_OF_TURN
// trigger's target is invalidated at resolve time (spec §7.3). The engine
// pops the fizzled trigger without opening a react window, so this slot is
// the ONLY visible indication that "something was going to happen but
// didn't". A subtle 💨 glyph reads as "dissipated" without competing with
// the more-prominent trigger-blip glyphs.
//
// Payload: {trigger_kind, source_minion_id, source_card_numeric_id, reason}
function playFizzle(ev, done) {
    var payload = ev && ev.payload;
    // Timing overhaul (2026-07-08, F10b): a NEGATE-countered card gets a
    // brief "Countered!" toast — today countered spells resolve into silent
    // nothing. Old payloads carry no reason and keep the plain puff.
    var isNegated = !!(payload && payload.reason === 'negated');
    if (isNegated) {
        try {
            var counteredName = (payload.card_numeric_id != null
                && cardDefs && cardDefs[payload.card_numeric_id])
                ? cardDefs[payload.card_numeric_id].name : null;
            var negToast = document.createElement('div');
            negToast.className = 'tutor-toast fizzle-negated-toast';
            negToast.textContent = '🚫 ' + (counteredName
                ? (counteredName + ' — Countered!') : 'Countered!');
            _stageMount().appendChild(negToast);
            setTimeout(function() {
                negToast.classList.add('fade-out');
                setTimeout(function() { negToast.remove(); }, 600);
            }, 1200);
        } catch (e) { /* defensive — toast is purely visual */ }
    }
    try {
        var puff = document.createElement('div');
        puff.className = 'fizzle-puff';
        puff.textContent = '💨';
        // Anchor to the source minion's board tile if we can find it.
        // pending_trigger fizzles carry source_minion_id but NOT a
        // position, so we search gameState/sandboxState to resolve it.
        var stateRef = (typeof sandboxState !== 'undefined' && sandboxMode)
            ? sandboxState : gameState;
        var srcPos = null;
        if (payload && payload.source_minion_id != null && stateRef
            && stateRef.board) {
            var rows = stateRef.board;
            for (var r = 0; r < rows.length && srcPos == null; r++) {
                var row = rows[r] || [];
                for (var c = 0; c < row.length; c++) {
                    var cell = row[c];
                    if (cell && cell.instance_id === payload.source_minion_id) {
                        srcPos = [r, c];
                        break;
                    }
                }
            }
        }
        var tile = _evTileForPos(srcPos);
        if (tile) {
            var rect = tile.getBoundingClientRect();
            puff.style.left = (rect.left + rect.width / 2) + 'px';
            puff.style.top = (rect.top + rect.height / 2) + 'px';
        } else {
            // Source already dead / off board — center on the STAGE.
            var mountEl = _stageMount();
            if (mountEl !== document.body) {
                var mrRect = mountEl.getBoundingClientRect();
                var mrScale = mrRect.width / 844;
                puff.style.left = (mrRect.left + 522 * mrScale) + 'px';
                puff.style.top = (mrRect.top + mrRect.height / 2) + 'px';
            } else {
                puff.style.left = '50%';
                puff.style.top = '50%';
            }
        }
        document.body.appendChild(puff);
        setTimeout(function() {
            if (puff.parentNode) puff.parentNode.removeChild(puff);
        }, 400);
    } catch (e) { /* defensive — fizzle is purely visual */ }
    // Negated fizzles hold a touch longer so the Countered! toast registers.
    setTimeout(done, isNegated
        ? Math.max(_evDurationOr(ev, 350), 800)
        : _evDurationOr(ev, 350));
}

// game_over — show the game-over overlay. Reuses showGameOver() from
// onGameOver socket handler. The server's engine_events frame carries
// the final_state payload (stashed on window.__lastFinalState by
// onEngineEvents), so we synthesize the same data shape showGameOver
// expects from a socket 'game_over' event.
//
// Payload: {winner, reason}
//
// NOTE: in live PvP, the snapshot path's onGameOver socket handler also
// fires with the same winner. showGameOver is idempotent (it just sets
// overlay.style.display='flex'), so the dual-fire is harmless. In sandbox
// there is no onGameOver socket path, so this handler is the primary
// trigger for the overlay.
function playGameOver(ev, done) {
    if (_passOfferedBy != null) _setPassOffer(null);
    var payload = (ev && ev.payload) || {};
    try {
        // Timing audit (2026-07-06): prefer the full socket game_over
        // payload stashed by onGameOver while the queue was busy — it
        // carries reason/final_state and runs the complete teardown
        // (spell-stage reset, SFX) at THIS beat, after the lethal beats.
        if (window.__pendingGameOverData) {
            var pgo = window.__pendingGameOverData;
            window.__pendingGameOverData = null;
            if (typeof _applyGameOver === 'function') _applyGameOver(pgo);
        } else {
            showGameOver({
                winner: payload.winner,
                final_state: window.__lastFinalState || gameState,
            });
        }
    } catch (e) { /* defensive — overlay is purely visual */ }
    // Game over modal stays up until user dismisses — no queue pacing needed.
    setTimeout(done, _evDurationOr(ev, 0));
}

// ----- Turn-structure redesign handlers (2026-07) ---------------------
//
// Three new event families from the Rally/Decay turn redesign:
//   * handshake     — both players passed consecutively; at end of turn each
//                     gains +1 mana (or draws a card if mana is already full).
//   * overdraw_burn — a draw happened with a full hand (MAX_HAND_SIZE=10);
//                     the drawn card is REVEALED then sent to the Exhaust
//                     Pile instead of entering the hand. Applies to every
//                     draw path (turn-start, card effects, Handshake, tutor).
//   * fatigue       — the turn-start auto-draw found an empty deck; the
//                     player takes escalating damage (10/20/30...) instead
//                     of drawing. PASS is free and NEVER deals fatigue.
//
// The concrete payouts (mana_change / card_drawn / player_hp_change) arrive
// as their own events on the same frame and animate via their existing slot
// handlers — these handlers only render the headline beat.

// Extraction of a per-player Handshake reward from the engine payload.
// The engine emits {"outcomes": [{player_idx, reward}]} where reward is
// 'mana' | 'card_drawn' | 'card_burned' | 'none' (react_stack.py
// _resolve_handshake_payout). Legacy shapes accepted defensively.
// Returns the reward string or null when unknown.
function _handshakeRewardFor(payload, idx) {
    if (!payload) return null;
    var direct = payload['p' + idx + '_reward'] || payload['player' + idx + '_reward'];
    if (typeof direct === 'string') return direct;
    var r = payload.outcomes || payload.rewards;
    if (Array.isArray(r)) {
        for (var i = 0; i < r.length; i++) {
            var e = r[i];
            if (e && typeof e === 'object' && e.player_idx === idx) {
                return e.reward || e.kind || e.type || null;
            }
        }
        var entry = r[idx];
        if (typeof entry === 'string') return entry;
        if (entry && typeof entry === 'object') {
            return entry.reward || entry.kind || entry.type || null;
        }
    }
    return null;
}

// Player-facing text for a Handshake reward value.
function _handshakeRewardText(reward) {
    switch (reward) {
        case 'mana':        return '+1 mana';
        case 'card_drawn':
        case 'draw':        return 'draws a card (mana full)';
        case 'card_burned': return 'draws a card (mana full) — hand full, it is exhausted!';
        case 'none':        return 'nothing (mana full, deck empty)';
        default:            return '+1 mana';  // legacy payloads carry no detail
    }
}

// handshake — full-screen 🤝 banner naming both players' payout. The
// mana/draw payout events that follow animate the actual numbers.
// Payload (best-effort): per-player rewards, see _handshakeRewardFor.
// pass_declared: brief toast so a pass is actually announced (user
// 2026-07-08 - there was NO notification for passing at all). The lasting
// indicators (pod palm flag + tooltip banner) are set at the beat commit.
function playPassDeclared(ev, done) {
    var payload = (ev && ev.payload) || {};
    try {
        var mine = (myPlayerIdx != null && payload.player_idx === myPlayerIdx);
        var who = mine ? 'You' : (opponentName || 'Opponent');
        var toast = document.createElement('div');
        toast.className = 'tutor-toast pass-toast';
        toast.textContent = payload.streak === 1
            ? ('🫴 ' + who + (mine ? ' pass' : ' passes') + ' — Handshake offered')
            : ('🤝 ' + who + (mine ? ' pass' : ' passes') + ' — Handshake!');
        _stageMount().appendChild(toast);
        setTimeout(function() {
            toast.classList.add('fade-out');
            setTimeout(function() { toast.remove(); }, 600);
        }, 1400);
    } catch (e) { /* defensive */ }
    setTimeout(done, _evDurationOr(ev, 700));
}

function playHandshake(ev, done) {
    if (_passOfferedBy != null) _setPassOffer(null);
    var payload = (ev && ev.payload) || {};
    try {
        var ownIdx = sandboxMode ? 0 : (myPlayerIdx != null ? myPlayerIdx : 0);
        var nameFor = function(idx) {
            if (sandboxMode || isSpectator) return 'P' + (idx + 1);
            return idx === ownIdx ? 'You' : (opponentName || 'Opponent');
        };
        var lineFor = function(idx) {
            var reward = _handshakeRewardFor(payload, idx);
            return nameFor(idx) + ': ' + _handshakeRewardText(reward);
        };
        runNudge('nudge-handshake',
            '<div class="handshake-emoji">🤝</div>' +
            '<div class="handshake-title">HANDSHAKE!</div>' +
            '<div class="handshake-sub">' + lineFor(0) + ' &nbsp;·&nbsp; ' + lineFor(1) + '</div>',
            2200);
    } catch (e) { /* defensive — banner is purely visual */ }
    // Pace at the banner's own 2200ms choreography — deliberately NOT
    // _evDurationOr: a shorter wire duration would let the next event
    // (turn banner etc.) play over the still-visible handshake banner.
    setTimeout(done, 2200);
}

// overdraw_burn — the drawn card is revealed center-screen for a beat, then
// flies to the owner's Exhaust pile via the existing card_fly ghost
// primitive (playCardFlyAnimation). Payload: {player_idx, card_numeric_id}.
// Overdrawn cards are revealed to BOTH players, so card_numeric_id should
// always be present; if redaction strips it, fall back to a text blip.
function playOverdrawBurn(ev, done) {
    var payload = (ev && ev.payload) || {};
    var ownIdx = sandboxMode ? 0 : myPlayerIdx;
    var zone = (payload.player_idx === ownIdx) ? 'exhaust_own' : 'exhaust_opp';
    // Timing overhaul (2026-07-08, F10): a discard-cost burn is a PAID cost
    // of playing another card, not an overdraw — no 1900ms "HAND FULL"
    // center-reveal ceremony. Short hand→exhaust fly instead. Old payloads
    // carry no source and keep the full overdraw treatment.
    if (payload.source === 'discard_cost') {
        var dcSlot = null;
        try {
            var dcContainerId = sandboxMode
                ? ('sandbox-hand-p' + payload.player_idx)
                : ((payload.player_idx === myPlayerIdx) ? 'hand-container' : null);
            var dcContainer = dcContainerId && document.getElementById(dcContainerId);
            if (dcContainer && payload.card_numeric_id != null) {
                var dcMatches = dcContainer.querySelectorAll(
                    '.card-frame[data-numeric-id="' + payload.card_numeric_id + '"]');
                for (var di = 0; di < dcMatches.length; di++) {
                    if (dcMatches[di].style.visibility !== 'hidden') {
                        dcSlot = dcMatches[di];
                        break;
                    }
                }
            }
        } catch (e) { /* defensive */ }
        if (!dcSlot || payload.card_numeric_id == null) {
            setTimeout(done, 0);
            return;
        }
        var dcSettled = false;
        var dcSettle = function() {
            if (dcSettled) return;
            dcSettled = true;
            done();
        };
        try {
            var dcRect = dcSlot.getBoundingClientRect();
            dcSlot.style.visibility = 'hidden';
            enqueueAnimation({
                type: 'card_fly',
                fromRect: dcRect,
                toZone: zone,
                cardNumericId: payload.card_numeric_id,
                stateApplied: true,
                _fromEventQueue: true,
                onDone: dcSettle,
            });
        } catch (e) { dcSettle(); return; }
        setTimeout(dcSettle, 3000);
        return;
    }
    var def = (payload.card_numeric_id != null && cardDefs)
        ? cardDefs[payload.card_numeric_id] : null;
    if (!def) {
        try {
            // Element card backs (2026-07): if the redacted payload still
            // carries the element (designed leak — see view_filter), show a
            // tinted card back so the burn animation carries the tint.
            var burnEl = (payload.element != null) ? payload.element : payload.card_element;
            var burnTint = (burnEl != null && ELEMENT_MAP[burnEl]) ? ELEMENT_MAP[burnEl] : null;
            runNudge('nudge-overdraw-fallback',
                (burnTint
                    ? '<div class="overdraw-burn-back" style="--back-tint:' + burnTint.color + '" title="' + burnTint.name + '"></div>'
                    : '') +
                '<div class="overdraw-reveal-label">HAND FULL — CARD EXHAUSTED</div>',
                1200);
        } catch (e) { /* defensive */ }
        setTimeout(done, 1200);  // match the fallback nudge, ignore wire duration
        return;
    }
    var HOLD_MS = 900;    // reveal hold before the burn starts
    var BURN_MS = 1000;   // Hearthstone-style char-away sweep (css keyframes)
    try {
        var reveal = document.createElement('div');
        reveal.className = 'overdraw-reveal';
        reveal.innerHTML =
            '<div class="overdraw-reveal-card">' +
                renderCardFrame(def, {
                    context: 'hand',
                    numericId: payload.card_numeric_id,
                    interactive: false,
                    showReactDeploy: false,
                }) +
                '<div class="burn-fire-line"></div>' +
            '</div>' +
            '<div class="overdraw-reveal-label">HAND FULL — EXHAUSTED</div>';
        _stageMount().appendChild(reveal);
        playSfx('burn_tick');
        setTimeout(function() {
            // Hearthstone-style burn: a fire line sweeps down the card,
            // char-dissolving it top-to-bottom while embers drift up.
            var cardBox = reveal.querySelector('.overdraw-reveal-card');
            if (!cardBox) { if (reveal.parentNode) reveal.remove(); return; }
            cardBox.classList.add('overdraw-burning');
            playSfx('burn_tick');
            // Ember particles — spawned on the reveal (not the masked card)
            // so they survive the dissolve.
            for (var i = 0; i < 10; i++) {
                var em = document.createElement('div');
                em.className = 'burn-ember';
                em.style.left = (8 + Math.random() * 84) + '%';
                em.style.animationDelay = (Math.random() * 550) + 'ms';
                em.style.setProperty('--edx', (Math.random() * 40 - 20) + 'px');
                cardBox.appendChild(em);
            }
            setTimeout(function() {
                if (reveal.parentNode) reveal.remove();
            }, BURN_MS + 150);
        }, HOLD_MS);
    } catch (e) { /* defensive — worst case the pile count just ticks up */ }
    // Pace at the handler's own choreography (reveal hold + burn) —
    // deliberately NOT _evDurationOr: a shorter wire duration would advance
    // the queue mid-reveal.
    setTimeout(done, HOLD_MS + BURN_MS);
}

// fatigue — DEFENSIVE ALIAS ONLY. The engine emits fatigue as
// player_hp_change with payload.cause === "fatigue" (no dedicated event
// type exists in engine_events.py); the live-play nudge fires from
// playPlayerHpChange. This handler stays wired for the "fatigue" /
// "fatigue_damage" aliases in case a dedicated type is added later.
// Payload (hypothetical): {player_idx, damage, fatigue_count?}.
function playFatigueDamage(ev, done) {
    var payload = (ev && ev.payload) || {};
    var dmg = (typeof payload.damage === 'number') ? payload.damage
        : (typeof payload.amount === 'number') ? payload.amount : null;
    try {
        triggerFatigueNudge(dmg, payload.player_idx);
    } catch (e) { /* defensive — nudge is purely visual */ }
    setTimeout(done, _evDurationOr(ev, 1200));
}

// mana_change — timing overhaul (2026-07-08, F10a). A player's mana pool
// changed. State commit stays in commitEventToDom; this handler pulses the
// pod's mana value (mirrors the dm-pulse badge treatment — no pod popup)
// and paces ~300ms so coalesced same-frame mana beats read as distinct.
// Payload: {player_idx, prev, new, delta, cause?}.
function playManaChange(ev, done) {
    var payload = (ev && ev.payload) || {};
    try {
        if (typeof payload.player_idx === 'number') {
            var manaEl = null;
            if (sandboxMode) {
                manaEl = document.getElementById('sandbox-p' + payload.player_idx + '-mana');
            } else if (myPlayerIdx != null) {
                manaEl = document.getElementById(
                    payload.player_idx === myPlayerIdx ? 'self-mana' : 'opp-mana');
            }
            // Pulse the whole .pod-mana pill when present (reads better than
            // the bare number span); fall back to the number element.
            var pulseEl = manaEl && (manaEl.closest ? (manaEl.closest('.pod-mana') || manaEl) : manaEl);
            if (pulseEl) {
                pulseEl.classList.remove('mana-pulse');
                void pulseEl.offsetWidth;  // restart the CSS animation
                pulseEl.classList.add('mana-pulse');
                setTimeout(function() { pulseEl.classList.remove('mana-pulse'); }, 900);
            }
        }
    } catch (e) { /* defensive — pulse is purely visual */ }
    setTimeout(done, 300);
}

// dark_matter_change — Dark Matter pool redesign (2026-07). A player's
// PLAYER-LEVEL DM pool changed (grant_dark_matter resolution). Public info
// for both viewers. Payload: {player_idx, prev, new, delta, source}.
// The state commit happens in commitEventToDom (same pattern as
// mana_change); this slot handler renders the beat: pulse the avatar's DM
// badge + float a 🌑 delta popup off the avatar pod.
function playDarkMatterChange(ev, done) {
    var payload = (ev && ev.payload) || {};
    try {
        if (!sandboxMode && myPlayerIdx != null
                && typeof payload.player_idx === 'number') {
            var which = (payload.player_idx === myPlayerIdx) ? 'self' : 'opp';
            var badge = document.getElementById('avatar-' + which + '-dm');
            if (badge) {
                badge.classList.remove('dm-pulse');
                void badge.offsetWidth;  // restart the CSS animation
                badge.classList.add('dm-pulse');
                setTimeout(function() { badge.classList.remove('dm-pulse'); }, 900);
            }
            var delta = (typeof payload.delta === 'number') ? payload.delta
                : (typeof payload['new'] === 'number' && typeof payload.prev === 'number')
                    ? payload['new'] - payload.prev
                    : null;
            // Compliance audit 2026-07-06: Dark Matter never surfaces at
            // the pods — pod-anchored delta popup removed (the player
            // preview + game log carry the pool change).
        }
    } catch (e) { /* defensive — pulse/popup are purely visual */ }
    setTimeout(done, _evDurationOr(ev, 400));
}

// Debug hook (mirrors __animDebug). Plan 04b extends with spell-stage state.
if (typeof window !== 'undefined') {
    window.__eventQueueDebug = {
        get queue() { return eventQueue; },
        get running() { return eventRunning; },
        get lastSeenSeq() { return lastSeenSeq; },
        get slotState() { return slotState; },
        reset: resetEventQueue,
    };
}

function enqueueAnimation(job) {
    animQueue.push(job);
    runQueue();
}

function runQueue() {
    if (animRunning) return;
    if (animQueue.length === 0) return;
    var job = animQueue.shift();
    animRunning = true;
    // Phase 14.8 hardening: a synchronous throw inside any animation branch
    // used to latch animRunning=true FOREVER — every later enqueueAnimation
    // returned at the top guard and no visual ever played again for the
    // rest of the session (and every playMinionSummoned stalled the
    // eventQueue for its full safety cap). Mirror drainEventQueue's guard:
    // on throw, finish the job (state apply + onDone + recurse) so the
    // queue keeps flowing. The finished flag makes completion idempotent
    // in case a branch throws AFTER scheduling its own done callback.
    var jobFinished = false;
    function finishJob() {
        if (jobFinished) return;
        jobFinished = true;
        // Apply the buffered state frame AFTER the animation completes,
        // unless the branch already applied it (e.g. summon applies up-front
        // so the minion is visible during scale-in and sets job.stateApplied).
        if (!job.stateApplied) {
            try {
                applyStateFrame(job.stateAfter, job.legalActionsAfter);
            } catch (e) {
                console.error('[animQueue] applyStateFrame failed for type='
                    + (job && job.type), e);
            }
        }
        animRunning = false;
        // Per-job completion callback (Phase 14.8): the eventQueue slot
        // handlers (playMinionSummoned, playMinionMoved, etc.) need to
        // wait for the actual visual to finish before pacing forward,
        // otherwise downstream events (turn_flipped, phase_changed) play
        // their visuals while this job is still queued behind earlier
        // animations. Fire the callback BEFORE recursing so a chained
        // job onDone can re-enter without contention.
        if (typeof job.onDone === 'function') {
            try { job.onDone(); } catch (e) { /* defensive */ }
        }
        runQueue();
    }
    try {
        playAnimation(job, finishJob);
    } catch (err) {
        console.error('[animQueue] playAnimation threw for type='
            + (job && job.type), err);
        finishJob();
    }
}

function playAnimation(job, done) {
    // Phase 14.3 contract: branches call done() when their animation
    // finishes. Some branches (summon) apply state at the START of the
    // animation; others (move/attack, future waves) apply state at
    // different points. The default applyStateFrame call in runQueue is
    // suppressed by setting job.stateApplied = true inside the branch.
    switch (job && job.type) {
        case 'summon':
            playSummonAnimation(job, done);
            return;
        case 'attack':
            playAttackAnimation(job, done);
            return;
        case 'move':
            playMoveAnimation(job, done);
            return;
        case 'draw_own':
            playDrawOwnAnimation(job, done);
            return;
        case 'draw_opp':
            playDrawOppAnimation(job, done);
            return;
        case 'card_fly':
            playCardFlyAnimation(job, done);
            return;
        case 'hp_damage_popup':
            playHpDamagePopup(job, done);
            return;
        case 'sacrifice_transcend':
            playSacrificeTranscendAnimation(job, done);
            return;
        case 'noop':
        default:
            setTimeout(done, 0);
            return;
    }
}

