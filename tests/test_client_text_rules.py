"""Regression tests for client-facing card/UI text under the 2026-07 turn
structure (Rally/Decay phases, Decay-phase burn tick, no draw-as-action).

Two layers:
  1. Node-harness tests: extract getEffectDescription from game.js
     (brace-balanced) and assert the actual rendered card text for
     start/end-of-turn triggered effects and Promote. Skipped when node
     is missing (same pattern as tests/test_client_game_js.py).
  2. Static-text assertions: KEYWORD_GLOSSARY / status-tooltip / comment
     strings in game.js, game.html, and wiki/sync/sync_cards.py must use
     the Rally/Decay vocabulary and carry no stale draw-as-action or
     start-of-turn-burn references.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GAME_JS = ROOT / "src" / "grid_tactics" / "server" / "static" / "game.js"
GAME_HTML = ROOT / "src" / "grid_tactics" / "server" / "static" / "game.html"
SYNC_CARDS = ROOT / "wiki" / "sync" / "sync_cards.py"

JS_SRC = GAME_JS.read_text(encoding="utf-8")
HTML_SRC = GAME_HTML.read_text(encoding="utf-8")
SYNC_SRC = SYNC_CARDS.read_text(encoding="utf-8")

NODE = shutil.which("node")


# ---------------------------------------------------------------------------
# Node harness helpers (mirrors tests/test_client_game_js.py)
# ---------------------------------------------------------------------------

def _balanced_block(start_idx: int) -> str:
    brace = JS_SRC.index("{", start_idx)
    depth = 0
    j = brace
    while j < len(JS_SRC):
        ch = JS_SRC[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return JS_SRC[start_idx : j + 1]
        j += 1
    raise AssertionError("unbalanced braces from index %d" % start_idx)


def extract_function(name: str) -> str:
    marker = "function " + name + "("
    idx = JS_SRC.index(marker)
    return _balanced_block(idx)


def run_js(tmp_path: Path, script: str) -> dict:
    path = tmp_path / "harness.js"
    path.write_text(script, encoding="utf-8")
    # encoding="utf-8": node prints UTF-8; without this Windows decodes
    # stdout with the locale codepage and mangles non-ASCII card text
    # (e.g. the '×' in Gargoyle Sorceress's ×3 placement clause).
    res = subprocess.run(
        [NODE, str(path)], capture_output=True, text=True, timeout=30,
        encoding="utf-8",
    )
    assert res.returncode == 0, (
        "node harness failed\nSTDOUT:\n%s\nSTDERR:\n%s" % (res.stdout, res.stderr)
    )
    return json.loads(res.stdout.strip().splitlines()[-1])


_EFFECT_DESC_STUBS = """
var SWORD = '[atk]';
var HEART = '[hp]';
var allCardDefs = null;
var cardDefs = {};
function _dmTokenLive() { return '(DM)'; }
"""


def _effect_desc_harness(tail: str) -> str:
    return (
        _EFFECT_DESC_STUBS
        + extract_function("findCardNameById")
        + extract_function("_isDmScale")
        + extract_function("getEffectDescription")
        + tail
    )


# ---------------------------------------------------------------------------
# Rendered card text: Rally/Decay trigger prefixes (game.js triggerMap)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node executable not available")
def test_end_of_turn_trigger_renders_decay_prefix(tmp_path):
    """Emberplague Rat's burn (trigger wire 10 = ON_END_OF_TURN) must render
    with a 'Decay:' prefix, not as bare 'Burn adjacent enemies'."""
    script = _effect_desc_harness(
        """
