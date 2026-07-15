// =============================================
// Phase 14.5 Wave 6: Card-draw animations
// =============================================
// Two pure-visual job types that run via the Phase 14.3 AnimationQueue:
//   draw_own — card flies from a source point into its hand slot (~600ms)
//   draw_opp — face-down card back pops into #oppHandRow           (~400ms)
//
// Both jobs assume state has ALREADY been applied before they run
// (job.stateApplied === true is set at enqueue time). Targets are resolved
// lazily at animation time so we read the live post-render DOM.
//
// Job shape (draw_own):
//   { type:'draw_own', cardNumericId:<int>, fromPos:'deck'|'center'|{x,y},
//     toSlotIndex:<int>, stateApplied:true }
// Job shape (draw_opp):
//   { type:'draw_opp', stateApplied:true }

function _resolveDrawFromPoint(fromPos) {
    // 'deck' → own deck pile button (closest thing to a deck visual);
    // 'center' → viewport center fallback;
    // {x,y} → absolute coords.
    if (fromPos && typeof fromPos === 'object' && typeof fromPos.x === 'number') {
        return { x: fromPos.x, y: fromPos.y };
    }
    if (fromPos === 'deck') {
        // Timing overhaul (2026-07-08, F9a): the old #pileBtnOwnGrave id is
        // dead DOM (zero matches) so draws always flew from viewport
        // center. Use the own DECK pile CELL on the active screen — the
        // real deck visual next to the board. (The deck-extrude SVG is a
        // full-viewBox overlay, so its own bounding rect is useless.)
        var screenSel = (typeof sandboxMode !== 'undefined' && sandboxMode)
            ? '#screen-sandbox' : '#screen-game';
        var cell = document.querySelector(
            screenSel + ' .pile-board[data-side="own"] .pile-cell[data-pile="deck"]');
        if (cell) {
            var r = cell.getBoundingClientRect();
            if (r.width > 0) {
                return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
            }
        }
    }
    // Default: viewport center.
    return { x: window.innerWidth / 2, y: window.innerHeight / 2 };
}

function playDrawOwnAnimation(job, done) {
    var handEl = document.getElementById('hand-container');
    if (!handEl) { setTimeout(done, 0); return; }
    var slotIdx = (job && typeof job.toSlotIndex === 'number') ? job.toSlotIndex : -1;
    var slotEl = slotIdx >= 0
        ? handEl.querySelector('.card-frame-hand[data-hand-idx="' + slotIdx + '"]')
        : null;
    // Fallback: last child of hand-container.
    if (!slotEl) {
        var cards = handEl.querySelectorAll('.card-frame-hand');
        if (cards.length > 0) slotEl = cards[cards.length - 1];
    }
    if (!slotEl) { setTimeout(done, 0); return; }

    var def = cardDefs && cardDefs[job.cardNumericId];
    if (!def) { setTimeout(done, 0); return; }

    var toRect = slotEl.getBoundingClientRect();
    var toCx = toRect.left + toRect.width / 2;
    var toCy = toRect.top + toRect.height / 2;
    var from = _resolveDrawFromPoint(job.fromPos);

    // Build a floating clone of the hand card at the target position.
    var floater = document.createElement('div');
    floater.className = 'draw-fly-in';
    floater.style.left = (toRect.left) + 'px';
    floater.style.top = (toRect.top) + 'px';
    floater.style.width = toRect.width + 'px';
    floater.style.height = toRect.height + 'px';
    // Starting transform offset (source → target delta), set as CSS vars
    // consumed by the keyframes.
    var dx = from.x - toCx;
    var dy = from.y - toCy;
    floater.style.setProperty('--draw-fly-dx', dx + 'px');
    floater.style.setProperty('--draw-fly-dy', dy + 'px');
    floater.innerHTML = renderCardFrame(def, {
        context: 'hand',
        numericId: job.cardNumericId,
        interactive: false,
        showReactDeploy: false,
    });
    document.body.appendChild(floater);

    // Hide the real slot until the floater lands, so we don't double-render.
    // Timing overhaul (2026-07-08, F9c): register the hidden slot in the
    // in-flight registry keyed by numeric id (index fallback). Any
    // renderHand rebuild detaches the captured node — renderHand re-hides
    // registered slots on rebuild, and finish() re-resolves by key, so
    // multi-draws no longer leave a visible duplicate mid-flight.
    if (!window.__inFlightHandSlots) window.__inFlightHandSlots = {};
    var slotKey = (job && job.cardNumericId != null)
        ? ('nid:' + job.cardNumericId)
        : ('idx:' + slotIdx);
    window.__inFlightHandSlots[slotKey] = (window.__inFlightHandSlots[slotKey] | 0) + 1;
    slotEl.style.visibility = 'hidden';

    playSfx('card_play');

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
        // Re-resolve by key — a rebuild may have replaced the captured node.
        var liveSlot = _resolveInFlightSlot(handEl, slotKey);
        if (liveSlot) liveSlot.style.visibility = '';
        slotEl.style.visibility = '';
        done();
    }
    floater.addEventListener('animationend', finish);
    // Fallback timeout in case animationend is swallowed (e.g. tab hidden).
    setTimeout(finish, 800);
}

