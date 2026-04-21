"""Engine event stream — phase 14.8-03a wire format.

Replaces the post-resolution state-snapshot diff approach with an explicit
event log. Each state mutation that already calls ``assert_phase_contract``
in plan 14.8-01 ALSO emits an ``EngineEvent`` into the optional collector
passed via ``event_collector`` to ``resolve_action``. The client's
eventQueue (plans 14.8-04a/b) consumes these in seq order.

Sandbox edits (cheat_mana, undo, set_active, etc.) ALSO produce events
tagged ``contract_source='sandbox:<verb>'``. They bypass phase-contract
assertions (see ``phase_contracts.py``) but flow through the same
event-stream pipeline so the client uses ONE rendering path for all
server-driven state changes.

Wire-format design:

- 19 ``EVT_*`` constants enumerated explicitly (no wildcards). Listed in
  ``ALL_EVENT_TYPES`` for runtime validation.
- Per-event ``DEFAULT_DURATION_MS`` lookup so emitters don't have to
  duplicate animation timings across modules. Emitters can override by
  passing ``animation_duration_ms`` explicitly.
- ``EventStream`` owns a monotonic ``next_seq`` counter. The session
  (plan 14.8-03b) seeds the starting seq on each ``resolve_action`` call
  via ``EventStream(next_seq=session.next_event_seq)`` and persists
  ``stream.next_seq`` back to the session afterwards. This keeps seq
  monotonic across the lifetime of a game.
- Inline-trigger nesting: ``push_parent(seq)`` / ``pop_parent()`` wraps
  inner ``resolve_effect`` calls so events emitted inside have
  ``triggered_by_seq`` pointing at the parent. Solves research-doc
  pitfall #4 (replay needs to know which on-attack trigger spawned which
  on-damaged trigger).

This module is PURE — no dependency on game_state / engine modules.
``EngineEvent.payload`` is an arbitrary dict so callers can include any
serializable data without tightening the schema here. The client
(plan 14.8-04a) will define payload schemas per event type.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Event type constants (19 total, per research §"Event types proposed")
# ---------------------------------------------------------------------------

# Board-state events
EVT_MINION_SUMMONED = "minion_summoned"
EVT_MINION_DIED = "minion_died"
EVT_MINION_HP_CHANGE = "minion_hp_change"
EVT_MINION_MOVED = "minion_moved"
EVT_ATTACK_RESOLVED = "attack_resolved"

# Card / hand events
EVT_CARD_DRAWN = "card_drawn"
EVT_CARD_PLAYED = "card_played"
EVT_CARD_DISCARDED = "card_discarded"

# Resource events
EVT_MANA_CHANGE = "mana_change"
EVT_PLAYER_HP_CHANGE = "player_hp_change"

# Phase / turn events
EVT_REACT_WINDOW_OPENED = "react_window_opened"
EVT_REACT_WINDOW_CLOSED = "react_window_closed"
EVT_PHASE_CHANGED = "phase_changed"
EVT_TURN_FLIPPED = "turn_flipped"

# Trigger / animation events
EVT_TRIGGER_BLIP = "trigger_blip"

# Pending modal events (orchestrator decision #4)
EVT_PENDING_MODAL_OPENED = "pending_modal_opened"
EVT_PENDING_MODAL_RESOLVED = "pending_modal_resolved"

# Edge events
EVT_FIZZLE = "fizzle"
EVT_GAME_OVER = "game_over"


ALL_EVENT_TYPES: frozenset[str] = frozenset({
    EVT_MINION_SUMMONED,
    EVT_MINION_DIED,
    EVT_MINION_HP_CHANGE,
    EVT_MINION_MOVED,
    EVT_ATTACK_RESOLVED,
    EVT_CARD_DRAWN,
    EVT_CARD_PLAYED,
    EVT_CARD_DISCARDED,
    EVT_MANA_CHANGE,
    EVT_PLAYER_HP_CHANGE,
    EVT_REACT_WINDOW_OPENED,
    EVT_REACT_WINDOW_CLOSED,
    EVT_PHASE_CHANGED,
    EVT_TURN_FLIPPED,
    EVT_TRIGGER_BLIP,
    EVT_PENDING_MODAL_OPENED,
    EVT_PENDING_MODAL_RESOLVED,
    EVT_FIZZLE,
    EVT_GAME_OVER,
})


# ---------------------------------------------------------------------------
# Default animation durations (ms)
# ---------------------------------------------------------------------------
#
# Client uses event-provided ``animation_duration_ms`` if set; falls back
# to this lookup. Values calibrated to existing game.js animation timings
# (Phase 14.7-09 turn banner = 1500ms, trigger blip ~900ms total, etc.).
# A zero-duration event is one whose visual is covered elsewhere
# (e.g. ``card_played`` is drawn by spell-stage from ``react_window_opened``).

DEFAULT_DURATION_MS: dict[str, int] = {
    EVT_MINION_SUMMONED: 600,
    EVT_MINION_DIED: 0,                 # covered by trigger_blip / hp_popup
    EVT_MINION_HP_CHANGE: 400,          # floating popup
    EVT_MINION_MOVED: 350,
    EVT_ATTACK_RESOLVED: 500,
    EVT_CARD_DRAWN: 350,
    EVT_CARD_PLAYED: 0,                 # covered by spell stage in/out
    EVT_CARD_DISCARDED: 300,
    EVT_MANA_CHANGE: 0,
    EVT_PLAYER_HP_CHANGE: 400,
    EVT_REACT_WINDOW_OPENED: 600,       # spell stage in
    EVT_REACT_WINDOW_CLOSED: 400,       # spell stage out
    EVT_PHASE_CHANGED: 0,
    EVT_TURN_FLIPPED: 1500,             # turn banner duration (matches game.css)
    EVT_TRIGGER_BLIP: 900,              # source pulse + center icon + target pulse
    EVT_PENDING_MODAL_OPENED: 0,        # gates queue, no fixed duration
    EVT_PENDING_MODAL_RESOLVED: 0,
    EVT_FIZZLE: 350,                    # optional puff
    EVT_GAME_OVER: 0,                   # game-over modal handles its own timing
}


# ---------------------------------------------------------------------------
# EngineEvent dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineEvent:
    """Single immutable event emitted by the engine.

    Fields:
        type: One of the ``EVT_*`` constants. Validated against
            ``ALL_EVENT_TYPES`` in ``EventStream.collect``.
        contract_source: The plan-01 contract source string that
            authorized the mutation (e.g. ``"trigger:on_play"``,
            ``"action:attack"``, ``"system:turn_flip"``,
            ``"sandbox:cheat_mana"``). Lets the client filter / route
            events without re-deriving causality.
        seq: Monotonic per-game sequence number. Plan 14.8-08 (deferred
            to Phase 15) uses this for reconnect/replay.
        payload: Arbitrary JSON-serializable dict. Schema per event type
            is defined client-side (plan 14.8-04a). Examples:
              - minion_summoned: {instance_id, card_numeric_id, position, owner_idx}
              - attack_resolved: {attacker_id, defender_id, attacker_dmg,
                                  defender_dmg, attacker_killed, defender_killed}
              - mana_change: {player_idx, prev, new, delta}
        animation_duration_ms: Hint for the client's eventQueue scheduler.
            Defaults to ``DEFAULT_DURATION_MS[type]`` when not provided
            to ``collect``. 0 means "no time gate" (event applied
            instantly or visualization handled elsewhere).
        triggered_by_seq: Parent event's seq. Set when the event was
            emitted inside a ``push_parent`` / ``pop_parent`` block
            (e.g. ON_DAMAGED triggers spawned by an ATTACK event are
            tagged with the attack's seq). None for top-level events.
        requires_decision: True when the event opens a UI modal that
            BLOCKS subsequent event processing until resolved by a
            user-submitted action (TUTOR_SELECT, DEATH_TARGET_PICK,
            etc.). The client's eventQueue stops draining at a
            ``requires_decision=True`` event until the corresponding
            ``EVT_PENDING_MODAL_RESOLVED`` arrives.
    """
    type: str
    contract_source: str
    seq: int
    payload: dict
    animation_duration_ms: int = 0
    triggered_by_seq: Optional[int] = None
    requires_decision: bool = False

    def to_dict(self) -> dict:
        """Serialize to a JSON-native dict for socket emission.

        Keep field names verbatim — the client (plan 14.8-04a) consumes
        the same shape. ``payload`` is passed through as-is (caller's
        responsibility to ensure JSON-serializability).
        """
        return {
            "type": self.type,
            "contract_source": self.contract_source,
            "seq": self.seq,
            "payload": self.payload,
            "animation_duration_ms": self.animation_duration_ms,
            "triggered_by_seq": self.triggered_by_seq,
            "requires_decision": self.requires_decision,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EngineEvent":
        """Inverse of ``to_dict`` for round-trip testing / replay."""
        return cls(
            type=d["type"],
            contract_source=d["contract_source"],
            seq=d["seq"],
            payload=d["payload"],
            animation_duration_ms=d.get("animation_duration_ms", 0),
            triggered_by_seq=d.get("triggered_by_seq"),
            requires_decision=d.get("requires_decision", False),
        )


# ---------------------------------------------------------------------------
# EventStream collector
# ---------------------------------------------------------------------------


@dataclass
class EventStream:
    """Append-only event collector handed into ``resolve_action``.

    Owned by the SESSION (plan 14.8-03b). Each ``resolve_action`` call
    receives a fresh stream seeded with the session's persistent
    ``next_event_seq`` field; after the call returns, the session
    persists ``stream.next_seq`` back. This keeps seq monotonic across
    the entire game lifetime, not just per-call.

    Usage::

        stream = EventStream(next_seq=session.next_event_seq)
        new_state = resolve_action(state, action, library, event_collector=stream)
        session.next_event_seq = stream.next_seq
        for ev in stream.events:
            socket.emit("engine_event", ev.to_dict())

    Inline-trigger nesting (research pitfall #4)::

        attack_ev = stream.collect(EVT_ATTACK_RESOLVED, ...)
        stream.push_parent(attack_ev.seq)
        try:
            # Resolve ON_DAMAGED triggers; their events get
            # triggered_by_seq=attack_ev.seq automatically.
            state = resolve_effects_for_trigger(...)
        finally:
            stream.pop_parent()

    Defaults: ``next_seq=0`` so a brand-new EventStream starts at seq 0.
    Plan 14.8-03b's session bootstrapping initializes
    ``next_event_seq=0`` on session create.
    """
    next_seq: int = 0
    events: list[EngineEvent] = field(default_factory=list)
    # Stack of parent seqs for inline-trigger nesting. Populated via
    # ``push_parent`` / ``pop_parent``; consulted by ``collect`` to fill
    # ``triggered_by_seq`` automatically.
    _parent_seq_stack: list[int] = field(default_factory=list)

    def collect(
        self,
        type: str,
        contract_source: str,
        payload: dict,
        *,
        animation_duration_ms: Optional[int] = None,
        requires_decision: bool = False,
    ) -> EngineEvent:
        """Append an event to the stream and return it.

        Args:
            type: One of the ``EVT_*`` constants. ``AssertionError``
                raised on unknown values to catch typos at test time.
            contract_source: Plan-01 contract source (e.g.
                ``"trigger:on_death"``). Caller passes the same source
                they pass to ``assert_phase_contract`` so events and
                contract violations correlate by source.
            payload: JSON-serializable dict. Schema per event type is
                client-defined.
            animation_duration_ms: Override for the per-event default.
                None → look up ``DEFAULT_DURATION_MS[type]``.
            requires_decision: True when this event blocks the client's
                event queue until a corresponding RESOLVED event arrives.

        Returns:
            The newly-created EngineEvent (also appended to ``events``).
        """
        assert type in ALL_EVENT_TYPES, (
            f"Unknown event type: {type!r} — must be one of ALL_EVENT_TYPES"
        )
        if animation_duration_ms is None:
            animation_duration_ms = DEFAULT_DURATION_MS[type]
        triggered_by = (
            self._parent_seq_stack[-1] if self._parent_seq_stack else None
        )
        ev = EngineEvent(
            type=type,
            contract_source=contract_source,
            seq=self.next_seq,
            payload=payload,
            animation_duration_ms=animation_duration_ms,
            triggered_by_seq=triggered_by,
            requires_decision=requires_decision,
        )
        self.events.append(ev)
        self.next_seq += 1
        return ev

    def push_parent(self, seq: int) -> None:
        """Begin a nested-trigger scope. Subsequent ``collect`` calls get
        ``triggered_by_seq=seq`` until ``pop_parent`` rebalances the stack.

        Use a try/finally pattern so an exception inside the nested call
        doesn't leak the parent into unrelated subsequent emissions.
        """
        self._parent_seq_stack.append(seq)

    def pop_parent(self) -> None:
        """Exit the most recent nested-trigger scope. Pairs with
        ``push_parent`` — call exactly once per push.
        """
        self._parent_seq_stack.pop()

    def to_dict_list(self) -> list[dict]:
        """Serialize all collected events. Convenience for socket fanout."""
        return [e.to_dict() for e in self.events]


__all__ = [
    # Event type constants
    "EVT_MINION_SUMMONED",
    "EVT_MINION_DIED",
    "EVT_MINION_HP_CHANGE",
    "EVT_MINION_MOVED",
    "EVT_ATTACK_RESOLVED",
    "EVT_CARD_DRAWN",
    "EVT_CARD_PLAYED",
    "EVT_CARD_DISCARDED",
    "EVT_MANA_CHANGE",
    "EVT_PLAYER_HP_CHANGE",
    "EVT_REACT_WINDOW_OPENED",
    "EVT_REACT_WINDOW_CLOSED",
    "EVT_PHASE_CHANGED",
    "EVT_TURN_FLIPPED",
    "EVT_TRIGGER_BLIP",
    "EVT_PENDING_MODAL_OPENED",
    "EVT_PENDING_MODAL_RESOLVED",
    "EVT_FIZZLE",
    "EVT_GAME_OVER",
    # Tables
    "ALL_EVENT_TYPES",
    "DEFAULT_DURATION_MS",
    # Classes
    "EngineEvent",
    "EventStream",
]
