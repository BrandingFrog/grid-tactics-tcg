"""Regression tests for player-facing card/doc TEXT under the 2026-07 turn
structure (Rally/Decay phases, one-action turns, mana pool, overdraw burns).

Guards the 2026-07-03 card-text audit fixes:
  - stale pre-redesign phrasing purged from data/cards/*.json tips/rulings
    (draw-as-action, mana crystals/"Water mana", start-of-turn burn,
    mulligan, react-on-any-action, burn "stacking", multi-action turns);
  - locked stat notation (dagger/white-heart glyphs) on the corrected lines;
  - data/GLOSSARY.md Start/End/Burn rows and their game.js KEYWORD_GLOSSARY
    mirrors stay in sync (CLAUDE.md convention);
  - data/turn_structure_spec.md internal-consistency fixes (Stack vs Queue,
    Handshake Action-Phase scoping, Rally/Decay used as phase names);
  - data/tests/tests.json Fallen Paladin UAT scenarios re-timed to the
    Rally Phase.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from grid_tactics.card_library import CardLibrary

ROOT = Path(__file__).resolve().parents[1]
CARDS_DIR = ROOT / "data" / "cards"
GLOSSARY_MD = ROOT / "data" / "GLOSSARY.md"
SPEC_MD = ROOT / "data" / "turn_structure_spec.md"
TESTS_JSON = ROOT / "data" / "tests" / "tests.json"
STATIC_DIR = ROOT / "src" / "grid_tactics" / "server" / "static"


def _load_client_js() -> str:
    """Modular client JS (2026-07-06): js/NN-*.js sorted by filename equals
    the former monolithic game.js; falls back to game.js if js/ absent."""
    js_dir = STATIC_DIR / "js"
    if js_dir.is_dir():
        return "".join(p.read_text(encoding="utf-8") for p in sorted(js_dir.glob("*.js")))
    return (STATIC_DIR / "game.js").read_text(encoding="utf-8")


def _load_client_css() -> str:
    css_dir = STATIC_DIR / "css"
    if css_dir.is_dir():
        return "".join(p.read_text(encoding="utf-8") for p in sorted(css_dir.glob("*.css")))
    return (STATIC_DIR / "game.css").read_text(encoding="utf-8")



def _load_all_cards() -> dict[str, dict]:
    cards: dict[str, dict] = {}
    for path in sorted(CARDS_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cards[data["card_id"]] = data
    assert cards, "no card JSONs found"
    return cards


CARDS = _load_all_cards()


def _facing_text(data: dict) -> str:
    """All player-facing prose on a card (tips + rulings + trivia)."""
    chunks: list[str] = []
    for key in ("tips", "rulings", "trivia"):
        chunks.extend(data.get(key, []) or [])
    if data.get("flavour_text"):
        chunks.append(data["flavour_text"])
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# JSON validity / completeness
# ---------------------------------------------------------------------------

def test_card_directory_loads_via_library() -> None:
    lib = CardLibrary.from_directory(CARDS_DIR)
    assert lib.get_by_card_id("rat") is not None
    assert lib.get_by_card_id("matter_possessed") is not None


def test_every_card_has_tips_and_rulings() -> None:
    """matter_possessed was the last card without tips/rulings — keep the
    set fully documented."""
    missing = [
        cid
        for cid, data in CARDS.items()
        if not data.get("tips") or not data.get("rulings")
    ]
    assert missing == [], f"cards missing tips/rulings: {missing}"


# ---------------------------------------------------------------------------
# Stale pre-redesign phrasing must never return to card text
# ---------------------------------------------------------------------------

STALE_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)mulligan", "no mulligan mechanic exists"),
    (r"any action they take", "opponent_ends_turn reacts fire only in the Decay window"),
    (r"(?i)burn (damage )?stacks\b", "burn is a boolean, non-stacking status"),
    (r"(?i)max curve", "mana pool caps at 10; 7 is not the top of the curve"),
    (r"(?i)water mana", "mana is a single untyped pool — no element crystals"),
    (r"is_burning=true", "engine-internal field leaked into player text"),
    (r"react_condition=opponent_sacrifices", "engine-internal field leaked into player text"),
    (r"(?i)\d+-health\b", "use the white-heart glyph, never the word 'health'"),
    (r"(?i)end-of-turn healing", "Fallen Paladin heals in the Rally Phase"),
    (r"alongside another action", "Action Phase allows exactly one action"),
    (r"clamped above 0", "Erebus cost clamps AT 0 (free at 20+ DM)"),
    (r"chain is infinite", "tutor searches the deck only; dead copies stay dead"),
    (r"Surgebot, and Sparkbot", "'Surgefed Sparkbot' is one card, not two"),
    (r"guaranteed damage", "react-stack negates make no payoff guaranteed"),
    (r"(?i)becomes active\b", "stale start-of-turn timing phrase — name the phase"),
]


@pytest.mark.parametrize("pattern,why", STALE_PATTERNS)
def test_no_stale_phrases_in_card_text(pattern: str, why: str) -> None:
    offenders = [
        cid
        for cid, data in CARDS.items()
        if re.search(pattern, _facing_text(data))
    ]
    assert offenders == [], (
        f"stale phrase {pattern!r} found on {offenders}: {why}"
    )


# ---------------------------------------------------------------------------
# Corrected rulings pinned to the implementation
# ---------------------------------------------------------------------------

def test_acidic_rain_react_scoped_to_decay_window() -> None:
    text = _facing_text(CARDS["acidic_rain"])
    assert "Decay Phase" in text
    assert "ANY opponent action" not in text


def test_prohibition_rulings_match_engine() -> None:
    text = _facing_text(CARDS["prohibition"])
    assert "goes to their Grave" in text, "negated magic goes to grave, not exhaust"
    assert "exhaust pile" not in text.lower()
    assert "CAN negate react cards" in text, "reacts are magic-like for Prohibition"


def test_giant_rat_promote_scoped_to_common_rat() -> None:
    text = _facing_text(CARDS["giant_rat"])
    assert "any Rat you control" not in text
    assert "Common Rat" in text


def test_ratchanter_not_a_promote_target() -> None:
    text = _facing_text(CARDS["ratchanter"])
    assert "NOT a promote target" in text


def test_erebus_cost_clamps_at_zero() -> None:
    text = _facing_text(CARDS["erebus"])
    assert "clamped at 0" in text
    assert "Grave Caller" not in CARDS["erebus"]["tips"][1], (
        "Grave Caller grants no DM — the DM-building tip must not name it"
    )


def test_battery_decay_phase_and_no_dm_ramp_myth() -> None:
    text = _facing_text(CARDS["dark_matter_battery"])
    assert "Decay Phase" in text
    assert "Ramp Battery's DM" not in text
    assert "Give Battery DM via" not in text


def test_matter_possessed_suicide_edge_case_documented() -> None:
    data = CARDS["matter_possessed"]
    rulings = "\n".join(data["rulings"])
    assert "exactly 25🤍 is legal" in rulings
    assert "0🤍 = defeat" in rulings


def test_tutor_overdraw_burn_documented_on_tutor_cards() -> None:
    """Tutor-to-hand is a draw path: full hand burns the pick (spec §9)."""
    for cid in ("blue_diodebot", "green_diodebot", "to_the_ratmobile", "tree_wyrm"):
        text = _facing_text(CARDS[cid])
        assert "Exhaust Pile" in text, f"{cid}: overdraw-burn rule missing"


def test_stat_notation_on_corrected_lines() -> None:
    """The audit's notation fixes must keep the dagger/white-heart glyphs."""
    expectations = {
        "blue_diodebot": "14🗡️/8🤍",
        "eclipse_shade": "20🗡️/26🤍",
        "rathopper": "19🗡️/13🤍",
        "pyre_archer": "9🗡️/5🤍",
        "flame_wyrm": "33🗡️/33🤍",
        "gargoyle_sorceress": "20🗡️/50🤍",
        "surgefed_sparkbot": "27🗡️/25🤍",
        "dark_matter_battery": "0🗡️/20🤍",
        "rat": "10🗡️/10🤍",
    }
    for cid, token in expectations.items():
        assert token in _facing_text(CARDS[cid]), f"{cid}: expected {token}"


