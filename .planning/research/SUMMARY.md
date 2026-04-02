# Project Research Summary

**Project:** Grid Tactics TCG
**Domain:** TCG game engine with reinforcement learning for strategy discovery and balance analysis
**Researched:** 2026-04-02
**Confidence:** HIGH

## Executive Summary

Grid Tactics TCG is a Python-based tactical card game engine designed for RL self-play, strategy discovery, and card balance analysis. The established pattern for this type of project is a four-layer architecture (Game Engine / RL Environment / Training Pipeline / Dashboard) where each layer has zero knowledge of the layer above it. The game engine is the foundation: it must be correct, deterministic, and completely decoupled from ML dependencies. The RL layer wraps the engine in Gymnasium/PettingZoo interfaces and feeds flat numpy observations to Stable-Baselines3's MaskablePPO. The dashboard reads from SQLite and presents balance insights via Streamlit. This layering is well-proven in projects like RLCard and multiple PettingZoo tutorials.

The recommended approach is to build the game engine first with exhaustive testing, then layer RL integration on top, then build the training pipeline, and finally the analytics dashboard. The stack is Python 3.12, NumPy for state representation, PettingZoo AEC for the two-player turn-based interface (including the React interrupt window), MaskablePPO from sb3-contrib for action-masked policy learning, and Streamlit with Plotly for the stats dashboard. All library versions have been verified for mutual compatibility. The React mechanic -- where the opponent can play a counter-card mid-turn -- maps cleanly to PettingZoo's Agent-Environment-Cycle model, which is specifically designed for sequential decision points with interrupts.

The dominant risk is game engine bugs silently corrupting RL training. Because RL agents explore states humans never would, they will find and exploit every rule gap, producing meaningless balance data. Prevention requires exhaustive unit tests, property-based testing with Hypothesis, random-agent smoke tests (10,000+ games), and assertions on game state invariants. The second major risk is self-play training collapse, where the agent cycles through strategies without converging. An agent pool (league of historical checkpoints) with diversified opponent sampling is the standard mitigation. Both risks must be addressed architecturally before any training begins.

## Key Findings

### Recommended Stack

The stack splits into three installable layers: core engine (numpy + stdlib only), RL training (SB3 + PettingZoo + SuperSuit), and dashboard (Streamlit + Plotly + pandas). This means you can test the game without PyTorch and run the dashboard without the RL stack. Python 3.12 is the correct target -- all libraries support it, and Python 3.13 would break PettingZoo's upper version bound.

**Core technologies:**
- **Python 3.12**: Runtime -- mature, 10-15% faster than 3.11, compatible with all dependencies
- **NumPy >=2.2**: Game state arrays, observation encoding -- foundation for all RL data
- **PettingZoo AEC >=1.25**: Multi-agent environment API -- purpose-built for sequential turn-based games with interrupts
- **MaskablePPO (sb3-contrib >=2.8)**: RL algorithm with action masking -- prevents agent from wasting training time on illegal actions
- **SuperSuit >=3.9**: PettingZoo-to-SB3 bridge -- vectorized environment conversion
- **Streamlit >=1.56**: Stats dashboard -- fastest Python-to-interactive-web path
- **Plotly >=6.6**: Interactive charts -- heatmaps, board visualization, balance charts
- **SQLite (stdlib)**: Game results and metrics storage -- zero-config, single-file
- **JSON files**: Card definitions -- human-readable, version-controllable, enables rapid balance iteration

### Expected Features

**Must have (table stakes):**
- Complete rule enforcement engine with 5x5 grid, mana system, three card types, action-per-turn, draw-costs-action
- Legal action enumeration from any game state (single source of truth for both validation and masking)
- Deterministic seeded RNG for full reproducibility
- Game state serialization/deserialization
- Gymnasium/PettingZoo-compatible environment interface with observation encoding, action space, and action masking
- Self-play training loop with MaskablePPO
- Win rate tracking and card usage statistics
- Training metrics logging (TensorBoard)

**Should have (differentiators):**
- Reward shaping with potential-based intermediate signals (only if sparse rewards fail to converge)
- Game replay viewer (web-based turn-by-turn playback)
- Balance heatmaps and card power rankings
- Data-driven card definitions (JSON, not hardcoded classes)
- Configurable mana cap for balance testing
- Deck composition explorer and archetype clustering

