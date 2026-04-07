"""Action space encoder -- maps between Action objects and integer IDs.

Provides deterministic, invertible mapping for all 7 action types to/from
a flat Discrete(1262) integer space for MaskablePPO compatibility.

Encoding scheme (position-based, not minion-ID-based):
  Section            Base    Encoding                          Count
  -----------------------------------------------------------------------
  PLAY_CARD          0       hand(10) * grid(25) + cell(25)    250
  MOVE               250     source(25) * dir(4)               100
  ATTACK             350     source(25) * target(25)           625
  SACRIFICE          975     source(25)                        25
  DRAW               1000    (no params)                       1
  PASS               1001    (no params)                       1
  PLAY_REACT         1002    hand(10) * tgt_or_none(26)        260
  -----------------------------------------------------------------------
  TOTAL                                                        1262
"""

from __future__ import annotations

import numpy as np

from grid_tactics.actions import (
    Action,
    attack_action,
    decline_post_move_attack_action,
    decline_tutor_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
    sacrifice_action,
    tutor_select_action,
)
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, CardType, TargetType, TriggerType
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.types import GRID_COLS, GRID_SIZE

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_HAND_SIZE: int = 10

PLAY_CARD_BASE: int = 0       # 250 slots: hand(10) * grid(25)
MOVE_BASE: int = 250           # 100 slots: source(25) * dir(4)
ATTACK_BASE: int = 350         # 625 slots: source(25) * target(25)
SACRIFICE_BASE: int = 975      # 25 slots: source(25)
DRAW_IDX: int = 1000           # 1 slot
PASS_IDX: int = 1001           # 1 slot
REACT_BASE: int = 1002         # 260 slots: hand(10) * target_or_none(26)

ACTION_SPACE_SIZE: int = 1262

# Direction mapping: (dr, dc) -> int
DIRECTION_MAP: dict[tuple[int, int], int] = {
    (-1, 0): 0,  # up
    (1, 0): 1,   # down
    (0, -1): 2,  # left
    (0, 1): 3,   # right
}
DIRECTION_REVERSE: dict[int, tuple[int, int]] = {v: k for k, v in DIRECTION_MAP.items()}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pos_to_flat(pos: tuple[int, int]) -> int:
    """Convert (row, col) to flat index (row-major)."""
    return pos[0] * GRID_COLS + pos[1]


