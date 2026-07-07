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
    title.textContent = 'Choose a card to tutor';
    var deckLine = document.createElement('div');
    deckLine.className = 'tutor-modal-deckline';
    deckLine.textContent = 'Deck: ' + deckSize + ' cards remaining';
    header.appendChild(title);
    header.appendChild(deckLine);
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
                // ActionType.TUTOR_SELECT = 9 (Phase 14.2). card_index reused as match index.
                submitAction({ action_type: 9, card_index: match.match_idx });
            });
            fan.appendChild(tile);
        });
    }
    modal.appendChild(fan);

    // Mandatory tutoring (2026-07): while matching picks remain, declining
    // is ILLEGAL for TUTORS — the Skip button only renders at zero matches
    // (defensive escape hatch; the engine auto-resolves zero-match tutors
    // so that footer should never appear in normal play). Conjure deck-
    // picks (pending_tutor_is_conjure — Ratchanter) keep their decline:
    // DECLINE_TUTOR leaves the card in the deck, so always offer Skip.
    if (!matches || matches.length === 0 || isConjurePick) {
        var footer = document.createElement('div');
        footer.className = 'tutor-modal-footer';
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
        modal.appendChild(footer);
    }

    overlay.appendChild(modal);
    // Block background clicks (no accidental dismiss — must Skip explicitly).
    overlay.addEventListener('click', function(e) { e.stopPropagation(); });
    _stageMount().appendChild(overlay);
}

function closeTutorModal() {
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
                // ActionType.TRIGGER_PICK = 17 (Phase 14.7-05).
                // card_index reused as queue_idx.
                submitAction({ action_type: 17, card_index: queueIdx });
            });
            fan.appendChild(tile);
        });
    }
    modal.appendChild(fan);

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
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
        if (reviveModalOpen) closeReviveModal();
        if (interactionMode === 'revive_place') interactionMode = null;
        return;
    }
    // Sandbox is god-mode — always show the modal regardless of myPlayerIdx.
    var isPicker = sandboxMode || pendingIdx === myPlayerIdx;
    if (isPicker) {
        // Re-assert revive_place mode so highlightBoard draws cell-valid on
        // REVIVE_PLACE legal tiles. A prior clearSelection() may have wiped
        // interactionMode even while reviveModalOpen stayed true.
        interactionMode = 'revive_place';
        if (!reviveModalOpen) {
            showReviveModal();
        }
    } else {
        if (reviveModalOpen) closeReviveModal();
    }
}

function showReviveModal() {
    closeReviveModal();
    // closeReviveModal clears interactionMode — re-assert picker mode so the
    // subsequent highlightBoard sees revive_place and draws cell-valid.
    reviveModalOpen = true;
    interactionMode = 'revive_place';

    var remaining = gameState.pending_revive_remaining || 0;
    var cardNid = gameState.pending_revive_card_numeric_id;
    var cardDef = cardNid != null && window.cardDefs ? window.cardDefs[cardNid] : null;
    var cardName = cardDef ? cardDef.name : 'minion';

    // Revive modal is NON-blocking: the board must remain clickable so the
    // player can pick a target cell. Overlay uses pointer-events:none; only
    // the inner banner receives clicks (for the Skip button).
    var overlay = document.createElement('div');
    overlay.className = 'tutor-modal-overlay revive-modal-overlay-nonblock';
    overlay.id = 'revive-modal-overlay';
    overlay.style.cssText = 'position:fixed;top:70px;left:0;right:0;bottom:auto;background:transparent;backdrop-filter:none;pointer-events:none;display:flex;justify-content:center;z-index:10;';

    var modal = document.createElement('div');
    modal.className = 'tutor-modal';
    modal.style.cssText = 'pointer-events:auto;max-width:480px;background:rgba(20,25,45,0.95);border:2px solid #1b5a7a;border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,.6);';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = 'Revive: Click a tile to place ' + cardName + ' (' + remaining + ' remaining)';
    header.appendChild(title);
    modal.appendChild(header);

    var body = document.createElement('div');
    body.style.cssText = 'padding:16px;text-align:center;color:var(--muted);font-size:14px;';
    body.textContent = 'Click a highlighted cell on the board to place the revived minion.';
    modal.appendChild(body);

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var skipBtn = document.createElement('button');
    skipBtn.className = 'btn btn-secondary';
    skipBtn.textContent = 'Done (skip remaining)';
    skipBtn.onclick = function() {
        submitAction({ action_type: 16 }); // DECLINE_REVIVE
    };
    footer.appendChild(skipBtn);
    modal.appendChild(footer);

    overlay.appendChild(modal);
    _stageMount().appendChild(overlay);

    // Highlight valid board cells
    highlightReviveCells();
}

