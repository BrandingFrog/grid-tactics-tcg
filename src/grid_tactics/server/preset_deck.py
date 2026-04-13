"""Default preset deck for Phase 11 testing (D-03).

30 cards, max 3 copies per card. Validated against CardLibrary at import time.
Used by programmatic test clients that don't have a deck builder UI.
Only uses cards that have card art (+ prohibition).
"""

from grid_tactics.card_library import CardLibrary

# 15 deckable cards (pyre_archer/grave_caller/fallen_paladin are tokens). 30-card deck.
# 6 at 3 copies (=18) + 6 at 2 copies (=12) = 30 total
PRESET_DECK_COUNTS: dict[str, int] = {
    # 3 copies - cheap core
    "rat": 3,
    "furryroach": 3,
    "reanimated_bones": 3,
    "red_diodebot": 3,
    "blue_diodebot": 3,
    "green_diodebot": 3,
    # 2 copies - mid game
    "emberplague_rat": 2,
    "rathopper": 2,
    "rgb_lasercannon": 2,
    "giant_rat": 1,
    "ratchanter": 1,
    "surgefed_sparkbot": 1,
    "ratical_resurrection": 1,
    "to_the_ratmobile": 1,
    "prohibition": 1,
}


def get_preset_deck(library: CardLibrary) -> tuple[int, ...]:
    """Build and validate the preset deck against the given library.

    Returns a tuple of numeric card IDs (length 30).
    Raises ValueError if deck is invalid.
    """
    return library.build_deck(PRESET_DECK_COUNTS)
