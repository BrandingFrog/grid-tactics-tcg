"""
Bootstrap Template:Card on the Grid Tactics Wiki.

Reads ``wiki/sync/templates/Card.wiki`` from disk and uploads it to the
``Template:Card`` page via the authenticated mwclient bot. Idempotent:
compares the current page text to the on-disk wikitext (with ``rstrip``
normalization for MediaWiki's trailing-newline strip) and skips the edit
when they match.

Usage:
    cd wiki
    python -m sync.bootstrap_template
"""

from __future__ import annotations

import sys
from pathlib import Path

from sync.client import MissingCredentialsError, get_site

TEMPLATE_PAGE = "Template:Card"
TEMPLATE_FILE = Path(__file__).resolve().parent / "templates" / "Card.wiki"
EDIT_SUMMARY = "bootstrap Template:Card from phase 1 (wiki/sync/templates/Card.wiki)"


def _same_text(current: str, expected: str) -> bool:
    return current.rstrip() == expected.rstrip()


def main() -> int:
    if not TEMPLATE_FILE.exists():
        print(f"ERROR: template file not found: {TEMPLATE_FILE}", file=sys.stderr)
        return 2

    expected = TEMPLATE_FILE.read_text(encoding="utf-8")

    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    page = site.pages[TEMPLATE_PAGE]
    if not page.exists:
        page.edit(expected, summary=EDIT_SUMMARY)
        print(f"created: {TEMPLATE_PAGE}")
        return 0

    current = page.text()
    if _same_text(current, expected):
        print(f"unchanged: {TEMPLATE_PAGE}")
        return 0

    page.edit(expected, summary=EDIT_SUMMARY)
    print(f"updated: {TEMPLATE_PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
