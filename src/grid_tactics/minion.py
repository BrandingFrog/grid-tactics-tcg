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

# Damage dealt to a burning minion when its burn ticks. Turn-structure
# redesign 2026-07: the tick fires in the DECAY phase (end of turn) of the
# minion OWNER's turn by default (see MinionInstance.burn_scope), moved
# from the old start-of-turn tick. Same once-per-round rate, just moved.
# Burn is a non-stacking BOOLEAN status: a minion is either burning or not.
# Re-applying burn to an already-burning minion is a no-op (no refresh,
# no stacks). Burn persists until the minion dies (no cleanse exists yet).
BURN_DAMAGE = 5

# Valid values for MinionInstance.burn_scope — which turns' Decay phase
# the burn ticks in. Card wording decides ("during your turn" / "during
# your opponent's turn" restrict; no wording = every turn).
BURN_SCOPE_OWNER = "owner"        # ticks only in the owner's Decay phase (default)
BURN_SCOPE_OPPONENT = "opponent"  # ticks only in the opponent's Decay phase
BURN_SCOPE_EVERY = "every"        # ticks in EVERY Decay phase (both players' turns)

# Backwards-compat alias kept for any external imports; new code should use
# BURN_DAMAGE. Will be removed in a future cleanup pass.
BURN_DPT = BURN_DAMAGE


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
    is_burning: bool = False     # Boolean burn status. Tick fires for BURN_DAMAGE in the Decay phase (end of turn) per burn_scope. Persists until death.
    dark_matter_stacks: int = 0  # Dark Matter counters on this minion. Granted by grant_dark_matter effects (Shady Trade Deal, Dark Matter Stash, Illicit Shadow Stones, Feed the Shadow, Matter of Time, Dark Matter Barrage); consumed by Ratchanter/Grave Caller DM-scaled buffs and by cost_reduction="dark_matter" (Erebus), which sums stacks across all your minions.
    max_health_bonus: int = 0    # Cumulative max-HP buff. Effective max HP = card_def.health + max_health_bonus. Heals cap at the effective max. Added on top of current_health when the buff is applied so it is immediately usable.
    from_deck: bool = True       # True for minions that originated from a deck card (PLAY_CARD or Conjure). False only for tokens spawned by activated abilities (summon_token). Death cleanup adds card to owner's grave only when from_deck=True; tokens vanish silently.
    # Appended field (keep at end — positional construction stability).
    burn_scope: str = "owner"    # Which turns' Decay phase the burn ticks in: "owner" (default) | "opponent" | "every". Card wording decides.

    @property
    def is_alive(self) -> bool:
        """Minion is alive if current_health > 0."""
        return self.current_health > 0
