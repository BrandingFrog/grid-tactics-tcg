# Phase 3: Turn Actions & Combat - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-02
**Phase:** 03-turn-actions-combat
**Areas discussed:** Combat resolution, React window rules, Card play mechanics, Action enumeration

---

## Combat Resolution

### Damage Model

| Option | Description | Selected |
|--------|-------------|----------|
| Simultaneous | Both deal damage at the same time — both can die | ✓ |
| Attacker first | Attacker hits first; defender may not counter | |
| Defender counters | Attacker hits, then defender responds if alive | |

**User's choice:** Simultaneous

### Minion Death Timing

| Option | Description | Selected |
|--------|-------------|----------|
| Immediately | Removed right after lethal damage | |
| End of action | Stays until full action resolves, then removed | ✓ |
| You decide | Claude's discretion | |

**User's choice:** End of action

---

## React Window Rules

### React Count

**User's choice:** One react per player per level, but reacts chain back and forth (full stack)
**Notes:** Player A acts → Player B plays 1 react → Player A can counter-react → etc.

### React Chain

| Option | Description | Selected |
|--------|-------------|----------|
| No chains | Only non-active player reacts | |
| One level deep | One counter-react allowed | |
| Full stack | Both players keep reacting until someone passes | ✓ |

**User's choice:** Full stack

---

## Card Play Mechanics

### Deployment

**User's choice:** Melee minions to any friendly row; ranged minions to back row only
**Notes:** Forces ranged behind front line

### Magic Targeting

| Option | Description | Selected |
|--------|-------------|----------|
| Specified on play | Player chooses target | |
| Auto-resolved | Determined by effect definition | |
| Both | Single-target needs choice; area effects auto-resolve | ✓ |

**User's choice:** Both

---

## Action Enumeration

### Action Format

**User's choice:** Structured tuples internally, mappable to flat ints for RL
**Notes:** User plans Roblox/Lua port eventually — wants clean, portable structure. Referenced YGOPro/EDOPro Lua scripting as inspiration.

### Pass Action

| Option | Description | Selected |
|--------|-------------|----------|
| Always allowed | Pass is always valid — important for mana banking | ✓ |
| Only if no other action | Must act if possible | |

**User's choice:** Always allowed

---

## Claude's Discretion

- Effect resolution order for simultaneous triggers
- Exact action tuple format
- Card instance HP tracking on the field
- Whether attack IS the action (vs attack + movement in one turn)

## Deferred Ideas

None — discussion stayed within phase scope
