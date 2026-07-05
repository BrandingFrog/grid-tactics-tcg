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

        # Build metadata rows — vintage ivory rows matching Template:Card
        _cs = (
            'style="padding:5px 12px; background:rgba(222,208,168,0.5); '
            'border-bottom:1px solid rgba(107,87,48,0.3);"'
        )
        _label = (
            "style=\"color:#6b5730; font-family:'Alegreya SC',Georgia,serif; "
            'font-weight:700; font-size:10.5px; letter-spacing:0.08em; '
            'text-transform:uppercase;"'
        )
        _value = 'style="float:right; color:#241c10; font-weight:700;"'
        meta = ""
        meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Type</span> <span {_value}>[[{card_type}]]</span>\n'
        if element:
            meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Element</span> <span {_value}>[[{element}]]</span>\n'
        if tribe:
            tribe_links = "<br/>".join(f"[[{t}]]" for t in tribe.split())
            meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Tribe</span> <span {_value}>{tribe_links}</span>\n'
        meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Mana</span> <span {_value}>{mana}</span>\n'
        if atk_range is not None:
            range_text = "[[Melee]]" if atk_range == 0 else f"[[Ranged|Range {atk_range}]]"
            meta += f'|-\n| colspan="3" {_cs} | <span {_label}>Range</span> <span {_value}>{range_text}</span>\n'

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
                    f'<hr style="border:0;border-top:1px dashed rgba(107,87,48,0.5); margin:8px 0;"/>'
                    f'<span style="color:#4a3d24;font-style:italic;font-size:12px;">{flavor}</span>'
                )
            # Type-coded mode box (minion leather / magic purple / react pink)
            _mode_bg = {
                "Magic": "#e8def1", "React": "#f6dcea",
            }.get(card_type, "rgba(242,233,206,0.95)")
            _mode_border = {
                "Magic": "#6f42a0", "React": "#c2367e",
            }.get(card_type, "#7a4f28")
            rules_row = (
                f'|-\n'
                f'| colspan="3" style="padding:0 8px;" '
                f'| <div style="background:{_mode_bg}; border:2px solid {_mode_border}; '
                f'border-left-width:8px; border-radius:6px; margin:8px 0; padding:8px 12px; '
                f"min-height:56px; font-family:'Alegreya',Georgia,serif; font-size:13.5px; "
                f'line-height:1.4; color:#241c10; box-shadow:0 3px 9px rgba(0,0,0,0.25);">'
                f'{"".join(text_parts)}</div>\n'
            )

        # ATK / RANGE / HP row for minions (vintage parchment stat strip)
        atk_hp_row = ""
        if attack is not None and health is not None:
            range_text = ""
            if atk_range is not None:
                range_text = "MELEE" if atk_range == 0 else f"RANGE {atk_range}"
            _stat_cell = (
                'padding:7px 12px; background:rgba(222,208,168,0.55); '
                'border-top:1px solid rgba(107,87,48,0.35);'
            )
            atk_hp_row = (
                f'|-\n'
                f'| style="{_stat_cell} text-align:left; '
                f"font-family:'Alegreya SC',Georgia,serif; font-weight:800; font-size:18px; "
                f'color:#b06a15; text-shadow:0 1px 0 rgba(255,250,235,0.6); '
                f'border-radius:0 0 0 10px;" '
                f'| {attack}\U0001f5e1\ufe0f\n'
                f'| style="{_stat_cell} text-align:center; '
                f"font-family:'Alegreya SC',Georgia,serif; font-weight:700; font-size:10px; "
                f'color:#6b5730; letter-spacing:2px;" '
                f'| {range_text}\n'
                f'| style="{_stat_cell} text-align:right; '
                f"font-family:'Alegreya SC',Georgia,serif; font-weight:800; font-size:18px; "
                f'color:#c0392b; text-shadow:0 1px 0 rgba(255,250,235,0.6); '
                f'border-radius:0 0 10px 0;" '
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
            cost_chip = (
                f'<span style="position:absolute; right:8px; top:50%; transform:translateY(-50%); '
                f'background:rgba(0,0,0,0.3); border-radius:5px; width:22px; height:22px; '
                f'border:1px solid rgba(255,255,255,0.5); display:flex; align-items:center; '
                f"justify-content:center; font-family:'Alegreya SC',Georgia,serif; "
                f'font-size:12px; font-weight:800; letter-spacing:0;">'
                f'{react_cost}</span>'
            )
            react_section = (
                f'|-\n'
                f'! colspan="3" style="padding:6px 12px; '
                f'background:linear-gradient(180deg,#c2367e,#7e1f50); text-align:left; '
                f"font-family:'Alegreya SC',Georgia,serif; font-weight:800; font-size:11px; "
                f'text-transform:uppercase; letter-spacing:2px; color:#fdf2f8; '
                f'text-shadow:0 1px 0 rgba(0,0,0,0.4); position:relative;" '
                f'| REACT{cost_chip}\n'
                f'|-\n'
                f'| colspan="3" style="padding:0 8px 8px;" '
                f'| <div style="background:#f6dcea; border:2px solid #c2367e; '
                f'border-left-width:8px; border-radius:6px; margin-top:8px; padding:8px 12px; '
                f"font-family:'Alegreya',Georgia,serif; font-size:13px; line-height:1.4; "
                f'color:#241c10; box-shadow:0 3px 9px rgba(0,0,0,0.25);">'
                f'{cond_text}{extra}{eff_text}</div>\n'
            )

        # Element chip colour (mirrors game.css .cf2-<element> --el-chip)
        _elem_colours = {
            "Wood": "#3c6424", "Fire": "#8c2a20",
            "Earth": "#71581f", "Water": "#234f86",
            "Metal": "#4a4a4e", "Dark": "#4b2d77",
            "Light": "#96822a",
        }
        elem_bg = _elem_colours.get(element, "#555559")

        # Type-coded title bar (minion leather / magic purple / react pink)
        _type_colours = {
            "Minion": "linear-gradient(180deg,#8a5c30,#7a4f28)",
            "Magic": "linear-gradient(180deg,#7d4fb2,#6f42a0)",
            "React": "linear-gradient(180deg,#d24390,#c2367e)",
        }
        title_bg = _type_colours.get(card_type, "linear-gradient(180deg,#4a4a4e,#3a3a3d)")

        _chip = (
            "border-radius:6px; width:34px; height:34px; border:2px solid #17110a; "
            "outline:2px solid #ded0a8; display:flex; align-items:center; "
            "justify-content:center; color:#f4ead0; "
            "font-family:'Alegreya SC',Georgia,serif; "
            "text-shadow:0 1px 0 rgba(0,0,0,0.5); "
            "box-shadow:inset 0 2px 4px rgba(255,255,255,0.12), 0 2px 7px rgba(0,0,0,0.5);"
        )

        cotd_section = (
            f'== Card of the Day ==\n'
            f'<div style="display:flex; justify-content:center; margin-bottom:1em;">\n'
            f'{{| class="gt-cotd" style="width:280px; border:none; border-radius:10px; '
            f'background:linear-gradient(148deg,#efe7d1 0%,#e5d9bc 58%,#d7c9a4 100%); '
            f"color:#241c10; font-family:'Alegreya',Georgia,serif; "
            f'box-shadow:inset 0 0 2px rgba(70,50,25,0.55), inset 0 0 11px rgba(120,92,50,0.3), '
            f'0 6px 24px rgba(0,0,0,0.55);"\n'
            f'|-\n'
            f'! colspan="3" style="padding:10px 46px; background:{title_bg}; '
            f'border-radius:10px 10px 0 0; text-align:center; position:relative; line-height:1.12;" | '
            f'<span style="position:absolute; left:8px; top:50%; transform:translateY(-50%); '
            f'background:{elem_bg}; font-weight:800; font-size:17px; {_chip}">{mana}</span>'
            f"<span style=\"font-size:1.05em; font-family:'Alegreya SC',Georgia,serif; "
            f'font-weight:800; letter-spacing:0.02em; text-shadow:0 1px 0 rgba(0,0,0,0.5);">'
            f'[[Card:{card_name}|<span style="color:#f4ead0;">{card_name}</span>]]</span>'
            f'<span style="position:absolute; right:8px; top:50%; transform:translateY(-50%); '
            f'background:{elem_bg}; font-weight:700; font-size:7.5px; text-transform:uppercase; '
            f'white-space:nowrap; letter-spacing:0.04em; {_chip}">{element}</span>\n'
            f'|-\n'
            f'| colspan="3" style="padding:0; border-top:1px solid rgba(107,87,48,0.45); '
            f'border-bottom:1px solid rgba(107,87,48,0.45); background:#0d0a07;" '
            f'| [[File:{card_id}.png|280px|center|link=Card:{card_name}]]\n'
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