// F9c helper: find the (hidden, preferably) hand slot matching an in-flight
// registry key inside the given hand container.
function _resolveInFlightSlot(handEl, key) {
    if (!handEl || !key) return null;
    var sel = key.indexOf('nid:') === 0
        ? '.card-frame-hand[data-numeric-id="' + key.slice(4) + '"]'
        : '.card-frame-hand[data-hand-idx="' + key.slice(4) + '"]';
    var els;
    try { els = handEl.querySelectorAll(sel); } catch (e) { return null; }
    for (var i = 0; i < els.length; i++) {
        if (els[i].style.visibility === 'hidden') return els[i];
    }
    return els.length ? els[els.length - 1] : null;
}

function playDrawOppAnimation(job, done) {
    var row = document.getElementById('oppHandRow');
    if (!row) { setTimeout(done, 0); return; }
    // State has already been applied, so renderOppHandRow just added a new
    // .opp-hand-card-back at the end. Stamp the pop-in class on the LAST
    // child and let the keyframe fire.
    var backs = row.querySelectorAll('.opp-hand-card-back');
    if (backs.length === 0) { setTimeout(done, 0); return; }
    var target = backs[backs.length - 1];
    // Element card backs (2026-07): the draw event carries the element so
    // the pop-in back is tinted even if the state re-render that normally
    // tints it hasn't happened yet.
    if (job && job.element != null) {
        try { _tintCardBack(target, job.element); } catch (e) { /* defensive */ }
    }
    target.classList.add('pop-in');

    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        target.classList.remove('pop-in');
        done();
    }
    target.addEventListener('animationend', finish);
    setTimeout(finish, 600);
}

// =============================================
// Section: Floating popups + status badges (Phase 14.3 Wave 7)
// =============================================
// Reusable popup system. One function, five variants. Adding a new
// status (frozen, stunned, etc.) is one CSS variant + one diff hook.
//
// Variant glyph convention:
//   combat-damage: '⚔️ -X'
//   heal:          '💚 +X'
//   burn-tick:     '🔥 -X'
//   buff:          '⬆️ +X ATK'
//   debuff:        '⬇️ -X ATK'
//
// tileEl should be the .board-cell (already position:relative). The
// popup is absolutely positioned and self-removes after the rise+fade
// keyframe completes (~1200ms; 1400ms setTimeout fallback).
// =============================================
// Audio system (CC0 Kenney sounds in /static/sfx/)
// =============================================
var SFX_FILES = {
    card_play:    '/static/sfx/card_play.ogg',
    move:         '/static/sfx/move.ogg',
    attack_hit:   '/static/sfx/attack_hit.ogg',
    slap:         '/static/sfx/attack_hit.ogg', // semantic alias; replaceable later
    damage:       '/static/sfx/damage.ogg',
    heal:         '/static/sfx/heal.ogg',
    burn_tick:    '/static/sfx/burn_tick.ogg',
    button_click: '/static/sfx/button_click.ogg',
    victory:      '/static/sfx/victory.ogg',
    defeat:       '/static/sfx/defeat.ogg',
    nudge_egg:    '/static/sfx/nudge_egg.ogg',
    nudge_boom:   '/static/sfx/nudge_boom.ogg',
    nudge_rain:   '/static/sfx/nudge_rain.ogg',
    nudge_kiss:   '/static/sfx/nudge_kiss.ogg',
    chat_ping:    '/static/sfx/chat_ping.ogg',
};
var sfxBuffers = {};
// 0.6 → 0.2 (user 2026-07-11: 'the sounds are really loud, lower to 20%')
// — the warm re-sourced set is loudnorm'd to -18 LUFS, hotter than the
// old Kenney interface beeps at the same element volume.
var sfxVolume = 0.2;
var sfxMuted = (function () {
    try { return localStorage.getItem('gt_sfx_muted') === '1'; } catch (e) { return false; }
})();
(function preloadSfx() {
    for (var k in SFX_FILES) {
        var a = new Audio(SFX_FILES[k]);
        a.preload = 'auto';
        sfxBuffers[k] = a;
    }
})();
function playSfx(name) {
    if (sfxMuted) return;
    var src = sfxBuffers[name];
    if (!src) return;
    // Clone so overlapping plays work (Audio elements can't double-play themselves)
    try {
        var node = src.cloneNode();
        node.volume = sfxVolume;
        var p = node.play();
        if (p && p.catch) p.catch(function () { /* autoplay blocked, ignore */ });
    } catch (e) {}
}
function setSfxMuted(muted) {
    sfxMuted = !!muted;
    try { localStorage.setItem('gt_sfx_muted', sfxMuted ? '1' : '0'); } catch (e) {}
}

