# Roadmap: Grid Tactics TCG

## Milestones

- :white_check_mark: **v1.0 Game Engine & RL** - Phases 1-10 (shipped 2026-04-04)
- :construction: **v1.1 Online PvP Dueling** - Phases 11-15 (in progress)

## Phases

<details>
<summary>v1.0 Game Engine & RL (Phases 1-10) - SHIPPED 2026-04-04</summary>

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Game State Foundation** - 5x5 grid, mana system, deterministic RNG, and core state representation
- [x] **Phase 2: Card System & Types** - Data-driven card definitions, three card types, multi-purpose cards, and starter pool
- [x] **Phase 3: Turn Actions & Combat** - Action-per-turn system, movement, melee/ranged combat, drawing, and legal action enumeration
- [x] **Phase 4: Win Condition & Game Loop** - Sacrifice-to-damage mechanic, HP tracking, win detection, and complete playable games
- [x] **Phase 5: RL Environment Interface** - Gymnasium/PettingZoo wrapper, observation encoding, action space with masking
- [x] **Phase 6: RL Training Pipeline** - MaskablePPO training, self-play loop, reward shaping, and data persistence
- [ ] **Phase 7: Self-Play Robustness** - PettingZoo AEC for react window modeling, agent pool, and league-based training
- [ ] **Phase 8: Card Expansion & Balance** - Expanded 20-30 card pool and automated RL-driven balance sweep
- [ ] **Phase 9: Analytics Dashboard Core** - Streamlit dashboard with win rates, card statistics, and training metrics
- [ ] **Phase 10: Replay & Balance Visualization** - Game replay viewer with step-by-step playback and balance heatmaps

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
- [x] 03-01-PLAN.md -- MinionInstance, ActionType enum, Action dataclass, GameState extension with minion/react fields
- [x] 03-02-PLAN.md -- Effect resolution engine and action resolver (deploy, move, attack, draw, pass, combat)
- [x] 03-03-PLAN.md -- React window stack with LIFO chaining, legal_actions() enumeration, integration tests

### Phase 4: Win Condition & Game Loop
**Goal**: Complete games can be played from start to finish between two agents (random or scripted) with correct win detection
**Depends on**: Phase 3
**Requirements**: ENG-07, ENG-09
**Success Criteria** (what must be TRUE):
  1. A minion that reaches the opponent's back row can sacrifice itself, dealing its Attack value as player damage
  2. The game correctly detects when a player's HP reaches zero and declares a winner
  3. A random-agent smoke test runs 1000+ complete games without crashes, hangs, or invalid states
**Plans:** 2 plans
Plans:
- [x] 04-01-PLAN.md -- SACRIFICE action type, win/draw detection, legal action enumeration
- [x] 04-02-PLAN.md -- Game loop with random agent and 1000-game smoke test

### Phase 5: RL Environment Interface
**Goal**: The game engine is wrapped in a standard RL environment that an agent can train against
**Depends on**: Phase 4
**Requirements**: RL-01, RL-02, RL-03
**Success Criteria** (what must be TRUE):
  1. A Gymnasium-compatible environment exposes reset(), step(), observation_space, and action_space
  2. Board state (5x5 grid with unit stats), hand, mana, and HP are encoded as fixed-size numerical tensors with no information leakage of opponent's hidden state
  3. All possible actions map to a discrete action space with a binary mask that marks illegal actions as unavailable
  4. A random agent can play 10,000 episodes through the environment wrapper without errors
**Plans:** 2 plans
Plans:
- [x] 05-01-PLAN.md -- Observation encoder, action space encoder, reward function with unit tests
- [x] 05-02-PLAN.md -- GridTacticsEnv Gymnasium environment class with 10k episode validation

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
**Plans:** 3 plans
Plans:
- [x] 06-01-PLAN.md -- Install SB3 stack, SQLite schema + writer + reader for data persistence
- [x] 06-02-PLAN.md -- Potential-based reward shaping, SelfPlayEnv wrapper, checkpoint pool
- [ ] 06-03-PLAN.md -- Training entry point, self-play training loop, beats-random validation

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

</details>

### :construction: v1.1 Online PvP Dueling (In Progress)

**Milestone Goal:** Two human players can play Grid Tactics against each other in real-time through a web UI, with the Python game engine enforcing all rules server-side.

- [ ] **Phase 11: Server Foundation & Room System** - Flask-SocketIO server with room code create/join and initial game state emission
- [ ] **Phase 12: State Serialization & Game Flow** - Hidden-info view filtering, action validation, legal action emission, complete game playable via WebSocket client
- [ ] **Phase 13: Board & Hand UI** - 5x5 CSS Grid board, hand display, mana/HP bars, and turn phase indicator in the browser
- [ ] **Phase 14: Gameplay Interaction** - Action submission via click targeting, react window UI, and game over screen
- [ ] **Phase 15: Resilience & Polish** - Reconnection handling, scrollable game log, and rematch flow

## Phase Details

