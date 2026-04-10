"""
Create the Phase 1 sample card page Card:Ratchanter on the wiki.

Purpose: prove the full Phase 1 pipeline end-to-end — Template:Card renders an
infobox and emits SMW annotations, and an ``#ask`` query for the card's type
returns this page with the expected property values. This is the **only**
hand-crafted card page in Phase 1; Phase 3's ``sync_cards.py`` will generate
real card pages from ``data/cards/*.json`` automatically.

Values are populated from ``data/cards/minion_ratchanter.json``. Effects and
subobjects are intentionally NOT emitted here — those get exercised in Phase 3
against the real sync path.

Usage:
    cd wiki
    python -m sync.create_sample_card
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sync.client import MissingCredentialsError, get_site

PAGE_TITLE = "Card:Ratchanter"
EDIT_SUMMARY = "create Phase 1 sample card (Card:Ratchanter) via Template:Card"

# data/cards/ lives two levels up from wiki/sync/
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CARD_JSON = _REPO_ROOT / "data" / "cards" / "minion_ratchanter.json"


def _load_card() -> dict:
    if not _CARD_JSON.exists():
        raise FileNotFoundError(
            f"Ratchanter card JSON not found at {_CARD_JSON}. "
            "This script sources real values from data/cards/."
        )
    return json.loads(_CARD_JSON.read_text(encoding="utf-8"))


def _build_wikitext(card: dict) -> str:
    # Normalize element/card_type to TitleCase for SMW Page-type consistency.
    element = str(card.get("element", "")).strip().capitalize()
    card_type = str(card.get("card_type", "")).strip().capitalize()

    # Ratchanter's JSON has no rules_text / flavor_text / keywords fields.
    # Synthesize a rules line from the activated_ability so the infobox has
    # something to show, and populate flavor + keywords from the Phase 1 plan.
    ability = card.get("activated_ability") or {}
    if ability:
        rules = (
            f"Activated: pay {ability.get('mana_cost', 0)} mana to "
            f"{ability.get('name', 'activate')}."
        )
    else:
        rules = card.get("rules_text", "")

    flavor = "The rats listen, and the rats remember."
    keywords = "Sacrifice, Summon"

    fields = {
        "name": card["name"],
        "type": card_type,
        "element": element,
        "tribe": card.get("tribe", ""),
        "cost": card.get("mana_cost", ""),
        "attack": card.get("attack", ""),
        "hp": card.get("health", ""),
        "range": card.get("range", ""),
        "rules": rules,
        "flavor": flavor,
        "keywords": keywords,
        "art": "Ratchanter.png",
        "patch": "0.4.2",
        "stable_id": card.get("card_id", ""),
        "deckable": "true",
    }

    body_lines = ["{{Card"]
    for key, value in fields.items():
        body_lines.append(f"| {key:9s}= {value}")
    body_lines.append("}}")
    body_lines.append("")
    body_lines.append("== Notes ==")
    body_lines.append(
        "This page is a Phase 1 sample created by "
        "`wiki/sync/create_sample_card.py`. It is NOT generated from "
        "`data/cards/` automatically — Phase 3 `sync_cards.py` will replace it."
    )
    body_lines.append("")
    body_lines.append("[[Category:Cards]]")
    body_lines.append("")
    return "\n".join(body_lines)


def _same_text(current: str, expected: str) -> bool:
    return current.rstrip() == expected.rstrip()


def _verify_via_ask(site, card: dict) -> bool:
    """Run an #ask query and assert Ratchanter comes back with expected values."""
    query = "[[CardType::Minion]][[Element::Dark]]|?ManaCost|?HP|limit=25"
    print(f"\nVerifying via ask: {query}")
    expected_cost = card.get("mana_cost")
    expected_hp = card.get("health")
    found = False
    # mwclient yields flat dicts shaped like
    #   {"fulltext": "Card:Ratchanter", "printouts": {"ManaCost": [4], "HP": [30]}}
    for result in site.ask(query):
        title = result.get("fulltext") if isinstance(result, dict) else None
        if title != PAGE_TITLE:
            continue
        printouts = result.get("printouts", {})
        cost_vals = printouts.get("ManaCost", [])
        hp_vals = printouts.get("HP", [])
        print(f"  found {title}: ManaCost={cost_vals}, HP={hp_vals}")
        # SMW may return plain numbers OR OrderedDicts with a "fulltext" key
        # depending on MediaWiki/SMW version. Normalize to string for comparison.
        def _smw_val(v):
            if isinstance(v, dict):
                return v.get("fulltext", v)
            return v

        if (
            cost_vals
            and hp_vals
            and float(_smw_val(cost_vals[0])) == float(expected_cost)
            and float(_smw_val(hp_vals[0])) == float(expected_hp)
        ):
            found = True
    return found


def main() -> int:
    try:
        card = _load_card()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    wikitext = _build_wikitext(card)

    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    page = site.pages[PAGE_TITLE]
    if not page.exists:
        page.edit(wikitext, summary=EDIT_SUMMARY)
        print(f"created: {PAGE_TITLE}")
    else:
        current = page.text()
        if _same_text(current, wikitext):
            print(f"unchanged: {PAGE_TITLE}")
        else:
            page.edit(wikitext, summary=EDIT_SUMMARY)
            print(f"updated: {PAGE_TITLE}")

    # Best-effort subobject sanity check (expected empty for this sample).
    try:
        sub_results = list(site.ask(f"[[-Has subobject::{PAGE_TITLE}]]"))
        print(
            f"subobject sanity: {len(sub_results)} subobject(s) "
            f"(expected 0 for Phase 1 sample)"
        )
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"note: subobject ask failed ({exc}) — non-fatal")

    ok = _verify_via_ask(site, card)
    url = "http://localhost:8080/wiki/Card:Ratchanter"
    print(f"\nSample page URL: {url}")
    if ok:
        print("PASS: #ask query returned Ratchanter with expected Cost and HP.")
        return 0
    print(
        "FAIL: #ask query did not return Ratchanter with expected values. "
        "Check the Factbox at the bottom of the page and re-run."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
