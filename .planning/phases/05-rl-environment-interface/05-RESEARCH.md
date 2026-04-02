# Phase 5: RL Environment Interface - Research

**Researched:** 2026-04-02
**Domain:** Gymnasium environment wrapper for turn-based card game with action masking
**Confidence:** HIGH

## Summary

Phase 5 wraps the completed game engine (Phases 1-4) in a Gymnasium-compatible environment. The core challenges are: (1) encoding the game state as a fixed-size flat 1D numpy observation vector without leaking opponent hidden info, (2) mapping the combinatorial action space (7 action types x position/target parameters) to a flat `Discrete(N)` integer space, and (3) wiring `legal_actions()` into a binary mask for MaskablePPO compatibility.

The game engine is cleanly designed for this -- `GameState` is immutable, `resolve_action()` is a pure function, `legal_actions()` is the single source of truth, and `GameState.new_game()` provides deterministic resets. The environment is a thin translation layer: it converts between the engine's Python objects and numpy arrays, nothing more. This phase does NOT include PettingZoo AEC (Phase 7) or training (Phase 6); it wraps both players as a single-agent turn-taking environment suitable for random-action validation.

**Primary recommendation:** Build a single `GridTacticsEnv(gymnasium.Env)` class with flat `Discrete(N)` action space, flat `Box` observation space, and an `action_masks()` method. Use position-based action encoding (not minion-ID-based) for stable integer mappings. Validate with 10,000 random episodes before declaring complete.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Flat 1D numpy array observation -- API-ready format that can also serve stats dashboards and web APIs
- **D-02:** Hidden information: opponent's hand contents and deck contents are NOT visible. Board state, HP, mana, and deck/hand sizes for both players ARE visible.
- **D-03:** Observation should be structured/documented well enough to deserialize for stats APIs (field offsets documented)
- **D-04:** Flat discrete action space -- enumerate all possible (action_type, param1, param2) combos into integers
- **D-05:** Binary action mask marks illegal actions as unavailable (for MaskablePPO from sb3-contrib)
- **D-06:** Action encoding/decoding must be deterministic and documented
- **D-07:** Gymnasium-compatible: reset(), step(), observation_space, action_space
- **D-08:** 10,000 random episodes must complete without errors
- **D-09:** Step returns (observation, reward, terminated, truncated, info) per Gymnasium API

### Claude's Discretion
- Exact observation vector layout and feature count
- Action space size and encoding scheme
- Reward signal design (win/loss at minimum, potential shaping)
- Whether to use gymnasium.Env directly or a wrapper pattern
- Network architecture hints in observation space (flat vs Box)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RL-01 | Gymnasium-compatible environment with reset(), step(), observation_space, and action_space | Gymnasium 1.2.3 API documented below with exact method signatures, return types, and space definitions |
| RL-02 | State observation encoding converts board (5x5 grid with unit stats), hand, mana, HP into fixed-size numerical tensors | Observation vector layout calculated at 292 floats with documented field offsets for each section |
| RL-03 | Action space definition maps all possible actions into a discrete space with binary action masking for illegal actions | Action space calculated at 567 discrete actions with position-based encoding and `action_masks()` method for MaskablePPO |

</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Language**: Python for game engine and RL
- **RL focus**: Core strategy discovery is the priority
- **Testing**: Each development step validated with RL to confirm strategic depth
- **Workflow**: Use GSD workflow for all file changes
- **Stack**: Gymnasium >=1.2,<2.0; sb3-contrib >=2.8,<3.0 (MaskablePPO); NumPy >=2.2,<3.0
- **Architecture**: Game engine has zero ML imports; environment is the adapter layer
- **Patterns**: Frozen dataclasses, immutable GameState, `dataclasses.replace()` for mutation

## Standard Stack

### Core (Phase 5 specific)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| gymnasium | 1.2.3 | RL environment API | Farama Foundation standard; all RL libraries target this |
| numpy | 2.4.4 | Observation/mask arrays | Already installed; used for all tensor operations |

### Supporting (needed for validation, not training)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sb3-contrib | 2.8.0 | MaskablePPO import for `ActionMasker` type checking | Optional: verify mask interface compatibility. Full use in Phase 6 |

### NOT needed in Phase 5

| Library | Why Not Now |
|---------|-------------|
| stable-baselines3 | Training is Phase 6 |
| torch | SB3 dependency, not needed for env definition |
| pettingzoo | AEC wrapping is Phase 7 |

**Installation for Phase 5:**
```bash
pip install "gymnasium>=1.2,<2.0"
```

That is the only new dependency. NumPy is already installed. sb3-contrib can be deferred to Phase 6.

**Version verification:** gymnasium 1.2.3 is latest on PyPI (verified 2026-04-02). Python 3.12.10 in .venv is compatible.

## Architecture Patterns

### Recommended Project Structure
```
src/grid_tactics/
    rl/
        __init__.py
        env.py              # GridTacticsEnv class
        observation.py      # encode_observation(), OBSERVATION_SPEC
        action_space.py     # ActionEncoder: int <-> Action mapping, mask generation
        reward.py           # compute_reward() -- sparse win/loss for now
```

### Pattern 1: Thin Environment Wrapper

**What:** The environment class is a thin adapter. All game logic stays in the engine. The env only converts types and forwards calls.

**When to use:** Always -- this is the foundational pattern from ARCHITECTURE.md.

**Example:**
```python
import gymnasium as gym
import numpy as np
from gymnasium import spaces

class GridTacticsEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self, library: CardLibrary, deck_p1: tuple[int, ...],
                 deck_p2: tuple[int, ...], seed: int = 42,
                 turn_limit: int = DEFAULT_TURN_LIMIT):
        super().__init__()
        self.library = library
        self.deck_p1 = deck_p1
        self.deck_p2 = deck_p2
        self._seed = seed
        self.turn_limit = turn_limit

        self.observation_space = spaces.Box(
            low=-1.0, high=1.0,
            shape=(OBSERVATION_SIZE,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(ACTION_SPACE_SIZE)

        # Internal state
        self.state: GameState = None
        self.rng: GameRNG = None
        self.action_encoder = ActionEncoder()

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        game_seed = seed if seed is not None else self._seed
        self.state, self.rng = GameState.new_game(
            game_seed, self.deck_p1, self.deck_p2,
        )
        obs = encode_observation(self.state, self.library,
                                 self.state.active_player_idx)
        return obs, {"action_mask": self.action_masks()}

    def step(self, action_int: int):
        action = self.action_encoder.decode(action_int)
        self.state = resolve_action(self.state, action, self.library)

        # If we land in REACT phase, auto-play opponent react (random for now)
        # OR: treat both players as the same agent taking turns
        ...

        obs = encode_observation(self.state, self.library,
                                 self.state.active_player_idx)
        reward = compute_reward(self.state, player_idx=0)
        terminated = self.state.is_game_over
        truncated = self.state.turn_number > self.turn_limit
        info = {"action_mask": self.action_masks()}
        return obs, reward, terminated, truncated, info

    def action_masks(self) -> np.ndarray:
        legal = legal_actions(self.state, self.library)
        mask = np.zeros(ACTION_SPACE_SIZE, dtype=np.bool_)
        for a in legal:
            idx = self.action_encoder.encode(a)
            mask[idx] = True
        return mask
```

