# Feature Landscape

**Domain:** TCG game engine with grid-based tactical combat and reinforcement learning strategy testing
**Researched:** 2026-04-02

## Table Stakes

Features users (here: the developer/researcher running RL experiments) expect. Missing = the system cannot fulfill its core purpose.

### Game Engine Layer

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Complete rule enforcement engine | RL agents exploit any rule gap; incorrect game logic produces meaningless training data | High | Must validate every action, enforce turn structure, mana costs, card effects. The rules engine is the foundation everything else sits on. |
| Legal action enumeration | RL agents need to know which actions are valid at every decision point; this is how RLCard and Gymnasium environments work | Medium | Return list of legal actions from any game state. Critical for masking illegal actions in the policy network. |
| Deterministic game state with seeded RNG | Reproducibility is non-negotiable for debugging RL training and validating results | Medium | Seed the random number generator so any game can be replayed identically given the same seed and actions. |
| Game state serialization / deserialization | Must save and load game states for replay buffers, checkpointing, and debugging | Medium | Serialize full state (board, hands, decks, mana, HP, turn order) to dictionary or bytes. |
| 5x5 grid with positional logic | Core game mechanic; without spatial reasoning the game is just a card game, not a tactical card game | High | Row ownership, adjacency for melee, range calculation, deployment zones, sacrifice-at-opponent-side mechanic. |
| Mana system with banking | Core resource mechanic that creates the spend-now-vs-save tension the RL agent must learn | Low | Pool regeneration (+1/turn), carry-over, spending on card play. Straightforward accounting. |
| Three card types (Minion, Magic, React) | Defines the action space and strategic possibilities | Medium | Each type has different play rules, timing windows, and effects. React cards need interrupt/response mechanics. |
| Action-per-turn system | Core turn structure where each "turn" is a single action, creating tight action economy | Medium | Player chooses one action (play card, move minion, attack, draw), then opponent may react, then turn passes. |
| Draw-costs-action mechanic | Part of the core action economy tension | Low | Drawing is an explicit action choice, not automatic. |
| Win/loss condition detection | RL needs terminal state signals | Low | Detect when a player's HP reaches zero. |
| Two-player game loop | Minimum viable game requires two agents playing against each other | Medium | Turn alternation, react windows, game-over detection. |

### RL Integration Layer

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Gymnasium-compatible environment interface | Standard API that all modern RL libraries expect (Stable Baselines3, CleanRL, RLlib) | Medium | Implement `reset()`, `step(action)`, `observation_space`, `action_space`. Return `(obs, reward, terminated, truncated, info)`. |
| State observation encoding | RL agents consume numerical tensors, not Python objects | High | Encode board state (5x5 grid with unit stats), hand cards, mana, HP, graveyard info into a fixed-size numerical representation. This is where most design effort goes. |
| Action space definition | RL agents need a finite, well-defined action space | High | Map all possible actions (play card X to position Y, move unit from A to B, attack unit C with unit D, draw, pass) into a discrete or multi-discrete space. Large combinatorial space needs careful design. |
| Reward signal (win/loss at minimum) | RL cannot learn without a reward signal | Low | +1 for win, -1 for loss, 0 for ongoing. Sparse but functional. |
| Self-play training loop | The primary training paradigm for two-player zero-sum games | Medium | Both sides controlled by agents (same or different policies). Collect trajectories, update policies. |
| Action masking for illegal actions | Agents must not attempt illegal actions; masking is standard practice in discrete-action RL for games | Low | Pass legal action mask alongside observation. Stable Baselines3 supports this via `MaskablePPO`. |

### Analytics / Output Layer

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Training metrics logging | Must track whether RL is actually learning (loss curves, reward trends, episode lengths) | Low | Log to TensorBoard, W&B, or CSV. Standard RL practice. |
| Win rate tracking | The primary signal for card balance analysis and strategy evaluation | Low | Track win rates per agent, per deck composition, over time windows. |
| Card usage statistics | Which cards are played, how often, win correlation. Core data for balance analysis. | Low | Count card plays, track win rate when card is included in deck vs. not. |
| Game result storage | Persist game outcomes for offline analysis | Low | Store game results (winner, scores, deck compositions, game length) to file or database. |

## Differentiators

