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

# Damage Per Tick for the burning status. Future statuses follow the
# `<STATUS>_DPT` naming pattern (e.g. POISON_DPT) so the tick architecture
# stays uniform across status effects.
BURN_DPT = 1


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
    burning_stacks: int = 0      # Phase 14.3: status effect — ticks at end of turn for BURN_DPT * stacks damage, decrements by 1

    @property
    def is_alive(self) -> bool:
        """Minion is alive if current_health > 0."""
        return self.current_health > 0
