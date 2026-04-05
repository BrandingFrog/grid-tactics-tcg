# Phase 11: Server Foundation & Room System - Research

**Researched:** 2026-04-04
**Domain:** Flask-SocketIO WebSocket server with room code system for PvP card game
**Confidence:** HIGH

## Summary

Phase 11 establishes the WebSocket server foundation for online PvP. The existing Python game engine (`src/grid_tactics/`) is already perfectly structured for server integration: `GameState.new_game()` creates games, `resolve_action()` applies moves as pure functions, `legal_actions()` validates moves, and `to_dict()` serializes state. The server layer is purely additive -- no engine modifications needed except fixing the `_fatigue` global dict at `action_resolver.py:110`.

Flask-SocketIO 5.6.1 with threading mode and simple-websocket 1.1.0 is the verified stack. Flask 3.1.3 is already installed in the project's venv. The SocketIOTestClient built into Flask-SocketIO enables full pytest-based testing of the create-join-receive flow without any browser, satisfying the "programmatic WebSocket client" success criterion.

The primary implementation work is: (1) a room manager with code generation and session token tracking, (2) a game session wrapper that holds GameState + player identity, (3) Socket.IO event handlers for create_room/join_room/ready/game_start, and (4) fixing the `_fatigue` global dict for concurrent game safety.

**Primary recommendation:** Use Flask-SocketIO's built-in `SocketIOTestClient` for all Phase 11 testing. Build the server as a package at `src/grid_tactics/server/` with `pvp_server.py` at project root as the entry point. Session tokens (UUID4) stored per-player enable Phase 15 reconnection without coupling to ephemeral socket IDs.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Players enter a display name when creating or joining a room. Name shown to opponent. No persistence, no accounts -- ephemeral session only.
- **D-02:** Server accepts player-chosen decks: up to 3 copies of any card, max 30 cards total. The deck is submitted by the client when readying up.
- **D-03:** For Phase 11 testing (before deck builder UI exists), use a default preset deck so programmatic clients can connect and play.
- **D-04:** Deck builder UI deferred to Phase 13 (Board & Hand UI) -- extend the existing dashboard's Cards tab to let players construct their deck before joining.
- **D-05:** Both players must click "Ready" to start the game. This allows reviewing opponent name before committing.
- **D-06:** First player is chosen randomly (coin flip via server RNG). Not deterministic by room creator.
- **D-07:** Fix `_fatigue` global dict (action_resolver.py:110) -- module-level mutable state keyed by seed corrupts concurrent games. Must be moved into GameState or scoped per-game before multi-game server works.

### Claude's Discretion
- Room code format (length, character set, case sensitivity)
- Session token implementation (cookie vs header, format)
- In-memory data structures for room/game tracking
- Flask-SocketIO async mode selection (threading recommended per research)

### Deferred Ideas (OUT OF SCOPE)
- **Deck builder UI** -- Extend dashboard Cards tab to let players build decks (up to 3x per card, max 30). Deferred to Phase 13.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SERVER-01 | User can create a new game room and receive a shareable room code | Flask-SocketIO rooms + `secrets` module for code gen; RoomManager class pattern; SocketIOTestClient for verification |
| SERVER-02 | User can join an existing game room by entering a room code | Flask-SocketIO `join_room()` + WaitingRoom -> GameSession promotion; session tokens for identity; game_start event with initial state |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Language:** Python for game engine and server
- **Testing:** pytest (>=8.0, currently 9.0.2 installed). Run `pytest tests/ -q` for quick check.
- **Conventions:** IntEnum for all game constants, frozen dataclasses + `replace()`, card definitions in `data/cards/` JSON
- **Action space:** 1262 discrete actions. Layout documented in CLAUDE.md.
- **No FastAPI/Flask listed as "What NOT to Use"** in original CLAUDE.md -- but that was for the analytics dashboard context. CONTEXT.md explicitly decides Flask-SocketIO for PvP, overriding that general guidance.
- **Card library:** 21 cards (not 19 as in some docs -- 3 rat cards added recently). Loaded by `CardLibrary.from_directory()`.
- **GSD Workflow:** Must use GSD commands for execution.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask-SocketIO | 5.6.1 | WebSocket server with rooms, events, broadcasting | Latest stable (Feb 2026). Built-in room management maps to game rooms. Event-driven architecture maps to game actions. SocketIOTestClient for testing. |
| Flask | 3.1.3 | HTTP framework / app scaffold | Already installed in venv. Base for Flask-SocketIO. Serves entry point. |
| simple-websocket | 1.1.0 | WebSocket transport for threading mode | Required for real WebSocket protocol with `async_mode='threading'`. Latest stable (Oct 2024). |
| python-socketio | 5.16.x | Transitive dep of Flask-SocketIO | Provides protocol implementation. Also provides `socketio.Client` for programmatic testing outside pytest. |

