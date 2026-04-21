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

- [x] **Phase 11: Server Foundation & Room System** - Flask-SocketIO server with room code create/join and initial game state emission (completed 2026-04-05)
- [x] **Phase 12: State Serialization & Game Flow** - Hidden-info view filtering, action validation, legal action emission, complete game playable via WebSocket client (completed 2026-04-05)
- [x] **Phase 13: Board & Hand UI** - 5x5 CSS Grid board, hand display, mana/HP bars, and turn phase indicator in the browser (completed 2026-04-05)
- [x] **Phase 14: Gameplay Interaction** - Action submission via click targeting, react window UI, and game over screen (completed 2026-04-06)
- [x] **Phase 14.1: Melee Move-and-Attack** - Player-driven Advance-Wars-style melee chain (move then choose attack target or decline); ranged minions get no chain (completed 2026-04-07)
- [x] **Phase 14.2: Tutor Choice Prompt** - Replace auto-tutor with player-facing selection modal; extend tutor_target to support selector dicts (completed 2026-04-07)
- [x] **Phase 14.3: Game Juice (Animation Layer)** - Client-side AnimationQueue serializing summon / move / attack / burn / floating-popup visuals; pending UIs (react, tutor, post-move-attack) gate behind queue drain via applyStateFrame (completed 2026-04-07)
- [x] **Phase 14.4: Spectator Mode** - Lobby Spectate button + optional God Mode, server-side join_as_spectator + spectator fanout + action gating, dual-hand god view and P1-perspective non-god view (completed 2026-04-07)
- [x] **Phase 14.5: Piles & Hand Visibility** - from_deck flag + exhaust pile, tensor parity, view_filter piles, uniform card renderer, symmetric pile buttons with modal, opponent face-down hand row, AnimationQueue-integrated draw animations (completed 2026-04-08)
- [x] **Phase 14.6: Sandbox Mode (Dev Tooling)** - Single-tab manual game state editor reusing the live engine: search/add cards, toggle active player, play any action, undo/redo stack, save/load via to_dict/from_dict, shareable base64 codes for bug reports (completed 2026-04-11)
- [ ] **Phase 14.7: Turn Structure Overhaul** - Implement `data/turn_structure_spec.md`: 3-phase turn (Start / Action / End), TURN X / PLAYER X banner, start-of-turn + end-of-turn react windows, compound react windows (Summon declaration + Summon: effect = two windows), LIFO stack with originator at bottom so magic effects defer until chain resolves, Prohibition can now negate the originator, react-condition matching, turn-player-first simultaneous-trigger priority with modal card-picker for multiple same-player triggers, fizzle-on-invalid-target rule. Uses the existing spell-stage center-screen react animation built in v0.11.32-35.
- [ ] **Phase 14.8: Phase Contract Enforcement** - Make it impossible for the engine to mutate state out of phase, and impossible for the client to paint a state that hasn't been "played" through its animation slot. Every state mutation declares a contract source (trigger-bound / status-bound / action-bound / system-bound) and the engine asserts the contract at apply time. The wire format becomes an ordered event stream tagged with `contract_source`, replacing the current "post-resolution state snapshot". Client has one animation queue; events schedule into slots by contract; DOM only reflects events that have been played. Same path for sandbox AND live PvP. Pytest invariant tests scan every card + every effect site and prove the engine never emits an out-of-phase mutation.
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
**Plans:** 2/2 plans complete
Plans:
- [x] 11-01-PLAN.md -- Fix _fatigue global, install Flask-SocketIO, server package skeleton with preset deck
- [x] 11-02-PLAN.md -- Room manager, game session, event handlers, entry point, and full test suite

