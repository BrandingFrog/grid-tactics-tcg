// =============================================
// Section 11: renderRoomBar() (UI-04)
// =============================================

function renderRoomBar() {
    // Turn indicator: determine if it's my turn
    var isMyTurn = legalActions && legalActions.length > 0;
    var turnDot = document.getElementById('turn-dot');
    var turnText = document.getElementById('turn-text');

    if (turnDot) {
        if (isMyTurn) {
            turnDot.className = 'turn-dot pulse-dot';
        } else {
            turnDot.className = 'turn-dot pulse-dot inactive';
        }
    }
    if (turnText) {
        if (isMyTurn) {
            turnText.textContent = 'YOUR TURN';
            turnText.className = 'turn-text';
        } else {
            turnText.textContent = "OPPONENT'S TURN";
            turnText.className = 'turn-text opp-turn';
        }
    }

    // Phase badge
    var phaseBadge = document.getElementById('phase-badge');
    if (phaseBadge && gameState.phase !== undefined) {
        _setPhaseLeds(phaseBadge, gameState.phase, gameState.react_return_phase);
    }

    // Turn number
    var turnNum = document.getElementById('turn-number');
    if (turnNum && gameState.turn_number !== undefined) {
        turnNum.textContent = 'Turn ' + gameState.turn_number;
    }

    // Spectators can't react — the REACT AUTO/OFF control is meaningless
    // and was overlapping the speed toggle (user 2026-07-11). Hide it and
    // let the speed button take its corner slot.
    var _rmBtn = document.getElementById('react-mode-btn');
    if (_rmBtn) _rmBtn.style.display = isSpectator ? 'none' : '';
    var _spBtn = document.getElementById('anim-speed-btn');
    if (_spBtn && _spBtn.classList.contains('stage-corner-btn')) {
        _spBtn.style.right = isSpectator ? '72px' : '175px';
    }

    // Phase 14.4: SPECTATING badge visibility + god-mode label.
    var specBadge = document.getElementById('spectating-badge');
    if (specBadge) {
        if (isSpectator) {
            specBadge.textContent = spectatorGodMode ? 'SPECTATING (GOD MODE)' : 'SPECTATING';
            specBadge.classList.add('visible');
        } else {
            specBadge.classList.remove('visible');
        }
    }
}

// =============================================
// Section 12: renderOpponentInfo() (UI-03)
// =============================================


// Handshake offer flag (user 2026-07-08): after the FIRST pass of a
// potential handshake, the passer's pill shows a palm-up hand until the
// opponent answers (pass -> handshake banner, anything else -> flag drops).
// consecutive_passes === 1 means exactly one unanswered pass, and the
// passer is whoever is NOT the active player.

// Waiting indicator (user 2026-07-08): a flipping hourglass over the
// avatar of whoever the game is waiting on — a pending pick first, then
// the react player during a react window, else the active player.
function _waitingOnIdx() {
    var g = gameState;
    if (!g) return null;
    if (g.pending_tutor_player_idx != null) return g.pending_tutor_player_idx;
    if (g.pending_conjure_deploy_player_idx != null) return g.pending_conjure_deploy_player_idx;
    if (g.pending_revive_player_idx != null) return g.pending_revive_player_idx;
    if (g.pending_death_target_owner_idx != null) return g.pending_death_target_owner_idx;
    if (g.phase === 1 && g.react_player_idx != null) return g.react_player_idx;
    return g.active_player_idx;
}

function _updateWaitBadge(which, playerIdx) {
    var wrap = document.querySelector('#screen-game .pod-' + which + ' .pod-ava-wrap');
    if (!wrap) return;
    var badge = wrap.querySelector('.pod-wait-badge');
    // Only show when the game is actually WAITING on a human: never while
    // the event queue / animations are draining (user 2026-07-08 — it was
    // reading raw state at beats and flagged "your turn" while input was
    // still blocked). For the local seat, additionally require that input
    // would be accepted (a board action via canActNow, or a pending pick
    // that owns a modal).
    var busy = (typeof isEventQueueBusy === 'function') && isEventQueueBusy();
    var waiting = !busy && _waitingOnIdx() === playerIdx
        && !(gameState && gameState.game_over);
    if (waiting && myPlayerIdx != null && playerIdx === myPlayerIdx) {
        var g = gameState;
        var pendingMine = g && (g.pending_tutor_player_idx === playerIdx
            || g.pending_conjure_deploy_player_idx === playerIdx
            || g.pending_revive_player_idx === playerIdx
            || g.pending_death_target_owner_idx === playerIdx);
        if (!pendingMine && typeof canActNow === 'function' && !canActNow()) {
            waiting = false;
        }
    }
    // Beats render while busy — re-check shortly so the badge appears the
    // moment the drain settles even if no further render fires.
    if (busy && !window.__waitBadgeTimer) {
        window.__waitBadgeTimer = setTimeout(function() {
            window.__waitBadgeTimer = null;
            try {
                if (gameState && gameState.players) { renderSelfInfo(); renderOpponentInfo(); }
            } catch (e) { /* defensive */ }
        }, 500);
    }
    // Unified react-wait (user 2026-07-10 MCQ): while the game waits on the
    // OPPONENT's react decision, show the same cursor "Waiting…" follower
    // as the fake no-response hold — if the two waits looked different,
    // the fake hold would be a tell. The avatar hourglass stays for
    // turn / pending-pick waits.
    var oppReactWait = waiting && gameState
        && gameState.phase === 1
        && gameState.react_player_idx === playerIdx
        && myPlayerIdx != null && playerIdx !== myPlayerIdx;
    if (myPlayerIdx != null && playerIdx !== myPlayerIdx
            && typeof _setReactWaitFollowerPersist === 'function') {
        _setReactWaitFollowerPersist(!!oppReactWait);
    }
    if (oppReactWait) waiting = false;  // no hourglass for this case
    if (waiting) {
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'pod-wait-badge';
            badge.textContent = '⌛';
            badge.title = 'Waiting for this player';
            wrap.appendChild(badge);
        }
    } else if (badge) {
        badge.remove();
    }
}

function _updatePassFlag(which, playerIdx) {
    var row = document.querySelector('#screen-game .pod-' + which + ' .pod-row-stats');
    if (!row) return;
    var flag = row.querySelector('.pod-pass-flag');
    // Event-driven (EVT_PASS_DECLARED sets _passOfferedBy at its beat; any
    // answering action clears it) — the raw state field is coalesced away
    // by the time frames land, so it can't be read off gameState.
    var offered = (typeof _passOfferedBy !== 'undefined')
        && _passOfferedBy === playerIdx;
    if (offered) {
        if (!flag) {
            flag = document.createElement('span');
            flag.className = 'pod-pass-flag';
            flag.textContent = '🫴';
            flag.title = 'Passed — handshake offered';
            row.appendChild(flag);
        }
    } else if (flag) {
        flag.remove();
    }
}

