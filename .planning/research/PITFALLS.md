# Domain Pitfalls

**Domain:** TCG game engine with reinforcement learning (5x5 grid tactical card game)
**Researched:** 2026-04-02

---

## Critical Pitfalls

Mistakes that cause rewrites, abandoned training runs, or fundamentally invalidated results.

---

### Pitfall 1: Game Engine Bugs Silently Corrupt RL Training

**What goes wrong:** A subtle rule bug (e.g., mana not deducted on card play, range check off by one, react window skipped in certain states, dead minions not removed) goes unnoticed. The RL agent trains for millions of episodes on broken rules. The agent becomes an adversarial optimizer -- it finds and exploits every rule gap. All training results, balance analysis, and strategy discoveries are invalidated.

**Why it happens:** Game engines have enormous state spaces. Manual testing catches obvious bugs but misses edge cases. RL agents are uniquely dangerous here because they explore states humans would never try, then ruthlessly exploit them.

**Consequences:**
- Complete training restart once the bug is found (all metrics are garbage)
- Balance conclusions are wrong (a card isn't overpowered, it's just buggy)
- Could waste days or weeks of training compute
- May not be immediately obvious -- agent appears to play well but is actually exploiting a bug

**Prevention:**
- Exhaustive unit tests for every rule, especially edge cases: mana exactly at zero, board full, hand empty, deck empty, simultaneous effects, sacrifice at opponent's row boundary
- Property-based testing with Hypothesis: generate random game states and verify invariants (mana never negative, HP never exceeds max, dead minions removed from board, board positions in valid range)
- Run a **random-agent smoke test** for 10,000 games before RL training. Check for crashes, infinite loops, and invariant violations
- Assertion-heavy game engine in debug mode: validate state after every action resolution
- Implement `GameState.validate()` that checks all invariants. Call it after every `step()` during development

**Detection:**
- Agent learns "impossible" strategies (dealing more damage than any card allows)
- Win rates are suspiciously high/low for one side
- Agent always takes the same unusual action sequence
- Games end in 1-2 turns consistently
- Game state contains negative mana, negative HP, units at invalid positions

**Phase:** Phase 1 (game engine). Must have comprehensive tests before any RL training begins.

**Confidence:** HIGH -- Universally documented in game engine + RL projects.

---

### Pitfall 2: Leaking Hidden Information Into the Observation Space

**What goes wrong:** The RL agent is given access to the opponent's hand, deck order, or other hidden information during training. The agent learns strategies that exploit perfect information. When later evaluated against agents with realistic observations, or used as the game's AI opponent, it performs terribly or behaves nonsensically because it learned a fundamentally different game.

**Why it happens:** During development it is simpler to pass the full game state as the observation. Developers plan to "fix it later" but the agent's learned policy becomes deeply dependent on the leaked information. Card games are imperfect information games by nature -- each player's hand is hidden.

