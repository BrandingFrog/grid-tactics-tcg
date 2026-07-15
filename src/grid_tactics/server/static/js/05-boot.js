// =============================================
// Section 8: DOMContentLoaded
// =============================================

// One-layout scaling for the duel/sandbox: the 844x390 design box is scaled
// by --duel-scale to fit the viewport (see the DUEL SCALE ROOT css block).
function _fitDuelScale() {
    // Audit fix (2026-07-07): when the sandbox nav bar is shown it eats
    // 54px of height — scale against the REMAINING space or the bar
    // overlays and chops the stage top.
    var navH = document.body.classList.contains('sbx-show-nav') ? 54 : 0;
    var h = Math.max(1, window.innerHeight - navH);
    document.documentElement.style.setProperty('--duel-scale',
        String(Math.min(window.innerWidth / 844, h / 390)));
    document.documentElement.style.setProperty('--duel-nav-h', navH + 'px');
}
window.addEventListener('resize', _fitDuelScale);

document.addEventListener('DOMContentLoaded', function() {
    _fitDuelScale();
    initSocket();
    setupLobbyHandlers();
    setupDeckBuilderHandlers();
    setupDeckFilters();
    setupDeckDragAndDrop();
    setupGameTooltipPin();
    setupBoardGapForgiveness();
    setupTooltipTabs();
    setupLogToolbar();
    setupLobbyQuickview();
    setupNavHandlers();
    setupActivityTabs();
    setupGameHandlers();
    setupPileHandlers();
    _wireReactModeButtonsOnce();
    _wireFloatingSkipReactOnce();
    _wireDeckReadinessMeter();
});

// =============================================
// Phase 14.5 Wave 5: Pile UI (grave / exhaust viewer + opp hand row)
// =============================================

// Shared modal for all four pile buttons. Renders every card in the pile as
// a full YGO-style frame via renderCardFrame(context: 'pile').
// Phase 14.6-03: Optional third arg `sandboxCtx = { pileType, playerIdx }`
// injects a "Move to..." button into each card cell when sandboxMode is true.
// Mount point for in-game popups (user 2026-07-06): inside the active
// screen's scaled layout, so overlays grey the BOARD AREA (right of the
// tooltip column) instead of the whole viewport. Falls back to body.
function _stageMount() {
    return document.querySelector('.screen.active .game-layout') || document.body;
}

// Shared board-modal minimise controller.  A minimised decision is a
// read-only peek: the SAME overlay node stays alive (so selections, scroll,
// form fields and closure state survive), while every gameplay mutation is
// gated until the player restores it.  Restore controls live in a tray so
// independently minimised windows never overlap each other.
function _boardModalRestoreTray() {
    var host = _stageMount();
    var tray = document.getElementById('board-modal-restore-tray');
    if (!tray) {
        tray = document.createElement('div');
        tray.id = 'board-modal-restore-tray';
        tray.className = 'board-modal-restore-tray';
        tray.setAttribute('role', 'group');
        tray.setAttribute('aria-label', 'Minimised windows');
    }
    if (tray.parentNode !== host) host.appendChild(tray);
    return tray;
}

function isBoardModalPeekActive() {
    var tray = document.getElementById('board-modal-restore-tray');
    return !!(tray && tray.children && tray.children.length);
}

// A second decision can legitimately arrive while an informational window
// is minimised (for example, a Pile peek followed by a Fortune round).  Its
// own visible Accept button may resolve that decision, while the board and
// the actually minimised window remain inert.
function canResolveVisibleBoardModal(overlayOrId) {
    var overlay = typeof overlayOrId === 'string'
        ? document.getElementById(overlayOrId) : overlayOrId;
    return !!(overlay && overlay.parentNode && !overlay._boardModalIsMinimized
        && !overlay.hidden && overlay.style.display !== 'none');
}

function canResolvePendingBoardDecisionDuringPeek() {
    if (typeof interactionMode === 'undefined') return false;
    if (interactionMode === 'revive_place') {
        // Revive deliberately keeps its non-blocking instruction window on
        // screen during tile placement. If THAT window is the minimised one,
        // the choice is still read-only; an unrelated old pill must not
        // deadlock the visible Revive placement.
        return canResolveVisibleBoardModal('revive-modal-overlay');
    }
    return interactionMode === 'post_move_attack_pick'
        || interactionMode === 'death_target_pick'
        || interactionMode === 'conjure_deploy';
}

function _refreshBoardPeekAffordances() {
    try {
        var peekActive = isBoardModalPeekActive();
        if (document.body && document.body.classList) {
            document.body.classList.toggle(
                'board-modal-peek-active', peekActive
            );
        }
        // Sandbox cheats bypass submitAction(), so freeze their native
        // controls explicitly during a read-only board peek.  Remember each
        // control's prior state so restore does not accidentally enable a
        // button that was already unavailable for another reason.
        if (typeof document.querySelectorAll === 'function') {
            document.querySelectorAll(
                '#sandbox-control-panel button, #sandbox-control-panel input, '
                + '#sandbox-control-panel select'
            ).forEach(function(control) {
                if (peekActive) {
                    if (!control.hasAttribute('data-peek-prior-disabled')) {
                        control.setAttribute(
                            'data-peek-prior-disabled', control.disabled ? 'true' : 'false'
                        );
                    }
                    control.disabled = true;
                } else if (control.hasAttribute('data-peek-prior-disabled')) {
                    control.disabled = control.getAttribute(
                        'data-peek-prior-disabled'
                    ) === 'true';
                    control.removeAttribute('data-peek-prior-disabled');
                }
            });
        }
        if (typeof updateHandHighlights === 'function') updateHandHighlights();
        if (typeof highlightBoard === 'function') highlightBoard();
        if (typeof renderActionBar === 'function') renderActionBar();
    } catch (e) { /* the controller must never break modal flow */ }
}

