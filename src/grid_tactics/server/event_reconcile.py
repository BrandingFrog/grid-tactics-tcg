"""React-window open/close event balancing at the emission boundary.

Phase 14.8 fix (spell-stage chain leak): three engine paths in
``react_stack.resolve_react_stack`` close a react window WITHOUT emitting
``EVT_REACT_WINDOW_CLOSED``:

  * the pending_tutor / pending_revive hand-off (react window closes, a
    modal takes over),
  * the drain-recheck path (the closing window is replaced by a NEW window
    opened by ``drain_pending_trigger_queue``, which emits a fresh
    ``EVT_REACT_WINDOW_OPENED`` but no CLOSED for the old one),
  * the melee pending_post_move early return.

The client tracks a ``spellStageChain`` that pushes one entry per OPENED
event and pops one per CLOSED event; every unbalanced open leaks a chain
entry, ``isSpellStageAnimating()`` then returns true forever, and all
board/hand input is gated off — a permanent soft-lock.

Rather than patching each engine path individually (and hoping no future
path regresses), the server reconciles at the emission boundary: after a
full action / auto-advance chain resolves, compare the OPENED/CLOSED
counts in the collected event stream against the ACTUAL window-open delta
between the pre-action and post-chain states, and append synthetic CLOSED
events to balance. Server-side react windows never nest (at most one is
open at any time), so the count comparison is exact.

Synthetic events are APPENDED (never inserted mid-stream) because the
client enforces strictly-increasing ``seq`` in arrival order — a
mid-stream insert with a later seq would cause every subsequent original
event to be dropped as out-of-order. Appending is safe: chain entries are
opaque counters client-side, so popping "the newest" entry instead of
"the replaced" entry has the same net effect.

The inverse imbalance (a window opened without an OPENED event, e.g. the
post-move ATTACK resume window) is deliberately NOT compensated: the
client's ``playReactWindowClosed`` guards against chain underflow, so the
eventual unmatched CLOSED is harmless, whereas a synthetic OPENED would
push a phantom spell-stage entry.
"""
from __future__ import annotations

from grid_tactics.engine_events import (
    EVT_REACT_WINDOW_CLOSED,
    EVT_REACT_WINDOW_OPENED,
    EventStream,
)
from grid_tactics.enums import TurnPhase


def _react_window_open(state) -> int:
    """1 if the state has a live react window, else 0.

    A window is "live" only when phase is REACT AND a react player is
    assigned — a wedged phase=REACT/react_player_idx=None state has no
    actionable window and counts as closed.
    """
    return (
        1
        if (
            state.phase == TurnPhase.REACT
            and state.react_player_idx is not None
        )
        else 0
    )


def reconcile_react_window_events(prev_state, new_state, stream: EventStream) -> int:
    """Append synthetic EVT_REACT_WINDOW_CLOSED events so opens balance closes.

    Args:
        prev_state: GameState snapshot from BEFORE the user action resolved.
        new_state: GameState after the full action + auto-advance chain.
        stream: The EventStream that collected the chain's events. Synthetic
            closes are appended via ``stream.collect`` so they get fresh,
            monotonically-increasing seq numbers.

    Returns:
        The number of synthetic CLOSED events appended (0 when balanced).
    """
    opened = sum(1 for ev in stream.events if ev.type == EVT_REACT_WINDOW_OPENED)
    closed = sum(1 for ev in stream.events if ev.type == EVT_REACT_WINDOW_CLOSED)
    expected_delta = _react_window_open(new_state) - _react_window_open(prev_state)
    surplus = (opened - closed) - expected_delta
    appended = 0
    while appended < surplus:
        stream.collect(
            EVT_REACT_WINDOW_CLOSED,
            "system:close_react_window",
            {
                "return_phase": (
                    new_state.phase.name if new_state.phase is not None else None
                ),
                "synthetic": True,
            },
            # Zero duration: the visual close (if the stage is up) is paced
            # client-side by the LIFO resolve, not by this event.
            animation_duration_ms=0,
        )
        appended += 1
    return appended