function showFloatingPopup(tileEl, text, variant) {
    if (!tileEl) return;
    // Sound for the popup variant
    if (variant === 'combat-damage') playSfx('damage');
    else if (variant === 'heal') playSfx('heal');
    else if (variant === 'burn-tick') playSfx('burn_tick');
    var el = document.createElement('div');
    el.className = 'floating-popup floating-popup-viewport ' + variant;
    el.textContent = text;

    // Portal combat text to the viewport instead of nesting it inside the
    // tilted board cell.  A cell popup inherits the board's 3-D transform
    // and every clipping ancestor around the duel stage, which can crop the
    // glyph or number even when the cell itself uses overflow:visible.
    // getBoundingClientRect already includes the board perspective/scale, so
    // it gives us the exact on-screen anchor for both live and sandbox boards.
    var tileRect = tileEl.getBoundingClientRect();
    var fontPx = Math.max(16, Math.min(26, tileRect.width * 0.36));
    el.style.fontSize = fontPx + 'px';
    document.body.appendChild(el);

    // Keep wide blips (e.g. combined buffs / Cleansed) inside the viewport.
    // The vertical floor protects fully-opaque frames of top-row popups; the
    // final portion may travel higher only while it is fading to zero.
    var edgePad = 8;
    var halfWidth = (el.scrollWidth / 2) + 5; // include text stroke
    var anchorX = tileRect.left + tileRect.width / 2;
    anchorX = Math.max(
        edgePad + halfWidth,
        Math.min(window.innerWidth - edgePad - halfWidth, anchorX)
    );
    var anchorY = Math.max(60, tileRect.top + tileRect.height * 0.30);
    el.style.left = anchorX + 'px';
    el.style.top = anchorY + 'px';

    var removed = false;
    var cleanup = function () {
        if (removed) return;
        removed = true;
        if (el.parentNode) el.parentNode.removeChild(el);
    };
    el.addEventListener('animationend', cleanup);
    setTimeout(cleanup, 2400);
}

// Helper: flatten all board minions from a state frame.
function collectMinions(state) {
    if (!state || !state.minions) return [];
    return state.minions;
}

// Helper: locate the .board-cell DOM node for a minion's position.
function getTileElForMinion(m) {
    if (!m || !m.position) return null;
    return document.querySelector(
        '.board-cell[data-row="' + m.position[0] + '"][data-col="' + m.position[1] + '"]');
}

// Wave 4 (Phase 14.3-04): Attack animation.
// Rubber-band pullback (180ms) -> pause (100ms) -> snap strike (120ms) ->
// target flash + damage popup -> return tween (300ms) -> apply state.
// Total ~800ms. State is applied by runQueue's default after done(),
// so killed minions disappear AFTER the strike, not before.
// Screen-scoped tile lookup (2026-07-10): an unscoped '.board-cell'
// selector matches the GAME screen's cells first even when playing in
// SANDBOX (both boards live in the DOM), so sandbox attack/move visuals
// silently no-op'd whenever a game had rendered earlier in the session.
function _boardCellFor(row, col) {
    var screenSel = (typeof sandboxMode !== 'undefined' && sandboxMode)
        ? '#screen-sandbox ' : '#screen-game ';
    return document.querySelector(
        screenSel + '.board-cell[data-row="' + row + '"][data-col="' + col + '"]');
}

function playAttackAnimation(job, done) {
    playSfx('attack_hit');
    var payload = (job && job.payload) || {};
    var attackerPos = payload.attackerPos;
    var targetPos = payload.targetPos;
    var damage = payload.damage;

    if (!attackerPos || !targetPos) { setTimeout(done, 0); return; }

    var attackerCell = _boardCellFor(attackerPos[0], attackerPos[1]);
    var targetCell = _boardCellFor(targetPos[0], targetPos[1]);

    if (!attackerCell || !targetCell) { setTimeout(done, 0); return; }

    // Branch on attacker range: ranged minions get a projectile-arrow, melee
    // gets the rubber-band rush. Look up the attacker's CardDef via the .board-minion
    // element's data-numeric-id (set by renderBoardMinion).
    var attackerMinionEl = attackerCell.querySelector('.board-minion');
    // Timing overhaul (2026-07-08, F1): mirror playMoveAnimation's guard —
    // if the attacker sprite isn't in the DOM (race / reconnection), skip
    // the visual instead of lunging the bare tile.
    if (!attackerMinionEl) { setTimeout(done, 0); return; }
    var atkRange = 0;
    if (attackerMinionEl) {
        var nid = parseInt(attackerMinionEl.getAttribute('data-numeric-id'), 10);
        var def = !isNaN(nid) ? cardDefs[nid] : null;
        if (def && typeof def.attack_range === 'number') atkRange = def.attack_range;
    }
    if (atkRange >= 1) {
        return playRangedAttackAnimation(attackerCell, targetCell, damage, done);
    }

    // Animate the inner .board-minion if present so the cell border stays put.
    var attackerEl = attackerCell.querySelector('.board-minion') || attackerCell;

    var aRect = attackerCell.getBoundingClientRect();
    var tRect = targetCell.getBoundingClientRect();
    var _asc = _duelScaleFor(attackerCell);
    var dx = ((tRect.left + tRect.width / 2) - (aRect.left + aRect.width / 2)) / _asc;
    var dy = ((tRect.top + tRect.height / 2) - (aRect.top + aRect.height / 2)) / _asc;

    var pullX = -0.3 * dx, pullY = -0.3 * dy;
    var strikeX = 0.7 * dx, strikeY = 0.7 * dy;

    // "Under the grid" fix (user 2026-07-10) — same as playMoveAnimation's
    // Bug B: the anim classes' z-index:30 rides the MINION, but that only
    // escapes the tile while no sibling cell out-stacks it. Lift the whole
    // attacker CELL above the grid for the lunge (and guarantee overflow)
    // so the sprite can never pass under neighboring tiles or minions.
    var prevCellZ = attackerCell.style.zIndex;
    var prevCellOverflow = attackerCell.style.overflow;
    attackerCell.style.zIndex = '30';
    attackerCell.style.overflow = 'visible';

    function cleanupAttacker() {
        attackerEl.classList.remove('anim-attack-windup');
        attackerEl.classList.remove('anim-attack-strike');
        attackerEl.style.transform = '';
        attackerCell.style.zIndex = prevCellZ;
        attackerCell.style.overflow = prevCellOverflow;
    }

    // PHASE A — pullback (0-180ms)
    attackerEl.classList.add('anim-attack-windup');
    attackerEl.style.transform = 'translate(' + pullX + 'px,' + pullY + 'px)';

    setTimeout(function () {
        // PHASE B — pause (180-280ms)
        setTimeout(function () {
            // PHASE C — strike (280-400ms)
            attackerEl.classList.remove('anim-attack-windup');
            attackerEl.classList.add('anim-attack-strike');
            attackerEl.style.transform = 'translate(' + strikeX + 'px,' + strikeY + 'px)';

            setTimeout(function () {
                // PHASE D — impact: flash + damage popup
                targetCell.classList.add('anim-target-hit');
                setTimeout(function () {
                    targetCell.classList.remove('anim-target-hit');
                }, 420);

                // Phase 14.3 Wave 7: route combat damage through the unified
                // showFloatingPopup pathway. Replaces the Wave 4 inline
                // .damage-popup span. The .damage-popup CSS block is now
                // unused (harmless to leave behind).
                if (damage != null && damage > 0) {
                    showFloatingPopup(targetCell, '⚔️ -' + damage, 'combat-damage');
                }

                // PHASE E — return tween (400-700ms)
                attackerEl.classList.remove('anim-attack-strike');
                attackerEl.classList.add('anim-attack-windup');
                attackerEl.style.transform = 'translate(0,0)';

                setTimeout(function () {
                    // PHASE F — finish; runQueue's default applyStateFrame
                    // will fire on done() and remove dead minions.
                    cleanupAttacker();
                    done();
                }, 300);
            }, 120);
        }, 100);
    }, 180);
}

