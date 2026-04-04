# Project Research Summary

**Project:** Grid Tactics TCG v1.1 — Online PvP Dueling
**Domain:** Real-time multiplayer turn-based card game over WebSockets
**Researched:** 2026-04-04
**Confidence:** HIGH

## Executive Summary

Grid Tactics already has a complete, battle-tested game engine (immutable frozen dataclasses, pure functions, 500+ tests). The v1.1 Online PvP Dueling feature is additive — it wraps the existing Python engine without modifying it. The recommended approach is Flask-SocketIO (threading mode + simple-websocket) as a thin orchestration server that holds one `GameState` per room, validates actions against `legal_actions()`, applies them via `resolve_action()`, and emits per-player filtered views over WebSocket. The entire PvP server is 5 new Python modules (`server/`) plus a single-page HTML UI (`web-pvp/`). Zero changes to the existing game engine are needed.

The critical path is short and well-defined: server setup -> room system -> state serialization with hidden-info filtering -> board UI -> action submission -> react window flow -> win detection. Each step is independently testable before the next. The existing engine's pure-function, immutable-state design is a perfect RPC interface for WebSocket-driven game actions — the server layer is genuinely thin and has no novel architecture challenges. Total new dependencies: 3 (Flask, Flask-SocketIO, simple-websocket).

The primary risks are information leakage (opponent hand visible in WebSocket frames) and react window desync (clients not correctly transitioning between ACTION and REACT phases). Both have clear, well-documented solutions. A secondary risk is turn timer race conditions in threading mode, mitigated by a `threading.Lock` per `GameSession`. Scope is deliberately narrow for v1.1: no accounts, no matchmaking, no deck builder, no AI opponent. This is the right call.

---

## Key Findings

### Recommended Stack

The PvP server adds exactly 3 new runtime dependencies: `Flask>=3.1`, `Flask-SocketIO>=5.6`, and `simple-websocket>=1.1`. Threading async mode is non-negotiable — eventlet is deprecated (maintainer guidance), gevent-websocket was abandoned in 2017. Threading with simple-websocket provides real WebSocket transport (not long-polling fallback) and is correct for the target scale of ~50 concurrent games. The frontend is vanilla HTML/CSS/JS with socket.io-client 4.8.3 from CDN — consistent with the existing Vercel analytics dashboard pattern, no npm or build tooling needed.

Serialization uses `dataclasses.asdict()` (already in use throughout the codebase), not msgspec or orjson. At one serialization per second per room, stdlib JSON is fast enough. A custom `to_client_dict(viewer_side)` method handles the hidden-information filtering that is the security-critical piece.

**Core technologies:**
- Flask 3.1.3 + Flask-SocketIO 5.6.1: WebSocket server with rooms, events, broadcasting — lowest-friction path to real-time multiplayer for an existing Python project
- simple-websocket 1.1.0: Required for real WebSocket transport in threading mode — maintained (2024 release), unlike gevent-websocket (2017, abandoned)
- Socket.IO client 4.8.3 (CDN): Browser-side WebSocket — auto-reconnect, protocol-compatible with Flask-SocketIO 5.x
- dataclasses.asdict() + custom view filter: State serialization — already the project pattern, zero new deps
- In-memory Python dict: Room state registry — correct for single-process server at target scale, no Redis needed

### Expected Features

**Must have (table stakes):**
- Server-authoritative game loop — validates every action against `legal_actions()` before applying; prevents cheating
- Room code system (create/join) — `secrets.token_urlsafe(6)` + Flask-SocketIO rooms; standard for private casual games
- Per-player views with hidden information — opponent's hand/deck stripped before emit; game is broken without this
- Legal action filtering in UI — server sends valid actions with each state update; client highlights them
- 5x5 grid board visualization — CSS Grid layout; the game is spatial and must render spatially
- Hand display with playable card indicators — mana cost, stats, dimmed-if-unplayable
- Turn flow indicator (ACTION vs REACT phase) — must be unambiguous which player acts in which role
- React window UI — distinct prompt for reactor, prominent pass button; core game differentiator
- Win detection + game over screen — clear outcome display

