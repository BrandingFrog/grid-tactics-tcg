# Move and Attack

Player-driven Advance Wars-style melee chain. Shipped in [[Phases/v1.1/Phase 14.1 Melee Move-and-Attack]].

## Flow
1. Melee minion moves forward (consumes the action).
2. Game enters a `pending_attack` state for that minion.
3. Player picks an attack target in melee range, **or** declines.
4. Pending state clears.

## Rules
- **Only melee minions** chain. Ranged units do not.
- Chain is optional — declining is legal.
- The legal action mask reflects pending state.

## Implementation
- Python: `src/grid_tactics/game_state.py`, `action_resolver.py`
- Tensor parity: `tensor_engine/` step kernel
- Mask: `legal_actions.py`
- Frontend: `server/static/game.js` two-step click flow

## Related
- [[Range and Attacks]] · [[Movement]] · [[Architecture/Action Space]]