function renderOpponentInfo() {
    var oppIdx = 1 - myPlayerIdx;
    var oppPlayer = gameState.players[oppIdx];

    // Name
    var oppNameEl = document.getElementById('opp-name');
    if (oppNameEl) {
        oppNameEl.textContent = opponentName || 'PLAYER 2 (Opponent)';
    }

    // HP
    var oppHp = document.getElementById('opp-hp');
    if (oppHp) {
        oppHp.textContent = oppPlayer.hp;
    }
    // Pod HP power-bar (green→amber→red by HP%).
    paintPodHpBar('opp-hp-bar', oppPlayer.hp);

    // Mana (banking pool — single number, not X/Y)
    var oppMana = document.getElementById('opp-mana');
    if (oppMana) {
        oppMana.textContent = oppPlayer.current_mana;
    }

    // Hand count (god-mode spectator has the full hand array instead of a count)
    var oppHand = document.getElementById('opp-hand');
    if (oppHand) {
        var hc = (oppPlayer.hand_count != null)
            ? oppPlayer.hand_count
            : (oppPlayer.hand ? oppPlayer.hand.length : 0);
        oppHand.textContent = hc;
    }

    // Deck count
    var oppDeck = document.getElementById('opp-deck');
    if (oppDeck) {
        oppDeck.textContent = oppPlayer.deck_count;
    }

    _updatePassFlag('opp', oppIdx);
    _updateWaitBadge('opp', oppIdx);
}

// =============================================
// Section 13: renderSelfInfo() (UI-03)
// =============================================

function renderSelfInfo() {
    var myPlayer = gameState.players[myPlayerIdx];

    // Name
    var selfNameEl = document.getElementById('self-name');
    if (selfNameEl) {
        selfNameEl.textContent = myName || 'PLAYER 1 (You)';
    }

    // HP
    var selfHp = document.getElementById('self-hp');
    if (selfHp) {
        selfHp.textContent = myPlayer.hp;
    }
    // Pod HP power-bar (green→amber→red by HP%).
    paintPodHpBar('self-hp-bar', myPlayer.hp);

    // Mana (banking pool — single number, not X/Y)
    var selfMana = document.getElementById('self-mana');
    if (selfMana) {
        selfMana.textContent = myPlayer.current_mana;
    }

    // Hand count
    var selfHand = document.getElementById('self-hand');
    if (selfHand) {
        selfHand.textContent = myPlayer.hand.length;
    }

    // Deck count
    var selfDeck = document.getElementById('self-deck');
    if (selfDeck) {
        selfDeck.textContent = myPlayer.deck_count;
    }
    _updatePassFlag('self', myPlayerIdx);
    _updateWaitBadge('self', myPlayerIdx);
}

// =============================================
// Section 13b: Player avatars (2026-07)
// =============================================
// One avatar pod at EACH sacrifice end of the board — behind the opponent's
// home row (top) and behind your own home row (bottom). Shows a neutral
// placeholder disc (player initial), live HP (🤍 + number) and the player's
// Dark Matter pool (🌑 + number — PUBLIC info, both pools always visible;
// your own pool therefore stays persistently on-screen next to your
// avatar). Clicking either avatar opens the existing hover-preview panel
// (game-tooltip) with that player's details — both players can click both.

function _avatarDisplayName(playerIdx) {
    if (myPlayerIdx != null && playerIdx === myPlayerIdx) {
        return myName || 'You';
    }
    return opponentName || ('Player ' + (playerIdx + 1));
}

function renderPlayerAvatars() {
    if (!gameState || !gameState.players || myPlayerIdx == null) return;
    _renderAvatarPod('self', myPlayerIdx);
    _renderAvatarPod('opp', 1 - myPlayerIdx);
}

function _renderAvatarPod(which, playerIdx) {
    var p = gameState.players[playerIdx];
    var pod = document.getElementById('avatar-' + which);
    if (!p || !pod) return;
    var disc = document.getElementById('avatar-' + which + '-disc');
    if (disc) {
        // Discord PFP (user 2026-07-08): show the avatar image when we have
        // one for this seat (self = my login; opp = server-relayed), else the
        // initial letter.
        var avatarUrl = (typeof _podAvatarUrl === 'function')
            ? _podAvatarUrl(which, playerIdx, p) : null;
        if (avatarUrl) {
            if (disc.getAttribute('data-av') !== avatarUrl) {
                disc.setAttribute('data-av', avatarUrl);
                disc.innerHTML = '<img class="pod-ava-img" src="'
                    + avatarUrl.replace(/"/g, '&quot;') + '" alt="">';
            }
        } else {
            disc.removeAttribute('data-av');
            var nm = _avatarDisplayName(playerIdx);
            disc.textContent = nm ? nm.charAt(0).toUpperCase() : ('P' + (playerIdx + 1));
        }
    }
    var hpEl = document.getElementById('avatar-' + which + '-hp');
    if (hpEl) hpEl.textContent = p.hp;
    // (Dark Matter pod chip removed 2026-07-06 — no DM writes here.)
    if (!pod._gtAvatarBound) {
        pod._gtAvatarBound = true;
        var openPreview = function() {
            // Resolve the player idx at CLICK time — myPlayerIdx can change
            // across rematches / re-joins while the DOM node persists.
            if (myPlayerIdx == null) return;
            showPlayerPreview(which === 'self' ? myPlayerIdx : 1 - myPlayerIdx);
        };
        pod.addEventListener('click', openPreview);
        pod.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPreview(); }
        });
    }
}

