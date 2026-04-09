"""
Main Page wikitext generation and upsert for the Grid Tactics Wiki.

Generates the wiki's Main Page with navigation links to all major index
pages (elements, tribes, keywords, rules, patches, card database).

Usage::

    from sync.sync_homepage import sync_main_page
    from sync.client import get_site

    site = get_site()
    sync_main_page(site)
"""

from __future__ import annotations


def main_page_wikitext() -> str:
    """Return the wikitext for the wiki Main Page.

    The Main Page serves as the entry point with navigation links to all
    major index pages created in Phases 3-6.
    """
    return (
        "= Welcome to the Grid Tactics Wiki =\n"
        "This is the knowledge base for '''Grid Tactics TCG''', a fantasy "
        "trading card game played on a 5x5 grid. Here you'll find cards, "
        "mechanics, element interactions, and patch history.\n"
        "\n"
        "== Card Database ==\n"
        "* [[:Category:Card|All Cards]] -- Browse every card in the game\n"
        "* [[Semantic:Showcase|Semantic Queries]] -- Explore cards with "
        "advanced queries\n"
        "\n"
        "== Elements ==\n"
        "[[Wood]] | [[Fire]] | [[Earth]] | [[Water]] | [[Metal]] | "
        "[[Dark]] | [[Light]]\n"
        "\n"
        "* [[:Category:Element|All Elements]]\n"
        "\n"
        "== Tribes ==\n"
        "* [[:Category:Tribe|All Tribes]]\n"
        "\n"
        "== Keywords ==\n"
        "* [[:Category:Keyword|All Keywords]]\n"
        "* [[:Category:Trigger Keyword|Trigger Keywords]]\n"
        "* [[:Category:Mechanic Keyword|Mechanic Keywords]]\n"
        "\n"
        "== Rules ==\n"
        "* [[Grid Tactics TCG]] -- Game overview\n"
        "* [[5x5 Board]] -- Board layout and movement\n"
        "* [[Mana]] -- Resource system\n"
        "* [[React Window]] -- Counter-play mechanic\n"
        "* [[Win Conditions]] -- How to win\n"
        "* [[Turn Structure]] -- Turn phases\n"
        "\n"
        "== Patch Notes ==\n"
        "* [[Patch:Index]] -- All patch notes\n"
        "\n"
        "[[Category:Rules]]"
    )


def sync_main_page(site, dry_run: bool = False) -> str:
    """Upsert the Main Page on the wiki.

    Uses ``rstrip()`` comparison for idempotency (MediaWiki strips
    trailing whitespace on storage).

    Returns ``"created"``, ``"updated"``, or ``"unchanged"``.
    """
    wikitext = main_page_wikitext()
    page = site.pages["Main Page"]

    if dry_run:
        if not page.exists:
            print("  Main Page: would-create")
            return "would-create"
        current = page.text()
        if current.rstrip() == wikitext.rstrip():
            print("  Main Page: unchanged")
            return "unchanged"
        print("  Main Page: would-update")
        return "would-update"

    summary = "sync Main Page from sync_homepage.py"

    if not page.exists:
        page.edit(wikitext, summary=summary)
        print("  Main Page: created")
        return "created"

    current = page.text()
    if current.rstrip() == wikitext.rstrip():
        print("  Main Page: unchanged")
        return "unchanged"

    page.edit(wikitext, summary=summary)
    print("  Main Page: updated")
    return "updated"