function _removeBoardModalRestorePill(restoreId) {
    if (!restoreId) return;
    var pill = document.getElementById(restoreId);
    if (pill && pill.parentNode) pill.parentNode.removeChild(pill);
    var tray = document.getElementById('board-modal-restore-tray');
    if (tray && (!tray.children || tray.children.length === 0)
            && tray.parentNode) {
        tray.parentNode.removeChild(tray);
    }
    _refreshBoardPeekAffordances();
}

function disposeBoardModalMinimizer(overlayOrRestoreId) {
    var overlay = (overlayOrRestoreId && typeof overlayOrRestoreId !== 'string')
        ? overlayOrRestoreId : null;
    var restoreId = typeof overlayOrRestoreId === 'string'
        ? overlayOrRestoreId
        : (overlay && overlay._boardModalRestoreId);
    _removeBoardModalRestorePill(restoreId);
    if (overlay) {
        if (overlay._boardModalIsMinimized) {
            overlay.classList.remove('board-modal-is-minimized');
            overlay.style.display = overlay._boardModalPriorDisplay || '';
            overlay._boardModalIsMinimized = false;
        }
        overlay.removeAttribute('aria-hidden');
        if (overlay._boardModalMinButton) {
            overlay._boardModalMinButton.setAttribute('aria-expanded', 'true');
        }
    }
}

function disposeAllBoardModalMinimizers() {
    var tray = document.getElementById('board-modal-restore-tray');
    if (tray && tray.children) {
        Array.prototype.slice.call(tray.children).forEach(function(pill) {
            var overlay = pill._boardModalOverlay;
            if (!overlay || !overlay._boardModalIsMinimized) return;
            overlay.classList.remove('board-modal-is-minimized');
            overlay.style.display = overlay._boardModalPriorDisplay || '';
            overlay._boardModalIsMinimized = false;
            overlay.removeAttribute('aria-hidden');
            if (overlay._boardModalMinButton) {
                overlay._boardModalMinButton.setAttribute('aria-expanded', 'true');
            }
        });
    }
    if (tray && tray.parentNode) tray.parentNode.removeChild(tray);
    _refreshBoardPeekAffordances();
}

function attachBoardModalMinimizer(config) {
    config = config || {};
    var overlay = config.overlay;
    var controlsHost = config.controlsHost;
    if (!overlay || !controlsHost) return null;
    if (overlay._boardModalMinButton) return overlay._boardModalMinButton;

    var label = config.label || 'window';
    var restoreId = config.restoreId
        || ((overlay.id || 'board-modal') + '-restore-pill');
    var minBtn = document.createElement('button');
    minBtn.type = 'button';
    minBtn.className = 'modal-min-btn tutor-min-btn';
    minBtn.textContent = '\u25be';
    minBtn.title = 'Minimise \u2014 peek at the board';
    minBtn.setAttribute('aria-label', 'Minimise ' + label + ' window');
    minBtn.setAttribute('aria-expanded', 'true');
    if (overlay.id) minBtn.setAttribute('aria-controls', overlay.id);

    overlay._boardModalRestoreId = restoreId;
    overlay._boardModalMinButton = minBtn;
    overlay.setAttribute('data-board-modal-minimisable', 'true');

    minBtn.addEventListener('click', function(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        overlay._boardModalPriorDisplay = overlay.style.display || '';
        overlay._boardModalIsMinimized = true;
        overlay.classList.add('board-modal-is-minimized');
        overlay.style.display = 'none';
        overlay.setAttribute('aria-hidden', 'true');
        minBtn.setAttribute('aria-expanded', 'false');
        try {
            if (typeof config.onMinimize === 'function') config.onMinimize();
        } catch (callbackErr) { /* visual cleanup is best-effort */ }
        _removeBoardModalRestorePill(restoreId);

        var pill = document.createElement('button');
        pill.type = 'button';
        pill.id = restoreId;
        pill.className = 'tutor-restore-pill board-modal-restore-pill';
        pill._boardModalOverlay = overlay;
        pill.textContent = '\u25b4 Resume ' + label;
        pill.setAttribute('aria-label', 'Restore ' + label + ' window');
        if (overlay.id) pill.setAttribute('aria-controls', overlay.id);
        pill.addEventListener('click', function(e2) {
            if (e2) {
                e2.preventDefault();
                e2.stopPropagation();
            }
            if (!overlay.parentNode) {
                _removeBoardModalRestorePill(restoreId);
                return;
            }
            // Restore the overlay before removing its pill. Removing the
            // pill refreshes board affordances; with another pill still in
            // the tray, contextual choices such as Revive must already be
            // visible so their legal tile highlights are repainted.
            overlay.classList.remove('board-modal-is-minimized');
            overlay.style.display = overlay._boardModalPriorDisplay || '';
            overlay._boardModalIsMinimized = false;
            overlay.removeAttribute('aria-hidden');
            minBtn.setAttribute('aria-expanded', 'true');
            _removeBoardModalRestorePill(restoreId);
            try {
                if (typeof config.onRestore === 'function') config.onRestore();
            } catch (callbackErr) { /* visual cleanup is best-effort */ }
            if (typeof minBtn.focus === 'function') minBtn.focus();
        });
        _boardModalRestoreTray().appendChild(pill);
        _refreshBoardPeekAffordances();
        if (typeof pill.focus === 'function') pill.focus();
    });

    if (config.before && config.before.parentNode === controlsHost
            && typeof controlsHost.insertBefore === 'function') {
        controlsHost.insertBefore(minBtn, config.before);
    } else {
        controlsHost.appendChild(minBtn);
    }
    return minBtn;
}

