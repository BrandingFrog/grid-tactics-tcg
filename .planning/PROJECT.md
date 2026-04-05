# Grid Tactics TCG

## What This Is

A fantasy trading card game played on a 5x5 grid where players deploy minions, cast magic, and use react cards to outmaneuver opponents. An RL system discovers optimal play strategies, validates card balance, and serves as the game's AI opponent. A live analytics dashboard (op.gg-style) tracks per-card win rates, training progress, and game statistics in real time.

## Core Value

The reinforcement learning engine that discovers and validates game strategies — every other component (game rules, cards, UI) exists to feed and display RL insights.

## Current Milestone: v1.1 Online PvP Dueling

**Goal:** Two human players can play Grid Tactics against each other in real-time through a web UI, with the Python game engine enforcing all rules server-side.

**Target features:**
- Flask-SocketIO game server running the existing Python engine
- Room code system (create/join) — no matchmaking
- Per-player views (hidden hand, hidden deck — no information leakage)
- Legal action filtering (UI shows only valid moves per game state)
- 5x5 grid game board UI with hand display, mana/HP, react windows
- Real-time turn flow: auto-draw → action → react window → turn passes
- Win detection and game-over screen

## Current State (2026-04-05)

**Working end-to-end pipeline:**
- 3x RTX 4090 pods on RunPod training via GPU-native tensor engine (100K+ FPS)
- Training data streams to Supabase PostgreSQL in real time
- Vercel dashboard at https://web-dashboard-bice-eight.vercel.app shows live analytics
- 21 cards in starter pool, 500+ tests passing

**Phase 11 complete** — Flask-SocketIO PvP server with room codes, create/join/ready flow, session tokens, preset deck. 22 new tests.
**Phase 12 complete** — Complete game playable via raw WebSocket. View filter (hidden info), action validation, submit_action handler, auto-draw fix. 44 new tests (66 total for PvP).

## Requirements

### Validated

- Game state foundation: immutable 5x5 grid, mana banking, deterministic RNG — Phase 1
- Card system: data-driven JSON cards, 3 types, multi-purpose, 19 starter cards — Phase 2
- Turn actions & combat: action resolver, effect resolver, react stack, legal_actions() — Phase 3
- Win conditions: sacrifice-to-damage, HP tracking, game loop with 1000+ game smoke test — Phase 4
- RL environment: Gymnasium wrapper, observation encoding, action masking — Phase 5
- RL training pipeline: MaskablePPO, self-play, reward shaping, SQLite persistence — Phase 6
- GPU tensor engine: batched PyTorch game engine, 32K parallel games, 100K+ FPS — Quick task
- Live dashboard: Supabase PostgreSQL + Vercel, 5-tab analytics with card tier list — Quick task
- PvP server foundation: Flask-SocketIO with room codes, session tokens, preset deck — Phase 11

### Active

- [ ] Flask-SocketIO game server with room code system
- [ ] Per-player views with hidden information and legal action filtering
- [ ] 5x5 grid game board web UI (hand, mana, HP, react windows)
- [ ] Real-time turn flow with win detection and game-over screen

### Deferred (from v1.0)

- [ ] RL-driven card balance analysis (per-card win rates feeding back into design)
- [ ] Self-play robustness (PettingZoo AEC for react window, agent pool, league training)
- [ ] Card expansion to 30+ cards with automated balance sweeps
- [ ] Game replay viewer with step-by-step playback

### Out of Scope

- Visual card art or polished game graphics — focus is on mechanics and RL
- Multiplayer networking — AI vs AI only for now
- Card trading or collection economy

## Game Rules

### Board
5x5 grid. Each player owns 2 rows. Middle row is contested. Minions deploy to friendly rows and must advance forward to sacrifice at the opponent's back row.

### Turn Structure
1. **Auto-draw**: Active player draws a card automatically at turn start
2. **Action**: One action per turn — play card, move minion, attack, sacrifice, or pass
3. **React window**: Opponent may play a React card to counter
4. **Turn passes** to the other player

