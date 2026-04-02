<!-- GSD:project-start source:PROJECT.md -->
## Project

**Grid Tactics TCG**

A fantasy trading card game played on a 5x5 grid where players deploy minions, cast magic, and use react cards to outmaneuver opponents. The primary purpose of this project is to build a reinforcement learning system in Python that discovers optimal play strategies, validates card balance, and eventually serves as the game's AI opponent. A stats dashboard provides a user-friendly UI for analyzing RL results.

**Core Value:** The reinforcement learning engine that discovers and validates game strategies — every other component (game rules, cards, UI) exists to feed and display RL insights.

### Constraints

- **Language**: Python for game engine and RL
- **RL focus**: Core strategy discovery is the priority — card balance and composition come later
- **Testing**: Each development step validated with RL to confirm strategic depth
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
### Stats Dashboard
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Streamlit | >=1.56,<2.0 | Web-based stats dashboard | Fastest path from Python data to interactive web UI. No HTML/CSS/JS required. Built-in charting with `st.line_chart`, `st.bar_chart`. Supports Plotly figures natively. Live reload during development. Data scientists' standard tool. |
| Plotly | >=6.6,<7.0 | Interactive charts for RL analysis | Richer charts than Streamlit's built-ins: heatmaps for board positions, scatter plots for card balance, animated replays. Plotly figures embed directly in Streamlit via `st.plotly_chart()`. |
### Data Persistence
| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| SQLite (stdlib) | -- | Game results, card statistics, RL metrics | Zero-config, single-file database. Perfect for a single-machine project. Store game outcomes, per-card win rates, mana curves, action distributions. No server to manage. |
| JSON files | -- | Card definitions, deck configurations | Human-readable, version-controllable card data. Load card pool from JSON, not hardcoded classes. Enables rapid balance iteration. |
| CSV / Parquet | -- | Training run exports, bulk analysis | Pandas-friendly export format for offline analysis. Parquet for large training datasets (millions of games). |
| pandas | >=2.2 | Data manipulation for dashboard | Powers the data layer between SQLite storage and Streamlit display. Aggregations, filtering, pivots for stats analysis. |
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
| Dashboard | Streamlit | Dash (Plotly) | Dash gives more UI control but requires callback architecture (Flask-like). Streamlit's script-based model is simpler for a stats dashboard. Dash is better for enterprise apps with complex interactivity. |
| Dashboard | Streamlit | Panel (HoloViz) | Panel integrates deeply with HoloViews/Bokeh ecosystem. Overkill for this project. Streamlit's larger community means more examples and faster problem-solving. |
| Dashboard | Streamlit | Gradio | Gradio is ML-model-demo focused (input -> output). Not designed for data exploration dashboards with multiple pages, filters, and historical data. |
| Data modeling | dataclasses | Pydantic | Pydantic adds runtime validation overhead on every object creation. In RL training, you create millions of game states. The game engine itself validates legality. Pydantic's strengths (API input validation, serialization) aren't needed here. |
| Database | SQLite | PostgreSQL | PostgreSQL requires a server process and administration. SQLite is embedded, zero-config, and handles the read patterns (dashboard queries) fine. Only switch if you need concurrent writes from multiple processes. |
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
## Architecture Implications
### Separation of Concerns
### Key Integration Points
- **Game Engine -> RL**: The PettingZoo AEC environment wraps the game engine. It calls `game.get_legal_actions()` to produce the action mask, `game.step(action)` to advance state, and `game.get_observation()` to produce the numpy observation array.
- **RL -> Dashboard**: Training writes results to SQLite (game outcomes, per-card stats, model checkpoints). Dashboard reads from SQLite.
- **Action Masking**: `sb3-contrib.MaskablePPO` requires the environment to provide `action_masks()` returning a boolean numpy array. The game engine must expose legal actions efficiently.
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
| MongoDB/Redis | Over-engineered for single-machine training. SQLite handles the data volume. |
| FastAPI/Flask | No API needed. The dashboard reads directly from SQLite. Only add an API if the dashboard and training run on separate machines. |
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

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
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
