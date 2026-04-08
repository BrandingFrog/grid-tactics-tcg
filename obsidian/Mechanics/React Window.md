# React Window

After every action, the opponent gets a window to play a [[Glossary|React]] card or pass. Reacts chain LIFO on the [[Architecture/Game Engine (Python)|react stack]].

## Rules
- Trigger conditions per react card: `opponent_plays_magic`, `opponent_plays_minion`, `opponent_attacks`, `opponent_sacrifices`, `opponent_plays_light`.
- React costs mana, possibly different from base cost (`react_mana_cost`).
- Some minion cards have a **deploy_self** react effect — they jump straight to the board.
- LIFO chaining: a react can be reacted to.
- Empty react windows auto-skip (Phase 14 polish).

## React Cards
- [[Cards/Counter Spell]] — negates magic
- [[Cards/Dark Mirror]] — punishes minion plays
- [[Cards/Shield Block]] — buffs 🤍 on attack
- [[Cards/Dark Sentinel]] — deploy on Light play
- [[Cards/Surgefed Sparkbot]] — deploy on opponent sacrifice (free)

## Action Slot
- REACT[1002:1262] — see [[Architecture/Action Space]]

## Implementation
- `src/grid_tactics/react_stack.py`
- Phase: [[Phases/v1.1/Phase 14 Gameplay Interaction]]
