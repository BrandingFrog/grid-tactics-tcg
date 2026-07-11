// =============================================
// Phase 14.2: Tutor-pick modal
// =============================================

var tutorModalOpen = false;
// Mandatory tutoring (2026-07): re-render key so the open modal refreshes
// when the match set or the hand-full status changes mid multi-pick chain
// (e.g. To The Ratmobile amount=2 — the second pick's indices shift and
// the first pick may have just filled the hand).
var tutorModalKey = null;
var TUTOR_MAX_HAND_SIZE = 10;  // mirrors grid_tactics.types.MAX_HAND_SIZE

function tutorPickerHandLen() {
    // Hand length of the PICKING player (pending_tutor_player_idx). Own
    // hand arrives as full card ids; a filtered opponent hand only has
    // hand_count (not hit in practice — the modal only opens for self).
    if (!gameState || !gameState.players) return 0;
    var pl = gameState.players[gameState.pending_tutor_player_idx];
    if (!pl) return 0;
    if (pl.hand && pl.hand.length) return pl.hand.length;
    if (typeof pl.hand_count === 'number') return pl.hand_count;
    return 0;
}

function tutorModalStateKey(matches) {
    var idxs = (matches || []).map(function(m) { return m.match_idx; }).join(',');
    var full = tutorPickerHandLen() >= TUTOR_MAX_HAND_SIZE ? 'full' : 'ok';
    return idxs + '|' + full;
}

function syncPendingTutorUI() {
    if (!gameState) {
        if (tutorModalOpen) closeTutorModal();
        hideOpponentTutoringToast();
        return;
    }
    var pendingIdx = gameState.pending_tutor_player_idx;
    if (pendingIdx == null) {
        if (tutorModalOpen) closeTutorModal();
        hideOpponentTutoringToast();
        return;
    }
    if (pendingIdx === myPlayerIdx) {
        // I'm the caster — show the picker modal.
        hideOpponentTutoringToast();
        var matches = gameState.pending_tutor_matches || [];
        var key = tutorModalStateKey(matches);
        if (!tutorModalOpen || key !== tutorModalKey) {
            // Multi-pick queue (user 2026-07-08): the player selected several
            // cards in ONE modal; the engine steps picks one at a time, so
            // consume the queued picks silently as each fresh match list
            // arrives instead of re-showing the modal per pick.
            if (window._tutorPickQueue && window._tutorPickQueue.length) {
                var wantNid = window._tutorPickQueue[0];
                var qm = null;
                for (var qi = 0; qi < matches.length; qi++) {
                    if (matches[qi].card_numeric_id === wantNid) { qm = matches[qi]; break; }
                }
                if (qm) {
                    window._tutorPickQueue.shift();
                    tutorModalKey = key;   // mark this state consumed
                    tutorModalOpen = true; // stay in "modal owns the flow" mode
                    submitAction({ action_type: 9, card_index: qm.match_idx });
                    return;
                }
                window._tutorPickQueue = [];   // unfulfillable — fall through to the modal
            }
            var deckSize = (gameState.players && gameState.players[myPlayerIdx])
                ? (gameState.players[myPlayerIdx].deck_count || 0)
                : 0;
            var totals = gameState.pending_tutor_total_copies_owned || {};
            showTutorModal(matches, deckSize, totals);
            tutorModalKey = key;
        }
    } else {
        // Opponent is choosing — passive toast, no modal.
        if (tutorModalOpen) closeTutorModal();
        showOpponentTutoringToast();
    }
}

function showTutorModal(matches, deckSize, totalCopiesByCardId) {
    closeTutorModal();
    tutorModalOpen = true;
    window._tutorPickQueue = [];   // a freshly-rendered modal owns the flow

    // Select-then-Accept (user 2026-07-08): clicking a card SELECTS it
    // (and previews it in the tooltip); Accept submits. Multi-pick tutors
    // (pending_tutor_remaining > 1, e.g. Ratmobile) select all picks in
    // this one modal — the extras queue and auto-submit as the engine
    // steps through them.
    var pickTarget = Math.max(1, (gameState && gameState.pending_tutor_remaining) || 1);
    var maxPick = Math.min(pickTarget, (matches || []).length || 1);
    var selectedPicks = [];   // [{nid, matchIdx, tile}]

    // Count remaining-in-deck per card_numeric_id (matches come from deck only).
    var remainingByNid = {};
    matches.forEach(function(m) {
        var k = String(m.card_numeric_id);
        remainingByNid[k] = (remainingByNid[k] || 0) + 1;
    });

    var overlay = document.createElement('div');
    overlay.className = 'tutor-modal-overlay';
    overlay.id = 'tutor-modal-overlay';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = maxPick > 1
        ? 'Choose cards to tutor \u2014 pick ' + maxPick
        : 'Choose a card to tutor';
    header.appendChild(title);
    var pickCounter = document.createElement('div');
    pickCounter.className = 'tutor-modal-deckline';
    pickCounter.textContent = 'Selected 0/' + maxPick;
    header.appendChild(pickCounter);
    // Minimise (user 2026-07-07): peek at the board mid-pick. The pick is
    // MANDATORY — while minimised only the restore pill acts (all other
    // inputs stay illegal server-side and gate-blocked client-side).
    var minBtn = document.createElement('button');
    minBtn.className = 'tutor-min-btn';
    minBtn.textContent = '▾';
    minBtn.title = 'Minimise — peek at the board';
    minBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        overlay.style.display = 'none';
        var pill = document.createElement('button');
        pill.id = 'tutor-restore-pill';
        pill.className = 'tutor-restore-pill';
        pill.textContent = '▴ Resume card pick';
        pill.addEventListener('click', function() {
            pill.remove();
            overlay.style.display = '';
        });
        _stageMount().appendChild(pill);
    });
    header.appendChild(minBtn);
    modal.appendChild(header);

    // Mandatory tutoring (2026-07): a full hand does NOT exempt the pick —
    // the tutored card overdraw-burns to the Exhaust Pile revealed (the
    // resolution reuses the existing overdraw-burn animation via
    // EVT_CARD_BURNED). Warn the picker above the card fan.
    // NOT for conjure picks (pending_tutor_is_conjure — Ratchanter): a
    // conjure TUTOR_SELECT goes to the FIELD via pending_conjure_deploy
    // and never burns on select, so the banner would be wrong there.
    var isConjurePick = !!(gameState && gameState.pending_tutor_is_conjure);
    if (!isConjurePick && tutorPickerHandLen() >= TUTOR_MAX_HAND_SIZE) {
        var warnBanner = document.createElement('div');
        warnBanner.className = 'tutor-modal-warning';
        warnBanner.textContent = 'Hand full — tutored card will be exhausted';
        modal.appendChild(warnBanner);
    }

    var fan = document.createElement('div');
    fan.className = 'tutor-modal-cards';

    if (!matches || matches.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'tutor-modal-empty';
        empty.textContent = 'No matching cards.';
        fan.appendChild(empty);
    } else {
        matches.forEach(function(match) {
            var nid = match.card_numeric_id;
            var tile = document.createElement('div');
            tile.className = 'tutor-modal-card';
            // No count badge: -1 renders the deck builder's non-deckable
            // 🚫 marker, which read as 'blocked' in the picker (user 2026-07-06).
            tile.innerHTML = renderDeckBuilderCard(nid, undefined);

            // copies-remaining pill removed (user 2026-07-07)
            tile.addEventListener('click', function(e) {
                e.stopPropagation();
                var at = -1;
                for (var si = 0; si < selectedPicks.length; si++) {
                    if (selectedPicks[si].tile === tile) { at = si; break; }
                }
                if (at !== -1) {
                    // second click unselects
                    selectedPicks.splice(at, 1);
                    tile.classList.remove('tutor-card-selected');
                } else {
                    if (maxPick === 1 && selectedPicks.length === 1) {
                        // single-pick: clicking another card switches selection
                        selectedPicks[0].tile.classList.remove('tutor-card-selected');
                        selectedPicks.length = 0;
                    }
                    if (selectedPicks.length >= maxPick) return;
                    selectedPicks.push({ nid: nid, matchIdx: match.match_idx, tile: tile });
                    tile.classList.add('tutor-card-selected');
                    try { showGameTooltip(nid, tile, null, { force: true }); } catch (e2) { /* defensive */ }
                }
                _updateTutorAccept();
            });
            fan.appendChild(tile);
        });
    }
    modal.appendChild(fan);

    // Footer: Accept confirms the selection (user 2026-07-08). Skip keeps
    // its old rules — zero matches (escape hatch) or conjure picks
    // (DECLINE_TUTOR leaves the card in the deck); mandatory tutors with
    // matches get no Skip.
    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var acceptBtn = null;
    if (matches && matches.length > 0) {
        acceptBtn = document.createElement('button');
        acceptBtn.className = 'tutor-accept-button';
        acceptBtn.textContent = 'Accept';
        acceptBtn.disabled = true;
        acceptBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            if (!selectedPicks.length) return;
            // Queue the extras; submit the first. Hide the modal NOW so the
            // deck->hand fly plays over the board, not over the picker.
            window._tutorPickQueue = [];
            for (var pi = 1; pi < selectedPicks.length; pi++) {
                window._tutorPickQueue.push(selectedPicks[pi].nid);
            }
            var first = selectedPicks[0];
            _hideTutorModalForSubmit();
            // ActionType.TUTOR_SELECT = 9 (Phase 14.2). card_index = match index.
            submitAction({ action_type: 9, card_index: first.matchIdx });
        });
        footer.appendChild(acceptBtn);
    }
    function _updateTutorAccept() {
        pickCounter.textContent = 'Selected ' + selectedPicks.length + '/' + maxPick;
        if (acceptBtn) {
            acceptBtn.disabled = selectedPicks.length === 0;
            acceptBtn.textContent = selectedPicks.length > 1
                ? 'Accept (' + selectedPicks.length + ')' : 'Accept';
        }
    }
    if (!matches || matches.length === 0 || isConjurePick) {
        var skipBtn = document.createElement('button');
        skipBtn.className = 'tutor-skip-button';
        skipBtn.textContent = 'Skip';
        skipBtn.title = isConjurePick
            ? 'Decline the conjure — leave the card in your deck'
            : 'No matching cards — close the search';
        skipBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            // ActionType.DECLINE_TUTOR = 10 (Phase 14.2)
            submitAction({ action_type: 10 });
        });
        footer.appendChild(skipBtn);
    }
    if (footer.children.length) modal.appendChild(footer);

    overlay.appendChild(modal);
    // Block background clicks (no accidental dismiss — must Skip explicitly).
    overlay.addEventListener('click', function(e) { e.stopPropagation(); });
    _stageMount().appendChild(overlay);
}

