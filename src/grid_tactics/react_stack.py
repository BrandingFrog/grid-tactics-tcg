"""React stack -- LIFO react window with chaining and resolution.

Implements the react window mechanic (D-04 through D-07):
  - After a main-phase action, opponent gets a react opportunity
  - React cards chain: after a react, the other player can counter-react
  - Stack resolves LIFO (last react played resolves first)
  - Passing closes that player's chain and resolves the stack

Entry points:
  - handle_react_action(): Handle PLAY_REACT or PASS during react window
  - resolve_react_stack(): Resolve stack LIFO and advance turn
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from grid_tactics.actions import Action
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import ActionType, CardType, EffectType, TriggerType, TurnPhase
from grid_tactics.game_state import GameState
from grid_tactics.types import MAX_REACT_STACK_DEPTH


@dataclass(frozen=True, slots=True)
class ReactEntry:
    """A single entry on the react stack.

    Tracks who played it, which card, and the optional target position
    for single-target react effects.
    """

    player_idx: int                              # who played this react
    card_index: int                              # which card from hand (at time of play)
    card_numeric_id: int                         # card definition ID for effect lookup
    target_pos: Optional[tuple[int, int]] = None  # for single-target react effects


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_player(
    players: tuple,
    idx: int,
    new_player,
) -> tuple:
    """Return a new players tuple with one player replaced."""
    if idx == 0:
        return (new_player, players[1])
    return (players[0], new_player)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def handle_react_action(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Handle an action during the react window.

    Valid actions during REACT phase:
      - PASS: resolve the stack LIFO and advance the turn
      - PLAY_REACT: push a react card onto the stack, switch to counter-react

    Args:
        state: Current game state (must be in REACT phase).
        action: The action to apply (PASS or PLAY_REACT).
        library: CardLibrary for card definition lookups.

    Returns:
        New GameState after handling the react action.

    Raises:
        ValueError: If the action is invalid during REACT phase.
    """
    if action.action_type == ActionType.PASS:
        return resolve_react_stack(state, library)

    if action.action_type == ActionType.PLAY_REACT:
        return _play_react(state, action, library)

    raise ValueError(
        f"Invalid action type {action.action_type.name} during REACT phase. "
        f"Only PASS and PLAY_REACT are allowed."
    )


