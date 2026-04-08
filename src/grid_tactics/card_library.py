"""Card library -- registry of all card definitions with lookup and deck validation.

CardLibrary is loaded once at game startup. It provides O(1) lookup by
numeric ID (used in Player.hand, Board.cells) and string card_id.
Numeric IDs are deterministic -- sorted alphabetically by card_id.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from grid_tactics.card_loader import CardLoader
from grid_tactics.cards import CardDefinition
from grid_tactics.types import MAX_COPIES_PER_DECK, MIN_DECK_SIZE


class CardLibrary:
    """Registry of all card definitions. Loaded once at game startup."""

    def __init__(self, cards: dict[str, CardDefinition]) -> None:
        self._cards = cards
        # Build deterministic numeric ID mapping (sorted alphabetically by card_id)
        self._id_to_card_id: dict[int, str] = {}
        self._card_id_to_id: dict[str, int] = {}
        for i, card_id in enumerate(sorted(cards.keys())):
            self._id_to_card_id[i] = card_id
            self._card_id_to_id[card_id] = i

    def get_by_id(self, numeric_id: int) -> CardDefinition:
        """Look up by numeric ID (used in Player.hand, Board.cells).

        Raises KeyError if numeric_id is not valid.
        """
        card_id = self._id_to_card_id[numeric_id]
        return self._cards[card_id]

    def get_by_card_id(self, card_id: str) -> CardDefinition:
        """Look up by string card_id.

        Raises KeyError if card_id is unknown.
        """
        return self._cards[card_id]

    def get_numeric_id(self, card_id: str) -> int:
        """Get numeric ID for a card_id string.

        Raises KeyError if card_id is unknown.
        """
        return self._card_id_to_id[card_id]

    @property
    def all_cards(self) -> tuple[CardDefinition, ...]:
        """Return all card definitions in deterministic order (sorted by card_id)."""
        return tuple(
            self._cards[self._id_to_card_id[i]] for i in range(len(self._cards))
        )

    @property
    def card_count(self) -> int:
        """Return total number of card definitions."""
        return len(self._cards)

    @classmethod
    def from_directory(cls, path: Path) -> CardLibrary:
        """Load all *.json files from directory into a CardLibrary.

        Raises ValueError if no JSON files found or duplicate card_ids exist.
        """
        cards: dict[str, CardDefinition] = {}
        for json_file in sorted(path.glob("*.json")):
            card_def = CardLoader.load_card(json_file)
            if card_def.card_id in cards:
                raise ValueError(f"Duplicate card_id: {card_def.card_id}")
            cards[card_def.card_id] = card_def
        if not cards:
            raise ValueError(f"No card JSON files found in {path}")
        return cls(cards)

    def validate_deck(self, deck: tuple[int, ...]) -> list[str]:
        """Validate a deck tuple against game rules (D-12, D-13).

        Returns list of error strings (empty = valid).
        """
        errors: list[str] = []

        # Check minimum deck size (D-13)
        if len(deck) < MIN_DECK_SIZE:
            errors.append(
                f"Deck has {len(deck)} cards, minimum is {MIN_DECK_SIZE}"
            )

        # Check all IDs are valid
        for card_id in deck:
            if card_id not in self._id_to_card_id:
                errors.append(f"Unknown card ID: {card_id}")

        # Check copy limit (D-12)
        counts = Counter(deck)
        for card_id, count in counts.items():
            if count > MAX_COPIES_PER_DECK:
                errors.append(
                    f"Card ID {card_id} has {count} copies, "
                    f"max is {MAX_COPIES_PER_DECK}"
                )

        # Reject non-deckable cards (tokens / summons / reward-only cards)
        for card_id in counts.keys():
            if card_id in self._id_to_card_id:
                cid_str = self._id_to_card_id[card_id]
                cdef = self._cards.get(cid_str)
                if cdef is not None and getattr(cdef, "deckable", True) is False:
                    errors.append(
                        f"Card '{cid_str}' is not deckable (tokens/summons only)"
                    )

        return errors

    def build_deck(self, card_counts: dict[str, int]) -> tuple[int, ...]:
        """Build a deck tuple from {card_id_str: count} mapping.

        Raises ValueError if the resulting deck is invalid.
        """
        deck_list: list[int] = []
        for card_id_str, count in card_counts.items():
            numeric_id = self.get_numeric_id(card_id_str)
            deck_list.extend([numeric_id] * count)
        deck = tuple(deck_list)
        errors = self.validate_deck(deck)
        if errors:
            raise ValueError(f"Invalid deck: {'; '.join(errors)}")
        return deck