**Verified on PyPI:** Flask-SocketIO 5.6.1, simple-websocket 1.1.0, Flask 3.1.3 (already installed).

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| secrets (stdlib) | -- | Cryptographically secure room codes and session tokens | Room code generation, session token creation |
| uuid (stdlib) | -- | UUID4 session tokens | Player identity tokens for reconnection readiness |
| threading (stdlib) | -- | Per-GameSession lock for thread safety | Protect state mutation in threading async mode |
| SocketIOTestClient | built-in | pytest testing of WebSocket events | All Phase 11 tests -- no external WebSocket client needed |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Flask-SocketIO | FastAPI + raw WebSockets | No rooms, no auto-reconnect, no broadcasting -- must build all manually |
| threading mode | gevent | gevent-websocket abandoned (2017). gevent itself fine but WebSocket transport broken without it |
| threading mode | eventlet | Deprecated, maintenance mode, Python 3.10+ issues |
| SocketIOTestClient | python-socketio.Client | Real network client; useful for integration testing but SocketIOTestClient is simpler for unit tests |
| In-memory dict | Redis | Single-process server with <50 rooms. Redis adds deployment complexity for zero benefit at this scale |

**Installation:**
```bash
pip install "Flask-SocketIO>=5.6,<6.0" "simple-websocket>=1.1"
```

**pyproject.toml addition:**
```toml
[project.optional-dependencies]
pvp = [
    "Flask-SocketIO>=5.6,<6.0",
    "simple-websocket>=1.1",
]
```

## Architecture Patterns

### Recommended Project Structure

```
src/grid_tactics/
  server/                    # NEW: PvP server package
    __init__.py
    app.py                   # Flask app + SocketIO setup
    room_manager.py          # Room creation, joining, lifecycle, session tokens
    game_session.py          # Per-game state management + player mapping
    events.py                # Socket.IO event handlers
    preset_deck.py           # Default 30-card deck for testing
  ... (existing engine files unchanged)

pvp_server.py                # NEW: entry point at project root (python pvp_server.py)

tests/
  test_pvp_server.py         # NEW: Phase 11 server tests using SocketIOTestClient
  test_fatigue_fix.py        # NEW: Verify _fatigue fix for concurrent games
```

### Pattern 1: Event-Driven State Machine (Not Game Loop)

**What:** The server waits for WebSocket events, processes them, emits results. No continuous game loop.

**When to use:** Always for PvP. The existing `game_loop.py` runs AI-vs-AI games in a loop. PvP is event-driven -- the server waits for human input.

**Example:**
```python
# Server processes one event at a time per game session
@socketio.on('action')
def handle_action(data):
    session = room_manager.get_session_by_token(get_player_token())
    if session is None:
        emit('error', {'msg': 'Not in a game'})
        return
    try:
        action = reconstruct_action(data)
        new_state = session.process_action(action, get_player_token())
        emit_state_to_players(session)
    except ValueError as e:
        emit('error', {'msg': str(e)})
```

### Pattern 2: Session Token Identity (Not Socket ID)

**What:** Each player receives a UUID4 session token on create/join. All player identity lookups use this token, not `request.sid`.

**When to use:** Always. Socket IDs change on every reconnection. Session tokens persist.

**Example:**
```python
import uuid

def create_session_token() -> str:
    return str(uuid.uuid4())

# On create_room: generate token, return it to client
# On join_room: generate token, return it to client  
# Client stores token, sends it with every event (or via auth dict)
# Server maps token -> player slot in GameSession
```

### Pattern 3: Two-Phase Room Lifecycle

**What:** Room starts as WaitingRoom (one player), promotes to GameSession (two players ready).

**When to use:** The create-join-ready flow requires intermediate state.

**Flow:**
```
create_room -> WaitingRoom(code, creator_token, creator_name)
join_room   -> WaitingRoom gains joiner info  
ready (P1)  -> WaitingRoom records P1 ready
ready (P2)  -> WaitingRoom promotes to GameSession, game_start emitted
```

