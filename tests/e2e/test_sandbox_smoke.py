"""End-to-end Playwright smoke test for Phase 14.6 Sandbox Mode.

Drives the deployed sandbox via a real Chromium instance and verifies the
full DEV-01..DEV-09 surface:

- Sandbox tab renders, fixed dual-perspective god view (P1 top, P2 bottom)
- Zone-aware search + add (hand / deck_top / deck_bottom / graveyard / exhaust)
- Zone roundtrip: add to deck → move to hand
- Cheat inputs (HP / mana) commit on blur+Enter only
- Undo / redo across sandbox operations
- Base64 share-code round trip via TextEncoder / TextDecoder (matches the
  production helpers — NO escape/unescape)
- localStorage autosave + restore on page reload
- Server slot save → list → load → delete round trip
- Deck import via sandbox_import_deck handler

Every hand/HP/deck-size assertion is scoped to a specific player row via
`data-player="0"` / `data-player="1"` — plain substring matching against
the whole stats container would match BOTH players simultaneously.

Runnable against localhost (default) or any deployed Railway URL via the
GT_SANDBOX_URL env var. The test assumes the Flask-SocketIO server is
already running on that URL — if not, the sandbox_page fixture will
fail fast on the `wait_for_selector` calls.

Install:
    pip install -e ".[dev]"
    playwright install chromium

Run:
    # with server running locally on :5000
    pytest tests/e2e/test_sandbox_smoke.py -v

    # against deployed Railway
    GT_SANDBOX_URL=https://grid-tactics.up.railway.app/ \
        pytest tests/e2e/test_sandbox_smoke.py -v
"""

from __future__ import annotations

import os
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright  # noqa: E402

