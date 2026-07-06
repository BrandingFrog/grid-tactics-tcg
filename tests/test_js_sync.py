"""Sync checks between Python enums and game.js client code.

These tests ensure new enum values added in Python are also handled
in the JS client, preventing silent fallbacks to generic text like
'Effect' instead of proper card descriptions.
"""

import re
from pathlib import Path

from grid_tactics.enums import EffectType

STATIC_DIR = (
    Path(__file__).resolve().parent.parent
    / "src" / "grid_tactics" / "server" / "static"
)


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



def test_all_effect_types_handled_in_game_js():
    """Every EffectType enum value must have a matching case in
    getEffectDescription() in game.js.

    If this test fails, a new EffectType was added in enums.py without
    updating game.js. The JS fallback shows generic 'Effect' text
    instead of a proper card description.
    """
    js_source = _load_client_js()

    # Find all numeric type checks: "type === N"
    handled = set(int(m) for m in re.findall(r'type === (\d+)', js_source))

    missing = []
    for et in EffectType:
        if int(et) not in handled:
            missing.append(f"EffectType.{et.name} ({int(et)})")

    assert not missing, (
        f"game.js getEffectDescription() is missing cases for: "
        f"{', '.join(missing)}. Add 'else if (type === N)' branches "
        f"and keyword matchers for each new EffectType."
    )
