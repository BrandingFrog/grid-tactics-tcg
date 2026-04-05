# Requirements: Grid Tactics TCG

**Defined:** 2026-04-02
**Core Value:** The reinforcement learning engine that discovers and validates game strategies

## v1.1 Requirements — Online PvP Dueling

Requirements for online PvP dueling milestone. Each maps to roadmap phases.

### Server & Networking

- [x] **SERVER-01**: User can create a new game room and receive a shareable room code
- [x] **SERVER-02**: User can join an existing game room by entering a room code
- [ ] **SERVER-03**: Both players receive real-time state updates after each action resolves

### Game State & Security

- [x] **VIEW-01**: User can only see their own hand and deck count — opponent's hand contents and deck order are hidden
- [ ] **VIEW-02**: Server validates all actions against legal_actions() before applying — illegal actions are rejected
- [ ] **VIEW-03**: User receives their legal actions list with every state update

### Game Board UI

- [ ] **UI-01**: User can see the 5x5 grid with minions showing name, ATK/HP, owner, and attribute
- [ ] **UI-02**: User can see their hand with card details (name, mana cost, ATK/HP, effects, attribute) and unplayable cards dimmed
- [ ] **UI-03**: User can see both players' current mana and HP
- [ ] **UI-04**: User can see whose turn it is and the current phase (ACTION vs REACT)

### Gameplay Interaction

- [ ] **PLAY-01**: User can submit an action by clicking cards and board positions, with valid targets highlighted
- [ ] **PLAY-02**: User can see the pending action during react window and choose to play a react card or pass
- [ ] **PLAY-03**: User sees a game over screen with victory/defeat result and final HP when the game ends

### Polish & Resilience

- [ ] **POLISH-01**: User can reconnect within 60 seconds after disconnecting and resume the game with full state restored
- [ ] **POLISH-02**: User can see a scrollable game log showing action history
- [ ] **POLISH-03**: User can click "Rematch" after game ends to start a new game in the same room

## v1.0 Requirements (Completed)

### Game Engine

