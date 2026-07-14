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


def resolve_ai_roguelike_decisions(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Resolve a pending fortune round for non-interactive engine games."""
    from grid_tactics.react_stack import (
        apply_new_turn_resources,
        enter_start_of_turn,
    )
    from grid_tactics.roguelike_events import (
        choose_marked_cards_for_ai,
        choose_roguelike_event_for_ai,
        resolve_marked_cards_choice,
        resolve_roguelike_event_choice,
    )

    while state.pending_roguelike_event_turn is not None:
        for player_idx in (0, 1):
            if state.pending_roguelike_event_turn is None:
                break
            if state.pending_roguelike_event_choices[player_idx] is None:
                choice = choose_roguelike_event_for_ai(
                    state, player_idx, library,
                )
                state = resolve_roguelike_event_choice(
                    state, player_idx, choice, library,
                )

    while not state.is_game_over and state.pending_marked_cards_player_idx is not None:
        player_idx = state.pending_marked_cards_player_idx
        keep_index, top_order = choose_marked_cards_for_ai(
            state, player_idx, library,
        )
        state = resolve_marked_cards_choice(
            state, player_idx, keep_index, top_order,
        )

    if not state.is_game_over:
        state = apply_new_turn_resources(state)
        if not state.is_game_over:
            state = enter_start_of_turn(state, library)
    return state


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
        if (
            state.pending_roguelike_event_turn is not None
            or state.pending_marked_cards_player_idx is not None
        ):
            state = resolve_ai_roguelike_decisions(state, library)
            continue
        actions = legal_actions(state, library)

        # No legal actions → PASS (free since the 2026-07 turn-structure
        # redesign; fatigue now only fires on empty-deck turn-start draws,
        # which resolve_action's turn-flip tail applies automatically).
        if len(actions) == 0:
            action = pass_action()
            state = resolve_action(state, action, library)
            # Check if turn-start fatigue killed a player
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
