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
# Top header bar (matches game site header)
# ---------------------------------------------------------------------------

_HEADER_BAR_CSS_MARKER = "/* --- Grid Tactics Header Bar --- */"

_HEADER_BAR_CSS_BLOCK = f"""{_HEADER_BAR_CSS_MARKER}
/* Top nav bar matching the game site header */
.gt-header {{
  background: linear-gradient(135deg, #0f0f24, #161638);
  border-bottom: 1px solid #252545;
  padding: 0 20px;
  display: flex;
  align-items: center;
  height: 52px;
  position: sticky;
  top: 0;
  z-index: 1000;
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
  box-sizing: border-box;
}}

.gt-header * {{
  box-sizing: border-box;
}}

.gt-header-logo {{
  font-size: 15px;
  font-weight: 800;
  color: #00d4ff;
  letter-spacing: 2px;
  margin-right: 32px;
  white-space: nowrap;
  text-decoration: none;
}}

.gt-header-logo:hover {{
  color: #00d4ff;
  text-decoration: none;
}}

.gt-header-nav {{
  display: flex;
  gap: 2px;
  flex: 1;
}}

.gt-header-nav a {{
  background: none;
  border: none;
  color: #777;
  font-size: 13px;
  font-weight: 600;
  padding: 14px 16px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  text-decoration: none;
  display: inline-block;
  line-height: calc(52px - 28px);
}}

.gt-header-nav a:hover {{
  color: #e0e0e0;
  text-decoration: none;
}}

.gt-header-nav a.gt-active {{
  color: #00d4ff;
  border-bottom-color: #00d4ff;
}}

.gt-header-right {{
  display: flex;
  align-items: center;
  gap: 8px;
}}

.gt-header-search {{
  position: relative;
}}

.gt-header-search input {{
  width: 200px;
  padding: 6px 32px 6px 12px;
  font-size: 13px;
  font-family: 'Inter', system-ui, sans-serif;
  background: rgba(255,255,255,0.07);
  color: #e0e0e0;
  border: 1px solid #333;
  border-radius: 6px;
  outline: none;
  transition: border-color 0.2s, width 0.2s;
}}

.gt-header-search input::placeholder {{
  color: #555;
}}

.gt-header-search input:focus {{
  border-color: #00d4ff;
  width: 260px;
}}

.gt-header-search button {{
  position: absolute;
  right: 2px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: #555;
  cursor: pointer;
  padding: 4px 6px;
  font-size: 14px;
  line-height: 1;
}}

.gt-header-search button:hover {{
  color: #00d4ff;
}}

/* Push Citizen skin content below the sticky header */
.citizen-header {{
  top: 52px !important;
}}

body {{
  padding-top: 52px;
}}

.gt-header {{
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
}}

@media (max-width: 600px) {{
  .gt-header {{
    padding: 0 8px;
    height: 44px;
  }}
  .gt-header-logo {{
    font-size: 12px;
    margin-right: 12px;
    letter-spacing: 1px;
  }}
  .gt-header-nav a {{
    padding: 10px 8px;
    font-size: 11px;
    line-height: calc(44px - 20px);
  }}
  .gt-header-search input {{
    width: 120px;
    font-size: 12px;
    padding: 5px 28px 5px 8px;
  }}
  .gt-header-search input:focus {{
    width: 160px;
  }}
  body {{
    padding-top: 44px;
  }}
  .citizen-header {{
    top: 44px !important;
  }}
}}
"""

_HEADER_BAR_JS_MARKER = "/* --- Grid Tactics Header Bar --- */"

_HEADER_BAR_JS_BLOCK = f"""{_HEADER_BAR_JS_MARKER}
(function() {{
  'use strict';
  if (document.querySelector('.gt-header')) return;

  var header = document.createElement('header');
  header.className = 'gt-header';
  header.innerHTML = ''
    + '<a class="gt-header-logo" href="/wiki/Main_Page">GRID TACTICS</a>'
    + '<nav class="gt-header-nav">'
    +   '<a href="/wiki/Main_Page">Home</a>'
    +   '<a href="/wiki/Category:Card">Cards</a>'
    +   '<a href="/wiki/Deck_Building_Guide">Decks</a>'
    +   '<a href="/wiki/Patch:Index">Patches</a>'
    + '</nav>'
    + '<div class="gt-header-right">'
    +   '<div class="gt-header-search">'
    +     '<form action="/wiki/Special:Search" method="get">'
    +       '<input type="search" name="search" placeholder="Search wiki…" autocomplete="off" />'
    +       '<button type="submit" aria-label="Search">&#128269;</button>'
    +     '</form>'
    +   '</div>'
    + '</div>';

  document.body.insertBefore(header, document.body.firstChild);
}})();
"""

