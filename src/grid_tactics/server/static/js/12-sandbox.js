// === SANDBOX-SECTION-START ===
// Phase 14.6 sandbox screen. All sandbox-related JS lives between
// SANDBOX-SECTION-START and SANDBOX-SECTION-END so plan 14.6-03 (and any
// future sandbox extension) can locate insertion points by grep, not by
// fragile line numbers.
//
// LAYOUT INVARIANT (D1): The sandbox is fixed dual-perspective god view.
// P1 hand mounts at #sandbox-hand-p0 (visually TOP), P2 hand mounts at
// #sandbox-hand-p1 (visually BOTTOM). Both render with godView:true. The
// sandbox NEVER calls filter_state_for_player or filter_state_for_spectator
// -- it renders the raw state from the server. There is NO view-toggle,
// NO flip button, NO perspective-swap. The plan 14.6-03 "Controlling:
// P1 / P2" button mutates state.active_player_idx server-side; it does
// NOT change which DOM mount renders which player's hand.

// ----- Global-swap strategy ------------------------------------------------
// The live game's renderers and click handlers read 5 module-level globals:
//   gameState, myPlayerIdx, legalActions, isSpectator, spectatorGodMode
// (plus animatingTiles, which we reset to {} on activation).
//
// Refactoring 50+ read sites in onHandCardClick / onBoardCellClick /
// submitAction is infeasible. Instead, while the sandbox screen is visible,
// the sandbox OWNS those globals. On activation we snapshot them; on
// deactivation we restore them. The opts-refactored renderBoard/renderHand
// take the sandbox mount targets via opts, so the sandbox renders into
// #sandbox-board / #sandbox-hand-p0 / #sandbox-hand-p1 even while the
// globals are pointing at the sandbox state.

function sandboxActivate() {
    sandboxMode = true;
    // Snapshot the 5 globals + animatingTiles so we can restore on exit
    _sandboxPreSnapshot = {
        gameState: gameState,
        myPlayerIdx: myPlayerIdx,
        legalActions: legalActions,
        isSpectator: isSpectator,
        spectatorGodMode: spectatorGodMode,
        animatingTiles: animatingTiles,
    };
    // While in sandbox: god view, no spectator filter, no animations queued
    // (they'd target the live #game-board which isn't visible).
    isSpectator = false;
    spectatorGodMode = true;
    animatingTiles = {};
    // Phase 14.8-04a: a fresh sandbox session restarts the engine event
    // seq counter at 0 (server SandboxSession._next_event_seq init / reset).
    if (typeof resetEventQueue === 'function') resetEventQueue();
    // gameState / myPlayerIdx / legalActions get assigned by the
    // sandbox_state handler when payload arrives.
    initSandboxScreen();
}

function sandboxDeactivate() {
    sandboxMode = false;
    if (_sandboxPreSnapshot) {
        gameState = _sandboxPreSnapshot.gameState;
        myPlayerIdx = _sandboxPreSnapshot.myPlayerIdx;
        legalActions = _sandboxPreSnapshot.legalActions;
        isSpectator = _sandboxPreSnapshot.isSpectator;
        spectatorGodMode = _sandboxPreSnapshot.spectatorGodMode;
        animatingTiles = _sandboxPreSnapshot.animatingTiles;
        _sandboxPreSnapshot = null;
    }
    // Phase 14.8-04a: clear any deferred events so they don't replay against
    // the live PvP board on next activation.
    if (typeof resetEventQueue === 'function') resetEventQueue();
}

// ============================================================
// Tests screen — structured UAT survey. Rides on top of the
// sandbox screen; each test loads a scenario server-side, the
// user performs the steps, then submits Pass/Fail/Skip. Results
// append to data/tests/results.jsonl on the server.
// ============================================================
var _testsState = {
    active: false,
    list: [],       // [{id, title}, ...]
    index: 0,       // index into list of the test currently shown
    currentId: null,
    results: [],    // local tally; server has the authoritative log
    wiredHandlers: false,
    wiredButtons: false,
};

function testsActivate() {
    if (_testsState.active) return;
    _testsState.active = true;
    _testsState.index = 0;
    _testsState.results = [];
    _wireTestsOnce();
    var ov = document.getElementById('tests-overlay');
    if (ov) ov.hidden = false;
    _setTestsTitle('Loading tests…');
    _setTestsInstructions('');
    _setTestsExpected('');
    _setTestsProgress('Test 0 / 0');
    _hideTestsSummary();
    if (socket && socket.connected) {
        socket.emit('tests_list');
    }
}

function testsExit() {
    if (!_testsState.active) return;
    _testsState.active = false;
    var ov = document.getElementById('tests-overlay');
    if (ov) ov.hidden = true;
}

function _wireTestsOnce() {
    if (!_testsState.wiredButtons) {
        _testsState.wiredButtons = true;
        var pass = document.getElementById('tests-btn-pass');
        var fail = document.getElementById('tests-btn-fail');
        var skip = document.getElementById('tests-btn-skip');
        var reset = document.getElementById('tests-btn-reset');
        var exitBtn = document.getElementById('tests-exit');
        if (pass) pass.addEventListener('click', function() { _submitTestResult('pass'); });
        if (fail) fail.addEventListener('click', function() { _submitTestResult('fail'); });
        if (skip) skip.addEventListener('click', function() { _submitTestResult('skip'); });
        if (reset) reset.addEventListener('click', function() {
            // Re-run the current test's setup without consuming the slot —
            // lets the user retry after mis-clicking.
            if (_testsState.currentId) {
                socket.emit('tests_load', { id: _testsState.currentId });
            } else if (_testsState.list.length > 0) {
                _loadCurrentTest();
            }
        });
        if (exitBtn) exitBtn.addEventListener('click', function() { showScreen('screen-sandbox'); });
        var minBtn = document.getElementById('tests-minimize');
        if (minBtn) minBtn.addEventListener('click', function() {
            var ov = document.getElementById('tests-overlay');
            if (!ov) return;
            var mini = ov.classList.toggle('is-minimized');
            minBtn.textContent = mini ? '▢' : '▁';
            minBtn.title = mini ? 'Expand' : 'Minimize';
        });
        // Phase 14.8-05c: TOC button. Toggles the jump-to-test panel.
        var tocBtn = document.getElementById('tests-toc');
        if (tocBtn) tocBtn.addEventListener('click', function() {
            var panel = document.getElementById('tests-toc-panel');
            if (!panel) return;
            if (panel.hidden) {
                _renderTestsToc();
                panel.hidden = false;
            } else {
                panel.hidden = true;
            }
        });
        var tocClose = document.getElementById('tests-toc-close');
        if (tocClose) tocClose.addEventListener('click', function() {
            var panel = document.getElementById('tests-toc-panel');
            if (panel) panel.hidden = true;
        });
    }
    if (!_testsState.wiredHandlers && socket) {
        _testsState.wiredHandlers = true;
        socket.on('tests_list_result', function(data) {
            _testsState.list = (data && data.tests) || [];
            _testsState.index = 0;
            if (_testsState.list.length === 0) {
                _setTestsTitle('No tests available');
                _setTestsInstructions('The server test manifest is empty.');
                _setTestsExpected('');
                return;
            }
            _loadCurrentTest();
        });
        socket.on('tests_scenario_loaded', function(data) {
            if (!data) return;
            _testsState.currentId = data.id;
            _setTestsProgress('Test ' + (_testsState.index + 1) + ' / ' + _testsState.list.length);
            _setTestsTitle(data.title || data.id);
            _setTestsInstructions(data.instructions || '');
            _setTestsExpected(data.expected || '');
            var ta = document.getElementById('tests-comment');
            if (ta) ta.value = '';
            // Client hints — picks which animation variant a test wants.
            var hints = data.client_hints || {};
            window.__sacrificeVariant = hints.sacrifice_animation || null;
            // Phase 14.8-05c: reset the eventQueue dedup cursor. The server
            // resets SandboxSession._next_event_seq=0 when a fresh scenario
            // loads (reset, skip, or TOC jump). Without flushing the
            // client's lastSeenSeq, the new scenario's events arrive as
            // seq=0..N and get rejected as "out-of-order" against the
            // stale cursor (seq=19 etc from the previous run). Symptom
            // observed: cards played but spell stage doesn't update,
            // chains appear to "trigger twice" (residual half-applied
            // state from the partial first pass overlaps with the new).
            if (typeof resetEventQueue === 'function') resetEventQueue();
        });
        socket.on('tests_result_saved', function() {
            // Move to next test (or show summary when done).
            _testsState.index += 1;
            if (_testsState.index >= _testsState.list.length) {
                _renderTestsSummary();
            } else {
                _loadCurrentTest();
            }
        });
    }
}