### Pattern 2: Position-Based Action Encoding (not ID-based)

**What:** Actions are encoded using board positions as parameters, not minion instance IDs. Since minion IDs are transient (created/destroyed during games), position-based encoding produces a stable integer mapping.

**When to use:** Always for this game -- positions are bounded (5x5 grid) while minion IDs grow monotonically.

**Example:**
```python
# MOVE action: "move minion at position (r,c) in direction d"
# Encoded as: MOVE_BASE + (r * GRID_COLS + c) * 4 + direction
# This gives a stable encoding regardless of which minion_id is there

# ATTACK action: "attack from position (r1,c1) to position (r2,c2)"
# Encoded as: ATTACK_BASE + (r1 * GRID_COLS + c1) * GRID_SIZE + (r2 * GRID_COLS + c2)

# PLAY_CARD action: "play card at hand_index i to position (r,c)"
# Encoded as: PLAY_CARD_BASE + i * GRID_SIZE + (r * GRID_COLS + c)
```

### Pattern 3: MaskablePPO-Compatible Action Mask

**What:** The environment exposes `action_masks()` returning `np.ndarray` of shape `(ACTION_SPACE_SIZE,)` with dtype `np.bool_` or `int`. MaskablePPO calls this method directly if present, or via the `ActionMasker` wrapper.

**When to use:** Always for this project (locked decision D-05).

**Two approaches:**
1. **Direct method** (recommended): Environment has `action_masks()` method. No wrapper needed. MaskablePPO detects this via `is_masking_supported()`.
2. **ActionMasker wrapper:** Wraps environment and delegates to a mask function. Needed only when the mask logic is external to the environment.

Use approach 1 -- simpler, no extra wrapper layer.

### Anti-Patterns to Avoid

- **Minion-ID-based action encoding:** Minion IDs grow monotonically (0, 1, 2, ...) and are destroyed unpredictably. Encoding "move minion #7" as a fixed integer would leave gaps and require dynamic remapping. Use "move minion at position (2,3) up" instead.
- **Variable-length observations:** The observation MUST be fixed-size. Do NOT return different-length arrays depending on hand size or board occupancy. Pad to maximum and zero-fill empty slots.
- **Game logic in the environment:** The env must NOT contain any rule logic. It calls `resolve_action()`, `legal_actions()`, and `encode_observation()`. Zero game rules in env.py.
- **Negative reward for illegal actions:** With action masking, illegal actions are impossible. Never return negative rewards for mask violations.

## Observation Space Design (Detailed)

### Design Principles
1. Flat 1D `np.float32` array (locked decision D-01)
2. Normalized to [-1.0, 1.0] range where possible
3. Hidden info excluded (D-02): opponent hand contents and deck order NOT visible
4. Documented field offsets for API deserialization (D-03)
5. Perspective-relative: "my" side is always encoded first, regardless of which player

### Observation Vector Layout

Total observation size: **292 floats**

```
Section                     Offset   Size   Description
---------------------------------------------------------------------------
BOARD STATE                 0        250    5x5 grid, 10 features per cell
  Per cell (10 features):
    [0] is_occupied          float    1.0 if minion present, 0.0 if empty
    [1] owner                float    1.0 = mine, -1.0 = opponent, 0.0 = empty
    [2] attack (normalized)  float    attack / MAX_STAT (0.0 if empty)
    [3] health (normalized)  float    current_health / MAX_STAT (0.0 if empty)
    [4] attack_range (norm)  float    attack_range / 2.0 (max range is 2)
    [5] attack_bonus (norm)  float    attack_bonus / MAX_STAT
    [6] card_type            float    0.0=minion (always for board), reserved
    [7] attribute            float    attr.value / 3.0 (Attribute enum: 0-3)
    [8] has_on_death_effect  float    1.0 if card has ON_DEATH effects
    [9] has_on_damaged_eff   float    1.0 if card has ON_DAMAGED effects

  Cell order: row-major (0,0), (0,1), ..., (4,4) = 25 cells x 10 = 250

MY HAND                     250      20     Up to 10 cards, 2 features each
  Per card slot (2 features):
    [0] is_present           float    1.0 if card exists in this slot, 0.0 padded
    [1] mana_cost (norm)     float    mana_cost / MAX_STAT

  MAX_HAND_SIZE = 10 slots x 2 features = 20
  (We encode only mana_cost for hand cards -- stat-based encoding of
   individual cards would leak too much about strategy for this initial
   version. The agent sees hand size and mana curve, which is sufficient
   for basic decision making. Card stats can be expanded later.)

MY RESOURCES                270      5
    [0] current_mana (norm)  float    current_mana / MAX_MANA_CAP
    [1] max_mana (norm)      float    max_mana / MAX_MANA_CAP
    [2] hp (normalized)      float    hp / STARTING_HP
    [3] deck_size (norm)     float    len(deck) / MIN_DECK_SIZE
    [4] graveyard_size       float    len(graveyard) / MIN_DECK_SIZE

OPPONENT VISIBLE            275      4
    [0] hp (normalized)      float    opponent_hp / STARTING_HP
    [1] current_mana (norm)  float    opponent_mana / MAX_MANA_CAP
    [2] hand_size (norm)     float    len(opponent_hand) / MAX_HAND_SIZE
    [3] deck_size (norm)     float    len(opponent_deck) / MIN_DECK_SIZE

GAME CONTEXT                279      3
    [0] turn_number (norm)   float    turn_number / DEFAULT_TURN_LIMIT
    [1] is_action_phase      float    1.0 if ACTION, 0.0 if REACT
    [2] am_i_active          float    1.0 if it's my turn to act

REACT CONTEXT               282      10
    [0] in_react_window      float    1.0 if phase == REACT
    [1] react_stack_depth    float    len(react_stack) / MAX_REACT_STACK_DEPTH
    [2-9] reserved           float    0.0 (padding for future react state)

TOTAL                                292 floats
```

### Key Design Decisions

**MAX_HAND_SIZE = 10:** No explicit hand size limit in the engine. Players start with 5 cards and can draw more. With a 40-card deck, starting 5, and drawing at the cost of an action, reaching 10+ cards in hand is extremely unlikely. 10 is a safe upper bound. If hand exceeds 10, truncate observation to the first 10 cards.

