# Domain Pitfalls: Online PvP Dueling

**Domain:** Real-time multiplayer turn-based card game server
**Researched:** 2026-04-04

---

## Critical Pitfalls

Mistakes that cause rewrites or security vulnerabilities.

---

### Pitfall 1: Information Leakage via WebSocket Payloads

**What goes wrong:** The server sends the full `GameState` (including opponent's hand contents, deck order, and card details) to both players. A player opens browser DevTools, inspects WebSocket frames, and sees exactly what cards the opponent holds. Game is fundamentally broken.

**Why it happens:** During development, it is tempting to serialize the entire GameState with `dataclasses.asdict()` and emit it. "I'll filter it on the client side" is the common shortcut. But WebSocket traffic is plainly visible to clients.

**Consequences:**
- Any player with basic web knowledge can cheat
- Hidden information (the foundation of card games) is destroyed
- Cannot be fixed client-side -- filtering must happen server-side before emit

**Prevention:**
- Implement `to_client_dict(viewer_side: PlayerSide)` that produces a filtered dict BEFORE emitting
- Opponent's hand becomes `opponent_hand_count: int` (not card contents)
- Opponent's deck becomes `opponent_deck_count: int` (not card order)
- Board minions, HP, mana, graveyard are public and included for both players
- Write a test: serialize state for Player 0, assert no Player 1 hand card IDs appear in the dict
- Never send raw `dataclasses.asdict(state)` over the wire

**Detection:**
- Open browser DevTools -> Network -> WS tab -> inspect messages
- If opponent's hand card IDs appear in any message, the filter is broken

---

### Pitfall 2: Client-Submitted Actions Not Validated Against legal_actions()

**What goes wrong:** The server trusts action dicts from the client without checking against `legal_actions()`. A modified client sends "play card with index 99" or "attack with a minion that doesn't exist" or "move to an occupied cell." The game engine crashes or enters an invalid state.

**Why it happens:** Developers assume the UI only shows legal moves, so the server doesn't need to validate. But any WebSocket client (or browser console) can emit arbitrary events.

**Consequences:**
- Game crashes or enters impossible states
- Cheating: play cards you can't afford, attack out of range, deploy to occupied cells
- Corrupted GameState that causes subsequent `legal_actions()` to fail

**Prevention:**
- ALWAYS validate: reconstruct the Action from the client dict, check it is in `legal_actions(state, library)`
- If not in legal actions: emit an error event, do NOT apply the action
- Wrap action reconstruction in try/except -- malformed dicts should not crash the server
- Consider rate limiting action submissions (max 1 per 500ms per player)

**Detection:**
- Open browser console, emit actions with invalid data
- If the game state changes, validation is missing

---

### Pitfall 3: React Window Desync Between Server and Client

**What goes wrong:** After Player A takes an action, the server enters REACT phase for Player B. But the client UI does not clearly transition to the react window, or Player B's client does not receive the state update indicating it is their turn to react. Player B sits staring at "Opponent's Turn" while the server waits for a react response. The game freezes.

**Why it happens:** The turn flow has a subtle state machine: ACTION -> (optional) REACT -> ACTION. The REACT phase changes which player is the active decision-maker. If the client relies on `active_player_idx` alone to determine whose turn it is, it will be wrong during REACT (where the reacting player acts, not the active player).

**Consequences:**
- Game appears frozen for one or both players
- Players disconnect thinking the game is stuck
- React window (a core differentiator) becomes unusable

**Prevention:**
- Emit a distinct event or clear state flag when entering REACT phase
- The client must check BOTH `active_player_idx` AND `phase` (ACTION vs REACT) to determine the current decision-maker
- During REACT: the decision-maker is `react_player_idx`, not `active_player_idx`
- Include `decision_player_idx` in the state update that resolves the ambiguity
- Add a turn timer to REACT phase (20s) so the game never freezes if the client fails to show the react prompt
- Test the full react flow end-to-end: action -> react prompt -> react card played -> resolution -> next turn

**Detection:**
- Play a game where the react player has a playable react card
- If the react player's client does not show the react prompt, the desync exists

---

## Moderate Pitfalls

---

### Pitfall 4: Socket.IO Connection ID Changes on Reconnect

**What goes wrong:** A player disconnects (WiFi drop, browser close) and reconnects. Flask-SocketIO assigns a new `request.sid`. The server's room mapping uses the old socket ID to identify the player. The reconnected player cannot rejoin their game because their identity was tied to the old connection.

**Why it happens:** Socket.IO connection IDs (`sid`) are ephemeral. They change on every new connection. If the server maps players to rooms only by `sid`, reconnection breaks identity.

**Prevention:**
- Assign a persistent session token (UUID) when a player creates or joins a room
- Store the token in a cookie or return it to the client for localStorage
- On reconnect, the client sends the session token (not the old sid)
- The server maps session tokens to player slots in GameSession, NOT socket IDs
- When a new connection arrives with a valid session token, update the player's socket ID in the GameSession and re-emit the current game state
- Flask's session or a simple dict of `{token: GameSession}` handles this

**Detection:**
- Disconnect a client (close tab), reopen it, attempt to rejoin the same room
- If the player cannot resume their game, the identity mapping is broken

---

### Pitfall 5: Turn Timer Race Conditions with Threading

**What goes wrong:** The turn timer (a background thread or timer task) fires at the exact moment a player submits an action. Both the timer callback and the action handler try to modify the game state simultaneously. With Flask-SocketIO in threading mode, this creates a race condition: the action might be applied after the auto-pass, or the auto-pass might overwrite the player's action.

**Why it happens:** Flask-SocketIO's threading async mode handles each event in a separate thread. Background tasks (timers) run in their own threads. Without synchronization, concurrent access to `GameSession.state` is unsafe.

**Prevention:**
- Use a `threading.Lock()` per GameSession to serialize access to state
- Both the action handler and the timer callback acquire the lock before reading or writing state
- When the timer fires: acquire lock, check if the state has already advanced (player acted in time), if not, auto-pass
- When an action arrives: acquire lock, cancel the pending timer (if any), validate and apply action, start new timer for next turn
- Keep the critical section small -- lock around state mutation only, not the emit

**Detection:**
- Rapidly submit actions right as the turn timer is about to expire
- If game enters an impossible state or actions are lost, there is a race condition

---

### Pitfall 6: Frozen Dataclass Serialization Pitfalls

**What goes wrong:** `dataclasses.asdict()` recursively converts nested dataclasses and tuples. But some fields in `GameState` may not serialize cleanly to JSON:
- `IntEnum` values serialize as integers (fine, but client needs to know the mapping)
- `tuple` serializes as list in JSON (fine, but round-trip loses type info)
- `Optional[tuple[int, int]]` positions need special handling
- `GameRNG` is NOT part of GameState (it's mutable, separate) -- accidentally including it would crash

**Why it happens:** The game engine uses frozen dataclasses with IntEnum, tuples, and Optional fields for performance and correctness. JSON has no concept of these types.

**Prevention:**
- Write a custom `to_client_dict()` method that explicitly builds the JSON-safe dict, rather than relying on `dataclasses.asdict()` for the full state
- IntEnum values: convert to int explicitly (they serialize naturally but document the mapping for the client)
- Position tuples: convert to `[row, col]` arrays
- Include only the fields the client needs -- skip internal bookkeeping fields
- Write a test: `json.dumps(to_client_dict(state, side))` must not raise for any valid GameState
- Ship a JavaScript-side enum mapping file (or inline dict) that maps integers back to display strings

**Detection:**
- `json.dumps(dataclasses.asdict(state))` throws TypeError on unexpected types
- Client receives integers where it expects strings ("PLAY_CARD" vs 0)

---

### Pitfall 7: Room Cleanup / Memory Leak on Disconnect

**What goes wrong:** Players disconnect without explicitly leaving the room (browser close, network drop, etc.). The `GameSession` and its `GameState` remain in the server's in-memory dict forever. Over time, abandoned rooms accumulate, consuming memory.

**Why it happens:** Flask-SocketIO fires a `disconnect` event when a player drops, but the `GameSession` may be waiting for the other player to act. Without cleanup logic, the room persists indefinitely.

**Prevention:**
- On disconnect: start a reconnection timer (60s). If the player does not reconnect, forfeit the game and destroy the room.
- Implement a periodic cleanup sweep: destroy rooms that have been inactive for >10 minutes
- When a game ends (win/loss/draw), mark the room as completed. Destroy after 60s (time for players to see the result).
- Log room creation/destruction counts for monitoring

**Detection:**
- Create 100 rooms, disconnect from all of them, check server memory after 15 minutes
- If memory grows without bound, cleanup is missing

---

## Minor Pitfalls

---

### Pitfall 8: Action Dict Schema Mismatch Between Client and Server

**What goes wrong:** The JavaScript client sends `{actionType: "PLAY_CARD", cardIndex: 2}` (camelCase, string enum) but the Python server expects `{action_type: 0, card_index: 2}` (snake_case, integer enum). The action reconstruction fails silently or crashes.

**Prevention:**
- Define the action dict schema once and share between client and server
- Use snake_case in the wire format (Python convention, JS can adapt)
- Use integer enum values on the wire (not strings) -- matches the engine's IntEnum
- Document the schema in a comment at the top of both the Python event handler and the JS emit function
- Validate incoming action dicts have required fields before reconstructing

---

### Pitfall 9: CORS Misconfiguration Blocks Client Connection

**What goes wrong:** The game HTML is served from one origin (e.g., file://, or a different port during dev) but the Flask-SocketIO server runs on another. CORS blocks the WebSocket connection. The client shows "connection failed" with no useful error message.

**Prevention:**
- During development: set `cors_allowed_origins="*"` in `SocketIO()` constructor
- For production: set `cors_allowed_origins` to the specific origin where the game UI is hosted
- If serving the HTML from the SAME Flask app (recommended for v1.1): CORS is not an issue
- Test the connection from the actual browser URL, not just localhost

---

### Pitfall 10: Deck Composition Not Decided Before Implementation

**What goes wrong:** The server needs to create a game with `GameState.new_game(seed, deck_p1, deck_p2)` but there is no decision about what decks the players use. With 19 cards and `MIN_DECK_SIZE=30`, the deck composition affects gameplay significantly but is not part of the PvP feature spec.

**Prevention:**
- For v1.1: use a hardcoded preset deck for both players (e.g., all 19 unique cards with varying copy counts to reach 30)
- Define the preset deck as a constant in the server code
- Both players get the same deck composition (symmetric start)
- Deck customization is a future feature (anti-feature for v1.1)

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Server setup | CORS blocks client connection (#9) | Serve HTML from Flask app or set cors_allowed_origins |
| Room system | Socket ID changes on reconnect (#4) | Session tokens, not socket IDs |
| Room system | Memory leak from abandoned rooms (#7) | Disconnect timers + periodic cleanup sweep |
| State serialization | Information leakage (#1) | to_client_dict() with per-player filtering, test with DevTools |
| State serialization | JSON serialization failures (#6) | Custom serializer, test json.dumps on all state types |
| Action handling | Unvalidated client actions (#2) | Always check against legal_actions() |
| Action handling | Schema mismatch (#8) | Document wire format, use integers for enums |
| React window | Client-server desync (#3) | Distinct phase flag, decision_player_idx, turn timer |
| Turn timer | Race condition with threading (#5) | threading.Lock per GameSession |
| Game start | Deck composition undefined (#10) | Hardcoded preset deck for v1.1 |

---

## Sources

- [Flask-SocketIO CORS handling](https://github.com/miguelgrinberg/Flask-SocketIO/issues/697) -- CORS configuration issues
- [Socket.IO reconnection](https://socket.io/docs/v4/client-options/#reconnection) -- Client reconnection behavior
- [Flask-SocketIO threading mode](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1601) -- Thread safety considerations
- [Building Multiplayer Board Games with WebSockets](https://dev.to/krishanvijay/building-a-multiplayer-board-game-with-javascript-and-websockets-4fae) -- Server authority, room management
- [Mastering Socket.IO Rooms](https://www.videosdk.live/developer-hub/socketio/socketio-rooms) -- Room management best practices

---
*Pitfalls research for: Grid Tactics TCG v1.1 Online PvP Dueling*
*Researched: 2026-04-04*
