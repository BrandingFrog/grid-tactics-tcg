"""
Unit tests for wiki drift detection (check_drift.py).

Validates drift detection logic with mocked wiki responses -- no live
wiki connection needed.

Run from ``wiki/`` directory::

    cd wiki
    python -m pytest tests/test_check_drift.py -v
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sync.check_drift import DriftReport, check_drift, main
from sync.sync_cards import build_card_name_map, card_to_wikitext

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CARDS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cards"
ART_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "src"
    / "grid_tactics"
    / "server"
    / "static"
    / "art"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page(exists: bool = False, text: str = "") -> MagicMock:
    """Create a mock mwclient page object."""
    page = MagicMock()
    page.exists = exists
    page.text.return_value = text
    return page


def _make_mock_site(page_store: dict[str, MagicMock]) -> MagicMock:
    """Create a mock mwclient.Site backed by a page store dict."""
    site = MagicMock()
    site.pages.__getitem__ = lambda self, title: page_store.get(
        title, _make_mock_page(exists=False)
    )
    return site


def _pick_card_files(tmp_path: Path, count: int = 2) -> Path:
    """Copy *count* card JSON files to tmp_path and return that directory."""
    cards_tmp = tmp_path / "cards"
    cards_tmp.mkdir()
    for src in sorted(CARDS_DIR.glob("*.json"))[:count]:
        shutil.copy(src, cards_tmp / src.name)
    return cards_tmp


def _build_clean_page_store(
    cards_dir: Path,
    art_dir: Path,
) -> dict[str, MagicMock]:
    """Build a page store where every card page returns the expected wikitext."""
    name_map = build_card_name_map(cards_dir)
    page_store: dict[str, MagicMock] = {}

    for path in sorted(cards_dir.glob("*.json")):
        card = json.loads(path.read_text(encoding="utf-8"))
        card_id = card.get("card_id", "")
        card_name = card.get("name", "")
        art_exists = (art_dir / f"{card_id}.png").exists()
        expected = card_to_wikitext(card, name_map, art_exists=art_exists)
        page_store[f"Card:{card_name}"] = _make_mock_page(
            exists=True, text=expected.rstrip()
        )

    return page_store


# ---------------------------------------------------------------------------
# TestCheckDrift
# ---------------------------------------------------------------------------


class TestCheckDrift:
    """Tests for the ``check_drift()`` function with mocked wiki responses."""

    def test_no_drift_clean(self, tmp_path: Path):
        """Mock site returns expected wikitext for every card -- no drift."""
        cards_tmp = _pick_card_files(tmp_path, count=2)
        page_store = _build_clean_page_store(cards_tmp, ART_DIR)
        site = _make_mock_site(page_store)

        reports = check_drift(
            site,
            cards_dir=cards_tmp,
            art_dir=ART_DIR,
            cards_only=True,
        )
        assert reports == [], f"Expected clean, got {reports}"

    def test_content_mismatch_detected(self, tmp_path: Path):
        """One card page has manually edited content -- drift detected."""
        cards_tmp = _pick_card_files(tmp_path, count=2)
        page_store = _build_clean_page_store(cards_tmp, ART_DIR)
        site = _make_mock_site(page_store)

        # Pick the first card and corrupt its wiki content
        first_json = sorted(cards_tmp.glob("*.json"))[0]
        card = json.loads(first_json.read_text(encoding="utf-8"))
        card_name = card["name"]
        page_title = f"Card:{card_name}"

        # Append junk to simulate manual edit
        original_text = page_store[page_title].text()
        page_store[page_title] = _make_mock_page(
            exists=True, text=original_text + "\nMANUALLY EDITED"
        )

        reports = check_drift(
            site,
            cards_dir=cards_tmp,
            art_dir=ART_DIR,
            cards_only=True,
        )
        assert len(reports) == 1
        assert reports[0].page_title == page_title
        assert reports[0].drift_type == "content_mismatch"

    def test_missing_page_detected(self, tmp_path: Path):
        """One card page does not exist -- missing page drift detected."""
        cards_tmp = _pick_card_files(tmp_path, count=2)
        page_store = _build_clean_page_store(cards_tmp, ART_DIR)
        site = _make_mock_site(page_store)

        # Remove one card page from the store (simulate missing wiki page)
        first_json = sorted(cards_tmp.glob("*.json"))[0]
        card = json.loads(first_json.read_text(encoding="utf-8"))
        card_name = card["name"]
        page_title = f"Card:{card_name}"

        page_store[page_title] = _make_mock_page(exists=False)

        reports = check_drift(
            site,
            cards_dir=cards_tmp,
            art_dir=ART_DIR,
            cards_only=True,
        )
        assert len(reports) == 1
        assert reports[0].page_title == page_title
        assert reports[0].drift_type == "missing_page"

    def test_multiple_drifts(self, tmp_path: Path):
        """Multiple drift types detected across cards."""
        cards_tmp = _pick_card_files(tmp_path, count=3)
        page_store = _build_clean_page_store(cards_tmp, ART_DIR)
        site = _make_mock_site(page_store)

        card_files = sorted(cards_tmp.glob("*.json"))

        # Card 0: content mismatch
        card0 = json.loads(card_files[0].read_text(encoding="utf-8"))
        title0 = f"Card:{card0['name']}"
        page_store[title0] = _make_mock_page(
            exists=True,
            text=page_store[title0].text() + "\nTAMPERED",
        )

        # Card 1: content mismatch
        card1 = json.loads(card_files[1].read_text(encoding="utf-8"))
        title1 = f"Card:{card1['name']}"
        page_store[title1] = _make_mock_page(
            exists=True,
            text=page_store[title1].text() + "\nALSO TAMPERED",
        )

        # Card 2: missing page
        card2 = json.loads(card_files[2].read_text(encoding="utf-8"))
        title2 = f"Card:{card2['name']}"
        page_store[title2] = _make_mock_page(exists=False)

        reports = check_drift(
            site,
            cards_dir=cards_tmp,
            art_dir=ART_DIR,
            cards_only=True,
        )
        assert len(reports) == 3

        types = {r.drift_type for r in reports}
        assert "content_mismatch" in types
        assert "missing_page" in types

        mismatch_count = sum(1 for r in reports if r.drift_type == "content_mismatch")
        missing_count = sum(1 for r in reports if r.drift_type == "missing_page")
        assert mismatch_count == 2
        assert missing_count == 1


# ---------------------------------------------------------------------------
# TestCheckDriftCLI
# ---------------------------------------------------------------------------


class TestCheckDriftCLI:
    """Tests for the ``main()`` CLI entry point."""

    @patch("sync.check_drift.get_site")
    def test_cli_exit_zero_no_drift(self, mock_get_site: MagicMock):
        """CLI returns 0 when no drift is detected."""
        mock_site = MagicMock()
        mock_get_site.return_value = mock_site

        with patch("sync.check_drift.check_drift", return_value=[]) as mock_cd:
            exit_code = main([])
            mock_cd.assert_called_once()
            assert exit_code == 0

    @patch("sync.check_drift.get_site")
    def test_cli_exit_one_on_drift(self, mock_get_site: MagicMock):
        """CLI returns 1 when drift is detected."""
        mock_site = MagicMock()
        mock_get_site.return_value = mock_site

        drift = [
            DriftReport(
                page_title="Card:Ratchanter",
                drift_type="content_mismatch",
                details="some diff output",
            ),
        ]
        with patch("sync.check_drift.check_drift", return_value=drift) as mock_cd:
            exit_code = main([])
            mock_cd.assert_called_once()
            assert exit_code == 1