// Hide the picker for a submitted pick WITHOUT resetting tutorModalOpen/
// tutorModalKey — syncPendingTutorUI then won't re-show the same pending
// state while the pick round-trips (and the deck->hand fly stays visible).
function _hideTutorModalForSubmit() {
    var _pill = document.getElementById('tutor-restore-pill');
    if (_pill) _pill.remove();
    var existing = document.getElementById('tutor-modal-overlay');
    if (existing) existing.remove();
}

function closeTutorModal() {
    var _pill = document.getElementById('tutor-restore-pill');
    if (_pill) _pill.remove();
    var existing = document.getElementById('tutor-modal-overlay');
    if (existing) existing.remove();
    tutorModalOpen = false;
    tutorModalKey = null;
}

function showOpponentTutoringToast() {
    if (document.getElementById('opponent-tutoring-toast')) return;
    var toast = document.createElement('div');
    toast.id = 'opponent-tutoring-toast';
    toast.className = 'tutor-toast';
    toast.textContent = 'Opponent is tutoring…';
    _stageMount().appendChild(toast);
}

function hideOpponentTutoringToast() {
    var existing = document.getElementById('opponent-tutoring-toast');
    if (existing) existing.remove();
}

// =============================================
// Phase 14.7-05: Trigger picker modal (simultaneous START/END triggers)
// =============================================
// When 2+ ON_START_OF_TURN or ON_END_OF_TURN effects fire simultaneously,
// the picker owner sees a modal with each triggering minion's full card
// face (reusing renderDeckBuilderCard — user directive "we want to use
// existing modals"). Clicking a card emits TRIGGER_PICK(queue_idx=i).
// A Skip button emits DECLINE_TRIGGER which fizzles the remaining queue.
// The opponent sees a passive toast while the picker is deciding.

var triggerPickerModalOpen = false;

function syncPendingTriggerPickerUI() {
    if (!gameState) {
        if (triggerPickerModalOpen) closeTriggerPickerModal();
        hideOpponentTriggerPickerToast();
        return;
    }
    var pickerIdx = gameState.pending_trigger_picker_idx;
    if (pickerIdx == null) {
        if (triggerPickerModalOpen) closeTriggerPickerModal();
        hideOpponentTriggerPickerToast();
        return;
    }
    // Sandbox is god-mode — always show the modal regardless of myPlayerIdx.
    var isPicker = sandboxMode || pickerIdx === myPlayerIdx;
    if (isPicker) {
        hideOpponentTriggerPickerToast();
        if (!triggerPickerModalOpen) {
            var options = gameState.pending_trigger_picker_options || [];
            showTriggerPickerModal(options);
        }
    } else {
        if (triggerPickerModalOpen) closeTriggerPickerModal();
        showOpponentTriggerPickerToast();
    }
}

function showTriggerPickerModal(options) {
    closeTriggerPickerModal();
    triggerPickerModalOpen = true;

    var overlay = document.createElement('div');
    // Reuse tutor-modal CSS class — same layout, same animations. Adding
    // a distinguishing class lets us restyle later without touching tutor.
    overlay.className = 'tutor-modal-overlay trigger-picker-modal-overlay';
    overlay.id = 'trigger-picker-modal-overlay';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal trigger-picker-modal';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = 'Pick the order to resolve these effects';
    var sub = document.createElement('div');
    sub.className = 'tutor-modal-deckline';
    sub.textContent = (options || []).length + ' triggers waiting';
    header.appendChild(title);
    header.appendChild(sub);
    modal.appendChild(header);

    var fan = document.createElement('div');
    fan.className = 'tutor-modal-cards';

    if (!options || options.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'tutor-modal-empty';
        empty.textContent = 'No triggers to pick.';
        fan.appendChild(empty);
    } else {
        options.forEach(function(opt) {
            var nid = opt.source_card_numeric_id;
            var queueIdx = opt.queue_idx;
            var tile = document.createElement('div');
            tile.className = 'tutor-modal-card trigger-picker-card';
            // Reuse renderDeckBuilderCard — same full-face card render
            // the tutor modal uses. count=-1 suppresses the deck count pill.
            // No count badge: -1 renders the deck builder's non-deckable
            // 🚫 marker, which read as 'blocked' in the picker (user 2026-07-06).
            tile.innerHTML = renderDeckBuilderCard(nid, undefined);

            // Optional label showing the trigger kind (Start/End/etc.)
            var kindPill = document.createElement('div');
            kindPill.className = 'tutor-copy-count';
            var kindLabel = opt.trigger_kind === 'start_of_turn'
                ? 'Rally Phase'
                : (opt.trigger_kind === 'end_of_turn' ? 'Decay Phase' : opt.trigger_kind);
            kindPill.textContent = kindLabel;
            tile.appendChild(kindPill);

            tile.addEventListener('click', function(e) {
                e.stopPropagation();
                var was = tile.classList.contains('tutor-card-selected');
                var all = fan.querySelectorAll('.tutor-card-selected');
                for (var ci = 0; ci < all.length; ci++) all[ci].classList.remove('tutor-card-selected');
                window._triggerPickIdx = null;
                if (!was) {
                    tile.classList.add('tutor-card-selected');
                    window._triggerPickIdx = queueIdx;
                    try { showGameTooltip(nid, tile, null, { force: true }); } catch (e2) { /* defensive */ }
                }
                var ab = document.getElementById('trigger-accept-btn');
                if (ab) ab.disabled = window._triggerPickIdx == null;
            });
            fan.appendChild(tile);
        });
    }
    modal.appendChild(fan);

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    window._triggerPickIdx = null;
    var trigAccept = document.createElement('button');
    trigAccept.id = 'trigger-accept-btn';
    trigAccept.className = 'tutor-accept-button';
    trigAccept.textContent = 'Accept';
    trigAccept.disabled = true;
    trigAccept.addEventListener('click', function(e) {
        e.stopPropagation();
        if (window._triggerPickIdx == null) return;
        var pick = window._triggerPickIdx;
        window._triggerPickIdx = null;
        // ActionType.TRIGGER_PICK = 17 (Phase 14.7-05). card_index = queue_idx.
        submitAction({ action_type: 17, card_index: pick });
    });
    footer.appendChild(trigAccept);
    var skipBtn = document.createElement('button');
    skipBtn.className = 'tutor-skip-button';
    skipBtn.textContent = 'Skip remaining';
    skipBtn.title = 'Decline remaining triggers — they fizzle silently';
    skipBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        // ActionType.DECLINE_TRIGGER = 18 (Phase 14.7-05).
        submitAction({ action_type: 18 });
    });
    footer.appendChild(skipBtn);
    modal.appendChild(footer);

    overlay.appendChild(modal);
    // Block background clicks — must Skip explicitly (matches tutor modal UX).
    overlay.addEventListener('click', function(e) { e.stopPropagation(); });
    _stageMount().appendChild(overlay);
}

