"""Room creation, joining, lifecycle, and session token management.

Spectator storage choice (Phase 14.4-01):
  Spectators are tracked in `RoomManager._room_spectators: dict[room_code,
  dict[token, SpectatorSlot]]` rather than on WaitingRoom. This is the least
  invasive option because `start_game` pops WaitingRoom out of `_rooms` and
  replaces it with a GameSession — keying spectators by room_code in the
  manager itself means they survive that transition without touching either
  WaitingRoom or GameSession dataclasses. Role lookups go through
  `_token_role` so any token (player or spectator) can be classified.
"""
import secrets
import string
import threading
import time
import uuid
from dataclasses import dataclass, field

from grid_tactics.card_library import CardLibrary
from grid_tactics.game_state import GameState
from grid_tactics.server.game_session import GameSession
from grid_tactics.server.preset_deck import get_preset_deck
from grid_tactics.server.sandbox_session import SandboxSession


@dataclass
class PlayerSlot:
    """A player waiting in a room."""

    token: str
    name: str
    sid: str
    avatar: str | None = None  # Discord avatar URL (None = guest → letter disc)
    ready: bool = False
    deck: tuple[int, ...] | None = None  # None = use preset


@dataclass
class SpectatorSlot:
    """A spectator watching a room (waiting or in-game)."""

    token: str
    name: str
    sid: str
    god_mode: bool = False


@dataclass
class WaitingRoom:
    """A room waiting for players to join and ready up."""

    code: str
    creator: PlayerSlot
    joiner: PlayerSlot | None = None
    created_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


# Preview-AI avatar (user 2026-07-11): the dummy seat wears the top half
# of Sparkfed Surgebot's card art. The ?crop=top hint is inert for static
# serving; the client CSS crops via an attribute selector.
_PREVIEW_AI_AVATAR = "/static/art/surgefed_sparkbot.thumb.webp?crop=top"

# Unjoined waiting rooms older than this are pruned from the Open-games
# list (user 2026-07-11 — ghost rooms). 30 minutes: long enough to wait
# for a friend, short enough that dead rooms don't accumulate.
OPEN_ROOM_TTL_SECONDS = 30 * 60


@dataclass
class PregameSeat:
    """One seat in a pregame (RPS + mulligan) stage.

    ``sid is None`` marks a preview dummy seat — the server auto-plays it.
    """

    token: str
    name: str
    sid: str | None
    deck: tuple[int, ...] | None = None
    avatar: str | None = None  # Discord avatar URL (None = guest/dummy)


@dataclass
class Pregame:
    """PREGAME stage (user 2026-07-08): sits between "both players ready"
    and the GameState broadcast. Rock-paper-scissors decides who goes
    first (winner becomes ENGINE PLAYER INDEX 0 — P1 = whoever goes first
    is a locked project convention), then both players may mulligan.

    Lifecycle: ``begin_pregame`` / ``begin_preview_pregame`` create it
    (the WaitingRoom is already popped), ``create_session_from_pregame``
    builds the GameSession once RPS resolves (seats reordered winner-
    first so seat idx == engine player idx from then on), and
    ``finish_pregame`` promotes the session into ``_games`` when both
    mulligans resolve. Tests that call ``start_game`` directly never
    touch this path.
    """

    code: str
    seats: list[PregameSeat]
    preview: bool = False
    stage: str = "rps"                         # 'rps' | 'mulligan'
    rps_picks: list = field(default_factory=lambda: [None, None])
    session: GameSession | None = None         # created when RPS resolves
    mulligan_done: list = field(default_factory=lambda: [False, False])
    mulligan_drawn: list = field(default_factory=lambda: [(), ()])
    lock: threading.Lock = field(default_factory=threading.Lock)

    def seat_idx(self, token: str) -> int | None:
        for i, seat in enumerate(self.seats):
            if seat.token == token:
                return i
        return None


