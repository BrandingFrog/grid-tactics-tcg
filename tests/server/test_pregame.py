"""Socket-flow tests for the PREGAME stage (user 2026-07-08).

Rock-paper-scissors decides who goes first (winner becomes ENGINE PLAYER
INDEX 0), then both players may mulligan, then the normal game_start
broadcast runs followed by one engine_events batch of
EVT_CARD_DRAWN(source='mulligan') per replacement card.

The suite-wide default is GRID_TACTICS_PREGAME=0 (tests/conftest.py), so
every test here re-enables via monkeypatching the module attribute.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.server import events as events_mod
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import register_events
from grid_tactics.server.room_manager import RoomManager


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(events_mod, "PREGAME_ENABLED", True)
    application = create_app(testing=True)
    library = CardLibrary.from_directory(Path("data/cards"))
    rm = RoomManager(library)
    register_events(rm)
    application.config["TEST_ROOM_MANAGER"] = rm
    return application


@pytest.fixture
def alice(app):
    return socketio.test_client(app)


@pytest.fixture
def bob(app):
    return socketio.test_client(app)


def _first(received, name):
    return next((m for m in received if m["name"] == name), None)


def _all(received, name):
    return [m for m in received if m["name"] == name]


def _ready_both(alice, bob):
    """create+join+ready both clients; returns the room code. Under
    PREGAME_ENABLED this parks both players in the RPS stage."""
    alice.emit("create_room", {"display_name": "Alice"})
    code = _first(alice.get_received(), "room_created")["args"][0]["room_code"]
    bob.emit("join_room", {"room_code": code, "display_name": "Bob"})
    alice.get_received()
    bob.get_received()
    alice.emit("ready", {})
    alice.get_received()
    bob.get_received()
    bob.emit("ready", {})
    return code


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ready_enters_rps_not_game_start(alice, bob):
    _ready_both(alice, bob)
    r_a = alice.get_received()
    r_b = bob.get_received()
    assert _first(r_a, "pregame_rps") is not None
    assert _first(r_b, "pregame_rps") is not None
    assert _first(r_a, "game_start") is None
    assert _first(r_b, "game_start") is None
    rps_a = _first(r_a, "pregame_rps")["args"][0]
    assert rps_a["opponent_name"] == "Bob"
    assert rps_a["already_picked"] is None


def test_rps_winner_becomes_player_zero_and_mulligan_hands(alice, bob):
    _ready_both(alice, bob)
    alice.get_received()
    bob.get_received()

    alice.emit("rps_pick", {"pick": "rock"})
    assert _all(alice.get_received(), "rps_result") == []  # waiting on Bob
    bob.emit("rps_pick", {"pick": "scissors"})

    r_a = alice.get_received()
    r_b = bob.get_received()
    res_a = _first(r_a, "rps_result")["args"][0]
    res_b = _first(r_b, "rps_result")["args"][0]
    assert res_a == {
        "tie": False, "your_pick": "rock", "opp_pick": "scissors",
        "you_go_first": True,
    }
    assert res_b["you_go_first"] is False
    assert res_b["your_pick"] == "scissors"

    # Winner (Alice) is engine P0 -> dealt STARTING_HAND_P1=3; Bob gets 4.
    mull_a = _first(r_a, "pregame_mulligan")["args"][0]
    mull_b = _first(r_b, "pregame_mulligan")["args"][0]
    assert mull_a["your_player_idx"] == 0
    assert mull_b["your_player_idx"] == 1
    assert len(mull_a["hand"]) == 3
    assert len(mull_b["hand"]) == 4
    assert mull_a["opponent_count"] == 4
    assert mull_b["opponent_count"] == 3


def test_rps_tie_replays_round(alice, bob):
    _ready_both(alice, bob)
    alice.get_received()
    bob.get_received()

    alice.emit("rps_pick", {"pick": "paper"})
    bob.emit("rps_pick", {"pick": "paper"})
    r_a = alice.get_received()
    res_a = _first(r_a, "rps_result")["args"][0]
    assert res_a["tie"] is True
    assert _first(r_a, "pregame_mulligan") is None
    bob.get_received()

    # Replay round works: picks were reset server-side.
    alice.emit("rps_pick", {"pick": "scissors"})
    bob.emit("rps_pick", {"pick": "paper"})
    r_a2 = alice.get_received()
    res_a2 = _first(r_a2, "rps_result")["args"][0]
    assert res_a2["tie"] is False
    assert res_a2["you_go_first"] is True


def test_rps_pick_only_counts_once_per_seat(alice, bob):
    _ready_both(alice, bob)
    alice.get_received()
    bob.get_received()

    alice.emit("rps_pick", {"pick": "rock"})
    alice.get_received()
    # Second pick from the same seat is ignored (no error, no resolution).
    alice.emit("rps_pick", {"pick": "paper"})
    r_a = alice.get_received()
    assert _first(r_a, "rps_result") is None
    bob.emit("rps_pick", {"pick": "scissors"})
    res_a = _first(alice.get_received(), "rps_result")["args"][0]
    # Alice's FIRST pick (rock) stood.
    assert res_a["your_pick"] == "rock"
    assert res_a["you_go_first"] is True


def test_mulligan_flow_and_replacement_events(alice, bob):
    _ready_both(alice, bob)
    alice.get_received()
    bob.get_received()
    alice.emit("rps_pick", {"pick": "rock"})
    bob.emit("rps_pick", {"pick": "scissors"})
    mull_a = _first(alice.get_received(), "pregame_mulligan")["args"][0]
    bob.get_received()

    # Alice (P0) redraws 2 of her 3 cards; Bob keeps.
    alice.emit("mulligan_pick", {"hand_indices": [0, 1]})
    r_a_wait = alice.get_received()
    assert _first(r_a_wait, "game_start") is None
    assert _first(r_a_wait, "pregame_status") is not None  # waiting toast

    bob.emit("mulligan_pick", {"hand_indices": []})
    r_a = alice.get_received()
    r_b = bob.get_received()

    gs_a = _first(r_a, "game_start")["args"][0]
    gs_b = _first(r_b, "game_start")["args"][0]
    assert gs_a["your_player_idx"] == 0
    assert gs_b["your_player_idx"] == 1
    # game_start ships Alice's hand TRIMMED of the 2 replacements — they
    # animate in via the engine_events batch below.
    assert len(gs_a["state"]["players"][0]["hand"]) == 1
    # Active player (Alice / P0) gets the opening legal actions.
    assert len(gs_a["legal_actions"]) > 0
    assert gs_b["legal_actions"] == []

    ev_a = _first(r_a, "engine_events")["args"][0]
    ev_b = _first(r_b, "engine_events")["args"][0]
    draws_a = [e for e in ev_a["events"] if e["type"] == "card_drawn"]
    assert len(draws_a) == 2
    for e in draws_a:
        assert e["payload"]["source"] == "mulligan"
        assert e["payload"]["player_idx"] == 0
        assert e["payload"]["card_numeric_id"] is not None
    # Bob sees the same events with the card identity REDACTED.
    draws_b = [e for e in ev_b["events"] if e["type"] == "card_drawn"]
    assert len(draws_b) == 2
    for e in draws_b:
        assert e["payload"]["card_numeric_id"] is None
    # The engine_events final_state carries the full 3-card hand.
    assert len(ev_a["final_state"]["players"][0]["hand"]) == 3
    # Turn 1 is an explicit final beat, after every mulligan draw, so the
    # standard turn banner appears without covering the replacement cards.
    assert ev_a["events"][-1]["type"] == "turn_flipped"
    assert ev_a["events"][-1]["payload"] == {
        "prev_turn": 0,
        "new_turn": 1,
        "new_active_idx": 0,
    }
    assert ev_b["events"][-1]["type"] == "turn_flipped"
    # Hand invariant: nobody gained or lost cards net.
    assert ev_a["final_state"]["players"][1].get("hand_count", 4) == 4


def test_mulligan_invalid_indices_rejected(alice, bob):
    _ready_both(alice, bob)
    alice.get_received()
    bob.get_received()
    alice.emit("rps_pick", {"pick": "rock"})
    bob.emit("rps_pick", {"pick": "scissors"})
    alice.get_received()
    bob.get_received()

    alice.emit("mulligan_pick", {"hand_indices": [99]})
    r_a = alice.get_received()
    err = _first(r_a, "error")
    assert err is not None and "mulligan" in err["args"][0]["msg"].lower()
    # Seat is NOT consumed — a valid retry still works.
    alice.emit("mulligan_pick", {"hand_indices": []})
    bob.emit("mulligan_pick", {"hand_indices": []})
    assert _first(alice.get_received(), "game_start") is not None


def test_pregame_resync_reemits_stage(alice, bob):
    _ready_both(alice, bob)
    alice.get_received()
    bob.get_received()

    alice.emit("pregame_resync", {})
    r_a = alice.get_received()
    rps = _first(r_a, "pregame_rps")
    assert rps is not None
    assert rps["args"][0]["already_picked"] is None

    alice.emit("rps_pick", {"pick": "rock"})
    alice.get_received()
    alice.emit("pregame_resync", {})
    rps2 = _first(alice.get_received(), "pregame_rps")["args"][0]
    assert rps2["already_picked"] == "rock"

    bob.emit("rps_pick", {"pick": "scissors"})
    alice.get_received()
    bob.get_received()
    # Mulligan-stage resync re-emits the hand payload.
    bob.emit("pregame_resync", {})
    mull = _first(bob.get_received(), "pregame_mulligan")
    assert mull is not None
    assert len(mull["args"][0]["hand"]) == 4


def test_preview_pregame_full_flow(alice):
    alice.emit("preview_game", {"display_name": "Solo"})
    r = alice.get_received()
    rps = _first(r, "pregame_rps")
    assert rps is not None
    # Dummy seat renamed Preview -> AI (Play VS AI, user 2026-07-11).
    assert rps["args"][0]["opponent_name"] == "AI"
    assert _first(r, "game_start") is None

    # Dummy auto-picks immediately (rigged to lose so the inert dummy
    # never holds the opening turn) — one human pick resolves the round.
    alice.emit("rps_pick", {"pick": "paper"})
    r2 = alice.get_received()
    res = _first(r2, "rps_result")["args"][0]
    assert res["tie"] is False
    assert res["you_go_first"] is True
    mull = _first(r2, "pregame_mulligan")["args"][0]
    assert mull["your_player_idx"] == 0
    # Normal 3-card P1 opening deal (the 10-card preview aid was retired
    # 2026-07-08 at user request — previews mirror real games).
    assert len(mull["hand"]) == 3
    assert mull["opponent_resolved"] is True  # dummy keeps instantly

    alice.emit("mulligan_pick", {"hand_indices": [0]})
    r3 = alice.get_received()
    gs = _first(r3, "game_start")["args"][0]
    assert gs["your_player_idx"] == 0
    assert gs.get("preview") is True
    ev = _first(r3, "engine_events")["args"][0]
    draws = [e for e in ev["events"] if e["type"] == "card_drawn"]
    assert len(draws) == 1
    assert draws[0]["payload"]["source"] == "mulligan"


def test_play_vs_ai_detaches_same_tab_from_old_ai_spectator_room(app, alice):
    rm = app.config["TEST_ROOM_MANAGER"]
    alice.emit("watch_ai_game", {"display_name": "Viewer"})
    watched = alice.get_received()
    joined = _first(watched, "spectator_joined")
    assert joined is not None
    old_room = joined["args"][0]["room_code"]
    assert rm.spectator_count(old_room) == 1

    alice.emit("preview_game", {"display_name": "Solo"})
    preview = alice.get_received()
    assert _first(preview, "pregame_rps") is not None
    assert rm.spectator_count(old_room) == 0


def test_pregame_disabled_keeps_instant_start(alice, bob, monkeypatch):
    monkeypatch.setattr(events_mod, "PREGAME_ENABLED", False)
    _ready_both(alice, bob)
    r_a = alice.get_received()
    assert _first(r_a, "game_start") is not None
    assert _first(r_a, "pregame_rps") is None
