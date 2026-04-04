# Stack Research: Online PvP Dueling Additions

**Domain:** Real-time multiplayer web game (turn-based card game over WebSockets)
**Researched:** 2026-04-04
**Confidence:** HIGH

**Scope:** This document covers ONLY the new stack additions for v1.1 Online PvP Dueling. The existing game engine (dataclasses, NumPy, PyTorch tensor engine), RL pipeline (SB3, PettingZoo, Gymnasium), cloud training (RunPod, Supabase, Vercel analytics dashboard), and testing (pytest, mypy, ruff) are validated and unchanged. See CLAUDE.md for the full existing stack.

---

## Recommended Stack

### Game Server

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Flask | >=3.1,<4.0 | HTTP framework / app scaffold | Flask 3.1.3 (Feb 2026) is the current stable release. Minimal, well-understood, and the base for Flask-SocketIO. The game server needs to serve the game HTML page and handle WebSocket connections -- Flask does both with zero ceremony. |
| Flask-SocketIO | >=5.6,<6.0 | WebSocket server with rooms, events, broadcasting | Flask-SocketIO 5.6.1 (Feb 2026) is the current release. Built-in room management maps directly to game rooms. Event-driven architecture (emit/on) maps to game actions. Auto-reconnection via Socket.IO protocol. The project already uses Python -- Flask-SocketIO is the lowest-friction path to add real-time multiplayer. |
| simple-websocket | >=1.1 | WebSocket transport for threading async mode | Required for WebSocket support in threading mode. simple-websocket 1.1.0 (Oct 2024) is the current release. Flask-SocketIO auto-detects it. |

**Async Mode Decision: Threading (not gevent, not eventlet).**

Rationale:
- **Eventlet is deprecated.** In maintenance mode ("life support"), incompatible with modern Python. Not recommended for new projects per Flask-SocketIO maintainer.
- **Gevent requires gevent-websocket for WebSocket transport.** gevent-websocket's last release was 0.10.1 in **2017** -- it is abandoned. Without it, gevent falls back to long-polling only, which adds latency to a real-time game. Using gevent + uWSGI for WebSocket is possible but adds deployment complexity.
- **Threading + simple-websocket** is the simplest, most compatible option. It supports true WebSocket transport (not just long-polling). For a turn-based card game with 2 players per room, threading handles the load trivially -- each game produces a handful of messages per second, not thousands.
- **Scaling ceiling is irrelevant here.** The single-worker gunicorn limitation of threading mode matters for apps serving thousands of concurrent WebSocket connections. A card game PvP server with ~10-50 simultaneous rooms (20-100 players) is well within threading capacity.

**Confidence:** HIGH -- versions verified on PyPI, async mode recommendation based on Flask-SocketIO maintainer discussions and current library maintenance status.

### Frontend (Game UI)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Socket.IO Client JS | 4.8.3 | Browser-to-server real-time communication | Matches Flask-SocketIO's server protocol. CDN delivery, no build step. Auto-reconnection, fallback to long-polling. |
| Vanilla HTML/CSS/JS | -- | Game board UI, hand display, mana/HP indicators | **Consistent with the existing dashboard pattern.** The Vercel analytics dashboard is vanilla HTML/JS with CDN libraries. No React/Vue/Svelte -- the game UI is a single page with a 5x5 grid, hand of cards, and status bars. A framework would add build tooling, bundle complexity, and npm dependency management for zero benefit at this UI complexity. |
| CSS Grid | -- | 5x5 board layout | Native CSS Grid (`grid-template: repeat(5, 1fr) / repeat(5, 1fr)`) is purpose-built for the 5x5 game board. No grid framework needed. |

**CDN includes (no npm, no build step):**
```html
<script src="https://cdn.socket.io/4.8.3/socket.io.min.js"></script>
```

**Confidence:** HIGH -- Socket.IO client 4.8.3 verified on CDN (jsDelivr, cdnjs). Vanilla JS is a deliberate choice matching project conventions.

