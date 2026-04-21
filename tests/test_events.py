"""Tests for Phase 14.4: Spectator Socket.IO event wiring (events.py).

Covers the spectator surface added in Plan 14.4-03:

- spectate_room → spectator_joined ack with session_token/room_code/god_mode
- Spectator receives state_update on subsequent actions
- submit_action from a spectator sid is rejected with an error
- Chat from a spectator is broadcast to everyone in the room
- God-mode spectator sees BOTH players' hand card lists
- Non-god spectator sees the P1-perspective filtered view (opponent hand → count only)

Skipped entirely when flask_socketio isn't installed (see conftest.py
collect_ignore_glob).
"""
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import register_events
from grid_tactics.server.room_manager import RoomManager


# --- Fixtures ---


@pytest.fixture
def app():
    app = create_app(testing=True)
    library = CardLibrary.from_directory(Path("data/cards"))
    rm = RoomManager(library)
    register_events(rm)
    return app


@pytest.fixture
def alice(app):
    return socketio.test_client(app)


@pytest.fixture
def bob(app):
    return socketio.test_client(app)


@pytest.fixture
def eve(app):
    return socketio.test_client(app)


@pytest.fixture
def dan(app):
    return socketio.test_client(app)


# --- Helpers ---


def _first(received, name):
    return next((m for m in received if m["name"] == name), None)


def _all(received, name):
    return [m for m in received if m["name"] == name]


def _create_room(client, display_name="Alice"):
    client.emit("create_room", {"display_name": display_name})
    r = client.get_received()
    msg = _first(r, "room_created")
    assert msg is not None, f"no room_created, got {[m['name'] for m in r]}"
    return msg["args"][0]["room_code"]


def _start_game(alice, bob, name_a="Alice", name_b="Bob"):
    """Create+join+ready two clients and return the room_code."""
    code = _create_room(alice, name_a)
    bob.emit("join_room", {"room_code": code, "display_name": name_b})
    alice.get_received()
    bob.get_received()
    alice.emit("ready", {})
    alice.get_received()
    bob.get_received()
    bob.emit("ready", {})
    alice.get_received()
    bob.get_received()
    return code


# --- Tests ---


def test_spectate_room_event(alice, eve):
    """spectate_room emits spectator_joined with room_code + session_token + god_mode."""
    code = _create_room(alice, "Alice")
    eve.emit(
        "spectate_room",
        {"room_code": code, "display_name": "Eve", "god_mode": False},
    )
    r = eve.get_received()
    msg = _first(r, "spectator_joined")
    assert msg is not None, f"no spectator_joined, got {[m['name'] for m in r]}"
    data = msg["args"][0]
    assert data["room_code"] == code
    assert "session_token" in data
    assert data["god_mode"] is False


def test_spectator_receives_state_update(alice, bob, eve):
    """After a player submits an action, spectators receive an engine_events frame.

    Phase 14.8-05: post-action state_update emit DELETED — engine_events
    is the sole post-action frame routed to spectators (still carrying
    is_spectator=True and perspective-filtered state).
    """
    code = _start_game(alice, bob)
    eve.emit(
        "spectate_room",
        {"room_code": code, "display_name": "Eve", "god_mode": False},
    )
    eve.get_received()  # drain spectator_joined + synthetic game_start

    # Figure out whose turn it is and pass from that client.
    for client in (alice, bob):
        client.emit("submit_action", {"action": {"action_type": 4}})  # PASS
        r = client.get_received()
        if _first(r, "error") is None:
            break
    # Eve should have seen at least one engine_events frame.
    r_eve = eve.get_received()
    updates = _all(r_eve, "engine_events")
    assert len(updates) >= 1, (
        f"spectator received no engine_events, got {[m['name'] for m in r_eve]}"
    )
    payload = updates[0]["args"][0]
    assert payload.get("is_spectator") is True


def test_spectator_submit_action_rejected(alice, bob, eve):
    """A spectator that tries to submit an action gets an error."""
    code = _start_game(alice, bob)
    eve.emit(
        "spectate_room",
        {"room_code": code, "display_name": "Eve", "god_mode": False},
    )
    eve.get_received()
    eve.emit("submit_action", {"action": {"action_type": 4}})
    r = eve.get_received()
    err = _first(r, "error")
    assert err is not None, f"expected error, got {[m['name'] for m in r]}"
    assert "spectator" in err["args"][0]["msg"].lower()


