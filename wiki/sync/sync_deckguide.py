"""
Deck Building Guide page generation and upsert for the Grid Tactics Wiki.

Generates a guide page with two parts:
1. Static strategy content (hand-written advice)
2. Auto-generated archetype listings (derived from card JSON data)

Usage::

    from sync.sync_deckguide import sync_deckguide
    from sync.client import get_site
    from pathlib import Path

    site = get_site()
    sync_deckguide(site, Path("../data/cards"))
"""

from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Element flavor descriptions
# ---------------------------------------------------------------------------

_ELEMENT_FLAVOR: dict[str, str] = {
    "Fire": "Aggressive element focused on direct damage and burn effects.",
    "Water": "Control-oriented element specializing in disruption and tempo.",
    "Earth": "Defensive element with high-HP minions and protective abilities.",
    "Wood": "Growth-based element that ramps resources and buffs allies.",
    "Metal": "Mechanical element with sturdy constructs and synergy effects.",
    "Dark": "Ruthless element leveraging sacrifice, drain, and reanimation.",
    "Light": "Restorative element with healing, shields, and purification.",
}


# ---------------------------------------------------------------------------
# Data scanning
# ---------------------------------------------------------------------------


def _scan_cards(cards_dir: Path) -> list[dict]:
    """Load all card JSONs from *cards_dir*."""
    cards: list[dict] = []
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            cards.append(card)
        except (json.JSONDecodeError, KeyError):
            continue
    return cards


def _count_by_element(cards: list[dict]) -> dict[str, int]:
    """Return ``{Element: count}`` sorted by element name."""
    counts: dict[str, int] = {}
    for card in cards:
        elem = card.get("element", "")
        if elem:
            key = elem.title()
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _count_by_tribe(cards: list[dict]) -> dict[str, int]:
    """Return ``{Tribe: count}`` sorted by tribe name."""
    counts: dict[str, int] = {}
    for card in cards:
        tribe = card.get("tribe", "")
        if tribe:
            counts[tribe] = counts.get(tribe, 0) + 1
    return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Wikitext generation (pure function, no wiki connection)
# ---------------------------------------------------------------------------


def generate_deckguide_wikitext(cards_dir: Path) -> str:
    """Generate the full Deck Building Guide wikitext.

    The page has two major sections:

    1. **Static content** -- Hand-written strategy advice that does not
       change between syncs.
    2. **Auto-generated archetypes** -- Element and tribe breakdowns
       computed from the card JSON files in *cards_dir*.

    Returns the complete wikitext string ready for upsert.
    """
    cards = _scan_cards(cards_dir)
    elem_counts = _count_by_element(cards)
    tribe_counts = _count_by_tribe(cards)

    parts: list[str] = []

    # ------------------------------------------------------------------
    # Static section
    # ------------------------------------------------------------------

    parts.append(
        "= Deck Building Guide =\n"
        "Building a strong deck in '''[[Grid Tactics TCG]]''' means "
        "balancing card costs, element synergies, and strategic "
        "flexibility. This guide covers the fundamentals and lists "
        "the current archetypes available in the card pool."
    )

    parts.append(
        "\n== Basic Principles ==\n"
        "* '''Mana curve''' -- Mix cheap cards (1-2 [[Mana|mana]]) with "
        "expensive finishers (4+ mana). Early plays secure board "
        "presence; late plays close out the game.\n"
        "* '''Element synergy''' -- Cards of the same element often "
        "share keywords or complement each other's effects. A focused "
        "element core with a small splash is usually stronger than "
        "spreading across many elements.\n"
        "* '''Tribe synergy''' -- Some tribes have mutual buffs or "
        "shared mechanics. Building around a tribe (e.g. Rat swarm, "
        "Robot value) can unlock powerful combos."
    )

    parts.append(
        "\n== Strategy Tips ==\n"
        "* '''Placement matters''' -- Minions move forward only in "
        "their lane. Choose your deployment column carefully based on "
        "the opponent's board state.\n"
        "* '''React cards are king''' -- Holding a react card creates "
        "uncertainty for your opponent. Even if you never play it, the "
        "threat alone changes their decisions. See [[React Window]].\n"
        "* '''Sacrifice wins''' -- A fast minion that crosses the "
        "[[5x5 Board|board]] can win the game instantly. Aggressive "
        "decks should include cheap, mobile minions to threaten the "
        "sacrifice [[Win Conditions|win condition]]."
    )

    parts.append(
        "\n== Key Mechanics ==\n"
        "* [[Mana]] -- Resource system and banking\n"
        "* [[React Window]] -- Counter-play after each action\n"
        "* [[Win Conditions]] -- Sacrifice or HP depletion\n"
        "* [[Turn Structure]] -- Draw, action, react, end"
    )

    # ------------------------------------------------------------------
    # Auto-generated archetypes section
    # ------------------------------------------------------------------

    parts.append(
        "\n<!-- AUTO-ARCHETYPES-START -->\n"
        "== Current Archetypes =="
    )

    # Per-element subsections
    for element, count in elem_counts.items():
        flavor = _ELEMENT_FLAVOR.get(element, "A versatile element.")
        parts.append(
            f"\n=== {element} ===\n"
            f"'''{count} card{'s' if count != 1 else ''}''' -- {flavor}\n"
            f"{{{{#ask:\n"
            f" [[Category:Card]]\n"
            f" [[Element::{element}]]\n"
            f" |?Cost\n"
            f" |?Attack\n"
            f" |?HP\n"
            f" |format=table\n"
            f" |limit=50\n"
            f"}}}}"
        )

    # Tribe synergies subsection (tribes with 3+ cards)
    big_tribes = {t: c for t, c in tribe_counts.items() if c >= 3}
    if big_tribes:
        parts.append("\n=== Tribe Synergies ===")
        for tribe, count in sorted(big_tribes.items()):
            parts.append(
                f"* '''[[{tribe}]]''' ({count} cards) -- "
                f"{{{{#ask:[[Category:Card]][[Tribe::{tribe}]]"
                f"|?Name|format=list|limit=50}}}}"
            )

    parts.append("\n<!-- AUTO-ARCHETYPES-END -->")

    # Category
    parts.append("\n[[Category:Rules]]")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------

_PAGE_TITLE = "Deck Building Guide"


def sync_deckguide(
    site,
    cards_dir: Path,
    dry_run: bool = False,
) -> str:
    """Upsert the Deck Building Guide page on the wiki.

    Uses ``rstrip()`` comparison for idempotency (MediaWiki strips
    trailing whitespace on storage).

    Returns ``"created"``, ``"updated"``, ``"unchanged"``,
    ``"would-create"``, or ``"would-update"``.
    """
    wikitext = generate_deckguide_wikitext(cards_dir)
    page = site.pages[_PAGE_TITLE]

    if dry_run:
        if not page.exists:
            print(f"  {_PAGE_TITLE}: would-create")
            return "would-create"
        current = page.text()
        if current.rstrip() == wikitext.rstrip():
            print(f"  {_PAGE_TITLE}: unchanged")
            return "unchanged"
        print(f"  {_PAGE_TITLE}: would-update")
        return "would-update"

    summary = "sync Deck Building Guide from sync_deckguide.py"

    if not page.exists:
        page.edit(wikitext, summary=summary)
        print(f"  {_PAGE_TITLE}: created")
        return "created"

    current = page.text()
    if current.rstrip() == wikitext.rstrip():
        print(f"  {_PAGE_TITLE}: unchanged")
        return "unchanged"

    page.edit(wikitext, summary=summary)
    print(f"  {_PAGE_TITLE}: updated")
    return "updated"
