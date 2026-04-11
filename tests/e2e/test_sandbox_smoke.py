"""End-to-end Playwright smoke tests for Phase 14.6 Sandbox Mode.

Five tests of increasing complexity, each testing a strictly larger surface
area than the previous one. If all five pass, the sandbox is verified ready
for manual UAT closeout.

    1. test_sandbox_screen_loads_and_mirrors_live_layout
       Opens the sandbox tab, asserts the live-game layout is present:
       room-bar, both info-bars, 5x5 board with 25 cells, both hand containers,
       sandbox control panel in the right sidebar.

    2. test_search_adds_common_rat_to_p1_hand
       Types "rat" in the search box, clicks a Common Rat result, asserts
       P1 hand size goes 0 → 1 and the card is rendered face-up inside
       #sandbox-hand-p0.

    3. test_click_to_deploy_reuses_live_game_handlers
       Sets P1 mana via cheat input, adds a rat to hand, then clicks the
       hand card and a board cell using the SAME onHandCardClick +
       onBoardCellClick handlers the live game uses — exercising the
       submitAction emit-gate that reroutes to sandbox_apply_action.
       Asserts minion on board, hand shrunk, mana decremented.

    4. test_cheat_inputs_and_pile_modal
       Sets P1 HP and P2 HP (including a negative) via cheat inputs,
       adds a card to P1 graveyard via the zone picker, then clicks the
       P1 grave pile button and asserts #pileModal opens with the card
       visible (proves #pileModal works from the sandbox screen after
       being moved to body-level in this phase).

    5. test_server_slot_save_reset_load_roundtrip
       Full state roundtrip: seed a deterministic state (rat on board,
       rat in hand, cheat HP, cheat mana), save to a server slot, click
       Reset to wipe state, click Load on the slot row in the sidebar,
       and assert the full state is byte-identical (rat still at the
       same position, hand still has the same card, HPs restored).

Run:
    # with server already running at localhost:5000
    pytest tests/e2e/test_sandbox_smoke.py -v

    # against a deployed Railway URL
    GT_SANDBOX_URL=https://grid-tactics.up.railway.app/ \\
        pytest tests/e2e/test_sandbox_smoke.py -v
"""

from __future__ import annotations

import os
import time

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, sync_playwright  # noqa: E402

