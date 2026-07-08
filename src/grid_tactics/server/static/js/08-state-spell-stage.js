// =============================================
// Section 9: Game Start / State Update Handlers
// =============================================

function onGameStart(data) {
    // Phase 14.8-04a: a fresh game means the engine event seq counter
    // restarts at 0; reset lastSeenSeq so the first event isn't dropped.
    if (typeof resetEventQueue === 'function') resetEventQueue();
    cardDefs = data.card_defs;
    allCardDefs = data.card_defs;
    gameState = data.state;
    myPlayerIdx = data.your_player_idx;
    legalActions = data.legal_actions;
    opponentName = data.opponent_name;
    // Phase 14.4: spectators receive is_spectator=true on game_start and in
    // every state frame. Pick it up from the game_start payload too so the
    // first render is already gated correctly.
    if (data.is_spectator || (data.state && data.state.is_spectator)) {
        isSpectator = true;
        if (data.state && typeof data.state.spectator_god_mode === 'boolean') {
            spectatorGodMode = data.state.spectator_god_mode;
        }
    }
    // Reset log for a new game
    clearGameLog();
    addLogEntry('Game started. ' + (opponentName || 'Opponent') + ' joined.');
    // If we're coming from a rematch, hide the game over modal
    hideGameOver();
    resetRematchUI();
    showScreen('screen-game');
    // Set room code in game screen
    var roomCodeEl = document.getElementById('game-room-code');
    if (roomCodeEl && roomCode) {
        roomCodeEl.textContent = roomCode;
    }
    renderGame();
}

// Phase 14.8-05: onStateUpdate is a snapshot-cache commit ONLY for the
// initial frame (game_start + reconnect). Post-action state_update emits
// were DELETED server-side in this plan; the subscription here is retained
// defensively for backward compat with any pre-04b client or reconnection
// flow that might still emit a snapshot. DOM commits for ongoing play
// flow exclusively through the eventQueue's slot handlers — summon,
// move, attack, draw, card fly, HP popup, spell stage, turn banner,
// trigger blip, etc. The seven prev→next derive-* helpers
// (deriveAnimationJob, deriveCardFlyJobs, deriveDrawJobs,
// derivePlayerHpDeltaAnims, detectSpellCast, detectReactWindowClose,
// detectSpellStageClose) were deleted at the same time — they're
// referenced only in historical comments below.
function onStateUpdate(data) {
    var next = data.state;
    var nextLegal = data.legal_actions;
    applyStateFrame(next, nextLegal);
}

// Phase 14.8-05: derivePlayerHpDeltaAnims DELETED. Replaced by the
// playPlayerHpChange slot handler (plan 14.8-04a) which fires from
// EVT_PLAYER_HP_CHANGE on the engine event stream — no snapshot diff
// needed. The playHpDamagePopup job helper below is retained because
// playPlayerHpChange creates its damage popup element inline; the
// function name is preserved for compatibility with any sandbox-time
// test harnesses that wire it up directly.

function _hpStatElementId(playerIdx) {
    if (sandboxMode) return 'sandbox-p' + playerIdx + '-hp';
    return playerIdx === myPlayerIdx ? 'self-hp' : 'opp-hp';
}

function playHpDamagePopup(job, done) {
    var el = document.getElementById(_hpStatElementId(job.playerIdx));
    if (!el) { setTimeout(done, 0); return; }
    var rect = el.getBoundingClientRect();
    var pop = document.createElement('div');
    pop.className = 'damage-popup hp-damage-popup';
    pop.style.position = 'fixed';
    pop.style.left = (rect.left + rect.width / 2 - 20) + 'px';
    pop.style.top = (rect.top - 8) + 'px';
    pop.textContent = job.delta;  // already negative (e.g. "-25")
    document.body.appendChild(pop);
    // Red flash on the HP stat to draw the eye.
    el.classList.add('hp-flash');
    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        if (pop.parentNode) pop.parentNode.removeChild(pop);
        el.classList.remove('hp-flash');
        done();
    }
    setTimeout(finish, 950);
}

// ============================================================
// Sacrifice transcend animation: the minion morphs into a purple-
// outlined jumper silhouette, leaps toward the enemy HP display, and
// fades out. The HP damage popup fires in parallel via the
// playPlayerHpChange event-queue slot handler (post Phase 14.8-05).
// ============================================================
var SACRIFICE_JUMPER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-50 -20 300 290" width="100%" height="100%">'
    + '<defs><filter id="sjglow" x="-50%" y="-50%" width="200%" height="200%">'
    + '<feMorphology in="SourceAlpha" operator="dilate" radius="3" result="wR"/>'
    + '<feFlood flood-color="#ffffff" result="wF"/>'
    + '<feComposite in="wF" in2="wR" operator="in" result="wL"/>'
    + '<feGaussianBlur in="wR" stdDeviation="8" result="wB"/>'
    + '<feFlood flood-color="#ffffff" result="wF2"/>'
    + '<feComposite in="wF2" in2="wB" operator="in" result="wG"/>'
    + '<feMorphology in="SourceAlpha" operator="dilate" radius="1" result="pR"/>'
    + '<feFlood flood-color="#b347ff" result="pF"/>'
    + '<feComposite in="pF" in2="pR" operator="in" result="pL"/>'
    + '<feGaussianBlur in="pR" stdDeviation="3" result="pB"/>'
    + '<feFlood flood-color="#b347ff" result="pF2"/>'
    + '<feComposite in="pF2" in2="pB" operator="in" result="pG"/>'
    + '<feMerge>'
    + '<feMergeNode in="wG"/><feMergeNode in="wG"/><feMergeNode in="wL"/>'
    + '<feMergeNode in="pG"/><feMergeNode in="pG"/><feMergeNode in="pL"/>'
    + '<feMergeNode in="SourceGraphic"/>'
    + '</feMerge></filter></defs>'
    + '<g transform="rotate(-15 100 100)" fill="#111" filter="url(#sjglow)">'
    + '<ellipse cx="100" cy="28" rx="36" ry="36"/>'
    + '<polygon points="86,52 114,52 116,74 84,74"/>'
    + '<polygon points="72,68 128,68 124,108 118,122 124,134 76,134 82,122 76,108"/>'
    + '<polygon points="86,70 29,22 15,42 76,82"/>'
    + '<circle cx="18" cy="26" r="22"/>'
    + '<polygon points="114,70 171,22 185,42 124,82"/>'
    + '<circle cx="182" cy="26" r="22"/>'
    + '<polygon points="78,132 94,132 40,198 20,184"/>'
    + '<polygon points="106,132 122,132 180,184 160,198"/>'
    + '<g transform="translate(30 191) rotate(30)"><ellipse cx="-20" cy="0" rx="32" ry="18"/></g>'
    + '<g transform="translate(170 191) rotate(-30)"><ellipse cx="20" cy="0" rx="32" ry="18"/></g>'
    + '</g></svg>'
);

// minion_sacrificed — EVT_MINION_SACRIFICED (2026-07 fix): the engine now
// emits a board event for SACRIFICE; route it into the existing transcend
// animation. State is NOT yet applied when this plays, so the minion is
// still on its tile — _sacrificeTileContext hides the sprite for the leap.
function playMinionSacrificed(ev, done) {
    var p = (ev && ev.payload) || {};
    playSacrificeTranscendAnimation({ payload: { pos: p.position || null } }, done);
}

// Dispatcher — picks a sacrifice animation variant based on
// window.__sacrificeVariant (set by the Tests tab when a scenario
// specifies a sacrifice_animation hint, or manually in the console).
// Default is 'shatter' — the jumper-leap-into-shard-explosion combo
// the user picked as the canonical sacrifice visual.
function playSacrificeTranscendAnimation(job, done) {
    var variant = (typeof window !== 'undefined' && window.__sacrificeVariant)
        || 'shatter';
    var impl = ({
        jumper: _playSacJumper,
        ghost:  _playSacGhostRise,
        shatter: _playSacShatter,
        portal: _playSacPortal,
    })[variant] || _playSacShatter;
    impl(job, done);
}

// Shared helpers — resolve the source tile rect and the enemy-face vector.
function _sacrificeTileContext(job) {
    var pos = job.payload && job.payload.pos;
    if (!pos) return null;
    var tile = document.querySelector(
        '.board-cell[data-row="' + pos[0] + '"][data-col="' + pos[1] + '"]');
    if (!tile) return null;
    var minionEl = tile.querySelector('.board-minion');
    var rect = (minionEl || tile).getBoundingClientRect();
    if (minionEl) minionEl.style.visibility = 'hidden';
    var enemyIdx = (pos[0] === 4) ? 1 : 0;
    var enemyHpEl = document.getElementById(_hpStatElementId(enemyIdx));
    var jumpDx = 0;
    var jumpDy = enemyIdx === 1 ? -140 : 140;
    if (enemyHpEl) {
        var hpRect = enemyHpEl.getBoundingClientRect();
        var mCx = rect.left + rect.width / 2;
        var mCy = rect.top + rect.height / 2;
        var hCx = hpRect.left + hpRect.width / 2;
        var hCy = hpRect.top + hpRect.height / 2;
        jumpDx = (hCx - mCx) * 0.45;
        jumpDy = (hCy - mCy) * 0.45;
    }
    return { rect: rect, enemyIdx: enemyIdx, jumpDx: jumpDx, jumpDy: jumpDy };
}