function closeTriggerPickerModal() {
    var existing = document.getElementById('trigger-picker-modal-overlay');
    if (existing) existing.remove();
    triggerPickerModalOpen = false;
}

function showOpponentTriggerPickerToast() {
    if (document.getElementById('opponent-trigger-picker-toast')) return;
    var toast = document.createElement('div');
    toast.id = 'opponent-trigger-picker-toast';
    // Reuse tutor-toast styling — same "waiting on opponent" visual treatment.
    toast.className = 'tutor-toast';
    toast.textContent = 'Opponent is ordering effects…';
    _stageMount().appendChild(toast);
}

function hideOpponentTriggerPickerToast() {
    var existing = document.getElementById('opponent-trigger-picker-toast');
    if (existing) existing.remove();
}

// =============================================
// Revive modal — place revived minions from grave
// =============================================

var reviveModalOpen = false;

function syncPendingReviveUI() {
    if (!gameState) {
        if (reviveModalOpen) closeReviveModal();
        return;
    }
    var pendingIdx = gameState.pending_revive_player_idx;
    if (pendingIdx == null) {
        window.__reviveSubmittedAtRemaining = null;
        if (reviveModalOpen) closeReviveModal();
        if (interactionMode === 'revive_place') interactionMode = null;
        return;
    }
    // Sandbox is god-mode — always show the modal regardless of myPlayerIdx.
    var isPicker = sandboxMode || pendingIdx === myPlayerIdx;
    if (!isPicker) {
        if (reviveModalOpen) closeReviveModal();
        return;
    }
    var remaining = gameState.pending_revive_remaining || 0;
    // In-flight guard (revive rework, user 2026-07-11): a placement was
    // already submitted against THIS remaining count — the frame is stale;
    // keep the UI down until the fresh frame (remaining decremented or
    // pending cleared) arrives.
    if (window.__reviveSubmittedAtRemaining != null) {
        if (window.__reviveSubmittedAtRemaining === remaining) {
            if (reviveModalOpen) closeReviveModal();
            return;
        }
        window.__reviveSubmittedAtRemaining = null;
    }
    // Tile-place phase (a minion was picked from the fan): keep the mode,
    // just refresh the highlights after any board rebuild.
    if (interactionMode === 'revive_place' && reviveModalOpen) {
        highlightReviveCells();
        return;
    }
    if (!reviveModalOpen) showReviveModal();
}

function showReviveModal() {
    // Revive rework (user 2026-07-11): the old banner said "click a
    // highlighted cell" but relied on inline cell.onclick handlers that
    // every renderBoard rebuild wiped — clicking did nothing. New flow
    // mirrors conjure: a horizontal fan of the revivable minions (like the
    // tutor picker); click one, then click a highlighted tile to place it.
    closeReviveModal();
    reviveModalOpen = true;
    interactionMode = null;   // board inert until a minion is picked

    var remaining = gameState.pending_revive_remaining || 0;
    var cardNid = gameState.pending_revive_card_numeric_id;
    var cardDef = cardNid != null && window.cardDefs ? window.cardDefs[cardNid] : null;
    var cardName = cardDef ? cardDef.name : 'minion';
    var pendingIdx = gameState.pending_revive_player_idx;

    // One fan tile per revivable copy: remaining, capped by how many
    // copies actually sit in the reviver's grave (when visible to us).
    var copies = remaining;
    try {
        var grave = gameState.players[pendingIdx] && gameState.players[pendingIdx].grave;
        if (Array.isArray(grave) && cardNid != null) {
            var inGrave = grave.filter(function(x) { return x === cardNid; }).length;
            if (inGrave > 0) copies = Math.min(remaining, inGrave);
        }
    } catch (e) { /* opponent grave counts may be redacted — keep remaining */ }

    var overlay = document.createElement('div');
    overlay.className = 'tutor-modal-overlay revive-modal-overlay-nonblock';
    overlay.id = 'revive-modal-overlay';
    overlay.style.cssText = 'position:fixed;top:56px;left:0;right:0;bottom:auto;background:transparent;backdrop-filter:none;pointer-events:none;display:flex;justify-content:center;z-index:10;';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal';
    modal.style.cssText = 'pointer-events:auto;max-width:560px;background:rgba(23,16,6,0.95);border:2px solid #6b5730;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.6);';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.id = 'revive-modal-title';
    title.textContent = 'Revive — pick a ' + cardName + ' to place (' + remaining + ' remaining)';
    header.appendChild(title);
    modal.appendChild(header);

    var fan = document.createElement('div');
    fan.className = 'tutor-modal-fan';
    fan.id = 'revive-modal-fan';
    for (var i = 0; i < Math.max(1, copies); i++) {
        var tile = document.createElement('div');
        tile.className = 'tutor-modal-card';
        tile.innerHTML = (typeof renderDeckBuilderCard === 'function' && cardNid != null)
            ? renderDeckBuilderCard(cardNid, undefined)
            : ('<div style="padding:20px;color:#cbb98f;">' + cardName + '</div>');
        tile.addEventListener('click', function(e) {
            e.stopPropagation();
            // Picked — collapse the fan, arm tile placement.
            var fanEl = document.getElementById('revive-modal-fan');
            if (fanEl) fanEl.style.display = 'none';
            var t = document.getElementById('revive-modal-title');
            if (t) t.textContent = 'Place ' + cardName + ' — click a highlighted tile';
            interactionMode = 'revive_place';
            try { highlightBoard(); } catch (e2) { /* defensive */ }
            highlightReviveCells();
        });
        fan.appendChild(tile);
    }
    modal.appendChild(fan);

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var skipBtn = document.createElement('button');
    skipBtn.className = 'btn btn-secondary';
    skipBtn.textContent = remaining > 0 ? 'Done (skip remaining)' : 'Done';
    skipBtn.onclick = function() {
        window.__reviveSubmittedAtRemaining = gameState
            ? (gameState.pending_revive_remaining || 0) : 0;
        submitAction({ action_type: 16 }); // DECLINE_REVIVE
        closeReviveModal();
    };
    footer.appendChild(skipBtn);
    modal.appendChild(footer);

    overlay.appendChild(modal);
    _stageMount().appendChild(overlay);
}

function highlightReviveCells() {
    // Highlight-only: the click handling lives in onBoardCellClick's
    // revive_place branch (rework 2026-07-11 — the old inline cell.onclick
    // handlers were wiped by every renderBoard rebuild).
    if (!window.legalActions) return;
    var screenSel = (typeof sandboxMode !== 'undefined' && sandboxMode)
        ? '#screen-sandbox' : '#screen-game';
    for (var i = 0; i < legalActions.length; i++) {
        var a = legalActions[i];
        if (a.action_type === 15 && a.position) { // REVIVE_PLACE
            var cell = document.querySelector(
                screenSel + ' .board-cell[data-row="' + a.position[0]
                + '"][data-col="' + a.position[1] + '"]');
            if (cell) cell.classList.add('cell-valid');
        }
    }
}

function closeReviveModal() {
    var existing = document.getElementById('revive-modal-overlay');
    if (existing) existing.remove();
    reviveModalOpen = false;
    if (interactionMode === 'revive_place') interactionMode = null;
    // Clear cell highlights
    var cells = document.querySelectorAll('.board-cell.cell-valid');
    cells.forEach(function(cell) { cell.classList.remove('cell-valid'); });
}

// =============================================
// Phase 14.6: Conjure deploy tile-picking UI
// =============================================

var conjureDeployActive = false;

function syncPendingConjureDeployUI() {
    if (!gameState) {
        closeConjureDeployUI();
        return;
    }
    var pendingIdx = gameState.pending_conjure_deploy_player_idx;
    if (pendingIdx == null) {
        // Pending gate cleared — the submitted deploy landed; release the
        // in-flight guard so the next conjure can arm normally.
        window.__conjureDeploySubmitted = false;
        closeConjureDeployUI();
        return;
    }
    // In-flight guard (GT-9833FF): a deploy was already submitted for this
    // pending gate — don't re-arm the mode off the stale frame.
    if (window.__conjureDeploySubmitted) {
        closeConjureDeployUI();
        return;
    }
    // Sandbox is god-mode — always show the deploy UI regardless of myPlayerIdx.
    var isDeployer = sandboxMode || pendingIdx === myPlayerIdx;
    if (isDeployer) {
        // Re-assert the mode on every state update; closeConjureDeployUI in
        // showConjureDeployUI will null it, so set AFTER opening too.
        interactionMode = 'conjure_deploy';
        if (!conjureDeployActive) {
            conjureDeployActive = true;
            showConjureDeployUI();
        }
    } else {
        // Opponent is deploying
        closeConjureDeployUI();
        showOpponentConjuringToast();
    }
}

