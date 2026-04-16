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
from grid_tactics.cards import CardDefinition, EffectDefinition
from grid_tactics.enums import EffectType, Element, PlayerSide, TargetType, TriggerType
from grid_tactics.game_state import GameState, PendingDeathTarget
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


def _check_placement_condition(
    state, caster_pos: tuple[int, int], caster_owner: PlayerSide,
    condition: str, library,
) -> bool:
    """Check if a placement condition is met for the minion at caster_pos."""
    if condition == "front_of_dark_ranged":
        # Check if there's a friendly dark ranged minion directly behind this position.
        # "In front of X" = this minion is forward of X, so X is behind.
        # P1 forward = +row, so behind = row-1. P2 forward = -row, so behind = row+1.
        row, col = caster_pos
        behind_row = row - 1 if caster_owner == PlayerSide.PLAYER_1 else row + 1
        if behind_row < 0 or behind_row > 4:
            return False
        ally = _find_minion_at_pos(state.minions, (behind_row, col))
        if ally is None or ally.owner != caster_owner:
            return False
        ally_def = library.get_by_id(ally.card_numeric_id)
        return (ally_def.element == Element.DARK and ally_def.attack_range >= 1)
    return False


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
    """Apply heal to a minion, capped at effective max HP.

    Effective max HP = CardDefinition.health + max_health_bonus so that
    flat max-HP buffs (e.g. Ratchanter's conjure_rat_and_buff) raise the
    heal ceiling too.
    """
    card_def = library.get_by_id(minion.card_numeric_id)
    effective_max = card_def.health + minion.max_health_bonus
    new_health = min(minion.current_health + amount, effective_max)
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
    """Apply an effect to a single minion based on effect_type.

    Effect types that don't apply to a minion (CONJURE, TUTOR, RALLY,
    NEGATE, DEPLOY_SELF, LEAP, DARK_MATTER_BUFF) are silently skipped
    here — they're handled by other code paths or are informational/
    state markers that don't mutate minion stats directly. PROMOTE
    is handled by ``_apply_promote_on_death`` dispatched from
    ``resolve_effects_for_trigger``; it transforms a friendly minion
    rather than mutating the dying one, so it doesn't fit this helper.
    """
    if effect.effect_type == EffectType.DAMAGE:
        return _apply_damage_to_minion(state, minion, effect.amount)
    elif effect.effect_type == EffectType.HEAL:
        return _apply_heal_to_minion(state, minion, effect.amount, library)
    elif effect.effect_type == EffectType.BUFF_ATTACK:
        return _apply_buff_attack_to_minion(state, minion, effect.amount)
    elif effect.effect_type == EffectType.BUFF_HEALTH:
        return _apply_buff_health_to_minion(state, minion, effect.amount)
    elif effect.effect_type == EffectType.DESTROY:
        new_minion = replace(minion, current_health=0)
        new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
        return replace(state, minions=new_minions)
    elif effect.effect_type == EffectType.BURN:
        # Boolean burn aura: set is_burning=True. No-op if already burning
        # (no refresh, no stacks). Burn persists until death.
        if minion.is_burning:
            return state
        new_minion = replace(minion, is_burning=True)
        new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
        return replace(state, minions=new_minions)
    elif effect.effect_type == EffectType.PASSIVE_HEAL:
        # Heal self by `amount`, capped at base health.
        return _apply_heal_to_minion(state, minion, effect.amount, library)
    elif effect.effect_type == EffectType.APPLY_BURNING:
        # Boolean burn: set is_burning=True. No-op if already burning.
        if minion.is_burning:
            return state
        new_minion = replace(minion, is_burning=True)
        new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
        return replace(state, minions=new_minions)
    elif effect.effect_type == EffectType.GRANT_DARK_MATTER:
        # Add `amount` Dark Matter stacks to the target minion. Stacks
        # additively; currently consumed by Ratchanter's activated ability.
        new_minion = replace(
            minion, dark_matter_stacks=minion.dark_matter_stacks + effect.amount,
        )
        new_minions = _replace_minion(state.minions, minion.instance_id, new_minion)
        return replace(state, minions=new_minions)
    # Unimplemented or non-minion-targeting effect types: skip gracefully
    return state


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
    caster_owner: Optional[PlayerSide] = None,
) -> GameState:
    """Resolve effect on all minions orthogonally adjacent to caster_pos.

    "Adjacent" in this engine means the four cardinal neighbours (no
    diagonals). Burn-aura effects (EffectType.BURN) are additionally
    restricted to enemies of the caster -- they should not set
    is_burning on friendlies.
    """
    adjacent_positions = Board.get_orthogonal_adjacent(caster_pos)
    for minion in state.minions:
        if minion.position not in adjacent_positions:
            continue
        if (
            effect.effect_type == EffectType.BURN
            and caster_owner is not None
            and minion.owner == caster_owner
        ):
            continue
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
    if effect.effect_type == EffectType.DRAW:
        player_idx = _player_index_for_side(caster_owner)
        player = state.players[player_idx]
        for _ in range(effect.amount):
            if player.deck:
                player, _card_id = player.draw_card()
        new_players = _replace_player(state.players, player_idx, player)
        return replace(state, players=new_players)
    elif effect.effect_type in (EffectType.DAMAGE, EffectType.HEAL):
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
# Tutor (deck search)
# ---------------------------------------------------------------------------