**Consequences:**
- Entire training runs are worthless (agent learned a different game)
- Strategies discovered don't transfer to real gameplay
- Balance conclusions are invalid (cards aren't OP when you can't see the opponent's hand)
- May not be obvious -- agent may appear to perform well in self-play while both agents exploit hidden info symmetrically

**Prevention:**
- From day one, separate `GameState` (full truth) from `PlayerObservation` (what one player can see)
- The RL environment must only expose `PlayerObservation` to the agent
- Include in the observation: own hand (stats-based encoding), board state (both sides visible), mana pools (both visible -- public info), graveyard/discard (public), number of cards in opponent's hand (but NOT their contents), current HP values, turn phase
- Exclude: opponent's hand contents, deck ordering, upcoming draws
- Write a unit test that asserts the observation space contains no reference to opponent private data
- Consider a perfect-information variant as a separate mode for debugging (where both hands are visible), but never use it for balance training

**Detection:**
- Agent performs dramatically worse when switched from training with full state to masked observations
- Agent "predicts" opponent plays with suspicious accuracy
- Agent never plays around possibilities -- always knows the exact opponent hand

**Phase:** Phase 1 (game engine + RL environment design). Retrofitting requires retraining from scratch.

**Confidence:** HIGH -- Extensively documented in imperfect information game RL research (RLCard, NFSP).

---

### Pitfall 3: Combinatorial Action Space Explosion

**What goes wrong:** The action space is defined as every possible combination of moves at every position. For Grid Tactics TCG, a single turn's action choices include: which card to play x which grid cell to target + which minion to move x which direction + attack with which minion x which target + draw + pass. With a 5x5 grid, multiple cards in hand, and multiple minions on board, the raw combinatorial space can reach thousands of actions. The agent cannot learn because most of the space is invalid at any given moment.

**Why it happens:** Developers define a flat `Discrete(N)` action space large enough to cover all possible actions in all possible states. Penalizing invalid actions with negative rewards seems like an easy fix but creates a secondary optimization problem.

**Consequences:**
- Training takes orders of magnitude longer (exploring invalid actions)
- Agent may never converge -- spends training learning what NOT to do rather than what to do
- Penalizing invalid actions creates reward signal noise that drowns out strategic learning
- Memory requirements balloon with action space size

**Prevention:**
- Use **action masking** (not penalties for invalid actions). Return a binary mask with each observation indicating which actions are currently legal. Use `sb3-contrib`'s `MaskablePPO` or equivalent
- Encode the action space as a fixed-size `Discrete(N)` where N covers all action types, but mask out unavailable actions per step
- For Grid Tactics TCG, design action encoding as: `action_type(5: play/move/attack/draw/pass) + card_index(max_hand) + grid_position(25) + target(25)` flattened to a single integer
- Validate: at every game state, at least one action is legal (pass is always legal)
- Log the ratio of legal-to-total actions during initial testing. If <5% of actions are legal on average, the space is too large

**Detection:**
- Training reward stays flat for thousands of episodes
- Agent frequently attempts invalid actions (logged by environment)
- Agent takes random-seeming actions even after substantial training
- Legal action count per step is extremely variable (1 to 500+)

**Phase:** Phase 1 (environment design). Action space encoding must be finalized before any training.

**Confidence:** HIGH -- Well documented in RLCard, Gymnasium action masking tutorials, and PettingZoo.

---

### Pitfall 4: The Effect System Becomes Unmaintainable Spaghetti

**What goes wrong:** Card effects are implemented as special-case `if/elif` chains in the game engine. Adding a new card requires modifying the engine core. Effect interactions (e.g., a React card countering a Magic card that was buffing a Minion) create deeply nested conditional logic. Multi-purpose cards (minion with react effect from hand) double the complexity.

**Why it happens:** The first few cards are simple enough that hardcoding works. By card 20, every new card touches 5 different functions. The React interrupt mechanic specifically creates an "effect stack" that interacts with everything. Developers don't realize the complexity curve until it is too late to refactor cheaply.

**Consequences:**
- Adding new cards takes hours instead of minutes
- Bugs in card interactions are nearly impossible to find or reproduce
- The RL agent may learn to exploit buggy interactions rather than real strategy
- Card balance analysis is unreliable if the engine doesn't correctly implement the rules
- Refactoring the effect system later requires revalidating every card

**Prevention:**
- Use a **data-driven effect system** from day one. Cards are data (JSON/YAML/Python dicts), not code branches
- Define a small set of primitive effects that compose: `deal_damage`, `heal`, `buff_stat`, `move_unit`, `draw_card`, `add_mana`, `destroy`, `summon_token`
- Implement an effect resolution queue with clear ordering (like MTG's stack): action -> React window -> React resolves -> original action resolves
- Each effect is a **Command object** (Command pattern) that can be executed, undone, and serialized -- this also enables game replays
- Multi-purpose cards: a card has a `play_effects` list (when deployed) and `react_effects` list (when played as React from hand). Same data structure, different trigger context
- The React mechanic: action resolves -> opponent gets a React window -> React effect pushes onto stack -> stack resolves LIFO

**Detection:**
- Adding a new card requires modifying more than 2 files
- Card interaction bugs appear regularly (impossible game states in training logs)
- Game engine code has functions longer than 100 lines with nested conditionals
- Developer avoids adding cards because "it might break something"

**Phase:** Phase 1 (game engine architecture). Architectural decision that must precede card implementation.

**Confidence:** HIGH -- Universally documented in TCG engine development resources and card game scripting discussions.

---

### Pitfall 5: Self-Play Training Collapse and Strategy Cycling

**What goes wrong:** During self-play training, the agent develops a dominant strategy (e.g., rush aggro), then evolves a counter-strategy, then a counter-counter, and eventually collapses back to a degenerate or trivially simple policy. The training loss looks fine but the agent plays poorly against novel strategies. Alternatively, both agents converge on a "draw every game" equilibrium that technically balances but produces uninteresting gameplay. Research on SPIRAL found that without variance reduction, policy gradient norms spike then collapse to near-zero, causing "thinking collapse" where agents abandon reasoning entirely.

**Why it happens:** Self-play in zero-sum games does not guarantee convergence to Nash equilibrium with standard RL algorithms (PPO, DQN). The training distribution is non-stationary (opponent keeps changing). Without explicit diversity pressure, the agent over-specializes against its current opponent version.

**Consequences:**
- Agent appears strong in self-play but loses to simple heuristic opponents
- Balance conclusions are unreliable (strategies cycle rather than converge)
- Training time is wasted on strategy oscillation
- Meta-discovery (Phase 4) produces noise rather than real insights

**Prevention:**
- Maintain a **league of past agent checkpoints**. Save checkpoints every N episodes and sample opponents from the pool: 50% latest agent, 30% recent agents, 20% random historical agents
- Use **Neural Fictitious Self-Play (NFSP)** or **PSRO (Policy-Space Response Oracles)** instead of naive self-play for imperfect information games
- Track exploitability metrics: periodically test the current agent against a set of fixed baseline strategies (random, greedy-aggressive, greedy-defensive, mana-hoarder) to ensure it isn't regressing on absolute quality
- Monitor for mode collapse: if win rate against all checkpoint opponents is >90%, the checkpoints are too similar and diversity must be injected
- Use Elo ratings across pool to track agent strength independently of cycling

**Detection:**
- Win rate against current opponent oscillates without upward trend
- Agent performance against fixed baselines degrades over training time
- Agent uses only 1-2 strategies despite having a diverse card pool
- Training curves show periodic spikes and crashes
- Win rate against the random baseline (should be >85%) degrades

**Phase:** Phase 1 (RL training infrastructure). Must be designed into the training loop architecture.

**Confidence:** HIGH -- Extensively documented in self-play RL research (NFSP, PSRO, AlphaStar league training, SPIRAL).

---

## Moderate Pitfalls

---

### Pitfall 6: Reward Function Misalignment

**What goes wrong:** The reward function incentivizes behavior that doesn't correspond to good play. Common mistakes: only rewarding win/loss at game end (too sparse -- agent can't learn which actions contributed to the outcome), rewarding damage dealt (agent ignores board control to deal face damage), rewarding cards played (agent dumps hand without strategy), or rewarding mana efficiency (agent never banks mana for big plays). Research shows agents sometimes learn to optimize shaped rewards while abandoning the actual objective.

**Prevention:**
- Start with **sparse rewards: +1 for win, -1 for loss, 0 everywhere else**. This is the ground truth objective
- Only add reward shaping if sparse training fails to converge after reasonable effort (500K+ games)
- If shaping is needed, use **potential-based reward shaping** (mathematically guaranteed to preserve the optimal policy). Shape based on change in advantage, not absolute values
- Never reward intermediate game metrics (damage dealt, cards played, mana spent) as primary rewards
- Always measure **win rate**, not just reward -- a high-reward agent that loses is broken
- Validate: does a known-good strategy (e.g., play strong cards, attack when advantageous) score higher than a known-bad strategy (e.g., pass every turn)?

**Detection:**
- Agent optimizes shaped reward but win rate doesn't improve
- Agent exhibits bizarre strategies (e.g., stalling games to farm intermediate rewards, dealing damage to own units)
- Removing reward shaping causes catastrophic performance drop (agent learned the shaping signal, not the game)

**Phase:** Phase 1 (RL environment). Start sparse, add shaping cautiously only in Phase 2 if needed.

**Confidence:** HIGH -- Reward shaping pitfalls are the most documented issue in applied RL.

---

### Pitfall 7: Incorrect Modeling of the React Interrupt Window

**What goes wrong:** The React mechanic (opponent plays a counter-card during your turn) doesn't fit neatly into standard turn-based RL environment abstractions. Developers either skip the React window (simplifying the game incorrectly), model it as a full separate turn (changing game pacing fundamentally), or implement it inconsistently (sometimes React is available, sometimes not, based on code paths rather than game state).

**Prevention:**
- Model the React window as a **sub-turn decision point** using PettingZoo's AEC (Agent Environment Cycle) API: agents alternate, including mid-turn react steps
- After the active player's action, the environment transitions to the opponent for a React-or-pass decision before completing the turn
- In the RL environment, `step()` alternates between players. The turn sequence is: Player A acts -> Player B reacts (or passes) -> turn ends -> Player B acts -> Player A reacts (or passes) -> turn ends
- The observation must encode whether we're in a React window (via a `TurnPhase` field: ACTION or REACT) so the agent knows the decision context
- During a React window, legal actions are: playable React cards the opponent can afford + PASS. Action masking handles this naturally
- Start testing with "pass-only" react to verify the turn flow works correctly before adding real react cards

**Detection:**
- Agent never learns to hold React cards (because the window isn't modeled or isn't visible)
- Agent always or never uses React cards (cost/benefit isn't learnable from the observation)
- Game replays show the React window being skipped or applied inconsistently across game states

**Phase:** Phase 1 (game engine + environment). The React mechanic is a core differentiator of Grid Tactics TCG.

**Confidence:** MEDIUM -- React/counter mechanics are well understood in TCG design but have limited specific documentation in RL-for-games literature. PettingZoo's AEC API is the closest standard pattern.

---

### Pitfall 8: Spatial Representation That Loses Positional Information

**What goes wrong:** The 5x5 grid is flattened into a 1D vector for the observation space, destroying the spatial relationships between units. The agent cannot learn positional strategies like "place ranged units behind tanks" or "block the opponent's advance through the center" because adjacency and range relationships are not encoded in the observation structure. Research shows coarse-grained representations lose tactical detail and produce overly simplistic learned strategies.

**Prevention:**
- Represent the board as a **multi-channel 2D grid**: shape `(5, 5, C)` where C channels encode unit properties (attack, health, owner, card_type, has_effects, is_empty)
- Use a **CNN** (convolutional neural network) as the observation encoder -- designed for spatial pattern recognition
- Encode range as a property visible in the grid, not as a separate scalar
- Consider including derived channels: which cells a unit can attack from its current position, valid movement targets, threat zones
- Augment with non-spatial features (mana, hand cards, HP) as a separate vector, concatenated after the CNN encoder
- The 5x5 grid is small enough that even a shallow CNN (2-3 layers) will capture all spatial patterns

**Detection:**
- Agent doesn't learn to position ranged units behind melee units (a core spatial strategy per PROJECT.md)
- Agent places units randomly on the grid with no spatial reasoning
- Adding range/positioning mechanics doesn't change learned behavior
- Agent performs equally well with shuffled grid positions (spatial info not being used)

**Phase:** Phase 1 (observation space design). The observation encoding determines what the agent can and cannot learn.

**Confidence:** MEDIUM -- Grid-based RL research strongly supports CNN encoding for spatial tasks, but this specific TCG+grid combination has limited prior art.

---

### Pitfall 9: Game Engine Tightly Coupled to RL Framework

**What goes wrong:** Game logic is interleaved with RL training code. The game engine imports PyTorch or TensorFlow. The `step()` function contains both game rules and reward calculation. Changing the RL algorithm requires modifying the game engine, and vice versa. Cannot test the game without installing ML libraries.

**Prevention:**
- Three clean layers with **no circular dependencies**:
  1. **Game engine** -- pure Python + numpy only. Exposes `reset()`, `step(action)`, `get_legal_actions()`, `get_observation(player)`, `is_terminal()`, `get_winner()`. Zero ML imports
  2. **RL environment wrapper** -- imports game engine + gymnasium/pettingzoo. Handles observation encoding, action decoding, reward calculation, action masking. This is the adapter layer
  3. **Training script** -- imports RL environment + ML framework (SB3, etc). Handles agent creation, training loops, logging, checkpointing
- The game engine should be usable standalone: testable without ML libraries, playable via CLI for manual verification, usable for non-RL purposes (e.g., rule validation, game simulation)
- RLCard uses exactly this pattern and it is proven to work

**Detection:**
- Cannot run a game without importing ML libraries
- Cannot switch from PPO to DQN without modifying the game engine
- Game engine unit tests require ML framework installation
- Single file contains both game rules and neural network code

**Phase:** Phase 1 (architecture). Establish layer boundaries before writing code.

**Confidence:** HIGH -- Standard software engineering practice, confirmed by RLCard's architecture.

---

### Pitfall 10: Card Pool Too Complex for Initial RL Training

**What goes wrong:** Starting with 40+ unique cards with complex effects, range mechanics, multi-purpose cards, and react interactions. The agent can't learn basic strategy because the combinatorial complexity of card interactions overwhelms the learning signal. Training doesn't converge or converges to trivially simple strategies (always play the cheapest card).

**Prevention:**
- Start with a **minimal card pool**: 5-8 simple cards (vanilla minions with varying attack/health/cost stats, one simple damage spell, one simple buff)
- Verify RL learns **basic strategy** with the simple set first: does it learn to play cards? To attack? To bank mana for expensive cards? To move units toward the opponent's side?
- Gradually add complexity in validated stages: ranged units -> simple React cards -> multi-purpose cards -> complex effects
- Each addition should be validated: does the agent still converge? Does it learn to use the new mechanic?
- This is the "RL before game polish" principle from PROJECT.md applied concretely

**Detection:**
- Agent with full card pool performs no better than random after substantial training
- Agent ignores complex cards entirely (always plays cheapest/simplest)
- Training time increases dramatically with card pool size without corresponding strategy improvement

**Phase:** Phase 1 (start simple), Phase 2 (expand validated).

**Confidence:** HIGH -- Standard RL curriculum learning principle, confirmed by card game RL research.

---

### Pitfall 11: Non-Deterministic Game Engine Breaks Reproducibility

**What goes wrong:** Training runs produce different results with the same seed. Bugs are unreproducible. A/B testing of card balance changes is impossible because variance from nondeterminism exceeds the signal from the change being tested.

**Prevention:**
- Use a seeded `numpy.random.Generator` instance (not the global `random` module or `numpy.random.seed()`) for all randomness: shuffling decks, resolving random effects
- Pass the RNG as a parameter to the game engine, never use module-level random state
- Set seeds **before** environment creation, not after
- Implement a `replay_game(seed, actions)` function that deterministically replays any game from a seed and action sequence
- Verify determinism with a test: run the same game 100 times with the same seed and actions, assert identical outcomes
- Log the per-game seed with results so any training game can be replayed for debugging

**Detection:**
- Same seed + same actions produces different game outcomes
- Training curves are not reproducible between runs with identical hyperparameters and seeds
- Bug reports cannot be reproduced ("it only happens sometimes")

**Phase:** Phase 1 (game engine). Must be baked into the engine's RNG handling from the start.

**Confidence:** HIGH -- PyTorch and Gymnasium documentation both emphasize seeded RNG management.

---

### Pitfall 12: Slow Training Due to Python Game Engine

**What goes wrong:** The game engine is pure Python with per-step overhead (object creation, method calls, deep copies). Each complete game takes 50-200ms. Training 1M games takes 14-55+ hours. Iteration on card balance becomes impractical. Research shows environment simulation speed -- not neural network training -- is the primary bottleneck in RL pipelines. In one study, Python simulation ran at 2,000 steps/sec while the neural network training required less than a minute total.

**Prevention:**
- **Profile early** (cProfile or py-spy). Identify hot paths before optimizing blindly
- Use **numpy arrays** for board state (`(5, 5, C)` array), not nested Python objects
- Minimize allocations in the inner loop: reuse arrays, avoid unnecessary copies of game state per step
- Implement **undo-based state management** instead of deep-copying the entire game state for each step
- Use `gymnasium.vector.SyncVectorEnv` or `SubprocVecEnv` to run 8-16 games in parallel
- Target: **10,000+ game steps per second** on a single core as minimum viable speed
- If still too slow after optimization: Cython or Numba JIT for legal action generation and board state updates
- Deferred: JAX/Pgx-style vectorized engines can achieve 100x but require a full rewrite (only if needed)

**Detection:**
- Profile shows >90% of training wall-clock time is in `env.step()`, not neural network
- A single complete game takes >50ms to simulate
- Training a baseline agent takes >24 hours

**Phase:** Design for speed in Phase 1, optimize aggressively at start of Phase 2 when training volume increases.

**Confidence:** HIGH -- Multiple sources confirm simulation speed is the primary RL training bottleneck.

---

## Minor Pitfalls

---

### Pitfall 13: Overlooking Draw-as-Action in the Action Economy

**What goes wrong:** In Grid Tactics TCG, drawing a card costs an action (not automatic per turn). Developers may implement draw as a free per-turn event (standard in most card games) or forget to include "draw" in the RL action space. This fundamentally changes the game's strategic tension between using your action to draw vs. play/move/attack.

**Prevention:**
- "Draw a card" must be an explicit action in the action space, equal to play/move/attack/pass
- The RL agent should discover when drawing is optimal vs. acting -- this is a core strategic dimension
- Verify: agent sometimes chooses draw over available plays (it should, when hand is depleted or saving for combo)

**Phase:** Phase 1 (game rules implementation). Directly specified in PROJECT.md.

**Confidence:** HIGH.

---

### Pitfall 14: Mana Banking Creates Degenerate Stalling

**What goes wrong:** The mana banking mechanic (unspent mana carries over) allows agents to discover a "bank until full, then one-turn-kill" strategy that dominates all others. If this strategy is too strong, it reduces the game to "who banks better" rather than tactical grid combat.

**Prevention:**
- Make the mana cap a **configurable parameter** from Phase 1 (even if initially uncapped)
- Track mana banking patterns in training analytics: average mana banked per turn by winning agents
- If >70% of winning games involve banking 5+ consecutive turns with no plays, the mechanic needs a cap
- Use RL to discover the right cap value by training with different caps and comparing strategic diversity
- This is exactly the kind of balance question the RL system should answer

**Phase:** Phase 2 (card balance discovery). Engine must support configurable mana caps from Phase 1.

**Confidence:** MEDIUM -- Theoretical concern; RL will reveal whether it's real.

---

### Pitfall 15: PettingZoo / SB3 / Gymnasium Version Incompatibility

**What goes wrong:** PettingZoo, SuperSuit, SB3, sb3-contrib, and Gymnasium must be mutually compatible. A version mismatch causes cryptic import errors or API mismatches at runtime. The ecosystem has undergone significant API changes (OpenAI Gym -> Gymnasium migration).

**Prevention:**
- Pin exact versions in `requirements.txt` or `pyproject.toml` after verifying compatibility
- Test the full stack integration early: create a minimal 2-player environment, wrap with SuperSuit, train with MaskablePPO for 100 episodes
- Verify compatibility before starting: PettingZoo 1.25+ requires Gymnasium >=1.0; SB3 2.x requires Gymnasium >=1.0
- Avoid Python 3.13 if PettingZoo has constraints

**Phase:** Phase 1 (initial setup). Resolve before writing any code.

**Confidence:** HIGH -- Documented in GitHub issues for all three libraries.

---

### Pitfall 16: Not Logging Enough Training Metadata

**What goes wrong:** After a promising training run, it can't be reproduced because hyperparameters, card pool version, observation space schema, or reward function variant weren't recorded. Two weeks later, "which run produced the good agent?" is unanswerable.

**Prevention:**
- Log at training start: full hyperparameter dict, card pool hash/version, observation/action space shapes, reward function description, git commit hash, random seed
- Use W&B (Weights and Biases) or MLflow for experiment tracking -- they capture this automatically
- If using TensorBoard only, write a metadata JSON alongside training logs
- Name training runs descriptively: `2026-04-15_mana-cap-5_simple-pool_sparse-reward`

**Phase:** Phase 1 (training infrastructure). Trivial to set up, painful to add retroactively.

**Confidence:** HIGH.

---

### Pitfall 17: SQLite Write Contention During Parallel Training

**What goes wrong:** Writing game results to SQLite after every game creates a bottleneck. SQLite uses file-level locking. With SubprocVecEnv running multiple processes, writes contend and training stalls on I/O.

**Prevention:**
- Buffer writes: accumulate results in memory, flush to SQLite every 100-1000 games
- Each subprocess writes to its own queue; main process aggregates and writes
- Use WAL mode (`PRAGMA journal_mode=WAL`) for concurrent read (dashboard) / write (training)
- For the dashboard, write aggregated stats (per-card win rates over N games), not raw per-game data

**Phase:** Phase 2 (when parallel training begins). Design the schema for batch writes from Phase 1.

**Confidence:** MEDIUM.

---

### Pitfall 18: Premature Neural Network Architecture Optimization

**What goes wrong:** Weeks spent tuning CNN architectures, attention layers, or transformer-based policies before the game engine and basic training pipeline work. Architecture becomes tightly coupled to an incomplete observation space that will change.

**Prevention:**
- Start with SB3's default MLP policy. A 5x5 grid flattened to a vector + MLP will learn basic strategy
- Upgrade to CNN + MLP hybrid only after the full pipeline (engine -> environment -> training -> evaluation) is validated end-to-end
- Architecture search is Phase 2+ work, after observation space is stable

**Phase:** Phase 2 at earliest. Phase 1 uses simple defaults.

**Confidence:** HIGH.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Game engine | Rule bugs corrupt training (#1) | Exhaustive unit tests, property-based testing, random-agent smoke tests |
| Phase 1: Game engine | Hidden info leak (#2) | Separate GameState from PlayerObservation from day one |
| Phase 1: Game engine | Effect system spaghetti (#4) | Data-driven effect system, Command pattern |
| Phase 1: Game engine | React window modeled wrong (#7) | PettingZoo AEC sub-turn, TurnPhase enum |
| Phase 1: Game engine | Draw not an action (#13) | Explicit draw action in action space |
| Phase 1: Game engine | Non-deterministic RNG (#11) | Seeded numpy.random.Generator, replay system |
| Phase 1: RL environment | Action space explosion (#3) | Action masking with MaskablePPO |
| Phase 1: RL environment | Spatial info lost (#8) | Multi-channel 2D grid observation + CNN |
| Phase 1: RL environment | Engine-RL coupling (#9) | Three-layer architecture, zero ML imports in engine |
| Phase 1: RL training | Self-play collapse (#5) | Agent pool/league from day one, fixed baselines |
| Phase 1: RL training | Reward misalignment (#6) | Sparse rewards only, add shaping cautiously |
| Phase 1: Stack setup | Version incompatibility (#15) | Pin versions, test integration early |
| Phase 2: Card balance | Slow engine (#12) | Profile and optimize before mass training |
| Phase 2: Card balance | Too many cards (#10) | Start minimal, validate before expanding |
| Phase 2: Card balance | Mana banking degeneracy (#14) | Configurable mana cap, track banking patterns |
| Phase 2: Training infra | SQLite contention (#17) | Buffered writes, WAL mode |
| Phase 2: Training infra | Missing metadata (#16) | W&B or MLflow from first real training run |
| Phase 3: Deck composition | Architecture bias (#18) | Test 2+ architectures before drawing conclusions |
| Phase 4: Meta discovery | Strategy cycling (#5) | NFSP or PSRO, exploitability monitoring |

---

## Sources

- [RLCard: A Toolkit for Reinforcement Learning in Card Games](https://rlcard.org/) -- Environment design patterns, state extraction, multi-agent coordination
- [RLCard Paper (IJCAI 2020)](https://www.ijcai.org/proceedings/2020/0764.pdf) -- Observation encoding, card game environment abstraction
- [Deep RL from Self-Play in Imperfect-Information Games (Heinrich & Silver)](https://arxiv.org/pdf/1603.01121) -- NFSP, training stability
- [SPIRAL: Self-Play on Zero-Sum Games](https://arxiv.org/html/2506.24119v1) -- Training collapse, variance reduction
- [A Survey on Self-play Methods in RL](https://arxiv.org/html/2408.01072v1) -- Strategy cycling, league training
- [Action Masking in Gymnasium](https://gymnasium.farama.org/tutorials/training_agents/action_masking_taxi/) -- Masking implementation
- [Maskable PPO (SB3-Contrib)](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) -- Action masking with PPO
- [PettingZoo Action Masking Tutorial](https://pettingzoo.farama.org/tutorials/custom_environment/3-action-masking/) -- Multi-agent masking, AEC API
- [Reward Shaping for Improved Learning](https://ar5iv.labs.arxiv.org/html/2311.16339) -- Reward shaping pitfalls, potential-based shaping
- [Comprehensive Overview of Reward Engineering](https://arxiv.org/html/2408.10215v1) -- Reward misalignment, reward hacking
- [Overcooked Training Performance](https://bsarkar321.github.io/blog/overcooked_madrona/index.html) -- Python simulation bottleneck (2K vs 2M steps/sec)
- [Speed Up Python RL Environments](https://medium.com/blackhc/a-way-to-speed-up-python-rl-environments-b9dd462c0df1) -- Python environment optimization
- [PyTorch Reproducibility](https://docs.pytorch.org/docs/stable/notes/randomness.html) -- Seed management, deterministic training
- [Grid-Wise Control for Multi-Agent RL](https://proceedings.mlr.press/v97/han19a/han19a.pdf) -- CNN spatial encoding for grids
- [Simulation-Driven Balancing with RL](https://arxiv.org/html/2503.18748v1) -- RL for game balance, degenerate strategies
- [Learning to Beat ByteRL: Exploitability of CCG Agents](https://arxiv.org/html/2404.16689v1) -- Agent robustness, exploitability
- [Card Game Design as Systems Architecture](https://critpoints.net/2023/05/26/card-game-design-as-systems-architecture/) -- Effect system design, stack resolution
- [Game Architecture for Card Game Model](https://bennycheung.github.io/game-architecture-card-ai-1) -- Component architecture
- [Two-Step RL for Multistage Strategy Card Game](https://arxiv.org/html/2311.17305v1) -- Action space decomposition
- [Invalid Action Masking Proposal (Gymnasium)](https://github.com/openai/gym/issues/2823) -- Masking vs penalty discussion
- [RLCard Development Guide](https://rlcard.org/development.html) -- Custom environment implementation patterns
