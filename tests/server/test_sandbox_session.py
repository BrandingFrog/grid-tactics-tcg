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
    counter_nid = _find_numeric_id(library, "prohibition")
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


def test_to_dict_load_dict_roundtrip_on_death_pending_trigger(
    library: CardLibrary,
) -> None:
    """Phase 14.7-05b: PendingTrigger entries with trigger_kind="on_death"
    must round-trip through the sandbox save/load serializer. This
    validates that a mid-death-cleanup state can be autosaved and
    restored without losing queue entries.
    """
    from dataclasses import replace
    from grid_tactics.game_state import PendingTrigger

    s1 = SandboxSession(library, "a")
    # Synthesize a state with a queued on_death trigger on each queue.
    rgb_nid = library.get_numeric_id("rgb_lasercannon")
    giant_rat_nid = library.get_numeric_id("giant_rat")
    pt_turn = PendingTrigger(
        trigger_kind="on_death",
        source_minion_id=0,
        source_card_numeric_id=rgb_nid,
        effect_idx=0,
        owner_idx=0,
        captured_position=(1, 2),
        target_pos=None,
    )
    pt_other = PendingTrigger(
        trigger_kind="on_death",
        source_minion_id=1,
        source_card_numeric_id=giant_rat_nid,
        effect_idx=0,
        owner_idx=1,
        captured_position=(2, 2),
        target_pos=None,
    )
    s1._state = replace(
        s1._state,
        pending_trigger_queue_turn=(pt_turn,),
        pending_trigger_queue_other=(pt_other,),
    )

    payload = s1.to_dict()
    s2 = SandboxSession(library, "b")
    s2.load_dict(payload)

    # Round-tripped queues preserve length, trigger_kind, and card ID.
    assert len(s2.state.pending_trigger_queue_turn) == 1
    assert len(s2.state.pending_trigger_queue_other) == 1
    t_turn = s2.state.pending_trigger_queue_turn[0]
    t_other = s2.state.pending_trigger_queue_other[0]
    assert t_turn.trigger_kind == "on_death"
    assert t_turn.source_card_numeric_id == rgb_nid
    assert t_turn.owner_idx == 0
    assert t_turn.captured_position == (1, 2)
    assert t_other.trigger_kind == "on_death"
    assert t_other.source_card_numeric_id == giant_rat_nid
    assert t_other.owner_idx == 1
    assert t_other.captured_position == (2, 2)


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


# ---------------------------------------------------------------------------
# Phase 14.7-04: Compound summon window state survives save/load round trip
# ---------------------------------------------------------------------------


def test_sandbox_saves_summon_declaration_state(
    library: CardLibrary, isolated_slot_dir,
) -> None:
    """Window A (AFTER_SUMMON_DECLARATION) round-trips through save/load.

    14.7-04 introduced summon_declaration originator entries on the react
    stack. The GameState serializer (14.7-01) already speaks generic
    origin_kind strings — this test pins that compound-window originator
    state survives a full sandbox slot round trip.

    Note: no current card has react_condition OPPONENT_PLAYS_MINION (that
    lands in 14.7-07), so Window A on a pure minion deploy auto-drains in
    a normal sandbox apply_action flow. We therefore synthesize the
    Window A state via direct GameState construction + load_dict to
    exercise the serializer/deserializer end-to-end without relying on
    the sandbox auto-drain semantics.
    """
    from dataclasses import replace as _replace
    from grid_tactics.board import Board
    from grid_tactics.enums import PlayerSide, ReactContext, TurnPhase
    from grid_tactics.game_state import GameState
    from grid_tactics.player import Player
    from grid_tactics.react_stack import ReactEntry
    from grid_tactics.types import STARTING_HP

    blue_nid = _find_numeric_id(library, "blue_diodebot")

    # Hand-build a GameState that is stopped mid-Window-A.
    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=STARTING_HP,
        current_mana=0, max_mana=2, hand=(), deck=(), grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP,
        current_mana=4, max_mana=4, hand=(), deck=(), grave=(),
    )
    originator = ReactEntry(
        player_idx=0, card_index=-1, card_numeric_id=blue_nid,
        target_pos=(1, 0),
        is_originator=True, origin_kind="summon_declaration",
    )
    state = GameState(
        board=Board.empty(), players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.REACT,
        turn_number=3, seed=42,
        react_stack=(originator,),
        react_player_idx=1,
        react_context=ReactContext.AFTER_SUMMON_DECLARATION,
        react_return_phase=TurnPhase.ACTION,
    )

    # Install the state in a session by load_dict-ing its serialized form.
    s1 = SandboxSession(library, "a")
    s1.load_dict({"state": state.to_dict(), "active_view_idx": 0})
    assert s1.state.phase == TurnPhase.REACT
    assert s1.state.react_context == ReactContext.AFTER_SUMMON_DECLARATION
    assert s1.state.react_stack[0].origin_kind == "summon_declaration"

    # Save + load into a fresh session through file-based slot persistence.
    s1.save_to_slot("summon_decl_round_trip")

    s2 = SandboxSession(library, "b")
    s2.load_from_slot("summon_decl_round_trip")

    # Compound-window state fully reconstructed.
    assert s2.state.phase == TurnPhase.REACT
    assert s2.state.react_context == ReactContext.AFTER_SUMMON_DECLARATION
    assert s2.state.react_return_phase == TurnPhase.ACTION
    assert len(s2.state.react_stack) == 1
    origin = s2.state.react_stack[0]
    assert origin.is_originator is True
    assert origin.origin_kind == "summon_declaration"
    assert origin.card_numeric_id == blue_nid
    assert origin.target_pos == (1, 0)


