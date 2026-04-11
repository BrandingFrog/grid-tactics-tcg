"""End-to-end Playwright tests for the Death: keyword fix (2026-04-11).

These exercise the full sandbox UI -> server -> Python engine path for the
two live cards that use ``trigger: on_death``:

  1. Giant Rat (PROMOTE / self_owner / on_death) — silently no-oped in the
     Python engine before the fix because no PROMOTE handler existed in
     ``effect_resolver._apply_effect_to_minion``. Now ported from the
     tensor engine via ``_apply_promote_on_death`` and dispatched in
     ``resolve_effects_for_trigger``.

  2. RGB Lasercannon (DESTROY / single_target / on_death) — also silently
     no-oped before the fix because ``resolve_effects_for_trigger``
     passed ``target_pos=None`` to the dispatch and ``_resolve_single_target``
     bailed early. Now opens a click-target modal via the new
     ``pending_death_target`` machinery.

The Python engine fix is already covered by 11 unit tests in
``test_action_resolver.py``; this file proves the fix is wired all the way
through the Socket.IO sandbox path and into the browser DOM.

Run:
    PYTHONPATH=src pytest tests/e2e/test_sandbox_death_mechanics.py -v

Requires the sandbox server running at ``$GT_SANDBOX_URL`` (default
``http://localhost:5000/``).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Page, Route, sync_playwright  # noqa: E402

SANDBOX_URL = os.environ.get("GT_SANDBOX_URL", "http://localhost:5000/")

# Sandbox UI loads socket.io from a CDN. In hermetic test environments
# (CI, sandboxed dev boxes) the CDN is unreachable, so we intercept the
# request and serve a local copy from tests/e2e/_assets/.
_SOCKET_IO_LOCAL = Path(__file__).parent / "_assets" / "socket.io.min.js"

# Card numeric IDs (looked up via CardLibrary at test-write time; stable across
# library reloads because they come from each card's JSON ``stable_id``).
COMMON_RAT_NID = 22
GIANT_RAT_NID = 13
FIREBALL_NID = 10
RGB_LASERCANNON_NID = 28
BLUE_DIODEBOT_NID = 0
RED_DIODEBOT_NID = 27

# Action type ints (mirror grid_tactics.enums.ActionType)
ACTION_PLAY_CARD = 0
ACTION_PASS = 4
ACTION_DEATH_TARGET_PICK = 14


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def browser_context():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1600, "height": 900})
        yield ctx
        ctx.close()
        browser.close()


def _serve_local_socket_io(route: Route) -> None:
    """Serve the bundled socket.io.min.js when the CDN is unreachable."""
    body = _SOCKET_IO_LOCAL.read_bytes()
    route.fulfill(
        status=200,
        content_type="application/javascript",
        body=body,
    )


@pytest.fixture
def sandbox_page(browser_context):
    page = browser_context.new_page()
    # Intercept the socket.io CDN load and serve the local copy.
    page.route("**/socket.io/**/socket.io*.js", _serve_local_socket_io)
    page.route("**/cdn.socket.io/**/socket.io*.js", _serve_local_socket_io)
    page.add_init_script("window.confirm = () => true;")
    page.goto(SANDBOX_URL)
    page.evaluate("() => localStorage.removeItem('gt_sandbox_autosave_v1')")
    page.wait_for_selector('[data-screen="sandbox"]', timeout=5000)
    page.click('[data-screen="sandbox"]')
    page.wait_for_function(
        "() => sandboxState && sandboxState.players"
        " && document.querySelector('#sandbox-p0-hp')"
        " && document.querySelector('#sandbox-p0-hp').textContent === '100'",
        timeout=5000,
    )
    # Force a clean session each test by hitting the Reset button.
    page.click("#sandbox-reset-btn")
    page.wait_for_function(
        "() => sandboxState && sandboxState.minions.length === 0"
        " && sandboxState.players[0].hand.length === 0"
        " && sandboxState.players[1].hand.length === 0",
        timeout=3000,
    )
    yield page
    page.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_card(page: Page, player_idx: int, card_nid: int, zone: str = "hand") -> None:
    page.evaluate(
        "({pi, cid, z}) => socket.emit('sandbox_add_card_to_zone',"
        " { player_idx: pi, card_numeric_id: cid, zone: z })",
        {"pi": player_idx, "cid": card_nid, "z": zone},
    )


def _set_field(page: Page, player_idx: int, field: str, value: int) -> None:
    page.evaluate(
        "({pi, f, v}) => socket.emit('sandbox_set_player_field',"
        " { player_idx: pi, field: f, value: v })",
        {"pi": player_idx, "f": field, "v": value},
    )


def _set_active(page: Page, player_idx: int) -> None:
    page.evaluate(
        "(pi) => socket.emit('sandbox_set_active_player', { player_idx: pi })",
        player_idx,
    )


def _apply_action(page: Page, action: dict) -> None:
    page.evaluate(
        "(a) => socket.emit('sandbox_apply_action', a)",
        action,
    )


def _wait_minions(page: Page, expected: int, timeout: int = 3000) -> None:
    page.wait_for_function(
        "(n) => sandboxState && sandboxState.minions"
        " && sandboxState.minions.length === n",
        arg=expected,
        timeout=timeout,
    )


def _wait_minion_at(
    page: Page, row: int, col: int, expected_card_nid: int, timeout: int = 3000
) -> None:
    page.wait_for_function(
        "({r, c, cid}) => sandboxState && sandboxState.minions"
        " && sandboxState.minions.some(m =>"
        "    m.position && m.position[0] === r && m.position[1] === c"
        "    && m.card_numeric_id === cid)",
        arg={"r": row, "c": col, "cid": expected_card_nid},
        timeout=timeout,
    )


def _has_minion_with_card(page: Page, card_nid: int) -> bool:
    return page.evaluate(
        "(cid) => sandboxState.minions.some(m => m.card_numeric_id === cid)",
        card_nid,
    )


# ---------------------------------------------------------------------------
# Test 1 — Giant Rat death promotes a friendly Common Rat (PROMOTE fix)
# ---------------------------------------------------------------------------


def test_giant_rat_death_promotes_friendly_rat(sandbox_page: Page):
    """End-to-end test of the PROMOTE / on_death fix.

    Setup:
      - P1 plays a Common Rat to (0, 1)  [back row, col 1]
      - P1 plays a Giant Rat  to (0, 2)  [back row, col 2]
      - P2 plays Fireball targeting (0, 2) — 40 damage, kills the 30-HP Giant Rat

    Expected after the fix:
      - The Giant Rat dies and its on_death PROMOTE fires
      - The Common Rat at (0, 1) is transformed in-place into a Giant Rat
        (same instance_id, same tile, but card_numeric_id changed to 13)
      - Total board has exactly 1 minion (the promoted rat at (0, 1))
      - P1 graveyard contains the dead Giant Rat (card_numeric_id 13)

    Pre-fix behavior would be: Giant Rat dies silently, no promotion,
    Common Rat stays as a Common Rat.
    """
    page = sandbox_page

    # P1 deploys a Common Rat to (0, 1)
    _add_card(page, 0, COMMON_RAT_NID, "hand")
    _set_field(page, 0, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD,
        "card_index": 0,
        "position": [0, 1],
    })
    _wait_minion_at(page, 0, 1, COMMON_RAT_NID)

    # The action drains the trivial react window and ends P1's turn,
    # so active is now P2. Reset to P1 so we can deploy again.
    _set_active(page, 0)

    # P1 deploys a Giant Rat to (0, 2)
    _add_card(page, 0, GIANT_RAT_NID, "hand")
    _set_field(page, 0, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD,
        "card_index": 0,
        "position": [0, 2],
    })
    _wait_minion_at(page, 0, 2, GIANT_RAT_NID)
    _wait_minions(page, 2)

    # Now P2 fireballs the Giant Rat at (0, 2). Fireball is single_target /
    # 40 damage. Switch to P2 first.
    _set_active(page, 1)
    _add_card(page, 1, FIREBALL_NID, "hand")
    _set_field(page, 1, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD,
        "card_index": 0,
        "target_pos": [0, 2],
    })

    # After Fireball lands, react drains, and the death-cleanup driver
    # runs the on_death PROMOTE. The Common Rat at (0, 1) should now be
    # a Giant Rat. The dead Giant Rat at (0, 2) should be gone.
    _wait_minion_at(page, 0, 1, GIANT_RAT_NID)

    # Final assertions: exactly 1 minion left, and it's a Giant Rat at (0, 1)
    _wait_minions(page, 1)
    promoted = page.evaluate("() => sandboxState.minions[0]")
    assert promoted["card_numeric_id"] == GIANT_RAT_NID, (
        f"Expected promoted Common Rat to become Giant Rat, "
        f"got card_numeric_id={promoted['card_numeric_id']}"
    )
    assert promoted["position"] == [0, 1], (
        f"Promoted minion should still be at (0, 1), got {promoted['position']}"
    )

    # The dead Giant Rat should be in P1's graveyard.
    grave = page.evaluate("() => sandboxState.players[0].grave")
    assert GIANT_RAT_NID in grave, (
        f"Dead Giant Rat should be in P1 graveyard, got {grave}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Giant Rat unique constraint: skips promotion when another Giant
# Rat is alive on the same side (regression guard for the unique check)
# ---------------------------------------------------------------------------


def test_giant_rat_unique_constraint_blocks_promotion(sandbox_page: Page):
    """If P1 already has another Giant Rat alive, the on_death promote
    must skip (the dying card is ``unique``). The Common Rat must remain
    a Common Rat after the dying Giant Rat resolves its on_death.

    This guards against a regression where the unique constraint is
    dropped and would lead to a perpetual rat-promotion chain.
    """
    page = sandbox_page

    # P1: Common Rat at (0, 0), Giant Rat at (0, 1), Giant Rat at (0, 2)
    _add_card(page, 0, COMMON_RAT_NID, "hand")
    _set_field(page, 0, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD, "card_index": 0, "position": [0, 0],
    })
    _wait_minion_at(page, 0, 0, COMMON_RAT_NID)

    _set_active(page, 0)
    _add_card(page, 0, GIANT_RAT_NID, "hand")
    _set_field(page, 0, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD, "card_index": 0, "position": [0, 1],
    })
    _wait_minion_at(page, 0, 1, GIANT_RAT_NID)

    _set_active(page, 0)
    _add_card(page, 0, GIANT_RAT_NID, "hand")
    _set_field(page, 0, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD, "card_index": 0, "position": [0, 2],
    })
    _wait_minion_at(page, 0, 2, GIANT_RAT_NID)
    _wait_minions(page, 3)

    # P2 fireballs the Giant Rat at (0, 1) — leaves the second Giant Rat
    # alive at (0, 2). Unique constraint should fire and skip promote.
    _set_active(page, 1)
    _add_card(page, 1, FIREBALL_NID, "hand")
    _set_field(page, 1, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD, "card_index": 0, "target_pos": [0, 1],
    })

    # Wait for the death cleanup to settle. The dead Giant Rat (0, 1) is
    # gone, the live Giant Rat (0, 2) remains, and the Common Rat (0, 0)
    # must NOT be promoted (unique constraint).
    page.wait_for_function(
        "() => sandboxState && sandboxState.minions"
        " && sandboxState.minions.length === 2",
        timeout=3000,
    )

    # The Common Rat at (0, 0) is still a Common Rat — not promoted.
    cm = page.evaluate(
        "() => sandboxState.minions.find(m =>"
        "    m.position && m.position[0] === 0 && m.position[1] === 0)"
    )
    assert cm is not None, "Common Rat at (0, 0) is missing"
    assert cm["card_numeric_id"] == COMMON_RAT_NID, (
        f"Common Rat at (0, 0) was promoted despite unique constraint! "
        f"card_numeric_id={cm['card_numeric_id']}"
    )

    # The other Giant Rat at (0, 2) is still alive.
    gr = page.evaluate(
        "() => sandboxState.minions.find(m =>"
        "    m.position && m.position[0] === 0 && m.position[1] === 2)"
    )
    assert gr is not None and gr["card_numeric_id"] == GIANT_RAT_NID, (
        f"Surviving Giant Rat at (0, 2) is missing or wrong: {gr}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Lasercannon death opens a click-target modal (DESTROY fix)
# ---------------------------------------------------------------------------


def test_lasercannon_death_opens_target_modal(sandbox_page: Page):
    """End-to-end test of the DESTROY / single_target / on_death fix.

    Setup:
      - P1 has a Common Rat on the board (destroy target for the modal)
      - P2's hand: 2 Blue Diodebots + 1 RGB Lasercannon. P2 plays the
        Lasercannon, sacrificing both diodebots from hand (per the
        legal_actions auto-pick fallback for sacrifice #2).
      - P1 fireballs the Lasercannon (40 dmg > 16 HP) → it dies
      - Lasercannon's on_death DESTROY/single_target opens a modal for
        its owner (P2) to pick an enemy minion to destroy

    Expected after the fix:
      - sandboxState.pending_death_target is populated with owner_idx=1
      - legal_actions yields DEATH_TARGET_PICK entries
      - Submitting DEATH_TARGET_PICK with the Common Rat's tile destroys it
      - pending_death_target clears, board ends with 0 minions
    """
    page = sandbox_page

    # --- 1. P1 deploys a Common Rat to (0, 0) as the destroy target ---
    _add_card(page, 0, COMMON_RAT_NID, "hand")
    _set_field(page, 0, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD, "card_index": 0, "position": [0, 0],
    })
    _wait_minion_at(page, 0, 0, COMMON_RAT_NID)

    # --- 2. P2 plays the Lasercannon, sacrificing 2 diodebots from hand ---
    # Hand layout matters: index 0 = first sacrifice candidate the
    # legal_actions enumerator picks. We add 2 diodebots THEN the
    # lasercannon so the lasercannon's hand index is 2 and the
    # diodebots are at indices 0 and 1.
    _set_active(page, 1)
    _add_card(page, 1, BLUE_DIODEBOT_NID, "hand")
    _add_card(page, 1, BLUE_DIODEBOT_NID, "hand")
    _add_card(page, 1, RGB_LASERCANNON_NID, "hand")
    _set_field(page, 1, "current_mana", 9)

    # Wait for the legal actions to include a PLAY_CARD for the lasercannon
    # at hand index 2 with a sacrifice_card_index pointing at one of the
    # diodebot slots. The action_resolver auto-picks the second sacrifice
    # from the remaining hand.
    page.wait_for_function(
        "() => sandboxState && sandboxState.players[1].hand.length === 3",
        timeout=2000,
    )

    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD,
        "card_index": 2,            # lasercannon
        "position": [4, 2],         # P2 back row
        "sacrifice_card_index": 0,  # first diodebot; the resolver auto-picks #2
    })

    # Lasercannon now on the board at (4, 2); both diodebots exhausted.
    _wait_minion_at(page, 4, 2, RGB_LASERCANNON_NID)

    # --- 3. P1 fireballs the lasercannon ---
    _set_active(page, 0)
    _add_card(page, 0, FIREBALL_NID, "hand")
    _set_field(page, 0, "current_mana", 9)
    _apply_action(page, {
        "action_type": ACTION_PLAY_CARD,
        "card_index": 0,
        "target_pos": [4, 2],
    })

    # The fireball lands, lasercannon dies (16 HP < 40 dmg). The death
    # cleanup driver runs the on_death DESTROY/single_target — which
    # _death_effect_needs_modal=True — and opens the pending_death_target
    # modal for P2 (the dying minion's owner). The auto-react drain should
    # NOT bypass the modal; the sandbox session pauses waiting for the pick.
    #
    # The view_filter enriches the state with the picker-side fields:
    #   pending_death_target_owner_idx
    #   pending_death_card_numeric_id
    #   pending_death_card_name
    #   pending_death_filter
    #   pending_death_valid_targets
    page.wait_for_function(
        "() => sandboxState"
        " && sandboxState.pending_death_target_owner_idx === 1",
        timeout=3000,
    )

    card_nid = page.evaluate("() => sandboxState.pending_death_card_numeric_id")
    assert card_nid == RGB_LASERCANNON_NID, (
        f"pending_death_card_numeric_id should be {RGB_LASERCANNON_NID}, got {card_nid}"
    )
    valid_targets = page.evaluate("() => sandboxState.pending_death_valid_targets")
    assert valid_targets, "pending_death_valid_targets should not be empty"
    assert [0, 0] in valid_targets, (
        f"P1's Common Rat at (0, 0) should be a valid death target, got {valid_targets}"
    )
    # The dying lasercannon should be in P2's graveyard already.
    grave1 = page.evaluate("() => sandboxState.players[1].grave")
    assert RGB_LASERCANNON_NID in grave1, (
        f"Dead lasercannon should be in P2 graveyard, got {grave1}"
    )

    # --- 4. P2 submits DEATH_TARGET_PICK on the Common Rat ---
    # The death-target gate routes to whichever player is the picker
    # regardless of active_player_idx, so we just emit the action.
    # NOTE: DEATH_TARGET_PICK uses ``target_pos``, not ``position`` (see
    # legal_actions._pending_death_target_actions).
    _apply_action(page, {
        "action_type": ACTION_DEATH_TARGET_PICK,
        "target_pos": [0, 0],
    })

    # --- 5. Verify: rat destroyed, modal cleared, board empty ---
    page.wait_for_function(
        "() => sandboxState"
        " && (sandboxState.pending_death_target_owner_idx === null"
        "     || sandboxState.pending_death_target_owner_idx === undefined)",
        timeout=3000,
    )
    page.wait_for_function(
        "() => sandboxState && sandboxState.minions.length === 0",
        timeout=3000,
    )

    # Common Rat should now be in P1's graveyard.
    grave0 = page.evaluate("() => sandboxState.players[0].grave")
    assert COMMON_RAT_NID in grave0, (
        f"Picked Common Rat should be in P1 graveyard, got {grave0}"
    )
