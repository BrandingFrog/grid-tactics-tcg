# Requirements: Grid Tactics TCG

**Defined:** 2026-04-02
**Core Value:** The reinforcement learning engine that discovers and validates game strategies

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Game Engine

- [x] **ENG-01**: Game enforces complete rule set on a 5x5 grid with row ownership, no-man's-land middle row, and deployment zones
- [x] **ENG-02**: Mana pool regenerates +1 per turn with unspent mana carrying over (banking)
- [ ] **ENG-03**: Each turn consists of a single action (play card, move minion, attack, draw) followed by an opponent react window
- [x] **ENG-04**: Three card types supported: Minion (deployed to field), Magic (immediate effect), React (counter/interrupt during opponent's action)
- [x] **ENG-05**: Minions have Attack, Health, Mana Cost, Range, and optional Effects/React effects
- [ ] **ENG-06**: Minions move in all 4 directions (up, down, left, right) as an action; melee attacks adjacent targets (orthogonal); ranged units attack up to 2 tiles orthogonally or 1 tile diagonally
- [ ] **ENG-07**: Minions that reach the opponent's back row can sacrifice to deal their Attack value as player damage
- [ ] **ENG-08**: Drawing a card costs an action (configurable rule to allow RL testing of auto-draw variant)
- [ ] **ENG-09**: Game correctly detects win condition when a player's HP reaches zero
- [ ] **ENG-10**: Legal action enumeration returns all valid actions from any game state
- [x] **ENG-11**: Deterministic seeded RNG ensures reproducible game outcomes for debugging and replay
- [x] **ENG-12**: Multi-purpose cards supported (e.g., a Minion card that also has a React effect playable from hand)

### RL Integration

- [ ] **RL-01**: Gymnasium-compatible environment with reset(), step(), observation_space, and action_space
- [ ] **RL-02**: State observation encoding converts board (5x5 grid with unit stats), hand, mana, HP into fixed-size numerical tensors
- [ ] **RL-03**: Action space definition maps all possible actions into a discrete space with binary action masking for illegal actions
- [ ] **RL-04**: MaskablePPO training via Stable-Baselines3 sb3-contrib
- [ ] **RL-05**: Self-play training loop where both players are controlled by RL agents
- [ ] **RL-06**: Reward shaping with intermediate signals (damage dealt, board control, mana efficiency) using potential-based shaping
- [ ] **RL-07**: PettingZoo AEC environment wrapper modeling the react window as alternating agent turns with restricted action sets
- [ ] **RL-08**: Agent pool / league-based self-play to prevent strategy cycling and collapse

### Analytics Dashboard

- [ ] **DASH-01**: Web-based stats dashboard (Streamlit) displaying RL training results
- [ ] **DASH-02**: Win rate tracking per agent, per deck composition, over time windows
- [ ] **DASH-03**: Card usage statistics showing play frequency, win correlation, and effectiveness per card
- [ ] **DASH-04**: Game replay viewer with step-by-step playback of AI vs AI matches showing board state and decisions
- [ ] **DASH-05**: Balance heatmaps and card power rankings visualizing overpowered/underpowered cards
- [ ] **DASH-06**: Training metrics display (loss curves, reward trends, episode lengths)

### Card System

- [ ] **CARD-01**: Data-driven card definitions in JSON/YAML with stats, effects, and keywords interpreted at runtime
- [ ] **CARD-02**: Starter card pool of 5-10 simple cards for initial RL validation
- [ ] **CARD-03**: Expanded card pool of 20-30 cards with varied effects for balance testing
- [ ] **CARD-04**: Automated balance sweep varying card stats (attack, health, cost) and re-running RL to find balanced configurations

### Data Storage

- [ ] **DATA-01**: Game results persisted to SQLite database (winner, scores, deck compositions, game length, card actions)
- [ ] **DATA-02**: Training run metadata stored for comparison across experiments

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced RL

- **ARL-01**: Vectorized/parallel environment execution for 10x+ training speedup
- **ARL-02**: Curriculum learning starting with simplified scenarios and increasing complexity
- **ARL-03**: Opponent modeling with recurrent policies (LSTM/GRU) for in-game adaptation
- **ARL-04**: Meta-strategy discovery with archetype clustering and matchup matrices
- **ARL-05**: Deck composition explorer showing strongest card combinations as archetypes

### User Experience

- **UX-01**: Human-playable interface to play against trained RL agent
- **UX-02**: Deck builder UI for constructing and testing custom decks

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Visual card art / polished graphics | Focus is on RL mechanics, not aesthetics |
| Multiplayer networking / online play | All games run locally (AI vs AI) |
| Card trading / collection economy | Not relevant to RL strategy testing |
| Mobile app | Desktop/web dashboard only |
| Real-time combat | Game is turn-based by design; real-time changes the RL problem fundamentally |
| Complex card effect scripting language | Start with Python functions; data-driven is sufficient |
| Tournament bracket system | Round-robin matchups and Elo from results suffice |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENG-01 | Phase 1 | Complete |
| ENG-02 | Phase 1 | Complete |
| ENG-03 | Phase 3 | Pending |
| ENG-04 | Phase 2 | Complete |
| ENG-05 | Phase 2 | Complete |
| ENG-06 | Phase 3 | Pending |
| ENG-07 | Phase 4 | Pending |
| ENG-08 | Phase 3 | Pending |
| ENG-09 | Phase 4 | Pending |
| ENG-10 | Phase 3 | Pending |
| ENG-11 | Phase 1 | Complete |
| ENG-12 | Phase 2 | Complete |
| RL-01 | Phase 5 | Pending |
| RL-02 | Phase 5 | Pending |
| RL-03 | Phase 5 | Pending |
| RL-04 | Phase 6 | Pending |
| RL-05 | Phase 6 | Pending |
| RL-06 | Phase 6 | Pending |
| RL-07 | Phase 7 | Pending |
| RL-08 | Phase 7 | Pending |
| DASH-01 | Phase 9 | Pending |
| DASH-02 | Phase 9 | Pending |
| DASH-03 | Phase 9 | Pending |
| DASH-04 | Phase 10 | Pending |
| DASH-05 | Phase 10 | Pending |
| DASH-06 | Phase 9 | Pending |
| CARD-01 | Phase 2 | Pending |
| CARD-02 | Phase 2 | Pending |
| CARD-03 | Phase 8 | Pending |
| CARD-04 | Phase 8 | Pending |
| DATA-01 | Phase 6 | Pending |
| DATA-02 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 32 total
- Mapped to phases: 32
- Unmapped: 0

---
*Requirements defined: 2026-04-02*
*Last updated: 2026-04-02 after roadmap creation*
