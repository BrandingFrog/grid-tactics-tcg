<!-- GSD:project-start source:PROJECT.md -->
## Project

**Grid Tactics TCG**

A fantasy trading card game on a 5x5 grid with RL-driven strategy discovery. Players deploy minions, cast magic, and use react cards. GPU tensor engine trains at 100K+ FPS on RunPod 4090s, streaming results to Supabase PostgreSQL. Live analytics dashboard on Vercel.

**Core Value:** The RL engine that discovers and validates game strategies.

### Current Rules
- **Auto-draw** at turn start (mandatory), then one action (play/move/attack/sacrifice/pass)
- **Forward-only movement** in lane (same column), attacks any direction
- **React window** after each action — opponent can counter
- **Win by sacrifice** (minion crosses board) or **HP depletion**
- 19 cards: 11 minions, 4 magic, 3 react, 1 multi-purpose. Elements: Wood, Fire, Earth, Water, Metal, Dark, Light.

### Constraints
- **Language**: Python for game engine and RL
- **Training**: GPU tensor engine (PyTorch) on RunPod, NOT SB3's built-in loop
- **Data**: Supabase PostgreSQL (not SQLite) for cloud training + live dashboard
- **Dashboard**: Vercel static site (not Streamlit)
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Python Version
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.12 | Runtime | Sweet spot: all key libraries require >=3.10 (PyTorch 2.11, SB3 2.8, Gymnasium 1.2, NumPy 2.4). 3.12 is mature, fast (10-15% faster than 3.11), and avoids bleeding-edge 3.13/3.14 compatibility surprises. |
## Recommended Stack
### Game Engine Layer
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| NumPy | >=2.2,<3.0 | Game state arrays, observation encoding | All RL libraries depend on NumPy. Game board (5x5 grid), card stats, and hand/deck state are naturally array-shaped. Pin to >=2.2 to support Python 3.12 while allowing minor upgrades. |
| dataclasses (stdlib) | -- | Card, Player, GameState modeling | Zero-dependency, fast, immutable-friendly (`frozen=True`). Cards and game rules are data-heavy but don't need runtime validation -- the game engine validates moves. Pydantic adds unnecessary overhead here. |
| enum (stdlib) | -- | Card types, game phases, action types | Type-safe constants for `CardType.MINION`, `ActionType.MOVE`, `Phase.REACT_WINDOW`, etc. |
### Reinforcement Learning Core
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Gymnasium | >=1.2,<2.0 | RL environment API standard | The Farama Foundation standard. All RL libraries target this API. Custom environments implement `step()`, `reset()`, `observation_space`, `action_space`. Required by SB3 and PettingZoo. |
| PettingZoo | >=1.25,<2.0 | Multi-agent (2-player) environment wrapper | "Gymnasium for multi-agent RL." The AEC (Agent-Environment-Cycle) API is purpose-built for turn-based games where agents act sequentially -- exactly the Grid Tactics turn model. Provides `agent_iter()`, legal action tracking, and reward per agent. |
| SuperSuit | >=3.9 | Environment preprocessing wrappers | Bridges PettingZoo environments to SB3's vectorized environment API via `ss.pettingzoo_env_to_vec_env_v1()`. Also provides observation normalization and padding utilities. |
### RL Training
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Stable-Baselines3 | >=2.8,<3.0 | RL algorithm implementations (PPO) | Best single-agent RL library. Clean API, excellent docs, PyTorch-based. Empirical research (Oct 2025 arXiv:2503.22575) shows SB3's PPO achieves superhuman performance in 50% of trials, outperforming RLlib (<15%). For a single-machine project, SB3's simplicity beats RLlib's distributed complexity. |
| sb3-contrib | >=2.8,<3.0 | MaskablePPO for action masking | **Critical for this project.** Card games have variable legal actions per turn. MaskablePPO prevents the agent from selecting invalid actions (playing cards you can't afford, moving to occupied tiles, attacking out of range). Without action masking, the agent wastes enormous training time learning what's illegal. |
| PyTorch | >=2.10,<3.0 | Neural network backend | SB3's backend. PyTorch 2.11 is current. Don't install separately -- SB3 pulls the right version as a dependency. Listed here for awareness. |
### RL Monitoring & Experiment Tracking
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| TensorBoard | >=2.18 | Training metrics visualization | Ships with SB3 integration out of the box. Logs reward curves, loss, episode length. Zero config: pass `tensorboard_log="./tb_logs"` to any SB3 model. |
| Weights & Biases (wandb) | >=0.19 | Experiment tracking, hyperparameter sweeps | Optional but recommended for Phase 2+. W&B's SB3 integration records metrics, saves model checkpoints, logs hyperparameters, and enables experiment comparison across runs. Free tier is sufficient. |
### Dashboard & Data
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Supabase PostgreSQL | -- | Cloud database for training data | Multi-pod training writes to shared DB. Live dashboard reads via REST API. Realtime subscriptions for auto-updates. Replaced SQLite for cloud training. |
| Vercel | -- | Static dashboard hosting | Zero-config deploy, global CDN, auto-SSL. Replaced Streamlit for always-on public dashboard. |
| Chart.js | 4.x | Dashboard charts | Lightweight, renders in browser. Win rate curves, loss charts, bar charts. |
| supabase-py | 2.x | Python DB client | Training script writes to Supabase. REST API (not direct PostgreSQL) due to IPv6 network constraints. |
| supabase-js | 2.x | Browser DB client | Dashboard reads from Supabase with anon key. Realtime subscriptions for live updates. |
| JSON files | -- | Card definitions | Human-readable, version-controllable card data in `data/cards/`. |
### Cloud Training
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| RunPod | -- | GPU cloud (RTX 4090) | On-demand 4090s at $0.59/hr. Auto-tune fills 24GB VRAM with 32K parallel games. |
| tensor_train.py | -- | GPU-native PPO training | Custom training loop bypassing SB3. Collects rollouts on GPU via tensor engine, 100K+ FPS. |
| deploy_runpod.py | -- | Pod deployment | Downloads code from Supabase Storage, installs deps, starts training with env vars. |
### Testing & Quality
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| pytest | >=8.0 | Test framework | Standard. Test game rules exhaustively (legal moves, mana costs, combat resolution, react windows). Test RL environment (observation shapes, reward values, termination conditions). |
| pytest-cov | >=5.0 | Coverage reporting | Game engine needs high coverage -- bugs in rules corrupt RL training data silently. |
| mypy | >=1.13 | Static type checking | Catch type errors in game state manipulation before they become RL training corruption. Type annotations on Card, GameState, Action are essential. |
| ruff | >=0.9 | Linting and formatting | Fast, replaces flake8+black+isort. Single tool for code quality. |
## Alternatives Considered
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| RL Framework | Stable-Baselines3 | RLlib (Ray) | RLlib is designed for distributed training across clusters. Grid Tactics trains on a single machine. RLlib's abstractions are deep and hard to customize. Empirical evidence shows worse PPO performance than SB3. Only choose RLlib if training takes days and you need GPU clusters. |
| RL Framework | Stable-Baselines3 | CleanRL | CleanRL is educational -- single-file implementations meant to be read, not imported. No library API. You'd copy-paste and modify code. Good for learning, bad for a production game engine. |
| RL Framework | Stable-Baselines3 | TorchRL | PyTorch's official RL library. Powerful but immature -- had compatibility issues with Gymnasium >=1.0 as recently as Jan 2025. API is more complex than SB3. Revisit if SB3 hits limitations. |
| RL Framework | Stable-Baselines3 | RLCard | Purpose-built for card games (poker, UNO). But it imposes its own game abstraction that doesn't fit Grid Tactics' grid-based positioning and react system. You'd fight the framework. |
| Multi-agent | PettingZoo | OpenSpiel (DeepMind) | OpenSpiel has a broader game theory focus (extensive-form games, normal-form games). More academic, C++ core with Python bindings. PettingZoo is pure Python, simpler API, better SB3 integration. |
| Dashboard | Vercel + vanilla JS | Streamlit | Streamlit requires a running Python server. Vercel is static, free, always-on. Supabase JS client handles data fetching. |
| Dashboard | Vercel + vanilla JS | Next.js | Overkill for a data dashboard. Single HTML file with Chart.js is simpler and faster to iterate. |
| Data modeling | dataclasses | Pydantic | Pydantic adds runtime validation overhead on every object creation. In RL training, you create millions of game states. The game engine itself validates legality. Pydantic's strengths (API input validation, serialization) aren't needed here. |
| Database | Supabase PostgreSQL | SQLite | Multiple RunPod pods write concurrently. Cloud DB enables live dashboard. SQLite was used initially but doesn't work for multi-pod cloud training. |
| Algorithm | MaskablePPO | DQN | PPO is on-policy and handles continuous/discrete mixed action spaces better. DQN requires a replay buffer and struggles with large discrete action spaces. MaskablePPO's action masking is the decisive advantage for card games. |
## Installation
# Create virtual environment
# Core game engine (no heavy dependencies)
# RL training stack
# Dashboard
# Optional: experiment tracking
# Dev dependencies
# Pin with a requirements file
### Recommended: Use `pyproject.toml` for dependency management
## Architecture

### Two Game Engines
1. **Python engine** (`src/grid_tactics/`) — Immutable dataclass-based. Used for tests and correctness verification.
2. **Tensor engine** (`src/grid_tactics/tensor_engine/`) — PyTorch batched tensors. Runs N games simultaneously on GPU. Used for training.

### Key Integration Points
- **Tensor Engine -> Training**: `tensor_train.py` calls `engine.step_batch(actions)` for all N games in parallel, collects rollouts on GPU, runs PPO gradient updates.
- **Training -> Supabase**: `supabase-py` REST client writes training_runs, training_snapshots, card_stats, game_results to PostgreSQL.
- **Supabase -> Dashboard**: Vercel HTML page reads via `supabase-js` anon key. Realtime subscriptions auto-refresh.
- **Code Deploy**: `deploy_runpod.py` uploads tarball to Supabase Storage, RunPod pods download and run.
- **Action Masking**: Legal action mask [N, 1262] computed on GPU by `legal_actions.py`. Prevents agent from selecting illegal actions.
## Version Compatibility Matrix
| Package | Version | Python Requirement | Notes |
|---------|---------|-------------------|-------|
| Python | 3.12 | -- | Target runtime |
| NumPy | 2.4.x | >=3.11 | OK with 3.12 |
| PyTorch | 2.11.x | >=3.10 | OK with 3.12 |
| Gymnasium | 1.2.x | >=3.10 | OK with 3.12 |
| PettingZoo | 1.25.x | >=3.9,<3.13 | OK with 3.12. Note: upper bound <3.13 |
| SuperSuit | 3.9.x | matches PettingZoo | OK with 3.12 |
| Stable-Baselines3 | 2.8.x | >=3.10 | OK with 3.12 |
| sb3-contrib | 2.8.x | >=3.10 | OK with 3.12 |
| Streamlit | 1.56.x | >=3.10 | OK with 3.12 |
| Plotly | 6.6.x | >=3.8 | OK with 3.12 |
| pandas | 2.2.x | >=3.9 | OK with 3.12 |
## What NOT to Use
| Technology | Why Not |
|------------|---------|
| Pygame | No value for RL training. The game has no visual rendering needed. If visualization is needed later, the Streamlit dashboard handles it. Pygame adds complexity for a visual layer that doesn't feed RL. |
| OpenAI Gym (old) | Deprecated. Gymnasium (Farama Foundation) is the successor. Gym is unmaintained since 2022. |
| TensorFlow/Keras | SB3 is PyTorch-only. Mixing frameworks creates dependency hell. Stick to PyTorch ecosystem. |
| Docker (initially) | Adds deployment complexity before there's anything to deploy. Add Docker for the dashboard when it's ready to share, not during development. |
| MongoDB/Redis | Supabase PostgreSQL handles everything. No need for additional databases. |
| FastAPI/Flask | No API server needed. Dashboard reads directly from Supabase REST API. |
| Jupyter Notebooks (for core code) | Fine for exploration, but game engine and RL code must be in proper `.py` modules for testing, importing, and version control. Use notebooks only for one-off analysis. |
## Sources
- [PettingZoo PyPI](https://pypi.org/project/pettingzoo/) -- version 1.25.0 (April 2025), confirmed Python <3.13
- [Stable-Baselines3 GitHub releases](https://github.com/DLR-RM/stable-baselines3/releases/tag/v2.8.0) -- version 2.8.0 (April 2026)
- [sb3-contrib PyPI](https://pypi.org/project/sb3-contrib/) -- version 2.8.0 (April 2026), MaskablePPO
- [Gymnasium PyPI](https://pypi.org/project/gymnasium/) -- version 1.2.3 (December 2025)
- [PyTorch PyPI](https://pypi.org/project/torch/) -- version 2.11.0 (March 2026)
- [Streamlit PyPI](https://pypi.org/project/streamlit/) -- version 1.56.0 (March 2026)
- [Plotly PyPI](https://pypi.org/project/plotly/) -- version 6.6.0 (March 2026)
- [NumPy PyPI](https://pypi.org/project/numpy/) -- version 2.4.4 (March 2026)
- [SB3 MaskablePPO docs](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html)
- [PettingZoo AEC API](https://pettingzoo.farama.org/api/aec/)
- [PettingZoo SB3 tutorial](https://pettingzoo.farama.org/tutorials/sb3/index.html)
- [arXiv:2503.22575](https://arxiv.org/html/2503.22575v2) -- PPO implementation comparison (SB3 vs RLlib performance)
- [SB3 Custom Environments](https://stable-baselines3.readthedocs.io/en/master/guide/custom_env.html)
- [W&B SB3 Integration](https://docs.wandb.ai/guides/integrations/stable-baselines-3/)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

- **Card definitions**: JSON files in `data/cards/`, one per card. Loaded by `CardLibrary.from_directory()`.
- **Card text stat notation** (locked 2026-04-08): Use 🗡️ (dagger) for **attack** and 🤍 (heart) for **HP/health** in all player-facing text. Applies uniformly to both minion health and player life pool — one glyph, reads clearer. Examples: `+5🗡️`, `+5🤍`, `+1🗡️/+1🤍`, `3🗡️/8🤍`, `player takes 5🤍 damage`, `0🤍 = defeat`. Do NOT use words like "attack"/"ATK"/"HP" or the shield emoji (🛡️) — shield was used briefly on 2026-04-07 and replaced with 🤍 for clarity. Engine field names (`attack`, `health`, `hp`, `attack_bonus`) stay as-is.
- **Keyword glossary**: `data/GLOSSARY.md` is the source of truth for all card keywords. When adding/changing/removing keywords, update BOTH `data/GLOSSARY.md` AND the `KEYWORD_GLOSSARY` object in `src/grid_tactics/server/static/game.js`. Always keep them in sync.
- **Enums**: IntEnum for all game constants (numpy/tensor compatible). New values append to end.
- **Immutable state**: Python engine uses frozen dataclasses + `replace()`. Tensor engine mutates in-place.
- **Action space**: 1262 discrete actions. Layout: PLAY_CARD[0:250], MOVE[250:350], ATTACK[350:975], SACRIFICE[975:1000], DRAW[1000], PASS[1001], REACT[1002:1262]. DRAW is reserved but no longer legal (auto-draw at turn start).
- **Forward movement**: Minions move forward only (P1 down, P2 up) in their column. Attacks any direction.
- **Testing**: 500+ tests via pytest. Run `pytest tests/ -q` for quick check.
- **Deploy flow**: Edit code -> rebuild tarball -> upload to Supabase Storage -> terminate pods -> `deploy_runpod.py` launches fresh pods.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
