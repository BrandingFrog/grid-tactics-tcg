# Phase 12: State Serialization & Game Flow - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 12-state-serialization-game-flow
**Areas discussed:** React card visibility, Game over behavior, Draw ruling

---

## React Card Visibility

| Option | Description | Selected |
|--------|-------------|----------|
| See the card played | Opponent sees which react card was used (name, effect). Full information. | ✓ |
| See "reacting" only | Opponent only knows a react card was played, not which one. | |
| You decide | Claude picks the approach | |

**User's choice:** See the card played
**Notes:** Full transparency on react cards.

---

## Game Over Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Reveal everything | Full unfiltered state — both hands, decks, final board. | |
| Keep hidden info hidden | Final board + HP shown but hands/decks stay hidden. | ✓ |
| You decide | Claude picks standard approach | |

**User's choice:** Keep hidden info hidden
**Notes:** Clean ending, no post-game reveal.

---

## Draw Ruling

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-draw only | Server auto-draws at turn start. Not a player action. | |
| Draw as action | Players spend their action to draw. No auto-draw. | ✓ |

**User's choice:** Draw is an action, no auto-draw
**Notes:** User confirmed "we changed it so that drawing is an action and there is no auto draw." `AUTO_DRAW_ENABLED = False` in types.py is correct.

---

## Claude's Discretion

- Action JSON serialization format
- Event protocol design (event names, payload shapes)
- Turn transition flow handling
- Per-player emit pattern
- Thread locking strategy

## Deferred Ideas

None