def _enter_pending_tutor(
    state: GameState,
    card_def: CardDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
    amount: int = 1,
) -> GameState:
    """Phase 14.2: enter pending_tutor state.

    Computes deck indices in the caster's deck whose card matches
    `card_def.tutor_target` (string shorthand or selector dict). Does NOT
    move any card -- the pick is resolved later in action_resolver via
    TUTOR_SELECT or DECLINE_TUTOR.

    ``amount`` is how many picks the player may make before the modal
    auto-closes (e.g. To The Ratmobile has amount=2 — picker gets 2
    picks). Capped to the number of available matches.

    Mutex: asserts no concurrent pending_post_move_attacker_id (defense in
    depth -- tutor only fires from on_play, not from MOVE).
    """
    if not card_def.tutor_target:
        return state

    assert state.pending_post_move_attacker_id is None, (
        "Cannot enter pending_tutor while pending_post_move_attacker_id is set"
    )
    assert state.pending_tutor_player_idx is None, (
        "Cannot enter pending_tutor while another pending_tutor is set"
    )

    player_idx = _player_index_for_side(caster_owner)
    player = state.players[player_idx]

    matches: list[int] = []
    for deck_idx, card_numeric_id in enumerate(player.deck):
        try:
            candidate = library.get_by_id(card_numeric_id)
        except KeyError:
            continue
        if card_def.tutor_matches(candidate):
            matches.append(deck_idx)

    if not matches:
        # No candidates -- silently no-op (caller proceeds to react window).
        return state

    remaining = max(1, min(amount, len(matches)))
    return replace(
        state,
        pending_tutor_player_idx=player_idx,
        pending_tutor_matches=tuple(matches),
        pending_tutor_remaining=remaining,
    )


def _resolve_tutor(*args, **kwargs):
    """Phase 14.2: legacy tutor resolver removed -- shim for defense in depth."""
    raise NotImplementedError(
        "_resolve_tutor was removed in Phase 14.2; use _enter_pending_tutor"
    )


