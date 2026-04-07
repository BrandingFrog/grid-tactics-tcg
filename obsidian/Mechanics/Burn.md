# Burn

A persistent boolean status that ticks damage at the start of the burning minion's owner's turn.

## Rules
- Burning is **boolean** — re-applying does nothing (non-stacking).
- A burning minion takes **5 damage** at the start of its owner's turn.
- Persists until the minion dies.

## Sources
- [[Cards/Pyre Archer]] — applies on attack
- [[Cards/Emberplague Rat]] — passive aura applies to adjacent enemies

## Implementation
- `src/grid_tactics/effect_resolver.py`
- Tensor parity: `src/grid_tactics/tensor_engine/`
- Phase: [[Phases/v1.1/Phase 14.3 Game Juice]] added burn tick animation
- Bug history: [[Bugs/_index|Emberplague redesign]]

## Related
- [[Status Effects]] · [[Auras]]
