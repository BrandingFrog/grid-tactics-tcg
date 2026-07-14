"""Regression tests for the Phase 14.8 server-lane bug fixes.

Covers:
  1. ``_decision_idx`` — PvP decision routing must mirror legal_actions'
     pending-gate ordering (trigger picker / revive / conjure / tutor /
     death target route to the picker, not the react/active player).
  2. ``reconcile_react_window_events`` — every react-window close path
     must produce an EVT_REACT_WINDOW_CLOSED on the wire (synthetic
     closes appended when an engine path skips the emission).
  3. Sandbox ``sandbox_apply_action`` error paths roll back to the
     pre-action snapshot (no partially-advanced state, no polluted undo).
  4. ``GameState.to_dict``/``from_dict`` round-trip ALL pending-modal
     fields (sandbox save/load fidelity).
  5. ``handle_ready`` rejects present-but-invalid custom decks loudly
     instead of silently falling back to the preset.
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from grid_tactics.actions import Action, pass_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.engine_events import (
    EVT_REACT_WINDOW_CLOSED,
    EVT_REACT_WINDOW_OPENED,
    EventStream,
)
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState, PendingDeathTarget
from grid_tactics.player import Player
from grid_tactics.roguelike_events import (
    CLUMSY_GREED,
    SHARP_EYED_SCEPTIC,
    WITH_A_SLAP,
)
from grid_tactics.server.action_codec import serialize_action
from grid_tactics.server.app import create_app, socketio
from grid_tactics.server.event_reconcile import reconcile_react_window_events
from grid_tactics.server.events import (
    _auto_advance_server_controlled_turn,
    _ai_watch_step_delay,
    _decision_idx,
    register_events,
)
from grid_tactics.server.room_manager import RoomManager
from grid_tactics.server.sandbox_session import SandboxSession


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library() -> CardLibrary:
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture
def app_and_rm():
    lib = CardLibrary.from_directory(Path("data/cards"))
    rm = RoomManager(lib)
    application = create_app(testing=True)
    register_events(rm)
    return application, rm


def _client(app):
    return socketio.test_client(app)


def _find(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    last = None
    for msg in events:
        if msg["name"] == name:
            last = msg["args"][0]
    return last


def _base_state(**overrides) -> GameState:
    p1 = Player.new(PlayerSide.PLAYER_1, ())
    p2 = Player.new(PlayerSide.PLAYER_2, ())
    state = GameState(
        board=Board.empty(),
        players=(p1, p2),
        active_player_idx=0,
        phase=TurnPhase.ACTION,
        turn_number=1,
        seed=0,
    )
    return replace(state, **overrides) if overrides else state


# ---------------------------------------------------------------------------
# 1. _decision_idx — pending-gate routing
# ---------------------------------------------------------------------------


class TestDecisionIdx:
    def test_trigger_picker_overrides_react_player(self):
        """The exact softlock state from the finding: active P0 owns the
        trigger picker while phase=REACT routes to P1. The picker (P0)
        must be the decision-maker."""
        state = _base_state(
            phase=TurnPhase.REACT,
            react_player_idx=1,
            pending_trigger_picker_idx=0,
        )
        assert _decision_idx(state) == 0

    def test_death_target_overrides_trigger_picker(self):
        state = _base_state(
            phase=TurnPhase.REACT,
            react_player_idx=0,
            pending_trigger_picker_idx=0,
            pending_death_target=PendingDeathTarget(
                card_numeric_id=0,
                owner_idx=1,
                dying_instance_id=7,
                effect_idx=0,
            ),
        )
        assert _decision_idx(state) == 1

    def test_revive_routes_to_reviving_player(self):
        state = _base_state(
            phase=TurnPhase.REACT,
            react_player_idx=0,
            pending_revive_player_idx=1,
            pending_revive_card_id="rat",
            pending_revive_remaining=2,
        )
        assert _decision_idx(state) == 1

    def test_conjure_deploy_routes_to_deployer(self):
        state = _base_state(
            phase=TurnPhase.ACTION,
            active_player_idx=0,
            pending_conjure_deploy_card=3,
            pending_conjure_deploy_player_idx=1,
        )
        assert _decision_idx(state) == 1

    def test_tutor_routes_to_tutoring_player(self):
        state = _base_state(
            phase=TurnPhase.ACTION,
            active_player_idx=0,
            pending_tutor_player_idx=1,
            pending_tutor_matches=(0,),
        )
        assert _decision_idx(state) == 1

    def test_react_phase_falls_back_to_react_player(self):
        state = _base_state(phase=TurnPhase.REACT, react_player_idx=1)
        assert _decision_idx(state) == 1


def test_preview_ai_resumes_when_fortune_returns_on_its_action(app_and_rm):
    """Turn 26 must not remain parked when the AI owns the postponed turn."""
    _application, rm = app_and_rm
    _code, session = rm.create_preview_game("Solo", "human-sid")
    session.state = replace(
        session.state,
        active_player_idx=1,
        phase=TurnPhase.ACTION,
        turn_number=26,
        pending_roguelike_event_turn=None,
        pending_roguelike_event_choices=(None, None),
        pending_roguelike_event_options=(),
        pending_marked_cards_player_idx=None,
        pending_marked_cards_cards=(),
        pending_marked_cards_queue=(),
    )

    stream = EventStream(next_seq=session.next_event_seq)
    _auto_advance_server_controlled_turn(session, stream)

    assert not (
        session.state.turn_number == 26
        and session.state.phase == TurnPhase.ACTION
        and session.state.active_player_idx == 1
    )
    if not session.state.is_game_over:
        assert (
            session.state.pending_roguelike_event_turn is not None
            or session.state.pending_marked_cards_player_idx is not None
            or session.player_sids[_decision_idx(session.state)] is not None
        )


def test_fortune_socket_handler_hands_turn_26_back_to_preview_ai(app_and_rm):
    application, rm = app_and_rm
    client = _client(application)
    client.emit("preview_game", {"display_name": "Solo"})
    client.get_received()
    session = next(iter(rm._games.values()))
    session.state = replace(
        session.state,
        active_player_idx=1,
        phase=TurnPhase.START_OF_TURN,
        turn_number=26,
        pending_roguelike_event_turn=26,
        pending_roguelike_event_choices=(None, None),
        pending_roguelike_event_options=(
            CLUMSY_GREED,
            SHARP_EYED_SCEPTIC,
            WITH_A_SLAP,
        ),
    )

    client.emit("roguelike_event_pick", {"choice": WITH_A_SLAP})

    assert not any(msg["name"] == "error" for msg in client.get_received())
    assert session.state.pending_roguelike_event_turn is None
    assert not (
        session.state.turn_number == 26
        and session.state.phase == TurnPhase.ACTION
        and session.state.active_player_idx == 1
    )

def test_action_phase_falls_back_to_active_player():
    state = _base_state(active_player_idx=1)
    assert _decision_idx(state) == 1


def test_ai_watch_fortune_offer_has_readable_dwell_even_at_4x():
    normal = _base_state()
    fortune = replace(
        normal,
        phase=TurnPhase.START_OF_TURN,
        turn_number=51,
        pending_roguelike_event_turn=51,
    )

    assert _ai_watch_step_delay(normal, 4) == pytest.approx(0.225)
    assert _ai_watch_step_delay(fortune, 4) == pytest.approx(2.4)


# ---------------------------------------------------------------------------
# 2. reconcile_react_window_events
# ---------------------------------------------------------------------------


class TestReconcileReactWindowEvents:
    def _stream_with(self, *types: str) -> EventStream:
        stream = EventStream(next_seq=0)
        for t in types:
            stream.collect(t, "system:test", {})
        return stream

    def test_appends_close_for_tutor_handoff_leak(self):
        """Window was open, engine emitted OPENED but closed the window
        via the pending_tutor hand-off (no CLOSED) — one synthetic close
        must be appended."""
        prev = _base_state()  # no window open before the action
        post = _base_state(pending_tutor_player_idx=0)  # ACTION + tutor gate
        stream = self._stream_with(EVT_REACT_WINDOW_OPENED)
        appended = reconcile_react_window_events(prev, post, stream)
        assert appended == 1
        closes = [e for e in stream.events if e.type == EVT_REACT_WINDOW_CLOSED]
        assert len(closes) == 1
        assert closes[-1].payload.get("synthetic") is True

    def test_appends_close_for_drain_recheck_reopen(self):
        """Old window closed + new window opened in one frame (drain
        recheck): OPENED emitted for the new window only. Net window
        count is unchanged, so one synthetic close balances the frame."""
        prev = _base_state(phase=TurnPhase.REACT, react_player_idx=1)
        post = _base_state(phase=TurnPhase.REACT, react_player_idx=1)
        stream = self._stream_with(EVT_REACT_WINDOW_OPENED)
        assert reconcile_react_window_events(prev, post, stream) == 1

    def test_balanced_frame_is_untouched(self):
        prev = _base_state()
        post = _base_state(phase=TurnPhase.REACT, react_player_idx=1)
        stream = self._stream_with(EVT_REACT_WINDOW_OPENED)
        assert reconcile_react_window_events(prev, post, stream) == 0
        assert len(stream.events) == 1

    def test_paired_open_close_is_untouched(self):
        prev = _base_state()
        post = _base_state()
        stream = self._stream_with(
            EVT_REACT_WINDOW_OPENED, EVT_REACT_WINDOW_CLOSED,
        )
        assert reconcile_react_window_events(prev, post, stream) == 0

    def test_missing_open_never_appends(self):
        """Inverse imbalance (window opened without an OPENED event, e.g.
        the post-move ATTACK resume) must NOT get a synthetic close."""
        prev = _base_state()
        post = _base_state(phase=TurnPhase.REACT, react_player_idx=1)
        stream = self._stream_with()
        assert reconcile_react_window_events(prev, post, stream) == 0
        assert stream.events == []

    def test_synthetic_events_have_monotonic_seq(self):
        prev = _base_state(phase=TurnPhase.REACT, react_player_idx=1)
        post = _base_state()
        stream = self._stream_with(EVT_REACT_WINDOW_OPENED)
        reconcile_react_window_events(prev, post, stream)
        seqs = [e.seq for e in stream.events]
        assert seqs == sorted(seqs)
        assert len(set(seqs)) == len(seqs)
        assert stream.next_seq == seqs[-1] + 1

    def test_wedged_react_state_counts_as_closed(self):
        """phase=REACT with react_player_idx=None (the drain-wedge shape)
        has no actionable window and must be treated as closed."""
        prev = _base_state(phase=TurnPhase.REACT, react_player_idx=1)
        post = _base_state(phase=TurnPhase.REACT, react_player_idx=None)
        stream = self._stream_with()
        # Window went away with no CLOSED emitted -> synthesize one.
        assert reconcile_react_window_events(prev, post, stream) == 1

    def test_sandbox_tutor_play_emits_balanced_open_close(self, library):
        """End-to-end through the real engine: playing a tutor magic card
        closes its react window via the pending_tutor hand-off, which the
        engine does not emit a CLOSED for. The reconciler must balance
        the frame so the client's spellStageChain drains."""
        sandbox = SandboxSession(library, sid="test-sid")
        ratmobile = library.get_numeric_id("to_the_ratmobile")
        rat = library.get_numeric_id("rat")
        sandbox.add_card_to_zone(0, ratmobile, "hand")
        sandbox.add_card_to_zone(0, rat, "deck_top")
        sandbox.add_card_to_zone(0, rat, "deck_top")
        sandbox.set_player_field(0, "current_mana", 10)

        play = None
        for a in sandbox.legal_actions():
            if a.action_type == ActionType.PLAY_CARD and a.card_index == 0:
                play = a
                break
        assert play is not None, "PLAY_CARD for the tutor magic must be legal"

        events = sandbox.apply_action(play)
        opened = sum(1 for e in events if e.type == EVT_REACT_WINDOW_OPENED)
        closed = sum(1 for e in events if e.type == EVT_REACT_WINDOW_CLOSED)
        # The tutor gate must be live server-side...
        assert sandbox.state.pending_tutor_player_idx == 0
        # ...and every emitted OPENED must have a matching CLOSED.
        assert opened >= 1
        assert opened == closed, (
            f"react window events unbalanced: {opened} opened vs "
            f"{closed} closed — spellStageChain would leak"
        )


