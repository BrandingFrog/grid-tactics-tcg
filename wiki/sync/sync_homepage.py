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

from sync.sync_cards import build_rules_text


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

        # Build metadata rows — single colspan="3" cells with label+value
        _cs = 'style="padding:4px 10px; background:#222;"'
        _label = 'style="color:#888; font-size:0.85em;"'
        meta = ""
        meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Type</span> <span style="float:right;">[[{card_type}]]</span>\n'
        if element:
            meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Element</span> <span style="float:right;">[[{element}]]</span>\n'
        if tribe:
            tribe_links = "<br/>".join(f"[[{t}]]" for t in tribe.split())
            meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Tribe</span> <span style="float:right;">{tribe_links}</span>\n'
        meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Mana</span> <span style="float:right;">{mana}</span>\n'
        if atk_range is not None:
            range_text = "[[Melee]]" if atk_range == 0 else f"[[Ranged|Range {atk_range}]]"
            meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Range</span> <span style="float:right;">{range_text}</span>\n'

        # Rules text + flavour text row
        rules = build_rules_text(cotd)
        flavor = cotd.get("flavour_text", "")
        rules_row = ""
        if rules or flavor:
            text_parts = []
            if rules:
                text_parts.append(rules)
            if flavor:
                text_parts.append(
                    f'<hr style="border:0;border-top:1px dashed #555;"/>'
                    f'<span style="color:#888;font-style:italic;">{flavor}</span>'
                )
            rules_row = (
                f'|-\n'
                f'| colspan="3" style="padding:8px 10px; min-height:60px;" '
                f'| {"".join(text_parts)}\n'
            )

        # ATK / RANGE / HP row for minions
        atk_hp_row = ""
        if attack is not None and health is not None:
            range_text = ""
            if atk_range is not None:
                range_text = "MELEE" if atk_range == 0 else f"RANGE {atk_range}"
            atk_hp_row = (
                f'|-\n'
                f'| style="padding:6px 10px; background:#111; text-align:left; '
                f"font-family:'Montserrat',sans-serif; font-weight:900; text-transform:uppercase; "
                f'-webkit-text-stroke:1px black; paint-order:stroke fill; font-size:1.1em; '
                f'color:rgb(200,50,32);" '
                f'| {attack}\U0001f5e1\ufe0f\n'
                f"| style=\"padding:6px 10px; background:#111; text-align:center; "
                f"font-family:'Inter',system-ui,sans-serif; font-weight:600; font-size:0.75em; "
                f'color:#888; letter-spacing:1px;" '
                f'| {range_text}\n'
                f'| style="padding:6px 10px; background:#111; text-align:right; '
                f"font-family:'Montserrat',sans-serif; font-weight:900; text-transform:uppercase; "
                f'-webkit-text-stroke:1px black; paint-order:stroke fill; font-size:1.1em; '
                f'color:rgb(40,160,60);" '
                f'| {health}\U0001f90d\n'
            )

        # React section for multi-purpose cards
        react_section = ""
        react_cond = cotd.get("react_condition")
        if react_cond is not None and cotd.get("card_type", "") != "react":
            from sync.sync_cards import _REACT_CONDITION_TEXT, _REACT_CONDITION_TEXT_STR
            cond_text = _REACT_CONDITION_TEXT.get(react_cond) or _REACT_CONDITION_TEXT_STR.get(str(react_cond), "Any action")
            extra = " while no allies" if cotd.get("react_requires_no_friendly_minions") else ""
            react_eff = cotd.get("react_effect")
            if react_eff and react_eff.get("type") == "deploy_self":
                eff_text = " \u25b6 Summon"
            else:
                eff_text = ""
            react_cost = cotd.get("react_mana_cost", 0)
            cost_circle = (
                f'<span style="position:absolute; right:6px; top:50%; transform:translateY(-50%); '
                f'background:rgb(30,100,220); border-radius:50%; width:22px; height:22px; '
                f'border:1.5px solid rgba(255,255,255,0.4); display:flex; align-items:center; '
                f'justify-content:center; font-size:11px; font-weight:900; letter-spacing:0;">'
                f'{react_cost}</span>'
            )
            react_section = (
                f'|-\n'
                f'! colspan="3" style="padding:6px 10px; background:rgb(160,40,100); text-align:left; '
                f"font-family:'Inter',system-ui,sans-serif; font-weight:700; font-size:0.85em; "
                f'text-transform:uppercase; letter-spacing:2px; position:relative;" '
                f'| REACT{cost_circle}\n'
                f'|-\n'
                f'| colspan="3" style="padding:6px 10px; background:rgba(160,40,100,0.15); '
                f'border:1px solid rgba(160,40,100,0.3); font-size:0.9em;" '
                f'| {cond_text}{extra}{eff_text}\n'
            )

        # Element colour
        _elem_colours = {
            "Wood": "rgb(102,187,106)", "Fire": "rgb(220,40,30)",
            "Earth": "rgb(140,100,40)", "Water": "rgb(66,165,245)",
            "Metal": "rgb(120,120,135)", "Dark": "rgb(130,50,180)",
            "Light": "rgb(240,220,40)",
        }
        elem_bg = _elem_colours.get(element, "rgb(128,128,128)")

        # Type-based title bar color
        _type_colours = {
            "Minion": "rgb(180,140,60)", "Magic": "rgb(30,140,120)", "React": "rgb(160,40,100)",
        }
        title_bg = _type_colours.get(card_type, "linear-gradient(90deg,#333,#111)")

        cotd_section = (
            f'== Card of the Day ==\n'
            f'<div style="display:flex; justify-content:center; margin-bottom:1em;">\n'
            f'{{| style="width:280px; border:2px solid #222; border-radius:10px; '
            f'background:#1a1a1a; color:#eee; font-family:sans-serif;"\n'
            f'|-\n'
            f'! colspan="3" style="padding:6px 10px; background:{title_bg}; '
            f'border-radius:8px 8px 0 0; text-align:center; position:relative;" | '
            f'<span style="position:absolute; left:10px; top:50%; transform:translateY(-50%); '
            f"background:rgb(30,100,220); border-radius:50%; width:40px; height:40px; "
            f"border:2px solid rgb(30,25,20); display:flex; align-items:center; justify-content:center; "
            f"color:white; font-family:'Inter',system-ui,sans-serif; font-weight:900; text-transform:uppercase; "
            f'font-size:16px; -webkit-text-stroke:3px black; paint-order:stroke fill;">{mana}</span> '
            f"<span style=\"font-size:1.2em; font-family:'Source Sans 3','Source Sans Pro',sans-serif; "
            f'font-weight:700; -webkit-text-stroke:1px black; paint-order:stroke fill;\">'
            f'[[Card:{card_name}|<span style="color:white;">{card_name}</span>]]</span> '
            f'<span style="position:absolute; right:10px; top:50%; transform:translateY(-50%); '
            f'background:{elem_bg}; border-radius:50%; width:40px; height:40px; '
            f"border:2px solid rgb(30,25,20); display:flex; align-items:center; justify-content:center; "
            f"color:white; font-family:'Inter',system-ui,sans-serif; font-weight:900; "
            f"font-size:9px; text-transform:uppercase; white-space:nowrap; letter-spacing:0; "
            f'-webkit-text-stroke:3px black; paint-order:stroke fill;">{element}</span>\n'
            f'|-\n'
            f'| colspan="3" style="padding:0;" | [[File:{card_id}.png|280px|center|link=Card:{card_name}]]\n'
            f'{meta}'
            f'{rules_row}'
            f'{atk_hp_row}'
            f'{react_section}'
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
        "* [[Special:BrowseData/Card|All Cards]] -- Browse every card in the game\n"
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