**Should have (differentiators):**
- Turn timer (45s action / 20s react) — prevents stalling; auto-pass on expiry
- Game log / action history — scrollable sidebar of events
- Card hover/inspect preview — full card details on hover
- Reconnection handling (60s window with session token) — WiFi drops should not end games
- Rematch button — quick restart in same room

**Defer (v2+):**
- Matchmaking / ELO ranking — requires critical player mass
- User accounts / authentication — no value for friends playing
- Deck builder — only 19 cards, not enough variety
- AI opponent in PvP UI — requires PyTorch model loading
- Mobile-responsive layout, sound effects, card art, persistent game history

### Architecture Approach

The PvP server is Layer 5 sitting above the existing architecture, wrapping the Python game engine (Layer 1) directly and bypassing RL layers (2-3) and dashboard (Layer 4) entirely. The engine's pure-function signatures — `resolve_action(state, action, library) -> new_state` and `legal_actions(state, library) -> list[Action]` — map perfectly to event-driven WebSocket architecture: receive event, call function, emit result.

**Major components:**
1. `server/app.py` — Flask + SocketIO initialization, static file serving, CORS, entry point
2. `server/room_manager.py` — Room code generation (6-char alphanumeric), player-to-room mapping, session lifecycle
3. `server/game_session.py` — Per-game container: holds `GameState`, player SIDs, `threading.Lock`, processes actions via `resolve_action()`
4. `server/view_filter.py` — Strips opponent hand/deck contents; produces per-player JSON views
5. `server/timer_manager.py` — Background turn timeout tasks via `start_background_task()`; auto-pass on expiry
6. `server/events.py` — All Socket.IO event handlers (create_room, join_room, action, disconnect)
7. `web-pvp/index.html` + JS — CSS Grid board, hand display, legal action highlights, action submission

Zero modifications to existing engine files. All server concerns live in `server/` that imports from `grid_tactics/` but never modifies it.

### Critical Pitfalls

1. **Information leakage via WebSocket payloads** — Never send raw `dataclasses.asdict(state)` over the wire. Implement `to_client_dict(viewer_side)` server-side: opponent hand becomes count-only, both decks become count-only. Write a test asserting opponent card IDs don't appear in filtered output. Verify with browser DevTools.

2. **Client-submitted actions not validated** — Always reconstruct the Action dataclass from client payload AND check it is in `legal_actions(state, library)` before applying. Emit error event on invalid actions; never crash. Wrap action reconstruction in try/except for malformed dicts.

3. **React window desync** — Client must check BOTH `phase` AND `react_player_idx` (not just `active_player_idx`) to determine who acts during REACT. Include a `decision_player_idx` field in every state update to eliminate client-side ambiguity. Turn timer on react phase prevents freeze if client fails to show prompt.

4. **Session token vs socket ID** — Socket IDs (`request.sid`) change on reconnect. Map players to game slots using a persistent session token (UUID stored in cookie/localStorage), not the socket ID. On reconnect, update the stored SID and re-emit current state.

5. **Turn timer race condition** — `threading.Lock()` per `GameSession` serializes access. Both timer callback and action handler acquire the lock. Timer checks whether state has already advanced before auto-passing.

---

## Implications for Roadmap

The dependency chain is clear and the build order is prescribed by architecture. FEATURES.md defines a tight critical path. Five phases map directly to it.

### Phase 1: Server Foundation + Room System

**Rationale:** Nothing else is possible without WebSocket connectivity and room management. Fully testable with programmatic clients (wscat or Python socketio client) — no browser UI needed.
**Delivers:** Two clients can connect, create a room, and receive a `game_start` event with initial game state.
**Addresses:** Server-authoritative game loop, room code system (create/join), preset deck definition
**Stack:** Flask 3.1, Flask-SocketIO 5.6, simple-websocket 1.1
**Implements:** `server/app.py`, `server/room_manager.py`, `server/game_session.py`, `server/events.py` (create/join handlers only)
**Avoids:** Pitfall 9 (CORS config from day one — serve HTML from Flask app), Pitfall 4 (session tokens, not socket IDs, established in room join flow), Pitfall 10 (preset deck constant defined at this step)