function _loadCurrentTest() {
    var t = _testsState.list[_testsState.index];
    if (!t) return;
    _setTestsProgress('Loading ' + (_testsState.index + 1) + ' / ' + _testsState.list.length + '…');
    _setTestsTitle(t.title || t.id);
    _setTestsInstructions('');
    _setTestsExpected('');
    socket.emit('tests_load', { id: t.id });
}

// Phase 14.8-05c: render the table-of-contents jump panel. Each row is
// a clickable list item that loads its scenario directly. The currently-
// active test gets a highlight so the user can see where they are in
// the sequence.
function _renderTestsToc() {
    var list = document.getElementById('tests-toc-list');
    if (!list) return;
    list.innerHTML = '';
    _testsState.list.forEach(function(t, i) {
        var li = document.createElement('li');
        li.className = 'tests-toc-item';
        if (i === _testsState.index) li.classList.add('is-current');
        li.textContent = (i + 1) + '. ' + (t.title || t.id);
        li.addEventListener('click', function() {
            _testsState.index = i;
            _testsState.currentId = null;  // allow re-submit on the new test
            _loadCurrentTest();
            var panel = document.getElementById('tests-toc-panel');
            if (panel) panel.hidden = true;
        });
        list.appendChild(li);
    });
    if (_testsState.list.length === 0) {
        var empty = document.createElement('li');
        empty.className = 'tests-toc-empty';
        empty.textContent = 'No tests loaded.';
        list.appendChild(empty);
    }
}

function _submitTestResult(result) {
    if (!_testsState.currentId) return;
    var ta = document.getElementById('tests-comment');
    var comment = ta ? ta.value : '';
    _testsState.results.push({ id: _testsState.currentId, result: result, comment: comment });
    socket.emit('tests_submit_result', {
        id: _testsState.currentId,
        result: result,
        comment: comment,
    });
    _testsState.currentId = null;  // prevent double-submit until next loads
}

function _renderTestsSummary() {
    var pass = 0, fail = 0, skip = 0;
    for (var i = 0; i < _testsState.results.length; i++) {
        var r = _testsState.results[i].result;
        if (r === 'pass') pass++;
        else if (r === 'fail') fail++;
        else if (r === 'skip') skip++;
    }
    _setTestsTitle('Tests complete');
    _setTestsInstructions('');
    _setTestsExpected('');
    _setTestsProgress(_testsState.list.length + ' / ' + _testsState.list.length);
    var summary = document.getElementById('tests-summary');
    if (summary) {
        summary.hidden = false;
        summary.innerHTML =
            '<strong>Summary:</strong> ' +
            '<span style="color:var(--green)">' + pass + ' pass</span> · ' +
            '<span style="color:var(--red)">' + fail + ' fail</span> · ' +
            '<span style="color:var(--muted)">' + skip + ' skip</span>' +
            '<br><span style="color:var(--muted);font-size:0.9em">Results logged to data/tests/results.jsonl on the server.</span>';
    }
}

function _setTestsProgress(s) { var el = document.getElementById('tests-progress'); if (el) el.textContent = s; }
function _setTestsTitle(s) { var el = document.getElementById('tests-title'); if (el) el.textContent = s; }
function _setTestsInstructions(s) { var el = document.getElementById('tests-instructions'); if (el) el.textContent = s; }
function _setTestsExpected(s) { var el = document.getElementById('tests-expected'); if (el) el.textContent = s; }
function _hideTestsSummary() { var el = document.getElementById('tests-summary'); if (el) { el.hidden = true; el.innerHTML = ''; } }

function initSandboxScreen() {
    if (!socket || !socket.connected) {
        console.warn('[sandbox] socket not connected yet');
        return;
    }
    setupSandboxToolbar();
    _wireSandboxPileButtons();
    // Try restore from localStorage; fall back to a fresh sandbox.
    // Note: sandbox_load auto-creates the session server-side if it doesn't
    // exist (see events.py:handle_sandbox_load) and also emits sandbox_card_defs
    // so the renderers can resolve numeric ids.
    var restored = false;
    try {
        var raw = localStorage.getItem(SANDBOX_AUTOSAVE_KEY);
        if (raw) {
            var payload = JSON.parse(raw);
            socket.emit('sandbox_load', { payload: payload });
            restored = true;
        }
    } catch (e) { /* corrupt -- just create fresh */ }
    if (!restored) {
        socket.emit('sandbox_create');
    }
    // Refresh server slot list every time the screen activates
    socket.emit('sandbox_list_slots');
}