### Pattern 4: SocketIOTestClient for Testing

**What:** Flask-SocketIO's built-in test client for pytest. No real network, no ports, no threads.

**When to use:** All Phase 11 tests.

**Example:**
```python
# Source: Flask-SocketIO test_socketio.py
def test_create_and_join_room(app, socketio):
    client1 = socketio.test_client(app, auth={'token': 'tok1'})
    client1.emit('create_room', {'display_name': 'Alice'})
    received = client1.get_received()
    room_code = received[0]['args'][0]['room_code']

    client2 = socketio.test_client(app, auth={'token': 'tok2'})
    client2.emit('join_room', {'room_code': room_code, 'display_name': 'Bob'})
    # Both clients should receive room_joined
```

### Anti-Patterns to Avoid

- **Client-side game logic:** Never compute legal_actions() or resolve_action() in JavaScript. Server is single source of truth.
- **Full state broadcast to room:** Never `emit('state', full_dict, to=room_code)`. Always emit per-player filtered views to individual SIDs. (Phase 12 concern, but architecture must support it from day 1.)
- **Modifying engine for server needs:** All server concerns (SID mapping, room codes, timers) live in `server/` modules. Import from `grid_tactics/` but never modify it.
- **Storing game state in database:** Games are ephemeral. In-memory dict only. No Supabase writes for active game state.
- **Using socket SID as player identity:** SIDs are ephemeral. Use session tokens.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Room management | Custom room tracking | Flask-SocketIO `join_room()`, `leave_room()`, `emit(to=room)` | Built-in, tested, handles edge cases |
| Random room codes | Custom RNG | `secrets.token_urlsafe(4)` or `secrets.choice()` | Cryptographically secure, stdlib |
| Session tokens | Custom token scheme | `uuid.uuid4()` | Standard, no collisions, no crypto needed |
| WebSocket protocol | Raw WebSockets | Socket.IO protocol (via Flask-SocketIO) | Auto-reconnect, fallback, rooms, namespaces |
| Test WebSocket clients | Spin up real server + client | `SocketIOTestClient` | No network, no ports, synchronous, pytest-friendly |
| Deck validation | Custom validation | `CardLibrary.validate_deck()` | Already exists, enforces MAX_COPIES_PER_DECK=3, MIN_DECK_SIZE=30 |
| Action reconstruction | Manual dict parsing | Pattern from `GameState.from_dict()` pending_action block | Already handles all Action fields with proper type conversion |
| Thread safety | Custom synchronization | `threading.Lock()` per GameSession | Standard, simple, sufficient for threading mode |

**Key insight:** The existing engine already has `validate_deck()`, `to_dict()`, `from_dict()`, and action reconstruction patterns. The server layer should reuse these directly, not reinvent them.

## Common Pitfalls

### Pitfall 1: _fatigue Global Dict Corrupts Concurrent Games

**What goes wrong:** `action_resolver.py:110` defines `_fatigue = {}` at module level, keyed by `state.seed`. Two games with the same seed share fatigue counters. Even different seeds accumulate entries that are never cleaned up (memory leak).

**Why it happens:** The fatigue dict was written for single-game contexts (tests, AI training). Module-level mutable state is invisible until multiple games run concurrently.

**How to avoid:** Move fatigue tracking into GameState itself. Add a `fatigue_counts: tuple[int, int] = (0, 0)` field to the frozen dataclass. Update `_apply_pass()` to read/write from state instead of the module dict.

**Warning signs:** Two concurrent games where PASS actions affect the wrong game's HP.

### Pitfall 2: Socket ID Used as Player Identity

**What goes wrong:** Player disconnects and reconnects. New socket ID assigned. Server can't find the player's game.

**Why it happens:** `request.sid` changes on every connection.

**How to avoid:** Assign UUID4 session tokens on create/join. Store token in client (auth dict or localStorage). Map tokens to player slots, update socket SID on reconnect.

**Warning signs:** "Not in a game" error after browser refresh.

### Pitfall 3: Room Code Collisions or Guessing

**What goes wrong:** Short codes (4 chars) may collide. Predictable codes allow uninvited players to join.

**Why it happens:** Insufficient randomness or too-small code space.

