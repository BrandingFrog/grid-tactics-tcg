"""Observation encoder -- converts GameState to a fixed-size numpy array.

Encodes the game state from a specific player's perspective into a flat
1D float32 array of size 292. All values normalized to [-1.0, 1.0].

Sections:
  - Board state (250): 25 cells x 10 features per cell
  - My hand (20): up to 10 cards x 2 features each
  - My resources (5): mana, max_mana, hp, deck_size, graveyard_size
  - Opponent visible (4): hp, mana, hand_size, deck_size (NO hand contents)
  - Game context (3): turn_number, is_action_phase, am_i_active
  - React context (10): in_react_window, stack_depth, 8 reserved
"""

from __future__ import annotations

import numpy as np

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import PlayerSide, TriggerType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.types import (
    DEFAULT_TURN_LIMIT,
    GRID_COLS,
    GRID_ROWS,
    MAX_MANA_CAP,
    MAX_REACT_STACK_DEPTH,
    MAX_STAT,
    MIN_DECK_SIZE,
    STARTING_HP,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_HAND_SIZE: int = 10
FEATURES_PER_CELL: int = 10
HAND_FEATURES: int = 2
OBSERVATION_SIZE: int = 292

OBSERVATION_SPEC: dict = {
    "board": {"offset": 0, "size": 250, "description": "5x5 grid, 10 features per cell"},
    "my_hand": {"offset": 250, "size": 20, "description": "Up to 10 cards, 2 features each"},
    "my_resources": {"offset": 270, "size": 5, "description": "mana, max_mana, hp, deck_size, graveyard_size"},
    "opponent_visible": {"offset": 275, "size": 4, "description": "opponent hp, mana, hand_size, deck_size"},
    "game_context": {"offset": 279, "size": 3, "description": "turn_number, is_action_phase, am_i_active"},
    "react_context": {"offset": 282, "size": 10, "description": "in_react_window, react_stack_depth, 8 reserved"},
}


def encode_observation(
    state: GameState,
    library: CardLibrary,
    observer_idx: int,
) -> np.ndarray:
    """Encode game state into a fixed-size observation vector.

    The observation is perspective-relative: the observer's own resources
    appear in the MY_RESOURCES section, opponent's in OPPONENT_VISIBLE.
    Board minion ownership is encoded relative to observer (+1=mine, -1=opponent).

    Hidden information (opponent hand card IDs, deck contents) is never included.

    Args:
        state: Current game state.
        library: CardLibrary for card definition lookups.
        observer_idx: 0 or 1, which player is observing.

    Returns:
        np.ndarray of shape (OBSERVATION_SIZE,) with dtype float32,
        all values in [-1.0, 1.0].
    """
    obs = np.zeros(OBSERVATION_SIZE, dtype=np.float32)
    observer_side = PlayerSide(observer_idx)
    me = state.players[observer_idx]
    opponent = state.players[1 - observer_idx]

    # ---- Board encoding: 25 cells x 10 features ----
    _encode_board(obs, state, library, observer_side)

    # ---- My hand: up to MAX_HAND_SIZE cards x 2 features ----
    _encode_hand(obs, me, library)

    # ---- My resources: 5 features ----
    offset = OBSERVATION_SPEC["my_resources"]["offset"]
    obs[offset + 0] = me.current_mana / MAX_MANA_CAP
    obs[offset + 1] = me.max_mana / MAX_MANA_CAP
    obs[offset + 2] = me.hp / STARTING_HP
    obs[offset + 3] = len(me.deck) / MIN_DECK_SIZE
    obs[offset + 4] = len(me.graveyard) / MIN_DECK_SIZE

    # ---- Opponent visible: 4 features (NO hand contents per D-02) ----
    offset = OBSERVATION_SPEC["opponent_visible"]["offset"]
    obs[offset + 0] = opponent.hp / STARTING_HP
    obs[offset + 1] = opponent.current_mana / MAX_MANA_CAP
    obs[offset + 2] = len(opponent.hand) / MAX_HAND_SIZE
    obs[offset + 3] = len(opponent.deck) / MIN_DECK_SIZE

    # ---- Game context: 3 features ----
    offset = OBSERVATION_SPEC["game_context"]["offset"]
    obs[offset + 0] = state.turn_number / DEFAULT_TURN_LIMIT
    obs[offset + 1] = 1.0 if state.phase == TurnPhase.ACTION else 0.0

    # am_i_active: depends on phase
    if state.phase == TurnPhase.ACTION:
        obs[offset + 2] = 1.0 if state.active_player_idx == observer_idx else 0.0
    elif state.phase == TurnPhase.REACT:
        obs[offset + 2] = 1.0 if state.react_player_idx == observer_idx else 0.0
    else:
        obs[offset + 2] = 0.0

    # ---- React context: 10 features (2 used, 8 reserved) ----
    offset = OBSERVATION_SPEC["react_context"]["offset"]
    obs[offset + 0] = 1.0 if state.phase == TurnPhase.REACT else 0.0
    obs[offset + 1] = len(state.react_stack) / MAX_REACT_STACK_DEPTH
    # obs[offset + 2:offset + 10] remain 0.0 (reserved)

    return obs


def _encode_board(
    obs: np.ndarray,
    state: GameState,
    library: CardLibrary,
    observer_side: PlayerSide,
) -> None:
    """Encode the 5x5 board into the observation vector (in-place).

    Per cell (10 features):
      [0] is_occupied: 1.0 if minion present, 0.0 if empty
      [1] owner: +1.0 = mine, -1.0 = opponent, 0.0 = empty
      [2] attack / MAX_STAT
      [3] current_health / MAX_STAT
      [4] attack_range / 2.0
      [5] attack_bonus / MAX_STAT
      [6] card_type (reserved, always 0.0 for minions on board)
      [7] attribute / 3.0
      [8] has_on_death_effect: 1.0 if card has ON_DEATH trigger
      [9] has_on_damaged_effect: 1.0 if card has ON_DAMAGED trigger
    """
    # Build a lookup of minion by position for O(1) access
    minion_by_pos: dict[tuple[int, int], object] = {}
    for m in state.minions:
        minion_by_pos[m.position] = m

    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            cell_idx = row * GRID_COLS + col
            base = cell_idx * FEATURES_PER_CELL

            minion = minion_by_pos.get((row, col))
            if minion is None:
                # Empty cell -- all zeros (already initialized)
                continue

            card_def = library.get_by_id(minion.card_numeric_id)

            obs[base + 0] = 1.0  # is_occupied
            obs[base + 1] = 1.0 if minion.owner == observer_side else -1.0  # owner
            obs[base + 2] = card_def.attack / MAX_STAT  # attack
            obs[base + 3] = minion.current_health / MAX_STAT  # health
            obs[base + 4] = card_def.attack_range / 2.0  # attack_range
            obs[base + 5] = minion.attack_bonus / MAX_STAT  # attack_bonus
            obs[base + 6] = 0.0  # card_type (reserved)

            # Attribute: encode as value / 3.0 (Attribute enum 0-3)
            if card_def.attribute is not None:
                obs[base + 7] = card_def.attribute.value / 3.0
            # else remains 0.0

            # Effect triggers
            has_on_death = any(e.trigger == TriggerType.ON_DEATH for e in card_def.effects)
            has_on_damaged = any(e.trigger == TriggerType.ON_DAMAGED for e in card_def.effects)
            obs[base + 8] = 1.0 if has_on_death else 0.0
            obs[base + 9] = 1.0 if has_on_damaged else 0.0


def _encode_hand(
    obs: np.ndarray,
    player,
    library: CardLibrary,
) -> None:
    """Encode the observer's hand cards into the observation vector (in-place).

    Per card slot (2 features):
      [0] is_present: 1.0 if card exists, 0.0 if empty slot
      [1] mana_cost / MAX_STAT

    Truncates to MAX_HAND_SIZE if hand exceeds 10 cards.
    """
    offset = OBSERVATION_SPEC["my_hand"]["offset"]
    hand = player.hand
    n_cards = min(len(hand), MAX_HAND_SIZE)

    for i in range(n_cards):
        card_def = library.get_by_id(hand[i])
        slot_base = offset + i * HAND_FEATURES
        obs[slot_base + 0] = 1.0  # is_present
        obs[slot_base + 1] = card_def.mana_cost / MAX_STAT  # mana_cost normalized
    # Remaining slots stay 0.0 (already initialized)