def flat_to_pos(flat: int) -> tuple[int, int]:
    """Convert flat index to (row, col)."""
    return (flat // GRID_COLS, flat % GRID_COLS)


# ---------------------------------------------------------------------------
# ActionEncoder
# ---------------------------------------------------------------------------


class ActionEncoder:
    """Encode/decode between Action objects and integer action IDs.

    All encoding uses board positions (not minion IDs) for stable mapping.
    """

    def encode(self, action: Action, state: GameState) -> int:
        """Encode an Action into an integer in [0, ACTION_SPACE_SIZE).

        Args:
            action: The Action to encode.
            state: Current game state (needed to look up minion positions).

        Returns:
            Integer action ID.
        """
        atype = action.action_type

        # Phase 14.1: DECLINE_POST_MOVE_ATTACK reuses slot 1001 (PASS).
        # Disambiguated at decode time by state.pending_post_move_attacker_id.
        if atype == ActionType.DECLINE_POST_MOVE_ATTACK:
            return PASS_IDX

        # Phase 14.2: DECLINE_TUTOR reuses slot 1001 (PASS).
        # Disambiguated at decode time by state.pending_tutor_player_idx.
        if atype == ActionType.DECLINE_TUTOR:
            return PASS_IDX

        # Phase 14.2: TUTOR_SELECT reuses the PLAY_CARD slot space [0:250].
        # The match index lives on Action.card_index. We pin cell=0 so the
        # decoded slot is PLAY_CARD_BASE + match_idx * GRID_SIZE.
        if atype == ActionType.TUTOR_SELECT:
            match_idx = action.card_index if action.card_index is not None else 0
            return PLAY_CARD_BASE + match_idx * GRID_SIZE

        if atype == ActionType.PASS:
            return PASS_IDX

        if atype == ActionType.DRAW:
            return DRAW_IDX

        if atype == ActionType.PLAY_CARD:
            return self._encode_play_card(action, state)

        if atype == ActionType.MOVE:
            return self._encode_move(action, state)

        if atype == ActionType.ATTACK:
            return self._encode_attack(action, state)

        if atype == ActionType.SACRIFICE:
            return self._encode_sacrifice(action, state)

        if atype == ActionType.PLAY_REACT:
            return self._encode_play_react(action)

        raise ValueError(f"Unknown action type: {atype}")

    def decode(
        self,
        action_int: int,
        state: GameState,
        library: CardLibrary | None,
    ) -> Action:
        """Decode an integer action ID back to an Action object.

        Args:
            action_int: Integer in [0, ACTION_SPACE_SIZE).
            state: Current game state (needed to look up minions at positions).
            library: CardLibrary for card type lookups (needed for PLAY_CARD).

        Returns:
            Action object.
        """
        if action_int == PASS_IDX:
            # Phase 14.2: slot 1001 reinterpreted as DECLINE_TUTOR while a
            # tutor pick is pending. Checked first because pending_tutor and
            # pending_post_move_attacker are mutually exclusive.
            if state.pending_tutor_player_idx is not None:
                return decline_tutor_action()
            # Phase 14.1: slot 1001 reinterpreted as DECLINE_POST_MOVE_ATTACK
            # while a post-move attack is pending.
            if state.pending_post_move_attacker_id is not None:
                return decline_post_move_attack_action()
            return pass_action()

        # Phase 14.2: PLAY_CARD slot space reinterpreted as TUTOR_SELECT while
        # a tutor pick is pending. The slot's hand_idx field carries the match
        # index (cell sub-index is ignored / always 0 on encode).
        if (
            state.pending_tutor_player_idx is not None
            and PLAY_CARD_BASE <= action_int < MOVE_BASE
        ):
            match_idx = (action_int - PLAY_CARD_BASE) // GRID_SIZE
            return tutor_select_action(match_index=match_idx)

        if action_int == DRAW_IDX:
            return draw_action()

        if PLAY_CARD_BASE <= action_int < MOVE_BASE:
            return self._decode_play_card(action_int, state, library)

        if MOVE_BASE <= action_int < ATTACK_BASE:
            return self._decode_move(action_int, state)

        if ATTACK_BASE <= action_int < SACRIFICE_BASE:
            return self._decode_attack(action_int, state)

        if SACRIFICE_BASE <= action_int < DRAW_IDX:
            return self._decode_sacrifice(action_int, state)

        if REACT_BASE <= action_int < REACT_BASE + MAX_HAND_SIZE * 26:
            return self._decode_play_react(action_int)

        raise ValueError(f"Action int {action_int} out of range [0, {ACTION_SPACE_SIZE})")

    # ----- PLAY_CARD encoding -----

    def _encode_play_card(self, action: Action, state: GameState) -> int:
        """Encode PLAY_CARD action.

        For minion deploy: cell = deploy position.
        For targeted magic: cell = target position.
        For untargeted magic: cell = 0.
        """
        hand_idx = action.card_index

        if action.position is not None:
            # Minion deploy (position = deploy location)
            cell = pos_to_flat(action.position)
        elif action.target_pos is not None:
            # Targeted magic (target_pos = target location)
            cell = pos_to_flat(action.target_pos)
        else:
            # Untargeted magic
            cell = 0

        return PLAY_CARD_BASE + hand_idx * GRID_SIZE + cell

    def _decode_play_card(
        self,
        action_int: int,
        state: GameState,
        library: CardLibrary | None,
    ) -> Action:
        """Decode PLAY_CARD action integer."""
        idx = action_int - PLAY_CARD_BASE
        hand_idx = idx // GRID_SIZE
        cell_flat = idx % GRID_SIZE
        cell_pos = flat_to_pos(cell_flat)

        if library is None:
            # Without library, can't determine card type
            # Return generic play_card with position
            return play_card_action(card_index=hand_idx, position=cell_pos)

        # Determine card type from active player's hand
        active = state.active_player
        if hand_idx < len(active.hand):
            card_numeric_id = active.hand[hand_idx]
            card_def = library.get_by_id(card_numeric_id)

            if card_def.card_type == CardType.MINION:
                # Minion deploy: cell is deploy position
                return play_card_action(card_index=hand_idx, position=cell_pos)
            elif card_def.card_type == CardType.MAGIC:
                # Check if targeted
                has_single_target = any(
                    e.trigger == TriggerType.ON_PLAY and e.target == TargetType.SINGLE_TARGET
                    for e in card_def.effects
                )
                if has_single_target:
                    return play_card_action(card_index=hand_idx, target_pos=cell_pos)
                else:
                    # Untargeted magic
                    return play_card_action(card_index=hand_idx)

        # Fallback
        return play_card_action(card_index=hand_idx, position=cell_pos)

    # ----- MOVE encoding -----

    def _encode_move(self, action: Action, state: GameState) -> int:
        """Encode MOVE action. Computes direction from minion's current position."""
        minion = state.get_minion(action.minion_id)
        if minion is None:
            raise ValueError(f"Minion {action.minion_id} not found in state")

        source_flat = pos_to_flat(minion.position)

        # Compute direction from source to destination
        dest = action.position
        dr = dest[0] - minion.position[0]
        dc = dest[1] - minion.position[1]
        direction = DIRECTION_MAP[(dr, dc)]

        return MOVE_BASE + source_flat * 4 + direction

    def _decode_move(self, action_int: int, state: GameState) -> Action:
        """Decode MOVE action integer."""
        idx = action_int - MOVE_BASE
        source_flat = idx // 4
        direction = idx % 4
        source_pos = flat_to_pos(source_flat)

        # Find minion at source position
        minion_id = self._find_minion_at(state, source_pos)

        # Compute destination
        dr, dc = DIRECTION_REVERSE[direction]
        dest = (source_pos[0] + dr, source_pos[1] + dc)

        return move_action(minion_id=minion_id, position=dest)

    # ----- ATTACK encoding -----

    def _encode_attack(self, action: Action, state: GameState) -> int:
        """Encode ATTACK action using attacker and target positions."""
        attacker = state.get_minion(action.minion_id)
        defender = state.get_minion(action.target_id)
        if attacker is None:
            raise ValueError(f"Attacker minion {action.minion_id} not found")
        if defender is None:
            raise ValueError(f"Defender minion {action.target_id} not found")

        source_flat = pos_to_flat(attacker.position)
        target_flat = pos_to_flat(defender.position)

        return ATTACK_BASE + source_flat * GRID_SIZE + target_flat

    def _decode_attack(self, action_int: int, state: GameState) -> Action:
        """Decode ATTACK action integer."""
        idx = action_int - ATTACK_BASE
        source_flat = idx // GRID_SIZE
        target_flat = idx % GRID_SIZE
        source_pos = flat_to_pos(source_flat)
        target_pos = flat_to_pos(target_flat)

        attacker_id = self._find_minion_at(state, source_pos)
        defender_id = self._find_minion_at(state, target_pos)

        return attack_action(minion_id=attacker_id, target_id=defender_id)

    # ----- SACRIFICE encoding -----

    def _encode_sacrifice(self, action: Action, state: GameState) -> int:
        """Encode SACRIFICE action using minion's position."""
        minion = state.get_minion(action.minion_id)
        if minion is None:
            raise ValueError(f"Minion {action.minion_id} not found for sacrifice")

        source_flat = pos_to_flat(minion.position)
        return SACRIFICE_BASE + source_flat

    def _decode_sacrifice(self, action_int: int, state: GameState) -> Action:
        """Decode SACRIFICE action integer."""
        source_flat = action_int - SACRIFICE_BASE
        source_pos = flat_to_pos(source_flat)

        minion_id = self._find_minion_at(state, source_pos)
        return sacrifice_action(minion_id=minion_id)

    # ----- PLAY_REACT encoding -----

    def _encode_play_react(self, action: Action) -> int:
        """Encode PLAY_REACT action."""
        hand_idx = action.card_index

        if action.target_pos is not None:
            target = pos_to_flat(action.target_pos)
        else:
            target = 25  # Untargeted sentinel value

        return REACT_BASE + hand_idx * 26 + target

    def _decode_play_react(self, action_int: int) -> Action:
        """Decode PLAY_REACT action integer."""
        idx = action_int - REACT_BASE
        hand_idx = idx // 26
        target = idx % 26

        if target < 25:
            target_pos = flat_to_pos(target)
        else:
            target_pos = None

        return play_react_action(card_index=hand_idx, target_pos=target_pos)

    # ----- Helpers -----

    @staticmethod
    def _find_minion_at(state: GameState, pos: tuple[int, int]) -> int:
        """Find the minion instance_id at the given board position."""
        for m in state.minions:
            if m.position == pos:
                return m.instance_id
        raise ValueError(f"No minion at position {pos}")


# ---------------------------------------------------------------------------
# Action mask builder
# ---------------------------------------------------------------------------


def build_action_mask(
    state: GameState,
    library: CardLibrary,
    encoder: ActionEncoder,
) -> np.ndarray:
    """Build a binary action mask from legal actions.

    Returns a boolean array of shape (ACTION_SPACE_SIZE,) where True
    indicates a legal action. Uses legal_actions() as the single source
    of truth -- never recomputes legality.

    Args:
        state: Current game state.
        library: CardLibrary for card lookups.
        encoder: ActionEncoder to map actions to integers.

    Returns:
        np.ndarray of shape (ACTION_SPACE_SIZE,) with dtype np.bool_.
    """
    mask = np.zeros(ACTION_SPACE_SIZE, dtype=np.bool_)
    actions = legal_actions(state, library)

    for action in actions:
        idx = encoder.encode(action, state)
        if 0 <= idx < ACTION_SPACE_SIZE:
            mask[idx] = True
        # Skip actions that encode out of bounds (e.g. hand_idx > MAX_HAND_SIZE)

    # Ensure at least PASS is always legal (fallback safety)
    if not mask.any():
        mask[PASS_IDX] = True

    return mask