def _recompute_tutor_matches(
    new_deck: tuple,
    prev_matches: tuple,
    picked_deck_idx: int,
    library: CardLibrary,
) -> list[int]:
    """Recompute pending_tutor_matches after a pick removed one deck card.

    The deck has had one slot removed at ``picked_deck_idx``, so every
    previously-matched index > picked_deck_idx must be decremented by 1,
    and the picked index is dropped entirely.
    """
    new_matches: list[int] = []
    for m in prev_matches:
        if m == picked_deck_idx:
            continue
        new_matches.append(m - 1 if m > picked_deck_idx else m)
    # Defense: clamp against new deck length.
    return [i for i in new_matches if 0 <= i < len(new_deck)]


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
    # Scale amount if scale_with is set (e.g. "dark_matter" adds caster's DM stacks)
    # When the caster is a minion on the board, scale once using the caster's DM.
    # When the caster is a magic card (no minion at caster_pos), defer scaling to
    # each individual target inside the dispatch branches below so the scale uses
    # the target's own DM — matches rulings like Dark Matter Stash
    # ("each Mage gains atk/hp equal to their own DM").
    scaled_effect = effect
    _per_target_dm_scale = False
    if effect.scale_with == "dark_matter":
        caster = _find_minion_at_pos(state.minions, caster_pos)
        if caster is not None:
            dm = caster.dark_matter_stacks
            scaled_amount = effect.amount + dm
            if scaled_amount > 0:
                scaled_effect = replace(effect, amount=scaled_amount)
            else:
                return state  # 0 damage, skip
        else:
            _per_target_dm_scale = True

    # Placement condition multiplier (e.g. "triple if placed in front of dark ranged")
    if scaled_effect.placement_condition and scaled_effect.condition_multiplier > 1:
        if _check_placement_condition(state, caster_pos, caster_owner, scaled_effect.placement_condition, library):
            scaled_effect = replace(scaled_effect, amount=scaled_effect.amount * scaled_effect.condition_multiplier)

    if scaled_effect.target == TargetType.SINGLE_TARGET:
        return _resolve_single_target(state, scaled_effect, library, target_pos)
    elif scaled_effect.target == TargetType.ALL_ENEMIES:
        return _resolve_all_enemies(state, scaled_effect, caster_owner, library)
    elif scaled_effect.target == TargetType.ADJACENT:
        return _resolve_adjacent(state, scaled_effect, caster_pos, library, caster_owner)
    elif scaled_effect.target == TargetType.SELF_OWNER:
        return _resolve_self_owner(state, scaled_effect, caster_pos, caster_owner, library)
    elif scaled_effect.target == TargetType.OPPONENT_PLAYER:
        opp_idx = 1 - _player_index_for_side(caster_owner)
        return _apply_effect_to_player(state, scaled_effect, opp_idx)
    elif scaled_effect.target == TargetType.ALL_ALLIES:
        for minion in state.minions:
            if minion.owner != caster_owner or minion.current_health <= 0:
                continue
            if scaled_effect.target_tribe:
                card_def = library.get_by_id(minion.card_numeric_id)
                if not card_def.tribe or scaled_effect.target_tribe.lower() not in card_def.tribe.lower():
                    continue
            if _per_target_dm_scale:
                # Scale per-target using the target's own DM (magic cards path)
                this_amount = effect.amount + minion.dark_matter_stacks
                if this_amount <= 0:
                    continue
                this_effect = replace(scaled_effect, amount=this_amount)
            else:
                this_effect = scaled_effect
            state = _apply_effect_to_minion(state, this_effect, minion, library)
        return state
    else:
        raise ValueError(f"Unknown target type: {scaled_effect.target}")


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
        if effect.effect_type == EffectType.TUTOR:
            state = _enter_pending_tutor(
                state, card_def, minion.owner, library,
                amount=max(1, effect.amount or 1),
            )
        elif effect.effect_type == EffectType.CONJURE:
            state = _resolve_conjure(state, card_def, minion.owner, library)
        elif effect.effect_type == EffectType.RALLY_FORWARD:
            state = _apply_rally_forward(state, minion)
        elif effect.effect_type == EffectType.PROMOTE:
            state = _apply_promote_on_death(
                state, minion.card_numeric_id, minion.owner, library,
            )
        else:
            state = resolve_effect(
                state, effect, minion.position, minion.owner, library, target_pos,
            )
    return state


def _death_effect_needs_modal(effect: EffectDefinition) -> bool:
    """Return True if a death-trigger effect ALWAYS requires a click-target modal.

    Currently the only such shape is ``DESTROY / SINGLE_TARGET`` (Lasercannon
    on_death). The dying minion's owner must click an enemy minion to
    destroy it — there's no automatic target resolution path that makes
    sense, so we enter the modal.

    Note: PROMOTE is handled separately in ``resolve_death_effects_or_enter_modal``
    because it only enters the modal when 2+ candidates exist (with 0/1 it
    resolves synchronously).
    """
    return (
        effect.trigger == TriggerType.ON_DEATH
        and effect.target == TargetType.SINGLE_TARGET
        and effect.effect_type == EffectType.DESTROY
    )


def _count_promote_candidates(
    state: GameState,
    dying_card_numeric_id: int,
    dying_owner: PlayerSide,
    library: CardLibrary,
) -> int:
    """Count friendly alive minions eligible for PROMOTE on death.

    Mirrors the filter in ``_apply_promote_on_death`` but only returns the
    count. Used by ``resolve_death_effects_or_enter_modal`` to decide
    whether to auto-resolve (0 or 1 candidates) or open the picker modal
    (2+ candidates).
    """
    try:
        dying_card_def = library.get_by_id(dying_card_numeric_id)
    except KeyError:
        return 0
    if not dying_card_def.promote_target:
        return 0
    try:
        target_card_numeric_id = library.get_numeric_id(dying_card_def.promote_target)
    except KeyError:
        return 0
    # Unique constraint: if another copy of the dying card is still alive on
    # the owner's board, no promote happens at all.
    if dying_card_def.unique:
        for m in state.minions:
            if m.owner == dying_owner and m.is_alive and m.card_numeric_id == dying_card_numeric_id:
                return 0
    return sum(
        1 for m in state.minions
        if m.owner == dying_owner
        and m.is_alive
        and m.card_numeric_id == target_card_numeric_id
    )