// A — Jumper silhouette leaps toward enemy face, fades.
function _playSacJumper(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var jumper = document.createElement('div');
    jumper.className = 'sacrifice-jumper sac-anim-overlay';
    jumper.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:150;pointer-events:none;transition:transform 850ms cubic-bezier(0.2,0.6,0.3,1),opacity 850ms ease-in;will-change:transform,opacity;';
    jumper.innerHTML = SACRIFICE_JUMPER_SVG;
    document.body.appendChild(jumper);
    requestAnimationFrame(function() { requestAnimationFrame(function() {
        jumper.style.transform = 'translate(' + ctx.jumpDx + 'px,' + ctx.jumpDy + 'px) scale(1.3)';
        jumper.style.opacity = '0';
    }); });
    setTimeout(function() {
        if (jumper.parentNode) jumper.parentNode.removeChild(jumper);
        done();
    }, 880);
}

// B — Ghost rise: purple ghost silhouette ascends out of the tile and
// dissolves while the original sprite tinges purple before fading.
function _playSacGhostRise(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var ghost = document.createElement('div');
    ghost.className = 'sac-anim-overlay sac-ghost';
    ghost.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:150;pointer-events:none;transition:transform 1000ms cubic-bezier(0.3,0,0.4,1),opacity 1000ms ease-out,filter 1000ms ease-out;will-change:transform,opacity,filter;';
    ghost.innerHTML = (
        '<div style="position:absolute;inset:0;border-radius:12px;background:radial-gradient(circle at 50% 60%, rgba(179,71,255,0.75) 0%, rgba(130,30,200,0.55) 35%, rgba(40,0,80,0.2) 65%, transparent 85%);mix-blend-mode:screen;filter:blur(2px);"></div>'
        + '<div style="position:absolute;inset:-12% 10% 30% 10%;border-radius:50%;background:radial-gradient(ellipse at 50% 40%, rgba(255,255,255,0.85) 0%, rgba(217,168,255,0.55) 35%, transparent 75%);mix-blend-mode:screen;filter:blur(3px);"></div>'
    );
    document.body.appendChild(ghost);
    requestAnimationFrame(function() { requestAnimationFrame(function() {
        ghost.style.transform = 'translate(' + (ctx.jumpDx * 0.3) + 'px,' + (ctx.jumpDy * 0.7 - 40) + 'px) scale(1.4)';
        ghost.style.opacity = '0';
        ghost.style.filter = 'blur(8px)';
    }); });
    setTimeout(function() {
        if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
        done();
    }, 1050);
}

// C — Jumper-Shatter combo: white-purple flash erupts on the tile, the
// pixel-art jumper silhouette leaps toward the enemy face; mid-arc it
// explodes into 8 purple shards that continue outward and fade. The
// jumper (variant A) is absorbed into this variant as the first beat.
function _playSacShatter(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var cx = ctx.rect.left + ctx.rect.width / 2;
    var cy = ctx.rect.top + ctx.rect.height / 2;

    // Beat 1 — tight launch flash under the silhouette's feet. Short
    // and small: a blink rather than a burst, so the jumper reads as
    // the main visual.
    var feetY = ctx.rect.top + ctx.rect.height * 0.82;
    var flashSize = 32;
    var flash = document.createElement('div');
    flash.className = 'sac-anim-overlay sac-flash';
    flash.style.cssText = 'position:fixed;left:' + (cx - flashSize / 2) + 'px;top:' + (feetY - flashSize / 2) + 'px;width:' + flashSize + 'px;height:' + flashSize + 'px;z-index:149;pointer-events:none;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,0.95) 0%,rgba(217,168,255,0.6) 40%,transparent 75%);opacity:0;transition:opacity 70ms ease-out,transform 70ms ease-out;';
    document.body.appendChild(flash);

    // Beat 2 — jumper silhouette rises out of the flash and leaps.
    var jumper = document.createElement('div');
    jumper.className = 'sacrifice-jumper sac-anim-overlay';
    jumper.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:152;pointer-events:none;transition:transform 400ms cubic-bezier(0.2,0.6,0.3,1),opacity 400ms ease-out;will-change:transform,opacity;';
    jumper.innerHTML = SACRIFICE_JUMPER_SVG;
    document.body.appendChild(jumper);

    // Beat 3 — shards pre-built at the tile, kicked off when the jumper
    // "explodes" mid-arc. Launch position follows the jumper's mid-arc
    // delta so the explosion happens where the silhouette lands.
    var shardDx = ctx.jumpDx * 0.6;
    var shardDy = ctx.jumpDy * 0.6;
    var fragEls = [];
    var N = 8;
    for (var i = 0; i < N; i++) {
        var frag = document.createElement('div');
        var angle = (i / N) * Math.PI * 2;
        var size = 18 + Math.random() * 14;
        frag.className = 'sac-anim-overlay sac-frag';
        frag.style.cssText = 'position:fixed;left:' + (cx - size/2) + 'px;top:' + (cy - size/2) + 'px;width:' + size + 'px;height:' + size + 'px;z-index:150;pointer-events:none;background:linear-gradient(135deg,#d9a8ff 0%,#8822cc 100%);box-shadow:0 0 12px rgba(179,71,255,0.8);clip-path:polygon(20% 0%,80% 0%,100% 50%,80% 100%,20% 100%,0% 50%);opacity:0;transform:translate(' + shardDx + 'px,' + shardDy + 'px) scale(0.4);transition:transform 650ms cubic-bezier(0.2,0.6,0.3,1),opacity 650ms ease-in;will-change:transform,opacity;';
        frag._angle = angle;
        frag._finalDx = Math.cos(angle) * (110 + Math.random() * 50) + shardDx;
        frag._finalDy = Math.sin(angle) * (110 + Math.random() * 50) + shardDy;
        frag._finalRot = Math.random() * 720 - 360;
        document.body.appendChild(frag);
        fragEls.push(frag);
    }

    // A small tilt feels like momentum — pick a sign based on jump
    // direction so the rotation leans INTO the enemy face.
    var tiltMid = (ctx.jumpDx >= 0 ? 1 : -1) * 8;
    var tiltEnd = (ctx.jumpDx >= 0 ? 1 : -1) * 14;

    // Kick beat 1+2 on the next frame pair.
    requestAnimationFrame(function() { requestAnimationFrame(function() {
        flash.style.opacity = '1';
        flash.style.transform = 'scale(1.8)';
        jumper.style.transform = 'translate(' + (ctx.jumpDx * 0.6) + 'px,' + (ctx.jumpDy * 0.6) + 'px) scale(1.15) rotate(' + tiltMid + 'deg)';
    }); });

    // Fade the flash out fast — a brief blink that seeds the jump.
    setTimeout(function() {
        flash.style.opacity = '0';
        flash.style.transform = 'scale(2)';
    }, 80);

    // Mid-arc: pop the jumper, launch the shards.
    setTimeout(function() {
        jumper.style.transition = 'transform 200ms ease-out,opacity 200ms ease-out,filter 200ms ease-out';
        jumper.style.transform = 'translate(' + (ctx.jumpDx * 0.65) + 'px,' + (ctx.jumpDy * 0.65) + 'px) scale(1.45) rotate(' + tiltEnd + 'deg)';
        jumper.style.opacity = '0';
        jumper.style.filter = 'brightness(2) saturate(1.3)';
        fragEls.forEach(function(f) {
            f.style.opacity = '1';
            f.style.transform = 'translate(' + f._finalDx + 'px,' + f._finalDy + 'px) rotate(' + f._finalRot + 'deg) scale(1)';
        });
        // Fade shards on the tail.
        setTimeout(function() {
            fragEls.forEach(function(f) { f.style.opacity = '0'; });
        }, 350);
    }, 420);

    // Cleanup.
    setTimeout(function() {
        fragEls.forEach(function(f) { if (f.parentNode) f.parentNode.removeChild(f); });
        if (flash.parentNode) flash.parentNode.removeChild(flash);
        if (jumper.parentNode) jumper.parentNode.removeChild(jumper);
        done();
    }, 1150);
}

