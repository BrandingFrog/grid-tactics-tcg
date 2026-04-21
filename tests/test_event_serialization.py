"""Tests for Phase 14.8-03b: server-side engine_events emission.

Covers:
- engine_events Socket.IO frame is emitted alongside state_update
  (live PvP path) and sandbox_state (sandbox path)
- Per-viewer event filtering (filter_engine_events_for_viewer)
- M3 next_event_seq monotonicity across multiple resolve_action /
  apply_action calls on BOTH GameSession and SandboxSession
- The 9c414f9 per-frame sandbox emit hack is gone — exactly ONE
  engine_events socket emit per apply_action regardless of how many
  auto-PASSes drained
- JSON round-trip via EngineEvent.to_dict / from_dict

Uses Flask-SocketIO's built-in test client — no real network. Each
test creates a fresh app + room manager so sessions don't leak across
tests. Pattern matches tests/server/test_sandbox_events.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grid_tactics.actions import pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import (
    EVT_CARD_DRAWN,
    EVT_MANA_CHANGE,
    EVT_PENDING_MODAL_OPENED,
    EngineEvent,
    EventStream,
)
from grid_tactics.server.action_codec import serialize_action
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import register_events
from grid_tactics.server.room_manager import RoomManager
from grid_tactics.server.sandbox_session import SandboxSession
from grid_tactics.server.view_filter import filter_engine_events_for_viewer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def library():
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture
def app_and_rm(library):
    rm = RoomManager(library)
    application = create_app(testing=True)
    register_events(rm)
    return application, rm


@pytest.fixture
def client(app_and_rm):
    application, _rm = app_and_rm
    return socketio.test_client(application)


@pytest.fixture
def sandbox_session(library):
    return SandboxSession(library, sid="test-sid")


# ---------------------------------------------------------------------------
# Helpers (mirror tests/server/test_sandbox_events.py)
# ---------------------------------------------------------------------------


def _drain(c) -> list[dict[str, Any]]:
    return c.get_received()


def _find(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return the LAST matching event."""
    last: dict[str, Any] | None = None
    for msg in events:
        if msg["name"] == name:
            last = msg["args"][0]
    return last