function showConjureDeployUI() {
    // Show a header bar instructing the player to pick a tile
    closeConjureDeployUI();
    conjureDeployActive = true;
    interactionMode = 'conjure_deploy';

    var banner = document.createElement('div');
    banner.id = 'conjure-deploy-banner';
    banner.className = 'tutor-toast';
    banner.style.background = '#4e5d28';
    banner.style.top = '60px';

    var cardNid = gameState.pending_conjure_deploy_card;
    var cardName = cardNid != null ? findCardNameByNid(cardNid) : 'card';
    banner.textContent = 'Deploy ' + cardName + ' — click a valid tile';

    // Conjure must deploy (user 2026-07-10): the To Hand escape renders
    // ONLY when the server offers DECLINE_CONJURE — which it now does
    // solely when the board has zero legal deploy tiles.
    var declineLegal = Array.isArray(legalActions)
        && legalActions.some(function(a) { return a.action_type === 13; });
    if (declineLegal) {
        var skipBtn = document.createElement('button');
        skipBtn.className = 'tutor-skip-button';
        skipBtn.style.marginLeft = '12px';
        skipBtn.style.display = 'inline';
        skipBtn.textContent = 'To Hand';
        skipBtn.title = 'No tile available — the conjured card goes to your hand';
        skipBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            // In-flight guard — same double-submit race as tile deploys.
            window.__conjureDeploySubmitted = true;
            // ActionType.DECLINE_CONJURE = 13
            submitAction({ action_type: 13 });
            closeConjureDeployUI();
        });
        banner.appendChild(skipBtn);
    }

    _stageMount().appendChild(banner);

    // Highlight valid deploy tiles
    highlightBoard();
}

function closeConjureDeployUI() {
    var existing = document.getElementById('conjure-deploy-banner');
    if (existing) existing.remove();
    var toast = document.getElementById('opponent-conjuring-toast');
    if (toast) toast.remove();
    if (conjureDeployActive) {
        conjureDeployActive = false;
        if (interactionMode === 'conjure_deploy') interactionMode = null;
    }
}

function showOpponentConjuringToast() {
    if (document.getElementById('opponent-conjuring-toast')) return;
    var toast = document.createElement('div');
    toast.id = 'opponent-conjuring-toast';
    toast.className = 'tutor-toast';
    toast.textContent = 'Opponent is deploying a conjured card\u2026';
    _stageMount().appendChild(toast);
}

// =============================================
// Death-trigger modal UI (e.g. Lasercannon on_death destroy)
// =============================================

var deathTargetActive = false;

function syncPendingDeathTargetUI() {
    if (!gameState) {
        closeDeathTargetUI();
        return;
    }
    var ownerIdx = gameState.pending_death_target_owner_idx;
    if (ownerIdx == null) {
        closeDeathTargetUI();
        return;
    }
    // Sandbox is god-mode — always enter picker UI regardless of myPlayerIdx.
    var isPicker = sandboxMode || ownerIdx === myPlayerIdx;
    if (isPicker) {
        // Always (re-)enter the picker mode on every state update while the
        // modal is open — a prior clearSelection() may have wiped
        // interactionMode even though deathTargetActive remained true.
        interactionMode = 'death_target_pick';
        if (!deathTargetActive) {
            deathTargetActive = true;
            showDeathTargetPickerUI();
        }
    } else {
        // Opponent is picking — passive toast, no modal.
        closeDeathTargetUI();
        showOpponentDeathPickToast();
    }
}

function showDeathTargetPickerUI() {
    closeDeathTargetUI();
    // closeDeathTargetUI nulls interactionMode — re-assert picker mode
    // AFTER so the rest of this function (and downstream highlightBoard)
    // sees the right mode.
    deathTargetActive = true;
    interactionMode = 'death_target_pick';

    var banner = document.createElement('div');
    banner.id = 'death-target-banner';
    banner.className = 'tutor-toast';
    banner.style.background = '#6e2a18';
    banner.style.top = '60px';

    var cardName = gameState.pending_death_card_name || 'Death effect';
    var filter = gameState.pending_death_filter || 'enemy_minion';
    var text;
    if (filter === 'friendly_promote') {
        banner.style.background = '#3a2e18';
        text = 'Pick an ally to promote (' + cardName + ' death)';
    } else {
        text = 'Pick an enemy to destroy (' + cardName + ' death)';
    }
    banner.textContent = text;
    _stageMount().appendChild(banner);

    highlightBoard();
}

function closeDeathTargetUI() {
    var existing = document.getElementById('death-target-banner');
    if (existing) existing.remove();
    var toast = document.getElementById('opponent-death-pick-toast');
    if (toast) toast.remove();
    if (deathTargetActive) {
        deathTargetActive = false;
        if (interactionMode === 'death_target_pick') interactionMode = null;
    }
}

function showOpponentDeathPickToast() {
    if (document.getElementById('opponent-death-pick-toast')) return;
    var toast = document.createElement('div');
    toast.id = 'opponent-death-pick-toast';
    toast.className = 'tutor-toast';
    toast.style.background = '#6e2a18';
    toast.textContent = 'Opponent is choosing a target for a Death effect\u2026';
    _stageMount().appendChild(toast);
}

function findCardNameByNid(nid) {
    // cardDefs is the nid-keyed map populated from sandbox_card_defs /
    // the game-start card defs payload; cardDefsMap was a stale name.
    var defs = (typeof cardDefs !== 'undefined' && cardDefs) ? cardDefs : null;
    if (defs && defs[nid]) return defs[nid].name || ('Card #' + nid);
    return 'Card #' + nid;
}