def test_sandbox_saves_summon_effect_state(
    library: CardLibrary, isolated_slot_dir,
) -> None:
    """Window B (AFTER_SUMMON_EFFECT) round-trips through save/load.

    Mirrors the Window A test but for a summon_effect originator that
    carries source_minion_id + effect_payload. Exercises the full
    serializer/deserializer path for compound-window Window B state.
    """
    from grid_tactics.board import Board
    from grid_tactics.enums import PlayerSide, ReactContext, TurnPhase
    from grid_tactics.game_state import GameState
    from grid_tactics.minion import MinionInstance
    from grid_tactics.player import Player
    from grid_tactics.react_stack import ReactEntry
    from grid_tactics.types import STARTING_HP

    blue_nid = _find_numeric_id(library, "blue_diodebot")

    # Blue Diodebot already on the board (landed via Window A PASS-PASS).
    landed = MinionInstance(
        instance_id=0, card_numeric_id=blue_nid,
        owner=PlayerSide.PLAYER_1, position=(1, 0),
        current_health=8,
    )
    board = Board.empty().place(1, 0, 0)

    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=STARTING_HP,
        current_mana=0, max_mana=2, hand=(), deck=(), grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP,
        current_mana=5, max_mana=5, hand=(), deck=(), grave=(),
    )
    # ON_SUMMON effect index is 0 for Blue Diodebot (single tutor effect).
    originator = ReactEntry(
        player_idx=0, card_index=-1, card_numeric_id=blue_nid,
        target_pos=None,
        is_originator=True, origin_kind="summon_effect",
        source_minion_id=0,  # the landed minion's instance_id
        effect_payload=((0, None, int(PlayerSide.PLAYER_1)),),
    )
    state = GameState(
        board=board, players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.REACT,
        turn_number=3, seed=42,
        minions=(landed,), next_minion_id=1,
        react_stack=(originator,),
        react_player_idx=1,
        react_context=ReactContext.AFTER_SUMMON_EFFECT,
        react_return_phase=TurnPhase.ACTION,
    )

    s1 = SandboxSession(library, "a")
    s1.load_dict({"state": state.to_dict(), "active_view_idx": 0})

    s1.save_to_slot("summon_effect_round_trip")

    s2 = SandboxSession(library, "b")
    s2.load_from_slot("summon_effect_round_trip")

    # Window B fully restored.
    assert s2.state.phase == TurnPhase.REACT
    assert s2.state.react_context == ReactContext.AFTER_SUMMON_EFFECT
    assert s2.state.react_return_phase == TurnPhase.ACTION
    assert len(s2.state.react_stack) == 1
    origin = s2.state.react_stack[0]
    assert origin.is_originator is True
    assert origin.origin_kind == "summon_effect"
    assert origin.card_numeric_id == blue_nid
    assert origin.source_minion_id == 0
    # effect_payload (the ON_SUMMON tutor index) carried over too.
    assert origin.effect_payload is not None
    assert len(origin.effect_payload) == 1
    assert origin.effect_payload[0][0] == 0  # effect index
    # And the landed minion survives the round trip.
    assert len(s2.state.minions) == 1
    assert s2.state.minions[0].card_numeric_id == blue_nid


