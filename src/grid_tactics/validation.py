"""State invariant validation for GameState.

Validates game rules and data integrity. Returns error lists rather than
raising exceptions, allowing callers to handle violations gracefully.
Used for debugging, testing, and catching silent corruption in RL training.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from grid_tactics.types import GRID_SIZE, MAX_MANA_CAP

if TYPE_CHECKING:
    from grid_tactics.game_state import GameState


def validate_state(state: GameState) -> list[str]:
    """Validate GameState invariants.

    Returns list of error strings (empty = valid).
    Never raises exceptions -- always returns results.
    """
    errors: list[str] = []

    # Board validation: must have exactly GRID_SIZE cells
    if len(state.board.cells) != GRID_SIZE:
        errors.append(
            f"Board has {len(state.board.cells)} cells, expected {GRID_SIZE}"
        )

    # Active player index must be 0 or 1
    if state.active_player_idx not in (0, 1):
        errors.append(
            f"active_player_idx={state.active_player_idx}, must be 0 or 1"
        )

    # Turn number must be >= 1
    if state.turn_number < 1:
        errors.append(
            f"turn_number={state.turn_number}, must be >= 1"
        )

    # Player validation
    for i, player in enumerate(state.players):
        prefix = f"Player {i}"

        # Current mana must be within [0, MAX_MANA_CAP]
        if not (0 <= player.current_mana <= MAX_MANA_CAP):
            errors.append(
                f"{prefix}: current_mana={player.current_mana} "
                f"out of range [0, {MAX_MANA_CAP}]"
            )

        # Max mana must be within [0, MAX_MANA_CAP]
        if not (0 <= player.max_mana <= MAX_MANA_CAP):
            errors.append(
                f"{prefix}: max_mana={player.max_mana} "
                f"out of range [0, {MAX_MANA_CAP}]"
            )

    # Board duplicate minion check
    minion_ids = [cell for cell in state.board.cells if cell is not None]
    if len(minion_ids) != len(set(minion_ids)):
        errors.append("Duplicate minion IDs on board")

    return errors


def is_valid_state(state: GameState) -> bool:
    """Convenience: returns True if state has no validation errors."""
    return len(validate_state(state)) == 0
