"""Unit tests for SandboxSession (Phase 14.6-01).

Covers:
  * Empty starting state (no RNG, no draws)
  * Zone editing across hand / deck_top / deck_bottom / graveyard / exhaust
  * Immutability (dataclasses.replace produces new objects)
  * Deck import replaces the deck
  * Cheat mode (set_player_field) bypasses rule checks
  * Active-player mutation persists into GameState
  * apply_action validates via legal_actions
  * Undo/redo depth via public properties, HISTORY_MAX holds >= 50
  * to_dict / load_dict round trip
  * Save/load/list/delete slot files (isolated tmp_path)
  * Slot name validation (regex + basename identity)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from grid_tactics.actions import Action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType
from grid_tactics.server.sandbox_session import (
    HISTORY_MAX,
    PLAYER_FIELDS,
    SLOT_DIR,
    ZONES,
    SandboxSession,
)
from grid_tactics.types import STARTING_HP, STARTING_MANA


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def library() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture
def session(library: CardLibrary) -> SandboxSession:
    return SandboxSession(library, "test-sid")


@pytest.fixture
def isolated_slot_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SLOT_DIR to a tmp_path so slot tests don't pollute the real dir."""
    import grid_tactics.server.sandbox_session as mod

    monkeypatch.setattr(mod, "SLOT_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Construction + invariants
# ---------------------------------------------------------------------------


def test_new_session_starts_empty(session: SandboxSession) -> None:
    for p in session.state.players:
        assert len(p.hand) == 0
        assert len(p.deck) == 0
        assert len(p.grave) == 0
        assert len(p.exhaust) == 0
        assert p.hp == STARTING_HP
        assert p.current_mana == STARTING_MANA
    assert session.state.turn_number == 1
    assert session.state.active_player_idx == 0
    assert session.undo_depth == 0
    assert session.redo_depth == 0


def test_no_rng_attribute(session: SandboxSession) -> None:
    assert not hasattr(session, "_rng")
    assert not hasattr(session, "rng")


def test_undo_redo_depth_properties(session: SandboxSession) -> None:
    assert session.undo_depth == 0
    assert session.redo_depth == 0
    session.add_card_to_zone(0, 0, "hand")
    assert session.undo_depth == 1
    assert session.redo_depth == 0
    session.undo()
    assert session.undo_depth == 0
    assert session.redo_depth == 1


# ---------------------------------------------------------------------------
# Zone editing
# ---------------------------------------------------------------------------


def test_add_card_to_zone_each_zone(library: CardLibrary) -> None:
    """Verify each zone string lands the card in the correct Player attribute."""
    for zone in ZONES:
        s = SandboxSession(library, "test")
        s.add_card_to_zone(0, 0, zone)
        p = s.state.players[0]
        if zone == "hand":
            assert p.hand == (0,)
        elif zone == "deck_top":
            assert p.deck == (0,)
            # deck_top means index 0
            assert p.deck[0] == 0
        elif zone == "deck_bottom":
            assert p.deck == (0,)
            assert p.deck[-1] == 0
        elif zone == "graveyard":
            assert p.grave == (0,)
        elif zone == "exhaust":
            assert p.exhaust == (0,)


def test_add_card_to_zone_immutability(session: SandboxSession) -> None:
    """Immutability proof: player object identity must change after a zone op."""
    before_id = id(session.state.players[0])
    session.add_card_to_zone(0, 0, "hand")
    after_id = id(session.state.players[0])
    assert before_id != after_id


def test_add_card_to_zone_invalid_zone_raises(session: SandboxSession) -> None:
    with pytest.raises(ValueError):
        session.add_card_to_zone(0, 0, "the_void")


def test_add_card_to_zone_invalid_player_raises(session: SandboxSession) -> None:
    with pytest.raises(ValueError):
        session.add_card_to_zone(7, 0, "hand")


def test_add_card_to_zone_invalid_card_id_raises(session: SandboxSession) -> None:
    with pytest.raises(ValueError):
        session.add_card_to_zone(0, 999_999, "hand")


def test_deck_top_vs_deck_bottom_ordering(library: CardLibrary) -> None:
    """deck_top prepends, deck_bottom appends."""
    s = SandboxSession(library, "test")
    s.add_card_to_zone(0, 3, "deck_top")     # deck = (3,)
    s.add_card_to_zone(0, 7, "deck_bottom")  # deck = (3, 7)
    s.add_card_to_zone(0, 5, "deck_top")     # deck = (5, 3, 7)
    assert s.state.players[0].deck == (5, 3, 7)


def test_move_card_between_zones_roundtrip(session: SandboxSession) -> None:
    session.add_card_to_zone(0, 0, "deck_top")
    session.move_card_between_zones(0, 0, "deck_top", "hand")
    assert session.state.players[0].deck == ()
    assert session.state.players[0].hand == (0,)

    session.move_card_between_zones(0, 0, "hand", "graveyard")
    assert session.state.players[0].hand == ()
    assert session.state.players[0].grave == (0,)

    session.move_card_between_zones(0, 0, "graveyard", "exhaust")
    assert session.state.players[0].grave == ()
    assert session.state.players[0].exhaust == (0,)


def test_move_card_not_in_src_raises(session: SandboxSession) -> None:
    with pytest.raises(ValueError):
        session.move_card_between_zones(0, 42, "hand", "graveyard")


def test_import_deck_replaces_existing_deck(session: SandboxSession) -> None:
    session.add_card_to_zone(0, 0, "deck_bottom")
    session.add_card_to_zone(0, 1, "deck_bottom")
    session.add_card_to_zone(0, 2, "deck_bottom")
    assert session.state.players[0].deck == (0, 1, 2)

    session.import_deck(0, [1, 2, 3])
    assert session.state.players[0].deck == (1, 2, 3)


def test_import_deck_validates_card_ids(session: SandboxSession) -> None:
    with pytest.raises(ValueError):
        session.import_deck(0, [99999])


def test_import_deck_empty_list_allowed(session: SandboxSession) -> None:
    session.add_card_to_zone(0, 0, "deck_bottom")
    session.import_deck(0, [])
    assert session.state.players[0].deck == ()


# ---------------------------------------------------------------------------
# Cheat inputs
# ---------------------------------------------------------------------------


def test_set_player_field_cheat_mode(session: SandboxSession) -> None:
    session.set_player_field(0, "hp", -50)
    assert session.state.players[0].hp == -50

    session.set_player_field(0, "max_mana", 9999)
    assert session.state.players[0].max_mana == 9999

    session.set_player_field(1, "current_mana", 500)
    assert session.state.players[1].current_mana == 500


def test_set_player_field_invalid_field_raises(session: SandboxSession) -> None:
    with pytest.raises(ValueError):
        session.set_player_field(0, "magic_resistance", 5)


def test_set_player_field_allowed_fields_match_constant(session: SandboxSession) -> None:
    # All three PLAYER_FIELDS values must be accepted.
    for field in PLAYER_FIELDS:
        session.set_player_field(0, field, 42)
    # And a non-member must not be.
    assert "hp" in PLAYER_FIELDS
    with pytest.raises(ValueError):
        session.set_player_field(0, "hand", 0)


# ---------------------------------------------------------------------------
# Active player toggle
# ---------------------------------------------------------------------------


def test_set_active_player_mutates_state(session: SandboxSession) -> None:
    assert session.state.active_player_idx == 0
    session.set_active_player(1)
    assert session.state.active_player_idx == 1
    assert session.active_view_idx == 1
    # legal_actions must run without error for the new active player
    _ = session.legal_actions()


def test_set_active_player_invalid_raises(session: SandboxSession) -> None:
    with pytest.raises(ValueError):
        session.set_active_player(5)


# ---------------------------------------------------------------------------
# apply_action
# ---------------------------------------------------------------------------


def test_apply_action_rejects_illegal(session: SandboxSession) -> None:
    # Hand is empty, so PLAY_CARD with card_index=0 is not in legal_actions.
    bogus = Action(action_type=ActionType.PLAY_CARD, card_index=0, position=(0, 0))
    with pytest.raises(ValueError, match="Illegal action"):
        session.apply_action(bogus)


def test_apply_action_legal_path_round_trip(session: SandboxSession) -> None:
    """apply_action should accept a real engine-legal action via legal_actions().

    On a state where the active player has a non-empty deck, DRAW appears in
    the legal set. Applying it advances state and bumps undo_depth.
    """
    session.add_card_to_zone(0, 0, "deck_top")
    actions = session.legal_actions()
    assert len(actions) >= 1
    # Apply the first legal action — must not raise
    depth_before = session.undo_depth
    session.apply_action(actions[0])
    assert session.undo_depth == depth_before + 1


def _find_numeric_id(library: CardLibrary, card_id: str) -> int:
    """Helper: look up a card's numeric_id by its string card_id."""
    for nid in range(library.card_count):
        if library.get_by_id(nid).card_id == card_id:
            return nid
    raise LookupError(f"card_id {card_id!r} not in library")


def test_apply_action_drains_trivial_react_window(
    session: SandboxSession, library: CardLibrary
) -> None:
    """Regression: sandbox deploy must NOT leave the session stuck in REACT phase.

    Repro for the 2026-04-11 "sandbox deploy silent-fail" bug: after playing a
    card that opens a react window, the sandbox was left sitting in REACT phase
    waiting for a PASS that no UI could issue (active_view_idx=0 but
    react_player_idx=1, so isReactWindow() returned false client-side).

    The fix is for ``SandboxSession.apply_action`` to auto-drain trivial react
    windows (where PASS is the ONLY legal action) immediately — matching what
    the real multiplayer client does via its auto-skip-empty-react block in
    renderActionBar. This mirrors how an empty-hand P2 would auto-pass in a
    real duel.

    Assertions after deploying a Common Rat from P1 with 1 mana:
      - mana deducted (1 -> 0)
      - rat on the board (minions count = 1)
      - phase back to ACTION (not stuck in REACT)
      - active player advanced to P2 (turn actually ended)
    """
    rat_nid = _find_numeric_id(library, "rat")
    session.set_player_field(0, "current_mana", 1)
    session.add_card_to_zone(0, rat_nid, "hand")

    play_actions = [
        a for a in session.legal_actions() if a.action_type == ActionType.PLAY_CARD
    ]
    assert play_actions, "Expected at least one legal PLAY_CARD for rat with 1 mana"

    session.apply_action(play_actions[0])

    from grid_tactics.enums import TurnPhase

    assert session.state.players[0].current_mana == 0, "mana not deducted"
    assert len(session.state.minions) == 1, "rat not deployed to board"
    assert session.state.phase == TurnPhase.ACTION, (
        f"session stuck in {session.state.phase.name} instead of ACTION — "
        "trivial react window was not drained"
    )
    assert session.state.active_player_idx == 1, "turn did not advance to P2"
    assert session.state.react_player_idx is None, "react state not cleared"


def test_apply_action_preserves_react_window_when_opponent_has_reacts(
    session: SandboxSession, library: CardLibrary
) -> None:
    """When P2 has a legal react card, the sandbox must NOT auto-pass.

    The auto-drain is strictly the "only PASS is legal" case (mirrors the real
    client's auto-skip-empty-react). If P2 actually has a react card that
    could counter the play, the sandbox user should be able to choose — so
    the session stays in REACT phase.

    We load P2's hand with counter_spell (reacts to OPPONENT_PLAYS_MAGIC) and
    give them enough mana; after P1 plays a magic card the session should
    remain in REACT.
    """
    magic_nid = _find_numeric_id(library, "to_the_ratmobile")
    counter_nid = _find_numeric_id(library, "counter_spell")
    counter_cost = library.get_by_id(counter_nid).mana_cost

    session.set_player_field(0, "current_mana", 3)  # enough for to_the_ratmobile (cost=3)
    session.add_card_to_zone(0, magic_nid, "hand")
    session.add_card_to_zone(1, counter_nid, "hand")
    session.set_player_field(1, "current_mana", max(counter_cost, 1))

    play_actions = [
        a for a in session.legal_actions() if a.action_type == ActionType.PLAY_CARD
    ]
    assert play_actions
    session.apply_action(play_actions[0])

    from grid_tactics.enums import TurnPhase

    # Engine state IS advanced (mana spent, magic resolved) even during the react
    # window — that part is baseline engine behavior.
    assert session.state.players[0].current_mana == 0

    # BUT because P2 has a legal react, the sandbox must leave the state in
    # REACT phase so the user can decide whether to counter.
    assert session.state.phase == TurnPhase.REACT, (
        "auto-drain fired despite P2 having a legal react card — it should "
        "only drain trivial (PASS-only) react windows"
    )
    assert session.state.react_player_idx == 1


# ---------------------------------------------------------------------------
# Undo / redo / reset
# ---------------------------------------------------------------------------


def test_undo_redo_round_trip(session: SandboxSession) -> None:
    initial_hand = session.state.players[0].hand
    session.add_card_to_zone(0, 0, "hand")
    session.add_card_to_zone(0, 1, "hand")
    session.add_card_to_zone(0, 2, "hand")
    assert session.state.players[0].hand == (0, 1, 2)

    # Undo 3 times → back to initial
    assert session.undo()
    assert session.undo()
    assert session.undo()
    assert session.state.players[0].hand == initial_hand

    # Redo 3 times → back to (0, 1, 2)
    assert session.redo()
    assert session.redo()
    assert session.redo()
    assert session.state.players[0].hand == (0, 1, 2)


def test_undo_stack_holds_at_least_50(session: SandboxSession) -> None:
    # HISTORY_MAX is 64 so undo_depth will cap there.
    for i in range(60):
        session.add_card_to_zone(0, 0, "hand")
    assert session.undo_depth == min(60, HISTORY_MAX)
    assert HISTORY_MAX >= 50

    # Undo everything the deque still remembers
    while session.undo():
        pass
    # If we did all 60, hand is empty; if we capped at HISTORY_MAX, the
    # earliest 60 - HISTORY_MAX adds are unreachable — either way, the
    # reachable history must be at least 50 steps deep.
    # Specifically: we did 60 pushes into a deque of maxlen 64, so every
    # push is still present and the final hand length equals 0 after all undos.
    assert len(session.state.players[0].hand) == 0


def test_undo_empty_returns_false(session: SandboxSession) -> None:
    assert session.undo() is False


def test_redo_empty_returns_false(session: SandboxSession) -> None:
    session.add_card_to_zone(0, 0, "hand")
    # no redo yet
    assert session.redo() is False


def test_reset_clears_to_empty(session: SandboxSession) -> None:
    session.add_card_to_zone(0, 0, "hand")
    session.set_player_field(0, "hp", 5)
    session.reset()
    assert len(session.state.players[0].hand) == 0
    assert session.state.players[0].hp == STARTING_HP
    assert session.state.turn_number == 1


# ---------------------------------------------------------------------------
# Serialization round trip
# ---------------------------------------------------------------------------


def test_to_dict_load_dict_round_trip(library: CardLibrary) -> None:
    s1 = SandboxSession(library, "a")
    s1.add_card_to_zone(0, 2, "hand")
    s1.add_card_to_zone(1, 3, "graveyard")
    s1.set_active_player(1)

    payload = s1.to_dict()

    s2 = SandboxSession(library, "b")
    s2.load_dict(payload)
    assert s2.state.players[0].hand == (2,)
    assert s2.state.players[1].grave == (3,)
    assert s2.state.active_player_idx == 1
    assert s2.active_view_idx == 1
    # load_dict clears the undo/redo deques
    assert s2.undo_depth == 0
    assert s2.redo_depth == 0


# ---------------------------------------------------------------------------
# Server slot persistence (isolated tmp_path)
# ---------------------------------------------------------------------------


def test_save_to_slot_writes_file(
    session: SandboxSession, isolated_slot_dir: Path
) -> None:
    session.save_to_slot("my_slot")
    expected = isolated_slot_dir / "my_slot.json"
    assert expected.exists()
    with expected.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    assert "state" in payload
    assert "active_view_idx" in payload


def test_load_from_slot_round_trip(
    library: CardLibrary, isolated_slot_dir: Path
) -> None:
    s1 = SandboxSession(library, "a")
    s1.add_card_to_zone(0, 1, "hand")
    s1.save_to_slot("round_trip")

    s2 = SandboxSession(library, "b")
    s2.load_from_slot("round_trip")
    assert s2.state.players[0].hand == (1,)


def test_list_slots_returns_sorted_names(
    library: CardLibrary, isolated_slot_dir: Path
) -> None:
    s = SandboxSession(library, "a")
    for name in ("zebra", "alpha", "gamma"):
        s.save_to_slot(name)
    assert SandboxSession.list_slots() == ["alpha", "gamma", "zebra"]


def test_delete_slot_returns_existence_flag(
    session: SandboxSession, isolated_slot_dir: Path
) -> None:
    session.save_to_slot("to_delete")
    assert SandboxSession.delete_slot("to_delete") is True
    assert SandboxSession.delete_slot("to_delete") is False


def test_load_from_slot_missing_raises(
    session: SandboxSession, isolated_slot_dir: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        session.load_from_slot("nonexistent")


def test_list_slots_skips_non_matching_files(
    library: CardLibrary, isolated_slot_dir: Path
) -> None:
    # Drop a file matching the regex and one that doesn't.
    (isolated_slot_dir / "valid_name.json").write_text("{}", encoding="utf-8")
    (isolated_slot_dir / "bad name.json").write_text("{}", encoding="utf-8")
    assert SandboxSession.list_slots() == ["valid_name"]


# ---------------------------------------------------------------------------
# Slot-name validation
# ---------------------------------------------------------------------------


def test_slot_name_validation_rejects_path_traversal() -> None:
    bad_names = [
        "../etc",
        "a/b",
        "a\\b",
        "",
        ".",
        "name with spaces",
        "a" * 65,
        "name.json",
        "name\u00e9",
    ]
    for bad in bad_names:
        with pytest.raises(ValueError):
            SandboxSession._validate_slot_name(bad)


def test_slot_name_validation_accepts_valid() -> None:
    good_names = ["a", "ABC123", "snake_case-with-dashes", "a" * 64]
    for good in good_names:
        assert SandboxSession._validate_slot_name(good) == good


def test_slot_name_validation_non_string_raises() -> None:
    with pytest.raises(ValueError):
        SandboxSession._validate_slot_name(42)  # type: ignore[arg-type]
