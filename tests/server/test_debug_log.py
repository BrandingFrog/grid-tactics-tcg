"""Server-side JSONL diagnostics for rejected and illegal actions."""
from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from grid_tactics.actions import Action
from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import EventStream
from grid_tactics.enums import ActionType, TurnPhase
from grid_tactics.legal_actions import legal_actions
from grid_tactics.phase_contracts import OutOfPhaseError
from grid_tactics.server import debug_log
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.events import (
    _debug_report,
    _illegal_action_detail,
    _resolve_server_ai_action,
    register_events,
)
from grid_tactics.server.room_manager import RoomManager


@pytest.fixture
def isolated_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GT_SERVER_LOG_DIR", str(tmp_path))
    monkeypatch.delenv("GT_DEBUG_LOG_PATH", raising=False)
    monkeypatch.delenv("GT_ILLEGAL_ACTION_LOG_PATH", raising=False)
    return tmp_path


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_illegal_action_gets_a_dedicated_local_jsonl_record(isolated_logs: Path):
    detail = _illegal_action_detail(
        "player_socket",
        "not_in_legal_actions",
        {
            "action_type": int(ActionType.MOVE),
            "minion_id": 12,
            "target_pos": [2, 3],
            "ignored_secret": "must-not-be-written",
        },
        Action(
            action_type=ActionType.MOVE,
            minion_id=12,
            target_pos=(2, 3),
        ),
        (),
    )
    detail["mode"] = "pvp"

    code = _debug_report("illegal_action", "ROOM42", None, 0, detail)

    dedicated = _read_jsonl(isolated_logs / "illegal-actions.jsonl")
    catch_all = _read_jsonl(isolated_logs / "gt-debug.jsonl")
    assert dedicated == catch_all
    assert len(dedicated) == 1
    record = dedicated[0]
    assert record["code"] == code
    assert record["kind"] == "illegal_action"
    assert record["reason"] == "not_in_legal_actions"
    assert record["action"]["action_type"] == int(ActionType.MOVE)
    assert record["wire_action"]["target_pos"] == [2, 3]
    assert "ignored_secret" not in record["wire_action"]
    assert "room" not in record
    assert len(record["room_ref"]) == 12
    assert record["timestamp_utc"].endswith("+00:00")


def test_known_action_fields_do_not_leak_malicious_strings(isolated_logs: Path):
    detail = _illegal_action_detail(
        "player_socket",
        "invalid_payload",
        {
            "action_type": "PASSWORD-123",
            "position": ["email@example.com", 2],
            "target_id": float("nan"),
            "transform_target": "PASSWORD123",
            "unrecognised": "another-secret",
        },
    )

    _debug_report("illegal_action", "ROOM42", None, 0, detail)

    raw = (isolated_logs / "illegal-actions.jsonl").read_text(encoding="utf-8")
    assert "PASSWORD-123" not in raw
    assert "email@example.com" not in raw
    assert "PASSWORD123" not in raw
    assert "another-secret" not in raw
    assert "NaN" not in raw
    record = json.loads(raw)
    assert record["wire_action"] == {
        "action_type": "<invalid-str>",
        "position": "<invalid-list>",
        "target_id": "<invalid-float>",
        "transform_target": "<valid-str-redacted>",
    }


def test_non_illegal_debug_record_stays_out_of_dedicated_file(isolated_logs: Path):
    _debug_report("resolver_crash", "ROOM42", None, 0, {"reason": "test"})

    assert (isolated_logs / "gt-debug.jsonl").exists()
    assert not (isolated_logs / "illegal-actions.jsonl").exists()