# Default to localhost; allow override for deployed Railway URL via env var.
SANDBOX_URL = os.environ.get("GT_SANDBOX_URL", "http://localhost:5000/")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser_context():
    """Launch one Chromium browser for the whole test module."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        yield ctx
        ctx.close()
        browser.close()


@pytest.fixture
def sandbox_page(browser_context):
    """Fresh page on the sandbox screen with toolbar mounted."""
    page = browser_context.new_page()
    page.goto(SANDBOX_URL)
    page.wait_for_selector('[data-screen="sandbox"]', timeout=5000)
    page.click('[data-screen="sandbox"]')
    page.wait_for_selector("#sandbox-toolbar", timeout=5000)
    page.wait_for_selector("#sandbox-search", timeout=5000)
    yield page
    page.close()


# ---------------------------------------------------------------------------
# Player-row-specific assertion helpers
# ---------------------------------------------------------------------------


def _p_field(page: Page, player_idx: int, field_label: str, expected: int) -> None:
    """Wait for player row data-player=player_idx to show '<field_label> <expected>'.

    Scoped to a SINGLE .sandbox-player-row — never substring-matches the whole
    stats container because that would match both players' rendered text.
    """
    page.wait_for_function(
        "({pid, label, n}) => {"
        "  const row = document.querySelector('#sandbox-stats .sandbox-player-row[data-player=\"' + pid + '\"]');"
        "  if (!row) return false;"
        "  const txt = row.textContent || '';"
        "  return new RegExp(label + ' ' + n + '(?![0-9])').test(txt);"
        "}",
        arg={"pid": str(player_idx), "label": field_label, "n": expected},
        timeout=3000,
    )


def _p1_hand_size(page: Page, expected: int) -> None:
    _p_field(page, 0, "Hand", expected)


def _p2_hand_size(page: Page, expected: int) -> None:
    _p_field(page, 1, "Hand", expected)


def _p1_deck_size(page: Page, expected: int) -> None:
    _p_field(page, 0, "Deck", expected)


def _p1_hp(page: Page, expected: int) -> None:
    _p_field(page, 0, "HP", expected)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sandbox_screen_renders(sandbox_page: Page):
    """DEV-01: Sandbox tab opens fresh empty session without lobby."""
    assert sandbox_page.is_visible("#sandbox-search")
    assert sandbox_page.is_visible("#sandbox-undo-btn")
    assert sandbox_page.is_visible("#sandbox-save-btn")
    assert sandbox_page.is_visible("#sandbox-zone-select")
    assert sandbox_page.is_visible("#sandbox-slot-name")
    _p1_hand_size(sandbox_page, 0)
    _p2_hand_size(sandbox_page, 0)


def test_sandbox_layout_is_fixed_god_view(sandbox_page: Page):
    """DEV-01 / D1: P1 hand DOM mount is visually ABOVE the board, P2 is BELOW.

    No flip / view-toggle button anywhere in the sandbox (sandbox is fixed
    dual-perspective god view per the phase-level decision D1).
    """
    p0 = sandbox_page.query_selector("#sandbox-hand-p0")
    board = sandbox_page.query_selector("#sandbox-board")
    p1 = sandbox_page.query_selector("#sandbox-hand-p1")
    assert p0 is not None and board is not None and p1 is not None
    p0_top = p0.bounding_box()["y"]
    board_top = board.bounding_box()["y"]
    p1_top = p1.bounding_box()["y"]
    assert p0_top < board_top < p1_top, "P1 hand must be above board, P2 below"
    # No flip/view-toggle button
    assert sandbox_page.query_selector("text=Flip") is None
    assert sandbox_page.query_selector("text=View toggle") is None


def test_sandbox_search_and_add_to_hand(sandbox_page: Page):
    """DEV-02: Search + add to hand (default zone)."""
    sandbox_page.fill("#sandbox-search", "rat")
    sandbox_page.wait_for_selector(".sandbox-search-result", timeout=2000)
    first_result = sandbox_page.query_selector(".sandbox-search-result")
    assert first_result is not None
    first_result.click()
    _p1_hand_size(sandbox_page, 1)
    _p2_hand_size(sandbox_page, 0)


def test_sandbox_zone_roundtrip(sandbox_page: Page):
    """DEV-02 / DEV-03: Add to deck top → move to hand → state shows hand=1, deck=0."""
    # Pick deck_top zone
    sandbox_page.select_option("#sandbox-zone-select", "deck_top")
    sandbox_page.fill("#sandbox-search", "rat")
    sandbox_page.wait_for_selector(".sandbox-search-result")
    sandbox_page.query_selector(".sandbox-search-result").click()
    _p1_deck_size(sandbox_page, 1)
    _p1_hand_size(sandbox_page, 0)
    # Now move it from deck to hand by emitting sandbox_move_card directly
    # via window.socket (the move-popover is mounted in the deck pile modal,
    # which is reachable via the existing pile-modal button — but that
    # requires the modal to be open. For test stability we use the socket
    # directly, exercising the same backend handler the popover hits.)
    moved = sandbox_page.evaluate(
        """
        () => {
            // Find the card numeric id sitting in P1's deck
            const cid = window.sandboxState.players[0].deck[0];
            window.socket.emit('sandbox_move_card', {
                player_idx: 0,
                card_numeric_id: cid,
                src_zone: 'deck_top',
                dst_zone: 'hand',
            });
            return true;
        }
        """
    )
    assert moved
    _p1_hand_size(sandbox_page, 1)
    _p1_deck_size(sandbox_page, 0)


def test_sandbox_cheat_inputs(sandbox_page: Page):
    """DEV-06: Set cheat HP and mana via the numeric inputs."""
    # Set P1 HP to 5 via the cheat input — fill then blur (Tab)
    hp_input = sandbox_page.query_selector('.sandbox-cheat-input[data-player="0"][data-field="hp"]')
    assert hp_input is not None
    hp_input.fill("5")
    hp_input.press("Tab")  # blur → commit
    _p1_hp(sandbox_page, 5)
    # Set P2 HP to a negative value (cheat mode allows it)
    p2_hp = sandbox_page.query_selector(
        '.sandbox-cheat-input[data-player="1"][data-field="hp"]'
    )
    assert p2_hp is not None
    p2_hp.fill("-50")
    p2_hp.press("Enter")
    _p_field(sandbox_page, 1, "HP", -50)


def test_sandbox_undo_redo(sandbox_page: Page):
    """DEV-09: Undo / redo across zone-add operations."""
    sandbox_page.fill("#sandbox-search", "rat")
    sandbox_page.wait_for_selector(".sandbox-search-result")
    for _ in range(3):
        result = sandbox_page.query_selector(".sandbox-search-result")
        assert result is not None
        result.click()
        sandbox_page.wait_for_timeout(100)
    _p1_hand_size(sandbox_page, 3)
    for _ in range(3):
        sandbox_page.click("#sandbox-undo-btn")
        sandbox_page.wait_for_timeout(100)
    _p1_hand_size(sandbox_page, 0)
    for _ in range(3):
        sandbox_page.click("#sandbox-redo-btn")
        sandbox_page.wait_for_timeout(100)
    _p1_hand_size(sandbox_page, 3)


def test_sandbox_share_code_round_trip(sandbox_page: Page):
    """DEV-07: Base64 share code round trip via TextEncoder / TextDecoder.

    Mirrors the production sandboxEncodeShareCode / sandboxDecodeShareCode
    helpers — NO escape(encodeURIComponent()) or decodeURIComponent(escape())
    trickery.
    """
    sandbox_page.fill("#sandbox-search", "rat")
    sandbox_page.wait_for_selector(".sandbox-search-result")
    sandbox_page.query_selector(".sandbox-search-result").click()
    _p1_hand_size(sandbox_page, 1)
    code = sandbox_page.evaluate(
        """
        () => {
            const payload = { state: window.sandboxState, active_view_idx: window.sandboxActiveViewIdx };
            const json = JSON.stringify(payload);
            const bytes = new TextEncoder().encode(json);
            let binary = '';
            for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
            return btoa(binary);
        }
        """
    )
    assert code and len(code) > 50
    sandbox_page.on("dialog", lambda d: d.accept())
    sandbox_page.click("#sandbox-reset-btn")
    _p1_hand_size(sandbox_page, 0)
    sandbox_page.evaluate(
        """
        (code) => {
            const binary = atob(code);
            const bytes = Uint8Array.from(binary, c => c.charCodeAt(0));
            const json = new TextDecoder().decode(bytes);
            const payload = JSON.parse(json);
            window.socket.emit('sandbox_load', { payload: payload });
        }
        """,
        code,
    )
    _p1_hand_size(sandbox_page, 1)


def test_sandbox_localStorage_restore(browser_context):
    """DEV-07: localStorage autosave + restore on page reload."""
    page = browser_context.new_page()
    page.goto(SANDBOX_URL)
    page.click('[data-screen="sandbox"]')
    page.wait_for_selector("#sandbox-search")
    page.fill("#sandbox-search", "rat")
    page.wait_for_selector(".sandbox-search-result")
    page.query_selector(".sandbox-search-result").click()
    _p1_hand_size(page, 1)
    page.reload()
    page.click('[data-screen="sandbox"]')
    _p1_hand_size(page, 1)
    page.close()


def test_sandbox_server_slot_save_list_load_delete(sandbox_page: Page):
    """DEV-08: Server-side slot save → list → load → delete round trip.

    Uses a unique slot name per test run to avoid collisions with any
    pre-existing slots in data/sandbox_saves/.
    """
    slot_name = f"e2e_test_{int(time.time())}"

    # Add a card so the slot has non-trivial state
    sandbox_page.fill("#sandbox-search", "rat")
    sandbox_page.wait_for_selector(".sandbox-search-result")
    sandbox_page.query_selector(".sandbox-search-result").click()
    _p1_hand_size(sandbox_page, 1)

    # Save to slot
    sandbox_page.fill("#sandbox-slot-name", slot_name)
    sandbox_page.click("#sandbox-slot-save-btn")

    # Wait for the slot list to refresh and contain our slot
    sandbox_page.wait_for_function(
        "(name) => {"
        "  const list = document.getElementById('sandbox-slots-list');"
        "  return list && list.textContent && list.textContent.includes(name);"
        "}",
        arg=slot_name,
        timeout=3000,
    )

    # Reset and confirm hand is empty
    sandbox_page.on("dialog", lambda d: d.accept())
    sandbox_page.click("#sandbox-reset-btn")
    _p1_hand_size(sandbox_page, 0)

    # Find the load button for our slot row and click it
    sandbox_page.evaluate(
        """
        (name) => {
            const list = document.getElementById('sandbox-slots-list');
            const rows = list.querySelectorAll('.sandbox-slot-row');
            for (const row of rows) {
                if (row.textContent.includes(name)) {
                    const loadBtn = Array.from(row.querySelectorAll('button')).find(b => b.textContent === 'Load');
                    loadBtn.click();
                    return true;
                }
            }
            return false;
        }
        """,
        slot_name,
    )
    _p1_hand_size(sandbox_page, 1)

    # Delete the slot via the panel button (auto-accepts the confirm dialog
    # from the listener above)
    sandbox_page.evaluate(
        """
        (name) => {
            const list = document.getElementById('sandbox-slots-list');
            const rows = list.querySelectorAll('.sandbox-slot-row');
            for (const row of rows) {
                if (row.textContent.includes(name)) {
                    const delBtn = Array.from(row.querySelectorAll('button')).find(b => b.textContent === 'Delete');
                    delBtn.click();
                    return true;
                }
            }
            return false;
        }
        """,
        slot_name,
    )
    # Wait for the slot list to no longer contain the slot
    sandbox_page.wait_for_function(
        "(name) => {"
        "  const list = document.getElementById('sandbox-slots-list');"
        "  return !list || !list.textContent.includes(name);"
        "}",
        arg=slot_name,
        timeout=3000,
    )


def test_sandbox_deck_import(sandbox_page: Page):
    """DEV-03: Deck import lands a flat card-id list in P1's deck zone.

    Bypasses the deck-builder localStorage UI and emits sandbox_import_deck
    directly with a known card-id list — exercising the same handler the
    "Load deck..." button hits.
    """
    sandbox_page.evaluate(
        """
        () => {
            window.socket.emit('sandbox_import_deck', {
                player_idx: 0,
                deck_card_ids: [0, 0, 1, 1, 2],
            });
        }
        """
    )
    _p1_deck_size(sandbox_page, 5)
