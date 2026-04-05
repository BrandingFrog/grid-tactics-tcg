"""Game loop -- runs a complete game from start to finish with random agents.

Provides:
  - GameResult: frozen dataclass capturing game outcome
  - run_game(): executes a full game with random action selection

This is the capstone of the game engine, proving all mechanics work together.
It also serves as the foundation for the RL environment wrapper in Phase 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from grid_tactics.action_resolver import resolve_action
from grid_tactics.actions import pass_action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import PlayerSide
from grid_tactics.game_state import GameState
from grid_tactics.legal_actions import legal_actions
from grid_tactics.rng import GameRNG
from grid_tactics.types import DEFAULT_TURN_LIMIT


@dataclass(frozen=True, slots=True)
class GameResult:
    """Immutable result of a completed game.

    Attributes:
        winner: Which player won, or None for a draw.
        turn_count: Total number of turns played.
        final_hp: (player1_hp, player2_hp) at game end.
        is_draw: True if the game ended in a draw.
        reason: Why the game ended ("hp_zero", "turn_limit").
    """

    winner: Optional[PlayerSide]
    turn_count: int
    final_hp: tuple[int, int]
    is_draw: bool
    reason: str


def run_game(
    seed: int,
    deck_p1: tuple[int, ...],
    deck_p2: tuple[int, ...],
    library: CardLibrary,
    turn_limit: int = DEFAULT_TURN_LIMIT,
) -> GameResult:
    """Run a complete game with random agents selecting uniformly from legal actions.

    Both players use the same random agent strategy: at each decision point
    (ACTION or REACT phase), pick uniformly at random from legal_actions().

    Args:
        seed: RNG seed for deterministic game replay.
        deck_p1: Player 1's deck as a tuple of card numeric IDs.
        deck_p2: Player 2's deck as a tuple of card numeric IDs.
        library: CardLibrary for card definition lookups.
        turn_limit: Maximum turns before declaring a draw (default 200).

    Returns:
        GameResult with winner, turn count, final HP, and termination reason.
    """
    state, rng = GameState.new_game(seed, deck_p1, deck_p2)

    while not state.is_game_over and state.turn_number <= turn_limit:
        actions = legal_actions(state, library)

        # No legal actions = fatigue bleed (escalating 10/20/30...)
        if len(actions) == 0:
            action = pass_action()
            state = resolve_action(state, action, library)
            # Check if fatigue killed the player
            if state.players[state.active_player_idx].hp <= 0 or state.players[1 - state.active_player_idx].hp <= 0:
                break
            continue

        action = rng.choice(actions)
        state = resolve_action(state, action, library)

    # Determine outcome
    if state.is_game_over:
        return GameResult(
            winner=state.winner,
            turn_count=state.turn_number,
            final_hp=(state.players[0].hp, state.players[1].hp),
            is_draw=state.winner is None,
            reason="hp_zero",
        )
    else:
        # Turn limit reached without natural game end.
        # Cap turn_count at turn_limit (state.turn_number may be limit+1
        # because turn advances happen inside resolve_action/react_stack).
        return GameResult(
            winner=None,
            turn_count=min(state.turn_number, turn_limit),
            final_hp=(state.players[0].hp, state.players[1].hp),
            is_draw=True,
            reason="turn_limit",
        )