### Mana
Pool-based. Regenerates +1 per turn. Unspent mana carries over (banking). Cards cost mana to play.

### Card Types
- **Minions** — Deploy to board. Stats: ATK, HP, Mana Cost, Range, Effects. Some have React effects (multi-purpose).
- **Magic** — Immediate effects (damage, heal, buff). Discarded after use.
- **React** — Counter/interrupt cards played during opponent's action window.

### Movement
**Forward only in lane.** Minions advance toward the enemy in their column. No lateral or backward movement. Player 1 moves down (row+1), Player 2 moves up (row-1).

### Combat
Melee units attack adjacent targets (orthogonal). Ranged units attack up to 2 tiles orthogonally or 1 tile diagonally. Attacks can target any direction.

### Win Condition
- **Sacrifice**: Minion on opponent's back row sacrifices itself, dealing ATK as player damage
- **HP Depletion**: Reduce opponent HP to 0
- **Timeout**: Turn limit (200), higher HP wins

### Card Pool (19 cards)
| Type | Count | Examples |
|------|-------|---------|
| Minion | 11 | Fire Imp (1/1), Shadow Knight (3/3), Flame Wyrm (4/4), Furryroach (1/1 rally) |
| Magic | 4 | Fireball (4 dmg), Dark Drain (2 dmg + 2 heal), Holy Light (3 heal), Inferno (2 AoE) |
| React | 3 | Counter Spell (negate magic), Shield Block (+2 HP), Dark Mirror (1 dmg + 1 heal) |
| Multi-purpose | 1 | Dark Sentinel (minion + react deploy vs light) |

Attributes: Fire, Dark, Light, Neutral, Earth

### Special Abilities
- **Furryroach** (Earth 1/1 Insect): ON_MOVE — all other friendly Furryroaches advance forward if possible (rally)

## Infrastructure

### Training Pipeline
```
RunPod RTX 4090 pods
  → tensor_train.py (GPU-native PPO, 32K parallel games)
  → Supabase PostgreSQL (training_runs, training_snapshots, card_stats, game_results)
  → Vercel dashboard (real-time analytics)
```

### Key Components
| Component | Technology | Location |
|-----------|-----------|----------|
| Python game engine | dataclasses, immutable state | `src/grid_tactics/` |
| Tensor game engine | PyTorch batched ops, GPU | `src/grid_tactics/tensor_engine/` |
| RL environment | Gymnasium, MaskablePPO | `src/grid_tactics/rl/` |
| GPU training | Custom PPO loop, 32K envs | `tensor_train.py` |
| Database | Supabase PostgreSQL | Cloud (qdyatyqbafzgcmfsqzuz) |
| Dashboard | Vanilla HTML/JS + Chart.js | `web-dashboard/` → Vercel |
| Deployment | RunPod API + Supabase Storage | `deploy_runpod.py` |
| Card definitions | JSON files | `data/cards/*.json` |

### Dashboard Tabs
1. **Overview** — KPIs, win rate chart, pod status cards
2. **Training** — Policy loss, value loss, entropy, FPS curves
3. **Cards** — Tier list with win rate, play rate, popularity + hover card preview
4. **Games** — Game length distribution, win conditions, recent games
5. **Models** — Leaderboard, head-to-head comparison, learning efficiency

## Key Decisions

| Decision | Rationale | Status |
|----------|-----------|--------|
| Action-per-turn | Tight action economy, every decision matters | Active |
| Mana banking | Strategic depth — save small to go big | Active |
| Sacrifice-to-damage | Positional gameplay, must cross board | Active |
| Auto-draw at turn start | Drawing is mandatory, not an action choice | Active (changed from draw-costs-action) |
| Forward-only movement | Lane-based strategy, no retreat | Active (changed from 4-dir movement) |
| GPU tensor engine over SB3 | 100-1000x faster training via batched GPU ops | Active |
| Supabase PostgreSQL over SQLite | Cloud DB for multi-pod training + live dashboard | Active |
| Vercel dashboard over Streamlit | Static deployment, real-time via Supabase, no server | Active |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-05*
