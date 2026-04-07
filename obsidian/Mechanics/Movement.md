# Movement

Minions move **forward only** in their column (P1 down, P2 up). Attacks fire any direction (see [[Range and Attacks]]).

## Leap
- A blocked minion advances to the **next available tile** in its column instead of stopping.
- User: [[Cards/Rathopper]]

## Rally
- When a minion moves, all friendly copies of it also advance forward.
- User: [[Cards/Furryroach]]

## Action Slot
- MOVE[250:350] — see [[Architecture/Action Space]]

## Implementation
- `src/grid_tactics/action_resolver.py`
- Bug: [[Bugs/_index|grid orientation bugs]], commit `e67e185` (critical movement bug fix)

## Related
- [[Move and Attack]]