function setupSandboxSocketHandlers() {
    if (!socket) return;

    socket.on('sandbox_card_defs', function(data) {
        sandboxCardDefs = (data && data.card_defs) || {};
        // Mirror into allCardDefs only if it isn't already populated by the live game,
        // so the existing renderers (which read allCardDefs/cardDefs) work inside the sandbox.
        if (!allCardDefs) {
            allCardDefs = sandboxCardDefs;
        }
        // cardDefs is the primary render-time lookup -- mirror into it too
        // (additively, so we don't stomp existing entries) so renderBoardMinion
        // / renderHandCard can resolve numeric ids inside the sandbox.
        if (cardDefs && typeof cardDefs === 'object') {
            for (var k in sandboxCardDefs) {
                if (!cardDefs[k]) cardDefs[k] = sandboxCardDefs[k];
            }
        } else {
            cardDefs = sandboxCardDefs;
        }
    });

    // === SANDBOX-STATE-HANDLER-START ===
    // Phase 14.8-04b: sandbox_state is now a pure snapshot commit — all
    // pacing / deferral / per-frame visuals that used to live in the
    // old sandbox frame queue + drainer + applier trio (Phase 14.7-09
    // paladin-heal fix) have been migrated to the unified eventQueue.
    // The engine emits a stream of EngineEvents alongside each
    // sandbox_state frame; each event's own slot handler owns its
    // animation + wall-clock pacing via animation_duration_ms.
    //
    // This handler's ONLY job is to commit the snapshot to sandboxState so
    // the renderers have something to draw. It's retained for reconnect /
    // initial-join / error-recovery parity with live PvP's state_update
    // — plan 14.8-05 deletes both once the eventQueue's commitEventToDom
    // hook covers every DOM mutation the snapshot path used to handle.
    socket.on('sandbox_state', function(payload) {
        if (!payload) return;
        sandboxState = payload.state;
        sandboxLegalActions = payload.legal_actions || [];
        sandboxActiveViewIdx = payload.active_view_idx || 0;
        sandboxUndoDepth = payload.undo_depth || 0;
        sandboxRedoDepth = payload.redo_depth || 0;
        if (sandboxMode) {
            gameState = sandboxState;
            myPlayerIdx = 0;
            legalActions = sandboxLegalActions;
        }
        // Plan 14.6-03 autosave + toolbar state sync (retained — the
        // eventQueue doesn't own these side-effects).
        try {
            localStorage.setItem(SANDBOX_AUTOSAVE_KEY, JSON.stringify({
                state: sandboxState,
                active_view_idx: sandboxActiveViewIdx,
            }));
        } catch (e) { /* quota exceeded — ignore */ }
        if (typeof renderSandboxToolbarState === 'function') renderSandboxToolbarState();
        renderSandbox();
    });
    // === SANDBOX-STATE-HANDLER-END ===

    socket.on('sandbox_save_blob', function(data) {
        // Plan 14.6-03: download the blob as a JSON file
        var payload = data && data.payload;
        if (!payload) return;
        var json = JSON.stringify(payload, null, 2);
        var blob = new Blob([json], { type: 'application/json' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        var ts = new Date().toISOString().replace(/[:.]/g, '-');
        a.download = 'sandbox-' + ts + '.json';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

    // Phase 14.6-03: Server-side save slot events
    socket.on('sandbox_slot_list', function(data) {
        if (typeof renderSandboxSlotList === 'function') {
            renderSandboxSlotList((data && data.slots) || []);
        }
    });
    socket.on('sandbox_slot_saved', function(data) {
        var input = document.getElementById('sandbox-slot-name');
        if (input && data && input.value === data.slot_name) input.value = '';
    });
    socket.on('sandbox_slot_deleted', function(_data) {
        // No-op; the slot list refresh handles UI update via sandbox_slot_list
    });
}

function renderSandbox() {
    if (!sandboxState) return;
    // renderActionBar's slot lookup (#hand-action-bar) is a no-op in
    // sandbox HTML, but it ALSO drives the floating Skip React button
    // visibility and the mode-aware auto-skip — both of which we want
    // in sandbox too. Calling it here keeps that logic in one place.
    if (typeof renderActionBar === 'function') {
        try { renderActionBar(); } catch (e) { /* defensive */ }
    }

    // Renderer reuse contract: call the SAME renderBoard / renderHand,
    // passing sandbox mount targets via opts. The sandbox state is RAW
    // god view from the server -- we never call filter_state_for_player
    // or filter_state_for_spectator. Per spec D1: fixed dual-perspective,
    // no flip. HTML places P2 hand at TOP and P1 hand at BOTTOM; the
    // board orientation is locked to match (P2 back row at top, P1 back
    // row at bottom) regardless of which player is currently active.

    var boardMount = document.getElementById('sandbox-board');
    var handP0Mount = document.getElementById('sandbox-hand-p0');  // P1 hand, visual BOTTOM
    var handP1Mount = document.getElementById('sandbox-hand-p1');  // P2 hand, visual TOP

    // Fixed perspective: perspectiveIdx=0 → rowOrder=[4,3,2,1,0], so row 0
    // (P1 back row) renders at bottom near P1's hand, row 4 (P2 back row)
    // renders at top near P2's hand. Do NOT key this off sandboxActiveViewIdx
    // — that would flip the board every time the active player toggles.
    var SANDBOX_PERSPECTIVE = 0;

    if (boardMount && typeof renderBoard === 'function') {
        renderBoard({
            mount: boardMount,
            state: sandboxState,
            perspectiveIdx: SANDBOX_PERSPECTIVE,
            legalActions: sandboxLegalActions,
        });
    }
    if (handP0Mount && typeof renderHand === 'function') {
        renderHand({
            mount: handP0Mount,
            state: sandboxState,
            ownerIdx: 0,
            godView: true,
            legalActions: sandboxLegalActions,
        });
    }
    if (handP1Mount && typeof renderHand === 'function') {
        renderHand({
            mount: handP1Mount,
            state: sandboxState,
            ownerIdx: 1,
            godView: true,
            legalActions: sandboxLegalActions,
        });
    }
    renderSandboxStats();
    // Pending-state modals (tutor/death/revive/post-move-attack) — sandbox
    // reuses the live-game handlers so modal banners + valid-target cell
    // highlights behave the same as a real duel.
    if (typeof syncPendingPostMoveAttackUI === 'function') syncPendingPostMoveAttackUI();
    if (typeof syncPendingTutorUI === 'function') syncPendingTutorUI();
    if (typeof syncPendingConjureDeployUI === 'function') syncPendingConjureDeployUI();
    if (typeof syncPendingDeathTargetUI === 'function') syncPendingDeathTargetUI();
    if (typeof syncPendingReviveUI === 'function') syncPendingReviveUI();
    if (typeof syncPendingTriggerPickerUI === 'function') syncPendingTriggerPickerUI();
    if (typeof highlightBoard === 'function') highlightBoard();
}

function renderSandboxStats() {
    // Phase 14.6 (redesign): now populates the live-game-style info bars
    // (opp-bar for P2 on top, self-bar for P1 on bottom) that live inside
    // #screen-sandbox, plus the room-bar header (active player / phase /
    // turn number). The old #sandbox-stats container has been removed.
    if (!sandboxState || !sandboxState.players) return;
    var p0 = sandboxState.players[0];
    var p1 = sandboxState.players[1];
    if (!p0 || !p1) return;

    function setText(id, val) {
        var el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    // Player 1 info bar (bottom)
    // Mana is a banking pool -- single number, not X/Y (matches duel screen).
    setText('sandbox-p0-hp', p0.hp);
    setText('sandbox-p0-mana', p0.current_mana);
    if (typeof _renderActionBank === 'function') {
        _renderActionBank('sandbox-p0-action-bank', p0);
    }
    setText('sandbox-p0-handcount', p0.hand ? p0.hand.length : 0);
    setText('sandbox-p0-deck', p0.deck ? p0.deck.length : 0);
    setText('sandbox-p0-deck-pile', p0.deck ? p0.deck.length : 0);
    setText('sandbox-p0-grave', p0.grave ? p0.grave.length : 0);
    setText('sandbox-p0-exhaust', p0.exhaust ? p0.exhaust.length : 0);

    // Player 2 info bar (top)
    setText('sandbox-p1-hp', p1.hp);
    setText('sandbox-p1-mana', p1.current_mana);
    if (typeof _renderActionBank === 'function') {
        _renderActionBank('sandbox-p1-action-bank', p1);
    }
    setText('sandbox-p1-handcount', p1.hand ? p1.hand.length : 0);
    setText('sandbox-p1-deck', p1.deck ? p1.deck.length : 0);
    setText('sandbox-p1-deck-pile', p1.deck ? p1.deck.length : 0);
    setText('sandbox-p1-grave', p1.grave ? p1.grave.length : 0);
    setText('sandbox-p1-exhaust', p1.exhaust ? p1.exhaust.length : 0);

    // Room bar
    setText('sandbox-active-label', 'Active: P' + ((sandboxState.active_player_idx || 0) + 1));
    var phaseEl = document.getElementById('sandbox-phase-badge');
    if (phaseEl) {
        _setPhaseLeds(phaseEl, sandboxState.phase, sandboxState.react_return_phase);
    }
    setText('sandbox-turn-number', 'Turn ' + sandboxState.turn_number);
}

// Wire the static .sandbox-pile-btn buttons once at activation time.
// (Previously rebuilt on every renderSandboxStats -- now the buttons are
// static in the HTML info bars, so we attach listeners exactly once.)
function _wireSandboxPileButtons() {
    document.querySelectorAll('#screen-sandbox .sandbox-pile-btn').forEach(function(btn) {
        if (btn.dataset.sandboxPileBound === '1') return;
        btn.dataset.sandboxPileBound = '1';
        btn.addEventListener('click', function() {
            if (!sandboxState) return;
            var pileKey = btn.dataset.pile;
            var playerIdx = parseInt(btn.dataset.player, 10);
            var player = sandboxState.players[playerIdx];
            if (!player) return;
            var ids;
            var title;
            if (pileKey === 'graveyard') {
                ids = player.grave || [];
                title = 'P' + (playerIdx + 1) + ' Grave';
            } else if (pileKey === 'exhaust') {
                ids = player.exhaust || [];
                title = 'P' + (playerIdx + 1) + ' Exhaust';
            } else {
                ids = player.deck || [];
                title = 'P' + (playerIdx + 1) + ' Deck';
            }
            showPileModal(title, ids, { pileType: pileKey, playerIdx: playerIdx });
        });
    });
}

// ---------------------------------------------------------------------------
// Phase 14.6-03: Interactive toolbar wiring
// ---------------------------------------------------------------------------

function setupSandboxToolbar() {
    if (_sandboxToolbarBound) return;
    _sandboxToolbarBound = true;

    // ---- A1. Card search + zone-aware add (DEV-02) ----
    var searchInput = document.getElementById('sandbox-search');
    var resultsBox = document.getElementById('sandbox-search-results');
    if (searchInput && resultsBox) {
        searchInput.addEventListener('input', function() {
            var q = searchInput.value.trim().toLowerCase();
            if (!q) { resultsBox.hidden = true; resultsBox.innerHTML = ''; return; }
            if (!sandboxCardDefs) return;
            var matches = [];
            var keys = Object.keys(sandboxCardDefs);
            for (var i = 0; i < keys.length; i++) {
                var nidStr = keys[i];
                var def = sandboxCardDefs[nidStr];
                if (def && def.name && def.name.toLowerCase().indexOf(q) !== -1) {
                    matches.push({ nid: parseInt(nidStr, 10), def: def });
                    if (matches.length >= 30) break;
                }
            }
            resultsBox.innerHTML = matches.map(function(m) {
                var cost = (m.def.mana_cost != null) ? m.def.mana_cost : '-';
                return '<div class="sandbox-search-result" data-nid="' + m.nid + '">' +
                       '<span class="sandbox-search-result-name">' + escapeHtml(m.def.name) + '</span>' +
                       '<span class="sandbox-search-result-meta">cost ' + cost + '</span>' +
                       '</div>';
            }).join('');
            resultsBox.hidden = matches.length === 0;
        });
        resultsBox.addEventListener('click', function(e) {
            var row = e.target.closest('.sandbox-search-result');
            if (!row) return;
            var nid = parseInt(row.dataset.nid, 10);
            // Add to currently selected zone immediately
            socket.emit('sandbox_add_card_to_zone', {
                player_idx: sandboxAddTargetIdx,
                card_numeric_id: nid,
                zone: sandboxAddZone,
            });
            // Also stage for optional board click-to-place
            sandboxStageCard(nid);
            // Dismiss dropdown + clear search
            resultsBox.hidden = true;
            resultsBox.innerHTML = '';
            searchInput.value = '';
        });
        document.addEventListener('click', function(e) {
            if (!e.target.closest('.sandbox-search-wrap')) resultsBox.hidden = true;
        });
    }

    // ---- A2. Target toggle (which player to add to) ----
    document.querySelectorAll('.sandbox-target-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            sandboxAddTargetIdx = parseInt(btn.dataset.target, 10);
            document.querySelectorAll('.sandbox-target-btn').forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
        });
    });

    // ---- A3. Zone selector (button row + hidden select sync) ----
    var zoneSelect = document.getElementById('sandbox-zone-select');
    if (zoneSelect) {
        zoneSelect.addEventListener('change', function() {
            sandboxAddZone = zoneSelect.value;
        });
    }
    document.querySelectorAll('.sandbox-zone-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            sandboxAddZone = btn.dataset.zone;
            if (zoneSelect) zoneSelect.value = sandboxAddZone;
            document.querySelectorAll('.sandbox-zone-btn').forEach(function(b) {
                b.classList.toggle('active', b === btn);
            });
        });
    });

    // ---- A4. Control toggle (set active_player_idx server-side; layout does NOT change) ----
    document.querySelectorAll('.sandbox-control-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var idx = parseInt(btn.dataset.control, 10);
            socket.emit('sandbox_set_active_player', { player_idx: idx });
        });
    });

    // ---- A5. Undo / Redo / Reset ----
    var undoBtn = document.getElementById('sandbox-undo-btn');
    if (undoBtn) undoBtn.addEventListener('click', function() { socket.emit('sandbox_undo'); });
    var redoBtn = document.getElementById('sandbox-redo-btn');
    if (redoBtn) redoBtn.addEventListener('click', function() { socket.emit('sandbox_redo'); });
    var resetBtn = document.getElementById('sandbox-reset-btn');
    if (resetBtn) resetBtn.addEventListener('click', function() {
        if (confirm('Reset sandbox to empty? This will clear undo history.')) {
            // Phase 14.8-04a: server's SandboxSession._next_event_seq resets
            // to 0 on reset(); match that client-side.
            if (typeof resetEventQueue === 'function') resetEventQueue();
            socket.emit('sandbox_reset');
        }
    });

    // ---- A6. Save / Load (client-side JSON file) ----
    var saveBtn = document.getElementById('sandbox-save-btn');
    if (saveBtn) saveBtn.addEventListener('click', function() { socket.emit('sandbox_save'); });
    var loadBtn = document.getElementById('sandbox-load-btn');
    var fileInput = document.getElementById('sandbox-load-file');
    if (loadBtn && fileInput) {
        loadBtn.addEventListener('click', function() { fileInput.click(); });
        fileInput.addEventListener('change', function(e) {
            var file = e.target.files[0];
            if (!file) return;
            var reader = new FileReader();
            reader.onload = function(ev) {
                try {
                    var payload = JSON.parse(ev.target.result);
                    // Phase 14.8-04a: server's load_dict() resets
                    // _next_event_seq to 0; match client-side.
                    if (typeof resetEventQueue === 'function') resetEventQueue();
                    socket.emit('sandbox_load', { payload: payload });
                } catch (err) {
                    alert('Invalid JSON file: ' + err.message);
                }
                fileInput.value = '';
            };
            reader.readAsText(file);
        });
    }

    // ---- A7. Share code (TextEncoder/TextDecoder -- NEVER escape/unescape) ----
    var shareBtn = document.getElementById('sandbox-share-btn');
    if (shareBtn) shareBtn.addEventListener('click', function() {
        if (!sandboxState) return;
        var payload = { state: sandboxState, active_view_idx: sandboxActiveViewIdx };
        var code = sandboxEncodeShareCode(payload);
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(code).then(function() {
                alert('Sandbox code copied to clipboard (' + code.length + ' chars)');
            }, function() {
                window.prompt('Copy this sandbox code:', code);
            });
        } else {
            window.prompt('Copy this sandbox code:', code);
        }
    });
    var pasteBtn = document.getElementById('sandbox-paste-btn');
    if (pasteBtn) pasteBtn.addEventListener('click', function() {
        var code = window.prompt('Paste sandbox code:');
        if (!code) return;
        try {
            var payload = sandboxDecodeShareCode(code.trim());
            // Phase 14.8-04a: matches server's load_dict() seq reset.
            if (typeof resetEventQueue === 'function') resetEventQueue();
            socket.emit('sandbox_load', { payload: payload });
        } catch (err) {
            alert('Invalid sandbox code: ' + err.message);
        }
    });

    // ---- B. Cheat inputs (DEV-06) --------------------------------------
    // Emit on blur OR Enter -- NEVER on every keystroke (would spam the
    // server and feel laggy). The server applies the value with NO
    // validation -- full cheat mode.
    document.querySelectorAll('.sandbox-cheat-input').forEach(function(input) {
        function commit() {
            var playerIdx = parseInt(input.dataset.player, 10);
            var field = input.dataset.field;
            var raw = input.value.trim();
            if (raw === '') return;
            var value = parseInt(raw, 10);
            if (Number.isNaN(value)) return;
            socket.emit('sandbox_set_player_field', {
                player_idx: playerIdx,
                field: field,
                value: value,
            });
        }
        input.addEventListener('blur', commit);
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                input.blur();  // triggers commit
            }
        });
    });

    // ---- C. Deck import (DEV-03) ---------------------------------------
    // Reuses the existing deck-builder localStorage helper loadDeckSlots()
    // which returns [{name, cards: {numericId: count}}, ...]
    var importDeckBtn = document.getElementById('sandbox-import-deck-btn');
    if (importDeckBtn) importDeckBtn.addEventListener('click', function() {
        var slots = (typeof loadDeckSlots === 'function') ? loadDeckSlots() : [];
        if (!slots.length) {
            alert('No saved decks found. Build one in the Deck Builder first.');
            return;
        }
        var lines = slots.map(function(s, i) {
            var total = (typeof getDeckTotal === 'function') ? getDeckTotal(s.cards) : '?';
            return i + ': ' + s.name + ' (' + total + ' cards)';
        });
        var choiceStr = window.prompt('Pick a deck to import:\n' + lines.join('\n') + '\n\nEnter index:');
        if (choiceStr == null) return;
        var choice = parseInt(choiceStr, 10);
        if (Number.isNaN(choice) || choice < 0 || choice >= slots.length) {
            alert('Invalid choice');
            return;
        }
        var targetStr = window.prompt('Import to which player? Enter 1 or 2:');
        if (targetStr == null) return;
        var targetIdx = parseInt(targetStr, 10) - 1;
        if (targetIdx !== 0 && targetIdx !== 1) {
            alert('Player must be 1 or 2');
            return;
        }
        var deckMap = slots[choice].cards || {};
        var flat = [];
        Object.keys(deckMap).forEach(function(nidStr) {
            var nid = parseInt(nidStr, 10);
            var count = deckMap[nidStr];
            for (var k = 0; k < count; k++) flat.push(nid);
        });
        socket.emit('sandbox_import_deck', {
            player_idx: targetIdx,
            deck_card_ids: flat,
        });
    });

    // ---- D. Server save slots (DEV-08) ---------------------------------
    var slotSaveBtn = document.getElementById('sandbox-slot-save-btn');
    if (slotSaveBtn) slotSaveBtn.addEventListener('click', function() {
        var input = document.getElementById('sandbox-slot-name');
        var name = (input && input.value || '').trim();
        if (!name) { alert('Enter a slot name'); return; }
        if (!/^[a-zA-Z0-9_-]{1,64}$/.test(name)) {
            alert('Slot name must be 1-64 chars of letters, digits, underscore, or dash.');
            return;
        }
        socket.emit('sandbox_save_slot', { slot_name: name });
    });
    var slotRefreshBtn = document.getElementById('sandbox-slot-refresh-btn');
    if (slotRefreshBtn) slotRefreshBtn.addEventListener('click', function() {
        socket.emit('sandbox_list_slots');
    });
}