### Phase 12: State Serialization & Game Flow
**Goal**: A complete game is playable via raw WebSocket messages -- both players take turns, react windows work, actions are validated, opponent hand is hidden, and the game ends with a correct winner
**Depends on**: Phase 11
**Requirements**: SERVER-03, VIEW-01, VIEW-02, VIEW-03
**Success Criteria** (what must be TRUE):
  1. Each player receives state updates containing only their own hand contents -- opponent hand is reduced to a card count with no card IDs or details leaked
  2. Server validates every submitted action against legal_actions() and rejects illegal actions with an error event (never crashes)
  3. Each state update includes the player's current legal actions list so the client knows what moves are available
  4. A complete game can be played to conclusion via two programmatic WebSocket clients taking alternating turns through action and react phases
**Plans:** 2/2 plans complete
Plans:
- [x] 12-01-PLAN.md -- View filter module, action codec, and auto-draw bug fix
- [x] 12-02-PLAN.md -- submit_action handler, game_start filter fix, integration tests for complete game flow

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
**Plans:** 3/3 plans complete
Plans:
- [x] 13-01-PLAN.md -- Server enhancements (Flask static serving, enhanced card_defs, deck ready) + HTML/CSS foundation
- [x] 13-02-PLAN.md -- Client JS: Socket.IO client, lobby, deck builder, board/hand/stats rendering
- [x] 13-03-PLAN.md -- Integration testing, bug fixes, and visual verification checkpoint
**UI hint**: yes

### Phase 14: Gameplay Interaction
**Goal**: Users can play the full game through the browser UI -- clicking cards and board positions to submit actions, responding to react windows, and seeing the game over result
**Depends on**: Phase 13
**Requirements**: PLAY-01, PLAY-02, PLAY-03
**Success Criteria** (what must be TRUE):
  1. User can submit an action by clicking a card in hand and then clicking a valid board target, with valid targets highlighted after card selection
  2. During the react window, the user can see the pending action, play a react card from hand to counter it, or click a pass button to let it resolve
  3. When the game ends, user sees a game over overlay showing victory or defeat, the reason (HP depletion / sacrifice / timeout), and final HP for both players
**Plans:** 2 plans
Plans:
- [ ] 14-01-PLAN.md -- React window UI: pending action banner, react card highlighting, click-to-play-react (PLAY-02)
- [ ] 14-02-PLAN.md -- Game over modal: VICTORY/DEFEAT overlay with reason, final HP, back-to-lobby flow (PLAY-03)
**UI hint**: yes

### Phase 14.1: Melee Move-and-Attack
**Goal:** Replace auto-attack-after-move with player-driven Advance-Wars-style melee chain (move then choose attack target or decline). Ranged minions get no chain.
**Depends on**: Phase 14
**Plans:** 5/5 plans complete
Plans:
- [x] 14.1-01-PLAN.md -- Python engine pending state + remove auto-attack
- [x] 14.1-02-PLAN.md -- Tensor engine parity
- [x] 14.1-03-PLAN.md -- Legal-action mask pending awareness
- [x] 14.1-04-PLAN.md -- Frontend two-step flow + range footprint
- [x] 14.1-05-PLAN.md -- Roadmap/state update + smoke test

### Phase 14.3: Game Juice (Animation Layer)
**Goal:** Make the game feel alive with visible animations for summon, move, attack, burn tick, and floating status popups, all serialized through a client-side AnimationQueue. Pending UIs (react window, tutor modal, post-move-attack picker) gate structurally behind queue drain via applyStateFrame.
**Depends on**: Phase 14.2
**Plans:** 7/7 plans complete
Plans:
- [x] 14.3-01-PLAN.md -- Client AnimationQueue infrastructure + applyStateFrame seam
- [x] 14.3-02-PLAN.md -- Summon scale-in + grid shake animation
- [x] 14.3-03-PLAN.md -- Move lift/translate/drop animation
- [x] 14.3-04-PLAN.md -- Attack rubber-band + flash + damage popup + last_action server payload
- [x] 14.3-05-PLAN.md -- Phase 14.1 / 14.2 integration + roadmap/STATE closeout + smoke test
- [x] 14.3-06-PLAN.md -- Burning status engine tick (added mid-phase)
- [x] 14.3-07-PLAN.md -- Floating popups (heal/burn/buff/debuff) + persistent status badges + Luckiest Guy font (added mid-phase)

