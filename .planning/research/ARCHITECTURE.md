# Architecture Patterns

**Domain:** TCG game engine with reinforcement learning (5x5 grid tactical card game)
**Researched:** 2026-04-02

## Recommended Architecture

Grid Tactics TCG requires a **four-layer architecture** that cleanly separates game rules from RL training from analytics. This mirrors the proven pattern used by [RLCard](https://rlcard.org/overview.html) (Environment / Game / Agent layers) but extends it with a grid-positional game layer and a dedicated analytics/dashboard layer.

```
+-------------------------------------------------------------+
|                    LAYER 4: DASHBOARD                       |
|  Stats API  |  Game Replay  |  Balance Viz  |  Meta Charts  |
+-------------------------------------------------------------+
        |                    reads from
+-------------------------------------------------------------+
|                    LAYER 3: TRAINING                        |
|  Self-Play Loop  |  Agent (PPO)  |  Curriculum  |  Logging  |
+-------------------------------------------------------------+
        |                    wraps
+-------------------------------------------------------------+
|                    LAYER 2: ENVIRONMENT                     |
|  Gymnasium/PettingZoo Env  |  Observation Encoder  |        |
|  Action Masking  |  Reward Shaper  |  Self-Play Wrapper     |
+-------------------------------------------------------------+
        |                    drives
+-------------------------------------------------------------+
|                    LAYER 1: GAME ENGINE                     |
|  GameState  |  Board(5x5)  |  Cards/Deck  |  Rules/Judger  |
|  Player  |  ActionResolver  |  ReactWindow  |  TurnManager  |
+-------------------------------------------------------------+
```

### Why This Layering

**Layer 1 (Game Engine)** knows nothing about RL. It is a pure Python implementation of the game rules that can be used headlessly, tested independently, and reasoned about without any ML dependencies. This is critical: if the game rules are tangled with the RL interface, every rule change breaks the training pipeline.

**Layer 2 (Environment)** translates between the game engine's rich Python objects and the flat numpy arrays that RL algorithms consume. It follows the [Gymnasium](https://gymnasium.farama.org/) / [PettingZoo AEC](https://pettingzoo.farama.org/) interface standard. This layer handles observation encoding, action decoding, action masking, and reward calculation.

**Layer 3 (Training)** orchestrates self-play, manages opponent pools, runs training loops, and logs metrics. It uses [Stable Baselines3](https://stable-baselines3.readthedocs.io/) (specifically [MaskablePPO from sb3-contrib](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)) as the RL algorithm. This layer is where training hyperparameters, curriculum schedules, and checkpointing live.

**Layer 4 (Dashboard)** reads training logs, game replays, and aggregated statistics to present balance analysis, win rates, and strategy insights. It is a consumer of data, never a producer of game state.

---

## Component Boundaries

### Layer 1: Game Engine Components

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `GameState` | Immutable snapshot of the entire game at a point in time. Contains board, both players, mana pools, decks, hands, graveyards, turn counter, whose-turn flag, phase flag (action/react). | Everything reads it; only `ActionResolver` produces new states |
| `Board` | 5x5 grid of cell references. Tracks which minion occupies each cell. Knows grid geometry (rows, adjacency, range calculations). | `GameState` (owns it), `ActionResolver` (queries for legal moves/attacks) |
| `Card` / `CardLibrary` | Card definitions (name, type, cost, attack, health, range, effects). `CardLibrary` is the design-time database; `Card` instances are runtime copies. | `Deck`, `Player.hand`, `Board` (deployed minions reference their card) |
| `Deck` | Ordered collection of cards. Handles shuffle, draw. | `Player` (each player has one) |
| `Player` | Owns a hand, deck, graveyard, mana pool, HP, and side-of-board assignment. | `GameState` (contains two players) |
| `TurnManager` | Tracks whose turn it is. Advances turns. A "turn" is a single action, not a full round. Manages the action-then-react-window sequence. | `GameState`, `ActionResolver` |
| `ActionResolver` | Given a GameState and an Action, validates legality and produces the next GameState. This is the core rules engine. Handles: play card, move minion, attack, draw card, pass, play react card. | `GameState` (reads current, produces next), `Board`, `Player`, `ReactWindow` |
| `ReactWindow` | After the active player's action resolves, opens a window for the opponent to play a React card. If they pass or have no legal reacts, the window closes and the turn advances. | `TurnManager`, `ActionResolver` |
| `Judger` | Determines game-over conditions (player HP <= 0, deck-out rules if any). Calculates final payoffs (+1 win, -1 loss). | `GameState` |

**Key design decision:** `GameState` should be **immutable** (or treated as such). `ActionResolver` takes a state + action and returns a new state. This enables:
- Easy undo/redo (keep prior states)
- Safe parallel simulation (no shared mutable state)
- Game replay (sequence of states)
- Tree search algorithms later (MCTS expansion)

#### The React Window Problem

The react mechanic (opponent can interrupt with a React card after each action) is the trickiest architectural element. It means a single "turn" has two decision points:

```
Active Player Action -> [Effects Pending] -> Opponent React Window -> [React Resolves or Skip] -> Effects Resolve -> Turn Passes
```

From the RL perspective, this maps cleanly to the **PettingZoo AEC (Agent Environment Cycle)** model where agents alternate. The active player takes an action, then the opponent gets a "turn" where their legal actions are either React cards or "pass." This is the same pattern used for bidding games and Magic: The Gathering priority systems.

**Implementation:** Model react as a normal turn where the legal action set is restricted to react-eligible cards plus "pass." The `TurnManager` tracks a `phase` enum: `ACTION` or `REACT`. After each `ACTION` phase resolves, it enters `REACT` phase for the opponent. If the opponent passes, it goes back to `ACTION` for the other player.

### Layer 2: Environment Components

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `GridTacticsEnv` | PettingZoo AEC environment wrapper. Implements `reset()`, `step()`, `observe()`, `action_space()`, `observation_space()`. | Layer 1 (`GameState`, `ActionResolver`), Layer 3 (training loop calls it) |
| `ObservationEncoder` | Converts `GameState` into a fixed-size numpy array from the perspective of the observing player. Handles information hiding (opponent's hand is hidden). | `GameState` (reads), `GridTacticsEnv` (called by) |
| `ActionEncoder` | Maps between the engine's structured `Action` objects and integer action IDs that RL algorithms use. Also provides action masks (which action IDs are legal). | `GameState` (reads legal actions), `GridTacticsEnv` (called by) |
| `RewardShaper` | Calculates reward signals. Start with sparse rewards (win=+1, loss=-1). Later add shaped rewards for intermediate signals (damage dealt, mana efficiency, board control). | `GameState` (reads), `GridTacticsEnv` (returns rewards) |
| `SelfPlayWrapper` | Wraps the 2-player AEC environment into a single-agent Gymnasium environment by having the opponent be a frozen policy (from the agent pool). Required for SB3 compatibility. | `GridTacticsEnv` (wraps), Agent pool (selects opponent) |

#### Observation Space Design

The observation vector encodes all visible information for one player. For a 5x5 grid TCG:

```
Observation Vector (estimated ~300-500 floats):
  Board State:        25 cells x ~8 features per cell = 200
                      (occupant owner, attack, health, range, has_acted, card_type_id, empty_flag, ...)
  My Hand:            max_hand_size x card_feature_count (e.g., 10 x 6 = 60)
  My Resources:       mana_current, mana_max, hp, deck_size, graveyard_count = 5
  Opponent Visible:   hp, mana_current, hand_size, deck_size = 4
  Game Phase:         turn_number, is_my_turn, is_react_phase = 3
  
  Total: ~270-350 features (normalize all to [-1, 1] range)
```

Encode cards by their stats (not one-hot over all card types) so the network generalizes across cards with similar stats.

#### Action Space Design

The action space must cover all possible actions. Use a **flat discrete space** with action masking:

```
Action Space (estimated ~200-400 discrete actions):
  Play card from hand to cell:  max_hand_size x 10 deploy_cells = 100
  Move minion from cell to cell: 25 x 4 directions = 100
  Attack from cell to cell:      25 x ~8 target_cells = 200 (many masked)
  Draw a card:                   1
  Pass (react window):           1
  Play react from hand:          max_hand_size = 10
  
  Total: ~400 actions (heavily masked -- typically only 5-20 legal at any time)
```

Use [MaskablePPO](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) which zeros out the probability of illegal actions before sampling, rather than relying on the network to learn which actions are legal.

### Layer 3: Training Components

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `TrainingLoop` | Orchestrates self-play training. Runs episodes, collects trajectories, calls SB3's `learn()`. | `SelfPlayWrapper` (runs episodes), `AgentPool` (selects opponents), SB3 `MaskablePPO` |
| `AgentPool` | Stores snapshots of the agent at various training checkpoints. Opponent for current training is sampled from this pool (not always the latest). Prevents strategy collapse. | `TrainingLoop` (adds snapshots), `SelfPlayWrapper` (provides opponent policy) |
| `MetricsLogger` | Records per-episode data: winner, game length, mana efficiency, cards played, damage dealt, etc. Writes to structured logs (JSON lines or SQLite). | `GridTacticsEnv` (reads post-game stats), TensorBoard/W&B (optional real-time) |
| `GameRecorder` | Saves full game trajectories (sequence of states + actions) for replay analysis. | `GridTacticsEnv` (records each step), Dashboard (reads replays) |
| `CheckpointManager` | Saves/loads model weights, training state, and agent pool. | SB3 model, filesystem |

#### Self-Play Architecture

Self-play for two-player games requires converting the multi-agent environment into a single-agent problem. The standard approach, validated in [Connect Four tutorials](https://pettingzoo.farama.org/tutorials/sb3/connect_four/) and card game research:

```
                    +------------------+
                    |  Training Agent  |  (being trained)
                    +--------+---------+
                             |
                    +--------v---------+
                    | SelfPlayWrapper   |  (Gymnasium interface)
                    |                   |
                    | When it's agent's |
                    | turn: return obs, |
                    | wait for action   |
                    |                   |
                    | When it's opp's   |
                    | turn: query       |
                    | opponent policy,  |
                    | auto-step         |
                    +--------+---------+
                             |
                    +--------v---------+
                    | GridTacticsEnv    |  (PettingZoo AEC)
                    | (2-player game)   |
                    +---+-----------+---+
                        |           |
              +---------v--+   +----v--------+
              | Player 1   |   | Player 2    |
              | (training) |   | (from pool) |
              +------------+   +-------------+
```

### Layer 4: Dashboard Components

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `StatsAPI` | Reads training logs and game records. Computes aggregated statistics (win rates per card, per strategy, over time). | `MetricsLogger` output, `GameRecorder` output |
| `ReplayViewer` | Renders a game step-by-step from recorded trajectories. Shows board state, hands, actions taken. | `GameRecorder` data |
| `BalanceAnalyzer` | Identifies outlier cards (too high/low win rate, pick rate, etc.). Suggests balance adjustments. | `StatsAPI` aggregations |
| `DashboardUI` | Web frontend for viewing all analytics. | `StatsAPI` (data source) |

---

## Data Flow

### During Training (primary loop)

```
1. TrainingLoop calls SelfPlayWrapper.reset()
2. SelfPlayWrapper calls GridTacticsEnv.reset()
3. GridTacticsEnv calls GameState.new_game() -> initial state
4. ObservationEncoder encodes state -> numpy observation
5. ActionEncoder provides action_mask -> numpy bool array
6. SelfPlayWrapper returns (observation, action_mask) to TrainingLoop
7. MaskablePPO selects action from masked policy
8. SelfPlayWrapper calls GridTacticsEnv.step(action)
9. ActionEncoder decodes action int -> structured Action
10. ActionResolver validates + applies action -> new GameState
11. TurnManager checks for ReactWindow -> may give opponent a turn
12. If opponent's turn: SelfPlayWrapper queries AgentPool opponent policy
13. RewardShaper calculates reward (0 during game, +1/-1 at end)
14. GameRecorder logs (state, action, reward) tuple
15. MetricsLogger records episode stats at game end
16. Repeat from step 4 until episode ends
17. MaskablePPO updates policy from collected trajectory
18. Every N episodes: save agent snapshot to AgentPool
```

### During Analysis (dashboard)

```
1. StatsAPI reads MetricsLogger files (JSON lines / SQLite)
2. StatsAPI computes aggregations (win rate by card, by turn count, etc.)
3. BalanceAnalyzer queries StatsAPI for card-level stats
4. ReplayViewer loads GameRecorder files for specific games
5. DashboardUI serves web pages pulling from StatsAPI
```

---

## Patterns to Follow

### Pattern 1: Immutable GameState with Action-Produces-New-State

**What:** Every game state is a frozen snapshot. Actions don't mutate state; they produce a new state.

**When:** Always -- this is the foundation pattern.

**Why:** Enables replay, undo, parallel simulation, and tree search. Prevents the most common class of bugs in game engines (stale state references, order-of-mutation issues).

**Example:**
```python
@dataclass(frozen=True)
class GameState:
    board: Board
    players: tuple[Player, Player]
    active_player_idx: int
    phase: TurnPhase  # ACTION or REACT
    turn_number: int
    
class ActionResolver:
    def resolve(self, state: GameState, action: Action) -> GameState:
        """Validate action, apply effects, return new state."""
        if not self._is_legal(state, action):
            raise IllegalActionError(action)
        new_state = self._apply(state, action)
        return self._advance_phase(new_state)
```

### Pattern 2: Legal Action Generator as Single Source of Truth

**What:** One function generates all legal actions for a given state. Both the game engine (for validation) and the environment (for action masking) use this same function.

**When:** Always -- prevents desync between what the engine allows and what the RL agent sees as legal.

**Example:**
```python
class ActionResolver:
    def legal_actions(self, state: GameState) -> list[Action]:
        """All legal actions for the active player in current state."""
        actions = []
        if state.phase == TurnPhase.REACT:
            actions.extend(self._legal_reacts(state))
            actions.append(Action.PASS)
        else:
            actions.extend(self._legal_plays(state))
            actions.extend(self._legal_moves(state))
            actions.extend(self._legal_attacks(state))
            actions.append(Action.DRAW)
        return actions
```

### Pattern 3: Encode by Stats, Not by Identity

**What:** Observation vectors encode card stats (attack, health, cost, range, type-flags) rather than one-hot card identity vectors.

**When:** When the card pool is moderate (50-200 cards) and you want the agent to generalize across similar cards.

**Why:** One-hot encoding over N card types creates a sparse, high-dimensional observation. Stat-based encoding lets the agent recognize "3-attack 2-health minion" as similar regardless of card name. This is critical for balance testing -- when you tweak a card's stats, the agent's understanding partially transfers.

### Pattern 4: Sparse Rewards First, Shape Later

**What:** Start with win/loss only (+1/-1 at game end, 0 during). Add intermediate reward signals only if training fails to converge.

**When:** Initial training phases.

**Why:** Reward shaping can introduce bias that makes the agent optimize for the shaped signal rather than winning. Sparse rewards are harder to learn from but produce more robust strategies. If convergence is too slow, add modest shaping (e.g., +0.01 per damage dealt, -0.01 per HP lost).

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Game Logic in the Environment Layer

**What:** Putting rule validation, damage calculation, or turn management inside the Gymnasium/PettingZoo environment wrapper.

**Why bad:** Makes the game untestable without RL infrastructure. Makes rule changes require understanding the RL interface. Tightly couples two concerns that change for different reasons.

**Instead:** Keep the environment as a thin translation layer. It calls `ActionResolver.resolve()` and `ObservationEncoder.encode()`, nothing more.

### Anti-Pattern 2: Mutable Game State

**What:** Having `game.play_card(card)` mutate the game object in place.

**Why bad:** Makes replay impossible (you lose prior states). Makes parallel simulation unsafe. Makes debugging state-dependent bugs extremely difficult. Prevents future MCTS integration.

**Instead:** `ActionResolver.resolve(state, action) -> new_state`. Use `dataclasses(frozen=True)` or equivalent.

### Anti-Pattern 3: Training the Agent Against Itself (No Pool)

**What:** Always using the latest policy as both the training agent and opponent.

**Why bad:** Causes **strategy cycling** where the agent discovers strategy A, then strategy B that beats A, then strategy C that beats B but loses to A, in an endless loop. The agent never builds robust play.

**Instead:** Maintain an `AgentPool` of historical checkpoints. Sample opponents from the pool with some probability of being the latest agent and some probability of being a random historical agent. This is well-established in self-play literature.

### Anti-Pattern 4: Enormous Flat Observation Vectors

**What:** Encoding everything as one massive 1D vector without structure.

**Why bad:** The grid has spatial structure. A 2D/3D tensor (channels x rows x cols) enables convolutional processing that exploits spatial locality. Flat vectors lose this.

**Instead:** Provide the board state as a multi-channel 2D grid (shape: `[C, 5, 5]` where C is features-per-cell) and concatenate non-spatial features (hand, mana, HP) separately. Use a network architecture with CNN for board + MLP for non-spatial, then merge.

---

## Suggested Build Order

Build order is driven by the dependency chain: you cannot train RL without a working game, and you cannot analyze results without training data.

```
Phase 1: Game Engine (Layer 1)
    No dependencies. Must be complete and correct before anything else.
    Build: GameState, Board, Card/CardLibrary, Player, Deck,
           TurnManager, ActionResolver, ReactWindow, Judger
    Test: Unit tests for every rule. Random-agent smoke tests.
    Deliverable: Can run a complete game with random players.

Phase 2: RL Environment (Layer 2)
    Depends on: Phase 1 (complete game engine)
    Build: ObservationEncoder, ActionEncoder, GridTacticsEnv,
           RewardShaper, SelfPlayWrapper
    Test: PettingZoo API compliance tests, observation shape checks,
          action mask correctness vs legal_actions().
    Deliverable: Can run a game through the Gymnasium interface.

Phase 3: Training Pipeline (Layer 3)
    Depends on: Phase 2 (working environment)
    Build: TrainingLoop, AgentPool, MetricsLogger, GameRecorder,
           CheckpointManager
    Test: Agent trains for N episodes without crashing.
           Win rate against random agent improves.
    Deliverable: Trained agent that beats random play convincingly.

Phase 4: Dashboard (Layer 4)
    Depends on: Phase 3 (training data exists)
    Build: StatsAPI, ReplayViewer, BalanceAnalyzer, DashboardUI
    Test: Can view replays, see win rate graphs, identify outlier cards.
    Deliverable: Web dashboard showing RL training insights.
```

**Critical dependency:** Phase 2 wraps Phase 1. If the game engine API changes, the environment must update. Design the `GameState` / `ActionResolver` / `legal_actions()` interface carefully in Phase 1 because Phase 2 depends on it heavily.

**Parallelizable work:** Card design (what cards exist, their stats) can happen in parallel with the engine. The `CardLibrary` is data, not logic. Similarly, dashboard UI mockups can be designed before training data exists.

---

## Network Architecture Recommendation

For the RL agent's neural network (inside MaskablePPO):

```
Input:
  Board features:  [C, 5, 5] tensor (C = features per cell, ~8-10)
  Hand features:   [max_hand, F] (F = features per card, ~6)
  Global features: [G] vector (mana, HP, turn, phase, ~10)

Architecture:
  Board branch:    Conv2d(C, 32, 3, padding=1) -> ReLU -> Conv2d(32, 64, 3, padding=1) -> ReLU -> Flatten
  Hand branch:     Linear(F, 32) per card -> mean pool -> Linear(32, 32)
  Global branch:   Linear(G, 32)
  
  Merge:           Concat(board_flat, hand_out, global_out) -> Linear(combined, 256) -> ReLU
  
  Policy head:     Linear(256, action_space_size) + action masking
  Value head:      Linear(256, 1)
```

Use a **custom feature extractor** with SB3 rather than the default MLP. The CNN over the board captures spatial patterns (tank-in-front-of-ranged, flanking positions), which is the core strategic element of this game.

---

## Scalability Considerations

| Concern | Initial (dev) | At scale (millions of games) | Notes |
|---------|--------------|------------------------------|-------|
| Training speed | Single process, ~100 games/min | Vectorized envs (SubprocVecEnv), ~5000 games/min | SB3 supports vectorized envs natively |
| State storage | JSON lines, ~1KB/game summary | SQLite for stats, compressed replays only for interesting games | Don't store full replays for all games |
| Card pool size | 20-30 cards | 100+ cards | Observation encoding scales linearly with hand size, not card pool |
| Action space | ~400 discrete | Same, just more masking | Masking handles sparsity |
| Dashboard | Local Flask/FastAPI | Same -- reads aggregated stats | No real scaling concern for analytics |

---

## Sources

- [RLCard Architecture Overview](https://rlcard.org/overview.html) -- Three-layer architecture (Environment/Game/Agent)
- [RLCard Development Guide](https://rlcard.org/development.html) -- Game/Round/Dealer/Judger/Player pattern
- [PettingZoo AEC API](https://pettingzoo.farama.org/) -- Agent Environment Cycle for turn-based multi-agent games
- [PettingZoo Custom Environment Tutorial](https://pettingzoo.farama.org/tutorials/custom_environment/2-environment-logic/) -- Implementation pattern
- [SB3 MaskablePPO](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) -- Invalid action masking for PPO
- [SB3 Connect Four with Action Masking](https://pettingzoo.farama.org/tutorials/sb3/connect_four/) -- Self-play + action masking reference
- [Benny Cheung: Game Architecture for Card Game AI (Parts 1-3)](https://bennycheung.github.io/game-architecture-card-ai-1) -- Card game engine structure
- [Mastering Jaipur Through Self-Play RL and Action Masks](https://link.springer.com/chapter/10.1007/978-3-031-47546-7_16) -- Self-play + action masking for card games
- [GridNet: Grid-Wise Control for Multi-Agent RL](https://proceedings.mlr.press/v97/han19a/han19a.pdf) -- CNN over grid for tactical games
- [Self-Play Deep RL for Board Games](https://medium.com/applied-data-science/how-to-train-ai-agents-to-play-multiplayer-games-using-self-play-deep-reinforcement-learning-247d0b440717) -- Agent pool, self-play wrapper pattern

### Confidence Assessment

| Component | Confidence | Notes |
|-----------|------------|-------|
| 4-layer architecture | HIGH | Matches RLCard, PettingZoo, and multiple implementations |
| Immutable GameState pattern | HIGH | Standard in game AI, enables replay/search |
| PettingZoo AEC for react window | HIGH | AEC explicitly designed for sequential turn-taking with interrupts |
| MaskablePPO for training | HIGH | Proven in card games (Jaipur, Connect Four, poker variants) |
| CNN + MLP hybrid network | MEDIUM | Standard for grid games but may need tuning for 5x5 (small grid) |
| Observation vector sizing (~300-500) | MEDIUM | Estimated; actual size depends on card feature count and hand size |
| Agent pool for self-play stability | HIGH | Well-established technique, prevents strategy cycling |