# ---------------------------------------------------------------------------
# 3. Sandbox apply_action error rollback
# ---------------------------------------------------------------------------


class TestSandboxErrorRollback:
    def _create_sandbox(self, app, rm):
        client = _client(app)
        client.emit("sandbox_create")
        client.get_received()
        sandbox = next(iter(rm._sandboxes.values()))
        return client, sandbox

    def test_value_error_mid_drain_rolls_back(self, app_and_rm):
        app, rm = app_and_rm
        client, sandbox = self._create_sandbox(app, rm)

        original_state = sandbox.state
        original_undo_depth = sandbox.undo_depth

        def broken_apply(action):
            # Simulate the failure mode: apply_action pushed its undo
            # frame and partially advanced the state (user action + a
            # drained PASS), then a drained resolve_action raised.
            sandbox._push_undo()
            sandbox._state = replace(
                sandbox._state, turn_number=sandbox._state.turn_number + 5,
            )
            raise ValueError("engine blew up mid-drain")

        sandbox.apply_action = broken_apply
        client.emit("sandbox_apply_action", serialize_action(pass_action()))
        received = client.get_received()

        err = _find(received, "error")
        assert err is not None
        assert "engine blew up mid-drain" in err["msg"]
        # Server state must be back at the pre-action snapshot...
        assert sandbox.state is original_state
        # ...and the polluting undo frame must be popped.
        assert sandbox.undo_depth == original_undo_depth

    def test_generic_exception_mid_drain_rolls_back(self, app_and_rm):
        app, rm = app_and_rm
        client, sandbox = self._create_sandbox(app, rm)

        original_state = sandbox.state
        original_undo_depth = sandbox.undo_depth

        def broken_apply(action):
            sandbox._push_undo()
            sandbox._state = replace(
                sandbox._state, turn_number=sandbox._state.turn_number + 9,
            )
            raise KeyError("unexpected engine crash")

        sandbox.apply_action = broken_apply
        client.emit("sandbox_apply_action", serialize_action(pass_action()))
        received = client.get_received()

        err = _find(received, "error")
        assert err is not None
        assert "Server error" in err["msg"]
        assert sandbox.state is original_state
        assert sandbox.undo_depth == original_undo_depth

    def test_pre_validation_error_pops_no_extra_frames(self, app_and_rm):
        """apply_action's legal_actions pre-check raises BEFORE pushing an
        undo frame — the rollback must not pop older, legitimate frames."""
        app, rm = app_and_rm
        client, sandbox = self._create_sandbox(app, rm)

        # Seed one legitimate undo frame.
        sandbox.set_player_field(0, "current_mana", 5)
        assert sandbox.undo_depth == 1
        state_after_edit = sandbox.state

        # ATTACK with a bogus minion id is never legal on an empty board,
        # so apply_action raises "Illegal action" pre-push.
        illegal = Action(action_type=ActionType.ATTACK, minion_id=999, target_id=998)
        client.emit("sandbox_apply_action", serialize_action(illegal))
        received = client.get_received()

        err = _find(received, "error")
        assert err is not None
        assert sandbox.state is state_after_edit
        assert sandbox.undo_depth == 1  # the legit frame survives


