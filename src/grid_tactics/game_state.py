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
from grid_tactics.enums import PlayerSide, TurnPhase
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
                }
                if hasattr(entry, "player_idx") else entry
                for entry in self.react_stack
            ],
            "react_player_idx": self.react_player_idx,
            "pending_action": None,
            # Phase 4: Win/draw detection
            "winner": int(self.winner) if self.winner is not None else None,
            "is_game_over": self.is_game_over,
            # Phase 11: Fatigue tracking
            "fatigue_counts": list(self.fatigue_counts),
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

        return cls(
            board=board,
            players=players,  # type: ignore[arg-type]
            active_player_idx=d["active_player_idx"],
            phase=TurnPhase(d["phase"]),
            turn_number=d["turn_number"],
            seed=d["seed"],
            minions=minions,
            next_minion_id=d.get("next_minion_id", 0),
            react_stack=tuple(d.get("react_stack", ())),
            react_player_idx=d.get("react_player_idx"),
            pending_action=pending_action,
            winner=winner,
            is_game_over=is_game_over,
            fatigue_counts=tuple(d.get("fatigue_counts", (0, 0))),
        )