var card = { card_type: 0, name: 'Emberplague Rat', card_id: 'emberplague_rat' };
var effects = [{ type: 10, target: 2, trigger: 10, amount: 0 }];
console.log(JSON.stringify({ desc: getEffectDescription(effects, card) }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["desc"] == "Decay: Burn adjacent enemies", (
        "ON_END_OF_TURN (10) must map to the 'Decay' phase prefix; got %r"
        % out["desc"]
    )


@pytest.mark.skipif(NODE is None, reason="node executable not available")
def test_start_of_turn_trigger_renders_rally_prefix(tmp_path):
    """Any ON_START_OF_TURN (wire 9) effect must render a 'Rally:' prefix."""
    script = _effect_desc_harness(
        """
var card = { card_type: 0, name: 'Dark Matter Battery' };
var effects = [{ type: 16, target: 3, trigger: 9, amount: 1 }];
console.log(JSON.stringify({ desc: getEffectDescription(effects, card) }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["desc"].startswith("Rally: "), (
        "ON_START_OF_TURN (9) must map to the 'Rally' phase prefix; got %r"
        % out["desc"]
    )


@pytest.mark.skipif(NODE is None, reason="node executable not available")
def test_passive_heal_renders_rally_heal(tmp_path):
    """Fallen Paladin's heal (EffectType 12) fires in the Rally Phase at the
    START of the owner's turn — the card face must say 'Rally: Heal N',
    never the old 'End: Heal N'."""
    script = _effect_desc_harness(
        """
var card = { card_type: 0, name: 'Fallen Paladin', card_id: 'fallen_paladin' };
var effects = [{ type: 12, target: 3, trigger: 9, amount: 2 }];
console.log(JSON.stringify({ desc: getEffectDescription(effects, card) }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["desc"] == "Rally: Heal 2", (
        "PASSIVE_HEAL must render 'Rally: Heal N' (fires at start of the "
        "owner's turn); got %r" % out["desc"]
    )
    assert "End" not in out["desc"]


@pytest.mark.skipif(NODE is None, reason="node executable not available")
def test_promote_names_actual_card_not_tribe(tmp_path):
    """Giant Rat's Promote must name the promote_target card (Common Rat),
    not claim 'any Rat' promotes — the engine only promotes that card."""
    script = _effect_desc_harness(
        """
allCardDefs = { 1: { card_id: 'minion_common_rat', name: 'Common Rat' } };
var card = { card_type: 0, name: 'Giant Rat', tribe: 'Rat',
             promote_target: 'minion_common_rat' };
var effects = [{ type: 7, target: 3, trigger: 1, amount: 0 }];
console.log(JSON.stringify({ desc: getEffectDescription(effects, card) }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["desc"] == "Death: Promote a Common Rat to Giant Rat", (
        "Promote text must name the promote_target card; got %r" % out["desc"]
    )
    assert "any Rat" not in out["desc"]


# ---------------------------------------------------------------------------
# Static text: glossary, tooltips, comments
# ---------------------------------------------------------------------------

def test_trigger_map_has_rally_and_decay_entries():
    m = re.search(r"var triggerMap = \{[^}]*\}", JS_SRC)
    assert m, "getEffectDescription's triggerMap not found in game.js"
    assert "9: 'Rally'" in m.group(0), "triggerMap missing 9: 'Rally'"
    assert "10: 'Decay'" in m.group(0), "triggerMap missing 10: 'Decay'"


def test_keyword_glossary_start_end_reference_phase_names():
    start = re.search(r"'Start': '([^']+(?:\\'[^']*)*)'", JS_SRC)
    end = re.search(r"'End': '([^']+(?:\\'[^']*)*)'", JS_SRC)
    assert start and "Rally Phase" in start.group(1), (
        "KEYWORD_GLOSSARY 'Start' must reference the Rally Phase"
    )
    assert end and "Decay Phase" in end.group(1), (
        "KEYWORD_GLOSSARY 'End' must reference the Decay Phase"
    )


def test_burning_status_tooltip_says_decay_phase():
    """The minion status-panel Burning tooltip (second copy, distinct from
    KEYWORD_GLOSSARY) must carry the Decay-phase timing."""
    assert "Takes 5\U0001f90d damage in its owner\\'s Decay Phase." in JS_SRC, (
        "Burning status-panel tooltip must say the tick happens in the "
        "owner's Decay Phase"
    )
    assert "damage at the start of its owner" not in JS_SRC, (
        "stale start-of-turn burn wording still present in game.js"
    )


def test_no_stale_start_of_turn_burn_comments():
    assert "start-of-turn burn tick" not in JS_SRC, (
        "game.js still documents the old start-of-turn burn tick"
    )
    assert "Decay-Phase burn tick" in JS_SRC


def test_burn_tick_popup_fires_for_previous_active_owner():
    """Burn now ticks in the OWNER's Decay Phase BEFORE the turn flips, so the
    popup guard must compare the owner against the PREVIOUS frame's active
    player (the old guard used the new frame's and never fired)."""
    assert "prevState.active_player_idx === p.owner" in JS_SRC
    assert "frame.active_player_idx === p.owner" not in JS_SRC, (
        "burn-tick popup still guards on the post-flip active player"
    )


def test_hand_action_bar_comment_has_no_draw_card():
    m = re.search(r"<!-- Hand Action Bar[^>]*-->", HTML_SRC)
    assert m, "Hand Action Bar comment not found in game.html"
    assert "Draw Card" not in m.group(0), (
        "game.html still advertises the removed Draw Card action"
    )
    assert "Pass" in m.group(0)


def test_wiki_sync_passive_heal_uses_rally():
    m = re.search(
        r'eff_type == "passive_heal":\s*\n\s*desc = f"(.+)"', SYNC_SRC
    )
    assert m, "passive_heal branch not found in wiki/sync/sync_cards.py"
    assert m.group(1).startswith("[[Rally]]"), (
        "wiki text for passive_heal must say Rally (start of owner's turn), "
        "got %r" % m.group(1)
    )
    assert "[[End]]" not in m.group(1)


# ---------------------------------------------------------------------------
# 2026-07 fixups: player_dark_matter rendering, minion_transformed handler,
# Rally/Decay keyword chips + glossary entries, wiki March/Rally split
# ---------------------------------------------------------------------------

@pytest.mark.skipif(NODE is None, reason="node executable not available")
def test_gargoyle_player_dark_matter_buff_renders_dm_scaling(tmp_path):
    """Gargoyle Sorceress's Summon buffs use scale_with='player_dark_matter'
    (the owner's POOLED Dark Matter). The rendered card text must carry the
    DM scaling and the ×3 placement clause — never '+0🗡️. +0🤍'."""
    script = _effect_desc_harness(
        """
var card = { card_type: 0, name: 'Gargoyle Sorceress', card_id: 'gargoyle_sorceress' };
var effects = [
  { type: 2, trigger: 8, target: 3, amount: 0, scale_with: 'player_dark_matter',
    placement_condition: 'front_of_dark_ranged', condition_multiplier: 3 },
  { type: 3, trigger: 8, target: 3, amount: 0, scale_with: 'player_dark_matter',
    placement_condition: 'front_of_dark_ranged', condition_multiplier: 3 }
];
console.log(JSON.stringify({ desc: getEffectDescription(effects, card) }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["desc"] == (
        "Gain (DM)[atk][hp]. ×3 if in front of Dark Ranged ally"
    ), (
        "player_dark_matter buff must render the DM scaling + placement "
        "clause; got %r" % out["desc"]
    )
    assert "+0" not in out["desc"]


@pytest.mark.skipif(NODE is None, reason="node executable not available")
def test_own_stacks_dark_matter_buff_still_renders(tmp_path):
    """Regression guard: the legacy scale_with='dark_matter' spelling
    (a minion's own stacks) must keep rendering after the
    player_dark_matter fix."""
    script = _effect_desc_harness(
        """
var card = { card_type: 0, name: 'Test', card_id: 'test' };
var effects = [
  { type: 2, trigger: 0, target: 3, amount: 0, scale_with: 'dark_matter' }
];
console.log(JSON.stringify({ desc: getEffectDescription(effects, card) }));
"""
    )
    out = run_js(tmp_path, script)
    assert out["desc"] == "Summon: Gain (DM)[atk]", (
        "legacy dark_matter buff rendering broke; got %r" % out["desc"]
    )


def test_playevent_handles_minion_transformed():
    """The engine emits EVT_MINION_TRANSFORMED (engine_events.py, 600ms
    'swap flash on the tile'); playEvent must route it to a handler instead
    of the unknown-event default branch."""
    assert 'case "minion_transformed":' in JS_SRC, (
        "playEvent has no minion_transformed case — the transform renders "
        "silently on the final snapshot commit"
    )
    assert "function playMinionTransformed(" in JS_SRC
    # The handler must flash the tile (CSS class lives in game.css).
    assert "transform-flash" in JS_SRC
    css_src = (GAME_JS.parent / "game.css").read_text(encoding="utf-8")
    assert ".transform-flash" in css_src


def test_keyword_glossary_has_rally_and_decay_entries():
    """getEffectDescription emits 'Rally:'/'Decay:' prefixes (triggerMap 9/10),
    so KEYWORD_GLOSSARY needs matching chip entries."""
    assert re.search(r"'Rally': '[^']*Rally Phase", JS_SRC), (
        "KEYWORD_GLOSSARY missing a 'Rally' entry describing the Rally Phase"
    )
    assert re.search(r"'Decay': '[^']*Decay Phase", JS_SRC), (
        "KEYWORD_GLOSSARY missing a 'Decay' entry describing the Decay Phase"
    )


def test_glossary_md_has_rally_and_decay_rows():
    """data/GLOSSARY.md is the keyword source of truth and must stay in sync
    with game.js KEYWORD_GLOSSARY (project convention)."""
    gl = (ROOT / "data" / "GLOSSARY.md").read_text(encoding="utf-8")
    assert "| Rally |" in gl, "GLOSSARY.md missing the Rally row"
    assert "| Decay |" in gl, "GLOSSARY.md missing the Decay row"


def test_passive_heal_chip_is_rally_not_end():
    """EffectType 12 (passive_heal) fires ON_START_OF_TURN — the Rally Phase.
    Its keyword chip must be 'Rally', not the old 'End' (which told players
    Fallen Paladin heals in the Decay Phase)."""
    m = re.search(r"if \(eff\.type === 12\) \{([^\n]*?)\}", JS_SRC)
    assert m, "type-12 keyword-chip branch not found in game.js"
    assert "addKw('Rally')" in m.group(1), (
        "passive_heal chip must be Rally; branch is %r" % m.group(1)
    )
    assert "addKw('End')" not in m.group(1)


def test_trigger_chip_loop_covers_rally_and_decay_triggers():
    """Triggers 9 (ON_START_OF_TURN) / 10 (ON_END_OF_TURN) must produce
    Rally / Decay keyword chips (e.g. Dark Matter Battery's Decay damage)."""
    assert "if (eff.trigger === 9) addKw('Rally')" in JS_SRC
    assert "if (eff.trigger === 10) addKw('Decay')" in JS_SRC


def test_wiki_sync_movement_keyword_is_march_not_rally():
    """2026-07 rename: the movement keyword is 'March'; '[[Rally]]' now names
    the start-of-turn phase. The wiki must not use [[Rally]] for both."""
    assert "[[March]] friendly" in SYNC_SRC, (
        "sync_cards.py march_forward rules text must link [[March]]"
    )
    assert "[[Rally]] friendly" not in SYNC_SRC, (
        "sync_cards.py still uses [[Rally]] for the movement mechanic"
    )
    assert '"rally_forward": "March"' in SYNC_SRC, (
        "derive_keywords trigger-name map still maps rally_forward to Rally"
    )
    assert '"march_forward": "March"' in SYNC_SRC


def test_wiki_sync_trigger_prefix_has_rally_and_decay():
    """on_start_of_turn / on_end_of_turn effects must render [[Rally]] /
    [[Decay]] prefixes on wiki card pages (matches game.js triggerMap)."""
    assert '"on_start_of_turn": "[[Rally]]"' in SYNC_SRC
    assert '"on_end_of_turn": "[[Decay]]"' in SYNC_SRC


def test_wiki_sync_recognizes_player_dark_matter_scale():
    """build_rules_text must treat scale_with='player_dark_matter' as
    DM-scaled (Gargoyle Sorceress) — same fix as game.js _isDmScale."""
    assert "player_dark_matter" in SYNC_SRC, (
        "sync_cards.py only recognizes the 'dark_matter' scale spelling"
    )


def test_minion_py_dark_matter_comment_not_stale():
    src = (ROOT / "src" / "grid_tactics" / "minion.py").read_text(
        encoding="utf-8"
    )
    assert "No card grants DM yet" not in src, (
        "minion.py still claims no card grants Dark Matter"
    )
    assert "grant_dark_matter" in src


def test_enums_dark_matter_buff_comment_not_stale():
    src = (ROOT / "src" / "grid_tactics" / "enums.py").read_text(
        encoding="utf-8"
    )
    m = re.search(r"DARK_MATTER_BUFF = 11\s*#(.*)", src)
    assert m, "DARK_MATTER_BUFF comment not found"
    assert "player's Dark Matter stacks" not in m.group(1), (
        "activated-ability path scales by the CASTER minion's stacks, not "
        "the player's pool — comment is stale"
    )
