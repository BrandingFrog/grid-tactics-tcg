# Phase 2: Card System & Types - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Data-driven card definition system supporting all three card types (Minion, Magic, React), multi-purpose cards (minion + react from hand), and a starter pool of 15-20 unique cards with stats in the 1-5 range. Cards are defined as per-card JSON files with declarative effects. This phase builds the card data model and loader — game actions like playing/moving/attacking are Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Card Effects System
- **D-01:** Effects are simple stat-based for starter cards (deal X damage, heal Y HP, buff +Z attack) but the engine must support the full effect system infrastructure
- **D-02:** Trigger types supported: on_play, on_death, on_attack, on_damaged
- **D-03:** Target types supported: single_target, all_enemies, adjacent, self_owner
- **D-04:** Effects are encoded as declarative JSON objects: `{"type": "damage", "target": "single", "amount": 3, "trigger": "on_play"}`
- **D-05:** Starter cards use only simple effects but the system must be extensible for complex effects in Phase 8

### Multi-Purpose Card Design
- **D-06:** A multi-purpose card (e.g., Minion with React) can be deployed as a minion OR used as a react from hand — not both. Choosing one consumes the card.
- **D-07:** Each mode has its own separate mana cost (deploy cost vs react cost)
- **D-08:** Once deployed as a minion, the react option is permanently gone for that card instance

### Card Data Model
- **D-09:** Cards have attributes/elements (dark, light, fire, etc.) for future synergy/weakness mechanics
- **D-10:** Cards can belong to tribes/archetypes (e.g., "Dark Mage") — cards sharing a tribe may have synergies
- **D-11:** Minion stats: Attack (1-5), Health (1-5), Mana Cost (1-5), Range (0 = melee, 1+ = ranged)
- **D-12:** Maximum 3 copies of any card in a deck
- **D-13:** Deck size minimum = 40 cards

### JSON Schema & File Organization
- **D-14:** Each card is its own JSON file (per-card files, not a single monolithic file)
- **D-15:** Effects are fully declarative as data objects in JSON — no string references to Python functions

### Starter Card Pool
- **D-16:** 15-20 unique cards to support full 40+ card decks with 3-copy limit
- **D-17:** Mix of all three types: Minions, Magic, React cards
- **D-18:** At least one multi-purpose card (Minion + React from hand)
- **D-19:** Stats in the 1-5 range for all numeric values

### Claude's Discretion
- Specific starter card designs (names, stats, effects) — whatever gives RL good signal
- JSON directory structure (e.g., data/cards/ or similar)
- Card ID format and naming conventions
- How the card loader validates JSON against the schema
- Whether to use Python dataclasses or a lighter Card model

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

No external specs — requirements fully captured in decisions above and in the following project docs:

### Project Context
- `.planning/PROJECT.md` — Game mechanics, card types, multi-purpose card description, attributes
- `.planning/REQUIREMENTS.md` — ENG-04 (three card types), ENG-05 (minion stats), ENG-12 (multi-purpose), CARD-01 (data-driven), CARD-02 (starter pool)
- `.planning/research/FEATURES.md` — Feature landscape, card system complexity, dependency chain
- `.planning/research/ARCHITECTURE.md` — Four-layer architecture, data-driven card definitions

### Phase 1 Code (upstream dependencies)
- `src/grid_tactics/enums.py` — PlayerSide, TurnPhase enums (may need card-related enums added)
- `src/grid_tactics/types.py` — Position type, grid/mana/player constants
- `src/grid_tactics/board.py` — Board dataclass pattern to follow for consistency
- `src/grid_tactics/player.py` — Player dataclass with hand management (cards will be stored here)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `@dataclass(frozen=True, slots=True)` pattern from Board/Player/GameState — Card model should follow same immutability pattern
- `enums.py` — Can extend with CardType, Attribute, Tribe enums
- `types.py` — Can extend with card-related type aliases and constants
- `player.py` — Player.hand is a `tuple[int, ...]` of card IDs, Player.draw_card()/discard_from_hand() already manage hand

### Established Patterns
- Frozen dataclasses with tuple collections for immutability
- JSON serialization via `dataclasses.asdict()` + `json.dumps()`
- Factory methods (`.new()`, `.empty()`) for construction
- Comprehensive pytest TDD approach

### Integration Points
- Player.hand stores card IDs — card system must provide a CardLibrary/CardPool that maps IDs to card definitions
- Board.cells stores `Optional[int]` — these are minion instance IDs that need to reference card definitions
- GameState will need access to the card library for rule enforcement in Phase 3

</code_context>

<specifics>
## Specific Ideas

- Cards can have fantasy-themed attributes (dark, light, fire) and tribe names (e.g., "X the Dark Mage", "Y the Dark Mage", "Dark Mage Candle") — these enable future synergy mechanics
- The effect system should be fully data-driven so automated balance sweeps (Phase 8) can vary stats without code changes

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-card-system-types*
*Context gathered: 2026-04-02*