// Populate the existing game preview panel (game-tooltip — the same host
// used for card/minion hover previews) with PLAYER details: name/side, HP,
// mana, Dark Matter pool, and player-level passives/statuses. All of this
// is public information, so either player may inspect either avatar.
function showPlayerPreview(playerIdx) {
    var state = sandboxMode ? sandboxState : gameState;
    if (!state || !state.players || !state.players[playerIdx]) return;
    var p = state.players[playerIdx];
    var tooltipId = sandboxMode ? 'sandbox-tooltip' : 'game-tooltip';
    var hintId = sandboxMode ? 'sandbox-tooltip-hint' : 'game-tooltip-hint';
    var host = document.getElementById(tooltipId);
    if (!host) return;
    host.style.display = '';

    var name = _avatarDisplayName(playerIdx);
    var initial = name ? name.charAt(0).toUpperCase() : ('P' + (playerIdx + 1));
    var dm = _playerDarkMatter(state, playerIdx);

    // Placeholder avatar art in the art slot (element-neutral disc).
    var artHost = host.querySelector('.tooltip-card-art');
    if (artHost) {
        artHost.innerHTML =
            '<div class="player-preview-disc">' + escapeHtml(initial) + '</div>';
    }

    var nameEl = host.querySelector('.tooltip-name');
    if (nameEl) nameEl.textContent = name + ' — Player ' + (playerIdx + 1);

    // Stat chips — same chip container the card preview uses.
    var statsEl = host.querySelector('.tooltip-stats');
    if (statsEl) {
        var chips = '';
        chips += '<span class="ts-hp">' + (p.hp | 0) + HEART + '</span>';
        chips += '<span class="ts-mana">' + (p.current_mana | 0) + ' Mana</span>';
        // Only surface Dark Matter once the player has stacks (user 2026-07-06).
        if (dm > 0) chips += '<span class="ts-dm">🌑 ' + dm + ' Dark Matter</span>';
        statsEl.innerHTML = chips;
    }

    // Body: player-level passives / statuses + zone counts.
    var bodyEl = host.querySelector('.tooltip-keywords');
    if (bodyEl) {
        var body = '';
        var handN = (p.hand_count != null)
            ? p.hand_count : (Array.isArray(p.hand) ? p.hand.length : 0);
        var deckN = (p.deck_count != null)
            ? p.deck_count : (Array.isArray(p.deck) ? p.deck.length : 0);
        body += '<div class="tooltip-text">Hand ' + handN + ' · Deck ' + deckN
            + ' · Grave ' + (p.grave ? p.grave.length : 0)
            + ' · Exhaust ' + (p.exhaust ? p.exhaust.length : 0) + '</div>';
        var panels = [];
        // Only surface Dark Matter once the player has stacks (user 2026-07-06).
        if (dm > 0) {
            panels.push('<div class="tooltip-keyword"><span class="tooltip-keyword-name">🌑 Dark Matter ×' + dm
                + '</span> <span class="tooltip-keyword-desc">— '
                + (KEYWORD_GLOSSARY['Dark Matter'] || 'A stacking player resource pool, visible to both players.')
                + '</span></div>');
        }
        if (p.discarded_last_turn) {
            panels.push('<div class="tooltip-keyword"><span class="tooltip-keyword-name">🗑️ Discarded last turn'
                + '</span> <span class="tooltip-keyword-desc">— enables cards with the "Discard last turn" play condition.</span></div>');
        }
        var fatigueN = 0;
        try {
            if (state.fatigue_counts && state.fatigue_counts[playerIdx] != null) {
                fatigueN = state.fatigue_counts[playerIdx] | 0;
            }
        } catch (e) { /* defensive */ }
        if (fatigueN > 0) {
            panels.push('<div class="tooltip-keyword"><span class="tooltip-keyword-name">💀 Fatigue ×' + fatigueN
                + '</span> <span class="tooltip-keyword-desc">— empty-deck turn-start draws deal escalating damage.</span></div>');
        }
        if (panels.length === 0) {
            panels.push('<div class="tooltip-text">No player passives active.</div>');
        }
        body += panels.join('');
        bodyEl.innerHTML = body;
    }

    var hint = document.getElementById(hintId);
    if (hint) hint.style.display = 'none';
    // Clear any minion status stack left over from a minion hover.
    _renderMinionStatusPanels(host, null);
}

// =============================================
// Section 14: renderBoard() (UI-01, D-03, D-10)
// =============================================

function renderBoard(opts) {
    // Phase 14.6: opts param is additive + backward-compatible.
    // Zero-arg calls (existing live-game sites) fall through to the original
    // globals-driven behavior. Sandbox passes { mount, state, perspectiveIdx,
    // legalActions } to route rendering to a different DOM target.
    opts = opts || {};
    var boardEl = opts.mount || document.getElementById('game-board');
    var state = opts.state || gameState;
    var perspectiveIdx = (opts.perspectiveIdx != null) ? opts.perspectiveIdx : myPlayerIdx;
    // legal is accepted for signature parity with renderHand; renderBoard
    // itself doesn't gate on legal actions (click handlers do).
    var legal = opts.legalActions || legalActions;  // eslint-disable-line no-unused-vars
    if (!boardEl) return;
    if (!state) return;
    boardEl.innerHTML = '';

    // Build minion lookup: "row,col" -> minion object (Pitfall 6)
    var minionMap = {};
    (state.minions || []).forEach(function(m) {
        minionMap[m.position[0] + ',' + m.position[1]] = m;
    });

    // Display order depends on perspective (D-03).
    // Engine truth: P1 back row = 0, P2 back row = 4. Each player should see
    // their own back row at the BOTTOM (standard TCG convention).
    // P1 (idx 0): render rows 4,3,2,1,0 top-to-bottom -> row 0 (P1 back) at bottom
    // P2 (idx 1): render rows 0,1,2,3,4 top-to-bottom -> row 4 (P2 back) at bottom
    var rowOrder = perspectiveIdx === 0
        ? [4, 3, 2, 1, 0]
        : [0, 1, 2, 3, 4];

    // Zone classification matches engine: P1 zone = rows 0,1; P2 zone = rows 3,4.
    var selfRows = perspectiveIdx === 0 ? [0, 1] : [3, 4];
    var oppRows = perspectiveIdx === 0 ? [3, 4] : [0, 1];

    rowOrder.forEach(function(row) {
        for (var col = 0; col < 5; col++) {
            var cell = document.createElement('div');
            cell.className = 'board-cell';
            cell.dataset.row = row;
            cell.dataset.col = col;

            // Zone tinting
            if (selfRows.indexOf(row) !== -1) {
                cell.classList.add('zone-self');
            } else if (row === 2) {
                cell.classList.add('zone-neutral');
            } else if (oppRows.indexOf(row) !== -1) {
                cell.classList.add('zone-opp');
            }

            // Phase 14.3: tag cell with the active animation class if its
            // tile key is in animatingTiles (set by the AnimationQueue).
            var animKind = animatingTiles[row + ',' + col];
            if (animKind) {
                cell.classList.add('anim-' + animKind);
                // Timing overhaul (2026-07-08, F10f): a re-render mid-
                // animation rebuilds the cell, which would RESTART the
                // keyframe from 0. Apply a negative animation-delay from
                // the stamped start time so the animation resumes where
                // it was instead of replaying.
                try {
                    if (typeof _animTileStart !== 'undefined'
                            && _animTileStart[row + ',' + col]) {
                        var _elapsed = Date.now() - _animTileStart[row + ',' + col];
                        if (_elapsed > 0) {
                            cell.style.animationDelay = (-_elapsed) + 'ms';
                        }
                    }
                } catch (e) { /* defensive — purely visual */ }
            }

            // Check for minion at this position
            var minion = minionMap[row + ',' + col];
            if (minion) {
                var isOwn = minion.owner === perspectiveIdx;
                cell.classList.add(isOwn ? 'cell-owner-self' : 'cell-owner-opp');
                // Perspective tilt (Approach A): the .board-standee wrapper
                // carries the upright counter-rotation via CSS so it stands
                // the minion up on the reclined board. The animation layer
                // still writes inline transforms onto the inner .board-minion
                // (summon scale-in, attack pullback, move slide, damage popup)
                // and the two compose — the wrapper is never clobbered.
                cell.innerHTML = '<div class="board-standee">' + renderBoardMinion(minion) + '</div>';
                // Hover tooltip for board minions
                (function(m) {
                    cell.addEventListener('mouseenter', function() { showGameTooltip(m.card_numeric_id, this, m); });
                    cell.addEventListener('mouseleave', function() { hideGameTooltip(); });
                    // click-to-pin (user 2026-07-06): stamp the id + minion ref
                    var mEl = cell.querySelector('.board-minion');
                    if (mEl) { mEl.dataset.numericId = m.card_numeric_id; mEl._minionRef = m; }
                })(minion);
            }

            // Click handler for board cell
            (function(r, c) {
                cell.addEventListener('click', function() { onBoardCellClick(r, c); });
            })(row, col);

            boardEl.appendChild(cell);
        }
    });
}

