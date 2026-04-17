"""Tests for Phase 11: Server Foundation & Room System.

Uses Flask-SocketIO's built-in SocketIOTestClient -- no real network.
Covers SERVER-01, SERVER-02, D-01, D-03, D-05, D-06.
"""
import re
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import register_events
from grid_tactics.server.room_manager import RoomManager


@pytest.fixture
def app():
    app = create_app(testing=True)
    library = CardLibrary.from_directory(Path("data/cards"))
    rm = RoomManager(library)
    register_events(rm)
    return app


@pytest.fixture
def client1(app):
    return socketio.test_client(app)


@pytest.fixture
def client2(app):
    return socketio.test_client(app)


# --- SERVER-01: Create room ---


def test_create_room(client1):
    """SERVER-01: create_room returns room_code and session_token."""
    client1.emit("create_room", {"display_name": "Alice"})
    received = client1.get_received()
    assert len(received) >= 1
    msg = next(m for m in received if m["name"] == "room_created")
    data = msg["args"][0]
    assert "room_code" in data
    assert "session_token" in data
    # Room code: 6 chars, uppercase alphanumeric
    assert re.match(r"^[A-Z0-9]{6}$", data["room_code"])
    # Token: UUID4 format
    assert re.match(r"^[0-9a-f]{8}-", data["session_token"])


def test_create_room_no_name(client1):
    """Error on empty display_name."""
    client1.emit("create_room", {"display_name": ""})
    received = client1.get_received()
    msg = next(m for m in received if m["name"] == "error")
    assert "display_name" in msg["args"][0]["msg"].lower()


def test_create_room_no_data(client1):
    """Error when no data provided."""
    client1.emit("create_room", None)
    received = client1.get_received()
    msg = next(m for m in received if m["name"] == "error")
    assert "display_name" in msg["args"][0]["msg"].lower()


def test_create_room_unique_codes(app):
    """Room codes are unique across rooms."""
    codes = set()
    for i in range(20):
        c = socketio.test_client(app)
        c.emit("create_room", {"display_name": f"Player{i}"})
        received = c.get_received()
        msg = next(m for m in received if m["name"] == "room_created")
        codes.add(msg["args"][0]["room_code"])
    assert len(codes) == 20  # all unique


# --- SERVER-02: Join room ---


def test_join_room(client1, client2):
    """SERVER-02: join_room succeeds with valid code."""
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    r2 = client2.get_received()
    msg = next(m for m in r2 if m["name"] == "room_joined")
    data = msg["args"][0]
    assert data["room_code"] == code
    assert "session_token" in data
    assert len(data["players"]) == 2


def test_join_room_creator_notified(client1, client2):
    """Creator receives player_joined when someone joins."""
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    r1_after = client1.get_received()
    joined_msgs = [m for m in r1_after if m["name"] == "player_joined"]
    assert len(joined_msgs) >= 1
    assert joined_msgs[0]["args"][0]["display_name"] == "Bob"


def test_join_invalid_room(client1):
    """SERVER-02: Invalid room code returns error."""
    client1.emit("join_room", {"room_code": "ZZZZZZ", "display_name": "Alice"})
    received = client1.get_received()
    msg = next(m for m in received if m["name"] == "error")
    assert "not found" in msg["args"][0]["msg"].lower()


def test_join_full_room(client1, client2, app):
    """Cannot join a room that already has two players."""
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    client2.get_received()

    client3 = socketio.test_client(app)
    client3.emit("join_room", {"room_code": code, "display_name": "Carol"})
    r3 = client3.get_received()
    msg = next(m for m in r3 if m["name"] == "error")
    assert "full" in msg["args"][0]["msg"].lower()


# --- D-01: Display names ---


def test_display_names_in_room_joined(client1, client2):
    """D-01: Player names appear in room_joined event."""
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    r2 = client2.get_received()
    msg = next(m for m in r2 if m["name"] == "room_joined")
    names = [p["name"] for p in msg["args"][0]["players"]]
    assert "Alice" in names
    assert "Bob" in names


# --- D-05: Ready flow ---


def test_ready_required(client1, client2):
    """D-05: Game does not start until both players ready."""
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    client1.get_received()  # clear
    client2.get_received()  # clear

    # Only creator readies
    client1.emit("ready", {})
    r1 = client1.get_received()
    r2 = client2.get_received()

    # Should see player_ready but NOT game_start
    all_events_1 = [m["name"] for m in r1]
    all_events_2 = [m["name"] for m in r2]
    assert "game_start" not in all_events_1
    assert "game_start" not in all_events_2


