"""Single-tab manual game state editor for Sandbox Mode (Phase 14.6).

SandboxSession is a thin per-tab harness around the existing immutable game
engine. It NEVER duplicates rule logic — every "rule-driven" mutation goes
through ``resolve_action`` (validated by ``legal_actions``), and every
"scratch-pad" mutation rebuilds the frozen ``Player`` and ``GameState`` via
``dataclasses.replace``.

Responsibilities (Phase 14.6 scope):
  * Hold a GameState + undo/redo deques + the shared CardLibrary
  * Apply real engine actions via ``apply_action``
  * Manually edit the five card zones (DEV-02 / DEV-03)
  * Cheat player fields (current_mana / max_mana / hp) — full god mode (DEV-06)
  * Toggle the active player (DEV-05)
  * Import a saved deck into a player's deck zone (DEV-03)
  * Undo / redo at least 50 prior states (DEV-09, HISTORY_MAX >= 50)
  * Client-side save/load via to_dict / load_dict (DEV-07)
  * Server-side named save slots under data/sandbox_saves/<slot>.json (DEV-08)

Non-responsibilities:
  * No new state classes, no parallel engine, no in-place mutation
  * No RNG attribute — sandbox is a deterministic scratch space; any randomness
    comes from the engine calls themselves when applicable
  * No schema migration — slot files store the exact ``GameState.to_dict`` shape
  * No multi-user sharing — one sandbox per browser tab, keyed by socket SID
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from grid_tactics.actions import Action, pass_action
from grid_tactics.action_resolver import resolve_action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import CardType
from grid_tactics.engine_events import (
    EVT_CARD_DISCARDED,
    EVT_CARD_DRAWN,
    EVT_MANA_CHANGE,
    EVT_MINION_SUMMONED,
    EVT_PHASE_CHANGED,
    EVT_PLAYER_HP_CHANGE,
    EngineEvent,
    EventStream,
)
from grid_tactics.enums import ActionType, PlayerSide, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player

# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

HISTORY_MAX = 64  # >= 50 per DEV-09; deque drops oldest on overflow
SLOT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
SLOT_DIR = Path("data/sandbox_saves")  # relative to project root
ZONES = ("hand", "deck_top", "deck_bottom", "graveyard", "exhaust")
PLAYER_FIELDS = ("current_mana", "max_mana", "hp")


# ---------------------------------------------------------------------------
# SandboxSession
# ---------------------------------------------------------------------------


class SandboxSession:
    """Single-tab manual game state editor. Wraps the existing engine; never duplicates it.

    State invariant: every public mutator pushes the OLD state onto ``_undo``
    before advancing ``_state``. ``_redo`` is cleared on any non-undo/redo
    mutation. Undo/redo operate on whole-state snapshots (immutable
    ``GameState`` references) so no surgery is needed for mid-react /
    mid-tutor / mid-pending positions.

    The sandbox is god-mode scratch space — there is NO RNG stored on the
    session. Every state-mutating helper rebuilds the immutable ``Player`` and
    ``GameState`` via ``dataclasses.replace``; there are NO parallel state
    classes, NO copies of engine code, NO in-place mutation.
    """

    def __init__(self, library: CardLibrary, sid: str):
        self.library = library
        self.sid = sid
        self._state: GameState = self._empty_state()
        self._active_view_idx: int = 0
        self._undo: deque[GameState] = deque(maxlen=HISTORY_MAX)
        self._redo: deque[GameState] = deque(maxlen=HISTORY_MAX)
        self.lock = threading.Lock()
        # Snapshot of (prev_state, action) from the most recent apply_action
        # call. Consumed by the sandbox emit path to enrich `last_action`
        # onto the wire payload so the client can drive sacrifice/attack/
        # move animations the same way real multiplayer does.
        self._last_prev_state: GameState | None = None
        self._last_action: Action | None = None
        # Phase 14.8-03b (M3): monotonic event seq for this sandbox
        # session. Each EventStream constructed by apply_action /
        # apply_sandbox_edit seeds from this counter and writes
        # stream.next_seq back when finished. Reset to 0 on reset() and
        # on load_dict() so loaded saves start fresh from the client's
        # POV. See SUMMARY for the contract.
        self._next_event_seq: int = 0

    # ------------------------------------------------------------------
    # Empty starting state (does NOT call GameState.new_game)
    # ------------------------------------------------------------------

    @classmethod
    def _empty_state(cls) -> GameState:
        """Build an empty starting GameState without touching ``new_game``.

        ``GameState.new_game`` unconditionally draws the starting hands via
        ``Player.draw_card``, which raises on an empty deck. The sandbox
        starts with both players holding zero cards everywhere, so we
        construct the frozen dataclasses directly.
        """
        p1 = Player.new(PlayerSide.PLAYER_1, ())
        p2 = Player.new(PlayerSide.PLAYER_2, ())
        return GameState(
            board=Board.empty(),
            players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=1,
            seed=0,
        )

    # ------------------------------------------------------------------
    # Public read-only properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def active_view_idx(self) -> int:
        return self._active_view_idx

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

    @property
    def last_prev_state(self) -> GameState | None:
        """Pre-action snapshot from the most recent apply_action (or None).

        Cleared to None on undo/redo and on any non-action mutation so stale
        last_action payloads never bleed into unrelated frames (zone edits,
        cheat toggles, save/load).
        """
        return self._last_prev_state

    @property
    def last_action(self) -> Action | None:
        """Most recently applied engine action (or None)."""
        return self._last_action

    # ------------------------------------------------------------------
    # Mutation primitives
    # ------------------------------------------------------------------

    def _push_undo(self) -> None:
        """Push current state onto undo stack and clear redo (on new mutation).

        Also clears the cached last_action/last_prev_state pair so zone edits,
        cheat toggles, and other non-engine mutations don't leave a stale
        engine action sitting around — the next emit would otherwise replay
        the previous SACRIFICE/ATTACK animation on top of e.g. a mana change.
        ``apply_action`` re-populates the pair immediately after calling this.
        """
        self._undo.append(self._state)
        self._redo.clear()
        self._last_prev_state = None
        self._last_action = None

    def _replace_player(self, player_idx: int, new_player: Player) -> None:
        """Swap ``players[idx]`` in ``self._state`` via ``dataclasses.replace``."""
        if player_idx == 0:
            new_players = (new_player, self._state.players[1])
        else:
            new_players = (self._state.players[0], new_player)
        self._state = replace(self._state, players=new_players)

    def apply_action(
        self,
        action: Action,
        on_frame: Optional[Callable[[], None]] = None,
    ) -> list[EngineEvent]:
        """Validate via ``legal_actions``, apply via ``resolve_action``.

        Returns the list of EngineEvents emitted across the entire call
        (the user action plus every drained auto-PASS). The server
        ``sandbox_apply_action`` handler fans these out via the new
        ``engine_events`` Socket.IO message; the legacy snapshot
        (``sandbox_state``) is still emitted alongside for back-compat
        with pre-04a clients.

        Raises ``ValueError("Illegal action")`` if the action is not present
        in the current legal-actions tuple.

        Auto-drain for trivial react windows: in real multiplayer the non-
        active player's client auto-passes empty react windows (see
        ``renderActionBar`` in ``game.js`` around the ``gameState.phase === 1
        && legalActions.length === 1`` block). Sandbox has only one human
        driving god view with ``active_view_idx`` pinned to ``0``, so when a
        PLAY_CARD / ATTACK / SACRIFICE opens a react window and the opponent
        has no legal react cards, nothing in the UI can issue the required
        PASS and the session silently "hangs" in REACT phase from the user's
        POV. Mirror the multiplayer auto-skip here: while the state is in
        REACT phase AND the only legal action is PASS, keep resolving PASS
        until we're back in ACTION (or a pending gate). Legal react branches
        (opponent has a react card they can actually play) are preserved so
        the user can still exercise them.

        Phase 14.8-03b (M3 + decommission per-frame hack): a single
        ``EventStream`` is constructed for the whole call, seeded from
        ``self._next_event_seq``. Both the user action and every drained
        PASS thread the same stream into ``resolve_action``, so the
        client receives ONE ``engine_events`` payload per call rather
        than one per intermediate frame. This eliminates the per-frame
        re-emit hack from commit 9c414f9 while still preserving pacing —
        the client uses ``animation_duration_ms`` on each event as its
        timing source instead of socket-frame cadence. After the call
        returns, ``stream.next_seq`` is written back to
        ``self._next_event_seq`` so the next call's seq numbers continue
        monotonically.

        ``on_frame`` is preserved as a back-compat shim for any caller
        that still uses the legacy per-frame emit pattern (most notably
        existing tests that may rely on intermediate-state visibility).
        New callers should pass ``None`` and consume the returned event
        list instead.
        """
        valid = legal_actions(self._state, self.library)
        if action not in valid:
            raise ValueError("Illegal action")
        self._push_undo()
        # Snapshot the pre-action state BEFORE resolve so the emit path can
        # populate `last_action.attacker_pos` from the pre-action minion
        # positions (mirrors real multiplayer's _emit_state_to_players,
        # which passes prev_state + resolved_action into enrich_last_action).
        self._last_prev_state = self._state
        self._last_action = action
        # Phase 14.8-03b (M3): one EventStream per apply_action call,
        # seeded from the persistent counter, threaded through every
        # resolve_action including drained PASSes. Stream.next_seq is
        # written back at end so subsequent calls keep monotonic seq.
        stream = EventStream(next_seq=self._next_event_seq)
        self._state = resolve_action(
            self._state, action, self.library, event_collector=stream,
        )
        if on_frame is not None:
            on_frame()
        # Drain trivial react windows — empty hand / no reactive cards means
        # the only legal action is PASS. Bounded by an attempt counter so a
        # pathological engine state can never spin forever.
        for _ in range(16):
            if self._state.phase != TurnPhase.REACT:
                break
            react_legals = legal_actions(self._state, self.library)
            if len(react_legals) != 1:
                break
            only = react_legals[0]
            if only.action_type != ActionType.PASS:
                break
            # Update prev/action so each drained frame's enrich_last_action
            # sees the CURRENT prev_state (the just-emitted frame) paired
            # with a PASS action — no animation, no attacker_pos, just a
            # transparent state delta. Phase 14.8-05: trigger-blip transitions
            # now flow through EVT_TRIGGER_BLIP in the event stream, not a
            # transient state field.
            self._last_prev_state = self._state
            self._last_action = pass_action()
            self._state = resolve_action(
                self._state, pass_action(), self.library, event_collector=stream,
            )
            if on_frame is not None:
                on_frame()

        # Auto-follow active player: after each action, sync the sandbox
        # view to whoever's turn it is so the user always controls the
        # active player without needing to manually toggle.
        self._active_view_idx = self._state.active_player_idx
        # M3: persist the new seq counter back to the session so the
        # next apply_action / apply_sandbox_edit picks up where we left
        # off. Plan 04b's client-side lastSeenSeq dedup depends on this.
        self._next_event_seq = stream.next_seq
        return list(stream.events)

    # ------------------------------------------------------------------
    # Zone editing (DEV-02 / DEV-03)
    # ------------------------------------------------------------------

    def add_card_to_zone(
        self, player_idx: int, card_numeric_id: int, zone: str
    ) -> None:
        """Insert a card into one of five zones for a player.

        ``zone`` in ``{"hand", "deck_top", "deck_bottom", "graveyard", "exhaust"}``.
        ``deck_top`` means index 0 (next-draw side) of ``Player.deck``;
        ``deck_bottom`` means appended to the end.
        Uses ONLY ``dataclasses.replace`` — no in-place mutation, no new classes.
        """
        if player_idx not in (0, 1):
            raise ValueError("player_idx must be 0 or 1")
        if not (0 <= card_numeric_id < self.library.card_count):
            raise ValueError("unknown card_numeric_id")
        if zone not in ZONES:
            raise ValueError(f"zone must be one of {ZONES}")
        self._push_undo()
        old_player = self._state.players[player_idx]
        cid = card_numeric_id
        if zone == "hand":
            new_player = replace(old_player, hand=old_player.hand + (cid,))
        elif zone == "deck_top":
            new_player = replace(old_player, deck=(cid,) + old_player.deck)
        elif zone == "deck_bottom":
            new_player = replace(old_player, deck=old_player.deck + (cid,))
        elif zone == "graveyard":
            new_player = replace(old_player, grave=old_player.grave + (cid,))
        else:  # exhaust
            new_player = replace(old_player, exhaust=old_player.exhaust + (cid,))
        self._replace_player(player_idx, new_player)

    def move_card_between_zones(
        self,
        player_idx: int,
        card_numeric_id: int,
        src_zone: str,
        dst_zone: str,
    ) -> None:
        """Move a card already in ``src_zone`` to ``dst_zone`` for the same player.

        Removes the FIRST occurrence of ``card_numeric_id`` from ``src_zone``
        and inserts it into ``dst_zone`` (``deck_top`` prepends,
        ``deck_bottom`` appends). Raises ``ValueError`` if the card isn't in
        ``src_zone``.
        """
        if player_idx not in (0, 1):
            raise ValueError("player_idx must be 0 or 1")
        if src_zone not in ZONES or dst_zone not in ZONES:
            raise ValueError(f"zones must be one of {ZONES}")
        old_player = self._state.players[player_idx]

        # Map zone -> attribute name on Player. deck_top and deck_bottom both
        # target Player.deck; the difference is which end we operate on.
        def _attr_for_zone(z: str) -> str:
            if z in ("deck_top", "deck_bottom"):
                return "deck"
            if z == "graveyard":
                return "grave"
            return z  # hand or exhaust

        src_attr = _attr_for_zone(src_zone)
        src_tuple = getattr(old_player, src_attr)
        if card_numeric_id not in src_tuple:
            raise ValueError(
                f"Card {card_numeric_id} not in {src_zone}: {src_tuple}"
            )

        # Build new src tuple with FIRST occurrence removed
        idx_in_src = src_tuple.index(card_numeric_id)
        new_src_tuple = src_tuple[:idx_in_src] + src_tuple[idx_in_src + 1 :]

        self._push_undo()
        # Apply src removal
        intermediate = replace(old_player, **{src_attr: new_src_tuple})

        # Apply dst insert
        cid = card_numeric_id
        if dst_zone == "hand":
            new_player = replace(intermediate, hand=intermediate.hand + (cid,))
        elif dst_zone == "deck_top":
            new_player = replace(intermediate, deck=(cid,) + intermediate.deck)
        elif dst_zone == "deck_bottom":
            new_player = replace(intermediate, deck=intermediate.deck + (cid,))
        elif dst_zone == "graveyard":
            new_player = replace(intermediate, grave=intermediate.grave + (cid,))
        else:  # exhaust
            new_player = replace(
                intermediate, exhaust=intermediate.exhaust + (cid,)
            )
        self._replace_player(player_idx, new_player)

    def place_on_board(
        self, player_idx: int, card_numeric_id: int, row: int, col: int
    ) -> None:
        """Place a minion directly onto the board at (row, col).

        Creates a fresh MinionInstance owned by ``player_idx`` and places it
        on the board. Only minion-type cards are allowed. Raises ValueError
        if the cell is occupied or the card is not a minion.
        """
        if player_idx not in (0, 1):
            raise ValueError("player_idx must be 0 or 1")
        if not (0 <= card_numeric_id < self.library.card_count):
            raise ValueError("unknown card_numeric_id")
        card_def = self.library.get_by_id(card_numeric_id)
        if card_def.card_type != CardType.MINION:
            raise ValueError("Only minion cards can be placed on the board")
        if self._state.board.get(row, col) is not None:
            raise ValueError(f"Cell ({row}, {col}) is already occupied")
        self._push_undo()
        mid = self._state.next_minion_id
        side = PlayerSide.PLAYER_1 if player_idx == 0 else PlayerSide.PLAYER_2
        minion = MinionInstance(
            instance_id=mid,
            card_numeric_id=card_numeric_id,
            owner=side,
            position=(row, col),
            current_health=card_def.health,
        )
        new_board = self._state.board.place(row, col, mid)
        self._state = replace(
            self._state,
            board=new_board,
            minions=self._state.minions + (minion,),
            next_minion_id=mid + 1,
        )

    def import_deck(self, player_idx: int, deck_card_ids: list[int]) -> None:
        """Replace a player's deck with the provided list of numeric card IDs.

        Reuses ``CardLibrary.card_count`` for ID validation. Empties the
        existing deck completely (does NOT append). Other zones are untouched.
        """
        if player_idx not in (0, 1):
            raise ValueError("player_idx must be 0 or 1")
        validated: list[int] = []
        for cid in deck_card_ids:
            cid_int = int(cid)
            if not (0 <= cid_int < self.library.card_count):
                raise ValueError(f"unknown card_numeric_id {cid_int}")
            validated.append(cid_int)
        self._push_undo()
        old_player = self._state.players[player_idx]
        new_player = replace(old_player, deck=tuple(validated))
        self._replace_player(player_idx, new_player)

    # ------------------------------------------------------------------
    # Cheat inputs (DEV-06)
    # ------------------------------------------------------------------

    def set_player_field(self, player_idx: int, field: str, value: int) -> None:
        """Cheat: set ``current_mana`` / ``max_mana`` / ``hp`` on a player to ANY integer.

        FULL CHEAT MODE — there is NO validation against game rules. Setting
        ``hp`` to ``-50`` or ``current_mana`` to ``9999`` is allowed. The
        engine will see whatever is set the next time an action is applied.
        """
        if player_idx not in (0, 1):
            raise ValueError("player_idx must be 0 or 1")
        if field not in PLAYER_FIELDS:
            raise ValueError(f"field must be one of {PLAYER_FIELDS}")
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            raise ValueError("value must be an integer")
        self._push_undo()
        old_player = self._state.players[player_idx]
        new_player = replace(old_player, **{field: int_value})
        self._replace_player(player_idx, new_player)

    # ------------------------------------------------------------------
    # Active player toggle (DEV-05)
    # ------------------------------------------------------------------

    def set_active_player(self, player_idx: int) -> None:
        """Mutate ``state.active_player_idx`` via ``dataclasses.replace``.

        This is a real ``GameState`` mutation — the next ``legal_actions``
        call will return the new active player's options. Engine-driven
        active-player transitions during react / pending-tutor still happen
        automatically inside ``resolve_action``; this method is for setting
        up scenarios manually.
        """
        if player_idx not in (0, 1):
            raise ValueError("player_idx must be 0 or 1")
        if (
            self._state.active_player_idx == player_idx
            and self._active_view_idx == player_idx
        ):
            return
        self._push_undo()
        self._state = replace(self._state, active_player_idx=player_idx)
        self._active_view_idx = player_idx

    # ------------------------------------------------------------------
    # Undo / redo / reset
    # ------------------------------------------------------------------

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._state)
        self._state = self._undo.pop()
        # Stepping back in history must not replay the last engine animation.
        self._last_prev_state = None
        self._last_action = None
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._state)
        self._state = self._redo.pop()
        self._last_prev_state = None
        self._last_action = None
        return True

    def reset(self) -> None:
        self._push_undo()
        self._state = self._empty_state()
        self._active_view_idx = 0
        # M3: a fresh empty state means the client should treat this as
        # a brand-new session — reset the monotonic event seq counter so
        # subsequent edits start at seq 0 again.
        self._next_event_seq = 0

    # ------------------------------------------------------------------
    # Serialization (delegates entirely to GameState)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "state": self._state.to_dict(),
            "active_view_idx": self._active_view_idx,
        }

    def load_dict(self, payload: dict) -> None:
        new_state = GameState.from_dict(payload["state"])
        self._state = new_state
        self._active_view_idx = int(payload.get("active_view_idx", 0))
        self._undo.clear()
        self._redo.clear()
        self._last_prev_state = None
        self._last_action = None
        # M3: load is a hard state replacement — reset seq so the
        # downstream client renders the loaded snapshot from scratch.
        self._next_event_seq = 0

    def legal_actions(self) -> tuple:
        return legal_actions(self._state, self.library)

    # ------------------------------------------------------------------
    # Sandbox edit event emission (Phase 14.8-03b)
    # ------------------------------------------------------------------

    def apply_sandbox_edit(self, verb: str, payload: dict) -> list[EngineEvent]:
        """Apply a sandbox-only edit and emit events for it.

        Per orchestrator decision #5: sandbox cheats / undo / redo /
        set_active / save / load / add_card_to_zone / move_card_between_zones
        all flow through the same EventStream pipeline as engine actions.
        Each event carries ``contract_source=f"sandbox:{verb}"`` — the
        ``sandbox:`` prefix bypasses phase-contract assertions per
        plan 14.8-01 but the wire format stays uniform so the client
        uses ONE rendering pipeline.

        ``verb`` is the canonical action verb (e.g. ``cheat_mana``,
        ``cheat_hp``, ``set_active``, ``undo``, ``redo``, ``reset``,
        ``add_card_to_zone``, ``move_card_between_zones``,
        ``place_on_board``, ``import_deck``, ``load``, ``load_slot``).
        ``payload`` carries verb-specific fields (player_idx, value,
        zone, etc.). Each verb maps to one or more event types; verbs
        without a natural per-field event (e.g. ``undo``, ``load``)
        emit a single ``phase_changed`` event tagged with the sandbox
        source so the client can drive a generic "state replaced" hook.

        Returns the list of EngineEvents emitted. Mutates state via the
        existing primitive helpers (no duplicate logic).
        """
        stream = EventStream(next_seq=self._next_event_seq)
        source = f"sandbox:{verb}"

        # Capture pre-edit snapshot so cheat verbs can compute deltas.
        prev_state = self._state

        if verb == "cheat_mana":
            player_idx = int(payload["player_idx"])
            field = str(payload.get("field", "current_mana"))
            value = int(payload["value"])
            self.set_player_field(player_idx, field, value)
            new_value = getattr(self._state.players[player_idx], field)
            stream.collect(
                EVT_MANA_CHANGE,
                source,
                {
                    "player_idx": player_idx,
                    "field": field,
                    "prev": int(getattr(prev_state.players[player_idx], field)),
                    "new": int(new_value),
                },
            )
        elif verb == "cheat_hp":
            player_idx = int(payload["player_idx"])
            value = int(payload["value"])
            self.set_player_field(player_idx, "hp", value)
            stream.collect(
                EVT_PLAYER_HP_CHANGE,
                source,
                {
                    "player_idx": player_idx,
                    "prev": int(prev_state.players[player_idx].hp),
                    "new": int(self._state.players[player_idx].hp),
                },
            )
        elif verb == "set_active":
            player_idx = int(payload["player_idx"])
            self.set_active_player(player_idx)
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {
                    "active_player_idx": player_idx,
                    "phase": int(self._state.phase),
                },
            )
        elif verb == "add_card_to_zone":
            player_idx = int(payload["player_idx"])
            card_numeric_id = int(payload["card_numeric_id"])
            zone = str(payload["zone"])
            self.add_card_to_zone(player_idx, card_numeric_id, zone)
            # Map zone → event type. hand → CARD_DRAWN-shaped (it's a
            # gain), graveyard → CARD_DISCARDED-shaped, others → DRAWN
            # (closest semantic for "card appears in zone").
            evt_type = (
                EVT_CARD_DISCARDED if zone == "graveyard" else EVT_CARD_DRAWN
            )
            stream.collect(
                evt_type,
                source,
                {
                    "player_idx": player_idx,
                    "card_numeric_id": card_numeric_id,
                    "zone": zone,
                },
            )
        elif verb == "move_card_between_zones":
            player_idx = int(payload["player_idx"])
            card_numeric_id = int(payload["card_numeric_id"])
            src_zone = str(payload["src_zone"])
            dst_zone = str(payload["dst_zone"])
            self.move_card_between_zones(
                player_idx, card_numeric_id, src_zone, dst_zone,
            )
            stream.collect(
                EVT_CARD_DISCARDED if dst_zone == "graveyard" else EVT_CARD_DRAWN,
                source,
                {
                    "player_idx": player_idx,
                    "card_numeric_id": card_numeric_id,
                    "src_zone": src_zone,
                    "dst_zone": dst_zone,
                },
            )
        elif verb == "place_on_board":
            player_idx = int(payload["player_idx"])
            card_numeric_id = int(payload["card_numeric_id"])
            row = int(payload["row"])
            col = int(payload["col"])
            self.place_on_board(player_idx, card_numeric_id, row, col)
            # The just-placed minion is the last entry in the tuple.
            placed = self._state.minions[-1] if self._state.minions else None
            stream.collect(
                EVT_MINION_SUMMONED,
                source,
                {
                    "player_idx": player_idx,
                    "card_numeric_id": card_numeric_id,
                    "instance_id": int(placed.instance_id) if placed else None,
                    "position": [row, col],
                },
            )
        elif verb == "import_deck":
            player_idx = int(payload["player_idx"])
            deck = list(payload["deck_card_ids"])
            self.import_deck(player_idx, deck)
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {
                    "player_idx": player_idx,
                    "deck_size": len(deck),
                },
            )
        elif verb == "undo":
            self.undo()
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {"phase": int(self._state.phase), "verb": "undo"},
            )
        elif verb == "redo":
            self.redo()
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {"phase": int(self._state.phase), "verb": "redo"},
            )
        elif verb == "reset":
            self.reset()
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {"phase": int(self._state.phase), "verb": "reset"},
            )
        elif verb == "load":
            self.load_dict(payload["payload"])
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {"phase": int(self._state.phase), "verb": "load"},
            )
        elif verb == "load_slot":
            self.load_from_slot(str(payload["slot_name"]))
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {
                    "phase": int(self._state.phase),
                    "verb": "load_slot",
                    "slot_name": str(payload["slot_name"]),
                },
            )
        elif verb == "save_slot":
            self.save_to_slot(str(payload["slot_name"]))
            # save is a side-effect-only verb (writes a file); still
            # emit one event so the client gets a uniform pipeline.
            stream.collect(
                EVT_PHASE_CHANGED,
                source,
                {
                    "phase": int(self._state.phase),
                    "verb": "save_slot",
                    "slot_name": str(payload["slot_name"]),
                },
            )
        elif verb == "set_player_field":
            # Generic cheat-field verb — covers set_player_field handler
            # which can target any of (current_mana, max_mana, hp).
            player_idx = int(payload["player_idx"])
            field = str(payload["field"])
            value = int(payload["value"])
            self.set_player_field(player_idx, field, value)
            evt_type = EVT_PLAYER_HP_CHANGE if field == "hp" else EVT_MANA_CHANGE
            stream.collect(
                evt_type,
                source,
                {
                    "player_idx": player_idx,
                    "field": field,
                    "prev": int(getattr(prev_state.players[player_idx], field)),
                    "new": int(getattr(self._state.players[player_idx], field)),
                },
            )
        else:
            raise ValueError(f"Unknown sandbox edit verb: {verb!r}")

        # Persist seq counter back so subsequent edits / actions stay
        # monotonic. Even single-event edits advance the counter.
        self._next_event_seq = stream.next_seq
        return list(stream.events)

    # ------------------------------------------------------------------
    # Server save slots (DEV-08)
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_slot_name(slot_name: str) -> str:
        """Validate via single regex + path-component identity check.

        Rejects path separators, traversal sequences, and anything outside
        ``[a-zA-Z0-9_-]{1,64}``. Returns the validated name unchanged.
        Raises ``ValueError`` on rejection.
        """
        if not isinstance(slot_name, str):
            raise ValueError("slot_name must be a string")
        if not SLOT_NAME_RE.match(slot_name):
            raise ValueError(
                "slot_name must be 1-64 chars of [a-zA-Z0-9_-]"
            )
        # Defensive belt-and-braces: filename must equal its basename.
        if os.path.basename(slot_name) != slot_name:
            raise ValueError("slot_name must not contain path separators")
        return slot_name

    @classmethod
    def _slot_path(cls, slot_name: str) -> Path:
        validated = cls._validate_slot_name(slot_name)
        SLOT_DIR.mkdir(parents=True, exist_ok=True)
        return SLOT_DIR / f"{validated}.json"

    def save_to_slot(self, slot_name: str) -> None:
        """Persist current state to ``data/sandbox_saves/<slot_name>.json``.

        Reuses ``to_dict()`` — NO new serialization format. Overwrites any
        existing file with the same slot name. Does NOT push undo (saving
        doesn't change game state).
        """
        path = self._slot_path(slot_name)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f)

    def load_from_slot(self, slot_name: str) -> None:
        """Load a slot file and restore via ``load_dict`` (clears undo/redo)."""
        path = self._slot_path(slot_name)
        if not path.exists():
            raise FileNotFoundError(f"Slot not found: {slot_name}")
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        self.load_dict(payload)

    @classmethod
    def list_slots(cls) -> list[str]:
        """Return sorted list of slot names (filenames without .json) in ``SLOT_DIR``.

        Skips files that don't match the slot-name regex (defensive: ignore
        any stray files a user may have dropped in the directory).
        """
        if not SLOT_DIR.exists():
            return []
        out: list[str] = []
        for entry in SLOT_DIR.iterdir():
            if entry.is_file() and entry.suffix == ".json":
                stem = entry.stem
                if SLOT_NAME_RE.match(stem):
                    out.append(stem)
        return sorted(out)

    @classmethod
    def delete_slot(cls, slot_name: str) -> bool:
        """Delete a slot file. Returns True if deleted, False if it didn't exist."""
        path = cls._slot_path(slot_name)
        if path.exists():
            path.unlink()
            return True
        return False