// ---- E. Move-card popover (DEV-03) ----------------------------------------
// Called from showPileModal (in sandbox mode) and from renderHand (when
// sandboxMode is true). Opens a small zone-picker popover anchored to the
// clicked button; emits sandbox_move_card.
var SANDBOX_ALL_ZONES = [
    { value: 'hand',        label: 'Hand' },
    { value: 'deck_top',    label: 'Deck top' },
    { value: 'deck_bottom', label: 'Deck bottom' },
    { value: 'graveyard',   label: 'Graveyard' },
    { value: 'exhaust',     label: 'Exhaust' },
];

function openSandboxMovePopover(anchorEl, playerIdx, cardNumericId, srcZone) {
    document.querySelectorAll('.sandbox-move-popover').forEach(function(el) { el.remove(); });
    var pop = document.createElement('div');
    pop.className = 'sandbox-move-popover';
    SANDBOX_ALL_ZONES.forEach(function(z) {
        if (z.value === srcZone) return;
        var btn = document.createElement('button');
        btn.className = 'sandbox-move-btn';
        btn.textContent = z.label;
        btn.addEventListener('click', function(e) {
            e.stopPropagation();
            socket.emit('sandbox_move_card', {
                player_idx: playerIdx,
                card_numeric_id: cardNumericId,
                src_zone: srcZone,
                dst_zone: z.value,
            });
            pop.remove();
        });
        pop.appendChild(btn);
    });
    var rect = anchorEl.getBoundingClientRect();
    pop.style.top = (rect.bottom + window.scrollY) + 'px';
    pop.style.left = (rect.left + window.scrollX) + 'px';
    document.body.appendChild(pop);
    setTimeout(function() {
        document.addEventListener('click', function closeOnce(ev) {
            if (!pop.contains(ev.target)) {
                pop.remove();
                document.removeEventListener('click', closeOnce);
            }
        });
    }, 0);
}