// Minimisable in-page replacement for sandbox confirm()/prompt() calls.
// Returns a Promise resolving to true/false for confirm, a string/null for
// prompt, and the selected value/null for select.
function showBoardDialog(options) {
    options = options || {};
    var prior = document.getElementById('board-dialog-overlay');
    if (prior && typeof prior._boardDialogFinish === 'function') {
        prior._boardDialogFinish(null);
    } else if (prior) {
        disposeBoardModalMinimizer(prior);
        prior.remove();
    }

    return new Promise(function(resolve) {
        var overlay = document.createElement('div');
        overlay.id = 'board-dialog-overlay';
        overlay.className = 'tutor-modal-overlay board-dialog-overlay';
        var modal = document.createElement('div');
        modal.className = 'tutor-modal board-dialog-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', 'board-dialog-title');

        var header = document.createElement('div');
        header.className = 'tutor-modal-header';
        var title = document.createElement('div');
        title.id = 'board-dialog-title';
        title.className = 'tutor-modal-title';
        title.textContent = options.title || 'Confirm';
        header.appendChild(title);
        modal.appendChild(header);

        var body = document.createElement('div');
        body.className = 'board-dialog-body';
        if (options.message) {
            var message = document.createElement('div');
            message.className = 'board-dialog-message';
            message.textContent = options.message;
            body.appendChild(message);
        }

        var input = null;
        if (options.mode === 'prompt') {
            input = document.createElement(options.multiline ? 'textarea' : 'input');
            input.className = 'board-dialog-input';
            if (!options.multiline) input.type = 'text';
            if (options.multiline) input.rows = options.rows || 5;
            input.value = options.value || '';
            input.readOnly = !!options.readOnly;
            input.setAttribute('aria-label', options.inputLabel || options.title || 'Value');
            body.appendChild(input);
        } else if (options.mode === 'select') {
            input = document.createElement('select');
            input.className = 'board-dialog-input board-dialog-select';
            input.setAttribute('aria-label', options.inputLabel || options.title || 'Choice');
            (options.choices || []).forEach(function(choice) {
                var option = document.createElement('option');
                option.value = String(choice.value);
                option.textContent = choice.label;
                input.appendChild(option);
            });
            if (options.value != null) input.value = String(options.value);
            body.appendChild(input);
        }
        modal.appendChild(body);

        var footer = document.createElement('div');
        footer.className = 'tutor-modal-footer board-dialog-footer';
        var finished = false;
        function finish(value) {
            if (finished) return;
            finished = true;
            disposeBoardModalMinimizer(overlay);
            if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
            resolve(value);
        }
        overlay._boardDialogFinish = finish;

        if (options.cancelLabel !== null) {
            var cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'btn btn-secondary';
            cancel.textContent = options.cancelLabel || 'Cancel';
            cancel.addEventListener('click', function() {
                finish(options.mode === 'confirm' ? false : null);
            });
            footer.appendChild(cancel);
        }
        var accept = document.createElement('button');
        accept.type = 'button';
        accept.className = 'tutor-accept-button';
        accept.textContent = options.confirmLabel || 'Accept';
        accept.addEventListener('click', function() {
            if (options.mode === 'confirm') finish(true);
            else if (input) finish(input.value);
            else finish(true);
        });
        footer.appendChild(accept);
        modal.appendChild(footer);
        overlay.appendChild(modal);
        overlay.addEventListener('click', function(e) { e.stopPropagation(); });
        attachBoardModalMinimizer({
            overlay: overlay,
            controlsHost: header,
            label: options.resumeLabel || options.title || 'dialog',
            restoreId: 'board-dialog-restore-pill'
        });
        _stageMount().appendChild(overlay);
        if (input && typeof input.focus === 'function') input.focus();
        else if (typeof accept.focus === 'function') accept.focus();

        overlay.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && options.cancelLabel !== null) {
                e.preventDefault();
                finish(options.mode === 'confirm' ? false : null);
            } else if (e.key === 'Enter' && !options.multiline) {
                e.preventDefault();
                accept.click();
            }
        });
    });
}

