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
    MAX_HAND_SIZE,
    ACTION_POINTS_PER_TURN,
    MAX_ACTION_POINTS,
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
    # Dark Matter pool redesign 2026-07 (appended field — keep at end for
    # positional-construction stability). Dark Matter is a PLAYER-level
    # stacking resource: grant_dark_matter effects add here, scale_with
    # "dark_matter" / "player_dark_matter" effects and Erebus'
    # cost_reduction read from here. Minions NEVER hold DM (the old
    # MinionInstance.dark_matter_stacks field is deprecated, always 0).
    # PUBLIC information — both players see both pools.
    dark_matter: int = 0
    # Set when this player opens a tutor this turn (effect_resolver
    # _enter_pending_tutor). Read by ReactCondition.OPPONENT_TUTORS so a
    # react like Tree Wyrm can answer the opponent's tutor. Reset for the
    # player STARTING their turn (react_stack turn flip). Appended field —
    # keep at end for positional-construction stability. (2026-07-09)
    tutored_this_turn: bool = False
    # Public, banked primary-action currency (active rules v5). Appended for
    # positional-construction and legacy-save stability.
    action_points: int = 1

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

    def regenerate_mana(self, amount: int = MANA_REGEN_PER_TURN) -> Player:
        """Regenerate mana per turn.

        Banking pool design (D-08):
          new_current = min(current + amount, MAX_MANA_CAP)

        Mana is a single banking pool — unspent mana carries over and the pool
        grows by +1 each turn. Cap (D-07): never exceeds MAX_MANA_CAP.
        """
        if amount < 0:
            raise ValueError(f"Cannot regenerate negative mana: {amount}")
        new_current = min(self.current_mana + amount, MAX_MANA_CAP)
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

    def gain_action_points(self, amount: int = ACTION_POINTS_PER_TURN) -> Player:
        """Bank action points up to the hard cap."""
        if amount < 0:
            raise ValueError(f"Cannot gain negative action points: {amount}")
        return replace(
            self,
            action_points=min(MAX_ACTION_POINTS, self.action_points + amount),
        )

    def spend_action_point(self) -> Player:
        """Spend one primary-action point."""
        if self.action_points <= 0:
            raise ValueError("No action points remaining")
        return replace(self, action_points=self.action_points - 1)

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

    def draw_card_with_overdraw(self) -> tuple[Player, int, bool]:
        """Draw the top deck card with overdraw-burn semantics.

        Turn-structure redesign 2026-07: if the hand is already at
        MAX_HAND_SIZE, the drawn card is BURNED — it goes to the exhaust
        pile (revealed) instead of the hand. It does NOT fizzle back into
        the deck. Used by ALL draw paths (turn-start draw, DRAW card
        effects, Handshake draw).

        Returns (new_player, card_id, burned). Raises if the deck is empty
        (callers handle empty-deck fatigue / no-op themselves).

        Note: unlike ``exhaust_from_hand`` this does NOT set
        ``discarded_this_turn`` — an overdraw burn is not a discard cost.
        """
        if not self.deck:
            raise ValueError("Cannot draw from empty deck")
        card_id = self.deck[0]
        if len(self.hand) >= MAX_HAND_SIZE:
            return (
                replace(
                    self,
                    deck=self.deck[1:],
                    exhaust=self.exhaust + (card_id,),
                ),
                card_id,
                True,
            )
        return (
            replace(
                self,
                hand=self.hand + (card_id,),
                deck=self.deck[1:],
            ),
            card_id,
            False,
        )

    def add_to_hand_with_overdraw(self, card_id: int) -> tuple[Player, bool]:
        """Add a card (from any source: tutor, conjure, decline-conjure)
        to hand with overdraw-burn semantics.

        Full hand (MAX_HAND_SIZE) → the card goes to the exhaust pile
        (revealed) instead. Returns (new_player, burned).
        """
        if len(self.hand) >= MAX_HAND_SIZE:
            return (
                replace(self, exhaust=self.exhaust + (card_id,)),
                True,
            )
        return (replace(self, hand=self.hand + (card_id,)), False)

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

    # -- Dark Matter pool ----------------------------------------------------

    def gain_dark_matter(self, amount: int) -> Player:
        """Add Dark Matter stacks to this player's pool.

        Dark Matter pool redesign 2026-07: DM is a player resource. There
        is no cap and no decay; the pool only grows (nothing currently
        spends it — Erebus' cost_reduction READS it without consuming).
        Negative amounts are rejected — no effect removes DM today.
        """
        if amount < 0:
            raise ValueError(f"Cannot gain negative Dark Matter: {amount}")
        return replace(self, dark_matter=self.dark_matter + amount)

    # -- HP / damage --------------------------------------------------------

    def take_damage(self, amount: int) -> Player:
        """Take damage. HP can go below 0."""
        return replace(self, hp=self.hp - amount)

    @property
    def is_alive(self) -> bool:
        """Player is alive if HP > 0."""
        return self.hp > 0
