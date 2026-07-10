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
from typing import Dict, Optional, Union

from grid_tactics.enums import (
    CardType,
    EffectType,
    Element,
    ReactCondition,
    TargetType,
    TriggerType,
)
from grid_tactics.types import MAX_EFFECT_AMOUNT, MAX_STAT, MIN_STAT


def is_dark_mage(card_def: "CardDefinition") -> bool:
    """THE single Dark-Mage predicate (Dark Matter pool redesign 2026-07).

    A "Dark Mage" is a MINION with the Mage tribe AND the DARK element.
    2026-07-10 (user): composite tribes COUNT — "Mage Rat" (Ratchanter)
    and "Mage Undead" (Grave Caller) are Dark Mages too. Any tribe list
    containing the word "Mage" qualifies. (Before 2026-07-10 the tribe
    had to be exactly "Mage".)

    Every card effect that targets / counts Dark Mages must route through
    this predicate rather than a bare target_tribe "Mage" filter, so the
    definition lives in exactly one place.
    """
    if card_def.card_type != CardType.MINION or card_def.element != Element.DARK:
        return False
    tribe = (card_def.tribe or "").strip().lower()
    return "mage" in tribe.split()


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
    scale_with: Optional[str] = None  # "dark_matter" / "player_dark_matter" (both read the CASTER PLAYER's Dark Matter pool — pool redesign 2026-07), "dark_mages" (grant_dark_matter only: amount × friendly Dark Mages on board), "destroyed_attack", "destroyed_attack_plus_dm" (destroyed ally's attack + caster player's DM pool)
    target_tribe: Optional[str] = None  # filter ALL_ALLIES/ALL_MINIONS to only this tribe (e.g. "Mage")
    target_element: Optional[str] = None  # filter ALL_MINIONS to only this element (e.g. "metal"); combined with target_tribe as OR
    placement_condition: Optional[str] = None  # e.g. "front_of_dark_ranged" — positional condition
    condition_multiplier: int = 1  # multiplier applied when placement_condition is met
    # Turn-structure redesign 2026-07 (spec §7.2/§11): per-card turn scoping
    # for BURN / APPLY_BURNING effects — which turns' Decay phase the applied
    # burn ticks in. Card wording decides: "during your turn" -> "owner",
    # "during your opponent's turn" -> "opponent", "every turn" -> "every".
    # None means the card carries no scoping wording; the standard Burn
    # keyword default ("owner" — spec §7.1: ticks in the minion OWNER's
    # Decay phase) is applied at burn-application time in effect_resolver.
    scope: Optional[str] = None
    # Tutor display nuance (2026-07-09): a "soft cap" tutor lets the owner
    # pick UP TO `amount` (Tree Wyrm), vs a committed tutor that reads as
    # exactly `amount` (To The Ratmobile). Purely a wording flag — the engine
    # already caps every tutor at the number of matches in deck; this only
    # drives whether the card text says "up to N".
    up_to: bool = False

    _VALID_SCOPES = ("owner", "opponent", "every")

    def __post_init__(self) -> None:
        if not (0 <= self.amount <= MAX_EFFECT_AMOUNT):
            raise ValueError(
                f"Effect amount {self.amount} out of range [0, {MAX_EFFECT_AMOUNT}]"
            )
        if self.scope is not None and self.scope not in self._VALID_SCOPES:
            raise ValueError(
                f"Effect scope '{self.scope}' invalid. "
                f"Valid: {list(self._VALID_SCOPES)} (or omit for the default)"
            )