### Phase 14.4: Spectator Mode
**Goal:** Any third-party client can join a room as a spectator (with optional God Mode to see both hands), watch a live game end-to-end, chat in the room, and never affect game state. Spectator perspective in non-god mode is fixed to the Player 1 seat; a perspective toggle is deferred.
**Depends on**: Phase 14.3
**Plans:** 5/5 plans complete
Plans:
- [x] 14.4-01-PLAN.md -- Spectator data model + join API in RoomManager
- [x] 14.4-02-PLAN.md -- filter_state_for_spectator (god + non-god)
- [x] 14.4-03-PLAN.md -- events.py spectator wiring (join, fanout, gating, chat, disconnect)
- [x] 14.4-04-PLAN.md -- Frontend spectator UI (lobby button, god-mode checkbox, dual-hand render, badge)
- [x] 14.4-05-PLAN.md -- Tests + roadmap/STATE closeout + smoke test

### Phase 14.2: Tutor Choice Prompt
**Goal:** Replace auto-tutor with player-facing selection modal; extend tutor_target to support selector dicts (tribe/element/card_type AND semantics) instead of only card_id strings.
**Depends on**: Phase 14.1
**Plans:** 5/5 plans complete
Plans:
- [x] 14.2-01-PLAN.md -- Python engine pending_tutor + tutor_target selector schema
- [x] 14.2-02-PLAN.md -- Tensor engine parity
- [x] 14.2-03-PLAN.md -- Legal-action masks
- [x] 14.2-04-PLAN.md -- Frontend modal + serialization
- [x] 14.2-05-PLAN.md -- Roadmap/STATE + smoke test

### Phase 14.5: Piles & Hand Visibility
**Goal:** Make piles (graveyard + exhaust) first-class and visible for both players, fix the minion-play-to-graveyard double-count bug, unify card rendering across hand/deck-builder/tooltip, show an opponent face-down hand row, and animate card draws through the Phase 14.3 AnimationQueue.
**Depends on**: Phase 14.4
**Plans:** 7/7 plans complete
Plans:
- [x] 14.5-01-PLAN.md -- Python engine: MinionInstance.from_deck + Player.exhaust + three hand-removal verbs
- [x] 14.5-02-PLAN.md -- Tensor engine parity: minion_from_deck + exhausts + exhaust_sizes; fix minion-play graveyard double-count
- [x] 14.5-03-PLAN.md -- view_filter symmetric piles (own/opp graveyard + exhaust) on every state frame
- [x] 14.5-04-PLAN.md -- Uniform card renderer (renderCardFrame single source of truth)
- [x] 14.5-05-PLAN.md -- 4 pile buttons + shared pile modal + opponent face-down hand row
- [x] 14.5-06-PLAN.md -- Card-draw animations via AnimationQueue (draw_own + draw_opp) driven by multiset hand diff
- [x] 14.5-07-PLAN.md -- Roadmap/STATE closeout + UAT (UAT deferred to post-deploy E2E)

