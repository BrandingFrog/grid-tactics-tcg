# Architecture Patterns: Online PvP Dueling

**Domain:** Real-time multiplayer card game server (Flask-SocketIO + existing Python game engine)
**Researched:** 2026-04-04
**Overall confidence:** HIGH

## Executive Summary

The existing Python game engine is already structured for clean PvP integration. The frozen-dataclass architecture with `resolve_action()` as a single entry point, `legal_actions()` for validation, and `GameState.to_dict()`/`from_dict()` for serialization means the server layer is a thin orchestration wrapper -- it does NOT need to modify engine internals.

The PvP server adds a **Layer 5: Multiplayer Server** on top of the existing architecture, wrapping the Python game engine (Layer 1) directly and bypassing the RL layers entirely. Three new components are needed: (1) a Flask-SocketIO game server that holds active game sessions in memory, (2) a room/session manager that maps room codes to game state + player SIDs, and (3) a state sanitizer that strips hidden information before emitting per-player views.

The existing `game_loop.py` pattern (call `legal_actions()`, pick action, call `resolve_action()`) becomes the server's action processing pipeline, with the "pick action" step replaced by receiving player input over WebSocket.

---

## Recommended Architecture

### System Overview

```
Browser (P1)                    Browser (P2)
    |                               |
    | socket.io-client              | socket.io-client
    |                               |
    +---------- WebSocket ----------+
                    |
     +------------------------------+
     |   LAYER 5: PVP SERVER (NEW)  |
     |  Flask-SocketIO  |  Rooms    |
     |  ViewFilter  |  TimerMgr     |
     +------------------------------+
                    |
         wraps directly (no RL layer)
                    |
     +------------------------------+
     |  LAYER 1: GAME ENGINE (existing)  |
     |  GameState  |  ActionResolver     |
     |  LegalActions  |  ReactStack      |
     |  CardLibrary  |  Board/Player     |
     +------------------------------+

Existing layers (unchanged, not involved in PvP):
  Layer 2: RL Environment (Gymnasium/PettingZoo)
  Layer 3: Training Pipeline (MaskablePPO, tensor engine)
  Layer 4: Dashboard (Vercel + Supabase)
```

The PvP server has **zero ML dependencies** -- it runs on the cheapest possible server with just Flask, Flask-SocketIO, and the core game engine.

### Component Boundaries

