# Phase 03 — Turn Actions & Combat

**Goal:** Action-per-turn, [[../../Mechanics/Movement]], combat, [[../../Mechanics/React Window]], legal action enumeration.

## Shipped
- ActionType enum, MinionInstance, Action dataclass
- Effect / action resolver
- React stack with LIFO chaining
- `legal_actions()`

## Files
- `action_resolver.py`, `effect_resolver.py`, `react_stack.py`, `legal_actions.py`
