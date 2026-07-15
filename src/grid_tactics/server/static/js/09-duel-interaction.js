// =============================================
// Section 10: renderGame() -- Master Render Function
// =============================================

function renderGame() {
    if (!gameState || !cardDefs) return;
    clearSelection();
    renderRoomBar();
    renderOpponentInfo();
    // Phase 14.5 Wave 5: face-down opp hand row + pile button counts.
    (function() {
        if (!gameState || !gameState.players || myPlayerIdx == null) return;
        var opp = gameState.players[1 - myPlayerIdx];
        var hc = (opp.hand_count != null)
            ? opp.hand_count
            : (opp.hand ? opp.hand.length : 0);
        renderOppHandRow(hc, _playerHandElements(opp));
        updatePileButtonCounts();
    })();
    renderBoard();
    renderPlayerAvatars();
    renderSelfInfo();
    if (activePlayerPreviewIdx != null) {
        showPlayerPreview(activePlayerPreviewIdx);
    }
    renderHand();
    renderActionBar();
    // Phase 14.3: do not open react window mid-animation; gated because
    // renderGame runs from applyStateFrame which the AnimationQueue only
    // calls AFTER the triggering animation completes.
    renderReactBanner();
    // Mandatory simultaneous milestone choice every 25 completed turns.
    syncRoguelikeEventUI();
    // Private follow-up picker for Marked Cards fortunes.
    syncMarkedCardsUI();
    // Phase 14.1: if server says a melee minion has just moved and a post-move
    // attack decision is pending, auto-enter the attack-pick UI mode and show
    // the decline button. Must run BEFORE highlightBoard so highlights reflect it.
    // Phase 14.3: do not open post-move-attack picker mid-animation; the
    // AnimationQueue guarantees applyStateFrame (which calls renderGame)
    // only runs AFTER the triggering animation completes.
    syncPendingPostMoveAttackUI();
    // Phase 14.2: pending_tutor modal sync. Caster sees full-card-art picker;
    // opponent sees a passive "Opponent is tutoring…" toast.
    // Phase 14.3: do not open tutor modal mid-animation; gated by the
    // AnimationQueue via applyStateFrame as above.
    syncPendingTutorUI();
    syncPendingConjureDeployUI();
    syncPendingDeathTargetUI();
    syncPendingReviveUI();
    // Phase 14.7-05: simultaneous-trigger priority picker modal.
    syncPendingTriggerPickerUI();
    // Always refresh highlights — even when it's not my turn — so stale
    // .card-playable classes from the previous render are cleared.
    highlightBoard();
    updateHandHighlights();
    updateNavLockState();
}

// =============================================
// Section 10b: Game Interaction System
// =============================================

function _clearBoardInteractionHighlights() {
    // Selection state and its paint are one lifecycle. Some cancellation
    // paths (notably post-move Decline Attack) optimistically re-render
    // while the old mode is still authoritative, then clearSelection after
    // that render. Removing the classes here prevents those stale range /
    // target indicators from surviving until the next server frame.
    document.querySelectorAll('.board-cell').forEach(function(cell) {
        cell.classList.remove(
            'cell-valid', 'cell-attack', 'cell-selected',
            'attack-range-footprint', 'attack-valid-target'
        );
    });
}

function clearSelection() {
    selectedHandIdx = null;
    selectedMinionId = null;
    selectedDeployPos = null;
    selectedAbilityMinionId = null;
    interactionMode = null;
    hideMinionActionMenu();
    closeTransformPicker();
    hideDeclinePostMoveAttackButton();
    _clearBoardInteractionHighlights();
}

function submitAction(actionData, allowDuringBoardPeek) {
    if (isSpectator) { console.warn('spectator cannot submit action'); return; }
    var _at = actionData && actionData.action_type;
    var _modalResolutionTypes = [9, 10, 12, 13, 14, 15, 16, 17, 18];
    var _pendingBoardResolution = canResolvePendingBoardDecisionDuringPeek()
        && (_at === 2 || _at === 8);
    // A minimised window is a board-inspection state, never permission to
    // start a second action while its original choice remains unresolved.
    if (typeof isBoardModalPeekActive === 'function'
            && isBoardModalPeekActive()
            && !allowDuringBoardPeek
            && !_pendingBoardResolution
            && _modalResolutionTypes.indexOf(_at) === -1) return;
    // Spell-stage gate (bug: effect-usable-during-react-window). While the
    // spell stage is still animating on-screen, block every self-initiated
    // action EXCEPT the two that can legitimately close a react window:
    //   PASS (4) — reacter confirms no response.
    //   PLAY_REACT (5) — reacter plays a counter.
    // This catches every submitAction call site (hand-card play, minion
    // move/attack, activated ability, sacrifice, transform, draw, etc.)
    // without having to guard each one individually. It is also a belt-
    // and-suspenders defense: the individual click handlers ALSO gate on
    // isSpellStageAnimating() so the click never even reaches this point
    // when the stage is busy.
    // Phase 14.8 deadlock fix: pending-modal resolution actions must ALSO
    // pass through. While a pending_* gate is set server-side they are the
    // ONLY legal actions, so blocking them on the spell stage could never
    // protect anything — it could only wedge the game at the modal
    // (e.g. TUTOR_SELECT while a leaked spell-stage chain entry keeps
    // isSpellStageAnimating() true).
    //   9 TUTOR_SELECT, 10 DECLINE_TUTOR, 12 CONJURE_DEPLOY,
    //   13 DECLINE_CONJURE, 14 DEATH_TARGET_PICK, 15 REVIVE_PLACE,
    //   16 DECLINE_REVIVE, 17 TRIGGER_PICK, 18 DECLINE_TRIGGER
    // Timing audit (2026-07-06): PASS(4) / PLAY_REACT(5) bypass the gates
    // ONLY when a react window actually awaits THIS player — an ACTION-phase
    // PASS is a normal self-initiated action and must wait for the drain.
    // The post-move attack pick (ATTACK 2 / DECLINE 8) is a server-gated
    // pending decision like the modals, so it passes while pending for us.
    var _reactAwaitsMe = gameState && gameState.phase === 1
        && (gameState.react_player_idx == null
            || myPlayerIdx == null
            || gameState.react_player_idx === myPlayerIdx);
    var _postMovePending = gameState
        && gameState.pending_post_move_attacker_id != null
        && (_at === 2 || _at === 8);
    var _gateExempt = ((_at === 4 || _at === 5) && _reactAwaitsMe)
        || _postMovePending
        || _modalResolutionTypes.indexOf(_at) !== -1;
    if (typeof isSpellStageAnimating === 'function' && isSpellStageAnimating()
            && !_gateExempt) {
        return;
    }
    // Event-queue gate (user 2026-07-06: "its letting me queue moves during
    // the opponents turns"): while queued engine events are still animating,
    // the DOM shows an OLDER state than gameState/legalActions (which hold
    // the final frame — often already the player's next turn). A click mid-
    // drain validated against that future state, submitted, and appeared to
    // "queue" an action that resolved after the animations caught up. Block
    // self-initiated actions until the drain finishes; the same whitelist
    // as the spell-stage gate keeps react windows + modals responsive.
    var _queueBusy = (typeof isEventQueueBusy === 'function' && isEventQueueBusy());
    if (!sandboxMode && _queueBusy && !_gateExempt) {
        return;
    }
    if (socket) {
        // === SANDBOX-EMIT-GATE-START ===
        if (sandboxMode) {
            socket.emit('sandbox_apply_action', actionData);
        } else {
            socket.emit('submit_action', actionData);
        }
        // === SANDBOX-EMIT-GATE-END ===
        // Timing audit (2026-07-06, generalizes the earlier PASS-only fix):
        // ANY submitted action makes us no longer the decision-maker until
        // the server replies. Optimistically clear legalActions and strip
        // every affordance immediately — glow/highlights must not linger on
        // a hand that can no longer act. The reply repopulates everything.
        if (!sandboxMode) {
            if (typeof window !== 'undefined') {
                window.__legalActionsBeforeSubmit = Array.isArray(legalActions)
                    ? legalActions.slice() : [];
            }
            legalActions = [];
            try {
                if (typeof updateHandHighlights === 'function') updateHandHighlights();
                if (typeof highlightBoard === 'function') highlightBoard();
                if (typeof renderHand === 'function') renderHand();
            } catch (e) { /* defensive */ }
        }
    }
    clearSelection();
}

