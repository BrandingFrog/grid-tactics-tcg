"""Sync checks between Python enums and game.js client code.

These tests ensure new enum values added in Python are also handled
in the JS client, preventing silent fallbacks to generic text like
'Effect' instead of proper card descriptions.
"""

import re
from pathlib import Path

from grid_tactics.enums import EffectType

GAME_JS = (
    Path(__file__).resolve().parent.parent
    / "src" / "grid_tactics" / "server" / "static" / "game.js"
)


def test_all_effect_types_handled_in_game_js():
    """Every EffectType enum value must have a matching case in
    getEffectDescription() in game.js.

    If this test fails, a new EffectType was added in enums.py without
    updating game.js. The JS fallback shows generic 'Effect' text
    instead of a proper card description.
    """
    js_source = GAME_JS.read_text(encoding="utf-8")

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