### Phase 2: State Serialization + Core Game Flow

**Rationale:** Hidden-info filtering is the security-critical foundation for all UI work. The full game must be playable via raw SocketIO before any browser UI is built — this catches all logic bugs before UI complexity is added.
**Delivers:** Complete game playable via Python/CLI WebSocket client. Both players take turns, react windows work, game ends with correct winner. View filter tested and verified.
**Addresses:** Per-player views (hidden information), legal action serialization, real-time state sync, react window state machine
**Implements:** `server/view_filter.py`, action handler in `server/events.py`, legal_actions emission
**Avoids:** Pitfall 1 (view filter proven before UI ships), Pitfall 2 (action validation always on), Pitfall 3 (decision_player_idx in every state update), Pitfall 6 (json.dumps test on all GameState types), Pitfall 8 (wire format schema documented once here)

### Phase 3: Browser Game UI

**Rationale:** Build UI only after the server is proven correct. This phase is pure rendering — all game logic is server-side. Consistent with existing `web-dashboard/` vanilla JS pattern.
**Delivers:** Full game playable in two browser windows. 5x5 CSS Grid board, hand display, mana/HP bars, legal action highlights, action submission.
**Addresses:** 5x5 grid board visualization, hand display with playable indicators, mana/HP display, turn flow indicator
**Stack:** Vanilla HTML/CSS/JS, Socket.IO client 4.8.3 CDN
**Implements:** `web-pvp/index.html`, `web-pvp/js/game.js`, `web-pvp/js/board.js`, `web-pvp/js/actions.js`
**Avoids:** Pitfall 8 (client action construction matches server wire format established in Phase 2)

### Phase 4: React Window UI + Win Detection

**Rationale:** React window is the most complex UI interaction. Separating it from base UI (Phase 3) keeps Phase 3 shippable and focused. Win detection display completes the game loop.
**Delivers:** React window fully usable in browser. Distinct react prompt, highlight playable react cards, prominent pass button. Win/loss/draw overlay with reason. Game is shippable at this milestone.
**Addresses:** React window UI, win detection + game over screen
**Avoids:** Pitfall 3 (client uses `decision_player_idx` to render react role correctly)

### Phase 5: Resilience + Polish

**Rationale:** Turn timer and reconnection handling prevent the most common user-facing failures in online games (stalling, network drops). Deferred because they add implementation complexity that would slow Phases 1-4.
**Delivers:** Turn timer with auto-pass, reconnection resilience (session tokens already laid in Phase 1), game log sidebar, room cleanup on disconnect, rematch button.
**Addresses:** Turn timer (45s/20s), reconnection handling, game log, room memory management
**Implements:** `server/timer_manager.py`, disconnect/reconnect handling in events.py, periodic room cleanup sweep
**Avoids:** Pitfall 5 (timer race condition — threading.Lock already in GameSession from Phase 1), Pitfall 7 (room memory leak — disconnect timers + cleanup)

### Phase Ordering Rationale

- Server before UI: server can be fully tested programmatically, catching all rule bugs before any browser complexity
- View filtering (Phase 2) before UI (Phase 3): the hidden-information guarantee must be established and tested before a UI could inadvertently expose it
- React window UI (Phase 4) separated from base UI (Phase 3): server already handles react state machine correctly — the UI split keeps Phase 3 scoped and shippable
- Resilience (Phase 5) last: a game that stalls on WiFi drop is acceptable for early testing; core gameplay comes first

### Research Flags

Phases with well-documented patterns (no research-phase needed):
- **Phase 1:** Flask-SocketIO rooms are a core documented feature; create/join pattern is standard
- **Phase 2:** State serialization, action validation, and view filtering are fully specified in ARCHITECTURE.md with production-ready code examples
- **Phase 3:** Vanilla HTML/CSS/JS with Socket.IO CDN — no novel integrations; existing `web-dashboard/` is the template
- **Phase 4:** React window state machine is handled by the existing engine; client rendering follows from Phase 3 patterns