// Get legal actions filtered by type
function getLegalByType(actionType) {
    return legalActions.filter(function(a) { return a.action_type === actionType; });
}

// Phase 14 PLAY-02: react window helpers

// True when the server has put us in a react window
function isReactWindow() {
    if (!gameState || gameState.phase !== 1) return false;
    if (!legalActions || legalActions.length === 0) return false;
    // Sandbox drives both sides, so any viewer is "in the react window"
    // when the state is in REACT phase with legal reacts available.
    if (sandboxMode) return true;
    return gameState.react_player_idx === myPlayerIdx;
}

// Hand indices that are legal as PLAY_REACT (action_type 5)
function getLegalReactCardIndices() {
    var indices = {};
    legalActions.forEach(function(a) {
        if (a.action_type === 5 && a.card_index != null) {
            indices[a.card_index] = true;
        }
    });
    return indices;
}

// Describe the pending opponent action for the react banner
function describePendingAction(pa) {
    if (!pa) {
        if (gameState && gameState.react_stack && gameState.react_stack.length > 0) {
            var top = gameState.react_stack[gameState.react_stack.length - 1];
            var topName = (top.card_numeric_id != null && cardDefs[top.card_numeric_id])
                ? cardDefs[top.card_numeric_id].name : 'a react card';
            return 'Opponent is responding with ' + topName;
        }
        return 'Opponent action pending';
    }
    var t = pa.action_type;
    if (t === 0) {
        if (pa.position) {
            return 'Opponent is playing a card at row ' + (pa.position[0] + 1) + ' col ' + (pa.position[1] + 1);
        }
        return 'Opponent is casting a card';
    }
    if (t === 1) {
        return 'Opponent is moving a minion';
    }
    if (t === 2) {
        if (pa.target_id != null && gameState && gameState.minions) {
            var tgt = null;
            gameState.minions.forEach(function(m) { if (m.instance_id === pa.target_id) tgt = m; });
            if (tgt) {
                var tgtName = (cardDefs[tgt.card_numeric_id]) ? cardDefs[tgt.card_numeric_id].name : 'minion';
                if (tgt.owner === myPlayerIdx) {
                    return 'Opponent is attacking your ' + tgtName;
                }
                return 'Opponent is attacking their own ' + tgtName;
            }
        }
        return 'Opponent is attacking';
    }
    if (t === 5) {
        if (gameState && gameState.react_stack && gameState.react_stack.length > 0) {
            var entry = gameState.react_stack[gameState.react_stack.length - 1];
            var rname = (entry.card_numeric_id != null && cardDefs[entry.card_numeric_id])
                ? cardDefs[entry.card_numeric_id].name : 'a react card';
            return 'Opponent is responding with ' + rname;
        }
        return 'Opponent is responding with a react card';
    }
    if (t === 6) {
        if (pa.minion_id != null && gameState && gameState.minions) {
            var src = null;
            gameState.minions.forEach(function(m) { if (m.instance_id === pa.minion_id) src = m; });
            if (src) {
                var sName = (cardDefs[src.card_numeric_id]) ? cardDefs[src.card_numeric_id].name : 'minion';
                return 'Opponent is sacrificing their ' + sName + ' for damage';
            }
        }
        return 'Opponent is sacrificing for damage';
    }
    return 'Opponent action pending';
}

// Render the react banner above the action bar
function renderReactBanner() {
    var existing = document.getElementById('react-banner');
    if (existing) existing.remove();
    if (!isReactWindow()) return;
    // Timing overhaul (2026-07-08, F6): suppress the phantom REACT WINDOW
    // flash when the window belongs to the OTHER player and it's the
    // PASS-only turn-end Decay window (BEFORE_END_OF_TURN with an empty
    // react stack) — nothing for the viewer to do or watch. Note
    // gameState.react_context is the wire INT (5 = BEFORE_END_OF_TURN);
    // some event paths stash the enum NAME string, so accept both.
    try {
        var _rc = gameState ? gameState.react_context : null;
        var _isDecayCtx = (_rc === 5 || _rc === 'BEFORE_END_OF_TURN');
        var _stackEmpty = !gameState || !gameState.react_stack
            || gameState.react_stack.length === 0;
        var _othersWindow = gameState && gameState.react_player_idx != null
            && myPlayerIdx != null
            && gameState.react_player_idx !== myPlayerIdx;
        if (_othersWindow && _isDecayCtx && _stackEmpty) return;
    } catch (e) { /* defensive — fall through to the normal banner */ }

    var banner = document.createElement('div');
    banner.id = 'react-banner';
    banner.className = 'react-banner';
    var label = document.createElement('span');
    label.className = 'react-banner-label';
    label.textContent = 'REACT WINDOW';
    var desc = document.createElement('span');
    desc.className = 'react-banner-desc';
    desc.textContent = describePendingAction(gameState.pending_action);
    banner.appendChild(label);
    banner.appendChild(desc);

    // Insert banner above the hand container
    var handEl = document.getElementById('hand-container');
    if (handEl && handEl.parentNode) {
        handEl.parentNode.insertBefore(banner, handEl);
    }
}

// Check if a specific hand card can be played to a specific position
function canPlayCardAt(handIdx, row, col) {
    return legalActions.some(function(a) {
        return a.action_type === 0 && a.card_index === handIdx
            && a.position && a.position[0] === row && a.position[1] === col;
    });
}

// Get unique deploy positions for a hand card (deduped)
function getDeployPositions(handIdx) {
    var seen = {};
    var positions = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 0 && a.card_index === handIdx && a.position) {
            var key = a.position[0] + ',' + a.position[1];
            if (!seen[key]) {
                seen[key] = true;
                positions.push(a.position);
            }
        }
    });
    return positions;
}

// Get unique target positions for a hand card. If deployPos is provided,
// only return targets that go with that deploy position (for minions with on-play targeting).
function getTargetPositions(handIdx, deployPos) {
    var seen = {};
    var positions = [];
    legalActions.forEach(function(a) {
        if (a.action_type !== 0 || a.card_index !== handIdx) return;
        if (!a.target_pos) return;
        if (deployPos != null) {
            if (!a.position) return;
            if (a.position[0] !== deployPos[0] || a.position[1] !== deployPos[1]) return;
        }
        var key = a.target_pos[0] + ',' + a.target_pos[1];
        if (!seen[key]) {
            seen[key] = true;
            positions.push(a.target_pos);
        }
    });
    return positions;
}

// Find a legal action for this card matching position+target_pos
// Build a submit-ready payload for a PLAY_CARD action that preserves every
// optional field the server checks (position, target_pos, discard_card_index,
// discard_card_indices, destroyed_minion_id). Synthesising payloads from
// (handIdx, target) alone drops these and the server's `action not in
// valid_actions` check rejects it as "Illegal action".
function _playCardPayload(action) {
    var payload = { action_type: 0, card_index: action.card_index };
    if (action.position) payload.position = action.position;
    if (action.target_pos) payload.target_pos = action.target_pos;
    if (action.discard_card_index != null) payload.discard_card_index = action.discard_card_index;
    if (action.discard_card_indices && action.discard_card_indices.length > 0) {
        payload.discard_card_indices = action.discard_card_indices;
    }
    // destroyed_minion_id on the wire; accept legacy sacrifice_minion_id
    // from an older server frame so a half-deployed stack doesn't break.
    var destroyed = (action.destroyed_minion_id != null)
        ? action.destroyed_minion_id
        : action.sacrifice_minion_id;
    if (destroyed != null) payload.destroyed_minion_id = destroyed;
    return payload;
}