// D — Portal warp: a swirling purple ring opens beneath the minion;
// the minion spirals inward while shrinking to a point, then the portal
// closes. Uses a clone of the minion so the CSS rotation doesn't spin
// the whole board cell.
function _playSacPortal(job, done) {
    var ctx = _sacrificeTileContext(job);
    if (!ctx) { setTimeout(done, 0); return; }
    var pos = job.payload && job.payload.pos;
    var tile = document.querySelector(
        '.board-cell[data-row="' + pos[0] + '"][data-col="' + pos[1] + '"]');
    var minionEl = tile && tile.querySelector('.board-minion');

    var cx = ctx.rect.left + ctx.rect.width / 2;
    var cy = ctx.rect.top + ctx.rect.height / 2;

    // Portal ring — a purple double-ring that grows then shrinks.
    var portal = document.createElement('div');
    portal.className = 'sac-anim-overlay sac-portal';
    portal.style.cssText = 'position:fixed;left:' + (cx - 90) + 'px;top:' + (cy - 90) + 'px;width:180px;height:180px;z-index:149;pointer-events:none;border-radius:50%;border:4px solid rgba(217,168,255,0.9);box-shadow:0 0 24px rgba(179,71,255,0.8),inset 0 0 32px rgba(179,71,255,0.7);background:radial-gradient(circle,rgba(40,0,80,0.7) 0%,rgba(179,71,255,0.3) 50%,transparent 80%);opacity:0;transform:scale(0.2) rotate(0deg);transition:transform 900ms cubic-bezier(0.2,0.6,0.3,1),opacity 900ms ease-out;animation:sac-portal-spin 900ms linear;';
    document.body.appendChild(portal);

    // Clone the minion so we can spiral/shrink it without touching the real tile.
    var clone = null;
    if (minionEl) {
        clone = minionEl.cloneNode(true);
        clone.className = 'sac-anim-overlay sac-portal-clone ' + minionEl.className;
        clone.style.cssText = 'position:fixed;left:' + ctx.rect.left + 'px;top:' + ctx.rect.top + 'px;width:' + ctx.rect.width + 'px;height:' + ctx.rect.height + 'px;z-index:150;pointer-events:none;visibility:visible;transition:transform 900ms cubic-bezier(0.4,0,1,0.7),opacity 900ms ease-in;will-change:transform,opacity;';
        document.body.appendChild(clone);
    }

    requestAnimationFrame(function() { requestAnimationFrame(function() {
        portal.style.opacity = '1';
        portal.style.transform = 'scale(1) rotate(360deg)';
        if (clone) {
            clone.style.transform = 'translate(' + (ctx.jumpDx * 0.2) + 'px,' + (ctx.jumpDy * 0.2) + 'px) scale(0.05) rotate(720deg)';
            clone.style.opacity = '0';
        }
    }); });

    // Close portal (shrink + fade) after main phase.
    setTimeout(function() {
        portal.style.transition = 'transform 300ms ease-in,opacity 300ms ease-in';
        portal.style.transform = 'scale(0.1) rotate(540deg)';
        portal.style.opacity = '0';
    }, 700);

    setTimeout(function() {
        if (portal.parentNode) portal.parentNode.removeChild(portal);
        if (clone && clone.parentNode) clone.parentNode.removeChild(clone);
        done();
    }, 1050);
}

// ============================================================
// Spell-cast center stage: when a magic or react is cast, show a
// giant [card art] ▶ [? / 👍] overlay in the middle of the screen.
// After 1s of react-window idleness the ? flips to 👍 and the stage
// fades; a new react landing before then slides the current card
// off-screen to the left and brings the new one in from the right.
// ============================================================
// Two-slot chain stage. New cards land in the RIGHT slot (replacing the
// waiting "?"). After a 1s beat the card shifts to the LEFT slot,
// pushing any prior LEFT card off-screen, and a fresh "?" appears in
// the RIGHT slot ready for the next react. When the chain resolves we
// replay every pushed card LIFO (top-down) into the LEFT slot with a
// "resolving" sigil in the RIGHT, then fade.
// =============================================
// Phase 14.7-09: Turn banner + trigger blip animations
// =============================================

// TURN X / PLAYER X banner — non-blocking overlay. CSS keyframes drive
// the animation; this function just drops a DOM node and schedules its
// removal after the animation finishes. Safe to call concurrently with
// the AnimationQueue; the banner never gates game state.
//
// Phase 14.8-04b: the 4 ad-hoc defer/buffer gate families that used to
// live in this region have been DELETED — same-turn dedupe, pending
// banner, pending trigger blip, post-stage-frame deferral, and the
// sandbox frame queue with its visual-duration budget table. Pacing
// between banner, blip, and spell stage close is now handled by the
// unified eventQueue's FIFO ordering: the engine emits react_window
// close → trigger blip → turn flip in seq order, and each handler
// calls done() only after its animation completes, so the user-
// expected order falls out of queue discipline without any ad-hoc
// deferral machinery.
function _runTurnFlipVisuals(turnNumber, activePlayerIdx) {
    // Timing overhaul (2026-07-08, F7d): END-LED pre-delay shortened
    // 900→300ms and the banner keyframe to ~1200ms (appended override in
    // zz-overrides.css) so the whole choreography fits inside
    // playTurnFlipped's 1500ms gate — no more banner blooming over the
    // next turn's draw.
    _flashPhaseLed('end', 900);
    setTimeout(function() {
        _showTurnBanner(turnNumber, activePlayerIdx);
        _flashPhaseLed('start', 900);
    }, 300);
}

function _showTurnBanner(turnNumber, activePlayerIdx) {
    try {
        // Plan 14.8-04b: the old same-turn-key dedupe guard has been
        // DELETED. Dedupe is now handled by the eventQueue's lastSeenSeq —
        // each EVT_TURN_FLIPPED event carries a unique seq, so a repeated
        // sandbox_state emit for turn=1 on initial load can no longer
        // trigger the banner twice.

        // Remove any prior banner (covers rapid turn flips).
        var prior = document.querySelector('.turn-transition-banner');
        if (prior && prior.parentNode) prior.parentNode.removeChild(prior);

        var banner = document.createElement('div');
        banner.className = 'turn-transition-banner';
        banner.setAttribute('data-turn', String(turnNumber));
        banner.setAttribute('data-player', String(activePlayerIdx));
        var playerLabel = 'PLAYER ' + ((activePlayerIdx | 0) + 1);
        banner.innerHTML =
            '<div class="turn-transition-banner-line1">TURN ' + turnNumber + '</div>' +
            '<div class="turn-transition-banner-line2">' + playerLabel + '</div>';
        // Defense-in-depth: remove on animationend (primary) + setTimeout
        // fallback (in case the browser drops the animationend event, e.g.
        // backgrounded tab).
        var removed = false;
        var remove = function () {
            if (removed) return;
            removed = true;
            if (banner.parentNode) banner.parentNode.removeChild(banner);
        };
        banner.addEventListener('animationend', remove);
        (document.querySelector('.screen.active .game-layout') || document.body).appendChild(banner);
        setTimeout(remove, 2000);
    } catch (e) { /* defensive */ }
}

// Trigger blip — source tile pulse → center icon → (optional) target tile
// pulse. Used for Start/End-of-turn and Death triggers where the source is
// a board minion (not a hand card). Reuses showFloatingPopup + existing
// tile-highlight patterns from Phase 14.3-07.
//
// blip shape: {
//   trigger_kind: "start_of_turn" | "end_of_turn" | "on_death" | "on_summon_effect",
//   source_minion_id: int | null,
//   source_position: [row, col],
//   target_position: [row, col] | null,
//   effect_kind: string  // lowercase EffectType.name (e.g. "heal", "damage", "apply_burning")
// }
function _triggerBlipIcon(blip) {
    var kind = blip && blip.trigger_kind;
    var effect = blip && blip.effect_kind;
    // Trigger-kind drives the primary glyph; effect_kind is a subtle hint.
    if (kind === 'on_death') return '💀';
    if (kind === 'start_of_turn') return '⏰';
    if (kind === 'end_of_turn') return '⏳';
    if (effect === 'heal') return '💚';
    if (effect === 'damage') return '💥';
    if (effect === 'apply_burning') return '🔥';
    return '✨';
}

function _tileElForPosition(pos) {
    if (!pos || pos.length < 2) return null;
    return document.querySelector(
        '.board-cell[data-row="' + pos[0] + '"][data-col="' + pos[1] + '"]'
    );
}

function _fireTriggerBlipAnimation(blip) {
    if (!blip) return;
    try {
        // 0) Flash the matching phase LED so the indicator surfaces
        //    START_OF_TURN / END_OF_TURN even though the wire-state
        //    phase has already cycled back to ACTION by then.
        var kind = blip.trigger_kind;
        if (kind === 'start_of_turn') _flashPhaseLed('start');
        else if (kind === 'end_of_turn') _flashPhaseLed('end');

        // 1) Pulse the source tile (if still on the board).
        var srcTile = _tileElForPosition(blip.source_position);
        if (srcTile) {
            srcTile.classList.remove('anim-trigger-source');
            // Force reflow so re-adding the class restarts the animation.
            void srcTile.offsetWidth;
            srcTile.classList.add('anim-trigger-source');
            setTimeout(function () {
                if (srcTile) srcTile.classList.remove('anim-trigger-source');
            }, 600);
        }

        // 2) Center-screen icon, ~800ms.
        var icon = document.createElement('div');
        icon.className = 'trigger-blip-center-icon';
        icon.textContent = _triggerBlipIcon(blip);
        _stageMount().appendChild(icon);
        setTimeout(function () {
            if (icon.parentNode) icon.parentNode.removeChild(icon);
        }, 900);

        // 3) Pulse the target tile slightly later (if any) so the beat is
        //    source → center → target.
        if (blip.target_position) {
            setTimeout(function () {
                var tgtTile = _tileElForPosition(blip.target_position);
                if (!tgtTile) return;
                tgtTile.classList.remove('anim-trigger-target');
                void tgtTile.offsetWidth;
                tgtTile.classList.add('anim-trigger-target');
                setTimeout(function () {
                    if (tgtTile) tgtTile.classList.remove('anim-trigger-target');
                }, 600);
            }, 350);
        }
    } catch (e) { /* defensive — blip must never throw */ }
}

// Stack-based react-window state. LEFT stack = original caster's pile;
// RIGHT stack = opponent's pile. Each chain entry tracks who played the
// card so we know which pile it lives on.
var _spellStage = {
    chain: [],         // [{ nid, playerIdx, el, side }, ...] oldest first
    casterIdx: null,   // chain[0].playerIdx, cached on first push
    resolving: false,
    exitTimer: null,
};

