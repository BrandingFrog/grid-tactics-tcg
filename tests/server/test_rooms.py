"""Open-games list hygiene (user 2026-07-11 — ghost rooms)."""

from pathlib import Path

from grid_tactics.card_library import CardLibrary
from grid_tactics.server.room_manager import OPEN_ROOM_TTL_SECONDS, RoomManager


def test_open_room_ttl_prunes_stale_rooms():
    """Unjoined waiting rooms older than OPEN_ROOM_TTL_SECONDS vanish from
    the public list (and their token maps are cleaned). Disconnected
    creators are vacated eagerly in handle_disconnect; the TTL covers AFK
    creators whose tab stays open."""
    rm = RoomManager(CardLibrary.from_directory(Path("data/cards")))
    code, token = rm.create_room("Ghost", sid="sid-ghost")
    assert any(r["code"] == code for r in rm.list_open_rooms())

    # Age the room past the TTL.
    room = rm.get_room(code)
    room.created_at -= OPEN_ROOM_TTL_SECONDS + 1

    assert all(r["code"] != code for r in rm.list_open_rooms())
    assert rm.get_room(code) is None
    assert rm.get_room_code_by_token(token) is None
    assert rm.get_token_by_sid("sid-ghost") is None
