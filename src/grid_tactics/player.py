"""Player state -- immutable dataclass with mana, HP, and hand management.

All operations return new Player instances (frozen dataclass).
Mana system implements decisions D-05 through D-08:
  D-05: Starting mana = 1
  D-06: Mana regen = +1 per turn
  D-07: Max mana cap = 10
  D-08: Unspent mana carries over (banking)
Player HP per D-09: starting HP = 20.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from grid_tactics.enums import PlayerSide
from grid_tactics.types import (
    MAX_MANA_CAP,
    MANA_REGEN_PER_TURN,
    STARTING_HP,
    STARTING_MANA,
)


@dataclass(frozen=True, slots=True)
class Player:
    """Immutable player state. All operations return new Player instances."""

    side: PlayerSide
    hp: int
    current_mana: int
    max_mana: int
    hand: tuple[int, ...]
    deck: tuple[int, ...]
    graveyard: tuple[int, ...]

    # -- Construction -------------------------------------------------------

    @classmethod
    def new(cls, side: PlayerSide, deck: tuple[int, ...]) -> Player:
        """Create a starting player per D-05, D-09."""
        return cls(
            side=side,
            hp=STARTING_HP,
            current_mana=STARTING_MANA,
            max_mana=STARTING_MANA,
            hand=(),
            deck=deck,
            graveyard=(),
        )

    # -- Mana operations ----------------------------------------------------

    def regenerate_mana(self) -> Player:
        """Regenerate mana per turn.

        Both current and max grow by +1 per turn (capped at MAX_MANA_CAP).
        Max grows so the display "X/Y" reflects the player's max capacity.
        Current grows so unspent mana banks (D-08).
        Cap (D-07): never exceeds MAX_MANA_CAP.
        """
        new_max = min(self.max_mana + MANA_REGEN_PER_TURN, MAX_MANA_CAP)
        new_current = min(self.current_mana + MANA_REGEN_PER_TURN, MAX_MANA_CAP)
        return replace(self, current_mana=new_current, max_mana=new_max)

    def spend_mana(self, cost: int) -> Player:
        """Spend mana. Raises ValueError if insufficient or negative."""
        if cost < 0:
            raise ValueError(f"Cannot spend negative mana: {cost}")
        if self.current_mana < cost:
            raise ValueError(
                f"Insufficient mana: have {self.current_mana}, need {cost}"
            )
        return replace(self, current_mana=self.current_mana - cost)

    # -- Hand management ----------------------------------------------------

    def draw_card(self) -> tuple[Player, int]:
        """Draw top card from deck to hand. Returns (new_player, card_id)."""
        if not self.deck:
            raise ValueError("Cannot draw from empty deck")
        card_id = self.deck[0]
        return (
            replace(
                self,
                hand=self.hand + (card_id,),
                deck=self.deck[1:],
            ),
            card_id,
        )

    def discard_from_hand(self, card_id: int) -> Player:
        """Move a card from hand to graveyard. Raises if card not in hand."""
        if card_id not in self.hand:
            raise ValueError(f"Card {card_id} not in hand: {self.hand}")
        hand_list = list(self.hand)
        hand_list.remove(card_id)
        return replace(
            self,
            hand=tuple(hand_list),
            graveyard=self.graveyard + (card_id,),
        )

    # -- HP / damage --------------------------------------------------------

    def take_damage(self, amount: int) -> Player:
        """Take damage. HP can go below 0."""
        return replace(self, hp=self.hp - amount)

    @property
    def is_alive(self) -> bool:
        """Player is alive if HP > 0."""
        return self.hp > 0