def test_full_create_join_ready_flow(client1, client2):
    """SERVER-01 + SERVER-02: Complete flow ending in game_start."""
    # Create
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    # Join
    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    client1.get_received()  # clear player_joined
    client2.get_received()  # clear room_joined

    # Ready up
    client1.emit("ready", {})
    client1.get_received()  # clear player_ready
    client2.get_received()  # clear player_ready

    client2.emit("ready", {})

    # Both should receive game_start
    r1 = client1.get_received()
    r2 = client2.get_received()

    gs1 = [m for m in r1 if m["name"] == "game_start"]
    gs2 = [m for m in r2 if m["name"] == "game_start"]
    assert len(gs1) >= 1, f"Client1 expected game_start, got: {[m['name'] for m in r1]}"
    assert len(gs2) >= 1, f"Client2 expected game_start, got: {[m['name'] for m in r2]}"

    d1 = gs1[0]["args"][0]
    d2 = gs2[0]["args"][0]

    # Verify structure
    assert "your_player_idx" in d1
    assert "state" in d1
    assert "opponent_name" in d1
    assert d1["your_player_idx"] != d2["your_player_idx"]
    assert d1["your_player_idx"] in (0, 1)
    assert d2["your_player_idx"] in (0, 1)


def test_game_start_has_valid_state(client1, client2):
    """game_start contains a valid GameState dict."""
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    client1.get_received()
    client2.get_received()

    client1.emit("ready", {})
    client1.get_received()
    client2.get_received()
    client2.emit("ready", {})

    r1 = client1.get_received()
    gs = next(m for m in r1 if m["name"] == "game_start")
    state = gs["args"][0]["state"]

    assert "board" in state
    assert "players" in state
    assert "active_player_idx" in state
    assert "phase" in state
    assert "turn_number" in state
    assert state["turn_number"] == 1
    assert len(state["players"]) == 2


def test_game_start_opponent_names(client1, client2):
    """D-01: game_start includes opponent_name."""
    client1.emit("create_room", {"display_name": "Alice"})
    r1 = client1.get_received()
    code = next(m for m in r1 if m["name"] == "room_created")["args"][0][
        "room_code"
    ]

    client2.emit("join_room", {"room_code": code, "display_name": "Bob"})
    client1.get_received()
    client2.get_received()

    client1.emit("ready", {})
    client1.get_received()
    client2.get_received()
    client2.emit("ready", {})

    r1 = client1.get_received()
    r2 = client2.get_received()
    gs1 = next(m for m in r1 if m["name"] == "game_start")["args"][0]
    gs2 = next(m for m in r2 if m["name"] == "game_start")["args"][0]

    # Each player sees the OTHER player's name as opponent
    assert gs1["opponent_name"] in ("Alice", "Bob")
    assert gs2["opponent_name"] in ("Alice", "Bob")
    assert gs1["opponent_name"] != gs2["opponent_name"]


# --- D-06: Random first player ---


def test_first_player_random(app):
    """D-06: First player assignment is not always the creator.
    Over 20 games, both assignments should appear."""
    creator_as_p0_count = 0
    for _ in range(20):
        c1 = socketio.test_client(app)
        c2 = socketio.test_client(app)
        c1.emit("create_room", {"display_name": "Alice"})
        r = c1.get_received()
        code = next(m for m in r if m["name"] == "room_created")["args"][0][
            "room_code"
        ]
        tok1 = next(m for m in r if m["name"] == "room_created")["args"][0][
            "session_token"
        ]

        c2.emit("join_room", {"room_code": code, "display_name": "Bob"})
        c1.get_received()
        c2.get_received()

        c1.emit("ready", {})
        c1.get_received()
        c2.get_received()
        c2.emit("ready", {})

        r1 = c1.get_received()
        gs1 = next((m for m in r1 if m["name"] == "game_start"), None)
        if gs1 and gs1["args"][0]["your_player_idx"] == 0:
            creator_as_p0_count += 1
        c1.disconnect()
        c2.disconnect()

    # With random assignment, creator should be P0 roughly 50% of the time
    # Allow wide range: at least 2 and at most 18 out of 20
    assert 2 <= creator_as_p0_count <= 18, (
        f"Creator was P0 in {creator_as_p0_count}/20 games -- not random enough"
    )


# --- D-03: Preset deck ---


def test_preset_deck_valid():
    """D-03: Preset deck matches MIN_DECK_SIZE and passes validate_deck."""
    from grid_tactics.server.preset_deck import PRESET_DECK_COUNTS, get_preset_deck
    from grid_tactics.types import MIN_DECK_SIZE

    library = CardLibrary.from_directory(Path("data/cards"))
    deck = get_preset_deck(library)
    assert len(deck) == MIN_DECK_SIZE
    errors = library.validate_deck(deck)
    assert errors == [], f"Deck validation errors: {errors}"
    assert sum(PRESET_DECK_COUNTS.values()) == MIN_DECK_SIZE