function showBoardNotice(message, isError) {
    var old = document.getElementById('board-notice-toast');
    if (old) old.remove();
    var toast = document.createElement('div');
    toast.id = 'board-notice-toast';
    toast.className = 'tutor-toast board-notice-toast'
        + (isError ? ' board-notice-error' : '');
    toast.setAttribute('role', isError ? 'alert' : 'status');
    toast.textContent = message || '';
    _stageMount().appendChild(toast);
    setTimeout(function() {
        if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, isError ? 4200 : 2800);
}

// Hard lifecycle boundary used when a duel/sandbox session is abandoned or
// replaced.  Closing through each modal's own function clears its local
// selection/interaction state as well as the shared restore pill.  The
// generic dialog is also settled so callers are never left with a dangling
// Promise after navigating away.
function closeNonterminalBoardModals() {
    var dialog = document.getElementById('board-dialog-overlay');
    if (dialog && typeof dialog._boardDialogFinish === 'function') {
        dialog._boardDialogFinish(null);
    } else if (dialog) {
        disposeBoardModalMinimizer(dialog);
        dialog.remove();
    }

    if (typeof closeTutorModal === 'function') closeTutorModal();
    if (typeof closeTriggerPickerModal === 'function') closeTriggerPickerModal();
    if (typeof closeReviveModal === 'function') closeReviveModal();
    if (typeof closeRoguelikeEventModal === 'function') closeRoguelikeEventModal();
    if (typeof closeMarkedCardsModal === 'function') closeMarkedCardsModal();
    if (typeof closeTransformPicker === 'function') closeTransformPicker();
    if (typeof hideSacrificePicker === 'function') hideSacrificePicker();
    if (typeof hidePileModal === 'function') hidePileModal();
    if (typeof closeRpsModal === 'function') closeRpsModal();
    if (typeof closeMulliganModal === 'function') closeMulliganModal();
    if (typeof closeBugReporterModal === 'function') closeBugReporterModal();
}

function closeAllBoardModalsForReset() {
    closeNonterminalBoardModals();
    if (typeof hideGameOver === 'function') hideGameOver();
    disposeAllBoardModalMinimizers();

    var notice = document.getElementById('board-notice-toast');
    if (notice) notice.remove();
}

var _openPileModalContext = null;

function showPileModal(title, cardNumericIds, sandboxCtx) {
    var modal = document.getElementById('pileModal');
    var titleEl = document.getElementById('pileModalTitle');
    var grid = document.getElementById('pileModalGrid');
    if (!modal || !titleEl || !grid) return;
    if (sandboxCtx && sandboxCtx.playerIdx != null && sandboxCtx.pileType) {
        _openPileModalContext = {
            title: title || 'Pile',
            playerIdx: sandboxCtx.playerIdx,
            pileType: sandboxCtx.pileType,
            sandbox: !!sandboxCtx.sandbox,
        };
    }
    disposeBoardModalMinimizer(modal);
    titleEl.textContent = title || 'Pile';
    // Center over the STAGE (right of the tooltip column): live inside the
    // active screen's scaled layout so the grey-out skips the tooltip panel.
    var layout = document.querySelector('.screen.active .game-layout');
    if (layout && modal.parentElement !== layout) layout.appendChild(modal);
    grid.innerHTML = '';
    // Newest-first (user 2026-07-11): piles append at the END engine-side,
    // but the modal reads left-to-right — reverse a copy so the most
    // recent addition leads.
    var ids = (cardNumericIds || []).slice().reverse();
    if (ids.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'pile-grid-empty';
        empty.textContent = 'Empty.';
        grid.appendChild(empty);
    } else {
        ids.forEach(function(nid, revIdx) {
            var c = (allCardDefs && allCardDefs[nid]) || cardDefs[nid];
            if (!c) return;
            var cell = document.createElement('div');
            cell.className = 'pile-grid-cell';
            cell.innerHTML = renderCardFrame(c, {
                context: 'pile',
                numericId: nid,
                showReactDeploy: false
            });
            // Light Wyrm (2026-07-11): playable-from-exhaust cards get a
            // Summon button in the OWN Exhaust pile when the server offers
            // a legal PLAY_FROM_EXHAUST for them. Click -> close the modal,
            // arm the tile-pick mode (09-duel-interaction submits with the
            // exhaust index).
            try {
                if (!sandboxMode && c.playable_from_exhaust
                        && typeof legalActions !== 'undefined') {
                    var exPlays = (legalActions || []).filter(function(a) {
                        return a.action_type === 19 && a.position
                            && gameState && gameState.players
                            && gameState.players[myPlayerIdx]
                            && gameState.players[myPlayerIdx].exhaust[a.card_index] === nid;
                    });
                    if (exPlays.length) {
                        var playBtn = document.createElement('button');
                        playBtn.className = 'btn btn-secondary pile-exhaust-play';
                        playBtn.textContent = '\u2694 Summon';
                        playBtn.addEventListener('click', function(e) {
                            e.stopPropagation();
                            if (isBoardModalPeekActive()) return;
                            window.__exhaustPlayIdx = exPlays[0].card_index;
                            interactionMode = 'exhaust_play';
                            hidePileModal();
                            try { highlightBoard(); } catch (e2) { /* defensive */ }
                            try {
                                exPlays.forEach(function(a) {
                                    var sel = '#screen-game .board-cell[data-row="'
                                        + a.position[0] + '"][data-col="' + a.position[1] + '"]';
                                    var bc = document.querySelector(sel);
                                    if (bc) bc.classList.add('cell-valid');
                                });
                            } catch (e3) { /* defensive */ }
                        });
                        cell.appendChild(playBtn);
                    }
                }
            } catch (e) { /* defensive — pile stays view-only */ }
            // Highlighting a card previews it in the tooltip panel
            cell.addEventListener('mouseenter', function() {
                showGameTooltip(nid, cell, null, { force: true });
            });
            // Phase 14.6-03: Move-to button in sandbox mode
            if (sandboxMode && sandboxCtx && typeof makeSandboxMoveButton === 'function') {
                var pileType = sandboxCtx.pileType;
                var srcZone;
                if (pileType === 'graveyard') srcZone = 'graveyard';
                else if (pileType === 'exhaust') srcZone = 'exhaust';
                else srcZone = 'deck_top';
                cell.appendChild(makeSandboxMoveButton(sandboxCtx.playerIdx, nid, srcZone));
            }
            grid.appendChild(cell);
        });
    }
    modal.style.display = 'flex';
}

function hidePileModal() {
    _openPileModalContext = null;
    var modal = document.getElementById('pileModal');
    if (modal) {
        disposeBoardModalMinimizer(modal);
        modal.style.display = 'none';
    }
    document.querySelectorAll('.sandbox-move-popover').forEach(function(popover) {
        popover.remove();
    });
}

function refreshOpenPileModal() {
    var ctx = _openPileModalContext;
    var modal = document.getElementById('pileModal');
    if (!ctx || !modal || modal._boardModalIsMinimized) return;
    var state = (ctx.sandbox && typeof sandboxState !== 'undefined' && sandboxState)
        ? sandboxState : gameState;
    var player = state && state.players && state.players[ctx.playerIdx];
    if (!player) return;
    var ids = Array.isArray(player[ctx.pileType]) ? player[ctx.pileType] : [];
    showPileModal(ctx.title, ids, ctx);
}

// Element-only opponent hand info (DESIGNED information leak, 2026-07):
// view_filter emits each opponent hand card's ELEMENT (and nothing else —
// no id/name/cost) so card backs can telegraph deck composition. Accept a
// couple of payload shapes defensively; return null when the server
// doesn't expose elements (older server / god-mode full hand of ints).
function _playerHandElements(p) {
    if (!p) return null;
    if (Array.isArray(p.hand_elements)) return p.hand_elements;
    if (Array.isArray(p.hand) && p.hand.length > 0
            && typeof p.hand[0] === 'object' && p.hand[0] !== null) {
        return p.hand.map(function(e) {
            return (e && e.element != null) ? e.element : null;
        });
    }
    return null;
}

// Apply an element tint to a face-down card back. Neutral (no-op) when the
// element is unknown/null. Uses the same ELEMENT_MAP colors as everywhere
// else in the client so the tint reads consistently.
function _tintCardBack(backEl, element) {
    // Element-tinted backs removed (user 2026-07-06) — all opp hand backs
    // render the neutral warm back. Kept as a no-op so call sites stay.
    return;
    if (!backEl || element == null || !ELEMENT_MAP[element]) return;
    backEl.classList.add('element-back');
    backEl.style.setProperty('--back-tint', ELEMENT_MAP[element].color);
    backEl.title = ELEMENT_MAP[element].name;
    backEl.dataset.element = element;
}

// Render N face-down card backs in the opp hand row. Count + per-card
// element tint only, no identities. `elements` is optional (array of
// element ints, index-aligned with the opponent's hand; null entries and
// missing arrays render neutral backs).
function renderOppHandRow(count, elements) {
    var row = document.getElementById('oppHandRow');
    if (!row) return;
    row.innerHTML = '';
    var n = count | 0;
    for (var i = 0; i < n; i++) {
        var back = document.createElement('div');
        back.className = 'opp-hand-card-back';
        back.style.setProperty('--i', i);
        back.style.setProperty('--n', n);
        var opponentOwnerIdx = (typeof myPlayerIdx === 'number') ? 1 - myPlayerIdx : null;
        if (opponentOwnerIdx != null
                && typeof _isHandDestinationReserved === 'function'
                && _isHandDestinationReserved(opponentOwnerIdx, i, null)) {
            back.style.visibility = 'hidden';
        }
        _tintCardBack(back, (elements && elements.length > i) ? elements[i] : null);
        row.appendChild(back);
    }
    // Width-aware overlap (approved 2026-07 duel layout) — same layout engine as
    // the player hand, at 90% of its max width so the opponent peek stays a hair
    // narrower. Overrides the legacy --i/--n margin calc; the fan rotation stays.
    _layoutHandRow(
        Array.prototype.slice.call(row.querySelectorAll('.opp-hand-card-back')),
        HAND_MAXW * 0.9
    );
}

// Piles live on the pile boards flanking the game board (user 2026-07-05):
// deck/grave/exhaust cells at the board-extension positions (own = E6/D6/D5,
// opponent mirrored top-left). This refreshes every cell's count.
function _pileLen(p, kind) {
    if (!p) return 0;
    // live mode hides deck CONTENTS (empty array) but ships deck_count —
    // a numeric *_count always wins over the possibly-redacted array
    var n = p[kind + '_count'];
    if (typeof n === 'number') return n;
    var v = p[kind];
    if (Array.isArray(v)) return v.length;
    if (typeof v === 'number') return v;
    return 0;
}
// Deck pile extrusion (user 2026-07-07, final): drawn in FLAT layout
// space as an SVG overlay anchored to the cell's PROJECTED corners. The
// base is the cell's real outline (in the tilted plane); the top face is
// that same projected quad translated STRAIGHT UP on screen by the
// count-driven rise; connectors join corresponding corners — so the
// connector lines are screen-vertical by construction, exactly like
// extruding a drawn shape in a technical drawing.
function _projectedQuad(cell, layoutRect, scale) {
    var pts = [];
    var anchors = [
        { left: '0', top: '0' }, { right: '0', top: '0' },
        { right: '0', bottom: '0' }, { left: '0', bottom: '0' },
    ];
    for (var i = 0; i < 4; i++) {
        var probe = document.createElement('div');
        probe.style.cssText = 'position:absolute;width:0;height:0;pointer-events:none;';
        var a = anchors[i];
        for (var k in a) probe.style[k] = a[k];
        cell.appendChild(probe);
        var r = probe.getBoundingClientRect();
        pts.push([(r.left - layoutRect.left) / scale, (r.top - layoutRect.top) / scale]);
        probe.remove();
    }
    return pts;   // [tl, tr, br, bl] in 844x390 design coords
}

function _renderDeckStack(cell, count, topCardId) {
    // Grave/exhaust reuse the deck extrusion (user 2026-07-07) EXCEPT the
    // top face shows the pile's last card face-up instead of the card back.
    var kind = cell.dataset.pile || 'deck';
    var layers = count <= 0 ? 0 : Math.max(1, Math.min(10, Math.ceil(count / 3)));
    cell.classList.toggle('deck-empty', layers === 0);
    var layout = cell.closest('.game-layout');
    if (!layout) return;
    var key = (cell.closest('.pile-board') || {}).dataset
        ? cell.closest('.pile-board').dataset.side : 'x';
    var screenEl = cell.closest('.screen');
    var svgId = 'deck-extrude-' + (screenEl ? screenEl.id : 's') + '-' + key + '-' + kind;
    var svg = document.getElementById(svgId);
    if (layers === 0) { if (svg) svg.remove(); return; }
    var lr = layout.getBoundingClientRect();
    if (!lr.width) return;
    var scale = lr.width / 844;
    var q = _projectedQuad(cell, lr, scale);
    var rise = 4 + (layers - 1) * 2.2;
    var top = q.map(function(p) { return [p[0], p[1] - rise]; });
    // rounded-corner path for an arbitrary quad (SVG polygons can't round)
    var R = function(pts, r) {
        var d = '';
        for (var i = 0; i < pts.length; i++) {
            var p0 = pts[(i + pts.length - 1) % pts.length];
            var p1 = pts[i];
            var p2 = pts[(i + 1) % pts.length];
            var v1 = [p1[0] - p0[0], p1[1] - p0[1]];
            var v2 = [p2[0] - p1[0], p2[1] - p1[1]];
            var l1 = Math.hypot(v1[0], v1[1]) || 1;
            var l2 = Math.hypot(v2[0], v2[1]) || 1;
            var a = [p1[0] - v1[0] / l1 * r, p1[1] - v1[1] / l1 * r];
            var b = [p1[0] + v2[0] / l2 * r, p1[1] + v2[1] / l2 * r];
            d += (i === 0 ? 'M' : 'L') + a[0].toFixed(1) + ' ' + a[1].toFixed(1);
            d += 'Q' + p1[0].toFixed(1) + ' ' + p1[1].toFixed(1) + ' '
               + b[0].toFixed(1) + ' ' + b[1].toFixed(1);
        }
        return d + 'Z';
    };
    var cx = (top[0][0] + top[1][0] + top[2][0] + top[3][0]) / 4;
    var cy = (top[0][1] + top[1][1] + top[2][1] + top[3][1]) / 4;
    // stripe angle follows the cell's SIDE edges (average of the two
    // projected flanks) instead of a fixed 45deg
    var _eL = Math.atan2(q[3][1] - q[0][1], q[3][0] - q[0][0]);
    var _eR = Math.atan2(q[2][1] - q[1][1], q[2][0] - q[1][0]);
    var stripeDeg = (((_eL + _eR) / 2) * 180 / Math.PI - 90).toFixed(1);
    // the FRONT band's card-seam lines follow the cell's front edge
    var frontDeg = (Math.atan2(q[2][1] - q[3][1], q[2][0] - q[3][0]) * 180 / Math.PI).toFixed(1);
    var NS = 'http://www.w3.org/2000/svg';
    if (!svg) {
        svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('id', svgId);
        svg.setAttribute('class', 'deck-extrude');
        svg.setAttribute('viewBox', '0 0 844 390');
        layout.appendChild(svg);
    }
    var stripes =
        '<defs><pattern id="' + svgId + '-w" width="12" height="12"'
        + ' patternTransform="rotate(45)" patternUnits="userSpaceOnUse">'
        + '<rect width="12" height="12" fill="#251b0d"/>'
        + '<rect width="6" height="12" fill="#41301a"/></pattern>'
        // card paper-edge color + dither for the deck's visible side
        + '<pattern id="' + svgId + '-p" width="4" height="4" patternUnits="userSpaceOnUse">'
        + '<rect width="4" height="4" fill="#e0d3ae"/>'
        + '<rect x="0" y="0" width="1" height="1" fill="#c9b98d"/>'
        + '<rect x="2" y="2" width="1" height="1" fill="#c9b98d"/>'
        + '<rect x="3" y="1" width="1" height="1" fill="#cfc09a"/>'
        + '<rect x="1" y="3" width="1" height="1" fill="#cfc09a"/>'
        + '</pattern>'
        // front band: horizontal card-seam lines along the cell's front edge
        + '<pattern id="' + svgId + '-pf" width="4" height="3" patternUnits="userSpaceOnUse"'
        + ' patternTransform="rotate(' + frontDeg + ')">'
        + '<rect width="4" height="3" fill="#e0d3ae"/>'
        + '<rect y="0" width="4" height="0.9" fill="#c3b183"/>'
        + '<rect x="1" y="1.8" width="1" height="0.6" fill="#cfc09a"/>'
        + '</pattern></defs>';
    // only the far-back-LEFT (tl) and front-forward-RIGHT (br) connectors.
    // Endpoints sit at the ROUNDED-CORNER tangent points (user 2026-07-07):
    //   TL: where the arc begins on the LEFT edge (r below the corner);
    //   BR: where the arc begins on the RIGHT edge (r above the corner).
    var _tang = function(pts, i, r) {
        var toward = pts[3 - i];   // tl->bl, tr->br, br->tr, bl->tl (side edges)
        var pC = pts[i];
        var v = [toward[0] - pC[0], toward[1] - pC[1]];
        var l = Math.hypot(v[0], v[1]) || 1;
        return [pC[0] + v[0] / l * r, pC[1] + v[1] / l * r];
    };
    // OWN deck: back-left (tl) + front-right (br) edges visible.
    // OPP deck (mirrored plane): front-left (bl) + back-right (tr).
    var lines = '';
    (key === 'opp' ? [1, 3] : [0, 2]).forEach(function(i) {
        var a = _tang(q, i, 5);
        var b = _tang(top, i, 5);
        lines += '<line x1="' + a[0].toFixed(1) + '" y1="' + a[1].toFixed(1)
            + '" x2="' + b[0].toFixed(1) + '" y2="' + b[1].toFixed(1)
            + '" stroke="rgba(224,162,60,0.75)" stroke-width="1"/>';
    });
    var topFace, topTexts;
    if (kind === 'deck') {
        topFace = '<path d="' + R(top, 5) + '" fill="url(#' + svgId + '-w)"'
            + ' stroke="rgba(224,162,60,0.8)" stroke-width="1.2"/>';
        topTexts = '<text x="' + cx.toFixed(1) + '" y="' + (cy - 1).toFixed(1) + '" class="dx-n">' + count + '</text>'
            + '<text x="' + cx.toFixed(1) + '" y="' + (cy + 9).toFixed(1) + '" class="dx-lbl">DECK</text>';
    } else {
        // face-up last card: cover-crop its full PNG onto the top quad via an
        // affine map of a 100x100 box onto (tl, tr, bl) — same crop treatment
        // as board minions, clipped to the rounded top face.
        var def = (typeof cardDefs !== 'undefined' && cardDefs) ? cardDefs[topCardId] : null;
        var art = (def && def.card_id) ? _cardArtUrl(def.card_id, true) : '';
        var mu = [(top[1][0] - top[0][0]) / 100, (top[1][1] - top[0][1]) / 100];
        var mv = [(top[3][0] - top[0][0]) / 100, (top[3][1] - top[0][1]) / 100];
        var mat = [mu[0], mu[1], mv[0], mv[1], top[0][0], top[0][1]]
            .map(function(x) { return x.toFixed(4); }).join(' ');
        topFace = '<clipPath id="' + svgId + '-clip"><path d="' + R(top, 5) + '"/></clipPath>'
            + '<g clip-path="url(#' + svgId + '-clip)">'
            + (art
                ? '<g transform="matrix(' + mat + ')"><image class="dx-art" href="' + art
                    + '" x="0" y="0" width="100" height="100" preserveAspectRatio="xMidYMid slice"/></g>'
                : '<path d="' + R(top, 5) + '" fill="url(#' + svgId + '-p)"/>')
            + '</g>'
            + '<path d="' + R(top, 5) + '" fill="none" stroke="rgba(224,162,60,0.8)" stroke-width="1.2"/>';
        // count + pile title centered on the face, same set as the deck
        topTexts = '<text x="' + cx.toFixed(1) + '" y="' + (cy - 1).toFixed(1) + '" class="dx-n">' + count + '</text>'
            + '<text x="' + cx.toFixed(1) + '" y="' + (cy + 9).toFixed(1) + '" class="dx-lbl">'
            + kind.toUpperCase() + '</text>';
    }
    svg.innerHTML = stripes
        // base outline (the cell's projected quad)
        + '<path d="' + R(q, 5) + '" fill="none" stroke="rgba(224,162,60,0.45)" stroke-width="1"/>'
        // the deck's visible SIDES: left + right flanks (between the face
        // edges and the wider base edges) and the front band, all in the
        // card paper-edge color + dither
        + '<path d="' + R([top[0], top[3], q[3], q[0]], 2)
        + '" fill="url(#' + svgId + '-p)" stroke="rgba(60,44,20,0.4)" stroke-width="0.6"/>'
        + '<path d="' + R([top[1], top[2], q[2], q[1]], 2)
        + '" fill="url(#' + svgId + '-p)" stroke="rgba(60,44,20,0.4)" stroke-width="0.6"/>'
        + '<path d="' + R([top[3], top[2], q[2], q[3]], 3)
        + '" fill="url(#' + svgId + '-pf)" stroke="rgba(60,44,20,0.5)" stroke-width="0.8"/>'
        // corner connectors — screen-vertical by construction
        + lines
        // top face: same projected shape, straight up, rounded corners
        + topFace + topTexts;
}

function updatePileButtonCounts() {
    if (!gameState || !gameState.players) return;
    var meIdx = myPlayerIdx != null ? myPlayerIdx : 0;  // sandbox: P1 = own
    var me = gameState.players[meIdx];
    var opp = gameState.players[1 - meIdx];
    document.querySelectorAll('.pile-board').forEach(function(board) {
        var p = board.dataset.side === 'own' ? me : opp;
        board.querySelectorAll('.pile-cell[data-pile]').forEach(function(cell) {
            var count = _pileLen(p, cell.dataset.pile);
            var n = cell.querySelector('.pile-cell-n');
            if (n) n.textContent = count;
            if (cell.dataset.pile === 'deck') {
                _renderDeckStack(cell, count);
            } else {
                var _arr = Array.isArray(p[cell.dataset.pile]) ? p[cell.dataset.pile] : [];
                _renderDeckStack(cell, count, _arr.length ? _arr[_arr.length - 1] : null);
            }
        });
    });
    refreshOpenPileModal();
}

function setupPileHandlers() {
    // Pile-board cells (deck / grave / exhaust, own + opponent, both stages)
    var PILE_TITLES = { deck: 'Deck', grave: 'Grave', exhaust: 'Exhaust' };
    // Decks are PRIVATE (user 2026-07-06): count only, never clickable.
    document.querySelectorAll('.pile-board .pile-cell[data-pile="grave"], .pile-board .pile-cell[data-pile="exhaust"]').forEach(function(cell) {
        cell.addEventListener('click', function() {
            if (!gameState || !gameState.players) return;
            // sandbox god-view has no seat: treat P1 as "own" (matches pods)
            var meIdx = myPlayerIdx != null ? myPlayerIdx : 0;
            var own = cell.closest('.pile-board').dataset.side === 'own';
            var idx = own ? meIdx : 1 - meIdx;
            var kind = cell.dataset.pile;
            var p = gameState.players[idx] || {};
            var ids = Array.isArray(p[kind]) ? p[kind] : [];
            var title = (own ? 'Your ' : "Opponent's ") + PILE_TITLES[kind];
            if (kind === 'deck' && ids.length === 0 && _pileLen(p, 'deck') > 0) {
                title += ' — ' + _pileLen(p, 'deck') + ' cards (hidden)';
            }
            var inSandbox = typeof sandboxState !== 'undefined' && sandboxState &&
                document.getElementById('screen-sandbox').classList.contains('active');
            showPileModal(title, ids, {
                pileType: kind,
                playerIdx: idx,
                sandbox: inSandbox,
            });
        });
    });

    var closeBtn = document.getElementById('pileModalClose');
    if (closeBtn) closeBtn.addEventListener('click', hidePileModal);
    var modal = document.getElementById('pileModal');
    if (modal) {
        var pileHeader = modal.querySelector('.pile-modal-header');
        if (pileHeader) {
            attachBoardModalMinimizer({
                overlay: modal,
                controlsHost: pileHeader,
                label: 'Pile',
                restoreId: 'pile-modal-restore-pill',
                before: closeBtn,
                onMinimize: function() {
                    document.querySelectorAll('.sandbox-move-popover').forEach(
                        function(popover) { popover.remove(); }
                    );
                },
                onRestore: refreshOpenPileModal,
            });
        }
        modal.addEventListener('click', function(e) {
            if (e.target === modal) hidePileModal();
        });
    }
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            var m = document.getElementById('pileModal');
            if (m && m.style.display !== 'none') hidePileModal();
        }
    });
}

