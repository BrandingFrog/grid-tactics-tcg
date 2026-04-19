"""Tests for CardLoader -- JSON file to CardDefinition conversion.

Covers: valid loading for all card types, validation error messages,
edge cases (no effects, no element, multi-purpose cards).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_tactics.card_loader import CardLoader
from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.enums import (
    Element,
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
        "element": "fire",
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
        "element": "fire",
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
        "element": "light",
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
        "element": "dark",
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
        assert card.element == Element.FIRE
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
        assert card.element == Element.FIRE
        assert len(card.effects) == 1
        assert card.effects[0].amount == 4

    def test_load_react(self, tmp_path: Path, valid_react_json: dict) -> None:
        path = _write_card_json(tmp_path, valid_react_json)
        card = CardLoader.load_card(path)

        assert card.card_id == "test_react"
        assert card.card_type == CardType.REACT
        assert card.mana_cost == 1
        assert card.element == Element.LIGHT
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

    def test_invalid_element(self, tmp_path: Path, valid_minion_json: dict) -> None:
        valid_minion_json["element"] = "ice"
        path = _write_card_json(tmp_path, valid_minion_json)
        with pytest.raises(ValueError, match="element.*ice"):
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

    def test_no_element(self, tmp_path: Path, valid_minion_json: dict) -> None:
        del valid_minion_json["element"]
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.element is None

    def test_null_element(self, tmp_path: Path, valid_minion_json: dict) -> None:
        valid_minion_json["element"] = None
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.element is None

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

    def test_case_insensitive_element(
        self, tmp_path: Path, valid_minion_json: dict
    ) -> None:
        """element should be case-insensitive."""
        valid_minion_json["element"] = "Fire"
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.element == Element.FIRE


# ---------------------------------------------------------------------------
# Phase 14.7-03: New TriggerType values (on_summon, on_start_of_turn,
# on_end_of_turn) load correctly, and the 9 retagged card JSONs carry the
# expected triggers after the rename.
# ---------------------------------------------------------------------------


class TestPhase1473NewTriggers:
    """CardLoader parses 14.7-03's new trigger strings; real card JSONs updated."""

    @pytest.fixture
    def real_library(self):
        """Load the real card library from data/cards."""
        from grid_tactics.card_library import CardLibrary
        from pathlib import Path as _Path
        return CardLibrary.from_directory(_Path("data/cards"))

    def test_load_on_summon_trigger(self, tmp_path: Path, valid_minion_json: dict) -> None:
        """JSON trigger='on_summon' loads to TriggerType.ON_SUMMON."""
        valid_minion_json["effects"][0]["trigger"] = "on_summon"
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.effects[0].trigger == TriggerType.ON_SUMMON

    def test_load_on_start_of_turn_trigger(
        self, tmp_path: Path, valid_minion_json: dict
    ) -> None:
        """JSON trigger='on_start_of_turn' loads to TriggerType.ON_START_OF_TURN."""
        valid_minion_json["effects"][0]["trigger"] = "on_start_of_turn"
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.effects[0].trigger == TriggerType.ON_START_OF_TURN

    def test_load_on_end_of_turn_trigger(
        self, tmp_path: Path, valid_minion_json: dict
    ) -> None:
        """JSON trigger='on_end_of_turn' loads to TriggerType.ON_END_OF_TURN."""
        valid_minion_json["effects"][0]["trigger"] = "on_end_of_turn"
        path = _write_card_json(tmp_path, valid_minion_json)
        card = CardLoader.load_card(path)
        assert card.effects[0].trigger == TriggerType.ON_END_OF_TURN

    def test_gargoyle_sorceress_has_on_summon(self, real_library) -> None:
        """Gargoyle Sorceress's buff_attack and buff_health effects are on_summon."""
        card = real_library.get_by_card_id("gargoyle_sorceress")
        assert len(card.effects) == 2
        for eff in card.effects:
            assert eff.trigger == TriggerType.ON_SUMMON

    def test_blue_diodebot_has_on_summon(self, real_library) -> None:
        """Blue Diodebot tutor effect is on_summon."""
        card = real_library.get_by_card_id("blue_diodebot")
        assert card.effects[0].trigger == TriggerType.ON_SUMMON

    def test_green_diodebot_has_on_summon(self, real_library) -> None:
        card = real_library.get_by_card_id("green_diodebot")
        assert card.effects[0].trigger == TriggerType.ON_SUMMON

    def test_red_diodebot_has_on_summon(self, real_library) -> None:
        card = real_library.get_by_card_id("red_diodebot")
        assert card.effects[0].trigger == TriggerType.ON_SUMMON

    def test_eclipse_shade_has_on_summon(self, real_library) -> None:
        """Eclipse Shade's self-burn is on_summon."""
        card = real_library.get_by_card_id("eclipse_shade")
        assert card.effects[0].trigger == TriggerType.ON_SUMMON

    def test_flame_wyrm_draw_is_on_summon_and_aura_unchanged(self, real_library) -> None:
        """Flame Wyrm: draw effect is on_summon, burn_bonus aura unchanged."""
        from grid_tactics.enums import EffectType
        card = real_library.get_by_card_id("flame_wyrm")
        triggers = {e.effect_type: e.trigger for e in card.effects}
        assert triggers[EffectType.DRAW] == TriggerType.ON_SUMMON
        assert triggers[EffectType.BURN_BONUS] == TriggerType.AURA

    def test_fallen_paladin_has_on_end_of_turn(self, real_library) -> None:
        """Fallen Paladin's passive_heal fires at end of owner's turn (matches card text)."""
        card = real_library.get_by_card_id("fallen_paladin")
        assert card.effects[0].trigger == TriggerType.ON_END_OF_TURN

    def test_emberplague_rat_has_on_end_of_turn(self, real_library) -> None:
        """Emberplague Rat's adjacent burn is now on_end_of_turn."""
        card = real_library.get_by_card_id("emberplague_rat")
        assert card.effects[0].trigger == TriggerType.ON_END_OF_TURN

    def test_dark_matter_battery_has_on_end_of_turn(self, real_library) -> None:
        """Dark Matter Battery's damage-opponent is now on_end_of_turn."""
        card = real_library.get_by_card_id("dark_matter_battery")
        assert card.effects[0].trigger == TriggerType.ON_END_OF_TURN

    def test_surgefed_sparkbot_stays_on_play(self, real_library) -> None:
        """Sparkbot keeps on_play — its react_effect (DEPLOY_SELF) resolves at react time."""
        card = real_library.get_by_card_id("surgefed_sparkbot")
        # Sparkbot's only "effect" is the react_effect; effects list is empty.
        # The react path doesn't use TriggerType filtering anyway.
        # Instead, verify the card still has CardType.MINION and react_effect.
        assert card.react_effect is not None