// Highlight valid board cells based on current selection
function highlightBoard() {
    document.querySelectorAll('.board-cell').forEach(function(cell) {
        cell.classList.remove('cell-valid', 'cell-attack', 'cell-selected',
                              'attack-range-footprint', 'attack-valid-target');
    });
    // Timing audit (2026-07-06): plain selection/targeting highlights only
    // paint when the player can act now. Pending-decision modes (post-move
    // attack pick, death target, conjure deploy, revive) stay live — those
    // are server-gated decisions awaiting THIS player mid-chain.
    var _pendingMode = interactionMode === 'post_move_attack_pick'
        || interactionMode === 'death_target_pick'
        || interactionMode === 'conjure_deploy'
        || interactionMode === 'revive_place';
    if (!_pendingMode && typeof canActNow === 'function' && !canActNow()) {
        return;
    }

    // Phase 14.1: post-move attack-pick layer (rendered first so the brighter
    // valid-target class can override the footprint visually).
    if (interactionMode === 'post_move_attack_pick' && gameState) {
        var rangeTiles = gameState.pending_attack_range_tiles || [];
        rangeTiles.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('attack-range-footprint');
        });
        var validTargets = gameState.pending_attack_valid_targets || [];
        validTargets.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('attack-valid-target');
        });
        // Mark the attacker's own cell as selected
        var pendingId = gameState.pending_post_move_attacker_id;
        (gameState.minions || []).forEach(function(m) {
            if (m.instance_id === pendingId) {
                var mc = document.querySelector('.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
                if (mc) mc.classList.add('cell-selected');
            }
        });
        return;  // Skip the regular selection-driven highlighting
    }

    // Revive placement tile highlighting (Ratical Resurrection modal).
    // Uses legalActions REVIVE_PLACE entries to mark valid tiles.
    if (interactionMode === 'revive_place' && legalActions) {
        for (var _i = 0; _i < legalActions.length; _i++) {
            var _a = legalActions[_i];
            if (_a.action_type === 15 && _a.position) {  // REVIVE_PLACE
                var _cell = document.querySelector('.board-cell[data-row="' + _a.position[0] + '"][data-col="' + _a.position[1] + '"]');
                if (_cell) _cell.classList.add('cell-valid');
            }
        }
        return;
    }

    // Death-target pick tile highlighting (click-target death modal).
    if (interactionMode === 'death_target_pick' && gameState) {
        var deathTargets = gameState.pending_death_valid_targets || [];
        deathTargets.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) {
                cell.classList.add('cell-attack');
                cell.classList.add('attack-valid-target');
            }
        });
        return;  // Skip regular highlighting
    }

    // Phase 14.6: conjure deploy tile highlighting.
    if (interactionMode === 'conjure_deploy' && gameState) {
        var deployPositions = gameState.pending_conjure_deploy_positions || [];
        deployPositions.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('cell-valid');
        });
        return;  // Skip regular highlighting
    }

    if (interactionMode === 'play' && selectedHandIdx !== null) {
        var positions = getDeployPositions(selectedHandIdx);
        positions.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('cell-valid');
        });
    }

    if (interactionMode === 'activate_target' && selectedAbilityMinionId !== null) {
        // Highlight the activator's tile as selected, plus every legal target
        // tile from ACTIVATE_ABILITY actions for this minion.
        (gameState.minions || []).forEach(function(m) {
            if (m.instance_id === selectedAbilityMinionId) {
                var ac = document.querySelector('.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
                if (ac) ac.classList.add('cell-selected');
            }
        });
        (legalActions || []).forEach(function(a) {
            if (a.action_type === 11 && a.minion_id === selectedAbilityMinionId && a.target_pos) {
                var tc = document.querySelector('.board-cell[data-row="' + a.target_pos[0] + '"][data-col="' + a.target_pos[1] + '"]');
                if (tc) tc.classList.add('cell-valid');
            }
        });
    }

    if (interactionMode === 'target' && selectedHandIdx !== null) {
        // Highlight locked deploy position (if any) as selected
        if (selectedDeployPos) {
            var depCell = document.querySelector('.board-cell[data-row="' + selectedDeployPos[0] + '"][data-col="' + selectedDeployPos[1] + '"]');
            if (depCell) depCell.classList.add('cell-selected');
        }
        // Highlight target candidates in red
        var targets = getTargetPositions(selectedHandIdx, selectedDeployPos);
        targets.forEach(function(p) {
            var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
            if (cell) cell.classList.add('cell-attack');
        });
    }

    if (selectedMinionId !== null) {
        // Highlight minion's cell as selected
        var minion = null;
        (gameState.minions || []).forEach(function(m) { if (m.instance_id === selectedMinionId) minion = m; });
        if (minion) {
            var mCell = document.querySelector('.board-cell[data-row="' + minion.position[0] + '"][data-col="' + minion.position[1] + '"]');
            if (mCell) mCell.classList.add('cell-selected');
        }

        if (interactionMode === 'move' || interactionMode === 'move_attack') {
            var movePos = getMovePositions(selectedMinionId);
            movePos.forEach(function(p) {
                var cell = document.querySelector('.board-cell[data-row="' + p[0] + '"][data-col="' + p[1] + '"]');
                if (cell) cell.classList.add('cell-valid');
            });
        }

        if (interactionMode === 'attack' || interactionMode === 'move_attack') {
            // Bug 1 unification: render the attack-range footprint AND the
            // bright valid-target highlight, mirroring the post-move-attack
            // pick UI. Range tiles are computed client-side from the source
            // minion's card range using the same geometry as engine
            // _can_attack (action_resolver.py). This is a cosmetic / UX
            // change only — actual legal targets still come from
            // legalActions via getAttackTargets().
            var srcMinion = null;
            (gameState.minions || []).forEach(function(m) {
                if (m.instance_id === selectedMinionId) srcMinion = m;
            });
            if (srcMinion) {
                var srcCard = cardDefs[srcMinion.card_numeric_id];
                var range = (srcCard && srcCard.attack_range != null) ? srcCard.attack_range : 0;
                var sr = srcMinion.position[0], sc = srcMinion.position[1];
                for (var rr = 0; rr < 5; rr++) {
                    for (var cc = 0; cc < 5; cc++) {
                        if (rr === sr && cc === sc) continue;
                        var manhattan = Math.abs(rr - sr) + Math.abs(cc - sc);
                        var chebyshev = Math.max(Math.abs(rr - sr), Math.abs(cc - sc));
                        var orthogonal = (rr === sr || cc === sc);
                        var inRange = false;
                        if (range === 0) {
                            inRange = (manhattan === 1 && orthogonal);
                        } else {
                            // Range N star footprint: orthogonal arm reaches
                            // N+1 tiles; diagonal arm reaches chebyshev<=N
                            // along the |dr|==|dc| lines.
                            // Mirrors action_resolver._can_attack.
                            var dr = Math.abs(rr - sr);
                            var dc = Math.abs(cc - sc);
                            var orthogonalInRange = orthogonal && manhattan <= range + 1;
                            var onDiagonal = (dr === dc && dr >= 1 && chebyshev <= range);
                            inRange = orthogonalInRange || onDiagonal;
                        }
                        if (inRange) {
                            var tile = document.querySelector('.board-cell[data-row="' + rr + '"][data-col="' + cc + '"]');
                            if (tile) tile.classList.add('attack-range-footprint');
                        }
                    }
                }
            }
            var atkTargets = getAttackTargets(selectedMinionId);
            (gameState.minions || []).forEach(function(m) {
                if (atkTargets.indexOf(m.instance_id) !== -1) {
                    var cell = document.querySelector('.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
                    if (cell) {
                        cell.classList.add('cell-attack');
                        cell.classList.add('attack-valid-target');
                    }
                }
            });
        }
    }
}

// Highlight playable hand cards
function updateHandHighlights() {
    if (isReactWindow()) {
        // Timing audit (2026-07-06): react glow only for the seat that may
        // actually react (live games; sandbox god-view keeps both).
        if (!sandboxMode && gameState && myPlayerIdx != null
                && gameState.react_player_idx != null
                && gameState.react_player_idx !== myPlayerIdx) {
            document.querySelectorAll('.card-frame-hand').forEach(function(card) {
                card.classList.remove('card-playable', 'card-selected-hand', 'card-react-playable');
            });
            return;
        }
        var reactIdxMap = getLegalReactCardIndices();
        // Sandbox: card_index in legalActions refers to react_player's
        // hand only. Restrict the playable glow to that hand's DOM
        // mount so the OTHER player's cards don't falsely light up.
        var reactOnlyContainer = null;
        if (sandboxMode && gameState) {
            reactOnlyContainer = document.getElementById(
                'sandbox-hand-p' + gameState.react_player_idx);
        }
        document.querySelectorAll('.card-frame-hand').forEach(function(card) {
            var idx = parseInt(card.dataset.handIdx, 10);
            card.classList.remove('card-playable', 'card-selected-hand');
            var inReactHand = !reactOnlyContainer || reactOnlyContainer.contains(card);
            if (inReactHand && reactIdxMap[idx]) {
                card.classList.add('card-react-playable');
            } else {
                card.classList.remove('card-react-playable');
            }
        });
        return;
    }
    // Sandbox has both hands in the DOM, so card_index alone is ambiguous.
    // Scope the "selected" / "playable" state to the ACTIVE player's hand
    // container; the other side's matching index stays inert.
    var activeContainer = null;
    if (sandboxMode && gameState) {
        activeContainer = document.getElementById(
            'sandbox-hand-p' + gameState.active_player_idx);
    }
    // Timing audit (2026-07-06): the playable glow only lights when the
    // player can genuinely act NOW — queue idle, legal actions held, any
    // react window ours. Mid-drain renders (draw beats, deferred refreshes,
    // anim-queue frames) run against the batch's FINAL legalActions and
    // used to light next-turn affordances during the opponent's animations.
    var _actNow = (typeof canActNow !== 'function') || canActNow();
    document.querySelectorAll('.card-frame-hand').forEach(function(card) {
        var idx = parseInt(card.dataset.handIdx, 10);
        card.classList.remove('card-playable', 'card-selected-hand', 'card-react-playable', 'card-confirm-armed');
        if (!_actNow) return;
        var inActiveHand = !activeContainer || activeContainer.contains(card);
        if (inActiveHand && selectedHandIdx === idx && interactionMode === 'confirm') {
            card.classList.add('card-confirm-armed');
        } else if (inActiveHand && selectedHandIdx === idx && (interactionMode === 'play' || interactionMode === 'target')) {
            card.classList.add('card-selected-hand');
        } else if (inActiveHand && canPlayCard(idx)) {
            card.classList.add('card-playable');
        }
    });
}

// Render action bar (pass / draw buttons) — lives ABOVE the hand so all
// player actions (cards, draw, skip, decline) are grouped together.
// Clear the Pass/Skip/Cancel buttons immediately (e.g. when a drain starts)
// so they don't linger through animations; renderActionBar rebuilds them at
// drain-end. Preserves the separately-managed decline-post-move button.
function hideActionBarButtons() {
    var slot = document.getElementById('hand-action-bar');
    if (!slot) return;
    var keep = document.getElementById('decline-post-move-attack-btn');
    slot.innerHTML = '';
    if (keep) slot.appendChild(keep);
}

function renderActionBar() {
    var slot = document.getElementById('hand-action-bar');
    // Phase 14.4: spectators have no action bar whatsoever.
    if (isSpectator) {
        if (slot) slot.innerHTML = '';
        var hintSpec = document.getElementById('how-to-play-hint');
        if (hintSpec) hintSpec.style.display = 'none';
        return;
    }
    // Preserve the decline-post-move-attack button if present (managed
    // separately); rebuild only the draw/skip buttons.
    if (slot) {
        var keep = document.getElementById('decline-post-move-attack-btn');
        slot.innerHTML = '';
        if (keep) slot.appendChild(keep);
    }
    var hint = document.getElementById('how-to-play-hint');

    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) {
        if (hint) hint.style.display = 'none';
        // Audit fix (2026-07-06): this early return used to skip the
        // floating Skip React refresh entirely, so once legalActions went
        // empty (we stopped being the decision-maker) the pill could NEVER
        // be re-hidden — it stayed up through the opponent's react window,
        // their whole turn, and game over. Refresh here too: canSkip is
        // false with empty legalActions, so this hides it.
        _refreshFloatingSkipReact();
        return;
    }

    // Auto-skip behavior gated by the user's react-prompt mode (AUTO/OFF):
    //   OFF  — auto-skip ALWAYS, even if a react card is playable. Useful
    //          when you trust the engine and want minimum interruptions.
    //   AUTO — auto-skip ONLY when no react card is legal (current default).
    //          Pauses for you when you actually have a viable react.
    //   ('ON' — never auto-skip — REMOVED per user 2026-07-10; the fake
    //   response-wait hourglass masks the information leak it existed for.)
    //
    // Sandbox NOTE: `SandboxSession.apply_action` already drains trivial
    // PASS-only REACT windows server-side and emits one frame per
    // intermediate state (commit 9c414f9). The intermediate frame the
    // server emits mid-drain has `phase==REACT` and `legal==[PASS]`,
    // which EXACTLY trips this auto-skip and causes the client to fire a
    // bogus PASS. That PASS arrives at the server AFTER the drain has
    // already advanced to ACTION phase, where PASS is routed to
    // `_apply_pass` — inflicting FATIGUE_DAMAGE (5) on the active player
    // AND flipping the turn a second time. Visible symptoms: phase-LED
    // thrash (END/START cycle twice in ~1s), active-player ping-pong,
    // phantom "-5 HP" popup. Sandbox is god-view with no pace-gated
    // opponent — the auto-skip provides zero value here (the server
    // already handles the drain) and actively breaks the per-frame
    // signal contract. Skip it entirely in sandbox mode.
    if (!sandboxMode
            && gameState.phase === 1
            && legalActions.some(function(a) { return a.action_type === 4; })) {
        var mode = _reactPromptMode();
        var onlyPass = legalActions.length === 1 && legalActions[0].action_type === 4;
        if (mode === 'off' || (mode === 'auto' && onlyPass)) {
            // Audit fix (2026-07-06): hide the floating pill before the
            // auto-PASS — previously it was shown first, then stranded on
            // screen for a window that was already auto-closed.
            var fsbAuto = document.getElementById('floating-skip-react-btn');
            if (fsbAuto) fsbAuto.hidden = true;
            submitAction({ action_type: 4 });
            return;
        }
        // mode === 'auto' && hasReactOption: fall through and let
        // renderActionBar / floating button drive the manual click.
    }

    // Show/refresh the floating Skip React button only AFTER the auto-skip
    // decision above declined to fire (audit fix 2026-07-06).
    _refreshFloatingSkipReact();

    // Action bar: show Pass / Skip React button.
    // Turn-structure redesign (2026-07): DRAW is no longer a legal action —
    // the turn-start auto-draw covers it — so the old "Draw Card" button is
    // GONE. In its place, ACTION phase shows a free "Pass" button (PASS no
    // longer deals fatigue damage; two consecutive passes seal a Handshake).
    if (slot) {
        // Turn ownership (user 2026-07-08): show Pass/Skip ONLY when it is
        // actually THIS player's turn to act — not merely when a PASS action
        // exists in legalActions. In preview/god-view legalActions reflects
        // the ACTIVE player (the dummy), which kept the Pass button up through
        // the opponent's whole turn. Sandbox (no seat) keeps god-view.
        var _myTurnToAct = (typeof myPlayerIdx !== 'number')
            ? true
            : (gameState.phase === 1
                ? gameState.react_player_idx === myPlayerIdx
                : gameState.active_player_idx === myPlayerIdx);
        if (gameState.phase === 1) {
            // REACT phase: show Skip React button (only when player has react cards available)
            var canPass = canShowPassButton();
            if (canPass) {
                var skipBtn = document.createElement('button');
                skipBtn.className = 'btn btn-action btn-pass';
                skipBtn.textContent = 'Skip React';
                skipBtn.addEventListener('click', function() {
                    submitAction({ action_type: 4 });
                });
                slot.appendChild(skipBtn);
            }
        } else {
            // ACTION phase (variant v4.2, user 2026-07-11): the engine
            // offers exactly ONE skip — Rest (DRAW slot, 3: +1 mana AND
            // +1 draw) until a magic is cast this turn, after which it
            // transforms into Pass (4: no benefit). Render whichever is
            // legal in the same slot; standard rules only ever offer Pass.
            var canPassAction = canShowSkipButton(4);
            var restLegal = canShowSkipButton(3);
            if (canPassAction || restLegal) {
                var actionCol = document.createElement('div');
                actionCol.className = 'action-bar-col';
                if (restLegal) {
                    var restBtn = document.createElement('button');
                    restBtn.className = 'btn btn-action btn-rest-action';
                    restBtn.textContent = 'Rest';
                    restBtn.title = 'Rest — gain 1 mana and draw a card (uses your action). '
                        + 'Counts toward the Handshake like a pass';
                    restBtn.addEventListener('click', function() {
                        submitAction({ action_type: 3 });
                    });
                    actionCol.appendChild(restBtn);
                }
                if (canPassAction) {
                    var passBtn = document.createElement('button');
                    passBtn.className = 'btn btn-action btn-pass btn-pass-action';
                    passBtn.textContent = 'Pass';
                    passBtn.title = 'Pass — no benefit. 2nd consecutive pass '
                        + 'seals a Handshake (both players gain a mana and draw a card)';
                    passBtn.addEventListener('click', function() {
                        submitAction({ action_type: 4 });
                    });
                    actionCol.appendChild(passBtn);
                }
                slot.appendChild(actionCol);
            }
        }

        // Bug 1 unification: when a minion is selected in a standalone
        // attack/move mode (NOT the pending post-move flow, which has its
        // own Decline button), show a Cancel button so the player has a
        // clear escape from the selection. Mirrors the post-move flow's
        // affordance and makes the two attack paths feel symmetric.
        if (gameState.phase !== 1
                && selectedMinionId !== null
                && interactionMode !== 'post_move_attack_pick'
                && (interactionMode === 'attack'
                    || interactionMode === 'move'
                    || interactionMode === 'move_attack')) {
            var cancelBtn = document.createElement('button');
            cancelBtn.className = 'btn btn-action btn-decline-attack';
            cancelBtn.textContent = 'Cancel';
            cancelBtn.title = 'Deselect this minion';
            cancelBtn.addEventListener('click', function() {
                clearSelection();
                hideMinionActionMenu();
                highlightBoard();
                updateHandHighlights();
                renderActionBar();
            });
            slot.appendChild(cancelBtn);
        }
    }

    // Show the hint during ACTION phase only (not during react)
    if (hint) {
        if (gameState.phase === 1) {
            hint.style.display = 'none';
        } else {
            hint.style.display = '';
        }
    }
}