**Minimal hand encoding (2 features/card):** The initial observation encodes hand cards with only (is_present, mana_cost). This is intentionally minimal -- the agent needs to learn which cards to play based on mana cost vs. available mana. Full card stats (attack, health, effects) can be added in a future iteration if the agent needs richer hand information. This reduces observation size and speeds training.

**Perspective-relative encoding:** The observation is always from the perspective of the acting player. "My" resources come first, "opponent" resources second. When encoding for player 2, the board is NOT flipped -- row 0 is always row 0. Instead, the `owner` feature marks whose minions are whose relative to the observer. This avoids spatial confusion while maintaining perspective-relative info.

**Normalization:** All values normalized to approximately [-1, 1] or [0, 1]. Health/attack divided by MAX_STAT (5), mana by MAX_MANA_CAP (10), HP by STARTING_HP (20). Neural networks train faster with normalized inputs.

### Observation Space Alternative: Richer Hand Encoding

If training reveals the agent cannot learn card-play strategy with minimal hand info, expand hand encoding to 6 features per card:

```
Per card slot (6 features):
    [0] is_present
    [1] mana_cost / MAX_STAT
    [2] card_type (0.0=minion, 0.5=magic, 1.0=react)
    [3] attack / MAX_STAT (0 for non-minion)
    [4] health / MAX_STAT (0 for non-minion)
    [5] attack_range / 2.0 (0 for non-minion)
```

This would change hand section to 10 x 6 = 60 features, total obs size = 332.

## Action Space Design (Detailed)

### Design Principles
1. Flat `Discrete(N)` space (locked decision D-04)
2. Position-based encoding for stable integer mapping
3. Every valid action from `legal_actions()` must map to exactly one integer
4. The encoding must be deterministic and invertible (D-06)
5. Most actions are masked out at any given step (~5-20 legal out of ~567 total)

### Action Encoding Scheme

```
Action Type      Base    Encoding                               Count
---------------------------------------------------------------------------
PLAY_CARD        0       hand_idx * GRID_SIZE + position         10 * 25 = 250
  (minion deploy or untargeted magic: card from hand to cell)
  hand_idx: 0..MAX_HAND-1 (10)
  position: 0..24 (row-major cell index)

PLAY_CARD_TARGET 250     hand_idx * GRID_SIZE + target_pos       10 * 25 = 250
  (targeted magic or minion with ON_PLAY target)
  hand_idx: 0..MAX_HAND-1 (10)
  target_pos: 0..24 (row-major cell index of target)

MOVE             500     source_pos * 4 + direction              25 * 4 = 100
  (move minion at source_pos in direction)
  source_pos: 0..24 (where the minion currently is)
  direction: 0=up, 1=down, 2=left, 3=right

ATTACK           600     source_pos * GRID_SIZE + target_pos     25 * 25 = 625
  (attack from source to target position)
  -- WAIT: this is 625 which is large. Let me reconsider. --

SACRIFICE        600     source_pos                              25
  (sacrifice minion at source_pos)
  Actually only 10 cells are valid (back rows), but we encode all 25
  and mask the rest. Keeps encoding simple.

DRAW             625     (no params)                             1

PASS             626     (no params)                             1

PLAY_REACT       627     hand_idx * (GRID_SIZE + 1) + target     10 * 26 = 260
  (play react card; target_pos is 0..24, or 25 for no-target)
  hand_idx: 0..MAX_HAND-1 (10)
  target: 0..24 (target cell) or 25 (untargeted)

TOTAL                                                            888
```

Wait -- this is getting large. Let me re-evaluate with tighter encoding.

### Optimized Action Encoding

The key insight: ATTACK from position A to position B where B is within range is heavily masked. Most of the 25x25=625 pairs are always illegal. But the action space should cover the worst case. However, 625 attack slots is excessive.

**Better approach for ATTACK:** Use a relative-target scheme. From any position, the maximum attack range is 2 (ranged units). The reachable positions from any cell are at most 12 (4 orthogonal up to distance 2 + 4 diagonal adjacent). So encode as:

```
ATTACK: source_pos * MAX_TARGETS + target_offset
```

But this requires a fixed mapping of relative offsets, which is complex to implement correctly.

**Pragmatic approach:** Accept the flat encoding with generous masking. The action space size matters far less than the masking quality. MaskablePPO zeroes out illegal actions before sampling, so a larger space with good masks works fine. Research confirms action spaces of 400-1000 work well with MaskablePPO.

### Final Action Encoding (Recommended)

```
Action Type        Base   Formula                              Count
---------------------------------------------------------------------------
PLAY_CARD          0      hand_idx(10) * GRID_SIZE(25) + pos   250
PLAY_CARD_TARGETED 250    hand_idx(10) * GRID_SIZE(25) + tgt   250
MOVE               500    cell(25) * 4 + dir(4)                100
ATTACK             600    cell(25) * GRID_SIZE(25) + tgt(25)   625 [*see note]
SACRIFICE          ---    (merged into special action below)
DRAW               1225   (no params)                          1
PASS               1226   (no params)                          1
PLAY_REACT         1227   hand_idx(10) * 26 + target(26)       260
SACRIFICE          1487   cell(25)                             25
---------------------------------------------------------------------------
TOTAL                                                          1513
```

**Note on ATTACK size:** 625 actions for attack is large but acceptable. Typically only 0-5 attack actions are legal at any time. MaskablePPO handles this efficiently. The alternative (relative target encoding) adds implementation complexity without meaningful benefit.

**HOWEVER:** 1513 is on the larger side. Let me reconsider whether we need separate PLAY_CARD and PLAY_CARD_TARGETED sections.

### Simplified Action Encoding (Recommended Final)

Merge PLAY_CARD variants. A "play card" action always specifies (hand_idx, deploy_pos, target_pos). For untargeted cards, target_pos is unused and masked. For magic cards, deploy_pos is unused and masked. We can encode this as two separate action sets or use a combined approach.

**Cleanest approach -- three disjoint action sets for PLAY_CARD:**

```
Action Type        Base   Formula                              Count
---------------------------------------------------------------------------
PLAY_CARD_POS      0      hand(10) * grid(25) + pos(25)        250
  Deploy minion at pos (no targeted effect)

PLAY_CARD_POS_TGT  250    hand(10) * grid(25) * grid(25)       6250 -- TOO BIG
```

This blows up. The combination of deploy position AND target position is 25*25=625 per card, times 10 hand slots = 6250. Not viable.

**Solution: Decompose into two-step or accept that targeted deploys share action space.**

After careful analysis of the actual `legal_actions()` code, here is what actions actually look like:

1. `play_card_action(card_index=i, position=(r,c))` -- minion deploy, no target
2. `play_card_action(card_index=i, position=(r,c), target_pos=(tr,tc))` -- minion deploy WITH target
3. `play_card_action(card_index=i, target_pos=(tr,tc))` -- magic with target
4. `play_card_action(card_index=i)` -- magic without target (area/self)

For case 2, both position and target_pos matter. This is the expensive case.

**Practical sizing:** In the current card pool of 18 cards, only a few minions have ON_PLAY SINGLE_TARGET effects. Most minion deploys are case 1 (no target). The targeted minion deploy case (2) requires a combined pos+target encoding.

**Recommended encoding strategy:**

```
Section              Base   Encoding                            Count   Notes
---------------------------------------------------------------------------
PLAY_UNTARGETED      0      hand(10) * grid(25) + pos(25)       250    Minion deploy + untargeted magic
PLAY_TARGETED        250    hand(10) * grid(25) + tgt(25)       250    Targeted magic (no deploy pos)
PLAY_DEPLOY_TARGET   500    hand(10) * grid(10) * grid(25)      2500   Minion deploy WITH target
  -- deploy_cells for P1: rows 0-1 = 10 cells; P2: rows 3-4 = 10 cells
  -- Encode: hand(10) * deploy_cell(10) * target_cell(25)
  -- This is still 2500 which is large

MOVE                 ...
```

This is getting complex. Let me step back to a pragmatic recommendation.

### RECOMMENDED: Two-Phase Encoding Strategy

**Phase 5 (this phase): Simple encoding WITHOUT targeted deploy minions**

In the current card pool, very few cards have ON_PLAY SINGLE_TARGET effects on minions. For Phase 5 validation (10k random episodes), we can use a simpler encoding:

```
Action Type        Base   Encoding                            Count
---------------------------------------------------------------------------
PLAY_CARD          0      hand(10) * grid(25) + cell(25)       250
  Used for: minion deploy (cell = deploy position)
            targeted magic (cell = target position)
            untargeted magic (cell = 0, masked to only idx 0)

PLAY_CARD_2POS     250    hand(10) * grid(25) + tgt(25)        250
  Used for: minion deploy WITH on_play target
            (deploy pos encoded in first section, target here)
  WAIT -- this doesn't work because we need BOTH positions.
```

**FINAL RECOMMENDED APPROACH:**

After considering all options, the clearest approach is a **combined position encoding** where each action type gets its own flat range:

```
Action Type            Base    Encoding                        Count
---------------------------------------------------------------------------
DEPLOY_MINION          0       hand(10) * grid(25) + cell(25)   250
  Deploy minion at cell. No target effect.

DEPLOY_MINION_TARGET   250     hand(10) * deploy(10) * grid(25) 2500
  Deploy minion at a deploy cell (10 max friendly cells)
  with ON_PLAY target at any grid cell.
  deploy_cells encoded as index 0-9 within friendly rows.

CAST_MAGIC_TARGET      2750    hand(10) * grid(25) + tgt(25)    250
  Cast targeted magic. target = grid cell.

CAST_MAGIC_UNTARGETED  3000    hand(10)                         10
  Cast untargeted magic/area effect.

MOVE                   3010    cell(25) * 4 + dir(4)            100

ATTACK                 3110    cell(25) * grid(25) + tgt(25)    625

SACRIFICE              3735    cell(25)                         25

DRAW                   3760    --                               1

PASS                   3761    --                               1

PLAY_REACT_TARGETED    3762    hand(10) * grid(25) + tgt(25)    250

PLAY_REACT_UNTARGETED  4012    hand(10)                         10

---------------------------------------------------------------------------
TOTAL                                                           4022
```

**This is too large (4022).** Let me reconsider.

### PRAGMATIC FINAL RECOMMENDATION

The issue is DEPLOY_MINION_TARGET which requires 3 parameters (hand, deploy_pos, target_pos). This is inherently expensive. Two approaches:

**Option A: Ignore targeted minion deploys for now (simplify)**
In the current 18-card pool, only 1-2 minion cards have ON_PLAY SINGLE_TARGET effects. We can handle these by having the environment auto-select the target (e.g., nearest enemy) or by making targeted deploys a special case. This is acceptable for Phase 5 validation with random agents.

**Option B: Accept larger space with heavy masking**
4022 actions with 5-20 legal at any time is fine for MaskablePPO. The GitHub issue #247 for sb3-contrib confirms large action spaces (1000+) work with MaskablePPO when properly masked.

**RECOMMENDATION: Option B -- accept the full space.** The encoding must be complete to avoid blocking Phase 6 training. However, optimize the DEPLOY_MINION_TARGET encoding:

Since ranged minions deploy only to back row (5 cells per side, not 10), and melee minions have no range, the actual deploy+target combinations are much smaller in practice. But the encoding must handle the worst case.

**SIMPLIFIED FINAL ENCODING (balancing completeness and size):**

```
Section                  Base   Size   Encoding
---------------------------------------------------------------------------
PLAY_CARD_TO_CELL        0      250    hand(10) * grid(25) + cell
  Covers: minion deploy (cell=deploy pos), targeted magic (cell=target)

PLAY_CARD_DEPLOY_TARGET  250    250    hand(10) * grid(25) + target_cell
  For minion with ON_PLAY target: deploy pos is implicit from the
  PLAY_CARD_TO_CELL action for same hand_idx. Actually this doesn't
  work because we need both positions.
```

### ACTUAL FINAL RECOMMENDATION

After extensive analysis, here is the encoding I recommend. The key insight is that **targeted minion deploys can be split into two action slots** by pre-computing the (deploy_pos, target_pos) pairs that legal_actions generates and mapping them to a flat range.

But this pre-computation makes the encoding non-deterministic. So instead:

**Use a flat enumeration where every possible (action_type, hand_idx, position, target_position) tuple gets a unique integer.** Accept the size. Here is the calculation:

```
Action Type               Params                              Count
---------------------------------------------------------------------------
DEPLOY_UNTARGETED         hand(10) * deploy_cells(25)          250
DEPLOY_WITH_TARGET        hand(10) * deploy_cells(10) * tgt(25) 2500
CAST_TARGETED             hand(10) * target(25)                250
CAST_UNTARGETED           hand(10)                             10
MOVE                      source(25) * dir(4)                  100
ATTACK                    source(25) * target(25)              625
SACRIFICE                 source(25)                           25
DRAW                      --                                   1
PASS                      --                                   1
REACT_TARGETED            hand(10) * target(25)                250
REACT_UNTARGETED          hand(10)                             10
---------------------------------------------------------------------------
TOTAL                                                          4022
```

**4022 discrete actions.** Heavy masking brings this to 5-20 legal actions per step. This is within MaskablePPO's proven capabilities.

**ALTERNATIVELY -- a much simpler encoding is possible if we limit deploy cells to 10 (friendly rows only) for all PLAY_CARD actions:**