Phases that may benefit from targeted investigation during planning:
- **Phase 5 (Reconnection):** Session token + reconnect flow has moderate implementation complexity. Cookie vs localStorage, token expiry, and state resend edge cases may surface. Consider a brief investigation before implementation.
- **Phase 5 (Timer cancellation):** ARCHITECTURE.md explicitly flags `start_background_task()` cancellation as MEDIUM confidence — "needs careful testing." Plan a timer integration test before shipping.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified on PyPI as of 2026-04-04. Async mode recommendation is from Flask-SocketIO maintainer, not inference. Only uncertainty: Flask-CORS may not be needed if HTML is served from the same Flask app (recommended). |
| Features | HIGH | Critical path is unambiguous. Table stakes are established conventions from online card games. Anti-features list prevents scope creep. |
| Architecture | HIGH | Engine reuse (zero modifications) verified by mapping existing API surface to PvP needs. Flask-SocketIO room/emit patterns are documented. Only MEDIUM area: timer cancellation edge cases. |
| Pitfalls | HIGH | All 10 pitfalls have concrete prevention strategies. Critical pitfalls (info leakage, action validation, react desync) are well-sourced from multiplayer game development practice and Flask-SocketIO documentation. |

**Overall confidence:** HIGH

### Gaps to Address

- **Preset deck composition:** The server needs `deck_p1` and `deck_p2` when creating a `GameSession`. With 19 cards and `MIN_DECK_SIZE=30`, the specific card copy counts in the preset deck are not decided. Must be resolved in Phase 1 — it is a game design decision, not a technical one. Suggestion: balanced across attributes (Fire/Dark/Light/Earth/Neutral).

- **Timer cancellation reliability:** ARCHITECTURE.md flags `start_background_task()` cancellation as MEDIUM confidence. Plan a Phase 5 integration test for rapid consecutive actions at timer expiry. The `session.timer_cancelled` flag approach is documented but edge cases may surface.

- **to_dict() completeness:** The existing `GameState.to_dict()` coverage appears complete for PvP needs. Verify during Phase 2 that `react_stack`, `pending_action`, and `react_player_idx` are all present and correctly structured for client rendering.

- **Deployment target:** Where the PvP server runs (same machine as training on a different port vs. Render/Railway/Fly.io) is not yet decided. Does not block Phase 1-4, but must be decided before Phase 5 (reconnection handling depends on whether the server can restart with state intact).

---

## Sources

### Primary (HIGH confidence)
- [Flask-SocketIO PyPI](https://pypi.org/project/Flask-SocketIO/) — version 5.6.1 (Feb 2026), async mode guidance
- [Flask PyPI](https://pypi.org/project/Flask/) — version 3.1.3 (Feb 2026)
- [simple-websocket PyPI](https://pypi.org/project/simple-websocket/) — version 1.1.0 (Oct 2024)
- [gevent-websocket PyPI](https://pypi.org/project/gevent-websocket/) — version 0.10.1 (2017), confirmed abandoned
- [Socket.IO Client CDN](https://www.jsdelivr.com/package/npm/socket.io-client) — version 4.8.3 (Dec 2025)
- [Flask-SocketIO deployment docs](https://flask-socketio.readthedocs.io/en/latest/deployment.html) — gunicorn config, async mode tradeoffs
- [Flask-SocketIO async mode discussion #1915](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1915) — maintainer guidance on threading vs gevent vs eventlet
- [Flask-SocketIO eventlet deprecation discussion #2037](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/2037) — eventlet maintenance status
- Existing codebase: `game_state.py`, `action_resolver.py`, `legal_actions.py`, `game_loop.py`, `actions.py`, `enums.py`

### Secondary (MEDIUM confidence)
- [Socket.IO Rooms documentation](https://socket.io/docs/v3/rooms/) — room concept and patterns
- [Flask-SocketIO timer discussion #1695](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1695) — background task timer pattern (cancellation details need testing)
- [Building Multiplayer Board Games with WebSockets](https://dev.to/sauravmh/browser-game-design-using-websockets-and-deployments-on-scale-1iaa) — server authority, room management
- [Mastering Socket.IO Rooms](https://www.videosdk.live/developer-hub/socketio/socketio-rooms) — room management best practices

---
*Research completed: 2026-04-04*
*Ready for roadmap: yes*
