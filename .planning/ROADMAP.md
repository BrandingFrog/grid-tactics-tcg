# Roadmap: Grid Tactics TCG

## Overview

This roadmap builds Grid Tactics TCG from the ground up: first a correct, deterministic game engine (Phases 1-4), then an RL training pipeline layered on top (Phases 5-7), then card expansion with RL-driven balance analysis (Phase 8), and finally an analytics dashboard for visualizing results (Phases 9-10). Each phase delivers a verifiable capability. The game engine is built in four incremental slices (state, cards, actions, game loop) rather than as a monolith, because RL agents will exploit every rule gap -- each slice gets tested before the next depends on it. The RL layer is split into environment interface, training pipeline, and self-play robustness to isolate observation/action design from training infrastructure from multi-agent dynamics.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Game State Foundation** - 5x5 grid, mana system, deterministic RNG, and core state representation
- [ ] **Phase 2: Card System & Types** - Data-driven card definitions, three card types, multi-purpose cards, and starter pool
- [ ] **Phase 3: Turn Actions & Combat** - Action-per-turn system, movement, melee/ranged combat, drawing, and legal action enumeration
- [ ] **Phase 4: Win Condition & Game Loop** - Sacrifice-to-damage mechanic, HP tracking, win detection, and complete playable games
- [ ] **Phase 5: RL Environment Interface** - Gymnasium/PettingZoo wrapper, observation encoding, action space with masking
- [ ] **Phase 6: RL Training Pipeline** - MaskablePPO training, self-play loop, reward shaping, and data persistence
- [ ] **Phase 7: Self-Play Robustness** - PettingZoo AEC for react window modeling, agent pool, and league-based training
- [ ] **Phase 8: Card Expansion & Balance** - Expanded 20-30 card pool and automated RL-driven balance sweep
- [ ] **Phase 9: Analytics Dashboard Core** - Streamlit dashboard with win rates, card statistics, and training metrics
- [ ] **Phase 10: Replay & Balance Visualization** - Game replay viewer with step-by-step playback and balance heatmaps

## Phase Details

### Phase 1: Game State Foundation
**Goal**: A correct, immutable game state representation exists for the 5x5 grid with mana banking and deterministic reproducibility
**Depends on**: Nothing (first phase)
**Requirements**: ENG-01, ENG-02, ENG-11
**Success Criteria** (what must be TRUE):
  1. A GameState object represents the full 5x5 grid with row ownership (2 rows per player, 1 middle row) and tracks all positions
  2. Mana pool regenerates +1 per turn and unspent mana carries over between turns
  3. Two games initialized with the same seed produce identical state sequences
  4. GameState is immutable -- applying an action returns a new state without modifying the original
**Plans:** 4 plans
Plans:
- [x] 01-01-PLAN.md -- Project scaffolding, enums, types, and test infrastructure
- [x] 01-02-PLAN.md -- Board dataclass with 5x5 grid geometry and adjacency helpers
- [x] 01-03-PLAN.md -- Player dataclass with mana system and hand management
- [x] 01-04-PLAN.md -- GameState, deterministic RNG, validation, and integration tests

### Phase 2: Card System & Types
**Goal**: Cards are defined as data (not hardcoded), all three card types work, and a starter pool of 15-20 unique cards exists for testing
**Depends on**: Phase 1
**Requirements**: ENG-04, ENG-05, ENG-12, CARD-01, CARD-02
**Success Criteria** (what must be TRUE):
  1. Card definitions are loaded from JSON files with stats, effects, and keywords interpreted at runtime
  2. Minion cards have Attack, Health, Mana Cost, Range, and optional Effects
  3. Magic cards resolve immediate effects (damage, heal, buff) when played
  4. A Minion card with a React effect can be played from hand as either a deployment or a counter
  5. A starter pool of 15-20 unique cards exists covering all three card types
**Plans:** 2 plans
Plans:
- [x] 02-01-PLAN.md -- Card enums, type constants, EffectDefinition and CardDefinition dataclasses
- [x] 02-02-PLAN.md -- CardLoader, CardLibrary, 18 starter card JSON files, deck validation

### Phase 3: Turn Actions & Combat
**Goal**: Players can take actions (play cards, move minions, attack, draw) with correct rule enforcement and the system can enumerate all legal actions from any state
**Depends on**: Phase 2
**Requirements**: ENG-03, ENG-06, ENG-08, ENG-10
**Success Criteria** (what must be TRUE):
  1. Each turn consists of exactly one action followed by an opponent react window
  2. Minions move in all 4 directions (up/down/left/right), melee units attack adjacent targets (orthogonal), ranged units attack up to 2 tiles orthogonally or 1 tile diagonally
  3. Drawing a card costs an action (with a configurable flag for auto-draw variant)
  4. Given any game state, legal_actions() returns the complete set of valid actions with no illegal actions included
**Plans:** 3 plans
Plans:
- [ ] 03-01-PLAN.md -- MinionInstance, ActionType enum, Action dataclass, GameState extension with minion/react fields
- [ ] 03-02-PLAN.md -- Effect resolution engine and action resolver (deploy, move, attack, draw, pass, combat)
- [ ] 03-03-PLAN.md -- React window stack with LIFO chaining, legal_actions() enumeration, integration tests