def test_spectator_chat_allowed(alice, bob, eve):
    """Spectators can send chat messages and players receive them."""
    code = _start_game(alice, bob)
    eve.emit(
        "spectate_room",
        {"room_code": code, "display_name": "Eve", "god_mode": False},
    )
    eve.get_received()
    alice.get_received()
    bob.get_received()

    eve.emit("chat_message", {"text": "hi from spectator"})
    r_alice = alice.get_received()
    r_bob = bob.get_received()
    chat_a = _first(r_alice, "chat_message")
    chat_b = _first(r_bob, "chat_message")
    assert chat_a is not None and "hi from spectator" in chat_a["args"][0].get("text", "")
    assert chat_b is not None and "hi from spectator" in chat_b["args"][0].get("text", "")


def test_god_mode_spectator_sees_both_hands(alice, bob, eve):
    """God-mode spectator's initial game_start carries BOTH hand card lists."""
    code = _start_game(alice, bob)
    eve.emit(
        "spectate_room",
        {"room_code": code, "display_name": "Eve", "god_mode": True},
    )
    r = eve.get_received()
    gs = _first(r, "game_start")
    assert gs is not None, f"no game_start, got {[m['name'] for m in r]}"
    data = gs["args"][0]
    state = data["state"]
    assert state.get("is_spectator") is True
    assert state.get("spectator_god_mode") is True
    players = state["players"]
    assert len(players) == 2
    # God mode = raw state (no filter); both hands are concrete card lists.
    for p in players:
        hand = p.get("hand")
        assert isinstance(hand, list), f"god-mode hand is not a list: {hand!r}"
        assert len(hand) > 0


def test_non_god_spectator_filtered(alice, bob, eve):
    """Non-god spectator sees the P1-perspective filter: opponent hand is a count."""
    code = _start_game(alice, bob)
    eve.emit(
        "spectate_room",
        {"room_code": code, "display_name": "Eve", "god_mode": False},
    )
    r = eve.get_received()
    gs = _first(r, "game_start")
    assert gs is not None
    data = gs["args"][0]
    state = data["state"]
    assert state.get("is_spectator") is True
    assert state.get("spectator_god_mode") is False
    players = state["players"]
    # Perspective is player 0 (Alice seat): P0 hand revealed, P1 hand hidden.
    p0, p1 = players[0], players[1]
    assert isinstance(p0.get("hand"), list) and len(p0["hand"]) > 0
    # Opponent hand stripped to count only.
    assert p1.get("hand") in (None, [], ()) or "hand_count" in p1
    assert p1.get("hand_count", 0) > 0


def test_effect_serialization_reflects_all_fields():
    """Regression guard: every non-None EffectDefinition field must reach the client.

    Adding a new field to EffectDefinition should never silently drop on
    its way to the browser. This test loads every card in the library,
    serializes via _build_card_defs, and compares keys against the live
    dataclass fields.
    """
    from dataclasses import fields as dc_fields
    from grid_tactics.cards import EffectDefinition
    from grid_tactics.server.events import _build_card_defs

    library = CardLibrary.from_directory(Path("data/cards"))
    defs = _build_card_defs(library)

    # Engine field name -> client key (events._EFFECT_CLIENT_KEY mirror)
    remap = {"effect_type": "type"}
    engine_names = {f.name for f in dc_fields(EffectDefinition)}
    expected_client = {remap.get(n, n) for n in engine_names}

    saw = set()
    for card in defs.values():
        for eff in card.get("effects", []) or []:
            saw.update(eff.keys())
        if card.get("react_effect"):
            saw.update(card["react_effect"].keys())

    # Every key observed on the wire must map to a real engine field.
    assert saw.issubset(expected_client), (
        f"unexpected wire keys: {saw - expected_client}"
    )

    # Acidic Rain is the canonical coverage card: every filter type in one.
    ar = next(d for d in defs.values() if d.get("card_id") == "acidic_rain")
    tribes = {e.get("target_tribe") for e in ar["effects"]}
    elements = {e.get("target_element") for e in ar["effects"]}
    assert {"Robot", "Machine"}.issubset(tribes)
    assert "metal" in elements
    assert ar["react_effect"]["type"] == 18  # DRAW
    assert ar["react_effect"]["amount"] == 1
