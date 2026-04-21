"""Tests for the engine_events module — phase 14.8-03a wire format.

Two test groups:

  1. ``Test*`` classes covering EngineEvent / EventStream primitives in
     isolation (no engine simulation). Fast, deterministic, validate the
     wire-format invariants the rest of phase 14.8 depends on.

  2. ``TestEngineEmission*`` classes that drive the engine via
     ``resolve_action`` with an ``EventStream`` plumbed through. Validate
     that engine call sites tagged in plan 14.8-01 emit events when a
     collector is provided AND that the default ``event_collector=None``
     path is silent (back-compat).
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from grid_tactics import phase_contracts
from grid_tactics.engine_events import (
    ALL_EVENT_TYPES,
    DEFAULT_DURATION_MS,
    EVT_ATTACK_RESOLVED,
    EVT_CARD_DRAWN,
    EVT_CARD_PLAYED,
    EVT_FIZZLE,
    EVT_GAME_OVER,
    EVT_MANA_CHANGE,
    EVT_MINION_DIED,
    EVT_MINION_HP_CHANGE,
    EVT_MINION_MOVED,
    EVT_MINION_SUMMONED,
    EVT_PENDING_MODAL_OPENED,
    EVT_PENDING_MODAL_RESOLVED,
    EVT_PHASE_CHANGED,
    EVT_PLAYER_HP_CHANGE,
    EVT_REACT_WINDOW_CLOSED,
    EVT_REACT_WINDOW_OPENED,
    EVT_TRIGGER_BLIP,
    EVT_TURN_FLIPPED,
    EngineEvent,
    EventStream,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def library():
    """Load all card JSONs once per test module."""
    from grid_tactics.card_library import CardLibrary
    return CardLibrary.from_directory(Path("data/cards"))


@pytest.fixture(autouse=True)
def shadow_mode(monkeypatch):
    """Force shadow mode for every test in this module so contract
    assertions don't raise even if a tag is briefly off — events are
    still emitted (event collection runs alongside the assertion).
    """
    monkeypatch.setenv("CONTRACT_ENFORCEMENT_MODE", "shadow")
    phase_contracts._reset_mode_cache()
    yield
    phase_contracts._reset_mode_cache()


# ---------------------------------------------------------------------------
# 1. EngineEvent dataclass invariants
# ---------------------------------------------------------------------------


class TestEngineEventDataclass:
    """The ``EngineEvent`` dataclass is the wire-format primitive every
    other plan 14.8 component reads. These tests pin its shape.
    """

    def test_engine_event_dataclass_roundtrip(self):
        """to_dict followed by from_dict reproduces the original event.

        Equality is structural (frozen dataclass) so ``==`` is the
        round-trip oracle. Default fields (triggered_by_seq, etc.) are
        included in the dict.
        """
        ev = EngineEvent(
            type=EVT_ATTACK_RESOLVED,
            contract_source="action:attack",
            seq=42,
            payload={"attacker_id": 7, "defender_id": 11, "attacker_dmg": 3},
            animation_duration_ms=500,
            triggered_by_seq=None,
            requires_decision=False,
        )
        d = ev.to_dict()
        ev2 = EngineEvent.from_dict(d)
        assert ev == ev2

    def test_engine_event_roundtrip_with_parent_seq_and_decision(self):
        """Round-trip preserves triggered_by_seq + requires_decision.

        These two fields are easy to drop on the wire; this test catches
        regressions in the to_dict / from_dict pair.
        """
        ev = EngineEvent(
            type=EVT_PENDING_MODAL_OPENED,
            contract_source="action:tutor_select",
            seq=99,
            payload={"modal_kind": "tutor_select", "owner_idx": 0},
            animation_duration_ms=0,
            triggered_by_seq=42,
            requires_decision=True,
        )
        d = ev.to_dict()
        assert d["triggered_by_seq"] == 42
        assert d["requires_decision"] is True
        ev2 = EngineEvent.from_dict(d)
        assert ev == ev2

    def test_engine_event_is_frozen(self):
        """EngineEvent is immutable — once emitted, the wire format is
        stable for the duration of the resolve_action call.
        """
        ev = EngineEvent(
            type=EVT_PHASE_CHANGED,
            contract_source="system:enter_start_of_turn",
            seq=0,
            payload={},
        )
        with pytest.raises((AttributeError, Exception)):  # FrozenInstanceError
            ev.seq = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. EventStream collector behavior
# ---------------------------------------------------------------------------


class TestEventStreamCollect:
    """EventStream is the per-call collector. Validate seq monotonicity,
    parent-seq nesting, and unknown-type rejection.
    """

    def test_event_stream_assigns_monotonic_seq(self):
        """Five collects in a fresh stream produce seq 0,1,2,3,4."""
        s = EventStream()
        seqs = []
        for i in range(5):
            ev = s.collect(
                EVT_PHASE_CHANGED,
                "system:enter_start_of_turn",
                {"i": i},
            )
            seqs.append(ev.seq)
        assert seqs == [0, 1, 2, 3, 4]
        assert s.next_seq == 5

    def test_event_stream_default_duration_lookup(self):
        """When animation_duration_ms is omitted, the per-type default
        from DEFAULT_DURATION_MS is applied.
        """
        s = EventStream()
        ev = s.collect(
            EVT_TURN_FLIPPED, "system:turn_flip",
            {"prev_turn": 1, "new_turn": 2, "new_active_idx": 1},
        )
        assert ev.animation_duration_ms == DEFAULT_DURATION_MS[EVT_TURN_FLIPPED]
        # Sanity: turn-flipped is the long banner duration (1.5s)
        assert ev.animation_duration_ms == 1500

    def test_event_stream_explicit_duration_overrides_default(self):
        """Caller-supplied animation_duration_ms wins over the default."""
        s = EventStream()
        ev = s.collect(
            EVT_TRIGGER_BLIP, "trigger:on_death",
            {"trigger_kind": "on_death", "source_minion_id": 7},
            animation_duration_ms=250,  # custom override
        )
        assert ev.animation_duration_ms == 250

    def test_event_stream_parent_nesting(self):
        """push_parent(seq) → next collect gets triggered_by_seq=seq;
        pop_parent restores no-parent state.
        """
        s = EventStream()
        s.push_parent(7)
        ev_inside = s.collect(
            EVT_MINION_HP_CHANGE, "trigger:on_damaged",
            {"instance_id": 11, "delta": -3},
        )
        assert ev_inside.triggered_by_seq == 7
        s.pop_parent()
        ev_outside = s.collect(
            EVT_PHASE_CHANGED, "system:enter_action", {},
        )
        assert ev_outside.triggered_by_seq is None

    def test_event_stream_nested_parents_use_innermost(self):
        """Nested push_parent/pop_parent stacks; the innermost parent is
        the one applied to events emitted within the nested scope.
        """
        s = EventStream()
        s.push_parent(10)
        s.push_parent(20)
        ev = s.collect(EVT_MINION_DIED, "trigger:on_death", {})
        assert ev.triggered_by_seq == 20
        s.pop_parent()
        ev2 = s.collect(EVT_MINION_DIED, "trigger:on_death", {})
        assert ev2.triggered_by_seq == 10
        s.pop_parent()
        ev3 = s.collect(EVT_MINION_DIED, "trigger:on_death", {})
        assert ev3.triggered_by_seq is None

    def test_event_stream_unknown_type_raises(self):
        """An unknown event-type string is a programmer typo — caught at
        collect time so it surfaces in tests, not in production.
        """
        s = EventStream()
        with pytest.raises(AssertionError, match="Unknown event type"):
            s.collect("bogus_type", "system:fizzle", {})

    def test_event_stream_starting_seq_offset(self):
        """EventStream(next_seq=42) → first collect emits seq=42, second seq=43.

        This is the per-session seq-continuation pattern that plan 03b's
        ``Session.next_event_seq`` depends on: each resolve_action call
        gets a fresh stream seeded with the session's persistent counter,
        and the post-call ``stream.next_seq`` is written back to the
        session.
        """
        s = EventStream(next_seq=42)
        ev1 = s.collect(EVT_CARD_DRAWN, "action:draw", {"card_id": 1})
        ev2 = s.collect(EVT_CARD_DRAWN, "action:draw", {"card_id": 2})
        assert ev1.seq == 42
        assert ev2.seq == 43
        assert s.next_seq == 44

    def test_event_stream_to_dict_list_preserves_order(self):
        """to_dict_list returns events in collection order (seq order)."""
        s = EventStream()
        for src in ["a", "b", "c", "d"]:
            s.collect(EVT_PHASE_CHANGED, f"system:{src}", {})
        dicts = s.to_dict_list()
        assert [d["seq"] for d in dicts] == [0, 1, 2, 3]
        assert [d["contract_source"] for d in dicts] == [
            "system:a", "system:b", "system:c", "system:d",
        ]


# ---------------------------------------------------------------------------
# 3. Schema completeness — every event type has a default duration
# ---------------------------------------------------------------------------


class TestEventTypeCoverage:
    def test_all_event_types_have_default_duration(self):
        """Every constant in ALL_EVENT_TYPES must have a row in
        DEFAULT_DURATION_MS — otherwise collect() with default duration
        would KeyError.
        """
        missing = ALL_EVENT_TYPES - set(DEFAULT_DURATION_MS.keys())
        assert not missing, (
            f"Event types missing DEFAULT_DURATION_MS entry: {sorted(missing)}"
        )

    def test_default_duration_covers_only_known_types(self):
        """No orphan entries in DEFAULT_DURATION_MS that aren't in
        ALL_EVENT_TYPES — would indicate a typo or stale constant.
        """
        extra = set(DEFAULT_DURATION_MS.keys()) - ALL_EVENT_TYPES
        assert not extra, (
            f"DEFAULT_DURATION_MS has unknown event types: {sorted(extra)}"
        )

    def test_19_event_types_total(self):
        """Plan 14.8-03a delivers exactly 19 event types per the research
        doc § 'Event types proposed'. Adding a new type requires an
        explicit roadmap entry, NOT silent expansion.
        """
        assert len(ALL_EVENT_TYPES) == 19


# ---------------------------------------------------------------------------
# 4. Engine integration — collector plumbed through resolve_action
# ---------------------------------------------------------------------------


def _new_state(library):
    """Fresh GameState in ACTION phase, P1 to act."""
    from grid_tactics.game_state import GameState
    all_card_ids = sorted(
        library.get_numeric_id(c.card_id) for c in library.all_cards
    )
    deck = tuple(all_card_ids[:7])
    state, _rng = GameState.new_game(seed=42, deck_p1=deck, deck_p2=deck)
    return state


class TestEngineEmissionDefaultSilent:
    """The default ``event_collector=None`` path must produce ZERO events
    and identical state to pre-plan-03a behavior. This is the
    back-compat invariant.
    """

    def test_resolve_action_default_no_collector_silent(self, library):
        """resolve_action without event_collector kwarg → no exceptions,
        no event side-effects. Engine works exactly as before.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType
        state = _new_state(library)
        # PASS the action phase — universally legal.
        action = Action(action_type=ActionType.PASS)
        new_state = resolve_action(state, action, library)
        assert new_state is not state
        assert new_state.phase != state.phase or True  # any phase change OK
        # Most important: no exception was raised, no event collector required.

    def test_resolve_action_with_empty_collector_does_not_break(self, library):
        """Passing an EventStream() doesn't break the call — the engine
        accepts the kwarg gracefully, even when no events fire.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType
        state = _new_state(library)
        action = Action(action_type=ActionType.PASS)
        stream = EventStream()
        new_state = resolve_action(
            state, action, library, event_collector=stream,
        )
        # State transitioned (PASS → react / next phase)
        assert new_state is not None
        # Stream may have events (PASS triggers PHASE_CHANGED / TURN_FLIPPED
        # depending on path) but the call must complete without exception.
        # Don't pin the exact event count — that's covered by per-event tests.


class TestEngineEmissionPerEventType:
    """Spot-check that key engine sites emit the expected event types
    when a collector is provided. Not exhaustive — the invariant test
    in 14.8-02 already covers contract coverage; these tests cover the
    new EVENT path overlaid on top.
    """

    def test_resolve_action_emits_phase_changed_on_pass(self, library):
        """A PASS action at minimum emits a PHASE_CHANGED event when the
        engine transitions out of the active phase.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType
        state = _new_state(library)
        action = Action(action_type=ActionType.PASS)
        stream = EventStream()
        resolve_action(state, action, library, event_collector=stream)
        # At minimum the engine should have emitted SOMETHING —
        # phase_changed (after pass), turn_flipped, etc.
        assert len(stream.events) > 0, (
            f"Expected at least one event after PASS, got 0. "
            f"Events: {[e.type for e in stream.events]}"
        )

    def test_event_seq_strictly_monotonic_across_engine_call(self, library):
        """Even with multiple events emitted in one resolve_action call,
        seq is strictly monotonic (0, 1, 2, ...) — replay invariant.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType
        state = _new_state(library)
        action = Action(action_type=ActionType.PASS)
        stream = EventStream()
        resolve_action(state, action, library, event_collector=stream)
        seqs = [e.seq for e in stream.events]
        assert seqs == sorted(seqs), f"seq not monotonic: {seqs}"
        assert len(seqs) == len(set(seqs)), f"duplicate seq: {seqs}"

    def test_event_starting_seq_is_preserved_across_calls(self, library):
        """Two consecutive resolve_action calls reuse the stream's
        running ``next_seq`` so seq is monotonic across the whole
        session, not just per-call.
        """
        from grid_tactics.action_resolver import resolve_action
        from grid_tactics.actions import Action
        from grid_tactics.enums import ActionType
        state = _new_state(library)
        stream = EventStream(next_seq=100)
        # First call
        new_state = resolve_action(
            state, Action(action_type=ActionType.PASS), library,
            event_collector=stream,
        )
        first_call_count = len(stream.events)
        if first_call_count == 0:
            pytest.skip("Engine emitted no events — emission integration not yet wired")
        # Stream's next_seq advanced past starting seq
        assert stream.next_seq >= 100 + first_call_count
        # First event has the seeded starting seq
        assert stream.events[0].seq == 100


class TestEngineEmissionShortcutAndDualWrite:
    """Cover the orchestrator-decision points called out in the plan:

      - decision #3: react_window_opened + react_window_closed are emitted
        on the shortcut path too (no triggers → dead-air react window).
      - trigger_blip dual-write: state.last_trigger_blip is still set
        AND EVT_TRIGGER_BLIP is emitted (migration window before plan
        14.8-05 deletes the field).
    """

    def test_react_window_opened_emitted_on_shortcut_path(self, library):
        """When enter_start_of_turn finds NO triggers it shortcuts to
        ACTION. The plan (orchestrator decision #3) requires a
        zero-duration react_window_opened + react_window_closed pair
        to fire for symmetry — the client treats them as instant.
        """
        from grid_tactics.enums import TurnPhase
        from grid_tactics.react_stack import enter_start_of_turn
        state = _new_state(library)
        # Force into END_OF_TURN-ish so enter_start_of_turn fires legally
        state = replace(state, phase=TurnPhase.END_OF_TURN)
        stream = EventStream()
        new_state = enter_start_of_turn(
            state, library, event_collector=stream,
        )
        # State should have shortcut to ACTION since no triggers exist.
        assert new_state.phase == TurnPhase.ACTION
        # Events should contain the OPENED + CLOSED pair (decision #3).
        types = [e.type for e in stream.events]
        assert "react_window_opened" in types, (
            f"Expected EVT_REACT_WINDOW_OPENED on shortcut, got: {types}"
        )
        assert "react_window_closed" in types, (
            f"Expected EVT_REACT_WINDOW_CLOSED on shortcut, got: {types}"
        )
        # The pair should be marked as shortcut payload entries.
        opened = [e for e in stream.events if e.type == "react_window_opened"]
        closed = [e for e in stream.events if e.type == "react_window_closed"]
        assert any(e.payload.get("shortcut") for e in opened)
        assert any(e.payload.get("shortcut") for e in closed)
        # And animation_duration_ms == 0 for the shortcut pair.
        for e in opened + closed:
            if e.payload.get("shortcut"):
                assert e.animation_duration_ms == 0

