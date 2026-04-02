"""Tests for CardLibrary -- card registry with lookup and deck validation.

Covers: from_directory loading, get_by_id/get_by_card_id lookups,
deterministic numeric IDs, validate_deck, build_deck.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import CardDefinition
from grid_tactics.enums import CardType
from grid_tactics.types import MAX_COPIES_PER_DECK, MIN_DECK_SIZE


# ---------------------------------------------------------------------------
# Fixtures: temporary card directories
# ---------------------------------------------------------------------------


def _write_card(directory: Path, data: dict) -> Path:
    """Write a card JSON dict to a file in the given directory."""
    filepath = directory / f"{data['card_id']}.json"
    filepath.write_text(json.dumps(data), encoding="utf-8")
    return filepath


@pytest.fixture
def sample_cards() -> list[dict]:
    """Three sample card dicts for testing."""
    return [
        {
            "card_id": "alpha_warrior",
            "name": "Alpha Warrior",
            "card_type": "minion",
            "mana_cost": 2,
            "attack": 2,
            "health": 3,
            "range": 0,
            "attribute": "neutral",
            "effects": [],
        },
        {
            "card_id": "beta_bolt",
            "name": "Beta Bolt",
            "card_type": "magic",
            "mana_cost": 1,
            "attribute": "fire",
            "effects": [
                {
                    "type": "damage",
                    "trigger": "on_play",
                    "target": "single_target",
                    "amount": 2,
                }
            ],
        },
        {
            "card_id": "gamma_guard",
            "name": "Gamma Guard",
            "card_type": "react",
            "mana_cost": 1,
            "attribute": "light",
            "react_condition": "any_action",
            "effects": [
                {
                    "type": "buff_health",
                    "trigger": "on_play",
                    "target": "single_target",
                    "amount": 1,
                }
            ],
        },
    ]


@pytest.fixture
def card_directory(tmp_path: Path, sample_cards: list[dict]) -> Path:
    """Create a temp directory with sample card JSON files."""
    for card_data in sample_cards:
        _write_card(tmp_path, card_data)
    return tmp_path


# ---------------------------------------------------------------------------
# Test: from_directory loading
# ---------------------------------------------------------------------------


class TestFromDirectory:
    """CardLibrary.from_directory loads all JSON files from a directory."""

    def test_loads_all_cards(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        assert lib.card_count == 3

    def test_empty_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="No card JSON files"):
            CardLibrary.from_directory(tmp_path)

    def test_duplicate_card_id_raises(
        self, card_directory: Path, sample_cards: list[dict]
    ) -> None:
        # Write a second file with the same card_id
        dup = sample_cards[0].copy()
        _write_card(card_directory, dup)
        # Now there are two files with card_id "alpha_warrior"
        # but since they have the same filename, it's the same file overwritten
        # Create with a different filename
        dup_path = card_directory / "alpha_warrior_dup.json"
        dup_path.write_text(json.dumps(dup), encoding="utf-8")
        with pytest.raises(ValueError, match="Duplicate card_id"):
            CardLibrary.from_directory(card_directory)


# ---------------------------------------------------------------------------
# Test: Lookups
# ---------------------------------------------------------------------------


class TestLookups:
    """CardLibrary provides O(1) lookup by numeric and string ID."""

    def test_get_by_id(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        # Sorted alphabetically: alpha_warrior=0, beta_bolt=1, gamma_guard=2
        card = lib.get_by_id(0)
        assert card.card_id == "alpha_warrior"

    def test_get_by_card_id(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        card = lib.get_by_card_id("beta_bolt")
        assert card.name == "Beta Bolt"
        assert card.card_type == CardType.MAGIC

    def test_get_by_id_invalid(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        with pytest.raises(KeyError):
            lib.get_by_id(99)

    def test_get_by_card_id_unknown(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        with pytest.raises(KeyError):
            lib.get_by_card_id("nonexistent_card")

    def test_all_cards(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        all_cards = lib.all_cards
        assert isinstance(all_cards, tuple)
        assert len(all_cards) == 3
        # Should be in deterministic order (sorted by card_id)
        assert all_cards[0].card_id == "alpha_warrior"
        assert all_cards[1].card_id == "beta_bolt"
        assert all_cards[2].card_id == "gamma_guard"

    def test_card_count(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        assert lib.card_count == 3


# ---------------------------------------------------------------------------
# Test: Deterministic numeric IDs
# ---------------------------------------------------------------------------


class TestDeterministicIDs:
    """Numeric IDs are deterministic -- sorted by card_id alphabetically."""

    def test_ids_are_sorted_alphabetically(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        # alpha < beta < gamma alphabetically
        assert lib.get_numeric_id("alpha_warrior") == 0
        assert lib.get_numeric_id("beta_bolt") == 1
        assert lib.get_numeric_id("gamma_guard") == 2

    def test_roundtrip_id(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        for card_id_str in ["alpha_warrior", "beta_bolt", "gamma_guard"]:
            numeric = lib.get_numeric_id(card_id_str)
            card = lib.get_by_id(numeric)
            assert card.card_id == card_id_str


# ---------------------------------------------------------------------------
# Test: Deck validation
# ---------------------------------------------------------------------------


class TestValidateDeck:
    """validate_deck enforces D-12 (max 3 copies) and D-13 (min 40 cards)."""

    def _build_valid_deck(self, lib: CardLibrary) -> tuple[int, ...]:
        """Build a valid 40+ card deck from available cards."""
        # With 3 cards, 3 copies each = 9. Need 40 minimum.
        # This helper builds a deck with enough cards by using all available IDs.
        # For 3 cards with max 3 copies, we can only get 9 -- not enough for 40.
        # So for valid deck tests, we need a larger card pool.
        # We'll handle this in the test that actually needs it.
        raise NotImplementedError("Use the fixture with more cards")

    def test_valid_deck(self, tmp_path: Path) -> None:
        """A valid 40-card deck with max 3 copies passes validation."""
        # Create 14 unique cards (14 * 3 = 42 capacity >= 40)
        cards = []
        for i in range(14):
            cards.append(
                {
                    "card_id": f"card_{i:02d}",
                    "name": f"Card {i}",
                    "card_type": "minion",
                    "mana_cost": (i % 5) + 1,
                    "attack": (i % 5) + 1,
                    "health": (i % 5) + 1,
                    "range": 0,
                    "effects": [],
                }
            )
        for c in cards:
            _write_card(tmp_path, c)

        lib = CardLibrary.from_directory(tmp_path)

        # Build a 40-card deck: 3 copies of first 13 cards + 1 copy of 14th
        deck_list: list[int] = []
        for i in range(13):
            deck_list.extend([i] * 3)  # 39 cards
        deck_list.append(13)  # 40th card
        deck = tuple(deck_list)

        errors = lib.validate_deck(deck)
        assert errors == []

    def test_too_few_cards(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        # Only 9 cards (3 * 3 copies)
        deck = tuple([0, 0, 0, 1, 1, 1, 2, 2, 2])
        errors = lib.validate_deck(deck)
        assert any(str(MIN_DECK_SIZE) in e for e in errors)

    def test_too_many_copies(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        # 4 copies of card 0
        deck = tuple([0] * 4 + [1] * 3 + [2] * 3)
        errors = lib.validate_deck(deck)
        assert any(str(MAX_COPIES_PER_DECK) in e or "copies" in e for e in errors)

    def test_unknown_card_ids(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        deck = tuple([0, 1, 2, 99])
        errors = lib.validate_deck(deck)
        assert any("99" in e or "Unknown" in e for e in errors)


# ---------------------------------------------------------------------------
# Test: build_deck helper
# ---------------------------------------------------------------------------


class TestBuildDeck:
    """build_deck creates a valid deck tuple from card_id strings and counts."""

    def test_build_valid_deck(self, tmp_path: Path) -> None:
        # Create 14 unique cards
        for i in range(14):
            _write_card(
                tmp_path,
                {
                    "card_id": f"card_{i:02d}",
                    "name": f"Card {i}",
                    "card_type": "minion",
                    "mana_cost": (i % 5) + 1,
                    "attack": (i % 5) + 1,
                    "health": (i % 5) + 1,
                    "range": 0,
                    "effects": [],
                },
            )

        lib = CardLibrary.from_directory(tmp_path)

        # Build 40-card deck: 3 of each of first 13 + 1 of 14th
        card_counts = {f"card_{i:02d}": 3 for i in range(13)}
        card_counts["card_13"] = 1

        deck = lib.build_deck(card_counts)
        assert isinstance(deck, tuple)
        assert len(deck) == 40

    def test_build_invalid_deck_raises(self, card_directory: Path) -> None:
        lib = CardLibrary.from_directory(card_directory)
        # Only 9 cards total -- won't meet min 40
        card_counts = {
            "alpha_warrior": 3,
            "beta_bolt": 3,
            "gamma_guard": 3,
        }
        with pytest.raises(ValueError, match="Invalid deck"):
            lib.build_deck(card_counts)


# ---------------------------------------------------------------------------
# Integration tests: Starter card pool (data/cards/)
# ---------------------------------------------------------------------------

# Path to the real starter card data
_STARTER_CARDS_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"


class TestStarterPool:
    """Load data/cards/ with CardLibrary.from_directory, verify pool properties."""

    @pytest.fixture
    def starter_lib(self) -> CardLibrary:
        return CardLibrary.from_directory(_STARTER_CARDS_DIR)

    def test_card_count_minimum(self, starter_lib: CardLibrary) -> None:
        """D-16: 15-20 unique starter cards."""
        assert starter_lib.card_count >= 15

    def test_all_cards_load_without_errors(self, starter_lib: CardLibrary) -> None:
        """All 18 cards load successfully -- no validation errors."""
        all_cards = starter_lib.all_cards
        assert len(all_cards) == 18
        for card in all_cards:
            assert isinstance(card, CardDefinition)


class TestStarterPoolTypes:
    """Starter pool has correct type distribution (D-17)."""

    @pytest.fixture
    def starter_lib(self) -> CardLibrary:
        return CardLibrary.from_directory(_STARTER_CARDS_DIR)

    def test_minion_count(self, starter_lib: CardLibrary) -> None:
        minions = [c for c in starter_lib.all_cards if c.card_type == CardType.MINION]
        assert len(minions) >= 8

    def test_magic_count(self, starter_lib: CardLibrary) -> None:
        magic = [c for c in starter_lib.all_cards if c.card_type == CardType.MAGIC]
        assert len(magic) >= 3

    def test_react_count(self, starter_lib: CardLibrary) -> None:
        react = [c for c in starter_lib.all_cards if c.card_type == CardType.REACT]
        assert len(react) >= 2


class TestStarterPoolMultiPurpose:
    """At least one multi-purpose card exists (D-18)."""

    def test_has_multi_purpose_card(self) -> None:
        lib = CardLibrary.from_directory(_STARTER_CARDS_DIR)
        multi = [c for c in lib.all_cards if c.is_multi_purpose]
        assert len(multi) >= 1


class TestStarterPoolDeck:
    """A valid 40-card deck can be built from the starter pool."""

    def test_build_valid_deck(self) -> None:
        lib = CardLibrary.from_directory(_STARTER_CARDS_DIR)
        # Build a 40-card deck: 3 copies of first 13 cards + 1 of 14th
        card_ids = sorted([c.card_id for c in lib.all_cards])
        card_counts = {}
        total = 0
        for card_id in card_ids:
            if total >= 40:
                break
            copies = min(3, 40 - total)
            card_counts[card_id] = copies
            total += copies

        deck = lib.build_deck(card_counts)
        assert len(deck) >= 40
        errors = lib.validate_deck(deck)
        assert errors == []


class TestManaDistribution:
    """Starter cards exist at mana costs 1 through 5."""

    def test_all_mana_costs_present(self) -> None:
        lib = CardLibrary.from_directory(_STARTER_CARDS_DIR)
        costs = {c.mana_cost for c in lib.all_cards}
        for cost in range(1, 6):
            assert cost in costs, f"No card at mana cost {cost}"


class TestAttributeDistribution:
    """At least 3 distinct attributes used in starter pool."""

    def test_at_least_three_attributes(self) -> None:
        lib = CardLibrary.from_directory(_STARTER_CARDS_DIR)
        attributes = {c.attribute for c in lib.all_cards if c.attribute is not None}
        assert len(attributes) >= 3
