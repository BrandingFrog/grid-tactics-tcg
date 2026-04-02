"""Action resolver -- validates and applies all main-phase action types.

Main entry point: resolve_action(state, action, library) -> GameState

Handles the 5 main-phase action types:
  - PASS:      No-op, transitions to react window
  - DRAW:      Moves top card from deck to hand
  - MOVE:      Moves minion to adjacent empty cell
  - PLAY_CARD: Deploys minion or casts magic
  - ATTACK:    Simultaneous damage exchange (D-01)

After every action:
  1. Dead minion cleanup (D-02): removes minions with health <= 0
  2. Phase transition to REACT (D-13): opponent gets react window
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from grid_tactics.actions import Action
from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import CardDefinition
from grid_tactics.effect_resolver import resolve_effects_for_trigger
from grid_tactics.enums import (
    ActionType,
    CardType,
    PlayerSide,
    TriggerType,
    TurnPhase,
)
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import BACK_ROW_P1, BACK_ROW_P2, PLAYER_1_ROWS, PLAYER_2_ROWS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _replace_player(
    players: tuple[Player, Player],
    idx: int,
    new_player: Player,
) -> tuple[Player, Player]:
    """Return a new players tuple with one player replaced."""
    if idx == 0:
        return (new_player, players[1])
    return (players[0], new_player)


def _replace_minion(
    minions: tuple[MinionInstance, ...],
    instance_id: int,
    new_minion: MinionInstance,
) -> tuple[MinionInstance, ...]:
    """Return a new minions tuple with one minion replaced by instance_id."""
    return tuple(
        new_minion if m.instance_id == instance_id else m
        for m in minions
    )


def _get_active_side(state: GameState) -> PlayerSide:
    """Return the PlayerSide of the active player."""
    return state.players[state.active_player_idx].side


def _is_orthogonal(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Return True if positions share a row or column (orthogonal alignment)."""
    return a[0] == b[0] or a[1] == b[1]


def _can_attack(
    attacker: MinionInstance,
    defender: MinionInstance,
    attacker_card: CardDefinition,
) -> bool:
    """Check if attacker can reach defender based on attack range (D-03).

    Melee (range=0): manhattan_distance == 1 AND orthogonal (same row or col).
    Ranged (range>=1): (orthogonal AND manhattan_distance <= range) OR
                       (diagonal adjacent, chebyshev_distance == 1).
    """
    a_pos = attacker.position
    d_pos = defender.position
    manhattan = Board.manhattan_distance(a_pos, d_pos)
    chebyshev = Board.chebyshev_distance(a_pos, d_pos)
    attack_range = attacker_card.attack_range

    if attack_range == 0:
        # Melee: orthogonal adjacent only
        return manhattan == 1 and _is_orthogonal(a_pos, d_pos)
    else:
        # Ranged: orthogonal up to N tiles OR diagonal adjacent
        orthogonal_in_range = _is_orthogonal(a_pos, d_pos) and manhattan <= attack_range
        diagonal_adjacent = chebyshev == 1 and not _is_orthogonal(a_pos, d_pos)
        return orthogonal_in_range or diagonal_adjacent


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


def _apply_pass(state: GameState) -> GameState:
    """Apply PASS action. Returns state unchanged (react transition in resolve_action)."""
    return state


def _apply_draw(state: GameState) -> GameState:
    """Apply DRAW action. Moves top card from deck to hand.

    Raises ValueError if the active player's deck is empty.
    """
    player = state.players[state.active_player_idx]
    if not player.deck:
        raise ValueError("Cannot draw from empty deck")
    new_player, _card_id = player.draw_card()
    new_players = _replace_player(state.players, state.active_player_idx, new_player)
    return replace(state, players=new_players)


