# Phase 1: Game State Foundation - Research

**Researched:** 2026-04-02
**Domain:** Immutable game state representation for a 5x5 grid tactical card game (Python, pure engine layer)
**Confidence:** HIGH

## Summary

Phase 1 establishes the foundational data model for Grid Tactics TCG: an immutable `GameState` object representing a 5x5 grid with row ownership, a mana system with banking, player state, and a deterministic seeded RNG. This phase delivers the data model only -- no game logic, card effects, action resolution, or RL integration.

The core technical challenge is designing an immutable state representation that is correct, fast to copy/create, serializable for replay, and deterministically reproducible via seeded RNG. The recommended approach uses Python's `@dataclass(frozen=True, slots=True)` with `tuple` for all collection fields (never `list`) and `dataclasses.replace()` for producing new states. The RNG uses `numpy.random.default_rng(seed)` with the Generator passed explicitly through the state, never relying on global random state.

This phase is greenfield -- no existing code, no virtual environment, no project structure. The plan must include project scaffolding (directory layout, pyproject.toml, venv creation) before any game state implementation.

**Primary recommendation:** Use `@dataclass(frozen=True, slots=True)` with tuple-only collections, `dataclasses.replace()` for state transitions, and `numpy.random.default_rng(seed)` for deterministic RNG. Keep the game engine layer free of any RL/ML dependencies.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Fixed row assignment: Rows 0-1 = Player 1, Row 2 = No-man's-land, Rows 3-4 = Player 2
- **D-02:** All 5 columns are equal -- no special column rules or bonuses
- **D-03:** One minion per space -- no stacking allowed, must move around blockers
- **D-04:** Minions can move in all 4 directions (up, down, left, right) -- movement logic is Phase 3 but the grid must support adjacency queries in all directions plus diagonal for ranged attacks
- **D-05:** Starting mana pool = 1
- **D-06:** Mana regenerates +1 per turn
- **D-07:** Maximum mana pool cap = 10
- **D-08:** Unspent mana carries over between turns (banking) up to the cap
- **D-09:** Starting HP = 20 per player
- **D-10:** Starting hand size = 5 cards
- **D-11:** Deck size = 40+ cards (enforced at deck validation, not in game state)

### Claude's Discretion
- First-turn advantage balancing (e.g., first player skips first action, or draws one fewer card) -- RL can test variants
- State immutability approach (deep copy vs structural sharing vs action log) -- pick what's best for RL training throughput
- Serialization format (Python dict, JSON, or hybrid) -- pick what's most practical for both speed and replay

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENG-01 | Game enforces complete rule set on a 5x5 grid with row ownership, no-man's-land middle row, and deployment zones | Frozen dataclass Board with 5x5 numpy array or tuple-of-tuples; row ownership encoded as PlayerSide enum; adjacency helpers for 4-direction + diagonal |
| ENG-02 | Mana pool regenerates +1 per turn with unspent mana carrying over (banking) | Mana fields on Player dataclass (current_mana, max_mana); regeneration is a pure function producing new Player via replace(); cap enforced with min() |
| ENG-11 | Deterministic seeded RNG ensures reproducible game outcomes for debugging and replay | numpy.random.default_rng(seed) passed through GameState; no global random state; replay function verifies determinism |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Language:** Python for game engine and RL
- **Testing:** Each development step validated with RL to confirm strategic depth
- **RL focus:** Core strategy discovery is the priority
- **GSD Workflow:** Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it

## Standard Stack

### Core (Phase 1 only -- game engine layer)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.12.10 | Runtime | Installed on this machine. All key libraries support 3.12. Avoids 3.13 PettingZoo incompatibility. |
| NumPy | >=2.2,<3.0 | Board state arrays, seeded RNG | `numpy.random.default_rng()` provides the deterministic RNG. Board can use numpy arrays internally. Required by all downstream RL libraries. |
| dataclasses (stdlib) | -- | GameState, Player, Board modeling | `frozen=True` + `slots=True` for immutability. Zero-dependency. 2.4x slower instantiation than mutable but correctness and safety outweigh cost at this stage. |
| enum (stdlib) | -- | PlayerSide, TurnPhase, CardType | Type-safe constants. IntEnum for serialization efficiency. |

