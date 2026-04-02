# Phase 3: Turn Actions & Combat - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Action system for the card game: play card (deploy minion or cast magic), move minion, attack, draw card, and pass. Includes the react window with full-stack chaining, combat resolution with simultaneous damage, and legal action enumeration from any game state. This phase makes the game mechanically playable — win condition and game loop are Phase 4.

</domain>

<decisions>
## Implementation Decisions

### Combat Resolution
- **D-01:** Damage is simultaneous — both attacker and defender deal damage at the same time; both can die
- **D-02:** Dead minions (health <= 0) are removed at end of action, not immediately — on_death effects all trigger together after damage resolves
- **D-03:** Melee units attack orthogonally adjacent targets; ranged units attack up to 2 tiles orthogonally or 1 tile diagonally (carried forward from PROJECT.md)

### React Window
- **D-04:** One react card per player per "level" of the stack
- **D-05:** Full stack chaining: Player A acts → Player B plays 1 react → Player A can counter-react → Player B can counter that → etc., until someone passes
- **D-06:** Stack resolves last-in-first-out (most recent react resolves first, then the one before it, etc.)
- **D-07:** Passing at any level means that player's chain ends — remaining stack resolves

### Card Play Mechanics
- **D-08:** Melee minions can deploy to any empty space in the player's friendly rows (rows 0-1 for P1, rows 3-4 for P2)
- **D-09:** Ranged minions must deploy to the back row only (row 0 for P1, row 4 for P2) — forces ranged behind front line
- **D-10:** Single-target Magic/effects require player to choose a target; area effects (all_enemies, adjacent) auto-resolve
- **D-11:** Playing a card costs mana equal to its mana_cost; insufficient mana = illegal action

### Turn Structure
- **D-12:** One action per turn: play card, move minion, attack with minion, draw card, or pass
- **D-13:** After action, react window opens (see D-04 through D-07)
- **D-14:** After react window closes, turn passes to the other player
- **D-15:** Drawing a card costs an action (configurable flag for auto-draw variant)
- **D-16:** Pass is always a valid action — critical for mana banking strategy

### Action Representation
- **D-17:** Actions are structured tuples (type, card_id/minion_id, position, target) internally — not just flat ints
- **D-18:** Structured actions can be mapped to flat integer IDs for RL (Phase 5), but the internal representation stays structured for clarity and future Roblox/Lua port
- **D-19:** legal_actions() returns the complete set of valid structured actions from any game state with no illegal actions included

### Claude's Discretion
- Effect resolution order when multiple effects trigger simultaneously (e.g., two on_death effects)
- Exact action tuple format and enum values for action types
- How card instances on the field track current health vs card definition health
- Whether attacking costs the minion its movement for that turn (or if attack IS the action)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — Game mechanics, turn structure, movement, range, sacrifice mechanic
- `.planning/REQUIREMENTS.md` — ENG-03 (action-per-turn + react), ENG-06 (movement + combat), ENG-08 (draw costs action), ENG-10 (legal action enumeration)
- `.planning/research/ARCHITECTURE.md` — Four-layer architecture, action-produces-new-state pattern
- `.planning/research/PITFALLS.md` — Action masking, legal action enumeration pitfalls

### Phase 1-2 Code (upstream dependencies)
- `src/grid_tactics/game_state.py` — GameState frozen dataclass (action must return new GameState)
- `src/grid_tactics/board.py` — Board with placement, removal, adjacency, distance helpers
- `src/grid_tactics/player.py` — Player with mana spending, hand management, HP/damage
- `src/grid_tactics/cards.py` — CardDefinition with effects, multi-purpose cards
- `src/grid_tactics/card_library.py` — CardLibrary for looking up card definitions by ID
- `src/grid_tactics/enums.py` — All enums (CardType, EffectType, TriggerType, TargetType)

### External Reference
- YGOPro/EDOPro Lua card scripting (https://github.com/Fluorohydride/ygopro) — reference for per-card effect structure, eventual Roblox/Lua port target

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Board.get_orthogonal_adjacent()`, `get_diagonal_adjacent()`, `get_all_adjacent()` — for attack range calculation
- `Board.manhattan_distance()`, `chebyshev_distance()` — for range checking
- `Board.place()`, `Board.remove()` — for deploying/removing minions
- `Player.spend_mana()`, `Player.draw_card()`, `Player.take_damage()` — all return new Player (immutable)
- `Player.regenerate_mana()` — for turn transitions
- `GameState.active_player`, `GameState.inactive_player` — for turn-based logic
- `CardDefinition.is_multi_purpose` — for dual-mode card play detection
- `EffectDefinition` with trigger/target/type — ready for resolution engine

### Established Patterns
- Frozen dataclasses with tuple collections — actions must return new state objects
- `dataclasses.replace()` for producing modified copies
- `__post_init__` for validation
- Comprehensive TDD (tests first, then implementation)

### Integration Points
- New action system must return `GameState` (immutable, new state per action)
- Card instances on the field need a way to track current HP separate from CardDefinition base HP
- `legal_actions()` must be computable from GameState alone (no side state)
- React window modifies turn flow — may need TurnPhase enum extended or a react-stack state

</code_context>

<specifics>
## Specific Ideas

- User plans to eventually port the game to Roblox with per-card Lua scripts (like YGOPro/EDOPro), so action/effect structure should be clean and portable
- The per-card JSON files already align with this goal — effects are declarative data, not Python functions
- React stack chaining adds complexity but is core to the game's identity — RL will need to learn when to counter vs pass

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-turn-actions-combat*
*Context gathered: 2026-04-02*
