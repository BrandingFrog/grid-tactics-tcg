"""Force Category re-evaluation on deprecated Card pages.

MediaWiki caches the category list computed when a page was last edited.
If a page already had ``deprecated = 1`` but was rendered with the OLD
Card template (which unconditionally emitted ``[[Category:Card]]``),
updating the template does NOT auto-purge the cached categorylinks.

This script calls ``action=purge`` with ``forcelinkupdate=1`` on every
page currently in Category:Card that isn't backed by a JSON in
``data/cards/``, forcing the stale category to drop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sync.client import MissingCredentialsError, get_site


def main() -> int:
    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parent.parent.parent
    cards_dir = repo_root / "data" / "cards"
    active = {json.loads(p.read_text(encoding="utf-8"))["name"]
              for p in sorted(cards_dir.glob("*.json"))}

    cat = site.categories["Card"]
    stale = [p.name for p in cat
             if p.name.startswith("Card:")
             and p.name[len("Card:"):] not in active]

    print(f"{len(stale)} stale Card: pages to purge.")
    for title in stale:
        # forcelinkupdate re-evaluates {{!ifeq:}} categories from the
        # updated Card.wiki template. Without it the page keeps whatever
        # category was computed at last edit.
        result = site.api(
            "purge",
            titles=title,
            forcelinkupdate=1,
            token=site.get_token("csrf"),
        )
        purged = result.get("purge", [])
        ok = any(p.get("purged") is not None for p in purged)
        print(f"  {title}: {'purged' if ok else 'unknown'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
