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
    """Apply PASS action. Only triggers when no other actions available.

    Applies escalating fatigue damage: 10, 20, 30...
    Fatigue counts are stored in GameState.fatigue_counts (per-player tuple)
    instead of a module-level dict, ensuring concurrent game safety.
    """
    active_idx = state.active_player_idx
    player = state.players[active_idx]
    counts = list(state.fatigue_counts)
    counts[active_idx] += 1
    dmg = counts[active_idx] * 10
    new_player = replace(player, hp=player.hp - dmg)
    new_players = _replace_player(state.players, active_idx, new_player)
    return replace(state, players=new_players, fatigue_counts=tuple(counts))


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


def _apply_move(state: GameState, action: Action, library: CardLibrary = None) -> GameState:
    """Apply MOVE action. Moves minion forward one cell in its lane.

    Validates:
      - Minion exists and belongs to active player
      - Target position is forward-only in the same column (lane-locked)
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

    # Lane-locked: must stay in the same column
    src_row, src_col = minion.position
    tgt_row, tgt_col = target_pos
    if tgt_col != src_col:
        raise ValueError(
            f"Lane-locked: cannot move laterally from col {src_col} to col {tgt_col}"
        )

    # Forward-only: P1 moves down (+1 row), P2 moves up (-1 row).
    # LEAP minions may move multiple tiles forward in the same column when
    # the immediate forward tile is blocked. We delegate the geometry check
    # to the legal-actions enumerator (legal_actions.py) and just verify
    # here that the target row is in the forward direction and reachable.
    delta = 1 if active_side == PlayerSide.PLAYER_1 else -1
    if (tgt_row - src_row) * delta <= 0:
        raise ValueError(
            f"Forward-only: {active_side.name} at row {src_row} must move "
            f"forward (delta={delta}), not to row {tgt_row}"
        )
    # Single-step is always allowed when target is empty (handled below).
    # Multi-step (leap) requires a LEAP effect on the minion's card AND the
    # immediate forward tile to be blocked.
    if abs(tgt_row - src_row) > 1:
        if library is None:
            raise ValueError("Multi-tile move requires library for LEAP validation")
        from grid_tactics.enums import EffectType as _ET
        minion_card = library.get_by_id(minion.card_numeric_id)
        leap_amount = 0
        for eff in minion_card.effects:
            if eff.effect_type == _ET.LEAP:
                leap_amount = max(leap_amount, eff.amount or 1)
        if leap_amount <= 0:
            raise ValueError(
                f"Minion {minion.instance_id} has no LEAP -- cannot multi-step move"
            )
        # Verify the immediate forward tile is occupied (precondition for leap)
        first_step_row = src_row + delta
        if state.board.get(first_step_row, src_col) is None:
            raise ValueError("LEAP only legal when the forward tile is blocked")
        # Leap distance cap: 1 (the immediate blocker) + leap_amount additional
        if abs(tgt_row - src_row) > 1 + leap_amount:
            raise ValueError("LEAP target row exceeds leap distance")

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
    state = replace(state, board=new_board, minions=new_minions)

    # Phase 14.1: For melee (range=0) minions, if there is at least one
    # in-range enemy from the new tile, enter pending-post-move-attack state.
    # The player must then ATTACK or DECLINE_POST_MOVE_ATTACK as the
    # continuation of the same logical action (single react window).
    if library is not None:
        attacker_card = library.get_by_id(new_minion.card_numeric_id)
        if attacker_card.attack_range == 0 and _has_any_attack_target(state, new_minion, library):
            state = replace(state, pending_post_move_attacker_id=new_minion.instance_id)

    return state


def _has_any_attack_target(
    state: GameState, attacker_minion: MinionInstance, library: CardLibrary,
) -> bool:
    """Return True if attacker has at least one in-range enemy from current tile."""
    attacker_card = library.get_by_id(attacker_minion.card_numeric_id)
    for m in state.minions:
        if m.owner == attacker_minion.owner:
            continue
        if _can_attack(attacker_minion, m, attacker_card):
            return True
    return False


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

    # Summon sacrifice: discard a card of the required tribe from hand.
    # Use the user's chosen sacrifice_card_index if provided; otherwise auto-pick first.
    if card_def.summon_sacrifice_tribe:
        sacrifice_id = None
        if action.sacrifice_card_index is not None:
            # Note: action.sacrifice_card_index references the ORIGINAL hand
            # (before this card was discarded). We recompute the index
            # by using the original `player.hand`, since `new_player.hand`
            # has the played card removed.
            sac_idx = action.sacrifice_card_index
            if 0 <= sac_idx < len(player.hand):
                candidate_id = player.hand[sac_idx]
                # Verify it's still in new_player.hand and tribe matches
                cand_def = library.get_by_id(candidate_id)
                if cand_def.tribe == card_def.summon_sacrifice_tribe and candidate_id in new_player.hand:
                    sacrifice_id = candidate_id
        if sacrifice_id is None:
            # Fallback: auto-pick first matching card
            for hand_card_id in new_player.hand:
                hand_card_def = library.get_by_id(hand_card_id)
                if hand_card_def.tribe == card_def.summon_sacrifice_tribe:
                    sacrifice_id = hand_card_id
                    break
        if sacrifice_id is None:
            raise ValueError(
                f"No {card_def.summon_sacrifice_tribe} card in hand to sacrifice"
            )
        new_player = new_player.discard_from_hand(sacrifice_id)

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


def _apply_sacrifice(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Apply SACRIFICE action. Remove minion from board and deal damage to opponent.

    Validates:
      - Minion exists and belongs to active player
      - Minion is on opponent's back row (P1 minion at row 4, P2 minion at row 0)

    After validation:
      1. Look up card definition for base attack
      2. Calculate effective attack (base + attack_bonus)
      3. Remove minion from board and minions tuple
      4. Add minion's card to owner's graveyard
      5. Deal effective attack as damage to opponent
    """
    active_side = _get_active_side(state)

    # Find the minion
    minion = state.get_minion(action.minion_id)
    if minion is None:
        raise ValueError(f"Minion {action.minion_id} not found")
    if minion.owner != active_side:
        raise ValueError(
            f"Cannot sacrifice opponent's minion (belongs to {minion.owner.name})"
        )

    # Validate minion is on opponent's back row
    row = minion.position[0]
    if active_side == PlayerSide.PLAYER_1:
        if row != BACK_ROW_P2:
            raise ValueError(
                f"P1 minion must be on opponent's back row {BACK_ROW_P2} to sacrifice, "
                f"got row {row}"
            )
    else:
        if row != BACK_ROW_P1:
            raise ValueError(
                f"P2 minion must be on opponent's back row {BACK_ROW_P1} to sacrifice, "
                f"got row {row}"
            )

    # Look up card definition for base attack
    card_def = library.get_by_id(minion.card_numeric_id)
    effective_attack = card_def.attack + minion.attack_bonus

    # Remove minion from board
    new_board = state.board.remove(minion.position[0], minion.position[1])

    # Remove minion from minions tuple
    new_minions = tuple(m for m in state.minions if m.instance_id != minion.instance_id)

    # Add card to owner's graveyard
    owner_idx = int(minion.owner)
    owner_player = state.players[owner_idx]
    new_owner = replace(owner_player, graveyard=owner_player.graveyard + (minion.card_numeric_id,))
    new_players = _replace_player(state.players, owner_idx, new_owner)

    # Deal damage to opponent
    opponent_idx = 1 - state.active_player_idx
    opponent = new_players[opponent_idx]
    new_opponent = opponent.take_damage(effective_attack)
    new_players = _replace_player(new_players, opponent_idx, new_opponent)

    return replace(state, board=new_board, minions=new_minions, players=new_players)