| Component | Location | Responsibility | Communicates With |
|-----------|----------|---------------|-------------------|
| **Flask-SocketIO Server** | `server/app.py` (NEW) | WebSocket event routing, CORS, static file serving, startup | RoomManager, EventHandlers |
| **RoomManager** | `server/room_manager.py` (NEW) | Room CRUD, player-to-room mapping, SID tracking, cleanup | GameSession instances |
| **GameSession** | `server/game_session.py` (NEW) | Holds one game: GameState + RNG + player SIDs, processes actions, thread-safe | GameState, resolve_action, legal_actions, CardLibrary |
| **ViewFilter** | `server/view_filter.py` (NEW) | Strips opponent hand/deck from state dicts, builds per-player views | GameState.to_dict() output |
| **TimerManager** | `server/timer_manager.py` (NEW) | Per-game background task for turn timeouts, auto-pass on expiry | GameSession, Flask-SocketIO background tasks |
| **Event Handlers** | `server/events.py` (NEW) | Socket.IO event handlers (create_room, join_room, action, etc.) | RoomManager, GameSession, ViewFilter |
| **GameState** | `src/grid_tactics/game_state.py` (REUSE) | Immutable game state with to_dict/from_dict | Board, Player, MinionInstance |
| **resolve_action** | `src/grid_tactics/action_resolver.py` (REUSE) | Validates and applies actions, dead cleanup, game over detection | GameState, CardLibrary |
| **legal_actions** | `src/grid_tactics/legal_actions.py` (REUSE) | Enumerates all valid actions for current state | GameState, CardLibrary |
| **CardLibrary** | `src/grid_tactics/card_library.py` (REUSE) | Card definitions loaded from JSON at startup | CardLoader, data/cards/*.json |
| **Web UI** | `web-pvp/` (NEW) | Browser game board, hand display, action selection | socket.io-client, server via WebSocket |

### New vs. Reused Code

**Reused as-is (zero modifications needed):**
- `game_state.py` -- GameState with to_dict()/from_dict() is already serialization-ready
- `action_resolver.py` -- resolve_action() is a pure function: state in, state out
- `legal_actions.py` -- legal_actions() is a pure function: state in, actions out
- `card_library.py` -- CardLibrary.from_directory() loads once at startup
- `card_loader.py` -- JSON card loading
- `cards.py` -- CardDefinition frozen dataclass
- `actions.py` -- Action dataclass + convenience constructors
- `enums.py` -- All IntEnum types (ActionType, TurnPhase, PlayerSide, etc.)
- `types.py` -- Constants (GRID_ROWS, STARTING_HP, etc.)
- `react_stack.py` -- React window handling (called internally by resolve_action)
- `board.py`, `player.py`, `minion.py`, `rng.py` -- All game primitives

**New components to build:**
- `server/app.py` -- Flask app + SocketIO initialization + entry point
- `server/room_manager.py` -- Room code generation, session registry, SID mapping
- `server/game_session.py` -- Per-game state container + action processing + locking
- `server/view_filter.py` -- Hidden information filtering per player
- `server/timer_manager.py` -- Background turn timeout tasks
- `server/events.py` -- All SocketIO event handlers
- `web-pvp/index.html` -- Game board UI (separate from analytics dashboard)

**Key insight:** The existing engine's immutable-state, pure-function design means the server layer is purely additive. No engine code needs modification. The `resolve_action(state, action, library) -> new_state` signature is already a perfect RPC-style interface.

---

## Data Flow: Browser Click to State Update

### Full Action Lifecycle

```
1. BROWSER (P1): User clicks "Play Fire Imp at (1,2)"
   |
   v
2. CLIENT JS: Constructs action payload
   emit('action', {
     action_type: 0, card_index: 2, position: [1, 2]
   })
   |
   v
3. FLASK-SOCKETIO: @socketio.on('action') handler fires
   |
   v
4. EVENT HANDLER (events.py):
   a. Look up GameSession by request.sid via RoomManager
   b. Validate request.sid matches current active player SID
   c. Reconstruct Action dataclass from payload dict
   |
   v
5. GAME SESSION (game_session.py):
   a. Acquire per-session threading lock
   b. Validate action is in legal_actions(state, library)
   c. new_state = resolve_action(state, action, library)
   d. Store new_state (replace self.state)
   e. Check new_state.phase -- if REACT, set react_player as "active"
   f. Check new_state.is_game_over
   |
   v
6. VIEW FILTER (view_filter.py):
   a. p1_view = filter_for_player(new_state.to_dict(), player_idx=0)
      -- strips P2 hand contents (shows count only)
      -- strips both decks (shows count only)
   b. p2_view = filter_for_player(new_state.to_dict(), player_idx=1)
      -- strips P1 hand contents (shows count only)
      -- strips both decks (shows count only)
   |
   v
7. FLASK-SOCKETIO EMIT (per-player, NOT room broadcast):
   a. emit('state_update', {state: p1_view, legal_actions: [...]}, to=p1_sid)
   b. emit('state_update', {state: p2_view, legal_actions: []}, to=p2_sid)
   c. If game over:
      emit('game_over', { winner, reason, final_hp }, to=room_code)
   |
   v
8. BROWSER (P1 + P2): Both receive their filtered view, UI re-renders
```

### React Window Flow

The react window creates an additional decision point mid-turn. The existing engine handles this internally:

```
P1 plays action
  -> resolve_action() sets phase=REACT, react_player_idx=1
  -> Server emits state to both players
  -> P2 sees legal react cards, P1 sees "waiting for opponent"

P2 either:
  a. Plays a react card -> resolve_action() handles REACT phase
     -> engine chains react (react_player_idx flips to P1 for counter-react)
     -> Server emits state, P1 may counter-react
  b. Passes -> resolve_react_stack() resolves stack LIFO
     -> Turn advances, P2 becomes active player for next turn
     -> Auto-draw occurs for P2
     -> Server emits new state to both players

Server never needs to manage react flow -- the engine already handles it
via TurnPhase.REACT and react_player_idx in GameState.
```

### Action Reconstruction

The client sends a JSON action payload. The server reconstructs the frozen `Action` dataclass:

```python
# server/events.py
from grid_tactics.actions import Action
from grid_tactics.enums import ActionType

def _reconstruct_action(data: dict) -> Action:
    """Convert client action payload to engine Action dataclass."""
    return Action(
        action_type=ActionType(data['action_type']),
        card_index=data.get('card_index'),
        position=tuple(data['position']) if data.get('position') else None,
        minion_id=data.get('minion_id'),
        target_id=data.get('target_id'),
        target_pos=tuple(data['target_pos']) if data.get('target_pos') else None,
    )
```

### Action Serialization (wire format)

The `Action` dataclass fields map directly to JSON, enabling simple client-side construction:

| Action Field | JSON Key | JSON Type | Notes |
|-------------|----------|-----------|-------|
| `action_type` | `action_type` | number (0-6) | ActionType IntEnum value |
| `card_index` | `card_index` | number or null | Index in player's hand tuple |
| `position` | `position` | [row, col] or null | Deploy location / move target |
| `minion_id` | `minion_id` | number or null | Minion instance_id |
| `target_id` | `target_id` | number or null | Attack target instance_id |
| `target_pos` | `target_pos` | [row, col] or null | Effect target position |

The client constructs action payloads from UI interactions:
- Click card in hand + click board cell: `{action_type: 0, card_index: N, position: [r, c]}`
- Click owned minion + click forward cell: `{action_type: 1, minion_id: N, position: [r, c]}`
- Click owned minion + click enemy minion: `{action_type: 2, minion_id: N, target_id: M}`
- Click sacrifice button on eligible minion: `{action_type: 6, minion_id: N}`
- Click pass button: `{action_type: 4}`
- Click react card in hand: `{action_type: 5, card_index: N}`

---

## Detailed Component Designs

### 1. GameSession (server/game_session.py)

The central per-game container. Wraps the immutable GameState with mutable session metadata.

```python
import threading
import time
from grid_tactics.actions import Action
from grid_tactics.action_resolver import resolve_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.rng import GameRNG

class GameSession:
    """One active PvP game. Holds state, RNG, player mapping."""

    def __init__(self, room_code: str, library: CardLibrary,
                 p1_sid: str, p2_sid: str,
                 deck_p1: tuple[int, ...], deck_p2: tuple[int, ...],
                 seed: int):
        self.room_code = room_code
        self.library = library
        self.p1_sid = p1_sid
        self.p2_sid = p2_sid
        self.state: GameState
        self.rng: GameRNG
        self.state, self.rng = GameState.new_game(seed, deck_p1, deck_p2)
        self.created_at: float = time.time()
        self.timer_cancelled: bool = False
        self._lock = threading.Lock()

    def get_active_sid(self) -> str:
        """Return the SID of whoever should act next."""
        if self.state.phase == TurnPhase.REACT:
            idx = self.state.react_player_idx
        else:
            idx = self.state.active_player_idx
        return self.p1_sid if idx == 0 else self.p2_sid

    def get_player_idx(self, sid: str) -> int:
        """Map a socket SID to player index (0 or 1)."""
        if sid == self.p1_sid:
            return 0
        elif sid == self.p2_sid:
            return 1
        raise ValueError(f"Unknown SID")

    def process_action(self, action: Action, player_sid: str) -> GameState:
        """Validate and apply an action. Thread-safe."""
        with self._lock:
            if player_sid != self.get_active_sid():
                raise ValueError("Not your turn")

            valid = legal_actions(self.state, self.library)
            if action not in valid:
                raise ValueError("Illegal action")

            self.state = resolve_action(self.state, action, self.library)
            return self.state
```

**Key design decision:** GameSession holds a mutable reference (`self.state`) to an immutable GameState. Each `process_action` call replaces `self.state` with a new frozen instance. The threading lock prevents race conditions if two WebSocket events arrive nearly simultaneously.

### 2. RoomManager (server/room_manager.py)

Maps room codes to GameSessions. Handles creation, joining, and cleanup.

```python
import random
import string
import time
from dataclasses import dataclass
from typing import Optional

@dataclass
class WaitingRoom:
    code: str
    p1_sid: str
    created_at: float

class RoomManager:
    def __init__(self):
        self._rooms: dict[str, GameSession] = {}
        self._sid_to_room: dict[str, str] = {}
        self._waiting: dict[str, WaitingRoom] = {}

    def create_room(self, creator_sid: str) -> str:
        code = self._generate_code()
        self._waiting[code] = WaitingRoom(code=code, p1_sid=creator_sid,
                                          created_at=time.time())
        self._sid_to_room[creator_sid] = code
        return code

    def join_room(self, code: str, joiner_sid: str,
                  library, default_deck, seed) -> GameSession:
        waiting = self._waiting.pop(code)
        session = GameSession(
            room_code=code, library=library,
            p1_sid=waiting.p1_sid, p2_sid=joiner_sid,
            deck_p1=default_deck, deck_p2=default_deck,
            seed=seed,
        )
        self._rooms[code] = session
        self._sid_to_room[joiner_sid] = code
        return session

    def get_session_by_sid(self, sid: str) -> Optional[GameSession]:
        code = self._sid_to_room.get(sid)
        return self._rooms.get(code) if code else None

    def cleanup(self, code: str):
        session = self._rooms.pop(code, None)
        if session:
            self._sid_to_room.pop(session.p1_sid, None)
            self._sid_to_room.pop(session.p2_sid, None)

    def _generate_code(self) -> str:
        while True:
            code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            if code not in self._rooms and code not in self._waiting:
                return code
```

**Room code format:** 6-character alphanumeric (e.g., "XK4D2M"). Short enough to share verbally, long enough to avoid collisions.

### 3. ViewFilter (server/view_filter.py)

Critically important for card game fairness. Each player sees only their own hand contents.

```python
import copy

def filter_for_player(state_dict: dict, player_idx: int) -> dict:
    """Strip hidden information from state dict for a specific player.

    Hidden: opponent hand contents, both deck contents/order.
    Visible: board, all minions, HP, mana, graveyards, own hand, card counts.
    """
    filtered = copy.deepcopy(state_dict)
    opponent_idx = 1 - player_idx

    # Strip opponent hand -- show count only
    opp = filtered['players'][opponent_idx]
    opp['hand_count'] = len(opp['hand'])
    opp['hand'] = []

    # Strip both decks -- show count only
    for p in filtered['players']:
        p['deck_count'] = len(p['deck'])
        p['deck'] = []

    # Convenience field for client rendering
    filtered['your_player_idx'] = player_idx
    return filtered
```

### 4. TimerManager (server/timer_manager.py)

Turn timeouts using Flask-SocketIO's `start_background_task()`.

```python
from grid_tactics.actions import Action
from grid_tactics.enums import ActionType, TurnPhase

class TimerManager:
    TURN_TIMEOUT = 60   # seconds for action phase
    REACT_TIMEOUT = 30  # seconds for react window

    def start(self, session, socketio):
        self.cancel(session)
        timeout = (self.REACT_TIMEOUT if session.state.phase == TurnPhase.REACT
                   else self.TURN_TIMEOUT)
        session.timer_cancelled = False
        socketio.start_background_task(
            target=self._countdown, session=session,
            socketio=socketio, timeout=timeout,
        )

    def cancel(self, session):
        session.timer_cancelled = True

    def _countdown(self, session, socketio, timeout):
        for remaining in range(timeout, 0, -1):
            if session.timer_cancelled or session.state.is_game_over:
                return
            socketio.emit('timer_tick', {'remaining': remaining},
                          to=session.room_code)
            socketio.sleep(1)
        # Auto-pass on expiry
        if not session.timer_cancelled and not session.state.is_game_over:
            auto_pass = Action(action_type=ActionType.PASS)
            session.process_action(auto_pass, session.get_active_sid())
            # Event handler should detect and broadcast
```

### 5. Event Contract

**Client -> Server Events:**

| Event | Payload | Description |
|-------|---------|-------------|
| `create_room` | `{ display_name: str }` | Create a new room, get room code back |
| `join_room` | `{ room_code: str, display_name: str }` | Join existing room by code |
| `action` | `{ action_type, card_index?, position?, minion_id?, target_id?, target_pos? }` | Submit a game action |
| `leave_room` | `{ }` | Leave current game |
| `disconnect` | (automatic) | Handle player disconnect |

**Server -> Client Events:**

| Event | Payload | Description |
|-------|---------|-------------|
| `room_created` | `{ room_code }` | Room created, share code with friend |
| `room_joined` | `{ room_code, players }` | Player joined, waiting or starting |
| `game_start` | `{ your_side: int, state, card_defs, legal_actions }` | Game begins with initial state + card catalog |
| `state_update` | `{ state, legal_actions }` | Updated game state (per-player filtered view) |
| `timer_tick` | `{ remaining: int }` | Countdown seconds remaining |
| `game_over` | `{ winner: int or null, reason, final_hp: [int, int] }` | Game ended |
| `error` | `{ msg: str }` | Invalid action or server error |
| `opponent_left` | `{ }` | Opponent disconnected |

---

## Patterns to Follow

### Pattern 1: Server as Single Source of Truth

**What:** All game state lives on the server. Clients display state and submit actions. Clients NEVER compute game logic.

**When:** Always. Non-negotiable for card games with hidden information.

**Why:** Prevents cheating. If a client computed legal moves locally, a modified client could submit illegal actions. The server validates every action against `legal_actions()` before applying it.

### Pattern 2: Event-Driven State Machine (Not Game Loop)

**What:** The server processes one event at a time per game session. No game loop runs continuously. State advances only when a player acts.

**When:** All action processing.

**Why:** Unlike `game_loop.py`'s `run_game()` which loops until game over (calling `rng.choice()` for AI decisions), the PvP server is event-driven -- it waits for a player's WebSocket event, processes it, emits the result, then waits again. Same engine calls, different orchestration pattern.

### Pattern 3: Per-SID Emission (Never Room Broadcast for State)

**What:** State updates are always emitted to individual player SIDs, never broadcast to the room.

**When:** Every state_update emission.

**Why:** Room broadcast would send the same data to both players. Card games require per-player filtering (hidden hands/decks). Timer ticks and game_over can broadcast to the room since they contain no hidden info.

### Pattern 4: Card Definitions Sent Once at Game Start

**What:** Send the full card definition catalog to both clients at `game_start`. Client uses this for rendering card details without further queries.

**When:** Once when game begins.

**Why:** Card definitions are public knowledge. Sending them once eliminates repeated lookups. The state only contains card numeric IDs; the client maps IDs to names/stats/art using the catalog.

### Pattern 5: Legal Actions from Server

**What:** Send the computed legal action list to the active player alongside each state update.

**When:** After every state change.

**Why:** The engine's `legal_actions()` is the authoritative source. Duplicating this in JavaScript would be fragile, error-prone, and a security risk. The client UI enables/disables moves based on the server-provided list.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Client-Side Game Logic

**What:** Running `legal_actions()` or `resolve_action()` in JavaScript.

**Why bad:** Two sources of truth, cheating vector, requires porting complex Python to JS, any rule change needs two updates.

**Instead:** Client sends raw intent, server validates and applies.

### Anti-Pattern 2: Full State Broadcast to Room

**What:** Using `emit('state', state_dict, to=room_code)`.

**Why bad:** Leaks hidden information (opponent's hand). Any network inspector reveals everything.

**Instead:** Emit per-player filtered views to individual SIDs.

### Anti-Pattern 3: Storing Game State in Database per Action

**What:** Writing GameState to Supabase after every action.

**Why bad:** Adds latency on every game action. Games are ephemeral (5-15 minutes). State persistence adds complexity for throwaway data.

**Instead:** In-memory dict of GameSession objects. If server restarts, active games are lost -- acceptable for v1.1.

### Anti-Pattern 4: Modifying Engine for Server Needs

**What:** Adding WebSocket awareness, SID tracking, or timer logic into game_state.py or action_resolver.py.

**Why bad:** Couples engine to infrastructure, breaks 500+ tests, diverges tensor engine further from Python engine.

**Instead:** All server concerns (SID mapping, timers, view filtering) live in `server/` modules that import from `grid_tactics/` but never modify it.

### Anti-Pattern 5: Complex Frontend Framework

**What:** Using React/Vue for the game UI.

**Why bad:** Adds npm, build step, bundling. The existing project uses vanilla HTML/JS for the analytics dashboard. A 5x5 grid with cards is well within vanilla JS capability.

**Instead:** Single HTML file with embedded or linked CSS/JS. Socket.IO client from CDN. Consistent with existing `web-dashboard/` pattern.

---

## Integration Points with Existing Engine

### What the Server Calls

| Engine Function | Where Called | Purpose |
|----------------|-------------|---------|
| `GameState.new_game(seed, deck_p1, deck_p2)` | `GameSession.__init__` | Start a new game |
| `legal_actions(state, library)` | `GameSession.process_action`, after each state change | Validate actions + send to client |
| `resolve_action(state, action, library)` | `GameSession.process_action` | Apply validated action |
| `GameState.to_dict()` | Before filtering + emit | Serialize state for transmission |
| `CardLibrary.from_directory(path)` | Server startup (once) | Load card definitions |
| `CardLibrary.all_cards` / `get_numeric_id()` | Building card catalog for `game_start` | Card definition lookup for client |

### What the Server Never Calls

| Engine Component | Why Not |
|-----------------|---------|
| `tensor_engine/` | GPU training only, not for human PvP |
| `rl/` | RL environment wrapper, not for human PvP |
| `game_loop.py` `run_game()` | Runs complete AI-vs-AI game -- PvP is event-driven |
| `rng.choice()` | Server does not choose actions -- players do |

### Existing `to_dict()` Coverage

`GameState.to_dict()` already serializes everything needed for PvP:

- `board`: Cell occupancy (list of 25 values, minion instance IDs or None)
- `players[i]`: `side`, `hp`, `current_mana`, `max_mana`, `hand` (list of numeric IDs), `deck` (list), `graveyard` (list)
- `minions`: Each with `instance_id`, `card_numeric_id`, `owner`, `position`, `current_health`, `attack_bonus`
- `active_player_idx`, `phase` (int), `turn_number`, `seed`
- `react_stack`, `react_player_idx`, `pending_action`
- `winner`, `is_game_over`

The ViewFilter strips `hand` and `deck` contents from the opponent. No changes to `to_dict()` are needed.

---

## File Structure

```
card game/
  src/grid_tactics/
    server/                    # NEW: PvP server package
      __init__.py
      app.py                   # Flask app + SocketIO setup + entry point
      room_manager.py          # Room creation, joining, lifecycle
      game_session.py          # Per-game state management + action handling
      view_filter.py           # GameState -> per-player JSON dict
      timer_manager.py         # Turn timeout background tasks
      events.py                # Socket.IO event handlers
    ... (existing engine files unchanged)

  web-pvp/                     # NEW: Game UI (separate from analytics dashboard)
    index.html                 # Game page
    css/
      game.css                 # Board, hand, status styling
    js/
      game.js                  # Socket.IO client + main controller
      board.js                 # 5x5 grid rendering
      hand.js                  # Hand display + card selection
      actions.js               # Legal action highlighting + submission

  web-dashboard/               # EXISTING: analytics dashboard (separate)
  data/cards/                  # EXISTING: card JSON files
  pvp_server.py                # NEW: entry point (python pvp_server.py)
```

**Why separate from `web-dashboard/`:** Different purpose, different deployment, different data source. Dashboard reads Supabase; game UI communicates with Flask-SocketIO server.

---

## Build Order (Recommended)

Build order respects dependency chains and enables testing at each step:

### Step 1: Server Foundation (test with wscat or Python socketio client)
1. `server/app.py` -- Flask + SocketIO init, CORS, static file serving
2. `server/room_manager.py` -- Room CRUD, room code generation
3. `server/game_session.py` -- GameState wrapper, process_action with locking
4. `server/events.py` -- create_room + join_room handlers only
5. **Test gate:** Two WebSocket clients create and join a room, receive `game_start`

### Step 2: Core Game Flow (test with Python socketio client)
1. `server/view_filter.py` -- Per-player state filtering
2. `server/events.py` -- Add action handler with filtered state emission
3. `server/events.py` -- Add legal_actions serialization + emission
4. **Test gate:** Full game playable via raw SocketIO events (two Python clients playing a complete game including react windows)

### Step 3: Turn Management + Resilience
1. `server/timer_manager.py` -- Background countdown, auto-pass on expiry
2. `server/events.py` -- Add disconnect/reconnect handling
3. **Test gate:** Timer expires and auto-passes, disconnect triggers opponent notification

### Step 4: Web UI
1. `web-pvp/index.html` -- Board grid, hand area, mana/HP display
2. `web-pvp/js/game.js` -- SocketIO connection, state rendering
3. `web-pvp/js/actions.js` -- Legal action highlighting, action submission
4. **Test gate:** Full game playable in two browser windows

### Step 5: Polish
1. React window UI indicators (highlight reactor, show countdown)
2. Game over screen with outcome
3. Card hover/preview with full details
4. Visual feedback for attacks, deploy, damage numbers

**Rationale:** Server before UI because the server can be fully tested with programmatic WebSocket clients. This catches all logic bugs before any UI complexity. The view filter comes in Step 2 (not Step 1) because you need the action handler to have state worth filtering.

---

## Scalability Considerations

| Concern | Dev (2 players) | Target (50 games) | Future (500+ games) |
|---------|-----------------|---------------------|----------------------|
| State storage | In-memory dict | In-memory dict | Redis for cross-process state |
| Async mode | threading | threading (fine <200 conns) | gevent + gunicorn workers |
| Turn processing | Direct function call | Direct call (<1ms per action) | Same -- game logic is trivially fast |
| Reconnection | Simple SID re-mapping | SID re-mapping + state resend | Redis pub/sub for cross-process |
| Persistence | None | Optional Supabase for completed games | Supabase for game history |

**Current target: 50 concurrent games.** In-memory + threading is correct. Do not over-engineer.

---

## Technology Decisions for PvP Layer

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Flask-SocketIO | >=5.6,<6.0 | WebSocket server with room system | Standard Python WebSocket library. 5.6.1 current (Feb 2026). Actively maintained. |
| simple-websocket | >=1.0 | WebSocket transport for threading mode | Required for real WebSocket protocol (not long-polling fallback) with async_mode='threading'. |
| Flask | >=3.0 | HTTP framework + static serving | Flask-SocketIO dependency. Also serves web-pvp/ files. |
| socket.io-client | 4.x | Browser WebSocket client | CDN-loaded. Must match python-socketio v5 protocol. |

**Async mode: `threading`** because:
1. Game engine is CPU-bound, not I/O-bound -- green threads do not help
2. Best third-party library compatibility (no monkey-patching)
3. Target scale (<200 concurrent connections) is well within threading limits
4. simple-websocket provides real WebSocket transport without gevent/eventlet

**Install:**
```bash
pip install flask-socketio>=5.6 simple-websocket>=1.0
```

---

## Confidence Assessment

| Component | Confidence | Notes |
|-----------|------------|-------|
| Engine reuse (zero modifications) | HIGH | Verified: to_dict(), resolve_action(), legal_actions() match PvP needs exactly |
| Flask-SocketIO room/emit pattern | HIGH | Documented API, standard pattern, version verified on PyPI |
| View filtering approach | HIGH | Standard TCG hidden-info pattern (opponent hand + both decks hidden) |
| Threading async mode for target scale | HIGH | Sufficient for <200 connections, documented tradeoffs |
| Timer via background tasks | MEDIUM | start_background_task() documented but cancellation needs careful testing |
| Per-SID emit for private state | HIGH | Flask-SocketIO's `to=sid` is the documented private message approach |
| Vanilla JS for game UI | HIGH | Consistent with existing web-dashboard pattern, no build tools needed |

---

## Sources

- [Flask-SocketIO documentation](https://flask-socketio.readthedocs.io/) -- Room management, emit API, async modes
- [Flask-SocketIO PyPI](https://pypi.org/project/Flask-SocketIO/) -- Version 5.6.1, Feb 2026, Python >=3.8
- [Flask-SocketIO GitHub](https://github.com/miguelgrinberg/Flask-SocketIO) -- Changelog, discussions
- [Flask-SocketIO deployment docs](https://flask-socketio.readthedocs.io/en/latest/deployment.html) -- Gevent vs threading vs eventlet
- [Flask-SocketIO CORS discussion #1762](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1762) -- Production CORS config
- [Flask-SocketIO async mode discussion #1915](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1915) -- Threading vs gevent selection
- [Flask-SocketIO timer discussion #1695](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1695) -- Background task timer pattern
- [Socket.IO Rooms documentation](https://socket.io/docs/v3/rooms/) -- Room concept
- [Multiplayer game state sync](https://dev.to/sauravmh/browser-game-design-using-websockets-and-deployments-on-scale-1iaa) -- Server-authoritative architecture
- Existing codebase: game_state.py (to_dict/from_dict), action_resolver.py (resolve_action), legal_actions.py, game_loop.py, actions.py