def resolve_death_effects_or_enter_modal(
    state: GameState,
    card_numeric_id: int,
    owner: PlayerSide,
    position: tuple[int, int],
    instance_id: int,
    library: CardLibrary,
    start_idx: int,
) -> tuple[GameState, int]:
    """Resolve a dead minion's on_death effects sequentially, with modal support.

    Iterates the card's effects tuple starting at ``start_idx``. For each
    ON_DEATH effect:

      - If the effect needs a click-target modal and no legal auto-target
        exists (e.g. Lasercannon destroy/single_target with enemy minions
        on the board), set ``state.pending_death_target`` and STOP.
        Returns ``(state, idx)`` where ``idx`` is the index of the
        modal-pending effect (the caller uses this to resume after the
        user submits DEATH_TARGET_PICK).

      - If the modal effect has no valid target available (no enemy
        minions on the board), auto-skip it as a silent no-op.

      - Otherwise, resolve the effect synchronously via the standard
        path (``_apply_promote_on_death``, ``_resolve_conjure``, etc.).

    Returns:
        (new_state, next_idx) — next_idx == len(effects) means "fully drained,
        move on to the next dead minion". next_idx in [0, len(effects)) means
        "a modal was opened at that index; resume there after the pick
        resolves".
    """
    try:
        card_def = library.get_by_id(card_numeric_id)
    except KeyError:
        return state, -1

    effects = card_def.effects

    # Collect the indices of ON_DEATH effects (preserve ordering).
    death_indices = [
        i for i, e in enumerate(effects) if e.trigger == TriggerType.ON_DEATH
    ]
    if not death_indices:
        return state, -1

    # Find our resume point in the death-effects list.
    remaining = [i for i in death_indices if i >= start_idx]

    for i in remaining:
        effect = effects[i]

        if _death_effect_needs_modal(effect):
            # Check that at least one legal target exists; otherwise no-op.
            has_target = any(
                m.owner != owner and m.is_alive for m in state.minions
            )
            if not has_target:
                # No valid targets — silent no-op, advance past this effect.
                continue

            # Defense: don't clobber an already-set modal. The cleanup
            # driver always drains before re-entering.
            assert state.pending_death_target is None, (
                "resolve_death_effects_or_enter_modal called while "
                "pending_death_target already set"
            )
            target = PendingDeathTarget(
                card_numeric_id=card_numeric_id,
                owner_idx=int(owner),
                dying_instance_id=instance_id,
                effect_idx=i,
                filter="enemy_minion",
            )
            return replace(state, pending_death_target=target), i

        # PROMOTE: open modal if 2+ candidates, otherwise resolve inline.
        if effect.effect_type == EffectType.PROMOTE:
            candidate_count = _count_promote_candidates(
                state, card_numeric_id, owner, library,
            )
            if candidate_count >= 2:
                assert state.pending_death_target is None, (
                    "resolve_death_effects_or_enter_modal called while "
                    "pending_death_target already set"
                )
                target = PendingDeathTarget(
                    card_numeric_id=card_numeric_id,
                    owner_idx=int(owner),
                    dying_instance_id=instance_id,
                    effect_idx=i,
                    filter="friendly_promote",
                )
                return replace(state, pending_death_target=target), i
            state = _apply_promote_on_death(
                state, card_numeric_id, owner, library,
            )
            continue

        # Synchronous resolution path.
        if effect.effect_type == EffectType.TUTOR:
            # Death-triggered tutor not currently used by any card; if it
            # shows up it will enter pending_tutor just like on_play tutor.
            state = _enter_pending_tutor(
                state, card_def, owner, library,
                amount=max(1, effect.amount or 1),
            )
        elif effect.effect_type == EffectType.CONJURE:
            state = _resolve_conjure(state, card_def, owner, library)
        elif effect.effect_type == EffectType.RALLY_FORWARD:
            # RALLY_FORWARD on death would need a mover reference; no live
            # card uses it, but keep the dispatch symmetric with
            # resolve_effects_for_trigger so a future card can slot in.
            pass
        else:
            state = resolve_effect(
                state, effect, position, owner, library, target_pos=None,
            )

    return state, -1