function findCardAction(handIdx, deployPos, targetPos) {
    for (var i = 0; i < legalActions.length; i++) {
        var a = legalActions[i];
        if (a.action_type !== 0 || a.card_index !== handIdx) continue;
        if (deployPos != null) {
            if (!a.position) continue;
            if (a.position[0] !== deployPos[0] || a.position[1] !== deployPos[1]) continue;
        } else {
            if (a.position) continue;
        }
        if (targetPos != null) {
            if (!a.target_pos) continue;
            if (a.target_pos[0] !== targetPos[0] || a.target_pos[1] !== targetPos[1]) continue;
        } else {
            if (a.target_pos) continue;
        }
        return a;
    }
    return null;
}

// Collect every discard-candidate hand index for this (handIdx, deployPos,
// targetPos) — the union of every index that appears in any legal action's
// discard_card_indices (falling back to the legacy single-index field).
// Without the union, multi-discard cards miss candidates because
// itertools.combinations is sorted, so the highest index never shows up as
// the first element.
function getSacrificeChoices(handIdx, deployPos, targetPos) {
    var seen = {};
    var choices = [];
    legalActions.forEach(function(a) {
        if (a.action_type !== 0 || a.card_index !== handIdx) return;
        if (deployPos != null && a.position) {
            if (a.position[0] !== deployPos[0] || a.position[1] !== deployPos[1]) return;
        }
        if (targetPos != null && a.target_pos) {
            if (a.target_pos[0] !== targetPos[0] || a.target_pos[1] !== targetPos[1]) return;
        }
        var indices = (a.discard_card_indices && a.discard_card_indices.length > 0)
            ? a.discard_card_indices
            : (a.discard_card_index != null ? [a.discard_card_index] : []);
        for (var k = 0; k < indices.length; k++) {
            var v = indices[k];
            if (!seen[v]) { seen[v] = true; choices.push(v); }
        }
    });
    return choices;
}

// Get valid move positions for a minion
function getMovePositions(minionId) {
    var positions = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 1 && a.minion_id === minionId && a.position) {
            positions.push(a.position);
        }
    });
    return positions;
}

// Get available transform actions for a minion
function getTransformActions(minionId) {
    var transforms = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 7 && a.minion_id === minionId && a.transform_target) {
            transforms.push(a);
        }
    });
    return transforms;
}

// Get valid attack targets for a minion
function getAttackTargets(minionId) {
    var targets = [];
    legalActions.forEach(function(a) {
        if (a.action_type === 2 && a.minion_id === minionId && a.target_id != null) {
            targets.push(a.target_id);
        }
    });
    return targets;
}

// Can this minion be sacrificed?
function canSacrifice(minionId) {
    return legalActions.some(function(a) {
        return a.action_type === 6 && a.minion_id === minionId;
    });
}

// Can this hand card be played (any legal PLAY_CARD with this index)?
function canPlayCard(handIdx) {
    return legalActions.some(function(a) {
        return a.action_type === 0 && a.card_index === handIdx;
    });
}

// Handle clicking a hand card
// ownerIdx — in sandbox, which player's hand the card came from. Live
// game passes nothing; own hand is always myPlayerIdx.
function onHandCardClick(handIdx, ownerIdx) {
    if (isSpectator) return;  // spectators cannot play cards
    if (typeof isBoardModalPeekActive === 'function'
            && isBoardModalPeekActive()) return;
    // Timing audit (2026-07-06): while the event queue is draining, the
    // board on screen is older than gameState — selection/targeting must
    // not engage. React clicks (my window) and pending-decision modes stay
    // live; everything else is inert until the drain ends.
    if (!sandboxMode && typeof isEventQueueBusy === 'function' && isEventQueueBusy()
            && !isReactWindow()
            && interactionMode !== 'death_target_pick'
            && interactionMode !== 'post_move_attack_pick'
            && interactionMode !== 'conjure_deploy'
            && interactionMode !== 'revive_place'
            && interactionMode !== 'exhaust_play') {
        return;
    }
    // Spell-stage gate: if a react window just closed and the stage is
    // still animating, only PLAY_REACT clicks are allowed through (those
    // still resolve against the live phase=REACT if we're somehow still
    // in it). Play-card-for-normal-action clicks are dropped until the
    // animation finishes. The authoritative gate is in submitAction; this
    // early return just avoids arming/targeting UI that would never fire.
    if (isSpellStageAnimating() && !isReactWindow()) return;
    // Phase 14 PLAY-02: react window has its own click semantics.
    // Sandbox: the clicked hand's owner must be the current reacting
    // player — otherwise the card_index matches the wrong side's legal
    // actions and we'd submit the opponent's react.
    if (isReactWindow()) {
        if (sandboxMode && ownerIdx != null && gameState && ownerIdx !== gameState.react_player_idx) {
            return;  // this hand isn't the reacting side — inert click
        }
        var reactAction = null;
        legalActions.forEach(function(a) {
            if (a.action_type === 5 && a.card_index === handIdx) reactAction = a;
        });
        if (reactAction) {
            var payload = { action_type: 5, card_index: handIdx };
            if (reactAction.target_pos) payload.target_pos = reactAction.target_pos;
            submitAction(payload);
        }
        return;
    }
    // Outside react phase, in sandbox, the clicked hand's owner must be
    // the active player — otherwise PLAY_CARD actions wouldn't match.
    if (sandboxMode && ownerIdx != null && gameState && gameState.phase === 0 && ownerIdx !== gameState.active_player_idx) {
        return;
    }
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // Second click on an already-armed untargeted magic → confirm and cast.
    // This is the commit half of the two-click-to-cast flow below, so
    // accidentally brushing a magic card doesn't fire it immediately.
    if (selectedHandIdx === handIdx && interactionMode === 'confirm') {
        // Discard-cost gate (user 2026-07-10): this path used to submit the
        // FIRST matching legal action verbatim — for a discard-cost card
        // (Shady Trade Deal) that silently exhausted whichever hand card
        // the first action happened to name. Paying a cost now always
        // requires an explicit pick + Accept in the picker.
        var confirmSacs = getSacrificeChoices(handIdx, null, null);
        if (confirmSacs.length > 0) {
            showSacrificePicker(handIdx, null, null, confirmSacs);
            return;
        }
        var armed = findCardAction(handIdx, null, null);
        if (armed) submitAction(_playCardPayload(armed));
        clearSelection();
        highlightBoard();
        updateHandHighlights();
        return;
    }

    // If already selected in play/target mode, deselect.
    if (selectedHandIdx === handIdx && (interactionMode === 'play' || interactionMode === 'target')) {
        clearSelection();
        highlightBoard();
        updateHandHighlights();
        return;
    }

    var deployPositions = getDeployPositions(handIdx);
    var targetOnly = getTargetPositions(handIdx, null); // for magics with no deploy

    // Untargeted magic: find an action with no position and no target. Arm
    // the card and wait for a second click to confirm — prevents an
    // accidental tap from firing an expensive board-wide spell.
    var untargeted = findCardAction(handIdx, null, null);
    if (deployPositions.length === 0 && targetOnly.length === 0 && untargeted) {
        selectedHandIdx = handIdx;
        selectedMinionId = null;
        selectedDeployPos = null;
        interactionMode = 'confirm';
        highlightBoard();
        updateHandHighlights();
        return;
    }

    // Magic with exactly ONE legal target — auto-arm AND auto-target on
    // first click. Users kept failing to click the highlighted tile (the
    // enemy minion draws over the cell) so for a one-target spell there's
    // nothing for them to resolve — just submit directly. A second click
    // on the same card re-selects in case they want to back out.
    if (deployPositions.length === 0 && targetOnly.length === 1) {
        var onlyTarget = targetOnly[0];
        // Discard-cost gate (user 2026-07-10): the auto-submit skipped the
        // discard picker entirely, silently paying with an arbitrary card.
        var onlySacs = getSacrificeChoices(handIdx, null, onlyTarget);
        if (onlySacs.length > 0) {
            selectedHandIdx = handIdx;
            selectedMinionId = null;
            selectedDeployPos = null;
            showSacrificePicker(handIdx, null, onlyTarget, onlySacs);
            return;
        }
        var onlyMatch = findCardAction(handIdx, null, onlyTarget);
        if (onlyMatch) {
            submitAction(_playCardPayload(onlyMatch));
            clearSelection();
            highlightBoard();
            updateHandHighlights();
            return;
        }
    }

    // Magic with target selection: no deploy positions, only target_pos
    if (deployPositions.length === 0 && targetOnly.length > 0) {
        selectedHandIdx = handIdx;
        selectedMinionId = null;
        selectedDeployPos = null;
        interactionMode = 'target';
        highlightBoard();
        updateHandHighlights();
        return;
    }

    // Minion deployment (with or without on-play targets)
    if (deployPositions.length > 0) {
        selectedHandIdx = handIdx;
        selectedMinionId = null;
        selectedDeployPos = null;
        interactionMode = 'play';
        highlightBoard();
        updateHandHighlights();
    }
}