def _apply_move(state: GameState, action: Action) -> GameState:
    """Apply MOVE action. Moves minion to adjacent empty cell.

    Validates:
      - Minion exists and belongs to active player
      - Target position is orthogonally adjacent
      - Target cell is empty
    """
    active_side = _get_active_side(state)

    # Find the minion
    minion = state.get_minion(action.minion_id)
    if minion is None:
        raise ValueError(f"Minion {action.minion_id} not found")
    if minion.owner != active_side:
        raise ValueError(
            f"Cannot move opponent's minion (belongs to {minion.owner.name})"
        )

    target_pos = action.position
    if target_pos is None:
        raise ValueError("Move action requires a target position")

    # Check orthogonal adjacency
    adjacent = Board.get_orthogonal_adjacent(minion.position)
    if target_pos not in adjacent:
        raise ValueError(
            f"Position {target_pos} is not adjacent to minion at {minion.position}"
        )

    # Check target cell is empty
    if state.board.get(target_pos[0], target_pos[1]) is not None:
        raise ValueError(
            f"Cell {target_pos} is occupied"
        )

    # Update board: remove from old position, place at new position
    new_board = state.board.remove(minion.position[0], minion.position[1])
    new_board = new_board.place(target_pos[0], target_pos[1], minion.instance_id)

    # Update minion position
    new_minion = replace(minion, position=target_pos)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)

    return replace(state, board=new_board, minions=new_minions)