function makeSandboxMoveButton(playerIdx, cardNumericId, srcZone) {
    var btn = document.createElement('button');
    btn.className = 'sandbox-move-btn';
    btn.textContent = 'Move to...';
    btn.addEventListener('click', function(e) {
        e.stopPropagation();
        openSandboxMovePopover(btn, playerIdx, cardNumericId, srcZone);
    });
    return btn;
}

// ---- E2. Staged card preview + drag-to-zone --------------------------------
function sandboxStageCard(nid) {
    var defs = sandboxCardDefs || cardDefs;
    var def = defs && defs[nid];
    if (!def) return;
    var staged = document.getElementById('sandbox-staged-card');
    if (!staged) return;
    var artStyle = def.card_id
        ? 'background-image:url(' + _cardArtUrl(def.card_id) + ')'
        : '';
    staged.innerHTML =
        '<div class="staged-art" style="' + artStyle + '"></div>' +
        '<span class="staged-name">' + escapeHtml(def.name) + '</span>' +
        '<span class="staged-cost">' + (def.mana_cost != null ? def.mana_cost : '-') + '\u{1F4A7}</span>' +
        '<span class="staged-drag-hint">CLICK CELL / DRAG</span>';
    staged.dataset.nid = nid;
    staged.hidden = false;
    // Click staged card → add to current zone selection
    if (!staged._clickBound) {
        staged._clickBound = true;
        staged.addEventListener('click', function() {
            var clickNid = parseInt(staged.dataset.nid, 10);
            if (isNaN(clickNid)) return;
            socket.emit('sandbox_add_card_to_zone', {
                player_idx: sandboxAddTargetIdx,
                card_numeric_id: clickNid,
                zone: sandboxAddZone,
            });
        });
    }
    // Wire drag handlers (idempotent — only binds once via the flag)
    if (!staged._dragBound) {
        staged._dragBound = true;
        staged.addEventListener('dragstart', function(e) {
            e.dataTransfer.setData('text/plain', staged.dataset.nid);
            e.dataTransfer.effectAllowed = 'copy';
            // Highlight all valid drop zones
            setTimeout(function() {
                document.querySelectorAll('#screen-sandbox .hand-container, #screen-sandbox .sandbox-pile-btn, #sandbox-board .board-cell')
                    .forEach(function(el) { el.classList.add('drop-target-active'); });
            }, 0);
        });
        staged.addEventListener('dragend', function() {
            document.querySelectorAll('.drop-target-active, .drop-target-hover')
                .forEach(function(el) {
                    el.classList.remove('drop-target-active');
                    el.classList.remove('drop-target-hover');
                });
        });
    }
    // Ensure drop zones are wired (idempotent)
    sandboxWireDropZones();
}

