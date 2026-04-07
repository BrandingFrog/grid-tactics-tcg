# Activated Abilities

Once-per-turn abilities used **instead of attacking** by a minion already on the board. They cost mana and consume the minion's action for the turn.

## Users
- [[Cards/Ratchanter]] — Summon Rat (1 mana, conjures a [[Cards/Common Rat]] on own side)

## Rules
- Counts as the minion's action for the turn (no attack/move).
- Costs mana from the [[Mana System]].
- Often used to [[Conjure]] tokens.

## Implementation
- `src/grid_tactics/action_resolver.py` — ACTIVATE action handler
- Phase: [[Phases/v1.1/Phase 14.2 Tutor Choice Prompt]] adjacent work
- Bugs: [[Bugs/_index|ratchanter-activated-ability]], [[Bugs/_index|ratchanter-conjure-and-buff]]
