"""
Launch polish: mobile CSS, logo/favicon generation & upload, search verification.

Provides functions for the ``--polish`` and ``--verify-search`` CLI flags
in :mod:`sync.sync_wiki`.

Usage::

    from sync.sync_polish import push_font_css, push_mobile_css, upload_logo, upload_favicon
    from sync.sync_polish import configure_logo_and_favicon, verify_search
    from sync.client import get_site

    site = get_site()
    push_mobile_css(site)
    upload_logo(site)
    upload_favicon(site)
    configure_logo_and_favicon(site)
    verify_search(site)
"""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DARK_SEARCH_CSS_MARKER = "/* --- Grid Tactics Dark Search --- */"

_DARK_SEARCH_CSS_BLOCK = f"""{_DARK_SEARCH_CSS_MARKER}
/* Search page: dark background for namespace filter and results */
.mw-search-profile-tabs,
.search-types,
fieldset#mw-searchoptions {{
  background: #1a1a1a !important;
  border-color: #333 !important;
  color: #eee !important;
}}

fieldset#mw-searchoptions legend {{
  color: #888 !important;
}}

fieldset#mw-searchoptions label {{
  color: #ccc !important;
}}

.mw-search-profile-tabs a {{
  color: var(--color-link, #00d4ff) !important;
}}

/* Search input */
#searchText, .mw-searchInput, input[type="search"] {{
  background: #222 !important;
  color: #eee !important;
  border-color: #444 !important;
}}

/* Search results */
.mw-search-results li,
.searchresults {{
  color: #ccc;
}}

.searchresult {{
  color: #ccc !important;
}}

.mw-search-result-data {{
  color: #888 !important;
}}
"""

_MOBILE_CSS_MARKER = "/* --- Grid Tactics Mobile --- */"

_MOBILE_CSS_BLOCK = f"""{_MOBILE_CSS_MARKER}
@media (max-width: 720px) {{
  /* Card infobox: full width, no float on mobile */
  .gt-card, .infobox, .card-infobox {{
    width: 100% !important;
    max-width: 100% !important;
    float: none !important;
    margin: 0 0 1em 0 !important;
  }}

  /* Card art: scale to container */
  .gt-card img {{
    max-width: 100% !important;
    height: auto !important;
  }}

  /* SMW result tables: horizontal scroll */
  .smw-table-result, .wikitable {{
    overflow-x: auto;
    display: block;
  }}

  /* Body content padding */
  .mw-body-content, #mw-content-text {{
    padding: 0.5em;
  }}

  /* Hide sidebar on mobile */
  .mw-sidebar, #mw-panel, .citizen-drawer {{
    display: none !important;
  }}

  /* Card art responsive */
  .card-art img, .infobox img {{
    max-width: 100%;
    height: auto;
  }}

  /* Content area full width */
  .mw-body {{
    margin-left: 0 !important;
  }}
}}
"""

# ---------------------------------------------------------------------------
# Dark Search CSS
# ---------------------------------------------------------------------------


def push_dark_search_css(site, dry_run: bool = False) -> str:
    """Append dark search page CSS to MediaWiki:Common.css (idempotent)."""
    page = site.pages["MediaWiki:Common.css"]
    current = page.text() if page.exists else ""

    if _DARK_SEARCH_CSS_MARKER in current:
        print("  MediaWiki:Common.css: unchanged (dark search CSS already present)")
        return "unchanged"

    new_text = (current.rstrip() + "\n\n" + _DARK_SEARCH_CSS_BLOCK) if current else _DARK_SEARCH_CSS_BLOCK

    if dry_run:
        print("  MediaWiki:Common.css: would-update (dark search CSS)")
        return "would-update"

    page.edit(new_text, summary="add dark theme CSS for search page")
    print("  MediaWiki:Common.css: updated (dark search CSS)")
    return "updated"


# ---------------------------------------------------------------------------
# Font CSS
# ---------------------------------------------------------------------------

_FONT_CSS_MARKER = "/* --- Grid Tactics Fonts --- */"

_FONT_CSS_BLOCK = f"""{_FONT_CSS_MARKER}
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@900&display=swap');
"""


def push_font_css(site, dry_run: bool = False) -> str:
    """Append Google Fonts import to MediaWiki:Common.css (idempotent).

    Returns ``"created"``, ``"updated"``, or ``"unchanged"``.
    """
    page = site.pages["MediaWiki:Common.css"]

    if not page.exists:
        if dry_run:
            print("  MediaWiki:Common.css: would-create (font CSS)")
            return "would-create"
        page.edit(_FONT_CSS_BLOCK, summary="add Google Fonts import for card names")
        print("  MediaWiki:Common.css: created (font CSS)")
        return "created"

    current = page.text()

    if _FONT_CSS_MARKER in current:
        print("  MediaWiki:Common.css: unchanged (font CSS already present)")
        return "unchanged"

    # Prepend font import before existing CSS so it loads first
    new_text = _FONT_CSS_BLOCK + "\n" + current

    if dry_run:
        print("  MediaWiki:Common.css: would-update (prepend font CSS)")
        return "would-update"

    page.edit(new_text, summary="prepend Google Fonts import for card names")
    print("  MediaWiki:Common.css: updated (prepended font CSS)")
    return "updated"


# ---------------------------------------------------------------------------
# HUD Theme CSS — Tactical Command aesthetic matching the game app
# ---------------------------------------------------------------------------

