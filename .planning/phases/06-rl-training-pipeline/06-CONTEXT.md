# Phase 6: RL Training Pipeline - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

MaskablePPO training via sb3-contrib, self-play loop with checkpoint saving, reward shaping with intermediate signals, SQLite persistence for game results and training metadata. This phase delivers the first trained RL agent and the data pipeline that feeds the stats dashboard (Phase 9).

</domain>

<decisions>
## Implementation Decisions

### Training
- **D-01:** MaskablePPO from sb3-contrib for training (decided in project setup)
- **D-02:** Self-play: both sides controlled by RL agents, periodic checkpoint saving
- **D-03:** Agent should beat random play convincingly after training

### Reward Shaping
- **D-04:** Potential-based reward shaping with intermediate signals: damage dealt, board control, mana efficiency
- **D-05:** Base reward: +1 win, -1 loss, 0 ongoing (already implemented in Phase 5)
- **D-06:** Shaping must use potential-based formulation to preserve optimal policy

### Data Persistence
- **D-07:** SQLite database for game results: winner, scores, deck compositions, game length, card actions
- **D-08:** Training run metadata: hyperparameters, timestamps, episode counts, win rates over time
- **D-09:** Data must be queryable for the stats dashboard (Phase 9 will read from SQLite)

### Claude's Discretion
- MaskablePPO hyperparameters (learning rate, batch size, n_steps, etc.)
- Self-play implementation (vs frozen opponent, vs latest, vs pool)
- SQLite schema design
- Checkpoint frequency
- Training duration for initial validation
- Reward shaping weights and potential function design

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Context
- `.planning/PROJECT.md` — RL focus, core value
- `.planning/REQUIREMENTS.md` — RL-04 (MaskablePPO), RL-05 (self-play), RL-06 (reward shaping), DATA-01 (SQLite), DATA-02 (training metadata)
- `.planning/research/STACK.md` — SB3 MaskablePPO, SQLite, TensorBoard
- `.planning/research/ARCHITECTURE.md` — Training pipeline layer
- `.planning/research/PITFALLS.md` — Self-play collapse, reward hacking

### Phase 5 Code (upstream)
- `src/grid_tactics/rl/env.py` — GridTacticsEnv (Gymnasium wrapper)
- `src/grid_tactics/rl/observation.py` — encode_observation()
- `src/grid_tactics/rl/action_space.py` — ActionEncoder, build_action_mask()
- `src/grid_tactics/rl/reward.py` — compute_reward() (base sparse signal)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `GridTacticsEnv` — ready for MaskablePPO training
- `compute_reward()` — base +1/-1/0, extend with shaping
- `CardLibrary` — for deck building in self-play
- `GameResult` — pattern for structured results
- `GameRNG` — deterministic seeds for reproducible training

### Integration Points
- MaskablePPO wraps GridTacticsEnv
- Self-play needs to set opponent policy in the environment
- SQLite writes happen after each game episode
- Training metadata logged per training run

</code_context>

<specifics>
## Specific Ideas

- This is where stats start appearing — win rates, card usage, training curves
- SQLite schema should be designed with the Phase 9 dashboard in mind
- User wants API-ready data (from Phase 5 context)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-rl-training-pipeline*
*Context gathered: 2026-04-02*