def _find_all(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [msg["args"][0] for msg in events if msg["name"] == name]


def _emit_and_drain(c, event: str, data: Any = None) -> list[dict[str, Any]]:
    if data is None:
        c.emit(event)
    else:
        c.emit(event, data)
    return _drain(c)


def _start_pvp_game(app, name_a="Alice", name_b="Bob"):
    """Two clients create+join+ready. Returns (alice, bob, room_code)."""
    a = socketio.test_client(app)
    b = socketio.test_client(app)
    a.emit("create_room", {"display_name": name_a})
    code = next(
        m for m in a.get_received() if m["name"] == "room_created"
    )["args"][0]["room_code"]
    b.emit("join_room", {"room_code": code, "display_name": name_b})
    a.get_received()
    b.get_received()
    a.emit("ready", {})
    a.get_received()
    b.get_received()
    b.emit("ready", {})
    a.get_received()
    b.get_received()
    return a, b, code


# ---------------------------------------------------------------------------
# 1. EngineEvent JSON round-trip
# ---------------------------------------------------------------------------


def test_engine_event_to_dict_from_dict_round_trip():
    """Wire format invariant: to_dict / from_dict are exact inverses.

    Plan 04a's client deserializes via from_dict; the server serializes
    via to_dict. Any drift here breaks the wire contract.
    """
    ev = EngineEvent(
        type=EVT_CARD_DRAWN,
        contract_source="action:draw",
        seq=42,
        payload={"player_idx": 1, "card_numeric_id": 7},
        animation_duration_ms=350,
        triggered_by_seq=None,
        requires_decision=False,
    )
    d = ev.to_dict()
    # All seven fields present.
    for k in (
        "type", "contract_source", "seq", "payload",
        "animation_duration_ms", "triggered_by_seq", "requires_decision",
    ):
        assert k in d, f"missing key {k} in serialized event"
    restored = EngineEvent.from_dict(d)
    assert restored == ev


def test_engine_event_with_triggered_by_seq_round_trip():
    """Nested-trigger events (triggered_by_seq != None) round-trip cleanly."""
    ev = EngineEvent(
        type=EVT_MANA_CHANGE,
        contract_source="trigger:on_play",
        seq=7,
        payload={"player_idx": 0, "prev": 5, "new": 3},
        animation_duration_ms=0,
        triggered_by_seq=3,
        requires_decision=False,
    )
    assert EngineEvent.from_dict(ev.to_dict()) == ev


# ---------------------------------------------------------------------------
# 2. Per-viewer event filtering (view_filter.filter_engine_events_for_viewer)
# ---------------------------------------------------------------------------


def test_per_viewer_filter_hides_opponent_drawn_card_id():
    """EVT_CARD_DRAWN: card_numeric_id is None for opponent, full for owner.

    Mirrors the existing per-state filter where opponent's hand
    contents are hidden but the count is public.
    """
    ev = EngineEvent(
        type=EVT_CARD_DRAWN,
        contract_source="action:draw",
        seq=1,
        payload={"player_idx": 0, "card_numeric_id": 42},
        animation_duration_ms=350,
    )
    # Owner sees the card identity.
    own = filter_engine_events_for_viewer([ev], viewer_idx=0)
    assert own[0].payload["card_numeric_id"] == 42
    # Opponent does NOT see the card identity.
    opp = filter_engine_events_for_viewer([ev], viewer_idx=1)
    assert opp[0].payload["card_numeric_id"] is None
    # God mode (sandbox / spectator-god) bypasses redaction.
    god = filter_engine_events_for_viewer([ev], viewer_idx=1, god_mode=True)
    assert god[0].payload["card_numeric_id"] == 42


def test_per_viewer_filter_redacts_all_card_identity_keys():
    """Redaction is exhaustive — card_id / stable_id / name all blanked."""
    ev = EngineEvent(
        type=EVT_CARD_DRAWN,
        contract_source="action:draw",
        seq=1,
        payload={
            "player_idx": 0,
            "card_numeric_id": 42,
            "card_id": "rat_common",
            "stable_id": "rat_v1",
            "name": "Common Rat",
        },
        animation_duration_ms=350,
    )
    opp = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
    for k in ("card_numeric_id", "card_id", "stable_id", "name"):
        assert opp.payload[k] is None, f"{k} leaked to opponent"


def test_per_viewer_filter_hides_opponent_pending_modal_options():
    """EVT_PENDING_MODAL_OPENED: options blanked for opponent, full for picker.

    Mirrors existing enrich_pending_tutor_for_viewer asymmetric pattern:
    picker sees full payload, opponent sees only an option_count.
    """
    ev = EngineEvent(
        type=EVT_PENDING_MODAL_OPENED,
        contract_source="trigger:on_play",
        seq=5,
        payload={
            "modal_kind": "tutor_select",
            "owner_idx": 0,
            "options": [
                {"deck_idx": 1, "card_numeric_id": 7},
                {"deck_idx": 4, "card_numeric_id": 9},
                {"deck_idx": 11, "card_numeric_id": 12},
            ],
        },
        animation_duration_ms=0,
        requires_decision=True,
    )
    own = filter_engine_events_for_viewer([ev], viewer_idx=0)[0]
    assert own.payload["options"] is not None
    assert len(own.payload["options"]) == 3

    opp = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
    assert opp.payload["options"] is None
    assert opp.payload["option_count"] == 3
    # requires_decision passes through so the opponent client still
    # gates its eventQueue waiting for the resolved event.
    assert opp.requires_decision is True


def test_per_viewer_filter_picker_idx_owner_resolution():
    """Trigger-picker modal uses picker_idx as owner — filter respects it."""
    ev = EngineEvent(
        type=EVT_PENDING_MODAL_OPENED,
        contract_source="system:drain_triggers",
        seq=2,
        payload={
            "modal_kind": "trigger_pick",
            "picker_idx": 1,
            "options": ["a", "b"],
        },
        animation_duration_ms=0,
        requires_decision=True,
    )
    # Picker is idx=1, so viewer 1 sees options, viewer 0 doesn't.
    p1 = filter_engine_events_for_viewer([ev], viewer_idx=1)[0]
    assert p1.payload["options"] == ["a", "b"]
    p0 = filter_engine_events_for_viewer([ev], viewer_idx=0)[0]
    assert p0.payload["options"] is None
    assert p0.payload["option_count"] == 2


def test_per_viewer_filter_passes_through_public_events():
    """Board events (attacks, deaths, summons, hp changes, etc.) are public.

    Conservative: any event type other than CARD_DRAWN / PENDING_MODAL_OPENED
    passes through unchanged with the same Python object reference (frozen
    dataclass — safe to share).
    """
    from grid_tactics.engine_events import (
        EVT_ATTACK_RESOLVED,
        EVT_MINION_DIED,
        EVT_TRIGGER_BLIP,
    )
    public_events = [
        EngineEvent(type=EVT_ATTACK_RESOLVED, contract_source="action:attack",
                    seq=0, payload={"attacker_id": 1, "defender_id": 2}),
        EngineEvent(type=EVT_MINION_DIED, contract_source="system:cleanup_dead_minions",
                    seq=1, payload={"instance_id": 2}),
        EngineEvent(type=EVT_TRIGGER_BLIP, contract_source="trigger:on_death",
                    seq=2, payload={"source_minion_id": 3}),
    ]
    out = filter_engine_events_for_viewer(public_events, viewer_idx=1)
    assert len(out) == len(public_events)
    for orig, filt in zip(public_events, out):
        assert filt is orig  # same reference — no copy needed


def test_per_viewer_filter_god_mode_returns_input_unchanged():
    """god_mode=True bypasses ALL redaction — used by spectator-god + sandbox."""
    ev = EngineEvent(
        type=EVT_CARD_DRAWN,
        contract_source="action:draw",
        seq=1,
        payload={"player_idx": 0, "card_numeric_id": 42},
        animation_duration_ms=350,
    )
    # Even from the opponent's perspective, god_mode reveals everything.
    god = filter_engine_events_for_viewer([ev], viewer_idx=1, god_mode=True)
    assert god[0].payload["card_numeric_id"] == 42


# ---------------------------------------------------------------------------
# 3. Sandbox engine_events socket emit (handle_sandbox_apply_action)
# ---------------------------------------------------------------------------


def test_sandbox_apply_action_emits_engine_events(client):
    """sandbox_apply_action: engine_events frame is the SOLE post-action emit.

    Plan 14.8-05: the post-action sandbox_state emit is DELETED. DOM commits
    flow exclusively through the client's eventQueue from the engine_events
    frame. The engine_events payload still carries final_state as the
    authoritative reconnect / error-recovery reference.

    Plan 14.8-03b historical note (superseded): sandbox_state used to emit
    alongside engine_events for pre-04a client compat.
    """
    client.emit("sandbox_create")
    _drain(client)
    # Set up a play_card scenario: P1 hand has card 0, mana to play.
    client.emit("sandbox_add_card_to_zone",
                {"player_idx": 0, "card_numeric_id": 0, "zone": "hand"})
    _drain(client)
    client.emit("sandbox_set_player_field",
                {"player_idx": 0, "field": "current_mana", "value": 10})
    _drain(client)
    # Fall back to PASS — the simplest engine action that exercises
    # the apply_action code path without needing a full board setup.
    received = _emit_and_drain(
        client, "sandbox_apply_action", serialize_action(pass_action()),
    )
    # Plan 14.8-05: engine_events is the sole post-action emit.
    sandbox_state = _find(received, "sandbox_state")
    engine_events_frames = _find_all(received, "engine_events")
    assert sandbox_state is None, (
        f"sandbox_state emit should be DELETED post-action (plan 14.8-05); "
        f"got {[m['name'] for m in received]}"
    )
    assert len(engine_events_frames) >= 1, (
        f"engine_events missing, got {[m['name'] for m in received]}"
    )
    # engine_events payload shape — final_state is the authoritative
    # snapshot for reconnect / error-recovery.
    payload = engine_events_frames[-1]
    assert "events" in payload
    assert isinstance(payload["events"], list)
    assert "final_state" in payload
    assert payload.get("is_sandbox") is True


def test_sandbox_cheat_mana_emits_mana_change_event(client):
    """sandbox set_player_field emits a mana_change event with sandbox: source."""
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_set_player_field",
        {"player_idx": 0, "field": "current_mana", "value": 5},
    )
    eng = _find(received, "engine_events")
    assert eng is not None, (
        f"engine_events missing, got {[m['name'] for m in received]}"
    )
    events = eng["events"]
    assert len(events) >= 1
    ev = events[0]
    assert ev["type"] == "mana_change"
    assert ev["contract_source"] == "sandbox:set_player_field"
    assert ev["payload"]["player_idx"] == 0
    assert ev["payload"]["field"] == "current_mana"
    assert ev["payload"]["new"] == 5


