"""Effect resolution engine -- declarative interpretation of EffectDefinition.

Resolves effects by dispatching on EffectType and TargetType. All operations
are pure functions that take a GameState and return a new GameState. No
mutation occurs -- immutability is preserved throughout.

Two main entry points:
  - resolve_effect(): Apply a single EffectDefinition to the game state.
  - resolve_effects_for_trigger(): Apply all effects matching a trigger on a minion's card.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Optional

from grid_tactics.board import Board
from grid_tactics.card_library import CardLibrary
from grid_tactics.cards import EffectDefinition
from grid_tactics.enums import EffectType, PlayerSide, TargetType, TriggerType
from grid_tactics.game_state import GameState
from grid_tactics.minion import MinionInstance
from grid_tactics.player import Player
from grid_tactics.types import STARTING_HP


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _replace_player(
    players: tuple[Player, Player],
    idx: int,
    new_player: Player,
) -> tuple[Player, Player]:
    """Return a new players tuple with one player replaced."""
    if idx == 0:
        return (new_player, players[1])
    return (players[0], new_player)


def _find_minion_at_pos(
    minions: tuple[MinionInstance, ...],
    pos: tuple[int, int],
) -> Optional[MinionInstance]:
    """Find a minion at the given position, or None."""
    for m in minions:
        if m.position == pos:
            return m
    return None


def _player_index_for_side(side: PlayerSide) -> int:
    """Return the player tuple index for a PlayerSide."""
    return int(side)


# ---------------------------------------------------------------------------
# Effect application helpers (per EffectType)
# ---------------------------------------------------------------------------


def _apply_damage_to_minion(
    state: GameState, minion: MinionInstance, amount: int,
) -> GameState:
    """Apply damage to a minion, reducing current_health."""
    new_minion = replace(minion, current_health=minion.current_health - amount)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_heal_to_minion(
    state: GameState, minion: MinionInstance, amount: int, library: CardLibrary,
) -> GameState:
    """Apply heal to a minion, capped at base health from CardDefinition."""
    card_def = library.get_by_id(minion.card_numeric_id)
    base_health = card_def.health
    new_health = min(minion.current_health + amount, base_health)
    new_minion = replace(minion, current_health=new_health)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_buff_attack_to_minion(
    state: GameState, minion: MinionInstance, amount: int,
) -> GameState:
    """Increase a minion's attack_bonus."""
    new_minion = replace(minion, attack_bonus=minion.attack_bonus + amount)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_buff_health_to_minion(
    state: GameState, minion: MinionInstance, amount: int,
) -> GameState:
    """Increase a minion's current_health (no cap -- buff_health can exceed base)."""
    new_minion = replace(minion, current_health=minion.current_health + amount)
    new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
    return replace(state, minions=new_minions)


def _apply_effect_to_minion(
    state: GameState,
    effect: EffectDefinition,
    minion: MinionInstance,
    library: CardLibrary,
) -> GameState:
    """Apply an effect to a single minion based on effect_type."""
    if effect.effect_type == EffectType.DAMAGE:
        return _apply_damage_to_minion(state, minion, effect.amount)
    elif effect.effect_type == EffectType.HEAL:
        return _apply_heal_to_minion(state, minion, effect.amount, library)
    elif effect.effect_type == EffectType.BUFF_ATTACK:
        return _apply_buff_attack_to_minion(state, minion, effect.amount)
    elif effect.effect_type == EffectType.BUFF_HEALTH:
        return _apply_buff_health_to_minion(state, minion, effect.amount)
    else:
        raise ValueError(f"Unknown effect type: {effect.effect_type}")


def _apply_effect_to_player(
    state: GameState,
    effect: EffectDefinition,
    player_idx: int,
) -> GameState:
    """Apply an effect to a player (DAMAGE or HEAL only)."""
    player = state.players[player_idx]
    if effect.effect_type == EffectType.DAMAGE:
        new_player = player.take_damage(effect.amount)
    elif effect.effect_type == EffectType.HEAL:
        new_hp = min(player.hp + effect.amount, STARTING_HP)
        new_player = replace(player, hp=new_hp)
    else:
        raise ValueError(
            f"Cannot apply {effect.effect_type.name} to a player"
        )
    new_players = _replace_player(state.players, player_idx, new_player)
    return replace(state, players=new_players)


# ---------------------------------------------------------------------------
# Target resolution (per TargetType)
# ---------------------------------------------------------------------------


