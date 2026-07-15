"""Best-effort, size-bounded local diagnostic logs for the game server.

The Socket.IO handlers must never fail because a diagnostic sink is missing,
read-only, or full.  This module therefore owns all filesystem interaction and
silently degrades to the normal process logger when a local file cannot be
written.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()
_LOGGER = logging.getLogger("grid_tactics.server.debug")
_DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 3
_MAX_RECORD_BYTES = 32 * 1024


def _repo_log_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "logs"


def _configured_path(env_name: str, default_name: str) -> Path:
    explicit = os.environ.get(env_name, "").strip()
    if explicit:
        return Path(explicit).expanduser()
    directory = os.environ.get("GT_SERVER_LOG_DIR", "").strip()
    return (Path(directory).expanduser() if directory else _repo_log_dir()) / default_name


def debug_log_path() -> Path:
    """Return the configured catch-all debug JSONL path."""
    return _configured_path("GT_DEBUG_LOG_PATH", "gt-debug.jsonl")


def illegal_action_log_path() -> Path:
    """Return the configured dedicated illegal-action JSONL path."""
    return _configured_path("GT_ILLEGAL_ACTION_LOG_PATH", "illegal-actions.jsonl")


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _json_line(record: Mapping[str, Any]) -> str:
    enriched = {"timestamp_utc": datetime.now(UTC).isoformat(timespec="milliseconds")}
    enriched.update(record)
    line = json.dumps(
        enriched,
        default=str,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    encoded = line.encode("utf-8")
    complete = line + "\n"
    if len(complete.encode("utf-8")) <= _MAX_RECORD_BYTES:
        return complete

    # Keep a valid, searchable JSON object even if a future caller supplies a
    # huge exception or payload.  The action paths only send whitelisted data;
    # this is defense-in-depth against log amplification.
    bounded = {
        key: _brief_value(enriched.get(key))
        for key in (
            "timestamp_utc",
            "code",
            "kind",
            "source",
            "reason",
            "mode",
            "turn",
            "phase",
            "player_idx",
            "decision_idx",
            "legal_count",
        )
        if key in enriched
    }
    bounded["record_truncated"] = True
    bounded["original_bytes"] = len(encoded)
    bounded["record_sha256"] = hashlib.sha256(encoded).hexdigest()
    bounded_line = json.dumps(
        bounded,
        default=str,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    if len(bounded_line.encode("utf-8")) <= _MAX_RECORD_BYTES:
        return bounded_line
    return json.dumps({
        "kind": "record_too_large",
        "record_sha256": hashlib.sha256(encoded).hexdigest(),
        "record_truncated": True,
    }, separators=(",", ":"), sort_keys=True) + "\n"


def _brief_value(value):
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        return value[:256]
    return f"<{type(value).__name__[:64]}>"


def _rotate_if_needed(path: Path, incoming_bytes: int) -> None:
    max_bytes = _env_int("GT_DEBUG_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES, 1024)
    backup_count = _env_int(
        "GT_DEBUG_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT, 1,
    )
    try:
        current_size = path.stat().st_size
    except FileNotFoundError:
        return
    if current_size + incoming_bytes <= max_bytes:
        return

    for index in range(backup_count, 0, -1):
        source = path if index == 1 else path.with_name(f"{path.name}.{index - 1}")
        destination = path.with_name(f"{path.name}.{index}")
        if source.exists():
            source.replace(destination)


def _append(path: Path, line: str) -> None:
    encoded_size = len(line.encode("utf-8"))
    with _WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path, encoded_size)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)


def write_debug_record(
    record: Mapping[str, Any],
    *,
    illegal_action: bool = False,
) -> None:
    """Write a diagnostic record without ever raising into game flow.

    Every record goes to the process logger and the catch-all local JSONL
    file.  Illegal actions are additionally copied to their own JSONL file so
    they can be inspected without filtering resolver and phase diagnostics.
    """
    try:
        line = _json_line(record)
    except Exception:  # pragma: no cover - pathological unserialisable objects
        try:
            line = json.dumps({
                "timestamp_utc": datetime.now(UTC).isoformat(timespec="milliseconds"),
                "kind": "serialization_error",
                "serialization_error": True,
            }, separators=(",", ":"), sort_keys=True) + "\n"
        except Exception:
            return

    try:
        _LOGGER.warning("[GT-DEBUG] %s", line.rstrip("\n"))
    except Exception:
        pass

    try:
        _append(debug_log_path(), line)
    except Exception:
        pass

    if illegal_action:
        try:
            _append(illegal_action_log_path(), line)
        except Exception:
            pass
