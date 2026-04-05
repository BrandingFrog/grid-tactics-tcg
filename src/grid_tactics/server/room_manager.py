"""Room creation, joining, lifecycle, and session token management."""
import secrets
import string
import threading
import uuid
from dataclasses import dataclass, field

from grid_tactics.card_library import CardLibrary
from grid_tactics.game_state import GameState
from grid_tactics.server.game_session import GameSession
from grid_tactics.server.preset_deck import get_preset_deck


@dataclass
class PlayerSlot:
    """A player waiting in a room."""

    token: str
    name: str
    sid: str
    ready: bool = False
    deck: tuple[int, ...] | None = None  # None = use preset


@dataclass
class WaitingRoom:
    """A room waiting for players to join and ready up."""

    code: str
    creator: PlayerSlot
    joiner: PlayerSlot | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class RoomManager:
    """Manages room lifecycle: create, join, ready, start game."""

    def __init__(self, library: CardLibrary):
        self._library = library
        self._rooms: dict[str, WaitingRoom] = {}          # code -> WaitingRoom
        self._games: dict[str, GameSession] = {}           # code -> GameSession
        self._token_to_room: dict[str, str] = {}           # token -> room code
        self._sid_to_token: dict[str, str] = {}            # sid -> token
        self._lock = threading.Lock()

    def _generate_code(self) -> str:
        """Generate a unique 6-char uppercase alphanumeric room code."""
        chars = string.ascii_uppercase + string.digits
        while True:
            code = "".join(secrets.choice(chars) for _ in range(6))
            if code not in self._rooms and code not in self._games:
                return code

    def create_room(self, display_name: str, sid: str) -> tuple[str, str]:
        """Create a new room. Returns (room_code, session_token)."""
        token = str(uuid.uuid4())
        with self._lock:
            code = self._generate_code()
            slot = PlayerSlot(token=token, name=display_name, sid=sid)
            room = WaitingRoom(code=code, creator=slot)
            self._rooms[code] = room
            self._token_to_room[token] = code
            self._sid_to_token[sid] = token
        return code, token

    def join_room(
        self, room_code: str, display_name: str, sid: str
    ) -> tuple[str, WaitingRoom]:
        """Join an existing room. Returns (session_token, room).

        Raises ValueError if room not found, full, or already in game.
        """
        token = str(uuid.uuid4())
        with self._lock:
            room = self._rooms.get(room_code)
            if room is None:
                raise ValueError(f"Room '{room_code}' not found")
            if room.joiner is not None:
                raise ValueError(f"Room '{room_code}' is full")
        # Don't hold global lock while modifying room -- use room lock
        with room.lock:
            if room.joiner is not None:
                raise ValueError(f"Room '{room_code}' is full")
            slot = PlayerSlot(token=token, name=display_name, sid=sid)
            room.joiner = slot
        with self._lock:
            self._token_to_room[token] = room_code
            self._sid_to_token[sid] = token
        return token, room

    def set_ready(self, token: str) -> tuple[str, WaitingRoom, bool]:
        """Mark player as ready. Returns (room_code, room, both_ready).

        Raises ValueError if not in a room or room not found.
        """
        with self._lock:
            room_code = self._token_to_room.get(token)
            if room_code is None:
                raise ValueError("Not in a room")
            room = self._rooms.get(room_code)
            if room is None:
                raise ValueError("Room not found")
        with room.lock:
            if room.creator.token == token:
                room.creator.ready = True
            elif room.joiner and room.joiner.token == token:
                room.joiner.ready = True
            else:
                raise ValueError("Token not in this room")
            both_ready = room.creator.ready and (
                room.joiner is not None and room.joiner.ready
            )
        return room_code, room, both_ready

    def start_game(self, room_code: str) -> GameSession:
        """Promote WaitingRoom to GameSession. Called when both players ready.

        Per D-06: randomly assign which human is P1 vs P2.
        """
        with self._lock:
            room = self._rooms.pop(room_code)
        assert room.joiner is not None

        # D-06: Coin flip for who is Player 1 vs Player 2
        seed = secrets.randbelow(2**31)
        coin = secrets.randbelow(2)  # 0 or 1

        if coin == 0:
            p0_slot, p1_slot = room.creator, room.joiner
        else:
            p0_slot, p1_slot = room.joiner, room.creator

        # Use preset deck for now (D-03). Future: use player-submitted decks.
        preset = get_preset_deck(self._library)
        deck_p0 = p0_slot.deck if p0_slot.deck else preset
        deck_p1 = p1_slot.deck if p1_slot.deck else preset

        state, rng = GameState.new_game(seed, deck_p0, deck_p1)

        session = GameSession(
            state=state,
            rng=rng,
            library=self._library,
            player_tokens=(p0_slot.token, p1_slot.token),
            player_names=(p0_slot.name, p1_slot.name),
            player_sids=[p0_slot.sid, p1_slot.sid],
        )

        with self._lock:
            self._games[room_code] = session
        return session

    def get_token_by_sid(self, sid: str) -> str | None:
        """Look up session token by socket ID."""
        return self._sid_to_token.get(sid)

    def get_room_code_by_token(self, token: str) -> str | None:
        """Look up room code by session token."""
        return self._token_to_room.get(token)

    def get_game(self, room_code: str) -> GameSession | None:
        """Get active game session by room code."""
        return self._games.get(room_code)

    def get_room(self, room_code: str) -> WaitingRoom | None:
        """Get waiting room by room code."""
        return self._rooms.get(room_code)