# ---------------------------------------------------------------------------
# GLOSSARY.md rows + game.js KEYWORD_GLOSSARY sync (CLAUDE.md convention)
# ---------------------------------------------------------------------------

def _glossary_md_rows() -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in GLOSSARY_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|$", line)
        if m and m.group(1) not in ("Keyword", "---------"):
            rows[m.group(1)] = m.group(2)
    return rows


def _game_js_glossary() -> dict[str, str]:
    src = _load_client_js()
    block = src[src.index("var KEYWORD_GLOSSARY") :]
    block = block[: block.index("};") + 2]
    entries: dict[str, str] = {}
    for m in re.finditer(r"'((?:[^'\\]|\\.)+)':\s*'((?:[^'\\]|\\.)+)'", block):
        key = m.group(1).replace("\\'", "'")
        entries[key] = m.group(2).replace("\\'", "'")
    return entries


def test_glossary_start_end_burn_rows_updated() -> None:
    rows = _glossary_md_rows()
    assert "Rally Phase" in rows["Start"]
    assert "Decay Phase" in rows["End"]
    # ISO glossary rewrite (user 2026-07-11): entries are terse and
    # example-free — the Burn row must state the damage number, not the
    # old 'usually enemies… burn their own minion' hedge.
    assert "5" in rows["Burn"] and "Decay Phase" in rows["Burn"], (
        "Burn row must state the 5-damage Decay tick"
    )
    assert "Eclipse Shade" not in rows["Burn"], (
        "glossary entries carry no card examples (ISO style)"
    )
    assert rows["Burn"] != "Applies Burning to affected enemies."