def _play_react(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Process a PLAY_REACT action: validate, spend mana, push to stack, switch player.

    Validates:
      - Card is react-eligible (CardType.REACT or is_multi_purpose)
      - Sufficient mana (mana_cost for React, react_mana_cost for multi-purpose)
      - Stack depth < MAX_REACT_STACK_DEPTH
    """
    # Validate stack depth
    if len(state.react_stack) >= MAX_REACT_STACK_DEPTH:
        raise ValueError(
            f"React stack depth at maximum ({MAX_REACT_STACK_DEPTH}). "
            f"Cannot play more react cards."
        )

    react_idx = state.react_player_idx
    player = state.players[react_idx]

    # Get card from hand
    if action.card_index is None or action.card_index < 0 or action.card_index >= len(player.hand):
        raise ValueError(f"Invalid card_index: {action.card_index}")

    card_numeric_id = player.hand[action.card_index]
    card_def = library.get_by_id(card_numeric_id)

    # Determine if card is react-eligible and the appropriate cost
    if card_def.card_type == CardType.REACT:
        mana_cost = card_def.mana_cost
    elif card_def.is_multi_purpose:
        mana_cost = card_def.react_mana_cost
    else:
        raise ValueError(
            f"Card '{card_def.card_id}' ({card_def.card_type.name}) is not react-eligible. "
            f"Only REACT cards and multi-purpose minions can be played during react window."
        )

    # Validate mana
    if player.current_mana < mana_cost:
        raise ValueError(
            f"Insufficient mana: have {player.current_mana}, need {mana_cost}"
        )

    # Spend mana and discard card from hand to graveyard
    new_player = player.spend_mana(mana_cost)
    new_player = new_player.discard_from_hand(card_numeric_id)
    new_players = _replace_player(state.players, react_idx, new_player)

    # Create ReactEntry and push onto stack
    entry = ReactEntry(
        player_idx=react_idx,
        card_index=action.card_index,
        card_numeric_id=card_numeric_id,
        target_pos=action.target_pos,
    )
    new_stack = state.react_stack + (entry,)

    # Switch react_player_idx to other player (counter-react opportunity, D-05)
    new_react_player_idx = 1 - react_idx

    return replace(
        state,
        players=new_players,
        react_stack=new_stack,
        react_player_idx=new_react_player_idx,
    )


def resolve_react_stack(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Resolve the react stack LIFO and advance the turn.

    Iterates over the stack in reverse order (LIFO, D-06).
    For each entry:
      - REACT cards: resolve all ON_PLAY effects
      - Multi-purpose cards: resolve the react_effect only

    After resolution:
      - Clean up dead minions
      - Clear react state
      - Advance turn (flip active player, increment turn_number)
      - Regenerate mana for the new active player
    """
    from grid_tactics.effect_resolver import resolve_effect

    # Resolve stack LIFO (D-06)
    # Track negated entries -- a NEGATE effect cancels the next entry in the stack
    negated_indices: set[int] = set()

    stack_list = list(reversed(state.react_stack))
    for i, entry in enumerate(stack_list):
        # Skip if this entry was negated by a previous NEGATE
        if i in negated_indices:
            continue

        card_def = library.get_by_id(entry.card_numeric_id)
        caster_owner = state.players[entry.player_idx].side

        if card_def.card_type == CardType.REACT:
            # Check if this react has NEGATE effects
            has_negate = any(
                e.effect_type == EffectType.NEGATE
                for e in card_def.effects
            )
            if has_negate:
                # NEGATE cancels the next entry in the stack (the action being countered)
                if i + 1 < len(stack_list):
                    negated_indices.add(i + 1)
                # Non-negate effects on the same card still resolve
                for effect in card_def.effects:
                    if effect.trigger == TriggerType.ON_PLAY and effect.effect_type != EffectType.NEGATE:
                        state = resolve_effect(
                            state, effect, (0, 0), caster_owner, library,
                            entry.target_pos,
                        )
            else:
                # Normal react -- resolve all ON_PLAY effects
                for effect in card_def.effects:
                    if effect.trigger == TriggerType.ON_PLAY:
                        state = resolve_effect(
                            state, effect, (0, 0), caster_owner, library,
                            entry.target_pos,
                        )
        elif card_def.is_multi_purpose:
            # Resolve the react_effect only for multi-purpose cards
            if card_def.react_effect is not None:
                if card_def.react_effect.effect_type == EffectType.DEPLOY_SELF:
                    # DEPLOY_SELF: deploy this minion to the board at target_pos
                    if entry.target_pos is not None:
                        from grid_tactics.minion import MinionInstance
                        new_minion = MinionInstance(
                            instance_id=state.next_minion_id,
                            card_numeric_id=entry.card_numeric_id,
                            owner=state.players[entry.player_idx].side,
                            position=entry.target_pos,
                            current_health=card_def.health,
                        )
                        new_board = state.board.place(
                            entry.target_pos[0], entry.target_pos[1],
                            new_minion.instance_id,
                        )
                        state = replace(
                            state,
                            board=new_board,
                            minions=state.minions + (new_minion,),
                            next_minion_id=state.next_minion_id + 1,
                        )
                else:
                    state = resolve_effect(
                        state, card_def.react_effect, (0, 0), caster_owner, library,
                        entry.target_pos,
                    )

    # Clean up dead minions after react resolution
    from grid_tactics.action_resolver import _cleanup_dead_minions, _check_game_over
    state = _cleanup_dead_minions(state, library)

    # Win/draw detection after react resolution (Phase 4)
    state = _check_game_over(state)
    if state.is_game_over:
        # Game is over -- clear react state but don't advance turn
        return replace(
            state,
            react_stack=(),
            react_player_idx=None,
            pending_action=None,
        )

    # Advance turn: flip active player, increment turn number, clear react state
    new_active_idx = 1 - state.active_player_idx
    state = replace(
        state,
        react_stack=(),
        react_player_idx=None,
        pending_action=None,
        phase=TurnPhase.ACTION,
        active_player_idx=new_active_idx,
        turn_number=state.turn_number + 1,
    )

    # Regenerate mana for the new active player at turn start
    new_active_player = state.players[new_active_idx].regenerate_mana()
    new_players = _replace_player(state.players, new_active_idx, new_active_player)
    state = replace(state, players=new_players)

    return state
