"""
Semantic:Showcase page wikitext generation and upsert logic.

Generates the showcase page demonstrating powerful SMW queries against
the Grid Tactics card database.  Each query runs live against the wiki's
semantic store and updates automatically as cards change.

Usage::

    from sync.sync_showcase import sync_showcase_page
    from sync.client import get_site

    site = get_site()
    sync_showcase_page(site)
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Wikitext generation (pure function, no wiki connection)
# ---------------------------------------------------------------------------


def showcase_page_wikitext() -> str:
    """Return wikitext for the ``Semantic:Showcase`` page.

    Contains 7 live ``#ask`` queries covering a range of card-database
    explorations, plus a "write your own" guide section.
    """
    return (
        "This page demonstrates the power of Semantic MediaWiki queries "
        "against the Grid Tactics card database. Each query runs live "
        "against the wiki's semantic store -- results update automatically "
        "as cards are added or changed.\n"
        "\n"
        "== Query 1: Fire Minions Under 3 Mana ==\n"
        "Budget fire cards for aggressive early-game openings.\n"
        "\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[Element::Fire]]\n"
        " [[CardType::Minion]]\n"
        " [[ManaCost::<<3]]\n"
        " |?ManaCost\n"
        " |?Attack\n"
        " |?HP\n"
        " |?Tribe\n"
        " |format=broadtable\n"
        " |link=subject\n"
        " |sort=ManaCost\n"
        "}}\n"
        "\n"
        "== Query 2: High-Attack Minions by Tribe ==\n"
        "All minions with attack power above 10, sorted by tribe for "
        "deckbuilding reference.\n"
        "\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[CardType::Minion]]\n"
        " [[Attack::>>10]]\n"
        " |?Attack\n"
        " |?HP\n"
        " |?ManaCost\n"
        " |?Element\n"
        " |?Tribe\n"
        " |format=broadtable\n"
        " |link=subject\n"
        " |sort=Tribe,Attack\n"
        " |order=asc,desc\n"
        " |limit=50\n"
        "}}\n"
        "\n"
        "== Query 3: Cards Changed in Recent Patches ==\n"
        "Track what's been modified recently for meta awareness.\n"
        "\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[LastChangedPatch::+]]\n"
        " |?LastChangedPatch\n"
        " |?CardType\n"
        " |?Element\n"
        " |?ManaCost\n"
        " |format=broadtable\n"
        " |link=subject\n"
        " |sort=LastChangedPatch\n"
        " |order=desc\n"
        " |limit=20\n"
        "}}\n"
        "\n"
        "== Query 4: Tanky Minions (HP >= 30) ==\n"
        "The most durable minions for defensive strategies.\n"
        "\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[CardType::Minion]]\n"
        " [[HP::>>29]]\n"
        " |?HP\n"
        " |?Attack\n"
        " |?ManaCost\n"
        " |?Element\n"
        " |?Tribe\n"
        " |format=broadtable\n"
        " |link=subject\n"
        " |sort=HP\n"
        " |order=desc\n"
        " |limit=50\n"
        "}}\n"
        "\n"
        "== Query 5: Low-Cost React Cards ==\n"
        "Cheap responses to keep in hand for the react window.\n"
        "\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[CardType::React]]\n"
        " |?ManaCost\n"
        " |?Element\n"
        " |?RulesText\n"
        " |format=broadtable\n"
        " |link=subject\n"
        " |sort=ManaCost\n"
        "}}\n"
        "\n"
        "== Query 6: Dark Element Cards ==\n"
        "The full roster of Dark-aligned cards across all types.\n"
        "\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[Element::Dark]]\n"
        " |?CardType\n"
        " |?ManaCost\n"
        " |?Attack\n"
        " |?HP\n"
        " |?Tribe\n"
        " |format=broadtable\n"
        " |link=subject\n"
        " |sort=CardType,ManaCost\n"
        " |limit=50\n"
        "}}\n"
        "\n"
        "== Query 7: Metal Robots ==\n"
        "The full Robot tribe lineup in the Metal element.\n"
        "\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[Element::Metal]]\n"
        " [[Tribe::Robot]]\n"
        " |?ManaCost\n"
        " |?Attack\n"
        " |?HP\n"
        " |format=broadtable\n"
        " |link=subject\n"
        " |sort=ManaCost\n"
        "}}\n"
        "\n"
        "== Writing Your Own Queries ==\n"
        "Semantic MediaWiki's <code>#ask</code> parser function lets you "
        "query any combination of card properties. See the "
        "[https://www.semantic-mediawiki.org/wiki/Help:Inline_queries "
        "SMW ask documentation] for full syntax.\n"
        "\n"
        "=== Available Properties ===\n"
        "The following properties are defined for all cards:\n"
        "\n"
        "* '''Name''' -- Display name of the card\n"
        "* '''CardType''' -- Minion, Magic, React, or Multi\n"
        "* '''Element''' -- Wood, Fire, Earth, Water, Metal, Dark, or Light\n"
        "* '''Tribe''' -- Creature tribe (Rat, Golem, Robot, etc.)\n"
        "* '''Cost''' -- Mana cost (0-10)\n"
        "* '''Attack''' -- Attack power (minions only)\n"
        "* '''HP''' -- Hit points (minions only)\n"
        "* '''Range''' -- Attack range in grid tiles\n"
        "* '''Keyword''' -- Gameplay keywords (multi-valued)\n"
        "* '''LastChangedPatch''' -- Most recent patch version that modified this card\n"
        "* '''RulesText''' -- Mechanical rules text\n"
        "\n"
        "=== Template ===\n"
        "Copy and adapt this skeleton for your own queries:\n"
        "\n"
        "<pre>\n"
        "{{#ask:\n"
        " [[Category:Card]]\n"
        " [[YourFilter::Value]]\n"
        " |?Property1\n"
        " |?Property2\n"
        " |format=broadtable\n"
        " |sort=Property1\n"
        " |limit=50\n"
        "}}\n"
        "</pre>\n"
        "\n"
        "[[Category:Rules]]"
    )


# ---------------------------------------------------------------------------
# Upsert function
# ---------------------------------------------------------------------------


def sync_showcase_page(site, dry_run: bool = False) -> str:
    """Upsert the ``Semantic:Showcase`` page on the wiki.

    Uses ``rstrip()`` comparison for idempotency (MediaWiki strips
    trailing whitespace on storage).

    Returns a status string: ``"created"``, ``"updated"``, ``"unchanged"``,
    ``"would-create"``, or ``"would-update"``.
    """
    page_title = "Semantic:Showcase"
    wikitext = showcase_page_wikitext()
    page = site.pages[page_title]

    if dry_run:
        if not page.exists:
            print(f"  {page_title}: would-create")
            return "would-create"
        current = page.text()
        if current.rstrip() == wikitext.rstrip():
            print(f"  {page_title}: unchanged")
            return "unchanged"
        print(f"  {page_title}: would-update")
        return "would-update"

    summary = "sync Semantic:Showcase page with 7 SMW queries"

    if not page.exists:
        page.edit(wikitext, summary=summary)
        print(f"  {page_title}: created")
        return "created"

    current = page.text()
    if current.rstrip() == wikitext.rstrip():
        print(f"  {page_title}: unchanged")
        return "unchanged"

    page.edit(wikitext, summary=summary)
    print(f"  {page_title}: updated")
    return "updated"