// =============================================
// renderBoardMinion() -- Compact card (D-10)
// =============================================

function renderBoardMinion(minion) {
    var cardDef = cardDefs[minion.card_numeric_id];
    if (!cardDef) return '';
    var isOwn = minion.owner === myPlayerIdx;
    var ownerClass = isOwn ? 'owner-self' : 'owner-opp';
    var typeClass = TYPE_CSS[cardDef.card_type] || '';
    var elem = (cardDef.element !== null && cardDef.element !== undefined)
        ? ELEMENT_MAP[cardDef.element] : NEUTRAL_ELEMENT;

    var atk = (cardDef.attack || 0) + (minion.attack_bonus || 0);
    var hp = minion.current_health;

    // Board art uses the FULL 1024px PNG (user 2026-07-07 'low res on the
    // grid'): the 4x-layer trick double-filters inside the 3D compositor
    // and thumbs blur under the desktop scale. The board holds at most 25
    // minions, so full-res textures are affordable here (the thumb
    // rationale was the 50-card hand/browse surfaces).
    var boardArtStyle = cardDef.card_id
        ? 'background-image:url(' + _cardArtUrl(cardDef.card_id, true) + ');background-size:cover;background-position:center;'
        : '';

    // Buff/debuff rework (user 2026-07-10): the big ⬆️/⬇️ badges are GONE —
    // the stat number itself already shows the modified value; a stroke
    // animation carries the state instead: golden pulse when net-BETTER
    // than the printed stat, slow grey drain when net-WORSE. A stat that
    // is both buffed and debuffed animates by its NET sign. Burning keeps
    // its badge (a status, not a stat change).
    var badges = [];
    if (minion.is_burning) {
        badges.push('<span class="minion-badge badge-burning" title="Burning">🔥</span>');
    }
    var badgesHtml = badges.length
        ? '<div class="minion-badges">' + badges.join('') + '</div>'
        : '';
    var atkNet = minion.attack_bonus | 0;
    var hpNet = minion.max_health_bonus | 0;
    var atkTone = atkNet > 0 ? ' stat-buffed' : (atkNet < 0 ? ' stat-debuffed' : '');
    var hpTone = hpNet > 0 ? ' stat-buffed' : (hpNet < 0 ? ' stat-debuffed' : '');

    return '<div class="board-minion ' + ownerClass + ' ' + typeClass + '" data-numeric-id="' + minion.card_numeric_id + '" style="' + boardArtStyle + '">'
        + '<div class="board-minion-overlay"></div>'
        /* element pill removed from board minions (user 2026-07-04) — the
           element reads from the card art/frame + tooltip; the label was
           noise at cell size */
        + '<div class="board-minion-name">' + cardDef.name + '</div>'
        + '<div class="board-minion-stats">'
        + '<span class="board-minion-atk' + atkTone + '"><span class="stat-emoji-bg">' + SWORD_SVG + '</span><span class="stat-num">' + atk + '</span></span>'
        + '<span class="board-minion-hp' + hpTone + '"><span class="stat-emoji-bg">' + HEART_SVG + '</span><span class="stat-num">' + hp + '</span></span>'
        + '</div>'
        + badgesHtml
        + '</div>';
}

// =============================================
// Section 15: renderHand() (UI-02, D-05)
// =============================================