// True while the spell-stage overlay is visually animating — i.e. cards
// are flying in (queue busy), stacked on screen (chain non-empty), or
// fading out (LIFO resolve). Used to GATE self-initiated action inputs
// so the player cannot activate effects / move / attack / play non-react
// cards while the spell-stage is still on screen, even if the server has
// already transitioned the wire-state back to ACTION (sandbox auto-drain,
// opponent auto-PASS, etc). PASS (action_type 4) and PLAY_REACT (5) are
// NEVER gated — those are the only actions that can close the react
// window server-side, so gating them would deadlock the game.
function isSpellStageAnimating() {
    if (_spellStageBusy) return true;
    if (_spellStageQueue && _spellStageQueue.length > 0) return true;
    if (_spellStage.resolving) return true;
    if (_spellStage.chain && _spellStage.chain.length > 0) return true;
    return false;
}

function _spellStageEls() {
    return {
        root: document.getElementById('spell-stage'),
        left: document.getElementById('spell-stage-stack-left'),
        right: document.getElementById('spell-stage-stack-right'),
        placeholder: document.getElementById('spell-stage-placeholder'),
    };
}

function _spellStageCardHtml(numericId) {
    var def = (cardDefs && cardDefs[numericId]) ||
              (window.sandboxCardDefs && window.sandboxCardDefs[numericId]);
    if (!def) return '';
    return renderCardFrame(def, {
        context: 'tooltip',
        numericId: numericId,
        interactive: false,
        showReactDeploy: false,
    });
}

// Hand / source rect for the fly-from-hand origin of a newly-cast card.
// In sandbox both hands are mounted so we use #sandbox-hand-p<idx>.
// In live game the opponent's hand is the back row; the own hand is
// the front. Falls back to the far-right edge if nothing found.
//
// Phase 14.7-09: a second form — _spellStageSourceRect({row, col}) —
// anchors to a board tile for trigger-driven windows where the source
// is a minion on the board (Start/End/Death triggers, summon effects).
function _spellStageSourceRect(playerIdxOrPos) {
    // Board-tile source (Phase 14.7-09).
    if (playerIdxOrPos && typeof playerIdxOrPos === 'object'
        && playerIdxOrPos.row != null && playerIdxOrPos.col != null) {
        var tileEl = document.querySelector(
            '.board-cell[data-row="' + playerIdxOrPos.row
            + '"][data-col="' + playerIdxOrPos.col + '"]'
        );
        if (tileEl) return tileEl.getBoundingClientRect();
        return { left: window.innerWidth / 2, top: window.innerHeight / 2, width: 1, height: 1 };
    }

    var playerIdx = playerIdxOrPos;
    if (playerIdx != null) {
        if (sandboxMode) {
            var el = document.getElementById('sandbox-hand-p' + playerIdx);
            if (el) return el.getBoundingClientRect();
        } else {
            var id = (playerIdx === myPlayerIdx) ? 'hand-container' : 'oppHandRow';
            var el2 = document.getElementById(id);
            if (el2) return el2.getBoundingClientRect();
        }
    }
    return { left: window.innerWidth, top: window.innerHeight / 2, width: 1, height: 1 };
}

// Queue for sequential push processing. Without this, rapid-fire pushes
// (sandbox test runs, or fast human chains) interrupt each other's fly-in
// transitions because each _doShowSpellStage flushes the previous shift
// mid-flight. Queueing lets each card complete its fly-in + hold + shift
// before the next one starts. Resolution defers until the queue drains.
var _spellStageQueue = [];
var _spellStageBusy = false;
var _spellStagePendingResolve = false;

// Audit fix (2026-07-06): hard reset of every spell-stage artifact. The
// stage was never reset on game over / leave / new game — leaving mid-react
// kept the previous game's cards stacked (visible at the next game's start)
// and a stale chain kept isSpellStageAnimating() true, soft-gating inputs.
// Also parks the react banner + floating Skip React pill.
function _resetSpellStageHard() {
    if (_spellStage.exitTimer) {
        clearTimeout(_spellStage.exitTimer);
        _spellStage.exitTimer = null;
    }
    _spellStage.chain = [];
    _spellStage.casterIdx = null;
    _spellStage.resolving = false;
    _spellStageQueue = [];
    _spellStageBusy = false;
    _spellStagePendingResolve = false;
    var els = _spellStageEls();
    if (els.left) els.left.innerHTML = '';
    if (els.right) els.right.innerHTML = '';
    if (els.root) {
        els.root.hidden = true;
        els.root.classList.remove('exit');
        els.root.classList.remove('enter');
    }
    var fsb = document.getElementById('floating-skip-react-btn');
    if (fsb) fsb.hidden = true;
    var rb = document.getElementById('react-banner');
    if (rb) rb.remove();
}
var SPELL_STAGE_PER_CARD_MS = 1500;  // 520ms fly-in + 1000ms hold beat ≈ shift starts

function _showSpellStage(numericId, sourcePlayerIdx) {
    _spellStageQueue.push({ nid: numericId, playerIdx: sourcePlayerIdx });
    if (!_spellStageBusy) _processSpellStageQueue();
}

function _processSpellStageQueue() {
    if (_spellStageQueue.length === 0) {
        _spellStageBusy = false;
        if (_spellStagePendingResolve) {
            _spellStagePendingResolve = false;
            _doSpellStageResolve();
        }
        return;
    }
    _spellStageBusy = true;
    var next = _spellStageQueue.shift();
    _doShowSpellStage(next.nid, next.playerIdx);
    setTimeout(_processSpellStageQueue, SPELL_STAGE_PER_CARD_MS);
}

// Slam a card onto its owner's stack with a small random rotation.
// The first card defines the caster — their cards always land on LEFT;
// the opponent's reacts always land on RIGHT.
function _doShowSpellStage(numericId, sourcePlayerIdx) {
    var els = _spellStageEls();
    if (!els.root || !els.left || !els.right) return;
    var html = _spellStageCardHtml(numericId);
    if (!html) return;

    _spellStage.resolving = false;
    if (_spellStage.exitTimer) {
        clearTimeout(_spellStage.exitTimer);
        _spellStage.exitTimer = null;
    }

    var isFirstCard = _spellStage.chain.length === 0;
    if (isFirstCard) _spellStage.casterIdx = sourcePlayerIdx;

    var goesToLeft = (sourcePlayerIdx === _spellStage.casterIdx);
    var stack = goesToLeft ? els.left : els.right;
    var otherStack = goesToLeft ? els.right : els.left;

    // Stage-centered: the react window centers between the tooltip column
    // and the screen's right edge, and scales with the design box.
    var stageMount = _stageMount();
    if (els.root.parentElement !== stageMount) stageMount.appendChild(els.root);
    els.root.hidden = false;
    els.root.classList.remove('exit');
    els.root.classList.remove('enter');
    void els.root.offsetWidth;
    els.root.classList.add('enter');

    // Build the card with a small random rotation + offset so accumulated
    // cards read like a physical pile, not a perfectly-stacked deck.
    var rotation = (Math.random() * 10 - 5).toFixed(2);  // -5..+5 deg
    // Per-card offset within the stack: each card on top sits a few px
    // down and a touch off-center, alternating side, so underlying cards
    // peek out of the pile.
    var stackDepth = 0;
    for (var ci = 0; ci < _spellStage.chain.length; ci++) {
        if (_spellStage.chain[ci].side === (goesToLeft ? 'left' : 'right')) stackDepth++;
    }
    // Base of the stack centers cleanly; subsequent cards drift slightly.
    var offX = stackDepth === 0 ? 0 : ((Math.random() * 20 - 10) | 0);   // -10..+10 px
    var offY = stackDepth === 0 ? 0 : stackDepth * 8 + ((Math.random() * 6 - 3) | 0);  // grow downward
    var card = document.createElement('div');
    card.className = 'spell-stage-stack-card';
    card.innerHTML = html;
    // Layer: each new card on top.
    card.style.zIndex = String(10 + _spellStage.chain.length);

    // Slam-in: pre-position over the source hand at small scale, then
    // animate to the stack with an over-scale punch on landing.
    var stackRect = stack.getBoundingClientRect();
    var src = _spellStageSourceRect(sourcePlayerIdx);
    var dx = (src.left + src.width / 2) - (stackRect.left + stackRect.width / 2);
    var dy = (src.top + src.height / 2) - (stackRect.top + stackRect.height / 2);
    // Audit fix (2026-07-07): rects are viewport px but the transform runs
    // INSIDE the scaled .game-layout — divide by the scale or the slam-in
    // overshoots by the --duel-scale factor on desktop (read as "chopped").
    var _sc = parseFloat(getComputedStyle(document.documentElement)
        .getPropertyValue('--duel-scale')) || 1;
    dx /= _sc;
    dy /= _sc;
    var restTransform = 'translate(' + offX + 'px, ' + offY + 'px) rotate(' + rotation + 'deg)';
    card.style.setProperty('--slam-from', 'translate(' + dx + 'px, ' + dy + 'px) scale(0.4) rotate(0deg)');
    card.style.setProperty('--slam-mid', restTransform.replace('rotate(', 'scale(1.06) rotate('));
    card.style.setProperty('--slam-to', restTransform);
    card.classList.add('slam-in');
    stack.appendChild(card);

    _spellStage.chain.push({
        nid: numericId,
        playerIdx: sourcePlayerIdx,
        el: card,
        side: goesToLeft ? 'left' : 'right',
    });

    // Move the placeholder to the OTHER stack (the one now waiting to
    // react) and pulse it. Skip on first card too — opponent owes a
    // react to the original cast.
    _movePlaceholderTo(otherStack, els);
}