var _sandboxDropZonesBound = false;
function sandboxWireDropZones() {
    if (_sandboxDropZonesBound) return;
    _sandboxDropZonesBound = true;

    function handleDrop(playerIdx, zone) {
        return function(e) {
            e.preventDefault();
            var nid = parseInt(e.dataTransfer.getData('text/plain'), 10);
            if (isNaN(nid)) return;
            socket.emit('sandbox_add_card_to_zone', {
                player_idx: playerIdx,
                card_numeric_id: nid,
                zone: zone,
            });
        };
    }
    function allowDrop(e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    }
    function hoverIn(e) { e.currentTarget.classList.add('drop-target-hover'); }
    function hoverOut(e) { e.currentTarget.classList.remove('drop-target-hover'); }

    // Hand containers
    var handP0 = document.getElementById('sandbox-hand-p0');
    var handP1 = document.getElementById('sandbox-hand-p1');
    if (handP0) {
        handP0.addEventListener('dragover', allowDrop);
        handP0.addEventListener('dragenter', hoverIn);
        handP0.addEventListener('dragleave', hoverOut);
        handP0.addEventListener('drop', handleDrop(0, 'hand'));
    }
    if (handP1) {
        handP1.addEventListener('dragover', allowDrop);
        handP1.addEventListener('dragenter', hoverIn);
        handP1.addEventListener('dragleave', hoverOut);
        handP1.addEventListener('drop', handleDrop(1, 'hand'));
    }

    // Pile buttons (grave / exhaust / deck)
    document.querySelectorAll('#screen-sandbox .sandbox-pile-btn').forEach(function(btn) {
        var playerIdx = parseInt(btn.dataset.player, 10);
        var pile = btn.dataset.pile;
        btn.addEventListener('dragover', allowDrop);
        btn.addEventListener('dragenter', hoverIn);
        btn.addEventListener('dragleave', hoverOut);
        btn.addEventListener('drop', handleDrop(playerIdx, pile));
    });

    // Board cells — drop places minion directly on the grid
    var boardEl = document.getElementById('sandbox-board');
    if (boardEl) {
        boardEl.addEventListener('dragover', allowDrop);
        boardEl.addEventListener('drop', function(e) {
            e.preventDefault();
            var cell = e.target.closest('.board-cell');
            if (!cell) return;
            var nid = parseInt(e.dataTransfer.getData('text/plain'), 10);
            if (isNaN(nid)) return;
            var row = parseInt(cell.dataset.row, 10);
            var col = parseInt(cell.dataset.col, 10);
            socket.emit('sandbox_place_on_board', {
                player_idx: sandboxAddTargetIdx,
                card_numeric_id: nid,
                row: row,
                col: col,
            });
        });
        // Per-cell hover highlight (delegated)
        boardEl.addEventListener('dragenter', function(e) {
            var cell = e.target.closest('.board-cell');
            if (cell) cell.classList.add('drop-target-hover');
        });
        boardEl.addEventListener('dragleave', function(e) {
            var cell = e.target.closest('.board-cell');
            if (cell) cell.classList.remove('drop-target-hover');
        });
    }
}

