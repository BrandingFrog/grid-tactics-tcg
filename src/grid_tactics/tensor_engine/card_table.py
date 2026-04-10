"""CardTable -- GPU-resident lookup table for card definitions.

Loads all card definitions from CardLibrary into fixed-size tensors.
Adding a new card = adding a row to each tensor (zero code changes).
"""

from __future__ import annotations

import torch

from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import CardType, EffectType
from grid_tactics.tensor_engine.constants import (
    GRID_COLS,
    GRID_ROWS,
    GRID_SIZE,
    MAX_EFFECTS_PER_CARD,
)


class CardTable:
    """Static card property lookup table on GPU.

    All tensors indexed by card_numeric_id (0..num_cards-1).
    """

    def __init__(
        self,
        card_type: torch.Tensor,
        mana_cost: torch.Tensor,
        attack: torch.Tensor,
        health: torch.Tensor,
        attack_range: torch.Tensor,
        element: torch.Tensor,
        effect_type: torch.Tensor,
        effect_trigger: torch.Tensor,
        effect_target: torch.Tensor,
        effect_amount: torch.Tensor,
        num_effects: torch.Tensor,
        react_condition: torch.Tensor,
        is_react_eligible: torch.Tensor,
        react_mana_cost: torch.Tensor,
        is_multi_purpose: torch.Tensor,
        react_effect_type: torch.Tensor,
        react_effect_target: torch.Tensor,
        react_effect_amount: torch.Tensor,
        adjacency: torch.Tensor,
        distance_manhattan: torch.Tensor,
        distance_chebyshev: torch.Tensor,
        is_orthogonal: torch.Tensor,
        promote_target_id: torch.Tensor,
        is_unique: torch.Tensor,
        tutor_target_id: torch.Tensor,
        tutor_has_target: torch.Tensor,
        tutor_selector_tribe_id: torch.Tensor,
        tutor_selector_element: torch.Tensor,
        tutor_selector_card_type: torch.Tensor,
        tribe_id: torch.Tensor,
        summon_sacrifice_tribe_id: torch.Tensor,
        leap_amount: torch.Tensor,
        passive_burn_amount: torch.Tensor,
        passive_heal_amount: torch.Tensor,
        is_rat: torch.Tensor,
        ratchanter_card_id: int,
        rat_card_id: int,
        _num_cards: int,
        device: torch.device,
    ):
        self.card_type = card_type
        self.mana_cost = mana_cost
        self.attack = attack
        self.health = health
        self.attack_range = attack_range
        self.element = element
        self.effect_type = effect_type
        self.effect_trigger = effect_trigger
        self.effect_target = effect_target
        self.effect_amount = effect_amount
        self.num_effects = num_effects
        self.react_condition = react_condition
        self.is_react_eligible = is_react_eligible
        self.react_mana_cost = react_mana_cost
        self.is_multi_purpose = is_multi_purpose
        self.react_effect_type = react_effect_type
        self.react_effect_target = react_effect_target
        self.react_effect_amount = react_effect_amount
        self.adjacency = adjacency
        self.distance_manhattan = distance_manhattan
        self.distance_chebyshev = distance_chebyshev
        self.is_orthogonal = is_orthogonal
        self.promote_target_id = promote_target_id  # [num_cards] int32, -1 if no promote
        self.is_unique = is_unique                  # [num_cards] bool
        self.tutor_target_id = tutor_target_id      # [num_cards] int32, -1 if no string target
        # Phase 14.2: tutor selector dict columns. tutor_has_target[i] is True
        # if card i has any tutor_target (string OR dict). The selector columns
        # are -1 for "any" (not constrained on this attribute) and a value for
        # an AND-constraint. String-form tutor uses tutor_target_id only and
        # leaves selectors as -1.
        self.tutor_has_target = tutor_has_target              # [num_cards] bool
        self.tutor_selector_tribe_id = tutor_selector_tribe_id  # [num_cards] int32, -1 = any
        self.tutor_selector_element = tutor_selector_element    # [num_cards] int32, -1 = any
        self.tutor_selector_card_type = tutor_selector_card_type  # [num_cards] int32, -1 = any
        self.tribe_id = tribe_id                    # [num_cards] int32, 0 if no tribe
        self.summon_sacrifice_tribe_id = summon_sacrifice_tribe_id  # [num_cards] int32, 0 if none
        # Audit-followup: precomputed per-card effect amounts for fast lookup
        # without re-scanning effect_type[i, j]. Zero means the card lacks the
        # effect. Used by LEAP move enumeration and the PASSIVE pipeline.
        self.leap_amount = leap_amount                        # [num_cards] int32
        self.passive_burn_amount = passive_burn_amount        # [num_cards] int32
        self.passive_heal_amount = passive_heal_amount        # [num_cards] int32
        # ACTIVATE_ABILITY parity (hardcoded for Ratchanter — only card with
        # an activated ability today). is_rat marks any card matching the
        # Python `_is_rat_card` rule (card_id 'rat' OR tribe contains 'Rat').
        # ratchanter_card_id / rat_card_id are -1 if the library lacks them.
        # TODO: when a second activated-ability card lands, generalise to a
        # per-card `activated_ability_effect_type` column and a real dispatch.
        self.is_rat = is_rat                                  # [num_cards] bool
        self.ratchanter_card_id = ratchanter_card_id          # int (-1 if absent)
        self.rat_card_id = rat_card_id                        # int (-1 if absent)
        self._num_cards = _num_cards
        self.device = device

    @property
    def num_cards(self) -> int:
        return self._num_cards

    @classmethod
    def from_library(cls, library: CardLibrary, device: torch.device) -> CardTable:
        """Build GPU lookup tables from a CardLibrary."""
        n = library.card_count

        # Allocate CPU tensors
        card_type = torch.zeros(n, dtype=torch.int32)
        mana_cost = torch.zeros(n, dtype=torch.int32)
        attack = torch.zeros(n, dtype=torch.int32)
        health = torch.zeros(n, dtype=torch.int32)
        attack_range = torch.zeros(n, dtype=torch.int32)
        element = torch.zeros(n, dtype=torch.int32)
        effect_type = torch.full((n, MAX_EFFECTS_PER_CARD), -1, dtype=torch.int32)
        effect_trigger = torch.full((n, MAX_EFFECTS_PER_CARD), -1, dtype=torch.int32)
        effect_target = torch.full((n, MAX_EFFECTS_PER_CARD), -1, dtype=torch.int32)
        effect_amount = torch.zeros((n, MAX_EFFECTS_PER_CARD), dtype=torch.int32)
        num_effects = torch.zeros(n, dtype=torch.int32)
        react_condition = torch.full((n,), -1, dtype=torch.int32)
        is_react_eligible = torch.zeros(n, dtype=torch.bool)
        react_mana_cost = torch.zeros(n, dtype=torch.int32)
        is_multi_purpose = torch.zeros(n, dtype=torch.bool)
        react_effect_type = torch.full((n,), -1, dtype=torch.int32)
        react_effect_target = torch.full((n,), -1, dtype=torch.int32)
        react_effect_amount = torch.zeros(n, dtype=torch.int32)
        promote_target_id = torch.full((n,), -1, dtype=torch.int32)
        is_unique = torch.zeros(n, dtype=torch.bool)
        tutor_target_id = torch.full((n,), -1, dtype=torch.int32)
        tutor_has_target = torch.zeros(n, dtype=torch.bool)
        tutor_selector_tribe_id = torch.full((n,), -1, dtype=torch.int32)
        tutor_selector_element = torch.full((n,), -1, dtype=torch.int32)
        tutor_selector_card_type = torch.full((n,), -1, dtype=torch.int32)
        tribe_id = torch.zeros(n, dtype=torch.int32)
        summon_sacrifice_tribe_id = torch.zeros(n, dtype=torch.int32)
        leap_amount = torch.zeros(n, dtype=torch.int32)
        passive_burn_amount = torch.zeros(n, dtype=torch.int32)
        passive_heal_amount = torch.zeros(n, dtype=torch.int32)
        is_rat = torch.zeros(n, dtype=torch.bool)

        # Build tribe string -> int mapping
        tribe_map: dict[str, int] = {}
        next_tribe_id = 1
        for i in range(n):
            card = library.get_by_id(i)
            if card.tribe and card.tribe not in tribe_map:
                tribe_map[card.tribe] = next_tribe_id
                next_tribe_id += 1

        for i in range(n):
            card = library.get_by_id(i)
            card_type[i] = card.card_type.value
            mana_cost[i] = card.mana_cost
            attack[i] = card.attack if card.attack is not None else 0
            health[i] = card.health if card.health is not None else 0
            attack_range[i] = card.attack_range if card.attack_range is not None else 0
            element[i] = card.element.value if card.element is not None else 0

            for j, eff in enumerate(card.effects[:MAX_EFFECTS_PER_CARD]):
                effect_type[i, j] = eff.effect_type.value
                effect_trigger[i, j] = eff.trigger.value
                effect_target[i, j] = eff.target.value
                effect_amount[i, j] = eff.amount
            num_effects[i] = len(card.effects)

            # Audit-followup: precompute LEAP / PASSIVE amounts so the move
            # enumerator and the PASSIVE pipeline don't need to re-scan
            # effect rows on every step. Mirrors Python engine semantics:
            #   - LEAP: ON_MOVE trigger ignored, only the amount matters;
            #     legal_actions checks `EffectType.LEAP in card.effects`.
            #   - BURN (passive aura): amount controls stacks-per-tick.
            #   - PASSIVE_HEAL: amount controls heal-per-tick.
            # If a card has multiple matching effects we take the max,
            # matching the Python `max(leap_amount, eff.amount or 1)` rule.
            for eff in card.effects:
                if eff.effect_type == EffectType.LEAP:
                    leap_amount[i] = max(int(leap_amount[i].item()), eff.amount or 1)
                elif eff.effect_type == EffectType.BURN:
                    passive_burn_amount[i] = max(
                        int(passive_burn_amount[i].item()), eff.amount or 1
                    )
                elif eff.effect_type == EffectType.PASSIVE_HEAL:
                    passive_heal_amount[i] = max(
                        int(passive_heal_amount[i].item()), eff.amount or 1
                    )

            if card.react_condition is not None:
                react_condition[i] = card.react_condition.value

            if card.card_type == CardType.REACT or card.is_multi_purpose:
                is_react_eligible[i] = True

            # Promote / unique
            if card.promote_target is not None:
                try:
                    promote_target_id[i] = library.get_numeric_id(card.promote_target)
                except KeyError:
                    pass  # promote target card not in library
            is_unique[i] = card.unique

            # Tutor target (Phase 14.2: string OR dict selector)
            tt = card.tutor_target
            if tt is not None:
                if isinstance(tt, str):
                    try:
                        tutor_target_id[i] = library.get_numeric_id(tt)
                        tutor_has_target[i] = True
                    except KeyError:
                        pass  # tutor target card not in library
                elif isinstance(tt, dict):
                    tutor_has_target[i] = True
                    # Resolve selector keys to integer ids/values for GPU matching
                    if "tribe" in tt:
                        # Case-insensitive tribe lookup against tribe_map
                        want = str(tt["tribe"]).lower()
                        match_id = -1
                        for tname, tid in tribe_map.items():
                            if tname.lower() == want:
                                match_id = tid
                                break
                        # If unknown tribe (no card has it), match_id stays -1
                        # which will produce zero matches at runtime — same as
                        # the Python engine semantics ("no candidate matches").
                        # Use a sentinel that can never equal a real tribe_id
                        # (>= 1) by storing -2 to disambiguate from "any".
                        tutor_selector_tribe_id[i] = match_id if match_id > 0 else -2
                    if "element" in tt:
                        # Element enum: match by name (case-insensitive)
                        from grid_tactics.enums import Element
                        want = str(tt["element"]).lower()
                        match_val = -2
                        for e in Element:
                            if e.name.lower() == want:
                                match_val = e.value
                                break
                        tutor_selector_element[i] = match_val
                    if "card_type" in tt:
                        from grid_tactics.enums import CardType as _CT
                        want = str(tt["card_type"]).lower()
                        match_val = -2
                        for ct_e in _CT:
                            if ct_e.name.lower() == want:
                                match_val = ct_e.value
                                break
                        tutor_selector_card_type[i] = match_val

            # Tribe
            if card.tribe:
                tribe_id[i] = tribe_map[card.tribe]

            # Mirror Python `_is_rat_card`: card_id 'rat' OR tribe contains
            # 'Rat' (case-insensitive, handles composite 'Mage/Rat').
            if card.card_id == "rat":
                is_rat[i] = True
            elif card.tribe:
                parts = [p.strip().lower() for p in card.tribe.split()]
                if "rat" in parts:
                    is_rat[i] = True

            # Summon sacrifice tribe
            if card.summon_sacrifice_tribe:
                tid = tribe_map.get(card.summon_sacrifice_tribe, 0)
                summon_sacrifice_tribe_id[i] = tid

            if card.card_type == CardType.REACT:
                react_mana_cost[i] = card.mana_cost
            elif card.is_multi_purpose:
                react_mana_cost[i] = card.react_mana_cost
                is_multi_purpose[i] = True
                if card.react_effect is not None:
                    react_effect_type[i] = card.react_effect.effect_type.value
                    react_effect_target[i] = card.react_effect.target.value
                    react_effect_amount[i] = card.react_effect.amount

        # Precompute grid geometry
        adjacency = cls._build_adjacency()
        distance_manhattan = cls._build_manhattan()
        distance_chebyshev = cls._build_chebyshev()
        is_ortho = cls._build_orthogonal()

        # Resolve hardcoded card IDs for ACTIVATE_ABILITY dispatch
        try:
            ratchanter_card_id = library.get_numeric_id("ratchanter")
        except KeyError:
            ratchanter_card_id = -1
        try:
            rat_card_id = library.get_numeric_id("rat")
        except KeyError:
            rat_card_id = -1

        return cls(
            card_type=card_type.to(device),
            mana_cost=mana_cost.to(device),
            attack=attack.to(device),
            health=health.to(device),
            attack_range=attack_range.to(device),
            element=element.to(device),
            effect_type=effect_type.to(device),
            effect_trigger=effect_trigger.to(device),
            effect_target=effect_target.to(device),
            effect_amount=effect_amount.to(device),
            num_effects=num_effects.to(device),
            react_condition=react_condition.to(device),
            is_react_eligible=is_react_eligible.to(device),
            react_mana_cost=react_mana_cost.to(device),
            is_multi_purpose=is_multi_purpose.to(device),
            react_effect_type=react_effect_type.to(device),
            react_effect_target=react_effect_target.to(device),
            react_effect_amount=react_effect_amount.to(device),
            adjacency=adjacency.to(device),
            distance_manhattan=distance_manhattan.to(device),
            distance_chebyshev=distance_chebyshev.to(device),
            is_orthogonal=is_ortho.to(device),
            promote_target_id=promote_target_id.to(device),
            is_unique=is_unique.to(device),
            tutor_target_id=tutor_target_id.to(device),
            tutor_has_target=tutor_has_target.to(device),
            tutor_selector_tribe_id=tutor_selector_tribe_id.to(device),
            tutor_selector_element=tutor_selector_element.to(device),
            tutor_selector_card_type=tutor_selector_card_type.to(device),
            tribe_id=tribe_id.to(device),
            summon_sacrifice_tribe_id=summon_sacrifice_tribe_id.to(device),
            leap_amount=leap_amount.to(device),
            passive_burn_amount=passive_burn_amount.to(device),
            passive_heal_amount=passive_heal_amount.to(device),
            is_rat=is_rat.to(device),
            ratchanter_card_id=ratchanter_card_id,
            rat_card_id=rat_card_id,
            _num_cards=n,
            device=device,
        )

    @staticmethod
    def _build_adjacency() -> torch.Tensor:
        """Build [25, 8, 2] adjacency tensor (ortho + diagonal), -1 padded."""
        adj = torch.full((GRID_SIZE, 8, 2), -1, dtype=torch.int32)
        for flat in range(GRID_SIZE):
            r, c = flat // GRID_COLS, flat % GRID_COLS
            neighbors = []
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1),
                           (-1, -1), (-1, 1), (1, -1), (1, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < GRID_ROWS and 0 <= nc < GRID_COLS:
                    neighbors.append((nr, nc))
            for i, (nr, nc) in enumerate(neighbors):
                adj[flat, i, 0] = nr
                adj[flat, i, 1] = nc
        return adj

    @staticmethod
    def _build_manhattan() -> torch.Tensor:
        """Build [25, 25] pairwise Manhattan distance."""
        dist = torch.zeros(GRID_SIZE, GRID_SIZE, dtype=torch.int32)
        for a in range(GRID_SIZE):
            ar, ac = a // GRID_COLS, a % GRID_COLS
            for b in range(GRID_SIZE):
                br, bc = b // GRID_COLS, b % GRID_COLS
                dist[a, b] = abs(ar - br) + abs(ac - bc)
        return dist

    @staticmethod
    def _build_chebyshev() -> torch.Tensor:
        """Build [25, 25] pairwise Chebyshev distance."""
        dist = torch.zeros(GRID_SIZE, GRID_SIZE, dtype=torch.int32)
        for a in range(GRID_SIZE):
            ar, ac = a // GRID_COLS, a % GRID_COLS
            for b in range(GRID_SIZE):
                br, bc = b // GRID_COLS, b % GRID_COLS
                dist[a, b] = max(abs(ar - br), abs(ac - bc))
        return dist

    @staticmethod
    def _build_orthogonal() -> torch.Tensor:
        """Build [25, 25] orthogonal mask (same row or col)."""
        ortho = torch.zeros(GRID_SIZE, GRID_SIZE, dtype=torch.bool)
        for a in range(GRID_SIZE):
            ar, ac = a // GRID_COLS, a % GRID_COLS
            for b in range(GRID_SIZE):
                br, bc = b // GRID_COLS, b % GRID_COLS
                ortho[a, b] = (ar == br) or (ac == bc)
        return ortho