// =============================================
// PREGAME (user 2026-07-08): Rock-Paper-Scissors + Mulligan
// =============================================
// Server flow: pregame_rps -> rps_pick -> rps_result (tie replays the
// round) -> pregame_mulligan -> mulligan_pick -> the normal game_start,
// followed by one engine_events batch of card_drawn(source:'mulligan')
// so the replacement cards fly into the hand via the existing draw path.
// All modals reuse the .tutor-modal chrome (vintage restyle lives in
// zz-overrides.css) and mount via _stageMount() -- on the lobby screen
// that resolves to document.body, where .tutor-modal-overlay is a fixed
// fullscreen overlay. Spectators only ever see pregame_status toasts.

var RPS_GLYPHS = { rock: '🪨', paper: '📄', scissors: '✂️' };
var RPS_LABELS = { rock: 'Rock', paper: 'Paper', scissors: 'Scissors' };
var _pregameClashRunning = false;
var _pregamePendingMulligan = null;

function onPregameRps(data) {
    window._pregameActive = true;
    // Bring up the duel stage NOW (user 2026-07-08: 'the mulligan is showing
    // in the lobby') — the empty board skeleton backs the pregame modals
    // instead of the lobby form. game_start re-runs the full setup later.
    try {
        if (typeof showScreen === 'function') {
            showScreen('screen-game');
            if (typeof _fitDuelScale === 'function') _fitDuelScale();
        }
    } catch (e) { /* defensive */ }
    try { showRpsPickModal(data || {}); } catch (e) { /* defensive */ }
}

// Pregame overlays mount on <body> (no scaled game stage exists yet) —
// size them to the viewport with the same min(vw/844, vh/390) ratio the
// design box uses. CSS can't do this (scale() needs a unitless number,
// --mfu is a px length), so it's set here.
function _pregameScaleEl(el) {
    // Deferred: the caller scales BEFORE the overlay is mounted, so the
    // ancestor check must wait a tick. Inside the scaled .game-layout (the
    // normal case — pregame switches to the duel screen first) the design
    // box already scales everything; adding a transform here DOUBLE-scaled
    // (user 2026-07-08). Only scale on a genuine body-mount fallback.
    setTimeout(function() {
        try {
            if (!el.isConnected) return;
            if (el.closest && el.closest('.game-layout')) {
                el.style.transform = '';
                return;
            }
            var sc = Math.min(window.innerWidth / 844, window.innerHeight / 390);
            if (sc > 1.05) {
                el.style.transform = 'scale(' + sc.toFixed(3) + ')';
                el.style.transformOrigin = 'center center';
            }
        } catch (e) { /* defensive */ }
    }, 0);
}