_HUD_FONTS_MARKER = "/* --- Grid Tactics HUD Fonts --- */"

# @import rules MUST come before all other rules in the stylesheet or
# browsers silently drop them — so this gets PREPENDED to Common.css by
# push_hud_theme() before any selectors are defined.
_HUD_FONTS_BLOCK = f"""{_HUD_FONTS_MARKER}
@import url('https://fonts.googleapis.com/css2?family=Michroma&family=Space+Mono:wght@400;700&display=swap');
"""

_HUD_THEME_MARKER = "/* --- Grid Tactics HUD Theme --- */"

_HUD_THEME_BLOCK = f"""{_HUD_THEME_MARKER}
/* Wiki-wide Tactical HUD treatment — mirrors the aesthetic pushed to
   the main app (lobby / deck-builder / navbar). Fonts: Michroma for
   display/headings, Space Mono for telemetry & mono data. Cyan accents
   (#00d4ff) on near-black surfaces. Targets the Citizen skin +
   MediaWiki core + SMW. Font @imports live in a separate prepended
   block so the browser actually honours them. */

/* Scope most rules to body so they apply everywhere except inside the
   card infobox (which has its own game-style font stack). */
html, body {{
  background: #050913 !important;
  color: #c8dbe8;
}}
body {{
  font-family: 'Space Mono', 'Inter', system-ui, sans-serif;
  position: relative;
}}

/* Subtle grid-line overlay behind everything. Fades at the edges via
   a radial mask so it never fights the content. */
body::before {{
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  background-image:
    linear-gradient(to right, rgba(0, 212, 255, 0.05) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(0, 212, 255, 0.05) 1px, transparent 1px);
  background-size: 64px 64px;
  -webkit-mask-image: radial-gradient(ellipse at 50% 30%, black 20%, transparent 85%);
          mask-image: radial-gradient(ellipse at 50% 30%, black 20%, transparent 85%);
  opacity: 0.8;
}}
/* Keep content above the grid underlay */
#mw-content, .citizen-body, #content, .mw-body {{ position: relative; z-index: 1; }}

/* --- Typography -------------------------------------------------- */
h1, h2, h3, h4, h5, h6,
.mw-first-heading, .mw-page-title-main,
.firstHeading, .mw-heading {{
  font-family: 'Michroma', 'Montserrat', sans-serif !important;
  letter-spacing: 0.08em !important;
  color: #e8f7ff !important;
  text-shadow: 0 0 12px rgba(0, 212, 255, 0.25);
}}

/* Page title: add a cyan edge-bar to either side like the lobby wordmark */
.mw-page-title, .mw-page-title-main, .firstHeading, h1.mw-first-heading {{
  position: relative;
  padding-bottom: 10px;
  letter-spacing: 0.14em !important;
  font-size: clamp(28px, 3.4vw, 42px) !important;
  line-height: 1.05 !important;
}}
.mw-page-title::after, h1.mw-first-heading::after {{
  content: '';
  position: absolute;
  left: 0;
  bottom: 0;
  width: 120px;
  height: 2px;
  background: linear-gradient(90deg, #00d4ff, transparent);
  box-shadow: 0 0 12px rgba(0, 212, 255, 0.55);
}}

/* Section headings (h2/h3) get a bracket accent + subtle bottom border */
.mw-parser-output h2,
.mw-parser-output h3,
.mw-parser-output .mw-heading2,
.mw-parser-output .mw-heading3 {{
  position: relative;
  padding: 8px 0 8px 24px !important;
  margin-top: 28px !important;
  border-bottom: 1px dashed rgba(0, 212, 255, 0.18) !important;
  font-size: 20px !important;
  letter-spacing: 0.1em !important;
}}
.mw-parser-output h2::before,
.mw-parser-output .mw-heading2::before {{
  content: '';
  position: absolute;
  left: 0;
  top: 14px;
  width: 12px;
  height: 12px;
  border: 2px solid #00d4ff;
  border-right: 0;
  border-bottom: 0;
  opacity: 0.75;
  box-shadow: 0 0 6px rgba(0, 212, 255, 0.4);
}}
.mw-parser-output h3::before,
.mw-parser-output .mw-heading3::before {{
  content: '▸';
  position: absolute;
  left: 4px;
  color: #00d4ff;
  text-shadow: 0 0 6px rgba(0, 212, 255, 0.5);
  font-size: 14px;
  top: 11px;
}}

/* Tagline / "From Grid Tactics Wiki" subtitle under the page title */
.page-header__sub, .mw-page-description, .citizen-tagline,
.citizen-body .mw-body-header .mw-body-header-description {{
  font-family: 'Space Mono', monospace !important;
  font-size: 11px !important;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: rgba(0, 212, 255, 0.55) !important;
}}

/* --- Links ------------------------------------------------------- */
a, a:visited {{
  color: #00d4ff;
  text-decoration: none;
  transition: color 140ms ease, text-shadow 140ms ease;
}}
a:hover {{
  color: #e8f7ff;
  text-shadow: 0 0 6px rgba(0, 212, 255, 0.6);
}}
a.new, a.new:visited {{ color: #ff9b7b; }}  /* red links stay warm */

/* --- Body content surfaces -------------------------------------- */
.mw-body, #mw-content, #content, .citizen-page-container,
.citizen-content-container {{
  background: transparent !important;
}}
.mw-body-content p,
.mw-parser-output p,
.mw-parser-output li {{
  line-height: 1.65;
  color: #c8dbe8;
  font-family: 'Inter', 'Space Mono', system-ui, sans-serif;
}}
.mw-parser-output ul, .mw-parser-output ol {{
  padding-left: 22px;
}}
.mw-parser-output strong, .mw-parser-output b {{
  color: #e8f7ff;
}}

/* --- Tables (generic wikitable + SMW results) ------------------- */
table.wikitable,
table.smwtable,
table.smwtable-clean,
.smw-table {{
  background: rgba(10, 20, 35, 0.65) !important;
  border: 1px solid rgba(0, 212, 255, 0.25) !important;
  border-collapse: separate !important;
  border-spacing: 0 !important;
  color: #c8dbe8 !important;
  font-family: 'Space Mono', monospace;
  font-size: 12.5px;
}}
table.wikitable th,
table.smwtable th,
table.smwtable-clean th {{
  background: linear-gradient(180deg, rgba(0, 212, 255, 0.12), rgba(0, 212, 255, 0.03)) !important;
  color: #e8f7ff !important;
  border-bottom: 1px solid rgba(0, 212, 255, 0.35) !important;
  border-right: 1px solid rgba(0, 212, 255, 0.12) !important;
  font-family: 'Michroma', sans-serif !important;
  font-size: 10.5px !important;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  padding: 9px 12px !important;
  text-align: left !important;
}}
table.wikitable td,
table.smwtable td,
table.smwtable-clean td {{
  border: 1px solid rgba(0, 212, 255, 0.08) !important;
  padding: 7px 12px !important;
  background: transparent !important;
}}
table.wikitable tr:hover td,
table.smwtable tr:hover td {{
  background: rgba(0, 212, 255, 0.05) !important;
}}
table.wikitable tr:nth-child(even) td {{
  background: rgba(0, 212, 255, 0.02) !important;
}}

/* --- Infobox (card pages and manual) ---------------------------- */
.infobox, table.infobox {{
  background: rgba(10, 20, 35, 0.85) !important;
  border: 1px solid rgba(0, 212, 255, 0.35) !important;
  border-radius: 0 !important;
  box-shadow: 0 10px 28px -14px rgba(0, 0, 0, 0.7),
              0 0 30px -14px rgba(0, 212, 255, 0.45);
  position: relative;
  /* Hexagonal-style chamfered corners (matches app panels) */
  clip-path: polygon(
    0 10px, 10px 0,
    calc(100% - 10px) 0, 100% 10px,
    100% calc(100% - 10px), calc(100% - 10px) 100%,
    10px 100%, 0 calc(100% - 10px)
  );
}}
.infobox::before {{
  content: '';
  position: absolute;
  top: 0; left: 14px; right: 14px;
  height: 2px;
  background: linear-gradient(90deg, transparent, #00d4ff, transparent);
  opacity: 0.55;
  z-index: 1;
}}
.infobox th,
.infobox caption {{
  color: #e8f7ff;
  font-family: 'Michroma', sans-serif;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-size: 11px;
  padding: 8px 12px;
  background: rgba(0, 212, 255, 0.06);
  border-bottom: 1px solid rgba(0, 212, 255, 0.18);
}}
.infobox td {{
  color: #c8dbe8;
  font-family: 'Space Mono', monospace;
  font-size: 13px;
  padding: 8px 12px;
}}
.infobox a {{ color: #00d4ff; }}

/* --- Table of contents (core + Citizen) ------------------------- */
.toc, .toccolours, .mw-toc, .toc-container,
.citizen-toc, .citizen-toc__list,
#toc, #toc > ul {{
  background: rgba(10, 20, 35, 0.7) !important;
  border: 1px solid rgba(0, 212, 255, 0.22) !important;
  border-radius: 0 !important;
  padding: 12px 14px !important;
  font-family: 'Space Mono', monospace;
}}
.toctitle h2, .toc .toctitle,
.citizen-toc__list-title {{
  font-family: 'Michroma', sans-serif !important;
  font-size: 10px !important;
  letter-spacing: 0.24em !important;
  color: rgba(0, 212, 255, 0.85) !important;
  text-transform: uppercase !important;
  border-bottom: 1px dashed rgba(0, 212, 255, 0.18);
  padding-bottom: 6px;
  margin-bottom: 8px !important;
}}
.toc ul, .citizen-toc ul {{ padding-left: 16px; }}
.toc a, .citizen-toc a {{
  color: rgba(200, 219, 232, 0.75);
  font-size: 12px;
  letter-spacing: 0.04em;
  line-height: 1.9;
  transition: color 140ms ease, padding-left 140ms ease;
}}
.toc a:hover, .citizen-toc a:hover {{
  color: #00d4ff;
  padding-left: 3px;
}}

/* --- Citizen skin specifics ------------------------------------- */
.citizen-drawer,
.citizen-drawer__list,
.citizen-sidebar,
.citizen-page-sidebar {{
  background: rgba(6, 12, 22, 0.92) !important;
  border-right: 1px solid rgba(0, 212, 255, 0.14) !important;
}}
.citizen-drawer__item a,
.citizen-sidebar a {{ color: rgba(200, 219, 232, 0.75); }}
.citizen-drawer__item a:hover,
.citizen-sidebar a:hover {{ color: #00d4ff; background: rgba(0, 212, 255, 0.05); }}

/* Top page-tools row (View source / History / Discussion / ...) */
.page-actions, .citizen-page-header__tools,
.citizen-header, .mw-body-header {{
  border-bottom: 1px dashed rgba(0, 212, 255, 0.12);
}}

/* Pill-style page action buttons */
.citizen-menu__card a,
.mw-portlet a.cdx-button,
.page-actions a,
.vector-menu-heading {{
  font-family: 'Michroma', sans-serif !important;
  font-size: 11px !important;
  letter-spacing: 0.18em !important;
  text-transform: uppercase;
}}

/* --- Footer ----------------------------------------------------- */
.citizen-footer,
#footer, .mw-footer,
.footer {{
  background:
    linear-gradient(180deg, rgba(0, 212, 255, 0.04), transparent) !important;
  border-top: 1px solid rgba(0, 212, 255, 0.18) !important;
  color: rgba(200, 219, 232, 0.55) !important;
  font-family: 'Space Mono', monospace;
  font-size: 11px;
  padding: 24px 24px 32px !important;
  margin-top: 48px;
}}
.citizen-footer h3,
.citizen-footer .citizen-footer__sitetitle,
#footer strong, .mw-footer strong {{
  font-family: 'Michroma', sans-serif !important;
  color: #e8f7ff !important;
  letter-spacing: 0.18em !important;
}}
.citizen-footer a, #footer a {{ color: #00d4ff; }}

/* --- Code / pre / kbd ------------------------------------------- */
code, pre, kbd, tt, samp {{
  font-family: 'Space Mono', 'JetBrains Mono', monospace !important;
  background: rgba(0, 212, 255, 0.06) !important;
  color: #c8dbe8 !important;
  border: 1px solid rgba(0, 212, 255, 0.18);
  padding: 2px 6px;
  border-radius: 0;
}}
pre {{
  padding: 12px 14px;
  line-height: 1.5;
}}

/* --- Hero search bar (already pushed earlier) gets HUD frame ---- */
.gt-hero-search {{
  border: 1px solid rgba(0, 212, 255, 0.25) !important;
  clip-path: polygon(
    0 6px, 6px 0,
    calc(100% - 6px) 0, 100% 6px,
    100% calc(100% - 6px), calc(100% - 6px) 100%,
    6px 100%, 0 calc(100% - 6px)
  );
}}
.gt-hero-search input {{
  font-family: 'Space Mono', monospace !important;
  letter-spacing: 0.06em;
}}
.gt-hero-search button {{
  font-family: 'Michroma', sans-serif !important;
  letter-spacing: 0.22em !important;
}}

/* --- Selection highlight matches HUD palette -------------------- */
::selection {{ background: rgba(0, 212, 255, 0.35); color: #e8f7ff; }}

/* --- Edit-source textarea (when logged-in users edit) ----------- */
textarea#wpTextbox1 {{
  background: #050913 !important;
  color: #c8dbe8 !important;
  border: 1px solid rgba(0, 212, 255, 0.25) !important;
  font-family: 'Space Mono', monospace !important;
  font-size: 12.5px;
  line-height: 1.55;
  padding: 12px;
}}

/* --- Responsive trims ------------------------------------------- */
@media (max-width: 720px) {{
  body::before {{ opacity: 0.5; }}
  .mw-parser-output h2,
  .mw-parser-output .mw-heading2 {{ font-size: 17px !important; padding-left: 18px !important; }}
  table.wikitable, table.smwtable {{ font-size: 11px; }}
}}
"""


