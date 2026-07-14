# Grid Tactics TCG

Grid Tactics is a two-player tactical card game played on a 5x5 board. The active product combines a Python rules engine, a Flask-SocketIO PvP server, a browser client, AI opponents, and an experimental reinforcement-learning stack.

## Quick start

1. Create a Python 3.12 virtual environment.
2. Install the PvP and development dependencies: `pip install -e ".[pvp,dev]"`.
3. Start the game with `python pvp_server.py`.
4. Open `http://127.0.0.1:5000/`.

The live entrypoint enables the manual-draw rules experiment by default. Set `GT_MANUAL_DRAW=0` to run the standard engine rules.

## Repository map

| Path | Purpose |
| --- | --- |
| `src/grid_tactics/` | Rules engine, AI/RL integration, persistence, and PvP server package |
| `src/grid_tactics/server/static/` | Browser game client, CSS, artwork, and sound |
| `data/` | Card definitions, rules references, and local training data |
| `tests/` | Unit, integration, server, JavaScript-contract, and end-to-end tests |
| `scripts/` | Maintenance, data-generation, debugging, and verification utilities |
| `assets/` | Source card artwork used by tooling and documentation |
| `wiki/` | Separately deployable game wiki |
| `web-dashboard/` | Static Supabase analytics dashboard for Vercel |
| `.planning/` | GSD roadmap, phase plans, decisions, and debugging evidence |
| `artifacts/` | Local-only browser captures and temporary investigation output |

Root-level Python and shell files are operational entrypoints. In particular, Railway starts `pvp_server.py`, so these files intentionally remain at the repository root.

## Development checks

- Full test suite: `pytest tests/ -q`
- Focused PvP checks: `pytest tests/server tests/test_pvp_server.py -q`
- Lint: `ruff check src tests`

Card definitions live in `data/cards/`. When changing a player-facing keyword, update both `data/GLOSSARY.md` and the browser glossary in `src/grid_tactics/server/static/js/03-deck-builder.js`.

## Deployment

Pushing `master` to `origin` triggers the connected Railway deployment. Railway builds with Nixpacks and starts `python pvp_server.py`. The analytics dashboard and wiki have their own deployment configuration in their respective folders.

Never commit `.env`, local editor state, browser traces, screenshots, training databases, or generated model outputs.