### Supporting (dev dependencies)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | >=8.0 | Test framework | Test every invariant exhaustively -- game engine bugs silently corrupt RL training |
| pytest-cov | >=5.0 | Coverage reporting | Target >90% coverage on game state code |
| mypy | >=1.13 | Static type checking | Type annotations on all dataclasses catch mutation bugs at lint time |
| ruff | >=0.9 | Linting and formatting | Single tool for code quality |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `frozen=True` dataclass | Pydantic BaseModel | Pydantic adds runtime validation overhead (~5-10x slower instantiation). Overkill for game engine where the engine itself validates moves. Only use if you need API serialization later. |
| `frozen=True` dataclass | Plain dict | Loses type safety, IDE support, and frozen enforcement. Faster but error-prone. Not recommended for complex nested state. |
| `frozen=True` dataclass | attrs `@frozen` | Functionally identical to dataclass frozen. Minor API differences. dataclass is stdlib -- no extra dependency. |
| `dataclasses.replace()` | Deep copy + mutate | Deep copy is ~10x slower than replace() for nested structures. replace() with tuples achieves structural sharing naturally (unchanged fields share references). |
| numpy array for board | tuple-of-tuples | numpy array is faster for numeric operations and observation encoding downstream. tuple-of-tuples is more Pythonic but requires conversion for RL. Use numpy internally, expose via properties. |

**Installation (Phase 1 only):**
```bash
# Create virtual environment with Python 3.12
"$LOCALAPPDATA/Programs/Python/Python312/python.exe" -m venv .venv
source .venv/Scripts/activate  # Windows bash

# Core
pip install numpy

# Dev
pip install pytest pytest-cov mypy ruff
```

## Architecture Patterns

### Recommended Project Structure
```
grid-tactics-tcg/
├── pyproject.toml          # Project metadata, dependencies, tool config
├── src/
│   └── grid_tactics/
│       ├── __init__.py
│       ├── enums.py         # PlayerSide, TurnPhase, CardType
│       ├── types.py         # Type aliases (Position, GridArray)
│       ├── board.py         # Board dataclass + adjacency helpers
│       ├── player.py        # Player dataclass (mana, HP, hand, deck)
│       ├── game_state.py    # GameState dataclass (top-level container)
│       ├── rng.py           # RNG wrapper for deterministic seeded randomness
│       └── validation.py    # GameState invariant checks
├── tests/
│   ├── conftest.py          # Shared fixtures (factory functions for states)
│   ├── test_board.py        # Grid geometry, adjacency, row ownership
│   ├── test_player.py       # Mana regen, HP, hand management
│   ├── test_game_state.py   # Full state creation, immutability, serialization
│   ├── test_rng.py          # Determinism, reproducibility
│   └── test_validation.py   # Invariant checking
└── .venv/                   # Virtual environment (gitignored)
```

### Pattern 1: Frozen Dataclass with Tuple Collections

**What:** All game state objects use `@dataclass(frozen=True, slots=True)`. All collection fields use `tuple` (never `list`). New states are produced via `dataclasses.replace()`.

**When to use:** Always -- this is the foundation pattern for this project.

**Why:** Frozen dataclasses prevent accidental mutation. Using `tuple` instead of `list` ensures nested immutability (a frozen dataclass with a list field is NOT truly immutable -- the list can still be mutated). `slots=True` prevents dynamic attribute addition and reduces memory usage.

**Example:**
```python
# Source: Python 3.12 dataclasses documentation
from dataclasses import dataclass, field, replace
from typing import Optional
import numpy as np

@dataclass(frozen=True, slots=True)
class Player:
    hp: int
    current_mana: int
    max_mana: int
    hand: tuple[int, ...]       # card IDs, NOT a list
    deck: tuple[int, ...]       # card IDs, NOT a list
    graveyard: tuple[int, ...]  # card IDs, NOT a list

    def with_mana_regen(self) -> 'Player':
        """Produce a new Player with +1 mana (capped at max_mana)."""
        new_max = min(self.max_mana + 1, 10)  # D-06, D-07
        new_current = min(self.current_mana + new_max - self.max_mana + 1, new_max)
        return replace(self, current_mana=new_current, max_mana=new_max)

@dataclass(frozen=True, slots=True)
class GameState:
    board: tuple[tuple[Optional[int], ...], ...]  # 5x5, None = empty
    players: tuple[Player, Player]
    active_player_idx: int
    turn_number: int
    rng_state: bytes  # serialized RNG state for determinism
```