def apply_death_target_pick(
    state: GameState,
    target_pos: tuple[int, int],
    library: CardLibrary,
) -> GameState:
    """Resolve the pending death-target modal with the user's pick.

    Called from ``action_resolver`` when a DEATH_TARGET_PICK action lands.
    Looks up the pending effect via ``state.pending_death_target``, applies
    it to the chosen target_pos, clears the pending-target field, and
    advances the head of ``state.pending_death_queue`` past the resolved
    effect. The caller (``_drain_pending_death_queue`` in
    action_resolver) is responsible for continuing the death-cleanup
    loop after this returns.

    Validation: raises ``ValueError`` if there is no pending death target,
    if the picked position doesn't contain a valid target, or if the
    effect_idx is stale.
    """
    target = state.pending_death_target
    if target is None:
        raise ValueError("DEATH_TARGET_PICK submitted with no pending_death_target")

    card_def = library.get_by_id(target.card_numeric_id)
    if target.effect_idx < 0 or target.effect_idx >= len(card_def.effects):
        raise ValueError(
            f"DEATH_TARGET_PICK: stale effect_idx {target.effect_idx} "
            f"on card {card_def.card_id}"
        )
    effect = card_def.effects[target.effect_idx]
    if effect.trigger != TriggerType.ON_DEATH:
        raise ValueError(
            f"DEATH_TARGET_PICK: effect at index {target.effect_idx} "
            f"is not an ON_DEATH trigger"
        )

    # Validate the click target against the filter.
    picked = _find_minion_at_pos(state.minions, target_pos)
    if picked is None or not picked.is_alive:
        raise ValueError(f"DEATH_TARGET_PICK: no alive minion at {target_pos}")
    owner_side = PlayerSide(target.owner_idx)
    if target.filter == "enemy_minion":
        if picked.owner == owner_side:
            raise ValueError(
                f"DEATH_TARGET_PICK: target {target_pos} is friendly to the "
                f"dying minion's owner (filter=enemy_minion)"
            )
    elif target.filter == "friendly_promote":
        if picked.owner != owner_side:
            raise ValueError(
                f"DEATH_TARGET_PICK: target {target_pos} is not friendly "
                f"(filter=friendly_promote)"
            )
        # Target must also match the promote_target card_id.
        promote_card_id = card_def.promote_target
        if not promote_card_id:
            raise ValueError(
                "DEATH_TARGET_PICK: dying card has no promote_target"
            )
        promote_numeric_id = library.get_numeric_id(promote_card_id)
        if picked.card_numeric_id != promote_numeric_id:
            raise ValueError(
                f"DEATH_TARGET_PICK: target at {target_pos} is not a "
                f"valid promote target (card_id mismatch)"
            )

    # Resolve the effect. For DESTROY, kill the picked minion by zeroing
    # its health — regular cleanup will remove it and fire its own on_death
    # as a chain-reaction on the next pass.
    if effect.effect_type == EffectType.DESTROY:
        new_picked = replace(picked, current_health=0)
        new_minions = _replace_minion(state.minions, picked.instance_id, new_picked)
        state = replace(state, minions=new_minions)
    elif effect.effect_type == EffectType.PROMOTE:
        # Transform the picked ally into the dying card (full stat reset).
        promoted = replace(
            picked,
            card_numeric_id=target.card_numeric_id,
            current_health=card_def.health,
            attack_bonus=0,
            max_health_bonus=0,
            is_burning=False,
        )
        new_minions = _replace_minion(state.minions, picked.instance_id, promoted)
        state = replace(state, minions=new_minions)
    else:
        # Future-proof: other effect types that could use this modal path.
        state = resolve_effect(
            state,
            effect,
            caster_pos=(0, 0),
            caster_owner=PlayerSide(target.owner_idx),
            library=library,
            target_pos=target_pos,
        )

    # Advance the head of the pending queue past this effect.
    queue = list(state.pending_death_queue)
    if queue:
        head = queue[0]
        queue[0] = replace(head, next_effect_idx=target.effect_idx + 1)
    state = replace(
        state,
        pending_death_target=None,
        pending_death_queue=tuple(queue),
    )
    return state


