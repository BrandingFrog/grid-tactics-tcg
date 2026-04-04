# Phase 11: Server Foundation & Room System - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 11-server-foundation-room-system
**Areas discussed:** Player identity, Deck composition, Game start flow

---

## Player Identity

| Option | Description | Selected |
|--------|-------------|----------|
| Display name on join | Prompt for a name when creating/joining. Shown to opponent. No persistence. | ✓ |
| Just Player 1 / Player 2 | No names. Room creator is P1, joiner is P2. Simplest possible. | |
| You decide | Claude picks the simplest approach that works | |

**User's choice:** Display name on join
**Notes:** No persistence, no accounts. Ephemeral session names only.

---

## Deck Composition

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror match preset | Both players get the same preset 30-card deck. Identical = pure skill test. | |
| All cards, fill with copies | All 19 cards included, fill remaining 11 slots with extra copies. | |
| Smaller deck size | Reduce deck to 19 (one of each). Simpler, no duplicates. | |
| You decide | Claude picks a balanced preset | |

**User's choice:** Other — "extend the database tab so people can make their deck there. players pick up to 3x of each card in the deck to a max of 30"
**Notes:** User wants a deck builder in the existing dashboard Cards tab. Up to 3 copies per card, max 30 cards. Deck builder UI deferred to Phase 13; Phase 11 server just accepts a deck from client.

---

## Game Start Flow

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-start on join | Game starts automatically when 2nd player joins. | |
| Ready button | Both players click "Ready" to start. Review opponent name first. | ✓ |
| You decide | Claude picks the smoothest approach | |

**User's choice:** Ready button
**Notes:** Allows reviewing opponent name before committing to game.

---

## First Turn

| Option | Description | Selected |
|--------|-------------|----------|
| Random (coin flip) | Server picks randomly. Fair. Standard for card games. | ✓ |
| Room creator goes first | P1 always starts. Predictable, simpler. | |
| You decide | Claude picks the standard approach | |

**User's choice:** Random (coin flip)
**Notes:** None.

---

## Claude's Discretion

- Room code format (length, character set, case sensitivity)
- Session token implementation
- In-memory data structures for room/game tracking
- Flask-SocketIO async mode selection

## Deferred Ideas

- Deck builder UI in dashboard Cards tab (deferred to Phase 13)
