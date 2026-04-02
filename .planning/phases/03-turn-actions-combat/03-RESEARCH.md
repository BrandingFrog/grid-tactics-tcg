# Phase 3: Turn Actions & Combat - Research

**Researched:** 2026-04-02
**Domain:** Game engine action system -- turn actions, combat resolution, react window, legal action enumeration
**Confidence:** HIGH

## Summary

Phase 3 builds the action layer of the game engine: the system that receives a GameState + Action pair and produces a new GameState. This is the largest and most complex phase of the game engine, encompassing card play (deploy minion, cast magic, play react), movement, combat (melee + ranged with simultaneous damage), the draw-as-action mechanic, the react window with full-stack chaining, and the legal_actions() enumeration function that Phase 5 will depend on for action masking.

The existing codebase provides strong foundations: immutable frozen GameState, Board with adjacency/distance helpers, Player with mana/hand/HP operations, CardDefinition/EffectDefinition as declarative data, and CardLibrary for lookups. The critical new concepts are: (1) MinionInstance -- a runtime minion on the board tracking current HP separate from CardDefinition base HP, (2) ActionType enum and structured action tuples, (3) an ActionResolver that validates and applies actions returning new GameState, (4) a ReactStack for the chaining react window, and (5) an EffectResolver that interprets EffectDefinition data declaratively.

**Primary recommendation:** Build in four waves: (1) MinionInstance + board integration, (2) action types + basic actions (move, draw, pass), (3) card play + effect resolution + combat, (4) react window stack + legal_actions() enumeration. Each wave is independently testable.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Damage is simultaneous -- both attacker and defender deal damage at the same time; both can die
- **D-02:** Dead minions (health <= 0) are removed at end of action, not immediately -- on_death effects all trigger together after damage resolves
- **D-03:** Melee units attack orthogonally adjacent targets; ranged units attack up to 2 tiles orthogonally or 1 tile diagonally (carried forward from PROJECT.md)
- **D-04:** One react card per player per "level" of the stack
- **D-05:** Full stack chaining: Player A acts -> Player B plays 1 react -> Player A can counter-react -> Player B can counter that -> etc., until someone passes
- **D-06:** Stack resolves last-in-first-out (most recent react resolves first, then the one before it, etc.)
- **D-07:** Passing at any level means that player's chain ends -- remaining stack resolves
- **D-08:** Melee minions can deploy to any empty space in the player's friendly rows (rows 0-1 for P1, rows 3-4 for P2)
- **D-09:** Ranged minions must deploy to the back row only (row 0 for P1, row 4 for P2) -- forces ranged behind front line
- **D-10:** Single-target Magic/effects require player to choose a target; area effects (all_enemies, adjacent) auto-resolve
- **D-11:** Playing a card costs mana equal to its mana_cost; insufficient mana = illegal action
- **D-12:** One action per turn: play card, move minion, attack with minion, draw card, or pass
- **D-13:** After action, react window opens (see D-04 through D-07)
- **D-14:** After react window closes, turn passes to the other player
- **D-15:** Drawing a card costs an action (configurable flag for auto-draw variant)
- **D-16:** Pass is always a valid action -- critical for mana banking strategy
- **D-17:** Actions are structured tuples (type, card_id/minion_id, position, target) internally -- not just flat ints
- **D-18:** Structured actions can be mapped to flat integer IDs for RL (Phase 5), but the internal representation stays structured for clarity and future Roblox/Lua port
- **D-19:** legal_actions() returns the complete set of valid structured actions from any game state with no illegal actions included

### Claude's Discretion
- Effect resolution order when multiple effects trigger simultaneously (e.g., two on_death effects)
- Exact action tuple format and enum values for action types
- How card instances on the field track current health vs card definition health
- Whether attacking costs the minion its movement for that turn (or if attack IS the action)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENG-03 | Each turn consists of a single action (play card, move minion, attack, draw) followed by an opponent react window | ActionResolver + ReactStack architecture, TurnPhase enum extension, turn flow state machine |
| ENG-06 | Minions move in all 4 directions; melee attacks adjacent orthogonal; ranged attacks up to 2 ortho or 1 diag | Board geometry helpers (already exist), MinionInstance tracking position, attack range validation |
| ENG-08 | Drawing a card costs an action (configurable flag for auto-draw variant) | ActionType.DRAW action, AUTO_DRAW_ENABLED flag in types.py |
| ENG-10 | Legal action enumeration returns all valid actions from any game state | legal_actions() function computing play/move/attack/draw/pass with full validation |
</phase_requirements>

## Standard Stack

