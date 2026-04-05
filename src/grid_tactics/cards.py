"""Card data model -- frozen dataclasses for card definitions.

EffectDefinition: A single declarative effect on a card (per D-04).
CardDefinition: Immutable card template loaded from JSON (per D-01, D-14, D-15).

Cards exist at two levels:
  - CardDefinition (this module): static templates, shared across all games.
  - Card instances (Phase 3): runtime copies with mutable health/state.

This module defines ONLY card definitions. Runtime instances and game
actions are Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from grid_tactics.enums import (
    CardType,
    EffectType,
    Element,
    ReactCondition,
    TargetType,
    TriggerType,
)
from grid_tactics.types import MAX_EFFECT_AMOUNT, MAX_STAT, MIN_STAT


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    """A single declarative effect on a card (per D-04).

    Effects are pure data -- the resolution engine that interprets them
    lives in Phase 3's ActionResolver.
    """

    effect_type: EffectType
    trigger: TriggerType
    target: TargetType
    amount: int

    def __post_init__(self) -> None:
        if not (1 <= self.amount <= MAX_EFFECT_AMOUNT):
            raise ValueError(
                f"Effect amount {self.amount} out of range [1, {MAX_EFFECT_AMOUNT}]"
            )


@dataclass(frozen=True, slots=True)
class CardDefinition:
    """Immutable card template. NOT a runtime instance (per D-01, D-14, D-15).

    Minion cards require attack, health, attack_range.
    Magic/React cards must NOT have attack/health.
    Multi-purpose cards (D-06): minion with react_effect + react_mana_cost.
    """

    card_id: str
    name: str
    card_type: CardType
    mana_cost: int

    # Minion-specific (None for Magic/React)
    attack: Optional[int] = None
    health: Optional[int] = None
    attack_range: Optional[int] = None  # named attack_range to avoid shadowing builtin range()

    # Element/tribes (D-09, D-10)
    element: Optional[Element] = None
    tribe: Optional[str] = None

    # Effects list (D-01 through D-05)
    effects: tuple[EffectDefinition, ...] = ()

    # React condition -- what opponent action triggers this react (required for REACT cards)
    react_condition: Optional[ReactCondition] = None

    # Multi-purpose react from hand (D-06, D-07, D-08)
    react_effect: Optional[EffectDefinition] = None
    react_mana_cost: Optional[int] = None

    # Promote mechanic (Patch 1.2)
    promote_target: Optional[str] = None  # card_id of the minion type that can be promoted into this
    unique: bool = False  # only 1 can exist on board per player at a time

    # Tutor mechanic (Diodebot chain)
    tutor_target: Optional[str] = None  # card_id to search deck for and add to hand

    # Summoning cost: sacrifice a card of this tribe from hand
    summon_sacrifice_tribe: Optional[str] = None

    # Transform: on-board minion can be transformed into these cards (costs mana)
    # Each entry is (card_id, mana_cost)
    transform_options: tuple[tuple[str, int], ...] = ()

    # Whether this card can be included in player decks (False = transform-only, etc.)
    deckable: bool = True

    # Flavour text for cards with no effects
    flavour_text: Optional[str] = None

    @property
    def is_multi_purpose(self) -> bool:
        """True if this card can be deployed OR used as react from hand (D-06)."""
        return self.react_effect is not None and self.react_mana_cost is not None

    def __post_init__(self) -> None:
        """Validate card definition invariants at construction time."""
        # mana_cost range (D-19)
        if not (MIN_STAT <= self.mana_cost <= MAX_STAT):
            raise ValueError(
                f"Card '{self.card_id}': mana_cost={self.mana_cost} "
                f"out of range [{MIN_STAT}, {MAX_STAT}]"
            )

        if self.card_type == CardType.MINION:
            # Minion required fields (ENG-05)
            for field_name, value in [
                ("attack", self.attack),
                ("health", self.health),
                ("attack_range", self.attack_range),
            ]:
                if value is None:
                    raise ValueError(
                        f"Card '{self.card_id}': Minion must have {field_name}"
                    )

            # Stat range validation (D-19) for attack, health
            for field_name, value in [
                ("attack", self.attack),
                ("health", self.health),
            ]:
                if not (MIN_STAT <= value <= MAX_STAT):  # type: ignore[operator]
                    raise ValueError(
                        f"Card '{self.card_id}': {field_name}={value} "
                        f"out of range [{MIN_STAT}, {MAX_STAT}]"
                    )

            # Range is 0+ (melee=0, ranged=1+), no upper bound enforced yet
            if self.attack_range < 0:  # type: ignore[operator]
                raise ValueError(
                    f"Card '{self.card_id}': attack_range cannot be negative"
                )
        else:
            # Non-minions must NOT have minion-specific fields (clean separation)
            if self.attack is not None or self.health is not None:
                raise ValueError(
                    f"Card '{self.card_id}': Non-minion cards cannot have attack/health"
                )

        # React cards must have a react_condition
        if self.card_type == CardType.REACT and self.react_condition is None:
            raise ValueError(
                f"Card '{self.card_id}': REACT cards must have a react_condition"
            )

        # Non-react cards without multi-purpose shouldn't have react_condition
        # (multi-purpose minions CAN have react_condition for their react mode)
        if (self.react_condition is not None
                and self.card_type != CardType.REACT
                and not (self.card_type == CardType.MINION and self.react_effect is not None)):
            raise ValueError(
                f"Card '{self.card_id}': Only REACT cards and multi-purpose minions "
                f"can have react_condition"
            )

        # Multi-purpose consistency (D-06, D-07)
        if (self.react_effect is None) != (self.react_mana_cost is None):
            raise ValueError(
                f"Card '{self.card_id}': react_effect and react_mana_cost "
                f"must both be set or both be None"
            )

        # Only minions can be multi-purpose (D-06)
        if self.react_effect is not None and self.card_type != CardType.MINION:
            raise ValueError(
                f"Card '{self.card_id}': Only minions can be multi-purpose"
            )

        # react_mana_cost range (D-19)
        if self.react_mana_cost is not None and not (
            MIN_STAT <= self.react_mana_cost <= MAX_STAT
        ):
            raise ValueError(
                f"Card '{self.card_id}': react_mana_cost={self.react_mana_cost} "
                f"out of range [{MIN_STAT}, {MAX_STAT}]"
            )