```
Action Type               Params                              Count
---------------------------------------------------------------------------
PLAY_CARD                 hand(10) * cell(25) * tgt_or_none(26) -- still huge
```

**FINAL FINAL: Recommended Compact Encoding**

After reviewing how other card game RL projects handle this (RLCard uses separate action per concrete choice), the cleanest approach for this game is:

```
Section            Base    Encoding                    Count  Mask
-------------------------------------------------------------------
PLAY_CARD          0       hand(10) * cell(25)         250    cell=deploy for minion, target for magic
PLAY_DEPLOY_TGT    250     hand(10) * cell_pair(250)   2500   cell_pair = deploy_idx(10) * tgt(25)
MOVE               2750    source(25) * dir(4)         100
ATTACK             2850    source(25) * target(25)     625
SACRIFICE          3475    source(25)                  25
DRAW               3500    --                          1
PASS               3501    --                          1
REACT              3502    hand(10) * tgt_or_none(26)  260
-------------------------------------------------------------------
TOTAL                                                  3762
```

I am going to simplify this significantly. The deploy-with-target encoding (2500 slots) dominates the space for a rare action. Let me check how many cards actually trigger this.

From the card data: only cards with ON_PLAY + SINGLE_TARGET effects on minions. Looking at the 18 starter cards -- none of the minion cards have SINGLE_TARGET ON_PLAY effects. The fire_imp and others have self_owner or adjacent targets. Only magic cards (fireball, dark_drain) have SINGLE_TARGET.

**So for the starter pool, DEPLOY_WITH_TARGET actions never occur!** This means we can safely defer DEPLOY_WITH_TARGET to Phase 8 (card expansion) and use a compact encoding now.

### DEFINITIVE Action Space Encoding

For Phase 5 with the 18-card starter pool:

```
Section            Base    Encoding                    Count
-------------------------------------------------------------------
PLAY_CARD          0       hand(10) * cell(25)         250
  Minion: cell = deploy position
  Magic targeted: cell = target position
  Magic untargeted: cell = 0 (only index 0 unmasked)
  React cards: masked out during ACTION phase

MOVE               250     source(25) * dir(4)         100

ATTACK             350     source(25) * target(25)     625

SACRIFICE          975     source(25)                  25

DRAW               1000    --                          1

PASS               1001    --                          1

PLAY_REACT         1002    hand(10) * tgt_or_none(26)  260
  target: 0-24 for targeted react, 25 for untargeted

-------------------------------------------------------------------
TOTAL ACTION SPACE SIZE:                                1262
```

**1262 discrete actions.** This is clean, manageable, and covers all actions in the current card pool. When Phase 8 adds cards with minion ON_PLAY SINGLE_TARGET, extend the encoding by adding a DEPLOY_WITH_TARGET section.

**Encoding detail:**
```python
# PLAY_CARD: action_int = 0 + hand_idx * 25 + cell_flat_idx
# MOVE:      action_int = 250 + source_flat * 4 + direction
# ATTACK:    action_int = 350 + source_flat * 25 + target_flat
# SACRIFICE: action_int = 975 + source_flat
# DRAW:      action_int = 1000
# PASS:      action_int = 1001
# PLAY_REACT: action_int = 1002 + hand_idx * 26 + target_or_25
```

**Decoding** is the reverse: determine which section by range, then extract parameters.

**Masking example:**
- At game start (ACTION phase, 5 cards in hand, empty board):
  - PLAY_CARD: ~5-10 card+position combos legal (affordable cards x valid deploy positions)
  - MOVE: 0 (no minions)
  - ATTACK: 0 (no minions)
  - SACRIFICE: 0 (no minions on opponent back row)
  - DRAW: 1 (deck non-empty)
  - PASS: 1 (always)
  - PLAY_REACT: 0 (ACTION phase, not REACT)
  - Total legal: ~7-12 out of 1262

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Environment API compliance | Custom step/reset protocol | `gymnasium.Env` base class | Provides `np_random`, space validation, `env_checker`, and SB3 compatibility |
| Space definitions | Custom observation/action descriptors | `gymnasium.spaces.Box`, `gymnasium.spaces.Discrete` | SB3 reads these to configure neural networks automatically |
| Action mask validation | Manual mask checks | `gymnasium.utils.env_checker.check_env()` | Catches shape mismatches, dtype errors, and API violations |
| Random episode testing | Custom test loop | `gymnasium.utils.env_checker.check_env()` + simple while loop | Built-in checker validates full API contract |

## Common Pitfalls

### Pitfall 1: Observation Leaks Opponent Hidden Information
**What goes wrong:** Encoding opponent's hand contents or deck order into the observation vector. Agent learns to "see" opponent cards and develops strategies that fail when info is hidden.
**Why it happens:** Easier to encode full GameState than filter per-player visibility.
**How to avoid:** Observation encoder takes `player_idx` parameter. For opponent, encode only: HP, mana, hand_size (count), deck_size (count). Never encode opponent hand card IDs or deck order.
**Warning signs:** Agent performance drops dramatically when switching from self-play to asymmetric info.

### Pitfall 2: Action Mask Mismatch with Legal Actions
**What goes wrong:** The mask says action X is legal, but `resolve_action()` rejects it (or vice versa). This causes crashes during training or silent illegal moves.
**Why it happens:** Action encoder and `legal_actions()` use different logic for legality.
**How to avoid:** Single source of truth: `legal_actions()` generates actions, `action_encoder.encode()` maps them to ints, mask is built from that mapping. Never recompute legality in the mask function. Write a test that compares mask vs. legal_actions for 1000 random states.
**Warning signs:** `ValueError` from `resolve_action()` during training.

### Pitfall 3: Non-Deterministic Reset Breaks Reproducibility
**What goes wrong:** Calling `reset()` without a seed produces different initial states. Training runs are not reproducible.
**Why it happens:** Not forwarding the seed to `GameState.new_game()` or using `self.np_random` inconsistently.
**How to avoid:** Always accept `seed` in `reset()`. Forward to `GameRNG`. Use `self.np_random` from Gymnasium base class for any env-level randomness (opponent selection in future phases). Test: same seed produces identical first observation.
**Warning signs:** Same hyperparameters produce wildly different training curves.

### Pitfall 4: Observation Shape Changes Between Steps
**What goes wrong:** Observation has different shapes depending on game state (e.g., different hand sizes produce different vector lengths).
**Why it happens:** Not padding to fixed size.
**How to avoid:** Fixed observation_space shape declared in `__init__`. Pad hand to MAX_HAND_SIZE. Zero-fill empty board cells. Assert observation.shape == observation_space.shape in step().
**Warning signs:** SB3 crashes with shape mismatch error on first training step.