// Re-parent the placeholder into the given stack and pulse it. Resets
// its 'confirmed' state (👍 is only set when chain finishes).
function _movePlaceholderTo(stackEl, els) {
    var ph = els.placeholder;
    if (!ph || !stackEl) return;
    ph.classList.remove('confirmed', 'pulse');
    ph.textContent = '?';
    if (ph.parentNode !== stackEl) {
        stackEl.appendChild(ph);
    }
    // Force pulse to re-trigger.
    ph.classList.add('visible');
    void ph.offsetWidth;
    ph.classList.add('pulse');
}

function _spellStageOnReactClosed() {
    if (_spellStage.resolving) return;
    // Wait for any pending pushes to fully animate before resolving.
    if (_spellStageBusy || _spellStageQueue.length > 0) {
        _spellStagePendingResolve = true;
        return;
    }
    _doSpellStageResolve();
}

function _doSpellStageResolve() {
    var els = _spellStageEls();
    if (!els.root || els.root.hidden) return;
    _spellStage.resolving = true;

    var chain = _spellStage.chain.slice();
    if (chain.length === 0) {
        _spellStage.exitTimer = setTimeout(_hideSpellStage, 200);
        return;
    }

    // Show 👍 over whichever stack the placeholder is currently on (the
    // side that was waiting for the next react). Then start LIFO pop.
    var ph = els.placeholder;
    if (ph) {
        ph.textContent = '👍';
        ph.classList.add('confirmed');
        ph.classList.remove('pulse');
    }

    var i = chain.length - 1;
    setTimeout(function() {
        _resolveSpellStageStep(chain, i, els);
    }, 700);
}

// LIFO resolution: top card pulses + fades from its stack, then we
// recurse onto the next-down card. No glide, no slot juggling — the
// stacks are now a stable visual that just gets popped one card at a
// time.
function _resolveSpellStageStep(chain, i, els) {
    if (i < 0) {
        // Hide placeholder before fading the stage so 👍 doesn't outlive
        // the cards.
        if (els.placeholder) {
            els.placeholder.classList.remove('visible', 'confirmed', 'pulse');
        }
        _spellStage.exitTimer = setTimeout(_hideSpellStage, 250);
        return;
    }

    var entry = chain[i];
    var card = entry && entry.el;
    if (card) {
        card.classList.remove('slam-in');
        // Force reflow so resolve-pop animation re-applies cleanly.
        void card.offsetWidth;
        card.classList.add('resolve-pop');
    }

    setTimeout(function() {
        if (card && card.parentNode) card.parentNode.removeChild(card);
        _resolveSpellStageStep(chain, i - 1, els);
    }, 550);
}

// Phase 14.8-05: detectReactWindowClose and detectSpellStageClose were
// DELETED. Both functions diffed snapshot state to infer spell-chain
// resolution; both are superseded by the playReactWindowClosed slot
// handler which consumes EVT_REACT_WINDOW_CLOSED directly from the
// engine event stream.

function _clearSpellStageTimers() {
    if (_spellStage.exitTimer) { clearTimeout(_spellStage.exitTimer); _spellStage.exitTimer = null; }
}

function _hideSpellStage() {
    _clearSpellStageTimers();
    var els = _spellStageEls();
    if (!els.root) return;
    els.root.classList.add('exit');
    setTimeout(function() {
        els.root.hidden = true;
        els.root.classList.remove('exit');
        els.root.classList.remove('enter');
        // Clear stack cards but keep the placeholder element (re-parent
        // it back to the root for next session).
        if (els.left) {
            Array.from(els.left.querySelectorAll('.spell-stage-stack-card')).forEach(function(c) {
                if (c.parentNode) c.parentNode.removeChild(c);
            });
        }
        if (els.right) {
            Array.from(els.right.querySelectorAll('.spell-stage-stack-card')).forEach(function(c) {
                if (c.parentNode) c.parentNode.removeChild(c);
            });
        }
        if (els.placeholder) {
            els.placeholder.classList.remove('visible', 'pulse', 'confirmed');
            els.placeholder.textContent = '?';
            // Park it back on the root so it's not stuck inside an empty stack.
            if (els.placeholder.parentNode !== els.root) {
                els.root.appendChild(els.placeholder);
            }
        }
        _spellStage.chain = [];
        _spellStage.casterIdx = null;
        _spellStage.resolving = false;

        // Phase 14.8-04b: the old post-stage deferral logic has been
        // DELETED. Previously _hideSpellStage would flush a parked sandbox
        // frame, fire a deferred trigger blip, and run a deferred turn
        // banner — all coordinated via ad-hoc buffer globals + the sandbox
        // frame queue drain. That entire coordination is superseded by the
        // eventQueue: the server emits react-window-close BEFORE trigger-
        // blip BEFORE turn-flip in seq order, and each handler calls done()
        // only after its animation completes, so the user-expected order
        // (stage close → HP commit → blip → banner) falls out of FIFO queue
        // discipline without any deferral machinery.
    }, 360);
}

// Phase 14.8-05: detectSpellCast DELETED. Replaced by the cooperating
// pair of playCardPlayed + playReactWindowOpened slot handlers — the
// former stashes the originator in slotState.lastOriginator, the latter
// consumes it to slam the card onto the spell-stage LEFT slot.

// Phase 14.8-05: deriveCardFlyJobs, _deriveFlyForPlayer, and the
// _multisetDelta helper DELETED. Replaced by playCardDiscarded and
// playCardPlayed slot handlers (plan 14.8-04a). playCardFlyAnimation
// and _zoneButton below are RETAINED — the card-fly ghost primitive
// is still used by the summon animation path.

function _zoneButton(zone) {
    // Piles live on the pile boards beside the game board (2026-07-05) —
    // card-fly animations land on the matching pile cell.
    var own = zone.indexOf('_own') !== -1;
    var kind = zone.indexOf('grave') === 0 ? 'grave' : 'exhaust';
    var screen = sandboxMode ? '#screen-sandbox' : '#screen-game';
    var el = document.querySelector(
        screen + ' .pile-board-' + (own ? 'own' : 'opp') + ' [data-pile="' + kind + '"]');
    return (el && el.getBoundingClientRect().width > 0) ? el : null;
}

// Generic card-to-pile fly animation: ghost starts at fromRect, flies to
// the destination pile button, shrinking and fading as it goes.
function playCardFlyAnimation(job, done) {
    var from = job.fromRect;
    var toEl = _zoneButton(job.toZone);
    if (!from || !toEl) { setTimeout(done, 0); return; }
    var to = toEl.getBoundingClientRect();
    var def = cardDefs && cardDefs[job.cardNumericId];
    if (!def) { setTimeout(done, 0); return; }

    var ghost = document.createElement('div');
    ghost.className = 'card-fly-ghost';
    ghost.style.left = from.left + 'px';
    ghost.style.top = from.top + 'px';
    ghost.style.width = from.width + 'px';
    ghost.style.height = from.height + 'px';
    ghost.innerHTML = renderCardFrame(def, {
        context: 'hand',
        numericId: job.cardNumericId,
        interactive: false,
        showReactDeploy: false,
    });
    document.body.appendChild(ghost);

    var dx = (to.left + to.width / 2) - (from.left + from.width / 2);
    var dy = (to.top + to.height / 2) - (from.top + from.height / 2);
    var scale = Math.max(0.15, Math.min(1, to.width / from.width));

    // Force a reflow so the starting position is committed, then transition.
    void ghost.offsetWidth;
    ghost.style.transform = 'translate(' + dx + 'px, ' + dy + 'px) scale(' + scale + ')';
    ghost.style.opacity = '0';

    var finished = false;
    function finish() {
        if (finished) return;
        finished = true;
        if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
        done();
    }
    ghost.addEventListener('transitionend', finish);
    setTimeout(finish, 750);
}

// Phase 14.8-05: deriveDrawJobs and deriveAnimationJob DELETED. Replaced
// by the playCardDrawn + playMinionSummoned + playMinionMoved +
// playAttackResolved + playSacrificeTranscend slot handlers (plan 14.8-04a).
// The eventQueue pipeline consumes engine events directly — no snapshot
// diff needed.

// =============================================
// Game log (rebuilt 2026-07-06) — event-driven, copyable, debug-grade.
//
// The old writer, logStateDiff, sat on the legacy state_update wire format
// that Phase 14.8-05 deleted server-side, so the log showed only the
// "Game started." line. The live pipeline is engine_events → onEngineEvents;
// logEngineEvent() below is called there per event, at enqueue time, in seq
// order. Plain-text lines accumulate unbounded in window.__gameLog (also
// copyable from the console); the DOM view is capped at LOG_DOM_CAP entries.
// =============================================
var LOG_DOM_CAP = 400;
var _logTurn = null;                 // maintained from turn_flipped events
var _logMinions = {};                // instance_id -> {name, owner}
window.__gameLog = window.__gameLog || [];

function clearGameLog() {
    var entries = document.getElementById('log-entries');
    if (entries) entries.innerHTML = '';
    window.__gameLog = [];
    _logTurn = null;
    _logMinions = {};
}