def push_hud_theme(site, dry_run: bool = False) -> str:
    """Push the HUD theme to MediaWiki:Common.css (idempotent).

    Two payloads, two idempotency markers:
    - HUD fonts block: PREPENDED so @import url(...Michroma...Space Mono)
      sits before any selector rules. CSS spec requires @import first
      or browsers silently drop them.
    - HUD theme block: APPENDED; contains all the selector rules.

    Applies the same Tactical Command aesthetic as the game app —
    Michroma/Space Mono typography, cyan-on-near-black palette, HUD
    panel chamfers, bracketed section headings, SMW-table re-skin.

    Returns ``"unchanged"`` only if BOTH markers already present.
    """
    page = site.pages["MediaWiki:Common.css"]
    current = page.text() if page.exists else ""

    need_fonts = _HUD_FONTS_MARKER not in current
    need_theme = _HUD_THEME_MARKER not in current

    if not need_fonts and not need_theme:
        print("  MediaWiki:Common.css: unchanged (HUD theme already present)")
        return "unchanged"

    new_text = current
    if need_fonts:
        new_text = _HUD_FONTS_BLOCK + "\n" + new_text
    if need_theme:
        new_text = (new_text.rstrip() + "\n\n" + _HUD_THEME_BLOCK) if new_text else _HUD_THEME_BLOCK

    if dry_run:
        which = []
        if need_fonts: which.append("fonts")
        if need_theme: which.append("theme")
        print(f"  MediaWiki:Common.css: would-update (HUD {'+'.join(which)})")
        return "would-update"

    page.edit(new_text, summary="add HUD theme CSS (Tactical Command aesthetic)")
    which = []
    if need_fonts: which.append("fonts")
    if need_theme: which.append("theme")
    print(f"  MediaWiki:Common.css: updated (HUD {'+'.join(which)})")
    return "updated"