function showRpsPickModal(data) {
    closeRpsModal();
    closeMulliganModal();

    var overlay = document.createElement('div');
    overlay.className = 'tutor-modal-overlay pregame-rps-overlay';
    overlay.id = 'pregame-rps-overlay';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal pregame-rps-modal';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = 'Rock, Paper, Scissors';
    header.appendChild(title);
    var sub = document.createElement('div');
    sub.className = 'tutor-modal-deckline';
    sub.textContent = 'Winner goes first';
    header.appendChild(sub);
    modal.appendChild(header);

    var selectedPick = null;
    var row = document.createElement('div');
    row.className = 'rps-tile-row';

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var acceptBtn = document.createElement('button');
    acceptBtn.className = 'tutor-accept-button';
    acceptBtn.textContent = 'Accept';
    acceptBtn.disabled = true;
    acceptBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (!selectedPick) return;
        socket.emit('rps_pick', { pick: selectedPick });
        _rpsShowWaiting(modal, selectedPick);
    });
    footer.appendChild(acceptBtn);

    ['rock', 'paper', 'scissors'].forEach(function(pick) {
        var tile = document.createElement('div');
        tile.className = 'rps-tile';
        tile.setAttribute('data-pick', pick);
        tile.innerHTML =
            '<div class="rps-tile-glyph">' + RPS_GLYPHS[pick] + '</div>' +
            '<div class="rps-tile-label">' + RPS_LABELS[pick] + '</div>';
        tile.addEventListener('click', function(e) {
            e.stopPropagation();
            var all = row.querySelectorAll('.rps-tile-selected');
            for (var i = 0; i < all.length; i++) all[i].classList.remove('rps-tile-selected');
            tile.classList.add('rps-tile-selected');
            selectedPick = pick;
            acceptBtn.disabled = false;
        });
        row.appendChild(tile);
    });
    modal.appendChild(row);
    modal.appendChild(footer);

    overlay.appendChild(modal);
    _pregameScaleEl(modal);
    // Block background clicks -- the pick is mandatory.
    overlay.addEventListener('click', function(e) { e.stopPropagation(); });
    _stageMount().appendChild(overlay);

    // Reconnect resync: the server echoes an already-recorded pick.
    if (data && data.already_picked) {
        selectedPick = data.already_picked;
        _rpsShowWaiting(modal, selectedPick);
    }
}

// Swap the pick modal body to a waiting state: your pick + a wait line.
function _rpsShowWaiting(modal, pick) {
    var row = modal.querySelector('.rps-tile-row');
    if (row && row.parentNode) row.parentNode.removeChild(row);
    var foot = modal.querySelector('.tutor-modal-footer');
    if (foot && foot.parentNode) foot.parentNode.removeChild(foot);
    if (modal.querySelector('.rps-waiting')) return;
    var wait = document.createElement('div');
    wait.className = 'rps-waiting';
    wait.innerHTML =
        '<div class="rps-tile rps-tile-selected rps-tile-static">' +
            '<div class="rps-tile-glyph">' + (RPS_GLYPHS[pick] || '') + '</div>' +
            '<div class="rps-tile-label">' + (RPS_LABELS[pick] || '') + '</div>' +
        '</div>' +
        '<div class="rps-waiting-text">Waiting for opponent…</div>';
    modal.appendChild(wait);
}

function closeRpsModal() {
    var existing = document.getElementById('pregame-rps-overlay');
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
}

function onRpsResult(data) {
    data = data || {};
    closeRpsModal();
    _pregameClashRunning = true;
    var afterClash = function() {
        _pregameClashRunning = false;
        if (data.tie) {
            _pregameBanner('TIE', 'GO AGAIN!');
            try { showRpsPickModal({}); } catch (e) { /* defensive */ }
            return;
        }
        _pregameBanner(data.you_go_first ? 'YOU GO FIRST!' : 'OPPONENT GOES FIRST', '');
        if (_pregamePendingMulligan) {
            var m = _pregamePendingMulligan;
            _pregamePendingMulligan = null;
            setTimeout(function() {
                try { showMulliganModal(m); } catch (e) { /* defensive */ }
            }, 900);
        }
    };
    try {
        _runRpsClash(data, afterClash);
    } catch (e) {
        // Visuals must never wedge the pregame flow.
        afterClash();
    }
}

// Reveal clash: your glyph flies in from the left, theirs from the right,
// brief pause, then the winner scales up with a gold glow while the loser
// dims (both pulse on a tie). Pure CSS keyframes (zz-overrides.css);
// whole beat stays under ~1.6s.
function _runRpsClash(data, done) {
    var prior = document.getElementById('rps-clash-overlay');
    if (prior && prior.parentNode) prior.parentNode.removeChild(prior);
    var overlay = document.createElement('div');
    overlay.id = 'rps-clash-overlay';
    overlay.className = 'rps-clash-overlay';

    var mine = document.createElement('div');
    mine.className = 'rps-tile rps-clash-tile rps-clash-mine';
    mine.innerHTML =
        '<div class="rps-tile-glyph">' + (RPS_GLYPHS[data.your_pick] || '?') + '</div>' +
        '<div class="rps-tile-label">You</div>';
    var theirs = document.createElement('div');
    theirs.className = 'rps-tile rps-clash-tile rps-clash-theirs';
    theirs.innerHTML =
        '<div class="rps-tile-glyph">' + (RPS_GLYPHS[data.opp_pick] || '?') + '</div>' +
        '<div class="rps-tile-label">Opponent</div>';
    // Both tiles live in a zero-size arena pinned at the overlay centre; each
    // tile straddles that centre via its own transform: translate. Scaling the
    // ARENA (not each tile) grows the pair AND the gap between them uniformly,
    // so the clash reads the same size relative to the window on phone and
    // desktop. Per-tile scaling can't do this: `scale: var(--mfu)` is invalid
    // (--mfu is a length, not a number, so it's silently ignored — the reason
    // the clash rendered design-size-tiny on desktop) and a per-tile
    // transform:scale clobbers the centring translate (user 2026-07-09).
    var arena = document.createElement('div');
    arena.className = 'rps-clash-arena';
    arena.appendChild(mine);
    arena.appendChild(theirs);
    overlay.appendChild(arena);
    document.body.appendChild(overlay);
    _pregameScaleEl(arena);

    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        done();
    }
    // Beat 1: fly-in (450ms CSS) + hold -> Beat 2: verdict (800ms) -> done.
    setTimeout(function() {
        try {
            if (data.tie) {
                mine.classList.add('rps-clash-tie');
                theirs.classList.add('rps-clash-tie');
            } else {
                (data.you_go_first ? mine : theirs).classList.add('rps-clash-winner');
                (data.you_go_first ? theirs : mine).classList.add('rps-clash-loser');
            }
        } catch (e) { /* defensive */ }
        setTimeout(finish, 800);
    }, 750);
    setTimeout(finish, 3000); // safety cap
}

// Short banner in the turn-banner vintage style ('You go first!' etc.).
function _pregameBanner(line1, line2) {
    try {
        var priorB = document.querySelector('.turn-transition-banner');
        if (priorB && priorB.parentNode) priorB.parentNode.removeChild(priorB);
        var banner = document.createElement('div');
        banner.className = 'turn-transition-banner pregame-banner';
        banner.innerHTML =
            '<div class="turn-transition-banner-line1"></div>' +
            (line2 ? '<div class="turn-transition-banner-line2"></div>' : '');
        banner.querySelector('.turn-transition-banner-line1').textContent = line1;
        if (line2) banner.querySelector('.turn-transition-banner-line2').textContent = line2;
        var removed = false;
        var remove = function() {
            if (removed) return;
            removed = true;
            if (banner.parentNode) banner.parentNode.removeChild(banner);
        };
        banner.addEventListener('animationend', remove);
        _stageMount().appendChild(banner);
        setTimeout(remove, 2000);
    } catch (e) { /* defensive */ }
}

function onPregameMulligan(data) {
    window._pregameActive = true;
    if (_pregameClashRunning) {
        // Server sends this right behind rps_result -- hold it until the
        // reveal clash finishes so the modal doesn't stomp the animation.
        _pregamePendingMulligan = data || {};
        return;
    }
    try { showMulliganModal(data || {}); } catch (e) { /* defensive */ }
}

