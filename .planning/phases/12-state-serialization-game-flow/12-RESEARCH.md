# Phase 12: State Serialization & Game Flow - Research

**Researched:** 2026-04-05
**Domain:** WebSocket game state filtering, action validation, turn-based multiplayer protocol
**Confidence:** HIGH

## Summary

Phase 12 adds the core game flow to the PvP server: state serialization with hidden information filtering, action validation, and a complete game lifecycle over WebSocket. The existing engine code (`resolve_action()`, `legal_actions()`, `GameState.to_dict()`) is already structured for clean integration -- the server layer is a thin orchestration wrapper that validates, dispatches, and filters.

Three critical findings drive the implementation: (1) `react_stack.py` lines 280-285 unconditionally auto-draw at turn transition, violating the D-04 draw-as-action rule -- this must be guarded by `AUTO_DRAW_ENABLED`; (2) `legal_actions()` returns an empty tuple in ACTION phase when no moves exist (no PASS included) -- the server must auto-pass in this case to trigger fatigue; (3) the existing `to_dict()` serializes everything including opponent hands and deck order -- a `filter_state_for_player()` function must strip hidden info before every emission.

**Primary recommendation:** Build a `view_filter.py` module for per-player state filtering, extend `events.py` with a `submit_action` handler that validates against `legal_actions()`, and fix the auto-draw bug in `react_stack.py` before any PvP testing.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- D-01: Server filters GameState before emitting to each player. Opponent's hand contents are replaced with a count only -- no card IDs or details leaked. Deck contents and seed also stripped.
- D-02: At game over, hidden info stays hidden -- final board + HP shown, but hands/decks remain private. No post-game reveal.
- D-03: When a player plays a react card, BOTH players see which card was played (name, effect). Full transparency after react card is committed. No hidden react cards.
- D-04: Draw is a player action (costs the turn's one action). NO auto-draw at turn start. AUTO_DRAW_ENABLED = False is the correct setting.
- D-05: If any auto-draw code fires in react_stack.py during turn transition, it must be disabled/skipped for PvP mode.
- D-06: Server validates every action against legal_actions() before applying. Illegal actions emit an error event -- never crash, never corrupt state.
- D-07: Each state update includes the player's filtered state AND their current legal actions list. Client always knows what moves are available without computing locally.

### Claude's Discretion
- Action JSON serialization format (how client sends actions, how server deserializes to Action dataclass)
- Event protocol design (event names, payload shapes)
- How to handle the turn transition flow (ACTION -> REACT -> next turn)
- Per-player emit pattern (emit to individual SIDs, not room broadcast)
- Thread locking strategy for state mutations

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SERVER-03 | Both players receive real-time state updates after each action resolves | Per-SID emission pattern via `emit(..., to=session.player_sids[idx])` -- already used in Phase 11 `game_start`. ViewFilter strips hidden info before emission. |
| VIEW-01 | User can only see their own hand and deck count -- opponent's hand contents and deck order are hidden | `filter_state_for_player()` replaces opponent hand with count, strips both decks to count. Verified `to_dict()` outputs all fields needed. |
| VIEW-02 | Server validates all actions against legal_actions() before applying -- illegal actions are rejected | `legal_actions()` returns tuple of valid Actions. Server reconstructs Action from JSON, checks membership, emits error on mismatch. |
| VIEW-03 | User receives their legal actions list with every state update | Serialize legal_actions() output alongside filtered state in every `state_update` event. |
</phase_requirements>

## Standard Stack

### Core (Phase 11 established -- reuse)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask-SocketIO | >=5.6 | WebSocket server | Already installed and used in Phase 11 |
| Flask | >=3.0 | HTTP framework | Flask-SocketIO dependency, already installed |
| simple-websocket | >=1.0 | WebSocket transport | Required for threading async mode |

### Supporting (game engine -- reuse as-is)
| Module | Location | Purpose | When to Use |
|--------|----------|---------|-------------|
| `resolve_action()` | `action_resolver.py:654` | Validate and apply actions | Every `submit_action` handler call |
| `legal_actions()` | `legal_actions.py:51` | Enumerate valid moves | After every state change for emission |
| `GameState.to_dict()` | `game_state.py:113` | Serialize state to JSON-safe dict | Before filtering for each player |
| `Action` dataclass | `actions.py:26` | Structured action representation | Reconstruct from client JSON payload |
| `CardLibrary` | `card_library.py` | Card definition lookups | Loaded once at server startup |

### No New Dependencies
This phase requires zero new pip packages. All dependencies were installed in Phase 11.

## Architecture Patterns

### Recommended New Files
```
src/grid_tactics/server/
  view_filter.py          # NEW: Per-player state filtering (D-01, D-02)
  events.py               # EXTEND: Add submit_action handler
  game_session.py         # EXTEND: Add process_action method (optional)
```

### Pattern 1: View Filter (Per-Player State Sanitization)
**What:** A standalone function that takes a full `to_dict()` output and a viewer player index, returns a filtered dict with hidden info stripped.
**When to use:** Before EVERY emission of state to a client. No exceptions.
**Example:**
```python
# Source: ARCHITECTURE.md research + D-01/D-02 decisions
import copy

def filter_state_for_player(state_dict: dict, viewer_idx: int) -> dict:
    """Strip hidden information for a specific player's view.
    
    Hidden: opponent hand contents, both deck contents/order, seed.
    Visible: board, minions, HP, mana, graveyards, own hand, card counts.
    Same filter at game over as during game (D-02).
    """
    filtered = copy.deepcopy(state_dict)
    opponent_idx = 1 - viewer_idx
    
    # Strip opponent hand -- show count only (D-01)
    opp = filtered['players'][opponent_idx]
    opp['hand_count'] = len(opp['hand'])
    opp['hand'] = []
    
    # Strip both decks -- show count only
    for p in filtered['players']:
        p['deck_count'] = len(p['deck'])
        p['deck'] = []
    
    # Strip seed (implementation detail, not player-visible)
    filtered.pop('seed', None)
    
    return filtered
```

### Pattern 2: Action Reconstruction (JSON to Action Dataclass)
**What:** Convert client-sent JSON action payload into a frozen `Action` dataclass, with full error handling.
**When to use:** In the `submit_action` event handler, before validation.
**Example:**
```python
# Source: ARCHITECTURE.md action reconstruction pattern
from grid_tactics.actions import Action
from grid_tactics.enums import ActionType

def reconstruct_action(data: dict) -> Action:
    """Convert client action payload to engine Action dataclass.
    
    Raises ValueError on malformed data.
    """
    if not isinstance(data, dict) or 'action_type' not in data:
        raise ValueError("Invalid action payload")
    
    return Action(
        action_type=ActionType(data['action_type']),
        card_index=data.get('card_index'),
        position=tuple(data['position']) if data.get('position') else None,
        minion_id=data.get('minion_id'),
        target_id=data.get('target_id'),
        target_pos=tuple(data['target_pos']) if data.get('target_pos') else None,
    )
```

### Pattern 3: Per-SID Emission with Legal Actions
**What:** After every state change, emit filtered state + serialized legal actions to each player individually.
**When to use:** After every `resolve_action()` call.
**Example:**
```python
# Source: Phase 11 pattern in events.py + D-07
def emit_state_to_players(session, state, library):
    """Emit per-player filtered state with legal actions."""
    state_dict = state.to_dict()
    
    # Compute legal actions for current decision-maker
    actions = legal_actions(state, library) if not state.is_game_over else ()
    serialized_actions = [serialize_action(a) for a in actions]
    
    # Determine who the decision-maker is
    if state.phase == TurnPhase.REACT:
        decision_player_idx = state.react_player_idx
    else:
        decision_player_idx = state.active_player_idx
    
    for idx in (0, 1):
        filtered = filter_state_for_player(state_dict, idx)
        payload = {
            'state': filtered,
            'legal_actions': serialized_actions if idx == decision_player_idx else [],
            'your_player_idx': idx,
        }
        emit('state_update', payload, to=session.player_sids[idx])
```

### Pattern 4: Auto-Pass for Zero Legal Actions
**What:** When `legal_actions()` returns empty tuple in ACTION phase, the server must auto-submit a PASS to trigger fatigue bleed.
**When to use:** After any state change where the next active player has no legal actions.
**Why:** `legal_actions()` does NOT include PASS in ACTION phase. The `game_loop.py` handles this at line 73-79 by auto-passing. The server must replicate this pattern.
**Example:**
```python
# After resolving an action, check if next player has moves
actions = legal_actions(new_state, library)
while len(actions) == 0 and not new_state.is_game_over:
    # Auto-pass triggers fatigue (escalating damage)
    new_state = resolve_action(new_state, pass_action(), library)
    if new_state.is_game_over:
        break
    actions = legal_actions(new_state, library)
```

### Pattern 5: Action Serialization for Wire Format
**What:** Serialize Action dataclass to JSON-safe dict for client consumption.
**When to use:** When building the `legal_actions` list for state_update events.
**Example:**
```python
def serialize_action(action: Action) -> dict:
    """Convert Action dataclass to JSON-safe dict for client."""
    d = {'action_type': int(action.action_type)}
    if action.card_index is not None:
        d['card_index'] = action.card_index
    if action.position is not None:
        d['position'] = list(action.position)
    if action.minion_id is not None:
        d['minion_id'] = action.minion_id
    if action.target_id is not None:
        d['target_id'] = action.target_id
    if action.target_pos is not None:
        d['target_pos'] = list(action.target_pos)
    return d
```

### Anti-Patterns to Avoid
- **Full state broadcast to room:** Room broadcast leaks hidden info. Always emit per-SID with filtered views.
- **Client-side legal action computation:** Never duplicate `legal_actions()` in JS. Server is the single source of truth.
- **Trusting client-submitted actions:** ALWAYS validate against `legal_actions()` before applying. A malicious WebSocket client can send anything.
- **Modifying engine code for server needs:** All server concerns live in `server/` modules. The engine remains clean for RL training.
- **Emitting raw `to_dict()` output:** Always run through `filter_state_for_player()` first.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Action validation | Custom validation logic | `legal_actions()` membership check | Engine already enumerates all valid actions exhaustively. Reconstructing and checking membership is a 3-line solution. Duplicating validation rules is fragile. |
| State serialization | Custom JSON builder | `GameState.to_dict()` + filter wrapper | `to_dict()` already handles IntEnum, tuples, Optional fields. Don't rebuild. |
| Turn phase tracking | Server-side state machine | `state.phase` + `state.react_player_idx` | Engine already manages the ACTION -> REACT -> ACTION flow internally. Server reads the phase from state. |
| React window chaining | Custom react flow logic | `resolve_action()` (delegates to `handle_react_action()`) | React stack with LIFO resolution, counter-react chaining, and NEGATE effects is already implemented in `react_stack.py`. |
| Dead minion cleanup | Post-action cleanup code | `resolve_action()` already calls `_cleanup_dead_minions()` | Part of the action resolution pipeline. |
| Game over detection | Custom win check | `state.is_game_over` + `state.winner` | Set automatically by `_check_game_over()` inside `resolve_action()`. |

**Key insight:** The game engine's pure-function architecture (`state_in -> state_out`) means the server is purely an I/O orchestrator. All game logic is reused as-is.

## Common Pitfalls

### Pitfall 1: Auto-Draw Bug in react_stack.py (CRITICAL)
**What goes wrong:** `react_stack.py` lines 280-285 unconditionally auto-draw at turn start during `resolve_react_stack()`. This fires every time a turn transitions, ignoring `AUTO_DRAW_ENABLED = False`.
**Why it happens:** The auto-draw code was written before the draw-as-action rule was established. It never checks the `AUTO_DRAW_ENABLED` flag from `types.py`.
**How to avoid:** Guard lines 280-285 with `if AUTO_DRAW_ENABLED:` check. Verified: `types.py` line 48 has `AUTO_DRAW_ENABLED: bool = False`.
**Warning signs:** Players' hand sizes increase after opponent passes in react window, even though no DRAW action was submitted.

### Pitfall 2: Empty Legal Actions in ACTION Phase (CRITICAL)
**What goes wrong:** `legal_actions()` in ACTION phase does NOT include PASS. When no actions are available (e.g., empty hand, no deck, no minions on board), it returns an empty tuple. If the server emits this to the client, the player has zero options and the game freezes.
**Why it happens:** The engine design treats zero-actions as a trigger for fatigue bleed (escalating 10/20/30 HP damage per forced pass). The `game_loop.py` handles this at line 73-79.
**How to avoid:** After each `resolve_action()`, check if `legal_actions()` returns empty and `state.is_game_over` is False. If so, auto-submit `pass_action()` in a loop until the player has actions or the game ends.
**Warning signs:** Client receives `legal_actions: []` during ACTION phase with `is_game_over: false`.

### Pitfall 3: Information Leakage in State Updates
**What goes wrong:** Opponent hand card IDs, deck order, or seed leak in WebSocket frames. Any player with browser DevTools can see opponent's cards.
**Why it happens:** Calling `to_dict()` and emitting without filtering. Or forgetting to filter in one code path (e.g., game_start, game_over, or react phase transitions).
**How to avoid:** Single function `filter_state_for_player()` called before EVERY emission. Same filter at game over (D-02). Write tests that assert opponent hand IDs never appear in filtered output.
**Warning signs:** Test: `json.dumps(filtered_state)` and search for opponent card numeric IDs.

### Pitfall 4: Turn Decision-Maker Confusion (React Phase)
**What goes wrong:** During REACT phase, the "decision maker" is `react_player_idx`, NOT `active_player_idx`. If the server uses `active_player_idx` to determine who can submit an action, the wrong player gets control during react windows.
**Why it happens:** `active_player_idx` tracks whose turn it is (the action initiator). During REACT, the responder is identified by `react_player_idx`.
**How to avoid:** Check `state.phase`: if ACTION, use `active_player_idx`; if REACT, use `react_player_idx`. Send legal actions only to the decision-maker.
**Warning signs:** Action player can submit during react window; react player's actions are rejected.

### Pitfall 5: Race Conditions on State Mutation
**What goes wrong:** Two WebSocket events arrive nearly simultaneously (e.g., player submits action just as timer fires). Both try to read and write `session.state` without synchronization. State gets corrupted.
**Why it happens:** Flask-SocketIO threading mode processes events in separate threads.
**How to avoid:** `GameSession.lock` (threading.Lock) already exists from Phase 11. Acquire it around all state reads and mutations in the `submit_action` handler. Keep the critical section small -- lock around validation + state mutation, emit after releasing.
**Warning signs:** Intermittent "action not in legal_actions" errors, or game state jumps backward.

### Pitfall 6: Malformed Action Payload Crashes Server
**What goes wrong:** Client sends `{action_type: "PLAY_CARD"}` (string instead of int), or `{position: [1]}` (array too short), or omits required fields. Action reconstruction crashes with an unhandled exception.
**Why it happens:** No input validation on the JSON payload before constructing the Action dataclass.
**How to avoid:** Wrap `reconstruct_action()` in try/except. On any ValueError/KeyError/TypeError, emit `error` event with a descriptive message. Never let raw exceptions propagate.
**Warning signs:** Server crashes or returns 500 errors on malformed input.

## Code Examples

### Complete submit_action Handler Pattern
```python
# Source: Derived from Phase 11 patterns + ARCHITECTURE.md
@socketio.on('submit_action')
def handle_submit_action(data):
    token = _room_manager.get_token_by_sid(request.sid)
    if token is None:
        emit('error', {'msg': 'Not in a game'})
        return
    
    room_code = _room_manager.get_room_code_by_token(token)
    session = _room_manager.get_game(room_code)
    if session is None:
        emit('error', {'msg': 'No active game'})
        return
    
    player_idx = session.get_player_idx(token)
    if player_idx is None:
        emit('error', {'msg': 'Not a player in this game'})
        return
    
    # Determine who should be acting
    state = session.state
    if state.is_game_over:
        emit('error', {'msg': 'Game is already over'})
        return
    
    if state.phase == TurnPhase.REACT:
        decision_idx = state.react_player_idx
    else:
        decision_idx = state.active_player_idx
    
    if player_idx != decision_idx:
        emit('error', {'msg': 'Not your turn'})
        return
    
    # Reconstruct action from client payload
    try:
        action = reconstruct_action(data)
    except (ValueError, KeyError, TypeError) as e:
        emit('error', {'msg': f'Invalid action: {e}'})
        return
    
    # Validate against legal actions
    with session.lock:
        valid_actions = legal_actions(session.state, session.library)
        if action not in valid_actions:
            emit('error', {'msg': 'Illegal action'})
            return
        
        # Apply action
        session.state = resolve_action(session.state, action, session.library)
        
        # Handle auto-pass for zero legal actions (fatigue)
        while not session.state.is_game_over:
            next_actions = legal_actions(session.state, session.library)
            if len(next_actions) > 0:
                break
            session.state = resolve_action(
                session.state, pass_action(), session.library
            )
        
        new_state = session.state
    
    # Emit (outside lock to avoid holding lock during I/O)
    _emit_state_to_players(session, new_state)
    
    if new_state.is_game_over:
        _emit_game_over(session, new_state, room_code)
```

### Action Equality for Validation
```python
# The Action dataclass is frozen with __eq__ auto-generated.
# This means `action in valid_actions` works via structural equality.
# Example:
from grid_tactics.actions import Action, draw_action
from grid_tactics.enums import ActionType

a1 = Action(action_type=ActionType.DRAW)
a2 = draw_action()
assert a1 == a2  # True -- frozen dataclass equality by fields
assert a1 in (a2,)  # True -- tuple membership via __eq__
```

### Wire Protocol Event Summary
```
CLIENT -> SERVER:
  submit_action  { action_type: int, card_index?: int, position?: [r,c],
                   minion_id?: int, target_id?: int, target_pos?: [r,c] }

SERVER -> CLIENT (per-SID):
  state_update   { state: <filtered>, legal_actions: [<action_dicts>],
                   your_player_idx: int }
  game_over      { winner: int|null, final_state: <filtered> }
  error          { msg: str }
```

### Game Over Emission Pattern
```python
def _emit_game_over(session, state, room_code):
    """Emit game_over to both players with filtered final state."""
    state_dict = state.to_dict()
    for idx in (0, 1):
        filtered = filter_state_for_player(state_dict, idx)
        emit('game_over', {
            'winner': int(state.winner) if state.winner is not None else None,
            'final_state': filtered,
            'your_player_idx': idx,
        }, to=session.player_sids[idx])
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw `to_dict()` in game_start | Needs filter wrapper | Phase 12 | Phase 11 emits unfiltered state in game_start (line 82) -- MUST be updated to use view filter |
| Auto-draw at turn start | Draw-as-action (D-04) | Phase 12 | `react_stack.py` lines 280-285 need AUTO_DRAW_ENABLED guard |

**Phase 11 game_start leak:** The Phase 11 `events.py` line 82 emits `session.state.to_dict()` without filtering at game start. This leaks both players' hands and decks. Phase 12 must update `game_start` emission to use the view filter.

## Open Questions

1. **game_start filter backport**
   - What we know: Phase 11 `events.py` line 82 emits raw `state_dict` without filtering in the `game_start` event
   - What's unclear: Should Phase 12 modify the game_start handler to use filtering, or is that a separate concern?
   - Recommendation: Fix it in Phase 12 as part of "all emissions use the filter" mandate. It is directly required by VIEW-01.

2. **Card definitions at game_start**
   - What we know: ARCHITECTURE.md Pattern 4 recommends sending full card catalog at game_start so clients can render card names/stats
   - What's unclear: The client needs card definitions to display hand contents -- should card_defs be sent with game_start or with every state_update?
   - Recommendation: Send once at game_start. Card definitions are public knowledge and do not change during a game. Include `card_defs` as a dict mapping numeric_id to `{name, mana_cost, attack, health, card_type, element, ...}`.

3. **PASS in ACTION phase for PvP**
   - What we know: `legal_actions()` does not include PASS in ACTION phase. The game_loop auto-passes when no actions available.
   - What's unclear: Should the server expose a "pass" option to human players? Or should humans always have at least one action (draw)?
   - Recommendation: Human players always have DRAW available (unless deck is empty AND hand is full). If truly no actions exist, the server auto-passes silently and emits the resulting state with fatigue damage applied. No player-facing PASS button needed in ACTION phase. PASS is only player-facing in REACT phase (where it is always included).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (version installed in .venv) |
| Config file | None -- implicit from project root |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/test_pvp_server.py -x -q` |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VIEW-01 | Opponent hand hidden, deck counts only | unit | `pytest tests/test_view_filter.py::test_opponent_hand_hidden -x` | No -- Wave 0 |
| VIEW-01 | Own hand visible in filtered state | unit | `pytest tests/test_view_filter.py::test_own_hand_visible -x` | No -- Wave 0 |
| VIEW-01 | Deck contents stripped, counts preserved | unit | `pytest tests/test_view_filter.py::test_decks_stripped -x` | No -- Wave 0 |
| VIEW-01 | Seed stripped from filtered state | unit | `pytest tests/test_view_filter.py::test_seed_stripped -x` | No -- Wave 0 |
| VIEW-01 | Game over state equally filtered (D-02) | unit | `pytest tests/test_view_filter.py::test_game_over_filter -x` | No -- Wave 0 |
| VIEW-02 | Legal action accepted by server | integration | `pytest tests/test_game_flow.py::test_legal_action_accepted -x` | No -- Wave 0 |
| VIEW-02 | Illegal action rejected with error | integration | `pytest tests/test_game_flow.py::test_illegal_action_rejected -x` | No -- Wave 0 |
| VIEW-02 | Malformed action rejected without crash | integration | `pytest tests/test_game_flow.py::test_malformed_action_rejected -x` | No -- Wave 0 |
| VIEW-02 | Wrong player's turn rejected | integration | `pytest tests/test_game_flow.py::test_wrong_turn_rejected -x` | No -- Wave 0 |
| VIEW-03 | State update includes legal actions list | integration | `pytest tests/test_game_flow.py::test_state_update_has_legal_actions -x` | No -- Wave 0 |
| VIEW-03 | Non-decision player receives empty legal actions | integration | `pytest tests/test_game_flow.py::test_non_active_gets_empty_actions -x` | No -- Wave 0 |
| SERVER-03 | Both players receive state after action | integration | `pytest tests/test_game_flow.py::test_both_receive_state_update -x` | No -- Wave 0 |
| SERVER-03 | React phase transitions correctly | integration | `pytest tests/test_game_flow.py::test_react_phase_flow -x` | No -- Wave 0 |
| SERVER-03 | Complete game playable to conclusion | integration | `pytest tests/test_game_flow.py::test_complete_game -x` | No -- Wave 0 |
| D-04 | Auto-draw disabled during turn transition | unit | `pytest tests/test_game_flow.py::test_no_auto_draw -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python.exe -m pytest tests/test_view_filter.py tests/test_game_flow.py -x -q`
- **Per wave merge:** `.venv/Scripts/python.exe -m pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_view_filter.py` -- covers VIEW-01 (state filtering, hidden info, game over filter)
- [ ] `tests/test_game_flow.py` -- covers SERVER-03, VIEW-02, VIEW-03, D-04 (action handling, validation, complete game)
- [ ] No new fixtures needed -- Phase 11 test patterns (`app` fixture, `socketio.test_client()`) are sufficient

## Sources

### Primary (HIGH confidence)
- Existing codebase: `game_state.py` (to_dict at line 113, from_dict at line 174)
- Existing codebase: `action_resolver.py` (resolve_action at line 653)
- Existing codebase: `legal_actions.py` (legal_actions at line 51, no PASS in action phase at line 176)
- Existing codebase: `react_stack.py` (auto-draw bug at lines 280-285)
- Existing codebase: `game_loop.py` (auto-pass pattern at lines 72-79)
- Existing codebase: `events.py` (Phase 11 game_start emission at line 82)
- Existing codebase: `game_session.py` (lock, get_player_idx, player_sids)
- Existing codebase: `types.py` (AUTO_DRAW_ENABLED = False at line 48)
- Existing codebase: `actions.py` (Action frozen dataclass with __eq__)
- `.planning/research/ARCHITECTURE.md` -- Server component design, data flow, view filter pattern
- `.planning/research/PITFALLS.md` -- Info leakage, action validation, react desync pitfalls
- `.planning/phases/12-state-serialization-game-flow/12-CONTEXT.md` -- User decisions D-01 through D-07

### Secondary (MEDIUM confidence)
- [Flask-SocketIO API Reference](https://flask-socketio.readthedocs.io/en/latest/api.html) -- test_client, emit to SID
- [Flask-SocketIO test patterns](https://github.com/miguelgrinberg/Flask-SocketIO/blob/main/test_socketio.py) -- get_received() usage

### Tertiary (LOW confidence)
None -- all findings verified against source code.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries already installed and used in Phase 11
- Architecture: HIGH - Patterns verified against existing codebase and Phase 11 implementations
- Pitfalls: HIGH - Auto-draw bug verified by reading react_stack.py source; empty legal actions verified by reading legal_actions.py source; game_start leak verified by reading events.py source
- View filter: HIGH - `to_dict()` output structure verified, filter logic is straightforward dict manipulation

**Research date:** 2026-04-05
**Valid until:** 2026-05-05 (stable -- all based on existing codebase, no external dependency changes)
