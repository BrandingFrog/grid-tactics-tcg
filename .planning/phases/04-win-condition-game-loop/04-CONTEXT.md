# Phase 4: Win Condition & Game Loop - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Sacrifice-to-damage mechanic, win/draw detection, and a complete game loop that plays full games between two random agents. This phase completes the game engine — after this, full games run start to finish.

</domain>

<decisions>
## Implementation Decisions

### Sacrifice Mechanic
- **D-01:** Sacrifice is an action — the player moves a minion "off the board" past the opponent's back row
- **D-02:** The minion is removed from the board and deals its current attack value as damage to the opponent's HP
- **D-03:** The minion must be on the opponent's back row to sacrifice (P1's minion on row 4, P2's minion on row 0)
- **D-04:** Sacrifice should appear in legal_actions() as a SACRIFICE action type when a minion is eligible

### Win/Draw Detection
- **D-05:** Game ends when any player's HP reaches 0 (checked after each action resolves and after react stack resolves)
- **D-06:** If both players reach 0 HP simultaneously (e.g., from simultaneous combat), the game is a draw
- **D-07:** Active player dealing the final sacrifice blow while their own HP is >0 = active player wins

### Game Loop
- **D-08:** Game loop runs a complete game: initialize state → alternate turns → detect win/draw → return result
- **D-09:** Random agent selects uniformly from legal_actions() at each decision point (including react windows)
- **D-10:** Smoke test: 1000+ complete games without crashes, hangs, or invalid states
- **D-11:** Turn limit (configurable, e.g., 200 turns) to prevent infinite games — draw if reached

### Claude's Discretion
- Game result data structure (winner, turn count, final HP, etc.)
- Whether to add deck-out as a loss condition or draw condition (when a player can't draw)
- Random agent implementation details
- Turn limit default value

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Sacrifice mechanic description, 20 HP, game flow
- `.planning/REQUIREMENTS.md` — ENG-07 (sacrifice-to-damage), ENG-09 (win detection)

### Phase 3 Code (upstream)
- `src/grid_tactics/action_resolver.py` — resolve_action() to extend with SACRIFICE
- `src/grid_tactics/legal_actions.py` — legal_actions() to extend with SACRIFICE enumeration
- `src/grid_tactics/actions.py` — Action dataclass, may need SACRIFICE ActionType
- `src/grid_tactics/enums.py` — ActionType enum to extend
- `src/grid_tactics/game_state.py` — GameState for win/draw checking
- `src/grid_tactics/minion.py` — MinionInstance for position/attack access

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `action_resolver.resolve_action()` — extend with SACRIFICE case
- `legal_actions._action_phase_actions()` — extend with sacrifice enumeration
- `Player.take_damage()` — already returns new Player with reduced HP
- `Player.is_alive` — already checks HP > 0
- `Board.remove()` — removes minion from grid
- `GameState.get_minion_at()`, `GameState.get_minions_for_player()` — find eligible minions

### Established Patterns
- ActionType enum + Action dataclass for new action types
- resolve_action dispatches on action_type
- legal_actions enumerates by checking board state

### Integration Points
- New SACRIFICE action type in enums.py
- sacrifice_action() convenience constructor in actions.py
- _resolve_sacrifice() handler in action_resolver.py
- Sacrifice enumeration in legal_actions.py
- Game loop as a new module (game_loop.py or similar)

</code_context>

<specifics>
## Specific Ideas

- The sacrifice action is conceptually "move off the board" — the minion steps past the edge, gets removed, and damages the opponent
- 1000+ random games is the key validation that the entire engine works correctly end-to-end

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-win-condition-game-loop*
*Context gathered: 2026-04-02*