### Core (all already in project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python dataclasses (stdlib) | -- | MinionInstance, Action frozen dataclasses | Matches Phase 1-2 pattern: frozen=True, slots=True |
| Python enum (stdlib) | -- | ActionType IntEnum | Matches existing IntEnum pattern (PlayerSide, TurnPhase, CardType) |
| numpy | >=2.2 | Already installed; no new dependency | Board cells already use flat tuple for numpy conversion |

### Supporting
No new dependencies needed. Phase 3 is pure game engine -- no external libraries beyond what Phase 1-2 installed.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Frozen dataclass Action tuples | NamedTuple | NamedTuples are lighter but lack __post_init__ validation; frozen dataclass is consistent with existing codebase pattern |
| Dict-based minion tracking | Full ORM/entity system | Entity system is overkill for 5x5 grid with max ~20 minions; dict mapping minion_id -> MinionInstance is sufficient |

## Architecture Patterns

### Recommended Project Structure
```
src/grid_tactics/
    enums.py            # EXTEND: add ActionType enum
    types.py            # EXTEND: add action constants, AUTO_DRAW_ENABLED
    minion.py           # NEW: MinionInstance frozen dataclass
    actions.py          # NEW: Action frozen dataclass and action constructors
    action_resolver.py  # NEW: validate + apply actions, return new GameState
    effect_resolver.py  # NEW: interpret EffectDefinition declaratively
    react_stack.py      # NEW: ReactStack for chaining react window
    game_state.py       # EXTEND: add minions field, react_stack field
    board.py            # EXISTING: no changes needed (helpers sufficient)
    player.py           # EXISTING: minor extend for react mana check
    cards.py            # EXISTING: no changes needed
    card_library.py     # EXISTING: no changes needed
    validation.py       # EXTEND: validate minion positions, action legality
```

### Pattern 1: MinionInstance -- Runtime Card on Board
**What:** A frozen dataclass representing a deployed minion on the field. Tracks current_health (which can differ from CardDefinition.health after taking damage), position, owner, and the card's numeric_id for looking up its definition.

**When to use:** Every time a minion is on the board. Board.cells stores minion_id integers; a separate mapping in GameState maps minion_id -> MinionInstance.

**Why needed:** CardDefinition is a static template (base health=3). When a minion takes 1 damage, it has current_health=2. This runtime state must live somewhere. Storing it on the Board would break the flat-tuple design optimized for numpy. A separate mapping is cleaner.

**Example:**
```python
@dataclass(frozen=True, slots=True)
class MinionInstance:
    """Runtime minion on the board. Tracks current health, position, owner."""
    instance_id: int        # unique per game, matches Board.cells value
    card_numeric_id: int    # index into CardLibrary for definition lookup
    owner: PlayerSide       # who controls this minion
    position: tuple[int, int]  # (row, col) on board
    current_health: int     # starts at CardDefinition.health, decreases from damage
    has_attacked: bool = False  # not needed if attack IS the action (1 action/turn)

    @property
    def is_alive(self) -> bool:
        return self.current_health > 0
```

**Integration with GameState:**
```python
@dataclass(frozen=True, slots=True)
class GameState:
    board: Board
    players: tuple[Player, Player]
    active_player_idx: int
    phase: TurnPhase
    turn_number: int
    seed: int
    # NEW fields:
    minions: tuple[MinionInstance, ...]  # all minions on board
    next_minion_id: int                   # counter for unique IDs
    react_stack: tuple[ReactEntry, ...]   # react chain state (empty = no react)
    pending_action: Optional[Action]      # action waiting for react resolution
```

**Key insight:** `minions` is a tuple of all MinionInstances. To find a minion by position, filter by position. To find by ID, filter by instance_id. For a 5x5 grid with typically 3-8 minions, linear scan is fast enough. If needed, a frozen dict could be used but adds complexity.

### Pattern 2: Structured Action Tuples
**What:** Actions are frozen dataclasses with an ActionType discriminator and optional fields depending on type.

