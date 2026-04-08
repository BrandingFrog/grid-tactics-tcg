"""
Bootstrap SMW Property: pages on the Grid Tactics Wiki.

Reads :data:`sync.schema.PROPERTIES` + :data:`sync.schema.EFFECT_SUBPROPERTIES`
and creates / updates the corresponding ``Property:<Name>`` page for each entry
via the authenticated mwclient bot.

Idempotent: the script compares the current page text against the canonical
wikitext from :func:`sync.schema.property_wikitext` and skips pages that are
already up to date. Running twice in a row produces zero edits on the second
run.

Usage:
    cd wiki
    python -m sync.bootstrap_schema
"""

from __future__ import annotations

import sys
import time
from typing import Iterable

import mwclient.errors

from sync.client import MissingCredentialsError, get_site
from sync.schema import (
    EFFECT_SUBPROPERTIES,
    PROPERTIES,
    PropertySpec,
    property_wikitext,
)

EDIT_SUMMARY = "bootstrap schema from wiki/sync/schema.py"

# SMW briefly locks Property: pages while it propagates schema changes. Retry
# a small number of times with backoff before giving up.
_PROPAGATION_RETRIES = 6
_PROPAGATION_BACKOFF_SECONDS = 5


def _all_specs() -> Iterable[PropertySpec]:
    yield from PROPERTIES
    yield from EFFECT_SUBPROPERTIES


def _same_text(current: str, expected: str) -> bool:
    """Compare ignoring trailing whitespace.

    MediaWiki strips the final newline on storage, so an exact ``==`` check
    against our canonical (newline-terminated) wikitext would falsely report
    "updated" forever. Normalize both sides to make the bootstrap idempotent.
    """
    return current.rstrip() == expected.rstrip()


def _edit_with_retry(page, text: str, summary: str) -> None:
    """Edit a page, retrying on SMW change-propagation locks."""
    for attempt in range(_PROPAGATION_RETRIES):
        try:
            page.edit(text, summary=summary)
            return
        except mwclient.errors.APIError as exc:
            if exc.code == "smw-change-propagation-protection":
                wait = _PROPAGATION_BACKOFF_SECONDS * (attempt + 1)
                print(
                    f"  (change-propagation lock on {page.name}, "
                    f"sleeping {wait}s — attempt {attempt + 1}/{_PROPAGATION_RETRIES})"
                )
                time.sleep(wait)
                continue
            raise
    raise RuntimeError(
        f"SMW change-propagation lock never cleared for {page.name}"
    )


def main() -> int:
    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    created = 0
    updated = 0
    unchanged = 0

    for spec in _all_specs():
        name = spec["name"]
        expected = property_wikitext(
            name,
            spec["type"],
            spec["description"],
            spec.get("allowed_values"),
        )
        page = site.pages[f"Property:{name}"]
        if not page.exists:
            _edit_with_retry(page, expected, EDIT_SUMMARY)
            print(f"created: Property:{name}")
            created += 1
            continue

        current = page.text()
        if _same_text(current, expected):
            print(f"unchanged: Property:{name}")
            unchanged += 1
        else:
            _edit_with_retry(page, expected, EDIT_SUMMARY)
            print(f"updated: Property:{name}")
            updated += 1

    total = created + updated + unchanged
    print(
        f"\nSummary: {created} created, {updated} updated, {unchanged} unchanged "
        f"({total} total)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