# ---------------------------------------------------------------------------
# 4. GameState pending-modal serialization round-trip
# ---------------------------------------------------------------------------


class TestPendingModalSerialization:
    def test_round_trip_preserves_all_pending_fields(self):
        state = _base_state(
            pending_post_move_attacker_id=4,
            pending_tutor_player_idx=1,
            pending_tutor_matches=(2, 5, 9),
            pending_tutor_is_conjure=True,
            pending_tutor_remaining=2,
            pending_revive_player_idx=0,
            pending_revive_card_id="rat",
            pending_revive_remaining=3,
            pending_conjure_deploy_card=7,
            pending_conjure_deploy_player_idx=1,
        )
        # JSON round-trip mirrors sandbox save slots / download blobs.
        loaded = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
        assert loaded.pending_post_move_attacker_id == 4
        assert loaded.pending_tutor_player_idx == 1
        assert loaded.pending_tutor_matches == (2, 5, 9)
        assert loaded.pending_tutor_is_conjure is True
        assert loaded.pending_tutor_remaining == 2
        assert loaded.pending_revive_player_idx == 0
        assert loaded.pending_revive_card_id == "rat"
        assert loaded.pending_revive_remaining == 3
        assert loaded.pending_conjure_deploy_card == 7
        assert loaded.pending_conjure_deploy_player_idx == 1

    def test_round_trip_preserves_pending_death_target(self):
        state = _base_state(
            pending_death_target=PendingDeathTarget(
                card_numeric_id=12,
                owner_idx=1,
                dying_instance_id=33,
                effect_idx=1,
                filter="friendly_promote",
            ),
        )
        loaded = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
        pdt = loaded.pending_death_target
        assert pdt is not None
        assert pdt.card_numeric_id == 12
        assert pdt.owner_idx == 1
        assert pdt.dying_instance_id == 33
        assert pdt.effect_idx == 1
        assert pdt.filter == "friendly_promote"

    def test_defaults_when_fields_absent_from_legacy_saves(self):
        """Old save dicts (pre-fix) lack the pending keys entirely — they
        must load with defaults, not crash."""
        state = _base_state()
        d = state.to_dict()
        for key in (
            "pending_post_move_attacker_id",
            "pending_tutor_player_idx",
            "pending_tutor_matches",
            "pending_tutor_is_conjure",
            "pending_tutor_remaining",
            "pending_revive_player_idx",
            "pending_revive_card_id",
            "pending_revive_remaining",
            "pending_conjure_deploy_card",
            "pending_conjure_deploy_player_idx",
            "pending_death_target",
        ):
            d.pop(key, None)
        loaded = GameState.from_dict(d)
        assert loaded.pending_post_move_attacker_id is None
        assert loaded.pending_tutor_player_idx is None
        assert loaded.pending_tutor_matches == ()
        assert loaded.pending_tutor_is_conjure is False
        assert loaded.pending_tutor_remaining == 0
        assert loaded.pending_revive_player_idx is None
        assert loaded.pending_revive_card_id is None
        assert loaded.pending_revive_remaining == 0
        assert loaded.pending_conjure_deploy_card is None
        assert loaded.pending_conjure_deploy_player_idx is None
        assert loaded.pending_death_target is None

    def test_sandbox_slot_round_trip_keeps_modal_state(self, library, tmp_path,
                                                       monkeypatch):
        """DEV-08 save slots must not strip an in-flight tutor modal."""
        import grid_tactics.server.sandbox_session as mod
        monkeypatch.setattr(mod, "SLOT_DIR", tmp_path)

        sandbox = SandboxSession(library, sid="slot-test")
        sandbox._state = replace(
            sandbox._state,
            pending_tutor_player_idx=0,
            pending_tutor_matches=(0, 1),
            pending_tutor_remaining=2,
        )
        sandbox.save_to_slot("modal_case")

        fresh = SandboxSession(library, sid="slot-test-2")
        fresh.load_from_slot("modal_case")
        assert fresh.state.pending_tutor_player_idx == 0
        assert fresh.state.pending_tutor_matches == (0, 1)
        assert fresh.state.pending_tutor_remaining == 2