### Phase 14.6: Sandbox Mode (Dev Tooling)
**Goal**: A "Sandbox" tab in the top nav lets the developer open a manual editor over the live game engine — fixed god-view dual perspective (P1 top, P2 bottom), search/add cards to any zone for either player, move cards between zones, import decks, take any legal action, manually toggle active player, cheat mana/HP, undo/redo, save and reload state both locally and via named server-side slots, and share state via base64 code — all reusing the existing GameState/CardLibrary/resolve_action/legal_actions code with no engine duplication.
**Depends on**: Phase 14.5
**Requirements**: DEV-01 through DEV-09
**Success Criteria** (what must be TRUE):
  1. A new "Sandbox" tab appears in the top nav before the Wiki link, opens a sandbox screen with fixed god-view layout (P1 hand on top, P2 hand on bottom, both face-up), and starts a fresh empty session without going through lobby/room codes
  2. User can search the full card library by name and add any card to a chosen zone (hand / deck top / deck bottom / graveyard / exhaust) for either player; sandbox state mutates only via in-engine state operations (no parallel "fake hand" data structure)
  3. User can move cards between zones (deck → hand, hand → grave, grave → exhaust, etc.) via the existing pile modals and hand row, and import a saved deck (deck-builder JSON) into a player's deck zone
  4. User can take any legal action (play / move / attack / pass / react / tutor / sacrifice) and the state is advanced by the same `resolve_action()` and validated by the same `legal_actions()` used in real games
  5. User can manually toggle which player is the active player (mutates `state.active_player_idx`); engine-driven react/tutor transitions still happen automatically
  6. User can edit either player's `current_mana`, `max_mana`, and `hp` to any value at any time (cheat inputs)
  7. User can save state to: localStorage (autosave), downloadable JSON file, base64 share code (round-trips perfectly), AND named server-side slots (`data/sandbox_saves/<slot>.json`) listed/loaded/deleted via Socket.IO handlers
  8. User can undo (and redo) at least 50 prior sandbox operations in one session — every state-mutating operation pushes the undo stack
  9. Existing `GameSession`, `view_filter.py`, `RoomManager` lobby code, real-game Socket.IO handlers, and game.js board/hand renderers are NOT modified beyond purely additive hooks (new dict on RoomManager, new event handlers in events.py, new screen branch in game.js, opts-parameter refactor on renderBoard/renderHand that is backward-compatible with all existing zero-arg call sites)
**Plans:** 4 plans
Plans:
- [x] 14.6-01-PLAN.md -- SandboxSession + RoomManager._sandboxes + 16 Socket.IO handlers + backend tests
- [x] 14.6-02-PLAN.md -- Sandbox screen scaffold: nav tab, screen div, render reuse via existing renderBoard/renderHand
- [x] 14.6-03-PLAN.md -- Sandbox toolbar: search, add-card, control toggle, undo/redo, save/load/share/paste, localStorage autosave, action submission via reused click handlers
- [x] 14.6-04-PLAN.md -- Playwright E2E smoke test + manual UAT + ROADMAP/STATE closeout
**UI hint**: yes

### Phase 14.7: Turn Structure Overhaul
**Goal**: The game's turn loop implements the priority / phase / stack rules in `data/turn_structure_spec.md` end-to-end — a turn has three distinct phases (Start / Action / End) each with its own react window, compound actions open multiple react windows, magic spells defer their effects until the react chain resolves so Prohibition can negate them, simultaneous effects resolve turn-player-first with a modal card-picker for multiple same-player triggers, and effects whose target is invalid at resolution time fizzle silently.
**Depends on**: Phase 14.6
**Requirements**: TURN-01 through TURN-18 (18 requirements derived from `data/turn_structure_spec.md`; to be added to REQUIREMENTS.md in plan 14.7-10)
**Success Criteria** (what must be TRUE):
  1. Every turn opens with a 1.2-1.8s `TURN X / PLAYER X` banner overlay; turn flow works on top of it without blocking
  2. Turn has three ordered phases (Start of Turn → Action → End of Turn); priority starts with the turn player in each phase
  3. A react window opens at the end of Start of Turn, after every Action Phase action (including each melee sub-action and each compound sub-trigger), and before End of Turn ends
  4. Magic cast: only costs (mana, HP, destroy-ally, discard) resolve on play. The spell's ON_PLAY effects sit at the bottom of the react stack (`cast_mode` originator) and resolve LAST after the chain closes; a Prohibition on top negates the originator and cancels the burn/damage/etc.
  5. Melee minions take up to two actions per turn (move + attack) and each opens its own independent react window
  6. A minion summon with a `Summon:` effect opens two react windows — one on declaration (negate the summon entirely) and one on the Summon: trigger (react to the effect only)
  7. React cards only fire when their written condition matches the trigger event (no free interrupts)
  8. When multiple effects trigger at the same game-state moment, the turn player's effects all resolve first; a modal card-picker lets a player order their own simultaneous effects one at a time
  9. An effect whose target is no longer valid at resolution time (destroyed, moved off-target) fizzles cleanly — no error, no partial resolution
  10. Visual: start-of-turn and end-of-turn triggered effects animate with a center-screen icon + source→effect→target blip, sequential when multiple queue
  11. The existing spell-stage center-screen react animation (LEFT-slot card + arrow + RIGHT-slot `?` / `⚡` / `👍`) drives every react window, not just magic casts
  12. Existing ~900 passing tests either continue to pass or are updated to match the new resolution timing; no silent regressions
