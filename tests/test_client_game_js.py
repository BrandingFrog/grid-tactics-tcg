"""Regression tests for browser-client (game.js) event-queue fixes.

There is no JavaScript test suite in this repo, so these tests extract the
patched functions from src/grid_tactics/server/static/game.js by name
(brace-balanced), run them under Node.js with stubbed browser globals, and
assert on observable behavior. Skipped automatically when node is missing.

Covers:
  1. drainEventQueue no longer deadlocks on pending_modal_opened: the
     pending_modal_resolved event queued behind the gate is drained, the
     safety deadline is enforced, and the stashed final_state is committed
     once so the modal UI can open.
  2. _commitFinalStateSnapshot force-clears leaked spell-stage chain
     entries when the server shows no open react window (defensive
     recovery for server paths that close windows without emitting
     react_window_closed).
  3. playMinionSummoned incrementally commits the summoned minion into the
     live state so the summon animation renders the actual minion.
  4. commitEventToDom normalizes phase NAMES to wire ints (never commits a
     string into gameState.phase).
  5. runQueue survives a throwing animation branch (animRunning never
     latches true; the queue keeps flowing).
  6. playReactWindowClosed accounts for still-queued slam-ins when pacing
     the LIFO resolve duration.
  7. playCardDrawn appends the drawn card to the live hand and targets the
     real new slot (not the pre-draw last hand card).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "grid_tactics" / "server" / "static"


def _load_client_js() -> str:
    """Client JS source. Modular since 2026-07-06: js/NN-*.js sorted by
    filename (the NN- prefix is the load order) concatenates to exactly the
    former monolithic game.js. Falls back to game.js if js/ is absent."""
    js_dir = STATIC_DIR / "js"
    if js_dir.is_dir():
        return "".join(
            p.read_text(encoding="utf-8") for p in sorted(js_dir.glob("*.js"))
        )
    return (STATIC_DIR / "game.js").read_text(encoding="utf-8")

NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node executable not available")

_SRC = _load_client_js()


def _balanced_block(start_idx: int) -> str:
    """Return source from start_idx through the matching close brace of the
    first '{' found at/after start_idx."""
    brace = _SRC.index("{", start_idx)
    depth = 0
    j = brace
    while j < len(_SRC):
        ch = _SRC[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return _SRC[start_idx : j + 1]
        j += 1
    raise AssertionError("unbalanced braces from index %d" % start_idx)


def extract_function(name: str) -> str:
    marker = "function " + name + "("
    idx = _SRC.index(marker)
    return _balanced_block(idx)


def extract_var_object(name: str) -> str:
    marker = "var " + name + " = {"
    idx = _SRC.index(marker)
    return _balanced_block(idx) + ";"


def run_js(tmp_path: Path, script: str) -> dict:
    path = tmp_path / "harness.js"
    path.write_text(script, encoding="utf-8")
    res = subprocess.run(
        [NODE, str(path)], capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, (
        "node harness failed\nSTDOUT:\n%s\nSTDERR:\n%s" % (res.stdout, res.stderr)
    )
    return json.loads(res.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# Fix 1: pending-modal deadlock in drainEventQueue
# ---------------------------------------------------------------------------

_DRAIN_STUBS = """
var processed = [];
var commitCalls = 0;
var committedMarkers = [];
var eventRunning = false;
var _drainFinalApplied = false;
var _clientLifecycleEpoch = 0;
var _activeEventBatch = null;
var window = { __lastFinalState: null };
var document = {
    getElementById: function() { return null; },
};
var slotState = {
    spellStageChain: [],
    pendingModalKind: null,
    pendingModalDeadline: 0,
    lastOriginator: null,
};
var eventQueue = [];
function _commitFinalStateSnapshot(fs) {
    commitCalls++;
    if (fs && fs.marker) committedMarkers.push(fs.marker);
}
function _activateEventBatch(batch) { _activeEventBatch = batch; return true; }
function _commitEventBatch(batch) {
    if (batch && !batch.committed) {
        batch.committed = true;
        _commitFinalStateSnapshot(batch.finalState);
    } else if (!batch && !_drainFinalApplied && window.__lastFinalState) {
        _drainFinalApplied = true;
        _commitFinalStateSnapshot(window.__lastFinalState);
    }
}
function commitEventToDom(ev) {}
function playEvent(ev, done) {
    processed.push(ev.type);
    if (ev.type === 'pending_modal_resolved') {
        slotState.pendingModalKind = null;
        slotState.pendingModalDeadline = 0;
    }
    done();
}
"""


def test_drain_queue_lets_pending_modal_resolved_through(tmp_path):
    """The pending_modal_resolved event travels through the same queue the
    modal gate blocks; the drain must still dequeue it (no circular wait)."""
    script = (
        _DRAIN_STUBS
        + extract_function("drainEventQueue")
        + """
