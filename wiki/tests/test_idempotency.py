"""
Idempotency regression tests for wiki sync operations.

Proves that a second sync run against the same state produces zero edits.
All wiki API calls are mocked via ``unittest.mock.MagicMock``.

Run from ``wiki/`` directory::

    cd wiki
    python -m pytest tests/test_idempotency.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sync.sync_cards import build_card_name_map, card_to_wikitext
from sync.sync_homepage import main_page_wikitext, sync_main_page
from sync.sync_taxonomy import upsert_taxonomy_pages, element_page_wikitext

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CARDS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cards"
ART_DIR = Path(__file__).resolve().parent.parent.parent / "src" / "grid_tactics" / "server" / "static" / "art"


@pytest.fixture(scope="module")
def name_map() -> dict[str, str]:
    return build_card_name_map(CARDS_DIR)


@pytest.fixture(scope="module")
def ratchanter_card() -> dict:
    return json.loads(
        (CARDS_DIR / "minion_ratchanter.json").read_text(encoding="utf-8")
    )


def _make_mock_page(exists: bool = False, text: str = "") -> MagicMock:
    """Create a mock mwclient page object."""
    page = MagicMock()
    page.exists = exists
    page.text.return_value = text
    return page


def _make_mock_site(page_store: dict[str, MagicMock]) -> MagicMock:
    """Create a mock mwclient.Site backed by a page store dict."""
    site = MagicMock()
    site.pages.__getitem__ = lambda self, title: page_store.setdefault(
        title, _make_mock_page()
    )
    return site


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIdempotency:

    def test_card_upsert_idempotent(self, ratchanter_card, name_map):
        """Second upsert_card_page returns 'unchanged', zero .edit() calls."""
        from sync.sync_wiki import upsert_card_page

        card = ratchanter_card
        card_id = card["card_id"]
        card_name = card["name"]
        art_exists = (ART_DIR / f"{card_id}.png").exists()
        expected_wikitext = card_to_wikitext(card, name_map, art_exists=art_exists)

        page_store: dict[str, MagicMock] = {}
        site = _make_mock_site(page_store)

        # --- First call: page doesn't exist, should create ---
        page_title = f"Card:{card_name}"
        page_store[page_title] = _make_mock_page(exists=False)

        result1 = upsert_card_page(site, card, name_map, ART_DIR, dry_run=False)
        assert result1["status"] == "created"

        # Capture the wikitext that was written via .edit()
        page_mock = page_store[page_title]
        page_mock.edit.assert_called_once()
        written_text = page_mock.edit.call_args[0][0]

        # --- Simulate MediaWiki state after creation ---
        # MediaWiki strips trailing newline, so store without it
        page_store[page_title] = _make_mock_page(
            exists=True, text=written_text.rstrip()
        )

        # --- Second call: same card data, should be unchanged ---
        result2 = upsert_card_page(site, card, name_map, ART_DIR, dry_run=False)
        assert result2["status"] == "unchanged"

        # The second page mock should NOT have had .edit() called
        page_store[page_title].edit.assert_not_called()

    def test_taxonomy_upsert_idempotent(self):
        """Second upsert_taxonomy_pages returns all 'unchanged', zero .edit() calls."""
        # Build a small taxonomy page set
        pages = {
            "Fire": element_page_wikitext("Fire"),
            "Water": element_page_wikitext("Water"),
        }

        page_store: dict[str, MagicMock] = {}
        site = _make_mock_site(page_store)

        # --- First call: pages don't exist ---
        for title in pages:
            page_store[title] = _make_mock_page(exists=False)

        counts1 = upsert_taxonomy_pages(site, pages, dry_run=False)
        assert counts1["created"] == 2
        assert counts1["unchanged"] == 0

        # Capture written text and simulate MediaWiki state
        for title in pages:
            page_mock = page_store[title]
            page_mock.edit.assert_called_once()
            written_text = page_mock.edit.call_args[0][0]
            # Replace with "existing" page that has the written content
            page_store[title] = _make_mock_page(
                exists=True, text=written_text.rstrip()
            )

        # --- Second call: same content, should all be unchanged ---
        counts2 = upsert_taxonomy_pages(site, pages, dry_run=False)
        assert counts2["created"] == 0
        assert counts2["updated"] == 0
        assert counts2["unchanged"] == 2

        # No .edit() calls on second run
        for title in pages:
            page_store[title].edit.assert_not_called()

    def test_homepage_upsert_idempotent(self):
        """Second sync_main_page returns 'unchanged', zero .edit() calls."""
        expected_wikitext = main_page_wikitext()

        page_store: dict[str, MagicMock] = {}
        site = _make_mock_site(page_store)

        # --- First call: page doesn't exist ---
        page_store["Main Page"] = _make_mock_page(exists=False)

        status1 = sync_main_page(site, dry_run=False)
        assert status1 == "created"

        # Capture the written text
        page_mock = page_store["Main Page"]
        page_mock.edit.assert_called_once()
        written_text = page_mock.edit.call_args[0][0]

        # Simulate MediaWiki state after creation
        page_store["Main Page"] = _make_mock_page(
            exists=True, text=written_text.rstrip()
        )

        # --- Second call: same content ---
        status2 = sync_main_page(site, dry_run=False)
        assert status2 == "unchanged"

        # No .edit() on second run
        page_store["Main Page"].edit.assert_not_called()