// opts (all optional): {plain: export-line override, title: hover tooltip,
// detail: true → dimmed tier hidden unless Verbose is on}
function addLogEntry(text, type, opts) {
    opts = opts || {};
    window.__gameLog.push(opts.plain != null ? opts.plain : ('[----] [T' + (_logTurn == null ? '?' : _logTurn) + '] ' + text));
    var entries = document.getElementById('log-entries');
    if (!entries) return;
    var entry = document.createElement('div');
    entry.className = 'log-entry' + (type ? ' log-' + type : '') + (opts.detail ? ' log-detail' : '');
    if (opts.title) entry.title = opts.title;
    var time = new Date();
    var timeStr = String(time.getHours()).padStart(2, '0') + ':' + String(time.getMinutes()).padStart(2, '0') + ':' + String(time.getSeconds()).padStart(2, '0');
    var timeEl = document.createElement('span');
    timeEl.className = 'log-time';
    timeEl.textContent = timeStr;
    entry.appendChild(timeEl);
    // textContent (not innerHTML) — chat-parity XSS safety: opponentName and
    // card names must never be parsed as markup.
    entry.appendChild(document.createTextNode(' ' + text));
    // Only autoscroll when the user is already at the bottom, so an
    // in-progress text selection (copy!) isn't yanked away mid-drag.
    var nearBottom = (entries.scrollHeight - entries.scrollTop - entries.clientHeight) < 40;
    entries.appendChild(entry);
    while (entries.children.length > LOG_DOM_CAP) {
        entries.removeChild(entries.firstChild);
    }
    if (nearBottom) entries.scrollTop = entries.scrollHeight;
}

// ---- formatting helpers ----------------------------------------------

function _logCardName(id) {
    if (id == null) return 'a card';
    var d = cardDefs && cardDefs[id];
    return (d && d.name) ? d.name : ('card#' + id);
}

function _logPos(pos) {
    // Chess-style tiles (user 2026-07-07): columns A-E, rows 1-5 — [B,1]
    // instead of raw engine (row,col).
    if (!pos || pos.length < 2) return '[?,?]';
    var col = 'ABCDE'.charAt(pos[1]) || '?';
    var row = (typeof pos[0] === 'number') ? pos[0] + 1 : '?';
    return '[' + col + ',' + row + ']';
}

function _logPlayer(idx) {
    if (idx == null) return '[P?]';
    // Spectators get a real seat idx from the server (your_player_idx: 0),
    // so gate on isSpectator explicitly — not on a null seat.
    // P1 = the player who went first (engine idx 0), P2 = second (user 2026-07-07).
    var n = idx + 1;
    if (typeof isSpectator !== 'undefined' && isSpectator) return '[P' + n + ']';
    if (myPlayerIdx != null && idx === myPlayerIdx) return '[P' + n + '·You]';
    if (myPlayerIdx != null) return '[P' + n + '·' + (opponentName || 'Opp') + ']';
    return '[P' + n + ']';
}

// attack_resolved / trigger_blip carry only instance_ids — resolve names via
// a registry fed by minion_summoned/transformed, falling back to live state
// and the last final_state snapshot.
function _logMinionInfo(instanceId) {
    if (instanceId == null) return null;
    if (_logMinions[instanceId]) return _logMinions[instanceId];
    var pools = [];
    var live = (typeof sandboxMode !== 'undefined' && sandboxMode) ? sandboxState : gameState;
    if (live && live.minions) pools.push(live.minions);
    if (window.__lastFinalState && window.__lastFinalState.minions) {
        pools.push(window.__lastFinalState.minions);
    }
    for (var pi = 0; pi < pools.length; pi++) {
        for (var mi = 0; mi < pools[pi].length; mi++) {
            var m = pools[pi][mi];
            if (m && m.instance_id === instanceId) {
                var info = {
                    name: _logCardName(m.card_numeric_id),
                    owner: (m.owner != null ? m.owner : m.owner_idx),
                };
                _logMinions[instanceId] = info;
                return info;
            }
        }
    }
    return null;
}

function _logMinionName(instanceId) {
    var info = _logMinionInfo(instanceId);
    return info ? info.name : ('m#' + instanceId);
}

function _logBurnSource(src) {
    if (src === 'turn_start') return 'overdraw, hand full';
    if (src === 'tutor') return 'tutor';
    if (src === 'decline_conjure') return 'declined conjure';
    if (src === 'card_effect') return 'card effect';
    return src || 'unknown';
}

