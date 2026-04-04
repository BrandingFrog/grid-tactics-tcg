# Phase 11: Server Foundation & Room System - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Flask-SocketIO server with room code system. Two clients connect via WebSocket, create/join a game room by code, both receive game_start event with initial state. Testable with programmatic WebSocket clients (no browser UI needed).

</domain>

<decisions>
## Implementation Decisions

### Player Identity
- **D-01:** Players enter a display name when creating or joining a room. Name shown to opponent. No persistence, no accounts — ephemeral session only.

### Deck Composition
- **D-02:** Server accepts player-chosen decks: up to 3 copies of any card, max 30 cards total. The deck is submitted by the client when readying up.
- **D-03:** For Phase 11 testing (before deck builder UI exists), use a default preset deck so programmatic clients can connect and play.
- **D-04:** Deck builder UI deferred to Phase 13 (Board & Hand UI) — extend the existing dashboard's Cards tab to let players construct their deck before joining.

### Game Start Flow
- **D-05:** Both players must click "Ready" to start the game. This allows reviewing opponent name before committing.
- **D-06:** First player is chosen randomly (coin flip via server RNG). Not deterministic by room creator.

### Engine Fixes (from research)
- **D-07:** Fix `_fatigue` global dict (action_resolver.py:110) — module-level mutable state keyed by seed corrupts concurrent games. Must be moved into GameState or scoped per-game before multi-game server works.

### Claude's Discretion
- Room code format (length, character set, case sensitivity)
- Session token implementation (cookie vs header, format)
- In-memory data structures for room/game tracking
- Flask-SocketIO async mode selection (threading recommended per research)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Game Engine (reused directly)
- `src/grid_tactics/game_state.py` — GameState frozen dataclass, `to_dict()` at line 110 (leaks hidden info — Phase 12 concern, but serialization boundary set here)
- `src/grid_tactics/action_resolver.py` — `resolve_action()` at line 654, `_fatigue` global at line 110 (MUST FIX for concurrent games)
- `src/grid_tactics/legal_actions.py` — `legal_actions()` at line 51
- `src/grid_tactics/game_loop.py` — `run_game()` at line 45 (reference for game flow, but PvP is event-driven not loop-driven)
- `src/grid_tactics/card_library.py` — `CardLibrary.from_directory()` for loading card definitions

### Research
- `.planning/research/ARCHITECTURE.md` — Server component design, data flow, integration patterns
- `.planning/research/PITFALLS.md` — 12 pitfalls including info leakage, _fatigue global, race conditions
- `.planning/research/STACK.md` — Flask 3.1, Flask-SocketIO 5.6, simple-websocket 1.1, threading mode

### Card Data
- `data/cards/*.json` — 19 card definition files loaded by CardLibrary

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `GameState.new_game(seed, deck_p1, deck_p2, library)` — Creates initial game state. Directly usable for PvP game initialization.
- `resolve_action(state, action, library)` → `GameState` — Pure function, no side effects (except _fatigue). Perfect for server-authoritative model.
- `legal_actions(state, library)` → `tuple[Action, ...]` — Enumerates all valid moves. Send to client with each state update.
- `GameState.to_dict()` — Full serialization exists. Phase 12 will add view filtering on top.
- `CardLibrary.from_directory("data/cards")` — Loads all 19 cards. Server loads once at startup.

### Established Patterns
- Frozen dataclasses with `replace()` for all state mutations — server holds GameState per room
- IntEnum for all game constants (PlayerSide, TurnPhase, ActionType) — serialize as ints over WebSocket
- Deterministic RNG via seed — server generates seed per game for reproducibility

### Integration Points
- Server wraps existing engine functions (no engine modifications except _fatigue fix)
- New `pvp_server.py` (or similar) at project root — Flask app serving SocketIO
- CardLibrary loaded once at server startup, shared across all games
- Action deserialization needed: client sends action as JSON, server constructs Action dataclass

</code_context>

<specifics>
## Specific Ideas

- User wants deck builder in the existing dashboard's Cards tab (Phase 13), not a separate page
- Both players use custom decks (up to 3x per card, max 30) — this is a core game design decision, not just a v1.1 feature
- Ready button before game start — important for the social aspect of playing with a friend

</specifics>

<deferred>
## Deferred Ideas

- **Deck builder UI** — Extend dashboard Cards tab to let players build decks (up to 3x per card, max 30). Deferred to Phase 13.

</deferred>

---

*Phase: 11-server-foundation-room-system*
*Context gathered: 2026-04-05*
