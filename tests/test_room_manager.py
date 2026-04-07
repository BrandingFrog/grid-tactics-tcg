"""Tests for Phase 14.4: RoomManager spectator data model + join API.

These tests exercise RoomManager directly (no Flask-SocketIO dep), covering
the spectator surface added in Plan 14.4-01:

- join_as_spectator against waiting rooms and active games
- Multiple spectators per room
- Spectator token/role lookup
- Removal cleans all indexes
- Unknown-room rejection
"""
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.server.room_manager import RoomManager, SpectatorSlot


@pytest.fixture(scope="module")
def library() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture
def rm(library: CardLibrary) -> RoomManager:
    return RoomManager(library)


def _create_and_fill(rm: RoomManager) -> str:
    """Create a room with two players, return the room_code."""
    code, _ = rm.create_room("Alice", sid="sid-alice")
    rm.join_room(code, "Bob", sid="sid-bob")
    return code


def _start_game(rm: RoomManager, code: str) -> None:
    """Ready both players and transition the room into a GameSession."""
    room = rm.get_room(code)
    assert room is not None
    rm.set_ready(room.creator.token)
    assert room.joiner is not None
    rm.set_ready(room.joiner.token)
    rm.start_game(code)


# --- Tests ---


def test_join_as_spectator_basic(rm: RoomManager) -> None:
    code, _ = rm.create_room("Alice", sid="sid-alice")
    token, room = rm.join_as_spectator(code, "Eve", sid="sid-eve", god_mode=False)
    assert rm.get_role(token) == "spectator"
    assert token in rm.get_spectator_tokens(code)
    slot = rm.get_spectator(token)
    assert isinstance(slot, SpectatorSlot)
    assert slot.name == "Eve"
    assert slot.god_mode is False


def test_multiple_spectators_same_room(rm: RoomManager) -> None:
    code, _ = rm.create_room("Alice", sid="sid-alice")
    tokens = [
        rm.join_as_spectator(code, f"Spec{i}", sid=f"sid-spec-{i}")[0]
        for i in range(3)
    ]
    assert len(set(tokens)) == 3
    specs = rm.get_spectator_tokens(code)
    for t in tokens:
        assert t in specs
    assert len(specs) == 3


def test_spectator_join_after_game_started(rm: RoomManager) -> None:
    code = _create_and_fill(rm)
    _start_game(rm, code)
    # Waiting room is gone; game session exists.
    assert rm.get_room(code) is None
    assert rm.get_game(code) is not None

    token, target = rm.join_as_spectator(code, "Eve", sid="sid-eve", god_mode=True)
    assert rm.get_role(token) == "spectator"
    assert token in rm.get_spectator_tokens(code)
    # Manager resolves room_code back from the spectator token.
    assert rm.get_room_code_by_token(token) == code
    slot = rm.get_spectator(token)
    assert slot is not None and slot.god_mode is True


def test_spectator_join_when_room_full(rm: RoomManager) -> None:
    code = _create_and_fill(rm)
    # Room slots are full; spectator join must still succeed.
    token, _ = rm.join_as_spectator(code, "Eve", sid="sid-eve")
    assert rm.get_role(token) == "spectator"
    assert token in rm.get_spectator_tokens(code)


def test_remove_spectator(rm: RoomManager) -> None:
    code, _ = rm.create_room("Alice", sid="sid-alice")
    token, _ = rm.join_as_spectator(code, "Eve", sid="sid-eve")
    assert rm.get_role(token) == "spectator"

    removed_code = rm.remove_spectator(token)
    assert removed_code == code
    assert rm.get_role(token) is None
    assert token not in rm.get_spectator_tokens(code)
    # sid index is cleaned too.
    assert rm.get_token_by_sid("sid-eve") is None


def test_remove_last_spectator_collapses_bucket(rm: RoomManager) -> None:
    code, _ = rm.create_room("Alice", sid="sid-alice")
    t1, _ = rm.join_as_spectator(code, "Eve", sid="sid-eve")
    t2, _ = rm.join_as_spectator(code, "Dan", sid="sid-dan")
    rm.remove_spectator(t1)
    assert rm.get_spectator_tokens(code) == [t2]
    rm.remove_spectator(t2)
    assert rm.get_spectator_tokens(code) == []


def test_join_as_spectator_unknown_room(rm: RoomManager) -> None:
    with pytest.raises(ValueError):
        rm.join_as_spectator("ZZZZZZ", "Eve", sid="sid-eve")


def test_remove_nonexistent_spectator_returns_none(rm: RoomManager) -> None:
    # Non-existent token.
    assert rm.remove_spectator("not-a-real-token") is None
    # Player token (not a spectator) should not be removable via this API.
    code, player_token = rm.create_room("Alice", sid="sid-alice")
    assert rm.remove_spectator(player_token) is None
    # Player role untouched.
    assert rm.get_role(player_token) == "player"