Features that make this project more than "yet another card game with RL." Not expected in a minimal system, but high value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Reward shaping with intermediate signals | Sparse win/loss rewards make learning slow. Intermediate signals (damage dealt, board control, mana efficiency) dramatically accelerate training. | Medium | Must be careful: agents can learn to optimize shaped rewards instead of winning. Use potential-based shaping to guarantee policy invariance. |
| Game replay viewer | Visual playback of recorded games lets humans understand what the RL agent learned and spot degenerate strategies | High | Web-based or terminal replay showing board state, card plays, and decision points turn by turn. Major debugging and insight tool. |
| Balance heatmaps and card power rankings | Go beyond raw win rates to show which cards are overpowered/underpowered, with visual dashboards | Medium | Aggregate card-level stats across thousands of games. Compute Elo-like ratings per card or per deck archetype. |
| Deck composition explorer | RL discovers which card combinations are strongest; surfacing these as "archetypes" provides meta-game insight | Medium | Cluster winning decks by card overlap. Identify core cards per archetype. Show archetype matchup matrix. |
| Configurable card definitions (data-driven) | Define cards in JSON/YAML instead of hardcoded classes, enabling rapid iteration on card stats and effects without code changes | Medium | Card data files with stats, effects, and keywords. Engine interprets card data at runtime. Enables automated balance sweeps. |
| Automated balance sweep | Programmatically vary card stats (attack, health, cost) and re-run RL training to find balanced configurations | High | Requires fast training (or simplified proxy). Evolutionary algorithms or grid search over card parameter space. Research shows this approach works (Hearthstone studies). |
| Vectorized / parallel environment execution | Run hundreds or thousands of games simultaneously for faster RL training | High | Use Python multiprocessing or JAX-based acceleration. Pgx achieves 10x speedups on GPU. Critical for scaling to millions of games. |
| Curriculum learning for agent training | Start with simplified scenarios (fewer cards, smaller board) and gradually increase complexity | Medium | Helps RL converge faster on complex games. Implement environment wrappers that control game complexity. |
| Multi-purpose card mechanics (minion + react from hand) | Unique game mechanic that adds deck-building depth. RL must learn when to deploy vs. hold for react. | Medium | Dual-use cards create interesting strategic tension that is rare in TCG engines. |
| Meta-strategy discovery and reporting | Identify dominant strategies, counter-strategies, and rock-paper-scissors dynamics across many games | High | Requires large-scale self-play, strategy clustering, and matchup analysis. The "Phase 4" ambition from PROJECT.md. |
| Opponent modeling | Agent that adapts to the opponent's observed strategy during a game (not just population-level) | High | More advanced RL technique. Could use recurrent policies (LSTM/GRU) or attention over game history. Deferred to later phases. |
| Human-playable interface | Let a human play against the trained RL agent | Medium | Terminal or simple web UI. Not the primary goal but valuable for subjective evaluation of AI quality. |

## Anti-Features

Features to explicitly NOT build. Each wastes effort or actively harms the project.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Visual card art / polished graphics | Project goal is RL strategy testing, not a consumer game. Art assets are a massive time sink with zero RL value. | Use text/emoji representations in terminal or simple colored rectangles in web UI. |
| Multiplayer networking / online play | Adds enormous complexity (latency, synchronization, cheating prevention) irrelevant to self-play RL. | All games run locally. Two RL agents in the same process. |
| Card trading / collection economy | Economic simulation is an entirely separate domain. Not relevant to strategy or balance testing. | Fixed card pools. Decks assembled programmatically. |
| Mobile app | Platform-specific development distracts from the core Python RL pipeline. | Desktop/web dashboard only. |
| Real-time combat | The game is turn-based by design. Real-time would fundamentally change the RL problem (continuous control) and break the action-per-turn mechanic. | Keep strict turn-based with discrete action steps. |
| Complex visual animations | Slow down simulation speed. RL needs millions of games; visual rendering is the bottleneck. | Headless execution for training. Optional text or simple render for debugging. |
| Overly complex card effect scripting language | Building a DSL for card effects is a rabbit hole. Start simple. | Use Python functions/classes for card effects. Graduate to data-driven definitions only when you have enough cards to justify it. |
| Blockchain / NFT integration | Irrelevant to RL research. Adds complexity, no value. | Not applicable. |
| Tournament bracket system | Nice-to-have for meta analysis but premature. Focus on pairwise matchups first. | Run round-robin matchups between deck/agent combinations. Compute Elo from results. |
| Perfect play solver / brute-force game tree | The game tree is too large for exact solutions (5x5 grid, 40+ card decks). RL is the approach because solving is intractable. | Use RL approximation. MCTS could supplement but not replace. |

## Feature Dependencies

```
Rule Enforcement Engine
  |
  +---> Legal Action Enumeration
  |       |
  |       +---> Action Space Definition ----+
  |                                          |
  +---> Game State Serialization             |
  |       |                                  |
  |       +---> Deterministic Replay (seeds) |
  |       |                                  |
  |       +---> Game Replay Viewer           |
  |                                          |
  +---> Win/Loss Detection                   |
          |                                  |
          +---> Reward Signal ---------------+
                  |                          |
                  +---> Reward Shaping       |
                                             |
State Observation Encoding ------------------+
  |                                          |
  +---> Gymnasium Environment Interface -----+
          |
          +---> Self-Play Training Loop
          |       |
          |       +---> Training Metrics Logging
          |       |
          |       +---> Win Rate Tracking
          |       |
          |       +---> Card Usage Statistics
          |       |
          |       +---> Game Result Storage
          |
          +---> Vectorized Parallel Execution
          |
          +---> Curriculum Learning

Card Usage Statistics + Win Rate Tracking
  |
  +---> Balance Heatmaps / Power Rankings
  |
  +---> Automated Balance Sweep

Game Result Storage + Strategy Clustering
  |
  +---> Deck Composition Explorer
  |
  +---> Meta-Strategy Discovery

Configurable Card Definitions (independent, but enables):
  |
  +---> Automated Balance Sweep
  |
  +---> Rapid Card Iteration
```

