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
var eventRunning = false;
var _drainFinalApplied = false;
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
function _commitFinalStateSnapshot(fs) { commitCalls++; }
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
var slotState = { spellStageChain: [] };
var _spellStage = { chain: [], resolving: false };
var _spellStageBusy = false;
var _spellStageQueue = [];
function _spellStageOnReactClosed() { resolveKicks++; }
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


# ---------------------------------------------------------------------------
# Fix 7: playCardDrawn targets the real new hand slot
# ---------------------------------------------------------------------------

def test_card_drawn_appends_to_live_hand_and_targets_new_slot(tmp_path):
    script = (
        """
var sandboxMode = false;
var sandboxState = null;
var myPlayerIdx = 0;
var gameState = { players: [ { hand: [10, 11, 12] }, { hand: [] } ] };
var window = { __lastFinalState:
    { players: [ { hand: [10, 11, 12, 33] }, { hand: [] } ] } };
var jobs = [];
var renderHandCalls = 0;
function renderHand() { renderHandCalls++; }
function updateHandHighlights() {}
function enqueueAnimation(job) { jobs.push(job); }
function _evDurationOr(ev, fb) { return fb; }
function animSpeed() { return 1; }
var isSpectator = false;
// Zero-delay callbacks (the non-spectator reveal wrapper) run inline;
// real pacing timers stay suppressed.
var setTimeout = function(fn, d) { if (!d) fn(); };
"""
        + extract_function("playCardDrawn")
        + """
var ev = { payload: { player_idx: 0, card_numeric_id: 33 } };
playCardDrawn(ev, function() {});
var firstSlot = jobs[0].toSlotIndex;
var handAfterFirst = gameState.players[0].hand.slice();
// Replay with hand already at final-state length: must NOT double-append.
playCardDrawn(ev, function() {});
console.log(JSON.stringify({
    firstSlot: firstSlot,
    handAfterFirst: handAfterFirst,
    handAfterSecond: gameState.players[0].hand,
    secondSlot: jobs[1].toSlotIndex,
    renderHandCalls: renderHandCalls,
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["handAfterFirst"] == [10, 11, 12, 33], (
        "drawn card must be appended to the live hand before the fly-in"
    )
    assert out["firstSlot"] == 3, (
        "fly-in must target the NEW slot, not fall back to the pre-draw last card"
    )
    assert out["handAfterSecond"] == [10, 11, 12, 33], (
        "final-state hand length must cap the append (no double-append)"
    )
    assert out["secondSlot"] == -1
    assert out["renderHandCalls"] == 1