**Recommended ActionType enum (Claude's discretion):**
```python
class ActionType(IntEnum):
    PLAY_CARD = 0       # Play a card from hand (deploy minion or cast magic)
    MOVE = 1            # Move a minion on the board
    ATTACK = 2          # Attack with a minion
    DRAW = 3            # Draw a card from deck
    PASS = 4            # Pass (always legal)
    PLAY_REACT = 5      # Play a react card during react window
```

**Action dataclass:**
```python
@dataclass(frozen=True, slots=True)
class Action:
    action_type: ActionType
    card_index: Optional[int] = None      # index into player's hand tuple
    position: Optional[tuple[int, int]] = None  # target position for deploy/move
    minion_id: Optional[int] = None       # which minion to move/attack with
    target_id: Optional[int] = None       # target minion ID for attack
    target_pos: Optional[tuple[int, int]] = None  # target position for effects
```

**Design note:** Using `card_index` (index into hand tuple) rather than card_numeric_id avoids ambiguity when a player has multiple copies of the same card. The hand is a tuple of numeric IDs; `card_index=2` means "the card at position 2 in the hand tuple."

**Portability for Roblox/Lua (D-17, D-18):** This structured format maps cleanly to Lua tables: `{type="PLAY_CARD", card_index=2, position={0,3}}`. The RL integer mapping (Phase 5) is a separate encoder layer.

### Pattern 3: ActionResolver -- Validate + Apply + Advance
**What:** A stateless module/class that takes (GameState, Action, CardLibrary) and returns a new GameState. Single entry point.

**Flow for a normal action:**
```
1. Validate action is legal (in legal_actions set)
2. Apply action effects:
   - PLAY_CARD: deduct mana, remove card from hand, place minion / resolve magic
   - MOVE: update minion position
   - ATTACK: simultaneous damage exchange, mark dead
   - DRAW: draw card from deck
   - PASS: no-op
3. Resolve triggered effects (on_play, on_attack, etc.)
4. Remove dead minions (health <= 0) per D-02
5. Trigger on_death effects for removed minions
6. Remove those dead minions from board
7. Open react window (set phase to REACT, set pending_action)
   OR if react window just closed, advance turn
```

**Flow during react window:**
```
1. Active player during REACT is the non-acting player
2. Legal actions: PLAY_REACT cards they can afford + PASS
3. If PLAY_REACT: push onto react_stack, switch react to other player
4. If PASS: resolve react_stack LIFO, then advance turn
```

### Pattern 4: React Stack with LIFO Resolution
**What:** The react window uses a stack (tuple) of pending react entries. Each entry records who played it and what effect it has.

**Example:**
```python
@dataclass(frozen=True, slots=True)
class ReactEntry:
    player_idx: int             # who played this react
    card_index: int             # which card from hand
    card_numeric_id: int        # card definition ID
    target_pos: Optional[tuple[int, int]] = None  # if single-target

# In GameState:
react_stack: tuple[ReactEntry, ...] = ()
react_player_idx: Optional[int] = None  # whose turn to react (None = no react window)
```

**Chaining rules (D-04 through D-07):**
- After Player A's action, Player B gets react opportunity (level 0)
- Player B plays a react card -> pushed to stack -> Player A gets counter-react (level 1)  
- Player A plays a react card -> pushed to stack -> Player B gets counter-counter (level 2)
- At any point, if a player passes, the stack resolves LIFO
- One react card per player per level (D-04)

**Resolution order:** Stack pops top entry, resolves its effect, then pops next, etc. This means the last react played resolves first (counter before the thing it counters).

### Pattern 5: Effect Resolution Engine
**What:** A module that takes an EffectDefinition + GameState + context (caster, targets) and produces a new GameState with the effect applied.

**Resolution by TargetType:**
- `SINGLE_TARGET`: requires target_pos in the action -- apply effect to minion at that position
- `ALL_ENEMIES`: find all enemy minions on board, apply effect to each
- `ADJACENT`: find all minions adjacent to caster/target position, apply effect
- `SELF_OWNER`: apply to the caster minion or owning player

**Resolution by EffectType:**
- `DAMAGE`: reduce target's current_health by amount
- `HEAL`: increase target's current_health by amount (capped at base health from CardDefinition)
- `BUFF_ATTACK`: not directly trackable on MinionInstance yet -- need `attack_bonus` field or resolve immediately for temporary buffs
- `BUFF_HEALTH`: increase current_health (and maybe max health) by amount

**Discretion decision -- simultaneous effect ordering:** When multiple on_death effects trigger (e.g., two minions die in combat), resolve in board position order: left-to-right, top-to-bottom. This is deterministic and matches grid reading order. Alternatively, resolve by instance_id (creation order). Recommend instance_id (creation order) since it is the most intuitive and deterministic.

### Pattern 6: legal_actions() -- Complete Enumeration
**What:** Given a GameState and CardLibrary, enumerate ALL valid structured Actions.

**During ACTION phase (one of these):**
```python
def legal_actions(state: GameState, library: CardLibrary) -> tuple[Action, ...]:
    actions = []
    player = state.active_player
    
    # 1. PLAY_CARD: for each card in hand, if enough mana, find valid positions
    for idx, card_num_id in enumerate(player.hand):
        card_def = library.get_by_id(card_num_id)
        if player.current_mana < card_def.mana_cost:
            continue
        if card_def.card_type == CardType.MINION:
            for pos in _valid_deploy_positions(state, card_def, player.side):
                # For minions with on_play single_target effects, also enumerate targets
                if _has_single_target_on_play(card_def):
                    for target in _valid_effect_targets(state, card_def, player.side):
                        actions.append(Action(PLAY_CARD, card_index=idx, position=pos, target_pos=target))
                else:
                    actions.append(Action(PLAY_CARD, card_index=idx, position=pos))
        elif card_def.card_type == CardType.MAGIC:
            if _has_single_target(card_def):
                for target in _valid_effect_targets(state, card_def, player.side):
                    actions.append(Action(PLAY_CARD, card_index=idx, target_pos=target))
            else:
                actions.append(Action(PLAY_CARD, card_index=idx))
    
    # 2. MOVE: for each owned minion, 4 directions if target cell empty and in bounds
    for minion in state.minions:
        if minion.owner != player.side:
            continue
        for adj_pos in Board.get_orthogonal_adjacent(minion.position):
            if state.board.get(adj_pos[0], adj_pos[1]) is None:
                actions.append(Action(MOVE, minion_id=minion.instance_id, position=adj_pos))
    
    # 3. ATTACK: for each owned minion, find valid attack targets
    for minion in state.minions:
        if minion.owner != player.side:
            continue
        card_def = library.get_by_id(minion.card_numeric_id)
        for target in _valid_attack_targets(state, minion, card_def):
            actions.append(Action(ATTACK, minion_id=minion.instance_id, target_id=target.instance_id))
    
    # 4. DRAW: if deck is not empty
    if player.deck:
        actions.append(Action(DRAW))
    
    # 5. PASS: always legal (D-16)
    actions.append(Action(PASS))
    
    return tuple(actions)
```

**During REACT phase:**
```python
# Only react-eligible cards + pass
for idx, card_num_id in enumerate(player.hand):
    card_def = library.get_by_id(card_num_id)
    if card_def.card_type == CardType.REACT and player.current_mana >= card_def.mana_cost:
        # enumerate targets for single-target reacts
        ...
    # Multi-purpose minion cards can also be played as react from hand
    if card_def.is_multi_purpose and player.current_mana >= card_def.react_mana_cost:
        ...
actions.append(Action(PASS))  # always can pass on react
```

### Anti-Patterns to Avoid
- **Mutating GameState fields directly:** Every operation must return a new GameState via `dataclasses.replace()`. This is enforced by `frozen=True`.
- **Hardcoding card effects in if/elif chains:** Use the declarative EffectDefinition data. The effect resolver reads `effect_type`, `target`, and `amount` and applies them generically.
- **Separate validation path for legal_actions vs resolve:** The ActionResolver must use legal_actions() as the single source of truth. `resolve(state, action)` should verify `action in legal_actions(state)` (or an equivalent check).
- **Storing minion state inside Board.cells:** Board.cells stores only minion instance IDs (integers). All minion state (health, owner, position) lives in the MinionInstance tuple in GameState.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Attack range checking | Custom distance math per card | Board.manhattan_distance() for orthogonal, Board.chebyshev_distance() for diagonal | Already implemented and tested in Phase 1 |
| Adjacent position finding | Manual offset calculation | Board.get_orthogonal_adjacent(), Board.get_all_adjacent() | Already implemented; handles edge cases at board boundaries |
| Mana deduction | Manual mana tracking | Player.spend_mana(cost) | Already validates insufficient mana and returns new Player |
| Card from hand removal | Manual list manipulation | Player.discard_from_hand(card_id) | Already handles card lookup and graveyard placement |
| Draw from deck | Manual deck/hand manipulation | Player.draw_card() | Already handles empty deck error case |
| Row ownership checking | Hardcoded row numbers | Board.get_row_owner(row), Board.get_positions_for_side(side) | Already implemented with PLAYER_1_ROWS/PLAYER_2_ROWS constants |

## Common Pitfalls

### Pitfall 1: Minion ID Collision
**What goes wrong:** Two minions end up with the same instance_id, causing board state corruption.
**Why it happens:** The ID counter isn't incremented correctly, or is reset between turns.
**How to avoid:** Store `next_minion_id` in GameState (frozen field). Every time a minion is created, use the current value and increment: `new_state = replace(state, next_minion_id=state.next_minion_id + 1)`.
**Warning signs:** Duplicate minion IDs detected by validation.py, minion disappears when another is placed.

### Pitfall 2: Stale Minion References After Death
**What goes wrong:** An effect targets a minion that was just killed (health <= 0) but not yet removed from the board.
**Why it happens:** D-02 says dead minions are removed at end of action. Between damage application and removal, dead minions are still in the state.
**How to avoid:** The dead-removal step must happen as a single atomic pass: (1) find all minions with health <= 0, (2) collect their on_death effects, (3) remove them all from board and minions tuple, (4) resolve on_death effects on the post-removal state. On_death effects should not be able to target the dead minions.
**Warning signs:** Effects applied to minions with current_health <= 0.

### Pitfall 3: React Stack Infinite Loop
**What goes wrong:** The react window never closes because both players keep playing react cards.
**Why it happens:** D-04 limits to 1 react per player per level, but if there is no hard cap on levels, two players with many react cards could chain indefinitely.
**How to avoid:** In practice, react cards cost mana and are limited in hand, so the chain self-limits. But add a safety cap (e.g., max 10 react levels) and validate in legal_actions that the cap is not exceeded. Also ensure each player can only play 1 react per level (not 1 per player per stack).
**Warning signs:** Games hanging in react phase during random agent testing.

### Pitfall 4: Card Index vs Card Numeric ID Confusion
**What goes wrong:** An action references `card_index=3` (position in hand) but the resolver uses it as a `card_numeric_id` (library lookup key), or vice versa.
**Why it happens:** Player.hand is `tuple[int, ...]` where each int IS a card_numeric_id. The action needs to specify WHICH copy in hand (by index) because a player may have duplicate cards.
**How to avoid:** Action uses `card_index` exclusively. Resolver does `card_numeric_id = player.hand[action.card_index]` to get the library ID. Add validation that `0 <= card_index < len(hand)`.
**Warning signs:** Wrong card played, "card not in hand" errors, index out of range.

### Pitfall 5: Deployment Zone Enforcement for Ranged vs Melee
**What goes wrong:** A ranged minion (attack_range >= 1) is deployed to the front row, violating D-09.
**Why it happens:** The deploy validation doesn't check the card's range to determine which rows are valid.
**How to avoid:** In legal_actions, when generating PLAY_CARD actions for minions: if `attack_range == 0` (melee), valid positions are all empty cells in friendly rows; if `attack_range >= 1` (ranged), valid positions are only the back row. Encode this as a helper function `_valid_deploy_positions(state, card_def, side)`.
**Warning signs:** Ranged minions placed on front row or middle row.

### Pitfall 6: Attack Range Semantics Mismatch
**What goes wrong:** The attack range validation doesn't match the game rules (D-03), causing melee units to attack at range or ranged units to be too limited.
**Why it happens:** The card data has `attack_range` as an integer (0, 1, 2) but the rules describe behavior categorically ("melee attacks adjacent orthogonal, ranged attacks up to 2 ortho or 1 diag").
**How to avoid:** Define attack range semantics precisely:
- `attack_range == 0`: melee. Can attack targets at manhattan_distance == 1 AND only orthogonal (same row or same col).
- `attack_range >= 1`: ranged. Can attack targets at manhattan_distance <= attack_range AND orthogonal, OR chebyshev_distance <= 1 AND diagonal.

Wait -- D-03 says ranged is specifically "up to 2 tiles orthogonally or 1 tile diagonally." This means the range value in the card IS the orthogonal reach, and diagonal is always 1 for any ranged unit. So:
- `attack_range == 0`: only orthogonal adjacent (manhattan 1, same row or col)
- `attack_range == 1`: orthogonal up to 1 tile OR diagonal adjacent (chebyshev 1)
- `attack_range == 2`: orthogonal up to 2 tiles OR diagonal adjacent (chebyshev 1)

This makes wind_archer (range=2) able to attack 2 tiles away orthogonally or 1 diagonally, while flame_wyrm (range=1) can attack 1 orthogonal or 1 diagonal (essentially all adjacent).
**Warning signs:** Test with specific board positions to verify range boundaries.

## Code Examples

### Example 1: MinionInstance Creation on Deploy
```python
# Source: derived from existing Board.place() and Player.discard_from_hand() patterns

def _apply_deploy_minion(
    state: GameState, card_def: CardDefinition, card_index: int, position: tuple[int, int]
) -> GameState:
    player = state.active_player
    card_numeric_id = player.hand[card_index]
    
    # Spend mana and remove card from hand
    new_player = player.spend_mana(card_def.mana_cost)
    new_player = new_player.discard_from_hand(card_numeric_id)
    
    # Create minion instance
    minion = MinionInstance(
        instance_id=state.next_minion_id,
        card_numeric_id=card_numeric_id,
        owner=player.side,
        position=position,
        current_health=card_def.health,
    )
    
    # Place on board
    new_board = state.board.place(position[0], position[1], minion.instance_id)
    
    # Update state
    new_players = _replace_player(state.players, state.active_player_idx, new_player)
    return replace(
        state,
        board=new_board,
        players=new_players,
        minions=state.minions + (minion,),
        next_minion_id=state.next_minion_id + 1,
    )
```

### Example 2: Simultaneous Combat Resolution
```python
# Source: derived from D-01 (simultaneous damage) and D-02 (dead removed at end)

def _apply_attack(
    state: GameState, attacker_id: int, defender_id: int, library: CardLibrary
) -> GameState:
    attacker = _find_minion(state, attacker_id)
    defender = _find_minion(state, defender_id)
    
    attacker_card = library.get_by_id(attacker.card_numeric_id)
    defender_card = library.get_by_id(defender.card_numeric_id)
    
    # Simultaneous damage (D-01)
    new_attacker = replace(attacker, current_health=attacker.current_health - defender_card.attack)
    new_defender = replace(defender, current_health=defender.current_health - attacker_card.attack)
    
    # Update minions tuple
    new_minions = tuple(
        new_attacker if m.instance_id == attacker_id
        else new_defender if m.instance_id == defender_id
        else m
        for m in state.minions
    )
    
    return replace(state, minions=new_minions)
    # Dead minion cleanup happens in the post-action cleanup step
```

### Example 3: Dead Minion Cleanup
```python
# Source: D-02 -- dead removed at end of action, on_death triggers together

def _cleanup_dead_minions(state: GameState, library: CardLibrary) -> GameState:
    dead = tuple(m for m in state.minions if not m.is_alive)
    if not dead:
        return state
    
    alive = tuple(m for m in state.minions if m.is_alive)
    
    # Remove dead from board
    new_board = state.board
    for m in dead:
        new_board = new_board.remove(m.position[0], m.position[1])
    
    state = replace(state, board=new_board, minions=alive)
    
    # Resolve on_death effects in instance_id order (deterministic)
    for m in sorted(dead, key=lambda x: x.instance_id):
        card_def = library.get_by_id(m.card_numeric_id)
        for effect in card_def.effects:
            if effect.trigger == TriggerType.ON_DEATH:
                state = resolve_effect(state, effect, caster_pos=m.position, caster_owner=m.owner, library=library)
    
    return state
```

### Example 4: Attack Range Validation
```python
# Source: D-03 + Board helper methods

def _can_attack(attacker: MinionInstance, target: MinionInstance, attacker_card: CardDefinition) -> bool:
    if attacker_card.attack_range == 0:
        # Melee: orthogonal adjacent only
        return (
            Board.manhattan_distance(attacker.position, target.position) == 1
            and (attacker.position[0] == target.position[0] or attacker.position[1] == target.position[1])
        )
    else:
        # Ranged: orthogonal up to attack_range OR diagonal adjacent (chebyshev 1)
        a, t = attacker.position, target.position
        is_orthogonal = (a[0] == t[0] or a[1] == t[1])
        manhattan = Board.manhattan_distance(a, t)
        chebyshev = Board.chebyshev_distance(a, t)
        
        if is_orthogonal and manhattan <= attacker_card.attack_range:
            return True
        if not is_orthogonal and chebyshev == 1:  # diagonal adjacent
            return True
        return False
```

### Example 5: React Window State Machine
```python
# React window flow (simplified pseudocode)

def _advance_after_action(state: GameState) -> GameState:
    """After an ACTION phase action, open the react window."""
    # Switch to REACT phase, opponent gets to react
    return replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1 - state.active_player_idx,
        react_level=0,
    )

def _handle_react(state: GameState, action: Action, library: CardLibrary) -> GameState:
    """Handle a react action (PLAY_REACT or PASS)."""
    if action.action_type == ActionType.PASS:
        # This player passes -- resolve the stack
        return _resolve_react_stack(state, library)
    
    # Play react card -- push to stack, give other player counter-react
    entry = ReactEntry(
        player_idx=state.react_player_idx,
        card_index=action.card_index,
        card_numeric_id=state.players[state.react_player_idx].hand[action.card_index],
        target_pos=action.target_pos,
    )
    new_stack = state.react_stack + (entry,)
    
    # Deduct mana and remove card from reacting player's hand
    # ... (mana/hand operations)
    
    # Switch react to other player (counter-react opportunity)
    return replace(
        state,
        react_stack=new_stack,
        react_player_idx=1 - state.react_player_idx,
        react_level=state.react_level + 1,
    )

def _resolve_react_stack(state: GameState, library: CardLibrary) -> GameState:
    """Resolve react stack LIFO, then advance turn."""
    # Pop from end of tuple (LIFO)
    for entry in reversed(state.react_stack):
        card_def = library.get_by_id(entry.card_numeric_id)
        for effect in card_def.effects:
            state = resolve_effect(state, effect, ...)
    
    # Clear react state, advance turn
    return replace(
        state,
        react_stack=(),
        react_player_idx=None,
        react_level=None,
        phase=TurnPhase.ACTION,
        active_player_idx=1 - state.active_player_idx,
        turn_number=state.turn_number + 1,
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Mutable game state with in-place updates | Immutable frozen dataclass with replace() | Established in Phase 1 | All Phase 3 code must follow this pattern |
| Card effects as Python functions | Declarative EffectDefinition data | Established in Phase 2 | Effect resolver reads data, doesn't call card-specific code |
| OpenAI Gym | Gymnasium (Farama Foundation) | 2022-2023 | Phase 5 will use Gymnasium; Phase 3 game engine has no ML dependency |

**Deprecated/outdated:**
- Nothing in this phase uses external libraries that could be outdated. Pure Python game engine.

## Open Questions

1. **Attack range for `attack_range=1` units (flame_wyrm, light_cleric)**
   - What we know: D-03 describes melee (adjacent orthogonal) and ranged (2 ortho / 1 diag). Cards have range 0, 1, and 2.
   - What's unclear: Does `attack_range=1` mean "1 orthogonal OR 1 diagonal" (effectively all 8 adjacent)? Or does it follow the melee pattern (orthogonal only, range 1)?
   - Recommendation: Treat `attack_range=0` as melee (orthogonal adjacent only), `attack_range >= 1` as ranged (orthogonal up to N tiles + diagonal at chebyshev 1). This makes range=1 functionally "all 8 adjacent cells" which is a meaningful step up from melee's 4 cells.

2. **Buff_attack tracking on MinionInstance**
   - What we know: EffectType includes BUFF_ATTACK. MinionInstance tracks current_health but not current_attack.
   - What's unclear: Are attack buffs permanent (lasting until minion dies) or temporary (one turn)?
   - Recommendation: Add `attack_bonus: int = 0` field to MinionInstance. The effective attack is `card_def.attack + minion.attack_bonus`. Start with permanent buffs for simplicity. If temporary buffs are needed later, add a `buffs: tuple[Buff, ...]` system in Phase 8.

3. **Whether `has_attacked` is needed**
   - What we know: D-12 says one action per turn. Attack IS the action, so you can only attack once per turn.
   - What's unclear: Can a newly deployed minion attack on the same turn it was deployed?
   - Recommendation: No -- deploying is the action for that turn, so the minion cannot also attack. Since each turn is exactly one action, no `has_attacked` flag is needed. The turn structure itself prevents double action.

4. **Auto-draw variant flag**
   - What we know: D-15 says "configurable flag for auto-draw variant." ENG-08 says the same.
   - What's unclear: Does auto-draw mean every turn you automatically draw without spending an action?
   - Recommendation: Add `AUTO_DRAW_ENABLED: bool = False` to types.py. When True, at the start of each turn the active player draws a card automatically (before choosing their action). This removes DRAW from the action space when enabled.

5. **What happens when deck is empty and player tries to draw?**
   - What we know: Player.draw_card() raises ValueError on empty deck.
   - What's unclear: Should drawing from empty deck be illegal (not in legal_actions) or should it cause a penalty/loss?
   - Recommendation: If deck is empty, DRAW is simply not in legal_actions(). No crash, no penalty. Player must pass or take other actions.

6. **Multi-purpose card react play during react window**
   - What we know: D-06 says multi-purpose minion cards can be played as react from hand. They have a separate `react_mana_cost`.
   - What's unclear: In the react window, can a player play a multi-purpose card's react effect?
   - Recommendation: Yes. During REACT phase, legal_actions includes multi-purpose cards (using react_mana_cost) alongside pure React cards. The card is discarded (not deployed), and the react_effect resolves.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.0+ |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/ -x -q` |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENG-03 | One action per turn + react window flow | unit + integration | `.venv/Scripts/python.exe -m pytest tests/test_action_resolver.py tests/test_react_stack.py -x` | Wave 0 |
| ENG-06 | Movement 4 directions + melee adjacent + ranged 2 ortho / 1 diag | unit | `.venv/Scripts/python.exe -m pytest tests/test_movement.py tests/test_combat.py -x` | Wave 0 |
| ENG-08 | Draw costs action + auto-draw config flag | unit | `.venv/Scripts/python.exe -m pytest tests/test_action_resolver.py -k draw -x` | Wave 0 |
| ENG-10 | legal_actions returns complete valid set | unit + property | `.venv/Scripts/python.exe -m pytest tests/test_legal_actions.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python.exe -m pytest tests/ -x -q`
- **Per wave merge:** `.venv/Scripts/python.exe -m pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_minion.py` -- MinionInstance construction, health tracking, is_alive
- [ ] `tests/test_actions.py` -- Action dataclass construction, validation
- [ ] `tests/test_action_resolver.py` -- action validation, apply, turn advance
- [ ] `tests/test_movement.py` -- move in 4 directions, blocked cells, out of bounds
- [ ] `tests/test_combat.py` -- melee attack, ranged attack, simultaneous damage, dead removal
- [ ] `tests/test_effect_resolver.py` -- damage, heal, buff effects with all target types
- [ ] `tests/test_react_stack.py` -- react window open/close, stack chaining, LIFO resolution
- [ ] `tests/test_legal_actions.py` -- complete enumeration for various game states
- [ ] `tests/test_deploy.py` -- melee any friendly row, ranged back row only, mana cost
- [ ] `tests/conftest.py` -- extend with make_game_state, make_minion fixtures
- [ ] Framework install: already installed (pytest in venv)

## Design Decisions (Claude's Discretion Items)

### Simultaneous Effect Resolution Order
**Decision:** When multiple effects trigger simultaneously (e.g., two on_death effects from two minions dying in combat), resolve in `instance_id` order (ascending). This means the minion that was created first has its effects resolve first.

**Rationale:** Instance IDs are deterministic (monotonically increasing counter in GameState). This gives a clear, reproducible ordering that doesn't depend on board position (which could change). It matches the "first in, first out" intuition for same-priority effects.

### Action Tuple Format
**Decision:** Use a single frozen `Action` dataclass with optional fields, discriminated by `ActionType`. Not a union of separate classes.

**Rationale:** A single class is simpler to serialize (to_dict/from_dict), easier to compare (equality checks), and matches the "portable to Lua table" goal. Optional fields are None when not relevant (e.g., `card_index` is None for MOVE actions).

### Card Instance Health Tracking
**Decision:** MinionInstance stores `current_health: int` and `attack_bonus: int`. Effective attack is `card_def.attack + attack_bonus`. Effective max health comes from card_def.health (for heal capping).

**Rationale:** Separate MinionInstance from CardDefinition keeps the definition immutable/shared while allowing per-instance runtime state. Only health and attack need runtime modification in the starter card pool. Phase 8 can extend with a general buff system if needed.

### Attack IS the Action
**Decision:** Attacking costs the player's action for the turn. A minion that was just deployed cannot attack that same turn (deploying was the action). No `has_attacked` flag is needed on MinionInstance.

**Rationale:** D-12 says "one action per turn." Each of play/move/attack/draw/pass is the single action. This simplifies the state model (no per-minion action tracking) and matches the fast-paced design intent.

## Project Constraints (from CLAUDE.md)

- **Language:** Python for game engine and RL
- **Testing:** Each development step validated (pytest with high coverage via pytest-cov)
- **Type checking:** mypy strict mode enabled
- **Linting:** ruff with target-version py312
- **Stack:** dataclasses (frozen=True), IntEnum, numpy >=2.2
- **Architecture:** Immutable GameState, action-produces-new-state pattern
- **No ML dependencies in game engine:** Phase 3 is pure Python + numpy
- **GSD Workflow:** All changes through GSD commands

## Sources

### Primary (HIGH confidence)
- Existing codebase: `src/grid_tactics/` -- all Phase 1-2 modules (directly read and analyzed)
- `.planning/research/ARCHITECTURE.md` -- four-layer architecture, ActionResolver pattern, legal_actions pattern
- `.planning/research/PITFALLS.md` -- effect system spaghetti (Pitfall 4), react window modeling (Pitfall 7), draw-as-action (Pitfall 13)
- `03-CONTEXT.md` -- 19 locked decisions (D-01 through D-19)
- Card JSON files in `data/cards/` -- 18 starter cards with range 0, 1, 2

### Secondary (MEDIUM confidence)
- Architecture patterns derived from RLCard and PettingZoo AEC model (documented in ARCHITECTURE.md with source links)
- React stack LIFO resolution pattern from MTG priority system analogy (referenced in ARCHITECTURE.md)

### Tertiary (LOW confidence)
- Attack range interpretation for `attack_range=1` -- inferred from card data patterns, not explicitly defined in any documentation. Flagged as Open Question #1.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all existing patterns
- Architecture: HIGH -- extends proven frozen-dataclass pattern with clear new modules
- MinionInstance design: HIGH -- straightforward runtime state tracking
- Action system: HIGH -- structured tuples matching D-17/D-18 requirements
- React stack: MEDIUM -- complex chaining logic, needs careful testing
- Effect resolver: MEDIUM -- starter effects are simple but must be extensible
- Attack range semantics: MEDIUM -- interpretation of range=1 needs validation with tests
- Pitfalls: HIGH -- directly derived from PITFALLS.md research and codebase analysis

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable game engine domain, no external dependencies to age)