# Legacy marker cleanup: remove old search bar blocks if present
_OLD_SEARCH_BAR_CSS_MARKER = "/* --- Grid Tactics Search Bar --- */"
_OLD_SEARCH_BAR_JS_MARKER = "/* --- Grid Tactics Search Bar --- */"


def _remove_old_block(text: str, marker: str) -> str:
    """Remove a marker-delimited CSS/JS block from page text."""
    if marker not in text:
        return text
    lines = text.split("\n")
    result: list[str] = []
    skip = False
    for line in lines:
        if marker in line:
            skip = True
            continue
        if skip:
            # End of block: next marker or blank line after a closing brace/paren
            if line.strip() == "" and result and result[-1].strip() == "":
                continue  # skip extra blank lines
            if line.strip() == "":
                skip = False
                continue
            continue
        result.append(line)
    return "\n".join(result)


def push_header_bar_css(site, dry_run: bool = False) -> str:
    """Push header bar CSS to MediaWiki:Common.css (idempotent).

    Also removes the old search bar CSS block if present.
    """
    page = site.pages["MediaWiki:Common.css"]
    current = page.text() if page.exists else ""

    # Remove old search bar CSS if present
    cleaned = _remove_old_block(current, _OLD_SEARCH_BAR_CSS_MARKER)
    had_old = cleaned != current

    if _HEADER_BAR_CSS_MARKER in cleaned:
        if had_old:
            if dry_run:
                print("  MediaWiki:Common.css: would-update (remove old search bar CSS)")
                return "would-update"
            page.edit(cleaned, summary="remove old search bar CSS (replaced by header bar)")
            print("  MediaWiki:Common.css: updated (removed old search bar CSS)")
            return "updated"
        print("  MediaWiki:Common.css: unchanged (header bar CSS already present)")
        return "unchanged"

    new_text = (cleaned.rstrip() + "\n\n" + _HEADER_BAR_CSS_BLOCK) if cleaned.strip() else _HEADER_BAR_CSS_BLOCK

    if dry_run:
        print("  MediaWiki:Common.css: would-update (header bar CSS)")
        return "would-update"

    page.edit(new_text, summary="add header bar CSS (matches game site)")
    print("  MediaWiki:Common.css: updated (header bar CSS)")
    return "updated"


def push_header_bar_js(site, dry_run: bool = False) -> str:
    """Push header bar JS to MediaWiki:Common.js (idempotent).

    Also removes the old search bar JS block if present.
    """
    page = site.pages["MediaWiki:Common.js"]
    current = page.text() if page.exists else ""

    # Remove old search bar JS if present
    cleaned = _remove_old_block(current, _OLD_SEARCH_BAR_JS_MARKER)
    had_old = cleaned != current

    if _HEADER_BAR_JS_MARKER in cleaned:
        if had_old:
            if dry_run:
                print("  MediaWiki:Common.js: would-update (remove old search bar JS)")
                return "would-update"
            page.edit(cleaned, summary="remove old search bar JS (replaced by header bar)")
            print("  MediaWiki:Common.js: updated (removed old search bar JS)")
            return "updated"
        print("  MediaWiki:Common.js: unchanged (header bar JS already present)")
        return "unchanged"

    new_text = (cleaned.rstrip() + "\n\n" + _HEADER_BAR_JS_BLOCK) if cleaned.strip() else _HEADER_BAR_JS_BLOCK

    if dry_run:
        print("  MediaWiki:Common.js: would-update (header bar JS)")
        return "would-update"

    page.edit(new_text, summary="add header bar JS (matches game site)")
    print("  MediaWiki:Common.js: updated (header bar JS)")
    return "updated"


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