slotState.pendingModalKind = 'tutor_select';
slotState.pendingModalDeadline = Date.now() + 300000;
eventQueue.push({type: 'pending_modal_resolved', seq: 1, payload: {}});
eventQueue.push({type: 'turn_flipped', seq: 2, payload: {}});
drainEventQueue();
console.log(JSON.stringify({
    processed: processed,
    gate: slotState.pendingModalKind,
    remaining: eventQueue.length,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["processed"] == ["pending_modal_resolved", "turn_flipped"], (
        "queued pending_modal_resolved must be drained through the gate; got %r"
        % out
    )
    assert out["gate"] is None
    assert out["remaining"] == 0


def test_drain_queue_commits_final_state_while_modal_gated(tmp_path):
    """While waiting for user input, the stashed final_state must be
    committed ONCE so the pending_* modal UI can actually open."""
    script = (
        _DRAIN_STUBS
        + extract_function("drainEventQueue")
        + """
slotState.pendingModalKind = 'tutor_select';
slotState.pendingModalDeadline = Date.now() + 300000;
window.__lastFinalState = { phase: 0, react_stack: [] };
eventQueue.push({type: 'turn_flipped', seq: 5, payload: {}});
drainEventQueue();
drainEventQueue();  // idempotence: guard must keep this at one commit
console.log(JSON.stringify({
    processed: processed,
    commits: commitCalls,
    gate: slotState.pendingModalKind,
    remaining: eventQueue.length,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["commits"] == 1, "final_state must be committed exactly once"
    assert out["processed"] == [], "gated events must not play before resolution"
    assert out["gate"] == "tutor_select"
    assert out["remaining"] == 1


def test_drain_queue_enforces_modal_deadline(tmp_path):
    """The safety deadline (previously dead code) must clear the gate."""
    script = (
        _DRAIN_STUBS
        + extract_function("drainEventQueue")
        + """
slotState.pendingModalKind = 'trigger_pick';
slotState.pendingModalDeadline = Date.now() - 1000;  // already passed
eventQueue.push({type: 'turn_flipped', seq: 9, payload: {}});
drainEventQueue();
console.log(JSON.stringify({
    processed: processed,
    gate: slotState.pendingModalKind,
    remaining: eventQueue.length,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["gate"] is None
    assert out["processed"] == ["turn_flipped"]
    assert out["remaining"] == 0


def test_multi_pick_modal_commits_latest_parked_batch(tmp_path):
    """Ratmobile's first pick keeps the tutor gate open. The next server
    frame must refresh the modal from its new final_state even though the
    frame's card-drawn event remains parked behind that same gate."""
    script = (
        _DRAIN_STUBS
        + extract_function("drainEventQueue")
        + """
slotState.pendingModalKind = 'tutor_select';
slotState.pendingModalDeadline = Date.now() + 300000;
var originalBatch = {
    committed: true,
    finalState: {marker: 'before-first-pick'}
};
var secondPickBatch = {
    committed: false,
    finalState: {
        marker: 'after-first-pick',
        pending_tutor_remaining: 1,
        pending_tutor_matches: [{match_idx: 0, card_numeric_id: 10}]
    }
};
_activeEventBatch = originalBatch;
eventQueue.push({
    type: 'card_drawn', seq: 6, payload: {},
    _clientBatch: secondPickBatch
});
drainEventQueue();
console.log(JSON.stringify({
    processed: processed,
    committed: secondPickBatch.committed,
    markers: committedMarkers,
    gate: slotState.pendingModalKind,
    remaining: eventQueue.length
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "processed": [],
        "committed": True,
        "markers": ["after-first-pick"],
        "gate": "tutor_select",
        "remaining": 1,
    }


def test_drain_queue_applies_stashed_game_over_when_terminal_event_is_missing(tmp_path):
    """The separate socket frame is a terminal fallback, not dead data.

    If the queued EVT_GAME_OVER beat is skipped or deduplicated, finishing the
    animation queue must still display the result and consume the payload once.
    """
    script = (
        _DRAIN_STUBS
        + """
var gameOverCalls = 0;
function _applyGameOver(data) {
    gameOverCalls++;
    processed.push(data.reason);
}
"""
        + extract_function("drainEventQueue")
        + """
window.__pendingGameOverData = { reason: 'fatigue' };
drainEventQueue();
drainEventQueue();
console.log(JSON.stringify({
    calls: gameOverCalls,
    processed: processed,
    pending: window.__pendingGameOverData || null,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["calls"] == 1
    assert out["processed"] == ["fatigue"]
    assert out["pending"] is None


def test_queue_reset_drops_terminal_payload_and_idempotence_guard(tmp_path):
    script = (
        """
var eventQueue = [{ type: 'game_over' }];
var eventRunning = true;
var lastSeenSeq = 77;
var _drainFinalApplied = true;
var _gameOverApplied = true;
var _clientLifecycleEpoch = 0;
var _activeEventBatch = {};
var animQueue = [{}];
var animRunning = true;
var window = { __pendingGameOverData: { winner: 1 } };
var slotState = {
    spellStageChain: [{}], pendingModalKind: 'tutor_select',
    pendingModalDeadline: 999, lastOriginator: {}, pendingStageOriginator: {},
    prevDispatchedEvent: {}, lastDispatchedEvent: {}, deferredStageGraves: []
};
var resetCalls = 0;
var logClears = 0;
function _resetSpellStageHard() { resetCalls++; }
function clearGameLog() { logClears++; }
function _clearCardTransfers() {}
function _removeAnimationArtifacts() {}
"""
        + extract_function("resetEventQueue")
        + """
resetEventQueue();
console.log(JSON.stringify({
    queue: eventQueue.length,
    pending: window.__pendingGameOverData || null,
    applied: _gameOverApplied,
    epoch: _clientLifecycleEpoch,
    animQueue: animQueue.length,
    animRunning: animRunning,
    finalState: window.__lastFinalState,
    resetCalls: resetCalls,
    logClears: logClears
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out == {
        "queue": 0,
        "pending": None,
        "applied": False,
        "epoch": 1,
        "animQueue": 0,
        "animRunning": False,
        "finalState": None,
        "resetCalls": 1,
        "logClears": 1,
    }


# ---------------------------------------------------------------------------
# Fix 2: spell-stage chain leak recovery in _commitFinalStateSnapshot
# ---------------------------------------------------------------------------

_COMMIT_STUBS = """
var sandboxMode = false;
var gameState = null;
var sandboxState = null;
var myPlayerIdx = 0;
var legalActions = [];
var resolveKicks = 0;
var window = { __lastLegalActions: [] };
var slotState = { spellStageChain: [], deferredStageGraves: [] };
var _spellStage = { chain: [], resolving: false };
var _spellStageBusy = false;
var _spellStageQueue = [];
function _spellStageOnReactClosed() { resolveKicks++; }
function _maskDeferredStageGraves() {}
"""


def test_final_commit_clears_leaked_spell_stage_chain(tmp_path):
    script = (
        _COMMIT_STUBS
        + extract_function("_commitFinalStateSnapshot")
        + """
slotState.spellStageChain = [{}, {}];
_spellStage.chain = [{}];
_commitFinalStateSnapshot({ phase: 0, react_stack: [] });
console.log(JSON.stringify({
    chainLen: slotState.spellStageChain.length,
    resolveKicks: resolveKicks,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["chainLen"] == 0, (
        "leaked chain entries must be cleared when server shows no react window"
    )
    assert out["resolveKicks"] == 1, "stranded visual stage must be resolved"


def test_final_commit_keeps_chain_during_real_react_window(tmp_path):
    script = (
        _COMMIT_STUBS
        + extract_function("_commitFinalStateSnapshot")
        + """
slotState.spellStageChain = [{}];
_spellStage.chain = [{}];
_commitFinalStateSnapshot({ phase: 1, react_stack: [{player_idx: 1}] });
console.log(JSON.stringify({
    chainLen: slotState.spellStageChain.length,
    resolveKicks: resolveKicks,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["chainLen"] == 1, "legit open react window must not be cleared"
    assert out["resolveKicks"] == 0


# ---------------------------------------------------------------------------
# Fix 3: playMinionSummoned commits the minion before animating
# ---------------------------------------------------------------------------

_SUMMON_STUBS = """
var sandboxMode = false;
var sandboxState = null;
var gameState = { minions: [] };
var legalActions = [];
var cardDefs = { 5: { health: 4, attack: 2 } };
var jobs = [];
var window = { __lastFinalState: null };
function enqueueAnimation(job) { jobs.push(job); }
function _evDurationOr(ev, fb) { return fb; }
function animSpeed() { return 1; }
var isSpectator = false;
// Zero-delay callbacks (the non-spectator reveal wrapper) run inline;
// real pacing timers stay suppressed.
var setTimeout = function(fn, d) { if (!d) fn(); };
"""


def test_summon_commits_minion_into_live_state(tmp_path):
    script = (
        _SUMMON_STUBS
        + extract_function("playMinionSummoned")
        + """
window.__lastFinalState = { minions: [
    { instance_id: 7, card_numeric_id: 3, owner: 1, position: [4, 2],
      current_health: 9, attack_bonus: 0, is_burning: false }
]};
var ev = { payload: { instance_id: 7, card_numeric_id: 3, owner_idx: 1,
                      position: [4, 2] } };
playMinionSummoned(ev, function() {});
playMinionSummoned(ev, function() {});  // replay must not duplicate
console.log(JSON.stringify({
    count: gameState.minions.length,
    minion: gameState.minions[0],
    jobStateHasMinion: jobs[0].stateAfter.minions.length,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["count"] == 1, "minion must be committed exactly once"
    assert out["minion"]["instance_id"] == 7
    assert out["minion"]["position"] == [4, 2]
    assert out["jobStateHasMinion"] == 1, (
        "the summon job's stateAfter must already contain the minion so the "
        "scale-in renders it (was: empty cell during the animation)"
    )


def test_summon_falls_back_to_card_def_when_final_state_missing(tmp_path):
    script = (
        _SUMMON_STUBS
        + extract_function("playMinionSummoned")
        + """
window.__lastFinalState = null;
playMinionSummoned({ payload: { instance_id: 11, card_numeric_id: 5,
                                owner_idx: 0, position: [0, 3] } },
                   function() {});
console.log(JSON.stringify({
    count: gameState.minions.length,
    minion: gameState.minions[0],
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["count"] == 1
    assert out["minion"]["current_health"] == 4
    assert out["minion"]["owner"] == 0


# ---------------------------------------------------------------------------
# Fix 4: phase name -> int normalization in commitEventToDom
# ---------------------------------------------------------------------------

def test_commit_event_normalizes_phase_names_to_ints(tmp_path):
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var gameState = { phase: 0, react_return_phase: null, players: [], minions: [] };
var document = { getElementById: function() { return null; } };
"""
        + extract_var_object("_PHASE_NAME_TO_INT")
        + extract_function("_normalizePhaseValue")
        + extract_function("_commitMinionHp")
        + extract_function("_commitMinionPos")
        + extract_function("_commitPlayerField")
        + extract_function("commitEventToDom")
        + """
commitEventToDom({ type: 'phase_changed', payload: { prev: 'ACTION', 'new': 'REACT' } });
var afterReact = gameState.phase;
var afterReactType = typeof gameState.phase;
commitEventToDom({ type: 'phase_changed', payload: { prev: 'REACT', 'new': 'END_OF_TURN' } });
var afterEnd = gameState.phase;
commitEventToDom({ type: 'phase_changed', payload: { prev: 'END_OF_TURN', 'new': 'BOGUS' } });
var afterBogus = gameState.phase;
commitEventToDom({ type: 'phase_changed', payload: { prev: 'X', 'new': 2 } });
var afterInt = gameState.phase;
console.log(JSON.stringify({
    afterReact: afterReact, afterReactType: afterReactType,
    afterEnd: afterEnd, afterBogus: afterBogus, afterInt: afterInt,
    mapped: [_normalizePhaseValue('ACTION'), _normalizePhaseValue('REACT'),
             _normalizePhaseValue('START_OF_TURN'), _normalizePhaseValue('END_OF_TURN')],
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["afterReact"] == 1 and out["afterReactType"] == "number", (
        "phase_changed must commit the wire INT, never the name string"
    )
    assert out["afterEnd"] == 3
    assert out["afterBogus"] == 3, "unmapped names must not clobber phase"
    assert out["afterInt"] == 2, "numeric payloads still commit as-is"
    assert out["mapped"] == [0, 1, 2, 3]


# ---------------------------------------------------------------------------
# Fix 5: runQueue exception guard
# ---------------------------------------------------------------------------

def test_run_queue_survives_throwing_animation(tmp_path):
    script = (
        """
var animRunning = false;
var animQueue = [];
var _clientLifecycleEpoch = 0;
var applied = [];
var onDoneCalls = [];
function applyStateFrame(f, l) { applied.push(f); }
function playAnimation(job, done) {
    if (job.type === 'bad') throw new Error('boom');
    done();
}
"""
        + extract_function("runQueue")
        + """
animQueue.push({ type: 'bad', stateAfter: 's1',
                 onDone: function() { onDoneCalls.push('bad'); } });
animQueue.push({ type: 'ok', stateAfter: 's2',
                 onDone: function() { onDoneCalls.push('ok'); } });
runQueue();
console.log(JSON.stringify({
    animRunning: animRunning,
    queueLen: animQueue.length,
    onDone: onDoneCalls,
    applied: applied,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["animRunning"] is False, (
        "a throwing branch must not latch animRunning=true forever"
    )
    assert out["queueLen"] == 0, "queue must keep flowing past the throw"
    assert out["onDone"] == ["bad", "ok"], "per-job onDone must still fire"
    assert out["applied"] == ["s1", "s2"]


# ---------------------------------------------------------------------------
# Fix 6: playReactWindowClosed accounts for queued slam-ins
# ---------------------------------------------------------------------------

def test_react_window_closed_paces_for_queued_slam_ins(tmp_path):
    script = (
        """
var delays = [];
var setTimeout = function(fn, d) { delays.push(d); };
var slotState = { spellStageChain: [{}] };
var _spellStage = { chain: [{}, {}], resolving: false };
var _spellStageQueue = [{}, {}];
var _spellStageBusy = true;
var SPELL_STAGE_PER_CARD_MS = 1500;
function isSpellStageAnimating() { return true; }
function _spellStageOnReactClosed() {}
function _evDurationOr(ev, fb) { return fb; }
function animSpeed() { return 1; }
"""
        + extract_function("playReactWindowClosed")
        + """
playReactWindowClosed({ payload: {} }, function() {});
console.log(JSON.stringify({ delays: delays }));
"""
    )
    out = run_js(tmp_path, script)
    # pendingIn = 2 queued + 1 busy = 3; totalCards = 2 chain + 2 queued = 4.
    # resolveDur = 3*1500 + 700 + 4*550 + 250 = 7650.
    assert 7650 in out["delays"], (
        "done() pacing must include the deferred-start (queued slam-ins) and "
        "queued cards; got delays=%r (old buggy formula gave 2050)" % out["delays"]
    )
    assert 2050 not in out["delays"]


# ---------------------------------------------------------------------------
# Fix 8: lobby 'error' frames re-enable the ready button
# ---------------------------------------------------------------------------
# The ready-button click handler disables the button and sets 'Waiting...'
# BEFORE emitting 'ready'. Since handle_ready now rejects invalid decks with
# an 'error' frame, onError must restore the button or the player can never
# ready up again without a page refresh.

_ON_ERROR_STUBS = """
var statusMsgs = [];
function showLobbyStatus(msg, type) { statusMsgs.push([msg, type]); }
var lobbyActive = true;
var btnReady = {
    disabled: true,
    textContent: 'Waiting...',
    innerHTML: 'Waiting...',
    dataset: { readyLabelHtml: '<span class="hud-btn-label">READY // DEPLOY</span>' },
};
var document = {
    getElementById: function(id) {
        if (id === 'screen-lobby') {
            return { classList: { contains: function() { return lobbyActive; } } };
        }
        if (id === 'btn-ready') { return btnReady; }
        return null;
    },
};
"""


def test_on_error_reenables_ready_button_in_lobby(tmp_path):
    """A server deck rejection ('error' frame) while on the lobby screen must
    re-enable the disabled ready button and restore its original markup."""
    script = (
        _ON_ERROR_STUBS
        + extract_function("onError")
        + """
onError({msg: 'Invalid deck: must be exactly 40 cards (got 39)'});
console.log(JSON.stringify({
    disabled: btnReady.disabled,
    html: btnReady.innerHTML,
    status: statusMsgs,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["disabled"] is False, (
        "ready button must be re-enabled after a lobby error frame"
    )
    assert "READY // DEPLOY" in out["html"], (
        "original button markup must be restored from dataset stash"
    )
    assert out["status"] and out["status"][0][1] == "error"


def test_on_error_restores_fallback_label_without_stash(tmp_path):
    """If the dataset stash is missing (error before any click stashed it),
    onError still re-enables the button with a plain-text label."""
    script = (
        _ON_ERROR_STUBS
        + extract_function("onError")
        + """
btnReady.dataset = {};
onError({msg: 'Invalid deck: expected a list of card ids'});
console.log(JSON.stringify({
    disabled: btnReady.disabled,
    text: btnReady.textContent,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["disabled"] is False
    assert out["text"] == "Ready"


def test_on_error_leaves_ready_button_alone_outside_lobby(tmp_path):
    """In-game error frames (lobby screen inactive) must not touch the
    ready button state."""
    script = (
        _ON_ERROR_STUBS
        + extract_function("onError")
        + """
lobbyActive = false;
onError({msg: 'Not your turn'});
console.log(JSON.stringify({
    disabled: btnReady.disabled,
    html: btnReady.innerHTML,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["disabled"] is True
    assert out["html"] == "Waiting..."


def test_on_error_restores_actions_cleared_while_submit_was_in_flight(tmp_path):
    assert "window.__legalActionsBeforeSubmit = Array.isArray(legalActions)" in _SRC
    script = (
        _ON_ERROR_STUBS
        + extract_function("onError")
        + """
var restored = [{action_type: 1, minion_id: 7, target_pos: [2, 2]}];
var window = {
    __legalActionsBeforeSubmit: restored,
    __conjureDeploySubmitted: true,
    __reviveSubmittedAtRemaining: 2,
    __postMoveSubmitted: true,
};
var legalActions = [];
var highlightCalls = 0;
var handCalls = 0;
function updateHandHighlights() { highlightCalls++; }
function highlightBoard() { highlightCalls++; }
function renderHand() { handCalls++; }
lobbyActive = false;
onError({msg: 'Illegal action', debug_code: 'GT-1234567890'});
console.log(JSON.stringify({
    legalActions: legalActions,
    pending: window.__legalActionsBeforeSubmit,
    highlightCalls: highlightCalls,
    handCalls: handCalls,
    guards: [
        window.__conjureDeploySubmitted,
        window.__reviveSubmittedAtRemaining,
        window.__postMoveSubmitted,
    ],
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["legalActions"] == [
        {"action_type": 1, "minion_id": 7, "target_pos": [2, 2]}
    ]
    assert out["pending"] is None
    assert out["highlightCalls"] == 2
    assert out["handCalls"] == 1
    assert out["guards"] == [False, None, False]


# ---------------------------------------------------------------------------
# Fix 7: playCardDrawn targets the real new hand slot
# ---------------------------------------------------------------------------

def test_each_card_draw_event_reserves_a_distinct_slot_even_when_net_hand_is_smaller(tmp_path):
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var _clientLifecycleEpoch = 0;
var myPlayerIdx = 0;
var gameState = { players: [ { hand: [10, 11, 12] }, { hand: [] } ] };
var window = { __lastFinalState:
    { players: [ { hand: [10, 11, 12, 33, 34] }, { hand: [] } ] } };
var jobs = [];
var renderHandCalls = 0;
var transfers = {};
var transferSeq = 0;
function renderHand() { renderHandCalls++; }
function updateHandHighlights() {}
function enqueueAnimation(job) { jobs.push(job); }
function _evDurationOr(ev, fb) { return fb; }
function animSpeed() { return 1; }
function _retireCardSource() {}
function _newCardTransfer(spec) {
    var id = 't' + (++transferSeq); transfers[id] = spec; return id;
}
function _finishCardTransfer(id) { delete transfers[id]; }
function _rerenderHandOwner() {}
function _cardTransfer(id) { return transfers[id] || null; }
var isSpectator = false;
// Zero-delay callbacks (the non-spectator reveal wrapper) run inline;
// real pacing timers stay suppressed.
var setTimeout = function(fn, d) { if (!d) fn(); };
"""
        + extract_function("playCardDrawn")
        + """
for (var nid = 33; nid <= 36; nid++) {
    playCardDrawn({ payload: {
        player_idx: 0, card_numeric_id: nid,
        source: 'roguelike_event', from_zone: 'deck'
    } }, function() {});
}
console.log(JSON.stringify({
    hand: gameState.players[0].hand,
    slots: jobs.map(function(job) { return job.toSlotIndex; }),
    renderHandCalls: renderHandCalls,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["hand"] == [10, 11, 12, 33, 34, 35, 36]
    assert out["slots"] == [3, 4, 5, 6], (
        "Draw 4 / Exhaust 2 still needs four causal landing reservations"
    )
    assert out["renderHandCalls"] == 4


def test_overlapping_frames_keep_their_own_final_snapshot(tmp_path):
    script = (
        """
var eventQueue = [];
var eventRunning = false;
var lastSeenSeq = -1;
var _eventBatchSerial = 0;
var _clientLifecycleEpoch = 0;
var _activeEventBatch = null;
var _drainFinalApplied = false;
var _gameOverApplied = false;
var callbacks = [];
var dispatched = [];
var commits = [];
var sandboxMode = false;
var window = { __pendingGameOverData: null };
var document = { getElementById: function() { return null; } };
var slotState = {
    pendingModalKind: null, pendingModalDeadline: 0,
    prevDispatchedEvent: null, lastDispatchedEvent: null
};
function hideMinionActionMenu() {}
function clearSelection() {}
function hideActionBarButtons() {}
function logEngineEvent() {}
function commitEventToDom() {}
function _commitFinalStateSnapshot(state) { commits.push(state.marker); }
function playEvent(ev, done) {
    dispatched.push([ev.seq, window.__lastFinalState.marker]);
    callbacks.push(done);
}
"""
        + extract_function("_activateEventBatch")
        + extract_function("_commitEventBatch")
        + extract_function("onEngineEvents")
        + extract_function("drainEventQueue")
        + """
onEngineEvents({
    events: [{type: 'phase_changed', seq: 1, payload: {}}],
    final_state: {marker: 'A'}, legal_actions: [{action_type: 1}]
});
onEngineEvents({
    events: [{type: 'turn_flipped', seq: 2, payload: {}}],
    final_state: {marker: 'B'}, legal_actions: [{action_type: 4}]
});
var whileAIsRunning = window.__lastFinalState.marker;
callbacks.shift()();
var afterA = { commits: commits.slice(), active: window.__lastFinalState.marker };
callbacks.shift()();
console.log(JSON.stringify({
    whileAIsRunning: whileAIsRunning,
    dispatched: dispatched,
    afterA: afterA,
    commits: commits
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "whileAIsRunning": "A",
        "dispatched": [[1, "A"], [2, "B"]],
        "afterA": {"commits": ["A"], "active": "B"},
        "commits": ["A", "B"],
    }


def test_played_duplicate_card_cannot_be_removed_again_by_discard_event(tmp_path):
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var _clientLifecycleEpoch = 0;
var gameState = { players: [{hand: [7, 9, 7], grave: []}, {hand: []}] };
var myPlayerIdx = 0;
var isSpectator = false;
var spectatorGodMode = false;
var _passOfferedBy = null;
var renderCalls = 0;
var transferSeq = 0;
var slotState = {
    lastOriginator: null, pendingStageOriginator: null,
    deferredStageGraves: []
};
var document = { getElementById: function() { return null; } };
function renderHand() { renderCalls++; }
function updatePileButtonCounts() {}
function _newCardTransfer() { return 't' + (++transferSeq); }
function _setPassOffer() {}
function _evDurationOr(ev, fallback) { return fallback; }
var setTimeout = function(fn) { fn(); };
"""
        + extract_function("_rerenderHandOwner")
        + extract_function("_retireCardSource")
        + extract_function("_batchPlayedCardKey")
        + extract_function("_markBatchPlayedCard")
        + extract_function("_consumeBatchPlayedCard")
        + extract_function("_deferStageGraveDestination")
        + extract_function("playCardPlayed")
        + extract_function("playCardDiscarded")
        + """
var batch = {playedCards: {}};
var played = { _clientBatch: batch, payload: {
    owner_idx: 0, card_numeric_id: 7, card_index: 2
} };
var discarded = { _clientBatch: batch, payload: {
    player_idx: 0, card_numeric_id: 7,
    cause: 'played', from_zone: 'stage', destination: 'grave'
} };
var done = 0;
playCardPlayed(played, function() { done++; });
playCardDiscarded(discarded, function() { done++; });
console.log(JSON.stringify({
    hand: gameState.players[0].hand,
    playedRemovedIndex: played.payload._clientSourceIndex,
    fromPlayed: discarded.payload._clientFromPlayed,
    deferred: slotState.deferredStageGraves.length,
    done: done,
    renderCalls: renderCalls
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "hand": [7, 9],
        "playedRemovedIndex": 2,
        "fromPlayed": True,
        "deferred": 1,
        "done": 2,
        "renderCalls": 1,
    }


def test_spell_cast_source_captures_exact_face_up_slot_and_opponent_back(tmp_path):
    script = (
        """
var sandboxMode = false;
var myPlayerIdx = 0;
var isSpectator = false;
var spectatorGodMode = false;
var own = {
    getBoundingClientRect: function() {
        return {left: 11, top: 22, width: 58, height: 58, right: 69, bottom: 80};
    }
};
var backs = [
    {getBoundingClientRect: function() { return {left: 100, top: 5, width: 40, height: 40}; }},
    {getBoundingClientRect: function() { return {left: 144, top: 5, width: 40, height: 40}; }}
];
var ownContainer = {
    querySelector: function(sel) {
        return sel.indexOf('data-owner-idx=\\"0\\"') !== -1
            && sel.indexOf('data-hand-idx=\\"2\\"') !== -1 ? own : null;
    },
    querySelectorAll: function() { return []; }
};
var oppContainer = {
    querySelector: function() { return null; },
    querySelectorAll: function(sel) { return sel === '.opp-hand-card-back' ? backs : []; }
};
var document = {
    getElementById: function(id) {
        if (id === 'hand-container') return ownContainer;
        if (id === 'oppHandRow') return oppContainer;
        return null;
    }
};
"""
        + extract_function("_plainSpellCastRect")
        + extract_function("_captureSpellCastSource")
        + """
var ownRect = _captureSpellCastSource({card_index: 2, card_numeric_id: 7}, 0);
var oppRect = _captureSpellCastSource({card_index: 1, card_numeric_id: 9}, 1);
console.log(JSON.stringify({own: ownRect, opp: oppRect}));
"""
    )
    assert run_js(tmp_path, script) == {
        "own": {"left": 11, "top": 22, "width": 58, "height": 58},
        "opp": {"left": 144, "top": 5, "width": 40, "height": 40},
    }


def test_card_played_preserves_cast_rect_after_hand_source_is_retired(tmp_path):
    script = (
        """
var _clientLifecycleEpoch = 0;
var slotState = { lastOriginator: null, pendingStageOriginator: null };
var retired = false;
function _captureSpellCastSource() {
    return {left: 31, top: 401, width: 59, height: 59};
}
function _retireCardSource() { retired = true; }
function _markBatchPlayedCard() {}
function _evDurationOr(ev, fallback) { return fallback; }
function setTimeout(fn) { fn(); }
"""
        + extract_function("playCardPlayed")
        + """
var done = 0;
playCardPlayed({payload: {
    owner_idx: 0, card_numeric_id: 12, card_index: 3, is_react: false
}}, function() { done++; });
console.log(JSON.stringify({
    retired: retired,
    done: done,
    origin: slotState.lastOriginator
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "retired": True,
        "done": 1,
        "origin": {
            "numericId": 12,
            "playerIdx": 0,
            "targetPos": None,
            "sourceRect": {"left": 31, "top": 401, "width": 59, "height": 59},
            "castKind": "magic",
            "source": "card_played",
        },
    }


def test_spell_stage_cast_queue_keeps_animation_options(tmp_path):
    script = (
        """
var _spellStageQueue = [];
var _spellStageBusy = true;
var _spellStageGeneration = 4;
function _processSpellStageQueue() { throw new Error('must remain queued'); }
"""
        + extract_function("_showSpellStage")
        + """
_showSpellStage(22, 1, {
    castKind: 'react',
    sourceRect: {left: 8, top: 9, width: 10, height: 11}
});
console.log(JSON.stringify(_spellStageQueue[0]));
"""
    )
    assert run_js(tmp_path, script) == {
        "nid": 22,
        "playerIdx": 1,
        "options": {
            "castKind": "react",
            "sourceRect": {"left": 8, "top": 9, "width": 10, "height": 11},
        },
    }


def test_spell_cast_visuals_include_arc_trail_sigil_and_impact():
    css = (STATIC_DIR / "css" / "01-base-tokens.css").read_text(encoding="utf-8")
    assert "--slam-arc" in _SRC
    assert "--slam-sweep" in _SRC
    assert "spell-cast-ribbon" in css
    assert "spell-cast-sigil" in css
    assert "spell-cast-impact-arrow" in css
    assert "prefers-reduced-motion" in css


def test_spell_stage_open_pacing_cannot_overtake_real_time_cast_css():
    opened = extract_function("playReactWindowOpened")
    assert "setTimeout(done, _perCard);" in opened
    assert "_perCard / animSpeed()" not in opened


def test_redacted_grave_transfer_uses_public_source_index(tmp_path):
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var gameState = { players: [{grave: []}, {grave: [7, 8, 7]}] };
var myPlayerIdx = 0;
var isSpectator = false;
var spectatorGodMode = false;
function updatePileButtonCounts() {}
"""
        + extract_function("_rerenderHandOwner")
        + extract_function("_retireCardSource")
        + """
var payload = {
    player_idx: 1, card_numeric_id: null,
    from_zone: 'grave', source_index: 2
};
var removed = _retireCardSource(payload, 1, 'grave');
console.log(JSON.stringify({
    removed: removed,
    grave: gameState.players[1].grave,
    sourceRemoved: payload._clientSourceRemoved
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "removed": 2,
        "grave": [7, 8],
        "sourceRemoved": True,
    }


def test_pile_modal_is_bound_to_live_zone_state():
    show = extract_function("showPileModal")
    refresh = extract_function("refreshOpenPileModal")
    counts = extract_function("updatePileButtonCounts")
    setup = extract_function("setupPileHandlers")
    assert "_openPileModalContext" in show
    assert "gameState" in refresh and "ctx.pileType" in refresh
    assert "refreshOpenPileModal();" in counts
    assert "onRestore: refreshOpenPileModal" in setup


# ---------------------------------------------------------------------------
# Spring Cleaning: batch the hand exhaust before any replacement draw
# ---------------------------------------------------------------------------

def test_spring_cleaning_hand_exhaust_batch_gates_later_draws(tmp_path):
    """The plural hand-exhaust event is one queue beat before any draw.

    The next draw must remain parked until that batch calls ``done``.  A later
    Spring Cleaning overdraw has the same source string but no ``from_zone``
    tag, so it must retain the normal single-card burn treatment.
    """
    script = (
        """
var eventRunning = false;
var _drainFinalApplied = false;
var _clientLifecycleEpoch = 0;
var _activeEventBatch = null;
var committed = [];
var dispatched = [];
var callbacks = [];
var logged = [];
var window = { __lastFinalState: null, __pendingGameOverData: null };
var document = { getElementById: function() { return null; } };
var slotState = {
    pendingModalKind: null,
    pendingModalDeadline: 0,
    lastDispatchedEvent: null,
    prevDispatchedEvent: null
};
var eventQueue = [
    { type: 'card_burned', seq: 1, payload: {
        player_idx: 0, card_numeric_ids: [10, 20], card_count: 2,
        source: 'spring_cleaning',
        destination: 'exhaust', from_zone: 'hand'
    } },
    { type: 'card_drawn', seq: 2, payload: {
        player_idx: 0, card_numeric_id: 30, source: 'spring_cleaning'
    } },
    { type: 'card_burned', seq: 3, payload: {
        player_idx: 0, card_numeric_id: 40, source: 'spring_cleaning',
        destination: 'exhaust'
    } }
];
function logEngineEvent(ev) { logged.push(ev.type); }
function playEvent(ev, done) {
    dispatched.push({ type: ev.type, payload: ev.payload });
    callbacks.push(done);
}
function commitEventToDom(ev) { committed.push(ev.type); }
function _activateEventBatch(batch) { _activeEventBatch = batch; return true; }
function _commitEventBatch(batch) {}
"""
        + extract_function("drainEventQueue")
        + """
drainEventQueue();
var beforeBatchDone = {
    dispatched: dispatched.slice(),
    remaining: eventQueue.length,
    running: eventRunning,
    committed: committed.slice()
};

// Finishing the one batch beat may dispatch the first replacement draw.
callbacks.shift()();
var afterBatchDone = {
    dispatched: dispatched.slice(),
    remaining: eventQueue.length,
    running: eventRunning,
    committed: committed.slice()
};

// Finishing the draw exposes the later, untagged overdraw as a normal burn.
callbacks.shift()();
var afterDrawDone = {
    dispatched: dispatched.slice(),
    remaining: eventQueue.length,
    running: eventRunning,
    committed: committed.slice()
};
console.log(JSON.stringify({
    beforeBatchDone: beforeBatchDone,
    afterBatchDone: afterBatchDone,
    afterDrawDone: afterDrawDone
}));
"""
    )
    out = run_js(tmp_path, script)
    before = out["beforeBatchDone"]
    assert len(before["dispatched"]) == 1
    batch = before["dispatched"][0]
    assert batch["type"] == "card_burned"
    assert batch["payload"]["player_idx"] == 0
    assert batch["payload"]["card_numeric_ids"] == [10, 20]
    assert batch["payload"]["source"] == "spring_cleaning"
    assert batch["payload"]["destination"] == "exhaust"
    assert before["remaining"] == 2
    assert before["running"] is True
    assert before["committed"] == []

    after_batch = out["afterBatchDone"]
    assert [event["type"] for event in after_batch["dispatched"]] == [
        "card_burned",
        "card_drawn",
    ]
    assert after_batch["remaining"] == 1
    assert after_batch["running"] is True
    assert after_batch["committed"] == ["card_burned"]

    after_draw = out["afterDrawDone"]
    assert [event["type"] for event in after_draw["dispatched"]] == [
        "card_burned",
        "card_drawn",
        "card_burned",
    ]
    assert after_draw["dispatched"][-1]["payload"]["card_numeric_id"] == 40
    assert "from_zone" not in after_draw["dispatched"][-1]["payload"]
    assert after_draw["remaining"] == 0
    assert after_draw["running"] is True
    assert after_draw["committed"] == [
        "card_burned",
        "card_drawn",
    ]


def test_spring_cleaning_batch_hides_hand_then_commits_pile_at_finish(tmp_path):
    """All exhausted cards mount together after leaving hand, not pile-first."""
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var myPlayerIdx = 0;
var isSpectator = false;
var activePlayerPreviewIdx = null;
var gameState = {
    players: [
        { hand: [10, 30, 10, 20], exhaust: [5], deck_count: 12 },
        { hand_count: 0, exhaust: [] }
    ]
};
var window = {};
var timeline = [];
var renderedCards = [];
var renderHandCalls = 0;
var pileCountRenders = 0;
var doneCalls = 0;
var now = 0;
var timers = [];

function makeClassList() {
    var names = {};
    return {
        add: function(name) { names[name] = true; },
        remove: function(name) { delete names[name]; },
        contains: function(name) { return !!names[name]; }
    };
}
function makeElement(tag) {
    var el = {
        tagName: tag,
        className: '',
        textContent: '',
        innerHTML: '',
        children: [],
        parentNode: null,
        classList: makeClassList(),
        style: { setProperty: function() {} },
        appendChild: function(child) {
            child.parentNode = el;
            el.children.push(child);
            return child;
        },
        removeChild: function(child) {
            el.children = el.children.filter(function(x) { return x !== child; });
            child.parentNode = null;
        },
        remove: function() { if (el.parentNode) el.parentNode.removeChild(el); },
        setAttribute: function() {},
        querySelector: function() { return null; },
        querySelectorAll: function() { return []; },
        addEventListener: function() {}
    };
    return el;
}
var mount = makeElement('main');
var originalAppend = mount.appendChild;
mount.appendChild = function(child) {
    timeline.push({
        step: 'mount',
        hand: gameState.players[0].hand.slice(),
        exhaust: gameState.players[0].exhaust.slice()
    });
    return originalAppend.call(mount, child);
};
var document = {
    createElement: makeElement,
    body: mount,
    getElementById: function() { return null; }
};
var cardDefs = { 10: { name: 'Ten' }, 20: { name: 'Twenty' } };
function renderCardFrame(def, opts) {
    renderedCards.push(opts.numericId);
    return '<article data-id="' + opts.numericId + '"></article>';
}
function _stageMount() { return mount; }
function animSpeed() { return 1; }
function _evDurationOr(ev, fallback) { return fallback; }
function renderHand() {
    renderHandCalls++;
    timeline.push({ step: 'render-hand', hand: gameState.players[0].hand.slice() });
}
function renderOppHandRow() {}
function updateHandHighlights() {}
function updatePileButtonCounts() { pileCountRenders++; }
function renderRoomBar() {}
function renderSelfInfo() {}
function renderOpponentInfo() {}
function renderPlayerAvatars() {}
function playSfx() {}
function requestAnimationFrame(fn) { fn(); }
function setTimeout(fn, delay) {
    timers.push({ fn: fn, due: now + (delay || 0) });
    return timers.length;
}
function runNextTimer() {
    timers.sort(function(a, b) { return a.due - b.due; });
    var timer = timers.shift();
    now = timer.due;
    timer.fn();
}
"""
        + extract_function("_removeSpringCleaningHandBeforeAnimation")
        + extract_function("playSpringCleaningExhaustBatch")
        + extract_function("commitEventToDom")
        + """
var ev = {
    type: 'card_burned',
    payload: {
        player_idx: 0,
        card_numeric_ids: [10, 10, 20],
        card_count: 3,
        source: 'spring_cleaning',
        from_zone: 'hand',
        destination: 'exhaust'
    }
};
playSpringCleaningExhaustBatch(ev, function() {
    // This is the event queue's ordering: commit the beat, then advance.
    commitEventToDom(ev);
    doneCalls++;
    timeline.push({
        step: 'done',
        hand: gameState.players[0].hand.slice(),
        exhaust: gameState.players[0].exhaust.slice()
    });
});
var beforeFinish = {
    hand: gameState.players[0].hand.slice(),
    exhaust: gameState.players[0].exhaust.slice(),
    renderedCards: renderedCards.slice(),
    renderHandCalls: renderHandCalls,
    mountedOverlays: mount.children.length,
    doneCalls: doneCalls,
    timeline: timeline.slice()
};
var guard = 0;
while (!doneCalls && timers.length && guard++ < 20) runNextTimer();
var afterFinish = {
    hand: gameState.players[0].hand.slice(),
    exhaust: gameState.players[0].exhaust.slice(),
    mountedOverlays: mount.children.length,
    doneCalls: doneCalls,
    pileCountRenders: pileCountRenders,
    timeline: timeline.slice()
};
console.log(JSON.stringify({ beforeFinish: beforeFinish, afterFinish: afterFinish }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["beforeFinish"]["hand"] == [30]
    assert out["beforeFinish"]["exhaust"] == [5]
    assert out["beforeFinish"]["renderedCards"] == [10, 10, 20]
    assert out["beforeFinish"]["renderHandCalls"] == 1
    assert out["beforeFinish"]["mountedOverlays"] == 1
    assert out["beforeFinish"]["doneCalls"] == 0
    assert out["beforeFinish"]["timeline"] == [
        {"step": "render-hand", "hand": [30]},
        {
            "step": "mount",
            "hand": [30],
            "exhaust": [5],
        },
    ]
    assert out["afterFinish"]["hand"] == [30]
    assert out["afterFinish"]["exhaust"] == [5, 10, 10, 20]
    assert out["afterFinish"]["mountedOverlays"] == 0
    assert out["afterFinish"]["doneCalls"] == 1
    assert out["afterFinish"]["pileCountRenders"] == 1
    assert out["afterFinish"]["timeline"][-1] == {
        "step": "done",
        "hand": [30],
        "exhaust": [5, 10, 10, 20],
    }
    assert "playSpringCleaningExhaustBatch(ev, done)" in extract_function(
        "playOverdrawBurn"
    )


def test_spring_cleaning_cards_exhaust_simultaneously_in_one_overlay():
    handler = extract_function("playSpringCleaningExhaustBatch")
    assert "overlay.className = 'spring-cleaning-exhaust-batch'" in handler
    assert "cardIds.forEach" in handler
    assert "overlay.classList.add('is-exhausting')" in handler

    css = (STATIC_DIR / "css" / "04-animations-overlays.css").read_text(
        encoding="utf-8"
    )
    selector = (
        ".spring-cleaning-exhaust-batch.is-exhausting "
        ".spring-cleaning-exhaust-card"
    )
    exhaust_rule = css.split(selector, 1)[1].split("}", 1)[0]
    assert "transition-delay: 0ms;" in exhaust_rule
    assert "var(--spring-delay" not in exhaust_rule


def test_god_spectator_p2_spring_cleaning_rebuilds_face_up_hands(tmp_path):
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var _clientLifecycleEpoch = 0;
var isSpectator = true;
var spectatorGodMode = true;
var myPlayerIdx = 0;
var gameState = {
    players: [
        { hand: [1] },
        { hand: [10, 20], hand_count: 2, hand_elements: [0, 1] }
    ]
};
var combinedHandRenders = [];
var opponentBackRenders = 0;
var selfInfoRenders = 0;
var opponentInfoRenders = 0;
function renderHand() {
    combinedHandRenders.push(gameState.players.map(function(player) {
        return Array.isArray(player.hand) ? player.hand.slice() : null;
    }));
}
function renderOppHandRow() { opponentBackRenders++; }
function renderSelfInfo() { selfInfoRenders++; }
function renderOpponentInfo() { opponentInfoRenders++; }
"""
        + extract_function("_removeSpringCleaningHandBeforeAnimation")
        + """
_removeSpringCleaningHandBeforeAnimation({
    player_idx: 1,
    card_numeric_ids: [10, 20],
    card_count: 2,
    source: 'spring_cleaning',
    from_zone: 'hand'
});
console.log(JSON.stringify({
    p2Hand: gameState.players[1].hand,
    p2HandCount: gameState.players[1].hand_count,
    p2Elements: gameState.players[1].hand_elements,
    combinedHandRenders: combinedHandRenders,
    opponentBackRenders: opponentBackRenders,
    selfInfoRenders: selfInfoRenders,
    opponentInfoRenders: opponentInfoRenders
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "p2Hand": [],
        "p2HandCount": 0,
        "p2Elements": [],
        "combinedHandRenders": [[[1], []]],
        "opponentBackRenders": 0,
        "selfInfoRenders": 1,
        "opponentInfoRenders": 1,
    }


def test_god_spectator_p2_spring_draw_is_face_up_and_owner_scoped(tmp_path):
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var _clientLifecycleEpoch = 0;
var myPlayerIdx = 0;
var isSpectator = true;
var spectatorGodMode = true;
var gameState = { players: [ { hand: [1] }, { hand: [] } ] };
var window = { __lastFinalState: {
    players: [ { hand: [1] }, { hand: [33] } ]
} };
var jobs = [];
var transfers = {};
var transferSeq = 0;
var combinedHandRenders = [];
var opponentBackRenders = 0;
var highlightCalls = 0;
function renderHand() {
    combinedHandRenders.push(gameState.players.map(function(player) {
        return player.hand.slice();
    }));
}
function renderOppHandRow() { opponentBackRenders++; }
function updateHandHighlights() { highlightCalls++; }
function enqueueAnimation(job) { jobs.push(job); }
function _evDurationOr(ev, fallback) { return fallback; }
function animSpeed() { return 1; }
function _retireCardSource() {}
function _newCardTransfer(spec) {
    var id = 't' + (++transferSeq); transfers[id] = spec; return id;
}
function _finishCardTransfer(id) { delete transfers[id]; }
function _rerenderHandOwner() {}
function _cardTransfer(id) { return transfers[id] || null; }
var setTimeout = function(fn, delay) { if (!delay) fn(); };
"""
        + extract_function("playCardDrawn")
        + """
playCardDrawn({ payload: {
    player_idx: 1,
    card_numeric_id: 33,
    source: 'spring_cleaning'
} }, function() {});
console.log(JSON.stringify({
    p2Hand: gameState.players[1].hand,
    combinedHandRenders: combinedHandRenders,
    opponentBackRenders: opponentBackRenders,
    highlightCalls: highlightCalls,
    jobs: jobs.map(function(job) {
        return {
            type: job.type,
            cardNumericId: job.cardNumericId,
            fromPos: job.fromPos,
            toSlotIndex: job.toSlotIndex,
            handOwnerIdx: job.handOwnerIdx,
            stateApplied: job.stateApplied,
            fromEventQueue: job._fromEventQueue
        };
    })
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "p2Hand": [33],
        "combinedHandRenders": [[[1], [33]]],
        "opponentBackRenders": 0,
        "highlightCalls": 1,
        "jobs": [{
            "type": "draw_own",
            "cardNumericId": 33,
            "fromPos": "deck",
            "toSlotIndex": 0,
            "handOwnerIdx": 1,
            "stateApplied": True,
            "fromEventQueue": True,
        }],
    }


def test_owner_scoped_draw_targets_correct_hand_and_deck_pile(tmp_path):
    script = (
        """
var sandboxMode = false;
var myPlayerIdx = 0;
var window = { innerWidth: 1200, innerHeight: 700 };
var idLookups = [];
var slotSelectors = [];
var pileSelectors = [];
var mountedFloaters = 0;
var timers = [];
var slot = {
    style: {},
    getBoundingClientRect: function() {
        return { left: 300, top: 400, width: 50, height: 60 };
    }
};
var hand = {
    querySelector: function(selector) {
        slotSelectors.push(selector);
        return slot;
    },
    querySelectorAll: function() { return [slot]; }
};
var pile = {
    getBoundingClientRect: function() {
        return { left: 100, top: 200, width: 20, height: 30 };
    }
};
function makeStyle() {
    var values = {};
    return {
        values: values,
        setProperty: function(name, value) { values[name] = value; }
    };
}
var body = {
    appendChild: function(child) {
        child.parentNode = body;
        mountedFloaters++;
    },
    removeChild: function(child) { child.parentNode = null; }
};
var document = {
    body: body,
    getElementById: function(id) {
        idLookups.push(id);
        return hand;
    },
    querySelector: function(selector) {
        pileSelectors.push(selector);
        return pile;
    },
    createElement: function() {
        return {
            className: '', innerHTML: '', parentNode: null,
            style: makeStyle(),
            addEventListener: function() {}
        };
    }
};
var cardDefs = { 33: { name: 'Drawn card' } };
function renderCardFrame() { return '<article></article>'; }
function playSfx() {}
function setTimeout(fn, delay) { timers.push([fn, delay]); }
"""
        + extract_function("_resolveDrawFromPoint")
        + extract_function("playDrawOwnAnimation")
        + """
function run(ownerIdx) {
    var beforeIds = idLookups.length;
    var beforeSlots = slotSelectors.length;
    var beforePiles = pileSelectors.length;
    var beforeFloaters = mountedFloaters;
    playDrawOwnAnimation({
        type: 'draw_own', cardNumericId: 33, fromPos: 'deck',
        toSlotIndex: 0, handOwnerIdx: ownerIdx, stateApplied: true
    }, function() {});
    return {
        id: idLookups[beforeIds],
        slotSelector: slotSelectors[beforeSlots],
        pileSelector: pileSelectors[beforePiles],
        floaters: mountedFloaters - beforeFloaters,
        slotHidden: slot.style.visibility,
        registry: Object.keys(window.__inFlightHandSlots).sort()
    };
}
var liveP2 = run(1);
sandboxMode = true;
slot.style.visibility = '';
var sandboxP2 = run(1);
console.log(JSON.stringify({ liveP2: liveP2, sandboxP2: sandboxP2 }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["liveP2"]["id"] == "hand-container"
    assert out["liveP2"]["slotSelector"] == (
        '.card-frame-hand[data-owner-idx="1"][data-hand-idx="0"]'
    )
    assert out["liveP2"]["pileSelector"] == (
        '#screen-game .pile-board[data-side="opp"] '
        '.pile-cell[data-pile="deck"]'
    )
    assert out["liveP2"]["floaters"] == 1
    assert out["liveP2"]["slotHidden"] == "hidden"
    assert out["liveP2"]["registry"] == ["owner:1:nid:33"]

    assert out["sandboxP2"]["id"] == "sandbox-hand-p1"
    assert out["sandboxP2"]["slotSelector"] == (
        '.card-frame-hand[data-owner-idx="1"][data-hand-idx="0"]'
    )
    assert out["sandboxP2"]["pileSelector"] == (
        '#screen-sandbox .pile-board[data-side="opp"] '
        '.pile-cell[data-pile="deck"]'
    )
    assert out["sandboxP2"]["floaters"] == 1
    assert out["sandboxP2"]["slotHidden"] == "hidden"
    assert out["sandboxP2"]["registry"] == ["owner:1:nid:33"]


# ---------------------------------------------------------------------------
# Roguelike milestone event modal wiring
# ---------------------------------------------------------------------------

def test_roguelike_event_modal_is_wired_into_render_and_event_queue():
    assert "function syncRoguelikeEventUI()" in _SRC
    assert "function closeRoguelikeEventModal()" in _SRC
    assert "syncRoguelikeEventUI();" in _SRC
    assert "socket.emit('roguelike_event_pick', { choice: selected })" in _SRC
    assert "kind === 'roguelike_event'" in _SRC
    assert "Stackable." in _SRC
    assert "function showRoguelikeChoicesReveal(payload)" in _SRC
    assert "Both resolve together · Reactions disabled" in _SRC
    assert "TURN ECONOMY:" in _SRC
    assert "ANTE UP:" not in extract_function("showRoguelikeChoicesReveal")
    assert "Math.max(_evDurationOr(ev, 0), revealMs)" in _SRC
    assert "Draw 4. Exhaust 2 random cards from your hand." in _SRC
    assert "Exhaust your hand. Draw that many cards plus 1." in _SRC
    assert "state.roguelike_event_history[playerIdx]" in _SRC
    assert "roguelike-player-choice" in _SRC
    assert "Handshakes deal +5 damage per stack." in _SRC
    assert "function _roguelikePlayerChoiceSummary" in _SRC
    assert "Chosen fortunes: " in _SRC
    assert "function syncMarkedCardsUI()" in _SRC
    assert "syncMarkedCardsUI();" in _SRC
    assert "socket.emit('marked_cards_resolve'" in _SRC
    assert "top_order: topOrder" in _SRC
    assert "Opponent is marking cards" in _SRC
    assert "A player is marking cards" in _SRC
    assert "kind === 'marked_cards'" in _SRC
    # Fortune uses the shared board-window minimise/restore controller.
    assert "function attachBoardModalMinimizer" in _SRC
    assert "fortune-restore-pill" in _SRC
    assert "marked-cards-restore-pill" in _SRC
    assert "tutor-modal pregame-rps-modal roguelike-event-modal" not in _SRC
    # Card-granting fortunes show the normal card face, and Uncharted reveals
    # the actual result as the primary Fortune rather than hiding it in copy.
    assert "reward_cards" in _SRC
    assert "renderDeckBuilderCard(" in extract_function("_appendFortuneRewardCards")
    reward_cards = extract_function("_appendFortuneRewardCards")
    assert "showGameTooltip(nid, tile" in reward_cards
    assert "stopPropagation" not in reward_cards, (
        "tapping a reward card must still bubble to select its Fortune"
    )
    reveal_card = extract_function("_roguelikeRevealCard")
    assert "_renderRoguelikeOptionTile(card, resolved)" in reveal_card
    assert "Rolled by " in reveal_card


def test_all_direct_card_choices_use_full_card_faces():
    marked = extract_function("showMarkedCardsModal")
    assert "tutor-modal-card marked-cards-tile" in marked
    assert "renderDeckBuilderCard(nid, undefined)" in marked
    assert "rps-tile-glyph" not in marked
    assert "rps-tile-label" not in marked

    action_menu = extract_function("showMinionActionMenu")
    transform_picker = extract_function("showTransformPicker")
    assert "addBtn('Transform'" in action_menu
    assert "Transform →" not in action_menu
    assert "renderDeckBuilderCard(targetNid, undefined)" in transform_picker
    assert "tutor-modal-card transform-picker-card" in transform_picker
    assert "tile.addEventListener('focus', inspectTransformCard)" in transform_picker
    assert "inspectTransformCard();" in transform_picker


def test_forced_card_modals_share_tutor_layout_and_minimise_conventions():
    trigger = extract_function("showTriggerPickerModal")
    revive = extract_function("showReviveModal")
    helper = extract_function("attachBoardModalMinimizer")
    assert "trigger-picker-restore-pill" in trigger
    assert "revive-modal-restore-pill" in revive
    assert "fan.className = 'tutor-modal-cards'" in revive
    assert "reviveAccept.className = 'tutor-accept-button'" in revive
    assert "tile.classList.add('tutor-card-selected')" in revive
    assert "tile.addEventListener('focus', inspectReviveCard)" in revive
    assert "showGameTooltip(match.card_numeric_id" in revive
    revive_highlights = extract_function("highlightReviveCells")
    assert "Array.isArray(legalActions)" in revive_highlights
    assert "window.legalActions" not in revive_highlights
    assert "'Minimise ' + label + ' window'" in helper
    assert "'Restore ' + label + ' window'" in helper


def test_board_modal_minimizer_preserves_state_and_manages_restore_tray(tmp_path):
    """Minimising hides, rather than rebuilds, the live decision node.

    This preserves selection/scroll/disabled state. Multiple minimised windows
    share one restore tray, disposing one leaves the other intact, and global
    cleanup removes the final affordance and read-only peek gate.
    """
    script = (
        """
var nodes = {};
function unregisterTree(node) {
    (node.children || []).slice().forEach(unregisterTree);
    if (node.id) delete nodes[node.id];
}
function makeClassList() {
    var values = {};
    return {
        add: function(name) { values[name] = true; },
        remove: function(name) { delete values[name]; },
        contains: function(name) { return !!values[name]; },
        toggle: function(name, force) {
            var next = force == null ? !values[name] : !!force;
            if (next) values[name] = true; else delete values[name];
            return next;
        }
    };
}
function makeElement(tag) {
    var el = {
        tagName: tag, _id: '', className: '', textContent: '', title: '',
        style: {}, attributes: {}, children: [], parentNode: null, listeners: {},
        classList: makeClassList(), focusCalls: 0,
        setAttribute: function(name, value) {
            this.attributes[name] = String(value);
            if (name === 'id') this.id = String(value);
        },
        getAttribute: function(name) {
            return Object.prototype.hasOwnProperty.call(this.attributes, name)
                ? this.attributes[name] : null;
        },
        hasAttribute: function(name) {
            return Object.prototype.hasOwnProperty.call(this.attributes, name);
        },
        removeAttribute: function(name) { delete this.attributes[name]; },
        addEventListener: function(name, fn) { this.listeners[name] = fn; },
        appendChild: function(child) {
            if (child.parentNode) child.parentNode.removeChild(child);
            child.parentNode = this;
            this.children.push(child);
            if (child.id) nodes[child.id] = child;
            return child;
        },
        insertBefore: function(child, before) {
            if (child.parentNode) child.parentNode.removeChild(child);
            var at = this.children.indexOf(before);
            if (at < 0) return this.appendChild(child);
            child.parentNode = this;
            this.children.splice(at, 0, child);
            if (child.id) nodes[child.id] = child;
            return child;
        },
        removeChild: function(child) {
            this.children = this.children.filter(function(x) { return x !== child; });
            child.parentNode = null;
            unregisterTree(child);
        },
        remove: function() {
            if (this.parentNode) this.parentNode.removeChild(this);
            else unregisterTree(this);
        },
        focus: function() { this.focusCalls++; }
    };
    Object.defineProperty(el, 'id', {
        get: function() { return this._id; },
        set: function(value) {
            if (this._id) delete nodes[this._id];
            this._id = value || '';
            if (this._id) nodes[this._id] = this;
        }
    });
    return el;
}
var document = {
    createElement: makeElement,
    getElementById: function(id) { return nodes[id] || null; },
    body: makeElement('body'),
    querySelectorAll: function(selector) {
        return selector.indexOf('#sandbox-control-panel') !== -1
            ? sandboxControls : [];
    }
};
var enabledSandboxControl = makeElement('button');
enabledSandboxControl.disabled = false;
var disabledSandboxControl = makeElement('button');
disabledSandboxControl.disabled = true;
var sandboxControls = [enabledSandboxControl, disabledSandboxControl];
var mount = makeElement('mount');
function _stageMount() { return mount; }
var refreshCalls = 0;
var reviveOverlay = null;
var reviveVisibleDuringRefresh = [];
function updateHandHighlights() { refreshCalls++; }
function highlightBoard() {
    refreshCalls++;
    var tray = document.getElementById('board-modal-restore-tray');
    if (reviveOverlay && tray && tray.children.length) {
        reviveVisibleDuringRefresh.push(reviveOverlay.style.display !== 'none');
    }
}
function renderActionBar() { refreshCalls++; }
function click(el) {
    el.listeners.click({
        preventDefault: function() {}, stopPropagation: function() {}
    });
}
function makeMinimised(id, restoreId, label) {
    var header = makeElement('header');
    var overlay = makeElement('overlay');
    overlay.id = id;
    overlay.style.display = 'flex';
    mount.appendChild(overlay);
    overlay.appendChild(header);
    var button = attachBoardModalMinimizer({
        overlay: overlay, controlsHost: header,
        label: label, restoreId: restoreId
    });
    click(button);
    return { overlay: overlay, button: button };
}
"""
        + extract_function("_boardModalRestoreTray")
        + extract_function("isBoardModalPeekActive")
        + extract_function("_refreshBoardPeekAffordances")
        + extract_function("_removeBoardModalRestorePill")
        + extract_function("disposeBoardModalMinimizer")
        + extract_function("disposeAllBoardModalMinimizers")
        + extract_function("attachBoardModalMinimizer")
        + """
var header = makeElement('header');
var overlay = makeElement('overlay');
overlay.id = 'choice-overlay';
overlay.style.display = 'flex';
overlay.scrollLeft = 73;
overlay.selectedChoice = 'rat';
mount.appendChild(overlay);
overlay.appendChild(header);
var accept = makeElement('button');
accept.disabled = false;
overlay.appendChild(accept);
var minButton = attachBoardModalMinimizer({
    overlay: overlay, controlsHost: header,
    label: 'Choice', restoreId: 'choice-restore-pill'
});
click(minButton);
var pill = document.getElementById('choice-restore-pill');
var hiddenSnapshot = {
    display: overlay.style.display,
    ariaHidden: overlay.getAttribute('aria-hidden'),
    expanded: minButton.getAttribute('aria-expanded'),
    selected: overlay.selectedChoice,
    scrollLeft: overlay.scrollLeft,
    acceptDisabled: accept.disabled,
    peek: isBoardModalPeekActive(),
    pillFocused: pill.focusCalls,
    sandboxDisabled: sandboxControls.map(function(control) { return control.disabled; }),
    sandboxPrior: sandboxControls.map(function(control) {
        return control.getAttribute('data-peek-prior-disabled');
    })
};
click(pill);
var restoredSnapshot = {
    display: overlay.style.display,
    ariaHidden: overlay.getAttribute('aria-hidden'),
    expanded: minButton.getAttribute('aria-expanded'),
    selected: overlay.selectedChoice,
    scrollLeft: overlay.scrollLeft,
    acceptDisabled: accept.disabled,
    peek: isBoardModalPeekActive(),
    buttonFocused: minButton.focusCalls,
    sandboxDisabled: sandboxControls.map(function(control) { return control.disabled; }),
    sandboxPrior: sandboxControls.map(function(control) {
        return control.getAttribute('data-peek-prior-disabled');
    })
};

var first = makeMinimised('first-overlay', 'first-restore-pill', 'First');
var second = makeMinimised('second-overlay', 'second-restore-pill', 'Second');
var tray = document.getElementById('board-modal-restore-tray');
var overlapCount = tray.children.length;
disposeBoardModalMinimizer(first.overlay);
var secondSurvived = !!document.getElementById('second-restore-pill')
    && isBoardModalPeekActive();
disposeAllBoardModalMinimizers();

// Multi-pill regression: restoring Revive while an unrelated window remains
// minimised must repaint the board after Revive is visible. Otherwise its
// placement instructions return with no legal tile highlights.
var unrelated = makeMinimised(
    'unrelated-overlay', 'unrelated-restore-pill', 'Unrelated'
);
var revive = makeMinimised(
    'revive-modal-overlay', 'revive-modal-restore-pill', 'Revive'
);
reviveOverlay = revive.overlay;
click(document.getElementById('revive-modal-restore-pill'));
var reviveRestoredWithOtherPill =
    reviveVisibleDuringRefresh[reviveVisibleDuringRefresh.length - 1] === true
    && revive.overlay.style.display === 'flex'
    && !!document.getElementById('unrelated-restore-pill');
disposeAllBoardModalMinimizers();

console.log(JSON.stringify({
    hidden: hiddenSnapshot,
    restored: restoredSnapshot,
    overlapCount: overlapCount,
    secondSurvived: secondSurvived,
    reviveRestoredWithOtherPill: reviveRestoredWithOtherPill,
    allDisposed: !document.getElementById('board-modal-restore-tray')
        && !isBoardModalPeekActive()
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "hidden": {
            "display": "none",
            "ariaHidden": "true",
            "expanded": "false",
            "selected": "rat",
            "scrollLeft": 73,
            "acceptDisabled": False,
            "peek": True,
            "pillFocused": 1,
            "sandboxDisabled": [True, True],
            "sandboxPrior": ["false", "true"],
        },
        "restored": {
            "display": "flex",
            "ariaHidden": None,
            "expanded": "true",
            "selected": "rat",
            "scrollLeft": 73,
            "acceptDisabled": False,
            "peek": False,
            "buttonFocused": 1,
            "sandboxDisabled": [False, True],
            "sandboxPrior": [None, None],
        },
        "overlapCount": 2,
        "secondSurvived": True,
        "reviveRestoredWithOtherPill": True,
        "allDisposed": True,
    }


def test_every_persistent_board_modal_has_a_unique_restore_id_and_cleanup():
    modal_openers = {
        "showTutorModal": "tutor-restore-pill",
        "showTriggerPickerModal": "trigger-picker-restore-pill",
        "showReviveModal": "revive-modal-restore-pill",
        "showRoguelikeEventModal": "fortune-restore-pill",
        "showMarkedCardsModal": "marked-cards-restore-pill",
        "showTransformPicker": "transform-picker-restore-pill",
        "showSacrificePicker": "discard-picker-restore-pill",
        "setupPileHandlers": "pile-modal-restore-pill",
        "setupGameHandlers": "game-over-restore-pill",
        "showBoardDialog": "board-dialog-restore-pill",
        "showRpsPickModal": "pregame-rps-restore-pill",
        "showMulliganModal": "pregame-mulligan-restore-pill",
    }
    found_ids = []
    for function_name, restore_id in modal_openers.items():
        function_src = extract_function(function_name)
        assert "attachBoardModalMinimizer" in function_src, function_name
        assert f"restoreId: '{restore_id}'" in function_src, function_name
        found_ids.append(restore_id)
    assert "restoreId: 'bug-report-restore-pill'" in _SRC
    found_ids.append("bug-report-restore-pill")
    assert len(found_ids) == len(set(found_ids)), "restore IDs must never collide"

    cleanup_functions = (
        "closeTutorModal",
        "closeTriggerPickerModal",
        "closeReviveModal",
        "closeRoguelikeEventModal",
        "closeMarkedCardsModal",
        "closeTransformPicker",
        "hideSacrificePicker",
        "hidePileModal",
        "hideGameOver",
        "closeRpsModal",
        "closeMulliganModal",
    )
    for function_name in cleanup_functions:
        assert "disposeBoardModalMinimizer" in extract_function(function_name), function_name
    assert "disposeAllBoardModalMinimizers" in extract_function("resetGameClientState")


def test_minimised_board_peek_blocks_every_gameplay_entry_point(tmp_path):
    script = (
        """
var isSpectator = false;
var sandboxMode = false;
var emitted = [];
var socket = { emit: function(name, payload) { emitted.push([name, payload]); } };
var document = { getElementById: function() { return null; } };
function isBoardModalPeekActive() { return true; }
"""
        + extract_function("canResolveVisibleBoardModal")
        + extract_function("canResolvePendingBoardDecisionDuringPeek")
        + extract_function("canActNow")
        + extract_function("_clientActionOverlayOpen")
        + extract_function("submitAction")
        + extract_function("onHandCardClick")
        + extract_function("onBoardCellClick")
        + extract_function("onBoardMinionClick")
        + extract_function("emitSandboxEvent")
        + """
submitAction({ action_type: 4 });
onHandCardClick(0, 0);
onBoardCellClick(0, 0);
onBoardMinionClick({ instance_id: 1 });
emitSandboxEvent('sandbox_reset');
console.log(JSON.stringify({
    canAct: canActNow(),
    overlayOpen: _clientActionOverlayOpen(),
    emitted: emitted.length
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "canAct": False,
        "overlayOpen": True,
        "emitted": 0,
    }


def test_static_client_uses_no_native_alert_confirm_or_prompt():
    native_dialog = re.compile(r"\b(?:window\s*\.\s*)?(?:alert|confirm|prompt)\s*\(")
    offenders = []
    for path in sorted((STATIC_DIR / "js").glob("*.js")):
        source = path.read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        for line_number, line in enumerate(source.splitlines(), start=1):
            code = line.split("//", 1)[0]
            if native_dialog.search(code):
                offenders.append(f"{path.name}:{line_number}: {code.strip()}")
    assert not offenders, "native browser dialogs found:\n" + "\n".join(offenders)


def test_tests_overlay_minimise_also_collapses_the_toc():
    wire = extract_function("_wireTestsOnce")
    assert "var tocPanel = document.getElementById('tests-toc-panel')" in wire
    assert "if (tocPanel) tocPanel.hidden = true;" in wire
    assert "aria-expanded" in wire
    assert "Restore Tests window" in wire

    css = (STATIC_DIR / "css" / "01-base-tokens.css").read_text(encoding="utf-8")
    collapsed = css.split("/* Minimized state:", 1)[1].split("}", 1)[0]
    assert ".tests-overlay.is-minimized .tests-toc-panel" in collapsed


def test_peek_mode_freezes_sandbox_controls_and_restores_prior_disabled_state():
    refresh = extract_function("_refreshBoardPeekAffordances")
    assert "#sandbox-control-panel button" in refresh
    assert "#sandbox-control-panel input" in refresh
    assert "#sandbox-control-panel select" in refresh
    assert "data-peek-prior-disabled" in refresh
    assert "control.disabled = true;" in refresh
    assert "control.removeAttribute('data-peek-prior-disabled')" in refresh

    css = (STATIC_DIR / "css" / "zz-overrides.css").read_text(encoding="utf-8")
    assert "body.board-modal-peek-active #sandbox-control-panel" in css

    sandbox = (STATIC_DIR / "js" / "12-sandbox.js").read_text(encoding="utf-8")
    assert "function emitSandboxEvent" in sandbox
    assert "socket.emit('sandbox_" not in sandbox


def test_board_modal_cleanup_runs_at_every_session_boundary():
    assert "closeAllBoardModalsForReset" in extract_function("sandboxDeactivate")
    assert "closeAllBoardModalsForReset" in extract_function("onGameStart")
    assert "closeNonterminalBoardModals" in extract_function("showGameOver")
    hard_reset = extract_function("closeAllBoardModalsForReset")
    assert "closeNonterminalBoardModals" in hard_reset
    assert "hideGameOver" in hard_reset
    assert "if (openGeneration !== bugOpenGeneration) return;" in _SRC


def test_tests_scenario_load_clears_prior_modal_restore_pills(tmp_path):
    reset_handler = extract_function("_wireTestsOnce")
    current_loader = extract_function("_loadCurrentTest")
    assert "_requestTestsScenario(_testsState.currentId)" in reset_handler
    assert "_requestTestsScenario(t.id)" in current_loader

    script = (
        """
var cleanupCalls = 0;
var restorePills = ['pile-modal-restore-pill', 'revive-modal-restore-pill'];
var emitted = [];
function closeAllBoardModalsForReset() {
    cleanupCalls++;
    restorePills = [];
}
var socket = {
    emit: function(name, payload) { emitted.push([name, payload]); }
};
"""
        + extract_function("_requestTestsScenario")
        + """
_requestTestsScenario('revive-placement');
console.log(JSON.stringify({
    cleanupCalls: cleanupCalls,
    restorePills: restorePills,
    emitted: emitted
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "cleanupCalls": 1,
        "restorePills": [],
        "emitted": [["tests_load", {"id": "revive-placement"}]],
    }


def test_visible_modal_resolutions_remain_consistent_during_another_peek():
    submit = extract_function("submitAction")
    assert "allowDuringBoardPeek" in submit
    assert "_modalResolutionTypes.indexOf(_at) === -1" in submit
    assert "_pendingBoardResolution" in submit
    pending = "!canResolvePendingBoardDecisionDuringPeek()"
    assert pending in extract_function("onBoardMinionClick")
    assert pending in extract_function("highlightBoard")
    cell_click = extract_function("onBoardCellClick")
    assert "if (_peekActive && !_pendingBoardDecision) return;" in cell_click
    assert "if (sandboxMode && !_pendingBoardDecision)" in cell_click
    assert "emitSandboxEvent('sandbox_place_on_board'" in cell_click
    contextual = extract_function("canResolvePendingBoardDecisionDuringPeek")
    assert "canResolveVisibleBoardModal('revive-modal-overlay')" in contextual

    transform = extract_function("showTransformPicker")
    discard = extract_function("showSacrificePicker")
    assert "}, true);" in transform
    assert "submitAction(payload, true);" in discard
    assert "submitAction(_playCardPayload(manaModeAction), true);" in discard

    for opener in (
        "showRoguelikeEventModal",
        "showMarkedCardsModal",
        "showRpsPickModal",
        "showMulliganModal",
    ):
        assert "canResolveVisibleBoardModal(overlay)" in extract_function(opener)


def test_pending_board_decision_beats_sandbox_staged_card_during_peek(tmp_path):
    script = (
        """
var sandboxMode = true;
var interactionMode = 'conjure_deploy';
var isSpectator = false;
var legalActions = [{ action_type: 12, position: [1, 2] }];
var gameState = { pending_conjure_deploy_positions: [[1, 2]] };
var window = {};
var staged = { hidden: false, dataset: { nid: '99' } };
var sandboxEvents = [];
var submitted = [];
var document = {
    getElementById: function(id) {
        return id === 'sandbox-staged-card' ? staged : null;
    }
};
function isBoardModalPeekActive() { return true; }
function canResolvePendingBoardDecisionDuringPeek() { return true; }
function emitSandboxEvent(name, payload) {
    sandboxEvents.push([name, payload]);
    return true;
}
function isSpellStageAnimating() { return false; }
function isReactWindow() { return false; }
function submitAction(payload) { submitted.push(payload); }
function closeConjureDeployUI() {}
"""
        + extract_function("onBoardCellClick")
        + """
onBoardCellClick(1, 2);
console.log(JSON.stringify({
    sandboxEvents: sandboxEvents,
    stagedHidden: staged.hidden,
    stagedNid: staged.dataset.nid,
    submitted: submitted,
    conjureSubmitted: window.__conjureDeploySubmitted,
    interactionMode: interactionMode
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "sandboxEvents": [],
        "stagedHidden": False,
        "stagedNid": "99",
        "submitted": [{"action_type": 12, "position": [1, 2]}],
        "conjureSubmitted": True,
        "interactionMode": None,
    }


def test_revive_placement_remains_clickable_while_cast_is_on_spell_stage(tmp_path):
    """Ratical's pending placement resolves before its cast stage closes."""
    script = (
        """
var sandboxMode = false;
var interactionMode = 'revive_place';
var isSpectator = false;
var legalActions = [
    { action_type: 15, card_index: 4, position: [1, 2] }
];
var gameState = {
    phase: 1,
    pending_revive_player_idx: 0,
    pending_revive_remaining: 3
};
var window = {
    __reviveSelectedGraveIdx: 4,
    __reviveSubmittedAtRemaining: null
};
var submitted = [];
var closeCalls = 0;
var document = { getElementById: function() { return null; } };
function isBoardModalPeekActive() { return false; }
function canResolvePendingBoardDecisionDuringPeek() { return false; }
function isEventQueueBusy() { return true; }
function isSpellStageAnimating() { return true; }
function isReactWindow() { return true; }
function submitAction(payload) { submitted.push(payload); }
function closeReviveModal() { closeCalls++; }
"""
        + extract_function("onBoardCellClick")
        + """
onBoardCellClick(1, 2);
console.log(JSON.stringify({
    submitted: submitted,
    closeCalls: closeCalls,
    submittedAt: window.__reviveSubmittedAtRemaining,
    selectedGraveIdx: window.__reviveSelectedGraveIdx,
    interactionMode: interactionMode
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "submitted": [
            {"action_type": 15, "position": [1, 2], "card_index": 4}
        ],
        "closeCalls": 1,
        "submittedAt": 3,
        "selectedGraveIdx": None,
        "interactionMode": None,
    }


def test_attack_selection_paints_range_without_restoring_inspection_overlay():
    client_js = _load_client_js()
    highlight = extract_function("highlightBoard")
    assert "attack-range-footprint" in client_js
    assert "function _paintAttackRangeFootprint" in client_js
    assert "_paintAttackRangeFootprint(selectedMinionId)" in highlight
    assert "pending_attack_range_tiles" in highlight
    assert "getAttackTargets(selectedMinionId)" in highlight
    assert "cell.classList.add('attack-valid-target')" in highlight
    assert "inspectedMinionId" not in highlight
    pin_setup = extract_function("setupGameTooltipPin")
    assert "}, true);" in pin_setup, "minion inspection must run before board-cell rendering"


def test_clearing_attack_selection_immediately_removes_all_board_indicators(tmp_path):
    script = (
        """
function makeClassList(names) {
    var values = names.slice();
    return {
        remove: function() {
            for (var i = 0; i < arguments.length; i++) {
                var target = arguments[i];
                values = values.filter(function(v) { return v !== target; });
            }
        },
        values: function() { return values.slice().sort(); }
    };
}
var cells = [
    {classList: makeClassList(['board-cell', 'attack-range-footprint', 'cell-selected'])},
    {classList: makeClassList(['board-cell', 'cell-attack', 'attack-valid-target', 'other'])}
];
var document = {
    querySelectorAll: function(sel) { return sel === '.board-cell' ? cells : []; }
};
var selectedHandIdx = 2;
var selectedMinionId = 9;
var selectedDeployPos = [1, 1];
var selectedAbilityMinionId = 9;
var interactionMode = 'attack';
function hideMinionActionMenu() {}
function closeTransformPicker() {}
function hideDeclinePostMoveAttackButton() {}
"""
        + extract_function("_clearBoardInteractionHighlights")
        + extract_function("clearSelection")
        + """
clearSelection();
console.log(JSON.stringify({
    classes: cells.map(function(c) { return c.classList.values(); }),
    selectedHandIdx: selectedHandIdx,
    selectedMinionId: selectedMinionId,
    selectedDeployPos: selectedDeployPos,
    selectedAbilityMinionId: selectedAbilityMinionId,
    interactionMode: interactionMode
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "classes": [["board-cell"], ["board-cell", "other"]],
        "selectedHandIdx": None,
        "selectedMinionId": None,
        "selectedDeployPos": None,
        "selectedAbilityMinionId": None,
        "interactionMode": None,
    }


def test_attack_range_footprint_matches_engine_geometry(tmp_path):
    script = (
        r"""
var painted = [];
var gameState = {
    minions: [{instance_id: 9, card_numeric_id: 3, position: [2, 2]}]
};
var cardDefs = {3: {attack_range: 0}};
var document = {
    querySelector: function(sel) {
        var m = /data-row=\"(\d+)\"\]\[data-col=\"(\d+)\"/.exec(sel);
        if (!m) return null;
        var key = m[1] + ',' + m[2];
        return {classList: {add: function(cls) { painted.push([key, cls]); }}};
    }
};
"""
        + extract_function("_paintAttackRangeFootprint")
        + """
_paintAttackRangeFootprint(9);
var melee = painted.map(function(x) { return x[0]; }).sort();
painted = [];
cardDefs[3].attack_range = 1;
_paintAttackRangeFootprint(9);
var ranged = painted.map(function(x) { return x[0]; }).sort();
console.log(JSON.stringify({melee: melee, ranged: ranged}));
"""
    )
    assert run_js(tmp_path, script) == {
        "melee": ["1,2", "2,1", "2,3", "3,2"],
        "ranged": [
            "0,2", "1,1", "1,2", "1,3", "2,0", "2,1",
            "2,3", "2,4", "3,1", "3,2", "3,3", "4,2",
        ],
    }


def test_explicit_card_origin_controls_live_deck_counter(tmp_path):
    """Only cards that actually came from the deck consume its live count.

    Fortune events can use the same event type for a deck draw, a generated
    card, or a card returned from the grave.  The explicit ``from_zone`` is
    therefore authoritative for both normal draws and full-hand burns.
    """
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var myPlayerIdx = 0;
var activePlayerPreviewIdx = null;
var gameState = {
    players: [
        { hp: 80, deck_count: 9, deck: [], exhaust: [] },
        { hp: 70, deck_count: 1, deck: [], exhaust: [] }
    ]
};
var pileRenders = [];
function updatePileButtonCounts() {
    pileRenders.push(gameState.players[1].deck_count);
}
function renderRoomBar() {}
function renderSelfInfo() {}
function renderOpponentInfo() {}
function renderPlayerAvatars() {}
"""
        + extract_function("_commitPlayerField")
        + extract_function("_commitFatigueDeckEmpty")
        + extract_function("commitEventToDom")
        + """
var opponent = gameState.players[1];

commitEventToDom({ type: 'card_burned', payload: {
    player_idx: 1, card_numeric_id: 101, source: 'pocket_change',
    from_zone: 'deck'
} });
var afterDeckBurn = opponent.deck_count;

opponent.deck_count = 4;
commitEventToDom({ type: 'card_drawn', payload: {
    player_idx: 1, card_numeric_id: 102, source: 'roguelike_event',
    from_zone: 'generated'
} });
var afterGeneratedDraw = opponent.deck_count;
commitEventToDom({ type: 'card_drawn', payload: {
    player_idx: 1, card_numeric_id: 103, source: 'grave_expectations',
    from_zone: 'grave'
} });
var afterGraveDraw = opponent.deck_count;
commitEventToDom({ type: 'card_burned', payload: {
    player_idx: 1, card_numeric_id: 104, source: 'roguelike_event',
    from_zone: 'generated'
} });
var afterGeneratedBurn = opponent.deck_count;
commitEventToDom({ type: 'card_burned', payload: {
    player_idx: 1, card_numeric_id: 105, source: 'grave_expectations',
    from_zone: 'grave'
} });
var afterGraveBurn = opponent.deck_count;

// God spectators/sandbox carry the real deck array instead of only a count.
// Both draw and burn must consume index 0, matching Player.draw_card().
delete opponent.deck_count;
opponent.deck = [201, 202, 203];
commitEventToDom({ type: 'card_burned', payload: {
    player_idx: 1, card_numeric_id: 201, source: 'marked_cards',
    from_zone: 'deck'
} });
var afterGodDeckBurn = opponent.deck.slice();
commitEventToDom({ type: 'card_drawn', payload: {
    player_idx: 1, card_numeric_id: 202, source: 'spring_cleaning',
    from_zone: 'deck'
} });
var afterGodDeckDraw = opponent.deck.slice();

opponent.deck_count = 4;
opponent.deck = [];

commitEventToDom({ type: 'player_hp_change', payload: {
    player_idx: 1, prev: 70, 'new': 65, delta: -5, cause: 'combat'
} });
console.log(JSON.stringify({
    afterDeckBurn: afterDeckBurn,
    afterGeneratedDraw: afterGeneratedDraw,
    afterGraveDraw: afterGraveDraw,
    afterGeneratedBurn: afterGeneratedBurn,
    afterGraveBurn: afterGraveBurn,
    afterGodDeckBurn: afterGodDeckBurn,
    afterGodDeckDraw: afterGodDeckDraw,
    afterOrdinaryDamage: opponent.deck_count,
    hp: opponent.hp,
    exhaust: opponent.exhaust,
    lastRenderedCount: pileRenders[pileRenders.length - 1]
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "afterDeckBurn": 0,
        "afterGeneratedDraw": 4,
        "afterGraveDraw": 4,
        "afterGeneratedBurn": 4,
        "afterGraveBurn": 4,
        "afterGodDeckBurn": [202, 203],
        "afterGodDeckDraw": [203],
        "afterOrdinaryDamage": 4,
        "hp": 65,
        "exhaust": [101, 104, 105, 201],
        "lastRenderedCount": 4,
    }


def test_fatigue_reconciles_empty_deck_before_nudge(tmp_path):
    """The fatigue visual must never mount beside a stale one-card pile."""
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var activePlayerPreviewIdx = null;
var gameState = {
    players: [
        { hp: 80, deck_count: 8, deck: [] },
        { hp: 70, deck_count: 1, deck: [999] }
    ]
};
var order = [];
var timers = [];
function updatePileButtonCounts() {
    order.push('pile:' + gameState.players[1].deck_count);
}
function renderSelfInfo() {
    order.push('self:' + gameState.players[1].deck_count);
}
function renderOpponentInfo() {
    order.push('opponent:' + gameState.players[1].deck_count);
}
function triggerFatigueNudge(damage, playerIdx) {
    order.push('nudge:' + gameState.players[playerIdx].deck_count);
}
function _showPlayerHpDamagePopup(payload) {
    order.push('popup:' + gameState.players[payload.player_idx].deck_count);
}
function _evDurationOr(ev, fallback) { return fallback; }
function setTimeout(fn, delay) { timers.push({ fn: fn, delay: delay }); }
function playHandshakeSlap() { throw new Error('unexpected slap'); }
"""
        + extract_function("_commitFatigueDeckEmpty")
        + extract_function("_showFatigueDeckEmptyImmediately")
        + extract_function("playPlayerHpChange")
        + """
var fatigue = {
    type: 'player_hp_change',
    payload: {
        player_idx: 1, prev: 70, 'new': 60, delta: -10, cause: 'fatigue'
    }
};
playPlayerHpChange(fatigue, function() {});
var fatigueSnapshot = {
    deckCount: gameState.players[1].deck_count,
    deckLength: gameState.players[1].deck.length,
    order: order.slice()
};

// The projection may already say zero while stale DOM still says one. The
// fatigue beat must repaint before its nudge even when no state value changes.
order.length = 0;
playPlayerHpChange(fatigue, function() {});
var alreadyEmptyOrder = order.slice();

gameState.players[1].deck_count = 1;
gameState.players[1].deck = [888];
order.length = 0;
playPlayerHpChange({
    type: 'player_hp_change',
    payload: {
        player_idx: 1, prev: 60, 'new': 55, delta: -5, cause: 'combat'
    }
}, function() {});
var ordinarySnapshot = {
    deckCount: gameState.players[1].deck_count,
    deckLength: gameState.players[1].deck.length,
    order: order.slice()
};
console.log(JSON.stringify({
    fatigue: fatigueSnapshot,
    alreadyEmptyOrder: alreadyEmptyOrder,
    ordinary: ordinarySnapshot
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["fatigue"] == {
        "deckCount": 0,
        "deckLength": 0,
        "order": [
            "pile:0",
            "self:0",
            "opponent:0",
            "nudge:0",
            "popup:0",
        ],
    }
    assert out["alreadyEmptyOrder"] == [
        "pile:0",
        "self:0",
        "opponent:0",
        "nudge:0",
        "popup:0",
    ]
    assert out["ordinary"] == {
        "deckCount": 1,
        "deckLength": 1,
        "order": ["popup:1"],
    }


def test_handshake_slap_routes_to_impact_animation():
    hp_handler = extract_function("playPlayerHpChange")
    route = "if (payload.cause === 'handshake_slap')"
    assert route in hp_handler
    assert hp_handler.index(route) < hp_handler.index("if (payload.cause === 'fatigue')")
    assert "playHandshakeSlap(ev, done);" in hp_handler
    assert "_showPlayerHpDamagePopup(payload);" in hp_handler


def test_handshake_slap_hits_at_170_degrees_and_stacks_once(tmp_path):
    script = (
        """
var timers = [];
var played = [];
var commits = 0;
var popupDeltas = [];
var doneCalls = 0;

function makeClassList() {
    var values = [];
    return {
        add: function(name) { if (values.indexOf(name) < 0) values.push(name); },
        remove: function(name) { values = values.filter(function(x) { return x !== name; }); },
        contains: function(name) { return values.indexOf(name) >= 0; }
    };
}
function makeStyle() {
    var values = {};
    return {
        setProperty: function(name, value) { values[name] = value; },
        removeProperty: function(name) { delete values[name]; },
        values: values
    };
}
function makeElement(tag) {
    var el = {
        tagName: tag,
        id: '',
        className: '',
        textContent: '',
        children: [],
        parentNode: null,
        classList: makeClassList(),
        style: makeStyle(),
        offsetWidth: 844,
        appendChild: function(child) { child.parentNode = el; el.children.push(child); },
        removeChild: function(child) {
            el.children = el.children.filter(function(x) { return x !== child; });
            child.parentNode = null;
        },
        remove: function() { if (el.parentNode) el.parentNode.removeChild(el); },
        setAttribute: function() {}
    };
    return el;
}

var screen = makeElement('section');
screen.classList.add('screen');
screen.classList.add('active');
var mount = makeElement('main');
mount.closest = function() { return screen; };
var document = {
    createElement: makeElement,
    getElementById: function() { return null; },
    querySelector: function(selector) { return selector === '.screen.active' ? screen : null; }
};
var window = { matchMedia: function() { return { matches: false }; } };
function _stageMount() { return mount; }
function animSpeed() { return 1; }
function _evDurationOr(ev, fallback) { return ev.animation_duration_ms || fallback; }
function playSfx(name) { played.push(name); }
function commitEventToDom() { commits++; }
function _showPlayerHpDamagePopup(payload) { popupDeltas.push(payload.delta); }
var setTimeout = function(fn, delay) { timers.push({ fn: fn, delay: delay }); return timers.length; };
"""
        + extract_function("playHandshakeSlap")
        + """
var ev = {
    animation_duration_ms: 1150,
    payload: {
        player_idx: 1,
        source_player_idx: 0,
        delta: -10,
        stacks: 2,
        cause: 'handshake_slap'
    }
};
playHandshakeSlap(ev, function() { doneCalls++; });
var overlay = mount.children[0];
var texts = [];
function collectText(el) {
    if (el.textContent) texts.push(el.textContent);
    el.children.forEach(collectText);
}
collectText(overlay);
var beforeImpact = { played: played.length, commits: commits, popups: popupDeltas.length };
var impactTimer = timers.filter(function(t) { return t.delay === 724; })[0];
var finishTimer = timers.filter(function(t) { return t.delay === 1150; })[0];
impactTimer.fn();
var atImpact = {
    played: played.slice(),
    commits: commits,
    popups: popupDeltas.slice(),
    impactClass: overlay.classList.contains('handshake-slap-impact'),
    shaking: screen.classList.contains('handshake-slap-shaking')
};
finishTimer.fn();
console.log(JSON.stringify({
    beforeImpact: beforeImpact,
    impactDelay: impactTimer.delay,
    finishDelay: finishTimer.delay,
    atImpact: atImpact,
    asciiTexts: texts.filter(function(text) { return /^[\x00-\x7F]*$/.test(text); }),
    handChildCount: overlay.children[1].children.length,
    doneCalls: doneCalls,
    overlayCountAfterFinish: mount.children.length
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "beforeImpact": {"played": 0, "commits": 0, "popups": 0},
        "impactDelay": 724,
        "finishDelay": 1150,
        "atImpact": {
            "played": ["slap"],
            "commits": 1,
            "popups": [-10],
            "impactClass": True,
            "shaking": True,
        },
        "asciiTexts": ["SLAP!", "-10 HP"],
        "handChildCount": 2,
        "doneCalls": 1,
        "overlayCountAfterFinish": 0,
    }


def test_handshake_slap_css_tracks_exact_arc_and_accessibility():
    css = (STATIC_DIR / "css" / "04-animations-overlays.css").read_text(
        encoding="utf-8"
    )
    assert "@keyframes handshake-slap-swing" in css
    assert "rotate(20deg)" in css
    assert "62.963%" in css
    assert "rotate(-150deg)" in css
    assert "rotate(-250deg)" in css
    assert "transform-origin: 50% 82%;" in css
    assert "@keyframes handshake-slap-screen-shake" in css
    shake = css.split("@keyframes handshake-slap-screen-shake", 1)[1]
    assert "translate: -8px 3px;" in shake
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".screen.handshake-slap-shaking { animation: none !important; }" in css
    assert "slap:         '/static/sfx/attack_hit.ogg'" in _SRC


def test_leaving_a_match_clears_pinned_tooltip_state():
    reset = extract_function("resetGameClientState")
    assert "gameTooltipPin = null;" in reset
    assert "hideGameTooltip({ force: true })" in reset


def test_game_over_modal_survives_a_final_board_render_exception(tmp_path):
    script = (
        """
var gameState = { winner: null };
var legalActions = [{ action_type: 1 }];
var myPlayerIdx = 0;
var isSpectator = false;
var _gameOverApplied = false;
var shown = 0;
var reset = 0;
var audio = [];
var window = { __pendingGameOverData: { winner: 1 } };
var document = { getElementById: function() { return null; } };
function _resetSpellStageHard() { reset++; }
function renderGame() { throw new Error('final render failed'); }
function playSfx(name) { audio.push(name); }
function showGameOver(data) { shown++; }
"""
        + extract_function("_applyGameOver")
        + """
_applyGameOver({ final_state: { winner: 1, players: [{ hp: -9 }, { hp: 100 }] } });
_applyGameOver({ final_state: { winner: 1, players: [{ hp: -9 }, { hp: 100 }] } });
console.log(JSON.stringify({
    shown: shown,
    reset: reset,
    winner: gameState.winner,
    legalCount: legalActions.length,
    audio: audio
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out == {
        "shown": 1,
        "reset": 1,
        "winner": 1,
        "legalCount": 0,
        "audio": ["defeat"],
    }
    assert "_applyGameOver(eventGameOver)" in extract_function("playGameOver")


def test_game_over_overlay_sits_above_fortune_and_fatigue_layers():
    css = (STATIC_DIR / "css" / "zz-overrides.css").read_text(encoding="utf-8")
    assert "#game-over-overlay { z-index: 20000 !important; }" in css


def test_three_fortune_tiles_fit_the_stage_modal_without_a_scrollbar():
    css = (STATIC_DIR / "css" / "zz-overrides.css").read_text(encoding="utf-8")
    assert "max-height: 100% !important;" in css
    assert "gap: 10px;\n  padding: 8px 12px;" in css
    assert "overflow-x: hidden;" in css
    assert "width: 180px;\n  height: 204px;\n  flex: 0 0 180px;" in css
    # 604px is the real overlay content width: three tiles + two gaps +
    # horizontal padding must all be visible at once.
    assert 3 * 180 + 2 * 10 + 2 * 12 <= 604
    assert ".fortune-reveal-modal {\n  width: 100% !important;\n  max-width: 960px !important;\n  max-height: 100% !important;" in css
    assert "width: min(190px, 100%);\n  height: 225px;" in css


def test_fortune_reward_count_badge_uses_fixed_design_size():
    css = (STATIC_DIR / "css" / "zz-overrides.css").read_text(encoding="utf-8")
    selector = ".fortune-reward-card.tutor-modal-card > .card-count-badge"
    assert selector in css
    rule = css.split(selector, 1)[1].split("}", 1)[0]
    assert "width: 18px !important;" in rule
    assert "height: 18px !important;" in rule
    assert "font-size: 9px !important;" in rule
    assert "var(--mfu)" not in rule, (
        "Fortune reward badges live inside an already scaled duel stage"
    )


def test_move_animation_phases_scale_with_fast_forward(tmp_path):
    script = (
        """
var delays = [];
var doneCalls = 0;
var animatingTiles = {};
var motionVars = {};
var motionStyle = {
    setProperty: function(name, value) { motionVars[name] = value; }
};
var minionEl = {
    classList: { add: function() {} },
    style: { transform: '' }
};
var fromCell = {
    style: { overflow: '', zIndex: '' },
    querySelector: function() { return minionEl; },
    closest: function() { return { style: motionStyle }; }
};
var document = { documentElement: { style: motionStyle } };
function playSfx() {}
function animSpeed() { return 4; }
function getTileDelta() {
    return { dx: 10, dy: 20, fromCell: fromCell, toCell: {} };
}
function applyStateFrame() {}
function renderBoard() {}
var setTimeout = function(fn, delay) { delays.push(delay); fn(); };
"""
        + extract_function("playMoveAnimation")
        + """
playMoveAnimation({
    payload: { from: [1, 2], to: [2, 2] },
    stateAfter: {},
    legalActionsAfter: []
}, function() { doneCalls++; });
console.log(JSON.stringify({
    delays: delays,
    doneCalls: doneCalls,
    motionVars: motionVars
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["delays"] == [30, 88, 33]
    assert out["doneCalls"] == 1
    assert out["motionVars"] == {
        "--move-lift-duration": "30ms",
        "--move-slide-duration": "88ms",
        "--move-drop-duration": "33ms",
    }
    css = (STATIC_DIR / "css" / "04-animations-overlays.css").read_text(
        encoding="utf-8"
    )
    assert "var(--move-lift-duration, 120ms)" in css
    assert "var(--move-slide-duration, 350ms)" in css
    assert "var(--move-drop-duration, 120ms)" in css


def test_deck_builder_lists_default_to_ascending_mana_cost():
    assert "let deckSortField = 'mana';" in _SRC
    assert "(a.card.mana_cost || 0) - (b.card.mana_cost || 0)" in _SRC
    game_html = (STATIC_DIR / "game.html").read_text(encoding="utf-8")
    assert 'id="fsort-field" type="button" title="Cycle sort field">Mana<' in game_html


def test_game_log_retains_the_complete_scrollable_match_history():
    assert "var LOG_DOM_CAP = 400;" not in _SRC
    assert "entries.removeChild(entries.firstChild)" not in _SRC
    assert "if (nearBottom) entries.scrollTop = entries.scrollHeight;" in _SRC


def test_player_game_start_clears_prior_spectator_role(tmp_path):
    script = (
        """
var window = {};
var isSpectator = false;
var spectatorGodMode = false;
var cardDefs, allCardDefs, gameState, myPlayerIdx, legalActions, opponentName;
var roomCode = null;
function cleanupPregameUI() {}
function resetEventQueue() {}
function clearGameLog() {}
function addLogEntry() {}
function hideGameOver() {}
function resetRematchUI() {}
function showScreen() {}
function renderGame() {}
var document = { getElementById: function() { return null; } };
"""
        + extract_function("onGameStart")
        + """
onGameStart({
    card_defs: {}, state: { is_spectator: true, spectator_god_mode: true },
    your_player_idx: 0, legal_actions: [], opponent_name: 'AI One',
    is_spectator: true, player_names: ['AI One', 'AI Two']
});
var watched = { spectator: isSpectator, god: spectatorGodMode,
                names: window.__spectPlayerNames };
onGameStart({
    card_defs: {}, state: {}, your_player_idx: 0,
    legal_actions: [{ action_type: 1 }], opponent_name: 'AI'
});
console.log(JSON.stringify({
    watched: watched,
    playerSpectator: isSpectator,
    playerGod: spectatorGodMode,
    hasSpectatorNames: Object.prototype.hasOwnProperty.call(window, '__spectPlayerNames')
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["watched"]["spectator"] is True
    assert out["watched"]["god"] is True
    assert out["playerSpectator"] is False
    assert out["playerGod"] is False
    assert out["hasSpectatorNames"] is False


def test_player_pregame_clears_prior_spectator_role_before_rps():
    fn = extract_function("onPregameRps")
    assert "isSpectator = false;" in fn
    assert "spectatorGodMode = false;" in fn
    assert "delete window.__spectPlayerNames;" in fn


def test_second_game_pregame_retires_first_game_cards_and_queues(tmp_path):
    script = (
        """
var window = { _pregameActive: false };
var gameState = { turn_number: 88 };
var legalActions = [{ action_type: 1 }];
var selectedHandIdx = 4;
var selectedMinionId = 17;
var interactionMode = 'attack';
var gameTooltipPin = { old: true };
var roomCode = 'KEEP';
var sessionToken = 'KEEP-TOKEN';
var closeCalls = 0;
var resetCalls = 0;
var tooltipCalls = 0;
var nodes = {};
['game-board', 'hand-container', 'oppHandRow', 'hand-action-bar',
 'action-bar-slot'].forEach(function(id) { nodes[id] = { innerHTML: 'OLD' }; });
var document = { getElementById: function(id) { return nodes[id] || null; } };
function closeAllBoardModalsForReset() { closeCalls++; }
function resetEventQueue() { resetCalls++; }
function hideGameTooltip() { tooltipCalls++; }
"""
        + extract_function("_beginPregameClientLifecycle")
        + """
_beginPregameClientLifecycle();
_beginPregameClientLifecycle();
console.log(JSON.stringify({
    active: window._pregameActive,
    closeCalls: closeCalls,
    resetCalls: resetCalls,
    tooltipCalls: tooltipCalls,
    stateCleared: gameState === null,
    legalCount: legalActions.length,
    selections: [selectedHandIdx, selectedMinionId, interactionMode],
    mounts: Object.keys(nodes).map(function(id) { return nodes[id].innerHTML; }),
    roomCode: roomCode,
    sessionToken: sessionToken
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "active": True,
        "closeCalls": 1,
        "resetCalls": 1,
        "tooltipCalls": 1,
        "stateCleared": True,
        "legalCount": 0,
        "selections": [None, None, None],
        "mounts": ["", "", "", "", ""],
        "roomCode": "KEEP",
        "sessionToken": "KEEP-TOKEN",
    }


def test_mulligan_explains_three_card_first_player_and_four_card_second_player():
    modal = extract_function("showMulliganModal")
    assert "data.your_player_idx === 0" in modal
    assert "'Going first' : 'Going second'" in modal
    assert "openingCount = hand.length" in modal


def test_initial_deal_callbacks_are_scoped_to_the_current_game_lifecycle():
    start = extract_function("onGameStart")
    deal = extract_function("animateInitialHandDeal")
    assert "_dealEpoch !== _clientLifecycleEpoch" in start
    assert "dealEpoch !== _clientLifecycleEpoch" in deal


def test_match_tooltips_do_not_show_deck_builder_related_cards():
    assert "populateTooltip(tooltipEl, numericId, { showRelated: false });" in _SRC


def test_mandatory_multi_tutor_requires_all_picks_in_one_menu(tmp_path):
    script = (
        extract_function("_isTutorSelectionComplete")
        + """
console.log(JSON.stringify({
    ratmobileOne: _isTutorSelectionComplete(1, 2, false),
    ratmobileTwo: _isTutorSelectionComplete(2, 2, false),
    conjureOne: _isTutorSelectionComplete(1, 2, true)
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out == {
        "ratmobileOne": False,
        "ratmobileTwo": True,
        "conjureOne": True,
    }
    assert "document.querySelectorAll('#tutor-modal-overlay')" in _SRC


def test_floating_combat_text_uses_unclipped_viewport_portal(tmp_path):
    script = (
        """
var appendedToBody = false;
var appendedToTile = false;
var popup = {
    className: '', textContent: '', style: {}, scrollWidth: 120,
    parentNode: null,
    addEventListener: function() {}
};
var document = {
    createElement: function() { return popup; },
    body: {
        appendChild: function(el) { appendedToBody = true; el.parentNode = this; },
        removeChild: function() {}
    }
};
var window = { innerWidth: 320 };
var tile = {
    getBoundingClientRect: function() {
        return { left: 0, top: 0, width: 40, height: 40 };
    },
    appendChild: function() { appendedToTile = true; }
};
function playSfx() {}
function setTimeout() {}
"""
        + extract_function("showFloatingPopup")
        + """
showFloatingPopup(tile, '\u2694 -10', 'combat-damage');
console.log(JSON.stringify({
    appendedToBody: appendedToBody,
    appendedToTile: appendedToTile,
    className: popup.className,
    left: popup.style.left,
    top: popup.style.top,
    fontSize: popup.style.fontSize
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out == {
        "appendedToBody": True,
        "appendedToTile": False,
        "className": "floating-popup floating-popup-viewport combat-damage",
        "left": "73px",
        "top": "60px",
        "fontSize": "16px",
    }


def test_targeted_react_waits_for_board_pick_before_submit(tmp_path):
    """Sparkfed-style reacts minimise, target, then commit exactly once."""
    script = (
        """
var window = {};
var isSpectator = false;
var sandboxMode = false;
var myPlayerIdx = 0;
var interactionMode = null;
var selectedHandIdx = null;
var selectedMinionId = null;
var selectedDeployPos = null;
var selectedAbilityMinionId = null;
var gameState = {
    phase: 1,
    react_player_idx: 0,
    players: [{hand: [33]}, {hand_count: 0}]
};
var legalActions = [
    {action_type: 5, card_index: 0, target_pos: [0, 0]},
    {action_type: 5, card_index: 0, target_pos: [1, 2]}
];
var submitted = [];
var minimized = [];
var previews = [];
function isBoardModalPeekActive() { return false; }
function canResolvePendingBoardDecisionDuringPeek() { return false; }
function isEventQueueBusy() { return false; }
function isSpellStageAnimating() { return true; }
function isReactWindow() { return true; }
function highlightBoard() {}
function updateHandHighlights() {}
function setSpellStageMinimized(value) { minimized.push(value); }
function previewSpellStageTarget(nid, pos, kind) {
    previews.push({nid: nid, pos: pos, kind: kind});
}
function submitAction(payload) { submitted.push(payload); }
"""
        + extract_function("getLegalReactActions")
        + extract_function("getReactTargetPositions")
        + extract_function("onHandCardClick")
        + extract_function("onBoardCellClick")
        + """
onHandCardClick(0, 0);
var afterCard = {
    submitted: submitted.slice(),
    mode: interactionMode,
    selected: selectedHandIdx,
    minimized: minimized.slice()
};
onBoardCellClick(1, 2);
console.log(JSON.stringify({
    afterCard: afterCard,
    submitted: submitted,
    previews: previews
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "afterCard": {
            "submitted": [],
            "mode": "react_target",
            "selected": 0,
            "minimized": [True],
        },
        "submitted": [
            {"action_type": 5, "card_index": 0, "target_pos": [1, 2]},
        ],
        "previews": [
            {"nid": 33, "pos": [1, 2], "kind": "react"},
        ],
    }