def _apply_promote_on_death(
    state: GameState,
    dying_card_numeric_id: int,
    dying_owner: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """PROMOTE on death: transform a friendly ``promote_target`` minion into
    the dying card. Mirrors ``tensor_engine/effects.py::_apply_promote``.

    Rules (locked, matches tensor engine):
      - Find all friendly, alive minions whose card_id == ``promote_target``.
      - If the dying card is ``unique``, skip entirely when another copy of
        the dying card is still alive on the owner's board.
      - Among candidates, pick the most advanced one (closest to the
        enemy's back row). Tiebreak by lowest column, then lowest
        instance_id, for determinism.
      - Transform in-place: set ``card_numeric_id`` to the dying card,
        reset ``current_health`` to the dying card's base health, clear
        ``attack_bonus`` (base attack now comes from the new card def),
        clear ``max_health_bonus``.

    Returns a new GameState. No-op if promote_target is unset, no valid
    candidate exists, or the unique constraint is violated.
    """
    try:
        dying_card_def = library.get_by_id(dying_card_numeric_id)
    except KeyError:
        return state

    if not dying_card_def.promote_target:
        return state

    try:
        target_card_numeric_id = library.get_numeric_id(dying_card_def.promote_target)
    except KeyError:
        return state

    # Unique constraint: bail if another copy of the dying card is alive.
    if dying_card_def.unique:
        for m in state.minions:
            if m.owner != dying_owner:
                continue
            if not m.is_alive:
                continue
            if m.card_numeric_id == dying_card_numeric_id:
                return state

    # Find candidates: friendly, alive, correct card_id.
    candidates = [
        m for m in state.minions
        if m.owner == dying_owner
        and m.is_alive
        and m.card_numeric_id == target_card_numeric_id
    ]
    if not candidates:
        return state

    # Pick the most advanced: P1 wants highest row (forward = +1 toward row 4),
    # P2 wants lowest row (forward = -1 toward row 0). Tiebreak by column
    # then instance_id for determinism.
    if dying_owner == PlayerSide.PLAYER_1:
        candidates.sort(key=lambda m: (-m.position[0], m.position[1], m.instance_id))
    else:
        candidates.sort(key=lambda m: (m.position[0], m.position[1], m.instance_id))

    chosen = candidates[0]
    # Full reset: new card, fresh HP, clear all buffs/debuffs/status
    promoted = replace(
        chosen,
        card_numeric_id=dying_card_numeric_id,
        current_health=dying_card_def.health,
        attack_bonus=0,
        max_health_bonus=0,
        is_burning=False,
    )
    new_minions = _replace_minion(state.minions, chosen.instance_id, promoted)
    return replace(state, minions=new_minions)


def _apply_rally_forward(
    state: GameState,
    mover: MinionInstance,
) -> GameState:
    """RALLY_FORWARD: advance every other friendly minion with the same
    card_numeric_id forward 1 tile in its column, if the destination is
    in-bounds and empty. Mirrors the tensor engine implementation
    (``tensor_engine/actions.py::_apply_rally_forward``).

    The mover itself is excluded. Minions whose forward tile is blocked
    or off the board are left in place.
    """
    delta = 1 if mover.owner == PlayerSide.PLAYER_1 else -1
    new_minions_list = list(state.minions)
    new_board = state.board
    for i, m in enumerate(new_minions_list):
        if m.instance_id == mover.instance_id:
            continue
        if m.owner != mover.owner:
            continue
        if m.current_health <= 0:
            continue
        if m.card_numeric_id != mover.card_numeric_id:
            continue
        src_row, src_col = m.position
        dst_row = src_row + delta
        if dst_row < 0 or dst_row >= 5:
            continue
        if new_board.get(dst_row, src_col) is not None:
            continue
        new_board = new_board.remove(src_row, src_col)
        new_board = new_board.place(dst_row, src_col, m.instance_id)
        new_minions_list[i] = replace(m, position=(dst_row, src_col))
    return replace(state, board=new_board, minions=tuple(new_minions_list))


def _resolve_conjure(
    state: GameState,
    card_def: CardDefinition,
    caster_owner: PlayerSide,
    library: CardLibrary,
) -> GameState:
    """Conjure: add a copy of summon_token_target card to the caster's hand.

    Unlike tutor (which searches the deck), conjure creates a card from outside
    the deck. Used by Ratchanter and similar 'summoner' minions.
    """
    if not card_def.summon_token_target:
        return state
    try:
        target_numeric_id = library.get_numeric_id(card_def.summon_token_target)
    except KeyError:
        return state
    player_idx = _player_index_for_side(caster_owner)
    player = state.players[player_idx]
    # Hand cap: skip if hand is full
    if len(player.hand) >= 10:
        return state
    new_player = replace(
        player,
        hand=player.hand + (target_numeric_id,),
    )
    new_players = _replace_player(state.players, player_idx, new_player)
    return replace(state, players=new_players)
