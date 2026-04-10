"""Action dataclass -- structured representation of player actions.

Actions are structured tuples (per D-17) representing what a player does
on their turn. Each action has an ActionType and optional fields depending
on the type:

- PASS: no additional fields
- DRAW: no additional fields
- MOVE: minion_id + position (destination)
- ATTACK: minion_id + target_id
- PLAY_CARD: card_index + position (deploy location) + target_pos (effect target)
- PLAY_REACT: card_index + target_pos (effect target)

Structured actions can be mapped to flat integer IDs for RL (Phase 5, D-18).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from grid_tactics.enums import ActionType


@dataclass(frozen=True, slots=True)
class Action:
    """Immutable structured action (D-17).

    All fields except action_type are optional -- only relevant fields
    are set for each action type.
    """

    action_type: ActionType
    card_index: Optional[int] = None       # index into player's hand tuple
    position: Optional[tuple[int, int]] = None   # target position for deploy/move
    minion_id: Optional[int] = None        # which minion to move/attack with
    target_id: Optional[int] = None        # target minion ID for attack
    target_pos: Optional[tuple[int, int]] = None  # target position for effects
    sacrifice_card_index: Optional[int] = None  # for PLAY_CARD with summon_sacrifice_tribe
    transform_target: Optional[str] = None  # for TRANSFORM action: target card_id


# ---------------------------------------------------------------------------
# Convenience constructors (module-level functions)
# ---------------------------------------------------------------------------


def pass_action() -> Action:
    """Create a PASS action (always legal per D-16)."""
    return Action(action_type=ActionType.PASS)


def draw_action() -> Action:
    """Create a DRAW action (costs an action per D-15)."""
    return Action(action_type=ActionType.DRAW)


def decline_post_move_attack_action() -> Action:
    """Create a DECLINE_POST_MOVE_ATTACK action (Phase 14.1).

    Only legal while ``state.pending_post_move_attacker_id`` is set. Encoded
    on the integer action space by reusing slot 1001 (PASS); the encoder
    disambiguates from PASS via the pending state at decode time.
    """
    return Action(action_type=ActionType.DECLINE_POST_MOVE_ATTACK)


def tutor_select_action(match_index: int) -> Action:
    """Create a TUTOR_SELECT action (Phase 14.2).

    Only legal while ``state.pending_tutor_player_idx`` is set. ``match_index``
    is reused on the ``card_index`` field and indexes into
    ``state.pending_tutor_matches``. Encoded on the integer action space by
    reusing the PLAY_CARD slot space [0:250]; the encoder disambiguates from
    PLAY_CARD via the pending state at decode time.
    """
    return Action(action_type=ActionType.TUTOR_SELECT, card_index=match_index)


def decline_tutor_action() -> Action:
    """Create a DECLINE_TUTOR action (Phase 14.2).

    Only legal while ``state.pending_tutor_player_idx`` is set. Encoded on the
    integer action space by reusing slot 1001 (PASS); the encoder
    disambiguates from PASS via the pending state at decode time.
    """
    return Action(action_type=ActionType.DECLINE_TUTOR)


def move_action(minion_id: int, position: tuple[int, int]) -> Action:
    """Create a MOVE action for a minion to a destination position."""
    return Action(action_type=ActionType.MOVE, minion_id=minion_id, position=position)


def attack_action(minion_id: int, target_id: int) -> Action:
    """Create an ATTACK action from one minion against another."""
    return Action(action_type=ActionType.ATTACK, minion_id=minion_id, target_id=target_id)


def play_card_action(
    card_index: int,
    position: Optional[tuple[int, int]] = None,
    target_pos: Optional[tuple[int, int]] = None,
) -> Action:
    """Create a PLAY_CARD action (deploy minion or cast magic).

    position: deployment location for minions.
    target_pos: target position for targeted effects.
    """
    return Action(
        action_type=ActionType.PLAY_CARD,
        card_index=card_index,
        position=position,
        target_pos=target_pos,
    )


def sacrifice_action(minion_id: int) -> Action:
    """Create a SACRIFICE action for a minion on the opponent's back row.

    The minion is removed from the board and deals its effective attack
    as damage to the opponent's HP.
    """
    return Action(action_type=ActionType.SACRIFICE, minion_id=minion_id)


def play_react_action(
    card_index: int,
    target_pos: Optional[tuple[int, int]] = None,
) -> Action:
    """Create a PLAY_REACT action during the react window.

    card_index: index into the reacting player's hand.
    target_pos: target position for targeted react effects.
    """
    return Action(
        action_type=ActionType.PLAY_REACT,
        card_index=card_index,
        target_pos=target_pos,
    )


def conjure_deploy_action(position: tuple[int, int]) -> Action:
    """Create a CONJURE_DEPLOY action (Phase 14.6).

    Only legal while ``state.pending_conjure_deploy_card`` is set.
    ``position`` is the board tile to deploy the conjured card onto.
    Encoded on the integer action space by reusing the PLAY_CARD slot
    space [0:250]; the encoder disambiguates via the pending state.
    """
    return Action(action_type=ActionType.CONJURE_DEPLOY, position=position)


def decline_conjure_action() -> Action:
    """Create a DECLINE_CONJURE action (Phase 14.6).

    Only legal while ``state.pending_conjure_deploy_card`` is set.
    The conjured card goes to hand instead of to the field.
    Encoded on slot 1001 (PASS); disambiguated via pending state.
    """
    return Action(action_type=ActionType.DECLINE_CONJURE)


def transform_action(
    minion_id: int,
    transform_target: str,
) -> Action:
    """Create a TRANSFORM action: pay mana to transform a board minion into another card.

    minion_id: instance_id of the minion to transform.
    transform_target: card_id of the target form (must be in the source minion's
                      transform_options list).
    """
    return Action(
        action_type=ActionType.TRANSFORM,
        minion_id=minion_id,
        transform_target=transform_target,
    )
