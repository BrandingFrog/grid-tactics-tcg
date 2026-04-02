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
from grid_tactics.types import STARTING_HAND_SIZE


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

        # Draw starting hands (D-10: 5 cards each)
        for _ in range(STARTING_HAND_SIZE):
            p1, _ = p1.draw_card()
            p2, _ = p2.draw_card()

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
                    "graveyard": list(p.graveyard),
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
                }
                for m in self.minions
            ],
            "next_minion_id": self.next_minion_id,
            "react_stack": list(self.react_stack),
            "react_player_idx": self.react_player_idx,
            "pending_action": None,
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
                graveyard=tuple(p["graveyard"]),
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
        )