### Pattern 2: Seeded RNG via numpy.random.Generator

**What:** All randomness flows through a `numpy.random.Generator` instance created with `default_rng(seed)`. The RNG is passed explicitly, never stored as global state.

**When to use:** Any operation requiring randomness (deck shuffle, random effects).

**Why:** Guarantees deterministic reproducibility. Two games with the same seed produce identical state sequences. The RNG state can be serialized for replay.

**Example:**
```python
# Source: NumPy v2.4 Random Generator documentation
import numpy as np

def create_game(seed: int) -> tuple['GameState', np.random.Generator]:
    """Create a new game with deterministic RNG."""
    rng = np.random.default_rng(seed)
    # Shuffle decks using this rng
    deck_p1 = list(range(40))
    rng.shuffle(deck_p1)
    deck_p2 = list(range(40))
    rng.shuffle(deck_p2)
    # ... build initial state
    return state, rng

def replay_game(seed: int, actions: list) -> 'GameState':
    """Replay a game deterministically from seed + action sequence."""
    state, rng = create_game(seed)
    for action in actions:
        state, rng = apply_action(state, action, rng)
    return state
```

**RNG state serialization:** The `numpy.random.Generator` exposes `rng.bit_generator.state` as a dict that can be serialized. To restore: create a new Generator and set its state. This enables saving/loading mid-game for replay.

### Pattern 3: Separate GameState from PlayerObservation (Future-Proofing)

