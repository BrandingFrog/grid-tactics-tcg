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

function showPileModal(title, cardNumericIds, sandboxCtx) {
    var modal = document.getElementById('pileModal');
    var titleEl = document.getElementById('pileModalTitle');
    var grid = document.getElementById('pileModalGrid');
    if (!modal || !titleEl || !grid) return;
    titleEl.textContent = title || 'Pile';
    // Center over the STAGE (right of the tooltip column): live inside the
    // active screen's scaled layout so the grey-out skips the tooltip panel.
    var layout = document.querySelector('.screen.active .game-layout');
    if (layout && modal.parentElement !== layout) layout.appendChild(modal);
    grid.innerHTML = '';
    var ids = cardNumericIds || [];
    if (ids.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'pile-grid-empty';
        empty.textContent = 'Empty.';
        grid.appendChild(empty);
    } else {
        ids.forEach(function(nid) {
            var c = (allCardDefs && allCardDefs[nid]) || cardDefs[nid];
            if (!c) return;
            var cell = document.createElement('div');
            cell.className = 'pile-grid-cell';
            cell.innerHTML = renderCardFrame(c, {
                context: 'pile',
                numericId: nid,
                showReactDeploy: false
            });
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
    var modal = document.getElementById('pileModal');
    if (modal) modal.style.display = 'none';
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
// 3D-esque deck pile (user 2026-07-07): the deck cell renders a stack of
// card-back layers whose thickness tracks the remaining count — a fat
// block at 30+ cards thinning to a single card, empty = dashed outline.
function _renderDeckStack(cell, count) {
    var stack = cell.querySelector('.deck-stack');
    if (!stack) {
        stack = document.createElement('div');
        stack.className = 'deck-stack';
        cell.insertBefore(stack, cell.firstChild);
    }
    var layers = count <= 0 ? 0 : Math.max(1, Math.min(10, Math.ceil(count / 3)));
    cell.classList.toggle('deck-empty', layers === 0);
    if (parseInt(stack.dataset.layers || '-1', 10) === layers) return;
    stack.dataset.layers = String(layers);
    // vertical rise of the top face — the count/label ride it (CSS --rise)
    cell.style.setProperty('--rise', ((Math.max(layers, 1) - 1) * 2.2) + 'px');
    stack.innerHTML = '';
    // Technical-extrusion mode (user 2026-07-07): ONE raised top face; the
    // base rectangle + corner connector lines are drawn by CSS on the
    // stack itself — like extruding a rect in a technical drawing.
    if (layers > 0) {
        var face = document.createElement('div');
        face.className = 'deck-stack-layer deck-stack-top';
        face.style.setProperty('--si', layers - 1);
        face.style.setProperty('--sr', 0);
        stack.appendChild(face);
    }
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
            if (cell.dataset.pile === 'deck') _renderDeckStack(cell, count);
        });
    });
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
            showPileModal(title, ids, inSandbox ? { pileType: kind, playerIdx: idx } : undefined);
        });
    });

    var closeBtn = document.getElementById('pileModalClose');
    if (closeBtn) closeBtn.addEventListener('click', hidePileModal);
    var modal = document.getElementById('pileModal');
    if (modal) {
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