### State Serialization

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| dataclasses.asdict() (stdlib) | -- | Convert frozen GameState to dict for JSON emission | Already used throughout the codebase. Zero new dependencies. Python 3.12 has optimized `asdict()` for common types (int, str, bool, float) -- significant speedup for JSON serialization. |
| json (stdlib) | -- | JSON encoding for Socket.IO emit | Socket.IO's Python library handles JSON serialization automatically when you `emit()` a dict. No manual `json.dumps()` needed for basic types. |
| Custom `to_client_dict()` methods | -- | Per-player view filtering (hidden information) | The serialization layer MUST strip opponent's hand, deck contents, and deck order before sending. A custom method on GameState that takes `viewer_side: PlayerSide` produces the filtered view. This is game logic, not a library concern. |

**Why NOT msgspec/orjson/cattrs:** The game server serializes one game state per action per room. At ~1 serialization per second per room, stdlib `json` is more than fast enough. Adding a serialization library would be premature optimization that adds a dependency for no measurable gain.

**Confidence:** HIGH -- `dataclasses.asdict()` is stdlib and already the project's pattern.

### Room Management

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Flask-SocketIO rooms (built-in) | -- | Group players by game room | Flask-SocketIO has first-class room support: `join_room(code)`, `leave_room(code)`, `emit('event', data, to=code)`. No additional library needed. |
| secrets.token_urlsafe(6) (stdlib) | -- | Generate room codes | 8-character URL-safe room codes. Short enough to share verbally, random enough to prevent guessing. Stdlib `secrets` module uses cryptographically secure randomness. |
| Python dict (in-memory) | -- | Room state registry (room_code -> GameSession) | A simple `dict[str, GameSession]` mapping room codes to active game sessions. For a single-server deployment with ~50 rooms, an in-memory dict is the right choice. No Redis, no database. |

**Why NOT Redis for room state:** Redis adds a network dependency, deployment complexity, and serialization overhead. The PvP server is a single process (threading mode, single gunicorn worker). In-memory state is faster and simpler. If the server restarts, active games are lost -- this is acceptable for a v1.1 MVP. Persistence is a future concern.

**Confidence:** HIGH -- Flask-SocketIO rooms are a core feature, not an add-on.

---

## Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Flask-CORS | >=5.0 | Cross-origin requests if game UI is served from different domain | Only needed if the game HTML is served from a different origin than the Flask-SocketIO server. If serving from the same Flask app (recommended for v1.1), CORS is handled by Flask-SocketIO's `cors_allowed_origins` parameter. |
| gunicorn | >=23.0 | Production WSGI server | For production deployment. Run with `gunicorn --worker-class=gthread --workers=1 --threads=100 server:app`. Single worker required for Flask-SocketIO session affinity. Threading mode with simple-websocket. |

**Confidence:** MEDIUM for Flask-CORS (may not be needed). HIGH for gunicorn.

---

## Integration With Existing Python Engine

The PvP server wraps the **existing Python game engine** (`src/grid_tactics/`). It does NOT use the tensor engine (that is for GPU training only).

### Integration Surface

```
Flask-SocketIO Server
  |
  |-- GameState.new_game(seed, deck_p1, deck_p2)     # Create game
  |-- legal_actions(state, library)                    # Get valid moves for UI
  |-- resolve_action(state, action, library)           # Apply player's chosen action
  |-- CardLibrary.from_directory("data/cards/")        # Load card pool once at startup
  |
  v
Existing Python Engine (unchanged)
```

**Key design point:** The server holds one `GameState` per room. When a player submits an action via WebSocket, the server:
1. Validates the action is in `legal_actions(state, library)`
2. Calls `resolve_action(state, action, library)` to get the new state
3. Emits filtered views to each player via `to_client_dict(viewer_side)`

The immutable `GameState` with `dataclasses.replace()` is ideal for this -- each action produces a new state snapshot, and the server holds the latest one.

### Serialization Boundary

The frozen dataclasses use `IntEnum` values throughout (PlayerSide, TurnPhase, ActionType, etc.). These serialize to integers naturally via `dataclasses.asdict()`. The JavaScript client maps integers back to display strings.

Action objects from the client arrive as JSON dicts and must be validated + reconstructed as `Action` dataclass instances server-side. Never trust client-submitted actions -- always validate against `legal_actions()`.

---

## Installation

```bash
# New dependencies for PvP server (add to existing venv)
pip install Flask>=3.1,<4.0
pip install Flask-SocketIO>=5.6,<6.0
pip install simple-websocket>=1.1

# Production server
pip install gunicorn>=23.0
```

