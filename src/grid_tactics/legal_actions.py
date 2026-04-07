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

from typing import Optional

from grid_tactics.action_resolver import _can_attack, _is_orthogonal
from grid_tactics.actions import (
    Action,
    attack_action,
    decline_post_move_attack_action,
    decline_tutor_action,
    draw_action,
    move_action,
    pass_action,
    play_card_action,
    play_react_action,
    sacrifice_action,
    transform_action,
    tutor_select_action,
)
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.enums import (
    ActionType, CardType, EffectType, Element, PlayerSide, ReactCondition,
    TargetType, TriggerType, TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.types import (
    BACK_ROW_P1,
    BACK_ROW_P2,
    GRID_COLS,
    GRID_ROWS,
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
    # Game is over -- no actions allowed
    if state.is_game_over:
        return ()

    # Mutex: the two pending flavours must never coexist. Loud assert (defense
    # in depth on top of the asserts in _enter_pending_tutor / action_resolver).
    assert not (
        state.pending_tutor_player_idx is not None
        and state.pending_post_move_attacker_id is not None
    ), "pending_tutor and pending_post_move_attacker cannot coexist"

    # Phase 14.2: while pending_tutor is set, the ONLY legal actions are
    # TUTOR_SELECT (one per match index in state.pending_tutor_matches) and
    # DECLINE_TUTOR. Slot reinterpretation in the integer action space:
    #   - TUTOR_SELECT reuses PLAY_CARD slots [0:n] (the encoder writes the
    #     match index on Action.card_index, then PLAY_CARD_BASE + match_idx*25)
    #     -- regular PLAY_CARD is illegal here so the channel is free.
    #   - DECLINE_TUTOR reuses slot 1001 (PASS); the encoder/decoder
    #     disambiguate using state.pending_tutor_player_idx, mirroring the
    #     14.1 DECLINE_POST_MOVE_ATTACK trick.
    # The action_resolver layer enforces the same restriction at runtime; this
    # branch keeps RL agents (and the human UI) from selecting illegal slots.
    if state.pending_tutor_player_idx is not None:
        return _pending_tutor_actions(state)

    # Phase 14.1: while a melee minion is mid-move-attack (pending), the only
    # legal actions are ATTACK from the pending attacker against an in-range
    # enemy, or DECLINE_POST_MOVE_ATTACK. Slot 1001 (PASS) is reinterpreted
    # as DECLINE in this state by the action encoder. PLAY_CARD, MOVE,
    # SACRIFICE, DRAW, regular PASS and REACT are all illegal here.
    if state.pending_post_move_attacker_id is not None:
        return _pending_post_move_attack_actions(state, library)

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

        # Summon sacrifice check: enumerate one action per valid sacrifice choice
        sacrifice_choices: list[Optional[int]] = [None]
        if card_def.summon_sacrifice_tribe:
            sacrifice_choices = []
            for j in range(len(player.hand)):
                if j == idx:
                    continue
                hand_card = library.get_by_id(player.hand[j])
                if hand_card.tribe == card_def.summon_sacrifice_tribe:
                    sacrifice_choices.append(j)
            if not sacrifice_choices:
                continue  # no valid sacrifice card -> can't play

        for sac_idx in sacrifice_choices:
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
                                actions.append(Action(
                                    action_type=ActionType.PLAY_CARD,
                                    card_index=idx, position=pos, target_pos=target_pos,
                                    sacrifice_card_index=sac_idx,
                                ))
                        else:
                            actions.append(Action(
                                action_type=ActionType.PLAY_CARD,
                                card_index=idx, position=pos,
                                sacrifice_card_index=sac_idx,
                            ))
                    else:
                        actions.append(Action(
                            action_type=ActionType.PLAY_CARD,
                            card_index=idx, position=pos,
                            sacrifice_card_index=sac_idx,
                        ))

            elif card_def.card_type == CardType.MAGIC:
                # Check if any ON_PLAY effect has SINGLE_TARGET
                has_single_target = any(
                    e.trigger == TriggerType.ON_PLAY and e.target == TargetType.SINGLE_TARGET
                    for e in card_def.effects
                )
                if has_single_target:
                    enemy_positions = _get_enemy_minion_positions(state, player_side)
                    for target_pos in enemy_positions:
                        actions.append(Action(
                            action_type=ActionType.PLAY_CARD,
                            card_index=idx, target_pos=target_pos,
                            sacrifice_card_index=sac_idx,
                        ))
                else:
                    actions.append(Action(
                        action_type=ActionType.PLAY_CARD,
                        card_index=idx,
                        sacrifice_card_index=sac_idx,
                    ))

        # Skip CardType.REACT during ACTION phase

    # MOVE enumeration (forward only in lane)
    owned_minions = state.get_minions_for_side(player_side)
    for minion in owned_minions:
        row, col = minion.position
        # Forward: P1 moves down (+1 row), P2 moves up (-1 row)
        delta = 1 if player_side == PlayerSide.PLAYER_1 else -1
        fwd_row = row + delta
        if 0 <= fwd_row < GRID_ROWS:
            if state.board.get(fwd_row, col) is None:
                actions.append(move_action(
                    minion_id=minion.instance_id, position=(fwd_row, col),
                ))
            else:
                # LEAP: if the forward tile is blocked but the minion has a
                # LEAP effect, allow jumping over the blocker to the next empty
                # tile in the same column (up to `amount` tiles past the blocker).
                minion_card = library.get_by_id(minion.card_numeric_id)
                leap_amount = 0
                for eff in minion_card.effects:
                    if eff.effect_type == EffectType.LEAP:
                        leap_amount = max(leap_amount, eff.amount or 1)
                if leap_amount > 0:
                    # Walk past the blocker(s) up to leap_amount additional steps
                    landing_row = fwd_row + delta
                    steps = 0
                    while (
                        0 <= landing_row < GRID_ROWS
                        and steps < leap_amount
                        and state.board.get(landing_row, col) is not None
                    ):
                        landing_row += delta
                        steps += 1
                    if (
                        0 <= landing_row < GRID_ROWS
                        and state.board.get(landing_row, col) is None
                    ):
                        actions.append(move_action(
                            minion_id=minion.instance_id,
                            position=(landing_row, col),
                        ))

    # ATTACK enumeration
    # General rule: a minion with effective attack <= 0 cannot attack.
    # Effective attack = card_def.attack + minion.attack_bonus.
    for minion in owned_minions:
        card_def = library.get_by_id(minion.card_numeric_id)
        effective_attack = card_def.attack + minion.attack_bonus
        if effective_attack <= 0:
            continue
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

    # TRANSFORM enumeration: minions with transform_options can transform on the board
    # for the listed mana cost into the target card form.
    for minion in owned_minions:
        card_def = library.get_by_id(minion.card_numeric_id)
        if not card_def.transform_options:
            continue
        for target_card_id, mana_cost in card_def.transform_options:
            if player.current_mana >= mana_cost:
                actions.append(transform_action(
                    minion_id=minion.instance_id,
                    transform_target=target_card_id,
                ))

    # ACTIVATED ABILITY enumeration: minions with an activated_ability whose
    # owner can pay the cost and has at least one valid target tile.
    for minion in owned_minions:
        card_def = library.get_by_id(minion.card_numeric_id)
        ability = card_def.activated_ability
        if ability is None:
            continue
        if player.current_mana < ability.mana_cost:
            continue
        if ability.target == "own_side_empty":
            own_rows = PLAYER_1_ROWS if player_side == PlayerSide.PLAYER_1 else PLAYER_2_ROWS
            for r in own_rows:
                for c in range(GRID_COLS):
                    if state.board.get(r, c) is None:
                        actions.append(Action(
                            action_type=ActionType.ACTIVATE_ABILITY,
                            minion_id=minion.instance_id,
                            target_pos=(r, c),
                        ))
        elif ability.target == "none":
            # Untargeted self-ability — emit exactly one action.
            actions.append(Action(
                action_type=ActionType.ACTIVATE_ABILITY,
                minion_id=minion.instance_id,
                target_pos=None,
            ))

    # DRAW as an action (in addition to auto-draw at turn start)
    if player.deck and len(player.hand) < 10:
        actions.append(draw_action())

    # No PASS -- if no actions available, fatigue bleed handles it
    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending tutor enumeration (Phase 14.2)
# ---------------------------------------------------------------------------


def _pending_tutor_actions(state: GameState) -> tuple[Action, ...]:
    """Enumerate the only-legal actions while pending_tutor is set.

    Legal:
      - TUTOR_SELECT(match_idx) for each ``match_idx in [0, len(matches))``
      - DECLINE_TUTOR (encoded on slot 1001 by the encoder)

    Mutually exclusive with the 14.1 pending-post-move-attack state (asserted
    upstream in ``legal_actions``).
    """
    actions: list[Action] = [
        tutor_select_action(match_index=i)
        for i in range(len(state.pending_tutor_matches))
    ]
    actions.append(decline_tutor_action())
    return tuple(actions)


# ---------------------------------------------------------------------------
# Pending post-move attack enumeration (Phase 14.1)
# ---------------------------------------------------------------------------


def _pending_post_move_attack_actions(
    state: GameState, library: CardLibrary,
) -> tuple[Action, ...]:
    """Enumerate the only-legal actions while a post-move attack is pending.

    Legal:
      - ATTACK from the pending attacker against any in-range enemy minion
      - DECLINE_POST_MOVE_ATTACK (encoded on slot 1001 by the encoder)

    Slot 1001 dual meaning: in non-pending state slot 1001 is PASS; in
    pending state the action encoder maps slot 1001 to
    DECLINE_POST_MOVE_ATTACK. The action_resolver dispatches based on
    ``state.pending_post_move_attacker_id``.
    """
    actions: list[Action] = []
    attacker = state.get_minion(state.pending_post_move_attacker_id)
    if attacker is None:
        # Defensive: pending references a missing minion -> only decline
        return (decline_post_move_attack_action(),)

    attacker_card = library.get_by_id(attacker.card_numeric_id)
    if attacker_card.attack + attacker.attack_bonus <= 0:
        return (decline_post_move_attack_action(),)
    for enemy in state.minions:
        if enemy.owner == attacker.owner:
            continue
        if _can_attack(attacker, enemy, attacker_card):
            actions.append(attack_action(
                minion_id=attacker.instance_id,
                target_id=enemy.instance_id,
            ))

    # DECLINE is always legal in pending state (escape hatch)
    actions.append(decline_post_move_attack_action())
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

    # Element-based conditions
    _ELEM_CONDITIONS = {
        ReactCondition.OPPONENT_PLAYS_WOOD: Element.WOOD,
        ReactCondition.OPPONENT_PLAYS_FIRE: Element.FIRE,
        ReactCondition.OPPONENT_PLAYS_EARTH: Element.EARTH,
        ReactCondition.OPPONENT_PLAYS_WATER: Element.WATER,
        ReactCondition.OPPONENT_PLAYS_METAL: Element.METAL,
        ReactCondition.OPPONENT_PLAYS_DARK: Element.DARK,
        ReactCondition.OPPONENT_PLAYS_LIGHT: Element.LIGHT,
    }
    if condition in _ELEM_CONDITIONS:
        required_elem = _ELEM_CONDITIONS[condition]
        if pending.action_type == ActionType.PLAY_CARD:
            # Check element of the card that was just played
            acting_player = state.players[state.active_player_idx]
            if acting_player.graveyard:
                last_played_id = acting_player.graveyard[-1]
                card_def = library.get_by_id(last_played_id)
                return card_def.element == required_elem
            # Check newly deployed minions (minion cards go to board, not graveyard)
            if pending.position is not None and state.minions:
                # Find minion at the deploy position
                for m in state.minions:
                    if m.position == pending.position:
                        card_def = library.get_by_id(m.card_numeric_id)
                        return card_def.element == required_elem
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