// Handle clicking a board cell
function onBoardCellClick(row, col) {
    // Must precede the sandbox direct-emit branch below: peek mode is
    // read-only in both live games and god-view sandbox.
    var _peekActive = typeof isBoardModalPeekActive === 'function'
        && isBoardModalPeekActive();
    var _pendingBoardDecision = canResolvePendingBoardDecisionDuringPeek();
    if (_peekActive && !_pendingBoardDecision) return;
    // Sandbox: if a card is staged, click-to-place on empty cell
    // (never let that convenience path steal a mandatory target/placement
    // click from Revive, Conjure, death targeting, or post-move attack).
    if (sandboxMode && !_pendingBoardDecision) {
        var staged = document.getElementById('sandbox-staged-card');
        if (staged && !staged.hidden && staged.dataset.nid) {
            var nid = parseInt(staged.dataset.nid, 10);
            if (!isNaN(nid)) {
                var stagedPlaced = emitSandboxEvent('sandbox_place_on_board', {
                    player_idx: sandboxAddTargetIdx,
                    card_numeric_id: nid,
                    row: row,
                    col: col,
                });
                if (!stagedPlaced) return;
                // Clear staged card so normal gameplay clicks work
                staged.hidden = true;
                staged.dataset.nid = '';
                return;
            }
        }
    }
    if (isSpectator) return;  // spectators are read-only
    // Timing audit (2026-07-06): while the event queue is draining, the
    // board on screen is older than gameState — selection/targeting must
    // not engage. React clicks (my window) and pending-decision modes stay
    // live; everything else is inert until the drain ends.
    if (!sandboxMode && typeof isEventQueueBusy === 'function' && isEventQueueBusy()
            && !isReactWindow()
            && interactionMode !== 'death_target_pick'
            && interactionMode !== 'post_move_attack_pick'
            && interactionMode !== 'conjure_deploy'
            && interactionMode !== 'revive_place'
            && interactionMode !== 'exhaust_play') {
        return;
    }
    // Spell-stage/react gates block ordinary board actions, but not the
    // board click that resolves a mandatory pending decision. Revive and
    // Conjure are commonly opened by the spell still parked on the stage;
    // swallowing their tile click deadlocks that spell (Ratical was the
    // visible regression). Post-move attack and death targeting follow the
    // same server-gated decision contract.
    var _pendingCellDecision = interactionMode === 'death_target_pick'
        || interactionMode === 'post_move_attack_pick'
        || interactionMode === 'conjure_deploy'
        || interactionMode === 'revive_place';
    if (isSpellStageAnimating() && !_pendingCellDecision) return;
    // A pending decision is authoritative even if the underlying state is
    // technically still in REACT while the interrupted chain waits on it.
    if (isReactWindow() && !_pendingCellDecision) return;
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // Death-target pick mode. Click a valid enemy minion tile to submit
    // DEATH_TARGET_PICK. Valid targets come from pending_death_valid_targets
    // on the state frame. Everything else is inert.
    if (interactionMode === 'death_target_pick') {
        var validDeath = (gameState && gameState.pending_death_valid_targets) || [];
        var isValidDeath = validDeath.some(function(p) { return p[0] === row && p[1] === col; });
        if (!isValidDeath) return;
        // ActionType.DEATH_TARGET_PICK = 14
        submitAction({ action_type: 14, target_pos: [row, col] });
        return;
    }

    // Light Wyrm (2026-07-11): tile placement after choosing Summon in
    // the Exhaust pile modal.
    if (interactionMode === 'exhaust_play') {
        var exIdx = window.__exhaustPlayIdx;
        var exAction = (legalActions || []).find(function(a) {
            return a.action_type === 19 && a.position
                && a.position[0] === row && a.position[1] === col
                && (exIdx == null || a.card_index === exIdx);
        });
        if (!exAction) return;
        window.__exhaustPlayIdx = null;
        submitAction({
            action_type: 19,
            card_index: exAction.card_index,
            position: [row, col],
        });
        interactionMode = null;
        return;
    }

    // Revive rework (user 2026-07-11): tile placement after picking a
    // minion from the revive fan. The old flow had NO cell-click branch —
    // it relied on inline cell.onclick handlers that renderBoard wiped.
    if (interactionMode === 'revive_place') {
        var pickedGraveIdx = window.__reviveSelectedGraveIdx;
        var revAction = (legalActions || []).find(function(a) {
            return a.action_type === 15 && a.position
                && a.position[0] === row && a.position[1] === col
                && (pickedGraveIdx == null || a.card_index == null
                    || a.card_index === pickedGraveIdx);
        });
        if (!revAction) return;
        // In-flight guard — suppress the modal until the fresh frame lands.
        window.__reviveSubmittedAtRemaining = (gameState
            && gameState.pending_revive_remaining) || 0;
        var revPayload = { action_type: 15, position: [row, col] }; // REVIVE_PLACE
        // Generalized revive (2026-07-11): send the picked grave index.
        var revIdx = (pickedGraveIdx != null) ? pickedGraveIdx : revAction.card_index;
        if (revIdx != null) revPayload.card_index = revIdx;
        window.__reviveSelectedGraveIdx = null;
        submitAction(revPayload);
        interactionMode = null;
        if (typeof closeReviveModal === 'function') closeReviveModal();
        return;
    }

    // Phase 14.6: conjure deploy mode. Player picks a tile to deploy the
    // conjured card. Valid positions are highlighted; everything else is inert.
    if (interactionMode === 'conjure_deploy') {
        var validPos = (gameState && gameState.pending_conjure_deploy_positions) || [];
        var isValid = validPos.some(function(p) { return p[0] === row && p[1] === col; });
        if (!isValid) return;
        // In-flight guard (GT-9833FF / GT-997B75): syncPendingConjureDeployUI
        // re-asserts conjure_deploy mode from the still-stale gameState on
        // every render, so a second click after submit re-sent the deploy —
        // rejected server-side as an Illegal action. Suppress re-arming
        // until a frame with the pending gate cleared arrives.
        window.__conjureDeploySubmitted = true;
        // ActionType.CONJURE_DEPLOY = 12
        submitAction({ action_type: 12, position: [row, col] });
        interactionMode = null;
        if (typeof closeConjureDeployUI === 'function') closeConjureDeployUI();
        return;
    }

    // Phase 14.1: post-move attack-pick mode. Only valid enemy targets are
    // clickable; everything else is inert (use Decline button to exit).
    if (interactionMode === 'post_move_attack_pick') {
        var enemy = getMinionAt(row, col);
        if (!enemy) return;
        var attackerId = gameState && gameState.pending_post_move_attacker_id;
        if (attackerId == null) return;
        // Primary: trust server-provided pending_attack_valid_targets.
        var validTargets = (gameState && gameState.pending_attack_valid_targets) || [];
        var isValidTargetTile = validTargets.some(function(p) { return p[0] === row && p[1] === col; });
        // Fallback: any legal ATTACK action by the pending attacker against
        // this enemy (defensive — should always match the target list but
        // guards against desync between view_filter and legal_actions).
        var isLegalAttack = (legalActions || []).some(function(a) {
            return a.action_type === 2 && a.minion_id === attackerId && a.target_id === enemy.instance_id;
        });
        if (!isValidTargetTile && !isLegalAttack) return;
        // In-flight guard (user 2026-07-11 "decline attack button stays up
        // too long"): syncPendingPostMoveAttackUI re-arms off the stale
        // frame during the drain, keeping the button (and pick mode) up
        // seconds after the choice. Suppress until the pending gate clears.
        window.__postMoveSubmitted = true;
        submitAction({
            action_type: 2,
            minion_id: attackerId,
            target_id: enemy.instance_id,
        });
        interactionMode = null;
        hideDeclinePostMoveAttackButton();
        return;
    }

    // Activated ability target picking (e.g. Ratchanter Summon Rat)
    if (interactionMode === 'activate_target' && selectedAbilityMinionId !== null) {
        var isLegal = (legalActions || []).some(function(a) {
            return a.action_type === 11
                && a.minion_id === selectedAbilityMinionId
                && a.target_pos && a.target_pos[0] === row && a.target_pos[1] === col;
        });
        if (isLegal) {
            submitAction({
                action_type: 11,
                minion_id: selectedAbilityMinionId,
                target_pos: [row, col],
            });
            selectedAbilityMinionId = null;
            interactionMode = null;
        }
        return;
    }

    // Armed untargeted magic: a click anywhere on the board (nothing to
    // target here) cancels the arm so the card doesn't stay committed
    // on deck after a stray click.
    if (interactionMode === 'confirm') {
        clearSelection();
        highlightBoard();
        updateHandHighlights();
        return;
    }

    // If we have a hand card selected for deploy
    if (interactionMode === 'play' && selectedHandIdx !== null) {
        if (canPlayCardAt(selectedHandIdx, row, col)) {
            // Check if this card has on-play targeting at this deploy position
            var targetsForDeploy = getTargetPositions(selectedHandIdx, [row, col]);
            if (targetsForDeploy.length > 0) {
                // Two-stage: deploy now locked, ask for target
                selectedDeployPos = [row, col];
                interactionMode = 'target';
                highlightBoard();
                return;
            }
            // Check for discard-cost choices (discard_cost_tribe card).
            // ALWAYS route through the picker — even with a single eligible
            // card, paying a cost requires an explicit pick + Accept
            // (user 2026-07-10; never silently discard from the hand).
            var sacChoices = getSacrificeChoices(selectedHandIdx, [row, col], null);
            if (sacChoices.length > 0) {
                selectedDeployPos = [row, col];
                showSacrificePicker(selectedHandIdx, [row, col], null, sacChoices);
                return;
            }
            // No targeting/discard needed — submit via matched action so
            // destroyed_minion_id (minions with destroy_ally_cost — not
            // currently used by minions, but future-proof) propagates.
            var matched0 = findCardAction(selectedHandIdx, [row, col], null);
            if (matched0) {
                submitAction(_playCardPayload(matched0));
            }
        }
        return;
    }

    // Target selection mode (magic targeting OR minion on-play target after deploy was picked)
    if (interactionMode === 'target' && selectedHandIdx !== null) {
        var validTarget = getTargetPositions(selectedHandIdx, selectedDeployPos).some(function(p) {
            return p[0] === row && p[1] === col;
        });
        if (validTarget) {
            // Check for discard-cost choices at this combo. ALWAYS route
            // through the picker — paying a cost requires an explicit
            // pick + Accept (user 2026-07-10).
            var sacChoices2 = getSacrificeChoices(selectedHandIdx, selectedDeployPos, [row, col]);
            if (sacChoices2.length > 0) {
                showSacrificePicker(selectedHandIdx, selectedDeployPos, [row, col], sacChoices2);
                return;
            }
            // Find the FULL matched legal action and rebuild the payload from
            // it — carries destroyed_minion_id for destroy_ally_cost cards
            // (e.g. Feed the Shadow) that the synthesised payload used to
            // drop. First match wins the ally pick for cards with >1 ally.
            var matched = findCardAction(selectedHandIdx, selectedDeployPos, [row, col]);
            if (matched) {
                submitAction(_playCardPayload(matched));
            }
        }
        return;
    }

    // If we have a minion selected for move, try to move here
    if ((interactionMode === 'move' || interactionMode === 'move_attack') && selectedMinionId !== null) {
        var movePositions = getMovePositions(selectedMinionId);
        var validMove = movePositions.some(function(p) { return p[0] === row && p[1] === col; });
        if (validMove) {
            submitAction({ action_type: 1, minion_id: selectedMinionId, position: [row, col] });
            return;
        }
        // In move_attack mode, clicking a non-valid-move empty cell should not block
        // the "click own minion to reselect" path below. In pure move mode we return.
        if (interactionMode === 'move') return;
    }

    // Click on any minion — route to minion handler so the attack/target/
    // post-move-attack/reselect branches all run. Previously gated on
    // `owner === myPlayerIdx`, which made enemy clicks a dead-end in
    // interactionMode === 'attack' / 'move_attack' (Bug C).
    var minion = getMinionAt(row, col);
    if (minion) {
        onBoardMinionClick(minion);
    }
}