# ---------------------------------------------------------------------------
# HUD Fonts JS — inject <link> tag directly (@import in ResourceLoader is dropped)
# ---------------------------------------------------------------------------

_HUD_FONTS_JS_MARKER = "/* --- Grid Tactics HUD Fonts Loader --- */"

_HUD_FONTS_JS_BLOCK = f"""{_HUD_FONTS_JS_MARKER}
(function gtHudFonts() {{
  if (document.getElementById('gt-hud-fonts')) return;
  var link = document.createElement('link');
  link.id = 'gt-hud-fonts';
  link.rel = 'stylesheet';
  link.href = 'https://fonts.googleapis.com/css2?family=Michroma&family=Space+Mono:wght@400;700&display=swap';
  document.head.appendChild(link);
}})();
"""


def push_hud_fonts_js(site, dry_run: bool = False) -> str:
    """Push a JS loader that injects the Google Fonts <link> directly.

    MediaWiki ResourceLoader silently drops @import rules from the CSS
    bundle regardless of their position — so we inject a <link> tag
    via MediaWiki:Common.js instead. Idempotent by marker + DOM id.
    """
    page = site.pages["MediaWiki:Common.js"]
    current = page.text() if page.exists else ""

    if _HUD_FONTS_JS_MARKER in current:
        print("  MediaWiki:Common.js: unchanged (HUD fonts loader already present)")
        return "unchanged"

    new_text = (current.rstrip() + "\n\n" + _HUD_FONTS_JS_BLOCK) if current.strip() else _HUD_FONTS_JS_BLOCK

    if dry_run:
        print("  MediaWiki:Common.js: would-update (HUD fonts loader)")
        return "would-update"

    page.edit(new_text, summary="add HUD fonts loader JS (Michroma + Space Mono via <link>)")
    print("  MediaWiki:Common.js: updated (HUD fonts loader)")
    return "updated"


