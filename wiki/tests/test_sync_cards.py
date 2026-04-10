"""
Unit tests for wiki/sync/sync_cards.py wikitext generation.

Tests load real card JSON from ``data/cards/`` (not mocked data) to validate
against actual card definitions.

Run from ``wiki/`` directory::

    cd wiki
    python -m pytest tests/test_sync_cards.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sync.sync_cards import (
    build_card_name_map,
    build_rules_text,
    card_to_wikitext,
    derive_keywords,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CARDS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cards"


@pytest.fixture(scope="module")
def name_map() -> dict[str, str]:
    return build_card_name_map(CARDS_DIR)


def _load(filename: str) -> dict:
    return json.loads((CARDS_DIR / filename).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# derive_keywords tests
# ---------------------------------------------------------------------------


class TestDeriveKeywords:
    def test_derive_keywords_minion_melee(self):
        """Ratchanter: activated_ability + range=0 -> Active, Conjure, Melee."""
        card = _load("minion_ratchanter.json")
        kws = derive_keywords(card)
        assert "Active" in kws
        assert "Conjure" in kws
        assert "Melee" in kws
        assert "Ranged" not in kws

    def test_derive_keywords_minion_ranged(self):
        """Wind Archer: range=2 -> Ranged."""
        card = _load("minion_wind_archer.json")
        kws = derive_keywords(card)
        assert "Ranged" in kws
        assert "Melee" not in kws

    def test_derive_keywords_react(self):
        """Counter Spell: card_type=react + negate effect -> React, Negate."""
        card = _load("react_counter_spell.json")
        kws = derive_keywords(card)
        assert "React" in kws
        assert "Negate" in kws
        # React cards should NOT have Melee/Ranged
        assert "Melee" not in kws
        assert "Ranged" not in kws

    def test_derive_keywords_unique(self):
        """Giant Rat: unique=true -> Unique."""
        card = _load("minion_giant_rat.json")
        kws = derive_keywords(card)
        assert "Unique" in kws

    def test_derive_keywords_transform(self):
        """Reanimated Bones: transform_options -> Transform."""
        card = _load("minion_reanimated_bones.json")
        kws = derive_keywords(card)
        assert "Transform" in kws

    def test_derive_keywords_tutor(self):
        """Blue Diodebot: tutor_target + on_play effect -> Tutor, Summon."""
        card = _load("minion_blue_diodebot.json")
        kws = derive_keywords(card)
        assert "Tutor" in kws
        assert "Summon" in kws

    def test_derive_keywords_promote(self):
        """Giant Rat: promote_target -> Promote."""
        card = _load("minion_giant_rat.json")
        kws = derive_keywords(card)
        assert "Promote" in kws

    def test_derive_keywords_discard_cost(self):
        """RGB Lasercannon: summon_sacrifice_tribe -> Cost, Discard."""
        card = _load("minion_rgb_lasercannon.json")
        kws = derive_keywords(card)
        assert "Cost" in kws
        assert "Discard" in kws

    def test_derive_keywords_passive(self):
        """Emberplague Rat: passive burn -> Passive, Burn."""
        card = _load("minion_emberplague_rat.json")
        kws = derive_keywords(card)
        assert "Passive" in kws
        assert "Burn" in kws

    def test_derive_keywords_death(self):
        """Giant Rat: on_death promote -> Death."""
        card = _load("minion_giant_rat.json")
        kws = derive_keywords(card)
        assert "Death" in kws

    def test_derive_keywords_react_condition_on_minion(self):
        """Dark Sentinel: minion with react_condition -> React, Deploy."""
        card = _load("minion_dark_sentinel.json")
        kws = derive_keywords(card)
        assert "React" in kws
        assert "Deploy" in kws

    def test_derive_keywords_sorted_deduped(self):
        """Keywords are always sorted and deduplicated."""
        card = _load("minion_ratchanter.json")
        kws = derive_keywords(card)
        assert kws == sorted(set(kws))


# ---------------------------------------------------------------------------
# build_rules_text tests
# ---------------------------------------------------------------------------


class TestBuildRulesText:
    def test_build_rules_text_activated(self, name_map):
        """Ratchanter: rules text includes Active:, Conjure link, and wikilink to Rat."""
        card = _load("minion_ratchanter.json")
        rules = build_rules_text(card, name_map)
        assert "Active" in rules
        assert "[[Conjure]]" in rules
        assert "[[Card:Common Rat|Common Rat]]" in rules

    def test_build_rules_text_transform(self, name_map):
        """Reanimated Bones: rules text includes wikilinks to all 3 targets."""
        card = _load("minion_reanimated_bones.json")
        rules = build_rules_text(card, name_map)
        assert "Transform:" in rules
        assert "[[Card:Pyre Archer|Pyre Archer]]" in rules
        assert "[[Card:Grave Caller|Grave Caller]]" in rules
        assert "[[Card:Fallen Paladin|Fallen Paladin]]" in rules

    def test_build_rules_text_tutor(self, name_map):
        """Blue Diodebot: rules text includes Tutor link and wikilink to Red Diodebot."""
        card = _load("minion_blue_diodebot.json")
        rules = build_rules_text(card, name_map)
        assert "[[Card:Red Diodebot|Red Diodebot]]" in rules
        assert "[[Tutor]]" in rules

    def test_build_rules_text_multi_effect(self, name_map):
        """Dark Drain: damage + heal -> both effects appear with links."""
        card = _load("magic_dark_drain.json")
        rules = build_rules_text(card, name_map)
        assert "Deal 20 damage" in rules
        assert "[[Heal]] 20" in rules

    def test_build_rules_text_promote(self, name_map):
        """Giant Rat: rules mentions Promote link."""
        card = _load("minion_giant_rat.json")
        rules = build_rules_text(card, name_map)
        assert "[[Promote]]" in rules

    def test_build_rules_text_react_condition(self, name_map):
        """Counter Spell: rules prefixed with react condition and Negate link."""
        card = _load("react_counter_spell.json")
        rules = build_rules_text(card, name_map)
        assert "[[Negate]]" in rules

    def test_build_rules_text_deploy_self(self, name_map):
        """Dark Sentinel: react_effect deploy_self appears in rules as link."""
        card = _load("minion_dark_sentinel.json")
        rules = build_rules_text(card, name_map)
        assert "[[Deploy]]" in rules

    def test_build_rules_text_no_name_map(self):
        """Cross-links work without name_map (fallback to title-cased id)."""
        card = _load("minion_ratchanter.json")
        rules = build_rules_text(card, name_map=None)
        assert "[[Conjure]]" in rules
        assert "[[Card:Rat|Rat]]" in rules

    def test_build_rules_text_empty(self, name_map):
        """Cards with no effects/abilities produce empty rules text."""
        card = _load("minion_shadow_knight.json")
        rules = build_rules_text(card, name_map)
        assert rules == ""


# ---------------------------------------------------------------------------
# card_to_wikitext tests
# ---------------------------------------------------------------------------


class TestCardToWikitext:
    def test_card_to_wikitext_minion(self, name_map):
        """Ratchanter: starts with {{Card, contains type/attack fields."""
        card = _load("minion_ratchanter.json")
        wt = card_to_wikitext(card, name_map)
        assert wt.startswith("{{Card")
        assert "| type     = Minion" in wt
        assert "| attack   = 15" in wt
        assert "| hp       = 30" in wt
        assert "| range    = 0" in wt
        assert "== History ==" in wt
        assert "== Gallery ==" in wt
        assert "== Tips ==" in wt
        assert "== Rulings ==" in wt
        assert "== Trivia ==" in wt

    def test_card_to_wikitext_magic(self, name_map):
        """Dark Drain (magic): no attack/hp/range fields in output."""
        card = _load("magic_dark_drain.json")
        wt = card_to_wikitext(card, name_map)
        assert "| type     = Magic" in wt
        assert "attack" not in wt.lower().split("| type")[0]  # no attack key
        # Check that attack/hp/range keys are absent
        lines = wt.split("\n")
        field_keys = [l.split("=")[0].strip().lstrip("| ") for l in lines if "=" in l]
        assert "attack" not in field_keys
        assert "hp" not in field_keys
        assert "range" not in field_keys

    def test_card_to_wikitext_react(self, name_map):
        """Counter Spell (react): no attack/hp/range, type = React."""
        card = _load("react_counter_spell.json")
        wt = card_to_wikitext(card, name_map)
        assert "| type     = React" in wt
        lines = wt.split("\n")
        field_keys = [l.split("=")[0].strip().lstrip("| ") for l in lines if "=" in l]
        assert "attack" not in field_keys
        assert "hp" not in field_keys
        assert "range" not in field_keys

    def test_card_to_wikitext_no_art(self, name_map):
        """With art_exists=False, no art field in output."""
        card = _load("minion_ratchanter.json")
        wt = card_to_wikitext(card, name_map, art_exists=False)
        lines = wt.split("\n")
        field_keys = [l.split("=")[0].strip().lstrip("| ") for l in lines if "=" in l]
        assert "art" not in field_keys

    def test_card_to_wikitext_deckable_false(self, name_map):
        """Fallen Paladin: deckable=false -> deckable field is 'false'."""
        card = _load("minion_fallen_paladin.json")
        wt = card_to_wikitext(card, name_map)
        assert "| deckable = false" in wt

    def test_card_to_wikitext_deckable_true_default(self, name_map):
        """Ratchanter: no deckable field in JSON defaults to true."""
        card = _load("minion_ratchanter.json")
        wt = card_to_wikitext(card, name_map)
        assert "| deckable = true" in wt

    def test_card_to_wikitext_no_category(self, name_map):
        """Template:Card handles categories -- wikitext should NOT append them."""
        card = _load("minion_ratchanter.json")
        wt = card_to_wikitext(card, name_map)
        assert "[[Category:" not in wt


# ---------------------------------------------------------------------------
# build_card_name_map tests
# ---------------------------------------------------------------------------


class TestBuildCardNameMap:
    def test_build_card_name_map(self):
        """Reads data/cards/ directory, returns dict with 34+ entries."""
        nm = build_card_name_map(CARDS_DIR)
        assert len(nm) >= 34
        # All values are strings
        for card_id, name in nm.items():
            assert isinstance(card_id, str)
            assert isinstance(name, str)
            assert len(name) > 0

    def test_build_card_name_map_known_entries(self):
        """Spot-check known card_id -> name mappings."""
        nm = build_card_name_map(CARDS_DIR)
        assert nm["ratchanter"] == "Ratchanter"
        assert nm["rat"] == "Common Rat"
        assert nm["blue_diodebot"] == "Blue Diodebot"
        assert nm["counter_spell"] == "Counter Spell"
