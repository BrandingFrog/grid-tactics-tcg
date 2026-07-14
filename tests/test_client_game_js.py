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
var window = { __pendingGameOverData: { winner: 1 } };
var slotState = {
    spellStageChain: [{}], pendingModalKind: 'tutor_select',
    pendingModalDeadline: 999, lastOriginator: {}, pendingStageOriginator: {},
    prevDispatchedEvent: {}, lastDispatchedEvent: {}
};
var resetCalls = 0;
var logClears = 0;
function _resetSpellStageHard() { resetCalls++; }
function clearGameLog() { logClears++; }
"""
        + extract_function("resetEventQueue")
        + """
resetEventQueue();
console.log(JSON.stringify({
    queue: eventQueue.length,
    pending: window.__pendingGameOverData || null,
    applied: _gameOverApplied,
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
    assert "FORTUNE RATE:" in _SRC
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
    # Fortune uses the same roomy shell and minimise/restore convention as Tutor.
    assert "function _attachFortuneMinimizeButton" in _SRC
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
    helper = extract_function("_attachFortuneMinimizeButton")
    assert "trigger-picker-restore-pill" in trigger
    assert "fan.className = 'tutor-modal-cards'" in revive
    assert "reviveAccept.className = 'tutor-accept-button'" in revive
    assert "tile.classList.add('tutor-card-selected')" in revive
    assert "tile.addEventListener('focus', inspectReviveCard)" in revive
    assert "showGameTooltip(match.card_numeric_id" in revive
    revive_highlights = extract_function("highlightReviveCells")
    assert "Array.isArray(legalActions)" in revive_highlights
    assert "window.legalActions" not in revive_highlights
    assert "'Minimise ' + (resumeLabel || 'Fortune') + ' window'" in helper


def test_minimised_decision_survives_the_other_modal_cleanup(tmp_path):
    """Every render syncs both decision modals, including the inactive one."""
    script = (
        """
var nodes = {};
function makeElement(tag) {
    return {
        tagName: tag, id: '', className: '', textContent: '', title: '',
        style: {}, children: [], parentNode: null, listeners: {},
        setAttribute: function() {},
        addEventListener: function(name, fn) { this.listeners[name] = fn; },
        appendChild: function(child) {
            child.parentNode = this;
            this.children.push(child);
            if (child.id) nodes[child.id] = child;
            return child;
        },
        removeChild: function(child) {
            this.children = this.children.filter(function(x) { return x !== child; });
            child.parentNode = null;
            if (child.id) delete nodes[child.id];
        },
        remove: function() {
            if (this.parentNode) this.parentNode.removeChild(this);
            else if (this.id) delete nodes[this.id];
        }
    };
}
var document = {
    createElement: makeElement,
    getElementById: function(id) { return nodes[id] || null; }
};
var mount = makeElement('mount');
function _stageMount() { return mount; }
function minimise(kind, id) {
    var header = makeElement('header');
    var overlay = makeElement('overlay');
    mount.appendChild(overlay);
    _attachFortuneMinimizeButton(header, overlay, kind, id);
    header.children[0].listeners.click({ stopPropagation: function() {} });
    return overlay;
}
"""
        + extract_function("_attachFortuneMinimizeButton")
        + extract_function("closeRoguelikeEventModal")
        + extract_function("closeMarkedCardsModal")
        + """
var fortuneOverlay = minimise('Fortune', 'fortune-restore-pill');
closeMarkedCardsModal();
var fortuneSurvived = !!document.getElementById('fortune-restore-pill');
document.getElementById('fortune-restore-pill').listeners.click();
var fortuneRestored = fortuneOverlay.style.display === '';

var markedOverlay = minimise('Marked Cards', 'marked-cards-restore-pill');
closeRoguelikeEventModal();
var markedSurvived = !!document.getElementById('marked-cards-restore-pill');
document.getElementById('marked-cards-restore-pill').listeners.click();
var markedRestored = markedOverlay.style.display === '';

console.log(JSON.stringify({
    fortuneSurvived: fortuneSurvived,
    fortuneRestored: fortuneRestored,
    markedSurvived: markedSurvived,
    markedRestored: markedRestored
}));
"""
    )
    assert run_js(tmp_path, script) == {
        "fortuneSurvived": True,
        "fortuneRestored": True,
        "markedSurvived": True,
        "markedRestored": True,
    }


def test_pinned_minion_paints_attack_footprint_even_without_action_permission(tmp_path):
    script = (
        """
var painted = [];
var gameState = { minions: [{
    instance_id: 7,
    card_numeric_id: 101,
    position: [2, 2]
}] };
var cardDefs = { 101: { attack_range: 1 } };
var document = {
    querySelector: function(selector) {
        return { classList: { add: function(name) {
            painted.push({ selector: selector, name: name });
        } } };
    }
};
"""
        + extract_function("_paintAttackRangeFootprint")
        + """
_paintAttackRangeFootprint(7);
console.log(JSON.stringify({
    count: painted.length,
    classes: painted.map(function(x) { return x.name; }),
    selectors: painted.map(function(x) { return x.selector; })
}));
"""
    )
    out = run_js(tmp_path, script)
    assert out["count"] == 12
    assert set(out["classes"]) == {"attack-range-footprint"}
    assert '.board-cell[data-row="2"][data-col="2"]' not in out["selectors"]
    highlight = extract_function("highlightBoard")
    assert highlight.index("_paintAttackRangeFootprint(inspectedMinionId)") < highlight.index(
        "if (!_pendingMode && typeof canActNow"
    )
    pin_setup = extract_function("setupGameTooltipPin")
    assert "}, true);" in pin_setup, "minion inspection must run before board-cell rendering"


def test_leaving_a_match_clears_pinned_minion_inspection_state():
    reset = extract_function("resetGameClientState")
    assert "inspectedMinionId = null;" in reset
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