// Handle clicking a board minion
function onBoardMinionClick(minion) {
    if (isSpectator) return;  // spectators are read-only
    if (typeof isBoardModalPeekActive === 'function'
            && isBoardModalPeekActive()
            && !canResolvePendingBoardDecisionDuringPeek()) return;
    // Timing audit (2026-07-06): while the event queue is draining, the
    // board on screen is older than gameState — selection/targeting must
    // not engage. React clicks (my window) and pending-decision modes stay
    // live; everything else is inert until the drain ends.
    if (!sandboxMode && typeof isEventQueueBusy === 'function' && isEventQueueBusy()
            && !isReactWindow()
            && interactionMode !== 'death_target_pick'
            && interactionMode !== 'post_move_attack_pick'
            && interactionMode !== 'conjure_deploy'
            && interactionMode !== 'revive_place'
            && interactionMode !== 'exhaust_play') {
        return;
    }
    // Spell-stage gate: same rationale as onBoardCellClick. Blocks the
    // action-menu open + attack/target routing so a click on a minion
    // during the spell-stage animation is inert (except death-target).
    if (isSpellStageAnimating() && interactionMode !== 'death_target_pick') return;
    // Board clicks are inert during react window EXCEPT when a death
    // target pick is pending (see onBoardCellClick comment).
    if (isReactWindow() && interactionMode !== 'death_target_pick') return;
    var isMyTurn = legalActions && legalActions.length > 0;
    if (!isMyTurn) return;

    // Phase 14.1: in post-move attack-pick mode, only enemy clicks on valid
    // target tiles are honored — selecting other minions is inert.
    if (interactionMode === 'post_move_attack_pick') {
        onBoardCellClick(minion.position[0], minion.position[1]);
        return;
    }

    // Death-target pick mode: defer to the cell click path so the same
    // valid-target filter runs.
    if (interactionMode === 'death_target_pick') {
        onBoardCellClick(minion.position[0], minion.position[1]);
        return;
    }

    // If in target-selection mode (magic with target), use this minion's position as target
    if (interactionMode === 'target' && selectedHandIdx !== null) {
        onBoardCellClick(minion.position[0], minion.position[1]);
        return;
    }

    // If in attack mode and clicking an enemy — attack it
    if ((interactionMode === 'attack' || interactionMode === 'move_attack') && selectedMinionId !== null && minion.owner !== myPlayerIdx) {
        var targets = getAttackTargets(selectedMinionId);
        if (targets.indexOf(minion.instance_id) !== -1) {
            submitAction({ action_type: 2, minion_id: selectedMinionId, target_id: minion.instance_id });
            return;
        }
    }

    // If clicking own minion — show action menu
    if (minion.owner === myPlayerIdx) {
        // If already selected, deselect
        if (selectedMinionId === minion.instance_id) {
            clearSelection();
            hideMinionActionMenu();
            highlightBoard();
            updateHandHighlights();
            return;
        }

        selectedMinionId = minion.instance_id;
        selectedHandIdx = null;
        // Don't auto-enter move/attack mode — wait for menu choice
        interactionMode = null;

        var moves = getMovePositions(minion.instance_id);
        var attacks = getAttackTargets(minion.instance_id);
        var transforms = getTransformActions(minion.instance_id);
        var canSac = canSacrifice(minion.instance_id);

        showMinionActionMenu(minion, moves, attacks, transforms, canSac);

        // Clear any stale highlights — they'll appear when a menu option is picked
        highlightBoard();
        updateHandHighlights();
    }
}

