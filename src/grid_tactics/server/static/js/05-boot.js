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

function _renderDeckStack(cell, count) {
    var layers = count <= 0 ? 0 : Math.max(1, Math.min(10, Math.ceil(count / 3)));
    cell.classList.toggle('deck-empty', layers === 0);
    var layout = cell.closest('.game-layout');
    if (!layout) return;
    var key = (cell.closest('.pile-board') || {}).dataset
        ? cell.closest('.pile-board').dataset.side : 'x';
    var screenEl = cell.closest('.screen');
    var svgId = 'deck-extrude-' + (screenEl ? screenEl.id : 's') + '-' + key;
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
    var NS = 'http://www.w3.org/2000/svg';
    if (!svg) {
        svg = document.createElementNS(NS, 'svg');
        svg.setAttribute('id', svgId);
        svg.setAttribute('class', 'deck-extrude');
        svg.setAttribute('viewBox', '0 0 844 390');
        layout.appendChild(svg);
    }
    var stripes =
        '<defs><pattern id="' + svgId + '-w" width="8" height="8"'
        + ' patternTransform="rotate(' + stripeDeg + ')" patternUnits="userSpaceOnUse">'
        + '<rect width="8" height="8" fill="#20170b"/>'
        + '<rect width="4" height="8" fill="#2c2010"/></pattern>'
        // card paper-edge color + dither for the deck's visible side
        + '<pattern id="' + svgId + '-p" width="4" height="4" patternUnits="userSpaceOnUse">'
        + '<rect width="4" height="4" fill="#e0d3ae"/>'
        + '<rect x="0" y="0" width="1" height="1" fill="#c9b98d"/>'
        + '<rect x="2" y="2" width="1" height="1" fill="#c9b98d"/>'
        + '<rect x="3" y="1" width="1" height="1" fill="#cfc09a"/>'
        + '<rect x="1" y="3" width="1" height="1" fill="#cfc09a"/>'
        + '</pattern></defs>';
    // only the far-back-LEFT (tl) and front-forward-RIGHT (br) connectors
    var lines = '';
    [0, 2].forEach(function(i) {
        lines += '<line x1="' + q[i][0].toFixed(1) + '" y1="' + q[i][1].toFixed(1)
            + '" x2="' + top[i][0].toFixed(1) + '" y2="' + top[i][1].toFixed(1)
            + '" stroke="rgba(224,162,60,0.75)" stroke-width="1"/>';
    });
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
        + '" fill="url(#' + svgId + '-p)" stroke="rgba(60,44,20,0.5)" stroke-width="0.8"/>'
        // corner connectors — screen-vertical by construction
        + lines
        // top face: same projected shape, straight up, rounded corners
        + '<path d="' + R(top, 5) + '" fill="url(#' + svgId + '-w)"'
        + ' stroke="rgba(224,162,60,0.8)" stroke-width="1.2"/>'
        + '<text x="' + cx.toFixed(1) + '" y="' + (cy - 1).toFixed(1) + '" class="dx-n">' + count + '</text>'
        + '<text x="' + cx.toFixed(1) + '" y="' + (cy + 9).toFixed(1) + '" class="dx-lbl">DECK</text>';
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

