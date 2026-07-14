# Mana System

A single banking pool — not an X/Y refresh. Mana persists across turns. Turn
income starts at **+1**, becomes **+2** after turn 25 and **+3** after turn 50,
then stays capped at **+3**. The turn-75 Fortune instead unlocks one automatic draw.

## Rules
- Gain 1 Action Point (cap 3) and turn income. After the third Fortune, also draw 1 automatically; an empty deck fatigues.
- REST costs no Action Point, banks the pool, grants +1 mana, and draws the Fortune ante.
- Pool is a single integer; UI displays bank total only.
- Spent on: card play, [[Activated Abilities]], [[Transform]], react card costs.

## Implementation
- `src/grid_tactics/player.py`
- Recent fix: commit `56a20b5` (mana display single banking pool)

## Related
- [[Win Conditions]] · [[React Window]]
