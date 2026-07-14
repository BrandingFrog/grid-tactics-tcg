# Grid Tactics TCG

Grid Tactics is a two-player tactical card game played on a 5x5 board. The active product combines a Python rules engine, a Flask-SocketIO PvP server, a browser client, AI opponents, and an experimental reinforcement-learning stack.

## Quick start

1. Create a Python 3.12 virtual environment.
2. Install the PvP and development dependencies: `pip install -e ".[pvp,dev]"`.
3. Start the game with `python pvp_server.py`.
4. Open `http://127.0.0.1:5000/`.

The action-bank/REST rules are the default for live, headless, and RL play. Set `GT_MANUAL_DRAW=0` only to run the legacy one-action engine rules.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/grid_tactics/` | Rules engine, AI/RL integration, persistence, and PvP server package |
| `src/grid_tactics/server/static/` | Browser game client, CSS, artwork, and sound |
| `data/` | Card definitions and local/generated game and training data |
| `docs/` | Maintained rules, design notes, and deployment guides |
| `tests/` | Unit, integration, server, JavaScript-contract, and end-to-end tests |
| `scripts/` | Maintenance, data-generation, debugging, and verification utilities |
| `assets/` | Source card artwork used by tooling and documentation |
| `wiki/` | Separately deployable game wiki |
| `web-dashboard/` | Static Supabase analytics dashboard for Vercel |
| `.planning/` | GSD roadmap, phase plans, decisions, and debugging evidence |
| `artifacts/` | Local-only browser captures and temporary investigation output |

The only root-level Python entrypoint is `pvp_server.py`, which Railway starts directly. Developer-operated utilities live in `scripts/`, and Windows launchers live in `scripts/windows/`.

Start with [`docs/README.md`](docs/README.md) for maintained project documentation. Historical planning evidence remains under `.planning/` and is not part of the current documentation contract.

## Development checks

- Full test suite: `pytest tests/ -q`
- Focused PvP checks: `pytest tests/server tests/test_pvp_server.py -q`
- Lint: `ruff check src tests`
- Local training dashboard: `python scripts/dashboard.py`
- RunPod manager: `python scripts/manage_pods.py --help`
- Windows launchers: `scripts/windows/`

Card definitions live in `data/cards/`. When changing a player-facing keyword, update both `data/GLOSSARY.md` and the browser glossary in `src/grid_tactics/server/static/js/03-deck-builder.js`.

## Deployment

Pushing `master` to `origin` triggers the connected Railway deployment. Railway builds with Nixpacks and starts `python pvp_server.py`. The analytics dashboard and wiki have their own deployment configuration in their respective folders.

See [`docs/deployment.md`](docs/deployment.md) for deployment boundaries and operator commands.

Never commit `.env`, local editor state, browser traces, screenshots, training databases, or generated model outputs.