**Defer (v2+):**
- Automated balance sweep (evolutionary search over card parameters)
- Vectorized/parallel environment execution (Pgx-style GPU acceleration)
- Opponent modeling with recurrent policies
- Human-playable interface
- Meta-strategy discovery and reporting (requires large-scale data corpus)
- Tournament bracket system

### Architecture Approach

The architecture follows a strict four-layer model mirroring RLCard's proven pattern. Layer 1 (Game Engine) is pure Python with immutable GameState objects -- actions produce new states rather than mutating in place. Layer 2 (Environment) is a thin adapter translating between rich Python objects and flat numpy arrays. Layer 3 (Training) orchestrates self-play with an agent pool and logs metrics. Layer 4 (Dashboard) reads from SQLite, never touches game state.

**Major components:**
1. **GameState + ActionResolver** -- Immutable game state with a resolver that validates and applies actions, producing new states. Single `legal_actions()` function serves both the engine and RL masking.
2. **GridTacticsEnv (PettingZoo AEC)** -- Wraps the game engine. Handles observation encoding (multi-channel 2D grid for board + flat vectors for hand/mana/HP), action decoding, and reward signals. The React window is modeled as a sub-turn where legal actions are restricted to react cards + pass.
3. **SelfPlayWrapper + AgentPool** -- Converts the 2-player AEC environment into a single-agent Gymnasium environment by auto-stepping the opponent from a pool of historical checkpoints. Prevents strategy cycling.
4. **StatsAPI + DashboardUI (Streamlit)** -- Reads training logs and game records from SQLite. Computes aggregated balance statistics and renders interactive charts.

### Critical Pitfalls

