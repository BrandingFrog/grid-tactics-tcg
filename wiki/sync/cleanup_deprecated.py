"""One-shot audit tool: move stale Card: pages out of Category:Card.

Identifies pages in Category:Card on the live wiki that aren't backed by
a JSON in ``data/cards/``. For each such page:

- If the card was renamed (we know the new name), overwrite with a
  ``#REDIRECT [[Card:NewName]]`` so links still resolve.
- Otherwise, ensure the existing {{Card|...}} invocation carries
  ``| deprecated = 1`` so the updated Card template categorizes it
  under ``Category:Deprecated`` instead of ``Category:Card``.

Also upserts the updated Card / DeprecatedCard templates from local
``wiki/sync/templates/`` so the category swap takes effect.

Usage::

    cd wiki
    python -m sync.cleanup_deprecated              # live edits
    python -m sync.cleanup_deprecated --dry-run    # preview
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from sync.client import MissingCredentialsError, get_site

# Known renames: {old page name: new page name}
RENAMES = {
    "Card:Illicit Stones": "Card:Illicit Shadow Stones",
    "Card:Surgefed Sparkbot": "Card:Sparkfed Surgebot",
}

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _active_card_names(cards_dir: Path) -> set[str]:
    names: set[str] = set()
    for p in sorted(cards_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            name = data.get("name")
            if name:
                names.add(name)
        except (json.JSONDecodeError, OSError):
            continue
    return names


def _upsert_template(site, title: str, path: Path) -> str:
    expected = path.read_text(encoding="utf-8")
    page = site.pages[title]
    if page.exists and page.text().rstrip() == expected.rstrip():
        return "unchanged"
    page.edit(expected, summary=f"cleanup: refresh {title}")
    return "updated" if page.exists else "created"


def _find_card_block(wikitext: str) -> tuple[int, int] | None:
    """Locate the outer {{Card ... }} invocation, tolerating nested {{!}}
    and other templates inside parameters (which break simple regexes).

    Returns (start_idx, end_idx) pointing at the opening ``{{`` and the
    char after the matching ``}}``. None if no Card block found.
    """
    m = re.search(r"\{\{\s*Card\b", wikitext)
    if not m:
        return None
    start = m.start()
    depth = 0
    i = start
    while i < len(wikitext) - 1:
        if wikitext[i:i + 2] == "{{":
            depth += 1
            i += 2
        elif wikitext[i:i + 2] == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return (start, i)
        else:
            i += 1
    return None


def _apply_deprecated_flag(wikitext: str) -> str:
    """Return wikitext where the {{Card|...}} invocation has ``deprecated = 1``.

    Idempotent: returns wikitext unchanged if the flag is already set on
    the Card template (not on {{DeprecatedCard|patch=...}}, which is a
    different template call).
    """
    pos = _find_card_block(wikitext)
    if pos is None:
        return wikitext
    start, end = pos
    block = wikitext[start:end]
    if re.search(r"\|\s*deprecated\s*=\s*1", block):
        return wikitext
    # Insert ``| deprecated = 1`` right before the closing ``}}``.
    closing = block.rfind("}}")
    new_block = block[:closing] + "| deprecated = 1\n" + block[closing:]
    return wikitext[:start] + new_block + wikitext[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent.parent
    cards_dir = repo_root / "data" / "cards"

    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # Step 1: refresh templates so the category-swap behavior lands first.
    if args.dry_run:
        print("Would upsert Template:Card and Template:DeprecatedCard.")
    else:
        for title, filename in (
            ("Template:Card", "Card.wiki"),
            ("Template:DeprecatedCard", "DeprecatedCard.wiki"),
        ):
            status = _upsert_template(site, title, _TEMPLATES_DIR / filename)
            print(f"  {title}: {status}")

    # Step 2: find all stale Card: pages (on wiki, not in data/cards).
    active_names = _active_card_names(cards_dir)
    cat = site.categories["Card"]
    wiki_titles = {p.name for p in cat if p.name.startswith("Card:")}

    stale: list[str] = []
    for title in sorted(wiki_titles):
        name = title[len("Card:"):]
        if name not in active_names:
            stale.append(title)

    print(f"\n{len(stale)} stale Card: pages detected.")

    for title in stale:
        page = site.pages[title]
        if not page.exists:
            print(f"  {title}: (missing, skipping)")
            continue

        if title in RENAMES:
            new_target = RENAMES[title]
            new_text = f"#REDIRECT [[{new_target}]]\n"
            if args.dry_run:
                print(f"  {title}: would redirect -> {new_target}")
                continue
            page.edit(new_text, summary=f"cleanup: redirect {title} -> {new_target}")
            print(f"  {title}: redirected -> {new_target}")
            continue

        current = page.text()
        new_text = _apply_deprecated_flag(current)
        if new_text == current:
            print(f"  {title}: already flagged (no-op)")
            continue
        if args.dry_run:
            print(f"  {title}: would add ``deprecated = 1``")
            continue
        page.edit(
            new_text,
            summary="cleanup: flag deprecated so page leaves Category:Card",
        )
        print(f"  {title}: updated (deprecated flag added)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