### Phase 4: Win Condition & Game Loop
**Goal**: Complete games can be played from start to finish between two agents (random or scripted) with correct win detection
**Depends on**: Phase 3
**Requirements**: ENG-07, ENG-09
**Success Criteria** (what must be TRUE):
  1. A minion that reaches the opponent's back row can sacrifice itself, dealing its Attack value as player damage
  2. The game correctly detects when a player's HP reaches zero and declares a winner
  3. A random-agent smoke test runs 1000+ complete games without crashes, hangs, or invalid states
**Plans**: TBD

### Phase 5: RL Environment Interface
**Goal**: The game engine is wrapped in a standard RL environment that an agent can train against
**Depends on**: Phase 4
**Requirements**: RL-01, RL-02, RL-03
**Success Criteria** (what must be TRUE):
  1. A Gymnasium-compatible environment exposes reset(), step(), observation_space, and action_space
  2. Board state (5x5 grid with unit stats), hand, mana, and HP are encoded as fixed-size numerical tensors with no information leakage of opponent's hidden state
  3. All possible actions map to a discrete action space with a binary mask that marks illegal actions as unavailable
  4. A random agent can play 10,000 episodes through the environment wrapper without errors
**Plans**: TBD

### Phase 6: RL Training Pipeline
**Goal**: An RL agent trains via self-play and learns to beat random play convincingly, with all results persisted for analysis
**Depends on**: Phase 5
**Requirements**: RL-04, RL-05, RL-06, DATA-01, DATA-02
**Success Criteria** (what must be TRUE):
  1. MaskablePPO from sb3-contrib trains against the environment and loss curves show convergence
  2. A self-play training loop runs where both sides are RL-controlled, with periodic checkpoint saving
  3. Reward shaping provides intermediate signals (damage dealt, board control, mana efficiency) using potential-based shaping
  4. Game results (winner, scores, deck compositions, game length, card actions) are persisted to SQLite
  5. Training run metadata is stored and queryable for experiment comparison
**Plans**: TBD

### Phase 7: Self-Play Robustness
**Goal**: The training pipeline handles the React interrupt mechanic correctly and resists strategy cycling through agent diversity
**Depends on**: Phase 6
**Requirements**: RL-07, RL-08
**Success Criteria** (what must be TRUE):
  1. A PettingZoo AEC environment correctly models the React window as alternating agent turns with restricted action sets (react cards + pass only)
  2. An agent pool stores historical checkpoints and samples opponents with diversity (latest, recent, historical mix)
  3. Training with the agent pool produces stable Elo progression without cycling back to previously abandoned strategies
**Plans**: TBD

### Phase 8: Card Expansion & Balance
**Goal**: The card pool grows to 20-30 cards and RL-driven analysis identifies which cards are overpowered or underpowered
**Depends on**: Phase 7
**Requirements**: CARD-03, CARD-04
**Success Criteria** (what must be TRUE):
  1. An expanded pool of 20-30 cards with varied effects exists and RL training converges with the larger pool
  2. An automated balance sweep varies card stats (attack, health, cost) and re-runs RL to identify balanced configurations
  3. Per-card win rate and usage data is available from training runs to identify outliers
**Plans**: TBD

### Phase 9: Analytics Dashboard Core
**Goal**: A web dashboard displays RL training results, win rates, card statistics, and training metrics
**Depends on**: Phase 6
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-06
**Success Criteria** (what must be TRUE):
  1. A Streamlit web dashboard launches and displays data from the SQLite database
  2. Win rate charts show performance per agent and per deck composition over configurable time windows
  3. Card usage statistics show play frequency, win correlation, and effectiveness per card
  4. Training metrics (loss curves, reward trends, episode lengths) are displayed with interactive charts
**Plans**: TBD
**UI hint**: yes

### Phase 10: Replay & Balance Visualization
**Goal**: Users can replay AI games step-by-step and see visual balance analysis of the card pool
**Depends on**: Phase 9, Phase 8
**Requirements**: DASH-04, DASH-05
**Success Criteria** (what must be TRUE):
  1. A game replay viewer shows step-by-step playback of AI vs AI matches with board state and decision annotations
  2. Balance heatmaps visualize card power rankings, showing which cards are overpowered or underpowered
  3. Balance data updates automatically as new training runs complete
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10
Note: Phase 9 depends on Phase 6 (not 8), so Phases 8 and 9 could run in parallel if desired.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Game State Foundation | 4/4 | Complete | 2026-04-02 |
| 2. Card System & Types | 2/2 | Complete | 2026-04-02 |
| 3. Turn Actions & Combat | 0/3 | Planned | - |
| 4. Win Condition & Game Loop | 0/TBD | Not started | - |
| 5. RL Environment Interface | 0/TBD | Not started | - |
| 6. RL Training Pipeline | 0/TBD | Not started | - |
| 7. Self-Play Robustness | 0/TBD | Not started | - |
| 8. Card Expansion & Balance | 0/TBD | Not started | - |
| 9. Analytics Dashboard Core | 0/TBD | Not started | - |
| 10. Replay & Balance Visualization | 0/TBD | Not started | - |
