"""Top-level GameState dataclass -- complete immutable game state snapshot.

Ties together Board (plan 02) and Player (plan 03) into a single frozen
dataclass representing the entire game at a point in time. All mutation
returns a new GameState via dataclasses.replace().
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from grid_tactics.actions import Action
from grid_tactics.board import Board
from grid_tactics.enums import PlayerSide, ReactContext, TurnPhase
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.rng import GameRNG
from grid_tactics.types import STARTING_HAND_P1, STARTING_HAND_P2


@dataclass(frozen=True, slots=True)
class PendingDeathWork:
    """A dead minion whose on_death effects have not yet been fully resolved.

    Captured snapshot of the dying minion at death time: the card_numeric_id
    drives effect lookup, owner determines "whose death effect this is" (for
    active-player-first ordering and for modal-prompt routing), and
    instance_id is the deterministic tiebreaker. The position is captured so
    that SELF_OWNER / position-relative effects can still resolve after the
    minion has been removed from the board.

    ``next_effect_idx`` records which effect on the card is next to fire. It
    advances past effects that have already resolved (including those that
    were resolved via a modal). Zero means "start from the beginning".
    """

    card_numeric_id: int
    owner: PlayerSide
    position: tuple[int, int]
    instance_id: int
    next_effect_idx: int = 0


@dataclass(frozen=True, slots=True)
class PendingDeathTarget:
    """A death-triggered effect waiting for a click-target modal pick.

    Currently the only shape that uses this is ``DESTROY / SINGLE_TARGET``
    (Lasercannon on_death) — the dying minion's owner picks an enemy minion
    to destroy. The schema intentionally carries enough information that
    future death-trigger modals (damage-single-target, buff-friendly, etc.)
    can be added without changing the state shape.

    Fields:
        card_numeric_id: The dying minion's card (for prompt text).
        owner_idx: Which player picks the target (0 or 1). ALWAYS the dying
            minion's owner — it's their card's effect.
        dying_instance_id: The dying minion's instance_id (for UI correlation).
        effect_idx: Which slot in the card's effects tuple this modal is for,
            so the drain logic can advance ``PendingDeathWork.next_effect_idx``.
        filter: Short string tag describing what the picker may click.
            Currently always "enemy_minion". Future: "friendly_minion",
            "any_minion", "empty_tile", etc.
    """

    card_numeric_id: int
    owner_idx: int
    dying_instance_id: int
    effect_idx: int
    filter: str = "enemy_minion"


@dataclass(frozen=True, slots=True)
class PendingTrigger:
    """A queued trigger effect waiting for resolution via priority picker.

    Phase 14.7-05: When multiple effects trigger at the same game-state
    moment (START_OF_TURN and END_OF_TURN in this plan; Death: migration
    lands in 14.7-05b), the turn player's effects ALL resolve before any
    non-turn-player effect resolves, and each player with 2+ simultaneous
    triggers picks resolution order via a modal.

    Fields:
        trigger_kind: "start_of_turn" | "end_of_turn" | "on_death" |
            "on_summon_effect" — determines how the source is rendered in
            the picker modal and which ReactContext the per-resolution
            react window carries.
        source_minion_id: None if the source minion is already dead
            (on_death case; 14.7-05b). For start/end-of-turn this is the
            living minion's instance_id.
        source_card_numeric_id: The card definition ID — used to look up
            the card's effects at resolution time and to render the full
            card face in the picker modal.
        effect_idx: Which effect index on the card this queue entry is
            for. A card with two simultaneous-trigger effects enqueues
            two PendingTrigger entries.
        owner_idx: 0 (Player 1) or 1 (Player 2) — whose queue this entry
            belongs to and who picks resolution order.
        captured_position: The minion's position at enqueue time. Used
            for SELF_OWNER targeting even if the minion has since moved
            or died. Fizzle (14.7-06) re-validates at resolution time.
        target_pos: Optional pre-captured target position for triggers
            that carry a target (rare for start/end; reserved for
            on-summon / on-death parity).
    """

    trigger_kind: str
    source_minion_id: Optional[int]
    source_card_numeric_id: int
    effect_idx: int
    owner_idx: int
    captured_position: tuple[int, int]
    target_pos: Optional[tuple[int, int]] = None


@dataclass(frozen=True, slots=True)
class GameState:
    """Complete immutable game state snapshot.

    All fields are frozen. Collections use tuples for true immutability.
    The RNG is NOT part of the state (it's mutable); it is passed separately.
    """

    board: Board
    players: tuple[Player, Player]
    active_player_idx: int
    phase: TurnPhase
    turn_number: int
    seed: int

    # Phase 3: Minion tracking
    minions: tuple[MinionInstance, ...] = ()  # all minions currently on the board
    next_minion_id: int = 0  # counter for unique IDs (per research Pitfall 1)

    # Phase 3: React window state
    react_stack: tuple = ()  # react chain state (will hold ReactEntry tuples in Plan 03)
    react_player_idx: Optional[int] = None  # whose turn to react (None = not in react window)
    pending_action: Optional[Action] = None  # action waiting for react resolution

    # Phase 14.7-02: 3-phase turn model. ``react_context`` tags WHY the
    # current REACT window is open (after an action, after a start-of-turn
    # trigger, before end-of-turn, etc.) so react_condition matching and
    # UI animations can branch on it. ``react_return_phase`` tells
    # resolve_react_stack WHERE to transition when the chain PASS-PASSes
    # out (START -> ACTION, ACTION -> advance turn via END, END -> next
    # turn's START). Both default None — set alongside phase=REACT at the
    # REACT-entry sites in action_resolver.py and (in 14.7-03) react_stack.
    react_context: Optional[ReactContext] = None
    react_return_phase: Optional[TurnPhase] = None

    # Phase 4: Win/draw detection
    winner: Optional[PlayerSide] = None  # which player won (None = no winner yet, or draw)
    is_game_over: bool = False  # True when game has ended (win or draw)

    # Phase 11: Fatigue tracking (moved from action_resolver module global)
    fatigue_counts: tuple[int, int] = (0, 0)  # (p0_pass_count, p1_pass_count)

    # Phase 14.1: Post-move attack-pick state for melee minions.
    # None = not in pending state. int = instance_id of the melee minion that
    # just moved and may now ATTACK an in-range enemy or DECLINE_POST_MOVE_ATTACK.
    pending_post_move_attacker_id: Optional[int] = None

    # Phase 14.2: Pending tutor-select state (on_play tutor effects).
    # When a card with a TUTOR effect resolves on_play and at least one
    # matching card exists in the caster's deck, we enter pending state and
    # the caster MUST TUTOR_SELECT a deck index or DECLINE_TUTOR. The single
    # react window for the play fires AFTER the pending clears.
    # Mutually exclusive with pending_post_move_attacker_id (asserted).
    pending_tutor_player_idx: Optional[int] = None      # Which player must pick
    pending_tutor_matches: tuple = ()                    # Deck indices of matching cards (in deck order)
    pending_tutor_is_conjure: bool = False               # True when tutor is for conjure-to-field (not hand)
    pending_tutor_remaining: int = 0                     # How many more picks before auto-close (Ratmobile amount=2 etc)
    # 2026-07 card-audit fix (Red Diodebot extra react window): WHERE the
    # pending tutor was opened from. "summon_effect" = a minion's on_summon
    # tutor (Window B already gave the opponent their react window, so the
    # TUTOR_SELECT / DECLINE_TUTOR resume must NOT open a third AFTER_ACTION
    # window — it routes straight to the Decay phase). Other values
    # ("magic_cast", "react", "trigger:*", None) keep the legacy resume path.
    pending_tutor_origin: Optional[str] = None

    # Pending revive-place state (revive effects from magic cards).
    # When a REVIVE effect fires, we enter pending state so the player can
    # choose WHERE to place each revived minion. One placement per
    # REVIVE_PLACE action; DECLINE_REVIVE stops early.
    pending_revive_player_idx: Optional[int] = None     # Which player is placing
    pending_revive_card_id: Optional[str] = None        # card_id to revive (e.g. "rat")
    pending_revive_remaining: int = 0                   # How many more placements allowed

    # Phase 14.6: Pending conjure-deploy state (conjure-to-field flow).
    # After TUTOR_SELECT resolves during a conjure (pending_tutor_is_conjure),
    # instead of adding the card to hand, we enter this state so the player
    # picks a deployment tile. The card is held here until CONJURE_DEPLOY
    # resolves it onto the board.
    pending_conjure_deploy_card: Optional[int] = None        # card_numeric_id to deploy
    pending_conjure_deploy_player_idx: Optional[int] = None  # Which player is deploying

    # Pending death-effect machinery (supports modal click-target death
    # triggers).
    #
    # Phase 14.8-05: ``pending_death_queue`` field DELETED. Since
    # Phase 14.7-05b the priority-queue path (PendingTrigger with
    # trigger_kind="on_death") has been the sole producer/consumer of
    # on_death effects; the legacy PendingDeathWork queue became a
    # defensive no-op and is now removed entirely alongside its callers
    # (_enqueue_dead_minions_and_cleanup_zones, _drain_pending_death_queue).
    # The PendingDeathWork dataclass itself is retained above for any
    # stale imports but is unreferenced in engine code.
    #
    # ``pending_death_target`` still gates click-target modal effects
    # (e.g. Lasercannon DESTROY/SINGLE_TARGET on_death) — while non-None,
    # the regular react window / turn-advance is deferred until the
    # owner submits DEATH_TARGET_PICK.
    pending_death_target: Optional["PendingDeathTarget"] = None

    # Phase 14.7-05: simultaneous-trigger priority queue + modal picker.
    # When multiple ON_START_OF_TURN / ON_END_OF_TURN effects fire at the
    # same moment, they ENQUEUE here instead of resolving inline. The
    # turn player's queue drains first (pending_trigger_queue_turn), then
    # the other player's (pending_trigger_queue_other). When either queue
    # has >=2 entries at drain time, pending_trigger_picker_idx is set to
    # that owner so the UI opens a modal card-picker (reusing the tutor
    # modal — renderDeckBuilderCard). With exactly 1 entry the drain
    # helper auto-resolves without a modal.
    pending_trigger_queue_turn: tuple = ()    # tuple[PendingTrigger, ...]
    pending_trigger_queue_other: tuple = ()   # tuple[PendingTrigger, ...]
    pending_trigger_picker_idx: Optional[int] = None

    # Turn-structure redesign 2026-07: Handshake tracking (appended fields).
    # ``consecutive_passes`` counts consecutive ACTION-phase PASS actions
    # across BOTH players (react-window passes do NOT count). When a PASS
    # lands while the counter is already 1 (i.e. the opponent's
    # immediately-previous action was also PASS), a Handshake occurs:
    # ``handshake_pending`` is set and the counter resets to 0 (no
    # chaining — the next Handshake needs a fresh pair of passes). The
    # payout (+1 mana each, or a draw if already at MAX_MANA_CAP) happens
    # in the end-of-turn tail (react_stack._close_end_of_turn_and_flip).
    consecutive_passes: int = 0
    handshake_pending: bool = False

    # Turn-structure redesign fixup (2026-07): when the Decay-phase burn
    # tick kills a minion and the death pipeline opens a react window or
    # modal, the remaining Decay work (ON_END_OF_TURN trigger drain +
    # BEFORE_END_OF_TURN react window) is DEFERRED, not skipped. This flag
    # marks the deferral; ``close_end_react_and_advance_turn`` consumes it
    # to resume the Decay phase after the death window closes instead of
    # flipping the turn early (which would have eaten Decay triggers like
    # Emberplague Rat / Dark Matter Battery every time a burn tick killed).
    decay_resume_pending: bool = False

    # Magic-free-action variant (user 2026-07-10 v3, GT_MANUAL_DRAW=1):
    # set when the active player casts a MAGIC (non-minion) card — the
    # cast does NOT consume the turn action. Consumed at the after-action
    # react-window close, which returns to the caster's ACTION phase
    # instead of entering END_OF_TURN. Defensively cleared on turn flip.
    # Appended field with a default — from_dict/serialization tolerant.
    magic_free_action_pending: bool = False

    # Variant v4.2 (user 2026-07-11): once the active player casts a MAGIC
    # card this turn, REST transforms into PASS — legal_actions offers PASS
    # instead of DRAW for the remainder of the turn (no mana+draw skip after
    # a free magic action). Cleared on turn flip. Unlike
    # ``magic_free_action_pending`` (consumed at the window close), this
    # persists across the returned action phase.
    magic_cast_this_turn: bool = False

    # Phase 14.8-05: ``last_trigger_blip`` DELETED. Plan 14.8-03a introduced
    # EVT_TRIGGER_BLIP as a first-class EngineEvent in the event stream;
    # plan 14.8-04b added playTriggerBlip as a client slot handler. The
    # transient field was a legacy dual-write during the transition and
    # has no remaining consumers. from_dict tolerates the missing key
    # naturally (explicit named-arg construction, no **d splat).

    @property
    def active_player(self) -> Player:
        """Return the currently active player."""
        return self.players[self.active_player_idx]

    @property
    def inactive_player(self) -> Player:
        """Return the currently inactive (opposing) player."""
        return self.players[1 - self.active_player_idx]

    def get_minion(self, instance_id: int) -> Optional[MinionInstance]:
        """Find a minion by its instance_id. Returns None if not found."""
        for m in self.minions:
            if m.instance_id == instance_id:
                return m
        return None

    def get_minions_for_side(self, side: PlayerSide) -> tuple[MinionInstance, ...]:
        """Return all minions owned by the given player side."""
        return tuple(m for m in self.minions if m.owner == side)

    @classmethod
    def new_game(
        cls,
        seed: int,
        deck_p1: tuple[int, ...],
        deck_p2: tuple[int, ...],
    ) -> tuple[GameState, GameRNG]:
        """Create a new game with deterministic setup.

        Returns (state, rng) -- RNG is separate because it's mutable.
        Shuffle order: p1 deck first, then p2 deck (deterministic sequence).
        Each player draws STARTING_HAND_SIZE cards from their shuffled deck (D-10).
        """
        rng = GameRNG(seed)

        # Shuffle decks deterministically (p1 first, then p2)
        shuffled_p1 = rng.shuffle(deck_p1)
        shuffled_p2 = rng.shuffle(deck_p2)

        # Create players with shuffled decks
        p1 = Player.new(PlayerSide.PLAYER_1, shuffled_p1)
        p2 = Player.new(PlayerSide.PLAYER_2, shuffled_p2)

        # Draw starting hands (P1=3, P2=4)
        for _ in range(STARTING_HAND_P1):
            p1, _ = p1.draw_card()
        for _ in range(STARTING_HAND_P2):
            p2, _ = p2.draw_card()

        # Both players start their first action with STARTING_MANA (1).
        # P1 takes the first action (turn 1) with STARTING_MANA as set in
        # Player.new(). P2 takes their first action (turn 2) also with
        # STARTING_MANA — the regen-on-turn-flip is suppressed for turn 2
        # in react_stack.resolve_react_stack so P2's first turn matches P1's.

        state = cls(
            board=Board.empty(),
            players=(p1, p2),
            active_player_idx=0,
            phase=TurnPhase.ACTION,
            turn_number=1,
            seed=seed,
        )
        return state, rng

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict.

        Converts enums to ints, tuples to lists for JSON compatibility.
        """
        result = {
            "board": list(self.board.cells),
            "players": [
                {
                    "side": int(p.side),
                    "hp": p.hp,
                    "current_mana": p.current_mana,
                    "max_mana": p.max_mana,
                    "hand": list(p.hand),
                    "deck": list(p.deck),
                    "grave": list(p.grave),
                    "exhaust": list(p.exhaust),
                    "discarded_last_turn": p.discarded_last_turn,
                    # Dark Matter pool redesign 2026-07 — PUBLIC info,
                    # serialized for both players (view_filter keeps it).
                    "dark_matter": p.dark_matter,
                }
                for p in self.players
            ],
            "active_player_idx": self.active_player_idx,
            "phase": int(self.phase),
            "turn_number": self.turn_number,
            "seed": self.seed,
            # Phase 3 fields
            "minions": [
                {
                    "instance_id": m.instance_id,
                    "card_numeric_id": m.card_numeric_id,
                    "owner": int(m.owner),
                    "position": list(m.position),
                    "current_health": m.current_health,
                    "attack_bonus": m.attack_bonus,
                    "is_burning": bool(m.is_burning),
                    "burn_scope": m.burn_scope,
                    "dark_matter_stacks": m.dark_matter_stacks,
                    "max_health_bonus": m.max_health_bonus,
                    "from_deck": bool(m.from_deck),
                }
                for m in self.minions
            ],
            "next_minion_id": self.next_minion_id,
            "react_stack": [
                {
                    "player_idx": entry.player_idx,
                    "card_index": entry.card_index,
                    "card_numeric_id": entry.card_numeric_id,
                    "target_pos": list(entry.target_pos) if entry.target_pos is not None else None,
                    # Phase 14.7-01: originator fields
                    "is_originator": bool(getattr(entry, "is_originator", False)),
                    "origin_kind": getattr(entry, "origin_kind", None),
                    "source_minion_id": getattr(entry, "source_minion_id", None),
                    "effect_payload": (
                        [
                            [
                                idx,
                                (list(tp) if tp is not None else None),
                                co,
                            ]
                            for (idx, tp, co) in getattr(entry, "effect_payload", ()) or ()
                        ]
                        if getattr(entry, "effect_payload", None) is not None else None
                    ),
                    "destroyed_attack": int(getattr(entry, "destroyed_attack", 0)),
                    "destroyed_dm": int(getattr(entry, "destroyed_dm", 0)),
                }
                if hasattr(entry, "player_idx") else entry
                for entry in self.react_stack
            ],
            "react_player_idx": self.react_player_idx,
            # Phase 14.7-02: 3-phase turn model fields
            "react_context": (
                int(self.react_context) if self.react_context is not None else None
            ),
            "react_return_phase": (
                int(self.react_return_phase) if self.react_return_phase is not None else None
            ),
            "pending_action": None,
            # Phase 4: Win/draw detection
            "winner": int(self.winner) if self.winner is not None else None,
            "is_game_over": self.is_game_over,
            # Phase 11 (repurposed 2026-07): escalating fatigue counter for
            # empty-deck turn-start draws (10/20/30... damage per player).
            "fatigue_counts": list(self.fatigue_counts),
            # Turn-structure redesign 2026-07: Handshake tracking.
            "consecutive_passes": self.consecutive_passes,
            "handshake_pending": self.handshake_pending,
            # Deferred-Decay marker (burn-tick death interrupt resume).
            "decay_resume_pending": self.decay_resume_pending,
            # Variant v4.2: REST→PASS transform flag — spans client
            # round-trips within the turn, so it must survive a
            # to_dict/from_dict round-trip (unlike the transient
            # magic_free_action_pending, consumed within one cycle).
            "magic_cast_this_turn": self.magic_cast_this_turn,
            # Phase 14.7-05: simultaneous-trigger priority queue
            "pending_trigger_queue_turn": [
                {
                    "trigger_kind": t.trigger_kind,
                    "source_minion_id": t.source_minion_id,
                    "source_card_numeric_id": t.source_card_numeric_id,
                    "effect_idx": t.effect_idx,
                    "owner_idx": t.owner_idx,
                    "captured_position": list(t.captured_position),
                    "target_pos": (
                        list(t.target_pos) if t.target_pos is not None else None
                    ),
                }
                for t in self.pending_trigger_queue_turn
            ],
            "pending_trigger_queue_other": [
                {
                    "trigger_kind": t.trigger_kind,
                    "source_minion_id": t.source_minion_id,
                    "source_card_numeric_id": t.source_card_numeric_id,
                    "effect_idx": t.effect_idx,
                    "owner_idx": t.owner_idx,
                    "captured_position": list(t.captured_position),
                    "target_pos": (
                        list(t.target_pos) if t.target_pos is not None else None
                    ),
                }
                for t in self.pending_trigger_queue_other
            ],
            "pending_trigger_picker_idx": self.pending_trigger_picker_idx,
            # Phase 14.8 fix: serialize EVERY pending-modal gate so sandbox
            # save/load and server save slots round-trip in-flight modal
            # state. Previously these silently reset to their defaults on
            # load, dropping the decision point mid-modal — and
            # pending_conjure_deploy_card lost the held card entirely
            # (it was removed from the deck and existed only here).
            "pending_post_move_attacker_id": self.pending_post_move_attacker_id,
            "pending_tutor_player_idx": self.pending_tutor_player_idx,
            "pending_tutor_matches": [int(i) for i in self.pending_tutor_matches],
            "pending_tutor_is_conjure": bool(self.pending_tutor_is_conjure),
            "pending_tutor_remaining": int(self.pending_tutor_remaining),
            "pending_tutor_origin": self.pending_tutor_origin,
            "pending_revive_player_idx": self.pending_revive_player_idx,
            "pending_revive_card_id": self.pending_revive_card_id,
            "pending_revive_remaining": int(self.pending_revive_remaining),
            "pending_conjure_deploy_card": self.pending_conjure_deploy_card,
            "pending_conjure_deploy_player_idx": self.pending_conjure_deploy_player_idx,
            "pending_death_target": (
                {
                    "card_numeric_id": int(self.pending_death_target.card_numeric_id),
                    "owner_idx": int(self.pending_death_target.owner_idx),
                    "dying_instance_id": int(self.pending_death_target.dying_instance_id),
                    "effect_idx": int(self.pending_death_target.effect_idx),
                    "filter": self.pending_death_target.filter,
                }
                if self.pending_death_target is not None
                else None
            ),
        }

        # Serialize pending_action if present
        if self.pending_action is not None:
            pa = self.pending_action
            result["pending_action"] = {
                "action_type": int(pa.action_type),
                "card_index": pa.card_index,
                "position": list(pa.position) if pa.position is not None else None,
                "minion_id": pa.minion_id,
                "target_id": pa.target_id,
                "target_pos": list(pa.target_pos) if pa.target_pos is not None else None,
            }

        return result

    @classmethod
    def from_dict(cls, d: dict) -> GameState:
        """Reconstruct a GameState from a dict produced by to_dict().

        Converts lists back to tuples and ints back to enums for full fidelity.
        """
        players = tuple(
            Player(
                side=PlayerSide(p["side"]),
                hp=p["hp"],
                current_mana=p["current_mana"],
                max_mana=p["max_mana"],
                hand=tuple(p["hand"]),
                deck=tuple(p["deck"]),
                grave=tuple(p["grave"]),
                exhaust=tuple(p.get("exhaust", ())),
                discarded_last_turn=p.get("discarded_last_turn", False),
                # Legacy-safe: pre-redesign save dicts lack the key.
                dark_matter=int(p.get("dark_matter", 0) or 0),
            )
            for p in d["players"]
        )
        board = Board(cells=tuple(d["board"]))

        # Reconstruct minions (Phase 3)
        minions_data = d.get("minions", [])
        minions = tuple(
            MinionInstance(
                instance_id=m["instance_id"],
                card_numeric_id=m["card_numeric_id"],
                owner=PlayerSide(m["owner"]),
                position=tuple(m["position"]),
                current_health=m["current_health"],
                attack_bonus=m.get("attack_bonus", 0),
                is_burning=bool(m.get("is_burning", False)),
                burn_scope=m.get("burn_scope", "owner"),
                dark_matter_stacks=m.get("dark_matter_stacks", 0),
                max_health_bonus=m.get("max_health_bonus", 0),
                from_deck=bool(m.get("from_deck", True)),
            )
            for m in minions_data
        )

        # Reconstruct pending_action (Phase 3)
        pending_action = None
        pa_data = d.get("pending_action")
        if pa_data is not None:
            from grid_tactics.enums import ActionType

            pending_action = Action(
                action_type=ActionType(pa_data["action_type"]),
                card_index=pa_data.get("card_index"),
                position=tuple(pa_data["position"]) if pa_data.get("position") is not None else None,
                minion_id=pa_data.get("minion_id"),
                target_id=pa_data.get("target_id"),
                target_pos=tuple(pa_data["target_pos"]) if pa_data.get("target_pos") is not None else None,
            )

        # Phase 4: Win/draw detection
        winner_raw = d.get("winner")
        winner = PlayerSide(winner_raw) if winner_raw is not None else None
        is_game_over = d.get("is_game_over", False)

        # Phase 14.7-02: 3-phase turn model fields
        rc_raw = d.get("react_context")
        react_context = ReactContext(rc_raw) if rc_raw is not None else None
        rrp_raw = d.get("react_return_phase")
        react_return_phase = TurnPhase(rrp_raw) if rrp_raw is not None else None

        # Reconstruct react_stack entries (Phase 14.7-01: includes originator fields)
        from grid_tactics.react_stack import ReactEntry
        react_stack_data = d.get("react_stack", ())
        react_stack_entries = []
        for e in react_stack_data:
            if not isinstance(e, dict):
                # Legacy tuple/other passthrough — keep as-is for backward compat.
                react_stack_entries.append(e)
                continue
            raw_payload = e.get("effect_payload")
            payload_tuple: Optional[tuple] = None
            if raw_payload is not None:
                payload_tuple = tuple(
                    (
                        int(item[0]),
                        (tuple(item[1]) if item[1] is not None else None),
                        int(item[2]),
                    )
                    for item in raw_payload
                )
            react_stack_entries.append(
                ReactEntry(
                    player_idx=e["player_idx"],
                    card_index=e["card_index"],
                    card_numeric_id=e["card_numeric_id"],
                    target_pos=(
                        tuple(e["target_pos"])
                        if e.get("target_pos") is not None else None
                    ),
                    is_originator=bool(e.get("is_originator", False)),
                    origin_kind=e.get("origin_kind"),
                    source_minion_id=e.get("source_minion_id"),
                    effect_payload=payload_tuple,
                    destroyed_attack=int(e.get("destroyed_attack", 0)),
                    destroyed_dm=int(e.get("destroyed_dm", 0)),
                )
            )

        # Phase 14.7-05: reconstruct pending_trigger queues.
        pending_trigger_queue_turn = tuple(
            PendingTrigger(
                trigger_kind=t["trigger_kind"],
                source_minion_id=t.get("source_minion_id"),
                source_card_numeric_id=t["source_card_numeric_id"],
                effect_idx=t["effect_idx"],
                owner_idx=t["owner_idx"],
                captured_position=tuple(t["captured_position"]),
                target_pos=(
                    tuple(t["target_pos"])
                    if t.get("target_pos") is not None else None
                ),
            )
            for t in d.get("pending_trigger_queue_turn", [])
        )
        pending_trigger_queue_other = tuple(
            PendingTrigger(
                trigger_kind=t["trigger_kind"],
                source_minion_id=t.get("source_minion_id"),
                source_card_numeric_id=t["source_card_numeric_id"],
                effect_idx=t["effect_idx"],
                owner_idx=t["owner_idx"],
                captured_position=tuple(t["captured_position"]),
                target_pos=(
                    tuple(t["target_pos"])
                    if t.get("target_pos") is not None else None
                ),
            )
            for t in d.get("pending_trigger_queue_other", [])
        )

        # Phase 14.8 fix: restore pending-modal gates (absent from older
        # save dicts -> defaults, matching pre-fix behavior for legacy
        # files). pending_tutor_matches tolerates BOTH the raw int-index
        # form written by to_dict AND the enriched per-viewer dict form
        # ({deck_idx: ...}) in case a filtered state dict is round-tripped.
        raw_tutor_matches = d.get("pending_tutor_matches") or ()
        pending_tutor_matches = tuple(
            int(m["deck_idx"]) if isinstance(m, dict) else int(m)
            for m in raw_tutor_matches
        )
        pdt_raw = d.get("pending_death_target")
        pending_death_target = (
            PendingDeathTarget(
                card_numeric_id=int(pdt_raw["card_numeric_id"]),
                owner_idx=int(pdt_raw["owner_idx"]),
                dying_instance_id=int(pdt_raw["dying_instance_id"]),
                effect_idx=int(pdt_raw["effect_idx"]),
                filter=pdt_raw.get("filter", "enemy_minion"),
            )
            if isinstance(pdt_raw, dict)
            else None
        )

        return cls(
            board=board,
            players=players,  # type: ignore[arg-type]
            active_player_idx=d["active_player_idx"],
            phase=TurnPhase(d["phase"]),
            turn_number=d["turn_number"],
            seed=d["seed"],
            minions=minions,
            next_minion_id=d.get("next_minion_id", 0),
            react_stack=tuple(react_stack_entries),
            react_player_idx=d.get("react_player_idx"),
            pending_action=pending_action,
            react_context=react_context,
            react_return_phase=react_return_phase,
            winner=winner,
            is_game_over=is_game_over,
            fatigue_counts=tuple(d.get("fatigue_counts", (0, 0))),
            consecutive_passes=int(d.get("consecutive_passes") or 0),
            handshake_pending=bool(d.get("handshake_pending", False)),
            decay_resume_pending=bool(d.get("decay_resume_pending", False)),
            magic_cast_this_turn=bool(d.get("magic_cast_this_turn", False)),
            pending_trigger_queue_turn=pending_trigger_queue_turn,
            pending_trigger_queue_other=pending_trigger_queue_other,
            pending_trigger_picker_idx=d.get("pending_trigger_picker_idx"),
            # Phase 14.8 fix: pending-modal gates (see to_dict).
            pending_post_move_attacker_id=d.get("pending_post_move_attacker_id"),
            pending_tutor_player_idx=d.get("pending_tutor_player_idx"),
            pending_tutor_matches=pending_tutor_matches,
            pending_tutor_is_conjure=bool(d.get("pending_tutor_is_conjure", False)),
            pending_tutor_remaining=int(d.get("pending_tutor_remaining") or 0),
            pending_tutor_origin=d.get("pending_tutor_origin"),
            pending_revive_player_idx=d.get("pending_revive_player_idx"),
            pending_revive_card_id=d.get("pending_revive_card_id"),
            pending_revive_remaining=int(d.get("pending_revive_remaining") or 0),
            pending_conjure_deploy_card=d.get("pending_conjure_deploy_card"),
            pending_conjure_deploy_player_idx=d.get("pending_conjure_deploy_player_idx"),
            pending_death_target=pending_death_target,
            # Phase 14.8-05: last_trigger_blip field deleted. Old saved
            # state dicts carrying this key are tolerated — from_dict uses
            # explicit named-arg construction, so unknown keys in ``d``
            # are simply ignored (m3 verified).
        )


def apply_mulligan(
    state: GameState,
    player_idx: int,
    hand_indices,
    rng: Optional[GameRNG] = None,
) -> tuple[GameState, tuple[int, ...]]:
    """PREGAME mulligan (user 2026-07-08): redraw part of the opening hand.

    Pure engine helper in the immutable-dataclass style: removes the cards
    at ``hand_indices`` from the player's hand, shuffles them back into the
    deck, then draws the same number of replacements off the top (fewer if
    the deck is somehow short — defensive, cannot happen after the shuffle-
    in unless the helper is called with a pathological state).

    Called by the server's pregame stage BEFORE the first turn is taken —
    never from action resolution, so no phase contract / event emission
    lives here. The server emits EVT_CARD_DRAWN(source='mulligan') for each
    replacement itself.

    Args:
        state: The freshly-dealt GameState (no actions taken yet).
        player_idx: 0 or 1 — whose hand to mulligan.
        hand_indices: Iterable of hand indices to redraw. Empty = keep
            (no-op; the SAME state object is returned).
        rng: The game's GameRNG (the server passes ``session.rng``).
            Defaults to a fresh ``GameRNG(state.seed)`` for pure callers.

    Returns:
        (new_state, drawn) — ``drawn`` is the tuple of replacement card
        numeric ids, appended at the END of the hand in draw order.

    Raises:
        ValueError: on duplicate or out-of-range indices.
    """
    player = state.players[player_idx]
    indices = [int(i) for i in hand_indices]
    if len(set(indices)) != len(indices):
        raise ValueError("duplicate hand indices")
    for i in indices:
        if i < 0 or i >= len(player.hand):
            raise ValueError(f"hand index out of range: {i}")
    if not indices:
        return state, ()

    idx_set = set(indices)
    returned = tuple(player.hand[i] for i in sorted(idx_set))
    kept = tuple(c for i, c in enumerate(player.hand) if i not in idx_set)

    if rng is None:
        rng = GameRNG(state.seed)
    new_deck = rng.shuffle(player.deck + returned)
    draw_n = min(len(returned), len(new_deck))
    drawn = new_deck[:draw_n]
    new_deck = new_deck[draw_n:]

    new_player = replace(player, hand=kept + drawn, deck=new_deck)
    players = list(state.players)
    players[player_idx] = new_player
    return replace(state, players=tuple(players)), drawn