**How to avoid:** Use 6-character uppercase alphanumeric (36^6 = 2.1 billion combinations). Generate with `secrets` module (crypto-secure). Check uniqueness against active rooms. For 50 concurrent rooms, collision probability is negligible.

**Warning signs:** Room creation returns an existing code, or strangers join games.

### Pitfall 4: Ready State Race Condition

**What goes wrong:** Both players send "ready" simultaneously. Two game_start events emitted, or game created twice.

**Why it happens:** Threading mode handles events in separate threads.

**How to avoid:** Use a `threading.Lock()` on the WaitingRoom/GameSession. The second "ready" event acquires the lock, finds the game already started, and receives the existing state instead of creating a new game.

**Warning signs:** Duplicate game_start events or "room not found" errors after both players ready up.

### Pitfall 5: Preset Deck Not Meeting MIN_DECK_SIZE

**What goes wrong:** Default preset deck has fewer than 30 cards. `CardLibrary.validate_deck()` rejects it. Game creation fails.

**Why it happens:** 21 unique cards exist. Even with 1 copy each, that's only 21. Must use multiple copies to reach 30.

**How to avoid:** Build a 30-card preset using `CardLibrary.build_deck()`. Distribute copies across all 21 cards (some at 1 copy, some at 2). Validate at server startup. Test that the preset deck passes `validate_deck()`.

**Warning signs:** "Invalid deck" error when creating a game.

### Pitfall 6: GameState.new_game() Returns (state, rng) Tuple

**What goes wrong:** Developer forgets that `new_game()` returns both the state AND the RNG. The RNG must be stored alongside the state in the GameSession because `resolve_action()` may need it for effects that involve randomness.

**Why it happens:** The RNG is mutable and separate from the frozen GameState by design.

**How to avoid:** GameSession stores both `self.state` and `self.rng`. However, checking the code: `resolve_action()` signature is `(state, action, library) -> GameState` -- it does NOT take `rng`. The RNG is only used during `new_game()` for deck shuffling and initial setup. After game creation, the RNG is not needed for action resolution (the game is deterministic from that point). Store the RNG anyway for completeness, but it is not passed to `resolve_action()`.

**Warning signs:** TypeError when calling `resolve_action()` with wrong argument count.

## Code Examples

### Action Reconstruction from Client Payload

```python
# Source: game_state.py:202-215 (existing pattern for pending_action)
from grid_tactics.actions import Action
from grid_tactics.enums import ActionType

def reconstruct_action(data: dict) -> Action:
    """Convert client JSON payload to engine Action dataclass.
    
    Mirrors the pattern in GameState.from_dict() for pending_action.
    """
    return Action(
        action_type=ActionType(data['action_type']),
        card_index=data.get('card_index'),
        position=tuple(data['position']) if data.get('position') else None,
        minion_id=data.get('minion_id'),
        target_id=data.get('target_id'),
        target_pos=tuple(data['target_pos']) if data.get('target_pos') else None,
    )
```

### Preset Deck Construction

```python
# Source: card_library.py:109-122 (build_deck method)
from pathlib import Path
from grid_tactics.card_library import CardLibrary

library = CardLibrary.from_directory(Path("data/cards"))

# 21 cards available. Need 30 total. MAX_COPIES_PER_DECK=3.
# Strategy: 2 copies of 9 cheap/versatile cards (18) + 1 copy of remaining 12 = 30
PRESET_DECK = library.build_deck({
    # 2 copies (9 cards = 18)
    "fire_imp": 2,        # 1-cost minion
    "shadow_stalker": 2,  # 1-cost minion  
    "rat": 2,             # 1-cost minion
    "light_cleric": 2,    # 2-cost minion
    "wind_archer": 2,     # 2-cost minion
    "dark_assassin": 2,   # 2-cost minion
    "dark_drain": 2,      # 2-cost magic
    "shield_block": 2,    # 1-cost react
    "dark_mirror": 2,     # 1-cost react
    # 1 copy (12 cards = 12)
    "furryroach": 1,      # 1-cost minion
    "counter_spell": 1,   # 2-cost react
    "holy_light": 1,      # 2-cost magic
    "fireball": 1,        # 3-cost magic
    "holy_paladin": 1,    # 3-cost minion
    "iron_guardian": 1,    # 3-cost minion
    "dark_sentinel": 1,   # 3-cost minion
    "shadow_knight": 1,   # 3-cost minion
    "giant_rat": 1,       # 3-cost minion
    "stone_golem": 1,     # 4-cost minion
    "flame_wyrm": 1,      # 5-cost minion
    "inferno": 1,         # 7-cost magic
})
# Total: 18 + 12 = 30 cards. All valid. Passes validate_deck().
```