// Ranged attack animation: SVG arrow drawn from attacker to target.
// Phase A: arrow grows from attacker (~350ms via stroke-dasharray)
// Phase B: target flash + damage popup
// Phase C: arrow fades (~300ms) then removed
// Total ~850ms.
function playRangedAttackAnimation(attackerCell, targetCell, damage, done) {
    var aRect = attackerCell.getBoundingClientRect();
    var tRect = targetCell.getBoundingClientRect();
    var ax = aRect.left + aRect.width / 2;
    var ay = aRect.top + aRect.height / 2;
    var tx = tRect.left + tRect.width / 2;
    var ty = tRect.top + tRect.height / 2;

    // Recoil the attacker slightly back along the firing axis
    var attackerEl = attackerCell.querySelector('.board-minion') || attackerCell;
    var dx = tx - ax, dy = ty - ay;
    var len = Math.max(1, Math.sqrt(dx * dx + dy * dy));
    var ux = dx / len, uy = dy / len;
    var recoilX = -8 * ux, recoilY = -8 * uy;
    attackerEl.style.transition = 'transform 120ms ease-out';
    attackerEl.style.transform = 'translate(' + recoilX + 'px,' + recoilY + 'px)';

    // SVG overlay covering the viewport so the arrow can span anywhere
    var SVG_NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'ranged-attack-svg');
    svg.style.position = 'fixed';
    svg.style.left = '0';
    svg.style.top = '0';
    svg.style.width = '100vw';
    svg.style.height = '100vh';
    svg.style.pointerEvents = 'none';
    svg.style.zIndex = '900';

    // Aerial arc (user 2026-07-10): the arrow lobs on a quadratic Bézier
    // instead of a straight line. The bow is PERPENDICULAR to the flight
    // path (a plain "screen-up" control point degenerates to a straight
    // line on same-column shots — the common case in a lane game),
    // preferring the screen-up side so horizontal shots read as a lob.
    // Height scales with shot distance, capped so close shots stay
    // shallow. marker orient=auto keeps the arrowhead on the tangent, so
    // it lands angled into the target.
    var nx = -uy, ny = ux;
    if (ny > 0) { nx = -nx; ny = -ny; }
    var arcH = Math.min(90, len * 0.35);
    var pathD = 'M ' + ax + ' ' + ay
        + ' Q ' + (((ax + tx) / 2) + nx * arcH) + ' ' + (((ay + ty) / 2) + ny * arcH)
        + ' ' + tx + ' ' + ty;

    // The arc itself: black halo underneath, gold on top, animated draw
    var halo = document.createElementNS(SVG_NS, 'path');
    halo.setAttribute('d', pathD);
    halo.setAttribute('fill', 'none');
    halo.setAttribute('stroke', 'rgba(0,0,0,0.85)');
    halo.setAttribute('stroke-width', '7');
    halo.setAttribute('stroke-linecap', 'round');
    var line = document.createElementNS(SVG_NS, 'path');
    line.setAttribute('d', pathD);
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', '#f0b64e');
    line.setAttribute('stroke-width', '4');
    line.setAttribute('stroke-linecap', 'round');

    svg.appendChild(halo);
    svg.appendChild(line);

    // Projectile (user 2026-07-11 "the ranged arc needs to be animated"):
    // a real arrow glyph flies along the Bézier, rotating with the
    // tangent; the gold trail draws on BEHIND it, synced to the same
    // flight clock. The old marker-end arrowhead sat at the target from
    // frame one, so the whole thing read as a static line.
    var arrow = document.createElementNS(SVG_NS, 'g');
    var shaftHalo = document.createElementNS(SVG_NS, 'line');
    shaftHalo.setAttribute('x1', '-16'); shaftHalo.setAttribute('y1', '0');
    shaftHalo.setAttribute('x2', '4');   shaftHalo.setAttribute('y2', '0');
    shaftHalo.setAttribute('stroke', 'rgba(0,0,0,0.85)');
    shaftHalo.setAttribute('stroke-width', '6');
    shaftHalo.setAttribute('stroke-linecap', 'round');
    var shaft = document.createElementNS(SVG_NS, 'line');
    shaft.setAttribute('x1', '-16'); shaft.setAttribute('y1', '0');
    shaft.setAttribute('x2', '4');   shaft.setAttribute('y2', '0');
    shaft.setAttribute('stroke', '#f0b64e');
    shaft.setAttribute('stroke-width', '3');
    shaft.setAttribute('stroke-linecap', 'round');
    var head = document.createElementNS(SVG_NS, 'path');
    head.setAttribute('d', 'M 2 -5.5 L 15 0 L 2 5.5 z');
    head.setAttribute('fill', '#f0b64e');
    head.setAttribute('stroke', 'rgba(0,0,0,0.85)');
    head.setAttribute('stroke-width', '1.5');
    arrow.appendChild(shaftHalo);
    arrow.appendChild(shaft);
    arrow.appendChild(head);
    arrow.style.transition = 'opacity 120ms ease-out';
    svg.appendChild(arrow);
    document.body.appendChild(svg);

    // Trail hidden until the projectile passes — both driven from the
    // flight clock below (no CSS transition on dashoffset).
    var pathLen = len;
    try { pathLen = line.getTotalLength(); } catch (e) { /* fallback */ }
    [halo, line].forEach(function (el) {
        el.style.strokeDasharray = pathLen + ' ' + pathLen;
        el.style.strokeDashoffset = pathLen;
        el.style.transition = 'opacity 300ms ease-out';
    });

    var FLIGHT_MS = 350;
    var flightStart = null;
    function _flightFrame(ts) {
        if (flightStart === null) flightStart = ts;
        var t = Math.min(1, (ts - flightStart) / FLIGHT_MS);
        var eased = 1 - (1 - t) * (1 - t);   // ease-out
        var dist = eased * pathLen;
        var pt, ahead;
        try {
            pt = line.getPointAtLength(dist);
            ahead = line.getPointAtLength(Math.min(pathLen, dist + 2));
        } catch (e) { pt = null; }
        if (pt) {
            var ang = Math.atan2(ahead.y - pt.y, ahead.x - pt.x) * 180 / Math.PI;
            arrow.setAttribute(
                'transform',
                'translate(' + pt.x + ' ' + pt.y + ') rotate(' + ang + ')'
            );
            halo.style.strokeDashoffset = pathLen - dist;
            line.style.strokeDashoffset = pathLen - dist;
        }
        if (t < 1) {
            requestAnimationFrame(_flightFrame);
        } else {
            // Impact — the projectile vanishes into the target.
            arrow.style.opacity = '0';
        }
    }
    requestAnimationFrame(_flightFrame);

    setTimeout(function () {
        // Impact: target flash + damage popup
        targetCell.classList.add('anim-target-hit');
        setTimeout(function () { targetCell.classList.remove('anim-target-hit'); }, 420);
        if (damage != null && damage > 0) {
            showFloatingPopup(targetCell, '⚔️ -' + damage, 'combat-damage');
        }

        // Recoil return
        attackerEl.style.transform = 'translate(0,0)';

        // Fade out the arrow
        halo.style.opacity = '0';
        line.style.opacity = '0';

        setTimeout(function () {
            if (svg.parentNode) svg.parentNode.removeChild(svg);
            attackerEl.style.transition = '';
            attackerEl.style.transform = '';
            done();
        }, 300);
    }, 380);
}

