"""Socket.IO handler tests for Phase 14.6-01 sandbox events.

Uses Flask-SocketIO's built-in test client — no real network. Each test
creates a fresh app + room manager so sandboxes don't leak across tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from grid_tactics.actions import pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType
from grid_tactics.server.action_codec import serialize_action
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import register_events
from grid_tactics.server.room_manager import RoomManager
from grid_tactics.types import STARTING_HP

# NOTE: the plan spec imports `app` as a module global, but the real
# src/grid_tactics/server/app.py only exposes `create_app(testing=True)`.
# We follow the existing test pattern from tests/test_pvp_server.py.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app_and_rm():
    library = CardLibrary.from_directory(Path("data/cards"))
    rm = RoomManager(library)
    application = create_app(testing=True)
    register_events(rm)
    return application, rm


@pytest.fixture
def client(app_and_rm):
    application, _rm = app_and_rm
    return socketio.test_client(application)


@pytest.fixture
def isolated_slot_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import grid_tactics.server.sandbox_session as mod

    monkeypatch.setattr(mod, "SLOT_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _drain(client) -> list[dict[str, Any]]:
    return client.get_received()


def _find(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    """Return the LAST matching event (so callers see the most recent state)."""
    last: dict[str, Any] | None = None
    for msg in events:
        if msg["name"] == name:
            last = msg["args"][0]
    return last


def _find_all(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [msg["args"][0] for msg in events if msg["name"] == name]


def _emit_and_drain(client, event: str, data: Any = None) -> list[dict[str, Any]]:
    if data is None:
        client.emit(event)
    else:
        client.emit(event, data)
    return _drain(client)


# ---------------------------------------------------------------------------
# sandbox_create
# ---------------------------------------------------------------------------


def test_sandbox_create_emits_state_and_card_defs(client) -> None:
    received = _emit_and_drain(client, "sandbox_create")
    card_defs_payload = _find(received, "sandbox_card_defs")
    state_payload = _find(received, "sandbox_state")
    assert card_defs_payload is not None
    assert state_payload is not None
    assert "card_defs" in card_defs_payload
    state = state_payload["state"]
    assert state["players"][0]["hp"] == STARTING_HP
    assert state["players"][0]["hand"] == []
    assert state_payload["undo_depth"] == 0
    assert state_payload["redo_depth"] == 0


def test_sandbox_apply_action_without_create_errors(client) -> None:
    received = _emit_and_drain(
        client,
        "sandbox_apply_action",
        serialize_action(pass_action()),
    )
    err = _find(received, "error")
    assert err is not None
    assert "No sandbox session" in err["msg"]


# ---------------------------------------------------------------------------
# sandbox_add_card_to_zone
# ---------------------------------------------------------------------------


def test_sandbox_add_card_to_zone_hand(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 0, "zone": "hand"},
    )
    state = _find(received, "sandbox_state")
    assert state is not None
    assert state["state"]["players"][0]["hand"] == [0]


@pytest.mark.parametrize(
    "zone,attr",
    [
        ("hand", "hand"),
        ("deck_top", "deck"),
        ("deck_bottom", "deck"),
        ("graveyard", "grave"),
        ("exhaust", "exhaust"),
    ],
)
def test_sandbox_add_card_to_zone_each_zone(
    app_and_rm, zone: str, attr: str
) -> None:
    application, _rm = app_and_rm
    c = socketio.test_client(application)
    c.emit("sandbox_create")
    _drain(c)
    c.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 0, "zone": zone},
    )
    state = _find(_drain(c), "sandbox_state")
    assert state is not None
    assert state["state"]["players"][0][attr] == [0]


def test_sandbox_add_card_to_zone_invalid_payload_errors(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "zone": "hand"},  # missing card_numeric_id
    )
    err = _find(received, "error")
    assert err is not None


# ---------------------------------------------------------------------------
# sandbox_move_card
# ---------------------------------------------------------------------------


def test_sandbox_move_card_between_zones(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    client.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 0, "zone": "deck_top"},
    )
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_move_card",
        {
            "player_idx": 0,
            "card_numeric_id": 0,
            "src_zone": "deck_top",
            "dst_zone": "hand",
        },
    )
    state = _find(received, "sandbox_state")
    assert state is not None
    assert state["state"]["players"][0]["deck"] == []
    assert state["state"]["players"][0]["hand"] == [0]


# ---------------------------------------------------------------------------
# sandbox_import_deck
# ---------------------------------------------------------------------------


def test_sandbox_import_deck(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_import_deck",
        {"player_idx": 0, "deck_card_ids": [1, 2, 3]},
    )
    state = _find(received, "sandbox_state")
    assert state is not None
    assert state["state"]["players"][0]["deck"] == [1, 2, 3]


def test_sandbox_import_deck_not_a_list_errors(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_import_deck",
        {"player_idx": 0, "deck_card_ids": "not-a-list"},
    )
    err = _find(received, "error")
    assert err is not None


# ---------------------------------------------------------------------------
# sandbox_set_player_field
# ---------------------------------------------------------------------------


def test_sandbox_set_player_field_hp(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_set_player_field",
        {"player_idx": 1, "field": "hp", "value": -50},
    )
    state = _find(received, "sandbox_state")
    assert state is not None
    assert state["state"]["players"][1]["hp"] == -50


def test_sandbox_set_player_field_invalid_field_returns_error(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client,
        "sandbox_set_player_field",
        {"player_idx": 0, "field": "foo", "value": 5},
    )
    err = _find(received, "error")
    assert err is not None
    # state should not be updated beyond the sandbox_create snapshot
    state_after = _find(received, "sandbox_state")
    assert state_after is None


# ---------------------------------------------------------------------------
# sandbox_apply_action
# ---------------------------------------------------------------------------


def test_sandbox_apply_action_legal_draw(client) -> None:
    """Apply a real engine-legal action via the handler.

    PASS is not automatically legal during ACTION phase (empty state has
    zero legal actions). The sandbox owner seeds a deck card then applies
    the first legal action the engine enumerates.

    Phase 14.8-05: post-action sandbox_state emit DELETED — engine_events
    is the sole post-action socket frame, and its top-level undo_depth /
    redo_depth fields replace the sandbox_state wrapper for that metadata.
    """
    client.emit("sandbox_create")
    _drain(client)
    client.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 0, "zone": "deck_top"},
    )
    state = _find(_drain(client), "sandbox_state")
    assert state is not None
    legal = state["legal_actions"]
    assert len(legal) >= 1

    received = _emit_and_drain(client, "sandbox_apply_action", legal[0])
    err = _find(received, "error")
    assert err is None, f"unexpected error: {err}"
    # Plan 14.8-05: no sandbox_state post-action.
    assert _find(received, "sandbox_state") is None
    engine_events_after = _find(received, "engine_events")
    assert engine_events_after is not None
    assert engine_events_after["undo_depth"] >= 1


def test_sandbox_apply_illegal_action_returns_error(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    # PLAY_CARD with card_index=0 is not legal (hand is empty).
    illegal_payload = {
        "action_type": int(ActionType.PLAY_CARD),
        "card_index": 0,
        "position": [0, 0],
    }
    received = _emit_and_drain(client, "sandbox_apply_action", illegal_payload)
    err = _find(received, "error")
    assert err is not None
    assert "Illegal" in err["msg"] or "illegal" in err["msg"].lower()


# ---------------------------------------------------------------------------
# sandbox_undo / sandbox_redo
# ---------------------------------------------------------------------------


def test_sandbox_undo_redo_via_events(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    client.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 0, "zone": "hand"},
    )
    client.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 1, "zone": "hand"},
    )
    _drain(client)

    # Undo twice → hand empty
    client.emit("sandbox_undo")
    client.emit("sandbox_undo")
    state = _find(_drain(client), "sandbox_state")
    assert state is not None
    assert state["state"]["players"][0]["hand"] == []
    assert state["undo_depth"] == 0
    assert state["redo_depth"] == 2

    # Redo twice → back to [0, 1]
    client.emit("sandbox_redo")
    client.emit("sandbox_redo")
    state = _find(_drain(client), "sandbox_state")
    assert state is not None
    assert state["state"]["players"][0]["hand"] == [0, 1]
    assert state["undo_depth"] == 2
    assert state["redo_depth"] == 0


# ---------------------------------------------------------------------------
# sandbox_set_active_player
# ---------------------------------------------------------------------------


def test_sandbox_set_active_player_event(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client, "sandbox_set_active_player", {"player_idx": 1}
    )
    state = _find(received, "sandbox_state")
    assert state is not None
    assert state["state"]["active_player_idx"] == 1
    assert state["active_view_idx"] == 1


# ---------------------------------------------------------------------------
# sandbox_save / sandbox_load (client-side transport)
# ---------------------------------------------------------------------------


def test_sandbox_save_load_round_trip(client) -> None:
    client.emit("sandbox_create")
    _drain(client)
    client.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 0, "zone": "hand"},
    )
    _drain(client)

    client.emit("sandbox_save")
    saved = _find(_drain(client), "sandbox_save_blob")
    assert saved is not None
    blob = saved["payload"]

    client.emit("sandbox_reset")
    state_after_reset = _find(_drain(client), "sandbox_state")
    assert state_after_reset is not None
    assert state_after_reset["state"]["players"][0]["hand"] == []

    client.emit("sandbox_load", {"payload": blob})
    state_after_load = _find(_drain(client), "sandbox_state")
    assert state_after_load is not None
    assert state_after_load["state"]["players"][0]["hand"] == [0]


# ---------------------------------------------------------------------------
# Server slot handlers (isolated)
# ---------------------------------------------------------------------------


def test_sandbox_save_slot_writes_file(
    client, isolated_slot_dir: Path
) -> None:
    client.emit("sandbox_create")
    _drain(client)
    client.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 0, "zone": "hand"},
    )
    _drain(client)
    received = _emit_and_drain(
        client, "sandbox_save_slot", {"slot_name": "e2e_slot"}
    )
    saved = _find(received, "sandbox_slot_saved")
    assert saved is not None
    assert saved["slot_name"] == "e2e_slot"
    slot_list = _find(received, "sandbox_slot_list")
    assert slot_list is not None
    assert "e2e_slot" in slot_list["slots"]
    # File should exist on disk
    assert (isolated_slot_dir / "e2e_slot.json").exists()


def test_sandbox_load_slot_round_trip(
    client, isolated_slot_dir: Path
) -> None:
    client.emit("sandbox_create")
    _drain(client)
    client.emit(
        "sandbox_add_card_to_zone",
        {"player_idx": 0, "card_numeric_id": 2, "zone": "hand"},
    )
    client.emit("sandbox_save_slot", {"slot_name": "rt"})
    _drain(client)

    client.emit("sandbox_reset")
    _drain(client)

    received = _emit_and_drain(client, "sandbox_load_slot", {"slot_name": "rt"})
    state = _find(received, "sandbox_state")
    assert state is not None
    assert state["state"]["players"][0]["hand"] == [2]


def test_sandbox_list_slots_returns_empty_initially(
    client, isolated_slot_dir: Path
) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(client, "sandbox_list_slots")
    slot_list = _find(received, "sandbox_slot_list")
    assert slot_list is not None
    assert slot_list["slots"] == []


def test_sandbox_delete_slot_idempotent(
    client, isolated_slot_dir: Path
) -> None:
    client.emit("sandbox_create")
    _drain(client)
    client.emit("sandbox_save_slot", {"slot_name": "gone"})
    _drain(client)

    received = _emit_and_drain(
        client, "sandbox_delete_slot", {"slot_name": "gone"}
    )
    deleted = _find(received, "sandbox_slot_deleted")
    assert deleted is not None
    assert deleted["existed"] is True

    received2 = _emit_and_drain(
        client, "sandbox_delete_slot", {"slot_name": "gone"}
    )
    deleted2 = _find(received2, "sandbox_slot_deleted")
    assert deleted2 is not None
    assert deleted2["existed"] is False


def test_sandbox_save_slot_invalid_name_returns_error(
    client, isolated_slot_dir: Path
) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client, "sandbox_save_slot", {"slot_name": "../etc"}
    )
    err = _find(received, "error")
    assert err is not None
    # No file written
    assert not any(isolated_slot_dir.iterdir())


def test_sandbox_load_slot_missing_returns_error(
    client, isolated_slot_dir: Path
) -> None:
    client.emit("sandbox_create")
    _drain(client)
    received = _emit_and_drain(
        client, "sandbox_load_slot", {"slot_name": "nonexistent"}
    )
    err = _find(received, "error")
    assert err is not None
    assert "Slot not found" in err["msg"]


# ---------------------------------------------------------------------------
# Disconnect cleanup
# ---------------------------------------------------------------------------


def test_disconnect_cleans_up_sandbox(app_and_rm) -> None:
    """Creating a sandbox, then disconnecting, removes it from RoomManager."""
    application, rm = app_and_rm
    c = socketio.test_client(application)
    c.emit("sandbox_create")
    _drain(c)
    # Find SID via RoomManager introspection — the test client registers
    # exactly one sandbox, so there must be exactly one entry in _sandboxes.
    assert len(rm._sandboxes) == 1
    c.disconnect()
    assert len(rm._sandboxes) == 0