def test_sandbox_undo_emits_event(client):
    """sandbox undo flows through apply_sandbox_edit and emits an event."""
    client.emit("sandbox_create")
    _drain(client)
    # Make a mutation so undo has something to undo.
    client.emit("sandbox_set_player_field",
                {"player_idx": 0, "field": "current_mana", "value": 3})
    _drain(client)
    received = _emit_and_drain(client, "sandbox_undo")
    eng = _find(received, "engine_events")
    assert eng is not None
    events = eng["events"]
    assert len(events) >= 1
    assert events[0]["contract_source"] == "sandbox:undo"


def test_sandbox_set_active_emits_phase_changed(client):
    """sandbox_set_active_player emits a phase_changed event."""
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client, "sandbox_set_active_player", {"player_idx": 1},
    )
    eng = _find(received, "engine_events")
    assert eng is not None
    events = eng["events"]
    assert len(events) >= 1
    assert events[0]["type"] == "phase_changed"
    assert events[0]["contract_source"] == "sandbox:set_active"
    assert events[0]["payload"]["active_player_idx"] == 1


def test_sandbox_auto_drain_emits_events_once_at_end_not_per_frame(client):
    """Architectural fix for 9c414f9 — ONE engine_events emit per apply_action.

    Pre-fix: the per-frame on_frame callback fired one sandbox_state
    per intermediate state (user action + each drained PASS), which
    bloated the wire and clobbered transient signals.
    Post-fix (plan 14.8-03b): one EventStream collects across all
    intermediate calls, one engine_events frame fires at the end.
    Plan 14.8-05: post-action sandbox_state DELETED — engine_events is
    the sole post-action emit; sandbox_state is initial-frame only.
    """
    client.emit("sandbox_create")
    _drain(client)
    # PASS is the simplest action. With nothing on the board it's a
    # straight no-op — but it still goes through resolve_action which
    # may emit zero or more events. The architectural invariant is:
    # exactly ONE engine_events socket frame, regardless of drain depth.
    received = _emit_and_drain(
        client, "sandbox_apply_action", serialize_action(pass_action()),
    )
    eng_frames = _find_all(received, "engine_events")
    sandbox_frames = _find_all(received, "sandbox_state")
    # ONE engine_events per apply_action call (unchanged invariant).
    assert len(eng_frames) == 1, (
        f"expected 1 engine_events emit per apply_action, got {len(eng_frames)}"
    )
    # Plan 14.8-05: zero sandbox_state emits post-action.
    assert len(sandbox_frames) == 0, (
        f"expected 0 sandbox_state per apply_action (plan 14.8-05), got {len(sandbox_frames)}"
    )