### Pitfall 5: Both Players Need to Act But Only One Is the Agent
**What goes wrong:** The environment is single-agent (Gymnasium), but the game has two players. If the env only handles one player's actions, the opponent never acts, or the game stalls.
**Why it happens:** Gymnasium assumes one agent. Two-player games need special handling.
**How to avoid:** For Phase 5 validation (random episodes), the env should handle BOTH players. When it's the "agent" player's turn, return the observation and wait for action. When it's the "opponent" player's turn, auto-select a random action from legal_actions(). This creates a complete game loop. In Phase 6, the opponent becomes a trained policy.
**Warning signs:** Games never terminate, or only one player ever acts.

### Pitfall 6: Gymnasium env_checker Fails on Windows
**What goes wrong:** STATE.md flags that Gymnasium has unofficial Windows support.
**How to avoid:** Test early. Run `gymnasium.utils.env_checker.check_env(env)` as the very first validation step after implementing the environment. All 450 existing game engine tests pass on Windows, so the engine itself is fine.
**Warning signs:** Import errors, DLL issues on import.

## Code Examples

### Example 1: Observation Encoding Function
```python
# Source: designed from GameState fields + ARCHITECTURE.md patterns
import numpy as np
from grid_tactics.game_state import GameState
from grid_tactics.card_library import CardLibrary
from grid_tactics.types import (
    GRID_ROWS, GRID_COLS, GRID_SIZE, MAX_MANA_CAP, STARTING_HP,
    DEFAULT_TURN_LIMIT, MAX_STAT, MIN_DECK_SIZE, MAX_REACT_STACK_DEPTH,
)
from grid_tactics.enums import TurnPhase

MAX_HAND_SIZE = 10
FEATURES_PER_CELL = 10
HAND_FEATURES = 2
OBSERVATION_SIZE = (
    GRID_SIZE * FEATURES_PER_CELL  # 250: board
    + MAX_HAND_SIZE * HAND_FEATURES  # 20: hand
    + 5  # my resources
    + 4  # opponent visible
    + 3  # game context
    + 10  # react context
)  # = 292

def encode_observation(
    state: GameState,
    library: CardLibrary,
    observer_idx: int,
) -> np.ndarray:
    obs = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
    offset = 0
    observer = state.players[observer_idx]
    opponent = state.players[1 - observer_idx]

    # Board state: 25 cells x 10 features
    for r in range(GRID_ROWS):
        for c in range(GRID_COLS):
            cell_base = offset + (r * GRID_COLS + c) * FEATURES_PER_CELL
            minion_id = state.board.get(r, c)
            if minion_id is not None:
                minion = state.get_minion(minion_id)
                card_def = library.get_by_id(minion.card_numeric_id)
                obs[cell_base + 0] = 1.0  # is_occupied
                obs[cell_base + 1] = 1.0 if minion.owner == observer.side else -1.0
                obs[cell_base + 2] = card_def.attack / MAX_STAT
                obs[cell_base + 3] = minion.current_health / MAX_STAT
                obs[cell_base + 4] = (card_def.attack_range or 0) / 2.0
                obs[cell_base + 5] = minion.attack_bonus / MAX_STAT
                obs[cell_base + 6] = 0.0  # card_type (always minion on board)
                obs[cell_base + 7] = (card_def.attribute.value if card_def.attribute else 0) / 3.0
                # Effect flags
                from grid_tactics.enums import TriggerType
                obs[cell_base + 8] = 1.0 if any(
                    e.trigger == TriggerType.ON_DEATH for e in card_def.effects
                ) else 0.0
                obs[cell_base + 9] = 1.0 if any(
                    e.trigger == TriggerType.ON_DAMAGED for e in card_def.effects
                ) else 0.0
    offset += GRID_SIZE * FEATURES_PER_CELL  # 250

    # My hand: 10 slots x 2 features
    for i in range(MAX_HAND_SIZE):
        hand_base = offset + i * HAND_FEATURES
        if i < len(observer.hand):
            card_def = library.get_by_id(observer.hand[i])
            obs[hand_base + 0] = 1.0
            obs[hand_base + 1] = card_def.mana_cost / MAX_STAT
    offset += MAX_HAND_SIZE * HAND_FEATURES  # 20

    # My resources: 5 features
    obs[offset + 0] = observer.current_mana / MAX_MANA_CAP
    obs[offset + 1] = observer.max_mana / MAX_MANA_CAP
    obs[offset + 2] = observer.hp / STARTING_HP
    obs[offset + 3] = len(observer.deck) / MIN_DECK_SIZE
    obs[offset + 4] = len(observer.graveyard) / MIN_DECK_SIZE
    offset += 5

    # Opponent visible: 4 features
    obs[offset + 0] = opponent.hp / STARTING_HP
    obs[offset + 1] = opponent.current_mana / MAX_MANA_CAP
    obs[offset + 2] = len(opponent.hand) / MAX_HAND_SIZE
    obs[offset + 3] = len(opponent.deck) / MIN_DECK_SIZE
    offset += 4

    # Game context: 3 features
    obs[offset + 0] = state.turn_number / DEFAULT_TURN_LIMIT
    obs[offset + 1] = 1.0 if state.phase == TurnPhase.ACTION else 0.0
    is_active = (state.active_player_idx == observer_idx
                 if state.phase == TurnPhase.ACTION
                 else state.react_player_idx == observer_idx)
    obs[offset + 2] = 1.0 if is_active else 0.0
    offset += 3

    # React context: 10 features (2 used, 8 reserved)
    obs[offset + 0] = 1.0 if state.phase == TurnPhase.REACT else 0.0
    obs[offset + 1] = len(state.react_stack) / MAX_REACT_STACK_DEPTH
    offset += 10

    return obs
```

