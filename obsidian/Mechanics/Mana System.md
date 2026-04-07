# Mana System

A single banking pool — not an X/Y refresh. Mana persists across turns and grows by **+1 each turn**.

## Rules
- Auto-draw at turn start, then one action.
- Pool is a single integer; UI displays bank total only.
- Spent on: card play, [[Activated Abilities]], [[Transform]], react card costs.

## Implementation
- `src/grid_tactics/player.py`
- Recent fix: commit `56a20b5` (mana display single banking pool)

## Related
- [[Win Conditions]] · [[React Window]]