def test_sandbox_saves_pending_trigger_queue_state(
    library: CardLibrary, isolated_slot_dir,
) -> None:
    """Phase 14.7-05: pending_trigger_queue_{turn,other} + picker_idx round-trip through save/load.

    Builds a state with 2 entries in turn queue + 1 in other queue and
    pending_trigger_picker_idx=0 (the modal is open for P1). Save, load
    into a fresh session, assert all three fields survive the round
    trip. This exercises the serializer/deserializer path for the new
    priority-queue fields added in 14.7-05 Task 1.
    """
    from grid_tactics.board import Board
    from grid_tactics.enums import PlayerSide, TurnPhase
    from grid_tactics.game_state import GameState, PendingTrigger
    from grid_tactics.player import Player
    from grid_tactics.types import STARTING_HP

    paladin_nid = _find_numeric_id(library, "fallen_paladin")
    ember_nid = _find_numeric_id(library, "emberplague_rat")

    p1 = Player(
        side=PlayerSide.PLAYER_1, hp=STARTING_HP,
        current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
    )
    p2 = Player(
        side=PlayerSide.PLAYER_2, hp=STARTING_HP,
        current_mana=3, max_mana=3, hand=(), deck=(), grave=(),
    )

    # Synthesize queue entries. The captured_position + source_card_numeric_id
    # are the fields the picker modal uses to render the full card face.
    turn_triggers = (
        PendingTrigger(
            trigger_kind="start_of_turn",
            source_minion_id=10,
            source_card_numeric_id=paladin_nid,
            effect_idx=0,
            owner_idx=0,
            captured_position=(0, 0),
            target_pos=None,
        ),
        PendingTrigger(
            trigger_kind="start_of_turn",
            source_minion_id=11,
            source_card_numeric_id=paladin_nid,
            effect_idx=0,
            owner_idx=0,
            captured_position=(2, 3),
            target_pos=None,
        ),
    )
    other_triggers = (
        PendingTrigger(
            trigger_kind="end_of_turn",
            source_minion_id=20,
            source_card_numeric_id=ember_nid,
            effect_idx=0,
            owner_idx=1,
            captured_position=(4, 4),
            target_pos=(1, 2),
        ),
    )

    state = GameState(
        board=Board.empty(), players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.START_OF_TURN,
        turn_number=3, seed=42,
        pending_trigger_queue_turn=turn_triggers,
        pending_trigger_queue_other=other_triggers,
        pending_trigger_picker_idx=0,
    )

    # Install into a session via load_dict (same shape sandbox save/load uses).
    s1 = SandboxSession(library, "a")
    s1.load_dict({"state": state.to_dict(), "active_view_idx": 0})
    assert s1.state.pending_trigger_picker_idx == 0
    assert len(s1.state.pending_trigger_queue_turn) == 2
    assert len(s1.state.pending_trigger_queue_other) == 1

    # Save + load through the file-based slot persistence layer.
    s1.save_to_slot("pending_trigger_round_trip")

    s2 = SandboxSession(library, "b")
    s2.load_from_slot("pending_trigger_round_trip")

    # All three fields reconstituted.
    assert s2.state.pending_trigger_picker_idx == 0
    assert len(s2.state.pending_trigger_queue_turn) == 2
    assert len(s2.state.pending_trigger_queue_other) == 1

    # Spot-check payload integrity.
    t0 = s2.state.pending_trigger_queue_turn[0]
    assert isinstance(t0, PendingTrigger)
    assert t0.trigger_kind == "start_of_turn"
    assert t0.source_minion_id == 10
    assert t0.source_card_numeric_id == paladin_nid
    assert t0.captured_position == (0, 0)
    assert t0.target_pos is None

    o0 = s2.state.pending_trigger_queue_other[0]
    assert o0.trigger_kind == "end_of_turn"
    assert o0.source_minion_id == 20
    assert o0.source_card_numeric_id == ember_nid
    assert o0.captured_position == (4, 4)
    assert o0.target_pos == (1, 2)
