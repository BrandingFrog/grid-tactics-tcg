# Action Space

Single discrete space of **1287 slots** with a binary legality mask.

| Range | Action | Notes |
|-------|--------|-------|
| 0-249 | PLAY_CARD | hand index x board target |
| 250-349 | MOVE | source x direction |
| 350-974 | ATTACK | source x target |
| 975-999 | SACRIFICE | see [[../Mechanics/Sacrifice]] |
| 1000 | DRAW / REST | REST under active action-bank rules |
| 1001 | PASS | end action / decline react |
| 1002-1261 | REACT | hand index x react target |
| 1262-1286 | ACTIVATE | source minion |

## Notes
- Action Points are state, not new action IDs. Primary actions cost 1; reacts and modal continuations cost 0.
- Pending states ([[../Mechanics/Move and Attack|pending_attack]], [[../Mechanics/Tutor|pending_tutor]]) restrict the mask further.

## Implementation
- `src/grid_tactics/legal_actions.py`
- `src/grid_tactics/rl/`