// Tile-rect measurement helper. Returns the pixel delta between the centers
// of two board tiles, or null if either tile is missing from the DOM.
// Shared by move (Wave 3) and available for future animations.
// Rects are VIEWPORT px, but board transforms apply INSIDE the scaled
// 844x390 layout — divide deltas by the effective duel scale or slides
// overshoot proportionally to window size (user 2026-07-08).
function _duelScaleFor(el) {
    var layout = el && el.closest ? el.closest('.game-layout') : null;
    if (!layout) layout = document.querySelector('.screen.active .game-layout');
    if (!layout) return 1;
    var w = layout.getBoundingClientRect().width;
    return w > 0 ? w / 844 : 1;
}

function getTileDelta(fromPos, toPos) {
    if (!fromPos || !toPos) return null;
    // Screen-scoped (2026-07-10) — see _boardCellFor.
    var fromCell = _boardCellFor(fromPos[0], fromPos[1]);
    var toCell = _boardCellFor(toPos[0], toPos[1]);
    if (!fromCell || !toCell) return null;
    var fr = fromCell.getBoundingClientRect();
    var tr = toCell.getBoundingClientRect();
    var sc = _duelScaleFor(fromCell);
    return {
        dx: ((tr.left + tr.width / 2) - (fr.left + fr.width / 2)) / sc,
        dy: ((tr.top + tr.height / 2) - (fr.top + fr.height / 2)) / sc,
        fromCell: fromCell,
        toCell: toCell,
    };
}