**Plans:** 10 plans
Plans:
- [ ] 14.7-01-PLAN.md -- Cast-mode originator + deferred magic ON_PLAY (fixes Acidic Rain / Prohibition bug standalone)
- [ ] 14.7-02-PLAN.md -- 3-phase turn model (TurnPhase + ReactContext + react_return_phase)
- [ ] 14.7-03-PLAN.md -- Start/End-of-turn triggered-effect pipeline + retag 9 card JSONs
- [ ] 14.7-04-PLAN.md -- Compound react windows (Summon declaration + Summon: effect)
- [ ] 14.7-05-PLAN.md -- Turn-player-first priority queue + same-player modal picker
- [ ] 14.7-06-PLAN.md -- Fizzle rule (target-validity at resolve time)
- [ ] 14.7-07-PLAN.md -- React-condition matching via ReactContext + 3 new conditions
- [ ] 14.7-08-PLAN.md -- Melee two react windows (supersedes Phase 14.1 combined-window)
- [ ] 14.7-09-PLAN.md -- UI: turn banner + spell-stage generalization + trigger blips
- [ ] 14.7-10-PLAN.md -- Test migration (~40 tests) + TURN-* requirements + closeout
**UI hint**: yes

### Phase 14.8: Phase Contract Enforcement
**Goal**: It is architecturally impossible for the engine to mutate state out of phase, and architecturally impossible for the client to paint a state that hasn't been "played" through its animation slot — verified by pytest invariants and visual ordering tests.
**Depends on**: Phase 14.7
**Requirements**: CONTRACT-01 through CONTRACT-08 (to be added to REQUIREMENTS.md in plan 14.8-01)
**Success Criteria** (what must be TRUE):
  1. Every state-mutating engine call declares a `contract_source` from one of four categories: trigger-bound (e.g. `trigger:on_end_of_turn`), status-bound (e.g. `status:burn`), action-bound (e.g. `action:play_card`), system-bound (e.g. `system:turn_flip`).
  2. A central phase-contract table maps each contract source to its allowed phase(s); the engine asserts the contract at apply time and raises `OutOfPhaseError` (action rejected, state unchanged) on violation.
  3. A pytest invariant test loads every card JSON and every effect site, simulates every legal trigger in every phase, and proves the engine never silently mutates state out of phase.
  4. The wire format emitted by `events.py` is an ordered stream of events `{type, contract_source, payload, animation_duration_ms, ...}` instead of a post-resolution state snapshot; both sandbox and live PvP paths emit through the same serializer.
  5. Client has a single `eventQueue` (replacing `_sandboxFrameQueue` and `_pendingPostStageFrame` ad-hoc gates); each inbound event is enqueued and only commits to DOM when its slot fires; DOM never reflects an event that hasn't been played.
  6. The "Fallen Paladin End: heal blip" test sequence visibly plays as discrete beats: rat in spell-stage → stage closes → paladin pulses → HP ticks 30→32 → turn-2 banner. Same ordering for live PvP, not just sandbox.
  7. The "spell-stage" gate, the "trigger-blip" gate, the "turn-banner" gate, and any future animation slot all queue through the same mechanism (one animation queue, not three).
  8. The 500+ existing pytest tests continue to pass, plus the new invariant tests; visual UAT tests prove ordering for at least the 5 trickiest interaction chains (3-deep react chain, paladin heal-on-rat-deploy, double-paladin priority modal, ratchanter activated ability, multi-purpose Tree Wyrm react).
