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
    # triggers and chain-reaction death cleanup).
    #
    # ``pending_death_queue`` is the list of dead minions whose on_death
    # effects have not been fully resolved yet. It's processed front-to-back
    # by ``_cleanup_dead_minions``. When an effect needs a click-target
    # modal (e.g. Lasercannon DESTROY/SINGLE_TARGET on_death), processing
    # halts and ``pending_death_target`` is set — the engine then waits
    # for a DEATH_TARGET_PICK action from the dying minion's owner before
    # continuing. While either field is non-empty, the regular react
    # window / turn-advance is deferred in exactly the same way as the
    # other pending_* states.
    pending_death_queue: tuple = ()                          # tuple[PendingDeathWork, ...]
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
    #
    # Death: triggers (14.7-05b) will migrate onto the same queues. Until
    # then, pending_death_queue + pending_death_target remain the source
    # of truth for on-death modal handling.
    pending_trigger_queue_turn: tuple = ()    # tuple[PendingTrigger, ...]
    pending_trigger_queue_other: tuple = ()   # tuple[PendingTrigger, ...]
    pending_trigger_picker_idx: Optional[int] = None

    # Phase 14.7-09: Trigger-blip animation payload (TRANSIENT).
    # Written by ``_resolve_trigger_and_open_react_window`` (react_stack.py)
    # when a Start/End/Death/Summon-effect trigger opens its react window,
    # so the client (game.js ``_fireTriggerBlipAnimation``) can animate a
    # source-tile pulse + center icon + (optional) target-tile pulse.
    #
    # Lifecycle: non-None only on the frame IMMEDIATELY FOLLOWING a trigger
    # resolution. ``resolve_action`` (action_resolver.py) clears this field
    # to None at the TOP of every new call so the client never sees a stale
    # blip on a later frame. See test_last_trigger_blip_cleared_on_next_frame.
    #
    # Shape: Optional[dict] with keys:
    #   trigger_kind: "start_of_turn" | "end_of_turn" | "on_death"
    #                 | "on_summon_effect"
    #   source_minion_id: Optional[int]
    #   source_position: list[int]  (len 2, [row, col])
    #   target_position: Optional[list[int]]  (len 2, [row, col])
    #   effect_kind: str  (lowercase EffectType.name, e.g. "heal", "damage")
    last_trigger_blip: Optional[dict] = None

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
            # Phase 11: Fatigue tracking
            "fatigue_counts": list(self.fatigue_counts),
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
            # Phase 14.7-09: transient trigger-blip payload (see field docstring)
            "last_trigger_blip": self.last_trigger_blip,
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
            pending_trigger_queue_turn=pending_trigger_queue_turn,
            pending_trigger_queue_other=pending_trigger_queue_other,
            pending_trigger_picker_idx=d.get("pending_trigger_picker_idx"),
            # Phase 14.7-09: transient trigger-blip payload (dict passthrough)
            last_trigger_blip=d.get("last_trigger_blip"),
        )