function showMulliganModal(data) {
    closeMulliganModal();
    closeRpsModal();
    var hand = (data && data.hand) || [];
    var selected = [];   // [{idx, nid, tile}]

    var overlay = document.createElement('div');
    overlay.className = 'tutor-modal-overlay pregame-mull-overlay';
    overlay.id = 'pregame-mull-overlay';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal pregame-mull-modal';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = 'Mulligan — select cards to redraw';
    header.appendChild(title);
    var counter = document.createElement('div');
    counter.className = 'tutor-modal-deckline';
    counter.textContent = 'Redraw 0';
    header.appendChild(counter);
    modal.appendChild(header);

    var fan = document.createElement('div');
    fan.className = 'tutor-modal-cards';

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var acceptBtn = document.createElement('button');
    acceptBtn.className = 'tutor-accept-button';
    acceptBtn.textContent = 'Keep hand';

    function _updateMullAccept() {
        counter.textContent = 'Redraw ' + selected.length;
        acceptBtn.textContent = selected.length
            ? 'Mulligan (' + selected.length + ')' : 'Keep hand';
    }

    hand.forEach(function(nid, idx) {
        var tile = document.createElement('div');
        tile.className = 'tutor-modal-card';
        tile.innerHTML = renderDeckBuilderCard(nid, undefined);
        tile.addEventListener('click', function(e) {
            e.stopPropagation();
            var at = -1;
            for (var si = 0; si < selected.length; si++) {
                if (selected[si].tile === tile) { at = si; break; }
            }
            if (at !== -1) {
                selected.splice(at, 1);
                tile.classList.remove('tutor-card-selected');
            } else {
                selected.push({ idx: idx, nid: nid, tile: tile });
                tile.classList.add('tutor-card-selected');
                try { showGameTooltip(nid, tile, null, { force: true }); } catch (e2) { /* defensive */ }
            }
            _updateMullAccept();
        });
        fan.appendChild(tile);
    });
    modal.appendChild(fan);

    acceptBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        var indices = selected.map(function(s) { return s.idx; });
        // Decorative: the picked cards fly to the deck pile as ghosts.
        try {
            selected.forEach(function(s) { _mullFlyToDeck(s.tile, s.nid); });
        } catch (e2) { /* defensive */ }
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        socket.emit('mulligan_pick', { hand_indices: indices });
        if (!(data && data.opponent_resolved)) {
            _pregameToast('Waiting for opponent…');
        }
    });
    footer.appendChild(acceptBtn);
    modal.appendChild(footer);

    overlay.appendChild(modal);
    _pregameScaleEl(modal);
    overlay.addEventListener('click', function(e) { e.stopPropagation(); });
    _stageMount().appendChild(overlay);
}

function closeMulliganModal() {
    var existing = document.getElementById('pregame-mull-overlay');
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
}

// card_fly-style ghost from a mulliganed tile to the own deck pile.
// Decorative only -- the authoritative shuffle happens server-side.
function _mullFlyToDeck(tile, nid) {
    var from = tile.getBoundingClientRect();
    if (!from || !from.width) return;
    var def = (typeof allCardDefs !== 'undefined' && allCardDefs && allCardDefs[nid])
        || (typeof cardDefs !== 'undefined' && cardDefs && cardDefs[nid]);
    if (!def) return;
    // Destination: the own deck pile cell when the duel screen is live;
    // pregame runs over the lobby, so fall back to the bottom-left corner
    // (where the deck sits once the game renders).
    var to = null;
    try {
        var cell = document.querySelector(
            '.screen.active .pile-board[data-side="own"] .pile-cell[data-pile="deck"]');
        if (cell) {
            var r = cell.getBoundingClientRect();
            if (r.width > 0) to = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }
    } catch (e) { /* defensive */ }
    if (!to) to = { x: window.innerWidth * 0.10, y: window.innerHeight * 0.85 };

    var ghost = document.createElement('div');
    ghost.className = 'card-fly-ghost';
    ghost.style.left = from.left + 'px';
    ghost.style.top = from.top + 'px';
    ghost.style.width = from.width + 'px';
    ghost.style.height = from.height + 'px';
    ghost.innerHTML = renderCardFrame(def, {
        context: 'hand',
        numericId: nid,
        interactive: false,
        showReactDeploy: false,
    });
    document.body.appendChild(ghost);

    var dx = to.x - (from.left + from.width / 2);
    var dy = to.y - (from.top + from.height / 2);
    void ghost.offsetWidth;
    ghost.style.transform = 'translate(' + dx + 'px, ' + dy + 'px) scale(0.18)';
    ghost.style.opacity = '0';

    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
    }
    ghost.addEventListener('transitionend', finish);
    setTimeout(finish, 800);
}

// Initial-hand deal (user 2026-07-10): after the mulligan resolves and the
// duel renders, the KEPT hand flies from the deck pile into its slots with
// a small stagger instead of popping in statically. Mulligan replacement
// draws (card_drawn source:'mulligan') still fly via the normal draw path;
// hidden slots register in the F9c in-flight registry so a concurrent
// renderHand rebuild re-hides them instead of showing doubles.
function animateInitialHandDeal() {
    try {
        var handEl = document.getElementById('hand-container');
        if (!handEl || typeof renderCardFrame !== 'function') return;
        var slots = handEl.querySelectorAll('.card-frame-hand');
        if (!slots.length) return;
        var handIds = (gameState && gameState.players
            && typeof myPlayerIdx === 'number'
            && gameState.players[myPlayerIdx])
            ? gameState.players[myPlayerIdx].hand : null;
        if (!Array.isArray(handIds)) return;
        var from = (typeof _resolveDrawFromPoint === 'function')
            ? _resolveDrawFromPoint('deck')
            : { x: window.innerWidth * 0.10, y: window.innerHeight * 0.85 };
        if (!window.__inFlightHandSlots) window.__inFlightHandSlots = {};
        Array.prototype.forEach.call(slots, function(slotEl, i) {
            var nid = handIds[i];
            var def = cardDefs && cardDefs[nid];
            var toRect = slotEl.getBoundingClientRect();
            if (def == null || !toRect.width) return;
            var slotKey = 'nid:' + nid;
            window.__inFlightHandSlots[slotKey] = (window.__inFlightHandSlots[slotKey] | 0) + 1;
            slotEl.style.visibility = 'hidden';
            setTimeout(function() {
                var floater = document.createElement('div');
                floater.className = 'draw-fly-in';
                floater.style.left = toRect.left + 'px';
                floater.style.top = toRect.top + 'px';
                floater.style.width = toRect.width + 'px';
                floater.style.height = toRect.height + 'px';
                floater.style.setProperty('--draw-fly-dx',
                    (from.x - (toRect.left + toRect.width / 2)) + 'px');
                floater.style.setProperty('--draw-fly-dy',
                    (from.y - (toRect.top + toRect.height / 2)) + 'px');
                floater.innerHTML = renderCardFrame(def, {
                    context: 'hand',
                    numericId: nid,
                    interactive: false,
                    showReactDeploy: false,
                });
                document.body.appendChild(floater);
                var finished = false;
                function finish() {
                    if (finished) return;
                    finished = true;
                    if (floater.parentNode) floater.parentNode.removeChild(floater);
                    try {
                        var reg = window.__inFlightHandSlots;
                        if (reg && reg[slotKey]) {
                            reg[slotKey] = reg[slotKey] - 1;
                            if (reg[slotKey] <= 0) delete reg[slotKey];
                        }
                    } catch (e) { /* defensive */ }
                    var live = (typeof _resolveInFlightSlot === 'function')
                        ? _resolveInFlightSlot(handEl, slotKey) : null;
                    if (live) live.style.visibility = '';
                    slotEl.style.visibility = '';
                }
                floater.addEventListener('animationend', finish);
                setTimeout(finish, 800);
            }, i * 110);
        });
        playSfx('card_play');
    } catch (e) { /* defensive — the deal is decorative */ }
}

// Spectator / waiting status line. Persists until replaced or cleaned up
// by cleanupPregameUI on game_start.
function onPregameStatus(data) {
    var msg = (data && data.msg) || '';
    if (!msg) return;
    _pregameToast(msg);
}

function _pregameToast(msg) {
    try {
        var t = document.getElementById('pregame-status-toast');
        if (!t) {
            t = document.createElement('div');
            t.id = 'pregame-status-toast';
            t.className = 'tutor-toast';
            _stageMount().appendChild(t);
        }
        t.textContent = msg;
    } catch (e) { /* defensive */ }
}

// Called from onGameStart: the game proper is starting -- tear down every
// pregame artifact so nothing lingers over the duel screen.
function cleanupPregameUI() {
    window._pregameActive = false;
    _pregameClashRunning = false;
    _pregamePendingMulligan = null;
    ['pregame-rps-overlay', 'pregame-mull-overlay', 'rps-clash-overlay',
     'pregame-status-toast'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el && el.parentNode) el.parentNode.removeChild(el);
    });
}