class RoomManager:
    """Manages room lifecycle: create, join, ready, start game."""

    def __init__(self, library: CardLibrary):
        self._library = library
        self._rooms: dict[str, WaitingRoom] = {}          # code -> WaitingRoom
        self._games: dict[str, GameSession] = {}           # code -> GameSession
        self._token_to_room: dict[str, str] = {}           # token -> room code
        self._sid_to_token: dict[str, str] = {}            # sid -> token
        self._token_role: dict[str, str] = {}              # token -> 'player' | 'spectator'
        self._room_spectators: dict[str, dict[str, SpectatorSlot]] = {}  # room_code -> token -> slot
        self._sandboxes: dict[str, SandboxSession] = {}    # sid -> SandboxSession (Phase 14.6)
        self._pregames: dict[str, Pregame] = {}            # code -> Pregame (PREGAME 2026-07-08)
        self._lock = threading.Lock()

    def _generate_code(self) -> str:
        """Generate a unique 6-char uppercase alphanumeric room code."""
        chars = string.ascii_uppercase + string.digits
        while True:
            code = "".join(secrets.choice(chars) for _ in range(6))
            if (
                code not in self._rooms
                and code not in self._games
                and code not in self._pregames
            ):
                return code

    def create_room(
        self, display_name: str, sid: str, avatar: str | None = None
    ) -> tuple[str, str]:
        """Create a new room. Returns (room_code, session_token)."""
        token = str(uuid.uuid4())
        with self._lock:
            code = self._generate_code()
            slot = PlayerSlot(token=token, name=display_name, sid=sid, avatar=avatar)
            room = WaitingRoom(code=code, creator=slot)
            self._rooms[code] = room
            self._token_to_room[token] = code
            self._sid_to_token[sid] = token
            self._token_role[token] = 'player'
        return code, token

    def join_room(
        self, room_code: str, display_name: str, sid: str, avatar: str | None = None
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
            slot = PlayerSlot(token=token, name=display_name, sid=sid, avatar=avatar)
            room.joiner = slot
        with self._lock:
            self._token_to_room[token] = room_code
            self._sid_to_token[sid] = token
            self._token_role[token] = 'player'
        return token, room

    def leave_room(self, token: str) -> tuple[str, str, PlayerSlot | None, bool]:
        """Remove a player from their WAITING room (pre-game only).

        Returns ``(room_code, leaver_name, other_slot, room_closed)``.
        The creator leaving closes the room (any joiner is kicked back to
        the lobby); a joiner leaving reopens the seat. Raises ValueError
        if the token is not seated in a waiting room (e.g. the room has
        already been promoted to a pregame/game).
        """
        with self._lock:
            room_code = self._token_to_room.get(token)
            if room_code is None:
                raise ValueError("Not in a room")
            room = self._rooms.get(room_code)
            if room is None:
                raise ValueError("Game already starting — can't leave the room")
        with room.lock:
            if room.creator.token == token:
                leaver_name = room.creator.name
                other = room.joiner
                closed = True
            elif room.joiner is not None and room.joiner.token == token:
                leaver_name = room.joiner.name
                other = room.creator
                closed = False
                room.joiner = None
            else:
                raise ValueError("Token not in this room")
        with self._lock:
            gone_tokens = [token]
            if closed:
                self._rooms.pop(room_code, None)
                if other is not None:
                    gone_tokens.append(other.token)
            for t in gone_tokens:
                self._token_to_room.pop(t, None)
                self._token_role.pop(t, None)
            gone = set(gone_tokens)
            for sid in [s for s, t in self._sid_to_token.items() if t in gone]:
                del self._sid_to_token[sid]
        return room_code, leaver_name, other, closed

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
            player_decks=(deck_p0, deck_p1),
            player_avatars=(p0_slot.avatar, p1_slot.avatar),
        )

        with self._lock:
            self._games[room_code] = session
        return session

    def create_preview_game(
        self, display_name: str, sid: str, avatar: str | None = None
    ) -> tuple[str, GameSession]:
        """Solo PREVIEW game (lobby quick view, user 2026-07-06): a real
        GameSession on the real duel screen where the requester is P0 and
        the opponent seat is an inert dummy. For checking the game view on
        any device — the dummy never acts, so play halts at the first
        opponent react window. Not listed in the lobby.
        """
        token = str(uuid.uuid4())
        dummy_token = str(uuid.uuid4())
        preset = get_preset_deck(self._library)
        seed = secrets.randbelow(2**31)
        state, rng = GameState.new_game(seed, preset, preset)
        # Preview hands are the NORMAL 3/4 opening deal (user 2026-07-08 —
        # the 2026-07-06 full-hand-of-10 testing aid is retired).
        import dataclasses as _dc
        # Guarantee Reanimated Bones in the human's opening hand (user
        # 2026-07-06 — transform-mechanic testing).
        try:
            bones = self._library.get_numeric_id("reanimated_bones")
            p0 = state.players[0]
            if bones not in p0.hand and bones in p0.deck:
                i = p0.deck.index(bones)
                state = _dc.replace(
                    state,
                    players=(
                        _dc.replace(
                            p0,
                            hand=p0.hand[:-1] + (bones,),
                            deck=p0.deck[:i] + (p0.hand[-1],) + p0.deck[i + 1:],
                        ),
                        state.players[1],
                    ),
                )
        except KeyError:
            pass  # card renamed/removed — preview still works without it
        session = GameSession(
            state=state,
            rng=rng,
            library=self._library,
            player_tokens=(token, dummy_token),
            player_names=(display_name or "You", "AI"),
            player_sids=[sid, None],
            player_decks=(preset, preset),
            player_avatars=(avatar, _PREVIEW_AI_AVATAR),  # AI: Surgebot art, top-crop
        )
        with self._lock:
            code = self._generate_code()
            self._games[code] = session
            self._token_to_room[token] = code
            self._sid_to_token[sid] = token
            self._token_role[token] = "player"
        return code, session

    # ------------------------------------------------------------------
    # PREGAME stage (user 2026-07-08): RPS + mulligan before game_start
    # ------------------------------------------------------------------
    # Only the socket start paths (handle_ready both_ready / preview_game)
    # enter pregame — start_game / create_preview_game above are untouched
    # so tests and any direct callers keep the old instant-start behavior.

    def begin_pregame(self, room_code: str) -> Pregame:
        """Promote a WaitingRoom to a Pregame (both players ready).

        Pops the WaitingRoom just like ``start_game`` but defers GameState
        creation until RPS resolves (seat order = who goes first).
        """
        with self._lock:
            room = self._rooms.pop(room_code)
        assert room.joiner is not None
        pregame = Pregame(
            code=room_code,
            seats=[
                PregameSeat(
                    token=room.creator.token, name=room.creator.name,
                    sid=room.creator.sid, deck=room.creator.deck,
                    avatar=room.creator.avatar,
                ),
                PregameSeat(
                    token=room.joiner.token, name=room.joiner.name,
                    sid=room.joiner.sid, deck=room.joiner.deck,
                    avatar=room.joiner.avatar,
                ),
            ],
        )
        with self._lock:
            self._pregames[room_code] = pregame
        return pregame

    def begin_preview_pregame(
        self, display_name: str, sid: str, avatar: str | None = None
    ) -> tuple[str, Pregame]:
        """Preview-game pregame: human seat + inert dummy seat (sid None)."""
        token = str(uuid.uuid4())
        dummy_token = str(uuid.uuid4())
        pregame = Pregame(
            code="",  # assigned under the lock below
            seats=[
                PregameSeat(token=token, name=display_name or "You", sid=sid, avatar=avatar),
                PregameSeat(token=dummy_token, name="AI", sid=None, avatar=_PREVIEW_AI_AVATAR),
            ],
            preview=True,
        )
        with self._lock:
            code = self._generate_code()
            pregame.code = code
            self._pregames[code] = pregame
            self._token_to_room[token] = code
            self._sid_to_token[sid] = token
            self._token_role[token] = "player"
        return code, pregame

    def get_pregame(self, room_code: str) -> Pregame | None:
        """Look up an in-progress pregame by room code."""
        return self._pregames.get(room_code)

    def create_session_from_pregame(
        self, pregame: Pregame, first_seat_idx: int
    ) -> GameSession:
        """Build the GameSession once RPS resolves.

        THE RPS WINNER MUST BECOME ENGINE PLAYER INDEX 0 (P1 = whoever
        goes first — locked project convention). Seats/decks/tokens/sids
        are reordered winner-first BEFORE GameState creation so all
        downstream code (view filters, spectator fanout keyed on
        player_tokens[0], submit_action routing) is untouched. After this
        call, pregame seat idx == engine player idx.
        """
        if first_seat_idx == 1:
            pregame.seats = [pregame.seats[1], pregame.seats[0]]
        s0, s1 = pregame.seats

        preset = get_preset_deck(self._library)
        deck_p0 = s0.deck if s0.deck else preset
        deck_p1 = s1.deck if s1.deck else preset

        seed = secrets.randbelow(2**31)
        state, rng = GameState.new_game(seed, deck_p0, deck_p1)

        if pregame.preview:
            state = self._apply_preview_hand_tweaks(
                state, human_idx=0 if s0.sid is not None else 1
            )

        session = GameSession(
            state=state,
            rng=rng,
            library=self._library,
            player_tokens=(s0.token, s1.token),
            player_names=(s0.name, s1.name),
            player_sids=[s0.sid, s1.sid],
            player_decks=(deck_p0, deck_p1),
            player_avatars=(s0.avatar, s1.avatar),
        )
        pregame.session = session
        # Dummy seats (preview) keep their hand instantly.
        for i, seat in enumerate(pregame.seats):
            if seat.sid is None:
                pregame.mulligan_done[i] = True
        pregame.stage = "mulligan"
        return session

    def _apply_preview_hand_tweaks(self, state: GameState, human_idx: int) -> GameState:
        """Preview testing aid: Reanimated Bones is guaranteed in the
        HUMAN's opening hand (transform-mechanic testing). The full-hand-
        of-10 aid was retired 2026-07-08 — previews deal the normal 3/4.
        """
        import dataclasses as _dc
        try:
            bones = self._library.get_numeric_id("reanimated_bones")
            ph = state.players[human_idx]
            if bones not in ph.hand and bones in ph.deck:
                i = ph.deck.index(bones)
                new_ph = _dc.replace(
                    ph,
                    hand=ph.hand[:-1] + (bones,),
                    deck=ph.deck[:i] + (ph.hand[-1],) + ph.deck[i + 1:],
                )
                players = list(state.players)
                players[human_idx] = new_ph
                state = _dc.replace(state, players=tuple(players))
        except KeyError:
            pass  # card renamed/removed — preview still works without it
        return state

    def finish_pregame(self, room_code: str) -> GameSession:
        """Promote the pregame's session into the live-games dict."""
        with self._lock:
            pregame = self._pregames.pop(room_code)
            assert pregame.session is not None
            self._games[room_code] = pregame.session
            return pregame.session

    def request_rematch(self, token: str) -> tuple[str, GameSession | None, GameSession | None]:
        """Mark player as wanting a rematch. Returns (status, old_session, new_session).

        status:
          - 'waiting'  : recorded the request, waiting for opponent. new_session=None
          - 'started'  : both players requested, new game started. new_session is the fresh GameSession
          - 'no_game'  : token not in any active game. Both sessions=None

        Re-uses the same room code so clients don't need to rejoin.
        """
        with self._lock:
            room_code = self._token_to_room.get(token)
            if room_code is None:
                return ('no_game', None, None)
            session = self._games.get(room_code)
            if session is None:
                return ('no_game', None, None)

        with session.lock:
            player_idx = session.get_player_idx(token)
            if player_idx is None:
                return ('no_game', None, None)
            session.rematch_requested[player_idx] = True
            both = all(session.rematch_requested)
            if not both:
                return ('waiting', session, None)

        # Both requested -- create a fresh game with the same players
        seed = secrets.randbelow(2**31)
        coin = secrets.randbelow(2)  # re-flip P1/P2 assignment

        # Original session p0 / p1 info
        p0_token, p1_token = session.player_tokens
        p0_name, p1_name = session.player_names
        p0_sid, p1_sid = session.player_sids
        p0_deck, p1_deck = session.player_decks
        p0_av, p1_av = getattr(session, 'player_avatars', (None, None))

        # Re-flip: with 50% chance, swap who is P1 vs P2
        if coin == 0:
            new_tokens = (p0_token, p1_token)
            new_names  = (p0_name, p1_name)
            new_sids   = [p0_sid, p1_sid]
            new_decks  = (p0_deck, p1_deck)
            new_avatars = (p0_av, p1_av)
        else:
            new_tokens = (p1_token, p0_token)
            new_names  = (p1_name, p0_name)
            new_sids   = [p1_sid, p0_sid]
            new_decks  = (p1_deck, p0_deck)
            new_avatars = (p1_av, p0_av)

        preset = get_preset_deck(self._library)
        d0 = new_decks[0] if new_decks[0] else preset
        d1 = new_decks[1] if new_decks[1] else preset

        state, rng = GameState.new_game(seed, d0, d1)

        new_session = GameSession(
            state=state,
            rng=rng,
            library=self._library,
            player_tokens=new_tokens,
            player_names=new_names,
            player_sids=new_sids,
            player_decks=new_decks,
            player_avatars=new_avatars,
        )

        with self._lock:
            self._games[room_code] = new_session

        return ('started', session, new_session)

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

    def list_open_rooms(self) -> list[dict]:
        """Return a snapshot of WaitingRooms that still have an empty
        joiner slot — shown in the public lobby so players can click to
        join without needing a code. Full rooms and in-game sessions
        are excluded.
        """
        with self._lock:
            # Ghost-room TTL (user 2026-07-11): an unjoined room older than
            # OPEN_ROOM_TTL_SECONDS is pruned at listing time — covers AFK
            # creators whose tab stays open (disconnected creators are
            # already vacated eagerly in handle_disconnect).
            now = time.time()
            expired = [
                code for code, room in self._rooms.items()
                if room.joiner is None
                and now - room.created_at > OPEN_ROOM_TTL_SECONDS
            ]
            for code in expired:
                room = self._rooms.pop(code)
                t = room.creator.token
                self._token_to_room.pop(t, None)
                self._token_role.pop(t, None)
                for sid in [s for s, tok in self._sid_to_token.items() if tok == t]:
                    del self._sid_to_token[sid]
            snapshot = [
                {
                    "code": room.code,
                    "creator_name": room.creator.name,
                    "created_at": room.created_at,
                }
                for room in self._rooms.values()
                if room.joiner is None
            ]
        # Newest first so freshly-opened rooms are obvious.
        snapshot.sort(key=lambda r: r["created_at"], reverse=True)
        return snapshot

    def list_live_games(self) -> list[dict]:
        """Lightweight snapshot of IN-PROGRESS games for the lobby quick
        view (testing aid): scores, turn and minion positions only — no
        hidden information (hands/decks stay server-side).
        """
        with self._lock:
            games = list(self._games.items())
        out = []
        for code, session in games:
            try:
                st = session.state
                out.append({
                    "code": code,
                    "turn": st.turn_number,
                    "active": st.active_player_idx,
                    "phase": getattr(st.phase, "name", str(st.phase)),
                    "players": [
                        {"name": session.player_names[i], "hp": st.players[i].hp}
                        for i in (0, 1)
                    ],
                    "minions": [
                        {
                            "row": m.position[0],
                            "col": m.position[1],
                            "owner": int(m.owner),
                        }
                        for m in st.minions
                        if m.is_alive
                    ],
                })
            except Exception:  # noqa: BLE001 — a dying session must not break the lobby
                continue
        return out

    # ------------------------------------------------------------------
    # Spectator API (Phase 14.4-01)
    # ------------------------------------------------------------------

    def get_role(self, token: str) -> str | None:
        """Return 'player' | 'spectator' | None for a session token."""
        return self._token_role.get(token)

    def join_as_spectator(
        self, room_code: str, display_name: str, sid: str, god_mode: bool = False
    ) -> tuple[str, "WaitingRoom | GameSession | Pregame"]:
        """Attach a spectator to an existing room (waiting, pregame, or in-game).

        Returns (session_token, room_or_session). Raises ValueError if neither
        a waiting room nor an active game with that code exists. Spectators can
        join even when the room is "full" (2 players) or already in-game.
        """
        token = str(uuid.uuid4())
        with self._lock:
            room: WaitingRoom | GameSession | None = self._rooms.get(room_code)
            if room is None:
                room = self._games.get(room_code)
            if room is None:
                # PREGAME (2026-07-08): rooms mid-RPS/mulligan are neither
                # waiting nor in-game — spectators may still join and get
                # a status toast until game_start fires.
                room = self._pregames.get(room_code)
            if room is None:
                raise ValueError(f"Room '{room_code}' not found")
            slot = SpectatorSlot(
                token=token, name=display_name, sid=sid, god_mode=god_mode
            )
            self._room_spectators.setdefault(room_code, {})[token] = slot
            self._token_to_room[token] = room_code
            self._sid_to_token[sid] = token
            self._token_role[token] = 'spectator'
        return token, room

    def get_spectator_tokens(self, room_code: str) -> list[str]:
        """Return list of spectator session tokens for a room."""
        return list(self._room_spectators.get(room_code, {}).keys())

    def get_spectator(self, token: str) -> SpectatorSlot | None:
        """Look up a spectator slot by token."""
        room_code = self._token_to_room.get(token)
        if room_code is None:
            return None
        return self._room_spectators.get(room_code, {}).get(token)

    def remove_spectator(self, token: str) -> str | None:
        """Remove a spectator from its room and indexes. Returns room_code or None."""
        with self._lock:
            if self._token_role.get(token) != 'spectator':
                return None
            room_code = self._token_to_room.pop(token, None)
            self._token_role.pop(token, None)
            slot: SpectatorSlot | None = None
            if room_code is not None:
                bucket = self._room_spectators.get(room_code)
                if bucket is not None:
                    slot = bucket.pop(token, None)
                    if not bucket:
                        self._room_spectators.pop(room_code, None)
            if slot is not None and self._sid_to_token.get(slot.sid) == token:
                self._sid_to_token.pop(slot.sid, None)
            return room_code

    # ------------------------------------------------------------------
    # Sandbox API (Phase 14.6)
    # ------------------------------------------------------------------
    # Sandboxes are keyed by socket SID, not by session token, and live in a
    # parallel dict so the existing room/game/spectator code paths are 100%
    # untouched. One sandbox per browser tab. No multi-user sharing.

    def create_sandbox(self, sid: str) -> SandboxSession:
        """Create (or replace) the sandbox session for this SID."""
        with self._lock:
            session = SandboxSession(self._library, sid)
            self._sandboxes[sid] = session
            return session

    def get_sandbox(self, sid: str) -> SandboxSession | None:
        """Look up the sandbox session for this SID, if any."""
        return self._sandboxes.get(sid)

    def remove_sandbox(self, sid: str) -> None:
        """Drop the sandbox for this SID (called on disconnect)."""
        with self._lock:
            self._sandboxes.pop(sid, None)