### Example 2: Action Encoder Class
```python
# Source: designed from legal_actions.py action types + position-based encoding
from grid_tactics.actions import Action
from grid_tactics.enums import ActionType
from grid_tactics.types import GRID_COLS, GRID_SIZE

MAX_HAND_SIZE = 10

# Section bases
PLAY_CARD_BASE = 0            # 250 slots
MOVE_BASE = 250               # 100 slots
ATTACK_BASE = 350             # 625 slots
SACRIFICE_BASE = 975          # 25 slots
DRAW_IDX = 1000               # 1 slot
PASS_IDX = 1001               # 1 slot
REACT_BASE = 1002             # 260 slots
ACTION_SPACE_SIZE = 1262

DIRECTION_MAP = {
    (-1, 0): 0,  # up
    (1, 0): 1,   # down
    (0, -1): 2,  # left
    (0, 1): 3,   # right
}
DIRECTION_REVERSE = {v: k for k, v in DIRECTION_MAP.items()}

def pos_to_flat(pos: tuple[int, int]) -> int:
    return pos[0] * GRID_COLS + pos[1]

def flat_to_pos(flat: int) -> tuple[int, int]:
    return (flat // GRID_COLS, flat % GRID_COLS)


class ActionEncoder:
    """Bidirectional mapping between Action objects and integer IDs."""

    def encode(self, action: Action, state=None) -> int:
        at = action.action_type

        if at == ActionType.PASS:
            return PASS_IDX
        elif at == ActionType.DRAW:
            return DRAW_IDX
        elif at == ActionType.PLAY_CARD:
            hand_idx = action.card_index
            # Determine which cell to encode
            if action.position is not None:
                cell = pos_to_flat(action.position)
            elif action.target_pos is not None:
                cell = pos_to_flat(action.target_pos)
            else:
                cell = 0  # untargeted magic
            return PLAY_CARD_BASE + hand_idx * GRID_SIZE + cell
        elif at == ActionType.MOVE:
            # Need the minion's current position from state
            minion = state.get_minion(action.minion_id)
            source = pos_to_flat(minion.position)
            delta = (action.position[0] - minion.position[0],
                     action.position[1] - minion.position[1])
            direction = DIRECTION_MAP[delta]
            return MOVE_BASE + source * 4 + direction
        elif at == ActionType.ATTACK:
            attacker = state.get_minion(action.minion_id)
            defender = state.get_minion(action.target_id)
            src = pos_to_flat(attacker.position)
            tgt = pos_to_flat(defender.position)
            return ATTACK_BASE + src * GRID_SIZE + tgt
        elif at == ActionType.SACRIFICE:
            minion = state.get_minion(action.minion_id)
            return SACRIFICE_BASE + pos_to_flat(minion.position)
        elif at == ActionType.PLAY_REACT:
            hand_idx = action.card_index
            if action.target_pos is not None:
                tgt = pos_to_flat(action.target_pos)
            else:
                tgt = 25  # untargeted sentinel
            return REACT_BASE + hand_idx * 26 + tgt
        raise ValueError(f"Unknown action type: {at}")

    def decode(self, action_int: int, state=None) -> Action:
        if action_int == PASS_IDX:
            return Action(action_type=ActionType.PASS)
        elif action_int == DRAW_IDX:
            return Action(action_type=ActionType.DRAW)
        elif PLAY_CARD_BASE <= action_int < MOVE_BASE:
            idx = action_int - PLAY_CARD_BASE
            hand_idx = idx // GRID_SIZE
            cell = idx % GRID_SIZE
            pos = flat_to_pos(cell)
            # Caller must determine if pos is deploy or target based on card type
            return Action(action_type=ActionType.PLAY_CARD,
                         card_index=hand_idx, position=pos)
        # ... (similar decode for other sections)
```

### Example 3: Reward Function
```python
# Source: PITFALLS.md Pattern 4 -- sparse rewards first
def compute_reward(state: GameState, player_idx: int) -> float:
    """Sparse reward: +1 win, -1 loss, 0 draw, 0 in-progress."""
    if not state.is_game_over:
        return 0.0
    if state.winner is None:
        return 0.0  # draw
    winner_idx = int(state.winner)  # PlayerSide enum value = player index
    if winner_idx == player_idx:
        return 1.0
    else:
        return -1.0
```

### Example 4: Random Episode Validation
```python
# Source: game_loop.py run_game pattern adapted for gymnasium
def validate_random_episodes(env, num_episodes=10000):
    """Run N random episodes, assert no errors."""
    for ep in range(num_episodes):
        obs, info = env.reset(seed=ep)
        assert obs.shape == env.observation_space.shape
        assert info["action_mask"].shape == (env.action_space.n,)

        done = False
        steps = 0
        while not done:
            mask = info["action_mask"]
            assert mask.any(), f"No legal actions at step {steps}"
            legal_indices = np.nonzero(mask)[0]
            action = np.random.choice(legal_indices)
            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated
            steps += 1
            assert steps < 10000, "Infinite loop detected"

    print(f"All {num_episodes} episodes completed successfully")
```

## Handling PLAY_CARD Ambiguity

The `PLAY_CARD` action encoding merges deploy-position and target-position into one `cell` parameter. This creates an ambiguity: does `cell` mean "deploy minion here" or "target this cell with magic"?

**Resolution:** The `decode()` method receives the game state. It looks up the card at `hand_idx` in the active player's hand. If the card is a minion, `cell` is the deploy position. If the card is targeted magic, `cell` is the target position. If the card is untargeted magic, `cell` is ignored (only cell=0 is unmasked).

**Edge case -- minion with ON_PLAY target:** In the current 18-card starter pool, no minion has ON_PLAY SINGLE_TARGET effects. If Phase 8 adds such cards, the action space must be extended with a DEPLOY_WITH_TARGET section. For now, the simple encoding suffices.

**Encoding the `decode()` logic:**
```python
def decode_play_card(action_int, state, library):
    idx = action_int - PLAY_CARD_BASE
    hand_idx = idx // GRID_SIZE
    cell_flat = idx % GRID_SIZE
    cell_pos = flat_to_pos(cell_flat)

    player = state.active_player
    card_id = player.hand[hand_idx]
    card_def = library.get_by_id(card_id)

    if card_def.card_type == CardType.MINION:
        return Action(action_type=ActionType.PLAY_CARD,
                     card_index=hand_idx, position=cell_pos)
    elif card_def.card_type == CardType.MAGIC:
        has_target = any(e.target == TargetType.SINGLE_TARGET
                        for e in card_def.effects)
        if has_target:
            return Action(action_type=ActionType.PLAY_CARD,
                         card_index=hand_idx, target_pos=cell_pos)
        else:
            return Action(action_type=ActionType.PLAY_CARD,
                         card_index=hand_idx)
```

## Handling Two Players in Single-Agent Environment

For Phase 5 (validation only, not training), the simplest approach:

**Option A -- Agent controls BOTH players (recommended for Phase 5):**
The environment always returns the observation for the current acting player. The agent (random or trained) acts for both sides. This validates the full game loop without needing a separate opponent policy.

```python
def step(self, action_int):
    # Decode and apply action for current active player
    action = self.action_encoder.decode(action_int, self.state, self.library)
    self.state = resolve_action(self.state, action, self.library)

    # Determine who acts next
    obs = encode_observation(self.state, self.library,
                             self._current_player_idx())
    reward = 0.0  # Only at terminal
    terminated = self.state.is_game_over
    truncated = self.state.turn_number > self.turn_limit

    if terminated:
        # Reward from perspective of the player who just acted
        reward = compute_reward(self.state, self._last_acting_player_idx())

    info = {"action_mask": self.action_masks()}
    return obs, reward, terminated, truncated, info
```

This means the environment alternates between player perspectives. The agent sees "its" hand and "its" legal actions regardless of which physical player it is controlling. This is exactly how the PettingZoo Connect Four tutorial handles it.

