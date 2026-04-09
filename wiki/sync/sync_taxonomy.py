"""
Taxonomy page wikitext generation and upsert logic.

Generates and syncs element and tribe category pages to the Grid Tactics
wiki.  Each page contains an ``{{#ask:}}`` SMW query that auto-lists member
cards, so pages stay current as cards are added or changed.

Pure-function generators (no wiki connection) are separated from the
upsert logic so they can be unit-tested offline.

Usage::

    from pathlib import Path
    from sync.sync_taxonomy import sync_elements, sync_tribes
    from sync.client import get_site

    site = get_site()
    sync_elements(site, Path("../data/cards"))
    sync_tribes(site, Path("../data/cards"))
"""

from __future__ import annotations

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Data scanning functions
# ---------------------------------------------------------------------------


def scan_elements(cards_dir: Path) -> list[str]:
    """Scan all card JSONs and return sorted unique element values (title-cased)."""
    elements: set[str] = set()
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            elem = card.get("element", "")
            if elem:
                elements.add(elem.title())
        except (json.JSONDecodeError, KeyError):
            continue
    return sorted(elements)


def scan_tribes(cards_dir: Path) -> list[str]:
    """Scan all card JSONs and return sorted unique tribe values."""
    tribes: set[str] = set()
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            tribe = card.get("tribe", "")
            if tribe:
                tribes.add(tribe)
        except (json.JSONDecodeError, KeyError):
            continue
    return sorted(tribes)


# ---------------------------------------------------------------------------
# Wikitext generation (pure functions, no wiki connection)
# ---------------------------------------------------------------------------


def element_page_wikitext(element: str) -> str:
    """Generate wikitext for an element category page.

    The page includes an ``{{#ask:}}`` query that lists all cards with
    this element, displayed as a broadtable.
    """
    return (
        f"'''{element}''' is one of seven elements in [[Grid Tactics TCG]].\n"
        f"\n"
        f"== Cards ==\n"
        f"{{{{#ask:\n"
        f" [[Category:Card]]\n"
        f" [[Element::{element}]]\n"
        f" |?Cost\n"
        f" |?Attack\n"
        f" |?HP\n"
        f" |?Tribe\n"
        f" |format=broadtable\n"
        f" |limit=50\n"
        f" |sort=Name\n"
        f"}}}}\n"
        f"\n"
        f"[[Category:Element]]"
    )


def tribe_page_wikitext(tribe: str) -> str:
    """Generate wikitext for a tribe category page.

    The page includes an ``{{#ask:}}`` query that lists all cards with
    this tribe, displayed as a broadtable.
    """
    return (
        f"'''{tribe}''' is a tribe in [[Grid Tactics TCG]].\n"
        f"\n"
        f"== Members ==\n"
        f"{{{{#ask:\n"
        f" [[Category:Card]]\n"
        f" [[Tribe::{tribe}]]\n"
        f" |?Cost\n"
        f" |?Element\n"
        f" |?Attack\n"
        f" |?HP\n"
        f" |format=broadtable\n"
        f" |limit=50\n"
        f" |sort=Name\n"
        f"}}}}\n"
        f"\n"
        f"[[Category:Tribe]]"
    )


# ---------------------------------------------------------------------------
# Upsert function
# ---------------------------------------------------------------------------


def upsert_taxonomy_pages(
    site,
    pages: dict[str, str],
    dry_run: bool = False,
) -> dict[str, int]:
    """Upsert a dict of ``{page_title: wikitext}`` to the wiki.

    Uses ``rstrip()`` comparison for idempotency (MediaWiki strips
    trailing whitespace on storage).

    Returns counts dict ``{"created": N, "updated": N, "unchanged": N}``.
    """
    counts = {"created": 0, "updated": 0, "unchanged": 0}

    for title, wikitext in sorted(pages.items()):
        page = site.pages[title]

        if dry_run:
            if not page.exists:
                counts["created"] += 1
                print(f"  {title}: would-create")
            elif page.text().rstrip() == wikitext.rstrip():
                counts["unchanged"] += 1
                print(f"  {title}: unchanged")
            else:
                counts["updated"] += 1
                print(f"  {title}: would-update")
            continue

        summary = f"sync taxonomy page: {title}"

        if not page.exists:
            page.edit(wikitext, summary=summary)
            counts["created"] += 1
            print(f"  {title}: created")
        elif page.text().rstrip() == wikitext.rstrip():
            counts["unchanged"] += 1
            print(f"  {title}: unchanged")
        else:
            page.edit(wikitext, summary=summary)
            counts["updated"] += 1
            print(f"  {title}: updated")

    return counts


# ---------------------------------------------------------------------------
# Orchestration functions
# ---------------------------------------------------------------------------


def sync_elements(
    site,
    cards_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Scan elements from card JSONs and upsert element pages to the wiki."""
    elements = scan_elements(cards_dir)
    print(f"Found {len(elements)} elements: {', '.join(elements)}")

    pages = {elem: element_page_wikitext(elem) for elem in elements}
    return upsert_taxonomy_pages(site, pages, dry_run=dry_run)


def sync_tribes(
    site,
    cards_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Scan tribes from card JSONs and upsert tribe pages to the wiki."""
    tribes = scan_tribes(cards_dir)
    print(f"Found {len(tribes)} tribes: {', '.join(tribes)}")

    pages = {tribe: tribe_page_wikitext(tribe) for tribe in tribes}
    return upsert_taxonomy_pages(site, pages, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from sync.client import get_site

    cards_dir = _REPO_ROOT / "data" / "cards"
    site = get_site()

    print("=== Elements ===")
    elem_counts = sync_elements(site, cards_dir)
    print(f"Elements: {elem_counts}")

    print("\n=== Tribes ===")
    tribe_counts = sync_tribes(site, cards_dir)
    print(f"Tribes: {tribe_counts}")