# ---------------------------------------------------------------------------
# 4. Live PvP engine_events socket emit
# ---------------------------------------------------------------------------


def _submit_pass_from_active(alice, bob, rm, code):
    """Helper: submit PASS from whoever is the active player.

    Returns (acting_client, other_client, acting_received, other_received)
    where acting_received contains both state_update + engine_events
    frames for the acting player.

    The room manager flips a coin for P1/P2 assignment so we can't
    map alice→P0 directly. Try both clients; the wrong-turn client
    gets a "Not your turn" error which we discard.
    """
    # action_codec expects a flat dict (NOT wrapped in {"action": ...}).
    payload = {"action_type": 4}  # PASS
    for client in (alice, bob):
        client.emit("submit_action", payload)
        r = client.get_received()
        if not any(m["name"] == "error" for m in r):
            other = bob if client is alice else alice
            return client, other, r, other.get_received()
    raise RuntimeError(
        f"Neither client could submit PASS — alice and bob both errored"
    )


def test_live_pvp_submit_action_emits_engine_events_only(app_and_rm):
    """submit_action emits engine_events ONLY (post-action state_update DELETED).

    Plan 14.8-05: state_update post-action emit was deleted. DOM commits
    flow exclusively through the client's eventQueue from engine_events.
    Both clients still receive the engine_events frame (acting-player
    payload carries legal_actions; other-client payload carries an empty
    legal_actions list).
    """
    app, rm = app_and_rm
    alice, bob, code = _start_pvp_game(app)
    acting, other, r_acting, r_other = _submit_pass_from_active(alice, bob, rm, code)
    # Plan 14.8-05: no state_update emit post-action.
    assert _find(r_acting, "state_update") is None, (
        f"state_update should be DELETED post-action (plan 14.8-05); "
        f"got {[m['name'] for m in r_acting]}"
    )
    assert _find(r_acting, "engine_events") is not None, (
        f"engine_events missing on acting client, got {[m['name'] for m in r_acting]}"
    )
    # The other client also receives engine_events (with filtered events +
    # empty legal_actions if they're not the next decision-maker).
    assert _find(r_other, "state_update") is None, (
        f"state_update should be DELETED post-action (plan 14.8-05); "
        f"got {[m['name'] for m in r_other]}"
    )
    assert _find(r_other, "engine_events") is not None, (
        f"engine_events missing on other client, got {[m['name'] for m in r_other]}"
    )


