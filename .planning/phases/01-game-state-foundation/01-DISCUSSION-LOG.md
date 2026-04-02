# Phase 1: Game State Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-02
**Phase:** 01-game-state-foundation
**Areas discussed:** Grid representation, Mana system design, Player HP and setup, State immutability

---

## Grid Representation

### Grid Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Rows 0-1 = P1, Row 2 = NML, Rows 3-4 = P2 | Player 1 deploys to rows 0-1, no-man's-land is row 2, Player 2 deploys to rows 3-4 | ✓ |
| Symmetric from each player's view | Each player always sees their side as 'bottom' — row indices are relative to perspective | |

**User's choice:** Rows 0-1 = P1, Row 2 = NML, Rows 3-4 = P2
**Notes:** Fixed absolute row assignment chosen for simplicity.

### Column Rules

| Option | Description | Selected |
|--------|-------------|----------|
| All columns equal | No special column rules — pure positional strategy | ✓ |
| Center column matters | Center column has a bonus or special rule | |

**User's choice:** All columns equal
**Notes:** None

### Stacking

| Option | Description | Selected |
|--------|-------------|----------|
| One per space | Each cell holds at most one minion — must move around blockers | ✓ |
| Stack allowed | Multiple minions can share a cell | |

**User's choice:** One per space
**Notes:** None

---

## Mana System Design

### Starting Mana

| Option | Description | Selected |
|--------|-------------|----------|
| 0 mana | Start empty — first turn is always draw or pass | |
| 1 mana | Can play a 1-cost card turn 1 | ✓ |
| 3 mana | Start with some options immediately | |

**User's choice:** 1 mana
**Notes:** None

### Mana Cap

| Option | Description | Selected |
|--------|-------------|----------|
| No cap | Bank unlimited mana | |
| Cap at 10 | Limits degenerate stalling strategies | ✓ |
| Let RL decide | Make the cap configurable | |

**User's choice:** Cap at 10
**Notes:** None

---

## Player HP and Setup

### Starting HP

| Option | Description | Selected |
|--------|-------------|----------|
| 20 HP | Fast games — a few minions getting through ends it quickly | ✓ |
| 30 HP | Mid-length — sustained pressure needed | |
| Configurable (RL tests) | Make HP a parameter so RL can find the sweet spot | |

**User's choice:** 20 HP
**Notes:** None

### Starting Hand Size

| Option | Description | Selected |
|--------|-------------|----------|
| 5 cards | Standard TCG starting hand | ✓ |
| 7 cards | More options from the start | |
| Configurable | Let RL test different starting hand sizes | |

**User's choice:** 5 cards
**Notes:** None

### First Turn Rules

| Option | Description | Selected |
|--------|-------------|----------|
| No restriction | First player takes a normal action | |
| First player skips | First player passes their first action | |
| You decide | Claude's discretion — RL can test this | ✓ |

**User's choice:** You decide (Claude's discretion)
**Notes:** RL can test first-turn advantage balancing

---

## State Immutability

### Copy Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| You decide (Recommended) | Let Claude pick based on research | ✓ |
| Deep copy every action | Simplest — full state copy on each action | |
| Action log replay | Store action sequence + seed, replay to reconstruct | |

**User's choice:** You decide (Claude's discretion)
**Notes:** None

### Serialization Format

| Option | Description | Selected |
|--------|-------------|----------|
| You decide (Recommended) | Let Claude pick the most practical format | ✓ |
| Python dict | Native Python — fast to create, easy to inspect | |
| JSON | Human-readable, portable, good for replays | |
| Both | Dict internally, JSON for persistence/replays | |

**User's choice:** You decide (Claude's discretion)
**Notes:** None

---

## Claude's Discretion

- First-turn advantage balancing approach
- State immutability implementation strategy
- Serialization format choice

## Deferred Ideas

None — discussion stayed within phase scope
