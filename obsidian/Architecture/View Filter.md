# View Filter

Server-side filter that strips hidden info from `GameState` before serializing it for a particular client.

## Rules
- Opponent's hand reduced to **count only** (no card IDs).
- Opponent deck is opaque.
- Player sees own legal actions list.
- Spectator variants:
  - **God mode**: both hands visible
  - **Non-god**: P1 perspective only — see [[Spectator Mode]]

## Files
- `src/grid_tactics/server/view_filter.py`

## Phases
- [[../Phases/v1.1/Phase 12 State Serialization Game Flow]]
- [[../Phases/v1.1/Phase 14.4 Spectator Mode]]
