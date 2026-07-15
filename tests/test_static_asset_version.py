"""Static asset cache-buster consistency checks.

Browsers can otherwise keep an older JavaScript/CSS bundle while the patch
badge advertises the new VERSION.json value. Keep this test independent of the
Node-backed client tests so it still runs when Node is unavailable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


STATIC_DIR = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "grid_tactics"
    / "server"
    / "static"
)


def test_all_game_assets_use_the_version_json_cache_buster():
    version_data = json.loads((STATIC_DIR / "VERSION.json").read_text(encoding="utf-8"))
    version = version_data["version"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", version), version

    html = (STATIC_DIR / "game.html").read_text(encoding="utf-8")
    refs = re.findall(
        r'["\'](/static/(?:css|js)/[^"\'?]+\?v=([^"\']+))["\']',
        html,
    )
    assert refs, "game.html contains no versioned local CSS/JS assets"

    mismatches = {url: cache_version for url, cache_version in refs if cache_version != version}
    assert not mismatches, (
        f"asset cache-busters must match VERSION.json ({version}): {mismatches}"
    )

    referenced_files = {
        url.split("?", 1)[0].removeprefix("/static/") for url, _ in refs
    }
    bundled_files = {
        f"css/{path.name}" for path in (STATIC_DIR / "css").glob("*.css")
    } | {
        f"js/{path.name}" for path in (STATIC_DIR / "js").glob("*.js")
    }
    assert referenced_files == bundled_files, {
        "missing_from_game_html": sorted(bundled_files - referenced_files),
        "missing_from_disk": sorted(referenced_files - bundled_files),
    }