// ---- F. Server-saves list rendering --------------------------------------
function renderSandboxSlotList(slots) {
    sandboxKnownSlots = slots || [];
    var list = document.getElementById('sandbox-slots-list');
    if (!list) return;
    list.innerHTML = '';
    if (!sandboxKnownSlots.length) {
        list.innerHTML = '<div class="sandbox-slots-empty">No server slots yet</div>';
        return;
    }
    sandboxKnownSlots.forEach(function(name) {
        var row = document.createElement('div');
        row.className = 'sandbox-slot-row';
        row.dataset.slotName = name;  // stable test hook
        var nameSpan = document.createElement('span');
        nameSpan.className = 'sandbox-slot-name';
        nameSpan.textContent = name;
        var loadBtn = document.createElement('button');
        loadBtn.className = 'btn btn-sm sandbox-slot-load-btn';
        loadBtn.textContent = 'Load';
        loadBtn.addEventListener('click', function() {
            // Phase 14.8-04a: server's load_dict resets _next_event_seq.
            if (typeof resetEventQueue === 'function') resetEventQueue();
            socket.emit('sandbox_load_slot', { slot_name: name });
        });
        var deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-sm sandbox-slot-delete-btn';
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', function() {
            if (confirm('Delete server slot "' + name + '"? This cannot be undone.')) {
                socket.emit('sandbox_delete_slot', { slot_name: name });
            }
        });
        row.appendChild(nameSpan);
        row.appendChild(loadBtn);
        row.appendChild(deleteBtn);
        list.appendChild(row);
    });
}

// ---- G. Share-code helpers (TextEncoder/TextDecoder, NOT escape/unescape) ----
function sandboxEncodeShareCode(stateDict) {
    var json = JSON.stringify(stateDict);
    var bytes = new TextEncoder().encode(json);
    var binary = '';
    for (var i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
}
function sandboxDecodeShareCode(code) {
    var binary = atob(code);
    var bytes = Uint8Array.from(binary, function(c) { return c.charCodeAt(0); });
    var json = new TextDecoder().decode(bytes);
    return JSON.parse(json);
}
function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function(c) {
        return { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c];
    });
}

// ---- H. Toolbar-state renderer --------------------------------------------
// Called from the sandbox_state handler. Updates history pill, active-control
// highlight, undo/redo enabled state, and syncs cheat inputs (without firing
// blur, which would cause a feedback loop).
function renderSandboxToolbarState() {
    var status = document.getElementById('sandbox-history-status');
    if (status) status.textContent = 'undo:' + sandboxUndoDepth + ' redo:' + sandboxRedoDepth;
    document.querySelectorAll('.sandbox-control-btn').forEach(function(btn) {
        var idx = parseInt(btn.dataset.control, 10);
        btn.classList.toggle('active', idx === sandboxActiveViewIdx);
    });
    var undoBtn = document.getElementById('sandbox-undo-btn');
    var redoBtn = document.getElementById('sandbox-redo-btn');
    if (undoBtn) undoBtn.disabled = sandboxUndoDepth === 0;
    if (redoBtn) redoBtn.disabled = sandboxRedoDepth === 0;
    // Sync cheat input values (skip focused input so we don't clobber typing)
    if (sandboxState && sandboxState.players) {
        document.querySelectorAll('.sandbox-cheat-input').forEach(function(input) {
            if (document.activeElement === input) return;
            var playerIdx = parseInt(input.dataset.player, 10);
            var field = input.dataset.field;
            var player = sandboxState.players[playerIdx];
            if (player && player[field] != null) {
                input.value = String(player[field]);
            }
        });
    }
}

// === SANDBOX-SECTION-END ===