1. **Game engine bugs corrupt RL training silently** -- RL agents exploit every rule gap. Prevention: exhaustive unit tests, property-based testing, random-agent smoke tests (10K games), `GameState.validate()` after every action, assertions on invariants (mana never negative, dead minions removed, positions in bounds).
2. **Information leakage in observations** -- Exposing opponent's hand contents teaches the agent a different game. Prevention: separate `GameState` (full truth) from `PlayerObservation` (visible info only) from day one. Unit test that observations contain no private data.
3. **Action space explosion** -- Thousands of possible actions with only 5-20 legal at any time. Prevention: fixed-size `Discrete(N)` action space with MaskablePPO action masking. Never penalize illegal actions with negative rewards.
4. **Effect system becomes unmaintainable** -- Adding card 20 requires modifying 5 functions. Prevention: data-driven effect system with composable primitive effects (deal_damage, buff_stat, etc.) and a Command pattern. Effect resolution queue for React stack ordering.
5. **Self-play training collapse** -- Strategy cycling without convergence. Prevention: agent pool with diversified opponent sampling (50% latest, 30% recent, 20% historical). Monitor exploitability against fixed baselines (random, greedy). Track Elo across pool.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Game Engine Foundation
**Rationale:** Everything depends on correct game rules. The game engine is the critical path -- no RL training, analytics, or balance analysis works without it. Architecture research strongly emphasizes building and testing the engine in isolation before adding ML dependencies.
**Delivers:** A complete, tested, deterministic game engine that can run full games between random agents. Includes the card library (small initial pool of 5-8 simple cards), 5x5 grid with positional logic, mana with banking, three card types, React window, action-per-turn, and draw-costs-action.
**Addresses:** Rule enforcement, legal action enumeration, deterministic RNG, game state serialization, win/loss detection
**Avoids:** Rule bugs corrupting training (#1), information leakage (#2), effect system spaghetti (#4), incorrect React modeling (#7), non-deterministic RNG (#11), draw-not-an-action (#13)

### Phase 2: RL Environment Interface
**Rationale:** Depends on Phase 1 (wraps the engine). The observation encoder and action encoder define what the agent can perceive and do -- getting these wrong means retraining from scratch. This is the second gate before any training can start.
**Delivers:** A PettingZoo AEC environment that wraps the game engine. Multi-channel 2D observation encoding for the board (CNN-compatible), flat encoding for hand/mana/HP. Fixed-size discrete action space with masking. Sparse reward signal (+1/-1). SelfPlayWrapper for single-agent SB3 compatibility.
**Uses:** PettingZoo, SuperSuit, Gymnasium, NumPy
**Implements:** ObservationEncoder, ActionEncoder, GridTacticsEnv, RewardShaper, SelfPlayWrapper
**Avoids:** Spatial info loss (#8), engine-RL coupling (#9), action space explosion (#3)

### Phase 3: Training Pipeline and Self-Play
**Rationale:** Depends on Phase 2 (needs a working environment). This is where the RL actually runs. The agent pool and self-play infrastructure must be designed from the start to prevent training collapse.
**Delivers:** A trained agent that beats random play convincingly. Training loop with MaskablePPO, agent pool with checkpoint diversity, TensorBoard logging, game recording, checkpoint management. Baseline evaluation suite (vs random, greedy-aggressive, greedy-defensive).
**Uses:** SB3, sb3-contrib (MaskablePPO), TensorBoard
**Implements:** TrainingLoop, AgentPool, MetricsLogger, GameRecorder, CheckpointManager
**Avoids:** Self-play collapse (#5), reward misalignment (#6), missing metadata (#16), premature architecture optimization (#18)

### Phase 4: Card Expansion and Balance Tuning
**Rationale:** With a validated training pipeline, expand the card pool and use RL to discover balance issues. This is where the project delivers on its core promise. Requires fast simulation speed, so performance optimization happens at the start of this phase.
**Delivers:** Expanded card pool (20-30 cards) with validated RL convergence. Balance metrics per card. Mana cap tuning. Data-driven card definitions in JSON. Performance-optimized engine (target: 10K+ steps/sec).
**Addresses:** Data-driven card definitions, configurable mana cap, reward shaping (if needed)
**Avoids:** Card pool too complex (#10), slow engine (#12), mana banking degeneracy (#14), SQLite write contention (#17)

### Phase 5: Analytics Dashboard
**Rationale:** Depends on Phase 3-4 (needs training data and game results to display). The dashboard is a consumer of data, not a producer. Building it after training data exists means real data for development and testing.
**Delivers:** Streamlit web dashboard with win rate graphs, card power rankings, balance heatmaps, game replay viewer, deck composition explorer. Reads from SQLite.
**Uses:** Streamlit, Plotly, pandas, SQLite
**Implements:** StatsAPI, ReplayViewer, BalanceAnalyzer, DashboardUI

### Phase 6: Advanced Strategy Discovery
**Rationale:** Requires large-scale training data and a mature pipeline. This is the ambitious research phase -- meta-game analysis, automated balance sweeps, and strategy clustering.
**Delivers:** Meta-strategy discovery, archetype identification, matchup matrices, automated balance sweep (vary card stats and retrain), Elo ratings across strategy pool.
**Addresses:** Automated balance sweep, meta-strategy discovery, deck archetype clustering

### Phase Ordering Rationale

- **Engine before RL**: The PettingZoo environment wraps the game engine. If the engine API changes, the environment must update. The engine's `legal_actions()` interface is the most critical contract -- it must be stable before Phase 2 depends on it.
- **Environment before training**: Observation and action space design determines what the agent can learn. A spatial representation mistake (flat vs 2D) would require retraining from scratch.
- **Training before dashboard**: The dashboard reads data that training produces. Building the dashboard first means developing against fake data, then discovering the schema doesn't match reality.
- **Card expansion as a separate phase**: Starting with a minimal card pool (5-8 cards) and validating RL convergence before expanding prevents the "too many cards, can't converge" pitfall. This is the curriculum learning principle applied to development itself.
- **Dashboard after training pipeline**: Parallelizable with Phase 4 if desired, but the data contracts must be defined in Phase 3.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (RL Environment):** Observation space sizing and action space encoding are estimated at ~300-500 features and ~400 discrete actions. Actual sizes depend on card feature count, max hand size, and whether derived channels (threat zones, valid targets) are included. Needs prototyping to finalize.
- **Phase 3 (Training Pipeline):** Self-play wrapper architecture has reference implementations (PettingZoo Connect Four tutorial) but Grid Tactics' React window adds a wrinkle -- the sub-turn interrupt changes agent alternation patterns. Needs careful implementation and testing.
- **Phase 4 (Card Expansion):** Performance optimization strategy (numpy arrays vs Cython vs Numba) depends on profiling results from Phase 3. Cannot decide in advance.
- **Phase 6 (Strategy Discovery):** Meta-strategy clustering and automated balance sweeps are research-grade problems with limited off-the-shelf solutions. Expect experimentation.

Phases with standard patterns (skip deep research):
- **Phase 1 (Game Engine):** Well-documented patterns -- immutable state, Command pattern for effects, dataclasses, unit testing. RLCard provides a direct reference architecture.
- **Phase 5 (Dashboard):** Streamlit development is straightforward. The only design question is the data schema, which is defined in Phase 3.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified on PyPI. Compatibility matrix confirmed. Python 3.12 validated across all packages. |
| Features | HIGH | Table stakes well-defined by domain research. Feature dependencies are clear. Differentiators validated by academic papers (Hearthstone RL, Jaipur self-play). |
| Architecture | HIGH | Four-layer pattern matches RLCard, PettingZoo tutorials, and multiple card game RL implementations. Immutable GameState and AEC for react windows are proven patterns. |
| Pitfalls | HIGH | All critical pitfalls sourced from multiple references (RLCard, NFSP, SPIRAL, Gymnasium docs). Phase-specific warnings are well-documented in RL training literature. |

**Overall confidence:** HIGH

### Gaps to Address

- **Observation space exact sizing:** Estimated at ~300-500 features but depends on card feature count, max hand size, and whether derived spatial channels are worth the complexity. Prototype in Phase 2 and validate with a "does the agent learn basic strategy?" test before finalizing.
- **CNN vs MLP for 5x5 grid:** A 5x5 grid is small. A CNN may not provide meaningful advantage over a flattened MLP for this grid size. Start with MLP (SB3 default), upgrade to CNN only if spatial strategy learning is poor. MEDIUM confidence on CNN necessity.
- **React window RL dynamics:** The sub-turn interrupt is well-modeled by PettingZoo AEC in theory, but there is limited published work on react/counter mechanics in RL training specifically. May affect training speed or strategy learning for react cards. Monitor in Phase 3.
- **Performance targets:** 10K+ steps/sec is the target, but pure Python game engines for tactical games with this state complexity may fall short. Profiling data from Phase 3 will determine whether Cython/Numba optimization is needed in Phase 4.
- **Agent pool sizing and sampling strategy:** The 50/30/20 split (latest/recent/historical) is a starting point from self-play literature, but optimal values depend on the game's strategy space. Treat as a hyperparameter to tune in Phase 3.
- **Windows platform:** Gymnasium and PettingZoo note unofficial Windows support. Test the full stack integration early. WSL is a fallback.

## Sources

### Primary (HIGH confidence)
- [PettingZoo AEC API](https://pettingzoo.farama.org/) -- Turn-based multi-agent environment standard
- [Stable-Baselines3 v2.8](https://github.com/DLR-RM/stable-baselines3/releases/tag/v2.8.0) -- RL algorithm library
- [MaskablePPO (sb3-contrib)](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) -- Action masking for discrete spaces
- [RLCard Architecture](https://rlcard.org/overview.html) -- Three-layer card game RL architecture reference
- [Gymnasium Environment API](https://gymnasium.farama.org/api/env/) -- Standard RL environment interface
- [PettingZoo SB3 Connect Four Tutorial](https://pettingzoo.farama.org/tutorials/sb3/connect_four/) -- Self-play + action masking reference implementation
- [arXiv:2503.22575](https://arxiv.org/html/2503.22575v2) -- SB3 PPO outperforms RLlib PPO empirically

### Secondary (MEDIUM confidence)
- [Mastering Jaipur Through Self-Play RL](https://link.springer.com/chapter/10.1007/978-3-031-47546-7_16) -- Self-play + action masking for card games
- [SPIRAL: Self-Play Training Collapse](https://arxiv.org/html/2506.24119v1) -- Variance reduction, thinking collapse
- [Deep RL from Self-Play (Heinrich & Silver)](https://arxiv.org/pdf/1603.01121) -- NFSP for imperfect information games
- [Automated Playtesting with Evolutionary Algorithms (Hearthstone)](https://www.researchgate.net/publication/324767888) -- RL for card game balance
- [Pgx: Hardware-Accelerated Game Simulators](https://arxiv.org/pdf/2303.17503) -- GPU-accelerated environments (deferred option)
- [GridNet: CNN over Grid for Tactical Games](https://proceedings.mlr.press/v97/han19a/han19a.pdf) -- Spatial encoding validation

### Tertiary (LOW confidence)
- [Overcooked Training Performance](https://bsarkar321.github.io/blog/overcooked_madrona/index.html) -- Python simulation bottleneck quantification (different domain)
- [Reward Shaping: Potential-Based Guarantees](https://ar5iv.labs.arxiv.org/html/2311.16339) -- Reward engineering (general, not TCG-specific)
- [Card Game Design as Systems Architecture](https://critpoints.net/2023/05/26/card-game-design-as-systems-architecture/) -- Effect system design (blog, not peer-reviewed)

---
*Research completed: 2026-04-02*
*Ready for roadmap: yes*