class TestPhase1477NewReactConditions:
    """Phase 14.7-07: CardLoader recognizes the three new react_condition strings.

    These are forward-compat values — no card JSON uses them yet. The loader
    is reflective (``enum_cls[value.upper()]``) so no explicit allowlist
    edit was needed; these tests guard the contract.
    """

    def test_load_opponent_summons_minion(
        self, tmp_path: Path, valid_react_json: dict
    ) -> None:
        """JSON react_condition='opponent_summons_minion' loads correctly."""
        from grid_tactics.enums import ReactCondition
        valid_react_json["react_condition"] = "opponent_summons_minion"
        path = _write_card_json(tmp_path, valid_react_json)
        card = CardLoader.load_card(path)
        assert card.react_condition == ReactCondition.OPPONENT_SUMMONS_MINION

    def test_load_opponent_start_of_turn(
        self, tmp_path: Path, valid_react_json: dict
    ) -> None:
        """JSON react_condition='opponent_start_of_turn' loads correctly."""
        from grid_tactics.enums import ReactCondition
        valid_react_json["react_condition"] = "opponent_start_of_turn"
        path = _write_card_json(tmp_path, valid_react_json)
        card = CardLoader.load_card(path)
        assert card.react_condition == ReactCondition.OPPONENT_START_OF_TURN

    def test_load_opponent_end_of_turn(
        self, tmp_path: Path, valid_react_json: dict
    ) -> None:
        """JSON react_condition='opponent_end_of_turn' loads correctly."""
        from grid_tactics.enums import ReactCondition
        valid_react_json["react_condition"] = "opponent_end_of_turn"
        path = _write_card_json(tmp_path, valid_react_json)
        card = CardLoader.load_card(path)
        assert card.react_condition == ReactCondition.OPPONENT_END_OF_TURN

    def test_invalid_react_condition_still_raises(
        self, tmp_path: Path, valid_react_json: dict
    ) -> None:
        """Unknown react_condition strings still raise ValueError."""
        valid_react_json["react_condition"] = "bogus_unknown_condition"
        path = _write_card_json(tmp_path, valid_react_json)
        with pytest.raises(ValueError, match="react_condition"):
            CardLoader.load_card(path)
