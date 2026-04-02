# Phase 2: Card System & Types - Research

**Researched:** 2026-04-02
**Domain:** Data-driven card definition system (frozen dataclasses + JSON loader + effect schema)
**Confidence:** HIGH

## Summary

Phase 2 builds the card data model, effect system infrastructure, JSON card definitions, and a starter card pool. The existing codebase uses `@dataclass(frozen=True, slots=True)` throughout (Board, Player, GameState), `IntEnum` for type-safe constants, and tuples for immutable collections. The card system must follow these identical patterns for consistency.

The key architectural insight is that cards exist at two levels: **card definitions** (static templates loaded from JSON, shared across all games) and **card instances** (runtime copies with mutable health/state, tracked by integer IDs that Board.cells and Player.hand already reference). Phase 2 covers definitions only -- runtime instances and game actions are Phase 3.

**Primary recommendation:** Use frozen dataclasses for CardDefinition and EffectDefinition, IntEnum for CardType/Attribute/Tribe/EffectType/TriggerType/TargetType, a CardLibrary class that loads per-card JSON files from `data/cards/`, validates them with `__post_init__`, and provides lookup by card ID. Keep effects as pure data (declarative EffectDefinition objects) -- Phase 3/8 will add the effect resolution engine that interprets them.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Effects are simple stat-based for starter cards (deal X damage, heal Y HP, buff +Z attack) but the engine must support the full effect system infrastructure
- **D-02:** Trigger types supported: on_play, on_death, on_attack, on_damaged
- **D-03:** Target types supported: single_target, all_enemies, adjacent, self_owner
- **D-04:** Effects are encoded as declarative JSON objects: `{"type": "damage", "target": "single", "amount": 3, "trigger": "on_play"}`
- **D-05:** Starter cards use only simple effects but the system must be extensible for complex effects in Phase 8
- **D-06:** A multi-purpose card (e.g., Minion with React) can be deployed as a minion OR used as a react from hand -- not both. Choosing one consumes the card.
- **D-07:** Each mode has its own separate mana cost (deploy cost vs react cost)
- **D-08:** Once deployed as a minion, the react option is permanently gone for that card instance
- **D-09:** Cards have attributes/elements (dark, light, fire, etc.) for future synergy/weakness mechanics
- **D-10:** Cards can belong to tribes/archetypes (e.g., "Dark Mage") -- cards sharing a tribe may have synergies
- **D-11:** Minion stats: Attack (1-5), Health (1-5), Mana Cost (1-5), Range (0 = melee, 1+ = ranged)
- **D-12:** Maximum 3 copies of any card in a deck
- **D-13:** Deck size minimum = 40 cards
- **D-14:** Each card is its own JSON file (per-card files, not a single monolithic file)
- **D-15:** Effects are fully declarative as data objects in JSON -- no string references to Python functions
- **D-16:** 15-20 unique cards to support full 40+ card decks with 3-copy limit
- **D-17:** Mix of all three types: Minions, Magic, React cards
- **D-18:** At least one multi-purpose card (Minion + React from hand)
- **D-19:** Stats in the 1-5 range for all numeric values