### Phase 11: Server Foundation & Room System
**Goal**: Two clients can connect via WebSocket, create or join a game room by code, and both receive a game_start event with initial state
**Depends on**: Nothing (first phase of v1.1; uses existing Python engine as-is)
**Requirements**: SERVER-01, SERVER-02
**Success Criteria** (what must be TRUE):
  1. User can create a new game room and receive back a short alphanumeric room code they can share
  2. User can join an existing room by entering the room code, and both players receive a game_start event with initial game state
  3. A programmatic WebSocket client (Python or wscat) can complete the full create-join-receive flow without any browser UI
  4. Room codes are unique and rooms are tracked in-memory with player session tokens (not socket IDs) for reconnection readiness
**Plans:** 1/2 plans executed
Plans:
- [x] 11-01-PLAN.md -- Fix _fatigue global, install Flask-SocketIO, server package skeleton with preset deck
- [ ] 11-02-PLAN.md -- Room manager, game session, event handlers, entry point, and full test suite

### Phase 12: State Serialization & Game Flow
**Goal**: A complete game is playable via raw WebSocket messages -- both players take turns, react windows work, actions are validated, opponent hand is hidden, and the game ends with a correct winner
**Depends on**: Phase 11
**Requirements**: SERVER-03, VIEW-01, VIEW-02, VIEW-03
**Success Criteria** (what must be TRUE):
  1. Each player receives state updates containing only their own hand contents -- opponent hand is reduced to a card count with no card IDs or details leaked
  2. Server validates every submitted action against legal_actions() and rejects illegal actions with an error event (never crashes)
  3. Each state update includes the player's current legal actions list so the client knows what moves are available
  4. A complete game can be played to conclusion via two programmatic WebSocket clients taking alternating turns through action and react phases
**Plans**: TBD

### Phase 13: Board & Hand UI
**Goal**: The game is fully rendered in the browser -- users see the 5x5 grid with minions, their hand with card details, both players' mana/HP, and whose turn it is
**Depends on**: Phase 12
**Requirements**: UI-01, UI-02, UI-03, UI-04
**Success Criteria** (what must be TRUE):
  1. User can see the 5x5 grid with minions displayed showing name, ATK/HP, owner color, and attribute indicator
  2. User can see their hand with full card details (name, mana cost, ATK/HP for minions, effects, attribute) and cards they cannot afford are visually dimmed
  3. User can see both players' current mana and HP displayed prominently
  4. User can see whose turn it is and whether the current phase is ACTION or REACT
  5. The board renders correctly with two browser windows connected to the same room, each showing their own perspective
**Plans**: TBD
**UI hint**: yes

### Phase 14: Gameplay Interaction
**Goal**: Users can play the full game through the browser UI -- clicking cards and board positions to submit actions, responding to react windows, and seeing the game over result
**Depends on**: Phase 13
**Requirements**: PLAY-01, PLAY-02, PLAY-03
**Success Criteria** (what must be TRUE):
  1. User can submit an action by clicking a card in hand and then clicking a valid board target, with valid targets highlighted after card selection
  2. During the react window, the user can see the pending action, play a react card from hand to counter it, or click a pass button to let it resolve
  3. When the game ends, user sees a game over overlay showing victory or defeat, the reason (HP depletion / sacrifice / timeout), and final HP for both players
**Plans**: TBD
**UI hint**: yes

### Phase 15: Resilience & Polish
**Goal**: The game handles real-world conditions -- disconnections recover gracefully, a game log tracks what happened, and players can rematch without creating a new room
**Depends on**: Phase 14
**Requirements**: POLISH-01, POLISH-02, POLISH-03
**Success Criteria** (what must be TRUE):
  1. User who disconnects and reconnects within 60 seconds resumes the game with full state restored and can continue playing
  2. User can see a scrollable game log sidebar showing the history of actions taken (who played what, damage dealt, cards drawn)
  3. After a game ends, user can click a "Rematch" button and both players start a new game in the same room without re-entering room codes
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 11 -> 12 -> 13 -> 14 -> 15

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Game State Foundation | v1.0 | 4/4 | Complete | 2026-04-02 |
| 2. Card System & Types | v1.0 | 2/2 | Complete | 2026-04-02 |
| 3. Turn Actions & Combat | v1.0 | 3/3 | Complete | 2026-04-03 |
| 4. Win Condition & Game Loop | v1.0 | 2/2 | Complete | 2026-04-03 |
| 5. RL Environment Interface | v1.0 | 2/2 | Complete | 2026-04-03 |
| 6. RL Training Pipeline | v1.0 | 2/3 | In progress | - |
| 7. Self-Play Robustness | v1.0 | 0/TBD | Not started | - |
| 8. Card Expansion & Balance | v1.0 | 0/TBD | Not started | - |
| 9. Analytics Dashboard Core | v1.0 | 0/TBD | Not started | - |
| 10. Replay & Balance Visualization | v1.0 | 0/TBD | Not started | - |
| 11. Server Foundation & Room System | v1.1 | 1/2 | In Progress|  |
| 12. State Serialization & Game Flow | v1.1 | 0/TBD | Not started | - |
| 13. Board & Hand UI | v1.1 | 0/TBD | Not started | - |
| 14. Gameplay Interaction | v1.1 | 0/TBD | Not started | - |
| 15. Resilience & Polish | v1.1 | 0/TBD | Not started | - |