// Wave 3 (Phase 14.3-03): Move animation.
// PHASE A — lift   (0ms):    add .anim-move-lift to source minion (scale + shadow)
// PHASE B — translate (120ms): add .anim-move-translate, set inline transform
//                              translate(dx,dy) scale(1.1). Wait 350ms.
// PHASE C — apply state + drop (470ms): applyStateFrame so the board re-renders
//   with the minion at the destination tile. The animatingTiles registry causes
//   renderBoard to tag the destination .board-cell with .anim-move-drop, which
//   plays a 120ms drop keyframe back to scale 1.0. Wait 120ms.
// PHASE D — cleanup, done().
//
// State application happens MID-animation (like summon, unlike attack), so we
// set job.stateApplied = true to suppress runQueue's default applyStateFrame.
function playMoveAnimation(job, done) {
    playSfx('move');
    var payload = (job && job.payload) || {};
    var from = payload.from;
    var to = payload.to;
    var speed = (typeof animSpeed === 'function') ? animSpeed() : 1;
    var liftMs = Math.max(1, Math.round(120 / speed));
    var slideMs = Math.max(1, Math.round(350 / speed));
    var dropMs = Math.max(1, Math.round(130 / speed));

    // Bail to a no-op if we don't have valid coords; runQueue will still
    // apply the state frame after done() because we don't set stateApplied.
    if (!from || !to) { setTimeout(done, 0); return; }

    var delta = getTileDelta(from, to);
    if (!delta) { setTimeout(done, 0); return; }

    var minionEl = delta.fromCell.querySelector('.board-minion');
    if (!minionEl) {
        // Source minion isn't in the DOM (race / reconnection). Skip visuals.
        setTimeout(done, 0);
        return;
    }

    // Keep the CSS transitions and JS phase clock on the same speed. Without
    // this, runQueue's 2x/4x fast-forward cap releases the next event before
    // Phase C moves the minion to its destination, making AI movement look
    // like it never happened at the exhibition speeds.
    var motionRoot = delta.fromCell.closest
        ? delta.fromCell.closest('.game-layout') : null;
    if (!motionRoot && typeof document !== 'undefined') {
        motionRoot = document.documentElement;
    }
    if (motionRoot && motionRoot.style && motionRoot.style.setProperty) {
        motionRoot.style.setProperty('--move-lift-duration', liftMs + 'ms');
        motionRoot.style.setProperty('--move-slide-duration', slideMs + 'ms');
        motionRoot.style.setProperty('--move-drop-duration', dropMs + 'ms');
    }

    var dx = delta.dx, dy = delta.dy;
    var destKey = to[0] + ',' + to[1];
    var srcKey = from[0] + ',' + from[1];

    // Bug B fix: .board-cell has overflow:hidden (for the cover-art bg).
    // The translated minion gets clipped at the source cell's bounds and
    // visually escapes only along the overflow edge — appearing "below the
    // grid" to the user. Lift overflow on the source cell for the duration
    // of the slide; Phase C re-renders the board so we don't need to
    // restore it explicitly (the cell is rebuilt by renderBoard).
    var prevOverflow = delta.fromCell.style.overflow;
    delta.fromCell.style.overflow = 'visible';
    // Also lift the parent stacking — z-index on board-minion won't escape
    // the cell otherwise. board-cell is position:relative so we can stack it.
    var prevZ = delta.fromCell.style.zIndex;
    delta.fromCell.style.zIndex = '30';

    // PHASE A — lift
    minionEl.classList.add('anim-move-lift');

    setTimeout(function () {
        // PHASE B — translate. The lift transform (scale 1.15) is preserved
        // explicitly because setting style.transform overrides the class rule.
        minionEl.classList.add('anim-move-translate');
        minionEl.style.transform = 'translate(' + dx + 'px,' + dy + 'px) scale(1.1)';

        setTimeout(function () {
            // PHASE C — apply state + drop. The board re-renders; the source
            // tile is now empty and the destination tile holds the minion.
            // animatingTiles[destKey] makes renderBoard tag that .board-cell
            // with .anim-move-drop so the freshly-rendered minion plays the
            // drop keyframe.
            animatingTiles[destKey] = 'move-drop';
            try {
                applyStateFrame(job.stateAfter, job.legalActionsAfter);
            } catch (e) { /* defensive */ }
            job.stateApplied = true;

            setTimeout(function () {
                // PHASE D — cleanup
                delete animatingTiles[destKey];
                delete animatingTiles[srcKey];
                try { renderBoard(); } catch (e) { /* defensive */ }
                done();
            }, dropMs);
        }, slideMs);
    }, liftMs);
}