@dataclass(frozen=True, slots=True)
class ActivatedAbility:
    """A mana-paid, turn-action ability granted by a minion's card definition.

    The minion stays on the board; activating spends the active player's
    turn action and pays the listed mana cost. Currently the only
    effect_type is "summon_token" with target "own_side_empty", but the
    schema is intentionally extensible.
    """

    name: str
    mana_cost: int
    effect_type: str
    summon_card_id: Optional[str] = None
    target: str = "own_side_empty"


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

    # Permanent numeric ID for deck codes (GT2 format). Assigned once,
    # NEVER reassigned. Default 0 = not yet assigned (tests / programmatic
    # cards without a JSON file). Real cards loaded from data/cards/ all
    # have a stable_id.
    stable_id: int = 0

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

    # Tutor mechanic (Diodebot chain).
    # Phase 14.2: Accepts EITHER a string (card_id shorthand, back-compat) OR
    # a selector dict with keys from {tribe, element, card_type}. ALL provided
    # selector keys must match (AND), case-insensitive string compare.
    tutor_target: Optional[Union[str, Dict[str, str]]] = None

    # Summoning cost: sacrifice card(s) of this tribe from hand
    discard_cost_tribe: Optional[str] = None
    discard_cost_count: int = 1

    # Transform: on-board minion can be transformed into these cards (costs mana)
    # Each entry is (card_id, mana_cost)
    transform_options: tuple[tuple[str, int], ...] = ()

    # Whether this card can be included in player decks (False = transform-only, etc.)
    deckable: bool = True

    # Flavour text for cards with no effects
    flavour_text: Optional[str] = None

    # Extra react condition: requires no friendly minions on board
    react_requires_no_friendly_minions: bool = False

    # Conjure mechanic
    summon_token_target: Optional[str] = None  # card_id to conjure
    summon_token_cost: Optional[int] = None    # mana cost for the conjure ability
    conjure_buff: Optional[str] = None         # buff type applied on conjure (e.g. 'dark_matter')

    # Cost reduction: e.g. "dark_matter" reduces mana cost by total DM stacks on board
    cost_reduction: Optional[str] = None

    # Play condition: e.g. "discarded_last_turn" — card can only be played if condition met
    play_condition: Optional[str] = None

    # Destroy-ally cost: must destroy a friendly minion on the board to play
    # this card. Named "destroy" (not "sacrifice") because the board-crossing
    # SACRIFICE action is a distinct game mechanic — see ActionType.SACRIFICE.
    destroy_ally_cost: bool = False

    # HP cost: caster takes this much damage to their own life total on play.
    # Enforced at legal_actions (caller must have hp >= hp_cost) and applied
    # inside action_resolver before effect resolution.
    hp_cost: Optional[int] = None

    # Revive mechanic: card_id of the minion to revive from grave
    revive_card_id: Optional[str] = None

    # Activated ability: spend mana + turn action to trigger an effect
    # while the minion is on the board. See ActivatedAbility.
    activated_ability: Optional[ActivatedAbility] = None

    def tutor_matches(self, candidate: "CardDefinition") -> bool:
        """Phase 14.2: True if `candidate` matches this card's tutor_target.

        - None: never matches.
        - str: exact card_id equality (back-compat).
        - dict: ALL provided keys must match (AND). Allowed keys:
          {tribe, element, card_type}. Comparisons are case-insensitive
          string compares against the candidate's stringified attribute.
          The tribe key matches against the space-split tribe WORD list
          (like _is_rat_card / discard_cost tribe matching) so composite
          tribes qualify: {"tribe": "Rat"} matches Ratchanter's
          "Mage Rat" — per To The Ratmobile's ruling.
        """
        tt = self.tutor_target
        if tt is None:
            return False
        if isinstance(tt, str):
            return candidate.card_id == tt
        if isinstance(tt, dict):
            for key, expected in tt.items():
                if key == "tribe":
                    # Composite tribes ("Mage Rat", "Archer Undead")
                    # match on any whole word, consistent with every
                    # other tribe-filtered system in the engine.
                    if candidate.tribe is None:
                        return False
                    tribe_words = [
                        w.lower() for w in str(candidate.tribe).split()
                    ]
                    if str(expected).lower() not in tribe_words:
                        return False
                    continue
                elif key == "element":
                    actual = candidate.element.name if candidate.element is not None else None
                elif key == "card_type":
                    actual = candidate.card_type.name if candidate.card_type is not None else None
                else:
                    raise ValueError(
                        f"Card '{self.card_id}': unknown tutor_target selector key '{key}'"
                    )
                if actual is None:
                    return False
                if str(actual).lower() != str(expected).lower():
                    return False
            return True
        return False

    @property
    def is_multi_purpose(self) -> bool:
        """True if this card can be deployed OR used as react from hand (D-06)."""
        return self.react_effect is not None and self.react_mana_cost is not None

    def __post_init__(self) -> None:
        """Validate card definition invariants at construction time."""
        # mana_cost range — 0 allowed for free spells
        if not (0 <= self.mana_cost <= MAX_STAT):
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

            # Stat range validation (D-19): health in [MIN_STAT, MAX_STAT];
            # attack in [0, MAX_STAT] -- 0 is a legal "cannot attack" card
            # (e.g. Emberplague Rat) gated by the effective-attack rule in
            # legal_actions. Buffs can give such a minion temporary teeth.
            if not (MIN_STAT <= self.health <= MAX_STAT):  # type: ignore[operator]
                raise ValueError(
                    f"Card '{self.card_id}': health={self.health} "
                    f"out of range [{MIN_STAT}, {MAX_STAT}]"
                )
            if not (0 <= self.attack <= MAX_STAT):  # type: ignore[operator]
                raise ValueError(
                    f"Card '{self.card_id}': attack={self.attack} "
                    f"out of range [0, {MAX_STAT}]"
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
                and not (self.card_type == CardType.MINION and self.react_effect is not None)
                and not (self.card_type == CardType.MAGIC and self.react_mana_cost is not None)):
            raise ValueError(
                f"Card '{self.card_id}': Only REACT cards and multi-purpose cards "
                f"can have react_condition"
            )

        # Multi-purpose consistency (D-06, D-07)
        # Minion multi-purpose: react_effect and react_mana_cost must both be set
        # Magic+react: react_mana_cost without react_effect is allowed (uses effects array)
        if (self.react_effect is None) != (self.react_mana_cost is None):
            is_magic_react = (self.card_type == CardType.MAGIC
                              and self.react_mana_cost is not None
                              and self.react_condition is not None)
            if not is_magic_react:
                raise ValueError(
                    f"Card '{self.card_id}': react_effect and react_mana_cost "
                    f"must both be set or both be None"
                )

        # Only minions or magic cards can carry a distinct react_effect (D-06).
        # React cards already use their effects array for react resolution.
        if (
            self.react_effect is not None
            and self.card_type not in (CardType.MINION, CardType.MAGIC)
        ):
            raise ValueError(
                f"Card '{self.card_id}': Only minions or magic cards can carry "
                f"a distinct react_effect"
            )

        # react_mana_cost range (D-19) — 0 allowed for free react abilities
        if self.react_mana_cost is not None and not (
            0 <= self.react_mana_cost <= MAX_STAT
        ):
            raise ValueError(
                f"Card '{self.card_id}': react_mana_cost={self.react_mana_cost} "
                f"out of range [{MIN_STAT}, {MAX_STAT}]"
            )
