# Grid Tactics package

The package is divided into the following areas:

- Core rules: `game_state.py`, `game_loop.py`, `legal_actions.py`, `action_resolver.py`, `effect_resolver.py`, `react_stack.py`, and `phase_contracts.py`.
- Domain models: `cards.py`, `minion.py`, `player.py`, `board.py`, `actions.py`, and `enums.py`.
- Card loading and validation: `card_library.py`, `card_loader.py`, and `validation.py`.
- Roguelike turn events: `roguelike_events.py` and their game-state/event integrations.
- PvP application: `server/`.
- Persistence and analytics: `db/`.
- Reinforcement learning: `rl/`.
- Batched GPU implementation: `tensor_engine/`; preserved but currently on hold while rules evolve.

The Python engine is authoritative for live play. New game rules should be implemented and tested there before any tensor-engine parity work.