function renderHand(opts) {
    // Phase 14.6: opts param is additive + backward-compatible.
    // Zero-arg calls (existing live-game sites) fall through to the original
    // globals-driven behavior. Sandbox passes { mount, state, ownerIdx,
    // godView, legalActions } to mount ONE player's hand into a sandbox
    // DOM target without walking the god-view spectator branch.
    //
    // When opts.godView is true (sandbox), we render ONLY the ownerIdx
    // player's hand face-up into the provided mount -- this is called
    // twice by renderSandbox(), once for P0 into #sandbox-hand-p0, once
    // for P1 into #sandbox-hand-p1. The spectator god-view branch below
    // is unchanged; it still fires for the live-game spectator path.
    opts = opts || {};
    var handEl = opts.mount || document.getElementById('hand-container');
    var state = opts.state || gameState;
    var ownerIdx = (opts.ownerIdx != null) ? opts.ownerIdx : myPlayerIdx;
    var legal = opts.legalActions || legalActions;
    if (!handEl) return;
    if (!state) return;
    // FLIP capture (user 2026-07-11): remember where each card sat before
    // the rebuild so _flipSlideHandRow can glide survivors to their new
    // spots instead of teleporting — without this, back-to-back draws look
    // like the same fly-in twice with no visible "making room" in between.
    // Keyed nid:occurrence so duplicate cards map stably left-to-right.
    var _flipOld = null;
    if (!opts.godView && !(isSpectator && spectatorGodMode)) {
        _flipOld = {};
        var _seen = {};
        var _prevCards = handEl.querySelectorAll('.card-frame-hand');
        for (var _pi = 0; _pi < _prevCards.length; _pi++) {
            var _nid = _prevCards[_pi].getAttribute('data-numeric-id');
            var _occ = (_seen[_nid] = (_seen[_nid] | 0) + 1);
            if (_prevCards[_pi].style.visibility !== 'hidden') {
                _flipOld[_nid + ':' + _occ] = _prevCards[_pi].getBoundingClientRect().left;
            }
        }
    }
    handEl.innerHTML = '';

    var myPlayer = state.players[ownerIdx];
    // Timing audit (2026-07-06): live-game affordance dims track canActNow
    // (queue idle + my decision), not raw legalActions — which mid-drain
    // already hold the batch's final frame.
    var isMyTurn = legal && legal.length > 0;
    if (!sandboxMode && typeof canActNow === 'function' && !canActNow()) {
        isMyTurn = false;
    }

    function appendHand(playerObj, label) {
        if (!playerObj || !playerObj.hand) return;
        if (label) {
            var lbl = document.createElement('div');
            lbl.className = 'spectator-hand-label';
            lbl.textContent = label;
            handEl.appendChild(lbl);
        }
        var totalCards = playerObj.hand.length;
        playerObj.hand.forEach(function(numericId, handIndex) {
            var mana = playerObj.current_mana;
            var cardHtml = renderHandCard(numericId, handIndex, mana, isMyTurn && !isSpectator);
            var wrapper = document.createElement('div');
            wrapper.innerHTML = cardHtml;
            if (wrapper.firstChild) {
                var cardEl = wrapper.firstChild;
                // Fan positioning via CSS custom properties
                cardEl.style.setProperty('--i', handIndex);
                cardEl.style.setProperty('--n', totalCards);
                cardEl.addEventListener('mouseenter', function() { showGameTooltip(numericId, this); });
                cardEl.addEventListener('mouseleave', function() {
                    // Only hide tooltip if this card is not pinned
                    if (!cardEl.classList.contains('card-preview-pinned')) {
                        hideGameTooltip();
                    }
                });
                (function(idx, nid, owner) {
                    cardEl.addEventListener('click', function() {
                        // Pin preview in the tooltip sidebar
                        pinHandCardPreview(nid, this);
                        onHandCardClick(idx, owner);
                    });
                })(handIndex, numericId, ownerIdx);
                // Phase 14.6-03: additive "Move to..." affordance in sandbox
                // mode. The existing play-from-hand click handler above is
                // unchanged; this button is a sibling affordance.
                if (sandboxMode && typeof makeSandboxMoveButton === 'function') {
                    cardEl.appendChild(makeSandboxMoveButton(ownerIdx, numericId, 'hand'));
                }
                handEl.appendChild(cardEl);
            }
        });
    }

    // Phase 14.4: god-mode spectators see BOTH hands; non-god spectators
    // see only the perspective player (server sends the opponent as count).
    // Phase 14.6: opts.godView (sandbox) renders ONLY the ownerIdx hand
    // face-up -- the sandbox calls renderHand twice with distinct mounts,
    // once per player, so each mount shows exactly one hand.
    if (opts && opts.godView) {
        appendHand(myPlayer, null);
    } else if (isSpectator && spectatorGodMode) {
        var oppIdx = 1 - ownerIdx;
        appendHand(state.players[oppIdx], 'Player ' + (oppIdx + 1) + ' hand');
        appendHand(myPlayer, 'Player ' + (ownerIdx + 1) + ' hand');
    } else {
        appendHand(myPlayer, null);
    }
    // Auto-fit names and effects for hand cards
    fitHandCardNames();
    fitHandCardEffects();

    // Width-aware overlap (approved 2026-07 duel layout). Replaces the legacy
    // count-based CSS fan (--i/--n margin calc) with a measured row: comfortable
    // gap when the cards fit, overlap only when they don't. The two-hand
    // spectator god-view keeps the legacy per-hand CSS fan (mixed hands + labels
    // in one flex row can't share a single measured spacing). Sandbox mounts
    // (opts.godView) are explicitly out of scope for the 2026-07 duel layout —
    // they keep the legacy --i/--n fan, and relayoutHandRows() never revisits
    // their mounts, so measured inline margins must NOT be stamped there.
    if (!(isSpectator && spectatorGodMode) && !(opts && opts.godView)) {
        _layoutHandRow(
            Array.prototype.slice.call(handEl.querySelectorAll('.card-frame-hand')),
            HAND_MAXW
        );
        if (_flipOld) _flipSlideHandRow(handEl, _flipOld);
    }

    // Timing overhaul (2026-07-08, F9c): re-hide slots whose draw fly-in is
    // still mid-flight. This rebuild just detached the nodes that
    // playDrawOwnAnimation hid — without re-applying visibility:hidden the
    // user sees the card in hand AND its flying duplicate. The registry is
    // keyed 'nid:<numeric-id>' (fallback 'idx:<hand-idx>') with a count of
    // concurrent flights per key.
    try {
        var _reg = window.__inFlightHandSlots;
        if (_reg) {
            for (var _k in _reg) {
                if (!Object.prototype.hasOwnProperty.call(_reg, _k)) continue;
                var _want = _reg[_k] | 0;
                if (_want <= 0) continue;
                var _sel = _k.indexOf('nid:') === 0
                    ? '.card-frame-hand[data-numeric-id="' + _k.slice(4) + '"]'
                    : '.card-frame-hand[data-hand-idx="' + _k.slice(4) + '"]';
                var _cand = handEl.querySelectorAll(_sel);
                var _hidden = 0;
                // Hide from the END of the fan (newest slots) first — the
                // in-flight cards are the most recently appended.
                for (var _ci = _cand.length - 1; _ci >= 0 && _hidden < _want; _ci--) {
                    if (_cand[_ci].style.visibility !== 'hidden') {
                        _cand[_ci].style.visibility = 'hidden';
                    }
                    _hidden++;
                }
            }
        }
    } catch (e) { /* defensive — worst case a brief duplicate */ }
}

// ==========================================================================
// Width-aware hand-row layout (approved 2026-07 duel layout).
// Given the card elements of a single row, sets an inline margin-left (which
// wins over the stylesheet's --i/--n calc): a comfortable HAND_ROW_GAP when the
// cards fit inside min(container, maxW), otherwise an even negative margin that
// slides them left, capped at HAND_OVERLAP_CAP (45%) of a card width. The
// maxW cap keeps the row from ever spanning the whole screen / running under
// the PASS button. Used for BOTH the player hand (#hand-container) and the
// opponent face-down row (#oppHandRow). Re-run on resize via relayoutHandRows.
// ==========================================================================
// 7 cards of the CURRENT 58.5px hand cards + 6 gaps — beyond this the row
// overlaps (up to the 45% cap). The old 615px value dated from 96px cards
// and had drifted to "overlap at 10" when the cards shrank (user 2026-07-06).
var HAND_MAXW = 7 * 58.5 + 6 * 4;   // ≈ 434
var HAND_ROW_GAP = 4;         // reduced padding (user design): tight but no overlap up to 7
var HAND_OVERLAP_CAP = 0.45;  // max fraction of a card width they may overlap

