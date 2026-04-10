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

import hashlib
import json
from datetime import date
from pathlib import Path


def _pick_card_of_the_day(cards_dir: Path | None = None) -> dict | None:
    """Pick a deterministic random card based on today's date.

    Uses a hash of the date string to seed selection so every viewer
    sees the same card on the same day, and it rotates at midnight.
    Only deckable cards are eligible.
    """
    if cards_dir is None:
        cards_dir = Path(__file__).resolve().parent.parent.parent / "data" / "cards"
    if not cards_dir.exists():
        return None

    cards = []
    for f in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(f.read_text(encoding="utf-8"))
            if card.get("deckable", True):
                cards.append(card)
        except (json.JSONDecodeError, KeyError):
            continue

    if not cards:
        return None

    today = date.today().isoformat()
    h = int(hashlib.sha256(today.encode()).hexdigest(), 16)
    return cards[h % len(cards)]


def main_page_wikitext(cards_dir: Path | None = None) -> str:
    """Return the wikitext for the wiki Main Page.

    The Main Page serves as the entry point with navigation links to all
    major index pages created in Phases 3-6. Includes a Card of the Day
    section that rotates daily.
    """
    # Card of the Day
    cotd = _pick_card_of_the_day(cards_dir)
    if cotd:
        card_name = cotd.get("name", "Unknown")
        card_id = cotd.get("card_id", "")
        card_type = cotd.get("card_type", "").capitalize()
        element = cotd.get("element", "").capitalize()
        tribe = cotd.get("tribe", "")
        mana = cotd.get("mana_cost", "?")
        attack = cotd.get("attack")
        health = cotd.get("health")
        atk_range = cotd.get("range")

        # Build metadata rows
        _rs = 'style="padding:4px 10px; background:#222; text-align:left; color:#888; font-weight:normal; font-size:0.85em;"'
        _vs = 'style="padding:4px 10px; background:#222;"'
        meta = ""
        meta += f'|-\n! {_rs} | Type\n| {_vs} | [[{card_type}]]\n'
        if element:
            meta += f'|-\n! {_rs} | Element\n| {_vs} | [[{element}]]\n'
        if tribe:
            tribe_links = "<br/>".join(f"[[{t}]]" for t in tribe.split())
            meta += f'|-\n! {_rs} | Tribe\n| {_vs} | {tribe_links}\n'
        meta += f'|-\n! {_rs} | Mana\n| {_vs} | {mana}\n'
        if atk_range is not None:
            range_text = "[[Melee]]" if atk_range == 0 else f"[[Ranged|Range {atk_range}]]"
            meta += f'|-\n! {_rs} | Range\n| {_vs} | {range_text}\n'

        # ATK/HP row for minions
        atk_hp_row = ""
        if attack is not None and health is not None:
            atk_hp_row = (
                f'|-\n'
                f'! style="padding:6px 10px; background:#111; text-align:left; '
                f"font-family:'Montserrat',sans-serif; font-weight:900; text-transform:uppercase; "
                f'-webkit-text-stroke:1px black; paint-order:stroke fill; font-size:1.1em;" '
                f'| {attack}\U0001f5e1\ufe0f\n'
                f'! style="padding:6px 10px; background:#111; text-align:right; '
                f"font-family:'Montserrat',sans-serif; font-weight:900; text-transform:uppercase; "
                f'-webkit-text-stroke:1px black; paint-order:stroke fill; font-size:1.1em;" '
                f'| {health}\U0001f90d\n'
            )

        # Element colour
        _elem_colours = {
            "Wood": "rgb(102,187,106)", "Fire": "rgb(220,40,30)",
            "Earth": "rgb(140,100,40)", "Water": "rgb(66,165,245)",
            "Metal": "rgb(189,189,189)", "Dark": "rgb(130,50,180)",
            "Light": "rgb(240,220,40)",
        }
        elem_bg = _elem_colours.get(element, "rgb(128,128,128)")

        cotd_section = (
            f'== Card of the Day ==\n'
            f'<div style="display:flex; justify-content:center; margin-bottom:1em;">\n'
            f'{{| style="width:280px; border:2px solid #222; border-radius:10px; '
            f'background:#1a1a1a; color:#eee; font-family:sans-serif;"\n'
            f'|-\n'
            f'! colspan="2" style="padding:6px 10px; background:linear-gradient(90deg,#333,#111); '
            f'border-radius:8px 8px 0 0; text-align:center; position:relative;" | '
            f'<span style="position:absolute; left:10px; top:50%; transform:translateY(-50%); '
            f"background:rgb(30,100,220); border-radius:50%; width:28px; height:28px; "
            f"display:inline-block; text-align:center; line-height:28px; "
            f"font-family:'Montserrat',sans-serif; font-weight:900; text-transform:uppercase; "
            f'-webkit-text-stroke:1px black; paint-order:stroke fill;">{mana}</span> '
            f"<span style=\"font-size:1.2em; font-family:'Source Sans 3','Source Sans Pro',sans-serif; "
            f'font-weight:700; -webkit-text-stroke:1px black; paint-order:stroke fill;\">'
            f'[[Card:{card_name}|{card_name}]]</span> '
            f'<span style="position:absolute; right:10px; top:50%; transform:translateY(-50%); '
            f'background:{elem_bg}; border-radius:50%; width:28px; height:28px; '
            f'display:inline-block; text-align:center; line-height:28px; font-weight:bold; '
            f'font-size:0.7em;">{element}</span>\n'
            f'|-\n'
            f'| colspan="2" style="padding:0;" | [[File:{card_id}.png|280px|center|link=Card:{card_name}]]\n'
            f'{meta}'
            f'{atk_hp_row}'
            f'|}}\n'
            f'</div>\n'
            f'\n'
        )
    else:
        cotd_section = ""

    return (
        "= Welcome to the Grid Tactics Wiki =\n"
        "This is the knowledge base for '''Grid Tactics TCG''', a fantasy "
        "trading card game played on a 5x5 grid. Here you'll find cards, "
        "mechanics, element interactions, and patch history.\n"
        "\n"
        + cotd_section +
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
        "* [[Deck Building Guide]] -- Archetypes and strategy\n"
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