# ---------------------------------------------------------------------------
# Mobile CSS
# ---------------------------------------------------------------------------


def push_mobile_css(site, dry_run: bool = False) -> str:
    """Append responsive mobile CSS to MediaWiki:Common.css (idempotent).

    Returns ``"created"``, ``"updated"``, or ``"unchanged"``.
    """
    page = site.pages["MediaWiki:Common.css"]

    if not page.exists:
        if dry_run:
            print("  MediaWiki:Common.css: would-create (mobile CSS)")
            return "would-create"
        page.edit(_MOBILE_CSS_BLOCK, summary="add mobile responsive CSS")
        print("  MediaWiki:Common.css: created (mobile CSS)")
        return "created"

    current = page.text()

    # Idempotent: if marker already present, skip
    if _MOBILE_CSS_MARKER in current:
        print("  MediaWiki:Common.css: unchanged (mobile CSS already present)")
        return "unchanged"

    new_text = current.rstrip() + "\n\n" + _MOBILE_CSS_BLOCK

    if dry_run:
        print("  MediaWiki:Common.css: would-update (append mobile CSS)")
        return "would-update"

    page.edit(new_text, summary="append mobile responsive CSS")
    print("  MediaWiki:Common.css: updated (appended mobile CSS)")
    return "updated"


# ---------------------------------------------------------------------------
# Logo generation
# ---------------------------------------------------------------------------


def generate_logo_png(output_path: str | Path) -> Path:
    """Generate a 135x135 PNG logo with 'GT' text.

    Uses Pillow if available, otherwise creates a minimal placeholder PNG.
    Returns the output path.
    """
    output_path = Path(output_path)
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGBA", (135, 135), (26, 26, 26, 255))
        draw = ImageDraw.Draw(img)

        # Draw border
        draw.rectangle([2, 2, 132, 132], outline=(100, 100, 100, 255), width=2)

        # Draw "GT" text centered
        try:
            font = ImageFont.truetype("arial.ttf", 52)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
            except (OSError, IOError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), "GT", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (135 - text_w) // 2
        y = (135 - text_h) // 2 - bbox[1]
        draw.text((x, y), "GT", fill=(255, 255, 255, 255), font=font)

        img.save(str(output_path), "PNG")
    except ImportError:
        print("  WARNING: Pillow not available, creating placeholder logo")
        _write_minimal_png(output_path, 135, 135)

    return output_path


def generate_favicon_ico(output_path: str | Path) -> Path:
    """Generate a 32x32 ICO favicon with 'GT' text.

    Uses Pillow if available, otherwise creates a minimal valid ICO.
    Returns the output path.
    """
    output_path = Path(output_path)
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGBA", (32, 32), (26, 26, 26, 255))
        draw = ImageDraw.Draw(img)

        # Draw border
        draw.rectangle([1, 1, 30, 30], outline=(100, 100, 100, 255), width=1)

        # Draw "GT" text centered
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            except (OSError, IOError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), "GT", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (32 - text_w) // 2
        y = (32 - text_h) // 2 - bbox[1]
        draw.text((x, y), "GT", fill=(255, 255, 255, 255), font=font)

        img.save(str(output_path), format="ICO", sizes=[(32, 32)])
    except ImportError:
        print("  WARNING: Pillow not available, creating minimal favicon")
        _write_minimal_ico(output_path)

    return output_path