### Flask-SocketIO App Setup

```python
# Source: Flask-SocketIO docs, threading mode pattern
from flask import Flask
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key'

socketio = SocketIO(
    app,
    async_mode='threading',
    cors_allowed_origins='*',  # Dev only. Restrict in production.
)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
```

### SocketIOTestClient Usage in pytest

```python
# Source: Flask-SocketIO test_socketio.py + API reference
import pytest
from grid_tactics.server.app import create_app, socketio

@pytest.fixture
def app():
    app = create_app(testing=True)
    return app

@pytest.fixture
def client1(app):
    return socketio.test_client(app)

@pytest.fixture
def client2(app):
    return socketio.test_client(app)

def test_create_room(client1):
    client1.emit('create_room', {'display_name': 'Alice'})
    received = client1.get_received()
    assert len(received) == 1
    assert received[0]['name'] == 'room_created'
    assert 'room_code' in received[0]['args'][0]
    assert 'session_token' in received[0]['args'][0]

def test_full_create_join_ready_flow(client1, client2):
    # Create
    client1.emit('create_room', {'display_name': 'Alice'})
    r1 = client1.get_received()
    room_code = r1[0]['args'][0]['room_code']
    
    # Join
    client2.emit('join_room', {'room_code': room_code, 'display_name': 'Bob'})
    # Both clients receive room_joined
    
    # Ready up
    client1.emit('ready', {})
    client2.emit('ready', {})
    
    # Both should receive game_start
    r1 = client1.get_received()
    r2 = client2.get_received()
    game_starts_1 = [m for m in r1 if m['name'] == 'game_start']
    game_starts_2 = [m for m in r2 if m['name'] == 'game_start']
    assert len(game_starts_1) == 1
    assert len(game_starts_2) == 1
```

### _fatigue Fix Pattern