### Key dependency insight

The rule enforcement engine is the critical path. Nothing works without correct game logic. The Gymnasium interface is the second gate -- all RL training depends on it. These two components must be rock-solid before any RL work begins.

## MVP Recommendation

**Prioritize (Phase 1 - Core Engine):**

1. **Complete rule enforcement engine** with 5x5 grid, mana system, three card types, action-per-turn, and draw-costs-action. This is the highest-complexity, highest-risk item. Get it right first.
2. **Legal action enumeration** from any game state. Build this into the engine from day one -- do not bolt it on later.
3. **Deterministic seeded RNG** for reproducibility. Trivial to add at the start, painful to retrofit.
4. **Game state serialization** to dictionary format.
5. **Win/loss detection** for terminal states.

**Prioritize (Phase 2 - RL Interface):**

6. **State observation encoding** -- the hardest design problem. Encode the 5x5 grid, hands, mana, HP into numerical tensors.
7. **Action space definition** -- map the combinatorial action space into a discrete space with masking.
8. **Gymnasium environment wrapper** implementing `reset()`, `step()`, and action masking.
9. **Basic reward signal** (win/loss: +1/-1).
10. **Self-play training loop** with PPO (via Stable Baselines3 `MaskablePPO`).

**Prioritize (Phase 3 - Analytics):**

11. **Training metrics logging** to TensorBoard.
12. **Win rate tracking** and **card usage statistics**.
13. **Game result storage** to files.

**Defer:**

- **Game replay viewer**: High value but high complexity. Build after the training pipeline works. Phase 3 or 4.
- **Reward shaping**: Start with sparse rewards. Add shaping only if training is too slow (likely will be needed, but measure first).
- **Vectorized execution**: Optimize after the single-environment pipeline is validated. Phase 3+.
- **Automated balance sweep**: Requires fast training. Phase 4+.
- **Meta-strategy discovery**: Requires large-scale data. Phase 4+.
- **Deck composition explorer**: Requires game result corpus. Phase 4.
- **Configurable card definitions**: Start with hardcoded cards for a small card set. Move to data-driven when card count exceeds ~20.
- **Human-playable interface**: Nice demo but not on the critical path.
- **Opponent modeling**: Advanced RL technique. Phase 5+ or research spike.

## Complexity Budget

| Complexity | Count | Items |
|------------|-------|-------|
| High | 5 | Rule engine, observation encoding, action space, game replay viewer, vectorized execution |
| Medium | 12 | Grid logic, card types, action-per-turn, Gymnasium interface, self-play loop, reward shaping, balance heatmaps, deck explorer, data-driven cards, curriculum learning, multi-purpose cards, human interface |
| Low | 7 | Mana system, draw-costs-action, win/loss detection, reward signal, action masking, metrics logging, win rate tracking |

Total feature surface is substantial. The MVP (Phases 1-2) focuses on the 5 highest-risk items plus essential low-complexity connectors.

## Sources

- [RLCard: A Toolkit for Reinforcement Learning in Card Games](https://rlcard.org/)
- [RLCard Paper](https://dczha.com/files/rlcard-a-toolkit.pdf)
- [Gymnasium: Custom Environment Creation](https://gymnasium.farama.org/introduction/create_custom_env/)
- [Gymnasium Environment API](https://gymnasium.farama.org/api/env/)
- [Pokemon TCG AI Simulator (self-play with PPO)](https://github.com/sethkarten/tcg)
- [PyTAG: Tabletop Games for Multi-Agent RL](https://arxiv.org/html/2405.18123v1)
- [Pgx: Hardware-Accelerated Parallel Game Simulators](https://arxiv.org/pdf/2303.17503)
- [Automated Playtesting in CCGs using Evolutionary Algorithms (HearthStone)](https://www.researchgate.net/publication/324767888_Automated_Playtesting_in_Collectible_Card_Games_using_Evolutionary_Algorithms_a_Case_Study_in_HearthStone)
- [Evolving the Hearthstone Meta](https://arxiv.org/pdf/1907.01623)
- [AI Playtesting](https://aiplaytesting.github.io/)
- [Game Architecture for Card Game AI](https://bennycheung.github.io/game-architecture-card-ai-3)
- [Asmodee Rules Engine Architecture](https://doc.asmodee.net/rules-engine)
- [Reward Shaping: Mastering RL](https://gibberblot.github.io/rl-notes/single-agent/reward-shaping.html)
- [Self-Improving Card Game Engine](https://www.emergentmind.com/topics/self-improving-card-game-engine)
- [Deep RL from Self-Play in Imperfect-Information Games](https://arxiv.org/pdf/1603.01121)
- [Grid Tactics: Duel (comparable commercial game)](https://store.steampowered.com/app/3294170/Grid_Tactics_Duel/)
- [Instant Replay: Building a Game Engine with Reproducible Behavior](https://www.gamedeveloper.com/design/instant-replay-building-a-game-engine-with-reproducible-behavior)
- [MTG AI Deck Builder (meta discovery)](https://github.com/georgejieh/mtg_ai_deck_builder)