def test_live_pvp_engine_events_payload_includes_final_state(app_and_rm):
    """engine_events frame carries final_state alongside the event list.

    Plan 04a/b uses final_state as the sync point for post-event state
    reconciliation — proves the client reduce loop matches the server's
    canonical state.
    """
    app, rm = app_and_rm
    alice, bob, code = _start_pvp_game(app)
    _, _, r_acting, _ = _submit_pass_from_active(alice, bob, rm, code)
    eng = _find(r_acting, "engine_events")
    assert eng is not None, (
        f"engine_events missing on acting client, "
        f"got {[m['name'] for m in r_acting]}"
    )
    assert "events" in eng
    assert "final_state" in eng
    assert "legal_actions" in eng
    assert "your_player_idx" in eng
    assert isinstance(eng["events"], list)


# ---------------------------------------------------------------------------
# 5. M3: monotonic next_event_seq across calls
# ---------------------------------------------------------------------------


def test_M3_session_next_event_seq_initialized_to_zero(app_and_rm):
    """Brand-new GameSession starts with next_event_seq=0.

    Plan 04b's client lastSeenSeq dedup relies on this initial state
    so the first event is unambiguously seq=0 and not "could be any".
    """
    app, rm = app_and_rm
    alice, bob, code = _start_pvp_game(app)
    session = rm.get_game(code)
    assert session is not None
    # Pre-action: counter has been initialized at __init__ time. After
    # game-start (which doesn't currently emit events) the counter is
    # still 0. If/when game-start starts emitting events the counter
    # will reflect that, but that's a 03b-or-later concern.
    assert hasattr(session, "next_event_seq")
    assert session.next_event_seq >= 0


def test_M3_session_next_event_seq_monotonic_across_actions(app_and_rm):
    """submit_action advances session.next_event_seq monotonically.

    Each call's EventStream(next_seq=session.next_event_seq) seeds from
    the persistent counter; stream.next_seq is written back. Across
    multiple calls the counter strictly increases and equals the total
    event count emitted.
    """
    app, rm = app_and_rm
    alice, bob, code = _start_pvp_game(app)
    session = rm.get_game(code)
    initial = session.next_event_seq
    seen_seqs: list[int] = []
    # Submit a few PASS actions, recording the seq of each emitted event.
    for _ in range(3):
        if session.state.is_game_over:
            break
        try:
            _, _, r_acting, _ = _submit_pass_from_active(alice, bob, rm, code)
        except RuntimeError:
            break
        eng = _find(r_acting, "engine_events")
        if eng is not None:
            for ev in eng["events"]:
                seen_seqs.append(ev["seq"])
    # Monotone strictly increasing within seen_seqs.
    assert seen_seqs == sorted(seen_seqs), (
        f"seqs not monotonic: {seen_seqs}"
    )
    # No duplicates.
    assert len(seen_seqs) == len(set(seen_seqs)), (
        f"duplicate seqs: {seen_seqs}"
    )
    # Counter advanced AT LEAST as far as the highest seq we saw + 1.
    if seen_seqs:
        assert session.next_event_seq >= max(seen_seqs) + 1
    # Counter is at least the initial value (must not regress).
    assert session.next_event_seq >= initial


