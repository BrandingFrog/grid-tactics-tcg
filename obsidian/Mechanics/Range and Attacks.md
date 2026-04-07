# Range and Attacks

## Melee (range 0)
- Attacks adjacent orthogonal tiles only.
- Triggers the [[Move and Attack]] chain after a forward move.

## Range X
- Attacks **X+1 tiles orthogonally** and **X tiles diagonally**.
- Cannot use the move-and-attack chain.

## Direction
- Attacks fire in any direction (unlike [[Movement|movement]] which is forward-only).

## Notable Ranged Cards
- [[Cards/Pyre Archer]] (Range 2)
- [[Cards/Wind Archer]] (Range 2)
- [[Cards/Flame Wyrm]] (Range 1)
- [[Cards/RGB Lasercannon]] (Range 1)

## Implementation
- `src/grid_tactics/action_resolver.py`, `legal_actions.py`
- Action space ATTACK slot range: see [[Architecture/Action Space]]