// Show a popup action menu sticking out from the selected minion's tile.
// Always shows Move/Attack/Effects/Cancel — options are disabled or hidden if not applicable.
// Uses fixed positioning anchored to the cell rect so it can't be clipped by
// .board-cell's overflow:hidden (which exists for the card-art background).
function showMinionActionMenu(minion, moves, attacks, transforms, canSac) {
    hideMinionActionMenu();
    var cell = document.querySelector('.board-cell[data-row="' + minion.position[0] + '"][data-col="' + minion.position[1] + '"]');
    if (!cell) return;
    var rect = cell.getBoundingClientRect();

    var menu = document.createElement('div');
    menu.id = 'minion-action-menu';
    menu.className = 'minion-action-menu';

    function addBtn(label, cls, handler, disabled, previewNid) {
        var btn = document.createElement('button');
        btn.className = 'minion-action-btn ' + (cls || '');
        btn.textContent = label;
        // Highlighting an option previews its card in the tooltip panel
        // (user 2026-07-06), matching the grave/exhaust modals.
        if (previewNid != null) {
            btn.addEventListener('mouseenter', function() {
                showGameTooltip(previewNid, btn, null, { force: true });
            });
        }
        if (disabled) {
            btn.disabled = true;
            btn.classList.add('disabled');
        } else {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                handler();
            });
        }
        menu.appendChild(btn);
    }

    // Move
    if (moves && moves.length > 0) {
        addBtn('Move', 'move', function() {
            interactionMode = (attacks && attacks.length > 0) ? 'move_attack' : 'move';
            hideMinionActionMenu();
            highlightBoard();
            renderActionBar();
        });
    }

    // Attack
    if (attacks && attacks.length > 0) {
        addBtn('Attack', 'attack', function() {
            interactionMode = 'attack';
            hideMinionActionMenu();
            highlightBoard();
            renderActionBar();
        });
    }

    // Activated ability (e.g. Ratchanter "Summon Rat (1)")
    var minionCard = cardDefs[minion.card_numeric_id];
    var ability = minionCard && minionCard.activated_ability;
    if (ability) {
        var myMana = (gameState && gameState.players && gameState.players[myPlayerIdx])
            ? gameState.players[myPlayerIdx].current_mana : 0;
        var abilityActions = (legalActions || []).filter(function(a) {
            return a.action_type === 11 && a.minion_id === minion.instance_id;
        });
        var canActivate = myMana >= ability.mana_cost && abilityActions.length > 0;
        addBtn(ability.name + ' (' + ability.mana_cost + ')', 'ability', function() {
            hideMinionActionMenu();
            if (ability.target === 'none') {
                // Untargeted self-ability -- submit directly.
                submitAction({
                    action_type: 11,
                    minion_id: minion.instance_id,
                    target_pos: null,
                });
                return;
            }
            selectedAbilityMinionId = minion.instance_id;
            interactionMode = 'activate_target';
            highlightBoard();
            renderActionBar();
        }, !canActivate);
    }

    // Effects: Sacrifice + Transform options (only if any apply)
    if (canSac) {
        addBtn('Sacrifice for damage', 'sacrifice', function() {
            submitAction({ action_type: 6, minion_id: minion.instance_id });
        });
    }
    // Transform is an operation button; the specific card target is chosen
    // in a Tutor-style full-card picker. This keeps card choices readable on
    // both pointer and touch devices instead of naming cards in tiny buttons.
    var transformSourceCard = cardDefs[minion.card_numeric_id];
    if (transformSourceCard && transformSourceCard.transform_options &&
        transformSourceCard.transform_options.length > 0) {
        addBtn('Transform', 'transform', function() {
            hideMinionActionMenu();
            showTransformPicker(
                minion, transformSourceCard,
                transformSourceCard.transform_options, transforms || []
            );
        });
    }

    // Cancel — always present
    addBtn('Cancel', 'cancel', function() {
        clearSelection();
        hideMinionActionMenu();
        highlightBoard();
        updateHandHighlights();
    });

    // Context menu at the clicked tile (user 2026-07-10): the centered
    // stage modal (2026-07-06) greyed the whole board and could overflow
    // below the grid when a minion had many options. The backdrop stays
    // as an invisible click-away catcher; the menu itself anchors beside
    // the minion's tile, clamped inside the stage.
    var backdrop = document.createElement('div');
    backdrop.id = 'stage-menu-backdrop';
    backdrop.className = 'stage-modal-backdrop ctx-menu-backdrop';
    backdrop.addEventListener('click', function(e) {
        if (e.target !== backdrop) return;
        clearSelection();
        hideMinionActionMenu();
        highlightBoard();
        updateHandHighlights();
    });
    backdrop.appendChild(menu);
    (document.querySelector('.screen.active .game-layout') || document.body)
        .appendChild(backdrop);
    // Position in LAYOUT coordinates: rects are viewport px but the menu
    // lives inside the scaled .game-layout — divide by --duel-scale (same
    // trick as the spell-stage slam-in, audit 2026-07-07).
    try {
        var bdRect = backdrop.getBoundingClientRect();
        var sc = parseFloat(getComputedStyle(document.documentElement)
            .getPropertyValue('--duel-scale')) || 1;
        var bw = bdRect.width / sc;
        var bh = bdRect.height / sc;
        var mw = menu.offsetWidth;
        var mh = menu.offsetHeight;
        // Prefer the tile's right edge; flip to the left side when it
        // would clip. Clamp vertically so long menus never sink below
        // the stage.
        var mx = (rect.right - bdRect.left) / sc + 6;
        var my = (rect.top - bdRect.top) / sc - 4;
        if (mx + mw > bw - 4) {
            mx = Math.max(4, (rect.left - bdRect.left) / sc - mw - 6);
        }
        if (my + mh > bh - 4) my = bh - mh - 4;
        if (my < 4) my = 4;
        menu.style.setProperty('--ctx-x', mx + 'px');
        menu.style.setProperty('--ctx-y', my + 'px');
    } catch (e) { /* CSS fallback centers it */ }
}

function hideMinionActionMenu() {
    var existing = document.getElementById('minion-action-menu');
    if (existing) existing.remove();
    var bd = document.getElementById('stage-menu-backdrop');
    if (bd) bd.remove();
}

function _transformTargetNumericId(cardId) {
    for (var nid in cardDefs) {
        if (cardDefs[nid] && cardDefs[nid].card_id === cardId) {
            return parseInt(nid, 10);
        }
    }
    return null;
}