- [x] **ENG-01**: Game enforces complete rule set on a 5x5 grid with row ownership, no-man's-land middle row, and deployment zones
- [x] **ENG-02**: Mana pool regenerates +1 per turn with unspent mana carrying over (banking)
- [x] **ENG-03**: Each turn consists of a single action (play card, move minion, attack, draw) followed by an opponent react window
- [x] **ENG-04**: Three card types supported: Minion (deployed to field), Magic (immediate effect), React (counter/interrupt during opponent's action)
- [x] **ENG-05**: Minions have Attack, Health, Mana Cost, Range, and optional Effects/React effects
- [x] **ENG-06**: Minions move in all 4 directions (up, down, left, right) as an action; melee attacks adjacent targets (orthogonal); ranged units attack up to 2 tiles orthogonally or 1 tile diagonally
- [x] **ENG-07**: Minions that reach the opponent's back row can sacrifice to deal their Attack value as player damage
- [x] **ENG-08**: Drawing a card costs an action (configurable rule to allow RL testing of auto-draw variant)
- [x] **ENG-09**: Game correctly detects win condition when a player's HP reaches zero
- [x] **ENG-10**: Legal action enumeration returns all valid actions from any game state
- [x] **ENG-11**: Deterministic seeded RNG ensures reproducible game outcomes for debugging and replay
- [x] **ENG-12**: Multi-purpose cards supported (e.g., a Minion card that also has a React effect playable from hand)

### RL Integration

- [x] **RL-01**: Gymnasium-compatible environment with reset(), step(), observation_space, and action_space
- [x] **RL-02**: State observation encoding converts board (5x5 grid with unit stats), hand, mana, HP into fixed-size numerical tensors
- [x] **RL-03**: Action space definition maps all possible actions into a discrete space with binary action masking for illegal actions
- [ ] **RL-04**: MaskablePPO training via Stable-Baselines3 sb3-contrib
- [x] **RL-05**: Self-play training loop where both players are controlled by RL agents
- [x] **RL-06**: Reward shaping with intermediate signals (damage dealt, board control, mana efficiency) using potential-based shaping
- [ ] **RL-07**: PettingZoo AEC environment wrapper modeling the react window as alternating agent turns with restricted action sets
- [ ] **RL-08**: Agent pool / league-based self-play to prevent strategy cycling and collapse

### Card System

- [x] **CARD-01**: Data-driven card definitions in JSON/YAML with stats, effects, and keywords interpreted at runtime
- [x] **CARD-02**: Starter card pool of 5-10 simple cards for initial RL validation
- [ ] **CARD-03**: Expanded card pool of 20-30 cards with varied effects for balance testing
- [ ] **CARD-04**: Automated balance sweep varying card stats (attack, health, cost) and re-running RL to find balanced configurations

### Data Storage

- [x] **DATA-01**: Game results persisted to SQLite database (winner, scores, deck compositions, game length, card actions)
- [x] **DATA-02**: Training run metadata stored for comparison across experiments

## Future Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### Gameplay Enhancements

- **FUTURE-01**: Turn timer with auto-pass (45s action / 20s react)
- **FUTURE-02**: Card play and attack animations
- **FUTURE-03**: Sound effects for actions
- **FUTURE-04**: Spectator mode for third-party viewers

### Advanced RL (from v1.0)

- **ARL-01**: Vectorized/parallel environment execution for 10x+ training speedup
- **ARL-02**: Curriculum learning starting with simplified scenarios and increasing complexity
- **ARL-03**: Opponent modeling with recurrent policies (LSTM/GRU) for in-game adaptation
- **ARL-04**: Meta-strategy discovery with archetype clustering and matchup matrices
- **ARL-05**: Deck composition explorer showing strongest card combinations as archetypes

### User Experience (from v1.0)

- **UX-01**: Human-playable interface to play against trained RL agent
- **UX-02**: Deck builder UI for constructing and testing custom decks

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Matchmaking / ELO ranking | No player base yet. Room codes sufficient for friends. |
| User accounts / authentication | Zero value for friends playing. Anonymous sessions with display names. |
| Deck builder | Only 19 cards. Not enough variety for meaningful deckbuilding. |
| Chat / free text | Moderation burden. Not needed for friends (use Discord). |
| AI opponent in PvP UI | Requires model loading/inference. Separate milestone. |
| Mobile-responsive layout | Desktop-first. Basic viewport meta tag only. |
| Persistent game history | Games are ephemeral. In-memory only. |
| Card art / visual polish | Time sink. Colored borders by attribute, simple type icons. |
| Peer-to-peer networking | Destroys server authority, enables cheating. |
| Visual card art / polished graphics | Focus is on RL mechanics, not aesthetics |
| Card trading / collection economy | Not relevant to RL strategy testing |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

### v1.1 — Online PvP Dueling

| Requirement | Phase | Status |
|-------------|-------|--------|
| SERVER-01 | Phase 11 | Complete |
| SERVER-02 | Phase 11 | Complete |
| SERVER-03 | Phase 12 | Pending |
| VIEW-01 | Phase 12 | Complete |
| VIEW-02 | Phase 12 | Pending |
| VIEW-03 | Phase 12 | Pending |
| UI-01 | Phase 13 | Pending |
| UI-02 | Phase 13 | Pending |
| UI-03 | Phase 13 | Pending |
| UI-04 | Phase 13 | Pending |
| PLAY-01 | Phase 14 | Pending |
| PLAY-02 | Phase 14 | Pending |
| PLAY-03 | Phase 14 | Pending |
| POLISH-01 | Phase 15 | Pending |
| POLISH-02 | Phase 15 | Pending |
| POLISH-03 | Phase 15 | Pending |

### v1.0 — Game Engine & RL (Historical)

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENG-01 | Phase 1 | Complete |
| ENG-02 | Phase 1 | Complete |
| ENG-03 | Phase 3 | Complete |
| ENG-04 | Phase 2 | Complete |
| ENG-05 | Phase 2 | Complete |
| ENG-06 | Phase 3 | Complete |
| ENG-07 | Phase 4 | Complete |
| ENG-08 | Phase 3 | Complete |
| ENG-09 | Phase 4 | Complete |
| ENG-10 | Phase 3 | Complete |
| ENG-11 | Phase 1 | Complete |
| ENG-12 | Phase 2 | Complete |
| RL-01 | Phase 5 | Complete |
| RL-02 | Phase 5 | Complete |
| RL-03 | Phase 5 | Complete |
| RL-04 | Phase 6 | Pending |
| RL-05 | Phase 6 | Complete |
| RL-06 | Phase 6 | Complete |
| RL-07 | Phase 7 | Pending |
| RL-08 | Phase 7 | Pending |
| CARD-01 | Phase 2 | Complete |
| CARD-02 | Phase 2 | Complete |
| CARD-03 | Phase 8 | Pending |
| CARD-04 | Phase 8 | Pending |
| DATA-01 | Phase 6 | Complete |
| DATA-02 | Phase 6 | Complete |

**Coverage (v1.1):**
- v1.1 requirements: 15 total
- Mapped to phases: 15
- Unmapped: 0

---
*Requirements defined: 2026-04-02*
*Last updated: 2026-04-04 after v1.1 roadmap creation*
