"""Legal action enumeration -- returns all valid actions from any game state.

Main entry point: legal_actions(state, library) -> tuple[Action, ...]

During ACTION phase, enumerates:
  - PLAY_CARD: minion deployment (D-08 melee, D-09 ranged), magic targeting
  - MOVE: all orthogonal adjacent empty cells for owned minions
  - ATTACK: all valid targets in range (D-03) for owned minions
  - DRAW: if deck is non-empty
  - PASS: always (D-16)

During REACT phase, enumerates:
  - PLAY_REACT: react-eligible cards (CardType.REACT or is_multi_purpose)
  - PASS: always

This is critical for Phase 5 RL action masking -- legal_actions() provides the
boolean mask that prevents the agent from selecting invalid actions (D-19).
"""

from __future__ import annotations

from grid_tactics.action_resolver import _can_attack, _is_orthogonal
from grid_tactics.actions import (
    Action,
    attack_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
    sacrifice_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import (
    ActionType, Attribute, CardType, EffectType, PlayerSide, ReactCondition,
    TargetType, TriggerType, TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.types import (
    BACK_ROW_P1,
    BACK_ROW_P2,
    GRID_COLS,
    MAX_REACT_STACK_DEPTH,
    PLAYER_1_ROWS,
    PLAYER_2_ROWS,
)


def legal_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Return all valid actions for the current game state.

    Never includes illegal actions. PASS is always present (D-16).

    Args:
        state: Current game state.
        library: CardLibrary for card definition lookups.

    Returns:
        Tuple of all valid Action instances.
    """
    # Game is over -- no meaningful actions allowed (Phase 4)
    if state.is_game_over:
        return (pass_action(),)

    if state.phase == TurnPhase.ACTION:
        return _action_phase_actions(state, library)
    elif state.phase == TurnPhase.REACT:
        return _react_phase_actions(state, library)
    else:
        # Unknown phase -- return only PASS as safe fallback
        return (pass_action(),)


# ---------------------------------------------------------------------------
# ACTION phase enumeration
# ---------------------------------------------------------------------------


def _action_phase_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate all valid actions during the ACTION phase."""
    actions: list[Action] = []
    player = state.active_player
    player_side = player.side

    # PLAY_CARD enumeration
    for idx, card_numeric_id in enumerate(player.hand):
        card_def = library.get_by_id(card_numeric_id)

        # Check mana (D-11)
        if player.current_mana < card_def.mana_cost:
            continue

        if card_def.card_type == CardType.MINION:
            deploy_positions = _valid_deploy_positions(state, card_def, player_side)
            for pos in deploy_positions:
                # Check if card has ON_PLAY effects with SINGLE_TARGET
                has_single_target_on_play = any(
                    e.trigger == TriggerType.ON_PLAY and e.target == TargetType.SINGLE_TARGET
                    for e in card_def.effects
                )
                if has_single_target_on_play:
                    # Enumerate target positions (enemy minions)
                    enemy_positions = _get_enemy_minion_positions(state, player_side)
                    if enemy_positions:
                        for target_pos in enemy_positions:
                            actions.append(play_card_action(
                                card_index=idx, position=pos, target_pos=target_pos,
                            ))
                    else:
                        # Deploy without target — on_play effect skipped (no valid targets)
                        actions.append(play_card_action(card_index=idx, position=pos))
                else:
                    actions.append(play_card_action(card_index=idx, position=pos))

        elif card_def.card_type == CardType.MAGIC:
            # Check if any ON_PLAY effect has SINGLE_TARGET
            has_single_target = any(
                e.trigger == TriggerType.ON_PLAY and e.target == TargetType.SINGLE_TARGET
                for e in card_def.effects
            )
            if has_single_target:
                enemy_positions = _get_enemy_minion_positions(state, player_side)
                for target_pos in enemy_positions:
                    actions.append(play_card_action(
                        card_index=idx, target_pos=target_pos,
                    ))
                # Single-target magic with no valid targets: cannot play
            else:
                # Area/self effects: single play action, no target needed
                actions.append(play_card_action(card_index=idx))

        # Skip CardType.REACT during ACTION phase

    # MOVE enumeration
    owned_minions = state.get_minions_for_side(player_side)
    for minion in owned_minions:
        adjacent_positions = Board.get_orthogonal_adjacent(minion.position)
        for adj_pos in adjacent_positions:
            if state.board.get(adj_pos[0], adj_pos[1]) is None:
                actions.append(move_action(
                    minion_id=minion.instance_id, position=adj_pos,
                ))

    # ATTACK enumeration
    for minion in owned_minions:
        card_def = library.get_by_id(minion.card_numeric_id)
        for enemy in state.minions:
            if enemy.owner != player_side:
                if _can_attack(minion, enemy, card_def):
                    actions.append(attack_action(
                        minion_id=minion.instance_id,
                        target_id=enemy.instance_id,
                    ))

    # SACRIFICE enumeration (Phase 4)
    # Minions on opponent's back row can be sacrificed
    for minion in owned_minions:
        row = minion.position[0]
        if player_side == PlayerSide.PLAYER_1 and row == BACK_ROW_P2:
            actions.append(sacrifice_action(minion_id=minion.instance_id))
        elif player_side == PlayerSide.PLAYER_2 and row == BACK_ROW_P1:
            actions.append(sacrifice_action(minion_id=minion.instance_id))

    # DRAW
    if player.deck:
        actions.append(draw_action())

    # PASS (D-16: always legal)
    actions.append(pass_action())

    return tuple(actions)


# ---------------------------------------------------------------------------
# REACT phase enumeration
# ---------------------------------------------------------------------------


def _check_react_condition(
    condition: ReactCondition, state: GameState, library: CardLibrary,
) -> bool:
    """Check if a react card's condition is met by the pending action or last react.

    Checks the pending_action (the main-phase action that opened the react window)
    or the last react on the stack (for counter-react conditions).
    """
    # If there are reacts on the stack, the most recent one is what we're reacting to
    if state.react_stack:
        last_react = state.react_stack[-1]
        last_card = library.get_by_id(last_react.card_numeric_id)
        if condition == ReactCondition.OPPONENT_PLAYS_REACT:
            return True  # Reacting to a react
        if condition == ReactCondition.OPPONENT_PLAYS_MAGIC:
            return last_card.card_type == CardType.MAGIC or last_card.card_type == CardType.REACT
        if condition == ReactCondition.ANY_ACTION:
            return True
        return False

    # Otherwise check the pending_action (the main-phase action that triggered the window)
    pending = state.pending_action
    if pending is None:
        return condition == ReactCondition.ANY_ACTION

    if condition == ReactCondition.OPPONENT_PLAYS_MAGIC:
        if pending.action_type == ActionType.PLAY_CARD and pending.card_index is not None:
            # Check if the played card was magic
            acting_player = state.players[state.active_player_idx]
            # pending_action was recorded before the card was removed from hand,
            # so look up the card in graveyard (most recently added)
            if acting_player.graveyard:
                last_played_id = acting_player.graveyard[-1]
                card_def = library.get_by_id(last_played_id)
                return card_def.card_type == CardType.MAGIC
        return False

    if condition == ReactCondition.OPPONENT_PLAYS_MINION:
        if pending.action_type == ActionType.PLAY_CARD:
            # Check if a minion was deployed (new minion on board from this action)
            return pending.position is not None  # minion deploy always has position
        return False

    if condition == ReactCondition.OPPONENT_ATTACKS:
        return pending.action_type == ActionType.ATTACK

    if condition == ReactCondition.OPPONENT_PLAYS_REACT:
        return False  # No react on stack means nothing to counter-react

    if condition == ReactCondition.ANY_ACTION:
        return True

    # Attribute-based conditions
    _ATTR_CONDITIONS = {
        ReactCondition.OPPONENT_PLAYS_FIRE: Attribute.FIRE,
        ReactCondition.OPPONENT_PLAYS_DARK: Attribute.DARK,
        ReactCondition.OPPONENT_PLAYS_LIGHT: Attribute.LIGHT,
        ReactCondition.OPPONENT_PLAYS_NEUTRAL: Attribute.NEUTRAL,
    }
    if condition in _ATTR_CONDITIONS:
        required_attr = _ATTR_CONDITIONS[condition]
        if pending.action_type == ActionType.PLAY_CARD:
            # Check attribute of the card that was just played
            acting_player = state.players[state.active_player_idx]
            if acting_player.graveyard:
                last_played_id = acting_player.graveyard[-1]
                card_def = library.get_by_id(last_played_id)
                return card_def.attribute == required_attr
            # Check newly deployed minions (minion cards go to board, not graveyard)
            if pending.position is not None and state.minions:
                # Find minion at the deploy position
                for m in state.minions:
                    if m.position == pending.position:
                        card_def = library.get_by_id(m.card_numeric_id)
                        return card_def.attribute == required_attr
        return False

    return False


def _react_phase_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate all valid actions during the REACT phase.

    React cards are only legal if their react_condition matches the
    pending action or last react on the stack.
    """
    actions: list[Action] = []
    react_player = state.players[state.react_player_idx]
    react_side = react_player.side

    # If stack is at max depth, only PASS is legal
    if len(state.react_stack) >= MAX_REACT_STACK_DEPTH:
        return (pass_action(),)

    for idx, card_numeric_id in enumerate(react_player.hand):
        card_def = library.get_by_id(card_numeric_id)

        if card_def.card_type == CardType.REACT:
            # Check condition matches the triggering action
            if card_def.react_condition is None:
                continue  # Shouldn't happen (validation catches this), but safety
            if not _check_react_condition(card_def.react_condition, state, library):
                continue  # Condition not met -- this react can't be played now

            if react_player.current_mana >= card_def.mana_cost:
                # NEGATE effects don't need a target (they cancel the triggering action)
                has_negate = any(
                    e.effect_type.name == "NEGATE"
                    for e in card_def.effects
                )
                if has_negate:
                    actions.append(play_react_action(card_index=idx))
                    continue

                # Check for single-target effects
                has_single_target = any(
                    e.target == TargetType.SINGLE_TARGET
                    for e in card_def.effects
                )
                if has_single_target:
                    enemy_positions = _get_enemy_minion_positions(state, react_side)
                    friendly_positions = _get_friendly_minion_positions(state, react_side)
                    all_target_positions = list(set(enemy_positions + friendly_positions))
                    for target_pos in all_target_positions:
                        actions.append(play_react_action(
                            card_index=idx, target_pos=target_pos,
                        ))
                    if not all_target_positions:
                        # No targets but card is playable (area effects, etc)
                        actions.append(play_react_action(card_index=idx))
                else:
                    actions.append(play_react_action(card_index=idx))

        elif card_def.is_multi_purpose:
            # Check condition if multi-purpose card has one
            if card_def.react_condition is not None:
                if not _check_react_condition(card_def.react_condition, state, library):
                    continue

            if react_player.current_mana >= card_def.react_mana_cost:
                # DEPLOY_SELF: react deploys this minion to the board at discount
                if (card_def.react_effect is not None
                        and card_def.react_effect.effect_type == EffectType.DEPLOY_SELF):
                    deploy_positions = _valid_deploy_positions(state, card_def, react_side)
                    for pos in deploy_positions:
                        actions.append(play_react_action(
                            card_index=idx, target_pos=pos,
                        ))
                elif (card_def.react_effect is not None
                        and card_def.react_effect.target == TargetType.SINGLE_TARGET):
                    enemy_positions = _get_enemy_minion_positions(state, react_side)
                    friendly_positions = _get_friendly_minion_positions(state, react_side)
                    all_target_positions = list(set(enemy_positions + friendly_positions))
                    for target_pos in all_target_positions:
                        actions.append(play_react_action(
                            card_index=idx, target_pos=target_pos,
                        ))
                    if not all_target_positions:
                        actions.append(play_react_action(card_index=idx))
                else:
                    actions.append(play_react_action(card_index=idx))

    # PASS always legal
    actions.append(pass_action())

    return tuple(actions)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_deploy_positions(state, card_def, side):
    """Return valid empty deploy positions for a minion card.

    D-08: Melee (range=0) -> any empty cell in friendly rows.
    D-09: Ranged (range>=1) -> only empty cells in back row.
    """
    if card_def.attack_range == 0:
        # Melee: all friendly rows
        rows = PLAYER_1_ROWS if side.value == 0 else PLAYER_2_ROWS
    else:
        # Ranged: back row only
        back_row = BACK_ROW_P1 if side.value == 0 else BACK_ROW_P2
        rows = (back_row,)

    positions = []
    for row in rows:
        for col in range(GRID_COLS):
            if state.board.get(row, col) is None:
                positions.append((row, col))
    return positions


def _get_enemy_minion_positions(state, player_side):
    """Return positions of all enemy minions on the board."""
    return [
        m.position for m in state.minions
        if m.owner != player_side
    ]


def _get_friendly_minion_positions(state, player_side):
    """Return positions of all friendly minions on the board."""
    return [
        m.position for m in state.minions
        if m.owner == player_side
    ]