function showTransformPicker(minion, sourceCard, options, legalTransforms) {
    closeTransformPicker();
    var legalTargets = {};
    (legalTransforms || []).forEach(function(action) {
        legalTargets[action.transform_target] = true;
    });

    var overlay = document.createElement('div');
    overlay.id = 'transform-picker-overlay';
    overlay.className = 'tutor-modal-overlay transform-picker-overlay';
    var modal = document.createElement('div');
    modal.className = 'tutor-modal transform-picker-modal';

    var header = document.createElement('div');
    header.className = 'tutor-modal-header';
    var title = document.createElement('div');
    title.className = 'tutor-modal-title';
    title.textContent = 'Choose a Transformation';
    var subtitle = document.createElement('div');
    subtitle.className = 'tutor-modal-deckline transform-picker-instruction';
    subtitle.textContent = (sourceCard && sourceCard.name ? sourceCard.name : 'This minion')
        + ' keeps its tile and becomes the selected card.';
    header.appendChild(title);
    header.appendChild(subtitle);

    attachBoardModalMinimizer({
        overlay: overlay,
        controlsHost: header,
        label: 'Transformation',
        restoreId: 'transform-picker-restore-pill'
    });
    modal.appendChild(header);

    var fan = document.createElement('div');
    fan.className = 'tutor-modal-cards transform-picker-cards';
    var selectedTarget = null;
    var selectedTile = null;
    var accept = document.createElement('button');
    accept.className = 'tutor-accept-button';
    accept.textContent = 'Accept';
    accept.disabled = true;

    (options || []).forEach(function(opt) {
        var targetNid = _transformTargetNumericId(opt.target);
        var targetCard = targetNid == null ? null : cardDefs[targetNid];
        if (!targetCard || typeof renderDeckBuilderCard !== 'function') return;
        var cost = opt.mana_cost;
        if (cost == null) cost = targetCard.mana_cost;
        var isLegal = !!legalTargets[opt.target];
        var tile = document.createElement('div');
        tile.className = 'tutor-modal-card transform-picker-card';
        tile.innerHTML = renderDeckBuilderCard(targetNid, undefined);
        tile.setAttribute('data-transform-target', opt.target);
        tile.setAttribute('aria-disabled', isLegal ? 'false' : 'true');
        tile.tabIndex = 0;
        if (!isLegal) tile.classList.add('transform-picker-card-disabled');

        var costPill = document.createElement('div');
        costPill.className = 'transform-cost-pill';
        costPill.textContent = 'TRANSFORM · ' + cost + ' MANA';
        tile.appendChild(costPill);
        function inspectTransformCard() {
            try { showGameTooltip(targetNid, tile, null, { force: true }); } catch (e) { /* defensive */ }
        }
        tile.addEventListener('mouseenter', inspectTransformCard);
        tile.addEventListener('focus', inspectTransformCard);
        if (isLegal) {
            tile.addEventListener('click', function(e) {
                e.stopPropagation();
                if (selectedTile) selectedTile.classList.remove('tutor-card-selected');
                if (selectedTile === tile) {
                    selectedTile = null;
                    selectedTarget = null;
                } else {
                    selectedTile = tile;
                    selectedTarget = opt.target;
                    tile.classList.add('tutor-card-selected');
                    try { showGameTooltip(targetNid, tile, null, { force: true }); } catch (e2) { /* defensive */ }
                }
                accept.disabled = selectedTarget == null;
            });
        } else {
            tile.title = 'Unavailable with your current mana and Action Points';
            tile.addEventListener('click', function(e) {
                e.stopPropagation();
                inspectTransformCard();
            });
        }
        fan.appendChild(tile);
    });
    if (!fan.children.length) {
        var empty = document.createElement('div');
        empty.className = 'tutor-modal-empty';
        empty.textContent = 'No transformation cards are available.';
        fan.appendChild(empty);
    }
    modal.appendChild(fan);

    var footer = document.createElement('div');
    footer.className = 'tutor-modal-footer';
    var cancel = document.createElement('button');
    cancel.className = 'tutor-skip-button';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', function(e) {
        e.stopPropagation();
        closeTransformPicker();
        clearSelection();
        highlightBoard();
        updateHandHighlights();
    });
    accept.addEventListener('click', function(e) {
        e.stopPropagation();
        if (selectedTarget == null) return;
        submitAction({
            action_type: 7,
            minion_id: minion.instance_id,
            transform_target: selectedTarget,
        }, true);
    });
    footer.appendChild(cancel);
    footer.appendChild(accept);
    modal.appendChild(footer);
    overlay.appendChild(modal);
    overlay.addEventListener('click', function(e) { e.stopPropagation(); });
    var host = typeof _stageMount === 'function'
        ? _stageMount()
        : (document.querySelector('.screen.active .game-layout') || document.body);
    host.appendChild(overlay);
}

function closeTransformPicker() {
    var overlay = document.getElementById('transform-picker-overlay');
    if (overlay) {
        disposeBoardModalMinimizer(overlay);
        overlay.remove();
    }
}

