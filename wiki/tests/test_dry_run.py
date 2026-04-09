"""
Dry-run mock tests proving ``--dry-run`` never calls ``.edit()`` or ``.upload()``.

All wiki API calls are mocked via ``unittest.mock.MagicMock``.  Each test
asserts that the relevant write method was NOT called when ``dry_run=True``.

Run from ``wiki/`` directory::

    cd wiki
    python -m pytest tests/test_dry_run.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sync.sync_cards import build_card_name_map, card_to_wikitext
from sync.sync_homepage import sync_main_page, main_page_wikitext
from sync.sync_showcase import sync_showcase_page, showcase_page_wikitext
from sync.sync_taxonomy import upsert_taxonomy_pages, element_page_wikitext
from sync.sync_wiki import upsert_card_page, upload_card_art

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CARDS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cards"
ART_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "src" / "grid_tactics" / "server" / "static" / "art"
)


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


class TestDryRunNoWrites:

    def test_card_create_dry_run_no_edit(self, ratchanter_card, name_map):
        """Dry-run on non-existent card page: status 'would-create', no .edit()."""
        card = ratchanter_card
        card_name = card["name"]
        page_title = f"Card:{card_name}"

        page_store: dict[str, MagicMock] = {}
        page_store[page_title] = _make_mock_page(exists=False)
        site = _make_mock_site(page_store)

        result = upsert_card_page(site, card, name_map, ART_DIR, dry_run=True)

        assert result["status"] == "would-create"
        page_store[page_title].edit.assert_not_called()

    def test_card_update_dry_run_no_edit(self, ratchanter_card, name_map):
        """Dry-run on existing card with different content: 'would-update', no .edit()."""
        card = ratchanter_card
        card_name = card["name"]
        page_title = f"Card:{card_name}"

        page_store: dict[str, MagicMock] = {}
        # Page exists but with stale/different content
        page_store[page_title] = _make_mock_page(
            exists=True, text="{{Card\n| name = Old Content\n}}"
        )
        site = _make_mock_site(page_store)

        result = upsert_card_page(site, card, name_map, ART_DIR, dry_run=True)

        assert result["status"] == "would-update"
        page_store[page_title].edit.assert_not_called()

    def test_card_unchanged_dry_run(self, ratchanter_card, name_map):
        """Dry-run on existing card with matching content: 'unchanged', no .edit()."""
        from sync.sync_cards import get_version

        card = ratchanter_card
        card_id = card["card_id"]
        card_name = card["name"]
        page_title = f"Card:{card_name}"
        art_exists = (ART_DIR / f"{card_id}.png").exists()
        # upsert_card_page seeds an "added" history entry when none exists,
        # so we must include a history section for the content to match.
        version = get_version()
        history = [{
            "version": version,
            "date": "2026-01-01",  # any date
            "change_type": "added",
            "changed_fields": [],
        }]
        expected_wikitext = card_to_wikitext(
            card, name_map, art_exists=art_exists, history_entries=history,
        )

        page_store: dict[str, MagicMock] = {}
        # Page exists with matching content (stripped, as MediaWiki does)
        page_store[page_title] = _make_mock_page(
            exists=True, text=expected_wikitext.rstrip()
        )
        site = _make_mock_site(page_store)

        result = upsert_card_page(site, card, name_map, ART_DIR, dry_run=True)

        assert result["status"] == "unchanged"
        page_store[page_title].edit.assert_not_called()

    def test_art_upload_dry_run_no_upload(self, ratchanter_card, tmp_path):
        """Dry-run art upload: status 'dry-run', no .upload() call."""
        card = ratchanter_card
        card_id = card["card_id"]
        card_name = card["name"]

        # Create a dummy PNG in tmp_path
        art_file = tmp_path / f"{card_id}.png"
        art_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        site = MagicMock()

        status = upload_card_art(site, card_id, card_name, tmp_path, dry_run=True)

        assert status == "dry-run"
        site.upload.assert_not_called()

    def test_taxonomy_dry_run_no_edit(self):
        """Dry-run taxonomy upsert: no .edit() calls."""
        pages = {
            "Fire": element_page_wikitext("Fire"),
            "Water": element_page_wikitext("Water"),
        }

        page_store: dict[str, MagicMock] = {}
        # Pages don't exist yet
        for title in pages:
            page_store[title] = _make_mock_page(exists=False)
        site = _make_mock_site(page_store)

        counts = upsert_taxonomy_pages(site, pages, dry_run=True)

        assert counts["created"] == 2
        assert counts["updated"] == 0
        assert counts["unchanged"] == 0

        # No .edit() calls on any page
        for title in pages:
            page_store[title].edit.assert_not_called()

    def test_homepage_dry_run_no_edit(self):
        """Dry-run homepage sync with different content: 'would-update', no .edit()."""
        page_store: dict[str, MagicMock] = {}
        # Page exists but with different content
        page_store["Main Page"] = _make_mock_page(
            exists=True, text="= Old Main Page ="
        )
        site = _make_mock_site(page_store)

        status = sync_main_page(site, dry_run=True)

        assert status == "would-update"
        page_store["Main Page"].edit.assert_not_called()

    def test_showcase_dry_run_no_edit(self):
        """Dry-run showcase sync with different content: 'would-update', no .edit()."""
        page_title = "Semantic:Showcase"
        page_store: dict[str, MagicMock] = {}
        # Page exists but with different content
        page_store[page_title] = _make_mock_page(
            exists=True, text="== Old Showcase =="
        )
        site = _make_mock_site(page_store)

        status = sync_showcase_page(site, dry_run=True)

        assert status == "would-update"
        page_store[page_title].edit.assert_not_called()
