"""wiki/sync/sync_filters.py — Phase 9.2

Idempotent upsert of Category:Card with {{#drilldowninfo:}} to drive
Special:BrowseData/Card faceted search. Single writer of Category:Card
(the entry was removed from fix_dead_links.py in Phase 9.2).

After a successful edit, runs an AUTHENTICATED null-edit of Category:Card
to invalidate the MediaWiki parser cache for the page (Phase 9.1 lesson:
action=purge is not enough to invalidate SMW #ask output).

CLI:
  python -m sync.sync_filters                # upsert
  python -m sync.sync_filters --dry-run      # print diff, no edit
  python -m sync.sync_filters --verify       # assert #drilldowninfo is live
"""

from __future__ import annotations

import argparse
import sys
from typing import Literal

from sync.client import get_site, MissingCredentialsError


CATEGORY_CARD_TITLE = "Category:Card"

CATEGORY_CARD_WIKITEXT = """This category contains all cards in [[Grid Tactics TCG]].

{{#drilldowninfo:
filters=Element (property=Element),
CardType (property=CardType),
Tribe (property=Tribe),
Mana Cost (property=ManaCost),
Attack (property=Attack),
HP (property=HP),
Range (property=Range),
Keyword (property=Keyword)
|display parameters=format=broadtable;?Element;?CardType;?ManaCost;?Attack;?HP;limit=50
}}

[[Category:Grid Tactics]]"""


def build_category_card_wikitext() -> str:
    """Pure function — returns the canonical Category:Card body for 9.2+."""
    return CATEGORY_CARD_WIKITEXT


def sync_drilldown_filters(
    site,
    dry_run: bool = False,
) -> Literal["unchanged", "updated", "would-update", "created", "would-create"]:
    """Upsert Category:Card with the 9.2 #drilldowninfo body.

    Idempotent: compares page.text().rstrip() == expected.rstrip() (same
    pattern as bootstrap_schema / bootstrap_template — MediaWiki strips the
    trailing newline on storage).

    After a successful non-dry-run edit, performs an authenticated null-edit
    to invalidate the parser cache (9.1 lesson).
    """
    expected = build_category_card_wikitext()
    page = site.pages[CATEGORY_CARD_TITLE]

    if page.exists:
        current = page.text()
        if current.rstrip() == expected.rstrip():
            return "unchanged"
        if dry_run:
            return "would-update"
        page.edit(expected, summary="sync_filters: install #drilldowninfo (Phase 9.2)")
        # Authenticated null-edit to invalidate parser cache.
        # Re-fetch and re-save identical content — MediaWiki treats identical-content
        # edits as no-ops in the revision table but DOES invalidate parser cache.
        page2 = site.pages[CATEGORY_CARD_TITLE]
        page2.edit(page2.text(), summary="sync_filters: null-edit to invalidate parser cache")
        return "updated"

    if dry_run:
        return "would-create"
    page.edit(expected, summary="sync_filters: create Category:Card with #drilldowninfo (Phase 9.2)")
    return "created"


def verify_drilldowninfo_live(site) -> bool:
    """Assert Category:Card's live wikitext contains our #drilldowninfo block.

    Returns True if present with expected filter list, False otherwise.
    """
    page = site.pages[CATEGORY_CARD_TITLE]
    if not page.exists:
        print(f"ERROR: {CATEGORY_CARD_TITLE} does not exist", file=sys.stderr)
        return False
    text = page.text()
    required_markers = [
        "#drilldowninfo",
        "property=Element",
        "property=CardType",
        "property=Tribe",
        "property=ManaCost",
        "property=Attack",
        "property=HP",
        "property=Range",
        "property=Keyword",
    ]
    missing = [m for m in required_markers if m not in text]
    if missing:
        print(f"ERROR: Category:Card missing markers: {missing}", file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 9.2: upsert Category:Card #drilldowninfo")
    parser.add_argument("--dry-run", action="store_true", help="print diff, make no edits")
    parser.add_argument("--verify", action="store_true", help="assert #drilldowninfo is live")
    args = parser.parse_args(argv)

    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.verify:
        ok = verify_drilldowninfo_live(site)
        print(f"verify: {'OK' if ok else 'FAIL'}")
        return 0 if ok else 1

    status = sync_drilldown_filters(site, dry_run=args.dry_run)
    print(f"Category:Card: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