// Discard-cost picker — collects one or more hand-index picks (based on
// the played card's discard_cost_count) then submits the matching PLAY_CARD
// action. Multi-pick cards re-render the grid after each click, disabling
// already-picked cards; submission fires when pick count reaches the
// required discard count.
function showSacrificePicker(handIdx, deployPos, targetPos, sacChoices) {
    hideSacrificePicker();
    // Sandbox god-view has no seat (myPlayerIdx null) — the paying hand is
    // the active player's.
    var _pickerSeat = (typeof myPlayerIdx === 'number')
        ? myPlayerIdx : (gameState.active_player_idx | 0);
    var myPlayer = gameState.players[_pickerSeat];
    var playedCardId = myPlayer.hand[handIdx];
    var playedDef = cardDefs[playedCardId];
    // Alternate discard cost (Dark Wyrm, user 2026-07-11): the discard is
    // a CHOICE — pay mana instead. isAltCost adds a Pay-Mana button below
    // when the mana mode is also legal.
    var isAltCost = !!(playedDef && playedDef.alt_cost_discard);
    var discardCount = isAltCost
        ? playedDef.alt_cost_discard
        : ((playedDef && playedDef.discard_cost_count) || 1);
    var manaModeAction = null;
    if (isAltCost) {
        for (var mi2 = 0; mi2 < legalActions.length; mi2++) {
            var la2 = legalActions[mi2];
            if (la2.action_type !== 0 || la2.card_index !== handIdx) continue;
            if (deployPos) {
                if (!la2.position || la2.position[0] !== deployPos[0] || la2.position[1] !== deployPos[1]) continue;
            } else if (la2.position) continue;
            if (targetPos) {
                if (!la2.target_pos || la2.target_pos[0] !== targetPos[0] || la2.target_pos[1] !== targetPos[1]) continue;
            } else if (la2.target_pos) continue;
            var _ind2 = la2.discard_card_indices || (la2.discard_card_index != null ? [la2.discard_card_index] : []);
            if (_ind2.length === 0) { manaModeAction = la2; break; }
        }
    }
    var picks = [];

    // Class names mirror the "discard" semantics (cards go to Exhaust,
    // not the grave — it's not a sacrifice). CSS continues to provide
    // back-compat selectors for .sacrifice-picker-* while new markup
    // uses .discard-picker-* so the DOM reads correctly.
    var modal = document.createElement('div');
    modal.id = 'sacrifice-picker';
    modal.className = 'discard-picker-overlay sacrifice-picker-overlay';
    var inner = document.createElement('div');
    inner.className = 'discard-picker-modal sacrifice-picker-modal';
    var title = document.createElement('div');
    title.className = 'discard-picker-title sacrifice-picker-title';
    var progress = document.createElement('div');
    progress.className = 'discard-picker-progress sacrifice-picker-progress';
    inner.appendChild(title);
    inner.appendChild(progress);
    attachBoardModalMinimizer({
        overlay: modal,
        controlsHost: inner,
        label: 'Discard choice',
        restoreId: 'discard-picker-restore-pill'
    });
    var row = document.createElement('div');
    row.className = 'discard-picker-row sacrifice-picker-row';
    inner.appendChild(row);

    function refresh() {
        title.textContent = isAltCost
            ? ('Discard ' + discardCount + ' to summon for 0'
               + (manaModeAction ? ' — or pay ' + playedDef.mana_cost + ' mana' : ''))
            : (discardCount > 1
                ? 'Pick ' + discardCount + ' cards to Discard'
                : 'Pick a card to Discard');
        progress.textContent = discardCount > 1
            ? (picks.length + ' / ' + discardCount + ' picked')
            : '';
        row.innerHTML = '';
        sacChoices.forEach(function(sacIdx) {
            var cardId = myPlayer.hand[sacIdx];
            var c = cardDefs[cardId];
            if (!c) return;
            var btn = document.createElement('button');
            btn.className = 'discard-picker-card sacrifice-picker-card';
            var picked = picks.indexOf(sacIdx) !== -1;
            if (picked) btn.className += ' picked';
            // Render the full card frame — same look as the tutor modal —
            // instead of a tiny name/tribe button. The badge stays on
            // top-right when picked.
            btn.innerHTML = renderCardFrame(c, {
                context: 'tooltip',
                numericId: cardId,
                interactive: false,
                showReactDeploy: false,
            }) + (picked ? '<div class="sp-badge">✓</div>' : '');
            btn.addEventListener('click', function() {
                if (picked) {
                    // second click unselects (tutor-style, user 2026-07-08)
                    picks = picks.filter(function(i) { return i !== sacIdx; });
                    refresh();
                    return;
                }
                if (discardCount === 1 && picks.length === 1) {
                    picks.length = 0;   // single-pick: switch selection
                }
                if (picks.length >= discardCount) return;   // cap reached
                picks.push(sacIdx);
                try { showGameTooltip(cardId, btn, null, { force: true }); } catch (e2) { /* defensive */ }
                refresh();
            });
            row.appendChild(btn);
        });
        if (acceptBtn) {
            acceptBtn.disabled = picks.length !== discardCount;
            acceptBtn.textContent = (discardCount > 1 && picks.length)
                ? 'Accept (' + picks.length + '/' + discardCount + ')'
                : 'Accept';
        }
    }

    // Accept submits the collected picks (tutor-style; no auto-submit).
    function acceptPicks() {
        if (picks.length !== discardCount) return;
        var sortedPicks = picks.slice().sort(function(a, b) { return a - b; });
        var matched = null;
        for (var mi = 0; mi < legalActions.length; mi++) {
            var la = legalActions[mi];
            if (la.action_type !== 0 || la.card_index !== handIdx) continue;
            if (deployPos) {
            if (!la.position || la.position[0] !== deployPos[0] || la.position[1] !== deployPos[1]) continue;
            } else if (la.position) continue;
            if (targetPos) {
                if (!la.target_pos || la.target_pos[0] !== targetPos[0] || la.target_pos[1] !== targetPos[1]) continue;
            } else if (la.target_pos) continue;
            var laIndices = la.discard_card_indices || (la.discard_card_index != null ? [la.discard_card_index] : []);
            if (laIndices.length !== sortedPicks.length) continue;
            var sorted = laIndices.slice().sort(function(a, b) { return a - b; });
            var same = sorted.every(function(v, i) { return v === sortedPicks[i]; });
            if (same) { matched = la; break; }
        }
        var payload;
        if (matched) {
            payload = _playCardPayload(matched);
        } else {
            payload = { action_type: 0, card_index: handIdx };
            if (deployPos) payload.position = deployPos;
            if (targetPos) payload.target_pos = targetPos;
            payload.discard_card_index = sortedPicks[0];
            payload.discard_card_indices = sortedPicks;
        }
        hideSacrificePicker();
        submitAction(payload, true);
    }

    var acceptBtn = document.createElement('button');
    acceptBtn.className = 'tutor-accept-button';
    acceptBtn.textContent = 'Accept';
    acceptBtn.disabled = true;
    acceptBtn.addEventListener('click', function() { acceptPicks(); });

    var cancel = document.createElement('button');
    cancel.className = 'btn btn-secondary';
    cancel.textContent = 'Cancel';
    cancel.addEventListener('click', function() {
        hideSacrificePicker();
        clearSelection();
        highlightBoard();
        updateHandHighlights();
    });
    var footer = document.createElement('div');
    footer.className = 'discard-picker-footer';
    footer.appendChild(acceptBtn);
    // Alternate cost: offer the mana mode as an explicit button.
    if (manaModeAction) {
        var payBtn = document.createElement('button');
        payBtn.className = 'btn btn-secondary';
        payBtn.textContent = 'Pay ' + playedDef.mana_cost + ' Mana';
        payBtn.title = 'Summon for mana instead of discarding';
        payBtn.addEventListener('click', function() {
            hideSacrificePicker();
            submitAction(_playCardPayload(manaModeAction), true);
        });
        footer.appendChild(payBtn);
    }
    footer.appendChild(cancel);
    inner.appendChild(footer);
    refresh();
    modal.appendChild(inner);
    _stageMount().appendChild(modal);
}

function hideSacrificePicker() {
    var existing = document.getElementById('sacrifice-picker');
    if (existing) {
        disposeBoardModalMinimizer(existing);
        existing.remove();
    }
}

function getMinionAt(row, col) {
    if (!gameState || !gameState.minions) return null;
    for (var i = 0; i < gameState.minions.length; i++) {
        var m = gameState.minions[i];
        if (m.position[0] === row && m.position[1] === col) return m;
    }
    return null;
}

// Phase 14.1 / 14.7-08: post-move attack-pick mode sync. Reads server-provided
// pending_post_move_attacker_id and sets interactionMode + decline button.
//
// 14.7-08 refinement: the pending flag now survives the post-move REACT
// window (two independent react windows per melee chain per spec v2 §4.1).
// Only surface the picker UI when we are BETWEEN the two windows — i.e.
// phase === ACTION. During the post-move REACT window the caster is
// waiting on the opponent's react decision, and showing the picker is
// premature (and the server would reject ATTACK/DECLINE anyway).
function syncPendingPostMoveAttackUI() {
    var pendingId = gameState && gameState.pending_post_move_attacker_id;
    if (pendingId == null) {
        // Gate cleared — the submitted pick landed; release the guard.
        window.__postMoveSubmitted = false;
    } else if (window.__postMoveSubmitted) {
        // A pick was already submitted for this gate — don't re-arm off
        // the stale frame (user 2026-07-11).
        hideDeclinePostMoveAttackButton();
        return;
    }
    // PHASE_ACTION = 0 (see PHASE_DISPLAY at top of file).
    var inActionPhase = gameState && gameState.phase === 0;
    if (pendingId != null && inActionPhase) {
        // Find the attacker minion to determine ownership; only the owner
        // (the player whose turn it is) sees the picker UI.
        var attacker = null;
        (gameState.minions || []).forEach(function(m) {
            if (m.instance_id === pendingId) attacker = m;
        });
        if (attacker && attacker.owner === myPlayerIdx) {
            interactionMode = 'post_move_attack_pick';
            selectedMinionId = pendingId;
            showDeclinePostMoveAttackButton();
            return;
        }
    }
    // Not pending, or mid-REACT, or not my pending — hide the button.
    hideDeclinePostMoveAttackButton();
}

function showDeclinePostMoveAttackButton() {
    if (document.getElementById('decline-post-move-attack-btn')) return;
    var btn = document.createElement('button');
    btn.id = 'decline-post-move-attack-btn';
    btn.className = 'btn btn-action btn-decline-attack';
    btn.textContent = 'Decline Attack';
    btn.title = 'End the action without attacking';
    btn.addEventListener('click', function(e) {
        e.stopPropagation();
        window.__postMoveSubmitted = true;
        // ActionType.DECLINE_POST_MOVE_ATTACK = 8 (Phase 14.1)
        submitAction({ action_type: 8 });
        interactionMode = null;
        hideDeclinePostMoveAttackButton();
    });
    var bar = document.getElementById('hand-action-bar');
    (bar || document.body).appendChild(btn);
}

function hideDeclinePostMoveAttackButton() {
    var existing = document.getElementById('decline-post-move-attack-btn');
    if (existing) existing.remove();
}