**What:** `GameState` contains the full ground truth (both players' hands, deck order, RNG state). `PlayerObservation` (not built in Phase 1, but the GameState must be designed to support it) will contain only what one player can legally see.

**When to use:** Design GameState with this separation in mind even though PlayerObservation is built in Phase 5.

**Why:** If GameState leaks hidden info into the RL observation, training results are invalidated. Designing for this separation from the start prevents a costly retrofit.

**Design implication:** Keep each player's private data (hand, deck) as separate fields on the Player dataclass, not mixed into the Board. This makes it easy to later build `get_observation(player_idx)` that returns visible board + own hand + opponent's public info only.

### Pattern 4: Mana System as Pure Functions

**What:** Mana operations (regen, spend, bank) are pure functions that take a Player and return a new Player. No mutation.

**When to use:** All mana operations.

**Example:**
```python
def regenerate_mana(player: Player, turn_number: int) -> Player:
    """
    Mana regen: +1 per turn, banking enabled, cap at 10.
    D-05: Start 1, D-06: +1/turn, D-07: cap 10, D-08: banking
    """
    # Turn 1: max_mana=1, Turn 2: max_mana=2, ... Turn 10+: max_mana=10
    new_max = min(turn_number, 10)
    # Current mana = banked (carried over) + new_max
    # But actually: regen gives you your max_mana for this turn
    # Banking means current_mana starts at whatever was unspent + new regen
    new_current = min(player.current_mana + new_max, 10)
    return replace(player, current_mana=new_current, max_mana=new_max)

def spend_mana(player: Player, cost: int) -> Player:
    """Spend mana. Raises if insufficient."""
    if player.current_mana < cost:
        raise ValueError(f"Insufficient mana: {player.current_mana} < {cost}")
    return replace(player, current_mana=player.current_mana - cost)
```

**Open design question for mana regen:** The exact mana regeneration formula needs clarification. Two interpretations exist:
- **Interpretation A (like Hearthstone):** Each turn, your mana crystals increase by 1 (max 10). Your mana refills to your crystal count. Banking means unspent mana carries over (so current_mana = unspent + max_mana_this_turn, capped at 10).
- **Interpretation B (simpler):** You gain +1 mana per turn. Unspent mana carries over. Current mana = previous_unspent + 1, capped at 10.

Based on D-05 through D-08, Interpretation B is more consistent: "Starting mana pool = 1, regenerates +1 per turn, cap 10, banking." This means: Turn 1 you have 1 mana. If you spend 0, Turn 2 you have 2 (1 banked + 1 regen). If you spend 1 on Turn 1, Turn 2 you have 1 (0 banked + 1 regen). Cap at 10. **Use Interpretation B.**

### Anti-Patterns to Avoid

- **Mutable collections in frozen dataclasses:** A `@dataclass(frozen=True)` with a `list` field is NOT truly immutable. The list can still be `.append()`ed to. Always use `tuple` for collections.
- **Global RNG state:** Never use `numpy.random.seed()` or `random.seed()`. These set global state that can be corrupted by any other code. Always use `numpy.random.default_rng(seed)` and pass the Generator explicitly.
- **Deep-copying entire state:** `copy.deepcopy()` on a complex game state is ~10x slower than `dataclasses.replace()` with structural sharing (unchanged tuple fields share memory). Replace only what changed.
- **Storing the numpy.random.Generator inside the frozen dataclass:** The Generator is mutable (its state advances on each call). Instead, store the RNG state as serialized bytes or a seed + call count alongside the GameState, and pass the Generator separately.
- **Board as nested Python objects:** Don't model each cell as a class instance in a list-of-lists. Use a flat structure (numpy array or tuple-of-tuples with integer/None values) for the 5x5 grid. Cell contents reference card IDs or minion IDs, not full card objects.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Random number generation | Custom PRNG or `random.Random` | `numpy.random.default_rng(seed)` | NumPy's PCG64 is statistically superior, supports spawning child generators for parallelism, and integrates with the RL stack downstream |
| Immutable data containers | Manual `__setattr__` override | `@dataclass(frozen=True, slots=True)` | Stdlib, battle-tested, works with `replace()`, `asdict()`, type checkers |
| State serialization | Custom recursive serializer | `dataclasses.asdict()` + `json.dumps()` (or `orjson` for speed) | `asdict()` handles nested dataclasses recursively. orjson is 40-50x faster than stdlib json for dataclasses |
| Adjacency/distance on grid | Manual coordinate math scattered everywhere | Centralized `Board.get_adjacent(pos)` and `Board.get_distance(a, b)` methods | Single source of truth for grid geometry prevents off-by-one bugs that corrupt RL training |
| Mana cap enforcement | Ad-hoc `min()` calls everywhere | Centralized `Player.with_mana_regen()` and `spend_mana()` functions | Consistent enforcement of D-07 (cap 10) and D-08 (banking) in one place |

**Key insight:** In a game engine that feeds RL training, every hand-rolled solution is a potential source of silent rule bugs. The RL agent will find and exploit any inconsistency. Centralize all rule logic into tested, single-source-of-truth functions.

## Common Pitfalls

### Pitfall 1: Mutable Collections in Frozen Dataclasses
**What goes wrong:** Developer uses `list` for hand, deck, or graveyard fields in a frozen dataclass. The dataclass appears immutable but the lists can be mutated, creating aliasing bugs where two "different" states share and mutate the same list.
**Why it happens:** Python's `frozen=True` only prevents attribute reassignment, not mutation of mutable attribute values.
**How to avoid:** Use `tuple` for ALL collection fields. Convert lists to tuples in `__post_init__` if needed. Add a test that attempts to mutate every collection field and asserts it raises TypeError.
**Warning signs:** Two GameState objects that should be independent show correlated changes.

### Pitfall 2: RNG State Not Properly Managed
**What goes wrong:** The RNG Generator is stored inside the frozen GameState (impossible -- it's mutable) or stored as a module-level global. When states are replayed or compared, the RNG is in a different position and results differ.
**Why it happens:** The numpy Generator is mutable by nature (its internal state advances with each call). This conflicts with immutable state design.
**How to avoid:** Pass the RNG as a separate parameter alongside GameState in all functions. Store the initial seed in the GameState for replay. For mid-game save/load, serialize `rng.bit_generator.state` separately.
**Warning signs:** Replaying the same seed + actions produces different outcomes. Nondeterministic test failures.

### Pitfall 3: Mana Regen Logic Off-by-One
**What goes wrong:** Mana regeneration is applied at the wrong point in the turn sequence (before vs after the action), or the banking math double-counts the regen, or the cap is enforced inconsistently.
**Why it happens:** The mana system has four interacting rules (D-05 through D-08) that must all be correct simultaneously.
**How to avoid:** Write exhaustive turn-sequence tests: "Turn 1 start: 1 mana. Spend 0. Turn 2 start: 2 mana. Spend 1. Turn 3 start: 2 mana (1 banked + 1 regen)." Test the cap at 10. Test that spending all mana on turn 9 gives exactly 1 mana on turn 10.
**Warning signs:** RL agent discovers infinite mana exploit. Games end impossibly quickly due to mana underflow/overflow.

### Pitfall 4: Grid Adjacency Bugs
**What goes wrong:** Adjacency helper returns out-of-bounds positions, or omits edge cells, or confuses row-column ordering. Range calculations for ranged attacks (diagonal adjacency) are incorrect.
**Why it happens:** 5x5 grid has 4 corners (2 neighbors each), 12 edges (3 neighbors each), and 9 interior cells (4 neighbors each). Diagonal adjacency adds more edge cases.
**How to avoid:** Test adjacency for every cell position (all 25). Test distance calculations between corner-to-corner, adjacent, and diagonal pairs. Use (row, col) consistently everywhere -- never mix (x, y) and (row, col).
**Warning signs:** Ranged units can attack through walls or from impossible positions. Minions move to position (-1, 3).

### Pitfall 5: Slow State Creation Blocking Future RL Training
**What goes wrong:** GameState creation via frozen dataclass + deep nested structures takes >1ms per state. At 10,000+ states per game and millions of games, this becomes the bottleneck.
**Why it happens:** Frozen dataclasses are 2.4x slower to instantiate. `dataclasses.replace()` on deeply nested structures can be expensive.
**How to avoid:** Use `slots=True` (reduces memory and access time). Keep nesting shallow (GameState -> Player, Board -- not GameState -> Board -> Row -> Cell -> Minion). Use numpy arrays for the board grid internally. Profile state creation time early and target <0.1ms per `replace()` call.
**Warning signs:** State creation dominates profiling output. Single game simulation takes >100ms.

## Code Examples

Verified patterns from official sources:

### Frozen Dataclass with Slots and Tuple Collections
```python
# Source: Python 3.12 dataclasses documentation
from dataclasses import dataclass, field, replace
from enum import IntEnum
from typing import Optional

class PlayerSide(IntEnum):
    PLAYER_1 = 0
    PLAYER_2 = 1

class TurnPhase(IntEnum):
    ACTION = 0
    REACT = 1

@dataclass(frozen=True, slots=True)
class Player:
    """Immutable player state."""
    side: PlayerSide
    hp: int
    current_mana: int
    max_mana: int
    hand: tuple[int, ...]        # card IDs
    deck: tuple[int, ...]        # card IDs (top = index 0)
    graveyard: tuple[int, ...]   # card IDs

@dataclass(frozen=True, slots=True)
class BoardCell:
    """What occupies a single grid cell. None fields = empty cell."""
    owner: Optional[PlayerSide] = None
    minion_id: Optional[int] = None

@dataclass(frozen=True, slots=True)
class GameState:
    """Complete immutable game state snapshot."""
    # Board: 5 rows x 5 cols, stored as flat tuple for performance
    board: tuple[Optional[int], ...]  # 25 entries, None = empty, int = minion_id
    players: tuple[Player, Player]
    active_player_idx: int
    phase: TurnPhase
    turn_number: int
    seed: int                         # initial seed for replay
    rng_call_count: int               # how many RNG calls have been made

    @property
    def active_player(self) -> Player:
        return self.players[self.active_player_idx]

    @property
    def inactive_player(self) -> Player:
        return self.players[1 - self.active_player_idx]
```

### Seeded Deterministic RNG
```python
# Source: NumPy v2.4 Random Generator documentation
import numpy as np

def create_rng(seed: int) -> np.random.Generator:
    """Create a deterministic RNG from seed."""
    return np.random.default_rng(seed)

def shuffle_deck(deck: tuple[int, ...], rng: np.random.Generator) -> tuple[int, ...]:
    """Shuffle a deck deterministically. Returns new tuple, does not mutate."""
    deck_list = list(deck)
    rng.shuffle(deck_list)
    return tuple(deck_list)

def draw_card(player: Player) -> tuple[Player, int]:
    """Draw the top card from deck. Returns (new_player, drawn_card_id)."""
    if not player.deck:
        raise ValueError("Cannot draw from empty deck")
    card_id = player.deck[0]
    new_player = replace(
        player,
        hand=player.hand + (card_id,),
        deck=player.deck[1:],
    )
    return new_player, card_id
```

### Grid Adjacency Helpers
```python
# Source: Standard grid geometry
from typing import Iterator

ROWS = 5
COLS = 5

Position = tuple[int, int]  # (row, col)

def is_valid_position(pos: Position) -> bool:
    """Check if position is within the 5x5 grid."""
    r, c = pos
    return 0 <= r < ROWS and 0 <= c < COLS

def get_orthogonal_adjacent(pos: Position) -> tuple[Position, ...]:
    """Get all valid orthogonally adjacent positions (4-direction)."""
    r, c = pos
    candidates = ((r-1, c), (r+1, c), (r, c-1), (r, c+1))
    return tuple(p for p in candidates if is_valid_position(p))

def get_diagonal_adjacent(pos: Position) -> tuple[Position, ...]:
    """Get all valid diagonally adjacent positions (for ranged attacks)."""
    r, c = pos
    candidates = ((r-1, c-1), (r-1, c+1), (r+1, c-1), (r+1, c+1))
    return tuple(p for p in candidates if is_valid_position(p))

def get_all_adjacent(pos: Position) -> tuple[Position, ...]:
    """Get all 8-direction adjacent positions (orthogonal + diagonal)."""
    return get_orthogonal_adjacent(pos) + get_diagonal_adjacent(pos)

def manhattan_distance(a: Position, b: Position) -> int:
    """Manhattan distance between two positions."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def chebyshev_distance(a: Position, b: Position) -> int:
    """Chebyshev distance (includes diagonal as 1 step)."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

def get_row_owner(row: int) -> Optional['PlayerSide']:
    """Which player owns this row? None for no-man's-land."""
    if row in (0, 1):
        return PlayerSide.PLAYER_1
    elif row in (3, 4):
        return PlayerSide.PLAYER_2
    else:  # row 2
        return None  # No-man's-land
```

### State Serialization
```python
# Source: Python dataclasses.asdict + json documentation
import json
from dataclasses import asdict

def state_to_dict(state: GameState) -> dict:
    """Convert GameState to a plain dict for serialization."""
    return asdict(state)

def state_to_json(state: GameState) -> str:
    """Serialize GameState to JSON string."""
    return json.dumps(asdict(state), separators=(',', ':'))

# For high-performance serialization (Phase 5+), consider orjson:
# import orjson
# def state_to_json_fast(state: GameState) -> bytes:
#     return orjson.dumps(asdict(state))
```

### Determinism Verification Test
```python
# Source: Pattern from PITFALLS.md - Pitfall 11
def test_deterministic_replay():
    """Two games with the same seed must produce identical states."""
    seed = 42
    state1, rng1 = create_game(seed)
    state2, rng2 = create_game(seed)
    assert state1 == state2, "Initial states differ with same seed"

    # Simulate several turns with identical actions
    actions = [Action.DRAW, Action.PASS, Action.DRAW, Action.PASS]
    for action in actions:
        state1, rng1 = apply_action(state1, action, rng1)
        state2, rng2 = apply_action(state2, action, rng2)
        assert state1 == state2, f"States diverged after action {action}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `numpy.random.seed()` (global) | `numpy.random.default_rng(seed)` (instance) | NumPy 1.17 (2019) | Instance-based RNG prevents cross-module contamination. `spawn()` added in 1.25 for parallel streams. |
| `@dataclass(frozen=True)` only | `@dataclass(frozen=True, slots=True)` | Python 3.10 (2021) | `slots=True` reduces memory footprint and prevents dynamic attribute addition. Combined with frozen for maximum safety. |
| `copy.deepcopy()` for new states | `dataclasses.replace()` with tuple fields | Always available, best practice solidified ~2023 | replace() with tuples achieves structural sharing -- unchanged fields share memory references. 5-10x faster than deepcopy. |
| `random.Random()` stdlib | `numpy.random.Generator` (PCG64) | NumPy 1.17 (2019) | PCG64 is statistically superior to Mersenne Twister. Better period, faster, supports jumping/spawning. |
| Mutable game state with undo stack | Immutable state with action-produces-new-state | Standard in game AI since ~2015 | Enables replay, parallel simulation, MCTS, safe RL training. No undo stack needed. |

**Deprecated/outdated:**
- `numpy.random.seed()`: Sets global state. Never use for deterministic game engines.
- `random.seed()` / `random.Random()`: Mersenne Twister is inferior to PCG64 and doesn't integrate with numpy ecosystem.
- `@dataclass` without `frozen=True`: Mutable game state is an anti-pattern for RL training (see PITFALLS.md Pitfall 2).

## Open Questions

1. **Mana Regeneration Formula Precision**
   - What we know: D-05 (start 1), D-06 (+1/turn regen), D-07 (cap 10), D-08 (banking)
   - What's unclear: Does "regen +1 per turn" mean the mana pool capacity increases by 1 (like Hearthstone crystals) or simply +1 added to current mana?
   - Recommendation: Use Interpretation B (simple +1 to current, capped at 10). This is most consistent with "banking" -- you keep unspent mana and gain 1 more. If needed, make the regen amount configurable for RL to test variants.

2. **First-Turn Advantage Balancing (Claude's Discretion)**
   - What we know: The user flagged this as Claude's discretion. Going first is typically advantageous in card games.
   - Recommendation: Implement a configurable `first_turn_rules` field on GameState that can be set to different variants (e.g., `NORMAL`, `SKIP_FIRST_ACTION`, `DRAW_MINUS_ONE`). Default to `NORMAL` for Phase 1. RL will test variants later.

3. **Board Representation: numpy array vs tuple-of-tuples**
   - What we know: numpy array is faster for numeric operations; tuple is immutable and hashable.
   - Recommendation: Use a flat `tuple[Optional[int], ...]` of length 25 for the board in GameState (immutable, hashable). Provide `Board` helper methods that work with (row, col) coordinates using `index = row * 5 + col`. When converting to RL observations later (Phase 5), the tuple converts to numpy trivially.

4. **RNG State Persistence**
   - What we know: numpy Generator's state can be extracted via `rng.bit_generator.state` (a dict). But storing the full state dict in GameState is verbose.
   - Recommendation: Store `seed: int` and `rng_call_count: int` in GameState. For replay, recreate `default_rng(seed)` and call it `rng_call_count` times to reach the same state. For efficiency, also support direct state serialization for save/load.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | Runtime | Yes | 3.12.10 | -- |
| pip | Package installation | Yes (via Python) | -- | -- |
| numpy | Board arrays, RNG | Not yet installed | Install >=2.2 | -- |
| pytest | Testing | Not yet installed | Install >=8.0 | -- |
| git | Version control | Not initialized | -- | Initialize in scaffolding |
| Virtual environment | Dependency isolation | Not yet created | -- | Create with `python -m venv .venv` |

**Missing dependencies with no fallback:**
- None -- all dependencies are installable via pip.

**Missing dependencies with fallback:**
- None -- this phase uses only Python stdlib + numpy.

**Note:** No virtual environment or project structure exists yet. Plan must include project scaffolding as Wave 0.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >=8.0 |
| Config file | None -- Wave 0 must create pyproject.toml with `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v --cov=src/grid_tactics --cov-report=term-missing` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENG-01 | 5x5 grid with row ownership and deployment zones | unit | `python -m pytest tests/test_board.py -x` | No -- Wave 0 |
| ENG-01 | Adjacency queries (4-direction + diagonal) | unit | `python -m pytest tests/test_board.py::test_adjacency -x` | No -- Wave 0 |
| ENG-01 | Row ownership: rows 0-1 P1, row 2 neutral, rows 3-4 P2 | unit | `python -m pytest tests/test_board.py::test_row_ownership -x` | No -- Wave 0 |
| ENG-01 | One minion per space enforcement | unit | `python -m pytest tests/test_board.py::test_single_occupancy -x` | No -- Wave 0 |
| ENG-02 | Mana starts at 1 | unit | `python -m pytest tests/test_player.py::test_mana_start -x` | No -- Wave 0 |
| ENG-02 | Mana regen +1 per turn | unit | `python -m pytest tests/test_player.py::test_mana_regen -x` | No -- Wave 0 |
| ENG-02 | Mana cap at 10 | unit | `python -m pytest tests/test_player.py::test_mana_cap -x` | No -- Wave 0 |
| ENG-02 | Unspent mana carries over (banking) | unit | `python -m pytest tests/test_player.py::test_mana_banking -x` | No -- Wave 0 |
| ENG-11 | Same seed produces identical states | unit | `python -m pytest tests/test_rng.py::test_deterministic_replay -x` | No -- Wave 0 |
| ENG-11 | Different seeds produce different states | unit | `python -m pytest tests/test_rng.py::test_different_seeds -x` | No -- Wave 0 |
| -- | GameState is immutable (frozen) | unit | `python -m pytest tests/test_game_state.py::test_immutability -x` | No -- Wave 0 |
| -- | replace() produces new state without modifying original | unit | `python -m pytest tests/test_game_state.py::test_replace_no_mutation -x` | No -- Wave 0 |
| -- | State serialization round-trip | unit | `python -m pytest tests/test_game_state.py::test_serialization -x` | No -- Wave 0 |
| -- | All invariants validated (HP >= 0, mana in range, board positions valid) | unit | `python -m pytest tests/test_validation.py -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q` (fast, stop on first failure)
- **Per wave merge:** `python -m pytest tests/ -v --cov=src/grid_tactics --cov-report=term-missing`
- **Phase gate:** Full suite green + >90% coverage before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `pyproject.toml` -- project metadata, dependencies, pytest/mypy/ruff config
- [ ] `src/grid_tactics/__init__.py` -- package init
- [ ] `tests/conftest.py` -- shared fixtures (state factory, player factory)
- [ ] `.gitignore` -- Python-standard ignores (.venv, __pycache__, .mypy_cache, etc.)
- [ ] Virtual environment creation: `python -m venv .venv && pip install numpy pytest pytest-cov mypy ruff`
- [ ] Git initialization: `git init`

## Sources

### Primary (HIGH confidence)
- [Python 3.12 dataclasses documentation](https://docs.python.org/3/library/dataclasses.html) -- frozen=True, replace(), asdict(), slots=True behavior
- [NumPy v2.4 Random Generator documentation](https://numpy.org/doc/stable/reference/random/generator.html) -- default_rng(), Generator API, spawn()
- [NumPy Parallel Random Generation](https://numpy.org/doc/stable/reference/random/parallel.html) -- SeedSequence, child generators, independent streams
- [Best Practices for NumPy RNG](https://blog.scientific-python.org/numpy/numpy-rng/) -- Instance-based RNG, passing generators

### Secondary (MEDIUM confidence)
- [Real Python: Data Classes Guide](https://realpython.com/python-data-classes/) -- frozen dataclass patterns, replace() usage
- [orjson GitHub](https://github.com/ijl/orjson) -- 40-50x faster JSON serialization for dataclasses (verified claim on GitHub benchmarks)
- `.planning/research/ARCHITECTURE.md` -- Four-layer architecture, immutable GameState pattern
- `.planning/research/PITFALLS.md` -- Game engine bug risks, deterministic RNG importance
- `.planning/research/STACK.md` -- Python 3.12, numpy, pytest versions

### Tertiary (LOW confidence)
- Frozen dataclass 2.4x instantiation overhead claim -- cited in multiple sources but exact benchmark conditions unknown. Profile in actual codebase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Python stdlib dataclasses + numpy are well-documented and verified on this machine
- Architecture: HIGH -- Immutable frozen dataclass pattern is the community standard for game state in RL-driven game engines, confirmed by ARCHITECTURE.md research
- Pitfalls: HIGH -- Mutable collections in frozen dataclasses and global RNG are well-documented failure modes
- Mana system: MEDIUM -- The exact regeneration formula has a design ambiguity (see Open Questions). Interpretation B is recommended but should be validated with the user if unclear.
- Serialization: MEDIUM -- `dataclasses.asdict()` + `json.dumps()` is adequate for Phase 1. Performance optimization with orjson deferred to Phase 5+.

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable domain, 30-day validity)
