# Phase 2: Card System & Types - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-02
**Phase:** 02-card-system-types
**Areas discussed:** Card effects system, Multi-purpose card design, Starter card pool, JSON schema design

---

## Card Effects System

### Effect Type

| Option | Description | Selected |
|--------|-------------|----------|
| Simple stat effects | Effects like 'deal 3 damage', 'heal 2 HP', 'buff +1 attack' | ✓ |
| Keyword abilities | Named abilities like 'Taunt', 'Rush', 'Shield' | |
| Both combined | Stat effects + keywords together | |

**User's choice:** Simple stat effects
**Notes:** For the actual starter cards

### Complexity

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal | Keep starter cards simple | |
| Moderate | Include some triggered effects | |
| Full featured | Build complete effect system with triggers, conditions, combos | ✓ |

**User's choice:** Full featured (build the engine, but starter cards stay simple)
**Notes:** Engine supports full complexity; starter cards use basic effects only

### Trigger Types

| Option | Description | Selected |
|--------|-------------|----------|
| On-play | Triggers when card is played | ✓ |
| On-death | Triggers when minion dies | ✓ |
| On-attack | Triggers when minion attacks | ✓ |
| On-damaged | Triggers when minion takes damage | ✓ |

**User's choice:** All four trigger types

### Target Types

| Option | Description | Selected |
|--------|-------------|----------|
| Single target | Effect hits one specific minion or player | ✓ |
| All enemies | Effect hits all enemy minions | ✓ |
| Adjacent minions | Effect hits minions adjacent to source | ✓ |
| Self/owner | Effect applies to card itself or owner | ✓ |

**User's choice:** All four target types

---

## Multi-Purpose Card Design

### Dual Mode

| Option | Description | Selected |
|--------|-------------|----------|
| Choose on play | Choose deploy or react, can't do both | |
| React from hand only | React triggers from hand; deploy loses react | ✓ |
| Both available | Deploy AND retain react on field | |

**User's choice:** React from hand only
**Notes:** Using the card as react consumes it; deploying loses the react option

### Mana Cost

| Option | Description | Selected |
|--------|-------------|----------|
| Same cost | Both modes cost the card's mana cost | |
| Separate costs | React mode has its own mana cost | ✓ |
| You decide | Claude's discretion | |

**User's choice:** Separate costs

---

## Starter Card Pool

### Pool Size

**User's choice:** 15-20 unique cards (enough for full 40+ card deck with 3-copy limit)
**Notes:** User corrected from roadmap's 5-10 to 15-20 to enable full playable decks

### Stat Ranges

| Option | Description | Selected |
|--------|-------------|----------|
| Low range (1-3) | Simple, fast games | |
| Medium range (1-5) | More variety, cheap weak and expensive strong | ✓ |

**User's choice:** Medium range (1-5)

---

## JSON Schema Design

### File Layout

**User's choice:** Per-card files (each card is its own JSON file)

### Effects Encoding

| Option | Description | Selected |
|--------|-------------|----------|
| Declarative objects | Effects as data objects | ✓ |
| Effect references | Name-based referencing Python implementations | |

**User's choice:** Declarative objects

### Additional Fields

**User's choice:** Cards can have attributes/elements (dark, light, fire) and tribe names (e.g., "Dark Mage")
**Notes:** For future synergy mechanics

---

## Claude's Discretion

- Specific starter card designs (names, stats, effects)
- JSON directory structure
- Card ID format and naming conventions
- Card loader validation approach
- Card model implementation (dataclass vs lighter model)

## Deferred Ideas

None — discussion stayed within phase scope