def generate_favicon_png(output_path: str | Path) -> Path:
    """Generate a 32x32 PNG favicon with 'GT' text.

    PNG fallback for MediaWiki instances that ban ICO uploads.
    Returns the output path.
    """
    output_path = Path(output_path)
    try:
        from PIL import Image, ImageDraw, ImageFont

        img = Image.new("RGBA", (32, 32), (26, 26, 26, 255))
        draw = ImageDraw.Draw(img)

        draw.rectangle([1, 1, 30, 30], outline=(100, 100, 100, 255), width=1)

        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
            except (OSError, IOError):
                font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), "GT", font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (32 - text_w) // 2
        y = (32 - text_h) // 2 - bbox[1]
        draw.text((x, y), "GT", fill=(255, 255, 255, 255), font=font)

        img.save(str(output_path), "PNG")
    except ImportError:
        print("  WARNING: Pillow not available, creating placeholder favicon PNG")
        _write_minimal_png(output_path, 32, 32)

    return output_path


def _write_minimal_png(path: Path, width: int, height: int) -> None:
    """Write a minimal valid 1-pixel transparent PNG (fallback)."""
    import io
    import zlib

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    # Single transparent pixel row, repeated
    raw_row = b"\x00" + b"\x1a\x1a\x1a\xff" * width
    raw = raw_row * height
    idat_data = zlib.compress(raw)

    with open(path, "wb") as f:
        f.write(sig)
        f.write(_chunk(b"IHDR", ihdr_data))
        f.write(_chunk(b"IDAT", idat_data))
        f.write(_chunk(b"IEND", b""))


