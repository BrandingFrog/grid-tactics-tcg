# Grid Tactics TCG

## What This Is

A fantasy trading card game played on a 5x5 grid where players deploy minions, cast magic, and use react cards to outmaneuver opponents. The primary purpose of this project is to build a reinforcement learning system in Python that discovers optimal play strategies, validates card balance, and eventually serves as the game's AI opponent. A stats dashboard provides a user-friendly UI for analyzing RL results.

## Core Value

The reinforcement learning engine that discovers and validates game strategies — every other component (game rules, cards, UI) exists to feed and display RL insights.

## Requirements

### Validated

- Game state foundation: immutable 5x5 grid, mana banking, deterministic RNG — Validated in Phase 1
- Card system: data-driven JSON cards, 3 types, multi-purpose, 18 starter cards — Validated in Phase 2
- Turn actions & combat: action resolver, effect resolver, react stack, legal_actions() — Validated in Phase 3

### Active

- [ ] Game engine implementing the full rule set (5x5 grid, action-based turns, mana banking, card types)
- [ ] Reinforcement learning agent that learns optimal play strategy through self-play
- [ ] Stats dashboard UI showing win rates, card usage, game replays, and balance graphs
- [ ] Card system supporting multi-purpose cards (minion with react effect from hand)
- [ ] RL-driven balance analysis for card tuning
- [ ] Meta-strategy discovery across many games

### Out of Scope

- Visual card art or polished game graphics — focus is on mechanics and RL, not aesthetics
- Multiplayer networking or online play — AI vs AI and local play only for now
- Mobile app — desktop/web stats dashboard only
- Card trading or collection economy — not relevant to RL strategy testing

## Context

### Game Mechanics

**Board:** 5x5 grid. Each player owns 2 rows (their side). Middle row is no-man's-land. Minions deploy to any friendly row and must cross the field to sacrifice themselves at the opponent's side, dealing their attack value as player damage.

**Turn structure:** Extremely fast-paced. Each "turn" is a single action (play a card, move a minion, attack, or draw a card). After the active player's action, the opponent may play a React card to counter/interrupt. Then the turn passes.

**Mana:** Pool-based. Regenerates +1 per turn. Unspent mana carries over (banking). Playing cards costs mana from the pool. This creates a core tension: spend small now or save for big plays.

**Card types:**
- **Minions** — Deployed to the field. Stats: Attack, Health, Mana Cost, Range, Effects. May also have a React effect playable from hand (multi-purpose cards).
- **Magic** — Direct effects that resolve immediately (damage, heal, buff, debuff). Cost mana.
- **React** — Counter/interrupt cards played during the opponent's action window. Cost mana/cards/resources.

**Movement:** Minions can move in all 4 directions (up, down, left, right) — not just forward. This enables flanking, retreating, and lateral positioning strategies.

**Positioning & Range:** Melee units attack adjacent targets (orthogonal). Ranged units can attack targets up to 2 tiles away orthogonally or 1 tile diagonally. Placing ranged units behind tanks is a core strategic layer.

**Drawing:** Costs an action (not automatic per turn).

**Deck size:** 40+ cards.

**Player HP:** To be determined — candidate for RL optimization.

### RL Strategy (Phased)

1. **Phase 1 — Core strategy:** RL learns optimal play decisions (when to play, move, attack, draw, save mana, use react)
2. **Phase 2 — Card balance:** Use RL win rates and usage data to identify overpowered/underpowered cards
3. **Phase 3 — Deck composition:** RL explores which card combinations make the strongest decks
4. **Phase 4 — Meta discovery:** Identify dominant strategies and counter-strategies across many games
5. **Eventually:** RL agent becomes the game's AI opponent

### Tech Stack

- **Python** — Game engine and RL training
- **Stats UI** — User-friendly web dashboard for viewing RL results

## Constraints

- **Language**: Python for game engine and RL
- **RL focus**: Core strategy discovery is the priority — card balance and composition come later
- **Testing**: Each development step validated with RL to confirm strategic depth

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Action-per-turn system | Creates tight action economy where every decision matters (play, move, attack, draw) | -- Pending |
| Mana banking | Adds strategic depth — save small to go big | -- Pending |
| Sacrifice-to-damage | Minions must cross the board and sacrifice to deal damage, creating positional gameplay | -- Pending |
| Draw costs action | Increases tension in action economy | -- Pending |
| Multi-purpose cards | Cards can serve multiple roles (minion + react from hand), adds deck-building depth | -- Pending |
| RL before game polish | Build the RL pipeline first, use it to validate mechanics before investing in visuals | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? Move to Out of Scope with reason
2. Requirements validated? Move to Validated with phase reference
3. New requirements emerged? Add to Active
4. Decisions to log? Add to Key Decisions
5. "What This Is" still accurate? Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-02 after Phase 3 completion*