def _apply_play_card(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Apply PLAY_CARD action. Deploys a minion or casts magic.

    Validates:
      - Card exists in hand at card_index
      - Sufficient mana
      - Deployment zone (D-08: melee any friendly row, D-09: ranged back row only)
      - React cards cannot be played during ACTION phase
    """
    active_idx = state.active_player_idx
    player = state.players[active_idx]
    active_side = player.side

    # Get card from hand
    if action.card_index is None or action.card_index < 0 or action.card_index >= len(player.hand):
        raise ValueError(f"Invalid card_index: {action.card_index}")
    card_numeric_id = player.hand[action.card_index]
    card_def = library.get_by_id(card_numeric_id)

    # React cards cannot be played in ACTION phase
    if card_def.card_type == CardType.REACT:
        raise ValueError("React cards cannot be played during ACTION phase")

    # Check mana
    if player.current_mana < card_def.mana_cost:
        raise ValueError(
            f"Insufficient mana: have {player.current_mana}, need {card_def.mana_cost}"
        )

    # Spend mana and remove card from hand (discard to graveyard)
    new_player = player.spend_mana(card_def.mana_cost)
    new_player = new_player.discard_from_hand(card_numeric_id)
    new_players = _replace_player(state.players, active_idx, new_player)
    state = replace(state, players=new_players)

    if card_def.card_type == CardType.MINION:
        return _deploy_minion(state, action, card_def, card_numeric_id, active_side, library)
    elif card_def.card_type == CardType.MAGIC:
        return _cast_magic(state, action, card_def, card_numeric_id, active_side, library)
    else:
        raise ValueError(f"Cannot play card type {card_def.card_type.name} during ACTION phase")


def _deploy_minion(
    state: GameState,
    action: Action,
    card_def: CardDefinition,
    card_numeric_id: int,
    active_side: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """Deploy a minion card to the board.

    D-08: Melee (range=0) can deploy to any empty cell in friendly rows.
    D-09: Ranged (range>=1) must deploy to back row only.
    """
    deploy_pos = action.position
    if deploy_pos is None:
        raise ValueError("Minion deployment requires a position")

    row, col = deploy_pos

    # Validate deployment zone
    if active_side == PlayerSide.PLAYER_1:
        friendly_rows = PLAYER_1_ROWS
        back_row = BACK_ROW_P1
    else:
        friendly_rows = PLAYER_2_ROWS
        back_row = BACK_ROW_P2

    if card_def.attack_range == 0:
        # Melee: any friendly row
        if row not in friendly_rows:
            raise ValueError(
                f"Melee minion must deploy to friendly rows {friendly_rows}, got row {row}"
            )
    else:
        # Ranged: back row only
        if row != back_row:
            raise ValueError(
                f"Ranged minion must deploy to back row {back_row}, got row {row}"
            )

    # Check cell is empty
    if state.board.get(row, col) is not None:
        raise ValueError(f"Cell ({row}, {col}) is occupied")

    # Create the MinionInstance
    minion = MinionInstance(
        instance_id=state.next_minion_id,
        card_numeric_id=card_numeric_id,
        owner=active_side,
        position=deploy_pos,
        current_health=card_def.health,
    )

    # Update board and state
    new_board = state.board.place(row, col, minion.instance_id)
    new_minions = state.minions + (minion,)
    state = replace(
        state,
        board=new_board,
        minions=new_minions,
        next_minion_id=state.next_minion_id + 1,
    )

    # Trigger ON_PLAY effects
    state = resolve_effects_for_trigger(
        state, TriggerType.ON_PLAY, minion, library, action.target_pos,
    )

    return state


def _cast_magic(
    state: GameState,
    action: Action,
    card_def: CardDefinition,
    card_numeric_id: int,
    active_side: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """Cast a magic card. Resolves all ON_PLAY effects, card already discarded.

    Uses a temporary "virtual" minion concept -- magic cards don't go on the board,
    but we need a caster_pos and caster_owner for effect resolution. We use a
    placeholder position (0,0) for the caster since magic doesn't have a board position.
    We call resolve_effect directly via the effect list instead.
    """
    # Magic cards resolve their ON_PLAY effects
    # Since magic doesn't have a minion on board, create a virtual caster context
    caster_pos = action.position if action.position is not None else (0, 0)

    for effect in card_def.effects:
        if effect.trigger == TriggerType.ON_PLAY:
            from grid_tactics.effect_resolver import resolve_effect
            state = resolve_effect(
                state, effect, caster_pos, active_side, library, action.target_pos,
            )

    return state


def _apply_attack(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Apply ATTACK action. Simultaneous damage exchange (D-01).

    Validates:
      - Attacker belongs to active player
      - Defender belongs to opponent
      - Attack range is valid per D-03

    After damage: triggers ON_ATTACK for attacker, ON_DAMAGED for both (if damaged).
    Dead minion cleanup happens in resolve_action after this returns.
    """
    active_side = _get_active_side(state)

    # Find attacker and defender
    attacker = state.get_minion(action.minion_id)
    if attacker is None:
        raise ValueError(f"Attacker minion {action.minion_id} not found")
    if attacker.owner != active_side:
        raise ValueError(
            f"Cannot attack with opponent's minion (belongs to {attacker.owner.name})"
        )

    defender = state.get_minion(action.target_id)
    if defender is None:
        raise ValueError(f"Defender minion {action.target_id} not found")
    if defender.owner == active_side:
        raise ValueError("Cannot attack your own minion")

    # Validate range
    attacker_card = library.get_by_id(attacker.card_numeric_id)
    if not _can_attack(attacker, defender, attacker_card):
        raise ValueError(
            f"Target is out of attack range "
            f"(attacker at {attacker.position}, defender at {defender.position}, "
            f"range={attacker_card.attack_range})"
        )

    # Calculate effective attack values
    defender_card = library.get_by_id(defender.card_numeric_id)
    attacker_effective = attacker_card.attack + attacker.attack_bonus
    defender_effective = defender_card.attack + defender.attack_bonus

    # Simultaneous damage (D-01)
    new_attacker = replace(attacker, current_health=attacker.current_health - defender_effective)
    new_defender = replace(defender, current_health=defender.current_health - attacker_effective)

    new_minions = _replace_minion(state.minions, attacker.instance_id, new_attacker)
    new_minions = _replace_minion(new_minions, defender.instance_id, new_defender)
    state = replace(state, minions=new_minions)

    # Trigger ON_ATTACK effects for attacker
    # Need to refresh attacker reference from state
    updated_attacker = state.get_minion(attacker.instance_id)
    if updated_attacker is not None:
        state = resolve_effects_for_trigger(
            state, TriggerType.ON_ATTACK, updated_attacker, library,
        )

    # Trigger ON_DAMAGED for both if they took damage
    if defender_effective > 0:
        updated_attacker = state.get_minion(attacker.instance_id)
        if updated_attacker is not None:
            state = resolve_effects_for_trigger(
                state, TriggerType.ON_DAMAGED, updated_attacker, library,
            )
    if attacker_effective > 0:
        updated_defender = state.get_minion(defender.instance_id)
        if updated_defender is not None:
            state = resolve_effects_for_trigger(
                state, TriggerType.ON_DAMAGED, updated_defender, library,
            )

    return state


# ---------------------------------------------------------------------------
# Dead minion cleanup (D-02)
# ---------------------------------------------------------------------------


def _cleanup_dead_minions(
    state: GameState, library: CardLibrary,
) -> GameState:
    """Remove dead minions (health <= 0) and trigger on_death effects (D-02).

    1. Find all dead minions (is_alive == False)
    2. Remove them from board and minions tuple
    3. Add their card_numeric_id to their owner's graveyard
    4. Trigger on_death effects in instance_id order (ascending)
    """
    dead_minions = [m for m in state.minions if not m.is_alive]

    if not dead_minions:
        return state

    # Remove dead from board
    new_board = state.board
    for m in dead_minions:
        new_board = new_board.remove(m.position[0], m.position[1])

    # Remove dead from minions tuple
    dead_ids = {m.instance_id for m in dead_minions}
    alive_minions = tuple(m for m in state.minions if m.instance_id not in dead_ids)

    # Add dead minion cards to their owner's graveyard
    new_players = state.players
    for m in dead_minions:
        player_idx = int(m.owner)
        player = new_players[player_idx]
        new_player = replace(player, graveyard=player.graveyard + (m.card_numeric_id,))
        new_players = _replace_player(new_players, player_idx, new_player)

    state = replace(state, board=new_board, minions=alive_minions, players=new_players)

    # Trigger on_death effects in instance_id order (ascending)
    sorted_dead = sorted(dead_minions, key=lambda m: m.instance_id)
    for dead_m in sorted_dead:
        state = resolve_effects_for_trigger(
            state, TriggerType.ON_DEATH, dead_m, library,
        )

    return state


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_action(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Validate and apply a single action, returning a new GameState.

    This is the single entry point for ALL actions. Dispatches based on phase:
      - ACTION phase: main-phase handlers (play card, move, attack, draw, pass)
      - REACT phase: delegates to handle_react_action from react_stack.py

    Flow (ACTION phase):
      1. Dispatch to action handler
      2. Clean up dead minions (D-02)
      3. Transition to REACT phase (D-13)

    Flow (REACT phase):
      Delegates entirely to handle_react_action (PLAY_REACT or PASS).

    Args:
        state: Current game state.
        action: The action to apply.
        library: CardLibrary for card definition lookups.

    Returns:
        New GameState after action processing.

    Raises:
        ValueError: If the action is invalid (wrong phase, illegal action, etc.).
    """
    # REACT phase: delegate to react handler
    if state.phase == TurnPhase.REACT:
        from grid_tactics.react_stack import handle_react_action
        return handle_react_action(state, action, library)

    # Validate ACTION phase
    if state.phase != TurnPhase.ACTION:
        raise ValueError(
            f"Cannot resolve action in phase {state.phase.name}, expected ACTION"
        )

    # Dispatch to action handler
    if action.action_type == ActionType.PASS:
        state = _apply_pass(state)
    elif action.action_type == ActionType.DRAW:
        state = _apply_draw(state)
    elif action.action_type == ActionType.MOVE:
        state = _apply_move(state, action)
    elif action.action_type == ActionType.PLAY_CARD:
        state = _apply_play_card(state, action, library)
    elif action.action_type == ActionType.ATTACK:
        state = _apply_attack(state, action, library)
    else:
        raise ValueError(f"Unsupported action type for main phase: {action.action_type}")

    # Dead minion cleanup (D-02)
    state = _cleanup_dead_minions(state, library)

    # Transition to REACT phase (D-13)
    state = replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1 - state.active_player_idx,
        pending_action=action,
    )

    return state
