"""Tests for CardLoader -- JSON file to CardDefinition conversion.

Covers: valid loading for all card types, validation error messages,
edge cases (no effects, no attribute, multi-purpose cards).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_tactics.card_loader import CardLoader
from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.enums import (
    Attribute,
    CardType,
    EffectType,
    TargetType,
    TriggerType,
)


# ---------------------------------------------------------------------------
# Fixtures: reusable card JSON dicts
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_minion_json() -> dict:
    """A valid minion card JSON dict."""
    return {
        "card_id": "test_minion",
        "name": "Test Minion",
        "card_type": "minion",
        "mana_cost": 2,
        "attack": 3,
        "health": 2,
        "range": 1,
        "attribute": "fire",
        "tribe": "Imp",
        "effects": [
            {
                "type": "damage",
                "trigger": "on_play",
                "target": "single_target",
                "amount": 1,
            }
        ],
    }


@pytest.fixture
def valid_magic_json() -> dict:
    """A valid magic card JSON dict."""
    return {
        "card_id": "test_magic",
        "name": "Test Magic",
        "card_type": "magic",
        "mana_cost": 3,
        "attribute": "fire",
        "effects": [
            {
                "type": "damage",
                "trigger": "on_play",
                "target": "single_target",
                "amount": 4,
            }
        ],
    }


@pytest.fixture
def valid_react_json() -> dict:
    """A valid react card JSON dict."""
    return {
        "card_id": "test_react",
        "name": "Test React",
        "card_type": "react",
        "mana_cost": 1,
        "attribute": "light",
        "react_condition": "any_action",
        "effects": [
            {
                "type": "buff_health",
                "trigger": "on_play",
                "target": "single_target",
                "amount": 2,
            }
        ],
    }


@pytest.fixture
def valid_multi_purpose_json() -> dict:
    """A valid multi-purpose minion card JSON dict."""
    return {
        "card_id": "test_multi",
        "name": "Test Multi",
        "card_type": "minion",
        "mana_cost": 3,
        "attack": 2,
        "health": 3,
        "range": 0,
        "attribute": "dark",
        "tribe": "Dark Mage",
        "effects": [],
        "react_effect": {
            "type": "damage",
            "trigger": "on_play",
            "target": "single_target",
            "amount": 2,
        },
        "react_mana_cost": 2,
    }


def _write_card_json(tmp_path: Path, data: dict, filename: str = "card.json") -> Path:
    """Helper to write a card dict as JSON to a temp file."""
    filepath = tmp_path / filename
    filepath.write_text(json.dumps(data), encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Test: Valid card loading
# ---------------------------------------------------------------------------


class TestLoadValidCards:
    """CardLoader.load_card loads valid JSON into correct CardDefinition."""

    def test_load_minion(self, tmp_path: Path, valid_minion_json: dict) -> None:
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)

        assert isinstance(card, CardDefinition)
        assert card.card_id == "test_minion"
        assert card.name == "Test Minion"
        assert card.card_type == CardType.MINION
        assert card.mana_cost == 2
        assert card.attack == 3
        assert card.health == 2
        assert card.attack_range == 1
        assert card.attribute == Attribute.FIRE
        assert card.tribe == "Imp"
        assert len(card.effects) == 1
        assert card.effects[0].effect_type == EffectType.DAMAGE
        assert card.effects[0].trigger == TriggerType.ON_PLAY
        assert card.effects[0].target == TargetType.SINGLE_TARGET
        assert card.effects[0].amount == 1

    def test_load_magic(self, tmp_path: Path, valid_magic_json: dict) -> None:
        path = _write_card_json(tmp_path, valid_magic_json)
        card = CardLoader.load_card(path)

        assert card.card_id == "test_magic"
        assert card.card_type == CardType.MAGIC
        assert card.mana_cost == 3
        assert card.attack is None
        assert card.health is None
        assert card.attack_range is None
        assert card.attribute == Attribute.FIRE
        assert len(card.effects) == 1
        assert card.effects[0].amount == 4

    def test_load_react(self, tmp_path: Path, valid_react_json: dict) -> None:
        path = _write_card_json(tmp_path, valid_react_json)
        card = CardLoader.load_card(path)

        assert card.card_id == "test_react"
        assert card.card_type == CardType.REACT
        assert card.mana_cost == 1
        assert card.attribute == Attribute.LIGHT
        assert len(card.effects) == 1
        assert card.effects[0].effect_type == EffectType.BUFF_HEALTH

    def test_load_multi_purpose(
        self, tmp_path: Path, valid_multi_purpose_json: dict
    ) -> None:
        path = _write_card_json(tmp_path, valid_multi_purpose_json)
        card = CardLoader.load_card(path)

        assert card.card_id == "test_multi"
        assert card.card_type == CardType.MINION
        assert card.is_multi_purpose is True
        assert card.react_effect is not None
        assert card.react_effect.effect_type == EffectType.DAMAGE
        assert card.react_effect.amount == 2
        assert card.react_mana_cost == 2
        assert len(card.effects) == 0


# ---------------------------------------------------------------------------
# Test: Validation errors
# ---------------------------------------------------------------------------


class TestLoaderValidation:
    """CardLoader raises ValueError for invalid/missing data."""

    def test_missing_card_id(self, tmp_path: Path, valid_minion_json: dict) -> None:
        del valid_minion_json["card_id"]
        path = _write_card_json(tmp_path, valid_minion_json)
        with pytest.raises(ValueError, match="card_id"):
            CardLoader.load_card(path)

    def test_missing_name(self, tmp_path: Path, valid_minion_json: dict) -> None:
        del valid_minion_json["name"]
        path = _write_card_json(tmp_path, valid_minion_json)
        with pytest.raises(ValueError, match="name"):
            CardLoader.load_card(path)

    def test_missing_card_type(self, tmp_path: Path, valid_minion_json: dict) -> None:
        del valid_minion_json["card_type"]
        path = _write_card_json(tmp_path, valid_minion_json)
        with pytest.raises(ValueError, match="card_type"):
            CardLoader.load_card(path)

    def test_invalid_card_type(self, tmp_path: Path, valid_minion_json: dict) -> None:
        valid_minion_json["card_type"] = "artifact"
        path = _write_card_json(tmp_path, valid_minion_json)
        with pytest.raises(ValueError, match="card_type.*artifact"):
            CardLoader.load_card(path)

    def test_invalid_effect_type(self, tmp_path: Path, valid_minion_json: dict) -> None:
        valid_minion_json["effects"][0]["type"] = "explode"
        path = _write_card_json(tmp_path, valid_minion_json)
        with pytest.raises(ValueError, match="effect.*type.*explode"):
            CardLoader.load_card(path)

    def test_invalid_attribute(self, tmp_path: Path, valid_minion_json: dict) -> None:
        valid_minion_json["attribute"] = "ice"
        path = _write_card_json(tmp_path, valid_minion_json)
        with pytest.raises(ValueError, match="attribute.*ice"):
            CardLoader.load_card(path)


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------


class TestLoaderEdgeCases:
    """CardLoader handles edge cases correctly."""

    def test_no_effects(self, tmp_path: Path, valid_minion_json: dict) -> None:
        valid_minion_json["effects"] = []
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.effects == ()

    def test_no_attribute(self, tmp_path: Path, valid_minion_json: dict) -> None:
        del valid_minion_json["attribute"]
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.attribute is None

    def test_null_attribute(self, tmp_path: Path, valid_minion_json: dict) -> None:
        valid_minion_json["attribute"] = None
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.attribute is None

    def test_missing_effects_key(
        self, tmp_path: Path, valid_minion_json: dict
    ) -> None:
        """If effects key is absent entirely, should default to empty tuple."""
        del valid_minion_json["effects"]
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.effects == ()

    def test_case_insensitive_card_type(
        self, tmp_path: Path, valid_minion_json: dict
    ) -> None:
        """card_type should be case-insensitive."""
        valid_minion_json["card_type"] = "Minion"
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.card_type == CardType.MINION

    def test_case_insensitive_attribute(
        self, tmp_path: Path, valid_minion_json: dict
    ) -> None:
        """attribute should be case-insensitive."""
        valid_minion_json["attribute"] = "Fire"
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.attribute == Attribute.FIRE