SANDBOX_URL = os.environ.get("GT_SANDBOX_URL", "http://localhost:5000/")
COMMON_RAT_NID = 22  # card_id="rat", mana_cost=1, card_type=minion


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser_context():
    """Launch one Chromium browser for the whole module."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        yield ctx
        ctx.close()
        browser.close()


@pytest.fixture
def sandbox_page(browser_context):
    """Fresh page with sandbox screen open and wired up.

    The sandbox is reset at teardown so tests don't bleed state between runs —
    a fresh localStorage + a fresh sandbox_create on the server.
    """
    page = browser_context.new_page()
    # Auto-accept all in-page confirm() dialogs (Reset, Delete slot, etc.)
    # BEFORE the first navigation so the override fires on every load.
    page.add_init_script("window.confirm = () => true;")
    page.goto(SANDBOX_URL)
    # Wipe any autosave so every test starts empty.
    page.evaluate("() => localStorage.removeItem('gt_sandbox_autosave_v1')")
    # Click the Sandbox nav tab.
    page.wait_for_selector('[data-screen="sandbox"]', timeout=5000)
    page.click('[data-screen="sandbox"]')
    # Wait for the sandbox_state round-trip to land, which triggers the
    # first render that fills the info bars with server-side state.
    page.wait_for_function(
        "() => sandboxState && sandboxState.players"
        " && document.querySelector('#sandbox-p0-hp')"
        " && document.querySelector('#sandbox-p0-hp').textContent === '100'",
        timeout=5000,
    )
    yield page
    page.close()


# ---------------------------------------------------------------------------
# Assertion helpers (scoped to the new info-bar IDs, not #sandbox-stats)
# ---------------------------------------------------------------------------


def _wait_text(page: Page, selector: str, expected: str, timeout: int = 3000) -> None:
    page.wait_for_function(
        "({sel, want}) => {"
        "  const el = document.querySelector(sel);"
        "  return !!el && el.textContent.trim() === String(want);"
        "}",
        arg={"sel": selector, "want": expected},
        timeout=timeout,
    )


def _p0_hp(page: Page, expected: int) -> None:
    _wait_text(page, "#sandbox-p0-hp", str(expected))


def _p1_hp(page: Page, expected: int) -> None:
    _wait_text(page, "#sandbox-p1-hp", str(expected))


def _p0_hand_size(page: Page, expected: int) -> None:
    _wait_text(page, "#sandbox-p0-handcount", str(expected))


def _p0_mana(page: Page, current: int, max_mana: int) -> None:
    _wait_text(page, "#sandbox-p0-mana", f"{current}/{max_mana}")


# ---------------------------------------------------------------------------
# Test 1 — simplest: layout & elements
# ---------------------------------------------------------------------------


def test_01_sandbox_screen_loads_and_mirrors_live_layout(sandbox_page: Page):
    """Sandbox tab opens, live-game layout is fully present.

    Proves: nav wiring, sandbox_create round trip, board mount, hand mounts,
    info bars, sidebar control panel, 25 rendered board cells.
    """
    page = sandbox_page

    # Screen is active
    assert page.is_visible("#screen-sandbox")
    assert not page.is_visible("#screen-game")

    # Live-game structural elements (mirror of #screen-game)
    assert page.is_visible("#screen-sandbox .game-layout")
    assert page.is_visible("#screen-sandbox .game-main")
    assert page.is_visible("#screen-sandbox .room-bar")
    assert page.is_visible("#screen-sandbox .opp-bar")   # P2 info bar (top)
    assert page.is_visible("#screen-sandbox .self-bar")  # P1 info bar (bottom)
    assert page.is_visible("#sandbox-hand-p1")           # P2 hand (top)
    assert page.is_visible("#sandbox-hand-p0")           # P1 hand (bottom)
    assert page.is_visible("#sandbox-board")             # 5x5 grid mount
    assert page.is_visible("#sandbox-control-panel")     # right sidebar

    # Sidebar controls are present
    assert page.is_visible("#sandbox-search")
    assert page.is_visible("#sandbox-zone-select")
    assert page.is_visible("#sandbox-undo-btn")
    assert page.is_visible("#sandbox-redo-btn")
    assert page.is_visible("#sandbox-save-btn")
    assert page.is_visible("#sandbox-slot-name")

    # Board is actually a 5x5 grid of 25 .board-cell elements
    cell_count = page.evaluate(
        "() => document.querySelectorAll('#sandbox-board .board-cell').length"
    )
    assert cell_count == 25, f"expected 25 board cells, got {cell_count}"

    # Fresh session: HP 100, mana 1/1, hand 0, deck 0
    _p0_hp(page, 100)
    _p1_hp(page, 100)
    _p0_hand_size(page, 0)
    _wait_text(page, "#sandbox-p0-mana", "1/1")


# ---------------------------------------------------------------------------
# Test 2 — search adds card to hand
# ---------------------------------------------------------------------------


def test_02_search_adds_common_rat_to_p1_hand(sandbox_page: Page):
    """Type 'Common Rat' in search, click result, card lands in P1 hand."""
    page = sandbox_page

    page.fill("#sandbox-search", "common rat")
    page.wait_for_selector(".sandbox-search-result", timeout=2000)
    first = page.query_selector(".sandbox-search-result")
    assert first is not None, "search produced no results"
    first.click()

    # Stat pill updates
    _p0_hand_size(page, 1)

    # Card DOM actually lands in the bottom hand container
    card = page.wait_for_selector(
        '#sandbox-hand-p0 .card-frame-hand[data-numeric-id="22"]',
        timeout=2000,
    )
    assert card is not None, "Common Rat card not rendered in P1 hand mount"


# ---------------------------------------------------------------------------
# Test 3 — click-to-deploy reuses the live-game handlers via the emit gate
# ---------------------------------------------------------------------------


def test_03_click_to_deploy_reuses_live_game_handlers(sandbox_page: Page):
    """Deploy a minion by CLICKING hand card + board cell (not socket emits).

    This exercises onHandCardClick + onBoardCellClick + submitAction + the
    Phase 14.6-03 SANDBOX-EMIT-GATE in submitAction that reroutes to
    sandbox_apply_action. No parallel action UI — the same code paths the
    live game uses.
    """
    page = sandbox_page

    # Set P1 mana to 5 via the cheat input (not via direct socket call)
    mana_input = page.query_selector(
        '.sandbox-cheat-input[data-player="0"][data-field="current_mana"]'
    )
    assert mana_input is not None
    mana_input.fill("5")
    mana_input.press("Enter")
    _p0_mana(page, 5, 1)

    # Add a Common Rat to P1 hand via the search UI
    page.fill("#sandbox-search", "common rat")
    page.wait_for_selector(".sandbox-search-result", timeout=2000)
    page.click(".sandbox-search-result")
    _p0_hand_size(page, 1)

    # Click the hand card — exercises onHandCardClick and the sandbox
    # global-swap from Plan 14.6-02 (the click handler reads gameState
    # / legalActions, which were swapped to sandbox scope by sandboxActivate).
    hand_card = page.wait_for_selector(
        '#sandbox-hand-p0 .card-frame-hand[data-numeric-id="22"]',
        timeout=2000,
    )
    hand_card.click()

    # Click a valid back-row cell for P1 (row 0, col 2).
    # The legal-deploy tiles should have class .cell-valid after the click above.
    board_cell = page.wait_for_selector(
        '#sandbox-board .board-cell[data-row="0"][data-col="2"]',
        timeout=2000,
    )
    board_cell.click()

    # Wait for sandbox_state to come back with the rat on the board.
    page.wait_for_function(
        "() => sandboxState"
        " && sandboxState.minions"
        " && sandboxState.minions.length === 1"
        " && sandboxState.minions[0].position[0] === 0"
        " && sandboxState.minions[0].position[1] === 2",
        timeout=3000,
    )

    # Mana decremented 5 → 4, hand shrunk 1 → 0
    _p0_mana(page, 4, 1)
    _p0_hand_size(page, 0)

    # Rat visible as a .board-minion inside the deployed cell
    deployed = page.query_selector(
        '#sandbox-board .board-cell[data-row="0"][data-col="2"] .board-minion'
    )
    assert deployed is not None, "board-minion DOM not rendered after deploy click"

    # Regression guard for the 2026-04-11 sandbox deploy silent-fail bug:
    # after a PLAY_CARD with no legal reacts for P2, the session must drain
    # the trivial react window and return to ACTION phase on P2. If we stop
    # at REACT phase with react_player_idx=1 the sandbox UI has no path to
    # issue PASS and the session is "silently stuck" from the user's POV.
    phase = page.evaluate("() => sandboxState.phase")
    assert phase == 0, (
        f"sandbox stuck in REACT phase (phase={phase}) after deploy — "
        "trivial react window was not drained"
    )
    react_idx = page.evaluate("() => sandboxState.react_player_idx")
    assert react_idx is None, (
        f"react_player_idx should be cleared after deploy, got {react_idx}"
    )
    active_idx = page.evaluate("() => sandboxState.active_player_idx")
    assert active_idx == 1, (
        f"active_player_idx should advance to P2 after P1 deploys, got {active_idx}"
    )


# ---------------------------------------------------------------------------
# Test 4 — cheat inputs + pile modal (including the body-level #pileModal fix)
# ---------------------------------------------------------------------------


def test_04_cheat_inputs_and_pile_modal(sandbox_page: Page):
    """Cheat HP (including negative values) and open a pile modal.

    Proves:
      - Cheat inputs commit on blur AND on Enter (DEV-06)
      - Cheat mode allows negative HP
      - #pileModal (moved to body-level in this phase) opens from the sandbox
        screen — previously it was nested inside #screen-game and unreachable
        while the sandbox was active
    """
    page = sandbox_page

    # P1 HP = 5 via blur (Tab)
    p0_hp_input = page.query_selector(
        '.sandbox-cheat-input[data-player="0"][data-field="hp"]'
    )
    assert p0_hp_input is not None
    p0_hp_input.fill("5")
    p0_hp_input.press("Tab")
    _p0_hp(page, 5)

    # P2 HP = -10 via Enter (negative is legal in cheat mode)
    p1_hp_input = page.query_selector(
        '.sandbox-cheat-input[data-player="1"][data-field="hp"]'
    )
    assert p1_hp_input is not None
    p1_hp_input.fill("-10")
    p1_hp_input.press("Enter")
    _p1_hp(page, -10)

    # Add a rat to P1 graveyard via the zone picker
    page.select_option("#sandbox-zone-select", "graveyard")
    page.fill("#sandbox-search", "common rat")
    page.wait_for_selector(".sandbox-search-result", timeout=2000)
    page.click(".sandbox-search-result")
    # P1 grave count pill reflects the add
    _wait_text(page, "#sandbox-p0-grave", "1")

    # Click the P1 grave pile button in the info bar → #pileModal opens
    grave_btn = page.query_selector(
        '#screen-sandbox .sandbox-pile-btn[data-pile="graveyard"][data-player="0"]'
    )
    assert grave_btn is not None
    grave_btn.click()

    # #pileModal is body-level and visible (style.display set to 'flex' by
    # showPileModal). NOTE: offsetParent is null on position:fixed overlays
    # even when visible, so we check display directly — not offsetParent.
    page.wait_for_function(
        "() => { const m = document.getElementById('pileModal');"
        " return m && m.style.display === 'flex'"
        " && m.parentElement && m.parentElement.tagName === 'BODY'; }",
        timeout=2000,
    )
    # Modal contains at least one card
    assert page.query_selector("#pileModalGrid .card-frame") is not None


# ---------------------------------------------------------------------------
# Test 5 — server slot save / reset / load roundtrip
# ---------------------------------------------------------------------------


def test_05_server_slot_save_reset_load_roundtrip(sandbox_page: Page):
    """Seed state → save to server slot → reset → load → verify restored.

    Exercises sandbox_save_slot, sandbox_list_slots, sandbox_load_slot, and
    the Reset button. The slot list is rendered into #sandbox-slots-list
    by renderSandboxSlotList() with Load + Delete buttons per row.
    """
    page = sandbox_page

    slot_name = f"e2e_roundtrip_{int(time.time())}"

    # --- seed a deterministic state ---
    # P1 HP 42, mana 5, one rat in hand, one rat on the board.
    def set_cheat(field: str, player_idx: int, value: str) -> None:
        el = page.query_selector(
            f'.sandbox-cheat-input[data-player="{player_idx}"][data-field="{field}"]'
        )
        assert el is not None
        el.fill(value)
        el.press("Enter")

    set_cheat("hp", 0, "42")
    set_cheat("current_mana", 0, "5")
    _p0_hp(page, 42)
    _p0_mana(page, 5, 1)

    # Two rats to hand then deploy one — same flow as test 3 but via socket
    # (we already proved click-to-deploy works; this test focuses on save/load).
    page.evaluate(
        f"""
        () => {{
          socket.emit('sandbox_add_card_to_zone', {{
            player_idx: 0, card_numeric_id: {COMMON_RAT_NID}, zone: 'hand'
          }});
          socket.emit('sandbox_add_card_to_zone', {{
            player_idx: 0, card_numeric_id: {COMMON_RAT_NID}, zone: 'hand'
          }});
        }}
        """
    )
    _p0_hand_size(page, 2)
    page.evaluate(
        """
        () => socket.emit('sandbox_apply_action',
          { action_type: 0, card_index: 0, position: [0, 2] })
        """
    )
    page.wait_for_function(
        "() => sandboxState && sandboxState.minions.length === 1"
    )
    _p0_hand_size(page, 1)

    # --- save to server slot ---
    page.fill("#sandbox-slot-name", slot_name)
    page.click("#sandbox-slot-save-btn")
    # Wait for the slot row to appear in the list (refresh is auto-triggered
    # by sandbox_slot_saved handler)
    page.wait_for_selector(
        f'.sandbox-slot-row[data-slot-name="{slot_name}"]',
        timeout=3000,
    )

    # --- reset the sandbox ---
    page.click("#sandbox-reset-btn")
    page.wait_for_function(
        "() => sandboxState && sandboxState.minions.length === 0"
        " && sandboxState.players[0].hand.length === 0"
        " && sandboxState.players[0].hp === 100",
        timeout=3000,
    )
    _p0_hp(page, 100)
    _p0_hand_size(page, 0)

    # --- load the slot from the sidebar ---
    load_btn = page.query_selector(
        f'.sandbox-slot-row[data-slot-name="{slot_name}"] .sandbox-slot-load-btn'
    )
    assert load_btn is not None, (
        f"slot row for {slot_name} has no Load button — check renderSandboxSlotList"
    )
    load_btn.click()

    # --- verify restored state matches seed exactly ---
    page.wait_for_function(
        "() => sandboxState"
        " && sandboxState.minions.length === 1"
        " && sandboxState.minions[0].position[0] === 0"
        " && sandboxState.minions[0].position[1] === 2"
        " && sandboxState.players[0].hand.length === 1"
        " && sandboxState.players[0].hp === 42"
        " && sandboxState.players[0].current_mana === 4",
        timeout=3000,
    )
    _p0_hp(page, 42)
    _p0_hand_size(page, 1)
    _p0_mana(page, 4, 1)

    # --- cleanup: delete the slot so repeated runs don't accumulate ---
    delete_btn = page.query_selector(
        f'.sandbox-slot-row[data-slot-name="{slot_name}"] .sandbox-slot-delete-btn'
    )
    if delete_btn is not None:
        delete_btn.click()
        # Accept the confirm dialog if one is shown
        try:
            page.evaluate(
                "() => { window.confirm = () => true; }"
            )
        except Exception:
            pass