**Plans:** 10 plans
Plans:
- [ ] 14.8-01-PLAN.md -- Foundation: PHASE_CONTRACTS table + OutOfPhaseError + assert_phase_contract; tag 30+ existing call sites; CONTRACT-01..08 added to REQUIREMENTS.md (default mode = off)
- [ ] 14.8-02-PLAN.md -- Pytest invariant test scanning every card × every trigger × every phase × every action × every pending modal; iterate against shadow mode; flip conftest default to shadow
- [ ] 14.8-03a-PLAN.md -- engine_events module (EngineEvent + EventStream + 19 event types) + emission threading through 4 engine files + tests/test_engine_events.py
- [ ] 14.8-03b-PLAN.md -- Server-side: events.py emit, sandbox_session refactor, view_filter, test_event_serialization.py + next_event_seq on Session AND SandboxSession
- [ ] 14.8-04a-PLAN.md -- eventQueue infrastructure + dispatcher + 10 simpler slot handlers (minion summoned/died/hp/moved, attack, draw, played, discarded, mana, player_hp)
- [ ] 14.8-04b-PLAN.md -- 9 harder handlers (spell-stage chain, turn banner, trigger blip, pending modals × 2, fizzle, game_over, phase_changed, instant) + 4-gate deletion + dead-code markings
- [ ] 14.8-04c-PLAN.md -- Visual UAT checkpoint (5 trickiest scenarios in sandbox + paladin-heal in live PvP)
- [ ] 14.8-05-PLAN.md -- Flip enforcement to strict (CI) and shadow (prod default); soft OutOfPhaseError catch + structured error emit; delete last_trigger_blip / TriggerType.PASSIVE / dead-code helpers; tests migrated from snapshot-field to event-stream assertions
- [ ] 14.8-06-PLAN.md -- 5 codified visual UAT scenarios in data/tests/tests.json; Playwright runner asserts event ordering + non-overlap; runs in sandbox + live PvP
- [ ] 14.8-07-PLAN.md -- Closeout: REQUIREMENTS / ROADMAP / STATE updated; data/wire_format.md as living spec; VERSION bumped; CHANGELOG entry; pushed to master
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
| 11. Server Foundation & Room System | v1.1 | 2/2 | Complete    | 2026-04-05 |
| 12. State Serialization & Game Flow | v1.1 | 2/2 | Complete    | 2026-04-05 |
| 13. Board & Hand UI | v1.1 | 3/3 | Complete   | 2026-04-05 |
| 14. Gameplay Interaction | v1.1 | 2/2 | Complete | 2026-04-06 |
| 14.1 Melee Move-and-Attack | v1.1 | 5/5 | Complete | 2026-04-07 |
| 14.2 Tutor Choice Prompt | v1.1 | 5/5 | Complete | 2026-04-07 |
| 14.3 Game Juice (Animation Layer) | v1.1 | 7/7 | Complete | 2026-04-07 |
| 14.4 Spectator Mode | v1.1 | 5/5 | Complete | 2026-04-07 |
| 14.5 Piles & Hand Visibility | v1.1 | 7/7 | Complete | 2026-04-08 |
| 14.6 Sandbox Mode (Dev Tooling) | v1.1 | 4/4 | Complete | 2026-04-11 |
| 14.7 Turn Structure Overhaul | v1.1 | 0/10 | Planned | - |
| 14.8 Phase Contract Enforcement | v1.1 | 0/10 | Planned | - |
| 15. Resilience & Polish | v1.1 | 0/TBD | Not started | - |