```python
# Current (BROKEN for concurrent games):
# action_resolver.py:110
_fatigue = {}  # module-level mutable state

# Fixed: Add to GameState frozen dataclass
@dataclass(frozen=True, slots=True)
class GameState:
    # ... existing fields ...
    fatigue_counts: tuple[int, int] = (0, 0)  # (p0_count, p1_count)

# Updated _apply_pass:
def _apply_pass(state: GameState) -> GameState:
    active_idx = state.active_player_idx
    counts = list(state.fatigue_counts)
    counts[active_idx] += 1
    dmg = counts[active_idx] * 10
    player = state.players[active_idx]
    new_player = replace(player, hp=player.hp - dmg)
    new_players = _replace_player(state.players, active_idx, new_player)
    return replace(state, players=new_players, fatigue_counts=tuple(counts))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| eventlet async mode | threading + simple-websocket | 2024-2025 | eventlet deprecated. Threading is now recommended for new Flask-SocketIO projects |
| gevent + gevent-websocket | threading + simple-websocket | gevent-websocket abandoned 2017 | gevent-websocket never updated past Python 2.7/3.5 |
| Socket ID for identity | Session tokens | Best practice | Socket IDs change on reconnect. Tokens enable Phase 15 reconnection |
| DRAW as explicit action | Auto-draw at turn start | Already in engine | Engine auto-draws at turn transition in react_stack.py:280-285 |

## Event Contract (Phase 11 Scope)

### Client -> Server

| Event | Payload | When |
|-------|---------|------|
| `create_room` | `{ display_name: str }` | Player wants to create a new room |
| `join_room` | `{ room_code: str, display_name: str }` | Player enters a room code to join |
| `ready` | `{}` | Player signals they are ready to start |

### Server -> Client

| Event | Payload | When |
|-------|---------|------|
| `room_created` | `{ room_code: str, session_token: str }` | Room created successfully |
| `room_joined` | `{ room_code: str, players: [{name, ready}], session_token: str }` | Player joined room |
| `player_joined` | `{ display_name: str }` | Notify creator that opponent joined |
| `player_ready` | `{ player_name: str }` | Notify that a player readied up |
| `game_start` | `{ your_player_idx: int, state: dict, opponent_name: str }` | Both players ready, game begins |
| `error` | `{ msg: str }` | Invalid operation |

### Key Design Notes

- **game_start includes initial state** as a filtered `to_dict()` output. Phase 12 adds view filtering -- Phase 11 can send full state since no UI is inspecting it yet, but the architecture should support per-player filtering from the start.
- **session_token** returned at create/join time. Client stores it for reconnection (Phase 15).
- **your_player_idx** tells the client which side they are (0 or 1), determined by D-06 coin flip.

## Open Questions

1. **Preset deck exact composition**
   - What we know: 21 cards available, need exactly 30, max 3 copies each. `build_deck()` validates.
   - What's unclear: Exact card counts for a balanced preset. The example above (9 cards at 2 copies + 12 at 1 copy = 30) is one option.
   - Recommendation: Claude's discretion per CONTEXT.md. Build a mana-curve-balanced preset. Test that it passes `validate_deck()`. Exact counts are a gameplay tuning concern, not a technical blocker.

2. **First player randomization seed source**
   - What we know: D-06 says random coin flip. `GameState.new_game()` always starts with `active_player_idx=0`.
   - What's unclear: Should we randomize which player is P1 (creator vs joiner as P1/P2), or always make creator P1 but randomize `active_player_idx`?
   - Recommendation: Randomize player assignment (creator could be P1 or P2). Then `active_player_idx=0` means P1 goes first as usual, but which human is P1 is random. This avoids modifying `new_game()`.

3. **Auth dict vs custom event for session token**
   - What we know: Socket.IO supports `auth` dict on connect. Alternatively, tokens can be passed in event payloads.
   - What's unclear: Which approach is cleaner for Phase 15 reconnection.
   - Recommendation: Return the token in the `room_created`/`room_joined` response. Client stores it. On reconnect, client passes token in the `auth` dict of the Socket.IO connect call. Server checks `auth` on connect to resume session.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | Yes | 3.12.10 | -- |
| Flask | Server framework | Yes | 3.1.3 | -- |
| Flask-SocketIO | WebSocket server | No | -- | pip install (3 seconds) |
| simple-websocket | WebSocket transport | No | -- | pip install (1 second) |
| pytest | Testing | Yes | 9.0.2 | -- |
| numpy | GameRNG (indirect) | Yes | (installed) | -- |

**Missing dependencies with no fallback:** None -- Flask-SocketIO and simple-websocket are a `pip install` away.

**Missing dependencies with fallback:** None.

**Action required:** `pip install "Flask-SocketIO>=5.6,<6.0" "simple-websocket>=1.1"` before implementation.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `pytest tests/test_pvp_server.py -x -q` |
| Full suite command | `pytest tests/ -q` |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SERVER-01 | Create room, receive room code | unit | `pytest tests/test_pvp_server.py::test_create_room -x` | No -- Wave 0 |
| SERVER-01 | Room code is unique alphanumeric | unit | `pytest tests/test_pvp_server.py::test_room_code_format -x` | No -- Wave 0 |
| SERVER-01 | Session token returned on create | unit | `pytest tests/test_pvp_server.py::test_create_room_returns_token -x` | No -- Wave 0 |
| SERVER-02 | Join room by code | unit | `pytest tests/test_pvp_server.py::test_join_room -x` | No -- Wave 0 |
| SERVER-02 | Both players receive game_start after ready | unit | `pytest tests/test_pvp_server.py::test_full_create_join_ready_flow -x` | No -- Wave 0 |
| SERVER-02 | game_start contains initial state | unit | `pytest tests/test_pvp_server.py::test_game_start_has_state -x` | No -- Wave 0 |
| SERVER-02 | Invalid room code rejected | unit | `pytest tests/test_pvp_server.py::test_join_invalid_room -x` | No -- Wave 0 |
| D-01 | Display names included in events | unit | `pytest tests/test_pvp_server.py::test_display_names -x` | No -- Wave 0 |
| D-03 | Preset deck valid (30 cards, <=3 copies) | unit | `pytest tests/test_pvp_server.py::test_preset_deck_valid -x` | No -- Wave 0 |
| D-05 | Ready flow required before game start | unit | `pytest tests/test_pvp_server.py::test_ready_required -x` | No -- Wave 0 |
| D-06 | First player randomized | unit | `pytest tests/test_pvp_server.py::test_first_player_random -x` | No -- Wave 0 |
| D-07 | _fatigue fix for concurrent games | unit | `pytest tests/test_fatigue_fix.py -x` | No -- Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/test_pvp_server.py tests/test_fatigue_fix.py -x -q`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_pvp_server.py` -- covers SERVER-01, SERVER-02, D-01, D-03, D-05, D-06
- [ ] `tests/test_fatigue_fix.py` -- covers D-07
- [ ] Flask-SocketIO install: `pip install "Flask-SocketIO>=5.6,<6.0" "simple-websocket>=1.1"`

## Existing Engine Interface Summary

These are the exact function signatures and return types the server will call.

### GameState.new_game()
```python
@classmethod
def new_game(cls, seed: int, deck_p1: tuple[int, ...], deck_p2: tuple[int, ...]) -> tuple[GameState, GameRNG]
```
- Returns `(state, rng)` tuple. RNG is mutable, stored separately.
- `active_player_idx` always starts at 0.
- Draws starting hands (P1=3, P2=4).

### legal_actions()
```python
def legal_actions(state: GameState, library: CardLibrary) -> tuple[Action, ...]
```
- Returns all valid actions for current state. Never includes illegal actions.
- PASS is always present.
- During REACT phase, only react cards and PASS are legal.

### resolve_action()
```python
def resolve_action(state: GameState, action: Action, library: CardLibrary) -> GameState
```
- Pure function (except `_fatigue` -- to be fixed). State in, state out.
- Handles both ACTION and REACT phases.
- Internally handles turn transitions, mana regen, auto-draw.

### GameState.to_dict()
```python
def to_dict(self) -> dict
```
- Full serialization including board, players (with hand/deck), minions, phase, etc.
- Converts IntEnum to int, tuples to lists for JSON compatibility.
- `json.dumps()` works on the output.

### CardLibrary.from_directory()
```python
@classmethod
def from_directory(cls, path: Path) -> CardLibrary
```
- Loads all `*.json` from path. 21 cards currently.
- Deterministic numeric IDs (sorted alphabetically by card_id).

### CardLibrary.validate_deck()
```python
def validate_deck(self, deck: tuple[int, ...]) -> list[str]
```
- Returns list of error strings (empty = valid).
- Checks MIN_DECK_SIZE=30, MAX_COPIES_PER_DECK=3, valid IDs.

### CardLibrary.build_deck()
```python
def build_deck(self, card_counts: dict[str, int]) -> tuple[int, ...]
```
- Converts `{card_id_str: count}` to numeric tuple.
- Validates internally; raises ValueError on invalid deck.

## Sources

### Primary (HIGH confidence)
- Existing codebase: `game_state.py`, `action_resolver.py`, `legal_actions.py`, `card_library.py`, `actions.py`, `types.py`, `enums.py`, `rng.py` -- direct code inspection
- [Flask-SocketIO PyPI](https://pypi.org/project/Flask-SocketIO/) -- version 5.6.1 verified
- [simple-websocket PyPI](https://pypi.org/project/simple-websocket/) -- version 1.1.0 verified
- [Flask PyPI](https://pypi.org/project/Flask/) -- version 3.1.3 already installed
- [Flask-SocketIO test_client.py source](https://github.com/miguelgrinberg/Flask-SocketIO/blob/main/src/flask_socketio/test_client.py) -- SocketIOTestClient API
- [Flask-SocketIO test_socketio.py](https://github.com/miguelgrinberg/Flask-SocketIO/blob/main/test_socketio.py) -- Test examples for rooms, multiple clients

### Secondary (MEDIUM confidence)
- [Flask-SocketIO async mode discussion](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1915) -- Threading recommendation
- [python-socketio client docs](https://python-socketio.readthedocs.io/en/latest/client.html) -- Programmatic client API
- `.planning/research/STACK.md` -- Prior research on Flask-SocketIO stack selection
- `.planning/research/ARCHITECTURE.md` -- Server component design patterns
- `.planning/research/PITFALLS.md` -- 12 documented pitfalls

### Tertiary (LOW confidence)
- None. All findings verified against code or official sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- versions verified on PyPI, Flask already installed
- Architecture: HIGH -- engine API verified by direct code inspection, all function signatures confirmed
- Pitfalls: HIGH -- `_fatigue` global confirmed at line 110, Socket ID ephemerality is documented Socket.IO behavior
- Testing: HIGH -- SocketIOTestClient API confirmed from source code

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (stable domain, 30-day validity)