### Claude's Discretion
- Specific starter card designs (names, stats, effects) -- whatever gives RL good signal
- JSON directory structure (e.g., data/cards/ or similar)
- Card ID format and naming conventions
- How the card loader validates JSON against the schema
- Whether to use Python dataclasses or a lighter Card model

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENG-04 | Three card types supported: Minion (deployed to field), Magic (immediate effect), React (counter/interrupt during opponent's action) | CardType IntEnum with MINION/MAGIC/REACT values; CardDefinition dataclass with card_type field; each type has type-specific fields (minion stats vs magic effect vs react effect) |
| ENG-05 | Minions have Attack, Health, Mana Cost, Range, and optional Effects/React effects | CardDefinition fields: attack, health, mana_cost, range, effects list, react_effect optional; validation ensures minion-specific fields present when card_type is MINION |
| ENG-12 | Multi-purpose cards supported (e.g., a Minion card that also has a React effect playable from hand) | CardDefinition with optional react_effect and react_mana_cost fields; when both are present, card is multi-purpose per D-06/D-07/D-08 |
| CARD-01 | Data-driven card definitions in JSON with stats, effects, and keywords interpreted at runtime | Per-card JSON files in data/cards/; CardLoader reads and validates JSON into CardDefinition frozen dataclasses; EffectDefinition as declarative data objects |
| CARD-02 | Starter card pool of 5-10 simple cards for initial RL validation | CONTEXT.md expanded this to 15-20 unique cards (D-16); design a balanced mix of Minions, Magic, React with stats 1-5 and simple stat effects |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| dataclasses (stdlib) | -- | CardDefinition, EffectDefinition modeling | Project convention from Phase 1 -- frozen dataclasses with slots throughout |
| enum (stdlib) | -- | CardType, Attribute, Tribe, EffectType, TriggerType, TargetType | Project convention -- IntEnum for numpy compatibility (Phase 1 pattern) |
| json (stdlib) | -- | Load per-card JSON files | Zero dependencies, built-in, sufficient for simple card data |
| pathlib (stdlib) | -- | Directory traversal for card loading | Cross-platform path handling (Windows host) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| typing (stdlib) | -- | Optional, type annotations | Card fields that may be absent (react_effect on non-multi-purpose cards) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual JSON validation | Pydantic | Pydantic adds runtime validation overhead per-object; project explicitly chose dataclasses over Pydantic for RL performance (millions of game states). Use `__post_init__` validation instead. |
| Manual JSON validation | jsonschema library | Adds a dependency for something achievable with ~50 lines of validation code in `__post_init__`. Not worth the dependency for a well-defined card schema. |
| Per-card JSON files | Single cards.json | User locked decision D-14 requires per-card files. Single file would be simpler to load but harder to diff/version individual cards. |
| IntEnum | StrEnum | IntEnum is the established project pattern for numpy compatibility. StrEnum would be more readable in JSON but breaks consistency. |

**Installation:**
```bash
# No new dependencies -- all stdlib
```

## Architecture Patterns

### Recommended Project Structure
```
src/grid_tactics/
    enums.py          # EXTEND: add CardType, Attribute, Tribe, EffectType, TriggerType, TargetType
    types.py          # EXTEND: add card-related constants (MAX_COPIES_PER_DECK, MIN_DECK_SIZE, stat ranges)
    cards.py          # NEW: CardDefinition, EffectDefinition frozen dataclasses
    card_loader.py    # NEW: CardLoader that reads JSON files into CardDefinition objects
    card_library.py   # NEW: CardLibrary registry mapping card_id -> CardDefinition
    board.py          # UNCHANGED
    player.py         # UNCHANGED
    game_state.py     # UNCHANGED
    validation.py     # UNCHANGED (extend later in Phase 3 to validate card references)
    rng.py            # UNCHANGED

data/
    cards/
        minion_fire_imp.json
        minion_shadow_knight.json
        magic_fireball.json
        react_shield_block.json
        ...                          # 15-20 per-card JSON files

tests/
    test_cards.py          # NEW: CardDefinition creation, validation, immutability
    test_card_loader.py    # NEW: JSON loading, validation errors, missing fields
    test_card_library.py   # NEW: CardLibrary lookup, full pool loading
    test_enums.py          # NEW: CardType, Attribute, Tribe enum coverage
```

### Pattern 1: Frozen Dataclass Card Definition
**What:** Card definitions as frozen dataclasses with `__post_init__` validation, following the exact same pattern as Board/Player/GameState.
**When to use:** Always -- this is the project's established pattern.
**Example:**
```python
# Source: Phase 1 codebase pattern (board.py, player.py, game_state.py)
@dataclass(frozen=True, slots=True)
class EffectDefinition:
    """A single declarative effect on a card."""
    effect_type: EffectType       # damage, heal, buff_attack, buff_health
    trigger: TriggerType          # on_play, on_death, on_attack, on_damaged
    target: TargetType            # single_target, all_enemies, adjacent, self_owner
    amount: int                   # magnitude of the effect (1-5 for starters)

    def __post_init__(self) -> None:
        if not (1 <= self.amount <= 10):
            raise ValueError(f"Effect amount {self.amount} out of range [1, 10]")


@dataclass(frozen=True, slots=True)
class CardDefinition:
    """Immutable card template loaded from JSON. NOT a runtime card instance."""
    card_id: str                          # unique identifier, e.g., "fire_imp"
    name: str                             # display name, e.g., "Fire Imp"
    card_type: CardType                   # MINION, MAGIC, REACT
    mana_cost: int                        # cost to play (deploy or cast)
    
    # Minion-specific (None for non-minions)
    attack: Optional[int] = None
    health: Optional[int] = None
    range: Optional[int] = None           # 0 = melee, 1+ = ranged
    
    # Attributes/tribes (for future synergy, D-09, D-10)
    attribute: Optional[Attribute] = None
    tribe: Optional[str] = None
    
    # Effects (D-01 through D-05)
    effects: tuple[EffectDefinition, ...] = ()
    
    # Multi-purpose react from hand (D-06, D-07, D-08)
    react_effect: Optional[EffectDefinition] = None
    react_mana_cost: Optional[int] = None
    
    @property
    def is_multi_purpose(self) -> bool:
        """True if this card can be deployed OR used as react from hand."""
        return self.react_effect is not None and self.react_mana_cost is not None
```

### Pattern 2: CardLibrary as Lookup Registry
**What:** A class that holds all loaded CardDefinitions and provides O(1) lookup by card_id. The single source of truth for what cards exist in the game.
**When to use:** Any time game code needs to resolve a card_id (int in Player.hand or Board.cells) to its definition.
**Example:**
```python
class CardLibrary:
    """Registry of all card definitions. Loaded once at game startup."""
    
    def __init__(self, cards: dict[str, CardDefinition]) -> None:
        self._cards = cards
        # Build int ID mapping for efficient lookup from Player.hand/Board.cells
        self._id_to_card: dict[int, CardDefinition] = {}
        for i, card_id in enumerate(sorted(cards.keys())):
            self._id_to_card[i] = cards[card_id]
    
    def get_by_id(self, numeric_id: int) -> CardDefinition:
        """Look up card definition by numeric ID (used in Player.hand, Board.cells)."""
        return self._id_to_card[numeric_id]
    
    def get_by_card_id(self, card_id: str) -> CardDefinition:
        """Look up card definition by string card_id."""
        return self._cards[card_id]
    
    @classmethod
    def from_directory(cls, path: Path) -> CardLibrary:
        """Load all card JSON files from a directory."""
        cards = {}
        for json_file in sorted(path.glob("*.json")):
            card_def = CardLoader.load_card(json_file)
            cards[card_def.card_id] = card_def
        return cls(cards)
```

### Pattern 3: Card ID Mapping Strategy
**What:** Player.hand and Board.cells already store `int` IDs. These need to map to card definitions. Use a two-level scheme: card definition IDs (which unique card template, e.g., "fire_imp") and card instance IDs (which specific copy in a game).
**When to use:** Always -- this bridges Phase 1's int-based references to Phase 2's card definitions.
**Example:**
```python
# Card definition: string ID -> numeric index in CardLibrary
# "fire_imp" -> 0, "shadow_knight" -> 1, "fireball" -> 2, etc.
# Sorted alphabetically for deterministic ordering.

# Card instance: unique per-game copy
# Deck building: player includes card_def_id=0 three times -> instance IDs 0, 1, 2
# Player.hand stores instance IDs, which resolve to definition IDs via a mapping.

# In Phase 3, a MinionInstance or CardInstance will track:
#   - instance_id: int (unique in this game)
#   - definition_id: int (which card template)
#   - current_health: int (may differ from definition.health after damage)
```

### Pattern 4: JSON Card Schema
**What:** Per-card JSON files with a consistent schema matching the CardDefinition fields.
**When to use:** Every card definition file.
**Example:**
```json
{
    "card_id": "fire_imp",
    "name": "Fire Imp",
    "card_type": "minion",
    "mana_cost": 2,
    "attack": 3,
    "health": 2,
    "range": 0,
    "attribute": "fire",
    "tribe": "Imp",
    "effects": [
        {
            "type": "damage",
            "trigger": "on_play",
            "target": "single_target",
            "amount": 1
        }
    ]
}
```
Multi-purpose card example:
```json
{
    "card_id": "dark_sentinel",
    "name": "Dark Sentinel",
    "card_type": "minion",
    "mana_cost": 3,
    "attack": 2,
    "health": 3,
    "range": 0,
    "attribute": "dark",
    "tribe": "Dark Mage",
    "effects": [],
    "react_effect": {
        "type": "damage",
        "trigger": "on_play",
        "target": "single_target",
        "amount": 2
    },
    "react_mana_cost": 2
}
```

### Anti-Patterns to Avoid
- **Hardcoded card classes:** Don't create `class FireImp(Card)`. Cards are data, not code. This is locked decision D-01/D-15.
- **String-to-function mapping in effects:** Don't use `{"effect": "apply_damage"}` that maps to a Python function by name. Effects are pure declarative data objects (D-15). The interpreter lives in Phase 3.
- **Mutable card definitions:** Don't use `@dataclass` without `frozen=True`. Card definitions are templates that never change. Runtime mutation (health damage) happens on card instances in Phase 3.
- **Single monolithic cards.json:** D-14 requires per-card files. Don't combine them.
- **Pydantic for card models:** Project explicitly chose dataclasses over Pydantic for RL performance (CLAUDE.md stack decision). Use `__post_init__` for validation.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON file loading | Custom file parser | `json.load()` + `pathlib.Path.glob()` | stdlib is sufficient, zero edge cases for simple card JSON |
| Cross-platform paths | String concatenation for paths | `pathlib.Path` | Windows host requires proper path handling; glob patterns work cross-platform |
| Enum serialization to JSON | Custom string mapping | IntEnum `.name` / `CardType[name]` for string-to-enum conversion | IntEnum has built-in `.name` property and bracket lookup |
| Frozen dataclass validation | External validation library | `__post_init__` with `raise ValueError` | Project pattern; validation code is ~30 lines, not worth a dependency |

**Key insight:** This phase is almost entirely stdlib Python. No external dependencies are needed. The complexity is in the data model design and the starter card pool balance, not in library choice.

## Common Pitfalls

### Pitfall 1: Confusing Card Definitions vs Card Instances
**What goes wrong:** Treating CardDefinition as mutable game state (e.g., tracking current health on the definition). This leads to shared-state bugs where damaging one copy of a card affects all copies.
**Why it happens:** The mental model conflates "what a card IS" (definition) with "what a card is DOING in this game" (instance).
**How to avoid:** CardDefinition is frozen, loaded once, shared. Card instances (Phase 3) are per-game copies that track current_health, has_attacked, position, etc. Phase 2 only builds definitions.
**Warning signs:** Any field on CardDefinition that would need to change during a game.

### Pitfall 2: Integer ID Ambiguity
**What goes wrong:** Player.hand stores `tuple[int, ...]` -- but what do these ints mean? Card definition IDs? Card instance IDs? The answer matters for deck building (3 copies of the same card have different instance IDs but the same definition ID).
**Why it happens:** Phase 1 didn't need to resolve this because cards were abstract.
**How to avoid:** Define the mapping clearly. Recommendation: Player.hand and Board.cells store **instance IDs**. A separate mapping (in Phase 3's game state) resolves instance_id -> definition_id. For Phase 2, document that the CardLibrary maps numeric definition IDs to CardDefinitions, and Phase 3 will add the instance layer.
**Warning signs:** Code that passes `card_id` as `int` without clarifying which ID space.

### Pitfall 3: Effect System Over-Engineering
**What goes wrong:** Building a complex effect resolution engine, condition system, and targeting pipeline when starter cards only use "deal X damage" and "heal Y HP."
**Why it happens:** D-01 says "engine must support the full effect system infrastructure." But infrastructure != implementation. Define the data model now, implement the resolution logic in Phase 3.
**How to avoid:** EffectDefinition as a frozen dataclass with type/trigger/target/amount fields is the "infrastructure." The code that reads an EffectDefinition and applies damage/heals/buffs is Phase 3's ActionResolver. Phase 2 just defines what effects LOOK LIKE as data.
**Warning signs:** Writing an `apply_effect(state, effect)` function in Phase 2.

### Pitfall 4: JSON Validation Gaps
**What goes wrong:** Loading a card JSON with missing fields or wrong types, and the error only surfaces deep in a game when the RL agent tries to play the card.
**Why it happens:** JSON is untyped; `json.load()` returns dicts with Any values.
**How to avoid:** Validate eagerly on load: check required fields exist, types match, enum values are valid, stats are within range (1-5 per D-19). The CardLoader should raise clear errors at load time, not at play time.
**Warning signs:** `card_def.attack` is `None` for a minion because the JSON was missing the field and no validation caught it.

### Pitfall 5: `__post_init__` with `frozen=True` and `slots=True`
**What goes wrong:** Trying to set computed fields in `__post_init__` on a frozen dataclass raises `FrozenInstanceError`.
**Why it happens:** `frozen=True` blocks all `__setattr__` calls, including in `__post_init__`.
**How to avoid:** For validation-only `__post_init__` (checking invariants, raising on bad data), there is no issue -- just read fields and raise. If you need to set a computed field, use `object.__setattr__(self, 'field_name', value)`. But prefer `@property` for computed values to avoid this complexity entirely.
**Warning signs:** Getting `FrozenInstanceError` in `__post_init__` when trying to assign a derived field.

### Pitfall 6: Starter Card Pool Imbalance
**What goes wrong:** Creating 15 minions and 2 spells, or making all cards cost 1 mana, resulting in degenerate RL strategies.
**Why it happens:** Designing cards without considering the mana curve and type distribution.
**How to avoid:** Design a balanced mana curve (some 1-cost, some 2-cost, up to 4-5 cost). Mix card types: ~8-10 minions, ~3-5 magic, ~2-4 react, ~1-2 multi-purpose. Vary ranges (melee vs ranged). The RL agent needs strategic variety to learn interesting play.
**Warning signs:** The RL agent converges on a single dominant strategy in early testing (Phase 6).

## Code Examples

### Enum Extensions for Card System
```python
# Source: Pattern consistent with existing enums.py (IntEnum for numpy compat)
from enum import IntEnum

class CardType(IntEnum):
    """Card type determines play rules and which fields are relevant."""
    MINION = 0  # Deployed to board, has attack/health/range
    MAGIC = 1   # Immediate effect, then discarded
    REACT = 2   # Played during opponent's action window

class Attribute(IntEnum):
    """Elemental attribute for future synergy mechanics (D-09)."""
    NEUTRAL = 0
    FIRE = 1
    DARK = 2
    LIGHT = 3
    # Extensible -- add more as card pool grows

class EffectType(IntEnum):
    """What the effect does. Starter cards use damage/heal/buff only (D-01)."""
    DAMAGE = 0
    HEAL = 1
    BUFF_ATTACK = 2
    BUFF_HEALTH = 3
    # Phase 8 extensibility: DEBUFF, DRAW, DESTROY, MOVE, etc.

class TriggerType(IntEnum):
    """When the effect activates (D-02)."""
    ON_PLAY = 0    # When the card is played/deployed
    ON_DEATH = 1   # When the minion dies
    ON_ATTACK = 2  # When the minion attacks
    ON_DAMAGED = 3 # When the minion takes damage

class TargetType(IntEnum):
    """What the effect targets (D-03)."""
    SINGLE_TARGET = 0  # Player chooses one target
    ALL_ENEMIES = 1    # Hits all enemy minions
    ADJACENT = 2       # Hits all adjacent units
    SELF_OWNER = 3     # Affects self or owning player
```

### CardDefinition Validation in `__post_init__`
```python
# Source: Consistent with project pattern (validation.py returns errors, 
# but __post_init__ raises on construction for fail-fast loading)
def __post_init__(self) -> None:
    """Validate card definition invariants at construction time."""
    # Type-specific field validation
    if self.card_type == CardType.MINION:
        if self.attack is None or self.health is None:
            raise ValueError(f"Card '{self.card_id}': Minion must have attack and health")
        if self.range is None:
            raise ValueError(f"Card '{self.card_id}': Minion must have range")
        # Stat range validation (D-19)
        for field_name, value in [("attack", self.attack), ("health", self.health)]:
            if not (1 <= value <= 5):
                raise ValueError(f"Card '{self.card_id}': {field_name}={value} out of range [1, 5]")
    
    # Mana cost validation
    if not (1 <= self.mana_cost <= 5):
        raise ValueError(f"Card '{self.card_id}': mana_cost={self.mana_cost} out of range [1, 5]")
    
    # Multi-purpose consistency (D-06, D-07)
    if (self.react_effect is None) != (self.react_mana_cost is None):
        raise ValueError(
            f"Card '{self.card_id}': react_effect and react_mana_cost must both be set or both be None"
        )
    
    # Only minions can be multi-purpose (D-06)
    if self.react_effect is not None and self.card_type != CardType.MINION:
        raise ValueError(f"Card '{self.card_id}': Only minions can be multi-purpose")
```

### CardLoader JSON-to-Dataclass Conversion
```python
# Source: Standard json.load() + manual field mapping (project avoids external deps)
import json
from pathlib import Path

class CardLoader:
    """Loads per-card JSON files into CardDefinition frozen dataclasses."""
    
    @staticmethod
    def load_card(path: Path) -> CardDefinition:
        """Load a single card definition from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)
        
        # Parse effects list
        effects = tuple(
            EffectDefinition(
                effect_type=EffectType[e["type"].upper()],
                trigger=TriggerType[e["trigger"].upper()],
                target=TargetType[e["target"].upper()],
                amount=e["amount"],
            )
            for e in data.get("effects", [])
        )
        
        # Parse optional react effect
        react_data = data.get("react_effect")
        react_effect = None
        if react_data:
            react_effect = EffectDefinition(
                effect_type=EffectType[react_data["type"].upper()],
                trigger=TriggerType[react_data["trigger"].upper()],
                target=TargetType[react_data["target"].upper()],
                amount=react_data["amount"],
            )
        
        # Parse optional attribute
        attr_str = data.get("attribute")
        attribute = Attribute[attr_str.upper()] if attr_str else None
        
        return CardDefinition(
            card_id=data["card_id"],
            name=data["name"],
            card_type=CardType[data["card_type"].upper()],
            mana_cost=data["mana_cost"],
            attack=data.get("attack"),
            health=data.get("health"),
            range=data.get("range"),
            attribute=attribute,
            tribe=data.get("tribe"),
            effects=effects,
            react_effect=react_effect,
            react_mana_cost=data.get("react_mana_cost"),
        )
```

### Starter Card Pool Design Guidance
```python
# Design principles for 15-20 starter cards:
#
# Mana curve distribution (D-19: stats 1-5):
#   1-cost: 3-4 cards (cheap aggressive options)
#   2-cost: 5-6 cards (core mid-range)
#   3-cost: 4-5 cards (strong mid-game)
#   4-cost: 2-3 cards (powerful late options)
#   5-cost: 1-2 cards (game-changers)
#
# Type distribution (D-17):
#   Minions: 8-10 (core board presence)
#   Magic: 3-5 (direct effects)
#   React: 2-4 (counter/interrupt)
#   Multi-purpose: 1-2 (Minion + React, per D-18)
#
# Range distribution:
#   Melee (range=0): 5-6 minions
#   Ranged (range=1-2): 3-4 minions
#
# Attribute distribution (D-09):
#   Fire: 4-5 cards (aggressive theme)
#   Dark: 4-5 cards (control/sacrifice theme)
#   Light: 4-5 cards (defensive/heal theme)
#   Neutral: 2-3 cards (versatile)
#
# Effect distribution (D-01):
#   Damage effects: most common
#   Heal effects: light-themed cards
#   Buff attack: aggressive support
#   Buff health: defensive support
#
# RL signal considerations:
#   - Cards should have clear tradeoffs (high attack = low health, etc.)
#   - Mana cost should correlate with power level
#   - React cards should meaningfully counter common actions
#   - Multi-purpose cards should have a real decision (deploy vs. react)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded card classes (class per card) | Data-driven JSON definitions | Standard practice since Hearthstone-era TCG engines (~2015+) | Enables automated balance sweeps without code changes |
| Mutable card objects | Frozen definition + mutable instance | Python dataclasses matured (3.7+, slots in 3.10+) | Prevents shared-state bugs, enables replay/undo |
| Single large YAML/JSON file | Per-entity files | Modern game dev convention | Better VCS diffs, easier card-by-card iteration |
| Pydantic for game data | stdlib dataclasses | Project-specific decision for RL performance | Avoids validation overhead on millions of state copies |

## Open Questions

1. **Numeric ID assignment strategy**
   - What we know: Player.hand stores `tuple[int, ...]` and Board.cells stores `Optional[int]`. CardLibrary needs a numeric ID for each card definition.
   - What's unclear: Should numeric IDs be auto-assigned (sorted alphabetical order) or explicitly set in JSON? Auto-assignment is simpler but fragile if cards are added/removed. Explicit is more work but stable.
   - Recommendation: Use auto-assignment from sorted card_id strings for Phase 2. If stability matters later (e.g., for saved models), add explicit `numeric_id` to JSON in a future phase. Document the mapping determinism.

2. **Deck building API**
   - What we know: D-12 (max 3 copies), D-13 (min 40 cards). GameState.new_game() takes `deck_p1` and `deck_p2` as `tuple[int, ...]`.
   - What's unclear: Should Phase 2 include a deck builder/validator, or is that Phase 3?
   - Recommendation: Include basic deck validation in Phase 2 (validate that a deck tuple satisfies D-12 and D-13 constraints against a CardLibrary). Deck construction can be a helper function. This is needed to create valid test decks.

3. **`range` field naming**
   - What we know: Python has a built-in `range()` function. Using `range` as a dataclass field name shadows it.
   - What's unclear: Whether this causes practical issues.
   - Recommendation: Use `attack_range` instead of `range` to avoid shadowing the builtin. This is clearer and avoids subtle bugs.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 8.0 |
| Config file | pyproject.toml `[tool.pytest.ini_options]` |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/ -x -q` |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENG-04 | CardType enum has MINION, MAGIC, REACT values | unit | `.venv/Scripts/python.exe -m pytest tests/test_enums.py -x` | Wave 0 |
| ENG-04 | CardDefinition accepts all three card types | unit | `.venv/Scripts/python.exe -m pytest tests/test_cards.py::TestCardTypes -x` | Wave 0 |
| ENG-05 | Minion cards have attack, health, mana_cost, range, effects | unit | `.venv/Scripts/python.exe -m pytest tests/test_cards.py::TestMinionFields -x` | Wave 0 |
| ENG-05 | Minion stats validated to 1-5 range | unit | `.venv/Scripts/python.exe -m pytest tests/test_cards.py::TestStatValidation -x` | Wave 0 |
| ENG-12 | Multi-purpose card has react_effect and react_mana_cost | unit | `.venv/Scripts/python.exe -m pytest tests/test_cards.py::TestMultiPurpose -x` | Wave 0 |
| ENG-12 | Non-minion cards cannot be multi-purpose | unit | `.venv/Scripts/python.exe -m pytest tests/test_cards.py::TestMultiPurposeValidation -x` | Wave 0 |
| CARD-01 | JSON files load into CardDefinition objects | unit | `.venv/Scripts/python.exe -m pytest tests/test_card_loader.py -x` | Wave 0 |
| CARD-01 | Invalid JSON raises clear validation errors | unit | `.venv/Scripts/python.exe -m pytest tests/test_card_loader.py::TestLoaderValidation -x` | Wave 0 |
| CARD-01 | EffectDefinition parsed from JSON effect objects | unit | `.venv/Scripts/python.exe -m pytest tests/test_cards.py::TestEffectDefinition -x` | Wave 0 |
| CARD-02 | CardLibrary loads 15-20 starter cards from data/cards/ | integration | `.venv/Scripts/python.exe -m pytest tests/test_card_library.py::TestStarterPool -x` | Wave 0 |
| CARD-02 | All starter cards pass validation | integration | `.venv/Scripts/python.exe -m pytest tests/test_card_library.py::TestStarterPoolValid -x` | Wave 0 |
| CARD-02 | Starter pool has all three card types | integration | `.venv/Scripts/python.exe -m pytest tests/test_card_library.py::TestStarterPoolTypes -x` | Wave 0 |
| CARD-02 | At least one multi-purpose card in starter pool | integration | `.venv/Scripts/python.exe -m pytest tests/test_card_library.py::TestStarterPoolMultiPurpose -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python.exe -m pytest tests/ -x -q`
- **Per wave merge:** `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_enums.py` -- covers ENG-04 (CardType enum), plus Attribute, Tribe, EffectType, TriggerType, TargetType
- [ ] `tests/test_cards.py` -- covers ENG-04, ENG-05, ENG-12, CARD-01 (CardDefinition, EffectDefinition)
- [ ] `tests/test_card_loader.py` -- covers CARD-01 (JSON loading and validation)
- [ ] `tests/test_card_library.py` -- covers CARD-02 (starter pool loading and validation)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | Yes | 3.12.10 | -- |
| pytest | Testing | Yes | (in .venv) | -- |
| numpy | Existing dependency | Yes | (in .venv) | -- |
| json (stdlib) | Card loading | Yes | -- | -- |
| pathlib (stdlib) | File paths | Yes | -- | -- |

No external dependencies needed. All tools available.

## Sources

### Primary (HIGH confidence)
- Phase 1 codebase: `src/grid_tactics/board.py`, `player.py`, `game_state.py`, `enums.py`, `types.py` -- established patterns
- CONTEXT.md decisions D-01 through D-19 -- locked user decisions
- REQUIREMENTS.md -- ENG-04, ENG-05, ENG-12, CARD-01, CARD-02 requirement text
- ARCHITECTURE.md -- Card/CardLibrary component boundary definition, Layer 1 game engine pattern
- [Python dataclasses documentation](https://docs.python.org/3/library/dataclasses.html) -- `__post_init__`, `frozen=True`, `slots=True`

### Secondary (MEDIUM confidence)
- [Benny Cheung: Game Architecture for Card Game AI](https://bennycheung.github.io/game-architecture-card-ai-1) -- Card as data pattern, separation of card definition vs instance
- [RLCard Architecture](https://rlcard.org/overview.html) -- Card data modeling in RL context
- [Python frozen dataclass __post_init__ patterns](https://www.pythonmorsels.com/customizing-dataclass-initialization/) -- Validation in frozen dataclasses

### Tertiary (LOW confidence)
- None -- this phase is well-understood stdlib Python; no novel libraries or patterns involved

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all stdlib, no library decisions needed
- Architecture: HIGH -- extends established Phase 1 patterns with clear data modeling
- Pitfalls: HIGH -- well-known patterns from game engine development; card definition vs instance confusion is the classic trap
- Starter card pool design: MEDIUM -- card balance is inherently subjective; RL will validate in later phases

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable -- stdlib only, no library version concerns)
