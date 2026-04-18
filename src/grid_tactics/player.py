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
    grave: tuple[int, ...]
    # Phase 14.5: cards removed from hand as a COST (e.g. discard_cost_tribe
    # discard) go here instead of grave. Exhaust is shown in a separate pile
    # in the UI and is NOT considered "played" for card-effect purposes.
    exhaust: tuple[int, ...] = ()
    discarded_this_turn: bool = False
    discarded_last_turn: bool = False

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
            grave=(),
            exhaust=(),
        )

    # -- Phase 14.5: hand removal without grave side-effect ------------

    def remove_from_hand(self, card_id: int) -> Player:
        """Remove a card from hand WITHOUT adding to any pile.

        Used by the minion PLAY_CARD path — deployed minions live on the board
        and only enter the grave if/when they die (gated on from_deck).
        Magic/react one-shots continue to use ``discard_from_hand`` which does
        route to grave.
        """
        if card_id not in self.hand:
            raise ValueError(f"Card {card_id} not in hand: {self.hand}")
        hand_list = list(self.hand)
        hand_list.remove(card_id)
        return replace(self, hand=tuple(hand_list))

    def exhaust_from_hand(self, card_id: int) -> Player:
        """Move a card from hand to exhaust pile (discard-for-cost).

        Also sets discarded_this_turn=True for play-condition tracking.
        """
        if card_id not in self.hand:
            raise ValueError(f"Card {card_id} not in hand: {self.hand}")
        hand_list = list(self.hand)
        hand_list.remove(card_id)
        return replace(
            self,
            hand=tuple(hand_list),
            exhaust=self.exhaust + (card_id,),
            discarded_this_turn=True,
        )

    # -- Mana operations ----------------------------------------------------

    def regenerate_mana(self) -> Player:
        """Regenerate mana per turn.

        Banking pool design (D-08):
          new_current = min(current + MANA_REGEN_PER_TURN, MAX_MANA_CAP)

        Mana is a single banking pool — unspent mana carries over and the pool
        grows by +1 each turn. Cap (D-07): never exceeds MAX_MANA_CAP.
        """
        new_current = min(self.current_mana + MANA_REGEN_PER_TURN, MAX_MANA_CAP)
        return replace(self, current_mana=new_current)

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
        """Move a card from hand to grave. Raises if card not in hand."""
        if card_id not in self.hand:
            raise ValueError(f"Card {card_id} not in hand: {self.hand}")
        hand_list = list(self.hand)
        hand_list.remove(card_id)
        return replace(
            self,
            hand=tuple(hand_list),
            grave=self.grave + (card_id,),
        )

    def add_to_grave(self, card_id: int) -> Player:
        """Append a card id to the grave. Used when a board minion dies or is
        destroyed (e.g. Feed the Shadow's destroy_ally_cost) — the card's
        numeric id is recorded in the owner's graveyard."""
        return replace(self, grave=self.grave + (card_id,))

    # -- HP / damage --------------------------------------------------------

    def take_damage(self, amount: int) -> Player:
        """Take damage. HP can go below 0."""
        return replace(self, hp=self.hp - amount)

    @property
    def is_alive(self) -> bool:
        """Player is alive if HP > 0."""
        return self.hp > 0