def test_glossary_md_matches_game_js_for_changed_keywords() -> None:
    md = _glossary_md_rows()
    js = _game_js_glossary()
    for keyword in ("Start", "End", "Burn", "Burning"):
        assert md[keyword] == js[keyword], (
            f"GLOSSARY.md and game.js KEYWORD_GLOSSARY disagree on "
            f"{keyword!r}:\n  md: {md[keyword]}\n  js: {js[keyword]}"
        )


# ---------------------------------------------------------------------------
# turn_structure_spec.md internal consistency
# ---------------------------------------------------------------------------

def test_spec_stack_and_queue_are_separate_entries() -> None:
    spec = SPEC_MD.read_text(encoding="utf-8")
    assert "**Stack / Queue:**" not in spec
    assert "- **Stack:** LIFO structure holding pending reacts" in spec
    assert "- **Queue:** Priority-ordered list of simultaneous triggers" in spec


def test_spec_handshake_scoped_to_action_phase_passes() -> None:
    spec = SPEC_MD.read_text(encoding="utf-8")
    assert "PASSES as their Action-Phase action" in spec
    assert "Passes that merely close react windows do not count" in spec


def test_spec_uses_phase_names_not_bare_rally_decay_triggers() -> None:
    spec = SPEC_MD.read_text(encoding="utf-8")
    assert "Rally-Phase (Start:) triggers, Decay-Phase (End:) triggers" in spec
    assert "**Summon: / Death: / Start (Rally Phase) / End (Decay Phase):**" in spec
    assert "**Summon: / Death: / Rally / Decay:**" not in spec


# ---------------------------------------------------------------------------
# UAT scenarios re-timed to the Rally Phase
# ---------------------------------------------------------------------------

def _uat_tests() -> dict[str, dict]:
    data = json.loads(TESTS_JSON.read_text(encoding="utf-8"))
    return {t["id"]: t for t in data["tests"]}


def test_paladin_blip_scenario_uses_rally_timing() -> None:
    t = _uat_tests()["end-of-turn-trigger-blip-paladin"]
    assert "Rally" in t["title"]
    assert "Rally Phase" in t["expected"]
    assert "End: passive_heal" not in t["expected"]
    assert "Before the turn flips" not in t["expected"]


def test_priority_modal_scenario_uses_rally_timing_and_correct_stats() -> None:
    t = _uat_tests()["priority-modal-two-end-triggers"]
    assert "Rally" in t["title"] or "Rally" in t["instructions"]
    assert "32/42" in t["expected"]
    assert "16/32" not in t["expected"]
