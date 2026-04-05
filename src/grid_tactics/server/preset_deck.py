"""Default preset deck for Phase 11 testing (D-03).

30 cards, max 3 copies per card. Validated against CardLibrary at import time.
Used by programmatic test clients that don't have a deck builder UI.
"""

from grid_tactics.card_library import CardLibrary

# Card counts: 9 cards at 2 copies (=18) + 12 cards at 1 copy (=12) = 30 total
PRESET_DECK_COUNTS: dict[str, int] = {
    # 2 copies - cheap/versatile cards
    "fire_imp": 2,
    "shadow_stalker": 2,
    "rat": 2,
    "light_cleric": 2,
    "wind_archer": 2,
    "dark_assassin": 2,
    "dark_drain": 2,
    "shield_block": 2,
    "dark_mirror": 2,
    # 1 copy - remaining cards
    "furryroach": 1,
    "counter_spell": 1,
    "holy_light": 1,
    "fireball": 1,
    "holy_paladin": 1,
    "iron_guardian": 1,
    "dark_sentinel": 1,
    "shadow_knight": 1,
    "giant_rat": 1,
    "stone_golem": 1,
    "flame_wyrm": 1,
    "inferno": 1,
}


def get_preset_deck(library: CardLibrary) -> tuple[int, ...]:
    """Build and validate the preset deck against the given library.

    Returns a tuple of numeric card IDs (length 30).
    Raises ValueError if deck is invalid.
    """
    return library.build_deck(PRESET_DECK_COUNTS)
