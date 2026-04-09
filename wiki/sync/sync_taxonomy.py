"""
Taxonomy page wikitext generation and upsert logic.

Generates and syncs element and tribe category pages to the Grid Tactics
wiki.  Each page contains an ``{{#ask:}}`` SMW query that auto-lists member
cards, so pages stay current as cards are added or changed.

Pure-function generators (no wiki connection) are separated from the
upsert logic so they can be unit-tested offline.

Usage::

    from pathlib import Path
    from sync.sync_taxonomy import sync_elements, sync_tribes
    from sync.client import get_site

    site = get_site()
    sync_elements(site, Path("../data/cards"))
    sync_tribes(site, Path("../data/cards"))
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Data scanning functions
# ---------------------------------------------------------------------------


def scan_elements(cards_dir: Path) -> list[str]:
    """Scan all card JSONs and return sorted unique element values (title-cased)."""
    elements: set[str] = set()
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            elem = card.get("element", "")
            if elem:
                elements.add(elem.title())
        except (json.JSONDecodeError, KeyError):
            continue
    return sorted(elements)


def scan_tribes(cards_dir: Path) -> list[str]:
    """Scan all card JSONs and return sorted unique tribe values."""
    tribes: set[str] = set()
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            tribe = card.get("tribe", "")
            if tribe:
                tribes.add(tribe)
        except (json.JSONDecodeError, KeyError):
            continue
    return sorted(tribes)


# ---------------------------------------------------------------------------
# Wikitext generation (pure functions, no wiki connection)
# ---------------------------------------------------------------------------


def element_page_wikitext(element: str) -> str:
    """Generate wikitext for an element category page.

    The page includes an ``{{#ask:}}`` query that lists all cards with
    this element, displayed as a broadtable.
    """
    return (
        f"'''{element}''' is one of seven elements in [[Grid Tactics TCG]].\n"
        f"\n"
        f"== Cards ==\n"
        f"{{{{#ask:\n"
        f" [[Category:Card]]\n"
        f" [[Element::{element}]]\n"
        f" |?Cost\n"
        f" |?Attack\n"
        f" |?HP\n"
        f" |?Tribe\n"
        f" |format=broadtable\n"
        f" |limit=50\n"
        f" |sort=Name\n"
        f"}}}}\n"
        f"\n"
        f"[[Category:Element]]"
    )


def tribe_page_wikitext(tribe: str) -> str:
    """Generate wikitext for a tribe category page.

    The page includes an ``{{#ask:}}`` query that lists all cards with
    this tribe, displayed as a broadtable.
    """
    return (
        f"'''{tribe}''' is a tribe in [[Grid Tactics TCG]].\n"
        f"\n"
        f"== Members ==\n"
        f"{{{{#ask:\n"
        f" [[Category:Card]]\n"
        f" [[Tribe::{tribe}]]\n"
        f" |?Cost\n"
        f" |?Element\n"
        f" |?Attack\n"
        f" |?HP\n"
        f" |format=broadtable\n"
        f" |limit=50\n"
        f" |sort=Name\n"
        f"}}}}\n"
        f"\n"
        f"[[Category:Tribe]]"
    )


# ---------------------------------------------------------------------------
# Upsert function
# ---------------------------------------------------------------------------


def upsert_taxonomy_pages(
    site,
    pages: dict[str, str],
    dry_run: bool = False,
) -> dict[str, int]:
    """Upsert a dict of ``{page_title: wikitext}`` to the wiki.

    Uses ``rstrip()`` comparison for idempotency (MediaWiki strips
    trailing whitespace on storage).

    Returns counts dict ``{"created": N, "updated": N, "unchanged": N}``.
    """
    counts = {"created": 0, "updated": 0, "unchanged": 0}

    for title, wikitext in sorted(pages.items()):
        page = site.pages[title]

        if dry_run:
            if not page.exists:
                counts["created"] += 1
                print(f"  {title}: would-create")
            elif page.text().rstrip() == wikitext.rstrip():
                counts["unchanged"] += 1
                print(f"  {title}: unchanged")
            else:
                counts["updated"] += 1
                print(f"  {title}: would-update")
            continue

        summary = f"sync taxonomy page: {title}"

        if not page.exists:
            page.edit(wikitext, summary=summary)
            counts["created"] += 1
            print(f"  {title}: created")
        elif page.text().rstrip() == wikitext.rstrip():
            counts["unchanged"] += 1
            print(f"  {title}: unchanged")
        else:
            page.edit(wikitext, summary=summary)
            counts["updated"] += 1
            print(f"  {title}: updated")

    return counts


# ---------------------------------------------------------------------------
# Orchestration functions
# ---------------------------------------------------------------------------


def sync_elements(
    site,
    cards_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Scan elements from card JSONs and upsert element pages to the wiki."""
    elements = scan_elements(cards_dir)
    print(f"Found {len(elements)} elements: {', '.join(elements)}")

    pages = {elem: element_page_wikitext(elem) for elem in elements}
    return upsert_taxonomy_pages(site, pages, dry_run=dry_run)


def sync_tribes(
    site,
    cards_dir: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Scan tribes from card JSONs and upsert tribe pages to the wiki."""
    tribes = scan_tribes(cards_dir)
    print(f"Found {len(tribes)} tribes: {', '.join(tribes)}")

    pages = {tribe: tribe_page_wikitext(tribe) for tribe in tribes}
    return upsert_taxonomy_pages(site, pages, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Keyword glossary parsing
# ---------------------------------------------------------------------------


def parse_glossary(glossary_path: Path) -> list[dict]:
    """Parse ``data/GLOSSARY.md`` into a sorted list of keyword dicts.

    Each dict has ``{"keyword": str, "description": str, "category": str}``
    where *category* is ``"Trigger"`` or ``"Mechanic"`` based on the
    section header the keyword appears under.
    """
    text = glossary_path.read_text(encoding="utf-8")
    keywords: list[dict] = []
    category = "Mechanic"  # default fallback

    for line in text.splitlines():
        # Detect section headers
        if re.match(r"^##\s+Trigger\b", line, re.IGNORECASE):
            category = "Trigger"
            continue
        if re.match(r"^##\s+Mechanic\b", line, re.IGNORECASE):
            category = "Mechanic"
            continue

        # Parse table rows: | Keyword | Description |
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", line)
        if not m:
            continue
        kw = m.group(1).strip()
        desc = m.group(2).strip()

        # Skip header/separator rows
        if kw.lower() == "keyword" or kw.startswith("-"):
            continue

        keywords.append({
            "keyword": kw,
            "description": desc,
            "category": category,
        })

    keywords.sort(key=lambda k: k["keyword"])
    return keywords


# ---------------------------------------------------------------------------
# Keyword page wikitext
# ---------------------------------------------------------------------------


def keyword_page_wikitext(keyword: str, description: str, category: str) -> str:
    """Generate wikitext for a keyword page.

    Includes an ``{{#ask:}}`` query that auto-lists cards with this keyword.
    """
    return (
        f"'''{keyword}''' is a [[{category} keyword]] in [[Grid Tactics TCG]].\n"
        f"\n"
        f"== Description ==\n"
        f"{description}\n"
        f"\n"
        f"== Cards with this keyword ==\n"
        f"{{{{#ask:\n"
        f" [[Category:Card]]\n"
        f" [[Keyword::{keyword}]]\n"
        f" |?Cost\n"
        f" |?Element\n"
        f" |?Tribe\n"
        f" |?CardType\n"
        f" |format=broadtable\n"
        f" |limit=50\n"
        f" |sort=Name\n"
        f"}}}}\n"
        f"\n"
        f"[[Category:Keyword]]\n"
        f"[[Category:{category} Keyword]]"
    )


# ---------------------------------------------------------------------------
# Rules / conceptual pages
# ---------------------------------------------------------------------------

RULES_PAGES: dict[str, str] = {
    "Grid Tactics TCG": (
        "'''Grid Tactics TCG''' is a fantasy trading card game played on a "
        "[[5x5 Board|5x5 grid]]. Two players deploy minions, cast magic, "
        "and play react cards in a battle of wits and strategy.\n"
        "\n"
        "== Overview ==\n"
        "Each player starts with a deck of cards and a pool of hit points. "
        "Cards belong to one of seven elements: Wood, Fire, Earth, Water, "
        "Metal, Dark, and Light. There are three card types:\n"
        "\n"
        "* '''Minion''' -- Creatures deployed to the board that can move, "
        "attack, and sacrifice.\n"
        "* '''Magic''' -- One-shot spells with immediate effects (damage, "
        "healing, board manipulation).\n"
        "* '''React''' -- Cards played during the opponent's turn in "
        "response to their actions.\n"
        "\n"
        "The goal is to reduce your opponent's HP to zero or successfully "
        "[[Win Conditions|sacrifice]] a minion by moving it across the "
        "entire board.\n"
        "\n"
        "== Core Mechanics ==\n"
        "* [[Mana]] -- Resource used to play cards. Unspent mana carries "
        "over between turns.\n"
        "* [[Turn Structure]] -- Auto-draw, then one action per turn.\n"
        "* [[React Window]] -- After each action, the opponent may respond.\n"
        "* [[Win Conditions]] -- Sacrifice or HP depletion.\n"
        "\n"
        "== See Also ==\n"
        "* [[:Category:Card|All Cards]]\n"
        "* [[:Category:Element|Elements]]\n"
        "* [[:Category:Tribe|Tribes]]\n"
        "* [[:Category:Keyword|Keywords]]\n"
        "\n"
        "{{ManuallyMaintained}}\n"
        "[[Category:Rules]]"
    ),

    "5x5 Board": (
        "The '''5x5 Board''' is the battlefield in [[Grid Tactics TCG]]. "
        "It consists of 5 columns (lanes) and 5 rows.\n"
        "\n"
        "== Layout ==\n"
        "Each player controls the row closest to them:\n"
        "\n"
        "* '''Player 1''' starts at the top row (row 0) and moves "
        "'''downward'''.\n"
        "* '''Player 2''' starts at the bottom row (row 4) and moves "
        "'''upward'''.\n"
        "\n"
        "The five columns function as lanes. A minion placed in a column "
        "can only move forward within that same column.\n"
        "\n"
        "== Movement ==\n"
        "Minions move '''forward only''' in their lane (same column). "
        "Player 1's minions move down; Player 2's minions move up. "
        "A minion cannot move backward or sideways.\n"
        "\n"
        "== Attacks ==\n"
        "Unlike movement, attacks can target '''any direction''' -- "
        "forward, backward, or diagonal -- as long as the target is "
        "within the minion's attack range.\n"
        "\n"
        "== Sacrifice ==\n"
        "When a minion reaches the opponent's back row (the far side of "
        "the board), it can be sacrificed to deal direct damage to the "
        "opponent or trigger a win condition. See [[Win Conditions]] for "
        "details.\n"
        "\n"
        "{{ManuallyMaintained}}\n"
        "[[Category:Rules]]"
    ),

    "Mana": (
        "'''Mana''' is the resource used to play cards in "
        "[[Grid Tactics TCG]].\n"
        "\n"
        "== Gaining Mana ==\n"
        "Players gain mana at the start of each turn. The amount "
        "increases as the game progresses, allowing more powerful cards "
        "to be played in later turns.\n"
        "\n"
        "== Mana Banking ==\n"
        "Unspent mana '''carries over''' between turns. This is called "
        "mana banking. If you choose not to spend all your mana in a "
        "turn, the remainder is added to your pool for the next turn.\n"
        "\n"
        "== Single Pool ==\n"
        "There is one shared mana pool per player -- mana is '''not''' "
        "separated by element. A Fire card and a Water card both draw "
        "from the same pool.\n"
        "\n"
        "== Spending Mana ==\n"
        "Each card has a mana cost shown in its top-left corner. You "
        "must have at least that much mana available to play the card. "
        "When you play a card, its cost is deducted from your pool.\n"
        "\n"
        "{{ManuallyMaintained}}\n"
        "[[Category:Rules]]"
    ),

    "React Window": (
        "The '''React Window''' is a core mechanic in [[Grid Tactics TCG]] "
        "that gives the opponent a chance to respond after each action.\n"
        "\n"
        "== How It Works ==\n"
        "After a player performs any action (playing a card, moving a "
        "minion, attacking, or sacrificing), a react window opens for "
        "the opponent. During this window, the opponent may play a "
        "[[React]] card from their hand.\n"
        "\n"
        "== React Cards ==\n"
        "React cards are a special card type designed to be played during "
        "the react window. They can:\n"
        "\n"
        "* '''Counter''' a spell or ability (e.g., [[Card:Counter Spell|"
        "Counter Spell]])\n"
        "* '''Deploy''' a minion to the board\n"
        "* '''Trigger''' defensive or offensive effects\n"
        "\n"
        "== Closing the Window ==\n"
        "If the opponent chooses not to play a react card (or has none "
        "available), the react window closes and play continues with the "
        "next turn.\n"
        "\n"
        "== Strategic Importance ==\n"
        "The react window adds a layer of interaction to every action. "
        "Players must consider what responses the opponent might have "
        "before committing to an action. Holding react cards in hand "
        "creates uncertainty and forces the opponent to play around "
        "potential counters.\n"
        "\n"
        "{{ManuallyMaintained}}\n"
        "[[Category:Rules]]"
    ),

    "Win Conditions": (
        "There are two ways to win a game of [[Grid Tactics TCG]].\n"
        "\n"
        "== Sacrifice ==\n"
        "When a minion moves across the entire [[5x5 Board|board]] and "
        "reaches the opponent's back row, it can be '''sacrificed'''. "
        "A successful sacrifice is an instant win. This rewards players "
        "who protect their minions and advance them through enemy lines.\n"
        "\n"
        "== HP Depletion ==\n"
        "Each player starts with a pool of hit points. HP can be reduced "
        "by:\n"
        "\n"
        "* Minion attacks that hit the opponent directly\n"
        "* Magic card effects that deal damage to the player\n"
        "* Other card abilities\n"
        "\n"
        "When a player's HP reaches zero, they lose the game.\n"
        "\n"
        "== Strategic Balance ==\n"
        "The two win conditions create strategic tension. Focusing on "
        "sacrifice means advancing minions aggressively, leaving fewer "
        "defenders. Focusing on HP depletion means dealing damage "
        "through attacks and spells, which may be slower but harder to "
        "counter. Most winning strategies combine both threats.\n"
        "\n"
        "{{ManuallyMaintained}}\n"
        "[[Category:Rules]]"
    ),

    "Turn Structure": (
        "The '''Turn Structure''' in [[Grid Tactics TCG]] defines the "
        "sequence of play each turn.\n"
        "\n"
        "== Turn Phases ==\n"
        "\n"
        "=== 1. Draw Phase ===\n"
        "At the start of each turn, the active player '''automatically "
        "draws''' one card from their deck. This is mandatory and "
        "happens before any other action.\n"
        "\n"
        "=== 2. Action Phase ===\n"
        "The player performs '''one action''' from the following:\n"
        "\n"
        "* '''Play a card''' -- Spend [[Mana|mana]] to play a minion or "
        "magic card from hand.\n"
        "* '''Move a minion''' -- Advance a minion forward in its lane "
        "(same column).\n"
        "* '''Attack''' -- Use a minion to attack an enemy minion or the "
        "opponent directly.\n"
        "* '''Sacrifice''' -- Sacrifice a minion that has reached the "
        "opponent's back row.\n"
        "* '''Pass''' -- Take no action and end the turn.\n"
        "\n"
        "=== 3. React Window ===\n"
        "After the action, a [[React Window|react window]] opens for "
        "the opponent. They may play a react card in response. If they "
        "pass or have no react cards, the window closes.\n"
        "\n"
        "=== 4. End of Turn ===\n"
        "Unspent [[Mana|mana]] is banked for the next turn. Play passes "
        "to the opponent, who begins their turn with the Draw Phase.\n"
        "\n"
        "{{ManuallyMaintained}}\n"
        "[[Category:Rules]]"
    ),
}


def sync_keywords(
    site,
    glossary_path: Path,
    dry_run: bool = False,
) -> dict[str, int]:
    """Parse GLOSSARY.md and upsert keyword pages to the wiki."""
    keywords = parse_glossary(glossary_path)
    print(f"Found {len(keywords)} keywords: "
          f"{', '.join(k['keyword'] for k in keywords)}")

    pages = {
        kw["keyword"]: keyword_page_wikitext(
            kw["keyword"], kw["description"], kw["category"]
        )
        for kw in keywords
    }
    return upsert_taxonomy_pages(site, pages, dry_run=dry_run)


def sync_rules_pages(
    site,
    dry_run: bool = False,
) -> dict[str, int]:
    """Upsert the 6 conceptual rules pages to the wiki."""
    print(f"Syncing {len(RULES_PAGES)} rules pages")
    return upsert_taxonomy_pages(site, RULES_PAGES, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_taxonomy(
    site,
    cards_dir: Path,
    glossary_path: Path,
) -> bool:
    """Run comprehensive verification of all Phase 4 taxonomy pages.

    Checks category counts, SMW query spot checks, keyword content,
    and rules page existence.  Returns True if all checks pass.
    """
    all_pass = True
    keywords = parse_glossary(glossary_path)

    # ---------------------------------------------------------------
    # [1/5] Category counts
    # ---------------------------------------------------------------
    print("[1/5] Category counts")
    checks = [
        ("Element", 7),
        ("Tribe", 14),
        ("Keyword", len(keywords)),
        ("Rules", 6),
    ]
    for cat_name, expected in checks:
        results = list(site.ask(f"[[Category:{cat_name}]]|limit=100"))
        actual = len(results)
        if actual == expected:
            print(f"  PASS  Category:{cat_name}: {actual} members")
        else:
            print(f"  FAIL  Category:{cat_name}: expected {expected}, got {actual}")
            all_pass = False

    # ---------------------------------------------------------------
    # [2/5] Fire element spot check
    # ---------------------------------------------------------------
    print("[2/5] Fire element spot check")
    # Count fire cards from JSON
    fire_expected = 0
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            if card.get("element", "").lower() == "fire":
                fire_expected += 1
        except (json.JSONDecodeError, KeyError):
            continue
    fire_results = list(site.ask(
        "[[Category:Card]][[Element::Fire]]|?Name|limit=50"
    ))
    fire_actual = len(fire_results)
    if fire_actual == fire_expected:
        print(f"  PASS  Fire element: expected {fire_expected}, got {fire_actual}")
    else:
        print(f"  FAIL  Fire element: expected {fire_expected}, got {fire_actual}")
        all_pass = False

    # ---------------------------------------------------------------
    # [3/5] Rat tribe spot check
    # ---------------------------------------------------------------
    print("[3/5] Rat tribe spot check")
    rat_expected = 0
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
            if card.get("tribe", "") == "Rat":
                rat_expected += 1
        except (json.JSONDecodeError, KeyError):
            continue
    rat_results = list(site.ask(
        "[[Category:Card]][[Tribe::Rat]]|?Name|limit=50"
    ))
    rat_actual = len(rat_results)
    if rat_actual == rat_expected:
        print(f"  PASS  Rat tribe: expected {rat_expected}, got {rat_actual}")
    else:
        print(f"  FAIL  Rat tribe: expected {rat_expected}, got {rat_actual}")
        all_pass = False

    # ---------------------------------------------------------------
    # [4/5] Keyword content check
    # ---------------------------------------------------------------
    print("[4/5] Keyword content check")
    check_keywords = ["Summon", "React", "Burn"]
    # Build lookup from parsed glossary
    glossary_lookup = {k["keyword"]: k["description"] for k in keywords}
    kw_ok = 0
    for kw_name in check_keywords:
        expected_desc = glossary_lookup.get(kw_name, "")
        if not expected_desc:
            print(f"  FAIL  {kw_name}: not found in glossary")
            all_pass = False
            continue
        page = site.pages[kw_name]
        if not page.exists:
            print(f"  FAIL  {kw_name}: page does not exist")
            all_pass = False
            continue
        page_text = page.text()
        # Check a significant substring of the description
        # Use first 40 chars to avoid minor formatting differences
        check_substr = expected_desc[:40]
        if check_substr in page_text:
            print(f"  PASS  {kw_name}: description matches")
            kw_ok += 1
        else:
            print(f"  FAIL  {kw_name}: description not found in page")
            all_pass = False
    print(f"  Keyword content: {kw_ok}/{len(check_keywords)} verified")

    # ---------------------------------------------------------------
    # [5/5] Rules pages check
    # ---------------------------------------------------------------
    print("[5/5] Rules pages check")
    rules_titles = list(RULES_PAGES.keys())
    rules_ok = 0
    for title in rules_titles:
        page = site.pages[title]
        if not page.exists:
            print(f"  FAIL  {title}: page does not exist")
            all_pass = False
            continue
        page_text = page.text()
        if "{{ManuallyMaintained}}" in page_text:
            print(f"  PASS  {title}: exists with ManuallyMaintained")
            rules_ok += 1
        else:
            print(f"  FAIL  {title}: missing ManuallyMaintained marker")
            all_pass = False
    print(f"  Rules pages: {rules_ok}/{len(rules_titles)} verified")

    # ---------------------------------------------------------------
    # Overall
    # ---------------------------------------------------------------
    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")
    return all_pass


# ---------------------------------------------------------------------------
# Standalone execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from sync.client import get_site

    cards_dir = _REPO_ROOT / "data" / "cards"
    site = get_site()

    print("=== Elements ===")
    elem_counts = sync_elements(site, cards_dir)
    print(f"Elements: {elem_counts}")

    print("\n=== Tribes ===")
    tribe_counts = sync_tribes(site, cards_dir)
    print(f"Tribes: {tribe_counts}")
