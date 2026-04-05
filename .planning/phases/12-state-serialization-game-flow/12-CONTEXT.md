# Phase 12: State Serialization & Game Flow - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Complete game playable via raw WebSocket messages. Both players take turns, react windows work, actions are validated, opponent hand is hidden, and the game ends with a correct winner. No browser UI — testable with programmatic WebSocket clients only.

</domain>

<decisions>
## Implementation Decisions

### Hidden Information Filtering
- **D-01:** Server filters GameState before emitting to each player. Opponent's hand contents are replaced with a count only — no card IDs or details leaked. Deck contents and seed also stripped.
- **D-02:** At game over, hidden info stays hidden — final board + HP shown, but hands/decks remain private. No post-game reveal.

### React Window
- **D-03:** When a player plays a react card, BOTH players see which card was played (name, effect). Full transparency after react card is committed. No hidden react cards.

### Draw Mechanic
- **D-04:** Draw is a player action (costs the turn's one action). NO auto-draw at turn start. `AUTO_DRAW_ENABLED = False` is the correct setting. Opponent sees hand count increase but not which card was drawn.
- **D-05:** If any auto-draw code fires in react_stack.py during turn transition, it must be disabled/skipped for PvP mode. The server must respect the draw-as-action rule.

### Action Validation
- **D-06:** Server validates every action against `legal_actions()` before applying. Illegal actions emit an error event back to the submitting player — never crash, never corrupt state.

### State Updates
- **D-07:** Each state update includes the player's filtered state AND their current legal actions list. Client always knows what moves are available without computing locally.

### Claude's Discretion
- Action JSON serialization format (how client sends actions, how server deserializes to Action dataclass)
- Event protocol design (event names, payload shapes)
- How to handle the turn transition flow (ACTION → REACT → next turn)
- Per-player emit pattern (emit to individual SIDs, not room broadcast)
- Thread locking strategy for state mutations

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Server Foundation (Phase 11 output)
- `src/grid_tactics/server/events.py` — Existing event handlers (create_room, join_room, ready). Extend with game action handlers.
- `src/grid_tactics/server/game_session.py` — GameSession with lock, state, rng, library, token→player mapping
- `src/grid_tactics/server/room_manager.py` — RoomManager with active_games dict mapping room_code → GameSession
- `src/grid_tactics/server/app.py` — Flask app factory with SocketIO

### Game Engine (reused directly)
- `src/grid_tactics/game_state.py` — GameState frozen dataclass, `to_dict()` at line 110 (MUST FILTER before emitting)
- `src/grid_tactics/action_resolver.py` — `resolve_action()` at line 654 (pure function, call from event handler)
- `src/grid_tactics/legal_actions.py` — `legal_actions()` at line 51 (enumerate valid moves per state)
- `src/grid_tactics/actions.py` — Action dataclass, action factory functions (play_card_action, move_action, etc.)
- `src/grid_tactics/react_stack.py` — React resolution, turn transition (line 280: auto-draw code that may need disabling for PvP)
- `src/grid_tactics/enums.py` — ActionType, TurnPhase, PlayerSide enums
- `src/grid_tactics/types.py` — `AUTO_DRAW_ENABLED = False` (line 48)

### Research
- `.planning/research/ARCHITECTURE.md` — Server component design, data flow patterns
- `.planning/research/PITFALLS.md` — Info leakage pitfalls, race conditions, react desync

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `GameSession.lock` — Threading lock for state mutations, already exists
- `GameSession.get_player_idx(token)` — Maps session token to player 0/1
- `GameSession.player_sids` — Mutable list for per-player SID emission
- `to_dict()` — Full serialization exists, needs a filtered wrapper (`to_player_dict(viewer_idx)`)
- `resolve_action(state, action, library)` → `GameState` — Pure function, ready for server use
- `legal_actions(state, library)` → `tuple[Action, ...]` — Ready to serialize and send

### Established Patterns
- `register_events(room_manager)` — Event handler registration pattern from Phase 11
- Per-SID emission via `emit(..., to=session.player_sids[idx])` — Already used in game_start
- GameState is frozen, `replace()` for mutations — server updates `session.state = new_state`

### Integration Points
- Extend `events.py` with `submit_action` handler
- Add `to_player_dict(viewer_idx)` method to GameState (or standalone function)
- Serialize Action dataclass to/from JSON for WebSocket transport
- Handle game_over detection in action handler (check `state.is_game_over` after resolve)

</code_context>

<specifics>
## Specific Ideas

- Draw-as-action is the active rule — no auto-draw. Must verify react_stack.py turn transition doesn't auto-draw.
- React cards fully visible when played — simplifies the state update since we just show the card.
- Game over keeps hidden info hidden — simpler filter logic (same filter at game over as during game).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 12-state-serialization-game-flow*
*Context gathered: 2026-04-05*