// ---- per-event formatter ---------------------------------------------
// Payload schemas: src/grid_tactics/engine_events.py (~line 190).
// KNOWN ENGINE GAP: minion_hp_change is currently emitted only for burn
// ticks — spell damage/heals to minions produce no event, so they appear
// in the log only via their card_played/trigger_blip lines.
function logEngineEvent(ev) {
    if (!ev || !ev.type) return;
    var p = ev.payload || {};
    if (_logTurn == null) {
        var live = (typeof sandboxMode !== 'undefined' && sandboxMode) ? sandboxState : gameState;
        _logTurn = (live && typeof live.turn_number === 'number') ? live.turn_number : 1;
    }
    var text = null;
    var cls = '';          // '' | damage | heal | react | turn | card | trigger | burn | over | debug
    var detail = false;    // detail tier: dimmed, hidden unless Verbose; always exported
    var i, parts;

    switch (ev.type) {
        case 'minion_summoned':
            _logMinions[p.instance_id] = { name: _logCardName(p.card_numeric_id), owner: p.owner_idx };
            text = _logPlayer(p.owner_idx) + ' summons ' + _logCardName(p.card_numeric_id)
                 + ' at ' + _logPos(p.position) + ' [m#' + p.instance_id + ']';
            cls = 'card';
            break;
        case 'minion_died':
            text = _logPlayer(p.owner_idx) + ' ' + _logCardName(p.card_numeric_id)
                 + ' dies at ' + _logPos(p.position)
                 + (p.from_deck ? ' (from deck)' : '') + ' [m#' + p.instance_id + ']';
            cls = 'damage';
            break;
        case 'minion_hp_change':
            text = _logPlayer(p.owner_idx) + ' ' + _logMinionName(p.instance_id) + ' ' + _logPos(p.position)
                 + ' ' + (p.cause || 'hp') + ' ' + (p.delta > 0 ? '+' : '') + p.delta
                 + ' → ' + p.new_hp + '🤍';
            cls = (p.delta < 0) ? 'damage' : 'heal';
            break;
        case 'minion_moved':
            text = _logPlayer(p.owner_idx) + ' ' + _logMinionName(p.instance_id)
                 + ' moves ' + _logPos(p.from) + '→' + _logPos(p.to);
            break;
        case 'minion_transformed':
            var oldName = _logMinionName(p.instance_id);
            _logMinions[p.instance_id] = { name: _logCardName(p.to_card_numeric_id), owner: p.owner_idx };
            text = _logPlayer(p.owner_idx) + ' '
                 + (p.from_card_numeric_id != null ? _logCardName(p.from_card_numeric_id) : oldName)
                 + ' → ' + _logCardName(p.to_card_numeric_id)
                 + ' at ' + _logPos(p.position) + ', ' + p.new_hp + '🤍';
            cls = 'card';
            break;
        case 'minion_sacrificed':
            text = _logPlayer(p.owner_idx) + ' SACRIFICE ' + _logCardName(p.card_numeric_id)
                 + ' at ' + _logPos(p.position) + ': ' + p.damage + ' dmg to opponent';
            cls = 'damage';
            break;
        case 'attack_resolved':
            var atkInfo = _logMinionInfo(p.attacker_id);
            var dmg = (p.defender_hp_before != null && p.defender_hp_after != null)
                ? (p.defender_hp_before - p.defender_hp_after) : null;
            text = (atkInfo ? _logPlayer(atkInfo.owner) + ' ' : '')
                 + _logMinionName(p.attacker_id) + ' attacks ' + _logMinionName(p.defender_id)
                 + ' ' + _logPos(p.target_pos) + ': '
                 + p.defender_hp_before + '→' + p.defender_hp_after + '🤍'
                 + (dmg != null ? ' (-' + dmg + ')' : '');
            if (p.attacker_hp_before !== p.attacker_hp_after) {
                text += '; retaliation: attacker ' + p.attacker_hp_before + '→' + p.attacker_hp_after;
            }
            if (p.defender_killed) text += ' — ' + _logMinionName(p.defender_id) + ' DIES';
            if (p.attacker_killed) text += ' — attacker DIES';
            cls = 'damage';
            break;
        case 'card_drawn':
            if (p.card_numeric_id != null) {
                text = _logPlayer(p.player_idx) + ' draws ' + _logCardName(p.card_numeric_id)
                     + (p.source ? ' (' + p.source + ')' : '');
                cls = 'card';
            } else {
                // opponent draw — card id redacted by view_filter
                var elem = p.element || p.card_element;
                text = _logPlayer(p.player_idx) + ' draws a card'
                     + (elem ? ' (' + elem + ')' : '')
                     + (p.source ? ' (' + p.source + ')' : '');
                detail = true;
            }
            break;
        case 'card_played':
            var def = cardDefs && cardDefs[p.card_numeric_id];
            text = _logPlayer(p.owner_idx) + ' plays ' + _logCardName(p.card_numeric_id)
                 + (def && def.cost != null ? ' (' + def.cost + ' mana)' : '')
                 + (p.position ? ' at ' + _logPos(p.position) : '')
                 + (p.target_pos ? ' → target ' + _logPos(p.target_pos) : '')
                 + (p.is_react ? ' [REACT]' : '');
            cls = p.is_react ? 'react' : 'card';
            break;
        case 'card_discarded':
            text = _logPlayer(p.player_idx) + ' discards ' + _logCardName(p.card_numeric_id)
                 + ' → graveyard';
            cls = 'card';
            break;
        case 'card_burned':
        case 'overdraw_burn':
        case 'card_overdrawn':
        case 'card_exhausted':
            text = _logPlayer(p.player_idx)
                 + (p.source === 'turn_start' ? ' OVERDRAWS — ' : ' ')
                 + _logCardName(p.card_numeric_id)
                 + ' EXHAUSTED (' + _logBurnSource(p.source) + ')';
            cls = 'burn';
            break;
        case 'handshake':
        case 'handshake_resolved':
            parts = [];
            if (Array.isArray(p.outcomes)) {
                for (i = 0; i < p.outcomes.length; i++) {
                    var o = p.outcomes[i];
                    var r = o.reward === 'mana' ? '+1 mana'
                          : o.reward === 'card_drawn' ? 'draws (full mana)'
                          : o.reward === 'card_burned' ? 'overdraws — card exhausted (hand full)'
                          : 'no reward';
                    parts.push(_logPlayer(o.player_idx) + ': ' + r);
                }
            }
            text = '🤝 HANDSHAKE' + (parts.length ? ' — ' + parts.join('; ') : '');
            cls = 'heal';
            break;
        case 'mana_change':
            // Sandbox cheat edits omit `delta` — derive it.
            var _md = (p.delta != null) ? p.delta : (p.new - p.prev);
            text = _logPlayer(p.player_idx) + ' mana ' + p.prev + '→' + p.new
                 + ' (' + (_md > 0 ? '+' : '') + _md + ')';
            detail = true;
            break;
        case 'player_hp_change':
            if (p.cause === 'fatigue') {
                text = _logPlayer(p.player_idx) + ' FATIGUE ' + p.delta + ': '
                     + p.prev + '→' + p.new + '🤍 (empty deck)';
            } else {
                var _hd = (p.delta != null) ? p.delta : (p.new - p.prev);
                text = _logPlayer(p.player_idx) + ' ' + p.prev + '→' + p.new + '🤍'
                     + ' (' + (_hd > 0 ? '+' : '') + _hd + ')'
                     + (p.cause ? ' [' + p.cause + ']' : '');
            }
            cls = (((p.delta != null) ? p.delta : (p.new - p.prev)) < 0) ? 'damage' : 'heal';
            break;
        case 'dark_matter_change':
            text = _logPlayer(p.player_idx) + ' Dark Matter ' + p.prev + '→' + p.new
                 + ' (' + (p.delta > 0 ? '+' : '') + p.delta + ')';
            break;
        case 'react_window_opened':
            // react_context typing is inconsistent server-side (int enum from
            // action_resolver, string name from react_stack) — show either.
            text = '⚡ react window: ' + _logPlayer(p.react_player_idx) + ' may react'
                 + ' (' + String(p.react_context)
                 + (p.return_phase != null ? ', return→' + String(p.return_phase) : '') + ')';
            cls = 'react';
            detail = true;
            break;
        case 'react_window_closed':
            text = '⚡ react window closed → ' + String(p.return_phase)
                 + (p.shortcut ? ' [shortcut]' : '');
            cls = 'react';
            detail = true;
            break;
        case 'phase_changed':
            text = 'phase ' + String(p.prev) + '→' + String(p.new);
            detail = true;
            break;
        case 'pass_declared':
            text = _logPlayer(p.player_idx) + ' passes'
                 + (p.streak === 1 ? ' (Handshake offered 🫴)'
                    : (p.handshake_pending ? ' (Handshake! 🤝)' : ''));
            break;
        case 'turn_flipped':
            if (typeof p.new_turn === 'number') _logTurn = p.new_turn;
            var _spec = (typeof isSpectator !== 'undefined' && isSpectator);
            var whoseTurn = (!_spec && myPlayerIdx != null && p.new_active_idx === myPlayerIdx)
                ? 'You' : ((!_spec && myPlayerIdx != null) ? (opponentName || 'Opponent') : 'P' + (p.new_active_idx + 1));
            text = '— Turn ' + p.new_turn + ': ' + whoseTurn + ' —';
            cls = 'turn';
            break;
        case 'trigger_blip':
            text = 'trigger ' + p.trigger_kind + ': ' + _logMinionName(p.source_minion_id)
                 + ' ' + _logPos(p.source_position) + ' → ' + p.effect_kind
                 + (p.target_position ? ' @ ' + _logPos(p.target_position) : '');
            cls = 'trigger';
            break;
        case 'pending_modal_opened':
            text = _logPlayer(p.owner_idx) + ' must choose: ' + p.modal_kind
                 + ' (' + p.options_count + ' options'
                 + (p.remaining != null ? ', ' + p.remaining + ' remaining' : '') + ')';
            detail = true;
            break;
        case 'pending_modal_resolved':
            text = 'choice resolved: ' + p.modal_kind
                 + (p.picked_position ? ' → ' + _logPos(p.picked_position) : '');
            detail = true;
            break;
        case 'fizzle':
            text = '✗ FIZZLE ' + p.trigger_kind
                 + ' (' + _logCardName(p.source_card_numeric_id) + '): '
                 + (p.reason || 'unknown reason');
            cls = 'burn';
            break;
        case 'game_over':
            text = '★ GAME OVER — ' + _logPlayer(p.winner) + ' wins ('
                 + (p.reason || 'unknown') + ')';
            cls = 'over';
            break;
        default:
            // never silently drop unknown events — they matter most for debugging
            var pj = '';
            try { pj = JSON.stringify(p); } catch (e2) { pj = '<unserializable>'; }
            text = ev.type + ' ' + pj.slice(0, 120);
            cls = 'debug';
            detail = true;
            break;
    }
    if (text == null) return;

    var nested = (ev.triggered_by_seq != null);
    if (nested && cls !== 'turn') text = '↳ ' + text;
    var tPrefix = 'T' + _logTurn + ' ';
    var domText = (cls === 'turn') ? text : (tPrefix + text);

    // Plain-text export line: "[seq] [T<turn>] message" + debug suffixes
    var seqStr = String(ev.seq);
    while (seqStr.length < 4) seqStr = '0' + seqStr;
    var plain = '[' + seqStr + '] [T' + _logTurn + '] ' + text
        + (ev.contract_source ? ' | src=' + ev.contract_source : '')
        + (nested ? ' by=' + ev.triggered_by_seq : '');

    // Hover tooltip: raw type + seq + truncated JSON payload
    var rawJson = '';
    try { rawJson = JSON.stringify(p); } catch (e3) { rawJson = '<unserializable>'; }
    var title = ev.type + ' seq=' + ev.seq
        + (nested ? ' by=' + ev.triggered_by_seq : '')
        + ' ' + rawJson.slice(0, 200);

    addLogEntry(domText, cls || null, { plain: plain, title: title, detail: detail });
}

// ---- Log toolbar: Copy button + Verbose toggle ------------------------

function setupLogToolbar() {
    var copyBtn = document.getElementById('btn-log-copy');
    var verbose = document.getElementById('log-verbose-toggle');
    var entries = document.getElementById('log-entries');
    if (verbose && entries) {
        verbose.addEventListener('change', function() {
            entries.classList.toggle('log-verbose-on', verbose.checked);
            entries.scrollTop = entries.scrollHeight;
        });
    }
    if (copyBtn) {
        copyBtn.addEventListener('click', function() {
            var header = [
                'Grid Tactics game log',
                'room=' + (typeof roomCode !== 'undefined' && roomCode ? roomCode : '?')
                    + ' seat=' + ((myPlayerIdx != null && !(typeof isSpectator !== 'undefined' && isSpectator)) ? 'P' + (myPlayerIdx + 1) : 'spectator')
                    + ' opponent=' + (opponentName || '?'),
                'exported ' + new Date().toISOString() + ' lastSeenSeq=' + lastSeenSeq,
                '',
            ].join('\n');
            var full = header + (window.__gameLog || []).join('\n');
            function feedback(ok) {
                copyBtn.textContent = ok ? 'Copied ✓' : 'Copy failed';
                setTimeout(function() { copyBtn.textContent = 'Copy'; }, 1200);
            }
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(full).then(
                    function() { feedback(true); },
                    function() { feedback(_logCopyFallback(full)); }
                );
            } else {
                feedback(_logCopyFallback(full));
            }
        });
    }
}

function _logCopyFallback(text) {
    // execCommand path for non-secure contexts (http:// LAN testing)
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
}