# ---------------------------------------------------------------------------
# 5. handle_ready deck validation
# ---------------------------------------------------------------------------


class TestReadyDeckValidation:
    def _room_with_two_players(self, app):
        c1, c2 = _client(app), _client(app)
        c1.emit("create_room", {"display_name": "Alice"})
        received = c1.get_received()
        code = _find(received, "room_created")["room_code"]
        c2.emit("join_room", {"room_code": code, "display_name": "Bob"})
        c1.get_received()
        c2.get_received()
        return c1, c2

    def test_wrong_size_deck_errors_instead_of_silent_preset(self, app_and_rm):
        app, _rm = app_and_rm
        c1, c2 = self._room_with_two_players(app)

        c1.emit("ready", {"deck": [0] * 39})
        received = c1.get_received()

        err = _find(received, "error")
        assert err is not None
        assert "Invalid deck" in err["msg"]
        assert "40" in err["msg"]
        # Ready-up must have been aborted — no player_ready broadcast.
        assert _find(received, "player_ready") is None
        assert _find(c2.get_received(), "player_ready") is None

    def test_non_list_deck_errors(self, app_and_rm):
        app, _rm = app_and_rm
        c1, _c2 = self._room_with_two_players(app)
        c1.emit("ready", {"deck": "not-a-deck"})
        received = c1.get_received()
        err = _find(received, "error")
        assert err is not None
        assert "Invalid deck" in err["msg"]
        assert _find(received, "player_ready") is None

    def test_null_deck_still_readies_on_preset(self, app_and_rm):
        """The client sends {deck: null} when no custom deck is selected —
        that must keep working (preset fallback is intended there)."""
        app, _rm = app_and_rm
        c1, _c2 = self._room_with_two_players(app)
        c1.emit("ready", {"deck": None})
        received = c1.get_received()
        assert _find(received, "error") is None
        assert _find(received, "player_ready") is not None

    def test_valid_40_card_deck_still_accepted(self, app_and_rm, library):
        app, _rm = app_and_rm
        c1, _c2 = self._room_with_two_players(app)
        # Build a legal 40-card deck: up to 3 copies (the max) per
        # deckable card until we reach exactly 40.
        deckable = [
            nid for nid in range(library.card_count)
            if getattr(library.get_by_id(nid), "deckable", True)
        ]
        deck = []
        for nid in deckable:
            deck.extend([nid] * 3)
            if len(deck) >= 40:
                break
        deck = deck[:40]
        c1.emit("ready", {"deck": deck})
        received = c1.get_received()
        assert _find(received, "error") is None
        assert _find(received, "player_ready") is not None
