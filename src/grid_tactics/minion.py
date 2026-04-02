"""MinionInstance -- runtime minion on the board.

A MinionInstance is a runtime copy of a card deployed to the field.
It tracks current_health (which decreases from damage) separate from
the CardDefinition's base health. The instance_id matches the value
stored in Board.cells for cross-referencing.

CardDefinition (Phase 2) = static template, shared across games.
MinionInstance (this module) = runtime copy with mutable state (via replace).
"""

from __future__ import annotations

from dataclasses import dataclass

from grid_tactics.enums import PlayerSide


@dataclass(frozen=True, slots=True)
class MinionInstance:
    """Immutable runtime minion on the board.

    All state changes produce new instances via dataclasses.replace().
    """

    instance_id: int             # unique per game, matches Board.cells value
    card_numeric_id: int         # index into CardLibrary for definition lookup
    owner: PlayerSide            # who controls this minion
    position: tuple[int, int]    # (row, col) on board
    current_health: int          # starts at CardDefinition.health, decreases from damage
    attack_bonus: int = 0        # cumulative attack buff (effective attack = card_def.attack + attack_bonus)

    @property
    def is_alive(self) -> bool:
        """Minion is alive if current_health > 0."""
        return self.current_health > 0
