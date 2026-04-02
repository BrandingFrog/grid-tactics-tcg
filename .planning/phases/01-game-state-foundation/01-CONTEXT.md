# Phase 1: Game State Foundation - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Core game state representation: immutable GameState for a 5x5 grid with row ownership, mana system with banking, and deterministic seeded RNG. This phase delivers the data model — no game logic, card types, or actions (those are Phases 2-4).

</domain>

<decisions>
## Implementation Decisions

### Grid Representation
- **D-01:** Fixed row assignment: Rows 0-1 = Player 1, Row 2 = No-man's-land, Rows 3-4 = Player 2
- **D-02:** All 5 columns are equal — no special column rules or bonuses
- **D-03:** One minion per space — no stacking allowed, must move around blockers
- **D-04:** Minions can move in all 4 directions (up, down, left, right) — movement logic is Phase 3 but the grid must support adjacency queries in all directions plus diagonal for ranged attacks

### Mana System
- **D-05:** Starting mana pool = 1
- **D-06:** Mana regenerates +1 per turn
- **D-07:** Maximum mana pool cap = 10
- **D-08:** Unspent mana carries over between turns (banking) up to the cap

### Player Setup
- **D-09:** Starting HP = 20 per player
- **D-10:** Starting hand size = 5 cards
- **D-11:** Deck size = 40+ cards (enforced at deck validation, not in game state)

### Claude's Discretion
- First-turn advantage balancing (e.g., first player skips first action, or draws one fewer card) — RL can test variants
- State immutability approach (deep copy vs structural sharing vs action log) — pick what's best for RL training throughput
- Serialization format (Python dict, JSON, or hybrid) — pick what's most practical for both speed and replay

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external specs — requirements fully captured in decisions above and in the following project docs:

### Project Context
- `.planning/PROJECT.md` — Game mechanics, core value (RL engine), card types, board layout
- `.planning/REQUIREMENTS.md` — ENG-01 (5x5 grid), ENG-02 (mana banking), ENG-11 (deterministic RNG)
- `.planning/research/ARCHITECTURE.md` — Four-layer architecture, immutable GameState pattern, component boundaries
- `.planning/research/PITFALLS.md` — Game engine bug risks, state/observation separation, deterministic RNG importance

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield project, no existing code

### Established Patterns
- None yet — this phase establishes the foundational patterns

### Integration Points
- GameState will be consumed by Phase 2 (card system), Phase 3 (actions/combat), Phase 5 (RL environment wrapper)
- Immutability and serialization design directly impacts RL training throughput (millions of state copies)
- Deterministic RNG seed must propagate through all future phases for reproducibility

</code_context>

<specifics>
## Specific Ideas

- Ranged attacks need diagonal adjacency support (1 tile diagonal = in range for ranged units) — grid must expose distance/adjacency helpers that account for this
- Research recommends separating GameState (full truth) from PlayerObservation (what one player can see) from the start to prevent hidden information leakage in RL

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-game-state-foundation*
*Context gathered: 2026-04-02*
