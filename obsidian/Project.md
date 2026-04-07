# Project: Grid Tactics TCG

A fantasy trading card game on a 5x5 grid with RL-driven strategy discovery. Players deploy minions, cast magic, and use react cards. A GPU tensor engine trains at 100K+ FPS streaming results to Supabase.

## Core Value
The RL engine that discovers and validates game strategies — backed by a playable PvP web client.

## Pillars
- [[Mechanics/_index|Mechanics]] — turn structure, [[React Window]], [[Sacrifice]]-to-damage
- [[Architecture/Game Engine (Python)]] — immutable dataclass engine
- [[Architecture/Tensor Engine]] — GPU batched simulation
- [[Architecture/RL Training]] — MaskablePPO + custom tensor PPO loop
- [[Architecture/Server]] — Flask-SocketIO PvP rooms
- [[Architecture/Frontend]] — vanilla JS web client

## Tech Stack (highlights)
| Layer | Tech |
|-------|------|
| Engine | Python 3.12, dataclasses, NumPy |
| RL | Gymnasium, PettingZoo, sb3-contrib (MaskablePPO), PyTorch |
| Tensor Sim | PyTorch batched on RTX 4090 |
| Server | Flask-SocketIO |
| DB | Supabase PostgreSQL |
| Dashboard | Vercel + Chart.js |
| Cloud | RunPod |

## Roadmap
- v1.0 — engine + RL core (see [[Phases/_index]])
- v1.1 — Online PvP dueling (in progress)