// =============================================
// Bug reporter widget
//
// Shows a floating "🐞 Report a bug" button on Duel / Sandbox / Tests
// screens. On submit, posts {title, description, severity, screen, url,
// browser, version, game_state, events, console} to /api/bug-report;
// the server forwards to Trello (see bug_report.py).
// =============================================
(function bugReporter() {
    var fab = null, modal = null, statusEl = null, severity = 'annoying';
    // Ring buffer of recent engine events for context.
    var recentEvents = [];
    var MAX_RECENT = 50;
    // Mirror console errors/warnings so the report includes them.
    var recentConsole = [];
    var MAX_CONSOLE = 30;

    function init() {
        fab = document.getElementById('bug-fab');
        modal = document.getElementById('bug-modal');
        statusEl = document.getElementById('bug-modal-status');
        if (!fab || !modal) return;

        fab.addEventListener('click', openModal);
        modal.querySelectorAll('[data-bug-close]').forEach(function(el) {
            el.addEventListener('click', closeModal);
        });
        modal.querySelectorAll('.bug-sev').forEach(function(btn) {
            btn.addEventListener('click', function() {
                modal.querySelectorAll('.bug-sev').forEach(function(b) { b.classList.remove('is-active'); });
                btn.classList.add('is-active');
                severity = btn.getAttribute('data-sev') || 'annoying';
            });
        });
        document.getElementById('bug-submit').addEventListener('click', submit);
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && !modal.hidden) closeModal();
        });

        // Hook engine_events so we can store the most recent batch.
        try {
            if (typeof socket !== 'undefined' && socket && typeof socket.on === 'function') {
                socket.on('engine_events', function(payload) {
                    var evs = (payload && payload.events) || [];
                    for (var i = 0; i < evs.length; i++) {
                        recentEvents.push(evs[i]);
                        if (recentEvents.length > MAX_RECENT) recentEvents.shift();
                    }
                });
            }
        } catch (_) { /* defensive — bug reporter must never crash the game */ }

        // Mirror console.error / console.warn (read-only — never block).
        ['error', 'warn'].forEach(function(level) {
            var orig = console[level];
            console[level] = function() {
                try {
                    var msg = Array.prototype.map.call(arguments, function(a) {
                        if (typeof a === 'string') return a;
                        try { return JSON.stringify(a); } catch (_) { return String(a); }
                    }).join(' ');
                    recentConsole.push({level: level, t: Date.now(), msg: msg.slice(0, 500)});
                    if (recentConsole.length > MAX_CONSOLE) recentConsole.shift();
                } catch (_) {}
                return orig.apply(console, arguments);
            };
        });

        // Toggle FAB visibility based on the active screen. Watch for
        // both .screen.active class flips and the tests-overlay hidden
        // attribute toggling.
        updateFabVisibility();
        var observer = new MutationObserver(updateFabVisibility);
        observer.observe(document.body, { subtree: true, attributes: true, attributeFilter: ['class', 'hidden'] });
    }

    function activeScreenId() {
        var screens = document.querySelectorAll('.screen.active');
        // Tests overlay sits on top of the sandbox screen; if it's
        // showing, prefer that label so the bug card reflects what
        // the user was actually doing.
        var tests = document.getElementById('tests-overlay');
        if (tests && !tests.hidden) return 'screen-tests';
        return screens.length > 0 ? screens[screens.length - 1].id : null;
    }

    function updateFabVisibility() {
        if (!fab) return;
        // Always show — every screen can have bugs worth reporting.
        // We still hide if literally no screen is active (e.g.
        // very early page load), to avoid a floating button on a
        // blank page.
        fab.hidden = activeScreenId() === null;
    }

    // Captured at FAB-click time so it reflects the screen the user
    // was looking at when they decided to report — not whatever it
    // looks like 30 seconds later after they finish typing. Cleared
    // after each submit attempt.
    var pendingScreenshot = null;

    function openModal() {
        statusEl.textContent = '';
        statusEl.className = 'bug-modal-status';
        document.getElementById('bug-title').value = '';
        document.getElementById('bug-description').value = '';
        pendingScreenshot = null;
        // Lazy-load html2canvas (45 KB CDN) on first open.
        ensureHtml2Canvas();
        // Capture FIRST (modal is still hidden because openModal is
        // the only path that shows it), THEN show the modal. ~150-300ms
        // delay on first click while html2canvas downloads + runs;
        // subsequent clicks are sub-100ms because the lib is cached.
        captureScreenshot().then(function(b64) {
            pendingScreenshot = b64;
            modal.hidden = false;
            setTimeout(function() {
                var t = document.getElementById('bug-title');
                if (t) t.focus();
            }, 30);
        });
    }
    function ensureHtml2Canvas() {
        if (window.html2canvas || window.__h2cLoading) return;
        window.__h2cLoading = true;
        var s = document.createElement('script');
        s.src = 'https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js';
        s.async = true;
        s.onload = function() { window.__h2cLoading = false; };
        s.onerror = function() {
            window.__h2cLoading = false;
            window.__h2cFailed = true;
        };
        document.head.appendChild(s);
    }
    // Wait for html2canvas to finish loading from CDN — first FAB
    // click hits an empty cache, but only the first one. Resolves
    // either way after at most 3 s so a slow CDN can't block the
    // modal opening forever.
    function waitForH2C() {
        if (window.html2canvas || window.__h2cFailed) return Promise.resolve();
        return new Promise(function(resolve) {
            var t0 = Date.now();
            (function check() {
                if (window.html2canvas || window.__h2cFailed || Date.now() - t0 > 3000) resolve();
                else setTimeout(check, 50);
            })();
        });
    }

    // Capture a viewport screenshot via html2canvas; returns a Promise
    // that resolves to a base64 PNG (no data: prefix) or null. Always
    // resolves — never rejects — so callers can attach if available
    // and quietly skip if not. Caller is responsible for ensuring the
    // bug modal is NOT visible when this runs (we capture document.body
    // and the modal would otherwise appear in the result).
    function captureScreenshot() {
        return waitForH2C().then(function() {
            if (!window.html2canvas) return null;
            return window.html2canvas(document.body, {
                backgroundColor: '#050913',
                scale: 0.6,                // 0.6x viewport — keeps file under ~150 KB
                logging: false,
                useCORS: true,
                foreignObjectRendering: false,
            }).then(function(canvas) {
                var dataUrl = canvas.toDataURL('image/png');
                return dataUrl.replace(/^data:image\/png;base64,/, '');
            });
        }).catch(function() { return null; });
    }
    function closeModal() { if (modal) modal.hidden = true; }

    function captureGameState() {
        // Prefer the most recent authoritative final state stashed by
        // onEngineEvents; fall back to the live sandboxState/gameState.
        if (window.__lastFinalState) return window.__lastFinalState;
        if (typeof sandboxMode !== 'undefined' && sandboxMode
                && typeof sandboxState !== 'undefined') return sandboxState;
        if (typeof gameState !== 'undefined') return gameState;
        return null;
    }

    function appVersion() {
        var b = document.getElementById('patch-badge');
        if (b) {
            var v = b.querySelector('.patch-version');
            if (v) return (v.textContent || '').replace(/^Patch\s+/, '').trim();
        }
        return '';
    }

    function submit() {
        var titleEl = document.getElementById('bug-title');
        var descEl = document.getElementById('bug-description');
        var submitBtn = document.getElementById('bug-submit');
        var title = (titleEl.value || '').trim();
        var desc = (descEl.value || '').trim();
        if (!title || !desc) {
            statusEl.textContent = 'Title and description are required.';
            statusEl.className = 'bug-modal-status is-error';
            return;
        }
        submitBtn.disabled = true;
        statusEl.textContent = 'Sending…';
        statusEl.className = 'bug-modal-status';
        var payload = {
            title: title,
            description: desc,
            severity: severity,
            screen: activeScreenId() || 'unknown',
            url: location.href,
            browser: navigator.userAgent,
            version: appVersion(),
            game_state: captureGameState(),
            events: recentEvents.slice(-MAX_RECENT),
            console: recentConsole.slice(-MAX_CONSOLE),
            // Captured at FAB-click time, not now — see openModal.
            screenshot_png_b64: pendingScreenshot,
        };
        fetch('/api/bug-report', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload),
        }).then(function(r) {
            return r.json().then(function(j) { return {ok: r.ok, body: j}; });
        }).then(function(res) {
            submitBtn.disabled = false;
            if (res.ok && res.body && res.body.ok) {
                statusEl.className = 'bug-modal-status is-ok';
                if (res.body.card_url) {
                    statusEl.innerHTML = 'Reported. <a href="' + res.body.card_url + '" target="_blank" rel="noopener">View card ↗</a>';
                } else {
                    statusEl.textContent = 'Reported. Thanks!';
                }
                setTimeout(closeModal, 2200);
            } else {
                statusEl.className = 'bug-modal-status is-error';
                statusEl.textContent = (res.body && res.body.error) || 'Failed to send.';
            }
        }).catch(function(err) {
            submitBtn.disabled = false;
            statusEl.className = 'bug-modal-status is-error';
            statusEl.textContent = 'Network error: ' + err.message;
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, {once: true});
    } else {
        init();
    }
})();
