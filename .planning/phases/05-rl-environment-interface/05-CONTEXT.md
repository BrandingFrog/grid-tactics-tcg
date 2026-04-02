# Phase 5: RL Environment Interface - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Gymnasium-compatible environment wrapper around the game engine. Converts game state to numerical observations, maps the combinatorial action space to discrete integers with binary masking, and validates with 10,000 random episodes. This phase does NOT include training (Phase 6) or PettingZoo AEC (Phase 7).

</domain>

<decisions>
## Implementation Decisions

### Observation Encoding
- **D-01:** Flat 1D numpy array observation — API-ready format that can also serve stats dashboards and web APIs
- **D-02:** Hidden information: opponent's hand contents and deck contents are NOT visible. Board state, HP, mana, and deck/hand sizes for both players ARE visible.
- **D-03:** Observation should be structured/documented well enough to deserialize for stats APIs (field offsets documented)

### Action Space
- **D-04:** Flat discrete action space — enumerate all possible (action_type, param1, param2) combos into integers
- **D-05:** Binary action mask marks illegal actions as unavailable (for MaskablePPO from sb3-contrib)
- **D-06:** Action encoding/decoding must be deterministic and documented

### Environment Interface
- **D-07:** Gymnasium-compatible: reset(), step(), observation_space, action_space
- **D-08:** 10,000 random episodes must complete without errors
- **D-09:** Step returns (observation, reward, terminated, truncated, info) per Gymnasium API

### Claude's Discretion
- Exact observation vector layout and feature count
- Action space size and encoding scheme
- Reward signal design (win/loss at minimum, potential shaping)
- Whether to use gymnasium.Env directly or a wrapper pattern
- Network architecture hints in observation space (flat vs Box)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — RL focus, core value, tech stack
- `.planning/REQUIREMENTS.md` — RL-01 (Gymnasium env), RL-02 (observation encoding), RL-03 (action space + masking)
- `.planning/research/STACK.md` — Stable-Baselines3 MaskablePPO, PettingZoo AEC, numpy
- `.planning/research/ARCHITECTURE.md` — Four-layer architecture, observation/action design
- `.planning/research/PITFALLS.md` — Hidden info leakage, action space explosion, observation encoding

### Game Engine Code (upstream)
- `src/grid_tactics/game_state.py` — GameState to convert to observations
- `src/grid_tactics/game_loop.py` — run_game() pattern to follow
- `src/grid_tactics/legal_actions.py` — legal_actions() for action masking
- `src/grid_tactics/actions.py` — Action dataclass to map to/from integers
- `src/grid_tactics/action_resolver.py` — resolve_action() called by step()
- `src/grid_tactics/card_library.py` — CardLibrary for card lookups
- `src/grid_tactics/minion.py` — MinionInstance for board encoding
- `src/grid_tactics/enums.py` — ActionType, CardType, Attribute enums

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `legal_actions()` returns all valid Action objects — convert to action mask
- `resolve_action()` applies action and returns new GameState — use in step()
- `GameState.new_game()` creates initial state — use in reset()
- `GameState.is_game_over`, `GameState.winner` — for terminated signal
- `GameResult` — pattern for episode results
- `CardLibrary` — needed for card definition lookups during encoding

### Established Patterns
- Frozen dataclasses for state
- Deterministic RNG via GameRNG
- All game logic is pure functions (state in, state out)

### Integration Points
- Environment wraps GameState + GameRNG + CardLibrary
- step() calls resolve_action() which may trigger react stack
- observation must handle both ACTION and REACT phases
- Action mask must align with the integer encoding

</code_context>

<specifics>
## Specific Ideas

- User wants the observation encoding to be API-ready — documented field offsets, clean structure that a web API could deserialize and serve to stats dashboards
- This is the bridge between the game engine and RL training — getting it right prevents retraining later

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 05-rl-environment-interface*
*Context gathered: 2026-04-02*
