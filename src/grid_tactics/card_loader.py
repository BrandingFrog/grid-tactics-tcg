"""Card loader -- reads per-card JSON files into CardDefinition frozen dataclasses.

Validates required fields exist and converts string enum values to IntEnum.
Raises ValueError with clear messages for invalid/missing data at load time,
not at play time (per D-14, D-15).
"""

from __future__ import annotations

import json
from pathlib import Path

from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.enums import (
    CardType,
    EffectType,
    Element,
    ReactCondition,
    TargetType,
    TriggerType,
)


class CardLoader:
    """Loads per-card JSON files into CardDefinition frozen dataclasses (per D-14, D-15)."""

    _REQUIRED_FIELDS = ("card_id", "name", "card_type")

    @staticmethod
    def load_card(path: Path) -> CardDefinition:
        """Load a single card definition from a JSON file.

        Validates required fields exist and converts string enum values to IntEnum.
        Raises ValueError with clear messages for invalid/missing data.
        """
        with open(path, "r", encoding="utf-8") as f:
            data: dict = json.load(f)

        # Validate required fields
        for field in CardLoader._REQUIRED_FIELDS:
            if field not in data:
                raise ValueError(
                    f"Card in '{path.name}': Missing required field '{field}'"
                )

        card_id = data["card_id"]

        # Parse card_type enum
        card_type = CardLoader._parse_enum(
            CardType, data["card_type"], "card_type", card_id
        )

        # Parse effects list
        effects = CardLoader._parse_effects(data.get("effects", []), card_id)

        # Parse optional react_effect
        react_effect = None
        react_data = data.get("react_effect")
        if react_data:
            react_effect = CardLoader._parse_single_effect(react_data, card_id, "react_effect")

        # Parse optional element
        element = None
        elem_str = data.get("element")
        if elem_str is not None:
            element = CardLoader._parse_enum(
                Element, elem_str, "element", card_id
            )

        # Parse optional react_condition
        react_condition = None
        react_cond_str = data.get("react_condition")
        if react_cond_str is not None:
            react_condition = CardLoader._parse_enum(
                ReactCondition, react_cond_str, "react_condition", card_id
            )

        # Construct CardDefinition -- __post_init__ validates invariants
        return CardDefinition(
            card_id=card_id,
            name=data["name"],
            card_type=card_type,
            mana_cost=data.get("mana_cost", 0),
            attack=data.get("attack"),
            health=data.get("health"),
            attack_range=data.get("range"),  # JSON "range" -> CardDefinition "attack_range"
            element=element,
            tribe=data.get("tribe"),
            effects=effects,
            react_condition=react_condition,
            react_effect=react_effect,
            react_mana_cost=data.get("react_mana_cost"),
            promote_target=data.get("promote_target"),
            unique=data.get("unique", False),
            tutor_target=data.get("tutor_target"),
            summon_sacrifice_tribe=data.get("summon_sacrifice_tribe"),
            transform_options=CardLoader._parse_transform_options(data, card_id),
            deckable=data.get("deckable", True),
            flavour_text=data.get("flavour_text"),
            react_requires_no_friendly_minions=data.get("react_requires_no_friendly_minions", False),
        )

    @staticmethod
    def _parse_enum(enum_cls: type, value: str, field_name: str, card_id: str):
        """Parse a string value into an IntEnum member (case-insensitive)."""
        try:
            return enum_cls[value.upper()]
        except KeyError:
            valid = list(enum_cls.__members__.keys())
            raise ValueError(
                f"Card '{card_id}': Invalid {field_name} '{value}'. "
                f"Valid: {valid}"
            )

    @staticmethod
    def _parse_effects(
        effects_data: list[dict], card_id: str
    ) -> tuple[EffectDefinition, ...]:
        """Parse a list of effect dicts into a tuple of EffectDefinition."""
        return tuple(
            CardLoader._parse_single_effect(e, card_id, f"effects[{i}]")
            for i, e in enumerate(effects_data)
        )

    @staticmethod
    def _parse_single_effect(
        data: dict, card_id: str, context: str
    ) -> EffectDefinition:
        """Parse a single effect dict into an EffectDefinition."""
        try:
            effect_type = CardLoader._parse_enum(
                EffectType, data["type"], f"{context} effect type", card_id
            )
        except ValueError:
            raise ValueError(
                f"Card '{card_id}': Invalid effect type '{data.get('type')}' "
                f"in {context}. Valid: {list(EffectType.__members__.keys())}"
            )

        trigger = CardLoader._parse_enum(
            TriggerType, data["trigger"], f"{context} trigger", card_id
        )
        target = CardLoader._parse_enum(
            TargetType, data["target"], f"{context} target", card_id
        )

        return EffectDefinition(
            effect_type=effect_type,
            trigger=trigger,
            target=target,
            amount=data["amount"],
        )

    @staticmethod
    def _parse_transform_options(
        data: dict, card_id: str,
    ) -> tuple[tuple[str, int], ...]:
        """Parse transform_options list from JSON."""
        raw = data.get("transform_options")
        if not raw:
            return ()
        return tuple(
            (opt["target"], opt["mana_cost"])
            for opt in raw
        )