### pyproject.toml Addition

```toml
[project.optional-dependencies]
# ... existing groups ...
pvp = [
    "Flask>=3.1,<4.0",
    "Flask-SocketIO>=5.6,<6.0",
    "simple-websocket>=1.1",
]
pvp-prod = [
    "gunicorn>=23.0",
]
```

**Total new dependencies: 3 (Flask, Flask-SocketIO, simple-websocket).** Flask-SocketIO pulls `python-socketio` and `python-engineio` as transitive deps. That is the full dependency tree for the game server.

---

## Alternatives Considered

| Recommended | Alternative | Why Not Alternative |
|-------------|-------------|---------------------|
| Flask-SocketIO | FastAPI + raw WebSockets | FastAPI WebSockets lack rooms, namespaces, auto-reconnection, and broadcasting -- you would implement all of these manually. Flask-SocketIO provides them out of the box. For a turn-based game where latency tolerance is ~100ms, the raw performance advantage of FastAPI is irrelevant. |
| Flask-SocketIO | FastAPI + python-socketio | Viable but adds complexity. You mount `socketio.ASGIApp` as a sub-application of FastAPI, requiring ASGI deployment (uvicorn). The project has no existing ASGI infrastructure. Flask-SocketIO is simpler and purpose-built. |
| Flask-SocketIO | Django Channels | Django is a heavy framework. Grid Tactics has no ORM, no admin panel, no template engine needs. Django Channels adds channel layers (Redis required), ASGI deployment, and significantly more moving parts for the same WebSocket functionality. |
| Vanilla HTML/JS | React/Vue/Svelte | The game UI is a single page: 5x5 grid, hand of cards, mana bar, HP bar, action buttons. The existing analytics dashboard is vanilla HTML/JS. Introducing a framework means adding npm, a build step, bundling, and a JS dependency tree -- all for a UI that can be built with ~500 lines of vanilla JS. If the UI grows significantly (deck builder, collection, matchmaking lobby), revisit this decision. |
| Vanilla HTML/JS | Phaser.js | Phaser is a canvas-based game engine. Overkill for a card game with a 5x5 grid that can be represented with CSS Grid and DOM elements. Phaser excels at sprite animation and physics -- neither is needed here. DOM-based UI is simpler to style, more accessible, and easier to debug. |
| In-memory dict | Redis for room state | Redis adds a network hop, a running service, serialization/deserialization of GameState objects, and deployment complexity. For a single-process server with tens of rooms, an in-memory dict is faster and simpler. Add Redis only if you need multiple server instances (horizontal scaling), which is out of scope for v1.1. |
| Threading async mode | Gevent | Gevent itself is fine, but its WebSocket support depends on gevent-websocket (last updated 2017, abandoned) or uWSGI with custom config. Threading with simple-websocket (maintained, 2024 release) is simpler and fully supports WebSocket transport. |
| Threading async mode | Eventlet | Eventlet is deprecated and in maintenance mode. Compatibility issues with Python 3.10+. Not recommended for new projects per Flask-SocketIO maintainer. |
| dataclasses.asdict() | Pydantic serialization | Pydantic would require rewriting all frozen dataclasses to Pydantic models. The game engine uses `frozen=True` dataclasses with `__post_init__` validation throughout. Pydantic would add runtime overhead to every GameState creation (millions during RL training). The PvP server should use the same data model as the engine, not a parallel one. |
| dataclasses.asdict() | msgspec / orjson | At ~1 serialization per second per room, stdlib JSON is fast enough. msgspec requires schema definitions, orjson requires a C extension. Neither provides meaningful benefit at this throughput. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| eventlet | Deprecated, maintenance-mode, Python 3.10+ compatibility issues | Threading + simple-websocket |
| gevent-websocket | Abandoned (last release 2017), Python 2.7/3.5 only | simple-websocket (1.1.0, 2024) |
| React / Vue / Svelte | Adds npm, build tooling, bundling for a single-page game UI | Vanilla HTML/CSS/JS (matches existing dashboard) |
| Redis | Unnecessary for single-process server with tens of rooms | In-memory Python dict |
| Pydantic | Would require rewriting game engine data model | dataclasses.asdict() with custom view filtering |
| Pygame | No value for a web-based game | HTML/CSS game board |
| boardgame.io | JavaScript library -- wrong language. Game engine is Python | Flask-SocketIO wrapping existing Python engine |
| WebSocket (raw) | No rooms, no auto-reconnect, no broadcasting, no long-polling fallback | Socket.IO (Flask-SocketIO + socket.io-client) |
| Docker (for v1.1 dev) | Adds container complexity before the server works | Run Flask-SocketIO directly in venv |
| Database for game state | Active game state does not need persistence. Games are ephemeral | In-memory dict |