def _write_minimal_ico(path: Path) -> None:
    """Write a minimal valid 32x32 ICO file (fallback)."""
    # Create a minimal BMP-in-ICO
    size = 32
    # Generate raw BGRA pixel data (dark gray)
    pixels = b"\x1a\x1a\x1a\xff" * (size * size)
    # AND mask (1bpp, all zeros = fully opaque)
    and_mask = b"\x00" * (size * size // 8)

    # BMP info header (40 bytes)
    bmp_header = struct.pack(
        "<IiiHHIIiiII",
        40,             # header size
        size,           # width
        size * 2,       # height (doubled for ICO)
        1,              # planes
        32,             # bpp
        0,              # compression
        len(pixels) + len(and_mask),  # image size
        0, 0,           # ppm x, y
        0, 0,           # colors used, important
    )

    image_data = bmp_header + pixels + and_mask
    # ICO header
    ico_header = struct.pack("<HHH", 0, 1, 1)  # reserved, type=ICO, count=1
    # ICO directory entry
    ico_entry = struct.pack(
        "<BBBBHHII",
        size,           # width
        size,           # height
        0,              # color palette
        0,              # reserved
        1,              # planes
        32,             # bpp
        len(image_data),  # size
        len(ico_header) + 16,  # offset (header + 1 entry)
    )

    with open(path, "wb") as f:
        f.write(ico_header)
        f.write(ico_entry)
        f.write(image_data)


# ---------------------------------------------------------------------------
# Logo / favicon upload
# ---------------------------------------------------------------------------


def upload_logo(site, dry_run: bool = False) -> str:
    """Generate and upload the site logo as File:Wiki.png.

    Returns status string.
    """
    if dry_run:
        print("  Logo: would-upload File:Wiki.png")
        return "would-upload"

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        generate_logo_png(tmp_path)
        with open(tmp_path, "rb") as f:
            site.upload(
                file=f,
                filename="Wiki.png",
                description="Grid Tactics Wiki logo (135x135)",
                ignore=True,
                comment="upload site logo",
            )
        print("  Logo: uploaded File:Wiki.png")
        return "uploaded"
    except Exception as exc:
        exc_str = str(exc)
        if "fileexists-no-change" in exc_str or "duplicate" in exc_str.lower():
            print("  Logo: unchanged (already exists)")
            return "unchanged"
        print(f"  Logo: error - {exc}")
        return "error"
    finally:
        tmp_path.unlink(missing_ok=True)


def upload_favicon(site, dry_run: bool = False) -> str:
    """Generate and upload the favicon as File:Favicon.png.

    Uses PNG format because MediaWiki instances commonly ban ICO uploads.
    Returns status string.
    """
    if dry_run:
        print("  Favicon: would-upload File:Favicon.png")
        return "would-upload"

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        generate_favicon_png(tmp_path)
        with open(tmp_path, "rb") as f:
            site.upload(
                file=f,
                filename="Favicon.png",
                description="Grid Tactics Wiki favicon (32x32)",
                ignore=True,
                comment="upload site favicon",
            )
        print("  Favicon: uploaded File:Favicon.png")
        return "uploaded"
    except Exception as exc:
        exc_str = str(exc)
        if "fileexists-no-change" in exc_str or "duplicate" in exc_str.lower():
            print("  Favicon: unchanged (already exists)")
            return "unchanged"
        print(f"  Favicon: error - {exc}")
        return "error"
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Logo/Favicon CSS + JS configuration
# ---------------------------------------------------------------------------

_LOGO_CSS_MARKER = "/* --- Grid Tactics Logo --- */"

_LOGO_CSS_BLOCK = f"""{_LOGO_CSS_MARKER}
/* Override default MediaWiki logo with uploaded Wiki.png */
.citizen-header__logo img,
.mw-logo-icon {{
  background-image: url('/w/images/Wiki.png') !important;
  background-size: contain;
  width: 50px;
  height: 50px;
}}
.mw-wiki-logo {{
  background-image: url('/w/images/Wiki.png') !important;
  background-size: contain;
}}
"""

_FAVICON_JS_MARKER = "/* --- Grid Tactics Favicon --- */"

_FAVICON_JS_BLOCK = f"""{_FAVICON_JS_MARKER}
(function() {{
  var link = document.createElement('link');
  link.rel = 'icon';
  link.type = 'image/png';
  link.href = '/w/images/Favicon.png';
  document.head.appendChild(link);
}})();
"""


_HERO_SEARCH_CSS_MARKER = "/* --- Grid Tactics Hero Search --- */"

_HERO_SEARCH_CSS_BLOCK = f"""{_HERO_SEARCH_CSS_MARKER}
#gt-hero-search {{
  text-align: center;
  margin: 0 auto;
  max-width: 560px;
  padding: 1em 1em 0.5em;
  width: 100%;
  box-sizing: border-box;
}}

#gt-hero-search form {{
  display: flex;
  gap: 0;
}}

#gt-hero-search input[type="search"] {{
  flex: 1;
  padding: 0.75em 1.1em;
  font-size: 1rem;
  background: #0d0d2b !important;
  color: #e0e0ff !important;
  border: 2px solid #2a2a5a !important;
  border-right: none !important;
  border-radius: 8px 0 0 8px !important;
  outline: none !important;
  box-shadow: none !important;
  transition: border-color 0.2s, box-shadow 0.2s;
  font-family: 'Source Sans 3', 'Source Sans Pro', system-ui, sans-serif;
}}

#gt-hero-search input[type="search"]:focus {{
  border-color: #00d4ff !important;
  box-shadow: 0 0 12px rgba(0, 212, 255, 0.25) !important;
}}

#gt-hero-search input[type="search"]::placeholder {{
  color: #5a5a8a !important;
}}

#gt-hero-search button[type="submit"] {{
  padding: 0.75em 1.4em;
  background: #00d4ff !important;
  color: #0a0a1a !important;
  border: 2px solid #00d4ff !important;
  border-radius: 0 8px 8px 0 !important;
  font-weight: 700;
  font-size: 0.95rem;
  cursor: pointer;
  font-family: 'Montserrat', sans-serif;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  transition: background 0.2s, box-shadow 0.2s;
}}

#gt-hero-search button[type="submit"]:hover {{
  background: #33e0ff !important;
  box-shadow: 0 0 16px rgba(0, 212, 255, 0.4) !important;
}}
"""

_HERO_SEARCH_JS_MARKER = "/* --- Grid Tactics Hero Search --- */"

_HERO_SEARCH_JS_BLOCK = f"""{_HERO_SEARCH_JS_MARKER}
(function gtHeroSearch() {{
  function build() {{
    var wrapper = document.createElement('div');
    wrapper.id = 'gt-hero-search';

    var form = document.createElement('form');
    form.action = '/wiki/Special:Search';
    form.method = 'get';
    form.setAttribute('role', 'search');
    form.setAttribute('aria-label', 'Search Grid Tactics Wiki');

    var label = document.createElement('label');
    label.setAttribute('for', 'gt-main-search');
    label.style.cssText = 'position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);';
    label.textContent = 'Search Grid Tactics Wiki';

    var input = document.createElement('input');
    input.type = 'search';
    input.name = 'search';
    input.id = 'gt-main-search';
    input.placeholder = 'Search cards, keywords, elements, rules\\u2026';
    input.autocomplete = 'off';
    input.spellcheck = false;

    var btn = document.createElement('button');
    btn.type = 'submit';
    btn.textContent = 'Search';

    form.appendChild(label);
    form.appendChild(input);
    form.appendChild(btn);
    wrapper.appendChild(form);
    return wrapper;
  }}

  function tryInject() {{
    if (document.getElementById('gt-hero-search')) return true;
    /* Insert BEFORE <main> to get a full-width row above the page title.
       (Citizen skin uses flex inside <main>, so siblings would sit beside the title.) */
    var main = document.getElementById('content')
      || document.querySelector('main.mw-body')
      || document.querySelector('main');
    if (main && main.parentNode) {{
      main.parentNode.insertBefore(build(), main);
      return true;
    }}
    return false;
  }}

  /* Try immediately, then poll for the header (it appears as the body parses) */
  if (!tryInject()) {{
    var poll = setInterval(function() {{
      if (tryInject()) clearInterval(poll);
    }}, 30);
    /* Fallback: stop polling after 5s */
    setTimeout(function() {{ clearInterval(poll); }}, 5000);
  }}
}})();
"""


def push_hero_search(site, dry_run: bool = False) -> str:
    """Push hero search bar CSS and JS to the wiki (idempotent).

    Returns combined status string.
    """
    statuses = []

    # --- CSS ---
    css_page = site.pages["MediaWiki:Common.css"]
    css_text = css_page.text() if css_page.exists else ""

    if _HERO_SEARCH_CSS_MARKER in css_text:
        print("  Hero search CSS: unchanged (already present)")
        statuses.append("unchanged")
    elif dry_run:
        print("  Hero search CSS: would-update")
        statuses.append("would-update")
    else:
        new_css = css_text.rstrip() + "\n\n" + _HERO_SEARCH_CSS_BLOCK
        css_page.edit(new_css, summary="add hero search bar CSS")
        print("  Hero search CSS: updated")
        statuses.append("updated")

    # --- JS ---
    js_page = site.pages["MediaWiki:Common.js"]
    js_text = js_page.text() if js_page.exists else ""

    if _HERO_SEARCH_JS_MARKER in js_text:
        print("  Hero search JS: unchanged (already present)")
        statuses.append("unchanged")
    elif dry_run:
        print("  Hero search JS: would-update")
        statuses.append("would-update")
    else:
        new_js = js_text.rstrip() + "\n\n" + _HERO_SEARCH_JS_BLOCK if js_text.strip() else _HERO_SEARCH_JS_BLOCK
        js_page.edit(new_js, summary="add hero search bar JS")
        print("  Hero search JS: updated")
        statuses.append("updated")

    if all(s == "unchanged" for s in statuses):
        return "unchanged"
    return ", ".join(statuses)


def configure_logo_and_favicon(site, dry_run: bool = False) -> str:
    """Push CSS logo override and JS favicon injection (idempotent).

    - Appends logo CSS to MediaWiki:Common.css
    - Appends favicon JS to MediaWiki:Common.js

    Returns combined status string.
    """
    statuses = []

    # --- Logo CSS ---
    css_page = site.pages["MediaWiki:Common.css"]
    if css_page.exists:
        css_text = css_page.text()
    else:
        css_text = ""

    if _LOGO_CSS_MARKER in css_text:
        print("  Logo CSS: unchanged (already present)")
        statuses.append("unchanged")
    elif dry_run:
        print("  Logo CSS: would-update")
        statuses.append("would-update")
    else:
        new_css = css_text.rstrip() + "\n\n" + _LOGO_CSS_BLOCK
        css_page.edit(new_css, summary="add logo CSS override")
        print("  Logo CSS: updated")
        statuses.append("updated")

    # --- Favicon JS ---
    js_page = site.pages["MediaWiki:Common.js"]
    if js_page.exists:
        js_text = js_page.text()
    else:
        js_text = ""

    if _FAVICON_JS_MARKER in js_text:
        # Check if content matches (may need update if favicon format changed)
        # Extract the existing block and compare
        if "Favicon.png" in js_text:
            print("  Favicon JS: unchanged (already present)")
            statuses.append("unchanged")
        elif dry_run:
            print("  Favicon JS: would-update (fix favicon reference)")
            statuses.append("would-update")
        else:
            # Replace old favicon block with new one
            lines = js_text.split("\n")
            new_lines = []
            skip = False
            for line in lines:
                if _FAVICON_JS_MARKER in line:
                    skip = True
                    continue
                if skip and line.strip() == "":
                    skip = False
                    continue
                if skip:
                    continue
                new_lines.append(line)
            cleaned = "\n".join(new_lines).rstrip()
            new_js = cleaned + "\n\n" + _FAVICON_JS_BLOCK if cleaned else _FAVICON_JS_BLOCK
            js_page.edit(new_js, summary="update favicon JS (PNG format)")
            print("  Favicon JS: updated (fixed favicon reference)")
            statuses.append("updated")
    elif dry_run:
        print("  Favicon JS: would-update")
        statuses.append("would-update")
    else:
        new_js = js_text.rstrip() + "\n\n" + _FAVICON_JS_BLOCK if js_text.strip() else _FAVICON_JS_BLOCK
        js_page.edit(new_js, summary="add favicon injection JS")
        print("  Favicon JS: updated")
        statuses.append("updated")

    # Return combined status
    if all(s == "unchanged" for s in statuses):
        return "unchanged"
    return ", ".join(statuses)


# ---------------------------------------------------------------------------
# Search verification
# ---------------------------------------------------------------------------


def verify_search(site) -> bool:
    """Verify MediaWiki search returns expected results.

    Checks:
    - Searching 'Rat' returns Rat-tribe cards
    - Searching 'Ranged' returns cards with that keyword

    Returns True if both checks pass.
    """
    all_pass = True

    # Search for "Rat"
    print("  Searching for 'Rat'...")
    try:
        result = site.api("query", list="search", srsearch="Rat", srlimit=20)
        hits = result.get("query", {}).get("search", [])
        titles = [h["title"] for h in hits]
        print(f"    Found {len(hits)} results: {', '.join(titles[:10])}")

        # Check that at least one Rat-tribe card appears
        rat_cards = [t for t in titles if "Rat" in t]
        if rat_cards:
            print(f"    OK: Rat-tribe cards found: {', '.join(rat_cards[:5])}")
        else:
            print("    WARN: No Rat-related cards in search results")
            all_pass = False
    except Exception as exc:
        print(f"    ERROR: search failed: {exc}")
        all_pass = False

    # Search for "Ranged" (use srwhat=text for full-text search of page content)
    print("  Searching for 'Ranged'...")
    try:
        result = site.api(
            "query", list="search", srsearch="Ranged",
            srlimit=20, srwhat="text",
        )
        hits = result.get("query", {}).get("search", [])
        titles = [h["title"] for h in hits]
        print(f"    Found {len(hits)} results: {', '.join(titles[:10])}")

        if hits:
            print(f"    OK: Ranged keyword cards found")
        else:
            print("    WARN: No results for 'Ranged' search")
            all_pass = False
    except Exception as exc:
        print(f"    ERROR: search failed: {exc}")
        all_pass = False

    return all_pass
