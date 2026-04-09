"""
Weekly wiki backup via MediaWiki XML export API.

Exports all wiki pages as a MediaWiki-native XML dump (importable via
``maintenance/importDump.php``).  Also produces a JSON manifest of
backed-up page titles and revision IDs.

Usage::

    cd wiki
    python -m sync.backup                      # default output: ./backup_output
    python -m sync.backup --output-dir ./bak   # custom output directory
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import mwclient
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Credential loading (mirrors client.py but avoids login -- we use raw API)
# ---------------------------------------------------------------------------

_WIKI_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_WIKI_DIR / ".env")


def _get_site() -> mwclient.Site:
    """Return an authenticated mwclient Site for the configured wiki."""
    from sync.client import get_site

    return get_site()


# ---------------------------------------------------------------------------
# Page discovery
# ---------------------------------------------------------------------------

# Categories whose members should be backed up.
BACKUP_CATEGORIES = [
    "Card",
    "Element",
    "Tribe",
    "Keyword",
    "Rules",
    "Patch",
    "Deprecated",
]

# Individual pages to always include (may not be in any category above).
SPECIAL_PAGES = [
    "Main Page",
    "Template:Card",
    "Template:DeprecatedCard",
    "Template:Patch",
    "MediaWiki:Common.css",
    "Semantic:Showcase",
]


def _discover_pages(site: mwclient.Site) -> list[str]:
    """Return a deduplicated sorted list of page titles to back up."""
    titles: set[str] = set()

    for cat_name in BACKUP_CATEGORIES:
        cat = site.categories[cat_name]
        for page in cat:
            titles.add(page.name)

    titles.update(SPECIAL_PAGES)
    return sorted(titles)


# ---------------------------------------------------------------------------
# XML export
# ---------------------------------------------------------------------------

def _export_pages(site: mwclient.Site, titles: list[str]) -> str:
    """Export *titles* via the MediaWiki XML export API.

    Uses ``action=query&export=1`` which returns Special:Export XML for the
    requested pages (including full revision text).

    Pages are exported in batches of 25 (API default limit for export).
    The individual XML fragments are merged into a single document.
    """
    # For simplicity, use the raw API via mwclient's api method.
    # action=query&titles=...&export=1&exportnowrap=1 returns raw XML.
    batch_size = 25
    all_xml_pages: list[str] = []
    xml_header = ""
    xml_ns = ""

    for i in range(0, len(titles), batch_size):
        batch = titles[i : i + batch_size]
        titles_param = "|".join(batch)

        result = site.api(
            "query",
            titles=titles_param,
            export=1,
            exportnowrap=1,
        )

        # The result contains an 'export' key with the XML string when
        # exportnowrap is used.  mwclient parses the outer JSON for us.
        xml_str = result.get("export", {})
        if isinstance(xml_str, dict):
            xml_str = xml_str.get("*", "")
        if not xml_str:
            continue

        # Parse the XML to extract <page> elements.
        root = ET.fromstring(xml_str)
        ns = ""
        # Detect namespace from root tag.
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        if not xml_header:
            xml_header = xml_str[: xml_str.find("<page")]
            if "<page" not in xml_str:
                # Edge case: no pages in this batch.
                xml_header = ""
            xml_ns = ns

        for page_el in root.findall(f"{ns}page"):
            all_xml_pages.append(ET.tostring(page_el, encoding="unicode"))

    if not xml_header:
        # Construct a minimal header.
        return (
            '<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">\n'
            + "\n".join(all_xml_pages)
            + "\n</mediawiki>\n"
        )

    # Reconstruct: header + pages + closing tag.
    # The header from the first batch ends just before the first <page>.
    closing = "</mediawiki>"
    xml_body = "\n".join(all_xml_pages)
    return f"{xml_header.rstrip()}\n{xml_body}\n{closing}\n"


# ---------------------------------------------------------------------------
# JSON manifest
# ---------------------------------------------------------------------------

def _build_manifest(
    xml_content: str, titles_requested: list[str]
) -> dict:
    """Parse the XML export and build a JSON manifest of pages + revisions."""
    root = ET.fromstring(xml_content)
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"

    pages_found: list[dict] = []
    for page_el in root.findall(f"{ns}page"):
        title_el = page_el.find(f"{ns}title")
        rev_el = page_el.find(f"{ns}revision/{ns}id")
        title = title_el.text if title_el is not None else "?"
        rev_id = rev_el.text if rev_el is not None else "?"
        pages_found.append({"title": title, "revision_id": str(rev_id)})

    return {
        "backup_date": datetime.now(timezone.utc).isoformat(),
        "pages_requested": len(titles_requested),
        "pages_exported": len(pages_found),
        "categories_covered": BACKUP_CATEGORIES,
        "special_pages_included": SPECIAL_PAGES,
        "pages": pages_found,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(output_dir: str = "./backup_output") -> Path:
    """Run the wiki backup and return the path to the XML file."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("Connecting to wiki...")
    site = _get_site()

    print("Discovering pages...")
    titles = _discover_pages(site)
    print(f"  Found {len(titles)} pages to back up.")

    print("Exporting pages via XML export API...")
    xml_content = _export_pages(site, titles)

    # Write XML file.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml_path = out / f"wiki_backup_{today}.xml"
    xml_path.write_text(xml_content, encoding="utf-8")

    # Write JSON manifest.
    manifest = _build_manifest(xml_content, titles)
    manifest_path = out / f"wiki_backup_{today}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Summary.
    size_kb = xml_path.stat().st_size / 1024
    print(f"\nBackup complete:")
    print(f"  XML:      {xml_path}  ({size_kb:.1f} KB)")
    print(f"  Manifest: {manifest_path}")
    print(f"  Pages:    {manifest['pages_exported']} exported")

    return xml_path


# ---------------------------------------------------------------------------
# CLI entry point (python -m sync.backup)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export Grid Tactics Wiki pages as MediaWiki XML backup."
    )
    parser.add_argument(
        "--output-dir",
        default="./backup_output",
        help="Directory to write backup files (default: ./backup_output)",
    )
    args = parser.parse_args()

    try:
        main(output_dir=args.output_dir)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