// FLIP slide (user 2026-07-11): after a rebuild, glide each surviving card
// from its captured pre-rebuild position to its new slot, so a draw visibly
// pushes the hand aside instead of teleporting it. Slides via relative
// `left` — the cf2 hand card's transform is pinned by a scale(0.25)
// !important rule (min-font-floor fix), and a relative offset also leaves
// siblings' LAYOUT rects untouched, so the in-flight draw fly-in still
// targets the true final slot position. Deltas are screen px; the stage is
// scaled by --duel-scale, so divide before applying.
function _flipSlideHandRow(handEl, oldLefts) {
    var cards = handEl.querySelectorAll('.card-frame-hand');
    if (!cards.length) return;
    var scale = 1;
    try {
        var screenEl = handEl.closest('#screen-game, #screen-sandbox');
        if (screenEl) {
            var sv = parseFloat(getComputedStyle(screenEl).getPropertyValue('--duel-scale'));
            if (sv > 0) scale = sv;
        }
    } catch (e) { /* defensive */ }
    var seen = {};
    for (var i = 0; i < cards.length; i++) {
        var el = cards[i];
        var nid = el.getAttribute('data-numeric-id');
        var occ = (seen[nid] = (seen[nid] | 0) + 1);
        var oldLeft = oldLefts[nid + ':' + occ];
        if (oldLeft == null) continue;                     // new card — the fly-in owns it
        if (el.style.visibility === 'hidden') continue;    // in-flight slot
        var dx = (oldLeft - el.getBoundingClientRect().left) / scale;
        if (Math.abs(dx) < 2) continue;
        el.style.transition = 'none';
        el.style.left = dx + 'px';
        void el.offsetWidth;                               // commit start frame
        el.style.transition = 'left 200ms ease';
        el.style.left = '0px';
        (function(node) {
            var release = function() {
                node.style.transition = '';
                node.style.left = '';
                node.removeEventListener('transitionend', release);
            };
            node.addEventListener('transitionend', release);
            setTimeout(release, 350);                      // safety cap
        })(el);
    }
}

function _layoutHandRow(cards, maxW) {
    var n = cards.length;
    if (!n) return;
    var parent = cards[0].parentElement;
    if (!parent) return;
    // Footprint width, not layout width: hand cf2 cards render their DOM at
    // 4x and scale(0.25) back down (min-font-size fix), collapsing the extra
    // via a negative margin-right — offsetWidth alone would read the 4x box.
    var cs0 = getComputedStyle(cards[0]);
    var cardW = (cards[0].offsetWidth || cards[0].getBoundingClientRect().width || 0)
        + (parseFloat(cs0.marginRight) || 0);
    var avail = Math.min(parent.clientWidth || Infinity, maxW || Infinity);
    var spacing;
    if (n <= 1 || !cardW) {
        spacing = HAND_ROW_GAP;
    } else if (n * cardW + (n - 1) * HAND_ROW_GAP <= avail) {
        spacing = HAND_ROW_GAP;                                       // they fit
    } else {
        spacing = -Math.min((n * cardW - avail) / (n - 1), cardW * HAND_OVERLAP_CAP);
    }
    for (var i = 0; i < n; i++) {
        cards[i].style.marginLeft = (i === 0 ? 0 : spacing) + 'px';
        cards[i].style.marginRight = '0px';
    }
}

// Re-apply width-aware overlap to the already-rendered rows (no rebuild) so the
// hand + opponent peek re-fit when the viewport changes size / orientation.
function relayoutHandRows() {
    if (isSpectator && spectatorGodMode) return;   // legacy fan owns this case
    var hc = document.getElementById('hand-container');
    if (hc) {
        _layoutHandRow(
            Array.prototype.slice.call(hc.querySelectorAll('.card-frame-hand')),
            HAND_MAXW
        );
    }
    var oh = document.getElementById('oppHandRow');
    if (oh) {
        _layoutHandRow(
            Array.prototype.slice.call(oh.querySelectorAll('.opp-hand-card-back')),
            HAND_MAXW * 0.9
        );
    }
}
window.addEventListener('resize', relayoutHandRows);

// Paint a pod HP power-bar from a live HP value (approved 2026-07 duel layout).
// Mirrors the self-contained observer in game.html, but called directly from
// renderSelfInfo/renderOppInfo so the bar tracks the number on every state
// update independent of MutationObserver timing. hue = pct*1.2 → green (full)
// through amber to red (near death). Heals above the starting pool cap at 100%.
var POD_MAX_HP = 20;
function paintPodHpBar(barId, hp) {
    var bar = document.getElementById(barId);
    if (!bar) return;
    var h = parseInt(hp, 10);
    if (isNaN(h)) h = 0;
    var pct = Math.max(0, Math.min(100, (h / POD_MAX_HP) * 100));
    var hue = pct * 1.2;
    bar.style.width = pct + '%';
    bar.style.background = 'linear-gradient(180deg, hsl(' + hue + ',80%,58%), hsl(' + hue + ',75%,44%))';
    bar.style.boxShadow = '0 0 8px -1px hsl(' + hue + ',80%,50%)';
}

// =============================================
// renderHandCard() -- thin wrapper over renderCardFrame (Wave 14.5-04)
// Single source of truth lives in renderCardFrame(). Hand context stamps
// data-hand-idx / data-numeric-id and dims on can't-afford OR not-my-turn.
// =============================================
function renderHandCard(numericId, handIndex, currentMana, isMyTurn) {
    var c = cardDefs[numericId];
    if (!c) return '';
    var canAfford = currentMana >= c.mana_cost;
    return renderCardFrame(c, {
        context: 'hand',
        handIndex: handIndex,
        numericId: numericId,
        dim: !(canAfford && isMyTurn),
        showReactDeploy: false,
    });
}

// =============================================
// Section 16: renderDeckBuilderCard (already defined above in Section 7)
// Section 17: Helper -- getEffectDescription()
// =============================================

// Dark Matter pool redesign (2026-07): DM is a PLAYER-level pool
// (players[i].dark_matter), not per-minion stacks. Returns the viewing
// player's pool, or null when not in an active game (deck builder, card
// DB) so the placeholder "(Dark Matter)" stays literal in those contexts.
// Legacy fallback: pre-redesign states lack the player field — sum the
// (deprecated, now always-0) per-minion stacks so old replays still read.
function _viewerDarkMatterSum() {
    if (!gameState || myPlayerIdx == null) return null;
    var p = gameState.players && gameState.players[myPlayerIdx];
    if (p && p.dark_matter != null) return p.dark_matter | 0;
    if (!gameState.minions) return null;
    var sum = 0;
    for (var i = 0; i < gameState.minions.length; i++) {
        var m = gameState.minions[i];
        if (m && m.owner === myPlayerIdx && (m.current_health == null || m.current_health > 0)) {
            sum += (m.dark_matter_stacks || 0);
        }
    }
    return sum;
}

