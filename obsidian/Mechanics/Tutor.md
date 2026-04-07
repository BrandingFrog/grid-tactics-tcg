# Tutor

Search your deck for a specific card and add it to your hand.

## Selection (Phase 14.2)
- `tutor_target` may be a **string card_id** or a **selector dict** (e.g. `{tribe: "Rat", AND: {...}}`).
- A modal prompts the player to choose among matching deck cards. Auto-tutor was removed.

## Users
- [[Cards/Blue Diodebot]] → tutors [[Cards/Red Diodebot]]
- [[Cards/Red Diodebot]] → tutors [[Cards/Green Diodebot]]
- [[Cards/Green Diodebot]] → tutors [[Cards/Blue Diodebot]]

## Implementation
- Phase: [[Phases/v1.1/Phase 14.2 Tutor Choice Prompt]]
- Python: `src/grid_tactics/effect_resolver.py` (`pending_tutor`)
- Tensor: `tensor_engine/`
- Frontend modal: `server/static/game.js`