def _apply_transform(
    state: GameState, action: Action, library: CardLibrary,
) -> GameState:
    """Apply TRANSFORM action: convert a board minion into a different card form.

    Validates:
      - Minion exists and belongs to active player
      - Source card has transform_options containing the requested transform_target
      - Active player has enough mana for the transform cost

    Effect:
      - Spends mana
      - Replaces the minion's card_numeric_id with the target form
      - Resets current_health to the new form's max HP
      - Resets attack_bonus to 0
    """
    active_side = _get_active_side(state)
    active_idx = state.active_player_idx

    minion = state.get_minion(action.minion_id)
    if minion is None:
        raise ValueError(f"Minion {action.minion_id} not found")
    if minion.owner != active_side:
        raise ValueError(
            f"Cannot transform opponent's minion (belongs to {minion.owner.name})"
        )

    source_card = library.get_by_id(minion.card_numeric_id)
    if not source_card.transform_options:
        raise ValueError(f"Minion {source_card.card_id} has no transform options")

    if action.transform_target is None:
        raise ValueError("TRANSFORM action missing transform_target")

    # Find the target in the source's transform_options
    matched_cost = None
    for target_card_id, mana_cost in source_card.transform_options:
        if target_card_id == action.transform_target:
            matched_cost = mana_cost
            break
    if matched_cost is None:
        raise ValueError(
            f"{source_card.card_id} cannot transform into {action.transform_target}"
        )

    # Mana check
    player = state.players[active_idx]
    if player.current_mana < matched_cost:
        raise ValueError(
            f"Insufficient mana to transform: have {player.current_mana}, need {matched_cost}"
        )

    # Look up target card
    try:
        target_numeric_id = library.get_numeric_id(action.transform_target)
    except KeyError:
        raise ValueError(f"Transform target card '{action.transform_target}' not in library")
    target_card = library.get_by_id(target_numeric_id)

    # Spend mana
    new_player = player.spend_mana(matched_cost)
    new_players = _replace_player(state.players, active_idx, new_player)

    # Replace minion stats
    new_minion = replace(
        minion,
        card_numeric_id=target_numeric_id,
        current_health=target_card.health,
        attack_bonus=0,
    )
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)

    return replace(state, players=new_players, minions=new_minions)


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

    # Range combat: shorter range at current distance = first strike
    dist = Board.manhattan_distance(attacker.position, defender.position)
    atk_range = attacker_card.attack_range or 0
    def_range = defender_card.attack_range or 0

    # Can defender retaliate at this distance?
    def_can_reach = (def_range == 0 and dist <= 1) or (def_range > 0 and dist <= def_range)

    # First strike: attacker has strictly shorter range = faster/closer unit
    attacker_strikes_first = atk_range < def_range and def_can_reach

    if not def_can_reach:
        # Defender can't reach: attacker hits, no retaliation
        new_defender = replace(defender, current_health=defender.current_health - attacker_effective)
        new_minions = _replace_minion(state.minions, attacker.instance_id, attacker)
        new_minions = _replace_minion(new_minions, defender.instance_id, new_defender)
    elif attacker_strikes_first:
        # Attacker hits first, defender retaliates if alive
        new_defender = replace(defender, current_health=defender.current_health - attacker_effective)
        if new_defender.current_health > 0:
            new_attacker = replace(attacker, current_health=attacker.current_health - defender_effective)
        else:
            new_attacker = attacker  # defender died, no retaliation
        new_minions = _replace_minion(state.minions, attacker.instance_id, new_attacker)
        new_minions = _replace_minion(new_minions, new_defender.instance_id, new_defender)
    else:
        # Simultaneous damage
        new_attacker = replace(attacker, current_health=attacker.current_health - defender_effective)
        new_defender = replace(defender, current_health=defender.current_health - attacker_effective)
        new_minions = _replace_minion(state.minions, attacker.instance_id, new_attacker)
        new_minions = _replace_minion(new_minions, defender.instance_id, new_defender)

    state = replace(state, minions=new_minions)

    # Trigger ON_ATTACK effects for attacker
    # Need to refresh attacker reference from state.
    # Pass defender.position as target_pos so SINGLE_TARGET on_attack effects
    # (e.g. Pyre Archer's burn) land on the attacked minion.
    updated_attacker = state.get_minion(attacker.instance_id)
    if updated_attacker is not None:
        state = resolve_effects_for_trigger(
            state, TriggerType.ON_ATTACK, updated_attacker, library,
            target_pos=defender.position,
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
# Win/draw detection (Phase 4)
# ---------------------------------------------------------------------------


def _check_game_over(state: GameState) -> GameState:
    """Check if the game is over (any player dead) and set winner/is_game_over.

    Called after dead minion cleanup and after react stack resolution.
    - Both dead: draw (is_game_over=True, winner=None)
    - P1 dead: P2 wins
    - P2 dead: P1 wins
    - Neither dead: no change
    """
    p1_alive = state.players[0].is_alive
    p2_alive = state.players[1].is_alive

    if p1_alive and p2_alive:
        return state

    if not p1_alive and not p2_alive:
        # Draw: both dead simultaneously
        return replace(state, is_game_over=True, winner=None)
    elif not p1_alive:
        return replace(state, is_game_over=True, winner=PlayerSide.PLAYER_2)
    else:
        return replace(state, is_game_over=True, winner=PlayerSide.PLAYER_1)


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

    # Phase 14.2: pending-tutor gate.
    # If a card with TUTOR on_play just played and matches exist in deck, the
    # caster MUST TUTOR_SELECT (with index into pending_tutor_matches) or
    # DECLINE_TUTOR. Anything else is illegal. The single react window for
    # the original play fires AFTER the pending clears.
    if state.pending_tutor_player_idx is not None:
        # Mutex defense
        assert state.pending_post_move_attacker_id is None, (
            "pending_tutor and pending_post_move_attacker cannot coexist"
        )
        if action.action_type == ActionType.TUTOR_SELECT:
            match_idx = action.card_index  # reuse card_index payload
            if match_idx is None or match_idx < 0 or match_idx >= len(state.pending_tutor_matches):
                raise ValueError(
                    f"TUTOR_SELECT: invalid match index {match_idx}; "
                    f"have {len(state.pending_tutor_matches)} matches"
                )
            deck_idx = state.pending_tutor_matches[match_idx]
            caster_idx = state.pending_tutor_player_idx
            caster = state.players[caster_idx]
            if deck_idx < 0 or deck_idx >= len(caster.deck):
                raise ValueError(
                    f"TUTOR_SELECT: stale deck index {deck_idx} (deck size {len(caster.deck)})"
                )
            chosen_card = caster.deck[deck_idx]
            new_deck = caster.deck[:deck_idx] + caster.deck[deck_idx + 1:]
            new_caster = replace(
                caster,
                deck=new_deck,
                hand=caster.hand + (chosen_card,),
            )
            new_players = _replace_player(state.players, caster_idx, new_caster)
            state = replace(
                state,
                players=new_players,
                pending_tutor_player_idx=None,
                pending_tutor_matches=(),
            )
        elif action.action_type == ActionType.DECLINE_TUTOR:
            state = replace(
                state,
                pending_tutor_player_idx=None,
                pending_tutor_matches=(),
            )
        else:
            raise ValueError(
                "Pending tutor: must TUTOR_SELECT or DECLINE_TUTOR"
            )

        # Single react window for the original on_play fires now.
        state = _cleanup_dead_minions(state, library)
        state = _check_game_over(state)
        if state.is_game_over:
            return state
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            pending_action=action,
        )
        return state

    # Not in pending tutor: TUTOR_SELECT / DECLINE_TUTOR are illegal
    if action.action_type in (ActionType.TUTOR_SELECT, ActionType.DECLINE_TUTOR):
        raise ValueError(
            f"{action.action_type.name} only legal during pending_tutor state"
        )

    # Phase 14.1: pending-post-move-attack gate.
    # If a melee minion just moved and has in-range targets, the player MUST
    # either ATTACK with that minion or DECLINE_POST_MOVE_ATTACK. Anything
    # else is illegal. The combined move+attack/decline counts as ONE
    # logical action, so the react window only fires after this resolves.
    if state.pending_post_move_attacker_id is not None:
        pending_id = state.pending_post_move_attacker_id
        if action.action_type == ActionType.ATTACK:
            if action.minion_id != pending_id:
                raise ValueError(
                    "Pending post-move attack: must ATTACK with the moved minion or DECLINE"
                )
            state = _apply_attack(state, action, library)
            state = replace(state, pending_post_move_attacker_id=None)
        elif action.action_type == ActionType.DECLINE_POST_MOVE_ATTACK:
            state = replace(state, pending_post_move_attacker_id=None)
        else:
            raise ValueError(
                "Pending post-move attack: must ATTACK with the moved minion or DECLINE"
            )

        # Dead minion cleanup + game-over check, then react window (single).
        state = _cleanup_dead_minions(state, library)
        state = _check_game_over(state)
        if state.is_game_over:
            return state
        state = replace(
            state,
            phase=TurnPhase.REACT,
            react_player_idx=1 - state.active_player_idx,
            pending_action=action,
        )
        return state

    # Not in pending state: DECLINE is illegal
    if action.action_type == ActionType.DECLINE_POST_MOVE_ATTACK:
        raise ValueError("DECLINE_POST_MOVE_ATTACK only legal in pending post-move state")

    # Dispatch to action handler
    if action.action_type == ActionType.PASS:
        state = _apply_pass(state)
    elif action.action_type == ActionType.DRAW:
        state = _apply_draw(state)
    elif action.action_type == ActionType.MOVE:
        state = _apply_move(state, action, library)
    elif action.action_type == ActionType.PLAY_CARD:
        state = _apply_play_card(state, action, library)
    elif action.action_type == ActionType.ATTACK:
        state = _apply_attack(state, action, library)
    elif action.action_type == ActionType.SACRIFICE:
        state = _apply_sacrifice(state, action, library)
    elif action.action_type == ActionType.TRANSFORM:
        state = _apply_transform(state, action, library)
    else:
        raise ValueError(f"Unsupported action type for main phase: {action.action_type}")

    # Dead minion cleanup (D-02)
    state = _cleanup_dead_minions(state, library)

    # Win/draw detection (Phase 4) -- after cleanup, before react transition
    state = _check_game_over(state)
    if state.is_game_over:
        return state

    # Phase 14.1: If MOVE entered pending-post-move-attack state, do NOT
    # fire the react window yet. The react window fires after the player
    # resolves with ATTACK or DECLINE_POST_MOVE_ATTACK.
    if state.pending_post_move_attacker_id is not None:
        return state

    # Phase 14.2: If PLAY_CARD on_play entered pending_tutor state, defer
    # the react window until TUTOR_SELECT/DECLINE_TUTOR clears it. One react
    # window per logical card play.
    if state.pending_tutor_player_idx is not None:
        return state

    # Transition to REACT phase (D-13)
    state = replace(
        state,
        phase=TurnPhase.REACT,
        react_player_idx=1 - state.active_player_idx,
        pending_action=action,
    )

    return state