// Wave 2: summon animation.
// Contract deviation from move/attack: state is applied at the START so the
// summoned minion is visible during its scale-in. We mark the destination
// tile in animatingTiles so renderBoard adds .anim-summon to that .board-cell.
function playSummonAnimation(job, done) {
    playSfx('card_play');
    var pos = job.payload && job.payload.pos;
    if (!pos) { setTimeout(done, 0); return; }
    var key = pos[0] + ',' + pos[1];

    // 1. Mark the tile so the next renderBoard tags it with .anim-summon.
    //    Stamp the start time (F10f) so renderBoard can apply a negative
    //    animation-delay — mid-summon re-renders resume the scale-in
    //    instead of restarting it.
    animatingTiles[key] = 'summon';
    if (typeof _animTileStart !== 'undefined') _animTileStart[key] = Date.now();

    // 2. Apply the post-summon state NOW (minion appears) and prevent the
    //    queue's default post-animation applyStateFrame.
    applyStateFrame(job.stateAfter, job.legalActionsAfter);
    job.stateApplied = true;
    // Phase 14.8: applyStateFrame → renderGame only repaints the LIVE
    // board; in sandbox mode the board lives in a different mount, so
    // repaint it too or the summoned minion stays invisible until the
    // post-drain commit.
    if (typeof sandboxMode !== 'undefined' && sandboxMode
        && typeof renderSandbox === 'function') {
        try { renderSandbox(); } catch (e) { /* defensive */ }
    }

    // 3. Shake the board container.
    var boardEl = document.getElementById('game-board');
    if (boardEl) {
        boardEl.classList.remove('anim-grid-shake');
        // Force reflow so re-adding the class restarts the animation.
        void boardEl.offsetWidth;
        boardEl.classList.add('anim-grid-shake');
        setTimeout(function() {
            if (boardEl) boardEl.classList.remove('anim-grid-shake');
        }, 360);
    }

    // 4. After one full scale-in cycle, drop the registry entry, re-render
    //    the board so the .anim-summon class falls off, and signal done.
    setTimeout(function() {
        delete animatingTiles[key];
        if (typeof _animTileStart !== 'undefined') delete _animTileStart[key];
        try {
            if (typeof sandboxMode !== 'undefined' && sandboxMode
                && typeof renderSandbox === 'function') {
                renderSandbox();
            } else {
                renderBoard();
            }
        } catch (e) { /* defensive: never block done() */ }
        done();
    }, 650);
}

// Single point of state application. Called directly for non-action frames
// (initial join, react open/close, lobby) and from runQueue() for queued
// action frames. All pending-UI sync lives downstream in renderGame() so
// it automatically runs post-animation.
// Cinder/paper-burn death animation. Adds .anim-cinder-death to the OLD
// .board-minion DOM node and sprinkles a few floating embers above it.
// Calls `done` after the animation completes (~1000ms). Used by
// applyStateFrame to defer state-swap on burn deaths so the player sees
// the kill animate instead of the minion vanishing instantly.
function playBurnDeathAnimation(prevMinion, done) {
    var tile = getTileElForMinion(prevMinion);
    if (!tile) { done && done(); return; }
    var minionEl = tile.querySelector('.board-minion');
    if (!minionEl) { done && done(); return; }

    playSfx('burn_tick');

    // Spawn 4 embers drifting up at slight horizontal offsets.
    var embers = [];
    for (var i = 0; i < 4; i++) {
        var em = document.createElement('span');
        em.className = 'cinder-ember';
        em.style.setProperty('--ex', ((i - 1.5) * 6) + 'px');
        em.style.animationDelay = (i * 80) + 'ms';
        tile.appendChild(em);
        embers.push(em);
    }

    minionEl.classList.add('anim-cinder-death');

    setTimeout(function () {
        try { minionEl.classList.remove('anim-cinder-death'); } catch (e) {}
        embers.forEach(function (e) { try { e.remove(); } catch (_) {} });
        done && done();
    }, 1000);
}

function applyStateFrame(frame, legal) {
    // Timing audit (2026-07-06): event-queue anim jobs capture
    // stateAfter=gameState at ENQUEUE. If the drain's final-snapshot commit
    // has already advanced gameState past that captured object, re-applying
    // the stale frame would REGRESS state + legalActions (and nothing
    // re-commits afterwards). Skip the application; the job's visuals have
    // already played against the right per-beat state.
    if (frame && gameState && frame !== gameState
            && window.__lastFinalState && gameState === window.__lastFinalState) {
        return;
    }
    var prevState = gameState;

    // Detect burn-deaths: minions that were is_burning in prevState and
    // are MISSING from the next frame. We assume these died from the
    // Decay-Phase burn tick (combat-killed minions are removed by other
    // code paths after their own animations).
    try {
        if (prevState && prevState.minions && frame && frame.minions) {
            var nextIds = {};
            collectMinions(frame).forEach(function (m) {
                if (m && m.instance_id != null) nextIds[m.instance_id] = true;
            });
            var burnDying = [];
            collectMinions(prevState).forEach(function (m) {
                if (!m || m.instance_id == null) return;
                if (nextIds[m.instance_id]) return;
                if (m.is_burning) burnDying.push(m);
            });
            if (burnDying.length > 0) {
                var pending = burnDying.length;
                var finish = function () {
                    pending -= 1;
                    if (pending <= 0) _applyStateFrameImmediate(frame, legal, prevState);
                };
                burnDying.forEach(function (m) { playBurnDeathAnimation(m, finish); });
                return;
            }
        }
    } catch (e) { /* defensive — fall through to immediate apply */ }

    _applyStateFrameImmediate(frame, legal, prevState);
}