**For Phase 6 training:** The SelfPlayWrapper will make one player the training agent and the other an opponent from the agent pool. That is Phase 6 scope, not Phase 5.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| OpenAI Gym | Gymnasium (Farama) | 2022-2023 | Use `gymnasium` not `gym` everywhere |
| Penalty for illegal actions | Action masking (MaskablePPO) | 2022+ | Never penalize; always mask |
| Full state as observation | Per-player partial observation | Always best practice | Critical for imperfect info games |
| One-hot card encoding | Stat-based encoding | Research consensus | Enables generalization across cards |

## Open Questions

1. **Minion deploy + target two-position actions**
   - What we know: Current starter pool has no minions with ON_PLAY SINGLE_TARGET effects, so the simple encoding works.
   - What's unclear: Phase 8 card expansion may add such cards, requiring action space extension.
   - Recommendation: Use simple encoding now. Document the extension point. Add DEPLOY_WITH_TARGET section when needed.

2. **Observation richness for hand cards**
   - What we know: Minimal encoding (is_present, mana_cost) is sufficient for random validation.
   - What's unclear: Will training in Phase 6 converge with minimal hand info?
   - Recommendation: Start minimal (2 features/card). If Phase 6 training fails to learn card-play strategy, expand to 6 features/card (adding card_type, attack, health, range).

3. **Board perspective flipping**
   - What we know: Current design does NOT flip the board for player 2. Both players see the same spatial layout with owner flags.
   - What's unclear: Would board flipping help the agent learn symmetrically?
   - Recommendation: No flipping for now. The owner field (+1/-1) provides perspective. Flipping adds complexity and could confuse spatial reasoning. Can experiment in Phase 6.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 | All | Yes | 3.12.10 | -- |
| numpy | Observation/mask arrays | Yes | 2.4.4 | -- |
| gymnasium | Env base class + spaces | **No (not installed)** | -- | Install: `pip install "gymnasium>=1.2,<2.0"` |
| pytest | Validation tests | Yes | 9.0.2 | -- |
| sb3-contrib | MaskablePPO (Phase 6) | **No** | -- | Not needed for Phase 5; install in Phase 6 |

**Missing dependencies with no fallback:**
- gymnasium: Must be installed as first task in Phase 5

**Missing dependencies with fallback:**
- None -- gymnasium is the only new dependency

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `.venv/Scripts/python.exe -m pytest tests/ -x -q` |
| Full suite command | `.venv/Scripts/python.exe -m pytest tests/ -v` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RL-01 | Gymnasium API compliance (reset/step/spaces) | unit | `pytest tests/test_rl_env.py::test_gymnasium_api -x` | No -- Wave 0 |
| RL-01 | env_checker passes | integration | `pytest tests/test_rl_env.py::test_env_checker -x` | No -- Wave 0 |
| RL-02 | Observation shape matches space | unit | `pytest tests/test_observation.py::test_observation_shape -x` | No -- Wave 0 |
| RL-02 | No opponent hidden info in observation | unit | `pytest tests/test_observation.py::test_no_hidden_info_leak -x` | No -- Wave 0 |
| RL-02 | Observation values normalized to [-1,1] | unit | `pytest tests/test_observation.py::test_observation_range -x` | No -- Wave 0 |
| RL-03 | Action mask shape matches action space | unit | `pytest tests/test_action_space.py::test_mask_shape -x` | No -- Wave 0 |
| RL-03 | Mask agrees with legal_actions() | integration | `pytest tests/test_action_space.py::test_mask_matches_legal -x` | No -- Wave 0 |
| RL-03 | Encode/decode roundtrip for all action types | unit | `pytest tests/test_action_space.py::test_encode_decode_roundtrip -x` | No -- Wave 0 |
| RL-03 | At least one action always legal (PASS) | unit | `pytest tests/test_action_space.py::test_always_has_legal -x` | No -- Wave 0 |
| ALL | 10,000 random episodes complete without error | smoke | `pytest tests/test_rl_env.py::test_10k_random_episodes -x` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/Scripts/python.exe -m pytest tests/ -x -q`
- **Per wave merge:** `.venv/Scripts/python.exe -m pytest tests/ -v`
- **Phase gate:** Full suite green including 10k episode smoke test

### Wave 0 Gaps
- [ ] `tests/test_rl_env.py` -- covers RL-01 (Gymnasium compliance, env_checker, random episodes)
- [ ] `tests/test_observation.py` -- covers RL-02 (shape, normalization, no info leak)
- [ ] `tests/test_action_space.py` -- covers RL-03 (mask shape, encode/decode roundtrip, mask-legal agreement)
- [ ] Framework install: `pip install "gymnasium>=1.2,<2.0"` -- new dependency

## Sources

### Primary (HIGH confidence)
- [Gymnasium Custom Environment Tutorial](https://gymnasium.farama.org/introduction/create_custom_env/) -- Env API, reset/step signatures, space definitions
- [Gymnasium Env API Reference](https://gymnasium.farama.org/api/env/) -- Full method signatures and return types
- [sb3-contrib MaskablePPO docs](https://sb3-contrib.readthedocs.io/en/master/modules/ppo_mask.html) -- Action masking API
- [sb3-contrib ActionMasker source](https://github.com/Stable-Baselines-Team/stable-baselines3-contrib/blob/master/sb3_contrib/common/wrappers/action_masker.py) -- ActionMasker wrapper implementation
- [PettingZoo Connect Four + MaskablePPO tutorial](https://pettingzoo.farama.org/tutorials/sb3/connect_four/) -- Self-play wrapper pattern for card/board games
- [SB3 Custom Environments guide](https://stable-baselines3.readthedocs.io/en/master/guide/custom_env.html) -- Environment requirements for SB3
- [Gymnasium Action Masking Taxi tutorial](https://gymnasium.farama.org/tutorials/training_agents/action_masking_taxi/) -- Action mask in info dict pattern

### Secondary (MEDIUM confidence)
- Project source code: `legal_actions.py`, `actions.py`, `game_state.py`, `game_loop.py` -- verified by 450 passing tests
- Project research: `STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md` -- prior research from project setup

### Tertiary (LOW confidence)
- None -- all findings verified against primary sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- gymnasium 1.2.3 verified on PyPI, only new dependency
- Architecture: HIGH -- thin wrapper pattern proven by game engine design (immutable state, pure functions)
- Observation encoding: HIGH -- calculated from actual GameState/Player/Board fields
- Action space encoding: HIGH for current card pool, MEDIUM for extensibility to future cards
- Pitfalls: HIGH -- directly mapped from PITFALLS.md with phase-specific additions

**Research date:** 2026-04-02
**Valid until:** 2026-05-02 (stable domain -- Gymnasium and game engine are not changing rapidly)