function highlightReviveCells() {
    // Use legalActions to find valid REVIVE_PLACE positions
    if (!window.legalActions) return;
    var cells = document.querySelectorAll('.board-cell');
    cells.forEach(function(cell) {
        cell.classList.remove('cell-valid');
    });
    for (var i = 0; i < legalActions.length; i++) {
        var a = legalActions[i];
        if (a.action_type === 15 && a.position) { // REVIVE_PLACE
            var r = a.position[0], c = a.position[1];
            var cell = document.querySelector('.board-cell[data-row="' + r + '"][data-col="' + c + '"]');
            if (cell) {
                cell.classList.add('cell-valid');
                (function(row, col) {
                    cell.onclick = function() {
                        submitAction({ action_type: 15, position: [row, col] }); // REVIVE_PLACE
                    };
                })(r, c);
            }
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
    banner.style.background = '#2a6b3a';
    banner.style.top = '60px';

    var cardNid = gameState.pending_conjure_deploy_card;
    var cardName = cardNid != null ? findCardNameByNid(cardNid) : 'card';
    banner.textContent = 'Deploy ' + cardName + ' — click a valid tile';

    var skipBtn = document.createElement('button');
    skipBtn.className = 'tutor-skip-button';
    skipBtn.style.marginLeft = '12px';
    skipBtn.style.display = 'inline';
    skipBtn.textContent = 'To Hand';
    skipBtn.title = 'Send the conjured card to your hand instead of deploying';
    skipBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        // ActionType.DECLINE_CONJURE = 13
        submitAction({ action_type: 13 });
    });
    banner.appendChild(skipBtn);

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
    banner.style.background = '#7a1b1b';
    banner.style.top = '60px';

    var cardName = gameState.pending_death_card_name || 'Death effect';
    var filter = gameState.pending_death_filter || 'enemy_minion';
    var text;
    if (filter === 'friendly_promote') {
        banner.style.background = '#1b5a7a';
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
    toast.style.background = '#7a1b1b';
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

    // Auto-skip behavior gated by the user's react-prompt mode (ON/AUTO/OFF):
    //   OFF  — auto-skip ALWAYS, even if a react card is playable. Useful
    //          when you trust the engine and want minimum interruptions.
    //   AUTO — auto-skip ONLY when no react card is legal (current default).
    //          Pauses for you when you actually have a viable react.
    //   ON   — never auto-skip. Always require a manual click on the
    //          floating Skip React button (or play a react card) to
    //          close the window. YGO-style "always confirm".
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
        // mode === 'on' OR (mode === 'auto' && hasReactOption): fall through
        // and let renderActionBar / floating button drive the manual click.
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
        if (gameState.phase === 1) {
            // REACT phase: show Skip React button (only when player has react cards available)
            var canPass = legalActions.some(function(a) { return a.action_type === 4; });
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
            // ACTION phase: show the free Pass button with the Handshake hint.
            var canPassAction = legalActions.some(function(a) { return a.action_type === 4; });
            if (canPassAction) {
                var passBtn = document.createElement('button');
                passBtn.className = 'btn btn-action btn-pass btn-pass-action';
                passBtn.textContent = 'Pass 🤝';
                passBtn.title = 'Pass — 2nd consecutive pass seals a Handshake '
                    + '(both players gain +1 mana at end of turn; full mana draws a card instead)';
                passBtn.addEventListener('click', function() {
                    submitAction({ action_type: 4 });
                });
                slot.appendChild(passBtn);
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