def test_local_jsonl_rotates_instead_of_growing_forever(
    isolated_logs: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GT_DEBUG_LOG_MAX_BYTES", "1024")
    monkeypatch.setenv("GT_DEBUG_LOG_BACKUP_COUNT", "2")

    for index in range(4):
        debug_log.write_debug_record({
            "code": f"GT-{index:06d}",
            "kind": "rotation_test",
            "detail": "x" * 700,
        })

    assert (isolated_logs / "gt-debug.jsonl").exists()
    assert (isolated_logs / "gt-debug.jsonl.1").exists()
    assert (isolated_logs / "gt-debug.jsonl.2").exists()
    for path in isolated_logs.glob("gt-debug.jsonl*"):
        assert _read_jsonl(path)


def test_oversized_record_is_replaced_with_bounded_metadata(isolated_logs: Path):
    debug_log.write_debug_record({
        "code": "GT-1234567890",
        "kind": "oversized_test",
        "detail": "private-value-" * 10000,
    })

    path = isolated_logs / "gt-debug.jsonl"
    raw = path.read_bytes()
    assert len(raw) <= debug_log._MAX_RECORD_BYTES
    assert b"private-value" not in raw
    record = json.loads(raw)
    assert record["record_truncated"] is True
    assert len(record["record_sha256"]) == 64


def test_record_cap_includes_the_trailing_newline():
    base = debug_log._json_line({"detail": ""})
    filler_size = debug_log._MAX_RECORD_BYTES - len(base.encode("utf-8"))

    exact = debug_log._json_line({"detail": "x" * filler_size})
    overflow = debug_log._json_line({"detail": "x" * (filler_size + 1)})

    assert len(exact.encode("utf-8")) == debug_log._MAX_RECORD_BYTES
    assert len(overflow.encode("utf-8")) <= debug_log._MAX_RECORD_BYTES
    assert json.loads(overflow)["record_truncated"] is True


def test_pathological_retained_field_type_cannot_bypass_record_cap():
    hostile_type = type("X" * 100000, (), {})

    line = debug_log._json_line({
        "kind": "oversized_test",
        "turn": hostile_type(),
        "detail": "x" * debug_log._MAX_RECORD_BYTES,
    })

    assert len(line.encode("utf-8")) <= debug_log._MAX_RECORD_BYTES
    assert json.loads(line)["record_truncated"] is True


def test_pathological_mapping_cannot_escape_reporting(isolated_logs: Path):
    class HostileMapping(Mapping):
        def __getitem__(self, _key):
            raise RuntimeError("no values")

        def __iter__(self) -> Iterator:
            raise RuntimeError("no iteration")

        def __len__(self):
            raise RuntimeError("no length")

    debug_log.write_debug_record(HostileMapping(), illegal_action=True)

    record = _read_jsonl(isolated_logs / "illegal-actions.jsonl")[-1]
    assert record["serialization_error"] is True


def test_debug_report_survives_hostile_detail_and_reserves_room_fields(
    isolated_logs: Path,
):
    class HostileError(Exception):
        def __str__(self):
            raise RuntimeError("do not stringify me")

    class HostileDetail(Mapping):
        def __getitem__(self, _key):
            raise HostileError()

        def __iter__(self) -> Iterator:
            raise HostileError()

        def __len__(self):
            raise HostileError()

    code = _debug_report("illegal_action", "ROOM42", None, 0, HostileDetail())
    _debug_report(
        "illegal_action",
        "ROOM42",
        None,
        0,
        {"room": "PLAINTEXT", "room_code": "ALSO-PLAINTEXT"},
    )

    records = _read_jsonl(isolated_logs / "illegal-actions.jsonl")
    assert records[0]["code"] == code
    assert records[0]["detail_error_type"] == "HostileError"
    assert all("room" not in record and "room_code" not in record for record in records)
    assert all("room_ref" in record for record in records)


def test_reporting_failure_never_escapes_into_game_flow(
    isolated_logs: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    class BrokenLogger:
        def warning(self, *_args, **_kwargs):
            raise BrokenPipeError("closed stderr")

    def broken_append(*_args, **_kwargs):
        raise PermissionError("read-only filesystem")

    monkeypatch.setattr(debug_log, "_LOGGER", BrokenLogger())
    monkeypatch.setattr(debug_log, "_append", broken_append)

    code = _debug_report("illegal_action", "ROOM42", None, 0, {"reason": "test"})

    assert code.startswith("GT-")
    assert len(code) == 13


def test_server_ai_illegal_selection_is_logged_before_resolution(
    isolated_logs: Path,
):
    library = CardLibrary.from_directory(Path("data/cards"))
    manager = RoomManager(library)
    _room_code, session = manager.create_preview_game("Solo", "human-sid")
    before = session.state
    valid = legal_actions(before, library)
    illegal = Action(
        action_type=ActionType.MOVE,
        minion_id=999,
        target_pos=(2, 2),
    )

    with pytest.raises(ValueError, match="Server AI selected an illegal action"):
        _resolve_server_ai_action(
            session,
            illegal,
            valid,
            EventStream(),
            room_code="AI-TEST",
            source="ai_watch",
        )

    assert session.state is before
    record = _read_jsonl(isolated_logs / "illegal-actions.jsonl")[-1]
    assert record["source"] == "ai_watch"
    assert record["reason"] == "ai_selection_not_legal"
    assert record["action"]["action_type"] == int(ActionType.MOVE)
    assert record["legal_count"] == len(valid)


def test_server_ai_phase_rejection_keeps_structured_error_and_logs_action(
    isolated_logs: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import grid_tactics.server.events as events

    library = CardLibrary.from_directory(Path("data/cards"))
    manager = RoomManager(library)
    _room_code, session = manager.create_preview_game("Solo", "human-sid")
    valid = legal_actions(session.state, library)
    action = valid[0]

    def reject_phase(*_args, **_kwargs):
        raise OutOfPhaseError(
            "effect:audit",
            TurnPhase.ACTION,
            frozenset({TurnPhase.REACT}),
        )

    monkeypatch.setattr(events, "resolve_action", reject_phase)

    with pytest.raises(OutOfPhaseError) as error:
        _resolve_server_ai_action(
            session,
            action,
            valid,
            EventStream(),
            room_code="AI-TEST",
            source="preview_ai",
        )

    record = _read_jsonl(isolated_logs / "illegal-actions.jsonl")[-1]
    assert error.value.debug_code == record["code"]
    assert record["reason"] == "ai_phase_contract_violation"
    assert record["source"] == "preview_ai"


def test_empty_action_fallback_is_logged_but_still_attempts_recovery(
    isolated_logs: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import grid_tactics.server.events as events

    library = CardLibrary.from_directory(Path("data/cards"))
    manager = RoomManager(library)
    _room_code, session = manager.create_preview_game("Solo", "human-sid")
    recovered_state = object()
    monkeypatch.setattr(
        events,
        "resolve_action",
        lambda *_args, **_kwargs: recovered_state,
    )

    result = _resolve_server_ai_action(
        session,
        Action(action_type=ActionType.PASS),
        (),
        EventStream(),
        room_code="AI-TEST",
        source="server_empty_action_fallback",
        allow_unlisted=True,
    )

    assert result is recovered_state
    record = _read_jsonl(isolated_logs / "illegal-actions.jsonl")[-1]
    assert record["reason"] == "forced_fallback_not_in_legal_actions"


def test_normal_preview_handoff_logs_illegal_ai_selection(
    isolated_logs: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import grid_tactics.server.preview_ai as preview_ai

    monkeypatch.setenv("GT_MANUAL_DRAW", "1")
    library = CardLibrary.from_directory(Path("data/cards"))
    manager = RoomManager(library)
    app = create_app(testing=True)
    register_events(manager)
    client = socketio.test_client(app)
    client.emit("preview_game", {"display_name": "Solo"})
    client.get_received()
    session = next(iter(manager._games.values()))
    before = session.state
    illegal = Action(
        action_type=ActionType.MOVE,
        minion_id=999,
        target_pos=(2, 2),
    )
    monkeypatch.setattr(
        preview_ai,
        "pick_preview_action",
        lambda _state, _library, _legal: illegal,
    )

    client.emit("submit_action", {"action_type": int(ActionType.DRAW)})

    errors = [
        message["args"][0]
        for message in client.get_received()
        if message["name"] == "error"
    ]
    assert errors
    assert "Server AI selected an illegal action" in errors[-1]["msg"]
    assert session.state is before
    record = _read_jsonl(isolated_logs / "illegal-actions.jsonl")[-1]
    assert record["code"] == errors[-1]["debug_code"]
    assert record["source"] == "preview_ai"
    assert record["reason"] == "ai_selection_not_legal"
    assert record["action"]["action_type"] == int(ActionType.MOVE)
