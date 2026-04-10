"""
Drift detection CLI for the Grid Tactics Wiki.

Compares live wiki page content against expected wikitext computed from
JSON source files.  Detects manual edits, missing pages, and content
mismatches across card pages, taxonomy pages, the Main Page, and the
Semantic:Showcase page.

Usage::

    cd wiki
    python -m sync.check_drift              # Full drift check
    python -m sync.check_drift --cards-only # Cards only (faster)
    python -m sync.check_drift --verbose    # Show unified diffs
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sync.client import MissingCredentialsError, get_site
from sync.sync_cards import build_card_name_map, card_to_wikitext

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CARDS_DIR = _REPO_ROOT / "data" / "cards"
_ART_DIR = _REPO_ROOT / "src" / "grid_tactics" / "server" / "static" / "art"
_GLOSSARY_PATH = _REPO_ROOT / "data" / "GLOSSARY.md"

# ---------------------------------------------------------------------------
# DriftReport dataclass
# ---------------------------------------------------------------------------


@dataclass
class DriftReport:
    """Record of a single drifted page."""

    page_title: str
    drift_type: str  # "content_mismatch", "missing_page", "extra_page"
    details: str = ""


# ---------------------------------------------------------------------------
# Diff helper
# ---------------------------------------------------------------------------


def _unified_diff_snippet(
    expected: str,
    actual: str,
    title: str,
    max_lines: int = 20,
) -> str:
    """Return a unified diff snippet (first *max_lines* lines)."""
    diff = list(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"expected:{title}",
            tofile=f"live:{title}",
            lineterm="",
        )
    )
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"... ({len(diff) - max_lines} more lines)"]
    return "\n".join(diff)


def _count_diff_lines(expected: str, actual: str) -> int:
    """Count lines that differ between expected and actual."""
    diff = list(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
        )
    )
    # Subtract header lines (--- and +++ and @@ lines)
    return max(0, len([l for l in diff if l.startswith("+") or l.startswith("-")]) - 2)


# ---------------------------------------------------------------------------
# Card drift checking
# ---------------------------------------------------------------------------


def _check_card_drift(
    site,
    cards_dir: Path,
    art_dir: Path,
) -> list[DriftReport]:
    """Check all card pages for drift against JSON source."""
    reports: list[DriftReport] = []

    # Load cards and name map
    name_map = build_card_name_map(cards_dir)
    for path in sorted(cards_dir.glob("*.json")):
        try:
            card = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            continue

        card_id = card.get("card_id", "")
        card_name = card.get("name", "")
        art_exists = (art_dir / f"{card_id}.png").exists()
        page_title = f"Card:{card_name}"

        page = site.pages[page_title]
        if not page.exists:
            reports.append(DriftReport(
                page_title=page_title,
                drift_type="missing_page",
            ))
            continue

        live = page.text()

        # Extract history from live page so we compare like-for-like
        from sync.card_history import extract_history_section
        _, live_history = extract_history_section(live)

        expected = card_to_wikitext(
            card, name_map, art_exists=art_exists,
            history_entries=live_history if live_history else None,
        )
        if live.rstrip() != expected.rstrip():
            details = _unified_diff_snippet(expected, live, page_title)
            reports.append(DriftReport(
                page_title=page_title,
                drift_type="content_mismatch",
                details=details,
            ))

    return reports


# ---------------------------------------------------------------------------
# Taxonomy drift checking
# ---------------------------------------------------------------------------


def _check_taxonomy_drift(site, cards_dir: Path, glossary_path: Path) -> list[DriftReport]:
    """Check element, tribe, keyword, and rules pages for drift."""
    from sync.sync_taxonomy import (
        RULES_PAGES,
        element_page_wikitext,
        keyword_page_wikitext,
        parse_glossary,
        scan_elements,
        scan_tribes,
        tribe_page_wikitext,
    )

    reports: list[DriftReport] = []

    # Elements
    elements = scan_elements(cards_dir)
    for elem in elements:
        expected = element_page_wikitext(elem)
        page = site.pages[elem]
        if not page.exists:
            reports.append(DriftReport(page_title=elem, drift_type="missing_page"))
            continue
        live = page.text()
        if live.rstrip() != expected.rstrip():
            details = _unified_diff_snippet(expected, live, elem)
            reports.append(DriftReport(
                page_title=elem, drift_type="content_mismatch", details=details,
            ))

    # Tribes
    tribes = scan_tribes(cards_dir)
    for tribe in tribes:
        expected = tribe_page_wikitext(tribe)
        page = site.pages[tribe]
        if not page.exists:
            reports.append(DriftReport(page_title=tribe, drift_type="missing_page"))
            continue
        live = page.text()
        if live.rstrip() != expected.rstrip():
            details = _unified_diff_snippet(expected, live, tribe)
            reports.append(DriftReport(
                page_title=tribe, drift_type="content_mismatch", details=details,
            ))

    # Keywords
    if glossary_path.exists():
        keywords = parse_glossary(glossary_path)
        for kw in keywords:
            expected = keyword_page_wikitext(kw["keyword"], kw["description"], kw["category"])
            page = site.pages[kw["keyword"]]
            if not page.exists:
                reports.append(DriftReport(
                    page_title=kw["keyword"], drift_type="missing_page",
                ))
                continue
            live = page.text()
            if live.rstrip() != expected.rstrip():
                details = _unified_diff_snippet(expected, live, kw["keyword"])
                reports.append(DriftReport(
                    page_title=kw["keyword"],
                    drift_type="content_mismatch",
                    details=details,
                ))

    # Rules pages
    for title, expected in RULES_PAGES.items():
        page = site.pages[title]
        if not page.exists:
            reports.append(DriftReport(page_title=title, drift_type="missing_page"))
            continue
        live = page.text()
        if live.rstrip() != expected.rstrip():
            details = _unified_diff_snippet(expected, live, title)
            reports.append(DriftReport(
                page_title=title, drift_type="content_mismatch", details=details,
            ))

    return reports


# ---------------------------------------------------------------------------
# Homepage / Showcase drift checking
# ---------------------------------------------------------------------------


def _check_homepage_drift(site) -> list[DriftReport]:
    """Check Main Page for drift."""
    from sync.sync_homepage import main_page_wikitext

    reports: list[DriftReport] = []
    expected = main_page_wikitext()
    page = site.pages["Main Page"]

    if not page.exists:
        reports.append(DriftReport(page_title="Main Page", drift_type="missing_page"))
    else:
        live = page.text()
        if live.rstrip() != expected.rstrip():
            details = _unified_diff_snippet(expected, live, "Main Page")
            reports.append(DriftReport(
                page_title="Main Page",
                drift_type="content_mismatch",
                details=details,
            ))

    return reports


def _check_showcase_drift(site) -> list[DriftReport]:
    """Check Semantic:Showcase page for drift."""
    from sync.sync_showcase import showcase_page_wikitext

    reports: list[DriftReport] = []
    expected = showcase_page_wikitext()
    page = site.pages["Semantic:Showcase"]

    if not page.exists:
        reports.append(DriftReport(
            page_title="Semantic:Showcase", drift_type="missing_page",
        ))
    else:
        live = page.text()
        if live.rstrip() != expected.rstrip():
            details = _unified_diff_snippet(expected, live, "Semantic:Showcase")
            reports.append(DriftReport(
                page_title="Semantic:Showcase",
                drift_type="content_mismatch",
                details=details,
            ))

    return reports


# ---------------------------------------------------------------------------
# Main check_drift function
# ---------------------------------------------------------------------------


def check_drift(
    site,
    cards_dir: Path = _CARDS_DIR,
    art_dir: Path = _ART_DIR,
    glossary_path: Path = _GLOSSARY_PATH,
    cards_only: bool = False,
) -> list[DriftReport]:
    """Run drift detection across all bot-managed wiki pages.

    Parameters
    ----------
    site:
        Authenticated ``mwclient.Site`` instance.
    cards_dir:
        Path to ``data/cards/`` containing card JSON files.
    art_dir:
        Path to art directory for card art existence checks.
    glossary_path:
        Path to ``data/GLOSSARY.md``.
    cards_only:
        If True, only check card pages (faster for CI).

    Returns
    -------
    list[DriftReport]
        One entry per drifted/missing page. Empty list means clean.
    """
    reports: list[DriftReport] = []

    # Always check cards
    reports.extend(_check_card_drift(site, cards_dir, art_dir))

    if not cards_only:
        # Taxonomy pages (elements, tribes, keywords, rules)
        reports.extend(_check_taxonomy_drift(site, cards_dir, glossary_path))

        # Homepage
        reports.extend(_check_homepage_drift(site))

        # Showcase
        reports.extend(_check_showcase_drift(site))

    return reports


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for drift detection.

    Returns 0 if clean, 1 if drift found, 2 on connection error.
    """
    parser = argparse.ArgumentParser(
        description="Detect drift between wiki pages and JSON source data.",
    )
    parser.add_argument(
        "--cards-only",
        action="store_true",
        help="Check only card pages (faster for CI)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show unified diff for each mismatched page",
    )
    args = parser.parse_args(argv)

    try:
        site = get_site()
    except MissingCredentialsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    scope = "cards only" if args.cards_only else "full"
    print(f"Running drift check ({scope})...")

    reports = check_drift(site, cards_only=args.cards_only)

    # Count pages checked (approximate from JSON files + taxonomy)
    card_count = len(list(_CARDS_DIR.glob("*.json")))
    if args.cards_only:
        pages_checked = card_count
    else:
        # Cards + elements(7) + tribes(~14) + keywords(~27) + rules(6) + Main Page + Showcase
        pages_checked = card_count + 56  # approximate

    # Report
    mismatched = sum(1 for r in reports if r.drift_type == "content_mismatch")
    missing = sum(1 for r in reports if r.drift_type == "missing_page")

    if reports:
        for r in reports:
            diff_info = ""
            if r.drift_type == "content_mismatch":
                diff_lines = _count_diff_lines("", r.details) if r.details else 0
                diff_info = f" ({diff_lines} lines differ)" if diff_lines else ""
            print(f"DRIFT {r.page_title} -- {r.drift_type}{diff_info}")
            if args.verbose and r.details:
                print(r.details)
                print()

        print(f"\nDrift check: {pages_checked} pages checked, "
              f"{mismatched} drifted, {missing} missing")
        return 1
    else:
        print(f"Drift check: {pages_checked} pages checked, 0 issues. CLEAN.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