def _resolve_single_target(
    state: GameState,
    effect: EffectDefinition,
    library: CardLibrary,
    target_pos: Optional[tuple[int, int]],
) -> GameState:
    """Resolve effect on a single target at target_pos."""
    if target_pos is None:
        # No valid target — skip effect (e.g., minion deployed with no enemies)
        return state
    minion = _find_minion_at_pos(state.minions, target_pos)
    if minion is None:
        return state  # no minion at position, state unchanged
    return _apply_effect_to_minion(state, effect, minion, library)


def _resolve_all_enemies(
    state: GameState,
    effect: EffectDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """Resolve effect on all enemy minions."""
    for minion in state.minions:
        if minion.owner != caster_owner:
            state = _apply_effect_to_minion(state, effect, minion, library)
    return state


def _resolve_adjacent(
    state: GameState,
    effect: EffectDefinition,
    caster_pos: tuple[int, int],
    library: CardLibrary,
) -> GameState:
    """Resolve effect on all minions adjacent (orthogonal + diagonal) to caster_pos."""
    adjacent_positions = Board.get_all_adjacent(caster_pos)
    for minion in state.minions:
        if minion.position in adjacent_positions:
            state = _apply_effect_to_minion(state, effect, minion, library)
    return state


def _resolve_self_owner(
    state: GameState,
    effect: EffectDefinition,
    caster_pos: tuple[int, int],
    caster_owner: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """Resolve effect on the caster's minion or the owning player.

    For minion-targeting effects (BUFF_ATTACK, BUFF_HEALTH): target the minion at caster_pos.
    For player-targeting effects (DAMAGE, HEAL): target the owning player.
    """
    if effect.effect_type in (EffectType.DAMAGE, EffectType.HEAL):
        # Target the owning player
        player_idx = _player_index_for_side(caster_owner)
        return _apply_effect_to_player(state, effect, player_idx)
    else:
        # Target the caster's minion at caster_pos
        minion = _find_minion_at_pos(state.minions, caster_pos)
        if minion is None:
            return state  # no minion at caster_pos, unchanged
        return _apply_effect_to_minion(state, effect, minion, library)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_effect(
    state: GameState,
    effect: EffectDefinition,
    caster_pos: tuple[int, int],
    caster_owner: PlayerSide,
    library: CardLibrary,
    target_pos: Optional[tuple[int, int]] = None,
) -> GameState:
    """Resolve a single effect, returning a new GameState.

    Dispatches on effect.target (TargetType) to determine which entities
    are affected, then on effect.effect_type (EffectType) to determine
    the modification.

    Args:
        state: Current game state.
        effect: The effect definition to resolve.
        caster_pos: Position of the caster (minion or card source).
        caster_owner: Which player owns the caster.
        library: CardLibrary for looking up base stats (heal caps).
        target_pos: Target position for SINGLE_TARGET effects.

    Returns:
        New GameState with effect applied.

    Raises:
        ValueError: If target_pos is None for SINGLE_TARGET effects.
    """
    if effect.target == TargetType.SINGLE_TARGET:
        return _resolve_single_target(state, effect, library, target_pos)
    elif effect.target == TargetType.ALL_ENEMIES:
        return _resolve_all_enemies(state, effect, caster_owner, library)
    elif effect.target == TargetType.ADJACENT:
        return _resolve_adjacent(state, effect, caster_pos, library)
    elif effect.target == TargetType.SELF_OWNER:
        return _resolve_self_owner(state, effect, caster_pos, caster_owner, library)
    else:
        raise ValueError(f"Unknown target type: {effect.target}")


def resolve_effects_for_trigger(
    state: GameState,
    trigger: TriggerType,
    minion: MinionInstance,
    library: CardLibrary,
    target_pos: Optional[tuple[int, int]] = None,
) -> GameState:
    """Resolve all effects on a minion's card that match the given trigger.

    Effects are processed in the order they appear in the card's effects tuple.

    Args:
        state: Current game state.
        trigger: Which trigger to filter for.
        minion: The minion whose card effects to check.
        library: CardLibrary for card definition lookup.
        target_pos: Optional target position for SINGLE_TARGET effects.

    Returns:
        New GameState with all matching effects applied in order.
    """
    card_def = library.get_by_id(minion.card_numeric_id)
    matching_effects = [e for e in card_def.effects if e.trigger == trigger]

    if not matching_effects:
        return state  # no matching effects, return unchanged

    for effect in matching_effects:
        state = resolve_effect(
            state, effect, minion.position, minion.owner, library, target_pos,
        )
    return state