// Log differences between previous and new state.
// NOTE (2026-07-06): CONFIRMED DEAD during live play — its only call site is
// _applyStateFrameImmediate on the legacy state_update path, and post-action
// state_update emits were deleted server-side in Phase 14.8-05. It can still
// fire on game_start/reconnect snapshots, where the diff is empty or benign.
// Superseded by logEngineEvent() above; kept per no-delete policy.
function logStateDiff(prev, next) {
    if (!prev || !next) return;
    var myName = (gameState && myPlayerIdx != null && gameState.players && gameState.players[myPlayerIdx]) ? 'You' : 'You';
    var oppName = opponentName || 'Opponent';

    // Turn change
    if (prev.turn_number !== next.turn_number) {
        var who = next.active_player_idx === myPlayerIdx ? 'Your' : oppName + "'s";
        addLogEntry('Turn ' + next.turn_number + ' — ' + who + ' turn');
    }

    // Phase change to REACT (someone took an action)
    if (prev.phase !== next.phase && next.phase === 1 && next.pending_action) {
        var pa = next.pending_action;
        var actor = next.active_player_idx === myPlayerIdx ? 'You' : oppName;
        var msg = describeAction(pa, prev, next, actor);
        if (msg) addLogEntry(msg);
    }

    // HP changes
    for (var i = 0; i < 2; i++) {
        var prevHp = prev.players?.[i]?.hp;
        var nextHp = next.players?.[i]?.hp;
        if (prevHp != null && nextHp != null && prevHp !== nextHp) {
            var diff = nextHp - prevHp;
            var who = i === myPlayerIdx ? 'You' : oppName;
            if (diff < 0) {
                addLogEntry(who + ' took ' + (-diff) + ' damage (' + nextHp + ' HP)', 'damage');
            } else {
                addLogEntry(who + ' healed +' + diff + ' (' + nextHp + ' HP)', 'heal');
            }
        }
    }

    // Minion count change
    var prevMinions = prev.minions?.length || 0;
    var nextMinions = next.minions?.length || 0;
    if (nextMinions > prevMinions) {
        addLogEntry((nextMinions - prevMinions) + ' minion(s) deployed');
    } else if (nextMinions < prevMinions) {
        addLogEntry((prevMinions - nextMinions) + ' minion(s) destroyed');
    }

    // Phase 14.2: tutor pick is now an explicit modal flow (showTutorModal),
    // not a silent hand-growth detection. The old auto-tutor heuristic that
    // lived here has been removed — pending_tutor_player_idx in state frames
    // drives the modal directly via syncPendingTutorUI().
}

function describeAction(pa, prevState, nextState, actor) {
    if (!pa) return null;
    var t = pa.action_type;
    if (t === 0) {
        // PLAY_CARD — try to find what was played
        if (pa.position) {
            return actor + ' played a card at row ' + (pa.position[0] + 1) + ' col ' + (pa.position[1] + 1);
        }
        return actor + ' cast a magic card';
    }
    if (t === 1) return actor + ' moved a minion';
    if (t === 2) return actor + ' attacked';
    if (t === 3) return actor + ' drew a card';
    if (t === 6) return actor + ' sacrificed a minion for damage';
    return null;
}

function onGameOver(data) {
    // Timing audit (2026-07-06): the game_over socket frame arrives in
    // parallel with the engine_events batch that carries the lethal beats.
    // If the queue is still draining, stash the payload — the queued
    // game_over EVENT (playGameOver) shows the overlay at ITS beat, after
    // the killing blow has actually played.
    if (typeof isEventQueueBusy === 'function' && isEventQueueBusy()) {
        window.__pendingGameOverData = data;
        return;
    }
    _applyGameOver(data);
}

function _applyGameOver(data) {
    gameState = data.final_state;
    legalActions = [];
    // A lethal react can end the game while the spell stage / Skip React
    // pill are still up — park them under the game-over overlay.
    if (typeof _resetSpellStageHard === 'function') _resetSpellStageHard();
    renderGame();
    var winner = data.final_state && data.final_state.winner;
    if (winner != null && myPlayerIdx != null) {
        playSfx(winner === myPlayerIdx ? 'victory' : 'defeat');
    }
    showGameOver(data);
}

// Phase 14 PLAY-03: game over modal

function deriveGameOverReason(finalState) {
    if (finalState == null || finalState.winner == null) {
        return 'Draw';
    }
    var winner = finalState.winner;
    var loser = 1 - winner;
    var loserHp = (finalState.players && finalState.players[loser]) ? finalState.players[loser].hp : null;
    if (loserHp != null && loserHp <= 0) {
        return 'HP depleted';
    }
    return 'Sacrifice damage';
}

function showGameOver(data) {
    var overlay = document.getElementById('game-over-overlay');
    if (!overlay) return;
    resetRematchUI();

    var finalState = data.final_state;
    var winner = (data.winner != null) ? data.winner : (finalState ? finalState.winner : null);
    var iWon = (winner != null) && (winner === myPlayerIdx);
    var isDraw = (winner == null);

    var resultEl = document.getElementById('game-over-result');
    if (resultEl) {
        if (isDraw) {
            resultEl.textContent = 'DRAW';
            resultEl.className = 'game-over-result draw';
        } else if (iWon) {
            resultEl.textContent = 'VICTORY';
            resultEl.className = 'game-over-result victory';
        } else {
            resultEl.textContent = 'DEFEAT';
            resultEl.className = 'game-over-result defeat';
        }
    }

    var reasonEl = document.getElementById('game-over-reason');
    if (reasonEl) {
        reasonEl.textContent = deriveGameOverReason(finalState);
    }

    if (finalState && finalState.players && myPlayerIdx != null) {
        var selfPlayer = finalState.players[myPlayerIdx];
        var oppPlayer  = finalState.players[1 - myPlayerIdx];
        var selfNameEl = document.getElementById('game-over-self-name');
        var selfHpEl   = document.getElementById('game-over-self-hp');
        var oppNameEl  = document.getElementById('game-over-opp-name');
        var oppHpEl    = document.getElementById('game-over-opp-hp');
        if (selfNameEl) selfNameEl.textContent = (myName || 'You');
        if (selfHpEl)   selfHpEl.textContent   = selfPlayer ? selfPlayer.hp : '?';
        if (oppNameEl)  oppNameEl.textContent  = (opponentName || 'Opponent');
        if (oppHpEl)    oppHpEl.textContent    = oppPlayer ? oppPlayer.hp : '?';
    }

    overlay.style.display = 'flex';
}

function hideGameOver() {
    var overlay = document.getElementById('game-over-overlay');
    if (overlay) overlay.style.display = 'none';
}

function resetGameClientState() {
    gameState = null;
    legalActions = [];
    myPlayerIdx = null;
    opponentName = '';
    roomCode = null;
    sessionToken = null;
    selectedHandIdx = null;
    selectedMinionId = null;
    interactionMode = null;

    var roomPanel = document.getElementById('room-panel');
    if (roomPanel) roomPanel.style.display = 'none';
    var roomCodeDisplay = document.getElementById('room-code-display');
    if (roomCodeDisplay) roomCodeDisplay.textContent = '';
    var playerList = document.getElementById('player-list');
    if (playerList) playerList.innerHTML = '';
    var lobbyStatus = document.getElementById('lobby-status');
    if (lobbyStatus) {
        lobbyStatus.textContent = '';
        lobbyStatus.className = 'lobby2-status';
    }
    var gameRoomCode = document.getElementById('game-room-code');
    if (gameRoomCode) gameRoomCode.textContent = '';

    var reactBanner = document.getElementById('react-banner');
    if (reactBanner) reactBanner.remove();
    var actionBar = document.getElementById('action-bar');
    if (actionBar) actionBar.remove();
    // Audit fix (2026-07-06): leaving mid-react-chain left the spell stage
    // populated (and queued events could re-show it over the lobby via the
    // _stageMount() body fallback). Hard-reset the whole react UI.
    if (typeof resetEventQueue === 'function') resetEventQueue();

    // Reset ready button
    var btnReady = document.getElementById('btn-ready');
    if (btnReady) {
        btnReady.disabled = false;
        btnReady.textContent = 'Ready Up';
    }
}

function returnToLobby() {
    hideGameOver();
    resetGameClientState();
    showScreen('screen-lobby');
    updateNavLockState();
}

function setupGameHandlers() {
    var btnLeave = document.getElementById('btn-leave');
    if (btnLeave) {
        btnLeave.addEventListener('click', returnToLobby);
    }
    var btnBackToLobby = document.getElementById('btn-back-to-lobby');
    if (btnBackToLobby) {
        btnBackToLobby.addEventListener('click', returnToLobby);
    }
    var btnRematch = document.getElementById('btn-rematch');
    if (btnRematch) {
        btnRematch.addEventListener('click', requestRematch);
    }
    var btnMute = document.getElementById('sfx-mute-btn');
    if (btnMute) {
        var refreshMuteBtn = function () { btnMute.textContent = sfxMuted ? '🔇' : '🔊'; };
        refreshMuteBtn();
        btnMute.addEventListener('click', function () {
            setSfxMuted(!sfxMuted);
            refreshMuteBtn();
            if (!sfxMuted) playSfx('button_click');
        });
    }
}

// POLISH-03 Rematch
function requestRematch() {
    if (!socket) return;
    socket.emit('request_rematch', {});
    var btnRematch = document.getElementById('btn-rematch');
    if (btnRematch) {
        btnRematch.disabled = true;
        btnRematch.textContent = 'Waiting...';
    }
    var statusEl = document.getElementById('game-over-status');
    if (statusEl) {
        statusEl.textContent = 'Waiting for opponent...';
        statusEl.className = 'game-over-status waiting';
    }
}

function onRematchWaiting(data) {
    var statusEl = document.getElementById('game-over-status');
    if (!statusEl) return;
    if (data.requester === 'opponent') {
        var name = data.name || 'Opponent';
        statusEl.textContent = name + ' wants a rematch — click Rematch to accept';
        statusEl.className = 'game-over-status incoming';
    }
}

function resetRematchUI() {
    var btnRematch = document.getElementById('btn-rematch');
    if (btnRematch) {
        btnRematch.disabled = false;
        btnRematch.textContent = 'Rematch';
    }
    var statusEl = document.getElementById('game-over-status');
    if (statusEl) {
        statusEl.textContent = '';
        statusEl.className = 'game-over-status';
    }
}