// Read any player's Dark Matter pool from a state dict (public info).
function _playerDarkMatter(state, playerIdx) {
    var p = state && state.players && state.players[playerIdx];
    if (!p) return 0;
    return (p.dark_matter != null) ? (p.dark_matter | 0) : 0;
}

// In card rules text, live games substitute "(Dark Matter)" with the
// viewer's current DM pool in purple, followed by the "(Dark Matter)"
// label so the number is unambiguous. Non-live contexts keep the literal.
function _dmTokenLive() {
    var dm = _viewerDarkMatterSum();
    if (dm == null) return '(Dark Matter)';
    return '<span class="dm-live-num">' + dm + '</span> (Dark Matter)';
}

// Two Dark-Matter scale spellings are live in card JSONs: 'dark_matter'
// (scales with a minion's OWN stacks — e.g. Dark Matter Battery) and
// 'player_dark_matter' (scales with the owner's pooled total across the
// board — e.g. Gargoyle Sorceress). Card-text rendering treats both as
// DM-scaled; the live substitution (_dmTokenLive) already sums the
// viewer's whole board, which IS the player pool.
function _isDmScale(s) {
    return s === 'dark_matter' || s === 'player_dark_matter';
}

function getEffectDescription(effects, cardData, opts) {
    if (!effects || effects.length === 0) return '';
    // opts.noTrigger: drop the leading trigger label (e.g. "Summon: "). Used
    // when the effect is rendered inside a React box — the react header already
    // states the trigger, so a react_effect that happens to carry trigger
    // on_summon must NOT read "Summon: ..." (user 2026-07-09, Tree Wyrm).
    var noTrigger = !!(opts && opts.noTrigger);
    var isMinion = cardData && cardData.card_type === 0;
    var DM = _dmTokenLive();
    // 8 (ON_SUMMON) added 2026-07-10 — it was missing, so on-summon effects
    // (Dark Mage "Summon: Dark Matter +1", Eclipse Shade's burn, diodebot
    // tutors) rendered with no prefix at all.
    var triggerMap = {0: isMinion ? 'Summon' : '', 1: 'Death', 2: 'Attack', 3: 'Damaged', 4: 'Move', 5: 'End', 6: 'Discarded', 8: isMinion ? 'Summon' : '', 9: 'Rally', 10: 'Decay', 11: 'Sacrifice'};
    // Coalesce sibling burn-all-minions effects that only differ in
    // target_tribe/target_element into a single rendered clause — so
    // Acidic Rain reads "Burn all Robots, Machines and Metal minions"
    // instead of three separate lines.
    effects = (function(effs) {
        var bucket = null;
        var out = [];
        effs.forEach(function(e) {
            var isBurnAll = e.type === 10 && e.target === 6;
            if (isBurnAll) {
                if (!bucket || bucket.trigger !== e.trigger) {
                    bucket = { type: 10, target: 6, trigger: e.trigger, amount: e.amount || 0, _tribes: [], _elements: [] };
                    out.push(bucket);
                }
                if (e.target_tribe && bucket._tribes.indexOf(e.target_tribe) < 0) bucket._tribes.push(e.target_tribe);
                if (e.target_element && bucket._elements.indexOf(e.target_element) < 0) bucket._elements.push(e.target_element);
            } else {
                bucket = null;
                out.push(e);
            }
        });
        return out;
    })(effects);
    var parts = [];
    effects.forEach(function(eff) {
        var trigger = triggerMap[eff.trigger];
        if (trigger === undefined) trigger = '';
        var prefix = (noTrigger || !trigger) ? '' : trigger + ': ';
        var amount = eff.amount || 0;
        var type = eff.type;
        var desc = '';

        if (type === 0) { // Damage
            if (_isDmScale(eff.scale_with)) {
                desc = prefix + 'Deal ' + DM + ' damage';
                if (amount > 0) desc = prefix + 'Deal ' + amount + ' + ' + DM + ' damage';
            } else if (eff.scale_with === 'destroyed_attack_plus_dm' || eff.scale_with === 'sacrificed_attack_plus_dm') {
                desc = prefix + "Deal destroyed ally's " + SWORD + ' + ' + DM + ' as damage';
            } else if (eff.scale_with === 'destroyed_attack' || eff.scale_with === 'sacrificed_attack') {
                desc = prefix + "Deal destroyed ally's " + SWORD + ' as damage';
            } else {
                desc = prefix + 'Deal ' + amount + ' damage';
            }
            if (eff.target === 1) desc += ' to all enemies';
            else if (eff.target === 0) desc += ' to target';
            else if (eff.target === 4) desc += ' to face';
        } else if (type === 1) { // Heal
            desc = prefix + 'Heal ' + amount;
        } else if (type === 2) { // Buff ATK
            if (_isDmScale(eff.scale_with)) {
                // Check if next effect is BUFF_HP with same scale — merge icons
                var hasMatchingHp = effects.some(function(e2) {
                    return e2.type === 3 && _isDmScale(e2.scale_with) && e2.target === eff.target;
                });
                var tribeName = eff.target_tribe === 'Mage' ? 'Dark Mages' : (eff.target_tribe ? eff.target_tribe + 's' : 'allies');
                var selfTarget = (eff.target === 3); // SELF_OWNER
                desc = prefix + (selfTarget ? 'Gain' : 'Ally ' + tribeName + ' gain') + ' ' + DM + SWORD + (hasMatchingHp ? HEART : '');
                if (eff.placement_condition === 'front_of_dark_ranged' && eff.condition_multiplier > 1) {
                    // Em-dash, not '. ' — the card frame splits effect text on
                    // '. ' into bullet lines, and this clause is not a sentence.
                    desc += ' — ×' + eff.condition_multiplier + ' if in front of Dark Ranged ally';
                }
            } else {
                desc = prefix + '+' + amount + SWORD;
            }
        } else if (type === 3) { // Buff HP
            if (_isDmScale(eff.scale_with)) {
                // Skip if already merged with BUFF_ATK above
                var alreadyMerged = effects.some(function(e2) {
                    return e2.type === 2 && _isDmScale(e2.scale_with) && e2.target === eff.target;
                });
                if (alreadyMerged) { desc = ''; return; }
                var tribeNameHp = eff.target_tribe === 'Mage' ? 'Dark Mages' : (eff.target_tribe ? eff.target_tribe + 's' : 'allies');
                desc = prefix + 'Ally ' + tribeNameHp + ' gain ' + DM + HEART;
            } else {
                desc = prefix + '+' + amount + HEART;
            }
        } else if (type === 4) { // Negate
            desc = prefix + 'Negate';
        } else if (type === 5) { // Deploy Self
            desc = prefix + 'Summon';
        } else if (type === 6) { // March Forward
            var marchName = (cardData && cardData.name) || 'this unit';
            desc = 'Move: March friendly ' + marchName;
        } else if (type === 7) { // Promote
            if (cardData && cardData.promote_target) {
                // Only the promote_target card promotes (e.g. Common Rat),
                // NOT any minion of the tribe — name the actual card.
                var promoFrom = findCardNameById(cardData.promote_target);
                desc = prefix + 'Promote a ' + (promoFrom || cardData.promote_target) + ' to ' + (cardData.name || '?');
            } else {
                desc = prefix + 'Promote';
            }
        } else if (type === 8) { // Tutor
            // Soft-cap tutors (eff.up_to, e.g. Tree Wyrm) read "up to N"; a
            // committed tutor (Ratmobile) reads the flat count (user 2026-07-09).
            var tutorCount = amount > 1 ? ((eff.up_to ? 'up to ' : '') + amount + ' ') : '';
            if (cardData && cardData.tutor_target) {
                var tt = cardData.tutor_target;
                if (typeof tt === 'string') {
                    // A self-tutor (Tree Wyrm tutors Tree Wyrm) reads as its
                    // pluralised tribe — "2 Wyrms" — not the full card name.
                    var tutorName;
                    if (tt === cardData.card_id && cardData.tribe) {
                        tutorName = cardData.tribe + (amount > 1 ? 's' : '');
                    } else {
                        tutorName = findCardNameById(tt);
                    }
                    desc = prefix + 'Tutor ' + tutorCount + tutorName;
                } else if (typeof tt === 'object') {
                    // Selector dict: {tribe: "Rat"} etc.
                    var selParts = [];
                    if (tt.tribe) selParts.push(tt.tribe + (amount > 1 ? 's' : ''));
                    if (tt.element) selParts.push(tt.element);
                    if (tt.card_type) selParts.push(tt.card_type);
                    desc = prefix + 'Tutor ' + tutorCount + (selParts.join(' ') || 'card');
                } else {
                    desc = prefix + 'Tutor ' + tutorCount + tt;
                }
            } else {
                desc = prefix + 'Tutor';
            }
        } else if (type === 9) { // Destroy
            desc = prefix + 'Destroy target';
        } else if (type === 10) { // Burn
            var burnTarget;
            if (eff.target === 6) {
                // Either a coalesced bucket (see top of this fn) with
                // _tribes/_elements arrays, or a single-effect fallback.
                var tribes = eff._tribes || (eff.target_tribe ? [eff.target_tribe] : []);
                var elements = eff._elements || (eff.target_element ? [eff.target_element] : []);
                var cap = function(s) { return s.charAt(0).toUpperCase() + s.slice(1); };
                var tribeParts = tribes.map(function(t) { return t + 's'; });
                var elemParts = elements.map(function(el) { return cap(el); });
                var joined = tribeParts.concat(elemParts);
                if (joined.length === 0) burnTarget = ' all minions';
                else if (joined.length === 1) burnTarget = ' all ' + joined[0];
                else burnTarget = ' all ' + joined.slice(0, -1).join(', ') + ' and ' + joined.slice(-1)[0];
                if (elements.length > 0) burnTarget += ' minions';
            } else {
                burnTarget = {0: ' target', 1: ' all enemies', 2: ' adjacent enemies', 3: ' self'}[eff.target] || '';
            }
            desc = prefix + 'Burn' + burnTarget;
        } else if (type === 11) { // Dark Matter Buff
            desc = prefix + 'Target gains (Dark Matter)' + SWORD;
        } else if (type === 12) { // Rally Heal
            desc = 'Rally: Heal ' + amount;
        } else if (type === 13) { // Leap
            desc = 'Move: Leap';
        } else if (type === 14) { // Conjure
            var conjureName = (cardData && cardData.summon_token_target) ? findCardNameById(cardData.summon_token_target) : 'a card';
            var conjureCost = (cardData && cardData.summon_token_cost) ? ' (' + cardData.summon_token_cost + ')' : '';
            desc = 'Active' + conjureCost + ': Summon ' + conjureName + ' from deck';
            if (cardData && cardData.conjure_buff === 'dark_matter') {
                desc += '. Buff all ' + conjureName + ' by Dark Matter';
            }
        } else if (type === 20) { // Cleanse (Water Wyrm 2026-07-11)
            desc = prefix + 'Cleanse (removes all debuffs)';
        } else if (type === 15) { // Apply Burning
            var burnAmt = amount || 1;
            desc = prefix + 'Apply ' + burnAmt + ' Burning';
        } else if (type === 16) { // Grant Dark Matter
            // DM pool redesign 2026-07: canonical shape is target 7
            // (owner_player) + scale_with 'dark_mages' (+N per friendly
            // Dark Mage). Legacy all_allies (target 5) JSONs render the
            // same wording. Mirrors wiki/sync/sync_cards.py.
            desc = prefix + 'Dark Matter +' + amount;
            if (eff.scale_with === 'dark_mages' || eff.target === 5) {
                var dmTribe = (eff.target_tribe && eff.target_tribe !== 'Mage') ? eff.target_tribe : 'Dark Mage';
                desc += ' per ally ' + dmTribe;
            }
        } else if (type === 17) { // Revive
            var reviveName = (cardData && cardData.revive_card_id)
                ? findCardNameById(cardData.revive_card_id)
                : (eff.target_tribe ? 'a ' + eff.target_tribe : 'minion');
            if (amount > 1 && cardData && cardData.revive_card_id) {
                reviveName = amount + ' ' + reviveName + 's';
            }
            desc = prefix + 'Revive ' + reviveName + ' from Grave';
            if (cardData && cardData.revive_exclude_card_id) {
                desc += ' (except ' + (findCardNameById(cardData.revive_exclude_card_id) || cardData.revive_exclude_card_id) + ')';
            }
        } else if (type === 18) { // Draw
            var cardText = amount > 1 ? amount + ' cards' : '1 card';
            desc = prefix + 'Draw ' + cardText;
        } else if (type === 19) { // Burn Bonus (passive aura)
            desc = 'Passive: Burn +' + amount;
        } else {
            console.warn('[getEffectDescription] Unhandled effect type ' + type + ' on card "' + (cardData && cardData.card_id) + '". Add a case for EffectType ' + type + ' in getEffectDescription().');
            desc = prefix + 'Effect';
        }
        if (desc) parts.push(desc);
    });
    return parts.join('. ');
}

function findCardNameById(cardId) {
    var defs = allCardDefs || cardDefs;
    for (var nid in defs) {
        if (defs[nid].card_id === cardId) return defs[nid].name;
    }
    return cardId; // fallback to raw id
}

