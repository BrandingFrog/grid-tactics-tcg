"""One-shot fix: create missing pages that cause red/dead links on the wiki.

Creates:
- Template:ManuallyMaintained
- Category description pages (Card, Element, Keyword, Tribe, Mechanic Keyword, Trigger Keyword)
- Patch:Index (if missing)

Run from wiki/ directory:
    python -m sync.fix_dead_links
    python -m sync.fix_dead_links --dry-run
"""

from __future__ import annotations

import sys
from pathlib import Path

from sync.client import MissingCredentialsError, get_site

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


# ---------------------------------------------------------------------------
# Template:ManuallyMaintained
# ---------------------------------------------------------------------------

def bootstrap_manually_maintained(site, dry_run: bool = False) -> str:
    """Upsert Template:ManuallyMaintained (idempotent)."""
    template_path = _TEMPLATES_DIR / "ManuallyMaintained.wiki"
    expected = template_path.read_text(encoding="utf-8")
    page = site.pages["Template:ManuallyMaintained"]
    if page.exists:
        current = page.text()
        if current.rstrip() == expected.rstrip():
            return "unchanged"
        if dry_run:
            return "would-update"
        page.edit(expected, summary="bootstrap Template:ManuallyMaintained")
        return "updated"
    if dry_run:
        return "would-create"
    page.edit(expected, summary="bootstrap Template:ManuallyMaintained")
    return "created"


# ---------------------------------------------------------------------------
# Category description pages
# ---------------------------------------------------------------------------

CATEGORY_PAGES: dict[str, str] = {
    # NOTE: Category:Card is owned by sync/sync_filters.py as of Phase 9.2.
    # Do NOT re-add it here — single-writer invariant. sync_filters.py upserts
    # Category:Card with a {{#drilldowninfo:}} body that drives
    # Special:BrowseData/Card faceted search.
    "Category:Element": (
        "This category lists the seven elements in [[Grid Tactics TCG]]: "
        "Wood, Fire, Earth, Water, Metal, Dark, and Light.\n"
        "\n"
        "[[Category:Grid Tactics]]"
    ),
    "Category:Keyword": (
        "This category lists all gameplay keywords in [[Grid Tactics TCG]].\n"
        "\n"
        "See also:\n"
        "* [[:Category:Trigger Keyword|Trigger Keywords]]\n"
        "* [[:Category:Mechanic Keyword|Mechanic Keywords]]\n"
        "\n"
        "[[Category:Grid Tactics]]"
    ),
    "Category:Tribe": (
        "This category lists all creature tribes in [[Grid Tactics TCG]].\n"
        "\n"
        "[[Category:Grid Tactics]]"
    ),
    "Category:Mechanic Keyword": (
        "This category lists mechanic keywords in [[Grid Tactics TCG]]. "
        "Mechanic keywords describe persistent abilities or effects "
        "that a card possesses.\n"
        "\n"
        "[[Category:Keyword]]"
    ),
    "Category:Trigger Keyword": (
        "This category lists trigger keywords in [[Grid Tactics TCG]]. "
        "Trigger keywords fire when a specific game event occurs.\n"
        "\n"
        "[[Category:Keyword]]"
    ),
}


def create_category_pages(site, dry_run: bool = False) -> dict[str, str]:
    """Create category description pages (idempotent)."""
    results: dict[str, str] = {}
    for title, wikitext in sorted(CATEGORY_PAGES.items()):
        page = site.pages[title]
        if page.exists:
            current = page.text()
            if current.rstrip() == wikitext.rstrip():
                results[title] = "unchanged"
                continue
            if dry_run:
                results[title] = "would-update"
                continue
            page.edit(wikitext, summary=f"create {title} description page")
            results[title] = "updated"
        else:
            if dry_run:
                results[title] = "would-create"
                continue
            page.edit(wikitext, summary=f"create {title} description page")
            results[title] = "created"
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    dry_run = "--dry-run" in sys.argv

    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    dry_label = " (dry run)" if dry_run else ""
    print(f"Fixing dead links{dry_label}...\n")

    # 1. Template:ManuallyMaintained
    print("=== Template:ManuallyMaintained ===")
    status = bootstrap_manually_maintained(site, dry_run=dry_run)
    print(f"  Template:ManuallyMaintained: {status}")

    # 2. Patch:0.3.82 (initial card pool patch page)
    print("\n=== Patch:0.3.82 ===")
    patch_page = site.pages["Patch:0.3.82"]
    if patch_page.exists:
        print("  Patch:0.3.82: already exists")
    elif dry_run:
        print("  Patch:0.3.82: would-create")
    else:
        patch_wikitext = (
            "{{Patch\n"
            "|version=0.3.82\n"
            "|date=2026-04-09\n"
            "}}\n"
            "\n"
            "Patch '''0.3.82''' established the initial card pool "
            "for [[Grid Tactics TCG]].\n"
            "\n"
            "== Summary ==\n"
            "All 34 cards were tagged with this version as their "
            "initial patch on the wiki.\n"
            "\n"
            "[[Category:Patch]]"
        )
        patch_page.edit(patch_wikitext, summary="create initial card pool patch page")
        print("  Patch:0.3.82: created")

    # 3. Patch:Index
    print("\n=== Patch:Index ===")
    idx_page = site.pages["Patch:Index"]
    if idx_page.exists:
        print("  Patch:Index: already exists")
    elif dry_run:
        print("  Patch:Index: would-create")
    else:
        from sync.sync_patches import sync_patch_index
        _repo_root = Path(__file__).resolve().parent.parent.parent
        idx_status = sync_patch_index(site, _repo_root, dry_run=False)
        print(f"  Patch:Index: {idx_status}")

    # 4. Category pages
    print("\n=== Category Pages ===")
    cat_results = create_category_pages(site, dry_run=dry_run)
    for title, status in cat_results.items():
        print(f"  {title}: {status}")

    print(f"\nDone.{dry_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
