# Game Engine (Python)

Immutable dataclass-based engine. Authoritative for tests and rules verification. Located in `src/grid_tactics/`.

## Key Modules
| File | Role |
|------|------|
| `enums.py` | IntEnums for tensor compatibility |
| `board.py` | 5x5 grid geometry + adjacency |
| `player.py` | Hand, deck, [[../Mechanics/Mana System|mana]] |
| `game_state.py` | Top-level immutable state |
| `cards.py` / `card_loader.py` / `card_library.py` | Card defs |
| `actions.py` | Action dataclass |
| `action_resolver.py` | Apply actions |
| `effect_resolver.py` | Card effects |
| `react_stack.py` | LIFO [[../Mechanics/React Window]] |
| `legal_actions.py` | Mask generation |
| `validation.py` | Action legality |
| `game_loop.py` | Smoke loop |
| `rng.py` | Deterministic seeding |

## Style
- `frozen=True` dataclasses, `replace()` semantics.
- IntEnum everywhere for tensor parity.

## Related
- [[Tensor Engine]] (parallel mutating impl)
