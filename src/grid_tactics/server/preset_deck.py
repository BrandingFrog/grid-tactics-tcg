"""Default preset deck for Phase 11 testing (D-03).

40 cards, max 3 copies per card. Validated against CardLibrary at import time.
Used by programmatic test clients that don't have a deck builder UI.
Only uses cards that have card art (+ prohibition).
"""

from grid_tactics.card_library import CardLibrary

# 16 deckable cards (pyre_archer/grave_caller/fallen_paladin are tokens).
# 40-card deck: 9 cards at 3 copies (=27) + 6 cards at 2 copies (=12)
# + 1 card at 1 copy (=1) = 40 total
PRESET_DECK_COUNTS: dict[str, int] = {
    # 3 copies - cheap core + key threats
    "rat": 3,
    "furryroach": 3,
    "reanimated_bones": 3,
    "red_diodebot": 3,
    "blue_diodebot": 3,
    "green_diodebot": 3,
    "emberplague_rat": 3,
    "rathopper": 3,
    "rgb_lasercannon": 3,
    # 2 copies - payoff + control
    "giant_rat": 2,
    "ratchanter": 2,
    "surgefed_sparkbot": 2,
    "ratical_resurrection": 2,
    "to_the_ratmobile": 2,
    "prohibition": 2,
    # 1 copy - splash
    "dark_matter_stash": 1,
}


def get_preset_deck(library: CardLibrary) -> tuple[int, ...]:
    """Build and validate the preset deck against the given library.

    Returns a tuple of numeric card IDs (length 30).
    Raises ValueError if deck is invalid.
    """
    return library.build_deck(PRESET_DECK_COUNTS)