---

## Version Compatibility Matrix

All versions verified on PyPI as of 2026-04-04.

| Package | Version | Python Requirement | Compatibility Notes |
|---------|---------|-------------------|---------------------|
| Flask | 3.1.3 | >=3.9 | OK with 3.12. Security fix release (Feb 2026). |
| Flask-SocketIO | 5.6.1 | >=3.8 | OK with 3.12. Session fixes for Flask >=3.1.3. CI tests 3.13/3.14. |
| python-socketio | 5.16.1 | >=3.8 | OK with 3.12. Transitive dep of Flask-SocketIO. |
| python-engineio | (matches socketio) | >=3.8 | OK with 3.12. Transitive dep of python-socketio. |
| simple-websocket | 1.1.0 | >=3.6 | OK with 3.12. WebSocket transport for threading mode. |
| Socket.IO Client JS | 4.8.3 | N/A (browser) | Protocol-compatible with python-socketio 5.x. CDN delivery. |
| gunicorn | 23.x | >=3.7 | OK with 3.12. Use `--worker-class=gthread --workers=1 --threads=100`. |

**No conflicts with existing stack.** Flask, Flask-SocketIO, and simple-websocket have no dependency overlap with PyTorch, SB3, NumPy, or the RL stack. The PvP server and training pipeline share the game engine code but have completely separate dependency trees.

---

## Stack Patterns by Variant

**If deploying on same machine as training:**
- Run Flask-SocketIO on a different port (e.g., 5000) than any training services
- The PvP server uses CPU only (Python game engine), so it does not compete with GPU training
- Share the `data/cards/` directory for card definitions

**If deploying on a separate server (Render, Railway, Fly.io):**
- Package as a single Python app with `gunicorn` entrypoint
- No GPU needed, cheapest tier is sufficient
- Upload `data/cards/` and `src/grid_tactics/` with the deployment
- Consider adding `CORS_ORIGINS` env var for the game UI if served separately

**If adding AI opponent later (vs RL agent):**
- Load the trained PyTorch model in the Flask-SocketIO server
- The AI player calls `model.predict(observation, action_masks)` instead of waiting for WebSocket input
- This requires PyTorch in the PvP server's dependencies -- keep it optional until needed

---

## Sources

- [Flask-SocketIO PyPI](https://pypi.org/project/Flask-SocketIO/) -- version 5.6.1 (Feb 2026), confirmed Python >=3.8
- [Flask PyPI](https://pypi.org/project/Flask/) -- version 3.1.3 (Feb 2026)
- [python-socketio PyPI](https://pypi.org/project/python-socketio/) -- version 5.16.1 (Feb 2026)
- [simple-websocket PyPI](https://pypi.org/project/simple-websocket/) -- version 1.1.0 (Oct 2024)
- [gevent PyPI](https://pypi.org/project/gevent/) -- version 25.9.1 (Sep 2025), Python 3.9+
- [gevent-websocket PyPI](https://pypi.org/project/gevent-websocket/) -- version 0.10.1 (Mar 2017), ABANDONED
- [Socket.IO Client CDN](https://www.jsdelivr.com/package/npm/socket.io-client) -- version 4.8.3 (Dec 2025)
- [Flask-SocketIO async mode discussion](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/1915) -- maintainer guidance on eventlet/gevent/threading
- [Flask-SocketIO eventlet deprecation discussion](https://github.com/miguelgrinberg/Flask-SocketIO/discussions/2037) -- eventlet maintenance status
- [Flask-SocketIO deployment docs](https://flask-socketio.readthedocs.io/en/latest/deployment.html) -- gunicorn config
- [Socket.IO client installation](https://socket.io/docs/v4/client-installation/) -- CDN URLs and version

---
*Stack research for: Grid Tactics TCG v1.1 Online PvP Dueling*
*Researched: 2026-04-04*