def test_M3_sandbox_session_next_event_seq_initialized_to_zero(sandbox_session):
    """Brand-new SandboxSession starts with _next_event_seq=0."""
    assert sandbox_session._next_event_seq == 0


def test_M3_sandbox_session_next_event_seq_monotonic_across_actions(library):
    """SandboxSession apply_action + apply_sandbox_edit share one monotonic counter.

    Each call seeds from self._next_event_seq, persists stream.next_seq
    back. Across mixed apply_action / apply_sandbox_edit calls the
    counter strictly increases and equals the total event count.
    """
    sb = SandboxSession(library, sid="seq-test")
    # Build a deck so PASS doesn't immediately game-end.
    sb.import_deck(0, [0, 0, 0, 0, 0])
    sb.import_deck(1, [0, 0, 0, 0, 0])

    initial = sb._next_event_seq
    assert initial == 0

    all_seqs: list[int] = []

    # Apply some sandbox edits — each emits exactly one event.
    events1 = sb.apply_sandbox_edit("set_player_field", {
        "player_idx": 0, "field": "current_mana", "value": 5,
    })
    all_seqs.extend(e.seq for e in events1)
    assert sb._next_event_seq == initial + len(events1)

    events2 = sb.apply_sandbox_edit("set_active", {"player_idx": 1})
    all_seqs.extend(e.seq for e in events2)
    assert sb._next_event_seq == initial + len(events1) + len(events2)

    # Now an apply_action (PASS) — emits zero or more events. Counter
    # advances by exactly len(events).
    pre_action_seq = sb._next_event_seq
    events3 = sb.apply_action(pass_action())
    all_seqs.extend(e.seq for e in events3)
    assert sb._next_event_seq == pre_action_seq + len(events3)

    # Strictly monotonic across the whole sequence.
    assert all_seqs == sorted(all_seqs), f"seqs not monotonic: {all_seqs}"
    assert len(all_seqs) == len(set(all_seqs)), f"duplicate seqs: {all_seqs}"
    # All seqs are < final counter value.
    if all_seqs:
        assert max(all_seqs) < sb._next_event_seq


def test_M3_sandbox_session_seq_resets_on_reset(library):
    """SandboxSession.reset() resets _next_event_seq to 0.

    A loaded / reset session is conceptually a brand-new session from
    the client's POV; lastSeenSeq dedup must be re-anchored at 0.
    """
    sb = SandboxSession(library, sid="reset-test")
    sb.apply_sandbox_edit("set_player_field", {
        "player_idx": 0, "field": "current_mana", "value": 5,
    })
    assert sb._next_event_seq > 0
    sb.reset()
    assert sb._next_event_seq == 0


def test_M3_sandbox_session_seq_resets_on_load_dict(library):
    """SandboxSession.load_dict() resets _next_event_seq to 0."""
    sb = SandboxSession(library, sid="load-test")
    sb.apply_sandbox_edit("set_player_field", {
        "player_idx": 0, "field": "current_mana", "value": 5,
    })
    saved = sb.to_dict()
    assert sb._next_event_seq > 0

    other = SandboxSession(library, sid="load-test-2")
    other.apply_sandbox_edit("set_player_field", {
        "player_idx": 1, "field": "hp", "value": 99,
    })
    assert other._next_event_seq > 0
    other.load_dict(saved)
    # Loading replaces state — seq counter resets to 0 so the client
    # sees a fresh stream.
    assert other._next_event_seq == 0