function _applyStateFrameImmediate(frame, legal, prevState) {
    if (prevState === undefined) prevState = gameState;

    // Phase 14.3 Wave 7: per-minion HP delta hooks BEFORE state mutates.
    // - Heal popup: any current_health increase between frames.
    // - Burn-tick popup: HP decrease on a burning minion at the moment
    //   the active player flips (the only frame where the engine ticks
    //   burning). Popups anchor to the OLD tile so lethal burns still
    //   show the number before the minion vanishes on the next render.
    // NOTE: Phase 14.3 now has 7 plans (waves 6+7 added). Re-run
    // /gsd:plan-phase Wave 5 closeout or update STATE.md/ROADMAP.md
    // manually after this lands.
    try {
        if (prevState && prevState.minions && frame && frame.minions) {
            var prevMinions = {};
            collectMinions(prevState).forEach(function (m) {
                if (m && m.instance_id != null) prevMinions[m.instance_id] = m;
            });
            var turnFlipped = prevState.active_player_idx !== frame.active_player_idx;
            collectMinions(frame).forEach(function (m) {
                var p = prevMinions[m.instance_id];
                if (!p) return; // newly summoned this frame
                var prevHp = p.current_health;
                var nextHp = m.current_health;
                var tileEl = getTileElForMinion(m);

                // Heal: HP went UP
                if (nextHp > prevHp) {
                    showFloatingPopup(tileEl, '💚 +' + (nextHp - prevHp), 'heal');
                }

                // Burn tick: prev was burning and HP went DOWN. The engine ticks
                // burn in the OWNER's Decay Phase (end of the owner's turn,
                // before the flip) — fire the popup when the owner was the
                // active player on the previous frame. Anchor to the prev tile
                // so lethal burns still show the number before the minion
                // vanishes.
                if (turnFlipped && p.is_burning && nextHp < prevHp
                        && prevState.active_player_idx === p.owner) {
                    var burnTile = getTileElForMinion(p) || tileEl;
                    showFloatingPopup(burnTile, '🔥 -' + (prevHp - nextHp), 'burn-tick');
                }
            });
        }
    } catch (e) { /* defensive: never block state application */ }

    // Fatigue nudge (legacy snapshot path — post-plan-05 this only fires on
    // reconnect/initial frames; live play renders fatigue via the eventQueue's
    // playPlayerHpChange handler on cause==="fatigue"): if the viewer's fatigue_counts just
    // incremented, show the DECK EMPTY — FATIGUE overlay with the escalating
    // damage (10/20/30... = count * 10).
    try {
        if (prevState && prevState.fatigue_counts && frame && frame.fatigue_counts) {
            for (var fi = 0; fi < 2; fi++) {
                var prevFat = prevState.fatigue_counts[fi] || 0;
                var nextFat = frame.fatigue_counts[fi] || 0;
                if (nextFat > prevFat && fi === myPlayerIdx) {
                    triggerFatigueNudge(nextFat * 10, fi);
                    break;
                }
            }
        }
    } catch (e) {}

    gameState = frame;
    if (legal !== undefined) legalActions = legal;
    // Phase 14.4: keep spectator flags in sync with authoritative frame.
    if (frame && frame.is_spectator) {
        isSpectator = true;
        if (typeof frame.spectator_god_mode === 'boolean') {
            spectatorGodMode = frame.spectator_god_mode;
        }
    }

    // Phase 14.8-04b: turn banner + trigger blip are now OWNED by the
    // eventQueue (playTurnFlipped + playTriggerBlip). The engine emits
    // EVT_TURN_FLIPPED / EVT_TRIGGER_BLIP events on the same socket frame
    // as state_update; the eventQueue handlers fire the visuals at the
    // server-declared animation_duration_ms pacing. The inline dispatch
    // paths that used to fire here have been DELETED — the legacy
    // last_trigger_blip field is still dual-written by the engine per
    // plan 03a but is no longer read by the client (plan 14.8-05 deletes
    // the field write).

    // Timing audit (2026-07-06): logStateDiff call REMOVED — event-driven
    // anim jobs re-enter this path mid-drain with stale stateAfter frames
    // and emitted contradictory legacy log lines (reversed prev/next). The
    // engine-event logger (logEngineEvent at queue dispatch) is the sole
    // log writer now; game_start/reconnect snapshots diff as empty/benign.
    renderGame();
}

function isAnimating() {
    return animRunning || animQueue.length > 0;
}

// Temporary debug hook (Phase 14.3). Safe to leave — no side effects.
if (typeof window !== 'undefined') {
    window.__animDebug = {
        get animQueue() { return animQueue; },
        get animRunning() { return animRunning; },
        isAnimating: isAnimating,
    };
}
